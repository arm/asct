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


@pytest.mark.parametrize("output_format", ["json", "csv"])
def test_quiet_mode(test_work_dir, output_format, memory_benchmarks, shorter_test_time):
    """Runs in quiet mode, verifies if no stdout output has been produced"""

    sysreport = get_sysreport(test_work_dir)
    extra_param = ["--quick-mode"] if shorter_test_time else []
    result = run_asct(
        "run",
        [*memory_benchmarks, "--format", output_format, "--quiet", *extra_param],
        output_dir=os.path.join(test_work_dir, output_format),
        enable_progress_bar=True,
    )
    assert not result.stdout, f"stdout has output with --quiet-mode:\nstdout: {result.stdout}"
    validate_result(result, memory_benchmarks, sysreport, output_format, True, shorter_test_time)
