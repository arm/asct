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

from __future__ import annotations

import itertools
from abc import ABC, abstractmethod
from typing import final
import shutil
import os

import asct.core.logger as log
import asct.core.managers.ubench_reporter as ub_rep
from asct.core import asct_pmu_api as perf_api
from asct.core.datatypes import Result
from asct.core.asct_env import ASCTGlobalSettings as AGS
from asct.core.recipes.recipe_base import RecipeBase
from asct.core.recipes.impl.system_info import SystemInfo
from asct.core.resources.output_folder import RawResultsFolder
from asct.core.term_ui.progress_bar import get_progress_tracker

from collections import OrderedDict  # ruff:ignore[typing-only-standard-library-import]


class RecipeBenchmarkBase(RecipeBase, ABC):
    supports_pmu: bool = False
    """
    Base Class for recipes that run ASCT Benchmarks.
    """

    def __init__(self, metadata):
        super().__init__(metadata)
        self._raw_results_folder = None

    @property
    def results_dir(self):
        if self._raw_results_folder is None:
            raise RuntimeError(f"raw results folder was not initialized for {self.name}")
        if os.path.isdir(self._raw_results_folder.requested_folder_path):
            return self._raw_results_folder.get_output_folder_path()
        return self._raw_results_folder.requested_folder_path

    @property
    def results_desc(self) -> str:
        return ""

    def _pre_setup(self):
        self.reporter = ub_rep.get_reporter()
        self._raw_results_folder = RawResultsFolder(os.path.join(self.reporter.output_dir, "raw", self.name))

    def _create_resources(self):
        return [self._raw_results_folder]

    def _pre_run(self):
        """Pre-run hook for benchmark recipes.

        Responsibilities:
        - If the config exposes a ``data_size`` field and it is unset, attempt to
          populate it via an optional ``get_optimal_data_size`` implementation.
        - If running in PMU mode, ensure any previous perf / PMU capture output
          directory is removed so the current run starts clean.

        This is written defensively so that recipes which do not implement
        ``get_optimal_data_size`` (or do not have a ``data_size`` field) are not
        impacted.
        """
        # Derive data size only if the field exists, is None and recipe implements the helper
        if (
            self._cfg is not None
            and hasattr(self._cfg, "data_size")
            and self._cfg.data_size is None
            and hasattr(self, "get_optimal_data_size")
        ):
            try:
                self._cfg.data_size = self.get_optimal_data_size()
            except (KeyError, TypeError, ValueError, AttributeError, OSError) as e:
                log.debug("Unable to auto-determine optimal data size: %s", e)

        # Clean previous PMU output if applicable
        if self.pmu_mode:
            try:
                perf_output_dir = perf_api.output_dir(str(self))
                if os.path.isdir(perf_output_dir):
                    shutil.rmtree(perf_output_dir)
                    log.debug("Cleared previous PMU output directory: %s", perf_output_dir)
            except OSError as e:
                log.warning("Failed to clear PMU output directory: %s", e)

    @final
    def _setup(self):
        self.benchmark_binary = self.lookup_benchmark_binary()
        self._register_resources()

    @property
    def pmu_mode(self):
        """
        Check if PMU mode is enabled.

        Returns:
            bool: True if PMU mode is enabled, False otherwise.
        """
        return self._cfg.pmu_mode and self.supports_pmu is True

    @property
    def sysreport(self):
        """
        Get the system report object.

        Returns:
            SystemReport: The system report object.
        """
        system_info = SystemInfo()
        if not system_info.ready:
            raise AssertionError("System information not available, cannot proceed with benchmark")
        return system_info

    @property
    def cpu_list_per_node(self):
        """
        Get the list of CPU IDs per NUMA node.

        Returns:
            list: A list of lists, where each inner list contains CPU IDs for a NUMA node.
        """
        return self.sysreport.sys_hw.cpu_list_per_numa_node

    @property
    def cpu_list(self):
        """
        Get a flat list of all CPU IDs ordered by NUMA node.

        Returns:
            list: A flat list of CPU IDs from all NUMA nodes, ordered by node ID.
        """
        return list(
            itertools.chain.from_iterable(
                self.cpu_list_per_node[node] for node in sorted(self.cpu_list_per_node.keys())
            )
        )

    @property
    def last_cpu_ids(self):
        """
        Get the last CPU IDs from each NUMA node.

        Returns:
            list: A list of the last CPU IDs for each NUMA node.
        """
        return self.sysreport.sys_hw.last_cpus_per_numa_node

    @property
    def single_core_cpu_choice(self):
        """
        Get the CPU ID to use for single-core runs.

        Returns:
            list: The last CPU ID from the first NUMA node as a [string].
        """
        # For single core runs, use the first socket we find and pick the last cpu id, as mentioned above for less
        # busy cpu empirically.
        # Get CPU choices from the first NUMA node we find
        first_node = min(self.last_cpu_ids.keys())
        cpu_choice = self.last_cpu_ids[first_node]
        return [str(cpu_choice)]

    @property
    def default_numa_node(self):
        """
        Get the default NUMA node.

        Returns:
            int: The default NUMA node (0).
        """
        return self.get_numa_node_for_cpu(int(self.single_core_cpu_choice[0]))

    @property
    def num_numa_nodes(self):
        """
        Get the number of NUMA nodes.

        Returns:
            int: The number of NUMA nodes.
        """
        return len(self.cpu_list_per_node)

    @property
    def dev_mode_data(self):
        return Result(desc=self.results_desc, dataframe=self.dev_mode_data_df)

    @property
    def cpus_to_numa_node_map(self) -> OrderedDict[int, int]:
        """
        Get the mapping of CPU IDs to NUMA nodes.

        Returns:
            dict[int, int]: A dictionary mapping CPU IDs to their corresponding NUMA node IDs.
        """
        return self.sysreport.sys_hw.cpus_to_numa_node_map

    @final
    def get_numa_node_for_cpu(self, cpu_id: int) -> int | None:
        """
        Get the NUMA node for a given CPU ID.
        Args:
            cpu_id (int): The CPU ID to look up.
        Returns:
            int | None: The NUMA node ID if found, None otherwise.
        """
        return self.cpus_to_numa_node_map.get(cpu_id, None)

    @abstractmethod
    def lookup_benchmark_binary(self):
        """
        Lookup the benchmark binary based on the configuration.

        Returns:
            str: The path to the benchmark binary.
        """
        raise NotImplementedError("lookup_benchmark_binary must be implemented in the derived class.")

    @abstractmethod
    def dev_mode_data_df(self):
        """
        Get the development mode data as a DataFrame.

        Returns:
            pd.DataFrame: The development mode data.
        """
        raise NotImplementedError("dev_mode_data_df must be implemented in the derived class.")

    @abstractmethod
    def gen_steps(self):
        raise NotImplementedError(
            "gen_steps() must be implemented in the derived class to generate steps for the benchmark run."
        )

    @abstractmethod
    def one_step(self, *args, **kwargs):
        """
        Perform a single step of the benchmark run.

        Args:
            *args: Variable length argument list.
            **kwargs: Arbitrary keyword arguments.
        """
        raise NotImplementedError(
            "one_step() must be implemented in the derived class to define the behavior for each step."
        )

    @abstractmethod
    def get_step_desc(self, step):
        """
        Get the description of the current step.

        Returns:
            str: The description of the current step.
        """
        raise NotImplementedError

    @abstractmethod
    def get_results_df(self):
        """
        Get the results of the benchmark run as a DataFrame.

        Returns:
            pd.DataFrame: The results of the benchmark run.
        """
        raise NotImplementedError("get_results_df() must be implemented in the derived class.")

    def get_results(self):
        """
        Get the results of the benchmark run.

        Returns:
            Result: The results of the benchmark run.
        """
        return Result(desc=self.results_desc, dataframe=self.get_results_df())

    # The run_function is the main entry point for running the benchmark.
    # The main part is the gen_steps() method, which should be implemented in the derived class to generate
    # the steps for the benchmark run.
    # For simple benchmarks, it can be a list of tuples, where each tuple contains the parameters for a single step.
    # For more complex benchmarks, it can be a generator that yields the parameters for each step. We can
    # consider the yield point is the point executing the one_step() method, which should also be implemented in the
    # derived class.  (See Latency Sweep for an example of a more complex benchmark.)
    @final
    def run_function(self):
        # Setup is done by overriding setup() in the derived class
        if AGS().dev_mode():
            return self.dev_mode_data
        get_progress_tracker().wait_until_idle()
        get_progress_tracker().set_slow_mode()
        for iteration in get_progress_tracker().iterate(self.gen_steps(), lambda _, elem: self.get_step_desc(elem)):
            try:
                self.one_step(iteration)
            except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as e:  # ruff:ignore[try-except-in-loop]
                log.error(f"Error during one_step at iteration {iteration}: {e}")
                get_progress_tracker().break_from_iteration()
                raise
            finally:
                get_progress_tracker().set_fast_mode()
        return self.get_results()
