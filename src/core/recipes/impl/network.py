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

import pandas as pd

from typing import Any
from collections.abc import Iterable  # noqa: TC003
from dataclasses import InitVar, dataclass, asdict, is_dataclass, field

from asct.core.recipes.recipe_base import RecipeBase
from asct.core.utility.misc import flatten_dict
from asct.core.datatypes import ASCTSingleton
from asct.core import logger as log
from asct.lib.networking.network_helpers import (
    classify_ipv6,
    get_local_ip_addresses,
    get_ip_addr,
    get_ip_addr_in_namespace,
    list_network_namespaces,
    decode_interface,
)


# Formatting defaults (kept as constants to avoid magic numbers)
DEFAULT_NETWORK_LOCAL_KEY_WIDTH = 15
DEFAULT_NETWORK_SECTION_LABEL_WIDTH = 20
NETWORK_INLINE_WRAP_LIMIT_CHARS = 100


@dataclass
class network_dev:
    name: str = None
    mac: str = None
    state: str = None
    admin_up: bool = None
    carrier_up: bool = None
    mtu: int = None
    flags: list[str] = field(default_factory=list)
    ipv4: list[str] = field(default_factory=list)
    ipv6: list[str] = field(default_factory=list)
    type: str = None
    bus: int = None
    slot: int = None
    description: str = None
    location: str = None
    port: str = None

    ifname: InitVar[str | None] = None
    info: InitVar[dict[str, Any] | None] = None

    def __post_init__(self, ifname: str | None, info: dict[str, Any] | None):
        try:
            info = info or {}
            log.debug(f"Decoding interface {ifname} info: {info}")

            decoded = decode_interface(ifname) if ifname else {}

            self.name = ifname
            self.mac = info.get("mac")
            self.state = info.get("state")
            self.admin_up = info.get("admin_up")
            self.carrier_up = info.get("carrier_up")
            self.mtu = info.get("mtu")
            self.flags = info.get("flags") or []
            self.ipv4 = [entry.get("address") for entry in info.get("ipv4", []) if entry.get("address")]
            self.ipv6 = [entry.get("address") for entry in info.get("ipv6", []) if entry.get("address")]

            self.type = decoded.get("type")
            self.bus = decoded.get("bus")
            self.slot = decoded.get("slot")
            self.port = decoded.get("port")
            self.description = decoded.get("description")
            self.location = decoded.get("location")
        except (TypeError, ValueError, KeyError, AttributeError, OSError) as exc:
            log.debug(f"Failed to initialize network_dev: {exc}")

    def _iface_friendly_type(self) -> str:
        n = (self.name or "").lower()
        if n.startswith("docker"):
            return "Docker bridge"
        if n.startswith("virbr"):
            return "Virtual bridge"
        if n.startswith("br"):
            return "Bridge"
        if n.startswith("tap"):
            return "TAP"
        if n.startswith("tun"):
            return "TUN"
        return self.type or "Unknown"

    def _fmt_loc_and_port(self) -> str:
        """
        Return a compact suffix like " loc=PCI 0000:03:00.0 port=p0".
        Only includes fields when present.
        """
        bits: list[str] = []
        if self.location:
            bits.append(f"loc={self.location}")
        if self.port:
            bits.append(f"port={self.port}")
        return (" " + " ".join(bits)) if bits else ""

    def _fmt_ip6_list(self) -> list[str]:
        """
        Format IPv6 list with short plain-English hints.
        """
        out: list[str] = []
        for a in self.ipv6 or []:
            kind = classify_ipv6(a)
            if kind == "link-local":
                out.append(f"{a} (link-local, on-link only)")
            elif kind == "global":
                out.append(f"{a} (global/routable)")
            elif kind == "unique-local":
                out.append(f"{a} (ULA/private)")
            elif kind == "loopback":
                out.append(f"{a} (loopback)")
            else:
                out.append(a)
        return out

    def format(self, indent: str = "  ", status: bool = True) -> str:
        return self.format_data(asdict(self), indent=indent, status=status)

    @staticmethod
    def format_data(data: dict[str, Any], indent: str = "  ", status: bool = True) -> str:
        lines: list[str] = []
        name = data.get("name")
        mac = data.get("mac")
        state = data.get("state")
        admin_up = data.get("admin_up")
        carrier_up = data.get("carrier_up")
        mtu = data.get("mtu")
        ipv4 = data.get("ipv4") or []
        ipv6 = data.get("ipv6") or []

        n = (name or "").lower()
        if n.startswith("docker"):
            iface_type = "Docker bridge"
        elif n.startswith("virbr"):
            iface_type = "Virtual bridge"
        elif n.startswith("br"):
            iface_type = "Bridge"
        elif n.startswith("tap"):
            iface_type = "TAP"
        elif n.startswith("tun"):
            iface_type = "TUN"
        else:
            iface_type = data.get("type") or "Unknown"

        bits: list[str] = []
        if data.get("location"):
            bits.append(f"loc={data['location']}")
        if data.get("port"):
            bits.append(f"port={data['port']}")
        extra = (" " + " ".join(bits)) if bits else ""

        lines.append(f"{indent}  {name}: type={iface_type} mac={mac}{extra}")

        if status:
            status_bits = []
            if state:
                status_bits.append(f"state={state}")
            if admin_up is not None:
                status_bits.append(f"admin={'up' if admin_up else 'down'}")
            if carrier_up is not None:
                status_bits.append(f"carrier={'up' if carrier_up else 'down'}")
            if mtu:
                status_bits.append(f"mtu={mtu}")
            if status_bits:
                lines.append(f"{indent}    Status: {', '.join(status_bits)}")

        if ipv4:
            lines.append(f"{indent}    IPv4: {', '.join(ipv4)}")
        if ipv6:
            formatted_ipv6 = []
            for addr in ipv6:
                kind = classify_ipv6(addr)
                if kind == "link-local":
                    formatted_ipv6.append(f"{addr} (link-local, on-link only)")
                elif kind == "global":
                    formatted_ipv6.append(f"{addr} (global/routable)")
                elif kind == "unique-local":
                    formatted_ipv6.append(f"{addr} (ULA/private)")
                elif kind == "loopback":
                    formatted_ipv6.append(f"{addr} (loopback)")
                else:
                    formatted_ipv6.append(addr)
            lines.append(f"{indent}    IPv6: {', '.join(formatted_ipv6)}")
        if not ipv4 and not ipv6:
            lines.append(f"{indent}    (no IP addresses)")
        return "\n".join(lines)


