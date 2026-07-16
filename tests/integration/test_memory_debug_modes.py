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

import os
import time

import pytest

from .data_validation_memory import validate_result
from .data_validation import is_int_str
from .test_memory import expect_output_dir, get_sysreport
from .utils import run_asct


def generate_dev_mode_sysreport():
    """Generate a fake sysreport for --dev-mode which has the exact number of numa nodes
    used for --dev-mode data
    """

    return {
        "sys_hw": {"n_numa_nodes": 2, "arch": "ARMv9.0", "cpu_features": ["sve"]},
        "memory": {"peak_theoretical_bw": 12345.6},
    }


@pytest.mark.parametrize("output_format", ["json", "csv", "stdout"])
def test_dev_mode(test_work_dir, output_format, memory_benchmarks):
    """Runs using dev-mode, validates the results"""

    sysreport = generate_dev_mode_sysreport()
    result = run_asct(
        "run",
        [*memory_benchmarks, "--format", output_format, "--dev-mode"],
        output_dir=os.path.join(test_work_dir, output_format)
        if expect_output_dir(memory_benchmarks, output_format, True)
        else None,
    )
    validate_result(result, memory_benchmarks, sysreport, output_format, False, False)


def test_quick_mode(test_work_dir, memory_benchmarks, long_memory_benchmark, shorter_test_time):
    """Runs quick mode, compares to regular mode and verifies it runs in at most 20% of the regular mode time"""

    benchmark_names = [long_memory_benchmark] if shorter_test_time else memory_benchmarks
    quick_mode_time_percentage = 20
    factor = quick_mode_time_percentage / 100.0
    times = [0] * 2

    sysreport = get_sysreport(test_work_dir)
    for idx, param in enumerate(["", "--quick-mode"]):
        start_time = time.time()
        cmd_params = [*benchmark_names, "--no-progress-bar", "--format", "json"]
        if param:
            cmd_params += [param]
        result = run_asct("run", cmd_params, output_dir=os.path.join(test_work_dir, f"{idx}"))
        end_time = time.time()
        times[idx] = end_time - start_time

        validate_result(result, benchmark_names, sysreport, "json", True, param == "--quick-mode")

    time_threshold = factor * times[0]
    assert times[1] < time_threshold, (
        f"--quick-mode took longer than {quick_mode_time_percentage}% of regular mode "
        f"({times[1]:.3f}s vs {quick_mode_time_percentage}% * {times[0]:.3f}s = {time_threshold:.3f}s)"
    )


def test_enable_pmu(test_work_dir, monkeypatch):
    # Set the environment variable for the test
    monkeypatch.setenv("ASCT_DEBUG_ENABLE_PMU", "1")
    sysreport = get_sysreport(test_work_dir)
    result = run_asct(
        "run",
        ["latency-sweep", "bandwidth-sweep", "--quick-mode", "--log-level", "debug"],
        output_dir=os.path.join(test_work_dir, "stdout"),
    )
    validate_result(result, ["latency-sweep", "bandwidth-sweep"], sysreport, "stdout", True, True)
    expected_debug_message = "compute_pmu_metrics()"
    assert expected_debug_message in result.stderr
    # check we got values for every sample
    output_json = ["bandwidth-sweep.ubench.json", "latency-presweep.ubench.json", "latency-sweep.ubench.json"]
    for file in output_json:
        assert f"{file}" in result.json_file_content, f"{file} not found in {result.json_file_content.keys()}"
        json_report = result.json_file_content[file]
        # this isn't all the columns, just the ones we're checking
        # CPU_CYCLES and INST_RETIRED should be reliable at returning non-zero integers for all samples
        pmu_data_columns = ["CPU_CYCLES", "CPU_CYCLES:time_enabled_ns", "INST_RETIRED", "INST_RETIRED:time_enabled_ns"]
        for x in pmu_data_columns:
            for n, v in json_report[x].items():
                is_int_str(v, x)  # should be a non-null integer
                assert int(v) != 0, f"{file}: PMU reading of zero (0) found for event: {x} in sample {n}"
