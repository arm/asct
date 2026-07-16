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

import subprocess
import json
import ipaddress
from pathlib import Path

import pytest

# should move this test to the yet-to-be-created lib/networking folder
from asct.lib.networking import network_helpers as nh


def test_extract_addr_and_iter_addrs_dedupes_and_normalizes():
    assert nh._extract_addr("10.0.0.1/24") == "10.0.0.1"
    assert nh._extract_addr({"address": "192.168.0.1/16"}) == "192.168.0.1"
    assert nh._extract_addr({"local": "127.0.0.1"}) == "127.0.0.1"
    assert nh._extract_addr({"addr": "::1/128"}) == "::1"
    assert nh._extract_addr({"ip": "fe80::1"}) == "fe80::1"
    assert nh._extract_addr("\n") is None

    info = {
        "ipv4": [{"address": "10.0.0.1/24"}, {"address": "10.0.0.1/24"}, {"address": "10.0.0.2"}],
        "ipv6": ["::1/128", "::1/128", "fe80::1/64"],
    }
    assert nh._iter_addrs(info, "ipv4") == ["10.0.0.1", "10.0.0.2"]
    assert nh._iter_addrs(info, "ipv6") == ["::1", "fe80::1"]


def test_classify_ipv6():
    assert nh.classify_ipv6("not-an-ip") == "unknown"
    assert nh.classify_ipv6("127.0.0.1") == "not-v6"
    assert nh.classify_ipv6("::1") == "loopback"
    assert nh.classify_ipv6("fe80::1") == "link-local"
    assert nh.classify_ipv6("fd00::1") == "unique-local"


def test_check_port_available_validates_range_and_local_bind(monkeypatch):
    monkeypatch.setattr(nh, "get_local_ip_addresses", lambda: {"ipv4": ["127.0.0.1"]})

    with pytest.raises(ValueError):
        nh.check_port_available("127.0.0.1", port=0)

    # Remote host: treated as available (no bind test)
    assert nh.check_port_available("192.0.2.1", port=5201, local_ips=["127.0.0.1"]) is True

    class FakeSock:
        def __init__(self, *_args, **_kwargs):
            self.bound = None

        def settimeout(self, *_args, **_kwargs):
            return None

        def bind(self, _addr):
            # Simulate a port already in use
            raise OSError("in use")

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(nh.socket, "socket", lambda *_a, **_k: FakeSock())

    # '' and 'localhost' normalize to 127.0.0.1 for local bind test.
    assert nh.check_port_available("", port=5201, local_ips=["127.0.0.1"]) is False
    assert nh.check_port_available("localhost", port=5201, local_ips=["127.0.0.1"]) is False


@pytest.mark.parametrize(
    ("host", "local_ips_v6", "bind_raises", "expected_result"),
    [
        (str(ipaddress.IPv4Address(0)), None, True, False),
        ("::1", ["::1"], False, True),
    ],
)
def test_check_port_available_uses_expected_bind_host(monkeypatch, host, local_ips_v6, bind_raises, expected_result):
    monkeypatch.setattr(nh, "get_local_ip_addresses", lambda: {"ipv4": ["127.0.0.1"], "ipv6": ["::1"]})

    captured = {"bound": None}

    class FakeSock:
        def __init__(self, *_args, **_kwargs):
            pass

        def settimeout(self, *_args, **_kwargs):
            return None

        def bind(self, addr):
            captured["bound"] = addr
            if bind_raises:
                raise OSError("in use")

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(nh.socket, "socket", lambda *_a, **_k: FakeSock())

    kwargs = {"local_ips": ["127.0.0.1"]}
    if local_ips_v6 is not None:
        kwargs["local_ips_v6"] = local_ips_v6

    assert nh.check_port_available(host, port=5201, **kwargs) is expected_result
    assert captured["bound"] == (host, 5201)


def test_is_local_host_resolves_hostname(monkeypatch):
    monkeypatch.setattr(
        nh,
        "get_local_ip_addresses",
        lambda: {"ipv4": ["127.0.0.1", "10.0.0.10"], "ipv6": ["::1"], "aliases": {"hostnames": ["localhost"]}},
    )
    monkeypatch.setattr(
        nh.socket,
        "getaddrinfo",
        lambda *_a, **_k: [
            (nh.socket.AF_INET, None, None, None, ("10.0.0.10", 0)),
        ],
    )

    assert nh.is_local_host("my-hostname.local") is True


