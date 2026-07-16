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
import json
from pathlib import Path
import pytest
from .utils import run_asct
from asct.core.utility.misc import flatten_dict


def create_fake_run_dir(tmp_path, run_data):
    """
    Creates mock run directories with asct.json files using provided run_data.
    Args:
        tmp_path: pytest tmp_path fixture.
        run_data: List of dicts, each dict is the content for one asct.json.
    Returns:
        List of str paths to created run directories.
    """
    run_dirs = []
    for i, data in enumerate(run_data, start=1):
        run_dir = tmp_path / f"run_dir{i}"
        run_dir.mkdir()
        with open(run_dir / "asct.json", "w") as f:
            json.dump(data, f)
        run_dirs.append(str(run_dir))
    return run_dirs


# fixture to provide for mock run directories with fake asct.json files
# and fake run data
@pytest.fixture
def setup_run_dirs(tmp_path):
    c2c_raw_result1 = {
        "CPUA": {"0": 0, "1": 1},
        "CPUB": {"0": 1, "1": 0},
        "LATENCY": {"0": 95.0, "1": 95.0},
        "CPUA_NODE": {"0": 0, "1": 0},
        "MEMBIND_NODE": {"0": 0, "1": 0},
    }
    c2c_raw_result2 = {
        "CPUA": {"0": 0, "1": 1},
        "CPUB": {"0": 1, "1": 0},
        "LATENCY": {"0": 98.0, "1": 98.0},
        "CPUA_NODE": {"0": 0, "1": 0},
        "MEMBIND_NODE": {"0": 0, "1": 0},
    }
    c2c_raw_result3 = {
        "CPUA": {"0": 0, "1": 1},
        "CPUB": {"0": 1, "1": 0},
        "LATENCY": {"0": 95.0, "1": 95.0},
        "CPUA_NODE": {"0": 0, "1": 0},
        "MEMBIND_NODE": {"0": 0, "1": 0},
    }
    peak_bw_raw_result1 = {
        "Traffic type": {"0": "All Reads", "1": "All Writes", "2": "Copy", "3": "Total"},
        "Peak BW [GB/s]": {"0": 500.0, "1": 300.0, "2": 400.0, "3": 1200.0},
    }
    system_info_raw_result1 = {
        "sys_info": {"manufacturer": "ubuntu"},
        "memory": {"total_size": 8},
    }
    system_info_raw_result2 = {
        "sys_info": {"manufacturer": "ubuntu"},
        "memory": {"total_size": 8},
    }
    system_info_raw_result3 = {
        "sys_info": {"manufacturer": "ubuntu"},
        "memory": {"total_size": 16},
    }

    asct_json_content1 = {
        "metadata": {
            "cmd_arguments": {"command": "asct run"},
            "version": "2.0.1",
        },
        "raw": {
            "c2c-latency": c2c_raw_result1,
            "system-info": system_info_raw_result1,
            "peak-bandwidth": peak_bw_raw_result1,
        },
    }

    asct_json_content2 = {
        "metadata": {
            "cmd_arguments": {"command": "asct run c2c-latency --quick-mode"},
            "version": "2.0.1",
        },
        "raw": {
            "c2c-latency": c2c_raw_result2,
            "system-info": system_info_raw_result2,
        },
    }

    asct_json_content3 = {
        "metadata": {
            "cmd_arguments": {"command": "asct run c2c-latency --quick-mode"},
            "version": "2.0.1",
        },
        "raw": {
            "c2c-latency": c2c_raw_result3,
            "system-info": system_info_raw_result3,
        },
    }

    run_data = [asct_json_content1, asct_json_content2, asct_json_content3]

    return create_fake_run_dir(tmp_path, run_data)


def create_run_dir(parent_dir: Path, run_name: str, run_data: dict) -> str:
    run_dir = parent_dir / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    run_dir.joinpath("asct.json").write_text(json.dumps(run_data))
    return str(run_dir)


