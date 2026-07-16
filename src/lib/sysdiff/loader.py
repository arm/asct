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

import json
import os
import ast
from collections import defaultdict
from typing import Any, ClassVar
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version
from asct.core.utility.files import read_json_file
from asct.core.utility.misc import flatten_dict, unflatten_dict
from asct.core.recipes.configuration.metadata import (
    get_recipe as _get_recipe_meta,
    ASCT_RECIPE_METADATA as _ALL_RECIPE_METADATA,
)
import asct.core.logger as log
from asct.lib.run.result_loader import recreate_recipe, read_saved_recipe_artifacts
from asct.core.sysdiff.adapters import get_recipe_diff_adapter, normalize_raw_entry


def group_by_first_dot(flat_dict):
    """
    Groups a flat dictionary by the substring before the first dot in each key.
    For each key in the input dictionary, splits the key at the first dot ('.').
    - If a dot is present, the part before the dot becomes the group key, and the rest becomes a subkey.
    - If no dot is present, the key itself becomes the group key, and its value is stored directly.
    Args:
        flat_dict (dict): A flat dictionary with string keys, potentially containing dots.
    Returns:
        dict: A nested dictionary grouped by the first segment of each key.
              If a key does not contain a dot, its value is stored directly.
              If a key contains a dot, the value is stored in a sub-dictionary under the group key.
    """

    grouped = defaultdict(dict)
    for k, v in flat_dict.items():
        if "." in k:
            group, rest = k.split(".", 1)
        else:
            group, rest = k, ""

        if rest:
            grouped[group][rest] = v
        else:
            grouped[group] = v  # If no dot, store value directly
    return grouped


