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


def test_sudo_check():
    """
    Checks behavior of the check_sudo resource object when ASCT runs without sudo
    """
    # skip when test is running with sudo
    if os.geteuid() == 0:
        pytest.skip("Skipping because test is running with sudo")

    expected_line = "sudo/root is required for this operation"

    result = run_asct("run", ["idle-latency", "--no-cache"])

    assert expected_line in result.stdout, f"'{expected_line}' not found in\n{result.stdout}"
