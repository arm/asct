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

from dataclasses import dataclass, field
from typing import Any, Callable
from asct.core.utility.misc import enable_sysreg
from asct.lib.ip_registers.ip_registers_api import is_ip_dump_available
from asct.core.constants import SYSREG_BASE_PATH

from asct.core.recipes.configuration.defaults import (
    C2C_DEFAULT_CONFIG,
    IPERF3_SWEEP_DEFAULT_CONFIG,
    LOADED_LATENCY_DEFAULT_CONFIG,
    MEMORY_DEFAULT_CONFIG,
    STORAGE_ACCESS_PATTERN_DEFAULT_CONFIG,
    STORAGE_IO_DEPTH_DEFAULT_CONFIG,
    STORAGE_PROCESS_COUNT_DEFAULT_CONFIG,
    STORAGE_REQUEST_SIZE_DEFAULT_CONFIG,
    REPORT_CMN_DEFAULT_CONFIG,
)
from asct.core.recipes.configuration.schema import (
    C2C_USER_CFG,
    IPERF3_TCP_SWEEP_USER_CFG,
    IPERF3_UDP_SWEEP_USER_CFG,
    LOADED_LATENCY_USER_CFG,
    MEMORY_COMMON_USER_CFG,
    MEMORY_ITERATIONS_USER_CFG,
    MEMORY_SWEEP_USER_CFG,
    STORAGE_ACCESS_PATTERN_USER_CFG,
    STORAGE_IO_DEPTH_USER_CFG,
    STORAGE_PROCESS_COUNT_USER_CFG,
    STORAGE_REQUEST_SIZE_USER_CFG,
    REPORT_CMN_USER_CFG,
    create_user_config,
)


# Config precedence is documented at the canonical merge point:
# `RecipeBase.initialize_config()`


TAG_DEFAULT = "default"
TAG_ALL = "all"

CHR_NEG_FILTER = "^"


@dataclass
class RecipeMetadata:
    name: str
    short_name: str
    recipe_name: str
    description: str
    tags: set[str]
    user_config: dict | None = None
    default_config: dict[str, Any] | None = None
    category: str | None = None
    depends_on: set[str] = field(default_factory=set)
    is_visible: Callable[[], bool] = lambda: True

    def __post_init__(self):
        self.tags.update([self.name, self.short_name, TAG_ALL])

    def set_default(self):
        self.tags.update([TAG_DEFAULT])
        return self

    def set_category(self, category):
        self.tags.update([category])
        self.category = category
        return self

    def get_printable_tags(self):
        return sorted(tag for tag in self.tags if tag not in [TAG_ALL, TAG_DEFAULT, self.name, self.short_name])

    def is_default(self):
        return TAG_DEFAULT in self.tags

    def get_default_user_config(self):
        return {key: self.default_config[key] for key in self.user_config if key in self.default_config}


def create_category(name, recipes):
    return [r.set_category(name) for r in recipes]


# Creates a list of RecipeMetadata by concatenating all the lists provided via create_category
# and verifies that each recipe has an unique name, short_name and recipe_name
def create_metadata(*args):
    metadata = []
    names = set()
    short_names = set()
    recipe_names = set()
    for metadata_list in args:
        visible_metadata = []
        for recipe in metadata_list:
            # Remove recipes that are not visible based on their is_visible condition
            if not recipe.is_visible():
                continue
            if recipe.name in names:
                raise AssertionError(f"Duplicate recipe name found: {recipe.name}")
            if recipe.short_name in short_names:
                raise AssertionError(f"Duplicate recipe short name found: {recipe.short_name}")
            if recipe.recipe_name in recipe_names:
                raise AssertionError(f"Duplicate recipe class name found: {recipe.recipe_name}")
            names.add(recipe.name)
            short_names.add(recipe.short_name)
            recipe_names.add(recipe.recipe_name)
            visible_metadata.append(recipe)
        metadata.extend(visible_metadata)
    return metadata


