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

import pytest
import shutil
from asct.core.resources.fio import Fio
import subprocess


# Fixtures to ensure test environment is suitable for Fio tests
@pytest.fixture(scope="session", autouse=True)
def require_fio_command():
    # Try to run fio --version, if failed, skip this test
    try:
        # Intentionally not using full path
        fio_path = shutil.which("fio")
        subprocess.run([fio_path, "--version"], capture_output=False, check=True)
    except (OSError, subprocess.CalledProcessError, TypeError):
        pytest.skip("fio command not installed")


def test_fio_init_with_available_engine_for_target(monkeypatch):
    requested_engine = "libaio"
    alternative_engines = ["mmap", "cpuio"]
    fio = Fio(requested_engine, alternative_engines)
    monkeypatch.setattr(fio, "get_available_ioengines", lambda: ["sync", "mmap", "libaio"])
    assert fio.setup() is True
    assert fio.finalized_engine == requested_engine
    # Reset the singleton instance for other tests
    Fio._inst = None


def test_fio_init_with_available_engine_for_alternative(monkeypatch):
    requested_engine = "sync"
    alternative_engines = ["mmap", "cpuio"]
    fio = Fio(requested_engine, alternative_engines)
    monkeypatch.setattr(fio, "get_available_ioengines", lambda: ["psync", "mmap", "cpuio"])
    assert fio.setup() is True
    assert fio.finalized_engine == "mmap"
    # Reset the singleton instance for other tests
    Fio._inst = None


def test_fio_init_with_no_available_engine_for_target_and_alternatives(monkeypatch):
    requested_engine = "sync"
    alternative_engines = []
    fio = Fio(requested_engine, alternative_engines)
    monkeypatch.setattr(fio, "get_available_ioengines", lambda: ["psync", "mmap", "cpuio"])
    with pytest.raises(RuntimeError, match="None of the requested fio engines"):
        fio.setup()
    # Reset the singleton instance for other tests
    Fio._inst = None
