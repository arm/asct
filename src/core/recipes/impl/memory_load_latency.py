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

import itertools

from abc import ABC
from typing import ClassVar

import pandas as pd

import asct.core.logger as log
from asct.core import asct_pmu_api as perf_api
from asct.core import benchrunner as br
from asct.core.recipes.recipe_benchmark_base import RecipeBenchmarkBase
from asct.core.resources.hugepages import Hugepage
from asct.core.resources.check_sudo import CheckSudo
from asct.core.resources.numactl import Numactl
from asct.core.sweep_algorithm import SweepAlgorithm
from asct.core.ubench_config import ubench_config as ub_cfg
from asct.core.utility.format import memsize_str
from asct.core.utility.numeric import range_up
from asct.core.constants import HUGE_PAGE_SIZE_1GB
from asct.core.benchspec.benchspec import ASCTBenchmarkConfig, CustomAppSpec
from asct.core.datatypes import Result
from asct.core.benchspec.memory_benchspec import LatencyBenchmarkSpec, BandwidthBenchmarkSpec


# Distinguish user-facing `duration` (measured run length) from background-run duration used
# only to keep helper loads alive until they are explicitly stopped by the recipe logic.
BACKGROUND_RUN_DURATION = 100000

# The default DRAM data size for memory benchmarks, used when we can't get a more accurate value
# from the latency sweep results. 400MB is chosen as it's larger than typical LLC sizes,
# to ensure we are measuring DRAM latency, but not too large to cause excessive runtime.
DEFAULT_DRAM_DATA_SIZE = 400_000_000  # 400MB


