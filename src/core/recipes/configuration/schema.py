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

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from asct.core.utility.format import str_memsize, str_time
from asct.core.utility.misc import create_dict_path


@dataclass(frozen=True)
class UserConfigDescr:
    name: str
    descr: str = ""
    conv: callable = str
    path: list | None = None

    def __post_init__(self):
        object.__setattr__(self, "path", self.name.split("."))
        object.__setattr__(self, "name", self.path[-1])

    def new_from(self, **updates: Any):
        valid_keys = {"name", "path", "descr", "conv"}
        invalid_keys = set(updates) - valid_keys
        if invalid_keys:
            raise TypeError(f"Unknown UserConfigDescr field override(s): {', '.join(sorted(invalid_keys))}")

        if "name" in updates and "path" in updates:
            raise ValueError("Only one of 'name' or 'path' can be overridden")

        base_path = self.path if self.path is not None else [self.name]

        if "path" in updates:
            updated_path = updates["path"]
            if isinstance(updated_path, str):
                name = updated_path
            else:
                name = ".".join(str(part) for part in updated_path)
        else:
            name = updates.get("name", ".".join(base_path))

        return UserConfigDescr(
            name=name,
            descr=updates.get("descr", self.descr),
            conv=updates.get("conv", self.conv),
        )


def create_user_config(settings):
    settings_dict = {}
    for current in settings:
        create_dict_path(settings_dict, current.path, current)
    return settings_dict


def mem_size_conv(value):
    # None is treated as "auto" or "default"
    if value is None:
        return None
    if isinstance(value, str):
        return str_memsize(value)
    return int(value)


def duration_conv(value):
    if isinstance(value, str):
        return str_time(value)
    return float(value)


def boolean_conv(value):
    if isinstance(value, str):
        val_lower = value.lower()
        if val_lower in ("1", "true", "yes"):
            return True
        if val_lower in ("0", "false", "no"):
            return False
        raise ValueError(f"Invalid boolean string: {value}")
    return bool(value)


def optional_int_conv(value):
    if value is None:
        return None
    return int(value)


def num_list_conv(
    accept_ranges,
    unique_items,
    num_type=int,
    separator=",",
    min_value=None,
    max_value=None,
    optional_items=False,
):
    """
    Returns a conversion function which takes a string or a list and converts it to a list of numbers.

    Ranges allow stepping using N-M:S syntax (for example: 1-10:2 will return odd numbers from 1 to 10).
    If unique_items is specified, the resulting list will remove duplicates while keeping the order.
    If min_value or max_value are specified, converted values outside those bounds are excluded.
    If optional_items is specified, None/default entries are preserved as None.

    Examples:
        >>> conv = num_list_conv(accept_ranges=True, unique_items=False)
        >>> conv("1,2,3")
        [1, 2, 3]
        >>> conv("1-3")
        [1, 2, 3]
        >>> conv("1-5:2")
        [1, 3, 5]
        >>> conv("0-999:333, 1000-1500:100")
        [0, 333, 666, 999, 1000, 1100, 1200, 1300, 1400, 1500]
        >>> conv([4, 5, 6])
        [4, 5, 6]
        >>> conv(7)
        [7]

        >>> conv_unique = num_list_conv(accept_ranges=True, unique_items=True)
        >>> conv_unique("1,2,2,3")
        [1, 2, 3]
        >>> conv_unique("1-3,2")
        [1, 2, 3]

        >>> float_conv = num_list_conv(accept_ranges=True, unique_items=False, num_type=float)
        >>> float_conv("1.5,2.5")
        [1.5, 2.5]
        >>> float_conv("1-3")
        [1.0, 2.0, 3.0]

        >>> natural_conv = num_list_conv(accept_ranges=True, unique_items=False, min_value=1)
        >>> natural_conv("0,1,2,3")
        [1, 2, 3]
    """

    def conv_func(value):
        none_tokens = {"", "none", "default", "null", "nil", "~"}
        result = []
        if value is None and optional_items:
            result = [None]
        elif isinstance(value, str):
            if not value:
                return [None] if optional_items else result
            for part in value.split(separator):
                part = part.strip()
                if optional_items and part.lower() in none_tokens:
                    result.append(None)
                elif accept_ranges and "-" in part:
                    start, end = part.split("-", maxsplit=1)
                    step = num_type(1)
                    if ":" in end:
                        end, step_str = end.split(":", maxsplit=1)
                        step = num_type(step_str)
                    start = num_type(start)
                    end = num_type(end)
                    while start <= end:
                        result.append(start)
                        start += step
                else:
                    result.append(num_type(part))
        elif isinstance(value, list):
            for item in value:
                if optional_items and (item is None or str(item).strip().lower() in none_tokens):
                    result.append(None)
                else:
                    result.append(num_type(item))
        else:
            result = [num_type(value)]

        if min_value is not None:
            result = [item for item in result if item is None or item >= min_value]
        if max_value is not None:
            result = [item for item in result if item is None or item <= max_value]

        if unique_items:
            seen = set()
            return [x for x in result if not (x in seen or seen.add(x))]

        return result

    return conv_func


