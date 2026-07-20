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

import json
import os
from types import SimpleNamespace

import pytest

from asct.core.cmd.helpers import run_helpers
from asct.core.recipes.configuration.schema import UserConfigDescr
from asct.lib.run import run_helper as lib_run_helper


class _FakeRecipe:
    # Minimal recipe double to drive run_helpers without importing real recipes.
    def __init__(self, *, csv: str = "", save_obj=None, diff_obj=None):
        self._csv = csv
        self._save_obj = save_obj
        self._diff_obj = diff_obj
        self._json = json.dumps(diff_obj or {})
        self.name = "fake-benchmark"

    def to_csv_str(self) -> str:
        return self._csv

    def to_json_str(self) -> str:
        return self._json

    def serialize(self):
        return self._save_obj

    def get_diff_data(self):
        return self._diff_obj


def test_write_benchmark_result_caches_live_recipe_and_writes_output(tmp_path, monkeypatch):
    class FakeCache:
        def __init__(self):
            self.saved = []

        def save(self, recipe):
            self.saved.append(recipe)

    fake_cache = FakeCache()
    calls = []

    monkeypatch.setattr(run_helpers, "cache", lambda: fake_cache)
    monkeypatch.setattr(
        run_helpers,
        "save_benchmark_result",
        lambda args, name, benchmark: calls.append(("save", args.output_dir, name, benchmark.name)),
    )
    monkeypatch.setattr(
        run_helpers,
        "write_benchmark_output_file",
        lambda args, benchmark: calls.append(("write", args.output_dir, benchmark.name)),
    )

    args = SimpleNamespace(output_dir=str(tmp_path), format="json")
    recipe = _FakeRecipe(diff_obj={"key": "value"})
    recipe.name = "peak-bandwidth"

    run_helpers.write_benchmark_result(args, "peak-bandwidth", recipe)

    assert fake_cache.saved == [recipe]
    assert calls == [
        ("save", str(tmp_path), "peak-bandwidth", "peak-bandwidth"),
        ("write", str(tmp_path), "peak-bandwidth"),
    ]


def test_write_benchmark_result_skips_cache_and_raw_save_for_deserialized_recipe(tmp_path, monkeypatch):
    class FakeCache:
        def __init__(self):
            self.saved = []

        def save(self, recipe):
            self.saved.append(recipe)

    fake_cache = FakeCache()
    calls = []

    monkeypatch.setattr(run_helpers, "cache", lambda: fake_cache)
    monkeypatch.setattr(
        run_helpers,
        "save_benchmark_result",
        lambda args, name, benchmark: calls.append(("save", args.output_dir, name, benchmark.name)),
    )
    monkeypatch.setattr(
        run_helpers,
        "write_benchmark_output_file",
        lambda args, benchmark: calls.append(("write", args.output_dir, benchmark.name)),
    )

    args = SimpleNamespace(output_dir=str(tmp_path), format="stdout")
    recipe = _FakeRecipe(save_obj={"raw_result": {"r": 1}})
    recipe._loaded_from_saved_output = True
    recipe.name = "latency-sweep"

    run_helpers.write_benchmark_result(args, "latency-sweep", recipe)

    assert fake_cache.saved == []
    assert calls == [("write", str(tmp_path), "latency-sweep")]


def test_write_asct_json_header(tmp_path, monkeypatch):
    written: dict[str, str] = {}

    def fake_write_to_file(path: str, payload: str, _mode: str, _kind: str | None = None):
        written[path] = payload

    monkeypatch.setattr(run_helpers, "write_to_file", fake_write_to_file)
    monkeypatch.setattr(run_helpers, "get_version", lambda: "1.2.3")
    monkeypatch.setattr(run_helpers, "_is_sudo_run", lambda: True)

    args = SimpleNamespace(output_dir=str(tmp_path))
    requested = ["latency-sweep", "bandwidth-sweep"]
    user_config = {"bandwidth-sweep": {"iterations": 42}}

    run_metadata = run_helpers.write_asct_json_header(args, requested, user_config)

    out_path = str(tmp_path / "asct.json")
    assert out_path in written

    data = json.loads(written[out_path])
    assert "metadata" in data
    assert "diff" not in data
    assert data["metadata"]["version"] == "1.2.3"
    assert data["metadata"]["is_sudo"] is True
    assert data["metadata"]["user_config"] == user_config
    assert data["metadata"]["cmd_arguments"]["benchmarks"] == requested
    assert "run_id" in data["metadata"]
    assert "timestamp" in data["metadata"]

    assert run_metadata["run_id"] == data["metadata"]["run_id"]
    assert run_metadata["is_sudo"] is True
    assert run_metadata["user_config"] == user_config


