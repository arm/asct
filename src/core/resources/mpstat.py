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

from asct.core.resources.ext_tool import ExternalToolResource
import subprocess


class Mpstat(ExternalToolResource):
    def __init__(self):
        """
        This Singleton class checks the availability of the 'mpstat' command-line utility,
        it is a singleton to ensure that the check is performed only once during the
        lifetime of an ASCT run.
        """
        super().__init__("mpstat")

    def get_tool_version(self):
        return subprocess.run(
            [self.tool_name, "-V"],
            text=True,
            capture_output=True,
            check=False,
        )