def extract_measurement_table(stdout: str) -> str:
    lines = stdout.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("Measurement Delta Percentage Between "))

    for i in range(start + 1, len(lines)):
        line = lines[i]
        if line and not line.startswith(("=", "-")) and " | " not in line:
            return "\n".join(lines[start:i]).strip()

    return "\n".join(lines[start:]).strip()


def make_memory_run(
    peak_bandwidth: list[tuple[str, float]],
    loaded_latency: list[tuple[int, float, float]],
    latency_sweep: dict[str, dict[str, float]],
    bandwidth_sweep: dict[str, dict[str, float]],
) -> dict:
    peak_bw_raw_result = {"Traffic type": {}, "Peak BW [GB/s]": {}}
    for idx, (traffic_name, value) in enumerate(peak_bandwidth):
        idx = str(idx)
        peak_bw_raw_result["Traffic type"][idx] = traffic_name
        peak_bw_raw_result["Peak BW [GB/s]"][idx] = value

    loaded_latency_raw_result = {
        "Injected NOPs": {},
        "Loaded latency [ns]": {},
        "Bandwidth [GB/s]": {},
    }
    for idx, (nops, latency_ns, bandwidth_gbps) in enumerate(loaded_latency):
        idx = str(idx)
        loaded_latency_raw_result["Injected NOPs"][idx] = nops
        loaded_latency_raw_result["Loaded latency [ns]"][idx] = latency_ns
        loaded_latency_raw_result["Bandwidth [GB/s]"][idx] = bandwidth_gbps

    bandwidth_key = next(key for key in next(iter(bandwidth_sweep.values())) if key.startswith("Bandwidth"))
    bandwidth_summary = {"Datasize Used": {}, "Level": {}, bandwidth_key: {}}
    for idx, (level_name, values) in enumerate(bandwidth_sweep.items()):
        idx = str(idx)
        bandwidth_summary["Datasize Used"][idx] = values["Datasize Used"]
        bandwidth_summary["Level"][idx] = level_name
        bandwidth_summary[bandwidth_key][idx] = values[bandwidth_key]

    return {
        "metadata": {
            "version": "0.5.0",
            "cmd_arguments": {"command": "run"},
        },
        "raw": {
            "peak-bandwidth": {
                "raw_result": peak_bw_raw_result,
                "metadata": {"name": "peak-bandwidth"},
            },
            "loaded-latency": {
                "raw_result": loaded_latency_raw_result,
                "metadata": {"name": "loaded-latency"},
            },
            "latency-sweep": {
                "raw_result": {
                    "sweep_data": {
                        "sizes": {"0": 128, "1": 256, "2": 4096},
                        "repetitions": {"0": 10, "1": 10, "2": 10},
                        "average_latency_ns": {"0": 1.0, "1": 2.0, "2": 10.0},
                        "average_latency_cyc": {"0": 3.0, "1": 6.0, "2": 30.0},
                    },
                    "summary": latency_sweep,
                },
                "metadata": {"name": "latency-sweep", "config": {"cycle_base": False}},
            },
            "bandwidth-sweep": {
                "raw_result": {
                    "sweep_data": {
                        "sizes": {"0": 128, "1": 256, "2": 4096},
                        "repetitions": {"0": 10, "1": 10, "2": 10},
                        "total_bandwidth_mbps": {"0": 500000.0, "1": 400000.0, "2": 300000.0},
                        "total_bandwidth_bpc": {"0": 100.0, "1": 80.0, "2": 60.0},
                    },
                    "summary": bandwidth_summary,
                },
                "metadata": {"name": "bandwidth-sweep", "config": {"cycle_base": False}},
            },
        },
    }


