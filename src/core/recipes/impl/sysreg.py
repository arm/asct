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

from __future__ import annotations

import pandas as pd

from typing import Any, ClassVar
from pathlib import Path
from copy import deepcopy

from dataclasses import dataclass, asdict, is_dataclass, field

from asct.core.recipes.recipe_base import RecipeBase
from asct.core.utility.misc import flatten_dict
from asct.core.datatypes import ASCTSingleton
from asct.core import logger as log
from asct.core.utility.files import read_json_file
from asct.sysreport.sysreport import System
from asct.core import constants


@dataclass
class sysreg:
    """
    System register snapshot and decoded bitfield information.

    Structure:
    {
      "cpuN": {                                # per-core key (e.g. "cpu0")
        "REGISTER_NAME": {                     # register name
          "raw_value": str,                    # raw hex or binary string read from sysfs
          "fields": {                          # decoded bitfields
            "FIELD_NAME": {
              "value": str,                    # bitfield value as hex string (e.g. "0x1F")
              "description": str | None        # optional text from schema
            },
            ...
          }
        },
        ...
      }
    }
    """

    kernel_module_access: bool = False
    registers: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)


class SysregProperties:
    """
    Get system register properties by reading sysfs
    from sysreg kernel module.
    """

    SYSREG_BASE = constants.SYSREG_BASE_PATH

    # TODO: Support more CPU parts in sysreg kernel module
    PARTNUM_TO_CPU: ClassVar[dict[int, str]] = {
        0xD0C: "N1",
        # 0xD40: "V1",
        0xD49: "N2",
        0xD4F: "V2",
        # 0xD8E: "N3",
        # 0xD83: "V3-AE",
        # 0xD84: "V3",
    }

    def __init__(self):
        self.sysreg = sysreg(kernel_module_access=False)
        is_arm = getattr(System(), "arm_arch", None) is not None
        if not is_arm:
            log.info("SysregProperties: Non-ARM architecture detected, skipping sysreg read.")
            return
        self.cpu_label = self._detect_cpu_label()
        self.schema_dir = self._resolve_schema_path()
        self.generic_schema = self._load_schema(Path(self.schema_dir) / "arm_registers.json")
        self.cpu_schema = self._load_schema(Path(self.schema_dir) / f"{self.cpu_label}.json") if self.cpu_label else {}
        self._read_sysreg()

    def _resolve_schema_path(self) -> str:
        core_dir = Path(__file__).resolve().parents[2]
        return str(core_dir / "config" / "sysreg")

    def _load_schema(self, json_path: Path) -> dict:
        schema = read_json_file(str(json_path))
        if not schema or "registers" not in schema:
            log.warning("Invalid or missing schema in %s", json_path)
            return {"registers": {}}

        registers = schema["registers"]
        if not isinstance(registers, dict):
            log.warning("'registers' must be a dict in schema: %s", json_path)
            return {"registers": {}}

        valid_regs = {}
        for name, reg in registers.items():
            fields = reg.get("fields")
            if isinstance(fields, list) and all(isinstance(f, dict) and "name" in f for f in fields):
                valid_regs[name] = reg
            else:
                log.debug("Skipping invalid register: %s", name)

        return {"registers": valid_regs}

    def _detect_cpu_label(self) -> str | None:
        try:
            base = Path(self.SYSREG_BASE)
            for cpu_dir in base.iterdir():
                if not cpu_dir.is_dir() or not cpu_dir.name.startswith("cpu"):
                    continue

                midr_path = cpu_dir / "midr_el1"
                if midr_path.is_file():
                    with midr_path.open("r") as f:
                        midr = int(f.read().strip(), 16)

                    partnum = (midr >> 4) & 0xFFF  # MIDR_EL1[15:4]
                    return self.PARTNUM_TO_CPU.get(partnum)
        except (OSError, ValueError) as e:
            log.debug(f"CPU label detection failed: {e}")
        return None

    def _read_sysreg(self) -> None:
        base = Path(self.SYSREG_BASE)
        if not base.exists():
            log.debug("Sysreg sysfs path not found: %s", base)
            return

        try:
            for cpu_dir in base.iterdir():
                if not cpu_dir.is_dir() or not cpu_dir.name.startswith("cpu"):
                    continue

                self.sysreg.registers.setdefault(cpu_dir.name, {})

                for fpath in cpu_dir.iterdir():
                    if not fpath.is_file():
                        continue
                    try:
                        val = fpath.read_text().strip()
                        self.sysreg.registers[cpu_dir.name][fpath.name] = {
                            "raw_value": val,
                            "fields": {},
                        }

                        fields = self._parse_register_bits(fpath.name, val)
                        if fields:
                            self.sysreg.registers[cpu_dir.name][fpath.name]["fields"] = fields

                    except (OSError, ValueError) as e:
                        log.error(f"Error reading sysreg file {fpath}: {e}")
                        continue

            if self.sysreg.registers:
                self.sysreg.kernel_module_access = True

        except OSError as e:
            log.error(f"Error scanning sysreg path: {e}")

    def _parse_register_bits(self, reg_name: str, raw_value: str) -> dict[str, dict[str, Any]]:
        reg_key = reg_name.upper()

        reg_schema = self.generic_schema.get("registers", {}).get(reg_key) or self.cpu_schema.get("registers", {}).get(
            reg_key
        )

        if not reg_schema:
            return {}

        try:
            val = int(raw_value, 16)
        except ValueError:
            return {}

        out: dict[str, dict[str, Any]] = {}
        for reg_field in reg_schema.get("fields", []):
            name, msb, lsb = reg_field.get("name"), reg_field.get("msb"), reg_field.get("lsb")
            if name is None or msb is None or lsb is None:
                continue

            # Compute field width and extract the corresponding bits from the raw register value.
            # Example: for msb=15, lsb=8, width = 8 bits -> extract bits [15:8].
            if msb < lsb:
                continue
            width = int(msb) - int(lsb) + 1
            field_value = (val >> int(lsb)) & ((1 << width) - 1)

            # Convert numeric field value to a zero-padded uppercase hex string for consistent schema matching.
            # Example: field_value=5, width=4 -> field_value_hex = "0x5"
            # Example: field_value=10, width=8 -> field_value_hex = "0x0A"
            hex_width = max(1, (width + 3) // 4)
            field_value_hex = f"0x{field_value:0{hex_width}X}"

            values = reg_field.get("values") or {}
            desc = values.get(field_value_hex) or values.get(field_value_hex.lower())

            out[name] = {"value": field_value_hex, "description": desc}

        return out


class SysregInfo(RecipeBase, metaclass=ASCTSingleton):
    def __init__(self, metadata):
        RecipeBase.__init__(self, metadata=metadata)

        self.register_map = sysreg()
        self.initialize_config()

    def run_function(self):
        if self.register_map is not None:
            sysreg_props = SysregProperties()
            self.register_map.kernel_module_access = sysreg_props.sysreg.kernel_module_access
            self.register_map.registers = dict(sysreg_props.sysreg.registers)

        return self

    def to_stdout(self):
        # System register configuration
        if self.register_map.registers:
            print("\nSystem register configuration:")
            print("  kernel_module_access: {}".format(self.register_map.kernel_module_access))
            num_cpus = System().get_cpu_count() or 0
            print(f"num_cpus: {num_cpus}")
            target_cpu = None

            for i in range(num_cpus):
                name = f"cpu{i}"
                if name in self.register_map.registers:
                    target_cpu = name
                    break

            print(f"  registers ({target_cpu}):")
            for reg_name in sorted(self.register_map.registers[target_cpu]):
                print(f"    {reg_name:<20} {self.register_map.registers[target_cpu][reg_name]['raw_value']}")

    def to_dict(self):
        """
        Convert only specific dataclass attributes to a dictionary,
        skipping any that are None at the top level.
        """
        if self._loaded_raw_result is not None:
            return self._loaded_raw_result

        allowed_attrs = [
            "register_map",
        ]

        result = {}
        for attr in allowed_attrs:
            value = getattr(self, attr, None)
            if value is not None:  # Skip if whole attribute is None
                result[attr] = asdict(value) if is_dataclass(value) else value
        return result

    def to_csv_str(self):
        """
        Save the sysreg results to a CSV file.
        """
        flat_dict = flatten_dict(self.to_dict())
        df = pd.DataFrame(list(flat_dict.items()))
        return df.to_csv(index=False, header=False)

    def deserialize(self, data):
        if not data:
            return
        _, self._loaded_raw_result = self._deserialize_payload(data)
        self.result = self

    def get_diff_data(self):
        if self._loaded_raw_result is None:
            raise RuntimeError(f"result data was not loaded for {self.name}")
        data = deepcopy(self._loaded_raw_result)
        root = next((data[k] for k in ("sysreg", "register_map") if isinstance(data.get(k), dict)), None)
        if not root:
            return data

        registers = root.get("registers", {})
        if not isinstance(registers, dict):
            return data

        for cpu_regs in registers.values():
            if not isinstance(cpu_regs, dict):
                continue
            for reg_name in ["mpidr_el1", "midr_el1"]:
                cpu_regs.pop(reg_name, None)

            for reg in cpu_regs.values():
                if not isinstance(reg, dict):
                    continue
                fields = reg.get("fields")
                if not isinstance(fields, dict):
                    continue

                # Keep only non-RES fields
                reg["fields"] = {
                    k: {kk: vv for kk, vv in v.items() if kk != "description"}
                    for k, v in fields.items()
                    if not (isinstance(k, str) and k.upper().startswith("RES"))
                }

        return data
