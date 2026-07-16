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

"""
The module capture characteristics of the memory benchmark but should not know run details
"""

import math
from collections import defaultdict
from typing import ClassVar, NamedTuple
from abc import abstractmethod

from asct.core.benchspec.benchspec import BenchmarkSpec, BenchmarkResults
from asct.core.asct_env import ASCTGlobalSettings as AGS
from asct.core.utility.format import memsize_str

import asct.core.logger as log


class MemBenchmarkSpec(BenchmarkSpec):
    START_DELAY = "0"

    def __init__(self, executable, config):
        super().__init__(executable, config)

    @staticmethod
    def get_do_count_iterations(output):
        for line in output.splitlines():
            if "do_count" in line and "iterations" in line:
                parts = line.split(",")
                do_count = int(parts[1].split("=")[1].strip())
                iterations = int(parts[2].split("=")[1].strip())
                return do_count, iterations
        return None, None

    @staticmethod
    @abstractmethod
    def get_repetitions(output):
        pass

    def process_output(self, runner):
        r = super().process_output(runner)
        output = runner.stdout
        r.sizes = self.config.data_size_orig
        reps = self.get_repetitions(output)
        if reps is None:
            raise ValueError("Could not find repetitions in the output.")
        r.repetitions = int(reps)

        return r

    def make_cmd(self):
        duration = self.config.duration
        if duration <= 0:
            raise ValueError(f"duration must be greater than 0, given {duration}")

        cmd = [
            *self.make_numa_cmd(self.config.numa_node),
            self.executable,
            "--duration",
            f"{self.config.duration}",
            "--delay-seconds",
            self.START_DELAY,
            *self.make_rest_cmd(self.config.target_cpus),
        ]

        log.debug("%s", log.LS(lambda: " ".join(cmd)))
        return cmd

    @abstractmethod
    def make_rest_cmd(self, cpus_to_use):
        pass

    def get_and_check_data(self, data_str):
        if data_str is None:
            raise ValueError("Could not find data in the output.")
        data = float(data_str)
        if math.isnan(data):
            raise ValueError("Got Nan data measurement.")
        return data


class LatencyBenchmarkSpec(MemBenchmarkSpec):
    def __init__(self, executable, config):
        super().__init__(executable, config)

    def make_rest_cmd(self, cpus_to_use):
        num_cl = self.config.data_size // self.config._cache_line_size
        randomize_flag = ["--lat-randomize"]
        if AGS().quick_mode():
            randomize_flag = []
        return [item for cpu in cpus_to_use for item in ["--lat-cpu", str(cpu)]] + [
            "--lat-cacheline-count",
            f"{num_cl}",
            "--lat-iterations",
            f"{self.config.iterations}",
            "--lat-use-hugepages",
            memsize_str(self.config.huge_page_size, suffix=""),
            "--lat-cacheline-bytes",
            f"{self.config._cache_line_size}",
            *randomize_flag,
        ]

    @staticmethod
    def get_repetitions(output):
        for line in output.splitlines():
            if "Latency Repetitions =" in line:
                return line.split(" = ")[1].split()[0]
        return None

    @staticmethod
    def get_average_latency(output):
        for line in output.splitlines():
            if line.startswith("Average Latency (ns) = "):
                return line.split(" = ")[1].split()[0]
        return "nan"

    @staticmethod
    def get_average_latency_cyc(output):
        for line in output.splitlines():
            if line.startswith("Average Latency (cycle) = "):
                return line.split(" = ")[1].split()[0]
        return "nan"

    def process_output(self, runner):
        r = super().process_output(runner)
        output = runner.stdout

        r.average_latency_ns = self.get_and_check_data(self.get_average_latency(output))
        r.average_latency_cyc = self.get_and_check_data(self.get_average_latency_cyc(output))

        return r


class MemoryAccessDesc(NamedTuple):
    long: str
    short: str

    def supported(self, _sysreport):
        """
        Indicates whether this access type is supported on the current platform.
        By default, assuming supported and let subclass to override.
        """
        return True


