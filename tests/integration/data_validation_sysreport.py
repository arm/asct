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
import re
import logging
from copy import deepcopy
from .data_validation import accept_none, is_bool, is_dict, is_list, is_int, is_str, validate_json
from asct.core.utility.misc import flatten_dict

log = logging.getLogger(__name__)


def _extract_stdout_values(stdout, keys):
    """Parses stdout and returns a dictionary with the values
    for the provided keys"""

    stdout_kv = {}
    for line in stdout.splitlines():
        line = line.strip()

        found_key = None
        for key in keys:
            full_key = key + ":"
            if not line.startswith(full_key):
                continue
            found_key = key
            break
        if not found_key:
            continue

        value = line[len(found_key) + 1 :].strip()
        stdout_kv[found_key] = value
        keys.remove(found_key)
        if not keys:
            break

    assert len(keys) == 0, f"Some keys were not found in stdout: {keys}"
    return stdout_kv


def _mem_size_to_bytes(value):
    """Parses a memory size returned by sysreport and converts it to bytes"""

    units = ["KiB", "MiB", "GiB", "TiB"]
    unit_search_pattern = "|".join(units)
    pattern = re.compile(f"([0-9.]+)({unit_search_pattern})")
    result = pattern.search(value)
    assert result is not None, f"Unable to parse memory size from stdout string {value}"
    exp = units.index(result.group(2)) + 1
    return float(result.group(1)) * (1024**exp)


def validate_stdout_data(stdout, system_cpu_count, system_mem_size):
    # The system-info command may include additional sections (e.g. networking).
    # Keep the validation focused on the system-info (core) content.
    expected_categs = [
        "System hardware",
        "Memory",
        "OS configuration",
        "Performance features",
    ]
    assert "System Information" in stdout, f"Expected a 'System Information' header not found in\n{stdout}"
    for line in expected_categs:
        assert line in stdout, f"'{line}' not found in\n{stdout}"

    values = _extract_stdout_values(stdout, ["System memory", "CPUs"])
    mem_size = _mem_size_to_bytes(values["System memory"])
    accepted_error = 100 * 1024 * 1024  # 100 MB of accepted error due to rounding
    assert abs(mem_size - system_mem_size) < accepted_error, (
        f"Reported mem size {mem_size} differs from system mem size {system_mem_size}"
    )

    cpu_count = int(values["CPUs"])
    assert cpu_count == system_cpu_count, (
        f"Reported number of CPUs {cpu_count} differs from system CPU count {system_cpu_count}"
    )

    # There are two "Manufacturer" lines in the report: one in "System Information"
    # and one in "Memory". Ensure both are present and that memory part number is shown.
    assert stdout.count("Manufacturer:") >= 2, "Expected memory/system manufacturer lines in stdout"
    assert "Part Number:" in stdout, "Expected memory part number line in stdout"


def validate_json_data(checked_json, system_cpu_count, system_mem_size, is_bare_metal):
    reference_json = {
        "system-info": {
            "report": {"collected_time": is_str, "asct_ver": is_str, "run_as_root": is_bool},
            "sys_hw": {
                "arch": is_str,
                "n_cpus": system_cpu_count,
                "cpu_type": is_str,
                "cache_info": is_str,
                "cache_line_size": is_int,
                "caches": is_dict,
                "atomics": is_bool,
                "interconnect": is_list,
                "n_numa_nodes": is_int,
                "numa_nodes": is_dict,
                "numa_kern_cfg": is_bool,
                "sockets": is_int,
            },
            "sys_info": {
                "manufacturer": accept_none(is_str, is_bare_metal),
                "product_name": accept_none(is_str, is_bare_metal),
                "version": accept_none(is_str, is_bare_metal),
                "serial": accept_none(is_str, is_bare_metal),
                "uuid": accept_none(is_str, is_bare_metal),
            },
            "memory": {
                "total_size": system_mem_size,
                "n_channels": accept_none(is_int, is_bare_metal),
                "manufacturer": accept_none(is_str, is_bare_metal),
                "part_number": accept_none(is_str, is_bare_metal),
                "speed": accept_none(is_int, is_bare_metal),
                "data_width": accept_none(is_int, is_bare_metal),
                "peak_theoretical_bw": accept_none(is_int, is_bare_metal),
            },
            "kern_cfg": {
                "ver": is_str,
                "cfg_file": is_str,
                "build_dir": None,
                "uses_atomics": is_bool,
                "huge_pages": is_str,
                "thp": is_str,
                "mpam": is_bool,
                "resctrl": is_bool,
                "distro": is_str,
                "libc_ver": is_str,
                "boot_info": is_str,
                "kpti": is_bool,
                "lockdown": is_str,
                "mitigations": is_str,
            },
            "perf_feats": {
                "has_tools": is_bool,
                "perf_dir": None,
                "perf_opencsd": is_bool,
                "n_counters": None,
                "perf_sampling": None,
                "perf_hw_trace": None,
                "paranoid": is_int,
                "kptr_restrict": is_int,
                # None is an acceptable value even when running on bare metal
                # because /proc/sys/kernel/perf_user_access was only added in Linux kernel >= v5.17
                "userspace_access": accept_none(is_int, False),
                "interconnect": accept_none(is_bool, is_bare_metal),
                "kcore": is_bool,
                "devmem": is_bool,
                "bpf": {"bpf": is_bool, "bpf_tool": None, "bpf_tool_ver": None, "bpftrace": None},
            },
            "vulnerabilities": is_dict,
        }
    }

    validate_json(reference_json, checked_json)


def validate_csv_data(json_report, csv_report):
    """Validates a CSV report array based on a JSON report that was collected and validated previously."""

    system_info_root = deepcopy(json_report["system-info"])
    interconnect = system_info_root.get("sys_hw", {}).get("interconnect")
    if isinstance(interconnect, list):
        system_info_root["sys_hw"]["interconnect"] = tuple(interconnect)
    numa_nodes = system_info_root.get("sys_hw", {}).get("numa_nodes")
    if isinstance(numa_nodes, dict):
        system_info_root["sys_hw"]["numa_nodes"] = {
            key: tuple(value) if isinstance(value, list) else value for key, value in numa_nodes.items()
        }
    allowed_top_level = set(system_info_root.keys())
    flat_json = flatten_dict(system_info_root)

    for line in csv_report:
        if not line:
            continue
        key_path = line[0]
        value = line[1] if len(line) > 1 else ""

        # system-info may include additional appended sections (e.g. network).
        # Ignore rows that don't belong to the system-info JSON root.
        top_level = key_path.split(".", 1)[0] if key_path else ""
        if top_level not in allowed_top_level:
            continue

        json_entry = flat_json[key_path]
        try:
            if type(json_entry) is str:
                conv_value = value
            elif json_entry is None:
                conv_value = None if not value else value
            else:
                conv_value = type(json_entry)(ast.literal_eval(value))
        except ValueError:
            log.error(f"Conversion failure {key_path} = {value} => {type(json_entry)}")
            raise
        except Exception as e:
            log.error(f"Generic error when converting {key_path} = {value}({conv_value}) => {type(json_entry)}: {e}")
            raise
        if "collected_time" in key_path:  # Don't compare collected_time, it will never match
            continue
        assert json_entry == conv_value, f"Values differ from JSON report for {key_path}: {conv_value} != {json_entry}"