class MemoryLoadLatencyBase(RecipeBenchmarkBase, ABC):
    """
    Direction is as follows: CPU <-> L1 <-> L2 <-> L3 <-> DRAM

    | Source         | Destination  | Direction      | Counter Name
    +----------------+--------------+----------------+------------------------------------------------------
    | CPU            | L1           | CPU <- L1      | L1D_CACHE_RD
    | L1             | CPU          | CPU -> L1      | L1D_CACHE_WR
    | L1             | L2           | L1 <- L2       | L2D_CACHE_RD
    | L2             | L1           | L1 -> L2       | L1D_CACHE_WB
    | L2             | L3           | L2 <- L3       | LL_CACHE_RD
    | L3 (SLC)       | L2           | L2 -> L3       | CMN: WriteEvictFull + WriteBackFull + WriteCleanFull
    | L2             | L3 (SLC)     | L2 <- L3       | CMN: ReadNotSharedDirty + ReadUnique
    | L3 (SLC)       | DRAM         | L3 <- DRAM     | LL_CACHE_MISS_RD
    | DRAM           | L3 (SLC)     | L3 <- DRAM     | CMN: ReadNoSnpSep + ReadNoSnp

    Multiplexing is not yet supporting by dietperf, maximum 7 PMUv3 events at one time
    L3 + DRAM events can be covered by CMN counters once we have CMN discovery
    """

    pmu_event_map: ClassVar[dict] = {
        "inst_retired": "INST_RETIRED",
        "cpu_cycles": "CPU_CYCLES",
        # "L1_Rd_Misses": "L1D_CACHE_REFILL_RD",
        # "L2_Rd_Misses": "L2D_CACHE_REFILL_RD",
        # "LL_Rd_Misses": "LL_CACHE_MISS_RD",
        "TLB_Misses": "L1D_TLB_REFILL",
        "L1_Rd": "L1D_CACHE_RD",
        "L1_Wr": "L1D_CACHE_WR",
        "L2_Rd": "L2D_CACHE_RD",
        "L2_Wr": "L1D_CACHE_WB",  # only measure L2 Wr caused by a WB from L1D
        # "LL_Rd": "LL_CACHE_RD",
        # "DRAM_Rd": "LL_CACHE_MISS_RD",
    }

    def __init__(self, metadata):
        super().__init__(metadata)

    def _create_resources(self):
        return [Numactl(self.sysreport.sys_hw.n_numa_nodes)]

    @property
    def rate_unit(self):
        return "B/cycle" if self._cfg.cycle_base else "GB/s"

    @property
    def latency_unit(self):
        return "cycle" if self._cfg.cycle_base else "ns"

    def get_optimal_data_size(self):
        """
        Get the optimal DRAM data size for memory benchmarks.

        Returns:
            int: The optimal DRAM data size in bytes.
        """
        try:
            sweep_summary = self.reporter.read_latency_sweep_summary()
            # For data size, run at sweep spot datasize
            if sweep_summary:
                return sweep_summary["DRAM"]["sweet_spot"]["sizes"]
        except (KeyError, TypeError, ValueError, AttributeError, OSError) as exc:
            log.debug("Failed to read latency sweep summary, falling back to default DRAM size: %s", exc)

        log.warning("Using default values - run --latency-sweep for more accurate per-system results")
        return DEFAULT_DRAM_DATA_SIZE

    def lookup_benchmark_binary(self):
        """
        Lookup the benchmark binary based on the configuration.

        Args:
            benchmark (str): The name of the benchmark.

        Returns:
            str: The path to the benchmark binary.
        """
        return ub_cfg.lookup_benchmark_binary(self.pmu_mode, "load_latency")

    def run_benchmark(self, bmk_spec, runner):
        if self.pmu_mode:
            events = self.pmu_event_map.values()
            runner_env = perf_api.setup_env(events, str(self))
            runner.update_env(runner_env)

        results = runner.run_and_collect_results(bmk_spec)
        bmk_res_df = results.to_dataframe()

        if self.pmu_mode:
            pmu_res_df = self.compute_pmu_metrics(bmk_res_df)
            bmk_res_df = pd.concat([bmk_res_df, pmu_res_df], axis=1)
        return bmk_res_df

    def compute_pmu_metrics(self, bmk_res_df):
        df = pd.DataFrame([perf_api.retrieve_pmu_data(str(self))])

        for metric_name, metric_counter in self.pmu_event_map.items():
            if metric_counter not in df.columns:
                log.warning(f"PMU metric {metric_name} not found in results, skipping")
                continue
            df[metric_name] = df[metric_counter]
            df[f"{metric_name}:time_enabled_ns"] = df[f"{metric_counter}:time_enabled_ns"]

        if "inst_retired" not in df.columns:
            raise RuntimeError("No count returned for inst_retired")
        if "cpu_cycles" not in df.columns:
            raise RuntimeError("No count returned for cpu_cycles")

        if "L1_Rd" in df.columns and "L1_Wr" in df.columns:
            df["L1_RW"] = df["L1_Rd"] + df["L1_Wr"]
            df["cycles_per_rep"] = df["cpu_cycles"] / bmk_res_df["repetitions"]
            df["cycles_per_read"] = df["cpu_cycles"] / df["L1_Rd"]
            df["cycles_per_write"] = df["cpu_cycles"] / df["L1_Wr"]
            df["cycles_per_memory_access"] = df["cpu_cycles"] / df["L1_RW"]
        # time enabled is in nanoseconds, convert to seconds
        df["cycle_freq"] = df["cpu_cycles"] / (df["cpu_cycles:time_enabled_ns"] / 1e9)
        CACHE_LINE_SIZE = 64
        if "L1_Rd" in df.columns:
            # Compute read bandwidth in MB/s using PMU counters, assuming every load is fetching a cache line
            df["PMU_bw [MB/s]"] = df["L1_Rd"] * CACHE_LINE_SIZE * df["cycle_freq"] / df["cpu_cycles"] / 1e6
            df["PMU_bw [B/cycle]"] = df["L1_Rd"] * CACHE_LINE_SIZE / df["cpu_cycles"]
            # Compute read latency in ns using PMU counters
            df["PMU_rd_latency [ns]"] = df["cpu_cycles"] / df["cycle_freq"] / df["L1_Rd"] * 1e9
            # Note: core cycles, not reference cycles
            df["PMU_rd_latency [cycle]"] = df["cpu_cycles"] / df["L1_Rd"]
            log.debug(f"PMU BYTES(L1): {df['L1_Rd'] * CACHE_LINE_SIZE}")

        if "DRAM_Rd" in df.columns:
            # Compute read DRAM bandwidth in MB/s using PMU counters, assuming every load is fetching a cache line
            df["PMU_bw_dram [MB/s]"] = df["DRAM_Rd"] * CACHE_LINE_SIZE * df["cycle_freq"] / df["cpu_cycles"] / 1e6
            df["PMU_bw_dram [B/cycle]"] = df["DRAM_Rd"] * CACHE_LINE_SIZE / df["cpu_cycles"]
            log.debug("PMU BYTES(DRAM) %d", df["DRAM_Rd"] * CACHE_LINE_SIZE)

        log.debug(f"PMU TIME {df['cpu_cycles'] / df['cycle_freq']}")
        return df

    @property
    def benchmark_rate_metric(self):
        return "total_bandwidth_bpc" if self._cfg.cycle_base else "total_bandwidth_mbps"

    def get_rate_metric(self, df):
        """
        Get the memory rate with chosen rate unit.

        :param self: This object with self.rate_unit providing rate unit to use
        :param df: data frame containing the metrics
        """
        return df["total_bandwidth_mbps"] / 1e3 if self.rate_unit == "GB/s" else df["total_bandwidth_bpc"]

    @property
    def benchmark_latency_metric(self):
        return "average_latency_cyc" if self._cfg.cycle_base else "average_latency_ns"


class CrossNumaBase(MemoryLoadLatencyBase):
    def __init__(self, metadata):
        super().__init__(metadata)

    def _pre_setup(self):
        super()._pre_setup()
        labels = [f"Node {i}" for i in self.cpu_list_per_node]  # row and column labels are the same
        self.results_df = pd.DataFrame(index=labels, columns=labels, dtype=float)

    def gen_steps(self):
        nodes = self.cpu_list_per_node.keys()
        return list(itertools.product(nodes, nodes))

    def get_results_df(self):
        return self.results_df

    def get_step_desc(self, step):
        return f"on NUMA nodes {step[0]}-{step[1]}"

    def get_diff_data(self):
        if self._loaded_raw_result is None:
            raise RuntimeError(f"result data was not loaded for {self.name}")
        raw_result = self._loaded_raw_result
        # raw_result from to_dict(orient="dict"): {col_node: {row_node: value}}
        # col = memory node (DataFrame column), row = run node (DataFrame index)
        result = {}
        for mem_node, by_run_node in raw_result.items():
            for run_node, value in by_run_node.items():
                if run_node not in result:
                    result[run_node] = {}
                result[run_node][mem_node] = value
        return result

    def deserialize(self, data):
        if not data:
            return
        metadata, raw_result = self._deserialize_payload(data)
        self._loaded_raw_result = raw_result
        if raw_result is not None:
            self.result = Result(
                desc=self._deserialized_result_desc(metadata),
                dataframe=pd.DataFrame.from_dict(raw_result).astype(float),
            )


