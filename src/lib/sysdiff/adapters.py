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

from typing import Any, ClassVar

from packaging.specifiers import SpecifierSet
from packaging.version import Version

from asct.core.utility.misc import flatten_dict, unflatten_dict


def normalize_raw_entry(entry: Any) -> Any:
    """Return the raw_result payload for current and legacy raw entries."""
    if isinstance(entry, dict) and "raw_result" in entry:
        return entry.get("raw_result", {})
    return entry


class RecipeDiffAdapter:
    """Base adapter for persisted recipe data."""

    IP_REGISTER_RECIPES: ClassVar[set[str]] = {"ucie", "dms", "pss"}

    @staticmethod
    def _ip_register_data(name: str, raw_data_entry: dict[str, Any]) -> dict[str, Any]:
        raw_result = normalize_raw_entry(raw_data_entry)
        registers = raw_result.get(name, []) if isinstance(raw_result, dict) else []
        normalized = {}
        for register in registers if isinstance(registers, list) else []:
            if not isinstance(register, dict):
                continue
            instance = register.get("instance")
            block = register.get("block_name") or f"block_{register.get('block_address')}"
            register_name = register.get("reg_name") or f"reg_{register.get('offset')}"
            prefix = f"instance{'unknown' if instance is None else instance}.{block}.{register_name}"
            normalized[f"{prefix}.raw_value"] = register.get("value")
            for field in register.get("fields", []):
                if not isinstance(field, dict):
                    continue
                field_name = field.get("field_name") or f"field_{field.get('bit_range')}"
                normalized[f"{prefix}.{field_name}"] = field.get("value")
        return normalized

    def normalize(
        self,
        name: str,
        raw_data_entry: dict[str, Any],
        _diff_section: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Return normalized data, or None when recipe reconstruction is required."""
        if name in self.IP_REGISTER_RECIPES:
            return self._ip_register_data(name, raw_data_entry)
        return None


class LegacyV05RecipeDiffAdapter(RecipeDiffAdapter):
    """Normalize ASCT 0.5.x persisted diff formats."""

    VERSION_SPEC: ClassVar[SpecifierSet] = SpecifierSet(">=0.5,<0.6")
    LEGACY_DATA_PREFIX_RECIPES: ClassVar[set[str]] = {"cmn", "ucie", "dms", "pss"}

    @staticmethod
    def _legacy_prefixed_data(name: str, diff_section: dict[str, Any]) -> dict[str, Any]:
        prefix = f"{name}.data."
        return {
            key.removeprefix(prefix).removeprefix(f"{name}."): value
            for key, value in diff_section.items()
            if key.startswith(prefix)
        }

    @staticmethod
    def _latency_sweep_data(data: dict[str, Any]) -> dict[str, Any]:
        normalized = {}
        for column_name, by_level in data.items():
            if not isinstance(by_level, dict):
                normalized[column_name] = by_level
                continue
            for level_name, value in by_level.items():
                normalized.setdefault(level_name, {})[column_name] = value
        return normalized

    def normalize(
        self,
        name: str,
        raw_data_entry: dict[str, Any],
        diff_section: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if diff_section:
            if name in self.LEGACY_DATA_PREFIX_RECIPES:
                legacy_data = self._legacy_prefixed_data(name, diff_section)
                if legacy_data:
                    return legacy_data

            if name in {"latency-sweep", "bandwidth-sweep"}:
                prefix = f"{name}.data."
                legacy_data = unflatten_dict({
                    key.removeprefix(prefix): value for key, value in diff_section.items() if key.startswith(prefix)
                })
                if name == "latency-sweep":
                    legacy_data = self._latency_sweep_data(legacy_data)
                return flatten_dict(legacy_data, unroll_lists=True)

        return super().normalize(name, raw_data_entry, diff_section)


class CurrentRecipeDiffAdapter(RecipeDiffAdapter):
    """Normalize ASCT 0.6+ persisted data formats."""

    VERSION_SPEC: ClassVar[SpecifierSet] = SpecifierSet(">=0.6")


VERSIONED_ADAPTERS: tuple[type[RecipeDiffAdapter], ...] = (
    LegacyV05RecipeDiffAdapter,
    CurrentRecipeDiffAdapter,
)


def get_recipe_diff_adapter(version: Version) -> RecipeDiffAdapter:
    """Return the adapter registered for an ASCT results version."""
    for adapter_class in VERSIONED_ADAPTERS:
        if version in adapter_class.VERSION_SPEC:
            return adapter_class()

    raise RuntimeError(f"No diff adapter is registered for ASCT version '{version}'")
