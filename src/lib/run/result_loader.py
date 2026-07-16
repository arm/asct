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

import os
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any

import asct.core.logger as log

from asct.core.recipes.configuration.metadata import ASCT_RECIPE_METADATA, get_recipe
from asct.core.recipes.impl import SystemInfo
from asct.core.utility.files import read_json_file
from asct.core.utility.files import hash_saved_recipe_files


@dataclass
class SerializedRecipeData:
    raw_result: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    summary: Any = None

    def payload_for_deserialize(self, *, name: str | None = None, description: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {}

        if self.raw_result is not None:
            raw_result = self.raw_result
            if self.summary is not None:
                if not isinstance(raw_result, dict):
                    raise RuntimeError("Saved summary requires object-shaped data.json")
                raw_result = {**raw_result, "summary": self.summary}
            payload["raw_result"] = raw_result
        elif self.summary is not None:
            raise RuntimeError("Saved summary requires data.json")

        metadata = self.metadata or {}
        if not metadata and (name is not None or description is not None):
            metadata = {
                "name": name,
                "description": description,
            }
        if metadata:
            payload["metadata"] = metadata
        return payload


def recipe_raw_dir(output_dir: str, recipe_name: str) -> str:
    return os.path.join(output_dir, "raw", recipe_name)


def data_json_path(output_dir: str, recipe_name: str) -> str:
    return os.path.join(recipe_raw_dir(output_dir, recipe_name), "data.json")


def summary_json_path(output_dir: str, recipe_name: str) -> str:
    return os.path.join(recipe_raw_dir(output_dir, recipe_name), "summary.json")


def metadata_json_path(output_dir: str, recipe_name: str) -> str:
    return os.path.join(recipe_raw_dir(output_dir, recipe_name), "metadata.json")


def hash_path(output_dir: str, recipe_name: str) -> str:
    return os.path.join(recipe_raw_dir(output_dir, recipe_name), ".hash")


def has_valid_saved_recipe(output_dir: str, recipe_name: str) -> bool:
    data_path = data_json_path(output_dir, recipe_name)
    saved_hash_path = hash_path(output_dir, recipe_name)
    if not os.path.isfile(data_path) or not os.path.isfile(saved_hash_path):
        return False

    try:
        file_payloads = {}
        for filename, file_path in [
            ("data.json", data_path),
            ("summary.json", summary_json_path(output_dir, recipe_name)),
            ("metadata.json", metadata_json_path(output_dir, recipe_name)),
        ]:
            if os.path.isfile(file_path):
                with open(file_path, "rb") as data_file:
                    file_payloads[filename] = data_file.read()

        digest = hash_saved_recipe_files(file_payloads)
        with open(saved_hash_path, "rt") as hash_stream:
            expected_digest = hash_stream.read().strip()
    except (OSError, TypeError, ValueError) as exc:
        log.warning(f"Unable to validate saved results for '{recipe_name}': {exc}")
        return False

    return digest == expected_digest


def read_saved_recipe_artifacts(
    output_dir: str,
    recipe_name: str,
    require_hash: bool = False,
) -> SerializedRecipeData:
    if require_hash and not has_valid_saved_recipe(output_dir, recipe_name):
        raise RuntimeError(f"Saved results for '{recipe_name}' are missing or failed validation")

    data_path = data_json_path(output_dir, recipe_name)
    recipe_metadata_path = metadata_json_path(output_dir, recipe_name)
    recipe_summary_path = summary_json_path(output_dir, recipe_name)

    data = read_json_file(data_path) if os.path.isfile(data_path) else None
    metadata = read_json_file(recipe_metadata_path) if os.path.isfile(recipe_metadata_path) else None
    summary = read_json_file(recipe_summary_path) if os.path.isfile(recipe_summary_path) else None

    if os.path.isfile(data_path) and data is None:
        raise RuntimeError(f"Unable to read saved raw data for '{recipe_name}'")
    if os.path.isfile(recipe_metadata_path) and metadata is None:
        raise RuntimeError(f"Unable to read saved metadata for '{recipe_name}'")
    if os.path.isfile(recipe_summary_path) and summary is None:
        raise RuntimeError(f"Unable to read saved summary data for '{recipe_name}'")

    if data is None and metadata is None and summary is None:
        raise RuntimeError(f"No saved results found for '{recipe_name}'")
    if metadata is not None and not isinstance(metadata, dict):
        raise TypeError(f"Saved metadata for '{recipe_name}' must be an object")

    return SerializedRecipeData(raw_result=data, metadata=metadata or {}, summary=summary)


def create_recipe(recipe_name: str):
    recipe_meta = get_recipe(recipe_name, ASCT_RECIPE_METADATA)
    if recipe_meta is None:
        raise RuntimeError(f"Unknown benchmark '{recipe_name}' in saved run output")

    if recipe_name == "system-info":
        return SystemInfo(recipe_meta)

    recipe_module = import_module("asct.core.recipes.impl")
    recipe_class = getattr(recipe_module, recipe_meta.recipe_name, None)
    if recipe_class is None:
        raise RuntimeError(f"Recipe class '{recipe_meta.recipe_name}' for '{recipe_name}' was not found")
    return recipe_class(recipe_meta)


def recreate_recipe(recipe_name: str, payload: dict[str, Any] | SerializedRecipeData):
    recipe = create_recipe(recipe_name)
    if isinstance(payload, SerializedRecipeData):
        payload = payload.payload_for_deserialize(name=recipe.name, description=recipe.desc)
    recipe.deserialize(payload)
    return recipe


def load_saved_recipe(output_dir: str, recipe_name: str, *, require_hash: bool = True):
    recipe = recreate_recipe(
        recipe_name,
        read_saved_recipe_artifacts(output_dir, recipe_name, require_hash=require_hash),
    )
    recipe._loaded_from_saved_output = True
    return recipe