class IdleLatency(CrossNumaBase):
    def __init__(self, metadata):
        super().__init__(metadata)
        self.priority = 2
        self.hugepage_request = None

    @property
    def results_desc(self) -> str:
        return f"Latencies of random memory access at idle ({self.latency_unit})"

    @property
    def dev_mode_data_df(self):
        return pd.DataFrame({"Node 0": [114.12, 254.05], "Node 1": [233.99, 105.63]}, index=["Node 0", "Node 1"])

    def _create_resources(self):
        hugepage_settings = {node: {HUGE_PAGE_SIZE_1GB: 1} for node in self.cpu_list_per_node}
        self.hugepage_request = Hugepage(hugepage_settings)
        return [self.hugepage_request, CheckSudo(), *super()._create_resources()]

    def one_step(self, iteration):
        run_node, mem_node = iteration
        output_metric = self.benchmark_latency_metric
        cpu_list = [str(self.last_cpu_ids[run_node])]

        config = ASCTBenchmarkConfig.new_from(
            self._cfg, numa_node=mem_node, target_cpus=cpu_list, huge_page_size=self.hugepage_request.get_page_size()
        )
        bmk_spec = LatencyBenchmarkSpec(self.benchmark_binary, config)

        df = self.run_benchmark(bmk_spec, br.SyncRunner())
        self.results_df.loc[f"Node {run_node}", f"Node {mem_node}"] = df[output_metric].item()


class PeakBandwidth(MemoryLoadLatencyBase):
    print_index: bool = False

    def __init__(self, metadata):
        super().__init__(metadata)
        self.priority = 3
        self.mode_info_lst = []
        self.bw_rate_unit_lst = []

    @property
    def results_desc(self) -> str:
        return "Peak memory bandwidth"

    @property
    def columns(self) -> list[str]:
        return ["Traffic type", f"Peak BW [{self.rate_unit}]", "% of Peak Theoretical"]

    @property
    def dev_mode_data_df(self):
        return pd.DataFrame({
            self.columns[0]: [access_desc.long for access_desc in BandwidthBenchmarkSpec.access_descs.values()],
            self.columns[1]: [185.933134199, 161.825716028, 158.086118694, 153.551170218, 119.536827829],
            self.columns[2]: [
                89.29756291943359,
                77.56377742529297,
                76.19291840039062,
                74.27996168408202,
                58.612440906249994,
            ],
        })

    def gen_steps(self):
        # Return only supported access types
        supported_keys = [k for k, v in BandwidthBenchmarkSpec.access_descs.items() if v.supported(self.sysreport)]
        return sorted(supported_keys)

    def get_step_desc(self, step):
        return f"using {BandwidthBenchmarkSpec.access_descs[step].short}"

    def get_results_df(self):
        df = pd.DataFrame({self.columns[0]: self.mode_info_lst, self.columns[1]: self.bw_rate_unit_lst})
        if self.sysreport.memory.peak_theoretical_bw is not None and self.sysreport.memory.peak_theoretical_bw > 0:
            # memory.peak_theoretical_bw is in bytes, peak bandwidth is in GB/s (decimal)
            # convert peak_theoretical_bw into decimal GB by dividing by 1000**3
            peak_theoretical_gb = self.sysreport.memory.peak_theoretical_bw / (1000**3)
            df[self.columns[2]] = (df[self.columns[1]] / peak_theoretical_gb) * 100
        return df

    def get_diff_data(self):
        if self._loaded_raw_result is None:
            raise RuntimeError(f"result data was not loaded for {self.name}")
        df = pd.DataFrame.from_dict(self._loaded_raw_result)

        traffic_type_col = "Traffic type"
        if traffic_type_col not in df.columns:
            raise RuntimeError(f"result data for {self.name} is missing '{traffic_type_col}'")

        return df.set_index(traffic_type_col).to_dict(orient="index")

    def _create_default_config(self):
        numa_node = self.default_numa_node
        cpu_list_first_numa_node = [str(c) for c in self.cpu_list_per_node[numa_node]]
        base_cfg = super()._create_default_config()
        return base_cfg.update_with(target_cpus=cpu_list_first_numa_node, numa_node=numa_node)

    def one_step(self, access_type):
        # See args.c in the loaded-latency folder
        # The options below define read-to-write access ratios for memory traffic patterns:
        # // support different read-write ratios
        # // 0 - Read only
        # // 1 - Write only
        # // 2 - 3:1 Reads-Writes
        # // 3 - 2:1 Reads-Writes
        # // 4 - 1:1 Reads-Writes
        # // 5 - 2:1 Reads-Writes (Non-Temporal Store)
        # So by default, all read and write will be done in the same buffer
        # For 2:1 Reads-Writes (Non-Temporal Store), a[i] = b[i] + c[i] * SCALAR,
        # there will be 2 read buffers and 1 write buffer.
        # With RFO, there will be 1 read induced by the write miss, so 3:1 read-write ratio (mode 5 below).
        loads = []

        spec = BandwidthBenchmarkSpec(self.benchmark_binary, None, access_type=access_type)
        load_configs = [
            ASCTBenchmarkConfig.new_from(
                self._cfg,
                duration=BACKGROUND_RUN_DURATION,
                target_cpus=self.cpu_list_per_node[node],
                numa_node=node,
            )
            for node in self.cpu_list_per_node
            if node != self.default_numa_node
        ]

        for load_cfg in load_configs:
            spec.set_config(load_cfg)

            load = br.AsyncRunner().run(spec)
            loads.append(load)

        spec.set_config(self._cfg)
        df = self.run_benchmark(spec, br.SyncRunner())

        for idx, load in enumerate(loads):
            load.stop()
            if load.retcode != 0:
                raise RuntimeError(f"Background load thread {idx} failed with errcode {load.ret_code}")

        bw_per_cpu = self.get_rate_metric(df).item() / len(self.cpu_list_per_node[self.default_numa_node])
        total_cpus = sum(len(cpus) for cpus in self.cpu_list_per_node.values())
        bw_rate_unit = bw_per_cpu * total_cpus

        mode_info = spec.access_desc.long
        self.mode_info_lst.append(mode_info)
        self.bw_rate_unit_lst.append(bw_rate_unit)

        log.debug(f"%s: %.3f{self.rate_unit}", mode_info, bw_rate_unit)

    def get_summary(self):
        """Convert peak-bandwidth data to use traffic type descriptions as keys."""
        if self._loaded_raw_result is None:
            raise RuntimeError(f"result data was not loaded for {self.name}")
        peak_theoretical_name = "% of Peak Theoretical"
        traffic_types = self._loaded_raw_result["Traffic type"]
        peak_bw_key = next(k for k in self._loaded_raw_result if k.startswith("Peak BW"))
        peak_bw = self._loaded_raw_result[peak_bw_key]
        peak_theoretical = self._loaded_raw_result.get(peak_theoretical_name, None)
        result = {}
        for key in traffic_types:
            traffic_name = traffic_types[key]
            result[traffic_name] = {peak_bw_key: peak_bw[key]}
            if peak_theoretical:
                result[traffic_name][peak_theoretical_name] = peak_theoretical[key]
        return result


