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

from dataclasses import dataclass
import json
from types import SimpleNamespace

import pytest

from asct.core.cmd import resume
from asct.core.managers.ubench_reporter import get_reporter
from asct.core.utility.files import hash_saved_recipe_files
from asct.lib.run.result_loader import load_saved_recipe


@dataclass
class _FakeSysHw:
    arch: str
    cpu_features: list[str]


@dataclass
class _FakeSystemInfo:
    sys_hw: _FakeSysHw
    ready: bool = True


def test_check_hw_match_returns_saved_system_info(monkeypatch):
    current = _FakeSystemInfo(sys_hw=_FakeSysHw(arch="x86_64", cpu_features=["fpu", "vme"]))
    saved = _FakeSystemInfo(sys_hw=_FakeSysHw(arch="x86_64", cpu_features=["fpu", "vme"]))

    monkeypatch.setattr(resume, "load_saved_recipe", lambda _output_dir, _recipe_name: saved)

    assert resume.check_hw_match("run-dir", current) is saved


def test_check_hw_match_rejects_first_hardware_difference(monkeypatch):
    current = _FakeSystemInfo(sys_hw=_FakeSysHw(arch="aarch64", cpu_features=["fpu", "vme"]))
    saved = _FakeSystemInfo(sys_hw=_FakeSysHw(arch="x86_64", cpu_features=["fpu", "vme"]))

    monkeypatch.setattr(resume, "load_saved_recipe", lambda _output_dir, _recipe_name: saved)

    with pytest.raises(RuntimeError, match=r"hardware changes detected after run: arch:aarch64 \(was x86_64\)"):
        resume.check_hw_match("run-dir", current)


def test_check_hw_match_rejects_missing_saved_system_info(monkeypatch):
    current = _FakeSystemInfo(sys_hw=_FakeSysHw(arch="x86_64", cpu_features=["fpu", "vme"]))

    monkeypatch.setattr(resume, "load_saved_recipe", lambda _output_dir, _recipe_name: None)

    with pytest.raises(RuntimeError, match=r"saved system-info results in run-dir are missing or invalid"):
        resume.check_hw_match("run-dir", current)


def test_resume_load_run_results_hydrates_system_info(tmp_path):
    recipe_dir = tmp_path / "raw" / "system-info"
    recipe_dir.mkdir(parents=True)

    raw_result = {
        "report": {"collected_time": "2026-06-16 00:00:00+00:00", "asct_ver": "0.5.0", "run_as_root": False},
        "sys_hw": {
            "arch": "x86_64",
            "cpu_features": ["fpu", "vme"],
            "interconnect": [None, 1],
            "numa_nodes": {"0": [1024, [0, 1]]},
        },
        "memory": {"total_size": 1234},
        "kern_cfg": {"ver": "6.8.0"},
        "perf_feats": {"bpf": {"bpf": True}},
    }
    data_json = json.dumps(raw_result)
    metadata_json = json.dumps({"description": "saved system info"})
    (recipe_dir / "data.json").write_text(data_json)
    (recipe_dir / "metadata.json").write_text(metadata_json)
    (recipe_dir / ".hash").write_text(
        hash_saved_recipe_files({
            "data.json": data_json.encode(),
            "metadata.json": metadata_json.encode(),
        })
    )

    recipe = load_saved_recipe(str(tmp_path), "system-info")

    assert recipe._loaded_from_saved_output is True
    assert recipe.result_metadata == {}
    assert (
        recipe.desc == "Output a report containing information about the hardware and software installed on the system."
    )
    assert recipe.memory.total_size == 1234
    assert recipe.sys_hw.arch == "x86_64"
    assert recipe.sys_hw.cpu_features == ["fpu", "vme"]
    assert recipe.sys_hw.interconnect == (None, 1)
    assert list(recipe.sys_hw.numa_nodes) == [0]
    assert recipe.sys_hw.numa_nodes[0][0] == 1024
    assert recipe.kern_cfg.ver == "6.8.0"
    assert recipe.perf_feats.bpf.bpf is True
    csv = recipe.to_csv_str()
    assert "(None, 1)" in csv
    assert "[None, 1]" not in csv
    assert "(1024, [0, 1])" in csv
    assert "[1024, [0, 1]]" not in csv


def test_resume_load_run_results_restores_c2c_stdout_shape(tmp_path, capsys):
    recipe_dir = tmp_path / "raw" / "c2c-latency"
    recipe_dir.mkdir(parents=True)

    raw_result = {
        "CPUA": {"0": 0, "1": 0, "2": 1, "3": 2},
        "CPUB": {"0": 1, "1": 2, "2": 0, "3": 0},
        "LATENCY": {"0": 10.0, "1": 20.0, "2": 11.0, "3": 21.0},
        "CPUA_NODE": {"0": 0, "1": 0, "2": 0, "3": 1},
        "MEMBIND_NODE": {"0": 0, "1": 1, "2": 0, "3": 0},
    }
    data_json = json.dumps(raw_result)
    metadata_json = json.dumps({
        "description": "saved c2c",
        "config": {"all_cpus": False, "hist_bins": 10, "heatmap_vmax": 200},
    })
    (recipe_dir / "data.json").write_text(data_json)
    (recipe_dir / "metadata.json").write_text(metadata_json)
    (recipe_dir / ".hash").write_text(
        hash_saved_recipe_files({
            "data.json": data_json.encode(),
            "metadata.json": metadata_json.encode(),
        })
    )

    reporter = get_reporter()
    reporter.output_dir = str(tmp_path)
    reporter.current_benchmark = "c2c-latency"

    recipe = load_saved_recipe(str(tmp_path), "c2c-latency")
    recipe.to_stdout()
    output = capsys.readouterr().out

    assert "Core-to-Core Latency Summary (ns): Data Address @ Local Numa Node" in output
    assert "Node-to-Node Median Latency Matrix (ns):" in output
    assert "Top Latency Core Pairs with Median Latency" in output
    assert "Local latency statistics (ns):" not in output


