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

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from importlib.machinery import SourceFileLoader

from asct.core.cmd import view


def _load_asct_cli_module():
    cli_path = Path(__file__).resolve().parents[2] / "src" / "asct"
    loader = SourceFileLoader("asct_cli_test_module", str(cli_path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_view_outputs_only_valid_requested_benchmarks(monkeypatch, tmp_path):
    captured = {}

    monkeypatch.setattr(
        view,
        "_discover_saved_recipe_names",
        lambda _run_dir, _manifest=None: (["loaded-latency", "peak-bandwidth"], None),
    )
    monkeypatch.setattr(
        view,
        "has_valid_saved_recipe",
        lambda _run_dir, benchmark_name: benchmark_name == "loaded-latency",
    )
    monkeypatch.setattr(
        view,
        "load_saved_recipe",
        lambda _run_dir, benchmark_name: SimpleNamespace(name=benchmark_name),
    )
    monkeypatch.setattr(
        view,
        "read_saved_recipe_artifacts",
        lambda _run_dir, _benchmark_name: SimpleNamespace(metadata={}),
    )
    monkeypatch.setattr(view, "_apply_view_user_config", lambda _recipe, _user_config, _saved_metadata=None: None)
    monkeypatch.setattr(view, "sort_for_output", lambda data: data)
    monkeypatch.setitem(
        view.OUTPUT_HANDLERS,
        "json",
        lambda _args, completed_benchmarks, _skipped, _failed: captured.update(completed_benchmarks),
    )

    args = SimpleNamespace(run_dir=str(tmp_path), format="json", output_dir=str(tmp_path / "out"))
    view.run(args)

    assert captured == {"loaded-latency": SimpleNamespace(name="loaded-latency")}


def test_view_also_restores_saved_system_info(monkeypatch, tmp_path):
    captured = {}

    monkeypatch.setattr(
        view,
        "_discover_saved_recipe_names",
        lambda _run_dir, _manifest=None: (["loaded-latency", "system-info"], None),
    )
    monkeypatch.setattr(
        view,
        "has_valid_saved_recipe",
        lambda _run_dir, benchmark_name: benchmark_name in {"loaded-latency", "system-info"},
    )
    monkeypatch.setattr(
        view,
        "load_saved_recipe",
        lambda _run_dir, benchmark_name: SimpleNamespace(name=benchmark_name),
    )
    monkeypatch.setattr(
        view,
        "read_saved_recipe_artifacts",
        lambda _run_dir, _benchmark_name: SimpleNamespace(metadata={}),
    )
    monkeypatch.setattr(view, "_apply_view_user_config", lambda _recipe, _user_config, _saved_metadata=None: None)
    monkeypatch.setattr(view, "sort_for_output", lambda data: data)
    monkeypatch.setitem(
        view.OUTPUT_HANDLERS,
        "json",
        lambda _args, completed_benchmarks, _skipped, _failed: captured.update(completed_benchmarks),
    )

    args = SimpleNamespace(run_dir=str(tmp_path), format="json", output_dir=str(tmp_path / "out"))
    view.run(args)

    assert captured == {
        "loaded-latency": SimpleNamespace(name="loaded-latency"),
        "system-info": SimpleNamespace(name="system-info"),
    }


def test_view_discovers_saved_recipe_directories_without_manifest_requested_benchmarks(monkeypatch, tmp_path):
    captured = {}
    recipe_dir = tmp_path / "raw" / "loaded-latency"
    recipe_dir.mkdir(parents=True)
    (recipe_dir / "data.json").write_text("{}")
    (tmp_path / "asct.json").write_text("{}")

    monkeypatch.setattr(
        view,
        "has_valid_saved_recipe",
        lambda _run_dir, benchmark_name: benchmark_name == "loaded-latency",
    )
    monkeypatch.setattr(
        view,
        "load_saved_recipe",
        lambda _run_dir, benchmark_name: SimpleNamespace(name=benchmark_name),
    )
    monkeypatch.setattr(view, "_apply_view_user_config", lambda _recipe, _user_config, _saved_metadata=None: None)
    monkeypatch.setattr(view, "sort_for_output", lambda data: data)
    monkeypatch.setitem(
        view.OUTPUT_HANDLERS,
        "json",
        lambda _args, completed_benchmarks, _skipped, _failed: captured.update(completed_benchmarks),
    )

    args = SimpleNamespace(run_dir=str(tmp_path), format="json", output_dir=str(tmp_path / "out"))
    view.run(args)

    assert captured == {"loaded-latency": SimpleNamespace(name="loaded-latency")}


def test_view_discovers_saved_recipe_directories_for_report_manifest_with_empty_benchmarks(monkeypatch, tmp_path):
    captured = {}
    recipe_dir = tmp_path / "raw" / "system-info"
    recipe_dir.mkdir(parents=True)
    (recipe_dir / "data.json").write_text("{}")
    (tmp_path / "asct.json").write_text(
        '{"metadata": {"version": "0.6.0", "is_sudo": false, "user_config": {}, "cmd_arguments": {"benchmarks": []}}}'
    )

    monkeypatch.setattr(
        view,
        "has_valid_saved_recipe",
        lambda _run_dir, benchmark_name: benchmark_name == "system-info",
    )
    monkeypatch.setattr(
        view,
        "load_saved_recipe",
        lambda _run_dir, benchmark_name: SimpleNamespace(name=benchmark_name),
    )
    monkeypatch.setattr(view, "_apply_view_user_config", lambda _recipe, _user_config, _saved_metadata=None: None)
    monkeypatch.setattr(view, "sort_for_output", lambda data: data)
    monkeypatch.setitem(
        view.OUTPUT_HANDLERS,
        "json",
        lambda _args, completed_benchmarks, _skipped, _failed: captured.update(completed_benchmarks),
    )

    args = SimpleNamespace(run_dir=str(tmp_path), format="json", output_dir=str(tmp_path / "out"))
    view.run(args)

    assert captured == {"system-info": SimpleNamespace(name="system-info")}


def test_view_loads_legacy_raw_results_from_manifest(monkeypatch, tmp_path):
    captured = {}

    (tmp_path / "asct.json").write_text(
        '{"raw": {"loaded-latency": {"value": 1}, "system-info": {"hostname": "host"}}}'
    )

    monkeypatch.setattr(
        view,
        "_load_legacy_saved_recipe",
        lambda _run_dir, benchmark_name, raw_entry: SimpleNamespace(name=benchmark_name, raw_entry=raw_entry),
    )
    monkeypatch.setattr(view, "_apply_view_user_config", lambda _recipe, _user_config, _saved_metadata=None: None)
    monkeypatch.setattr(view, "sort_for_output", lambda data: data)
    monkeypatch.setitem(
        view.OUTPUT_HANDLERS,
        "json",
        lambda _args, completed_benchmarks, _skipped, _failed: captured.update(completed_benchmarks),
    )

    args = SimpleNamespace(run_dir=str(tmp_path), format="json", output_dir=str(tmp_path / "out"))
    view.run(args)

    assert captured == {
        "loaded-latency": SimpleNamespace(name="loaded-latency", raw_entry={"value": 1}),
        "system-info": SimpleNamespace(name="system-info", raw_entry={"hostname": "host"}),
    }


def test_view_applies_manifest_user_config_to_loaded_recipes(monkeypatch, tmp_path):
    captured = {}

    class FakeRecipe:
        def __init__(self, name):
            self.name = name
            self._metadata = SimpleNamespace(default_config={"saved_only": "default"})
            self._cfg = None

    loaded_recipe = FakeRecipe("latency-sweep")

    monkeypatch.setattr(
        view,
        "read_manifest_data",
        lambda _run_dir: SimpleNamespace(
            manifest={},
            metadata={},
            cmd_arguments={},
            user_config={"latency-sweep": {"cycle_base": False}},
        ),
    )
    monkeypatch.setattr(
        view,
        "_discover_saved_recipe_names",
        lambda _run_dir, _manifest=None: (["latency-sweep"], None),
    )
    monkeypatch.setattr(
        view,
        "has_valid_saved_recipe",
        lambda _run_dir, benchmark_name: benchmark_name == "latency-sweep",
    )
    monkeypatch.setattr(
        view,
        "read_saved_recipe_artifacts",
        lambda _run_dir, benchmark_name: SimpleNamespace(
            metadata={"config": {"cycle_base": True, "saved_only": "saved"}}
            if benchmark_name == "latency-sweep"
            else {}
        ),
    )
    monkeypatch.setattr(
        view,
        "load_saved_recipe",
        lambda _run_dir, benchmark_name: loaded_recipe if benchmark_name == "latency-sweep" else None,
    )
    monkeypatch.setattr(view, "sort_for_output", lambda data: data)
    monkeypatch.setitem(
        view.OUTPUT_HANDLERS,
        "json",
        lambda _args, completed_benchmarks, _skipped, _failed: captured.update(completed_benchmarks),
    )

    args = SimpleNamespace(run_dir=str(tmp_path), format="json", output_dir=str(tmp_path / "out"))
    view.run(args)

    assert loaded_recipe._cfg.cycle_base is False
    assert loaded_recipe._cfg.saved_only == "saved"
    assert captured == {"latency-sweep": loaded_recipe}


def test_view_loads_legacy_latency_sweep_summary(tmp_path):
    (tmp_path / "latency-sweep-summary.ubench.json").write_text(
        '{"L1": {"LB": 128, "UB": 256, "sweet_spot": {"sizes": 192, "average_latency_ns": 1.5}}}'
    )

    recipe = view._load_legacy_saved_recipe(
        str(tmp_path),
        "latency-sweep",
        '{"sizes": {"0": 128}, "average_latency_ns": {"0": 1.5}}',
    )

    assert recipe.result.dataframe.to_dict(orient="dict") == {
        "Lower Bound": {"L1": 128},
        "Upper Bound": {"L1": 256},
        "Optimum Datasize": {"L1": 192},
        "Latency [ns]": {"L1": 1.5},
    }


def test_view_loads_legacy_latency_sweep_average_latency(tmp_path):
    (tmp_path / "latency-sweep-summary.ubench.json").write_text(
        '{"L1": {"LB": 128, "UB": 256, "sweet_spot": {"sizes": 192, "average_latency": 1.5}}}'
    )

    recipe = view._load_legacy_saved_recipe(
        str(tmp_path),
        "latency-sweep",
        '{"sizes": {"0": 128}, "average_latency": {"0": 1.5}}',
    )

    assert recipe.result.dataframe.to_dict(orient="dict") == {
        "Lower Bound": {"L1": 128},
        "Upper Bound": {"L1": 256},
        "Optimum Datasize": {"L1": 192},
        "Latency [ns]": {"L1": 1.5},
    }


def test_view_loads_legacy_bandwidth_sweep_summary(tmp_path):
    (tmp_path / "latency-sweep-summary.ubench.json").write_text(
        '{"L1": {"LB": 128, "UB": 256, "sweet_spot": {"sizes": 192, "average_latency_ns": 1.5}}}'
    )
    (tmp_path / "bandwidth.ubench.json").write_text(
        '{"sizes": {"0": 128, "1": 192}, "total_bandwidth_mbps": {"0": 5000.0, "1": 6000.0}}'
    )

    recipe = view._load_legacy_saved_recipe(
        str(tmp_path),
        "bandwidth-sweep",
        '{"sizes": {"0": 128, "1": 192}, "total_bandwidth_mbps": {"0": 5000.0, "1": 6000.0}}',
    )

    assert recipe.result.dataframe.to_dict(orient="dict") == {
        "Datasize Used": {"0": 192},
        "Level": {"0": "L1"},
        "Bandwidth [GB/s]": {"0": 6.0},
    }


def test_view_loads_legacy_bandwidth_sweep_total_bandwidth(tmp_path):
    (tmp_path / "latency-sweep-summary.ubench.json").write_text(
        '{"L1": {"LB": 128, "UB": 256, "sweet_spot": {"sizes": 192, "average_latency": 1.5}}}'
    )
    (tmp_path / "bandwidth.ubench.json").write_text(
        '{"sizes": {"0": 128, "1": 192}, "total_bandwidth": {"0": 5000.0, "1": 6000.0}}'
    )

    recipe = view._load_legacy_saved_recipe(
        str(tmp_path),
        "bandwidth-sweep",
        '{"sizes": {"0": 128, "1": 192}, "total_bandwidth": {"0": 5000.0, "1": 6000.0}}',
    )

    assert recipe.result.dataframe.to_dict(orient="dict") == {
        "Datasize Used": {"0": 192},
        "Level": {"0": "L1"},
        "Bandwidth [GB/s]": {"0": 6.0},
    }


def test_exec_cmd_view_preserves_cli_output_dir(monkeypatch, tmp_path):
    cli_module = _load_asct_cli_module()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    view_dir = tmp_path / "view"

    captured = {}

    class ViewModule:
        @staticmethod
        def run(args):
            captured["run_args"] = {
                "command": args.command,
                "force": args.force,
                "output_dir": args.output_dir,
                "output_dir_path": args.output_dir_path,
                "format": args.format,
                "quiet": getattr(args, "quiet", None),
                "log_file": getattr(args, "log_file", None),
            }

    def fake_import_module(name):
        if name == "asct.core.cmd.view":
            return ViewModule()
        raise AssertionError(f"Unexpected import: {name}")

    monkeypatch.setattr(cli_module, "import_module", fake_import_module)
    monkeypatch.setattr(
        cli_module,
        "initialize_asct",
        lambda args: captured.setdefault(
            "initialize_args",
            {
                "command": args.command,
                "force": args.force,
                "output_dir": args.output_dir,
                "output_dir_path": args.output_dir_path,
                "format": args.format,
                "quiet": getattr(args, "quiet", None),
                "log_file": getattr(args, "log_file", None),
            },
        ),
    )

    args = SimpleNamespace(run_dir=str(run_dir), output_dir=str(view_dir), command="view", force=True)
    cli_module.exec_cmd_view(args)

    expected = {
        "command": "view",
        "force": True,
        "output_dir": str(view_dir),
        "output_dir_path": str(run_dir),
        "format": "stdout",
        "quiet": None,
        "log_file": None,
    }
    assert captured["initialize_args"] == expected
    assert captured["run_args"] == expected
