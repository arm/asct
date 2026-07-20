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

from os import path
import os
import json

import pytest

from .utils import run_asct

# cmn.csv implementation is not merged into repo yet
csv_report_csv = ["system-info.csv", "network-info.csv"]
json_report_content = ["system-info", "network-info", "cmn"]


def extract_stdout_result_tables(stdout: str) -> str:
    marker = "SYSTEM-INFO -----------------------------------"
    idx = stdout.find(marker)
    assert idx != -1, f"Could not find result table marker {marker!r} in stdout"
    return stdout[idx:]


# most of the report command's functionality is already covered by
# other tests that run recipes and check their output.
# add output formats as a parameter
@pytest.mark.parametrize("recipe", ["", "all"])
@pytest.mark.parametrize("output_format", ["stdout", "json", "csv"])
def test_report(test_work_dir, recipe, output_format):
    """
    Validate report command output artifacts for stdout/json/csv.
    """

    work_dir = path.join(test_work_dir, f"{recipe}_{output_format}")

    args = ["--format", output_format]

    if len(recipe) > 0:
        args = [recipe, *args]

    result = run_asct("report", args, output_dir=work_dir)

    if output_format == "stdout":
        assert result.stdout, "Expected stdout output, but got none"
        assert "System feature report" in result.stdout, (
            "Expected 'System Information Report' section not found in stdout"
        )
        assert "Local IPv4" in result.stdout, "Expected 'Network Information Report' section not found in stdout"
    elif output_format == "json":
        assert "report.json" in result.json_file_content, f"report.json not found in {result.json_file_content.keys()}"
        for key in json_report_content:
            assert key in result.json_file_content["report.json"], f"{key} not found in report.json"
    elif output_format == "csv":
        # Check that CSV files exist and are non-empty
        for csv_file in csv_report_csv:
            assert csv_file in result.csv_file_content, f"{csv_file} not found in {result.csv_file_content.keys()}"
            assert result.csv_file_content[csv_file], f"{csv_file} is empty"


@pytest.mark.parametrize("output_format", ["stdout", "json", "csv"])
def test_report_view_matches_output(test_work_dir, output_format):
    report_dir = path.join(test_work_dir, f"report_saved_{output_format}")
    view_dir = path.join(test_work_dir, f"view_saved_{output_format}")
    if output_format != "stdout":
        os.makedirs(view_dir)

    report_result = run_asct("report", ["all", "--format", output_format], output_dir=report_dir)
    view_result = run_asct(
        "view",
        [report_dir, "--format", output_format],
        output_dir=view_dir if output_format != "stdout" else None,
    )

    with open(path.join(report_dir, "asct.json"), "rt") as manifest_file:
        manifest = json.load(manifest_file)

    assert manifest["metadata"]["cmd_arguments"]["benchmarks"] == []
    assert path.isdir(path.join(report_dir, "raw", "system-info"))
    assert path.isdir(path.join(report_dir, "raw", "network-info"))
    if output_format == "stdout":
        assert extract_stdout_result_tables(report_result.stdout) == extract_stdout_result_tables(view_result.stdout)
    elif output_format == "json":
        assert report_result.json_file_content["report.json"] == view_result.json_file_content["report.json"]
    elif output_format == "csv":
        assert report_result.csv_file_content.keys() == view_result.csv_file_content.keys()
        for csv_name, csv_content in report_result.csv_file_content.items():
            assert csv_content == view_result.csv_file_content[csv_name]