int_list_conv = num_list_conv(accept_ranges=True, unique_items=False, num_type=int)
whole_int_list_conv = num_list_conv(
    accept_ranges=True,
    unique_items=False,
    num_type=int,
    min_value=0,
)
natural_int_list_conv = num_list_conv(
    accept_ranges=True,
    unique_items=False,
    num_type=int,
    min_value=1,
)
whole_int_or_default_list_conv = num_list_conv(
    accept_ranges=True,
    unique_items=False,
    num_type=int,
    min_value=0,
    optional_items=True,
)
float_list_conv = num_list_conv(accept_ranges=True, unique_items=False, num_type=float)
numa_cpu_list_conv = num_list_conv(accept_ranges=True, unique_items=False, num_type=int)


def optional_int_list_conv(value):
    if value is None:
        return []
    return int_list_conv(value)


def str_list_conv(value):
    if isinstance(value, str):
        return [str(x) for x in value.split(",") if x]
    if isinstance(value, list):
        return [str(x) for x in value]
    return [str(value)]


def cfg(name, descr, conv=str):
    return UserConfigDescr(name=name, descr=descr, conv=conv)


# -----------------------------------------------------------------------------
# User-defined configuration schema
# -----------------------------------------------------------------------------
# Field catalog used to build per-recipe user configuration schemas.
USER_CFG_FIELDS = {
    # Shared benchmark controls used across memory and storage recipes.
    "duration": cfg(name="duration", descr="Benchmark duration in seconds", conv=duration_conv),
    "iterations": cfg(name="iterations", descr="Number of iterations for the benchmark", conv=int),
    "number_of_runs": cfg(name="number_of_runs", descr="Number of runs per sweep point", conv=int),
    "data_size": cfg(name="data_size", descr="Payload size", conv=mem_size_conv),
    "cycle_base": cfg(name="cycle_base", descr="Use cycle-based time measurement", conv=boolean_conv),
    # Memory-recipe specific controls.
    "workload_cmd": cfg(name="workload_cmd", descr="Command to run custom workload", conv=str),
    "injected_nops": cfg(name="injected_nops", descr="Nops to slow down BW benchmark", conv=int_list_conv),
    "phase": cfg(name="phase", descr="Choice of loading/bandwidth/both", conv=str),
    "bw_cpu_blocklist": cfg(
        name="bw_cpu_blocklist",
        descr="CPUs not to run bandwidth benchmarks",
        conv=numa_cpu_list_conv,
    ),
    "latency_cpu_id": cfg(name="latency_cpu_id", descr="CPU ID for latency thread", conv=int),
    "all_cpus": cfg(name="all_cpus", descr="Measure all CPU pairs", conv=boolean_conv),
    "hist_bins": cfg(name="hist_bins", descr="Number of latency histogram bins", conv=int),
    "heatmap_vmax": cfg(name="heatmap_vmax", descr="Max value (ns) for heatmap colorscale", conv=int),
    # Storage-recipe specific controls.
    "blocksize": cfg(name="blocksize", descr="Block size for I/O operations", conv=mem_size_conv),
    "iodepth": cfg(name="iodepth", descr="I/O depth for operations", conv=int),
    "numjobs": cfg(name="numjobs", descr="Number of I/O jobs", conv=int),
    "rw_pattern": cfg(name="rw_pattern", descr="Read/Write pattern", conv=str),
    "rwmixread": cfg(name="rwmixread", descr="Read/Write mix (percentage of reads)", conv=int),
    "filesize": cfg(name="filesize", descr="Size of the files to use", conv=mem_size_conv),
    "filenames": cfg(name="filenames", descr="List of filenames to use", conv=str_list_conv),
    "direct": cfg(name="direct", descr="Direct I/O flag", conv=boolean_conv),
    "create_temp_file": cfg(
        name="create_temp_file",
        descr="Flag to create a temporary file for the benchmark",
        conv=boolean_conv,
    ),
    "request_size_sweep_steps": cfg(
        name="request_size_sweep_steps",
        descr="List of request sizes to sweep",
        conv=int_list_conv,
    ),
    "iodepth_sweep_steps": cfg(name="iodepth_sweep_steps", descr="List of IODepth to sweep", conv=int_list_conv),
    "process_count_sweep_steps": cfg(
        name="process_count_sweep_steps",
        descr="List of process counts to sweep",
        conv=int_list_conv,
    ),
    "access_pattern_sweep_steps": cfg(
        name="access_pattern_sweep_steps",
        descr="List of access patterns to sweep",
        conv=str_list_conv,
    ),
    # Report-recipe specific controls.
    "detect": cfg(
        name="detect",
        descr="Detect CMN configuration, must run at least once on a system",
        conv=boolean_conv,
    ),
    "diagram": cfg(
        name="diagram",
        descr="Display CMN diagram, requires --detect to have been run at least once",
        conv=boolean_conv,
    ),
    # Networking-recipe specific controls.
    # Sweep compatibility notes:
    # - bandwidth_target_bps_sweep_steps maps to iperf3 -b for both TCP and UDP.
    #   Use None/default to omit -b and keep iperf3's protocol default behavior.
    # - window_sweep_steps maps to iperf3 --window (socket send/receive buffer
    #   sizes) for both TCP and UDP; it indirectly influences TCP window size.
    # - For UDP, message_size_sweep_steps values above 65507 bytes are not
    #   clamped; runtime emits a warning and proceeds with the requested value.
    "server_host": cfg(name="server_host", descr="iperf3 server hostname or IP address", conv=str),
    "port": cfg(name="port", descr="iperf3 TCP/UDP port", conv=int),
    "protocol_sweep_steps": cfg(
        name="protocol_sweep_steps",
        descr="Protocols to sweep, for example tcp,udp",
        conv=str_list_conv,
    ),
    "duration_sweep_steps": cfg(
        name="duration_sweep_steps",
        descr="Run durations in seconds to sweep, for example 3,10",
        conv=natural_int_list_conv,
    ),
    "message_size_sweep_steps": cfg(
        name="message_size_sweep_steps",
        descr="Message sizes in bytes to sweep, for example 1200,131072",
        conv=natural_int_list_conv,
    ),
    "window_sweep_steps": cfg(
        name="window_sweep_steps",
        descr="TCP socket window sizes to sweep, for example 256K,1M",
        conv=str_list_conv,
    ),
    "bandwidth_target_bps_sweep_steps": cfg(
        name="bandwidth_target_bps_sweep_steps",
        descr="Bandwidth targets in bits per second to sweep, for example default,1000000",
        conv=whole_int_or_default_list_conv,
    ),
    "client_affinities": cfg(
        name="client_affinities",
        descr="CPU affinities for iperf3 client sweep",
        conv=optional_int_list_conv,
    ),
    "server_affinity": cfg(
        name="server_affinity",
        descr="CPU affinity for local iperf3 server",
        conv=optional_int_conv,
    ),
    "secure_access": cfg(
        name="secure_access",
        descr="Assume CMN Secure registers are accessible when dumping CMN registers",
        conv=boolean_conv,
    ),
}