def test_save_benchmark_result_writes_raw_file(tmp_path, monkeypatch):
    written: dict[str, str] = {}

    def fake_write_to_file(path: str, payload: str, _mode: str, _kind: str | None = None):
        written[path] = payload

    monkeypatch.setattr(run_helpers, "write_to_file", fake_write_to_file)

    args = SimpleNamespace(output_dir=str(tmp_path))

    # Normal recipe should write raw/<name>/data.json and metadata.json.
    recipe = _FakeRecipe(
        save_obj={"raw_result": {"r": 42}, "metadata": {"description": "desc", "result_desc": "desc"}},
        diff_obj={"k": 1},
    )
    run_helpers.save_benchmark_result(args, "latency-sweep", recipe)

    expected_raw = str(tmp_path / "raw" / "latency-sweep" / "data.json")
    expected_metadata = str(tmp_path / "raw" / "latency-sweep" / "metadata.json")
    assert expected_raw in written
    assert expected_metadata in written
    assert json.loads(written[expected_raw]) == {"r": 42}
    assert json.loads(written[expected_metadata]) == {"description": "desc", "result_desc": "desc"}
    assert str(tmp_path / "raw" / "latency-sweep" / "summary.json") not in written
    expected_hash = str(tmp_path / "raw" / "latency-sweep" / ".hash")
    hash_payload = {
        "data.json": written[expected_raw],
        "metadata.json": written[expected_metadata],
    }
    assert written[expected_hash] == run_helpers.hash_saved_recipe_files({
        filename: payload.encode() for filename, payload in hash_payload.items()
    })

    # system-info should be written to its own artifact directory too.
    sysinfo = _FakeRecipe(save_obj={"raw_result": {"r": 2}, "metadata": {"description": "sys"}}, diff_obj={"sys": 1})
    run_helpers.save_benchmark_result(args, "system-info", sysinfo)
    assert str(tmp_path / "raw" / "system-info" / "data.json") in written
    assert str(tmp_path / "raw" / "system-info" / "metadata.json") in written
    assert str(tmp_path / "raw" / "system-info" / ".hash") in written

    # Recipe with no serialize payload should be skipped entirely
    no_save = _FakeRecipe(save_obj=None, diff_obj={"skip": 1})
    run_helpers.save_benchmark_result(args, "bandwidth-sweep", no_save)
    assert str(tmp_path / "raw" / "bandwidth-sweep" / "data.json") not in written


def test_save_benchmark_result_splits_top_level_summary_from_raw_result(tmp_path, monkeypatch):
    written: dict[str, str] = {}

    def fake_write_to_file(path: str, payload: str, _mode: str, _kind: str | None = None):
        written[path] = payload

    monkeypatch.setattr(run_helpers, "write_to_file", fake_write_to_file)

    args = SimpleNamespace(output_dir=str(tmp_path))
    recipe = _FakeRecipe(
        save_obj={
            "metadata": {"description": "desc", "result_desc": "desc"},
            "raw_result": {
                "sweep_data": {"sizes": {"0": 128}},
                "summary": {"L1": {"Lower Bound": 128}},
            },
        }
    )

    run_helpers.save_benchmark_result(args, "latency-sweep", recipe)

    expected_raw = str(tmp_path / "raw" / "latency-sweep" / "data.json")
    expected_metadata = str(tmp_path / "raw" / "latency-sweep" / "metadata.json")
    expected_summary = str(tmp_path / "raw" / "latency-sweep" / "summary.json")
    expected_hash = str(tmp_path / "raw" / "latency-sweep" / ".hash")

    assert json.loads(written[expected_raw]) == {"sweep_data": {"sizes": {"0": 128}}}
    assert json.loads(written[expected_metadata]) == {"description": "desc", "result_desc": "desc"}
    assert json.loads(written[expected_summary]) == {"L1": {"Lower Bound": 128}}
    hash_payload = {
        "data.json": written[expected_raw],
        "metadata.json": written[expected_metadata],
        "summary.json": written[expected_summary],
    }
    assert written[expected_hash] == run_helpers.hash_saved_recipe_files({
        filename: payload.encode() for filename, payload in hash_payload.items()
    })

    fields_path = str(tmp_path / "asct-fields.json")
    assert fields_path in written
    fields_data = json.loads(written[fields_path])
    assert list(fields_data) == ["system-info"]
    assert fields_data["system-info"]["sys_hw.arch"]["label"] == "Architecture"


def test_output_dispatches_to_formatter(monkeypatch):
    calls = {"csv": 0}

    def fake_csv(*_args, **_kwargs):
        calls["csv"] += 1

    monkeypatch.setattr(run_helpers, "output_csv", fake_csv)

    args = SimpleNamespace(format="csv")

    run_helpers.output(args, completed_benchmarks={}, skipped_benchmarks={}, failed_benchmarks={})

    assert calls["csv"] == 1


