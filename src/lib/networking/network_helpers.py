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

"""Network-related discovery and utility functions.

Sections:
    - Sysfs interface metadata
    - Address parsing helpers
    - Command helpers
    - IP classification
    - Local host discovery
    - Port utilities
    - Interface name decoding
    - Network namespaces
    - Interface address discovery (ip/ifconfig)
    - Parsers
    - Convenience APIs
"""

from __future__ import annotations

import socket
import ipaddress
import re
import subprocess
import shutil

from pathlib import Path
from typing import Any

import asct.core.logger as log
from asct.core.utility.files import read_json_stdout


###################################################################################################
# Constants
###################################################################################################

# Outbound probe target used to infer primary egress IPv4
OUTBOUND_PROBE_IPV4 = "8.8.8.8"
OUTBOUND_PROBE_PORT = 80

# Loopback aliases
LOOPBACK_IPV4 = "127.0.0.1"
LOOPBACK_IPV6 = "::1"
LOOPBACK_HOSTNAME = "localhost"
WILDCARD_IPV4 = str(ipaddress.IPv4Address(0))
WILDCARD_IPV6 = str(ipaddress.IPv6Address(0))

# Socket bind/probe timeout (seconds)
DEFAULT_BIND_TIMEOUT_S = 0.2

# Port sanity bounds
MIN_PORT = 1
MAX_PORT = 65535
USERSPACE_PORT_MIN = 1024

# Common defaults
DEFAULT_IPERF3_PORT = 5201
# Max UDP payload size for IPv4 datagrams (65535 - 8 byte UDP header - 20 byte IPv4 header).
IPERF3_MAX_UDP_PAYLOAD_BYTES = 65507

# Commands used for interface discovery
LINUX_IP_CMD = ["ip", "-details", "-json", "addr"]
IFCONFIG_CMD = ["ifconfig"]
LSNS_CMD = ["lsns", "-t", "net", "-o", "NS,PATH,PID,COMMAND", "--noheadings"]

# Other command argument lists (kept as constants to avoid duplication)
IP_NETNS_LIST_CMD = ["ip", "netns", "list"]
READLINK_CMD = ["readlink"]

# Predictable interface name decoding
IFACE_PREFIX_TYPE_MAP = {"en": "Ethernet", "wl": "Wireless", "ww": "WWAN", "lo": "Loopback"}
REGEX_MAC_DERIVED = r"^(?P<prefix>en|wl)x(?P<mac>[0-9a-fA-F]{12})$"
REGEX_PCI_FORMS = (
    r"^(?P<prefix>[a-z]+)"
    r"(?:(?:P|p)(?P<bus>\d+))?"
    r"(?:(?:p)(?P<slot>\d+))?"
    r"(?:(?:s)(?P<port>\d+))?"
    r".*$"
)
LINK_LOCAL_PREFIX = "fe80:"

# Sysfs helpers
SYSFS_CLASS_NET_DIR = Path("/sys/class/net")
SYSFS_DEVICE_ENTRY = "device"
VIRTUAL_SYSFS_SUBPATH = "/devices/virtual/"

# Regex helpers
PCI_BDF_REGEX = r"\b[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7]\b"
USB_ID_REGEX = r"\b\d-\d(?:\.\d+)*:\d\.\d\b"
USB_SYSFS_HINTS = ("/usb", "usb")

# Sysfs port hint files (best-effort; may not exist for many devices)
SYSFS_PHYS_PORT_NAME = "phys_port_name"
SYSFS_DEV_PORT = "dev_port"

###################################################################################################
# Sysfs Interface Metadata
###################################################################################################


def _sysfs_iface_device_link(ifname: str) -> Path | None:
    """
    Return the resolved /sys device path for an interface (best-effort).
    For many virtual interfaces (lo, docker0, virbr0, etc.), /device may be missing.
    """
    try:
        p = SYSFS_CLASS_NET_DIR / ifname / SYSFS_DEVICE_ENTRY
        if not p.exists():
            return None
        # resolve() follows symlinks; gives us the real device path
        return p.resolve()
    except OSError:
        return None