def build_legacy_run_data_from(current_run: dict) -> dict:
    legacy_run = {
        "diff": {
            "metadata.version": "0.5.0",
            "metadata.cmd_arguments.command": current_run["metadata"]["cmd_arguments"]["command"],
        },
        "raw": {},
    }

    peak_bw_raw_result = current_run["raw"]["peak-bandwidth"]["raw_result"]
    legacy_run["raw"]["peak-bandwidth"] = peak_bw_raw_result
    for idx, traffic_name in peak_bw_raw_result["Traffic type"].items():
        legacy_run["diff"][f"peak-bandwidth.data.{traffic_name}.Peak BW [GB/s]"] = peak_bw_raw_result["Peak BW [GB/s]"][
            idx
        ]

    loaded_latency_raw_result = current_run["raw"]["loaded-latency"]["raw_result"]
    legacy_run["raw"]["loaded-latency"] = loaded_latency_raw_result

    latency_sweep_raw_result = current_run["raw"]["latency-sweep"]["raw_result"]
    legacy_run["raw"]["latency-sweep"] = json.dumps(latency_sweep_raw_result["sweep_data"])
    for path, value in flatten_dict(latency_sweep_raw_result["summary"]).items():
        legacy_run["diff"][f"latency-sweep.data.{path}"] = value

    bandwidth_sweep_raw_result = current_run["raw"]["bandwidth-sweep"]["raw_result"]
    legacy_run["raw"]["bandwidth-sweep"] = json.dumps(bandwidth_sweep_raw_result["sweep_data"])
    summary = bandwidth_sweep_raw_result["summary"]
    bandwidth_key = next(key for key in summary if key.startswith("Bandwidth"))
    for idx, level_name in summary["Level"].items():
        legacy_run["diff"][f"bandwidth-sweep.data.{level_name}.Datasize Used"] = summary["Datasize Used"][idx]
        legacy_run["diff"][f"bandwidth-sweep.data.{level_name}.{bandwidth_key}"] = summary[bandwidth_key][idx]

    return legacy_run


@pytest.mark.parametrize("output_format", ["stdout", "json", "csv"])
def test_sysdiff_integration(test_work_dir, output_format, setup_run_dirs):
    """
    Tests sysdiff integration with different output formats.
    Args:
        test_work_dir: pytest tmp_path fixture for working directory.
        output_format: Output format to test ("stdout", "json", "csv").
        setup_run_dirs: Fixture providing list of mock run directories.
    """
    work_dir = os.path.join(test_work_dir, output_format)
    result = run_asct(
        "diff",
        [*setup_run_dirs, "--format", output_format],
        output_dir=work_dir if output_format != "stdout" else None,
    )
    if output_format == "stdout":
        expect_stdout = [
            "Total # of Benchmarks | 4",
            "Measurement Delta Percentage Between Run_Dir1 And Comparison Runs",
            "Differences In System-Info",
            "field|run_dir1|run_dir2|run_dir3",
            "c2c-latency.Local.mean|95.0|3.16%|<same as baseline>",
            "peak-bandwidth.Total.Peak BW [GB/s]|1200.0|N/A|N/A",
            "system-info.memory.total_size|8|16|<same as baseline>",
        ]
        # Check that sysdiff summary is in stdout
        output = result.stdout.replace("\n", "").replace(" ", "")
        for expected in expect_stdout:
            assert expected.replace(" ", "") in output, f"Expected '{expected}' in stdout"

    elif output_format == "json":
        # Check that diff.json exists and contains the right keys
        assert "diff.json" in result.json_file_content
        json_data = result.json_file_content["diff.json"]
        data_key = "peak-bandwidth.Total.Peak BW [GB/s]"
        found = False

        # Check that the expected entry is in diff.json
        for data in json_data:
            if data.get("field") == data_key:
                found = True
                assert data.get("recipe") == "peak-bandwidth"
                assert data.get("comparator") == "<missing>"
                assert data.get("delta") == "removed"
                assert data.get("delta_percent") == "N/A"
                assert data.get("baseline") == "1200.0"
                assert data.get("run") == "run_dir2" or data.get("run") == "run_dir3"

        assert found, f"Expected to find entry with field '{data_key}' in diff.json"

    elif output_format == "csv":
        # Check that diff.csv exists and contains the right headers and data
        assert "diff.csv" in result.csv_file_content
        csv_data = result.csv_file_content["diff.csv"]
        expected_headers = ["", "field", "recipe", "run", "comparator", "delta", "delta_percent", "baseline"]
        headers = [h.strip() for h in csv_data[0]]
        assert headers == expected_headers, f"Expected headers {expected_headers}, got {headers}"

        data_key = "peak-bandwidth.Total.Peak BW [GB/s]"
        found = False

        # Check that the expected entry is in diff.csv
        # format 0,peak-bandwidth.result.copy,peak-bandwidth,run_dir2,<missing>,removed,N/A,400
        for row in csv_data[1:]:
            if row[1].strip() == data_key:
                found = True
                assert row[2].strip() == "peak-bandwidth"
                assert row[3].strip() == "run_dir2" or row[3].strip() == "run_dir3"
                assert row[4].strip() == "<missing>"
                assert row[5].strip() == "removed"
                assert row[6].strip() == "N/A"
                assert row[7].strip() == "1200.0"

        assert found, f"Expected to find entry with field '{data_key}' in diff.csv"


