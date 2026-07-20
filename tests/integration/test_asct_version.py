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

from .utils import run_asct, get_asct_version_from_src


def test_basic_version():
    """
    Print version and verify some strings are there
    """
    version = get_asct_version_from_src()
    result = run_asct("version")
    # The package might have 'editable.' in the version if installed in dev mode.
    # e.g.   'ASCT 0.3.0.post0+d0a04a1'
    # versus 'ASCT 0.3.0.post0+editable.d0a04a1'
    # so we'll accept either of those forms in the output.
    [main_version, commit_sha] = version.split("+")
    any_expected_lines = [version, f"{main_version}+editable.{commit_sha}"]
    assert any(line in result.stdout for line in any_expected_lines)
