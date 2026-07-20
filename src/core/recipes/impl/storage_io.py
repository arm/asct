# ---------------------------------------------------------------------------------
# SPDX-FileCopyrightText: Copyright (C) 2025-2026 Arm Limited and/or its affiliates
# SPDX-FileCopyrightText: <open-source-office@arm.com>
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
# ---------------------------------------------------------------------------------

from asct.core.recipes.recipe_benchmark_base import RecipeBenchmarkBase
from asct.core.resources.fio import Fio
from asct.core.resources.temporary_file import TemporaryFile
from asct.core.resources.mpstat import Mpstat
from asct.core.resources.numactl import Numactl
from abc import ABC, abstractmethod
import pandas as pd
from asct.core import benchrunner as br
from asct.core.benchspec.storage_benchspec import StorageBenchSpec
from asct.core.benchspec.benchspec import ASCTBenchmarkConfig, MpstatSpec
import asct.core.managers.ubench_reporter as ub_rep
from asct.core.utility.format import memsize_str
import os


class StorageIORecipe(RecipeBenchmarkBase, ABC):
    def __init__(self, metadata):
        super().__init__(metadata)
        self.dfs = []
        self.temp_file = None
        self.fio = None

    def lookup_benchmark_binary(self):
        return None

    @property
    def recipe_name(self):
        return f"storage_{self.sweep_variable_name.lower()}_sweep"

    def _create_resources(self):
        self.fio = Fio(self._cfg.ioengine, self._cfg.alternative_ioengines)
        extra_resources = []
        if self._cfg.create_temp_file:
            self.temp_file = TemporaryFile(self.results_dir, self._cfg.filesize)
            extra_resources.append(self.temp_file)
        elif not self._cfg.filenames:
            # ASCT not creating temp file, so filenames must be provided
            raise ValueError(
                "Filenames must be specified by adding --update-config srss.filenames=<file1>,<file2>,...,<filen>."
            )
        return [
            self.fio,
            Mpstat(),
            Numactl(self.sysreport.sys_hw.n_numa_nodes),
            *super()._create_resources(),
            *extra_resources,
        ]

    def get_step_desc(self, step):
        return f"{self.sweep_variable_name} : {self.pretty_print_sweep_variable(step)}"

    @abstractmethod
    def gen_steps(self):
        raise NotImplementedError("Steps should be implemented in the derived class.")

    def run_benchmark(self, bmk_spec, runner):
        results = runner.run_and_collect_results(bmk_spec)
        return results.to_dataframe()

    @property
    @abstractmethod
    def sweep_variable_name(self):
        raise NotImplementedError("Sweep variable should be implemented in the derived class.")

    # Subclass overrides to pretty print iteration
    def pretty_print_sweep_variable(self, iteration):
        return str(iteration)

    def one_step(self, iteration):
        pretty_print_iteration = self.pretty_print_sweep_variable(iteration)
        variable_name = self.sweep_variable_name
        step_config = self.update_variable_value_in_config(iteration)
        # Create output directory for this step of format <output_dir>/storage/<block_size>
        output_dir = os.path.join(self.results_dir, f"{variable_name}-{pretty_print_iteration}")
        os.makedirs(output_dir, exist_ok=True)
        # Get the last num_cpus_to_use cpus from cpu list and pass to ASCTBenchmarkConfig
        num_cpus_to_use = min(self._cfg.numjobs, len(self.cpu_list))
        load = (
            br
            .AsyncRunner(cwd=output_dir, suppress_output=False)
            .update_env({"LC_ALL": "C"})
            .run(
                mpstat_spec := MpstatSpec(
                    ASCTBenchmarkConfig.new_from(
                        step_config, numa_node=self.default_numa_node, target_cpus=[self.cpu_list[0]]
                    )
                )
            )
        )
        chosen_cpus = self.cpu_list[-num_cpus_to_use:]
        df = self.run_benchmark(
            StorageBenchSpec(ASCTBenchmarkConfig.new_from(step_config, target_cpus=chosen_cpus)),
            br.SyncRunner(cwd=output_dir),
        )
        # Use INT signal to stop mpstat gracefully for proper output
        load.stop(use_int=True)
        mp_stat_results = load.collect_results(mpstat_spec)
        start_epoch_s = int(df["run_start_ms"].item()) / 1000
        end_epoch_s = int(df["run_end_ms"].item()) / 1000
        mp_stat_df = mp_stat_results.mpstat_df
        df[variable_name] = pretty_print_iteration
        # extract the relevant rows from mp_stat_results.mpstat_df
        if not mp_stat_df.empty:
            mp_stat_df = mp_stat_df[
                mp_stat_df["epoch"].between(start_epoch_s, end_epoch_s) & mp_stat_df["cpu"].isin(map(str, chosen_cpus))
            ]
        for metric in ["usr", "sys", "iowait", "irq", "soft"]:
            df[f"CPU {metric} (%)"] = mp_stat_df[metric].mean() if metric in mp_stat_df.columns else None
        self.dfs.append(df)

    def update_variable_value_in_config(self, _iteration):
        # Just create a new one for further update for this step.
        cfg = ASCTBenchmarkConfig.new_from(self._cfg)
        if self.temp_file:
            # Update to temp_file if temp file being used
            cfg.update_with(filenames=[self.temp_file.get_file_path()])
        # Use the ioengine finalized by fio resource check, which may be different from the requested one
        # if the requested one is not supported by the currently installed fio.
        cfg.update_with(ioengine=self.fio.finalized_engine)
        return cfg

    @property
    def results_desc(self):
        default_run_info = {
            "BlockSize": memsize_str(self._cfg.blocksize),
            "IODepth": self._cfg.iodepth,
            "ProcessCount": self._cfg.numjobs,
            "AccessPattern": self._cfg.rw_pattern,
            "DirectIO": self._cfg.direct,
            "ReadWriteMix": self._cfg.rwmixread,
        }
        # Remove the sweep variable from the default run info
        default_run_info.pop(self.sweep_variable_name, None)
        # Remove rwmixread information if the run fix the access pattern to pure read or write
        fixed_access_pattern = default_run_info.get("AccessPattern", None)
        if fixed_access_pattern is not None and fixed_access_pattern not in ["rw", "randrw"]:
            # fixed access pattern fixed and not mix, so pure read/write
            default_run_info.pop("ReadWriteMix", None)

        default_run_info_str = ", ".join(f"{key}: {value}" for key, value in default_run_info.items())
        return f"Storage I/O Benchmark Results: {default_run_info_str}"

    def get_results_df(self):
        combined_df = pd.concat(self.dfs, ignore_index=True)

        combined_df["Read BW (MB/s)"] = combined_df["read_bw_bytes_per_sec"] / (1024 * 1024)
        combined_df["Write BW (MB/s)"] = combined_df["write_bw_bytes_per_sec"] / (1024 * 1024)
        combined_df["Total BW (MB/s)"] = combined_df["Read BW (MB/s)"] + combined_df["Write BW (MB/s)"]
        combined_df["Read Thruput (kops)"] = combined_df["read_iops_per_sec"] / 1000
        combined_df["Write Thruput (kops)"] = combined_df["write_iops_per_sec"] / 1000
        combined_df["Thruput (kops)"] = combined_df["Read Thruput (kops)"] + combined_df["Write Thruput (kops)"]
        combined_df["Read Lat. (us)"] = combined_df["read_mean_latency_ns"] / 1000.0
        combined_df["Write Lat. (us)"] = combined_df["write_mean_latency_ns"] / 1000.0
        combined_df["Lat. (us)"] = (
            combined_df["Read Lat. (us)"] * combined_df["read_latency_sample_counts"]
            + combined_df["Write Lat. (us)"] * combined_df["write_latency_sample_counts"]
        ) / (combined_df["read_latency_sample_counts"] + combined_df["write_latency_sample_counts"])
        combined_df = combined_df.set_index(self.sweep_variable_name)
        # Plot bar chart of Bandwidth vs Block Size, saved as storage_io_bandwidth.png
        reporter = ub_rep.get_reporter()
        reporter.plot_storage_io_bw_rate(combined_df, f"{self.recipe_name}_bw.png")
        reporter.plot_storage_io_io_rate(combined_df, f"{self.recipe_name}_io_rate.png")
        reporter.plot_storage_io_cpu_util(combined_df, f"{self.recipe_name}_cpu_util.png")
        reporter.plot_storage_latency_distribution(
            combined_df, "read_mean_latency_ns_percentiles_dict", f"{self.recipe_name}_rd_lat_dist.png"
        )
        reporter.plot_storage_latency_distribution(
            combined_df, "write_mean_latency_ns_percentiles_dict", f"{self.recipe_name}_wr_lat_dist.png"
        )

        return combined_df[
            [
                "Read BW (MB/s)",
                "Write BW (MB/s)",
                "Total BW (MB/s)",
                "Read Thruput (kops)",
                "Write Thruput (kops)",
                "Thruput (kops)",
                "Read Lat. (us)",
                "Write Lat. (us)",
                "Lat. (us)",
                "CPU usr (%)",
                "CPU sys (%)",
                "CPU iowait (%)",
            ]
        ]

    def get_diff_data(self):
        """Return diff data keyed by the sweep-step index."""
        if self._loaded_raw_result is None:
            raise RuntimeError(f"result data was not loaded for {self.name}")
        diff_data = pd.DataFrame.from_dict(self._loaded_raw_result).sort_index().to_dict(orient="index")
        return {str(step): row for step, row in diff_data.items()}