class CrossNumaBandwidth(CrossNumaBase):
    def __init__(self, metadata):
        super().__init__(metadata)
        self.priority = 4

    @property
    def results_desc(self) -> str:
        return f"Cross-NUMA bandwidths for the system (in {self.rate_unit})"

    @property
    def dev_mode_data_df(self):
        return pd.DataFrame({"Node 0": [458.40, 78.16], "Node 1": [76.13, 458.54]}, index=["Node 0", "Node 1"])

    def one_step(self, iteration):
        run_node, mem_node = iteration
        # For each NUMA node, pick the last cpu id, as mentioned above for less busy cpu empircally.
        cpu_list = [str(c) for c in self.cpu_list_per_node[run_node]]

        config = ASCTBenchmarkConfig.new_from(self._cfg, numa_node=mem_node, target_cpus=cpu_list)
        bmk_spec = BandwidthBenchmarkSpec(self.benchmark_binary, config, access_type=0)

        df = self.run_benchmark(bmk_spec, br.SyncRunner())
        self.results_df.loc[f"Node {run_node}", f"Node {mem_node}"] = self.get_rate_metric(df).item()


class Sweep(MemoryLoadLatencyBase):
    level_names: ClassVar[list[str]] = ["L1", "L2", "LLC", "DRAM"]
    # TODO: determine these bounds from the system
    MIN_DATA_SIZE = 128
    MAX_DATA_SIZE = 1073741825

    def __init__(self, metadata):
        super().__init__(metadata)

    @property
    def columns(self) -> list[str]:
        return []

    def get_optimal_data_size(self):
        return 0

    @property
    def cache_size_dict(self):
        # Get the cache sizes from sysreport, ensure sorted
        return dict(sorted(self.sysreport.sys_hw.cache_size_dict.items()))


