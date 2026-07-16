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

import asct.core.logger as log
from asct.core.resources.resource_base import Resource
from asct.core.datatypes import ASCTSingleton


class CheckParanoidLevel(Resource, metaclass=ASCTSingleton):
    PERF_EVENT_PARANOID_PATH = "/proc/sys/kernel/perf_event_paranoid"

    def __init__(self, max_required):
        super().__init__()
        self._max_required_level = max_required
        self._level = self._get_current_level()

    def _get_current_level(self):
        try:
            return int(self._get_sysfile_value(self.PERF_EVENT_PARANOID_PATH))
        except (OSError, ValueError, TypeError) as exc:
            log.error(f"Unable to get perf_event_paranoid level: {exc}")
        return -1

    def setup(self):
        """Check if running paranoid level is correct. Raise RuntimeError if not."""
        if self._level > self._max_required_level:
            raise RuntimeError(
                "/proc/sys/kernel/perf_event_paranoid has to be set to a value <= "
                f"{self._max_required_level}, current value: {self._level}"
            )
        return True

    def teardown(self):
        pass
