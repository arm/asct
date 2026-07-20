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

from asct.core.utility.misc import flatten_dict


def test_flatten_dict_unrolls_lists_of_dicts_and_scalars():
    data = {
        "network": {
            "net_ns": [
                {"name": "ns0", "pid": 1},
                {"name": "ns1", "pid": 2},
            ],
            "local_ipv6": ["::1", "fe80::1"],
        },
    }

    assert flatten_dict(data) == {
        "network.net_ns.0.name": "ns0",
        "network.net_ns.0.pid": 1,
        "network.net_ns.1.name": "ns1",
        "network.net_ns.1.pid": 2,
        "network.local_ipv6.0": "::1",
        "network.local_ipv6.1": "fe80::1",
    }
