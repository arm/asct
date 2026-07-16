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

import pytest
from os import path
from .utils import run_asct


def test_force_flag(test_work_dir):
    """
    Verify the behavior of the --force flag
    Note: The --force flag is useful when the --output directory
    already exists and you want to overwrite the existing output.
    """

    recipe_name = "idle-latency"
    work_dir = path.join(test_work_dir, "force_flag")

    # run asct to generate a csv file
    result = run_asct("run", [recipe_name, "--dev-mode", "--format", "csv"], output_dir=work_dir)
    assert path.exists(f"{path.join(work_dir, recipe_name)}.csv"), "CSV output file was not generated"

    # Run ASCT again using the same output directory without the --force flag.
    # This run is expected to fail.
    with pytest.raises(AssertionError):
        run_asct("run", ["idle-latency", "--dev-mode", "--format", "csv"], output_dir=work_dir)

    # Run ASCT again with the --force flag to the same output directory.
    # This should overwrite the output from the first run.
    result = run_asct("run", ["idle-latency", "--dev-mode", "--format", "csv", "--force"], output_dir=work_dir)
    expected_line = f"Specified output directory '{work_dir}' already exists, some results may be overwritten"
    assert expected_line in result.stderr, "ASCT failed to display warning run message"
