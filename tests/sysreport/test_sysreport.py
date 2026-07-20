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

"""
Simple tests of src/sysreport/sysreport.py utilities
"""

import pytest
import subprocess

from asct.sysreport import sysreport


def test_boot_info_type():
    boot_info = sysreport.boot_info_type()
    if boot_info is None:
        pytest.skip("boot firmware metadata is unavailable on this host")
    assert boot_info in ["ACPI", "DT"]


def test_kernel_config_returns_none_when_config_open_fails(monkeypatch):
    monkeypatch.setattr(sysreport, "kernel_config_file", lambda: "/boot/config-test")
    monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("nope")))

    assert sysreport.kernel_config() is None


def test_run_cmd_logs_and_reraises_oserror(monkeypatch):
    messages = []

    def fake_run(*_args, **_kwargs):
        raise OSError("boom")

    monkeypatch.setattr(sysreport.subprocess, "run", fake_run)

    with pytest.raises(OSError):
        sysreport.run_cmd("missing tool", log_func=messages.append)

    assert any("Error running sysreport command" in message for message in messages)


def test_get_cache_line_size_handles_command_and_parse_errors(monkeypatch):
    system = object.__new__(sysreport.System)

    def raise_called_process_error(*_args, **_kwargs):
        raise subprocess.CalledProcessError(1, "getconf")

    monkeypatch.setattr(sysreport, "run_cmd", raise_called_process_error)
    assert system.get_cache_line_size() is None

    monkeypatch.setattr(sysreport, "run_cmd", lambda *_args, **_kwargs: (b"not-an-int", b""))
    assert system.get_cache_line_size() is None


def test_perf_helpers_handle_command_failures(monkeypatch):
    sysreport.perf_binary.cache_clear()
    monkeypatch.setattr(sysreport, "run_cmd", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("no perf")))
    assert not sysreport.perf_binary()

    monkeypatch.setattr(sysreport, "perf_binary", lambda: "/usr/bin/perf")
    monkeypatch.setattr(
        sysreport,
        "run_cmd",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(subprocess.CalledProcessError(1, "ldd")),
    )
    assert sysreport.perf_binary_imports("libopencsd.so") is None


def test_bpf_tool_helpers_handle_command_failures(monkeypatch):
    monkeypatch.setattr(sysreport.os.path, "exists", lambda path: path in {"/usr/sbin/bpftool", "/usr/bin/bpftrace"})
    monkeypatch.setattr(sysreport, "run_cmd", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("nope")))

    assert sysreport.bpftool_installed() is None
    assert sysreport.bpftrace_installed() is None


def test_run_cmd_reraises_original_error(monkeypatch):
    expected = RuntimeError("boom")

    def fake_run(*_args, **_kwargs):
        raise expected

    monkeypatch.setattr(sysreport.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as exc_info:
        sysreport.run_cmd("missing tool", log_func=lambda _msg: None)

    assert exc_info.value is expected
