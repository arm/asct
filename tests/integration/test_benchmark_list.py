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
import pytest

from .utils import run_asct
from .data_validation_benchmark_list import validate_stdout_data, validate_json_data, validate_csv_data


@pytest.mark.parametrize("output_format", ["stdout", "json", "csv"])
def test_benchmark_list(test_work_dir, output_format, memory_benchmarks_all_names):
    work_dir = os.path.join(test_work_dir, output_format) if output_format != "stdout" else None
    result = run_asct("list", ["--format", output_format], output_dir=work_dir)
    if output_format == "stdout":
        validate_stdout_data(result.stdout, memory_benchmarks_all_names)
    elif output_format == "json":
        assert "benchmark_list.json" in result.json_file_content, "benchmark_list.json not found in results"
        validate_json_data(result.json_file_content["benchmark_list.json"], memory_benchmarks_all_names)
    elif output_format == "csv":
        assert "benchmark_list.csv" in result.csv_file_content, "benchmark_list.csv not found in results"
        validate_csv_data(result.csv_file_content["benchmark_list.csv"], memory_benchmarks_all_names)