# --- Loader ---
class RecipeRunLoader:
    SUPPORTED_ASCT_VERSION_SPEC = ">=0.5.0"
    LEGACY_STRING_ENCODED_SWEEPS: ClassVar[set[str]] = {"latency-sweep", "bandwidth-sweep"}

    def _load_metadata(self, data: dict[str, Any]) -> dict[str, Any]:
        """Return top-level metadata for current and legacy asct.json formats."""
        metadata_entry = data.get("metadata", {})
        if not metadata_entry and isinstance(data.get("diff"), dict):
            metadata_entry = unflatten_dict({
                key.removeprefix("metadata."): value
                for key, value in data["diff"].items()
                if key.startswith("metadata.")
            })
        return metadata_entry

    def _handle_asct_version(self, metadata: dict[str, Any]) -> None:
        """Parse and validate the ASCT version from metadata."""
        version_str = metadata.get("version")
        if not version_str:
            raise RuntimeError("ASCT version is missing from the results and is not supported")
        try:
            self.asct_version = Version(version_str)
        except InvalidVersion as exc:
            raise RuntimeError(f"ASCT version '{version_str}' results are not supported") from exc
        if self.asct_version not in SpecifierSet(self.SUPPORTED_ASCT_VERSION_SPEC):
            raise RuntimeError(f"ASCT version '{self.asct_version}' results are not supported")
        self.diff_adapter = get_recipe_diff_adapter(self.asct_version)

    def _normalize_legacy_raw_entry(self, name: str, entry: Any) -> Any:
        """Decode legacy string-encoded raw payloads for the known sweep recipes."""
        normalized = normalize_raw_entry(entry)
        if name in self.LEGACY_STRING_ENCODED_SWEEPS and isinstance(normalized, str):
            try:
                return json.loads(normalized)
            except json.JSONDecodeError:
                return normalized
        return normalized

    def _make_metadata_diff_data(self, metadata_entry: dict[str, Any]) -> dict[str, Any]:
        """Flatten only metadata.cmd_arguments for diff output, keeping the rest of metadata nested."""
        metadata_diff = {key: value for key, value in metadata_entry.items() if key != "cmd_arguments"}
        cmd_arguments = metadata_entry.get("cmd_arguments")
        if isinstance(cmd_arguments, dict):
            normalized_cmd_arguments = dict(cmd_arguments)
            update_config = normalized_cmd_arguments.get("update_config")
            if isinstance(update_config, str):
                try:
                    normalized_cmd_arguments["update_config"] = ast.literal_eval(update_config)
                except (SyntaxError, ValueError):
                    pass
            metadata_diff.update({
                f"cmd_arguments.{key}": value for key, value in flatten_dict(normalized_cmd_arguments).items()
            })
        elif cmd_arguments is not None:
            metadata_diff["cmd_arguments"] = cmd_arguments
        return metadata_diff

    def _generate_recipe_diff_data(self, name: str, raw_data_entry: dict[str, Any]) -> dict:
        """Instantiate the named recipe, restore it, and return current get_diff_data() output."""
        meta = _get_recipe_meta(name, _ALL_RECIPE_METADATA)
        if meta is None:
            return {}

        try:
            recipe = recreate_recipe(name, raw_data_entry)
            return recipe.get_diff_data()
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            log.warning(f"Unable to load data for '{name}': {exc}")
            return {}

    def _normalize_saved_summary_data(
        self, name: str, summary_entry: dict[str, Any], raw_data_entry: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Normalize saved summary artifacts before flattening them for diff use."""
        combined_entry = None
        if isinstance(raw_data_entry, dict):
            if "raw_result" in raw_data_entry:
                combined_raw_result = dict(raw_data_entry.get("raw_result") or {})
                combined_raw_result["summary"] = summary_entry
                combined_entry = {**raw_data_entry, "raw_result": combined_raw_result}
            else:
                combined_entry = {**raw_data_entry, "summary": summary_entry}

        if combined_entry is not None:
            rebuilt = self._generate_recipe_diff_data(name, combined_entry)
            if rebuilt:
                return flatten_dict(rebuilt)
        return flatten_dict(summary_entry)

    def _make_recipe_diff_data(
        self, name: str, raw_data_entry: dict[str, Any], diff_section: dict[str, Any] | None = None
    ) -> dict:
        """Return normalized recipe diff data for both current and legacy run formats."""
        adapted = self.diff_adapter.normalize(name, raw_data_entry, diff_section)
        if adapted is not None:
            return adapted
        return flatten_dict(self._generate_recipe_diff_data(name, raw_data_entry), unroll_lists=True)

    def __init__(self, dir_path: str, recipe_list: list[str], recipe_exclude_list: list[str]):
        """Loads the asct.json in the target directory, parses its contents,
            and applies include/exclude recipe filters.
        Args:
            dir_path (str): Path to the directory containing asct.json.
            recipe_list (List[str]): List of recipe names to include. If empty, includes all.
            recipe_exclude_list (List[str]): List of recipe names to exclude. If empty, excludes none.
        """
        self.asct_version: Version | None = None

        # Load the diff data and raw data from the specified directory
        data = read_json_file(os.path.join(dir_path, "asct.json"))
        if not data or not isinstance(data, dict):
            raise FileNotFoundError(
                f"Invalid ASCT run output directory: {dir_path}. Missing or unreadable artifacts.\n"
                f"See ASCT user guide for more information."
            )
        metadata_entry = self._load_metadata(data)

        if not metadata_entry:
            raise RuntimeError(f"Unsupported ASCT.json format in {dir_path} - missing version information.")

        self._handle_asct_version(metadata_entry)
        flat_metadata = flatten_dict(metadata_entry)
        self.cmd = flat_metadata.get("cmd_arguments.command", "")
        self.run_name = os.path.basename(dir_path)
        diff_section = data.get("diff", {}) if isinstance(data.get("diff", {}), dict) else {}
        raw_section = data.get("raw", {}) if isinstance(data.get("raw", {}), dict) else {}
        self.raw_data = {name: self._normalize_legacy_raw_entry(name, entry) for name, entry in raw_section.items()}

        summary_data = {}
        raw_dir = os.path.join(dir_path, "raw")
        if os.path.isdir(raw_dir):
            for entry in sorted(os.listdir(raw_dir)):
                recipe_dir = os.path.join(raw_dir, entry)
                if not os.path.isdir(recipe_dir):
                    continue

                try:
                    artifacts = read_saved_recipe_artifacts(dir_path, entry)
                except RuntimeError:
                    artifacts = None

                if artifacts is not None and (artifacts.raw_result is not None or artifacts.metadata):
                    existing_raw_data = self.raw_data.get(entry)
                    if isinstance(existing_raw_data, dict) and "raw_result" in existing_raw_data:
                        merged_entry = dict(existing_raw_data)
                    else:
                        merged_entry = {}

                    if artifacts.raw_result is not None:
                        merged_entry["raw_result"] = artifacts.raw_result
                    if artifacts.metadata:
                        merged_entry["metadata"] = artifacts.metadata

                    self.raw_data[entry] = merged_entry or artifacts.raw_result

                if artifacts is not None and artifacts.summary is not None:
                    content = artifacts.summary
                    if isinstance(content, dict):
                        summary_data[entry] = self._normalize_saved_summary_data(
                            entry, content, self.raw_data.get(entry)
                        )
                    else:
                        summary_data[entry] = content

        selected_recipe_names = sorted(set(summary_data) | set(self.raw_data))
        if recipe_list:
            selected_recipe_names = [name for name in selected_recipe_names if name in recipe_list]
        if recipe_exclude_list:
            selected_recipe_names = [name for name in selected_recipe_names if name not in recipe_exclude_list]

        include_metadata = bool(metadata_entry)

        # Build recipes: metadata from the root section, per-recipe data via deserialize + get_diff_data
        self.recipes = {}
        if include_metadata:
            self.recipes["metadata"] = self._make_metadata_diff_data(metadata_entry)
        for name in selected_recipe_names:
            if name in summary_data:
                self.recipes[name] = summary_data[name]
            elif name in self.raw_data:
                self.recipes[name] = self._make_recipe_diff_data(name, self.raw_data[name], diff_section)

    @property
    def cmd_arguments(self):
        """Returns the ASCT command arguments used to generate the raw data."""
        return f"{self.cmd}"

    def get_recipe(self, name: str) -> dict[str, Any]:
        """Returns the data for a specific recipe by name, or an empty dict if not found."""
        return self.recipes.get(name, {})

    def all_recipe_names(self):
        """Returns a list of all recipe names."""
        return list(self.recipes.keys())


if __name__ == "__main__":
    import sys  # For quick testing

    result_directory = sys.argv[1] if len(sys.argv) > 1 else None
    if not result_directory:
        print("Usage: python loader.py /path/to/result_directory")
        sys.exit(1)
    loader = RecipeRunLoader(result_directory, [], [])
    print(loader.cmd_arguments)
    print(loader.all_recipe_names())
    print(loader.get_recipe("peak-bandwidth"))
