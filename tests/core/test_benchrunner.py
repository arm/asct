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

from types import SimpleNamespace

import pytest

from asct.core import benchrunner
from asct.core.asct_env import ProcessWatcher
from asct.core.benchrunner import AsyncRunner, Runner, SyncRunner
from asct.core.benchspec.benchspec import ProgramSpec
from asct.core.resources.resource_base import MultiResourceContainer
from asct.lib.run import run_helper
from asct.core.utility import format as lib_format


class _FakeRunner(Runner):
    def run(self, _bmk_spec):
        self._stdout = "fake-stdout"
        self._stderr = "fake-stderr"
        self._retcode = 0
        return self


class _RunnerAwareSpec(ProgramSpec):
    def make_cmd(self):
        return []

    def process_output(self, runner):
        # Contract under test: benchspec receives full runner context.
        return {
            "stdout": runner.stdout,
            "stderr": runner.stderr,
            "cwd": runner.cwd,
        }


class _CheckOutputSpec(ProgramSpec):
    def make_cmd(self):
        return []

    def process_output(self, runner):
        return runner.stdout


class _CmdSpec(ProgramSpec):
    def __init__(self, cmd):
        super().__init__(config=None)
        self._cmd = cmd

    def make_cmd(self):
        return self._cmd

    def process_output(self, runner):
        return runner.stdout


def test_run_and_collect_results_passes_runner_object_to_process_output(tmp_path):
    # tmp_path is a pytest-provided temporary directory fixture.
    # We use it instead of hardcoded "/tmp/..." paths to keep tests isolated and satisfy Ruff S108.
    runner = _FakeRunner(cwd=str(tmp_path))
    spec = _RunnerAwareSpec(config=None)

    result = runner.run_and_collect_results(spec)

    assert result == {
        "stdout": "fake-stdout",
        "stderr": "fake-stderr",
        "cwd": str(tmp_path),
    }


def test_runner_enforces_check_output_for_empty_stdout():
    runner = _FakeRunner(cwd=None)
    spec = _CheckOutputSpec(config=None)

    assert runner.run_and_collect_results(spec) == "fake-stdout"

    runner._stdout = ""
    runner._retcode = 0
    with pytest.raises(RuntimeError, match="didn't produce any output"):
        runner.collect_results(spec)


def test_runner_update_env_rejects_non_dict():
    runner = _FakeRunner(cwd=None)

    with pytest.raises(TypeError, match="Environment must be a dictionary"):
        runner.update_env(["not", "a", "dict"])


def test_multi_resource_container_stores_resources_as_a_list():
    resource_a = SimpleNamespace()
    resource_b = SimpleNamespace()

    container = MultiResourceContainer(resource_a, resource_b, require_all=False)

    assert container._resources == [resource_a, resource_b]
    assert container._require_all is False


def test_setup_benchmarks_skips_dependents_after_setup_failure(monkeypatch):
    class FakeBenchmark:
        def __init__(self, fail_setup=False):
            self.fail_setup = fail_setup
            self.initialize_calls = []
            self.setup_calls = 0
            self.alloc_calls = 0

        def initialize_config(self, cfg, pmu_mode=False):
            self.initialize_calls.append((cfg, pmu_mode))

        def setup(self):
            self.setup_calls += 1
            if self.fail_setup:
                raise RuntimeError("broken setup")

        def allocate_resources(self):
            self.alloc_calls += 1

    failed = FakeBenchmark(fail_setup=True)
    dependent = FakeBenchmark()

    class FakeRegistry:
        def get_recipes(self, _names):
            return [("base", failed), ("dependent", dependent)]

        def get_dependents(self, benchmark_name, benchmark_names):
            assert benchmark_name == "base"
            assert benchmark_names == ["base", "dependent"]
            return ["dependent"]

    monkeypatch.setattr(run_helper, "AGS", lambda: SimpleNamespace(enable_pmu=False))
    monkeypatch.setattr(run_helper.log, "is_log_level", lambda _level: False)

    runnable, skipped = run_helper.setup_benchmarks(["base", "dependent"], {"base": {"x": 1}}, FakeRegistry())

    assert runnable == []
    assert skipped["base"] == "broken setup"
    assert skipped["dependent"] == "A dependency of this benchmark was skipped"
    assert failed.initialize_calls == [({"x": 1}, False)]
    assert failed.alloc_calls == 0
    assert dependent.initialize_calls == []
    assert dependent.setup_calls == 0
    assert dependent.alloc_calls == 0