def interface_location(ifname: str) -> dict[str, Any]:
    """
    Best-effort location classification using sysfs.

    Returns:
      {
        "location": "PCI 0000:03:00.0" | "USB 1-2:1.0" | "virtual" | "unknown",
        "location_type": "pci" | "usb" | "virtual" | "unknown",
        "sysfs": "/sys/devices/...." | None,
      }
    """

    def _pci_location(sysfs_path: str) -> dict[str, Any] | None:
        # PCI NICs usually have a stable BDF like 0000:03:00.0 somewhere in the path
        bdfs = re.findall(PCI_BDF_REGEX, sysfs_path)
        # Heuristic: the *last* BDF in the path is usually the endpoint function for the netdev.
        bdf = bdfs[-1] if bdfs else None
        if "pci" not in sysfs_path and not bdf:
            return None

        loc = f"PCI {bdf}" if bdf else "PCI"
        out: dict[str, Any] = {"location": loc, "location_type": "pci", "sysfs": sysfs_path}
        if bdf:
            # also provide structured parts for debugging/reporting
            try:
                dom, bus, devfn = bdf.split(":")
                dev, fn = devfn.split(".")
                out.update({"pci_domain": dom, "pci_bus": bus, "pci_device": dev, "pci_function": fn})
            except ValueError:
                log.debug(f"Failed to parse PCI BDF components from {bdf}")
        return out

    def _usb_location(sysfs_path: str) -> dict[str, Any] | None:
        # USB NICs typically sit under .../usb... in sysfs
        if not any(hint in sysfs_path for hint in USB_SYSFS_HINTS):
            return None

        # Try to grab a compact-ish USB identifier like "1-2:1.0" if present
        m_usb = re.search(USB_ID_REGEX, sysfs_path)
        usb_id = m_usb.group(0) if m_usb else None
        loc = f"USB {usb_id}" if usb_id else "USB"
        return {"location": loc, "location_type": "usb", "sysfs": sysfs_path}

    def _virtual_location(sysfs_path: str) -> dict[str, Any] | None:
        # Virtio can show up without "pci" in the path depending on setup,
        # but usually still looks "devices/virtual/..." or has no device.
        if VIRTUAL_SYSFS_SUBPATH not in sysfs_path:
            return None
        return {"location": "virtual", "location_type": "virtual", "sysfs": sysfs_path}

    def _classify_sysfs_path(sysfs_path: str) -> dict[str, Any]:
        # Prefer USB over PCI when both hints exist in the sysfs path.
        # USB NICs often sit behind a PCI root/hub path, so we want the label to
        # reflect the NIC's attachment point.
        for classifier in (_usb_location, _pci_location, _virtual_location):
            out = classifier(sysfs_path)
            if out is not None:
                return out
        return {"location": "unknown", "location_type": "unknown", "sysfs": sysfs_path}

    sysfs = _sysfs_iface_device_link(ifname)
    sysfs_str = str(sysfs) if sysfs is not None else None

    # Most virtual interfaces have no "device" entry
    # (lo, bridges, veth*, docker0, virbr0, etc.)
    out = {"location": "virtual", "location_type": "virtual", "sysfs": None}
    if sysfs_str:
        out = _classify_sysfs_path(sysfs_str)
    return out


def interface_port_hints(ifname: str) -> dict[str, Any]:
    """
    Best-effort port discovery for a netdev using sysfs.

    Useful for multi-port NICs and SR-IOV-ish setups where "which port is this?"
    matters more than humans want to admit.

    Returns:
      {
        "phys_port": "p0" | "p1" | "pf0vf3" | ... | None,
        "dev_port": "0" | "1" | ... | None,
        "port": <best single display token> | None
      }
    """
    base = SYSFS_CLASS_NET_DIR / ifname
    phys_port: str | None = None
    dev_port: str | None = None

    try:
        p = base / SYSFS_PHYS_PORT_NAME
        if p.exists():
            phys_port = p.read_text(errors="ignore").strip() or None
    except OSError:
        phys_port = None

    try:
        p = base / SYSFS_DEV_PORT
        if p.exists():
            dev_port = p.read_text(errors="ignore").strip() or None
    except OSError:
        dev_port = None

    # "port" is the single, human-facing hint:
    # prefer phys_port_name (usually meaningful), else dev_port (numeric-ish).
    port = phys_port or dev_port

    return {"phys_port": phys_port, "dev_port": dev_port, "port": port}


###################################################################################################
# Address Parsing Helpers
###################################################################################################


def _extract_addr(entry: Any) -> str | None:
    """
    Extract an IP address from a dict-like entry or string.
    Normalizes "10.0.0.1/24" -> "10.0.0.1".
    """
    if isinstance(entry, str):
        s = entry.strip()
        if not s:
            return None
        return s.split("/", 1)[0]

    if isinstance(entry, dict):
        for k in ("address", "local", "addr", "ip"):
            v = entry.get(k)
            if isinstance(v, str) and v.strip():
                s = v.strip()
                return s.split("/", 1)[0]

    return None


def _iter_addrs(info: dict[str, Any], fam: str) -> list[str]:
    """
    Return a de-duplicated list of addresses for fam in ("ipv4", "ipv6")
    from a parsed interface info dict.
    """
    out: list[str] = []
    for e in info.get(fam, []) or []:
        a = _extract_addr(e)
        if a:
            out.append(a)

    # De-dupe while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for a in out:
        if a not in seen:
            seen.add(a)
            uniq.append(a)
    return uniq


###################################################################################################
# Command Helpers
###################################################################################################


