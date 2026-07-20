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

import shutil
from graphlib import TopologicalSorter
from importlib import import_module
from dataclasses import dataclass
from asct.core.recipes.configuration.metadata import CHR_NEG_FILTER, TAG_DEFAULT, ASCT_RECIPE_METADATA
from asct.core.utility.format import format_definition_table
from asct.core.cache import ASCTCache as cache


@dataclass(init=False)
class RecipeFilteredBenchmarks:
    # filters used
    positive_filters: list[str]
    negative_filters: list[str]

    # benchmarks filtered not including dependencies
    filtered_list: list[str]

    # list of all benchmarks including dependencies
    complete_list: list[str]

    # benchmarks added based on positive filters
    filtered_in: list[str]

    # benchmarks removed based on negative filters
    filtered_out: list[str]

    # benchmarks removed because one of their depencies was removed - [(benchmark, removed_dependency)...]
    filtered_out_depends: list[tuple[str, str]]

    # benchmarks added as dependency - { dependency_name: set(dependent_benchmarks...) ... }
    added_dependencies: dict[str, list[str]]

    # dependency benchmarks restored from cache - { dependency_name: [dependent_benchmarks...] ... }
    cached_dependencies: dict[str, list[str]]

    def __init__(self):
        self.positive_filter = []
        self.negative_filter = []
        self.filtered_list = []
        self.complete_list = []
        self.filtered_in = []
        self.filtered_out = []
        self.filtered_out_depends = []
        self.added_dependencies = {}
        self.cached_dependencies = {}

    def get_description(self, detailed):
        table_data_pre_details = []
        table_data_bm_details = []

        if detailed:
            deselect_extra_info = ""
            table_data_pre_details.append((
                "Selected keywords:",
                ", ".join(self.positive_filter),
            ))

            if self.negative_filter:
                table_data_pre_details.append((
                    "Deselected keywords:",
                    ", ".join(self.negative_filter),
                ))
            if self.filtered_in:
                table_data_pre_details.append(("Selected benchmarks:", ", ".join(self.filtered_in)))
            if self.filtered_out:
                table_data_pre_details.append(("Deselected benchmarks:", ", ".join(self.filtered_out)))
                if self.filtered_out_depends:
                    table_data_pre_details.append((
                        "Auto-deselected benchmarks°:",
                        ", ".join([f"{name}({dep})" for name, dep in self.filtered_out_depends]),
                    ))
                    deselect_extra_info = (
                        "  ° These benchmarks were automatically deselected because "
                        "the user deselected one of their dependencies, shown in "
                        "parentheses in the list\n"
                    )

        if self.filtered_list:
            table_data_bm_details.append(("Benchmarks to run:", ", ".join(self.filtered_list)))
        else:
            table_data_bm_details.append(("Benchmarks to run:", "None"))

        deps_info = ""
        for dep, dependents in self.added_dependencies.items():
            if deps_info:
                deps_info += "\n"
            deps_info += f"{dep}({', '.join(dependents)})"

        if deps_info:
            table_data_bm_details.append(("Dependencies to run:", deps_info))

        total_width = max(shutil.get_terminal_size().columns, 60)

        description = ""
        # first section
        if table_data_pre_details:
            description += "Benchmark run request details\n"
            description += format_definition_table(table_data_pre_details, total_width, 2, 1)
            if deselect_extra_info:
                description += "\n" + deselect_extra_info
            description += "\n"
        # second section
        if table_data_bm_details:
            description += format_definition_table(table_data_bm_details, total_width, 0, 1)
        return description


def _create_recipes(metadata):
    recipes = {}
    recipe_module = import_module("asct.core.recipes.impl")
    for item in metadata:
        if hasattr(recipe_module, item.recipe_name):
            recipe_class = getattr(recipe_module, item.recipe_name)
        else:
            raise AttributeError(f"{item.recipe_name} not found in {recipe_module.__name__}")
        recipe_obj = recipe_class(item)
        recipes[item.name] = recipe_obj
    return recipes


def _resolve_dependencies(global_recipes, benchmark_list: list) -> dict:
    dependencies = set()
    rev_dependencies = {}
    for benchmark in benchmark_list:
        for dep in global_recipes[benchmark].depends_on:
            if dep not in rev_dependencies:
                rev_dependencies[dep] = []
            rev_dependencies[dep].append(benchmark)
        dependencies.update(global_recipes[benchmark].depends_on)

    dependencies.difference_update(benchmark_list)

    return {dep: rev_dependencies[dep] for dep in dependencies}