class NonTemporalMemoryAccessDesc(MemoryAccessDesc):
    def supported(self, _sysreport):
        """
        Indicates whether this access type is supported on the current platform.
        Non-temporal accesses may not be supported on all architectures.
        For Intel systems, we assume support.
        For ARM systems, need SVE extension.
        For other systems, assume not supported.
        """
        if _sysreport.sys_hw.arch == "x86_64":
            return True  # Intel systems, assume support
        # The archtecture string for ARM system should have been normalized to start with 'arm' in sysreport
        # e.g. ARMv9.0
        if _sysreport.sys_hw.arch.lower().startswith("arm"):
            # ARM systems, check SVE using CPU features
            cpu_features = _sysreport.sys_hw.cpu_features
            if cpu_features is None:
                return False  # Cannot determine CPU features, assume not supported
            return "sve" in cpu_features
        return False  # Other systems, assume not supported


class BandwidthBenchmarkSpec(MemBenchmarkSpec):
    # key = access_type, value = MemoryAccessDesc
    access_descs: ClassVar[dict[int, MemoryAccessDesc]] = {
        0: MemoryAccessDesc("All Reads", "All Reads"),
        # 1 is write only, but we don't use that
        2: MemoryAccessDesc("3:1 Reads-Writes", "3:1 Rd-Wr"),
        3: MemoryAccessDesc("2:1 Reads-Writes", "2:1 Rd-Wr"),
        4: MemoryAccessDesc("1:1 Reads-Writes", "1:1 Rd-Wr"),
        5: NonTemporalMemoryAccessDesc("2:1 Rd-Wr (Non-Temporal)", "2:1 Rd-Wr (NTS)"),
    }

    def __init__(self, executable, config, access_type):
        super().__init__(executable, config)
        self.access_type = access_type
        self.access_desc = self.access_descs[access_type]

    def make_rest_cmd(self, cpus_to_use):
        return [item for cpu in cpus_to_use for item in ["--bw-cpu", str(cpu)]] + [
            "--bw-buflen",
            f"{self.config.data_size}",
            "--bw-fine-delay",
            f"{self.config.bw_delay}",
            f"--bw-write={self.access_type}",
            "--bw-cacheline-bytes",
            f"{self.config._cache_line_size}",
        ]

    @staticmethod
    def get_repetitions(output):
        for line in output.splitlines():
            if "Bandwidth Repetitions =" in line:
                return line.split(" = ")[1].split()[0]
        return None

    @staticmethod
    def get_total_bandwidth_mbps(output):
        for line in output.splitlines():
            if line.startswith("Total Bandwidth (MB/sec) = "):
                return line.split(" = ")[1].split()[0]
        return "nan"

    @staticmethod
    def get_total_bandwidth_bpc(output):
        for line in output.splitlines():
            if line.startswith("Total Bandwidth (B/cycle) = "):
                return line.split(" = ")[1].split()[0]
        return "nan"

    def process_output(self, runner):
        r = super().process_output(runner)
        output = runner.stdout

        r.total_bandwidth_mbps = self.get_and_check_data(self.get_total_bandwidth_mbps(output))
        r.total_bandwidth_bpc = self.get_and_check_data(self.get_total_bandwidth_bpc(output))

        return r


class CoreToCoreResults(BenchmarkResults):
    def __init__(self):
        super().__init__()
        self._set("result_data", defaultdict(list))

    def to_dict(self):
        return self.result_data


class CoreToCoreBenchmarkSpec(BenchmarkSpec):
    def __init__(self, exec_file, config):
        super().__init__(exec_file, config)

    def make_cmd(self):
        command = [self.executable, str(self.config.target_cpus[0]), f"-I{self.config.iterations}", "-x"]
        # If node_mask is provided, add it to the command
        # This is used to bind the memory allocation to a specific NUMA node.
        if "numa_node" in self.config and self.config.numa_node:
            node_mask = 1 << int(self.config.numa_node)
            command += [f"-m{node_mask}"]

        if "data_size" in self.config and self.config.data_size and self.config.data_size > 0:
            command += [f"-s{self.config.data_size}"]

        return command

    def check_output(self, runner):
        # Ping-pong outputs nothing when running for last core so not error to have empty output.
        pass

    def process_output(self, runner):
        output = runner.stdout
        results = CoreToCoreResults()
        for line in output.strip().split("\n"):
            if not line.strip():
                log.debug("Skipping empty line in latency output")
                continue
            parts = line.split()
            if len(parts) != 3:
                log.debug(f"Malformed latency output line: '{line}'")
                continue
            cpua, cpub, lat = parts
            # Skip lines that indicate offline CPUs or malformed lines
            if lat == "-1":
                log.debug(f"Skipping CPU{cpua} or CPU{cpub} is offline")
                continue

            results.result_data[int(cpua), int(cpub), self.config.numa_node].append(float(lat))
        return results