def _run_cmd(cmd: list[str]) -> str:
    """Run a command and return stdout (best-effort; raises on hard failures)."""
    r = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return r.stdout or ""


###################################################################################################
# IP Classification
###################################################################################################


def classify_ipv6(addr: str) -> str:
    """
    Return a short human label for an IPv6 address.
    """
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return "unknown"

    if ip.version != 6:
        return "not-v6"
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link-local"
    if ip.is_private:
        # For IPv6, this covers ULA (fc00::/7) in practice
        return "unique-local"
    if ip.is_global:
        return "global"
    return "other"


###################################################################################################
# Local Host Discovery
###################################################################################################


def get_local_ip_addresses() -> dict[str, Any]:
    """Discover local IP addresses and return a mapping.
    Returns:
      {
        "ipv4": [...],
        "ipv6": [...],
        "aliases": {"hostnames": [...]}
      }
    """

    def _outbound_primary_ip() -> str | None:
        # UDP connect does not send traffic here; it asks the kernel which
        # source address it would use for outbound IPv4.
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(DEFAULT_BIND_TIMEOUT_S)
                sock.connect((OUTBOUND_PROBE_IPV4, OUTBOUND_PROBE_PORT))
                return sock.getsockname()[0]
        except OSError:
            return None

    hostname = socket.gethostname()
    addrs: set[str] = {LOOPBACK_IPV4, LOOPBACK_IPV6}

    try:
        # Hostname resolution can include addresses not present in interface
        # output (for example container host aliases), so keep both sources.
        for info in socket.getaddrinfo(hostname, None):
            if info[0] in (socket.AF_INET, socket.AF_INET6):
                addrs.add(info[4][0])
    except OSError as exc:
        log.debug(f"Failed to get local IP addresses: {exc}")

    primary = _outbound_primary_ip()
    if primary:
        addrs.add(primary)

    # pull interface IPv4/IPv6 too (best-effort).
    try:
        iface_map = get_ip_addr()
        for info in iface_map.values():
            addrs.update(_iter_addrs(info, "ipv4"))
            addrs.update(_iter_addrs(info, "ipv6"))
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError) as exc:
        log.debug(f"Failed to merge interface IPs into local IP list: {exc}")

    v4: list[str] = []
    v6: list[str] = []
    # Normalize and classify discovered strings into stable IPv4/IPv6 lists.
    for addr_str in addrs:
        if not addr_str:
            continue
        try:
            ip_obj = ipaddress.ip_address(addr_str)
        except ValueError:
            continue
        (v4 if ip_obj.version == 4 else v6).append(addr_str)

    v4.sort()
    v6.sort()

    aliases = {"hostnames": [LOOPBACK_HOSTNAME]}
    log.debug(f"Discovered local IPv4 addresses: {', '.join(v4)}")
    log.debug(f"Discovered local IPv6 addresses: {', '.join(v6)}")
    log.debug(f"Discovered local aliases: {', '.join(aliases['hostnames'])}")
    return {"ipv4": v4, "ipv6": v6, "aliases": aliases}


###################################################################################################
# Port Utilities
###################################################################################################


def check_port_value(
    port: Any,
    *,
    userspace_only: bool = False,
    raise_on_error: bool = False,
) -> int | None:
    """Return a valid port number, or None when the requested value is invalid."""
    try:
        port = int(port)
    except (TypeError, ValueError) as exc:
        if raise_on_error:
            raise ValueError(f"invalid port: {port}") from exc
        return None

    min_port = USERSPACE_PORT_MIN if userspace_only else MIN_PORT
    if min_port <= port <= MAX_PORT:
        return port

    if raise_on_error:
        raise ValueError(f"invalid port: {port}")
    return None


def normalize_port_value(
    port: Any,
    *,
    default_port: int = DEFAULT_IPERF3_PORT,
    userspace_only: bool = False,
    context: str = "port",
) -> int:
    """Return a normalized port, or default_port when input is invalid/out of range.

    If userspace_only is True, allowed range is USERSPACE_PORT_MIN-MAX_PORT.
    Otherwise, allowed range is MIN_PORT-MAX_PORT.
    """
    normalized = check_port_value(port, userspace_only=userspace_only)
    if normalized is not None:
        return normalized

    min_port = USERSPACE_PORT_MIN if userspace_only else MIN_PORT
    range_label = "userspace" if userspace_only else "full"
    log.warning(
        "%s '%s' is invalid for the allowed %s port range %s-%s; using default port %s",
        context,
        port,
        range_label,
        min_port,
        MAX_PORT,
        default_port,
    )
    return default_port


