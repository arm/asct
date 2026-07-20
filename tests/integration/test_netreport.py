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

from . import data_validation_netreport as dvn
from .utils import run_asct


def test_netreport(test_work_dir):
    json_report = None

    # Validate JSON first (network-info report structure).
    result_json = run_asct(
        "report",
        ["network-info", "--format", "json"],
        output_dir=os.path.join(test_work_dir, "json"),
    )
    assert "report.json" in result_json.json_file_content, (
        f"report.json not found in {result_json.json_file_content.keys()}"
    )
    json_report = result_json.json_file_content["report.json"]
    dvn.validate_json_data(json_report)

    # Validate stdout is present (lightweight marker checks only).
    result_stdout = run_asct("report", ["network-info", "--format", "stdout"], output_dir=None)
    dvn.validate_stdout_data(result_stdout.stdout)

    # Validate CSV output exists and network rows can be mapped back to JSON structure.
    csv_file = "network-info.csv"
    result_csv = run_asct("report", ["network-info", "--format", "csv"], output_dir=os.path.join(test_work_dir, "csv"))
    assert result_csv.csv_file_content, "No CSV files were produced"
    assert csv_file in result_csv.csv_file_content, f"{csv_file} not found in {result_csv.csv_file_content.keys()}"
    dvn.validate_csv_data(json_report, result_csv.csv_file_content[csv_file])