def test_normalize_port_value_userspace_toggle_behavior():
    assert nh.normalize_port_value(80, default_port=5201, userspace_only=True) == 5201
    assert nh.normalize_port_value(80, default_port=5201, userspace_only=False) == 80
    assert nh.normalize_port_value(70000, default_port=5201, userspace_only=False) == 5201
    assert nh.normalize_port_value("bad-port", default_port=5201, userspace_only=True) == 5201


def test_resolve_wildcard_host_normalizes_common_tokens():
    assert nh.resolve_wildcard_host("") == nh.LOOPBACK_IPV4
    assert nh.resolve_wildcard_host(nh.LOOPBACK_HOSTNAME) == nh.LOOPBACK_IPV4
    assert nh.resolve_wildcard_host(nh.WILDCARD_IPV4) == nh.WILDCARD_IPV4
    assert nh.resolve_wildcard_host(nh.WILDCARD_IPV6) == nh.WILDCARD_IPV6


def test_interface_port_hints_reads_sysfs(tmp_path, monkeypatch):
    sysfs = tmp_path / "sys" / "class" / "net"
    (sysfs / "eth0").mkdir(parents=True)

    (sysfs / "eth0" / nh.SYSFS_PHYS_PORT_NAME).write_text("p0\n")
    (sysfs / "eth0" / nh.SYSFS_DEV_PORT).write_text("1\n")

    monkeypatch.setattr(nh, "SYSFS_CLASS_NET_DIR", sysfs)

    out = nh.interface_port_hints("eth0")
    assert out["phys_port"] == "p0"
    assert out["dev_port"] == "1"
    assert out["port"] == "p0"


def test_interface_location_classifies_pci_and_usb(monkeypatch):
    monkeypatch.setattr(nh, "_sysfs_iface_device_link", lambda _ifname: Path("/sys/devices/pci0000:00/0000:03:00.0"))
    out = nh.interface_location("eth0")
    assert out["location_type"] == "pci"
    assert "PCI" in out["location"]

    monkeypatch.setattr(
        nh,
        "_sysfs_iface_device_link",
        lambda _ifname: Path("/sys/devices/pci0000:00/0000:00:14.0/usb1/1-2/1-2:1.0"),
    )
    out = nh.interface_location("eth1")
    assert out["location_type"] == "usb"
    assert out["location"].startswith("USB")

    monkeypatch.setattr(nh, "_sysfs_iface_device_link", lambda _ifname: None)
    out = nh.interface_location("lo")
    assert out["location_type"] == "virtual"


def test_decode_interface_mac_derived_and_unknown_pattern(monkeypatch):
    monkeypatch.setattr(
        nh, "interface_location", lambda _ifname: {"location": "virtual", "location_type": "virtual", "sysfs": None}
    )
    monkeypatch.setattr(nh, "interface_port_hints", lambda _ifname: {"phys_port": None, "dev_port": None, "port": None})

    out = nh.decode_interface("enx001122334455")
    assert out["type"] == "Ethernet"
    assert "MAC-derived" in out["description"]

    out2 = nh.decode_interface("")
    assert out2["type"] == "Unknown"
    assert "Unrecognized" in out2["description"]


def test_list_network_namespaces_merges_ip_and_lsns(monkeypatch):
    def fake_which(cmd: str):
        return "/bin/" + cmd

    def fake_run_cmd(cmd: list[str]) -> str:
        if cmd == nh.IP_NETNS_LIST_CMD:
            return "ns1\n"
        if cmd[:1] == ["readlink"]:
            return "net:[4026532000]\n"
        if cmd == nh.LSNS_CMD:
            return "net:[4026532000] /run/netns/ns1 1234 bash\nnet:[4026533000] /proc/1/ns/net 1 init\n"
        raise AssertionError(f"Unexpected cmd: {cmd}")

    monkeypatch.setattr(nh.shutil, "which", fake_which)
    monkeypatch.setattr(nh, "_run_cmd", fake_run_cmd)

    out = nh.list_network_namespaces()
    assert len(out) == 2

    # Deterministic sort: named first
    assert out[0]["name"] == "ns1"
    assert out[0]["ns"] == "net:[4026532000]"
    assert out[1]["name"] is None


def test_list_network_namespaces_handles_readlink_and_stat_failures(monkeypatch):
    monkeypatch.setattr(nh.shutil, "which", lambda cmd: "/bin/" + cmd if cmd in {"ip", "readlink"} else None)

    def fake_run_cmd(cmd: list[str]) -> str:
        if cmd == nh.IP_NETNS_LIST_CMD:
            return "ns1\n"
        raise OSError("readlink failed")

    monkeypatch.setattr(nh, "_run_cmd", fake_run_cmd)

    out = nh.list_network_namespaces()
    assert out == [{"ns": None, "name": "ns1", "path": "/run/netns/ns1", "pid": None, "command": None}]