class CycleLatencySweep(Sweep):
    supports_pmu: bool = True

    def __init__(self, metadata):
        super().__init__(metadata)
        self.priority = 0
        # CycleLatencySweep produces the DRAM size internally;
        # no need to retrieve it from a privious run.
        # Disabled to prevent warning output.
        self.hugepage_size = HUGE_PAGE_SIZE_1GB
        self.hugepage_request = None
        self.sweep_algo = SweepAlgorithm(self.MIN_DATA_SIZE, self.MAX_DATA_SIZE, self.level_names)
        self.dfs = []
        self.final_df = pd.DataFrame()

    @property
    def results_desc(self) -> str:
        return "Latencies at different levels of cache"

    @property
    def columns(self) -> list[str]:
        return ["Lower Bound", "Upper Bound", "Optimum Datasize", f"Latency [{self.latency_unit}]"]

    def get_step_desc(self, step):
        return f"{step[1]} for size {memsize_str(step[0], precision=2, suffix='B')}"

    def _create_resources(self):
        hugepage_settings = {node: {self.hugepage_size: 1} for node in self.cpu_list_per_node}
        self.hugepage_request = Hugepage(hugepage_settings)
        return [self.hugepage_request, CheckSudo(), *super()._create_resources()]

    def _create_default_config(self):
        base_cfg = super()._create_default_config()
        return base_cfg.update_with(numa_node=self.default_numa_node, target_cpus=self.single_core_cpu_choice)

    @property
    def dev_mode_data_df(self):
        return pd.DataFrame(
            {
                self.columns[0]: [128, 131072, 8388608, 134217728],
                self.columns[1]: [65536, 1048576, 8388608, 1073741824],
                self.columns[2]: [32832, 589824, 8388608, 603979776],
                self.columns[3]: [1.484032, 4.068406, 23.646303, 114.838327],
            },
            index=self.level_names,
        )

    def to_stdout(self):
        """
        Prints the recipe result to standard output, including description,
        a separator line, and the dataframe content.
        """
        print(self.result.desc)
        print("-" * len(self.result.desc))
        print(
            self.result.dataframe.to_string(
                index=True,
                formatters={
                    self.columns[0]: memsize_str,
                    self.columns[1]: memsize_str,
                    self.columns[2]: memsize_str,
                    self.columns[3]: lambda x: f"{x:.1f}",
                },
            )
        )
        print()

    def gen_steps(self):
        data_size_list = list(range_up(self.MIN_DATA_SIZE, self.MAX_DATA_SIZE, steps=1, step=2))
        df = self.reporter.read_latency_presweep_results()
        if df is None:
            self.dfs = []
            for s in data_size_list:
                yield s, "presweep"
            df = pd.concat(self.dfs)
            df = df.sort_values(by="sizes").reset_index(drop=True)
            self.reporter.write_latency_presweep_results(df)

        bounds = {}
        bounds_df = pd.DataFrame({"level_name": self.level_names, "LB": float("inf"), "UB": float("-inf")}).set_index(
            "level_name"
        )
        cpm_metric = self.benchmark_latency_metric
        while True:
            new_data_sizes = self.sweep_algo.compute_new_data_sizes_cpm(df, cpm_metric, bounds_df, True)
            if not new_data_sizes:
                break
            log.debug("New datasizes: %s, bounds: %s", new_data_sizes, bounds)
            self.dfs = [df]
            for s in new_data_sizes:
                yield s, "precheck"
            df = pd.concat(self.dfs)
            df = df.sort_values(by="sizes").reset_index(drop=True)

        bounds_df["LB"] = 2 ** bounds_df["LB"].astype(int)
        bounds_df["UB"] = 2 ** bounds_df["UB"].astype(int)
        bounds = bounds_df.to_dict(orient="index")

        self.bench_summary = {}
        if bounds:
            self.dfs = [df]
            for level_name in self.level_names:
                lb = bounds[level_name]["LB"]
                ub = bounds[level_name]["UB"]
                log.debug("Data size bounds for %s: %s - %s", level_name, lb, ub)
                sweet_plot_size = int((ub + lb) / 2)
                yield sweet_plot_size, f"using {level_name}"
                self.bench_summary[level_name] = {
                    "LB": lb,
                    "UB": ub,
                    "sweet_spot": self.new_df.to_dict(orient="records")[0],
                }
            df = pd.concat(self.dfs)
            self.final_df = df.sort_values(by="sizes").reset_index(drop=True)
        else:
            self.final_df = df

    def get_results_df(self):
        self.reporter.write_latency_sweep_results(self.final_df)
        self.reporter.plot_latency_sweep_results(
            self.final_df, self.benchmark_latency_metric, self.latency_unit, self.cache_size_dict
        )
        self.reporter.write_latency_sweep_summary(self.bench_summary)
        return pd.DataFrame(
            {
                self.columns[0]: [self.bench_summary[level]["LB"] for level in self.level_names],
                self.columns[1]: [self.bench_summary[level]["UB"] for level in self.level_names],
                self.columns[2]: [self.bench_summary[level]["sweet_spot"]["sizes"] for level in self.level_names],
                self.columns[3]: [
                    self.bench_summary[level]["sweet_spot"][self.benchmark_latency_metric] for level in self.level_names
                ],
            },
            index=self.level_names,
        )

    def get_diff_data(self):
        if self._loaded_raw_result is None:
            raise RuntimeError(f"result data was not loaded for {self.name}")
        raw_result = self._loaded_raw_result
        # raw_result from to_dict(orient="dict"): {col_name: {level: value}}
        # Invert to {level: {col_name: value}} for per-cache-level comparison.
        result = {}
        for col, by_level in raw_result.items():
            for level, value in by_level.items():
                result.setdefault(level, {})[col] = value
        return result

    def get_raw_results(self):
        return {
            "sweep_data": self.final_df.to_dict(),
            "summary": self.result.dataframe.to_dict(orient="dict"),
        }

    def deserialize(self, data):
        if not data:
            return
        metadata, raw_result = self._deserialize_payload(data)
        raw_result = raw_result or {}
        if isinstance(raw_result, dict) and "summary" in raw_result:
            # Current format: {"sweep_data": full_data, "summary": per_level_summary}
            self.final_df = pd.DataFrame.from_dict(raw_result["sweep_data"])
            summary = raw_result["summary"]
        else:
            # Legacy format: raw_result is the summary dict directly
            self.final_df = pd.DataFrame.from_dict(raw_result) if raw_result else pd.DataFrame()
            summary = raw_result
        self._loaded_raw_result = summary
        if summary:
            self.result = Result(
                desc=self._deserialized_result_desc(metadata),
                dataframe=pd.DataFrame.from_dict(summary),
            )

    def one_step(self, s):
        config = ASCTBenchmarkConfig.new_from(
            self._cfg, data_size=s[0], huge_page_size=self.hugepage_request.get_page_size()
        )
        bmk_spec = LatencyBenchmarkSpec(self.benchmark_binary, config)
        self.new_df = self.run_benchmark(bmk_spec, br.SyncRunner())
        self.dfs.append(self.new_df)

    @classmethod
    def _get_name(self):
        return "latency-sweep"

    def cache_results(self):
        """
        Cache the results of the recipe for future runs.
        """
        return {
            "latency-sweep-summary.ubench.json": self.bench_summary,
            "latency-sweep.ubench.json": self.final_df.to_dict(),
        }


