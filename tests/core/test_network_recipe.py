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

from __future__ import annotations

from asct.core.recipes.configuration.metadata import ASCT_RECIPE_METADATA, get_recipe
from asct.core.recipes.impl import network as net


def test_network_info_short_name_is_netinfo():
    assert get_recipe("netinfo", ASCT_RECIPE_METADATA).name == "network-info"


def test_network_dataclasses_handle_expected_collection_errors(monkeypatch):
    monkeypatch.setattr(net, "decode_interface", lambda _ifname: (_ for _ in ()).throw(OSError("bad sysfs")))

    dev = net.network_dev(ifname="eth0", info={})
    assert dev.name is None
    assert "type=Unknown" in dev.format()
    assert "(no IP addresses)" in dev.format()

    monkeypatch.setattr(
        net,
        "get_ip_addr_in_namespace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("ns gone")),
    )
    ns = net.network_ns(ns_info={"name": "ns1", "pid": 42, "command": "bash"})
    assert ns.error == "ns gone"
    assert "unable to be inspected: ns gone" in ns.format()

    monkeypatch.setattr(net, "get_local_ip_addresses", lambda: (_ for _ in ()).throw(OSError("no resolver")))
    local = net.network_local()
    assert local.local_ipv4 == []
    assert "Local IPv4:" in local.format()


def test_network_dev_friendly_type_and_ipv6_formatting(monkeypatch):
    # Validate the user-facing formatting logic for a network device, including:
    #  - friendly interface type mapping (e.g. docker bridge)
    #  - IPv6 classification annotations in formatted output
    monkeypatch.setattr(
        net,
        "decode_interface",
        lambda _ifname: {"type": "Ethernet", "bus": 3, "slot": 0, "port": 0, "description": "x", "location": "PCI"},
    )

    def fake_classify(addr: str) -> str:
        if addr.startswith("fe80:"):
            return "link-local"
        if addr == "::1":
            return "loopback"
        return "global"

    monkeypatch.setattr(net, "classify_ipv6", fake_classify)

    dev = net.network_dev(
        ifname="docker0",
        info={
            "mac": "aa:bb",
            "state": "UP",
            "admin_up": True,
            "carrier_up": True,
            "mtu": 1500,
            "flags": ["UP"],
            "ipv4": [{"address": "172.17.0.1"}],
            "ipv6": [{"address": "fe80::1"}, {"address": "::1"}],
        },
    )

    assert dev._iface_friendly_type() == "Docker bridge"
    s = dev.format()
    assert "IPv6:" in s
    # Check for IPv6 classification in the formatted output
    assert "(link-local" in s
    assert "(loopback" in s


def test_network_local_wrapping(monkeypatch):
    # Long alias values should wrap across multiple lines so stdout output stays readable.
    monkeypatch.setattr(
        net,
        "get_local_ip_addresses",
        lambda: {"ipv4": ["10.0.0.1"], "ipv6": [], "aliases": {"hostnames": ["a" * 120, "b" * 120]}},
    )

    nl = net.network_local()
    out = nl.format()
    # Should wrap long aliases over multiple lines
    assert "Aliases:" in out
    assert "\n" in out


def test_network_info_run_function_and_format_notes(monkeypatch):
    # Exercise NetworkInfo end-to-end (run_function + format) with fully mocked
    # data sources so the test doesn't depend on host networking.
    monkeypatch.setattr(
        net, "get_local_ip_addresses", lambda: {"ipv4": ["10.0.0.1"], "ipv6": ["fe80::1"], "aliases": {}}
    )
    monkeypatch.setattr(
        net,
        "get_ip_addr",
        lambda: {
            "eth0": {
                "mac": "aa:bb:cc:dd:ee:ff",
                "state": "UP",
                "admin_up": True,
                "carrier_up": True,
                "mtu": 1500,
                "flags": ["UP"],
                "ipv4": [{"address": "10.0.0.2"}],
                "ipv6": [{"address": "fe80::1"}],
            }
        },
    )
    monkeypatch.setattr(
        net, "list_network_namespaces", lambda: [{"name": "ns1", "ns": "net:[1]", "pid": None, "command": None}]
    )
    monkeypatch.setattr(
        net, "get_ip_addr_in_namespace", lambda _ns, return_error=False: ({}, "needs sudo") if return_error else {}
    )
    monkeypatch.setattr(
        net,
        "decode_interface",
        lambda _ifname: {"type": "Ethernet", "location": "PCI", "port": None, "bus": None, "slot": None},
    )
    monkeypatch.setattr(net, "classify_ipv6", lambda a: "link-local" if a.startswith("fe80") else "unknown")

    ni = net.NetworkInfo(get_recipe("network-info", ASCT_RECIPE_METADATA))
    out_recipe = ni.run_function()
    assert out_recipe is ni
    assert isinstance(ni.to_dict(), dict)
    assert ni.net_dev
    assert ni.net_ns

    out = ni.format()
    # Formatting should include section headers and informational notes.
    assert "Interfaces:" in out
    assert "Namespaces:" in out
    assert "Note:" in out
    assert "No globally-routable IPv6 address detected" in out
    assert "Link-local" in out
    assert "Some namespaces" in out