def test_list_network_namespaces_handles_ip_enumeration_failure(monkeypatch):
    monkeypatch.setattr(nh.shutil, "which", lambda cmd: "/bin/" + cmd if cmd == "ip" else None)
    monkeypatch.setattr(nh, "_run_cmd", lambda _cmd: (_ for _ in ()).throw(OSError("ip failed")))

    assert nh.list_network_namespaces() == []


def test_get_ip_addr_in_namespace_handles_errors(monkeypatch):
    # ip missing -> hard failure
    monkeypatch.setattr(nh.shutil, "which", lambda cmd: None if cmd == "ip" else "/bin/" + cmd)
    with pytest.raises(FileNotFoundError):
        nh.get_ip_addr_in_namespace({"name": "ns1"})

    # ip present; CalledProcessError -> returns empty + error when requested
    monkeypatch.setattr(nh.shutil, "which", lambda cmd: "/bin/" + cmd)

    def raise_cpe(_cmd):
        raise subprocess.CalledProcessError(1, _cmd, stderr="nope")

    monkeypatch.setattr(nh, "_run_cmd", raise_cpe)

    parsed, err = nh.get_ip_addr_in_namespace({"name": "ns1"}, return_error=True)
    assert parsed == {}
    assert err == "nope"

    monkeypatch.setattr(nh, "_run_cmd", lambda _cmd: (_ for _ in ()).throw(OSError("namespace gone")))
    parsed, err = nh.get_ip_addr_in_namespace({"name": "ns1"}, return_error=True)
    assert parsed == {}
    assert err == "namespace gone"


def test_parse_ip_details_addr_and_ifconfig_backend(monkeypatch):
    ip_out = json.dumps([
        {
            "ifindex": 1,
            "ifname": "lo",
            "flags": ["LOOPBACK", "UP", "LOWER_UP"],
            "mtu": 65536,
            "operstate": "UNKNOWN",
            "link_type": "loopback",
            "address": "00:00:00:00:00:00",
            "addr_info": [
                {"family": "inet", "local": "127.0.0.1", "prefixlen": 8, "scope": "host"},
                {"family": "inet6", "local": "::1", "prefixlen": 128, "scope": "host"},
            ],
        }
    ])
    parsed = nh._parse_ip_details_addr(ip_out)
    assert parsed["lo"]["mac"] == "00:00:00:00:00:00"
    assert parsed["lo"]["admin_up"] is True
    assert parsed["lo"]["carrier_up"] is True
    assert parsed["lo"]["ipv4"][0]["address"] == "127.0.0.1"
    assert parsed["lo"]["ipv6"][0]["address"] == "::1"

    # ifconfig backend: parse continuation lines with spaces and infer state
    monkeypatch.setattr(nh.shutil, "which", lambda _cmd: "/bin/" + _cmd)

    ifconfig_out = (
        "eth0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500\n"
        "    ether aa:bb:cc:dd:ee:ff\n"
        "    inet 10.0.0.2  netmask 255.255.255.0\n"
        "    inet6 fe80::1  prefixlen 64\n"
    )

    monkeypatch.setattr(nh, "_run_cmd", lambda _cmd: ifconfig_out)
    out = nh._get_ip_addr_ifconfig()
    assert out["eth0"]["mac"] == "aa:bb:cc:dd:ee:ff"
    assert out["eth0"]["ipv4"][0]["address"] == "10.0.0.2"
    assert out["eth0"]["ipv6"][0]["address"] == "fe80::1"
    assert out["eth0"]["state"] == "UP"


def test_get_ip_addr_falls_back_and_all_interface_ips_filters(monkeypatch):
    monkeypatch.setattr(nh, "_get_ip_addr_linux", lambda: (_ for _ in ()).throw(FileNotFoundError("no ip")))
    monkeypatch.setattr(
        nh,
        "_get_ip_addr_ifconfig",
        lambda: {
            "lo": {"ipv4": [{"address": "127.0.0.1"}], "ipv6": [{"address": "::1"}]},
            "eth0": {"ipv4": [{"address": "10.0.0.2"}], "ipv6": [{"address": "fe80::1"}]},
        },
    )

    m = nh.get_ip_addr()
    assert "eth0" in m

    ips = nh.all_interface_ips(include_loopback=False)
    assert "lo" not in ips
    assert ips["eth0"]["ipv4"] == ["10.0.0.2"]
    assert ips["eth0"]["ipv6"] == ["fe80::1"]
