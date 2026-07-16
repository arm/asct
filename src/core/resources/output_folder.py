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
import asct.core.logger as log
from asct.core.resources.filesystem import FileSystemResource
import shutil


class OutputFolder(FileSystemResource):
    def __init__(self, requested_folder_path, force_create=False, force_delete_on_teardown=False):
        """
        Initializes the output folder with the specified path and options.
        Args:
        requested_folder_path (str): The path to the output folder to be created.
        force_create (bool, optional): If True, the folder will be created/used even when it exists. Defaults to False.
        force_delete_on_teardown (bool, optional): If True, a folder created by this object will be
            deleted during teardown, even if it is not empty. Defaults to False
        """
        super().__init__(force_delete_on_teardown)
        self.requested_folder_path = requested_folder_path
        self.force_create = force_create

    def _create_resource(self):
        try:
            # Only return non-None if we created the folder ourselves
            if not os.path.exists(self.requested_folder_path):
                os.makedirs(self.requested_folder_path, exist_ok=True)
                return self.requested_folder_path
            # Return None to indicate we did not create the folder but not error condition
            return None
        except OSError as e:
            log.error(f"Unable to create output directory '{self.requested_folder_path}': {e}")
            self.requested_folder_path = None  # Clear the invalid folder path
            raise RuntimeError("Failed to create filesystem resource.") from e

    def _check_resource_creatable(self):
        if os.path.exists(self.requested_folder_path):
            if not self.force_create:
                log.error(
                    f"Specified output directory '{self.requested_folder_path}' already exists, "
                    "use --force to overwrite!"
                )
                return False
            log.warning(
                f"Specified output directory '{self.requested_folder_path}' already exists, "
                "some results may be overwritten!"
            )
        # either directory does not exist (will be deleted later) or force_create is True (will not be deleted later)
        # see _create_resource(self)
        return True

    def get_output_folder_path(self):
        """
        Retrieve the file path of the output folder.

        Returns:
            str: The file path of the output folder.
        """
        if not self.requested_folder_path or not os.path.isdir(self.requested_folder_path):
            raise (FileNotFoundError("Output folder does not exist"))

        return self.requested_folder_path

    def _check_resource_deletable(self, fs_resource_path):
        if fs_resource_path is None:
            # do not delete a folder that wasn't created by this object
            # even when it is empty
            log.debug("folder was not created by this object and hence will not be deleted")
            return False

        if not os.path.isdir(fs_resource_path):
            log.debug(f"Output folder '{fs_resource_path}' does not exist, nothing to clean up.")
            return False

        return True

    def _resource_is_empty(self, fs_resource_path):
        return not os.listdir(fs_resource_path)

    def _delete_resource(self, fs_resource_path):
        log.debug(f"Cleaning up output folder '{fs_resource_path}'.")
        shutil.rmtree(fs_resource_path, ignore_errors=True)


class RawResultsFolder(OutputFolder):
    def __init__(self, requested_folder_path):
        super().__init__(requested_folder_path, True, False)

    def _check_resource_creatable(self):
        return True