def is_local_host(
    host: str,
    local_ipv4: list[str] | None = None,
    local_ipv6: list[str] | None = None,
    aliases: list[str] | None = None,
) -> bool:
    """Return True if host resolves to a local address/alias."""
    # Cache-free by design: network state can change between calls.
    local_data = get_local_ip_addresses()
    local_ipv4 = local_ipv4 if local_ipv4 is not None else local_data.get("ipv4", [])
    local_ipv6 = local_ipv6 if local_ipv6 is not None else local_data.get("ipv6", [])
    aliases = aliases if aliases is not None else local_data.get("aliases", {}).get("hostnames", [LOOPBACK_HOSTNAME])

    test_host = host.strip() if isinstance(host, str) else str(host)
    # Empty is treated as local so callers can use default-host semantics.
    if not test_host:
        return True
    if test_host.lower() in {str(a).strip().lower() for a in aliases}:
        return True

    try:
        # Fast path for literal IP addresses.
        ip_obj = ipaddress.ip_address(test_host)
        if ip_obj.version == 4:
            return str(ip_obj) in set(local_ipv4) or ip_obj.is_loopback
        return str(ip_obj) in set(local_ipv6) or ip_obj.is_loopback
    except ValueError:
        pass

    try:
        # Hostname/FQDN path: resolve and compare against local inventories.
        resolved = {info[4][0] for info in socket.getaddrinfo(test_host, None, family=socket.AF_UNSPEC)}
    except OSError as exc:
        log.debug(f"Failed to resolve host '{test_host}' for local host check: {exc}")
        return False

    local_set = set(local_ipv4) | set(local_ipv6)
    return any(addr in local_set for addr in resolved)


def resolve_wildcard_host(host: Any, default_host: str = LOOPBACK_IPV4) -> str:
    """Normalize empty/localhost/wildcard host tokens to stable bind/check hosts."""
    test_host = host.strip() if isinstance(host, str) else str(host)
    if not test_host:
        return default_host

    lowered = test_host.lower()
    if lowered == LOOPBACK_HOSTNAME:
        return LOOPBACK_IPV4

    if test_host == str(ipaddress.IPv4Address(0)):
        return WILDCARD_IPV4
    if test_host == str(ipaddress.IPv6Address(0)):
        return WILDCARD_IPV6

    return test_host


def check_port_available(
    host: str,
    port: int = DEFAULT_IPERF3_PORT,
    local_ips: list[str] | None = None,
    local_ips_v6: list[str] | None = None,
) -> bool:
    """Return True if port is free for bind test on given host (local only), else False.
    Remote hosts (not in local_ips) are skipped (treated as available). Host aliases
    '' / 'localhost' map to 127.0.0.1.
    Note: Specific recipes may enforce stricter port ranges (e.g., >=1024).
    """
    local_data = get_local_ip_addresses()
    if local_ips is None:
        local_ips = local_data.get("ipv4", [])
    if local_ips_v6 is None:
        local_ips_v6 = local_data.get("ipv6", [])
    local_aliases = local_data.get("aliases", {}).get("hostnames", [LOOPBACK_HOSTNAME])
    if not isinstance(port, int) or port < MIN_PORT or port > MAX_PORT:
        raise ValueError(f"Port {port} out of valid range {MIN_PORT}-{MAX_PORT}")
    # Normalize host tokens and resolve hostnames to decide if "local enough" to bind-test.
    test_host = resolve_wildcard_host(host)

    if test_host in (WILDCARD_IPV4, WILDCARD_IPV6):
        # Wildcard binds are always local checks.
        is_local = True
    else:
        is_local = is_local_host(
            test_host,
            local_ipv4=local_ips,
            local_ipv6=local_ips_v6,
            aliases=local_aliases,
        )

    # Not checking remote hosts (best-effort behavior).
    if not is_local:
        return True

    bind_family = socket.AF_INET
    try:
        # Select address family from normalized host when possible.
        ip_obj = ipaddress.ip_address(test_host)
        bind_family = socket.AF_INET6 if ip_obj.version == 6 else socket.AF_INET
    except ValueError:
        if test_host == WILDCARD_IPV6:
            bind_family = socket.AF_INET6

    if test_host == WILDCARD_IPV6:
        # Keep wildcard overrides explicit for readability.
        bind_family = socket.AF_INET6
    elif test_host == WILDCARD_IPV4:
        bind_family = socket.AF_INET

    try:
        with socket.socket(bind_family, socket.SOCK_STREAM) as sock:
            sock.settimeout(DEFAULT_BIND_TIMEOUT_S)
            sock.bind((test_host, port))
        return True
    except OSError:
        return False


###################################################################################################
# Interface Name Decoding
###################################################################################################


