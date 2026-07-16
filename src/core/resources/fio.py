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

from asct.core.resources.ext_tool import ExternalToolResource
import asct.core.logger as log
from packaging import version
import subprocess


class Fio(ExternalToolResource):
    def __init__(self, requested_engine, alterative_engines):
        """
        This Singleton class checks the availability of the 'fio' command-line utility,
        it is a singleton to ensure that the check is performed only once during the
        lifetime of an ASCT run.
        """
        super().__init__("fio")
        self.requested_engine = requested_engine
        self.alternative_engines = alterative_engines
        self.finalized_engine = None

    # Override setup to perform additional engine availability check after confirming fio is installed.
    def setup(self):
        if super().setup():
            # Only perform engine check if the basic version check passed.
            return self.check_engines()
        return False

    # Get the list of available ioengines from fio.
    # FIO does not support JSON format output for engine listing, so we need to parse the stdout of --enghelp command.
    #
    # Typical output:
    # Available IO engines:
    #       cpuio
    #       mmap
    #       ...
    #       libaio
    def get_available_ioengines(self):
        result = subprocess.run([self.tool_name, "--enghelp"], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to get fio engines: {result.stderr}")
        # Skip the first line which is just a header, and parse the rest of the lines to get the engine names.
        engines = [line.strip() for line in result.stdout.splitlines()[1:]]
        if not engines:
            raise RuntimeError("Failed to parse fio engines from output")
        return engines

    def check_engines(self):
        available_engines = self.get_available_ioengines()

        if self.requested_engine in available_engines:
            self.finalized_engine = self.requested_engine
        else:
            # Consider alternative engines, filtering out engines that is not available
            candidate_engines = [e for e in self.alternative_engines if e in available_engines]
            if not candidate_engines:
                raise RuntimeError(
                    f"None of the requested fio engines ({self.requested_engine} "
                    f"and alternatives {self.alternative_engines}) are available. "
                    f"Available engines are: {available_engines}"
                )
            # Pick the first candidate engine as the finalized engine to use for the fio tests.
            self.finalized_engine = candidate_engines[0]
            log.warning(
                f"Requested fio engine '{self.requested_engine}' is not available in the installed fio. "
                f"Falling back to alternative engine '{self.finalized_engine}'."
            )
        return True

    def check_version(self):
        super().check_version()
        required_version = version.parse("3.36")
        raw_ver_str = self.version.replace("fio-", "")
        # Replace the first '-' (often a build/rev separator) with '.post'
        # and any remaining '-' with '+', for local version info.
        clean_ver_str = raw_ver_str.replace("-", ".post", 1).replace("-", "+")
        current_version = version.parse(clean_ver_str)
        if current_version < required_version:
            raise RuntimeError(
                f"fio version {required_version} or higher is required, found version {current_version}."
            )
