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

import ast
import logging

from .data_validation import is_dict, is_list, is_str, validate_json
from asct.core.utility.misc import flatten_dict

log = logging.getLogger(__name__)


def _require_keys(d: dict, keys: list[str], context: str) -> None:
    for k in keys:
        assert k in d, f"Missing key {context}[{k}]"


def validate_stdout_data(stdout: str) -> None:
    # Keep this deliberately loose: output can vary widely by host.
    required_markers = [
        "NETWORK",
        "Interfaces:",
    ]
    for marker in required_markers:
        assert marker in stdout, f"'{marker}' not found in\n{stdout}"


def validate_json_data(checked_json: dict) -> None:
    """Validate the network-info report JSON produced by `asct report network-info --format json`.

    The JSON report is expected to contain a top-level `network-info` key.
    Validation is intentionally tolerant of host-specific variability.
    """

    reference_json = {
        "network-info": {
            "net_local": is_dict,
            "net_ns": is_list,
            "net_dev": is_list,
        }
    }

    validate_json(reference_json, checked_json)

    net = checked_json["network-info"]
    assert isinstance(net, dict)

    # net_local
    net_local = net.get("net_local") or {}
    _require_keys(net_local, ["local_ipv4", "local_ipv6", "aliases"], "network-info[net_local]")
    assert isinstance(net_local["local_ipv4"], list)
    assert isinstance(net_local["local_ipv6"], list)
    assert isinstance(net_local["aliases"], dict)

    # net_dev
    net_dev = net.get("net_dev") or []
    assert isinstance(net_dev, list)
    assert len(net_dev) >= 1, "Expected at least one interface in network-info.net_dev"

    # Ensure we have a loopback entry on Linux.
    ifnames = {d.get("name") for d in net_dev if isinstance(d, dict)}
    assert "lo" in ifnames, f"Expected 'lo' interface not found, got {sorted([n for n in ifnames if n])}"

    required_dev_keys = [
        "name",
        "mac",
        "state",
        "admin_up",
        "carrier_up",
        "mtu",
        "flags",
        "ipv4",
        "ipv6",
        "type",
        "description",
        "location",
    ]

    for idx, dev in enumerate(net_dev):
        assert isinstance(dev, dict), f"network-info.net_dev[{idx}] is not a dict: {type(dev)}"
        _require_keys(dev, required_dev_keys, f"network-info[net_dev][{idx}]")
        is_str(dev["name"], f"network-info[net_dev][{idx}][name]")
        assert isinstance(dev["ipv4"], list)
        assert isinstance(dev["ipv6"], list)

    # net_ns
    net_ns = net.get("net_ns") or []
    assert isinstance(net_ns, list)
    for idx, ns in enumerate(net_ns):
        assert isinstance(ns, dict), f"network-info.net_ns[{idx}] is not a dict: {type(ns)}"
        # Best-effort keys (can vary by env)
        _require_keys(ns, ["ns", "name", "pid", "command", "error", "devices"], f"network-info[net_ns][{idx}]")
        assert isinstance(ns["devices"], list)


def validate_csv_data(json_report: dict, csv_report: list[list[str]]) -> None:
    """Validate network rows in a CSV against a json report.

    The system-info command may write network data into the same CSV as the
    system-info core data (e.g. `system_info.csv`). This validator tolerates that
    by skipping any non-network rows.

    The CSV and JSON runs are separate invocations in integration tests, so
    values may drift; we primarily ensure that:
      - CSV rows have the expected shape
      - keys exist in the JSON structure
      - values can be parsed into the JSON value type (when possible)
    """

    assert "network-info" in json_report, "JSON report missing top-level 'network-info' key"
    network_root = json_report.get("network-info") or {}
    allowed_top_level = set(network_root.keys())
    flat_json = flatten_dict(network_root)

    for row in csv_report:
        # Some CSV parsers may surface empty rows; skip those.
        if not row:
            continue
        assert len(row) >= 2, f"CSV row has unexpected shape: {row}"

        key_path = row[0]
        value = row[1]

        top_level = key_path.split(".", 1)[0] if key_path else ""
        if top_level not in allowed_top_level:
            continue

        assert key_path in flat_json, f"CSV key '{key_path}' not found in flattened JSON"
        json_entry = flat_json[key_path]

        # Try to type-convert CSV value to JSON type (best-effort).
        try:
            if isinstance(json_entry, str):
                _ = value
            elif json_entry is None:
                _ = None if not value else value
            else:
                _ = type(json_entry)(ast.literal_eval(value))
        except Exception as exc:
            log.error("Failed converting CSV value %s=%r to %s: %s", key_path, value, type(json_entry), exc)
            raise
