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

from .utils import run_asct

COLUMNS_WITH_CYCLE_NAME = {
    "idle-latency": None,
    "peak-bandwidth": ["Traffic type", "Peak BW [B/cycle]", "% of Peak Theoretical"],
    "cross-numa-bandwidth": None,
    "latency-sweep": ["Lower Bound", "Upper Bound", "Optimum Datasize", "Latency [cycle]"],
    "bandwidth-sweep": ["Datasize Used", "Level", "Bandwidth [B/cycle]"],
    "loaded-latency": ["Injected NOPs", "Loaded latency [cycle]", "Bandwidth [B/cycle]", "% of Peak Theoretical BW"],
}


@pytest.mark.parametrize("output_format", ["json", "csv", "stdout"])
def test_all_benchmarks(test_work_dir, output_format, memory_benchmarks, shorter_test_time):
    """Runs all benchmarks, verifies all output formats"""
    shorter_test_time = True
    extra_param = ["--quick-mode"] if shorter_test_time else []
    for bm in memory_benchmarks:
        data_columns = COLUMNS_WITH_CYCLE_NAME[bm]
        if data_columns is None:
            # Skip benchmarks without cycle-based data columns
            continue
        work_dir = os.path.join(test_work_dir, output_format, bm)
        result = run_asct(
            "run",
            [
                bm,
                "--format",
                output_format,
                "--update-config",
                f"{bm}.cycle_base=1",
                *extra_param,
            ],
            output_dir=work_dir,
        )

        if output_format == "stdout":
            for data_col in data_columns:
                assert data_col in result.stdout, f"{data_col} not found in stdout"
        elif output_format == "json":
            # Check that report.json exists and contains the right keys
            assert "report.json" in result.json_file_content, "report.json was not found in results"
            json_data = result.json_file_content["report.json"]
            assert "memory" in json_data, "'memory' section not found in report.json"
            assert bm in json_data["memory"], f"'{bm}' section not found in 'memory' section of report.json"
            for data_col in data_columns:
                assert data_col in json_data["memory"][bm], (
                    f"'{data_col}' not found in '{bm}' section of 'memory' section of report.json"
                )
        elif output_format == "csv":
            # Check that csv data file exists and is non-empty
            assert f"{bm}.csv" in result.csv_file_content, f"{bm}.csv was not found in results"
            csv_data = result.csv_file_content[f"{bm}.csv"]
            assert len(csv_data) > 0, f"{bm}.csv is empty"
            # Header check, all except first column
            assert data_columns == csv_data[0][1:], f"Header mismatch in {bm}.csv"
            # Check that the CSV data has the expected number of columns
            assert len(csv_data[1]) == len(data_columns) + 1, f"Column count mismatch in {bm}.csv"