class BandwidthSweep(Sweep):
    supports_pmu: bool = True

    def __init__(self, metadata):
        super().__init__(metadata)
        self.priority = 1
        self.dfs = []
        self.final_df = pd.DataFrame()

    @property
    def results_desc(self) -> str:
        return "Bandwidth at different levels of cache"

    @property
    def columns(self) -> list[str]:
        return ["Datasize Used", "Level", f"Bandwidth [{self.rate_unit}]"]

    def _create_default_config(self):
        base_cfg = super()._create_default_config()
        return base_cfg.update_with(
            numa_node=self.default_numa_node,
            target_cpus=self.single_core_cpu_choice,
            min_data_size=None,
            max_data_size=None,
        )

    @property
    def dev_mode_data_df(self):
        return pd.DataFrame({
            self.columns[0]: [32832, 589824, 8388608, 603979776],
            self.columns[1]: self.level_names,
            self.columns[2]: [163.936378416, 89.897001343, 53.109808304, 34.40022485],
        })

    def to_stdout(self):
        """
        Prints the recipe result to standard output, including description,
        a separator line, and the dataframe content.
        """
        print(self.result.desc)
        print("-" * len(self.result.desc))
        print(
            self.result.dataframe.to_string(
                index=False,
                formatters={
                    self.columns[0]: memsize_str,
                    self.columns[2]: lambda x: f"{x:.1f}",
                },
            )
        )
        print()

    def get_step_desc(self, step):
        return f"for size {memsize_str(step, precision=2, suffix='B')}"

    def gen_steps(self):
        if self._cfg.min_data_size is not None and self._cfg.max_data_size is not None:
            return list(
                range_up(
                    self._cfg.min_data_size,
                    self._cfg.max_data_size,
                    steps=1,
                    step=2,
                )
            )
        if (lat_run_df := self.reporter.read_latency_sweep_results()) is not None:
            # If latency sweep data is available, run the same data sizes for bandwidth runs
            return lat_run_df["sizes"]
        # Otherwise just run the presweep data set default run
        return list(range_up(self.MIN_DATA_SIZE, self.MAX_DATA_SIZE, steps=1, step=2))

    def get_results_df(self):
        df = pd.concat(self.dfs)
        self.final_df = df.sort_values(by="sizes").reset_index(drop=True)
        self.reporter.write_bandwidth_sweep_results(self.final_df)
        self.reporter.plot_bandwidth_sweep_results(self.final_df, self.rate_unit, self.cache_size_dict)

        if sweep_summary := self.reporter.read_latency_sweep_summary():
            sweet_spot_sizes = [sweep_summary[level]["sweet_spot"]["sizes"] for level in self.level_names]
            results = self.final_df[self.final_df["sizes"].isin(sweet_spot_sizes)].drop_duplicates(
                subset="sizes", keep="first"
            )
            # Compute index of first occurence of the data size w.r.t. cache level
            # One data size shows up in multiple levels happens in quick_mode where degenerated data is produced
            size_index = [sweet_spot_sizes.index(s) for s in sorted(set(sweet_spot_sizes))]
            levels = [self.level_names[i] for i in size_index]
        else:
            # Don't have sweet spot information so just return the whole results
            results = self.final_df
            levels = None
        return pd.DataFrame({
            self.columns[0]: results["sizes"],
            self.columns[1]: levels,
            self.columns[2]: self.get_rate_metric(results),
        }).reset_index(drop=True)

    def one_step(self, s):
        config = ASCTBenchmarkConfig.new_from(self._cfg, data_size=s)
        bmk_spec = BandwidthBenchmarkSpec(self.benchmark_binary, config, access_type=0)
        new_df = self.run_benchmark(bmk_spec, br.SyncRunner())
        self.dfs.append(new_df)

    def get_summary(self):
        """Convert to single dictionary with Level as keys containing both datasize and bandwidth."""
        if self._loaded_raw_result is None:
            raise RuntimeError(f"result data was not loaded for {self.name}")
        raw_result = self._loaded_raw_result

        levels = raw_result["Level"]
        datasize_used = raw_result["Datasize Used"]
        bw_key = next(k for k in raw_result if k.startswith("Bandwidth"))
        bandwidth = raw_result[bw_key]
        result = {}
        for key in levels:
            level_name = levels[key]
            result[level_name] = {"Datasize Used": datasize_used[key], bw_key: bandwidth[key]}
        return result

    def get_diff_data(self):
        return self.get_summary()

    def get_raw_results(self):
        return {
            "sweep_data": self.final_df.to_dict(),
            "summary": self.result.dataframe.to_dict(orient="dict"),
        }

    def deserialize(self, data):
        if not data:
            return
        metadata, raw_result = self._deserialize_payload(data)
        raw_result = raw_result or {}

        if isinstance(raw_result, dict) and "summary" in raw_result:
            # Current format: {"sweep_data": full_data, "summary": per_level_summary}
            self.final_df = pd.DataFrame.from_dict(raw_result["sweep_data"])
            summary = raw_result["summary"]
        else:
            # Legacy format: raw_result is the summary dict directly
            self.final_df = pd.DataFrame.from_dict(raw_result) if raw_result else pd.DataFrame()
            summary = raw_result

        self._loaded_raw_result = summary
        if summary:
            self.result = Result(
                desc=self._deserialized_result_desc(metadata),
                dataframe=pd.DataFrame.from_dict(summary),
            )