# Select specific benchmarks to include/exclude (^ for exclude)
@pytest.mark.parametrize("benchmarks", [["system-info", "peak-bandwidth"], ["^system-info", "^peak-bandwidth"]])
def test_sysdiff_select_benchmarks_integration(benchmarks, setup_run_dirs):
    """
    Tests sysdiff integration with benchmark selection (inclusion/exclusion).
    Args:
        test_work_dir: pytest tmp_path fixture for working directory.
        benchmarks: List of benchmarks to include or exclude (prefix with ^ to exclude).
        setup_run_dirs: Fixture providing list of mock run directories.
    """
    result = run_asct("diff", [*setup_run_dirs, "--benchmarks", *benchmarks], output_dir=None)
    output = result.stdout.replace("\n", "").replace(" ", "")

    if "^system-info" in benchmarks and "^peak-bandwidth" in benchmarks:
        assert "system-info" not in output, "Did not expect system-info differences in stdout"
        assert "peak-bandwidth" not in output, "Did not expect peak-bandwidth differences in stdout"

    elif "system-info" in benchmarks and "peak-bandwidth" in benchmarks:
        assert "system-info" in output, "Expected system-info differences in stdout"
        assert "peak-bandwidth" in output, "Expected peak-bandwidth differences in stdout"


# Select specific baselines for the comparison.
# Scope to system-info so the test only exercises baseline selection, not the
# fixture's intentionally lightweight c2c-latency placeholder payload.
@pytest.mark.parametrize("baseline", ["run_dir2", "run_dir3"])
def test_sysdiff_select_baselines_integration(baseline, setup_run_dirs):
    """
    Tests sysdiff integration with baseline selection.
    Args:
        test_work_dir: pytest tmp_path fixture for working directory.
        baseline: Baseline directory to include.
        setup_run_dirs: Fixture providing list of mock run directories.
    """
    baseline_path = baseline
    for paths in setup_run_dirs:
        if baseline in paths:
            baseline_path = paths
            break

    result = run_asct(
        "diff",
        [*setup_run_dirs, "--baseline", baseline_path, "--benchmarks", "system-info"],
        output_dir=None,
    )
    output = result.stdout.replace("\n", "").replace(" ", "")

    assert f"Baseline|{baseline}" in output, f"Expected baseline '{baseline}' in stdout"


def test_sysdiff_invalid_args(test_work_dir, setup_run_dirs):
    """
    Tests sysdiff integration with invalid arguments.
    Args:
        test_work_dir: pytest tmp_path fixture for working directory.
        setup_run_dirs: Fixture providing list of mock run directories.
    """
    work_dir = os.path.join(test_work_dir, "test_sysdiff_invalid_args")

    # Test with only one run dir and no baseline
    result = run_asct("diff", [setup_run_dirs[0]], output_dir=work_dir)
    assert "Provide at least two unique run directories" in result.stderr

    # Test with baseline same as run dir
    work_dir = os.path.join(test_work_dir, "test_sysdiff_invalid_args_baseline")
    result = run_asct("diff", [setup_run_dirs[0], "--baseline", setup_run_dirs[0]], output_dir=work_dir)
    assert "Provide at least two unique run directories" in result.stderr

    # # Test with --sort-by not in comparison runs
    work_dir = os.path.join(test_work_dir, "test_sysdiff_invalid_args_sortby")
    result = run_asct(
        "diff",
        [setup_run_dirs[0], setup_run_dirs[1], "--baseline", setup_run_dirs[2], "--sort-by", "nonexistent_dir"],
        output_dir=work_dir,
    )
    assert "--sort-by must be one of the comparison run directories" in result.stderr