def decode_interface(interface_name: str) -> dict[str, Any]:
    """Decode a Linux predictable network interface name (e.g. enP3p5s0) into a dict.
    Returns a dictionary with keys:
      interface: original name
      type: inferred interface family (Ethernet/Wireless/WWAN/Loopback/Unknown)
      bus: PCI bus number (int or None)
      slot: PCI slot number (int or None)
      port: physical/function port number (int or None)
      description: human readable string
    """
    # Common predictable-name prefixes.
    prefix_map = IFACE_PREFIX_TYPE_MAP

    # Handle MAC-derived names like enx<MAC> / wlx<MAC>.
    m_mac = re.match(REGEX_MAC_DERIVED, interface_name)
    if m_mac:
        pfx = m_mac.group("prefix")
        iface_type = prefix_map.get(pfx, "Unknown")
        loc = interface_location(interface_name)
        port_hints = interface_port_hints(interface_name)
        return {
            "interface": interface_name,
            "type": iface_type,
            "bus": None,
            "slot": None,
            "port": None,
            "description": f"{iface_type} device (MAC-derived name)",
            **loc,
            **port_hints,
        }

    # Best-effort heuristic for PCI-ish forms (multiple variants exist in the wild).
    # Examples: enP3p5s0, enp0s31f6, eno1, ens3
    m = re.match(REGEX_PCI_FORMS, interface_name)
    if not m:
        loc = interface_location(interface_name)
        port_hints = interface_port_hints(interface_name)
        return {
            "interface": interface_name,
            "type": "Unknown",
            "bus": None,
            "slot": None,
            "port": None,
            "description": "Unrecognized interface naming pattern",
            **loc,
            **port_hints,
        }

    iface_type = prefix_map.get(m.group("prefix"), "Unknown")
    bus_str, slot_str, port_str = m.group("bus"), m.group("slot"), m.group("port")
    desc = f"{iface_type} device"
    if bus_str or slot_str or port_str:
        desc += " on"
        if bus_str:
            desc += f" PCI bus {bus_str}"
        if slot_str:
            desc += f", slot {slot_str}"
        if port_str:
            desc += f", port {port_str}"
    loc = interface_location(interface_name)
    port_hints = interface_port_hints(interface_name)
    return {
        "interface": interface_name,
        "type": iface_type,
        "bus": int(bus_str) if bus_str else None,
        "slot": int(slot_str) if slot_str else None,
        "port": int(port_str) if port_str else None,
        "description": desc,
        **loc,
        **port_hints,
    }


###################################################################################################
# Network Namespaces
###################################################################################################


def list_network_namespaces() -> list[dict[str, Any]]:
    """
    Return a list of net namespaces we can find.

    Each entry:
      {
        "ns": "net:[402653xxxx]",   # namespace inode-ish label from lsns/readlink
        "name": "nsname" | None,    # from `ip netns list` if present
        "path": "/run/netns/nsname" | "/proc/<pid>/ns/net" | None,
        "pid": 1234 | None,         # owner pid for unnamed namespaces (containers, etc.)
        "command": "..." | None
      }

    Best-effort strategy:
      1) `ip netns list` for named namespaces
      2) `lsns -t net ...` for everything (including unnamed)
      3) Merge by ns id when possible
    """
    ns_by_id: dict[str, dict[str, Any]] = {}

    # 1) Named namespaces (created via `ip netns add`)
    if shutil.which("ip"):
        try:
            out = _run_cmd(IP_NETNS_LIST_CMD)
            for raw in out.splitlines():
                name = raw.split()[0].strip()
                if not name:
                    continue

                entry = {
                    "ns": None,
                    "name": name,
                    "path": f"/run/netns/{name}",
                    "pid": None,
                    "command": None,
                }

                # Try to resolve ns id.
                # On many systems /run/netns/<name> is a bind-mounted file (not a symlink),
                # so readlink() returns nothing; in that case use the inode number.
                try:
                    if shutil.which("readlink"):
                        link = _run_cmd([*READLINK_CMD, entry["path"]]).strip()
                        if link:
                            entry["ns"] = link
                            ns_by_id[link] = entry
                            continue
                except (subprocess.SubprocessError, OSError):
                    log.debug(f"Failed to readlink namespace path for {name}")

                try:
                    inode = Path(entry["path"]).stat().st_ino
                    entry["ns"] = str(inode)
                    ns_by_id[str(inode)] = entry
                    continue
                except OSError:
                    log.debug(f"Failed to stat namespace path for {name}")

                ns_by_id[f"name:{name}"] = entry
        except (subprocess.SubprocessError, OSError) as exc:
            log.debug(f"Failed to enumerate named namespaces via ip netns: {exc}")

    # 2) All namespaces (including unnamed) via lsns
    if shutil.which("lsns"):
        try:
            out = _run_cmd(LSNS_CMD)
            for raw in out.splitlines():
                line = raw.strip()
                if not line:
                    continue

                # Output is columnar; COMMAND may contain spaces.
                # We requested: NS PATH PID COMMAND
                parts = line.split(None, 3)
                if len(parts) < 3:
                    continue

                ns_id = parts[0].strip()
                path = parts[1].strip() if len(parts) >= 2 else None
                pid = None
                try:
                    pid = int(parts[2])
                except (TypeError, ValueError):
                    pid = None
                cmd = parts[3].strip() if len(parts) == 4 else None

                entry = ns_by_id.get(ns_id) or {
                    "ns": ns_id,
                    "name": None,
                    "path": path,
                    "pid": pid,
                    "command": cmd,
                }

                # Merge/refresh fields
                entry["ns"] = entry.get("ns") or ns_id
                entry["path"] = entry.get("path") or path
                entry["pid"] = entry.get("pid") or pid
                entry["command"] = entry.get("command") or cmd

                ns_by_id[ns_id] = entry
        except (subprocess.SubprocessError, OSError) as exc:
            log.debug(f"Failed to enumerate namespaces via lsns: {exc}")

    # 3) Try to fill in ns id for named namespaces (optional nicer merge)
    # Not strictly required, but helps de-dup if both sources are present.
    # We can attempt `ip -n <name> link` and read its "link-netnsid" etc. but
    # it's messy; keep it simple: just return what we found.
    namespaces = list(ns_by_id.values())

    # Deterministic sort: named first, then ns id
    namespaces.sort(key=lambda d: (0 if d.get("name") else 1, d.get("name") or "", d.get("ns") or ""))
    return namespaces


