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
import asct.core.logger as log
from asct.core.resources.resource_base import Resource
from asct.core.datatypes import ASCTSingleton


class CheckSudo(Resource, metaclass=ASCTSingleton):
    def __init__(self):
        super().__init__()
        self._is_sudo = os.geteuid() == 0

    def setup(self):
        """Check if running as root. Raise RuntimeError if not."""
        if self._is_sudo:
            log.debug("Running with sudo/root privileges.")
        else:
            error = "sudo/root is required for this operation - please re-run as root or with sudo"
            log.debug(error)
            raise RuntimeError(error)
        return True

    def teardown(self):
        """
        Nothing to clean up here.
        """
        log.debug("tearing down CheckSudo")