# This list determines how recipes are ordered in standard outputs,
# so make sure categories and recipes are arranged in the desired order
ASCT_RECIPE_METADATA = create_metadata(
    create_category(
        "report",
        [
            RecipeMetadata(
                "system-info",
                "sysinfo",
                "SystemInfo",
                "Output a report containing information about the hardware and software installed on the system.",
                {"system", "info", "sysreport"},
                create_user_config([]),
            ).set_default(),
            RecipeMetadata(
                "cmn",
                "cmn",
                "CMN",
                "Collect cmn configuration information",
                {"cmn", "interconnect", "registers"},
                create_user_config(REPORT_CMN_USER_CFG),
                default_config=REPORT_CMN_DEFAULT_CONFIG,
            ).set_default(),
            RecipeMetadata(
                "ucie",
                "ucie",
                "UCIe",
                "Collect UCIe register information",
                {"ucie", "registers"},
                create_user_config([]),
                is_visible=is_ip_dump_available,
            ).set_default(),
            RecipeMetadata(
                "dms",
                "dms",
                "DMS",
                "Collect DMS register information",
                {"dms", "registers"},
                create_user_config([]),
                is_visible=is_ip_dump_available,
            ).set_default(),
            RecipeMetadata(
                "pss",
                "pss",
                "PSS",
                "Collect PSS register information",
                {"pss", "registers"},
                create_user_config([]),
                is_visible=is_ip_dump_available,
            ).set_default(),
            RecipeMetadata(
                "sysreg",
                "sysreg",
                "SysregInfo",
                "Output a report containing information about the system register values",
                {"register", "sysreg"},
                create_user_config([]),
                is_visible=lambda: enable_sysreg(SYSREG_BASE_PATH),
            ),
            RecipeMetadata(
                "network",
                "network",
                "NetworkInfo",
                "Collect network device names, IP addresses and status data and report it in a structured format.",
                {"IP-address", "NIC", "IP", "network", "network-namespace"},
                create_user_config([]),
            ).set_default(),
        ],
    ),
    create_category(
        "memory",
        [
            RecipeMetadata(
                "idle-latency",
                "il",
                "IdleLatency",
                "Report a matrix of idle memory latency across NUMA nodes",
                {"latency", "uses-huge-pages"},
                create_user_config(MEMORY_COMMON_USER_CFG),
                default_config=MEMORY_DEFAULT_CONFIG,
                depends_on={"latency-sweep"},
            ).set_default(),
            RecipeMetadata(
                "peak-bandwidth",
                "pb",
                "PeakBandwidth",
                "Report peak memory bandwidth",
                {"bandwidth"},
                create_user_config(MEMORY_ITERATIONS_USER_CFG),
                default_config=MEMORY_DEFAULT_CONFIG,
                depends_on={"latency-sweep"},
            ).set_default(),
            RecipeMetadata(
                "cross-numa-bandwidth",
                "cnb",
                "CrossNumaBandwidth",
                "Report cross-NUMA node memory bandwidth",
                {"bandwidth"},
                create_user_config(MEMORY_ITERATIONS_USER_CFG),
                default_config=MEMORY_DEFAULT_CONFIG,
                depends_on={"latency-sweep"},
            ).set_default(),
            RecipeMetadata(
                "latency-sweep",
                "ls",
                "CycleLatencySweep",
                "Sweep latency by datasize to map cache hierarchy and find optimal datasize for other benchmarks",
                {"latency", "sweep", "uses-huge-pages"},
                create_user_config(MEMORY_SWEEP_USER_CFG),
                default_config=MEMORY_DEFAULT_CONFIG,
            ).set_default(),
            RecipeMetadata(
                "bandwidth-sweep",
                "bs",
                "BandwidthSweep",
                "Sweep bandwidth by datasize to map cache hierarchy",
                {"bandwidth", "sweep"},
                create_user_config(MEMORY_SWEEP_USER_CFG),
                default_config=MEMORY_DEFAULT_CONFIG,
                depends_on={"latency-sweep"},
            ).set_default(),
            RecipeMetadata(
                "loaded-latency",
                "ll",
                "LoadedLatency",
                "Report loaded memory latency",
                {"latency", "uses-huge-pages", "long-runtime"},
                create_user_config(LOADED_LATENCY_USER_CFG),
                default_config=LOADED_LATENCY_DEFAULT_CONFIG,
                depends_on={"latency-sweep"},
            ),
            RecipeMetadata(
                "c2c-latency",
                "ccl",
                "CoreToCoreLatency",
                "Report core to core latency (Experimental feature)",
                {"latency", "long-runtime"},
                create_user_config(C2C_USER_CFG),
                default_config=C2C_DEFAULT_CONFIG,
                depends_on={"latency-sweep"},
            ).set_default(),
        ],
    ),
    create_category(
        "network",
        [
            RecipeMetadata(
                "iperf3-tcp-sweep",
                "ipts",
                "Iperf3TcpSweep",
                "Run a TCP-only iperf3 sweep and report throughput plus CPU utilization.",
                {"network", "iperf3", "experimental", "tcp"},
                create_user_config(IPERF3_TCP_SWEEP_USER_CFG),
                default_config=IPERF3_SWEEP_DEFAULT_CONFIG,
                depends_on={"network"},
            ),
            RecipeMetadata(
                "iperf3-udp-sweep",
                "ipus",
                "Iperf3UdpSweep",
                "Run a UDP-only iperf3 sweep and report throughput plus CPU utilization.",
                {"network", "iperf3", "experimental", "udp"},
                create_user_config(IPERF3_UDP_SWEEP_USER_CFG),
                default_config=IPERF3_SWEEP_DEFAULT_CONFIG,
                depends_on={"network"},
            ),
        ],
    ),
    create_category(
        "io",
        [
            RecipeMetadata(
                "storage-request-size-sweep",
                "srss",
                "RequestSizeSweep",
                "Sweep storage I/O request sizes to measure performance",
                {"storage", "dsweep"},
                create_user_config(STORAGE_REQUEST_SIZE_USER_CFG),
                default_config=STORAGE_REQUEST_SIZE_DEFAULT_CONFIG,
            ),
            RecipeMetadata(
                "storage-io-depth-sweep",
                "sids",
                "IODepthSweep",
                "Sweep storage I/O depths to measure performance",
                {"storage", "dsweep"},
                create_user_config(STORAGE_IO_DEPTH_USER_CFG),
                default_config=STORAGE_IO_DEPTH_DEFAULT_CONFIG,
            ),
            RecipeMetadata(
                "storage-process-count-sweep",
                "spcs",
                "ProcessCountSweep",
                "Sweep process count to measure performance",
                {"storage", "dsweep"},
                create_user_config(STORAGE_PROCESS_COUNT_USER_CFG),
                default_config=STORAGE_PROCESS_COUNT_DEFAULT_CONFIG,
            ),
            RecipeMetadata(
                "storage-access-pattern-sweep",
                "saps",
                "AccessPatternSweep",
                "Sweep storage I/O access patterns to measure performance",
                {"storage", "dsweep"},
                create_user_config(STORAGE_ACCESS_PATTERN_USER_CFG),
                default_config=STORAGE_ACCESS_PATTERN_DEFAULT_CONFIG,
            ),
        ],
    ),
)