def get_ip_addr_in_namespace(
    ns: dict[str, Any],
    *,
    return_error: bool = False,
) -> dict[str, dict] | tuple[dict[str, dict], str | None]:
    """
    Return interface map inside a namespace entry from list_network_namespaces().

        Prefers:
            - named: `ip -n <name> -details -json addr`
            - pid-owned: `nsenter -t <pid> -n ip -details -json addr`
    """
    if not shutil.which("ip"):
        raise FileNotFoundError("ip command not found")

    name = ns.get("name")
    pid = ns.get("pid")

    if name:
        cmd = ["ip", "-n", str(name), "-json", "-details", "addr"]
    elif pid:
        if not shutil.which("nsenter"):
            raise FileNotFoundError("nsenter command not found")
        cmd = ["nsenter", "-t", str(pid), "-n", "ip", "-details", "-json", "addr"]
    else:
        return ({}, None) if return_error else {}

    try:
        out = _run_cmd(cmd)
        parsed = _parse_ip_details_addr(out)
        return (parsed, None) if return_error else parsed
    except subprocess.CalledProcessError as exc:
        msg = (exc.stderr or "").strip() or str(exc)
        log.debug(f"Failed to get ip addr in namespace {ns}: {msg}")
        return ({}, msg) if return_error else {}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        msg = str(exc)
        log.debug(f"Failed to get ip addr in namespace {ns}: {msg}")
        return ({}, msg) if return_error else {}


###################################################################################################
# Parsers
###################################################################################################


def _parse_ip_details_addr(output: str) -> dict[str, dict]:
    """
    Parse `ip -details -json addr` output into the same structure as get_ip_addr().

    Expected output is JSON (a list of link objects), e.g. from:
        ip -details -json addr
        ip -details addr --json   (variant)
    """
    data = read_json_stdout(output or "[]")
    if data is None:
        log.debug("Failed to parse ip --json output")
        return {}

    if not isinstance(data, list):
        log.debug("Unexpected ip --json shape (expected list), got: %s", type(data))
        return {}

    def _first_present(d: dict[str, Any], keys: list[str], default=None):
        for k in keys:
            if k in d and d[k] is not None:
                return d[k]
        return default

    def _norm_flags(raw_flags: Any) -> list[str]:
        # iproute2 may return flags as ["BROADCAST","MULTICAST",...] or as "BROADCAST,MULTICAST"
        if raw_flags is None:
            return []
        if isinstance(raw_flags, list):
            return [str(x) for x in raw_flags if x]
        if isinstance(raw_flags, str):
            # Sometimes it's already comma-separated, sometimes space-separated
            if "," in raw_flags:
                return [f for f in raw_flags.split(",") if f]
            return [f for f in raw_flags.split() if f]
        return []

    def _norm_ifname(name: str) -> str:
        # ip text mode had "@ifX" suffix; JSON often does not, but normalize anyway.
        return (name or "").split("@", 1)[0]

    interfaces: dict[str, dict] = {}

    for link in data:
        if not isinstance(link, dict):
            continue

        ifname = _norm_ifname(_first_present(link, ["ifname", "name"], default=None))
        if not ifname:
            continue

        # Pull common link metadata (index/mtu/state) from the JSON record.
        idx = link.get("ifindex") or link.get("index")
        mtu = link.get("mtu")
        state = link.get("operstate") or link.get("state")

        # flags are typically a list in iproute2 JSON; use directly when available
        raw_flags = _first_present(link, ["flags"], default=[])
        flags_list = raw_flags if isinstance(raw_flags, list) else _norm_flags(raw_flags)

        derived = _derive_link_status(flags_list)

        # MAC address usually lives at "address" in JSON
        mac = _first_present(link, ["address", "mac"], default=None)

        iface_entry = {
            "index": int(idx) if isinstance(idx, int) or (isinstance(idx, str) and str(idx).isdigit()) else None,
            "flags": flags_list,
            "state": state or None,
            "mtu": int(mtu) if isinstance(mtu, int) or (isinstance(mtu, str) and str(mtu).isdigit()) else None,
            "mac": mac,
            "ipv4": [],
            "ipv6": [],
            **derived,
        }

        # Addresses: iproute2 JSON typically uses "addr_info": [ {family, local, prefixlen, scope}, ... ]
        addr_info = link.get("addr_info") or link.get("addrinfo") or []
        if isinstance(addr_info, list):
            for a in addr_info:
                if not isinstance(a, dict):
                    continue

                family = (a.get("family") or "").lower()
                # "local" is common; some builds use "address"
                addr = a.get("local") or a.get("address")
                if not addr:
                    continue

                prefix = a.get("prefixlen")
                scope = a.get("scope")

                try:
                    prefix_i = int(prefix) if prefix is not None else None
                except (TypeError, ValueError):
                    prefix_i = None

                rec = {"address": addr, "prefix": prefix_i, "scope": scope}

                if family == "inet":
                    iface_entry["ipv4"].append(rec)
                elif family == "inet6":
                    iface_entry["ipv6"].append(rec)

        interfaces[ifname] = iface_entry
    return interfaces


