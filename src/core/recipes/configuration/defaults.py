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

from asct.core.recipes.configuration.schema import mem_size_conv

# -----------------------------------------------------------------------------
# Default configuration templates
# -----------------------------------------------------------------------------
# Static per-recipe defaults are declared here and referenced by metadata entries.
BENCHMARK_BASE_DEFAULT_CONFIG = {
    "pmu_mode": False,
    "duration": 0.25,
    "iterations": 100000,
    "data_size": None,
    "bw_delay": 0,
}

# Used by: idle-latency, peak-bandwidth, cross-numa-bandwidth, latency-sweep,
# bandwidth-sweep, loaded-latency
MEMORY_DEFAULT_CONFIG = {
    **BENCHMARK_BASE_DEFAULT_CONFIG,
    "cycle_base": False,
}

C2C_DEFAULT_CONFIG = {
    **BENCHMARK_BASE_DEFAULT_CONFIG,
    "iterations": 400,
    "number_of_runs": 1,
    "node_mask": None,
    "heatmap_vmax": 200,
    "all_cpus": False,
    "hist_bins": 10,
}

LOADED_LATENCY_DEFAULT_CONFIG = {
    **MEMORY_DEFAULT_CONFIG,
    "injected_nops": [3000, 900, 500, 180, 100, 80, 70, 50, 40, 30, 20, 10, 0],
    "phase": "both",
    # Runtime-specific values are intentionally omitted here and
    # are resolved in recipe class _create_default_config():
    # latency_cpu_id and bw_cpu_blocklist.
}

# Shared by all storage sweep recipes:
# storage-request-size-sweep, storage-io-depth-sweep,
# storage-process-count-sweep, storage-access-pattern-sweep.
STORAGE_BASE_DEFAULT_CONFIG = {
    **BENCHMARK_BASE_DEFAULT_CONFIG,
    "duration": 60,
    "blocksize": 4 * 1024,
    "ioengine": "libaio",
    # Alternative asynchronous ioengines to consider if the requested one is not available.
    "alternative_ioengines": ["io_uring", "posixaio"],
    "iodepth": 16,
    "numjobs": 4,
    "rw_pattern": "randread",
    "rwmixread": 70,
    "filesize": mem_size_conv("1000MiB"),
    "filenames": [],
    "create_temp_file": True,
    "direct": True,
}

STORAGE_REQUEST_SIZE_DEFAULT_CONFIG = {
    **STORAGE_BASE_DEFAULT_CONFIG,
    "request_size_sweep_steps": [4 * 1024, 8 * 1024, 16 * 1024, 32 * 1024, 64 * 1024, 128 * 1024],
}

STORAGE_IO_DEPTH_DEFAULT_CONFIG = {
    **STORAGE_BASE_DEFAULT_CONFIG,
    "iodepth_sweep_steps": [2**i for i in range(8)],
}

STORAGE_PROCESS_COUNT_DEFAULT_CONFIG = {
    **STORAGE_BASE_DEFAULT_CONFIG,
    "process_count_sweep_steps": [1, 2, 4, 8, 16],
}

STORAGE_ACCESS_PATTERN_DEFAULT_CONFIG = {
    **STORAGE_BASE_DEFAULT_CONFIG,
    "access_pattern_sweep_steps": ["read", "write", "randread", "randwrite", "rw", "randrw"],
}

REPORT_CMN_DEFAULT_CONFIG = {
    "detect": False,
    "diagram": False,
    "secure_access": False,
}

IPERF3_DEFAULT_CONFIG = {
    "server_host": None,
    "port": None,
    "client_affinities": [],
    "server_affinity": None,
    "duration_sweep_steps": [10],
    "window_sweep_steps": [None],
    "message_size_sweep_steps": [1460],
    "bandwidth_target_bps_sweep_steps": [None],
    "number_of_runs": 1,
}

IPERF3_SWEEP_DEFAULT_CONFIG = {
    **IPERF3_DEFAULT_CONFIG,
    "port": 5202,
    "message_size_sweep_steps": [131072],
    "bandwidth_target_bps_sweep_steps": [None],
}
