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


def test_nofile_overwrite(test_work_dir, shorter_test_time):
    shorter_test_time = True
    extra_param = ["--quick-mode"] if shorter_test_time else []

    def run_count_png(test_work_dir, bms, folder_name):
        work_dir = os.path.join(test_work_dir, folder_name)
        _ = run_asct(
            "run",
            [
                *bms,
                *extra_param,
            ],
            output_dir=work_dir,
        )
        return len([f for f in os.listdir(work_dir) if f.endswith(".png")])

    # Just run srss and sids separately and together and check the number of png files created in the output directory
    # See whether they add up to the same number of png files when run together
    num_png_srss = run_count_png(test_work_dir, ["srss"], "srss")
    num_png_sids = run_count_png(test_work_dir, ["sids"], "sids")
    num_png_both = run_count_png(test_work_dir, ["srss", "sids"], "both")
    assert num_png_both == num_png_srss + num_png_sids, (
        "Number of png files when running both should equal the sum of png files when running separately"
    )


@pytest.mark.parametrize("output_format", ["json", "csv", "stdout"])
def test_all_benchmarks(test_work_dir, output_format, storage_benchmarks, shorter_test_time):
    """Runs all benchmarks, verifies all output formats"""
    shorter_test_time = True
    extra_param = ["--quick-mode"] if shorter_test_time else []
    for bm in storage_benchmarks:
        work_dir = os.path.join(test_work_dir, output_format, bm)
        result = run_asct(
            "run",
            [
                bm,
                "--format",
                output_format,
                *extra_param,
            ],
            output_dir=work_dir,
        )
        data_columns = [
            "Read BW (MB/s)",
            "Write BW (MB/s)",
            "Total BW (MB/s)",
            "Read Thruput (kops)",
            "Write Thruput (kops)",
            "Thruput (kops)",
            "Read Lat. (us)",
            "Write Lat. (us)",
            "Lat. (us)",
            "CPU usr (%)",
            "CPU sys (%)",
            "CPU iowait (%)",
        ]
        if output_format == "stdout":
            for data_col in data_columns:
                assert data_col in result.stdout, f"{data_col} not found in stdout"
        elif output_format == "json":
            # Check that report.json exists and contains the right keys
            assert "report.json" in result.json_file_content, "report.json was not found in results"
            json_data = result.json_file_content["report.json"]
            assert "io" in json_data, "'io' section not found in report.json"
            assert bm in json_data["io"], f"'{bm}' section not found in 'io' section of report.json"
            for data_col in data_columns:
                assert data_col in json_data["io"][bm], (
                    f"'{data_col}' not found in '{bm}' section of 'io' section of report.json"
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
            for check_col in ["Total BW (MB/s)", "Thruput (kops)", "Lat. (us)"]:
                index_of_check_col = data_columns.index(check_col) + 1  # +1 to account for first empty column
                assert isinstance(float(csv_data[1][index_of_check_col]), float), f"Data type error in {bm}.csv"
