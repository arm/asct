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

import json
from functools import lru_cache
from importlib.resources import files


FIELD_METADATA_FILE = "fields.json"


@lru_cache(maxsize=1)
def load_field_metadata():
    """Load the field metadata from the JSON file."""
    metadata_path = files(__package__).joinpath(FIELD_METADATA_FILE)
    with metadata_path.open("r", encoding="utf-8") as metadata_file:
        return json.load(metadata_file)


def get_recipe_field_metadata(recipe_name: str):
    """Get the field metadata for a specific recipe."""
    return load_field_metadata().get(recipe_name, {})


def get_field_metadata_for_recipes(recipe_names):
    """Get field metadata for the provided recipes."""
    metadata = load_field_metadata()
    return {recipe_name: metadata[recipe_name] for recipe_name in recipe_names if recipe_name in metadata}


def get_field_metadata(recipe_name: str, field_path: str):
    """Get the metadata for a specific field in a recipe."""
    return get_recipe_field_metadata(recipe_name).get(field_path, {})


def get_field_label(recipe_name: str, field_path: str):
    """Get the label for a specific field in a recipe."""
    label = get_field_metadata(recipe_name, field_path).get("label")
    if not label:
        return "{} [missing label]".format(field_path)
    return label


def field_string(recipe_name: str, field_path: str, value, label_width: int = 20, indent: str = "  "):
    """Format a field and its value as a string with a label."""
    label = "{}:".format(get_field_label(recipe_name, field_path))
    return "{indent}{label:<{label_width}} {value}".format(
        indent=indent,
        label=label,
        label_width=label_width,
        value=value,
    )


def get_section_metadata(recipe_name: str, section_name: str):
    """Get the metadata for a specific section in a recipe."""
    return load_field_metadata().get(recipe_name, {}).get("sections", {}).get(section_name, {})


def get_section_label(recipe_name: str, section_name: str):
    """Get the label for a specific section in a recipe."""
    label = get_section_metadata(recipe_name, section_name).get("label")
    if not label:
        return "{} [missing section label]".format(section_name)
    return label


def section_string(recipe_name: str, section_name: str, prefix: str = "", suffix: str = ":"):
    """Format a section label as a string with optional prefix and suffix."""
    return "{}{}{}".format(prefix, get_section_label(recipe_name, section_name), suffix)