def user_cfg_schema(*field_names, overrides: dict[str, dict[str, Any]] | None = None):
    missing_fields = [name for name in field_names if name not in USER_CFG_FIELDS]
    if missing_fields:
        known_fields = ", ".join(sorted(USER_CFG_FIELDS.keys()))
        raise ValueError(f"Unknown user config field(s): {', '.join(missing_fields)}. Known fields: {known_fields}")

    overrides = overrides or {}
    missing_override_fields = [name for name in overrides if name not in field_names]
    if missing_override_fields:
        known_fields = ", ".join(field_names)
        raise ValueError(
            "Override field(s) not present in this schema: "
            + ", ".join(missing_override_fields)
            + f". Schema fields: {known_fields}"
        )

    result = []
    for name in field_names:
        field_descr = USER_CFG_FIELDS[name]
        if name in overrides:
            field_descr = field_descr.new_from(**overrides[name])
        result.append(field_descr)
    return result


# Used by: idle-latency
MEMORY_COMMON_USER_CFG = user_cfg_schema("duration", "data_size", "cycle_base")
# Used by: peak-bandwidth, cross-numa-bandwidth
MEMORY_ITERATIONS_USER_CFG = user_cfg_schema("iterations", "data_size", "cycle_base")
# Used by: latency-sweep, bandwidth-sweep
MEMORY_SWEEP_USER_CFG = user_cfg_schema("cycle_base")
LOADED_LATENCY_USER_CFG = user_cfg_schema(
    "duration",
    "data_size",
    "workload_cmd",
    "injected_nops",
    "phase",
    "bw_cpu_blocklist",
    "latency_cpu_id",
    "cycle_base",
)
# Used by: c2c-latency
C2C_USER_CFG = user_cfg_schema("iterations", "all_cpus", "hist_bins", "heatmap_vmax", "cycle_base")