def test_sysdiff_rejects_older_version_run(test_work_dir, tmp_path):
    old_run = make_memory_run(
        peak_bandwidth=[("All Reads", 257.69)],
        loaded_latency=[(10, 120.0, 40.0)],
        latency_sweep={
            "Lower Bound": {"L1": 128},
            "Upper Bound": {"L1": 256},
            "Optimum Datasize": {"L1": 192},
            "Latency [ns]": {"L1": 1.10},
        },
        bandwidth_sweep={
            "L1": {"Datasize Used": 192, "Bandwidth [GB/s]": 538.75},
        },
    )
    old_run["metadata"]["version"] = "0.3.9"

    current_run = make_memory_run(
        peak_bandwidth=[("All Reads", 272.74)],
        loaded_latency=[(10, 150.0, 38.0)],
        latency_sweep={
            "Lower Bound": {"L1": 160},
            "Upper Bound": {"L1": 320},
            "Optimum Datasize": {"L1": 224},
            "Latency [ns]": {"L1": 1.35},
        },
        bandwidth_sweep={
            "L1": {"Datasize Used": 224, "Bandwidth [GB/s]": 525.10},
        },
    )

    run_a = create_run_dir(tmp_path, "run_a", old_run)
    run_b = create_run_dir(tmp_path, "run_b", current_run)

    result = run_asct(
        "diff",
        [run_a, run_b],
        output_dir=os.path.join(test_work_dir, "test_sysdiff_rejects_older_version_run"),
        assert_on_failure=False,
    )

    assert "diff.json" not in result.json_file_content
    assert "diff.csv" not in result.csv_file_content
    assert "ASCT version '0.3.9' results are not supported" in result.stderr


def test_sysdiff_stdout_handles_mixed_legacy_and_current_graph_payloads(test_work_dir, tmp_path):
    legacy_run = {
        "metadata": {
            "cmd_arguments": {"command": "asct run latency-sweep loaded-latency"},
            "version": "0.5.0",
        },
        "raw": {
            "latency-sweep": json.dumps({
                "sizes": {"0": 128, "1": 256},
                "repetitions": {"0": 10, "1": 10},
                "average_latency_ns": {"0": 1.0, "1": 2.0},
                "average_latency_cyc": {"0": 3.0, "1": 6.0},
            }),
            "loaded-latency": {
                "Injected NOPs": {"0": 10, "1": 0},
                "Loaded latency [ns]": {"0": 120.0, "1": 240.0},
                "Bandwidth [GB/s]": {"0": 10.0, "1": 20.0},
            },
            "system-info": {"os": {"0": "ubuntu"}},
        },
    }

    current_run = {
        "metadata": {
            "cmd_arguments": {"command": "asct run latency-sweep loaded-latency"},
            "version": "0.5.0",
        },
        "raw": {
            "latency-sweep": {
                "raw_result": {
                    "sweep_data": {
                        "sizes": {"0": 128, "1": 256},
                        "repetitions": {"0": 10, "1": 10},
                        "average_latency_ns": {"0": 1.1, "1": 2.2},
                        "average_latency_cyc": {"0": 3.3, "1": 6.6},
                    }
                },
                "metadata": {"name": "latency-sweep", "config": {"cycle_base": False}},
            },
            "loaded-latency": {
                "raw_result": {
                    "Injected NOPs": {"0": 10, "1": 0},
                    "Loaded latency [ns]": {"0": 121.0, "1": 242.0},
                    "Bandwidth [GB/s]": {"0": 11.0, "1": 21.0},
                },
                "metadata": {"name": "loaded-latency", "config": {"cycle_base": False}},
            },
            "system-info": {"raw_result": {"os": {"0": "ubuntu"}}, "metadata": {"name": "system-info"}},
        },
    }

    run_dirs = create_fake_run_dir(tmp_path, [legacy_run, current_run])
    work_dir = os.path.join(test_work_dir, "test_sysdiff_stdout_handles_mixed_graph_payloads")

    result = run_asct("diff", run_dirs, output_dir=work_dir)

    assert "Error occurred:" not in result.stderr
    assert "latency-sweep_ns.png" in result.png_file_content
    assert "latency-sweep_cycle.png" in result.png_file_content
    assert "loaded-latency_ns.png" in result.png_file_content


