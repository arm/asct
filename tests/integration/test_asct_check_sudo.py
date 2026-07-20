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

from .data_validation_memory import validate_result
from .test_memory import get_sysreport
from .utils import run_asct


def test_sudoless(test_work_dir):
    """Run loaded latency and validate its output without sudo."""
    if os.geteuid() == 0:
        pytest.skip("Skipping because test is running with sudo")

    benchmark_names = ["loaded-latency"]
    sysreport = get_sysreport(test_work_dir)
    result = run_asct(
        "run",
        [*benchmark_names, "--format", "json", "--quick-mode"],
        output_dir=os.path.join(test_work_dir, "sudoless-loaded-latency"),
    )

    validate_result(result, benchmark_names, sysreport, "json", validate_extra_artifacts=True, permissive=True)