def test_format_definition_table_uses_indented_longest_key_for_column_width(monkeypatch):
    calls = []

    def fake_format_term_definition(*args):
        calls.append(args)
        return "row\n"

    monkeypatch.setattr(lib_format, "format_term_definition", fake_format_term_definition)

    output = lib_format.format_definition_table([("a", "x"), ("long", "y")], 20, 2, 1)

    assert output == "row\nrow\n"
    assert calls[0][:4] == ("  a", 6, "x", 13)
    assert calls[1][:4] == ("  long", 6, "y", 13)


def test_sync_runner_marks_expected_command_errors_failed():
    class FailingSyncRunner(SyncRunner):
        def execute_command(self, _cmd, output_pipe):
            del output_pipe
            raise OSError("spawn failed")

    runner = FailingSyncRunner(cwd=None)

    assert runner.run(_CmdSpec(["tool"])) is None
    assert runner.retcode == 255


def test_async_runner_marks_expected_command_errors_failed():
    class FailingAsyncRunner(AsyncRunner):
        def execute_command(self, _cmd, output_pipe):
            del output_pipe
            raise RuntimeError("background failed")

    runner = FailingAsyncRunner(cwd=None)
    runner._run(["tool"])

    assert runner.retcode == 255
    assert runner._current_proc is None


def test_sync_runner_registers_and_unregisters_processes(monkeypatch, tmp_path):
    calls = []

    class FakeProcess:
        def __init__(self):
            self.returncode = 0

        def communicate(self):
            return ("stdout", "stderr")

    fake_process = FakeProcess()

    class FakeWatcher:
        def __enter__(self):
            calls.append(("enter", None))
            return self

        def __exit__(self, exc_type, exc_value, exc_traceback):
            del exc_type, exc_value, exc_traceback
            calls.append(("exit", None))
            return False

        def register(self, process):
            calls.append(("register", process))

        def unregister(self, process):
            calls.append(("unregister", process))

    fake_watcher = FakeWatcher()

    monkeypatch.setattr(benchrunner, "ProcessWatcher", lambda: fake_watcher)
    monkeypatch.setattr(benchrunner.subprocess, "Popen", lambda *_args, **_kwargs: fake_process)

    class FakeSpec:
        def make_cmd(self):
            return ["echo", "hello"]

    runner = SyncRunner(cwd=str(tmp_path))
    runner.run(FakeSpec())

    assert calls == [
        ("enter", None),
        ("register", fake_process),
        ("exit", None),
        ("unregister", fake_process),
    ]


def test_process_watcher_sigint_stops_registered_processes(monkeypatch):
    ProcessWatcher._inst = None
    signal_calls = []
    monkeypatch.setattr(benchrunner.signal, "SIGINT", benchrunner.signal.SIGINT)
    monkeypatch.setattr("asct.core.asct_env.signal.default_int_handler", "default-handler")
    monkeypatch.setattr("asct.core.asct_env.signal.signal", lambda *args, **_kwargs: signal_calls.append(args))
    monkeypatch.setattr("asct.core.asct_env.get_progress_tracker", lambda: SimpleNamespace(terminate=lambda: None))

    watcher = ProcessWatcher()
    watcher.initialize()

    class FakeProcess:
        def __init__(self):
            self.signals = []
            self.killed = False
            self.wait_calls = 0
            self._alive = True

        def poll(self):
            return None if self._alive else 0

        def send_signal(self, sig):
            self.signals.append(sig)

        def wait(self, timeout=None):
            self.wait_calls += 1
            raise benchrunner.subprocess.TimeoutExpired(cmd="fake", timeout=timeout)

        def kill(self):
            self.killed = True
            self._alive = False

    process = FakeProcess()
    watcher.register(process)
    with pytest.raises(SystemExit, match="130"):
        watcher._handle_sigint(benchrunner.signal.SIGINT, None)

    assert watcher.stop_requested is True
    assert process.signals == [benchrunner.signal.SIGINT]
    assert process.killed is True
    assert watcher._handler_installed is False
    assert watcher._processes == set()
    assert signal_calls == [
        (benchrunner.signal.SIGINT, watcher._handle_sigint),
        (benchrunner.signal.SIGINT, "default-handler"),
    ]


def test_sync_runner_exits_immediately_when_process_watcher_stop_requested(monkeypatch, tmp_path):
    ProcessWatcher._inst = None
    monkeypatch.setattr("asct.core.asct_env.signal.signal", lambda *_args, **_kwargs: None)

    watcher = ProcessWatcher()
    watcher.initialize()
    watcher._stop_requested = True

    popen_calls = []
    monkeypatch.setattr(benchrunner.subprocess, "Popen", lambda *_args, **_kwargs: popen_calls.append("popen"))

    class FakeSpec:
        def make_cmd(self):
            return ["echo", "hello"]

    runner = SyncRunner(cwd=str(tmp_path))
    with pytest.raises(SystemExit, match="130"):
        runner.run(FakeSpec())

    assert popen_calls == []
