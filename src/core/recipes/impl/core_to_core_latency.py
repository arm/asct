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

from collections import defaultdict
from itertools import chain, product

import asct.core.logger as log
import pandas as pd
from asct.core.asct_env import ASCTGlobalSettings as AGS
from asct.core.benchrunner import SyncRunner
from asct.core.benchspec.benchspec import ASCTBenchmarkConfig
from asct.core.benchspec.memory_benchspec import CoreToCoreBenchmarkSpec
from asct.core.datatypes import Result
from asct.core.managers.ubench_reporter import get_reporter
from asct.core.recipes.recipe_benchmark_base import RecipeBenchmarkBase
from asct.core.ubench_config import ubench_config as ub_cfg
from asct.lib.c2c_latency.report import CoreToCoreLatencyReport


class CoreToCoreLatency(RecipeBenchmarkBase):
    supports_pmu: bool = True

    def __init__(self, metadata):
        super().__init__(metadata)
        # Set up reporter
        self.reporter = None
        # L2 data size determined from latency sweep
        self._l2_data_size = None
        # Initialize latency result summary object,
        # Local :  Data to be written is homed on the same node/socket as the CPUA
        # Remote : Data to be written is homed on a different node/socket than the CPUA
        self._latency_summary = {"Local": None, "Remote": None}
        self._node_to_cpus = {}
        # Initialize DataFrame to store raw results
        # Columns: CPUA, CPUB, LATENCY, CPUA_NODE, MEMBIND_NODE
        # CPUA and CPUB are the core IDs, LATENCY is the measured latency,
        # CPUA_NODE is the node where CPUA is located, and MEMBIND_NODE is the node where the data is homed
        # during a run.
        self.columns = ["CPUA", "CPUB", "LATENCY", "CPUA_NODE", "MEMBIND_NODE"]
        self.raw_results_df = pd.DataFrame(columns=self.columns)
        # Dictionary to store compiled results
        # Key: (CPUA, CPUB, MEMBIND_NODE), Value: List of latencies
        # This will be used to compile results for the run, then *median/min
        # latency is taken and stored in the results DataFrame.
        self.compiled_results = defaultdict(list)
        # Dictionary to map CPU cores to nodes they belong to
        self._cpus_to_nodes = {}
        # Initialize current run counter for the progress bar
        self.current_run = 0

    # Use the default size from the benchmark if not specified by the user
    def get_optimal_data_size(self):
        if self._l2_data_size:
            return self._l2_data_size
        try:
            sweep_summary = get_reporter().read_latency_sweep_summary()
            # For data size, run at sweep spot datasize
            self._l2_data_size = sweep_summary["L2"]["sweet_spot"]["sizes"]
        except (KeyError, TypeError, ValueError, AttributeError, OSError) as exc:
            log.debug("Failed to read latency sweep summary, falling back to default L2 size: %s", exc)
            log.warning("Using default values - run --latency-sweep for more accurate per-system results")
            self._l2_data_size = 256 * 1024  # 256 KB

        return self._l2_data_size

    @property
    def number_of_cpus(self):
        """
        Returns the number of CPUs configured for the benchmark.
        """
        if AGS().dev_mode():
            return 5

        return self.sysreport.sys_hw.n_cpus

    @property
    def cpus_to_nodes(self):
        """
        Returns the mapping of CPUs to nodes.
        If not set, initializes it with a default mapping.
        """
        if not self._cpus_to_nodes:
            self._cpus_to_nodes = {core: node for node, cores in self.node_to_cpus.items() for core in cores}
        return self._cpus_to_nodes

    @property
    def result_df(self):
        """
        Returns the results DataFrame.
        This DataFrame is expected to be filled with the results of the benchmark.
        """
        if self.raw_results_df.empty and self.result is not None and self.result.dataframe is not None:
            self.raw_results_df = self.result.dataframe.copy()
        if self.raw_results_df.empty:
            self.raw_results_df = self.get_results_df()
        return self.raw_results_df

    @result_df.setter
    def result_df(self, value):
        self.raw_results_df = value

    @property
    def latency_summary(self):
        """
        Returns a dict with 'Local' and 'Remote' core-to-core latency summaries.
        """

        if self._latency_summary.get("Local") is None:
            report_kwargs = {
                "vmax": self._cfg.heatmap_vmax,
                "bins": self._cfg.hist_bins,
            }
            # Convert DataFrame to CoreToCoreLatencyReport
            # Create a mask for local and remote latencies, where local means CPUA and MEMBIND_NODE are the same,
            # and remote means they are different.
            mask = self.result_df["CPUA_NODE"] == self.result_df["MEMBIND_NODE"]
            local = self.result_df[mask]
            if not local.empty:
                self._latency_summary["Local"] = CoreToCoreLatencyReport(
                    local,
                    node_to_cpus=self.node_to_cpus,
                    **report_kwargs,
                )

            # Ensure that remote summary applies to entries where CPUA NUMA Node
            # and MEMBIND_NODE are different and
            # that CPUB NUMA Node and MEMBIND_NODE are the same
            # This filters out runs with membind not to CPUA nor CPUB's NUMA NODE.
            mask = (self.result_df["CPUA_NODE"] != self.result_df["MEMBIND_NODE"]) & (
                self.result_df["CPUB"].map(self.cpus_to_nodes) == self.result_df["MEMBIND_NODE"]
            )
            remote = self.result_df[mask]
            if not remote.empty:
                self._latency_summary["Remote"] = CoreToCoreLatencyReport(
                    remote,
                    node_to_cpus=self.node_to_cpus,
                    **report_kwargs,
                )
        return self._latency_summary

    @property
    def dev_mode_data_df(self):
        """
        Returns a DataFrame with dummy data for development mode.
        """
        self._node_to_cpus = {0: list(range(self.number_of_cpus))}
        data = pd.DataFrame([
            [None, 19.11, 52.19, 53.32, 45.36],
            [19.63, None, 44.07, 58.23, 50.41],
            [42.18, 55.94, None, 27.15, 50.27],
            [34.48, 46.22, 22.85, None, 55.17],
            [39.27, 53.30, 54.91, 51.60, None],
        ])

        self.raw_results_df = data.stack().reset_index()
        self.raw_results_df["CPUA_NODE"] = 0
        self.raw_results_df["MEMBIND_NODE"] = 0
        self.raw_results_df.columns = self.columns
        return self.raw_results_df

    def gen_steps(self):
        """
        Returns a list of steps for the benchmark.
        Generates all combinations of CPU pairs for latency measurement.
        """
        # Get list of all CPUs and NUMA nodes from the node_to_cpus mapping
        all_cpus = list(chain.from_iterable(self.node_to_cpus.values()))
        all_numa_nodes = list(self.node_to_cpus.keys())
        # Generate all combinations of CPUA and numa_node pairs
        # Each step is a tuple (cpua, membind_node)
        result = list(product(all_cpus, all_numa_nodes)) * self.number_of_runs  # Repeat for the number of runs
        result.append((None, None))  # Add a step for the finalization phase
        return result

    def get_results_df(self):
        """
        Returns the results DataFrame.
        This DataFrame is expected to be filled with the results of the benchmark.
        """

        if self.compiled_results and self.raw_results_df.empty:
            raw_data = []
            for (cpua, cpub, membind_node), lats in self.compiled_results.items():
                # Get the node for cpua and cpub
                cpua_node = self.cpus_to_nodes.get(cpua, None)
                cpub_node = self.cpus_to_nodes.get(cpub, None)
                # filter out entries which are missing in node mapping
                if cpua_node is None or cpub_node is None:
                    continue

                # Add one row per latency sample to preserve the full distribution.
                raw_data.extend(
                    [
                        int(cpua),
                        int(cpub),
                        float(latency),
                        int(cpua_node),
                        int(membind_node),
                    ]
                    for latency in lats
                )

            self.raw_results_df = pd.DataFrame(raw_data, columns=self.columns)

            self.raw_results_df["CPUA"] = self.raw_results_df["CPUA"].astype(int)
            self.raw_results_df["CPUB"] = self.raw_results_df["CPUB"].astype(int)
            self.raw_results_df["LATENCY"] = self.raw_results_df["LATENCY"].astype(float)
            self.raw_results_df["CPUA_NODE"] = self.raw_results_df["CPUA_NODE"].astype(int)
            self.raw_results_df["MEMBIND_NODE"] = self.raw_results_df["MEMBIND_NODE"].astype(int)

        return self.raw_results_df

    @property
    def results_desc(self):
        """
        Returns a description of the results.
        """
        return "Core-to-Core Latency Results"

    @property
    def number_of_runs(self):
        """
        Returns the number of runs configured for the benchmark.
        """
        return self._cfg.number_of_runs

    @property
    def run_all_cpus(self):
        """
        Returns whether to run the benchmark on all CPU pairs.
        """
        return self._cfg.all_cpus

    @property
    def node_to_cpus(self):
        """
        Returns the mapping of NUMA nodes to their respective CPUs.
        """
        if not self._node_to_cpus:
            numa_nodes = self.sysreport.sys_hw.cpu_list_per_numa_node
            if numa_nodes:
                if self.run_all_cpus:
                    log.info("Measuring latency for all CPU pairs.")
                    self._node_to_cpus = numa_nodes
                else:
                    for node, cpus in numa_nodes.items():
                        # By default, use the last two CPUs from each NUMA node for testing
                        self._node_to_cpus[node] = cpus[-2:] if len(cpus) >= 2 else cpus
            else:
                # If no NUMA nodes are detected, assume a single node with all CPUs
                cpus = list(range(self.number_of_cpus))
                if not self.run_all_cpus and len(cpus) > 2:  # Use only last two CPUs if not running all
                    cpus = cpus[-2:]
                self._node_to_cpus = {0: cpus}

        return self._node_to_cpus

    def get_step_desc(self, step):
        """Return a short description for the current benchmark step."""

        if step[0] is None:
            string = "generating outputs"
        elif not self.run_all_cpus:
            string = "measuring c2c latency"
        else:
            string = f"CPUs {step[0]}-{self.number_of_cpus - 1} data addr @ node {step[1]}"
        return string

    def lookup_benchmark_binary(self):
        return ub_cfg.lookup_benchmark_binary(self.pmu_mode, "core_to_core_latency")

    def run_benchmark(self, bmk_spec, runner):
        return runner.run_and_collect_results(bmk_spec)

    def one_step(self, cpu_a_membind_node_pair):
        """
        Measure latency between pairs of cores.
        """
        cpu_a, membind_node = cpu_a_membind_node_pair
        if cpu_a is None:
            log.debug("Finalizing step, compiling results and generating summaries")
            for key in ["Local", "Remote"]:
                # self.latency_summary generates summaries for Local and Remote latencies
                # when called for the first time.
                result = self.latency_summary.get(key, None)
                # the heatmap is always generated regardless of the output format
                if result is None:
                    continue
                result.generate_heatmap(key)
                result.generate_histogram_image(key)
            return

        core_to_core_config = ASCTBenchmarkConfig.new_from(
            self._cfg,
            target_cpus=[cpu_a],
            numa_node=membind_node,
            data_size=self.get_optimal_data_size(),
        )
        bmk_spec = CoreToCoreBenchmarkSpec(self.benchmark_binary, core_to_core_config)

        results = self.run_benchmark(bmk_spec, SyncRunner())
        results_dict = results.to_dict()

        for key, lat in results_dict.items():
            self.compiled_results[key].extend(lat)

    def deserialize(self, data):
        if not data:
            return

        metadata, raw_result = self._deserialize_payload(data)
        if raw_result is None:
            return

        self._loaded_raw_result = raw_result
        self._latency_summary = {"Local": None, "Remote": None}
        self._node_to_cpus = {}
        self._cpus_to_nodes = {}

        self.raw_results_df = pd.DataFrame.from_dict(raw_result)

        for column, dtype in {
            "CPUA": int,
            "CPUB": int,
            "LATENCY": float,
            "CPUA_NODE": int,
            "MEMBIND_NODE": int,
        }.items():
            if column in self.raw_results_df.columns:
                self.raw_results_df[column] = self.raw_results_df[column].astype(dtype)

        config = metadata.get("config", {}) if isinstance(metadata, dict) else {}
        self._cfg = self._create_default_config()
        if isinstance(config, dict) and config:
            self._cfg.update_with_dict(config)

        if {"CPUA", "CPUA_NODE"}.issubset(self.raw_results_df.columns):
            cpu_node_pairs = {
                int(cpu): int(node)
                for cpu, node in self.raw_results_df[["CPUA", "CPUA_NODE"]].drop_duplicates().itertuples(index=False)
            }
            for cpu, node in sorted(cpu_node_pairs.items()):
                self._node_to_cpus.setdefault(node, []).append(cpu)

        self.result = Result(desc=self._deserialized_result_desc(metadata), dataframe=self.raw_results_df.copy())

    def to_stdout(self):
        for key in ["Local", "Remote"]:
            result = self.latency_summary.get(key, None)
            if result is None:
                continue
            result.to_stdout(key)

    def get_save_data(self):
        result = {}
        for key in ["Local", "Remote"]:
            data = self.latency_summary.get(key, None)
            if data is not None:
                result[key] = data.get_save_data()
        return result

    def get_diff_data(self):
        """
        Returns a dictionary containing summary statistics
        for Local and Remote latency measurements.
        """
        if self._loaded_raw_result is None:
            raise RuntimeError(f"result data was not loaded for {self.name}")

        df = pd.DataFrame.from_dict(self._loaded_raw_result)
        diff_data = {}
        for locality, mask in [
            ("Local", df["CPUA_NODE"] == df["MEMBIND_NODE"]),
            ("Remote", df["CPUA_NODE"] != df["MEMBIND_NODE"]),
        ]:
            subset = df[mask]
            if not subset.empty:
                diff_data[locality] = CoreToCoreLatencyReport(subset).stats
        return diff_data
