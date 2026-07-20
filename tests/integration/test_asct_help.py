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


def test_basic_help():
    """
    Print help and verify some strings are there
    """
    result = run_asct("help")
    expected_lines = [
        "ASCT commands",
        "Available benchmarks",
    ]
    for line in expected_lines:
        assert line in result.stdout, f"'{line}' not found in\n{result.stdout}"

    # We also expect help to include the version number.
    # The package might have 'editable.' in the version if installed in dev mode.
    # e.g.   'ASCT 0.3.0.post0+d0a04a1'
    # versus 'ASCT 0.3.0.post0+editable.d0a04a1'
    # so we'll accept either of those forms in the output.
    version = get_asct_version_from_src()
    [main_version, commit_sha] = version.split("+")
    expected_versions = [version, f"{main_version}+editable.{commit_sha}"]
    any_expected_lines = [
        f"ASCT: Arm System Characterization Tool (version: {version})" for version in expected_versions
    ]
    assert any(line in result.stdout for line in any_expected_lines)
