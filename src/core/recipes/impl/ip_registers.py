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


import pandas as pd
from asct.lib.ip_registers.ip_registers_api import collect_registers
from asct.core.recipes.recipe_base import RecipeBase
from asct.core.resources.check_sudo import CheckSudo
from asct.core.datatypes import ASCTSingleton
from asct.core import logger as log


class IPRegistersBase(RecipeBase, metaclass=ASCTSingleton):
    """
    RecipeBase-derived class for running and reporting sysreport results.
    """

    def __init__(self, metadata):
        RecipeBase.__init__(self, metadata=metadata)
        self.initialize_config()
        self.ip_registers = []
        self.ip_name = None
        self.ip_dumps = None
        self.regs = []

    def run_function(self):
        """
        Run the sysreport and collect results.
        """
        self._loaded_raw_result = None
        self.ip_registers = []
        try:
            for ip_dump in self.ip_dumps:
                self.ip_registers.extend(
                    collect_registers(ip=ip_dump, reg_filter=self.regs, fields=True, exclude_volatile=False)
                )
        except Exception as e:
            log.debug(f"Could not collect {self.ip_name.capitalize()} registers: {e}")
            raise RuntimeError("register collection failed") from e
        return self

    def _create_resources(self):
        """Declare the privilege required to read IP registers."""
        return [CheckSudo()]

    def to_dict(self):
        """
        Convert only specific dataclass attributes to a dictionary,
        skipping any that are None at the top level.
        """
        if self._loaded_raw_result is not None:
            return self._loaded_raw_result

        # results = {"system_type": self.cmn_data.system_type if self.cmn_data else None, "instances": []}
        return {self.ip_name: list(self.ip_registers)}

    def get_diff_data(self):
        diff_data = {}
        data = self.to_dict()

        for reg in data.get(self.ip_name, []):
            instance = reg.get("instance")
            block = reg.get("block_name") or f"block_{reg.get('block_address')}"
            reg_name = reg.get("reg_name") or f"reg_{reg.get('offset')}"
            reg_dict = (
                diff_data
                .setdefault(f"instance{'unknown' if instance is None else instance}", {})
                .setdefault(block, {})
                .setdefault(reg_name, {})
            )
            reg_dict["raw_value"] = reg.get("value")
            for field in reg.get("fields", []):
                field_name = field.get("field_name") or f"field_{field.get('bit_range')}"
                reg_dict[field_name] = field.get("value")

        return diff_data

    def to_stdout(self):
        print()

    def to_stdout_verbose(self):
        """
        Prints the recipe result to standard output in a verbose,
        which may include additional details
        """
        if self.to_dict().get(self.ip_name):
            print(self.ip_registers_str())

    def ip_registers_str(self):
        lines = [f"        {self.ip_name.capitalize()} Registers:"]
        lines.extend(
            (
                f"           instance{reg.get('instance')} "
                f"{reg.get('block_name') or reg.get('block_address')}."
                f"{reg.get('reg_name')} = {reg.get('value')}"
            )
            for reg in self.to_dict().get(self.ip_name, [])
        )
        return "\n".join(lines)

    def to_csv_str(self):
        """
        Save the sysreport results to a CSV file.
        """
        rows = []

        for reg in self.to_dict().get(self.ip_name, []):
            fields = reg.get("fields") or [
                {
                    "field_name": "raw_value",
                    "bit_range": None,
                    "value": reg.get("value"),
                    "description": reg.get("description"),
                }
            ]
            rows.extend(
                {
                    # "system_type": system_type,
                    "component": self.ip_name,
                    f"{self.ip_name}_instance": reg.get("instance"),
                    "block_name": reg.get("block_name"),
                    "block_address": reg.get("block_address"),
                    "node": (
                        f"{self.ip_name}.instance{reg.get('instance')}."
                        f"{reg.get('block_name') or reg.get('block_address')}"
                    ),
                    "reg_name": reg.get("reg_name"),
                    **field,
                }
                for field in fields
            )

        df = pd.DataFrame(rows)
        return df.to_csv(index=False, header=True)

    def to_json(self):
        """
        Save the sysreport results to a JSON file.
        """
        return self.to_dict()

    def deserialize(self, data):
        """Restore and validate saved IP-register results."""
        if not data:
            self._loaded_raw_result = {self.ip_name: []}
            self.result = self
            return

        _, raw_result = self._deserialize_payload(data)
        if not isinstance(raw_result, dict):
            raw_result = {}
        registers = raw_result.get(self.ip_name, [])
        if not isinstance(registers, list):
            registers = []
        self._loaded_raw_result = {self.ip_name: registers}
        self.result = self


class UCIe(IPRegistersBase, metaclass=ASCTSingleton):
    """
    IPRegistersBase-derived class for running and reporting UCIe sysreport results.
    """

    def __init__(self, metadata):
        IPRegistersBase.__init__(self, metadata=metadata)
        self.ip_name = "ucie"
        self.ip_dumps = ["ucie"]
        # Todo revisit
        self.regs = ["cmn_mcu", "adapter_fdi", "reg_adapter_impsp"]


class DMS(IPRegistersBase, metaclass=ASCTSingleton):
    """
    IPRegistersBase-derived class for running and reporting DMS sysreport results.
    """

    def __init__(self, metadata):
        IPRegistersBase.__init__(self, metadata=metadata)
        self.ip_name = "dms"
        self.ip_dumps = ["dms-ctl", "dms-phy", "dms-pi"]


class PSS(IPRegistersBase, metaclass=ASCTSingleton):
    """
    IPRegistersBase-derived class for running and reporting PSS sysreport results.
    """

    def __init__(self, metadata):
        IPRegistersBase.__init__(self, metadata=metadata)
        self.ip_name = "pss"
        self.ip_dumps = ["pss"]