def get_filtered_recipes(metadata, keywords, add_dependencies=True):
    filtered_results = RecipeFilteredBenchmarks()

    positive_filter = set()
    negative_filter = set()
    for item in keywords:
        if item.startswith(CHR_NEG_FILTER):
            negative_filter.add(item[len(CHR_NEG_FILTER) :])
        else:
            positive_filter.add(item)

    if not positive_filter:
        positive_filter.add(TAG_DEFAULT)

    filtered_results.positive_filter = sorted(positive_filter)
    filtered_results.negative_filter = sorted(negative_filter)

    metadata_by_name = {item.name: item for item in metadata}
    global_metadata_by_name = {item.name: item for item in ASCT_RECIPE_METADATA}

    added_items = {item.name for item in metadata if positive_filter.intersection(item.tags)}

    removed_items = set()
    removed_items_indirect = set()
    for item in added_items:
        if negative_filter.intersection(metadata_by_name[item].tags):
            removed_items.add(item)
            continue
        for depend_name in metadata_by_name[item].depends_on:
            if negative_filter.intersection(global_metadata_by_name[depend_name].tags):
                removed_items_indirect.add(item)
                filtered_results.filtered_out_depends.append((item, depend_name))
                break

    filtered_results.filtered_in = sorted(added_items)
    filtered_results.filtered_out = sorted(removed_items)

    filtered_items = added_items - removed_items - removed_items_indirect
    filtered_results.filtered_list = sorted(filtered_items)

    if add_dependencies:
        dep_info = _resolve_dependencies(global_metadata_by_name, filtered_items)
        filtered_results.added_dependencies = dep_info
        filtered_results.complete_list = sorted(filtered_results.filtered_list + list(dep_info.keys()))
    else:
        filtered_results.complete_list = filtered_results.filtered_list

    return filtered_results


class RecipeRegistry:
    def __init__(self, metadata):
        self._metadata = metadata
        self._recipes = _create_recipes(metadata)
        self._global_recipes = _create_recipes(ASCT_RECIPE_METADATA)

    def __getitem__(self, recipe_name):
        return self._recipes[recipe_name]

    def get_recipes(self, name_list):
        """Returns a list of (name, recipe_instance) sorted by priority
        and grouped by category.
        """
        requested_categories = {}
        for item in name_list:
            recipe = self._global_recipes[item]
            if recipe._category not in requested_categories:
                requested_categories[recipe._category] = []
            requested_categories[recipe._category].append(recipe)

        return [
            (recipe._name, recipe)
            for categ_list in requested_categories.values()
            for recipe in sorted(categ_list, key=lambda r: r.priority)
        ]

    def resolve_dependencies(self, recipes_list):
        """
        Perform a topological sort on a list of recipes objects based on their dependencies.
        Args:
            recipes_list (Iterable[str]): A list of recipe names.
        Returns:
            List[str]: The recipe names sorted in topological order of dependencies.
        Raises:
            CycleError: If a cycle is detected in the dependency graph.
        """

        # Map recipe name → recipes object
        recipes = [self._global_recipes[name] for name in recipes_list]

        # Create dependency graph: name → list of dependencies (by name)
        dep_graph = {r.name: r.depends_on for r in recipes}

        # Perform topological sort PYTHON 3.9+
        sorter = TopologicalSorter(dep_graph)

        return list(sorter.static_order())

    def get_filtered_recipes(self, keywords):
        """
        Returns a list of benchmark names based on a list of keywords
        """
        return get_filtered_recipes(self._metadata, keywords, add_dependencies=True)

    def remove_cached_dependencies(self, filtered_results: list) -> list:
        """
        Returns filtered results with cached dependencies removed from the added_dependencies dict
        """
        dependencies = {}
        cached_dependencies = {}
        for bm, value in filtered_results.added_dependencies.items():
            if cache().is_cache_available(bm) and cache().restore_to_output_folder(bm):
                cached_dependencies[bm] = value
                continue
            dependencies[bm] = value

        filtered_results.cached_dependencies = cached_dependencies
        filtered_results.added_dependencies = dependencies
        filtered_results.complete_list = [
            bm for bm in filtered_results.complete_list if bm in filtered_results.filtered_list or bm in dependencies
        ]
        return filtered_results

    def get_dependents(self, dependency: str, benchmark_list: list) -> list:
        """
        Returns a list of all the benchmarks from benchmark_list that depend on a given benchmark
        """
        return [bm for bm in benchmark_list if bm != dependency and dependency in self._global_recipes[bm].depends_on]
