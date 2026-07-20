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

import logging
import os

from . import data_validation_sysreport as dvs

from .utils import run_asct, get_system_total_mem_bytes, get_system_cpu_count

log = logging.getLogger(__name__)


def test_sysreport(test_work_dir, is_bare_metal):
    total_system_mem_size = get_system_total_mem_bytes()
    total_system_cpu_count = get_system_cpu_count()

    json_report = None
    for fmt in ["stdout", "json", "csv"]:
        result = run_asct(
            "report",
            ["system-info", "--format", fmt],
            output_dir=os.path.join(test_work_dir, fmt) if fmt != "stdout" else None,
        )
        if fmt == "stdout":
            dvs.validate_stdout_data(result.stdout, total_system_cpu_count, total_system_mem_size)
        elif fmt == "json":
            assert "report.json" in result.json_file_content, (
                f"report.json not found in {result.json_file_content.keys()}"
            )
            json_report = result.json_file_content["report.json"]
            dvs.validate_json_data(json_report, total_system_cpu_count, total_system_mem_size, is_bare_metal)
        elif fmt == "csv":
            # system-info may now write multiple CSV files (e.g. extra sections).
            # Pick the one that looks like sysreport by checking for known keys.
            assert result.csv_file_content, "No CSV files were produced"

            csv_report = None
            for content in result.csv_file_content.values():
                keys = [row[0] for row in content if row]
                if any(k.startswith("sys_hw.") for k in keys) and any(k.startswith("memory.") for k in keys):
                    csv_report = content
                    break

            assert csv_report is not None, f"No sysreport-like CSV found in {list(result.csv_file_content.keys())}"
            dvs.validate_csv_data(json_report, csv_report)
