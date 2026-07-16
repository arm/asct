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
import json


UBENCH_JSON = os.path.join(os.path.dirname(__file__), "config/ubench.json")


# Ubench configuration manager
class UbenchConfig:
    def __init__(self, config_path):
        self.config_path = config_path
        with open(self.config_path, "r") as config_file:
            self.config_dict = json.load(config_file)

    def lookup_benchmark_binary(self, use_probe, benchmark_name):
        bench_info = None
        benchmark_dict = self.config_dict["benchmarks"]
        if benchmark_name in benchmark_dict:
            bench_info = benchmark_dict[benchmark_name]
        else:
            raise ValueError(f"Unknown benchmark: {benchmark_name}")

        benchmark_info = bench_info["probe_version"] if use_probe else bench_info["no_probe_version"]
        return benchmark_info["binary"]


ubench_config = UbenchConfig(UBENCH_JSON)
