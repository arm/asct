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
import threading

import pytest

from .data_validation_memory import validate_result
from .test_memory import get_sysreport
from .utils import run_asct


@pytest.mark.parametrize("dev_mode", [True, False])
def test_locking(test_work_dir, dev_mode, short_memory_benchmark):
    """Runs multiple instances of ASCT in parallel, checks only one ran successfully if dev_mode is not set
    and if all instances run successfully if it is set"""

    instance_count = 10
    expected_success_count = 1
    benchmark_names = [short_memory_benchmark]
    extra_param = []
    command_results = [None] * instance_count
    if dev_mode:
        expected_success_count = 10
        extra_param = ["--dev-mode"]

    def run_one_instance(instance_index):
        command_results[instance_index] = run_asct(
            "run",
            [*benchmark_names, "--format", "json", *extra_param],
            output_dir=os.path.join(test_work_dir, f"{instance_index}"),
            assert_on_failure=False,
        )

    sysreport = get_sysreport(test_work_dir)
    threads = [threading.Thread(target=run_one_instance, args=(idx,)) for idx in range(instance_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    success_count = 0
    for result in command_results:
        if result.ret_code == 0:
            validate_result(result, benchmark_names, sysreport, "json", not dev_mode, False)
            success_count += 1
            continue
        expected_error_message = "Unable to acquire application lock, another instance of ASCT is running"
        assert expected_error_message in result.stderr, (
            f"ASCT didn't produce the expected error message\nstderr: {result.stderr}"
        )

    assert success_count == expected_success_count, (
        f"{success_count} ASCT instances completed successfully (expected: {expected_success_count})"
    )