# Subclasses for specific Storage I/O recipes
# RequestSizeSweep
# IODepthsweep
# ProcessCountSweep
# AccessPatternSweep


class RequestSizeSweep(StorageIORecipe):
    def __init__(self, metadata):
        super().__init__(metadata)

    @property
    def sweep_variable_name(self):
        return "BlockSize"

    # Override to print number if memsize
    def pretty_print_sweep_variable(self, iteration):
        return memsize_str(iteration)

    def update_variable_value_in_config(self, _iteration):
        base_cfg = super().update_variable_value_in_config(_iteration)
        return base_cfg.update_with(blocksize=_iteration)

    def gen_steps(self):
        return self._cfg.request_size_sweep_steps

    @property
    def dev_mode_data_df(self):
        data = {
            "Read BW (MB/s)": [12.8, 25.7, 51.6, 103.2, 137.6, 137.6],
            "Write BW (MB/s)": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "Total BW (MB/s)": [12.8, 25.7, 51.6, 103.2, 137.6, 137.6],
            "Read Thruput (kops)": [3.3, 3.3, 3.3, 3.3, 2.2, 1.1],
            "Write Thruput (kops)": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "Thruput (kops)": [3.3, 3.3, 3.3, 3.3, 2.2, 1.1],
            "Read Lat. (us)": [1210.5, 1213.9, 1211.9, 1210.6, 1817.0, 3634.4],
            "Write Lat. (us)": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "Lat. (us)": [1210.5, 1213.9, 1211.9, 1210.6, 1817.0, 3634.4],
            "CPU Util. (%)": [97.5, 100.0, 97.5, 100.0, 97.5, 100.0],
        }

        df = pd.DataFrame(data, index=["4K", "8K", "16K", "32K", "64K", "128K"])
        df.index.name = self.sweep_variable_name
        return df


