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

import asct.core.logger as log
from asct.core.resources.ext_tool import ExternalToolResource


class Numactl(ExternalToolResource):
    def __init__(self, n_numa_nodes):
        """
        This Singleton class checks the availability of the 'numactl' command-line utility,
        it is a singleton to ensure that the check is performed only once during the
        lifetime of an ASCT run.

        Parameters:
            n_numa_nodes (int): The number of NUMA nodes reported by the system. This is used to
                determine whether 'numactl' can be used; if the system reports zero NUMA nodes,
                'numactl' cannot be used and benchmarks will be skipped or fail.
        """
        super().__init__("numactl")
        self.n_numa_nodes = n_numa_nodes

    def setup(self):
        """
        Checks for the presence of the 'numactl' executable in the system's PATH.

        If 'numactl' is found, it attempts to retrieve and store its version.

        Additionally, we can only use 'numactl' on systems where sysreport has
        sys_hw.n_numa_nodes >= 1.

        On kernels built with CONFIG_NUMA=n where sys_hw.n_numa_nodes=0 we cannot use 'numactl' as
        it returns the error: "This system does not support NUMA policy". Since we currently rely on
        'numactl' to pin threads to individual cores, we simply cannot run our benchmarks correctly
        on those systems.

        Therefore we also check for sys_hw.n_numa_nodes >= 1 and fail/skip the benchmark if that
        requirement is not met.

        Returns:
            bool: True if 'numactl' is installed and sys_hw.n_numa_nodes >= 1
        Raises:
            FileNotFoundError: If 'numactl' is not found in the system PATH.
            RuntimeError: If the system reports sys_hw.n_numa_nodes == 0
        """

        log.debug(f"self.sysreport.sys_hw.n_numa_nodes = {self.n_numa_nodes}")
        if self.n_numa_nodes == 0:
            log.error(
                "No NUMA nodes reported. Linux kernel may be built with CONFIG_NUMA=n. This "
                "benchmark requires at least 1 NUMA node to be configured, even if it's a "
                "single node. Configure the kernel with CONFIG_NUMA=y"
            )
            raise RuntimeError

        return super().setup()
