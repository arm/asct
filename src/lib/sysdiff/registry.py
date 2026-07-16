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

from asct.core.sysdiff.diff_rules import RuleBase
from asct.core.sysdiff.display import RecipeDisplay

RECIPE_RULES: dict[str, RuleBase] = {}

RECIPE_DISPLAYS: dict[str, RecipeDisplay] = {}


class SweepDisplay(RecipeDisplay):
    def filter_graph_data(self, data):
        if not isinstance(data, dict):
            return data

        # Newer result files store sweep payloads under raw_result.sweep_data,
        # while legacy files store the sweep columns directly at the top level.
        return data.get("sweep_data", data)


class RawResultDisplay(RecipeDisplay):
    def filter_graph_data(self, data):
        if not isinstance(data, dict):
            return data

        return data.get("raw_result", data)


RECIPE_DISPLAYS["latency-sweep"] = SweepDisplay()
RECIPE_DISPLAYS["bandwidth-sweep"] = SweepDisplay()
RECIPE_DISPLAYS["loaded-latency"] = RawResultDisplay()


def get_display(recipe):
    """Get the display class for a given recipe, defaulting to RecipeDisplay if not found."""
    return RECIPE_DISPLAYS.get(recipe, RecipeDisplay())


def get_rules(name: str) -> RuleBase:
    """Get the RuleBase for a given recipe name, defaulting to an empty RuleBase if not found."""
    return RECIPE_RULES.get(name, RuleBase([]))