class IODepthSweep(StorageIORecipe):
    def __init__(self, metadata):
        super().__init__(metadata)

    def gen_steps(self):
        # Generate I/O depths as power of 2 from 1 to 128
        return self._cfg.iodepth_sweep_steps

    @property
    def sweep_variable_name(self):
        return "IODepth"

    def update_variable_value_in_config(self, _iteration):
        base_cfg = super().update_variable_value_in_config(_iteration)
        return base_cfg.update_with(iodepth=_iteration)

    @property
    def dev_mode_data_df(self):
        data = {
            "Read BW (MB/s)": [12.7, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9],
            "Write BW (MB/s)": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "Total BW (MB/s)": [12.7, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9, 12.9],
            "Read Thruput (kops)": [3.3, 3.3, 3.3, 3.3, 3.3, 3.3, 3.3, 3.3],
            "Write Thruput (kops)": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "Thruput (kops)": [3.3, 3.3, 3.3, 3.3, 3.3, 3.3, 3.3, 3.3],
            "Read Lat. (us)": [1210.3, 1211.8, 1212.7, 1211.8, 1211.9, 1211.8, 1211.9, 1212.2],
            "Write Lat. (us)": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "Lat. (us)": [1210.3, 1211.8, 1212.7, 1211.8, 1211.9, 1211.8, 1211.9, 1212.2],
            "CPU Util. (%)": [95.8, 100.0, 96.3, 100.0, 94.9, 100.0, 100.0, 95.6],
        }

        df = pd.DataFrame(data, index=[1, 2, 4, 8, 16, 32, 64, 128])
        df.index.name = self.sweep_variable_name
        return df