class LoadedLatency(MemoryLoadLatencyBase):
    print_index: bool = False

    def __init__(self, metadata):
        super().__init__(metadata)
        self.priority = 5
        self.latencies = []
        self.bandwidths_bpc = []
        self.bandwidths_gbps = []
        self.acceptable_increase = 0.15
        self.hugepage_request = None

    @property
    def results_desc(self) -> str:
        return "Loaded latency with background memory activity"

    @property
    def columns(self) -> list[str]:
        return [
            "Injected NOPs",
            f"Loaded latency [{self.latency_unit}]",
            f"Bandwidth [{self.rate_unit}]",
            "% of Peak Theoretical BW",
        ]

    def _create_resources(self):
        hugepage_settings = {node: {HUGE_PAGE_SIZE_1GB: 1} for node in self.cpu_list_per_node}
        self.hugepage_request = Hugepage(hugepage_settings)
        return [self.hugepage_request, CheckSudo(), *super()._create_resources()]

    def _create_default_config(self):
        last_cpu_id = self.last_cpu_ids[self.default_numa_node]
        base_cfg = super()._create_default_config()
        return base_cfg.update_with(latency_cpu_id=last_cpu_id, bw_cpu_blocklist=[last_cpu_id])

    @property
    def dev_mode_data_df(self):
        injected_nops = [3000, 900, 500, 180, 100, 80, 70, 50, 40, 30, 20, 10, 0]
        return pd.DataFrame({
            self.columns[0]: injected_nops,
            self.columns[1]: [
                115.903799,
                114.81909,
                115.68127,
                121.712008,
                128.792813,
                134.12702,
                137.305216,
                158.687514,
                190.462513,
                249.858392,
                327.900536,
                343.030213,
                306.227356,
            ],
            self.columns[2]: [
                10.65099277608421,
                34.831728518778945,
                61.951493474978946,
                175.92551190857895,
                307.9220375064316,
                385.9830004696001,
                435.1691330583895,
                607.2540830972001,
                740.0332192103053,
                911.4180296547895,
                918.1269011524527,
                917.661742153021,
                920.4542213911684,
            ],
            self.columns[3]: [
                2.683969650390625,
                9.013406564941405,
                15.684295096679685,
                46.70340874658203,
                86.38608106054687,
                88.70410695996092,
                88.70218813378906,
                89.08080890966797,
                89.35366641699218,
                88.83501068896484,
                89.22602097021483,
                89.07046712792969,
                88.35412600097655,
            ],
        })

    def get_step_desc(self, step):
        return f"with {step} nops"

    def gen_steps(self):
        return self._cfg.injected_nops

    @property
    def latency_node(self):
        return self.get_numa_node_for_cpu(self._cfg.latency_cpu_id)

    def one_step(self, mem_bw_delay):
        dummy_loads = []

        latency_node = self.latency_node
        latency_cpu_id = self._cfg.latency_cpu_id
        bw_cpu_blocklist = self._cfg.bw_cpu_blocklist

        # Base bw configuration set delay
        base_bw_config = ASCTBenchmarkConfig.new_from(self._cfg, bw_delay=mem_bw_delay)
        # Load bw configuration extend base_bw_config to set for long duration
        load_bw_config = ASCTBenchmarkConfig.new_from(base_bw_config, duration=BACKGROUND_RUN_DURATION)
        bw_spec = BandwidthBenchmarkSpec(self.benchmark_binary, None, access_type=0)

        # Base latency configuration is just defaults
        base_lat_config = ASCTBenchmarkConfig.new_from(self._cfg, huge_page_size=self.hugepage_request.get_page_size())
        # Load latency configuration extend base_lat_config to set for long duration
        load_lat_config = ASCTBenchmarkConfig.new_from(base_lat_config, duration=BACKGROUND_RUN_DURATION)
        if self._cfg.workload_cmd:
            lat_spec = CustomAppSpec(self._cfg.workload_cmd)
        else:
            lat_spec = LatencyBenchmarkSpec(self.benchmark_binary, None)

        for numa in self.cpu_list_per_node:
            # Run the bw load on all numa node except the latency one
            if numa == latency_node:
                continue
            bw_dummy_cpu_list = [str(c) for c in self.cpu_list_per_node[numa] if c not in bw_cpu_blocklist]
            # dummy_load_bw_config choose CPU for dummy runs
            bw_spec.set_config(
                ASCTBenchmarkConfig.new_from(load_bw_config, target_cpus=bw_dummy_cpu_list, numa_node=numa)
            )

            # Load generators - will run in the background for all NUMA nodes except the benchmarked one
            # for both runs of this benchmark
            load = br.AsyncRunner().run(bw_spec)
            dummy_loads.append(load)

        # ASCT tries to measure loaded latency + BW in two runs
        # 1) Background BW runs + simple latency run (measured)
        # 2) Background latency run + BW run (measured)

        # For the BW runs, use all CPUs on the latency node except the latency CPU
        bw_cpu_list_loaded_latency_node = [
            str(c) for c in self.cpu_list_per_node[latency_node] if c not in bw_cpu_blocklist
        ]

        measured_latency = float("nan")
        total_bw_gbps = float("nan")
        total_bw_bpc = float("nan")
        if self._cfg.phase == "loading" or self._cfg.phase == "both":
            # Run 1: Background BW runs + simple latency run (measured)
            # 1.1: Load generator - will run bw in the background for the benchmarked NUMA node
            # load_bw_config choose CPU for bw load on the latency node
            bw_spec.set_config(
                ASCTBenchmarkConfig.new_from(
                    load_bw_config, target_cpus=bw_cpu_list_loaded_latency_node, numa_node=latency_node
                )
            )
            bw_load = br.AsyncRunner().run(bw_spec)

            # 1.2: Benchmark latency while bw runners are running
            # measure_lat_config choose CPU for latency run
            lat_spec.set_config(
                ASCTBenchmarkConfig.new_from(base_lat_config, target_cpus=[str(latency_cpu_id)], numa_node=latency_node)
            )
            lat_df = self.run_benchmark(lat_spec, br.SyncRunner())

            bw_load.stop()
            if bw_load.retcode != 0:
                raise RuntimeError(f"Background load thread failed with errcode {bw_load.retcode}")
            if self.benchmark_latency_metric in lat_df.columns:
                measured_latency = lat_df[self.benchmark_latency_metric].item()
            if "output" in lat_df.columns:
                log.info(lat_df["output"].item())

        if self._cfg.phase == "bandwidth" or self._cfg.phase == "both":
            # Run 2: Background latency run + BW run (measured)
            # 2.1: Load generator - will run latency in the background for the benchmarked NUMA node
            lat_spec.set_config(
                ASCTBenchmarkConfig.new_from(load_lat_config, target_cpus=[str(latency_cpu_id)], numa_node=latency_node)
            )
            lat_load = br.AsyncRunner().run(lat_spec)

            # 2.2: Benchmark bandwidth while latency is running in the background on the NUMA node
            bw_spec.set_config(
                ASCTBenchmarkConfig.new_from(
                    base_bw_config, target_cpus=bw_cpu_list_loaded_latency_node, numa_node=latency_node
                )
            )
            bw_df = self.run_benchmark(bw_spec, br.SyncRunner())

            lat_load.stop()
            if lat_load.retcode != 0:
                raise RuntimeError(f"Background latency thread failed with errcode {lat_load.retcode}")

            total_bw_gbps = self.extrapolate_total_bw(bw_df["total_bandwidth_mbps"].item() / 1e3)
            total_bw_bpc = self.extrapolate_total_bw(bw_df["total_bandwidth_bpc"].item())

        for idx, load in enumerate(dummy_loads):
            load.stop()
            if load.retcode != 0:
                raise RuntimeError(f"Background load thread {idx} failed with errcode {load.retcode}")

        self.latencies.append(measured_latency)
        self.bandwidths_gbps.append(total_bw_gbps)
        self.bandwidths_bpc.append(total_bw_bpc)

    def extrapolate_total_bw(self, measured_bw):
        bw_per_cpu = measured_bw / (len(self.cpu_list_per_node[self.default_numa_node]) - 1)
        dummy_bw = bw_per_cpu * sum(
            len(self.cpu_list_per_node[n]) for n in self.cpu_list_per_node if n != self.default_numa_node
        )
        return dummy_bw + measured_bw

    def get_results_df(self):
        df = pd.DataFrame({
            self.columns[0]: self._cfg.injected_nops,
            self.columns[1]: self.latencies,
            self.columns[2]: self.bandwidths_gbps if self.rate_unit == "GB/s" else self.bandwidths_bpc,
        })
        if self.sysreport.memory.peak_theoretical_bw is not None and self.sysreport.memory.peak_theoretical_bw > 0:
            # For % peak bw calculation, always use GB/s
            # memory.peak_theoretical_bw is in bytes, peak bandwidth is in GB/s (decimal)
            # convert peak_theoretical_bw into decimal GB by dividing by 1000**3
            peak_theoretical_gbps = self.sysreport.memory.peak_theoretical_bw / (1000**3)
            df[self.columns[3]] = [bw_gbps / peak_theoretical_gbps * 100 for bw_gbps in self.bandwidths_gbps]
        self.reporter.plot_loaded_latency_results(df, self.latency_unit, self.acceptable_increase)
        return df

    def get_diff_data(self):
        """Return diff data keyed by injected NOP count."""
        if self._loaded_raw_result is None:
            raise RuntimeError(f"result data was not loaded for {self.name}")
        df = pd.DataFrame.from_dict(self._loaded_raw_result)

        nops_col = next(
            (
                column_name
                for column_name in df.columns
                if isinstance(column_name, str) and column_name.startswith("Injected NOPs")
            ),
            "Injected NOPs",
        )
        if nops_col not in df.columns:
            raise RuntimeError(f"result data for {self.name} is missing '{nops_col}'")

        diff_data = df.set_index(nops_col).sort_index().to_dict(orient="index")
        return {str(nops): row for nops, row in diff_data.items()}