def test_read_run_manifest_rejects_unsupported_version(tmp_path):
    (tmp_path / "asct.json").write_text(
        json.dumps({
            "metadata": {
                "version": "0.5.9",
                "is_sudo": False,
                "user_config": {},
                "cmd_arguments": {"benchmarks": ["loaded-latency"]},
            },
        })
    )

    with pytest.raises(RuntimeError, match=r"ASCT version '0\.5\.9' is not supported for resume"):
        resume.read_run_manifest(str(tmp_path))


def test_read_run_manifest_rejects_missing_version(tmp_path):
    (tmp_path / "asct.json").write_text(
        json.dumps({
            "metadata": {
                "is_sudo": False,
                "user_config": {},
                "cmd_arguments": {"benchmarks": ["loaded-latency"]},
            },
        })
    )

    with pytest.raises(TypeError, match=r"metadata\.version is missing"):
        resume.read_run_manifest(str(tmp_path))


def test_read_run_manifest_rejects_unsupported_legacy_diff_version(tmp_path):
    (tmp_path / "asct.json").write_text(
        json.dumps({
            "diff": {
                "metadata.version": "0.4.1",
            },
        })
    )

    with pytest.raises(RuntimeError, match=r"ASCT version '0\.4\.1' is not supported for resume"):
        resume.read_run_manifest(str(tmp_path))


def test_load_asct_run_args_uses_manifest_cmd_arguments_and_respects_format_override(tmp_path):
    (tmp_path / "asct.json").write_text(
        json.dumps({
            "metadata": {
                "version": "0.6.0",
                "is_sudo": resume._is_sudo_run(),
                "user_config": {},
                "cmd_arguments": {
                    "benchmarks": ["loaded-latency"],
                    "format": "json",
                    "quiet": "True",
                    "verbose": "True",
                    "no_progress_bar": "True",
                    "log_file": "None",
                    "log_level_console": "debug",
                    "quick_mode": "False",
                },
            },
        })
    )

    args = SimpleNamespace(run_dir=str(tmp_path), format=None)
    resume.load_asct_run_args(args)

    assert args.format == "json"
    assert args.quiet is True
    assert args.verbose is True
    assert args.no_progress_bar is True
    assert args.log_file is None
    assert args.log_level_console == "debug"
    assert args.quick_mode is False

    override_args = SimpleNamespace(run_dir=str(tmp_path), format="csv")
    resume.load_asct_run_args(override_args)
    assert override_args.format == "csv"


def test_read_run_manifest_rejects_non_list_benchmarks(tmp_path):
    (tmp_path / "asct.json").write_text(
        json.dumps({
            "metadata": {
                "version": "0.6.0",
                "is_sudo": resume._is_sudo_run(),
                "user_config": {},
                "cmd_arguments": {"benchmarks": "['loaded-latency', 'peak-bandwidth']"},
            },
        })
    )

    with pytest.raises(TypeError, match=r"metadata\.cmd_arguments\.benchmarks must be a list"):
        resume.read_run_manifest(str(tmp_path))


def test_read_run_manifest_rejects_empty_benchmarks(tmp_path):
    (tmp_path / "asct.json").write_text(
        json.dumps({
            "metadata": {
                "version": "0.6.0",
                "is_sudo": resume._is_sudo_run(),
                "user_config": {},
                "cmd_arguments": {"benchmarks": []},
            },
        })
    )

    with pytest.raises(RuntimeError, match=r"no requested benchmarks found in the manifest file"):
        resume.read_run_manifest(str(tmp_path))


def test_load_asct_run_args_rejects_mismatched_sudo_status(tmp_path, monkeypatch):
    (tmp_path / "asct.json").write_text(
        json.dumps({
            "metadata": {
                "version": "0.6.0",
                "is_sudo": True,
                "user_config": {},
                "cmd_arguments": {"benchmarks": ["loaded-latency"]},
            },
        })
    )

    monkeypatch.setattr(resume, "_is_sudo_run", lambda: False)

    with pytest.raises(
        RuntimeError, match=r"sudo status does not match the original run; run the resume command with sudo"
    ):
        resume.load_asct_run_args(SimpleNamespace(run_dir=str(tmp_path), format=None))


def test_read_run_manifest_rejects_non_boolean_is_sudo(tmp_path):
    (tmp_path / "asct.json").write_text(
        json.dumps({
            "metadata": {
                "version": "0.6.0",
                "is_sudo": "False",
                "user_config": {},
                "cmd_arguments": {"benchmarks": ["loaded-latency"]},
            },
        })
    )

    with pytest.raises(TypeError, match=r"metadata\.is_sudo must be a boolean"):
        resume.read_run_manifest(str(tmp_path))