def test_network_info_to_dict_and_to_csv_str(monkeypatch):
    # Smoke-test serialization helpers used by JSON and CSV formatters.
    monkeypatch.setattr(
        net,
        "get_local_ip_addresses",
        lambda: {"ipv4": ["10.0.0.1"], "ipv6": [], "aliases": {"hostnames": ["localhost"]}},
    )
    monkeypatch.setattr(net, "get_ip_addr", dict)
    monkeypatch.setattr(net, "list_network_namespaces", list)

    ni = net.NetworkInfo(get_recipe("network-info", ASCT_RECIPE_METADATA))
    ni.run_function()

    d = ni.to_dict()
    assert "net_local" in d

    csv = ni.to_csv_str()
    assert isinstance(csv, str)
    assert csv


def test_network_info_run_function_handles_best_effort_failures(monkeypatch):
    net.NetworkInfo._inst = None

    class BrokenLocal:
        def __init__(self):
            raise ValueError("local failed")

    monkeypatch.setattr(net, "network_local", BrokenLocal)
    monkeypatch.setattr(net, "get_ip_addr", lambda: (_ for _ in ()).throw(OSError("ip failed")))
    monkeypatch.setattr(net, "list_network_namespaces", lambda: (_ for _ in ()).throw(AttributeError("lsns failed")))

    ni = net.NetworkInfo(get_recipe("network-info", ASCT_RECIPE_METADATA))

    assert ni.run_function() is ni
    assert ni.net_dev == []
    assert ni.net_ns == []
    assert "Interfaces:" in ni.format()
    assert "(no interfaces detected)" in ni.format()

    net.NetworkInfo._inst = None


def test_network_info_serialize_after_run_and_deserialize_uses_recipe_result(monkeypatch):
    monkeypatch.setattr(
        net,
        "get_local_ip_addresses",
        lambda: {"ipv4": ["10.0.0.1"], "ipv6": [], "aliases": {"hostnames": ["localhost"]}},
    )
    monkeypatch.setattr(net, "get_ip_addr", dict)
    monkeypatch.setattr(net, "list_network_namespaces", list)

    ni = net.NetworkInfo(get_recipe("network-info", ASCT_RECIPE_METADATA))
    ni.run()

    serialized = ni.serialize()

    assert serialized["metadata"]["result_desc"] == ni.desc

    ni2 = net.NetworkInfo(get_recipe("network-info", ASCT_RECIPE_METADATA))
    ni2.deserialize(serialized)

    assert ni2.result is ni2
    assert ni2.to_dict() == serialized["raw_result"]


def test_network_info_format_uses_deserialized_raw_data():
    ni = net.NetworkInfo(get_recipe("network", ASCT_RECIPE_METADATA))
    ni.deserialize({
        "raw_result": {
            "net_local": {
                "local_ipv4": ["10.0.0.1"],
                "local_ipv6": ["fe80::1"],
                "aliases": {"hostnames": ["localhost"]},
            },
            "net_dev": [
                {
                    "name": "eth0",
                    "mac": "aa:bb:cc:dd:ee:ff",
                    "state": "UP",
                    "admin_up": True,
                    "carrier_up": True,
                    "mtu": 1500,
                    "flags": ["UP"],
                    "ipv4": ["10.0.0.2"],
                    "ipv6": ["fe80::1"],
                    "type": "Ethernet",
                    "location": "PCI",
                    "port": "p0",
                }
            ],
            "net_ns": [
                {
                    "name": "ns1",
                    "ns": "net:[1]",
                    "pid": 1,
                    "command": "/sbin/init",
                    "devices": [
                        {
                            "name": "eth0",
                            "mac": "aa:bb:cc:dd:ee:ff",
                            "ipv4": ["10.0.0.2"],
                            "ipv6": ["fe80::1"],
                            "type": "Ethernet",
                        }
                    ],
                }
            ],
        }
    })

    out = ni.format()
    assert "Local IPv4:" in out
    assert "eth0: type=Ethernet" in out
    assert "Namespaces:" in out
    assert "Namespace ns1" in out