@dataclass
class network_ns:
    ns: str = None
    name: str = None
    pid: int = None
    command: str = None
    error: str = None
    devices: list[network_dev] = field(default_factory=list)

    ns_info: InitVar[dict[str, Any] | None] = None

    def __post_init__(self, ns_info: dict[str, Any] | None):
        try:
            log.debug(f"Decoding network namespace info: {ns_info}")
            ns_info = ns_info or {}
            self.ns = ns_info.get("ns")
            self.name = ns_info.get("name")
            self.pid = ns_info.get("pid")
            self.command = ns_info.get("command")

            iface_map, ns_err = get_ip_addr_in_namespace(ns_info, return_error=True)
            self.error = ns_err
            for ifname, info in (iface_map or {}).items():
                dev = network_dev(ifname=ifname, info=info)
                self.devices.append(dev)
        except (TypeError, ValueError, KeyError, AttributeError, OSError) as exc:
            # keep object usable; mark namespace as uninspectable
            self.error = str(exc)
            log.debug(f"Failed to initialize network_ns: {exc}")

    def format(self, indent: str = "  ") -> str:
        return self.format_data(asdict(self), indent=indent)

    @staticmethod
    def format_data(data: dict[str, Any], indent: str = "  ") -> str:
        lines: list[str] = []
        label = data.get("name") or data.get("ns")
        extra = []
        if data.get("pid"):
            extra.append(f"pid={data['pid']}")
        if data.get("command"):
            extra.append(f"cmd={data['command']}")
        header = f"{indent}Namespace {label}"
        if extra:
            header += f" ({', '.join(extra)})"
        header += ":"
        lines.append(header)

        devices = data.get("devices") or []
        if not devices:
            if data.get("error"):
                lines.append(f"{indent}  (unable to be inspected: {data['error']})")
            else:
                lines.append(f"{indent}  (no interfaces detected)")
        else:
            lines.extend(network_dev.format_data(dev, indent=indent + indent, status=False) for dev in devices)
        return "\n".join(lines)