def test_setup_benchmarks_skips_failed_dependency(monkeypatch):
    monkeypatch.setattr(lib_run_helper.AGS(), "enable_pmu", False, raising=False)
    monkeypatch.setattr(lib_run_helper.log, "is_log_level", lambda _level: False)
    monkeypatch.setattr(lib_run_helper, "ProcessWatcher", lambda: SimpleNamespace(stop_requested=False))

    class FakeBenchmark:
        def __init__(self, name, fail_setup=False):
            self.name = name
            self.fail_setup = fail_setup
            self.setup_calls = 0
            self.alloc_calls = 0

        def initialize_config(self, *_args, **_kwargs):
            return None

        def setup(self):
            self.setup_calls += 1
            if self.fail_setup:
                raise RuntimeError("setup failed")

        def allocate_resources(self):
            self.alloc_calls += 1

    dependency = FakeBenchmark("dependency", fail_setup=True)
    dependent = FakeBenchmark("dependent")

    class FakeRegistry:
        def get_recipes(self, _names):
            return [("dependency", dependency), ("dependent", dependent)]

        def get_dependents(self, name, _names):
            return ["dependent"] if name == "dependency" else []

    ready, skipped = lib_run_helper.setup_benchmarks(["dependency", "dependent"], {}, FakeRegistry())

    assert ready == []
    assert skipped["dependency"] == "setup failed"
    assert skipped["dependent"] == "A dependency of this benchmark was skipped"
    assert dependent.setup_calls == 0
    assert dependent.alloc_calls == 0


def test_teardown_benchmarks_logs_expected_failures(monkeypatch):
    warnings = []
    monkeypatch.setattr(lib_run_helper.log, "warning", warnings.append)

    class FailingBenchmark:
        def teardown(self):
            raise OSError("busy")

    lib_run_helper.teardown_benchmarks([("bench", FailingBenchmark())])

    assert warnings == ["Failed to teardown benchmark bench: busy"]


def test_get_conv_user_config_validation_and_default_filtering(monkeypatch):
    class FakeRecipe:
        name = "bench"

        def __init__(self):
            self.user_config = {"outer": {"leaf": UserConfigDescr("leaf", conv=int)}}

        def get_default_user_config(self):
            return {"outer": {"leaf": 7}}

    monkeypatch.setattr(lib_run_helper, "get_recipe", lambda _name, _metadata: FakeRecipe())

    dest = {}
    lib_run_helper.get_conv_user_config(
        {"alias": {"outer": {"leaf": "8"}}},
        dest,
        ["bench"],
        "test",
        recipe_metadata=[],
    )
    assert dest == {"bench": {"outer": {"leaf": 8}}}

    dest = {}
    lib_run_helper.get_conv_user_config(
        {"alias": {"outer": {"leaf": "7"}}},
        dest,
        ["bench"],
        "test",
        recipe_metadata=[],
    )
    assert dest == {}

    with pytest.raises(ValueError, match="Incorrect format"):
        lib_run_helper.get_conv_user_config(
            {"alias": {"outer": {"leaf": "not-int"}}},
            {},
            ["bench"],
            "test",
            recipe_metadata=[],
            just_check=True,
        )


def test_write_benchmark_output_file_writes_csv_and_json(tmp_path, monkeypatch):
    written = {}

    def fake_write_to_file(path, payload, _mode, _kind=None):
        written[path] = payload

    monkeypatch.setattr(run_helpers, "write_to_file", fake_write_to_file)

    recipe = _FakeRecipe(csv="a,b\n1,2\n", diff_obj={"key": "value"})
    recipe.name = "loaded-latency"

    run_helpers.write_benchmark_output_file(SimpleNamespace(format="csv", output_dir=str(tmp_path)), recipe)
    run_helpers.write_benchmark_output_file(SimpleNamespace(format="json", output_dir=str(tmp_path)), recipe)
    run_helpers.write_benchmark_output_file(SimpleNamespace(format="stdout", output_dir=str(tmp_path)), recipe)

    assert written[str(tmp_path / "loaded-latency.csv")] == "a,b\n1,2\n"
    assert json.loads(written[str(tmp_path / "loaded-latency.json")]) == {"key": "value"}
    assert len(written) == 2


def test_print_failure_table_stdout_uses_terminal_width_and_formats_each_section(monkeypatch, capsys):
    calls = []

    def fake_format_term_definition(name, name_width, definition, definition_width, column_spacing=0):
        calls.append((name, name_width, definition, definition_width, column_spacing))
        return f"{name}:{definition}\n"

    monkeypatch.setattr(run_helpers, "format_term_definition", fake_format_term_definition)
    monkeypatch.setattr(
        run_helpers.shutil,
        "get_terminal_size",
        lambda *_args, **_kwargs: os.terminal_size((20, 24)),
    )

    run_helpers.print_failure_table_stdout([("skip", "reason")], [("failed-name", "boom")])

    assert calls == [
        ("skip", 4, "reason", 30, 2),
        ("failed-name", 11, "boom", 30, 2),
    ]
    assert capsys.readouterr().out == "skip:reason\n\nfailed-name:boom\n\n"


def test_print_failure_table_logging_aligns_names_and_uses_warning_then_error(monkeypatch):
    warnings = []
    errors = []

    monkeypatch.setattr(run_helpers.log, "warning", warnings.append)
    monkeypatch.setattr(run_helpers.log, "error", errors.append)

    run_helpers.print_failure_table_logging([("a", "skip"), ("longer", "")], [("bad", "failed")])

    assert warnings == ["a     : skip", "longer"]
    assert errors == ["bad: failed"]