def test_diff_backwards_compatibility(test_work_dir, tmp_path):
    new_a = make_memory_run(
        peak_bandwidth=[
            ("All Reads", 257.69),
            ("1:1 Reads-Writes", 104.47),
        ],
        loaded_latency=[
            (10, 120.0, 40.0),
            (100, 180.0, 25.0),
        ],
        latency_sweep={
            "Lower Bound": {"L1": 128, "DRAM": 8192},
            "Upper Bound": {"L1": 256, "DRAM": 16384},
            "Optimum Datasize": {"L1": 192, "DRAM": 12288},
            "Latency [ns]": {"L1": 1.10, "DRAM": 99.25},
        },
        bandwidth_sweep={
            "L1": {"Datasize Used": 192, "Bandwidth [GB/s]": 538.75},
            "DRAM": {"Datasize Used": 12288, "Bandwidth [GB/s]": 27.43},
        },
    )
    new_b = make_memory_run(
        peak_bandwidth=[
            ("All Reads", 272.74),
            ("1:1 Reads-Writes", 97.31),
        ],
        loaded_latency=[
            (10, 150.0, 38.0),
            (100, 210.0, 22.0),
        ],
        latency_sweep={
            "Lower Bound": {"L1": 160, "DRAM": 16384},
            "Upper Bound": {"L1": 320, "DRAM": 32768},
            "Optimum Datasize": {"L1": 224, "DRAM": 24576},
            "Latency [ns]": {"L1": 1.35, "DRAM": 110.50},
        },
        bandwidth_sweep={
            "L1": {"Datasize Used": 224, "Bandwidth [GB/s]": 525.10},
            "DRAM": {"Datasize Used": 24576, "Bandwidth [GB/s]": 25.00},
        },
    )
    legacy_a = build_legacy_run_data_from(new_a)
    legacy_b = build_legacy_run_data_from(new_b)
    datasets = {
        "legacy_a": legacy_a,
        "new_a": new_a,
        "legacy_b": legacy_b,
        "new_b": new_b,
    }
    combinations = {
        "legacy_legacy": ("legacy_a", "legacy_b"),
        "legacy_new": ("legacy_a", "new_b"),
        "new_legacy": ("new_a", "legacy_b"),
        "new_new": ("new_a", "new_b"),
    }

    tables = {}
    for combo_name, (run_a_key, run_b_key) in combinations.items():
        combo_dir = tmp_path / combo_name
        run_a = create_run_dir(combo_dir, "run_a", datasets[run_a_key])
        run_b = create_run_dir(combo_dir, "run_b", datasets[run_b_key])

        result = run_asct("diff", [run_a, run_b], output_dir=os.path.join(test_work_dir, combo_name))
        tables[combo_name] = extract_measurement_table(result.stdout)

    reference_combo = "legacy_legacy"
    reference_table = tables[reference_combo]
    for combo_name, table in tables.items():
        assert table == reference_table, (
            f"Expected measurement table for {combo_name} to match {reference_combo}\n"
            f"{combo_name}:\n{table}\n\n{reference_combo}:\n{reference_table}"
        )
