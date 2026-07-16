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

import os
import pytest

from .utils import run_asct


def extract_node_to_node_medians(stdout, section_title):
    """
    Extracts the node-to-node median latency matrix from the stdout for a given section.
    Returns a dict of dicts: {src_node: {dst_node: median}}
    """
    lines = stdout.splitlines()
    medians = {}
    try:
        # Find section and matrix header
        idx = next(i for i, line in enumerate(lines) if section_title in line)
        idx = next(i for i in range(idx, len(lines)) if lines[i].startswith("        Node"))
        header = lines[idx].split()[1:]
        medians = {}
        for line in lines[idx + 1 :]:
            if not line.strip() or not line.startswith("Node"):
                break

            if "-" in line:
                continue
            parts = line.split()
            src = parts[0]
            medians[src] = {dst: float(val) for dst, val in zip(header, parts[1:], strict=False)}
    except StopIteration:
        return {}

    return medians


@pytest.mark.parametrize("output_format", ["stdout", "json", "csv"])
def test_core_to_core_latency_integration(test_work_dir, output_format):
    """
    Integration test for core-to-core-latency benchmark.
    Checks output files and validates median values in all formats.
    """
    work_dir = os.path.join(test_work_dir, output_format)
    result = run_asct("run", ["c2c-latency", "--format", output_format, "--quick-mode"], output_dir=work_dir)

    if output_format == "stdout":
        # Check that the stdout contains the expected summary sections
        assert "Core-to-Core Latency Summary (ns): Data Address @ Local Numa Node" in result.stdout
        assert "Node-to-Node Median Latency Matrix (ns):" in result.stdout
        # Extract and check median latencies
        medians_local = extract_node_to_node_medians(result.stdout, "Data Address @ Local Numa Node")
        medians_remote = extract_node_to_node_medians(result.stdout, "Data Address @ Remote Numa Node")
        # Check that the median latencies are present and are floats
        for medians in (medians_local, medians_remote):
            assert all(isinstance(val, float) for dsts in medians.values() for val in dsts.values())

    elif output_format == "json":
        # Check that report.json exists and contains the right keys
        assert "report.json" in result.json_file_content
        json_data = result.json_file_content["report.json"]
        assert "memory" in json_data
        assert "c2c-latency" in json_data["memory"]
    elif output_format == "csv":
        # Check that c2c-latency.csv exists and is non-empty
        assert "c2c-latency.csv" in result.csv_file_content
        csv_data = result.csv_file_content["c2c-latency.csv"]
        assert len(csv_data) > 0
        assert ["", "CPUA", "CPUB", "LATENCY", "CPUA_NODE", "MEMBIND_NODE"] == csv_data[0]  # Header check
        # Check that the CSV data has the expected number of columns
        assert len(csv_data[1]) == 6
        # Check that the latency value can be converted to float
        assert isinstance(float(csv_data[1][3]), float)


# Generate testing for using --update-config with c2c-latency
@pytest.mark.parametrize("all_cpus", [True, False])
def test_core_to_core_latency_update_config(test_work_dir, all_cpus):
    """
    Test c2c-latency with various --update-config settings.
    """
    work_dir = os.path.join(test_work_dir, "user_config", str(all_cpus))
    config_str = f"c2c-latency.all_cpus={all_cpus}"
    result = run_asct("run", ["c2c-latency", "--quick-mode", "--update-config", config_str], output_dir=work_dir)

    expected = "data addr @ node" if all_cpus else "measuring c2c latency"
    assert expected in result.stderr
