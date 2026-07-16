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
from asct.core.resources.resource_base import Resource
from abc import ABC, abstractmethod


class FileSystemResource(Resource, ABC):
    """
    Abstract base class for filesystem-related resources.
    """

    def __init__(self, force_delete_on_teardown: bool):
        super().__init__()
        self.force_delete_on_teardown = force_delete_on_teardown
        self._fs_resource_path = None

    def setup(self):
        """
        Setup the filesystem resource.
        """
        # Create resource and exception would be raised if it fails
        self._create_filesystem_resource()
        return True

    def teardown(self):
        """
        Clean up the filesystem resource after use.
        """
        if not self._check_resource_deletable(self.fs_resource_path):
            return

        # Delete the file if force_delete_on_teardown is enabled,
        # or if the file is empty
        if self.force_delete_on_teardown or self._resource_is_empty(self._fs_resource_path):
            self._delete_resource(self._fs_resource_path)
            self._fs_resource_path = None

    def _create_filesystem_resource(self):
        if not self._check_resource_creatable():
            raise RuntimeError("Failed to create filesystem resource.")
        self._fs_resource_path = self._create_resource()

    @property
    def fs_resource_path(self):
        # Use absolute path for filesystem resources path normalization
        return os.path.abspath(self._fs_resource_path) if self._fs_resource_path else None

    @abstractmethod
    def _create_resource(self):
        raise NotImplementedError("Subclasses must implement _create_resource method")

    @abstractmethod
    def _check_resource_creatable(self):
        raise NotImplementedError("Subclasses must implement _check_resource_creatable method")

    @abstractmethod
    def _check_resource_deletable(self, fs_resource_path):
        raise NotImplementedError("Subclasses must implement _check_resource_deletable method")

    @abstractmethod
    def _resource_is_empty(self, fs_resource_path):
        raise NotImplementedError("Subclasses must implement _resource_is_empty method")

    @abstractmethod
    def _delete_resource(self, fs_resource_path):
        raise NotImplementedError("Subclasses must implement _delete_resource method")

    def __eq__(self, other):
        # Two instances are considered equal if they have the same file resource path.
        # This ensures that duplicate objects with identical paths are not registered.
        return isinstance(other, self.__class__) and self.fs_resource_path == other.fs_resource_path

    def __hash__(self):
        # allows FileSystemResource to be used in hash-based collections like sets and dicts
        return hash(self.fs_resource_path)