class ProcessCountSweep(StorageIORecipe):
    def __init__(self, metadata):
        super().__init__(metadata)

    def gen_steps(self):
        return self._cfg.process_count_sweep_steps

    def update_variable_value_in_config(self, _iteration):
        base_cfg = super().update_variable_value_in_config(_iteration)
        return base_cfg.update_with(numjobs=_iteration)

    @property
    def sweep_variable_name(self):
        return "ProcessCount"

    @property
    def dev_mode_data_df(self):
        data = {
            "Read BW (MB/s)": [6.9, 12.9, 12.9, 12.9, 12.9],
            "Write BW (MB/s)": [0.0, 0.0, 0.0, 0.0, 0.0],
            "Total BW (MB/s)": [6.9, 12.9, 12.9, 12.9, 12.9],
            "Read Thruput (kops)": [1.8, 3.3, 3.3, 3.3, 3.3],
            "Write Thruput (kops)": [0.0, 0.0, 0.0, 0.0, 0.0],
            "Thruput (kops)": [1.8, 3.3, 3.3, 3.3, 3.3],
            "Read Lat. (us)": [561.6, 605.8, 1213.7, 2423.3, 4846.8],
            "Write Lat. (us)": [0.0, 0.0, 0.0, 0.0, 0.0],
            "Lat. (us)": [561.6, 605.8, 1213.7, 2423.3, 4846.8],
            "CPU Util. (%)": [25.0, 48.8, 100.0, 96.0, 100.0],
        }

        df = pd.DataFrame(data, index=[1, 2, 4, 8, 16])
        df.index.name = self.sweep_variable_name
        return df


class AccessPatternSweep(StorageIORecipe):
    def __init__(self, metadata):
        super().__init__(metadata)

    def gen_steps(self):
        return self._cfg.access_pattern_sweep_steps

    @property
    def sweep_variable_name(self):
        return "AccessPattern"

    def update_variable_value_in_config(self, _iteration):
        base_cfg = super().update_variable_value_in_config(_iteration)
        return base_cfg.update_with(rw_pattern=_iteration)

    @property
    def dev_mode_data_df(self):
        data = {
            "Read BW (MB/s)": [12.7, 0.0, 12.9, 0.0, 8.9, 8.9],
            "Write BW (MB/s)": [0.0, 12.9, 0.0, 12.9, 3.9, 3.9],
            "Total BW (MB/s)": [12.7, 12.9, 12.9, 12.9, 12.9, 12.9],
            "Read Thruput (kops)": [3.3, 0.0, 3.3, 0.0, 2.3, 2.3],
            "Write Thruput (kops)": [0.0, 3.3, 0.0, 3.3, 1.0, 1.0],
            "Thruput (kops)": [3.3, 3.3, 3.3, 3.3, 3.3, 3.3],
            "Read Lat. (us)": [1213.0, 0.0, 1211.9, 0.0, 1106.6, 1122.9],
            "Write Lat. (us)": [0.0, 1211.9, 0.0, 1211.8, 1450.5, 1415.5],
            "Lat. (us)": [1213.0, 1211.9, 1211.9, 1211.8, 1211.9, 1212.4],
            "CPU Util. (%)": [95.7, 100.0, 97.8, 100.0, 97.4, 100.0],
        }

        df = pd.DataFrame(data, index=["read", "write", "randread", "randwrite", "rw", "randrw"])
        df.index.name = self.sweep_variable_name
        return df
