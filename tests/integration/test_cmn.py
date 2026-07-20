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
import subprocess
import pytest
from pathlib import Path
from .utils import run_asct


# Manage perf_event_paranoid level for tests that require perf access
# Test needs to set level to 0 to allow perf access
SYSCTL = "/proc/sys/kernel/perf_event_paranoid"


# Fixtures to ensure test environment is suitable for CMN perf tests
@pytest.fixture(scope="session", autouse=True)
def require_arm_cmn_driver():
    if not os.path.exists("/sys/bus/event_source/devices/arm_cmn_0"):
        pytest.skip("arm-cmn driver not installed")


# Fixtures to ensure test environment is suitable for CMN perf tests
@pytest.fixture(scope="session", autouse=True)
def require_root():
    if os.geteuid() != 0:
        pytest.skip("Root required to manage perf_event_paranoid")


def get_level():
    return int(Path(SYSCTL).read_text().strip())


def set_level(val):
    subprocess.check_call(
        ["sysctl", "-w", f"kernel.perf_event_paranoid={val}"],  # ruff:ignore[start-process-with-partial-path]
        stdout=subprocess.DEVNULL,
    )


# Fixture to set perf_event_paranoid to 0 for CMN cpu detection tests
@pytest.fixture(scope="session", autouse=True)
def perf_paranoid_guard():
    original = get_level()
    if original != 0:
        set_level(0)

    yield

    if get_level() != original:
        set_level(original)


# Test cases for CMN recipe
@pytest.mark.parametrize("print_level", ["detect", "standard", "verbose", "verbose_csv", "verbose_json"])
def test_cmn_display_levels(test_work_dir, print_level):
    """
    Test the CMN recipe with different print levels.
    Validates that the expected output is present in stderr.
    """

    work_dir = os.path.join(test_work_dir, "cmn", str(print_level))
    cmd = ["cmn"]

    if print_level == "standard":
        cmd.extend(["--update-config", "cmn.diagram=true"])
    elif print_level == "verbose_csv":
        cmd.extend(["--verbose", "--format", "csv"])
    elif print_level == "verbose_json":
        cmd.extend(["--verbose", "--format", "json"])
    else:
        cmd.append(f"--{print_level}")

    result = run_asct("report", cmd, output_dir=work_dir)

    if print_level == "verbose_csv":
        # Check that cmn.csv exists and is non-empty
        assert "cmn.csv" in result.csv_file_content
        csv_data = result.csv_file_content["cmn.csv"]
        title = [
            "system_type",
            "cmn_id",
            "version",
            "CHI version",
            "X/Y config",
            "hn_type",
            "hn_count",
            "CCG count",
            "node",
            "reg_name",
            "field_name",
            "value",
            "bit_range",
            "description",
        ]
        assert len(csv_data) > 0
        assert csv_data[0] == title  # Header check

    elif print_level == "verbose_json":
        assert "report.json" in result.json_file_content
        json_data = result.json_file_content["report.json"]
        assert "cmn" in json_data
        assert "system_type" in json_data["cmn"]

    else:
        expected = ["System", "CMN Instance #0"]

        if print_level != "standard":
            expected.append("CPU Grid Layout")

        elif print_level == "verbose":
            expected.append("Registers:")

        for exp in expected:
            assert exp in result.stdout, f"Expected '{exp}' in output"

        if print_level == "detect":
            assert "Detecting CPU locations in the CMN topology" in result.stderr
            assert "Discovered CPUs:" not in result.stdout
            assert "Discovered CPUs:" not in result.stderr