def get_recipe_metadata(category: list[RecipeMetadata] | None = None):
    """Return recipes, optionally filtered by category.

    Use '^' to exclude a category (for example: ["^memory"]).
    """

    if not category:
        return ASCT_RECIPE_METADATA

    category_filters = category
    include_categories = {value for value in category_filters if not value.startswith(CHR_NEG_FILTER)}
    exclude_categories = {value[1:] for value in category_filters if value.startswith(CHR_NEG_FILTER)}

    recipes = []
    for recipe in ASCT_RECIPE_METADATA:
        recipe_category = recipe.category

        if recipe_category in exclude_categories:
            continue
        if include_categories and recipe_category not in include_categories:
            continue

        recipes.append(recipe)
    return recipes


def get_recipe_metadata_for_names(name_list):
    """Given a list of __valid__ recipe names, return their metadata."""
    metadata_by_name = {item.name: item for item in ASCT_RECIPE_METADATA}
    return [metadata_by_name[name] for name in name_list]


# Get recipes under run cmd (exclude report category)
ASCT_RUN_RECIPE_METADATA = get_recipe_metadata(["^report"])

# Get recipes under report cmd (exclude run category)
ASCT_REPORT_RECIPE_METADATA = get_recipe_metadata(["report"])


def get_recipe_descr_as_dict(recipe_metadata_list=ASCT_RUN_RECIPE_METADATA):
    """
    Returns a dict which includes all the recipes and their description
    for every category in the provided recipe_metadata_list
    """
    dict_data = {}
    for recipe in recipe_metadata_list:
        category = recipe.category
        if category not in dict_data:
            dict_data[category] = {}
        dict_data[category][recipe.name] = recipe.description
    return dict_data


def get_recipe_descr_as_list(recipe_metadata_list=ASCT_RUN_RECIPE_METADATA):
    """
    Returns a list where each item is a list containing 3 items: category_name, benchmark_name, benchmark_descr
    which can be serialized to a csv for every recipe, for every category in the provided recipe_metadata_list
    """
    list_data = []
    for recipe in recipe_metadata_list:
        list_data += [[recipe.category, recipe.name, recipe.description]]
    return list_data


def get_recipe_descr_as_printable_list(recipe_metadata_list=ASCT_RUN_RECIPE_METADATA):
    """
    Returns a list where each row contains a tuple with: name and printable description, for every recipe for
    every category in the provided recipe_metadata_list
    """
    list_data = []
    for recipe in recipe_metadata_list:
        descr_entry = f"{recipe.description}\n  Default: {'yes' if recipe.is_default() else 'no'}"
        descr_entry += f"\n  Keywords: {', '.join(recipe.get_printable_tags())}"
        if recipe.user_config:
            descr_entry += "\n  User configurable parameters:"
            for conf in recipe.user_config.values():
                descr_entry += f"\n  - {conf.name}: {conf.descr}"
        list_data += [(f"{recipe.name},{recipe.short_name}", descr_entry)]
    return list_data


def get_recipe(benchmark_name, recipe_metadata_list=ASCT_RUN_RECIPE_METADATA):
    for recipe in recipe_metadata_list:
        if benchmark_name in (recipe.short_name, recipe.name):
            return recipe
    return None


def get_all_tags(recipe_metadata_list=ASCT_RUN_RECIPE_METADATA):
    """
    Returns a list with all possible tags (including negative ones)
    """
    name_tags = []
    other_tags = set()

    for recipe in recipe_metadata_list:
        name_tags.append(recipe.name)
        name_tags.append(recipe.short_name)
        other_tags.update(recipe.get_printable_tags())
    other_tags.update([TAG_ALL, TAG_DEFAULT])
    return (
        name_tags
        + [f"{CHR_NEG_FILTER}{tag}" for tag in name_tags]
        + list(other_tags)
        + [f"{CHR_NEG_FILTER}{tag}" for tag in other_tags]
    )


def get_all_run_tags():
    return get_all_tags(ASCT_RUN_RECIPE_METADATA)


def get_all_report_tags():
    return get_all_tags(ASCT_REPORT_RECIPE_METADATA)