@dataclass
class network_local:
    local_ipv4: list[str] = field(default_factory=list)
    local_ipv6: list[str] = field(default_factory=list)
    aliases: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self):
        try:
            ips = get_local_ip_addresses() or {}
            self.local_ipv4 = ips.get("ipv4", [])
            self.local_ipv6 = ips.get("ipv6", [])
            self.aliases = ips.get("aliases", {}) or {}
        except (TypeError, ValueError, KeyError, AttributeError, OSError) as exc:
            log.debug(f"Failed to get local IP addresses: {exc}")

    @staticmethod
    def _fmt_key(key: str, width_label: int = DEFAULT_NETWORK_LOCAL_KEY_WIDTH, indent: str = "") -> str:
        return f"{indent}{key:<{width_label}}"

    @staticmethod
    def _add_wrapped_list(
        key: str,
        values: Iterable[str],
        sep: str = ", ",
        width_label: int = DEFAULT_NETWORK_LOCAL_KEY_WIDTH,
        indent: str = "",
    ) -> str:
        vals = [v for v in (values or []) if v]
        if not vals:
            return f"{network_local._fmt_key(key, width_label=width_label, indent=indent)}-"

        joined = sep.join(str(v) for v in vals)
        prefix = network_local._fmt_key(key, width_label=width_label, indent=indent)
        if len(prefix) + len(joined) <= NETWORK_INLINE_WRAP_LIMIT_CHARS:
            return f"{prefix}{joined}"

        lines: list[str] = []
        lines.append(f"{prefix}{vals[0]}")
        cont = " " * len(prefix)
        lines.extend(f"{cont}{v}" for v in vals[1:])
        return "\n".join(lines)

    def format(self, width_label: int = DEFAULT_NETWORK_SECTION_LABEL_WIDTH, indent: str = "  ") -> str:
        return self.format_data(asdict(self), width_label=width_label, indent=indent)

    @staticmethod
    def format_data(
        data: dict[str, Any], width_label: int = DEFAULT_NETWORK_SECTION_LABEL_WIDTH, indent: str = "  "
    ) -> str:
        lines: list[str] = []

        lines.append(
            network_local._add_wrapped_list(
                "Local IPv4:", data.get("local_ipv4"), width_label=width_label, indent=indent
            )
        )
        lines.append(
            network_local._add_wrapped_list(
                "Local IPv6:", data.get("local_ipv6"), width_label=width_label, indent=indent
            )
        )

        aliases = data.get("aliases") or {}
        hostnames = aliases.get("hostnames", []) if isinstance(aliases, dict) else []
        if hostnames:
            lines.append(
                network_local._add_wrapped_list(
                    "Aliases:",
                    hostnames,
                    width_label=width_label,
                    indent=indent,
                )
            )

        return "\n".join(lines)


