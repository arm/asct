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

import json
import os

import pytest

from asct.core.utility.misc import flatten_dict

from .data_validation_memory import validate_result
from .test_memory import get_sysreport
from .utils import run_asct


@pytest.mark.parametrize("phase", ["loading", "bandwidth"])
def test_loaded_latency_user_loading(test_work_dir, phase):
    """
    Verifies loaded-latency benchmark accepts specific update-config overrides for two phases:
    loading and bandwidth. Ensures run succeeds and configuration entries are reflected in stderr.
    """
    sysreport = get_sysreport(test_work_dir)

    # Get the last core of the first NUMA node
    latency_cpu_id = sysreport["sys_hw"]["numa_nodes"]["0"][1][-1]

    # second and third cores of the first NUMA node
    bw_cpu_blocklist = [1, 2]

    # Build --update-config arguments exactly as feature documentation / example command
    user_config_args = [
        "--update-config",
        "loaded-latency.injected_nops=0",
        "loaded-latency.workload_cmd=sleep 5",
        f"loaded-latency.phase={phase}",
        f"loaded-latency.bw_cpu_blocklist={','.join(map(str, bw_cpu_blocklist))}",
        f"loaded-latency.latency_cpu_id={latency_cpu_id}",
    ]

    cmd_args = ["loaded-latency", *user_config_args]

    result = run_asct(
        "run",
        cmd_args,
        output_dir=os.path.join(test_work_dir, f"stdout-loaded-latency-{phase}"),
    )

    expected_outputs = [
        f"bw_cpu_blocklist: {bw_cpu_blocklist}",
        f"phase: {phase}",
        "workload_cmd: sleep 5",
        "injected_nops: [0]",
        f"latency_cpu_id: {latency_cpu_id}",
    ]

    assert result.ret_code == 0, f"ASCT failed to run loaded-latency:\n{result.stderr}"
    for expected in expected_outputs:
        assert expected in result.stderr, f"Expected config '{expected}' not found in output"


def test_update_config(test_work_dir):
    full_name = "loaded-latency"
    short_name = "ll"

    sysreport = get_sysreport(test_work_dir)

    for bench_name in [full_name, short_name]:
        user_config_overwrite = {bench_name: {"data_size": "0.5MiB"}}

        user_config = {bench_name: {"data_size": "2MiB", "duration": "0.0025m", "non-existing": "1"}}

        expected_conversions = {"0.5MiB": "524288", "2MiB": "2097152", "0.0025m": "0.15"}

        for mode in ["cli", "file", "file_cli"]:
            cmd_line_args = [full_name, "--quick-mode", "--force"]
            if "file" in mode:
                config_file = os.path.join(test_work_dir, "user_config.conf")
                with open(config_file, "wt") as config_file_handle:
                    json.dump(user_config_overwrite if "cli" in mode else user_config, config_file_handle)
                cmd_line_args = [*cmd_line_args, "--config-file", config_file]
            if "cli" in mode:
                flat = flatten_dict(user_config)
                cmd_line_args = [*cmd_line_args, "--update-config", *[f"{key}={value}" for key, value in flat.items()]]

            result = run_asct("run", cmd_line_args, output_dir=os.path.join(test_work_dir, "stdout"))
            validate_result(result, [full_name], sysreport, "stdout", True, True)

            for config in user_config.values():
                for key, value in config.items():
                    if key != "non-existing":
                        expected_string = f"  {key}: {expected_conversions[value]}"
                    else:
                        expected_string = f"Invalid config path: {full_name}.{key}"
                    assert expected_string in result.stderr, f"{expected_string} config not found in output"
