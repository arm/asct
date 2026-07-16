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
import asct.core.logger as logger_mod
from asct.core.resources.ext_tool import ExternalToolResource
from asct.core.resources.output_folder import OutputFolder
from asct.core.resources.temporary_file import TemporaryFile
import pathlib
import subprocess


class DummyLogger:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.debugs = []

    def error(self, msg):
        self.errors.append(msg)

    def warning(self, msg):
        self.warnings.append(msg)

    def debug(self, msg):
        self.debugs.append(msg)


@pytest.fixture(autouse=True)
def patch_logger(monkeypatch):
    dummy = DummyLogger()
    monkeypatch.setattr(logger_mod, "error", dummy.error)
    monkeypatch.setattr(logger_mod, "warning", dummy.warning)
    monkeypatch.setattr(logger_mod, "debug", dummy.debug)
    yield dummy


def test_create_output_folder(tmp_path):
    folder = os.path.join(tmp_path, "output")
    out = OutputFolder(folder)
    assert out.setup() is True
    assert os.path.isdir(folder)
    assert out.get_output_folder_path() == folder
    out.teardown()
    assert not os.path.isdir(folder)


def test_force_create_existing_folder(tmp_path, patch_logger):
    folder = os.path.join(tmp_path, "output")
    os.makedirs(folder)
    out = OutputFolder(folder, force_create=True)
    assert out.setup() is True
    assert "already exists" in patch_logger.warnings[0]
    out.teardown()
    assert os.path.isdir(folder)


def test_no_force_create_existing_folder(tmp_path, patch_logger):
    folder = os.path.join(tmp_path, "output")
    os.makedirs(folder)
    out = OutputFolder(folder, force_create=False)
    with pytest.raises(RuntimeError):
        out.setup()
    assert "already exists" in patch_logger.errors[0]


def test_get_output_folder_path_not_exist(tmp_path):
    folder = os.path.join(tmp_path, "not_exist")
    out = OutputFolder(folder)
    with pytest.raises(FileNotFoundError):
        out.get_output_folder_path()


def test_teardown_deletes_if_created_and_empty(tmp_path):
    folder = os.path.join(tmp_path, "output")
    out = OutputFolder(folder)
    out.setup()
    out.teardown()
    assert not os.path.exists(folder)


def test_teardown_deletes_if_force_delete(tmp_path):
    folder = os.path.join(tmp_path, "output")
    out = OutputFolder(folder, force_delete_on_teardown=True)
    out.setup()
    # create a file inside
    pathlib.Path(os.path.join(folder, "file.txt")).write_text("data")
    out.teardown()
    assert not os.path.exists(folder)


def test_teardown_does_not_delete_if_not_created(tmp_path, patch_logger):
    folder = os.path.join(tmp_path, "output")
    os.makedirs(folder)
    out = OutputFolder(folder)
    out.created_by_this = False
    out.teardown()
    assert os.path.exists(folder)
    assert "not created by this object" in patch_logger.debugs[-1]


def test_teardown_folder_not_exist(tmp_path, patch_logger):
    folder = os.path.join(tmp_path, "output")
    out = OutputFolder(folder)
    out.teardown()
    # Did not run setup(), so nothing to teardown
    assert "not created by this object" in patch_logger.debugs[-1]


def test_temporary_file_create_get_and_delete_paths(tmp_path, monkeypatch, patch_logger):
    tmp = TemporaryFile(str(tmp_path), requested_filesize=4)
    assert tmp.setup() is True
    file_path = tmp.get_file_path()
    assert os.path.isfile(file_path)
    assert os.path.getsize(file_path) == 4
    tmp.teardown()
    assert tmp.fs_resource_path is None

    tmp = TemporaryFile(str(tmp_path), requested_filesize=4)
    assert tmp.setup() is True
    file_path = tmp.get_file_path()
    monkeypatch.setattr(os, "remove", lambda _path: (_ for _ in ()).throw(OSError("busy")))
    tmp._delete_resource(file_path)
    assert "Failed deleting temporary file" in patch_logger.debugs[-1]

    pathlib.Path(file_path).unlink()

    with pytest.raises(FileNotFoundError):
        tmp.get_file_path()


def test_temporary_file_reports_expected_create_failures(tmp_path, monkeypatch, patch_logger):
    missing_parent = tmp_path / "missing"
    tmp = TemporaryFile(str(missing_parent))

    assert tmp._check_resource_creatable() is False
    assert "does not exist" in patch_logger.errors[-1]

    monkeypatch.setattr(
        "asct.core.resources.temporary_file.tempfile.NamedTemporaryFile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("no space")),
    )

    with pytest.raises(RuntimeError, match="Failed to create filesystem resource"):
        TemporaryFile(str(tmp_path))._create_resource()

    assert "Unable to create temporary file" in patch_logger.errors[-1]


def test_external_tool_resource_wraps_expected_failures(monkeypatch, patch_logger):
    ExternalToolResource._inst = None
    tool = ExternalToolResource("tool")
    monkeypatch.setattr(tool, "get_tool_version", lambda: (_ for _ in ()).throw(FileNotFoundError("missing")))

    with pytest.raises(FileNotFoundError):
        tool.setup()

    assert "command not found" in patch_logger.errors[-1]

    ExternalToolResource._inst = None
    tool = ExternalToolResource("tool")
    monkeypatch.setattr(tool, "get_tool_version", lambda: (_ for _ in ()).throw(subprocess.SubprocessError("boom")))

    with pytest.raises(subprocess.SubprocessError):
        tool.setup()

    assert "An error occurred while checking for tool: boom." in patch_logger.errors[-1]

    ExternalToolResource._inst = None
