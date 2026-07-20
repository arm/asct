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

from .data_validation import is_str, validate_json


# benchmark_names is a list of (full_name, short_name) tuples
def validate_stdout_data(stdout, benchmark_names):
    benchmarks_found = []
    for line in stdout.splitlines()[:-1]:
        # skip lines where there's no benchmark name (4 chars is the indent for a benchmark name)
        if line.startswith(" " * 5):
            continue
        line = line.strip()
        benchmarks_found.append(line.split()[0])
    benchmarks_found = set(benchmarks_found)
    # we expect to find <full_name>,<short_name> in the list, for example:
    # idle-latency,il             Report a matrix of idle memory latency across NUMA nodes
    for benchmark in benchmark_names:
        assert f"{benchmark[0]},{benchmark[1]}" in benchmarks_found, f"Benchmark {benchmark} missing from stdout list"


def validate_json_data(json_data, benchmark_names):
    expected_json = {"memory": {benchmark[0]: is_str for benchmark in benchmark_names}}
    validate_json(expected_json, json_data)


def validate_csv_data(csv_data, benchmark_names):
    benchmarks_found = [line[1] for line in csv_data]
    benchmarks_found = set(benchmarks_found)
    for benchmark in benchmark_names:
        assert benchmark[0] in benchmarks_found, f"Benchmark {benchmark} missing from csv list"
