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


class Resource:
    def __init__(self):
        self.applied = False
        self.name = self.__class__.__name__
        self.depends_on = []

    @staticmethod
    def _set_sysfile_value(file, value):
        """
        Writes a value to a sysfs file.

        Args:
            value (str): Value to write.
            file (str): Path to the sysfs file.

        Raises:
            Any exception from subprocess.run()
        """
        try:
            with open(file, "wt") as f:
                f.write(value)
        except (OSError, ValueError, TypeError, LookupError, RuntimeError) as exc:
            raise exc.__class__(f"Error writing to sysfs path '{file}': {exc}") from exc

    @staticmethod
    def _get_sysfile_value(file):
        """
        Reads a value from a sysfs file.

        Args:
            file (str): Path to the sysfs file.

        Raises:
            Any exception from subprocess.run()
        """
        try:
            with open(file, "rt") as f:
                return f.read().strip()
        except (OSError, ValueError, TypeError, LookupError, RuntimeError) as exc:
            raise exc.__class__(f"Error reading from sysfs path '{file}': {exc}") from exc

    def setup(self):
        """
        Sets up the necessary configurations or resources for the derived class.

        This method must be implemented by subclasses to define specific setup
        logic. If not implemented, calling this method will raise a
        NotImplementedError.

        Raises:
            NotImplementedError: If the method is not implemented in a subclass.
        """
        raise NotImplementedError

    def teardown(self):
        """
        Perform cleanup or resource deallocation tasks.

        This method should be overridden in subclasses to define specific
        teardown behavior. It is intended to release resources or perform
        any necessary cleanup operations before the object is discarded.

        Raises:
            NotImplementedError: If the method is not implemented in a subclass.
        """
        raise NotImplementedError

    def __str__(self):
        """Returns the class name as a string."""
        return f"{self.__class__.__name__}"

    def __eq__(self, value):
        """Checks equality with another object."""
        return type(self) is type(value)

    def __hash__(self):
        """Returns the hash of the class name."""
        return hash(type(self))


class MultiResourceContainer(Resource):
    """
    Encapsulates multiple resources where setup succeeds if:
    - at least one of the resources' setup succeeds if require_all=False (similar to 'or')
    - all conditions' setup succeds if require_all=True (similar to 'and')
    """

    def __init__(self, *args, require_all=True):
        super().__init__()
        self._resources = list(args)
        self._require_all = require_all

    def setup(self):
        failures = []
        for res in self._resources:
            try:
                res.setup()
            except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as exc:  # ruff:ignore[try-except-in-loop]
                failures.append(exc)
                if self._require_all:
                    break
        if failures:
            if self._require_all:
                raise failures[0]
            if len(failures) == len(self._resources):
                raise RuntimeError(" OR ".join(f"{exc}" for exc in failures))

        self.applied = True

        return True

    def teardown(self):
        for res in self._resources:
            res.teardown()

    def __str__(self):
        return f"MultiResourceContainer({', '.join(str(r) for r in self._resources)})"
