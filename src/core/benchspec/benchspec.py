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
The module capture characteristics of the benchmark but should not know run details
"""

import pandas as pd

from abc import ABC, abstractmethod

import asct.core.logger as log

from asct.core.asct_env import ASCTGlobalSettings as AGS
from asct.core.datatypes import ASCTDataRegistry
from asct.core.utility.files import read_json_stdout
import shlex
import datetime

SLOW_MODE_SCALING_FACTORS = {"iter": 1.0e-3, "time": 1.0e-2, "dsize": 1.0e-1}
CACHE_LINE_SIZE_DEFAULT = 64


class ASCTBenchmarkConfig(ASCTDataRegistry):
    def __init__(self, **fields):
        super().__init__()
        self._set("_cache_line_size", CACHE_LINE_SIZE_DEFAULT)
        self.update_with(**fields)

    def _get_adjusted_iter_count(self, original_count):
        if AGS().quick_mode():
            return max(1, int(original_count * SLOW_MODE_SCALING_FACTORS["iter"]))
        return original_count

    def _get_adjusted_time_delay(self, original_delay):
        if AGS().quick_mode():
            return 0
        return original_delay

    def _get_adjusted_number_of_runs(self, original_runs):
        if AGS().quick_mode():
            return 1
        return original_runs

    def _get_adjusted_duration(self, original_duration):
        # Currently, benchmark duration is usually 0.25s
        # quick_mode reduces it to 7.5% of the original one down to a minimum
        # of 0.015s or 15ms in order to allow some data to be captured
        if AGS().quick_mode():
            return max(0.002, original_duration * SLOW_MODE_SCALING_FACTORS["time"])
        return original_duration

    def _get_adjusted_size(self, original_size):
        if AGS().quick_mode():
            cache_line_count = original_size // self._cache_line_size
            adj_cache_line_count = max(int(cache_line_count * SLOW_MODE_SCALING_FACTORS["dsize"]), 1)
            return self._cache_line_size * adj_cache_line_count
        return original_size

    def _get_adjusted_value(self, name, orig_value):
        """
        Parses the name and scales the values only if the name doesn't start with '_'.
        Returns a tuple (adjusted_value, keep_original) and if the second value is True,
        the original value is kept under {key_name}_orig: value
        """
        if name.startswith("_"):
            return orig_value, False
        if name == "iteration":
            return self._get_adjusted_iter_count(orig_value), False
        if name == "duration":
            return self._get_adjusted_duration(orig_value), False
        if name == "time_delay":
            return self._get_adjusted_time_delay(orig_value), False
        if name == "data_size":
            return self._get_adjusted_size(orig_value), True
        if name == "number_of_runs":
            return self._get_adjusted_number_of_runs(orig_value), False
        return orig_value, False

    def _set(self, name, value):
        if value is None:
            return
        adjusted_value, keep_original = self._get_adjusted_value(name, value)
        super()._set(name, adjusted_value)
        if keep_original:
            super()._set(f"{name}_orig", value)


class BenchmarkResults(ASCTDataRegistry):
    """
    Results from a single workload run.
    """

    def to_dict(self):
        return self.get_dict()

    def to_dataframe(self):
        return pd.DataFrame([self.to_dict()])


class ProgramSpec(ABC):
    def __init__(self, config):
        self.set_config(config)

    @abstractmethod
    def make_cmd(self):
        pass

    def process_output(self, runner):  # ruff:ignore[unused-method-argument]
        # Subclasses should override this method to process the output
        return BenchmarkResults()

    def set_config(self, config):
        self.config = config

    def make_numa_cmd(self, ll_membind_default, cpu_list=None):
        if ll_membind_default is None:
            return []
        cmd = ["numactl", "--membind", str(ll_membind_default)]
        if cpu_list:
            cmd.extend(["-C"] + [str(cpu) for cpu in cpu_list])
        return cmd

    # Subclass can override to check for benchmark specific output
    def check_output(self, runner):
        if not runner.stdout:
            raise RuntimeError("Benchmark execution didn't produce any output")


class BenchmarkSpec(ProgramSpec):
    def __init__(self, executable, config):
        super().__init__(config)
        self.executable = executable


class CustomAppSpec(ProgramSpec):
    def __init__(self, run_cmd):
        super().__init__(None)
        self.run_cmd = run_cmd

    def make_cmd(self):
        numa_cmd = self.make_numa_cmd(self.config.numa_node, self.config.target_cpus)
        run_cmd_array = shlex.split(self.run_cmd)
        # Warn when numactl command is found in run_cmd_array
        if "numactl" in run_cmd_array:
            log.warning("numactl found in the custom command. It will be prefixed again by ASCT.")
        return numa_cmd + run_cmd_array

    def check_output(self, runner):
        # Custom workload may not do any output, so just accept anything
        pass

    def process_output(self, runner):
        r = super().process_output(runner)
        r.output = runner.stdout
        return r


class MpstatSpec(ProgramSpec):
    def make_cmd(self):
        return [
            *self.make_numa_cmd(self.config.numa_node, self.config.target_cpus),
            "mpstat",
            "-o",
            "JSON",
            "-P",
            "ALL",
            "1",
        ]

    # Parse the output of mpstat JSON format
    # Below is a sample of the JSON structure
    # {
    #   "sysstat": {
    #     "hosts": [
    #       {
    #         "nodename": "hostname",
    #         "sysname": "Linux",
    #         "release": "5.4.0-42-generic",
    #         "machine": "aarch64",
    #         "number-of-cpus": 192,
    #         "date": "11/25/25",
    #         "statistics": [
    #           {
    #             "timestamp": "16:00:00",
    #             "cpu-load": [
    #               {"cpu": "all", "usr": 0.02, "nice": 0.00, "sys": 0.03, "iowait": 0.00, "irq": 0.00, "soft": 0.00,
    #                   "steal": 0.00, "guest": 0.00, "gnice": 0.00, "idle": 99.95},
    #               {"cpu": "0", "usr": 0.00, "nice": 0.00, "sys": 0.00, "iowait": 0.00, "irq": 0.00, "soft": 0.00,
    #                   "steal": 0.00, "guest": 0.00, "gnice": 0.00, "idle": 100.00},
    #               ,
    #               ...
    #             ]
    #           },
    #           ...
    #         ]
    #       }
    #     ]
    #   }
    def process_output(self, runner):
        r = super().process_output(runner)
        output = runner.stdout
        # Read the output JSON if exist and parse it to a DataFrame
        try:
            mpstat_dict = read_json_stdout(output)
            host_list = mpstat_dict["sysstat"]["hosts"]
            if len(host_list) != 1:
                raise RuntimeError("Expect to collect on one host and got too many.")
            host_dict = host_list[0]
            run_date = host_dict["date"]
            all_data = []
            # iterate the statistics list to collect relevant information
            for stats in host_dict["statistics"]:
                time_stamp = stats["timestamp"]
                for info in stats["cpu-load"]:
                    info["run_date"] = run_date
                    info["time_stamp"] = time_stamp
                    all_data.append(info)
            mpstat_df = pd.DataFrame(all_data)
            mpstat_df["datetime_str"] = mpstat_df["run_date"] + " " + mpstat_df["time_stamp"]
            # Parse as local time
            local_tz = datetime.datetime.now().astimezone().tzinfo
            parsed_dt = pd.to_datetime(mpstat_df["datetime_str"], format="%m/%d/%y %H:%M:%S")
            mpstat_df["datetime"] = parsed_dt.dt.tz_localize(local_tz)
            # Convert to UTC and epoch
            mpstat_df["datetime_utc"] = mpstat_df["datetime"].dt.tz_convert("UTC")
            epoch_start = pd.Timestamp("1970-01-01", tz="UTC")
            # Calculate the epoch time in seconds (epoch start from 1970-01-01)
            mpstat_df["epoch"] = (mpstat_df["datetime_utc"] - epoch_start).dt.total_seconds().astype("int64")
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            log.error(f"Failed to parse mpstat output JSON: {e}")
            mpstat_df = pd.DataFrame()

        r.output = output
        r.mpstat_df = mpstat_df
        return r
