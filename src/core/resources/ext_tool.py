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

from asct.core.datatypes import ASCTSingleton
import asct.core.logger as log
from asct.core.resources.resource_base import Resource
import subprocess


class ExternalToolResource(Resource, metaclass=ASCTSingleton):
    def __init__(self, tool_name):
        """
        This Singleton class checks the availability of a command-line utility,
        it is a singleton to ensure that the check is performed only once during the
        lifetime of an ASCT run.
        """
        super().__init__()
        self.version = None
        self.tool_name = tool_name

    def setup(self):
        """
        Checks for the presence of the executable in the system's PATH.

        If found, it attempts to retrieve and store its version.

        Returns:
            bool: True if the tool is installed
        Raises:
            FileNotFoundError: If the tool is not found in the system PATH.
        """

        if self.version is not None:
            log.debug(f"Presence of {self.tool_name} is already checked, version: " + self.version)
            return True

        try:
            result = self.get_tool_version()

            if result.returncode == 0:
                self.version = result.stdout.strip()
            else:
                # older versions may not have a --version flag and will return non-zero exit code
                self.version = "unknown"

            # May throw exception if version check fails
            try:
                self.check_version()
            except (RuntimeError, ValueError) as exc:
                log.error(f"Version check for {self.tool_name} failed: {exc}")
                raise

            log.debug(f"{self.tool_name} is installed on the system path.")
            log.debug(f"{self.tool_name} version: " + self.version)

        except FileNotFoundError:
            message = (
                f"{self.tool_name} command not found in system PATH."
                f" Please install the {self.tool_name} package. See ASCT install instructions for more details."
            )
            log.error(message)
            raise
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as e:
            # Catch any other exceptions that may occur during tool checking.
            message = f"An error occurred while checking for {self.tool_name}: {e}."
            log.error(message)
            raise

        return True

    # Subclass can override this method for more version checks.
    def check_version(self):
        """
        Validates the retrieved tool version.

        Raises:
            RuntimeError: If the tool version is not retrievable or invalid.
        """
        if not self.version:
            raise RuntimeError(f"Unable to determine version of {self.tool_name}.")

    # Subclass can override this method to customize version retrieval
    def get_tool_version(self):
        return subprocess.run(
            [self.tool_name, "--version"],
            text=True,
            capture_output=True,
            check=False,
        )

    def teardown(self):
        """
        Clean up the tool resources after use.
        """
        # Nothing to clean up for external tools
        log.debug(f"Cleaning up {self.tool_name} resources")