def _netmask_to_prefix(netmask: str) -> int | None:
    """Convert hex or dotted netmask to CIDR prefix."""
    if netmask.startswith("0x"):
        return int(netmask, 16).bit_count()
    try:
        return sum(int(octet).bit_count() for octet in netmask.split("."))
    except (TypeError, ValueError):
        return None


###################################################################################################
# Interface Address Discovery (ip/ifconfig)
###################################################################################################


def _derive_link_status(flags: list[str] | None) -> dict[str, Any]:
    """
    Best-effort derivation of useful status booleans from flags.
    - admin_up: interface is administratively up (UP flag)
    - carrier_up: link detected (LOWER_UP and not NO-CARRIER)
    """
    flags = flags or []
    admin_up = "UP" in flags

    carrier_up: bool | None = None
    if "LOWER_UP" in flags:
        carrier_up = True
    if "NO-CARRIER" in flags:
        carrier_up = False

    # If state is provided and carrier is unknown, make a weak inference.
    if carrier_up is None and "RUNNING" in flags:
        carrier_up = True

    return {"admin_up": admin_up, "carrier_up": carrier_up}


# -------------------------
# Linux backend (ip addr)
# -------------------------


def _get_ip_addr_linux() -> dict[str, dict]:
    if not shutil.which(LINUX_IP_CMD[0]):
        raise FileNotFoundError("ip command not found")

    out = _run_cmd(LINUX_IP_CMD)
    return _parse_ip_details_addr(out)


# -------------------------
# BSD / macOS backend (ifconfig)
# -------------------------


