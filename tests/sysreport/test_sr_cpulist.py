# ---------------------------------------------------------------------------------
# SPDX-FileCopyrightText: Copyright (C) 2026 Arm Limited and/or its affiliates
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

from types import SimpleNamespace

from asct.lib.sysreport.sr_cpulist import System


def test_cache_level_max_returns_highest_cache_level(monkeypatch):
    monkeypatch.setattr(System, "discover", lambda _: None)

    system = System()
    system.caches_by_key = {
        "l1": SimpleNamespace(level=1),
        "l3": SimpleNamespace(level=3),
        "l2": SimpleNamespace(level=2),
    }

    assert system.cache_level_max() == 3