class NetworkInfo(RecipeBase, metaclass=ASCTSingleton):
    net_local: network_local | None = None
    net_ns: list[network_ns]
    net_dev: list[network_dev]

    def __init__(self, metadata):
        RecipeBase.__init__(self, metadata=metadata)

        # Ensure we always have a config object for serialize() metadata.
        # (SystemInfo does this too.)
        self.initialize_config()

        self.net_ns = []
        self.net_dev = []

    def run_function(self):
        try:
            self.net_local = network_local()
        except (TypeError, ValueError, KeyError, AttributeError, OSError) as exc:
            log.debug(f"Failed to initialize network_local: {exc}")

        # Interfaces and per-interface IPs
        try:
            iface_map = get_ip_addr()
            for ifname, info in iface_map.items():
                dev = network_dev(ifname=ifname, info=info)
                self.net_dev.append(dev)
        except (TypeError, ValueError, KeyError, AttributeError, OSError) as exc:
            log.debug(f"Failed to get interface details: {exc}")

        # Namespaces (best-effort)
        try:
            ns_list = list_network_namespaces()
            for ns in ns_list:
                ns = network_ns(ns_info=ns)
                self.net_ns.append(ns)
        except (TypeError, ValueError, KeyError, AttributeError, OSError) as exc:
            log.debug(f"Failed to list network namespaces: {exc}")

        # Return the recipe object itself so RecipeBase.serialize() can use the
        # standard report-style contract (`self.result.desc` plus `to_dict()`).
        return self

    def format(self, width_label: int = DEFAULT_NETWORK_SECTION_LABEL_WIDTH, indent: str = "  ") -> str:
        """
        Format network output to match the existing SystemInfo to_stdout style,
        but with clearer IPv6 explanations (especially link-local).
        """
        lines: list[str] = []
        data = self._loaded_raw_result if self._loaded_raw_result is not None else self.to_dict()
        net_local_data = data.get("net_local") if isinstance(data, dict) else None
        net_dev_data = data.get("net_dev") if isinstance(data, dict) else []
        net_ns_data = data.get("net_ns") if isinstance(data, dict) else []

        all_v6: list[str] = []
        if isinstance(net_local_data, dict):
            all_v6.extend([a for a in (net_local_data.get("local_ipv6") or []) if a])
        for dev in net_dev_data or []:
            if isinstance(dev, dict):
                all_v6.extend([x for x in (dev.get("ipv6") or []) if x])

        kinds = {classify_ipv6(a) for a in all_v6 if a}
        has_global = "global" in kinds
        has_non_loopback = any(k not in ("loopback", "not-v6", "unknown") for k in kinds)

        if isinstance(net_local_data, dict):
            lines.append(network_local.format_data(net_local_data, width_label=width_label, indent=indent))

        lines.append(f"{indent}Interfaces:")
        if not net_dev_data:
            lines.append(f"{indent}  (no interfaces detected)")
        else:
            lines.extend(network_dev.format_data(dev, indent=indent) for dev in net_dev_data if isinstance(dev, dict))

        # Namespaces (best-effort)
        has_uninspectable_namespaces = False
        if net_ns_data:
            has_uninspectable_namespaces = any(ns.get("error") for ns in net_ns_data if isinstance(ns, dict))
            lines.append(f"{indent}Namespaces:")
            lines.extend(
                network_ns.format_data(ns, indent=indent + indent) for ns in net_ns_data if isinstance(ns, dict)
            )

        note_lines: list[str] = []
        if not has_global:
            if not all_v6:
                note_lines.append(f"{indent}  No IPv6 addresses detected.")
                note_lines.append(f"{indent}  This usually means IPv6 is disabled or not configured on this host.")
            else:
                note_lines.append(f"{indent}  No globally-routable IPv6 address detected.")
                if "link-local" in kinds:
                    note_lines.append(
                        f"{indent}  Link-local (fe80::/10) is normal and only works on the local L2 segment."
                    )
                if not has_non_loopback:
                    note_lines.append(
                        f"{indent}  Only loopback (::1) exists, meaning IPv6 is not configured on any interface."
                    )
                note_lines.append(
                    f"{indent}  If you expected public IPv6, check router/DHCPv6/SLAAC or corporate network policy."
                )

        if has_uninspectable_namespaces:
            note_lines.append(
                f"{indent}  Some namespaces are only visible/inspectable with elevated privileges (e.g. sudo)."
            )

        if note_lines:
            lines.append(f"{indent}Note:")
            lines.extend(note_lines)

        return "\n".join(lines)

    def to_stdout(self):
        print(self.format())

    def to_dict(self):
        """
        Convert only specific dataclass attributes to a dictionary,
        skipping any that are None at the top level.
        """
        if self._loaded_raw_result is not None:
            return self._loaded_raw_result

        allowed_attrs = [
            "net_local",
            "net_ns",
            "net_dev",
        ]

        result = {}
        for attr in allowed_attrs:
            value = getattr(self, attr, None)
            if value is not None:  # Skip if whole attribute is None
                if is_dataclass(value):
                    result[attr] = asdict(value)
                elif isinstance(value, list):
                    # net_ns / net_dev are lists of dataclasses
                    if value and all(is_dataclass(v) for v in value):
                        result[attr] = [asdict(v) for v in value]
                    else:
                        result[attr] = value
                else:
                    result[attr] = value
        return result

    def to_csv_str(self):
        """
        Save the results to a CSV file.
        """
        flat_dict = flatten_dict(self.to_dict())
        df = pd.DataFrame(list(flat_dict.items()))
        return df.to_csv(index=False, header=False)

    def get_diff_data(self):
        if self._loaded_raw_result is None:
            raise RuntimeError(f"result data was not loaded for {self.name}")
        return self._loaded_raw_result

    def deserialize(self, data):
        if not data:
            return
        _, self._loaded_raw_result = self._deserialize_payload(data)
        self.result = self


if __name__ == "__main__":
    # Get networking information
    network = NetworkInfo()
    print("\nNetwork Information ------------------------------------------------------------\n")
    network.to_stdout()