def _get_ip_addr_ifconfig() -> dict[str, dict]:
    """
    Best-effort Linux/BSD/macOS backend using `ifconfig`.

    Supports Linux-style output where continuation lines are space-indented
    (not necessarily tab-indented).
    """
    if not shutil.which(IFCONFIG_CMD[0]):
        raise FileNotFoundError("ifconfig command not found")

    out = _run_cmd(IFCONFIG_CMD)
    interfaces: dict[str, dict] = {}
    current_iface: str | None = None

    def _status_to_state(status_val: str) -> str | None:
        sv = (status_val or "").strip().lower()
        if sv in ("active", "running", "up"):
            return "UP"
        if sv in ("inactive", "down", "no carrier", "no-carrier"):
            return "DOWN"
        return None

    header_re = re.compile(r"^\s*(?P<ifname>[^\s:]+):\s+(?P<rest>.*)$")

    for raw in out.splitlines():
        line = raw.rstrip("\n")

        # Header line: "<iface>: flags=... mtu ..."
        m_hdr = header_re.match(line)
        if m_hdr and "flags=" in m_hdr.group("rest"):
            name = m_hdr.group("ifname").strip()
            rest = m_hdr.group("rest")
            current_iface = name

            interfaces[current_iface] = {
                "index": None,
                "flags": [],
                "state": None,
                "mtu": None,
                "mac": None,
                "ipv4": [],
                "ipv6": [],
                "admin_up": None,
                "carrier_up": None,
            }

            # flags=4163<UP,BROADCAST,RUNNING,MULTICAST>
            m_flags = re.search(r"flags=\d+<([^>]*)>", rest)
            if m_flags:
                flags_list = [f.strip() for f in m_flags.group(1).split(",") if f.strip()]
                interfaces[current_iface]["flags"] = flags_list
                interfaces[current_iface].update(_derive_link_status(flags_list))

                # RUNNING is a decent “carrier-ish” hint on ifconfig outputs
                if interfaces[current_iface]["carrier_up"] is None and "RUNNING" in flags_list:
                    interfaces[current_iface]["carrier_up"] = True

            # mtu 1500
            m_mtu = re.search(r"\bmtu\s+(\d+)\b", rest)
            if m_mtu:
                interfaces[current_iface]["mtu"] = int(m_mtu.group(1))

            continue

        # Continuation lines: anything indented (spaces OR tabs)
        if current_iface is None:
            continue
        if line and not line[:1].isspace():
            # Non-indented non-header: ignore rather than accidentally clobber parsing
            continue

        s = line.strip()
        if not s:
            continue

        # MAC: "ether xx:xx:..." or "lladdr xx:xx:..."
        if s.startswith(("ether ", "lladdr ")):
            parts = s.split()
            if len(parts) >= 2:
                interfaces[current_iface]["mac"] = parts[1]
            continue

        # BSD/macOS: "status: active"
        if s.startswith("status:"):
            status_val = s.split(":", 1)[1].strip()
            state = _status_to_state(status_val)
            if state:
                interfaces[current_iface]["state"] = state
            if status_val.lower() in ("active", "running"):
                interfaces[current_iface]["carrier_up"] = True
            elif status_val.lower() in ("inactive", "no carrier", "no-carrier"):
                interfaces[current_iface]["carrier_up"] = False
            continue

        # IPv4: "inet 10.0.0.1  netmask 255.255.0.0  broadcast ..."
        if s.startswith("inet "):
            parts = s.split()
            if len(parts) >= 2:
                addr = parts[1]
                netmask = None
                if "netmask" in parts:
                    i = parts.index("netmask")
                    if i + 1 < len(parts):
                        netmask = parts[i + 1]
                prefix = _netmask_to_prefix(netmask) if netmask else None
                interfaces[current_iface]["ipv4"].append({"address": addr, "prefix": prefix, "scope": "global"})
            continue

        # IPv6: "inet6 fe80::...  prefixlen 64  scopeid ..."
        if s.startswith("inet6 "):
            parts = s.split()
            if len(parts) >= 2:
                addr = parts[1].split("%", 1)[0]
                prefix = None
                if "prefixlen" in parts:
                    i = parts.index("prefixlen")
                    if i + 1 < len(parts):
                        try:
                            prefix = int(parts[i + 1])
                        except (TypeError, ValueError):
                            prefix = None
                scope = "link" if addr.lower().startswith(LINK_LOCAL_PREFIX) else "global"
                interfaces[current_iface]["ipv6"].append({"address": addr, "prefix": prefix, "scope": scope})
            continue

    # Infer state if still missing
    for info in interfaces.values():
        if info.get("state") is None:
            admin = info.get("admin_up")
            carrier = info.get("carrier_up")
            if admin is False or (admin is True and carrier is False):
                info["state"] = "DOWN"
            elif admin is True and carrier is True:
                info["state"] = "UP"

    return interfaces


def get_ip_addr() -> dict[str, dict]:
    """
    Return structured interface information.

    Output:
    {
        "eth0": {
            "index": 2,
            "flags": [...],
            "state": "UP",
            "mtu": 1500,
            "mac": "aa:bb:cc:dd:ee:ff",
            "ipv4": [{"address": "1.2.3.4", "prefix": 24, "scope": "global"}],
            "ipv6": [{"address": "fe80::1", "prefix": 64, "scope": "link"}],
        },
        ...
    }
    """
    try:
        return _get_ip_addr_linux()
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    try:
        return _get_ip_addr_ifconfig()
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        log.debug(f"Failed to get interface addresses via ifconfig: {exc}")
        return {}


###################################################################################################
# Convenience APIs
###################################################################################################


def all_interface_ips(include_loopback: bool = True) -> dict:
    """
    Return { interface: {"ipv4": [...], "ipv6": [...]}, ... }.

    Uses structured output from get_ip_addr().
    Set include_loopback=False to drop lo / 127.0.0.1 / ::1.
    """
    interfaces = get_ip_addr()
    result: dict = {}

    for ifname, info in interfaces.items():
        if not include_loopback and ifname == "lo":
            continue

        ipv4_addrs = _iter_addrs(info, "ipv4")
        ipv6_addrs = _iter_addrs(info, "ipv6")
        if not include_loopback:
            ipv4_addrs = [a for a in ipv4_addrs if a != LOOPBACK_IPV4]
            ipv6_addrs = [a for a in ipv6_addrs if a != LOOPBACK_IPV6]

        if ipv4_addrs or ipv6_addrs:
            result[ifname] = {
                "ipv4": ipv4_addrs,
                "ipv6": ipv6_addrs,
            }
    return result
