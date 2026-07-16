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

from os import path
from .utils import run_asct


def test_default_log_to_file(test_work_dir):
    """
    Validate default asct log to file
    """
    work_dir = path.join(test_work_dir, "log_files")

    log_file = path.join(work_dir, "asct.log")

    run_asct("run", ["idle-latency", "--dev-mode"], output_dir=work_dir)

    assert path.exists(log_file), "asct.log not found"

    # file may not be empty in this scenario
    assert path.getsize(log_file) > 0, "asct.log is empty"
