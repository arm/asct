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

from asct.core import logger as log
from asct.core.cmn.cmn_api import cmn_lock_unlock_registers
from asct.core.resources.resource_base import Resource


CMN_MEMAP_ENV_VAR = "CMN_MEMAP"


class CMNSecureAccess(Resource):
    def __init__(self, node_type: str = "all"):
        super().__init__()
        self.node_type = node_type
        self._unlocked = False
        self._done = False

    def _check_cmn_memap(self):
        cmn_memap = os.environ.get(CMN_MEMAP_ENV_VAR)
        if not cmn_memap:
            raise RuntimeError("CMN secure access is not available in this environment")

    def setup(self):

        self._check_cmn_memap()

        try:
            # attempt to unlock the CMN registers, ensuring we will attempt
            # to relock them if unlocking fails
            cmn_lock_unlock_registers(node_type=self.node_type, lock=False)
        except Exception:
            # If unlocking fails, ensure we attempt to relock any registers that
            # may have been unlocked before the failure occurred.
            try:
                cmn_lock_unlock_registers(node_type=self.node_type, lock=True)
            except Exception as exc:  # ruff:ignore[blind-except]
                log.warning(f"Failed to relock CMN registers after unlock failure: {exc}")
            raise

        self._unlocked = True
        return True

    def teardown(self):
        # If the registers were not successfully unlocked,
        # there is no need to attempt to relock them.
        if not self._unlocked:
            log.debug("CMN registers were not unlocked, skipping relock attempt.")
            return

        cmn_lock_unlock_registers(node_type=self.node_type, lock=True)

        self._unlocked = False