# Intentional schema differences between storage recipes:
# - request-size-sweep omits blocksize because blocksize itself is the sweep variable.
# - io-depth-sweep omits iodepth because iodepth itself is the sweep variable.
# - process-count-sweep omits numjobs because numjobs itself is the sweep variable.
# - access-pattern-sweep omits rw_pattern because rw_pattern itself is the sweep variable.
STORAGE_REQUEST_SIZE_USER_CFG = user_cfg_schema(
    "duration",
    "iodepth",
    "numjobs",
    "rw_pattern",
    "rwmixread",
    "filesize",
    "filenames",
    "request_size_sweep_steps",
    "direct",
    "create_temp_file",
)
STORAGE_IO_DEPTH_USER_CFG = user_cfg_schema(
    "duration",
    "blocksize",
    "numjobs",
    "rw_pattern",
    "rwmixread",
    "filesize",
    "filenames",
    "iodepth_sweep_steps",
    "direct",
    "create_temp_file",
)
STORAGE_PROCESS_COUNT_USER_CFG = user_cfg_schema(
    "duration",
    "blocksize",
    "iodepth",
    "rw_pattern",
    "rwmixread",
    "filesize",
    "filenames",
    "process_count_sweep_steps",
    "direct",
    "create_temp_file",
)
STORAGE_ACCESS_PATTERN_USER_CFG = user_cfg_schema(
    "duration",
    "blocksize",
    "iodepth",
    "numjobs",
    "rwmixread",
    "filesize",
    "filenames",
    "access_pattern_sweep_steps",
    "direct",
    "create_temp_file",
)
IPERF3_TCP_SWEEP_USER_CFG = user_cfg_schema(
    "server_host",
    "port",
    "duration_sweep_steps",
    "message_size_sweep_steps",
    "window_sweep_steps",
    "bandwidth_target_bps_sweep_steps",
    "client_affinities",
    "server_affinity",
)
IPERF3_UDP_SWEEP_USER_CFG = user_cfg_schema(
    "server_host",
    "port",
    "duration_sweep_steps",
    "message_size_sweep_steps",
    "window_sweep_steps",
    "bandwidth_target_bps_sweep_steps",
    "client_affinities",
    "server_affinity",
)
REPORT_CMN_USER_CFG = user_cfg_schema("detect", "diagram", "secure_access")
