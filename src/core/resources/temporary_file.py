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
import tempfile
import asct.core.logger as log
from asct.core.resources.filesystem import FileSystemResource


class TemporaryFile(FileSystemResource):
    def __init__(self, parent_path, requested_filesize=0, force_delete_on_teardown=True):
        """
        Initializes the temporary file with the specified path and options.
        Args:
        folder_path (str): The path to the output folder.
        force_create (bool, optional): If True, the folder will be created/used even when it exists. Defaults to False.
        force_delete_on_teardown (bool, optional): If True, a folder created by this object will be
            deleted during teardown, even if it is not empty. Defaults to False
        """
        super().__init__(force_delete_on_teardown)
        self.parent_path = parent_path
        self.requested_filesize = requested_filesize

    def _allocate_size(self, file_handle, chunk=1024 * 1024):
        """Fully write data until file reaches requested size."""
        remaining = self.requested_filesize
        buf = b"\0" * chunk
        while remaining > 0:
            write_size = min(chunk, remaining)
            file_handle.write(buf[:write_size])
            remaining -= write_size
        file_handle.flush()
        os.fsync(file_handle.fileno())

    def _create_resource(self):
        try:
            with tempfile.NamedTemporaryFile(dir=self.parent_path, delete=False) as temp_file:
                self._allocate_size(temp_file)
                return temp_file.name
        except (IOError, OSError) as e:
            log.error(f"Unable to create temporary file under '{self.parent_path}': {e}")
            raise RuntimeError("Failed to create filesystem resource.") from e

    def _check_resource_creatable(self):
        # We always create a new temporary file, so no need to check for existing file
        # Check parent directory exists, fail if not.  Caller should ensure folder exists including using OutputFolder
        # resource
        if os.path.isdir(self.parent_path):
            return True
        log.error(f"Parent directory '{self.parent_path}' does not exist.")
        return False

    def get_file_path(self):
        if not os.path.isfile(self.fs_resource_path):
            raise FileNotFoundError("Temporary file does not exist")
        return self.fs_resource_path

    def _check_resource_deletable(self, fs_resource_path):
        if fs_resource_path and os.path.isfile(fs_resource_path):
            return True
        log.debug(f"Temporary file '{fs_resource_path}' does not exist; nothing to clean up.")
        return False

    def _resource_is_empty(self, fs_resource_path):
        return os.path.getsize(fs_resource_path) == 0

    def _delete_resource(self, fs_resource_path):
        try:
            os.remove(fs_resource_path)
            log.debug(f"Deleted temporary file '{fs_resource_path}'.")
        except OSError as e:
            log.debug(f"Failed deleting temporary file '{fs_resource_path}': {e}")
