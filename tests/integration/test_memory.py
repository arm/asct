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

import pytest
import os

from . import data_validation_memory as dvm
from .utils import run_asct

IPERF3_TEST_PORT = "25201"
IPERF3_TEST_PORT_CONFIG = [
    "--update-config",
    f"iperf3-tcp-sweep.port={IPERF3_TEST_PORT}",
    f"iperf3-udp-sweep.port={IPERF3_TEST_PORT}",
]


def expect_output_dir(benchmark_names, output_type, dev_mode=False):
    # if output_type is not "stdout", there will be one or more output files
    if output_type != "stdout":
        return True

    # output_type is stdout
    # if there's no sweep benchmark, there's no output file
    if all("sweep" not in name for name in benchmark_names):
        return False
    # if there's a sweep benchmark, it will only write to an output file if dev_mode is False
    return not dev_mode


def get_sysreport(work_dir):
    """Get sysreport used for validation"""

    result = run_asct("report", ["system-info", "--format", "json"], output_dir=os.path.join(work_dir, "system_info"))
    assert "report.json" in result.json_file_content, f"report.json not found in {result.json_file_content.keys()}"
    assert "system-info" in result.json_file_content["report.json"], "system-info not found in report.json"
    return result.json_file_content["report.json"]["system-info"]


def extract_stdout_result_tables(stdout: str) -> str:
    marker = "SYSTEM-INFO -----------------------------------"
    idx = stdout.find(marker)
    assert idx != -1, f"Could not find result table marker {marker!r} in stdout"
    return stdout[idx:]


@pytest.mark.parametrize("output_format", ["json", "csv", "stdout"])
def test_all_benchmarks(test_work_dir, output_format, memory_benchmarks, shorter_test_time):
    """Runs all benchmarks, verifies all output formats"""

    sysreport = get_sysreport(test_work_dir)
    extra_param = ["--quick-mode"] if shorter_test_time else []
    result = run_asct(
        "run",
        [*memory_benchmarks, "--format", output_format, *extra_param],
        output_dir=os.path.join(test_work_dir, output_format)
        if expect_output_dir(memory_benchmarks, output_format)
        else None,
    )
    dvm.validate_result(result, memory_benchmarks, sysreport, output_format, True, shorter_test_time)


def test_all_argument(test_work_dir, memory_benchmarks):
    """Quick runs all benchmarks using --all, verifies all benchmarks ran"""

    sysreport = get_sysreport(test_work_dir)
    result = run_asct(
        "run",
        ["all", "--format", "json", "--quick-mode", *IPERF3_TEST_PORT_CONFIG],
        output_dir=os.path.join(test_work_dir, "json"),
    )
    dvm.validate_result(result, memory_benchmarks, sysreport, "json", True, True)


@pytest.mark.parametrize("output_format", ["stdout", "json", "csv"])
def test_run_memory_view_matches_saved_output(test_work_dir, output_format):
    run_dir = os.path.join(test_work_dir, f"run_{output_format}")
    view_dir = os.path.join(test_work_dir, f"view_{output_format}")
    os.makedirs(view_dir)

    run_result = run_asct(
        "run",
        ["memory", "--format", output_format, "--quick-mode"],
        output_dir=run_dir,
    )
    view_result = run_asct(
        "view",
        [run_dir, "--format", output_format],
        output_dir=view_dir,
    )

    if output_format == "stdout":
        assert extract_stdout_result_tables(run_result.stdout) == extract_stdout_result_tables(view_result.stdout)
    elif output_format == "json":
        assert run_result.json_file_content["report.json"] == view_result.json_file_content["report.json"]
    elif output_format == "csv":
        assert run_result.csv_file_content.keys() == view_result.csv_file_content.keys()
        for csv_name, csv_content in run_result.csv_file_content.items():
            assert csv_content == view_result.csv_file_content[csv_name]
