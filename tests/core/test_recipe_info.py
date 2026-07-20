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

"""
Simple tests of src/core/recipes/configuration/metadata.py
"""

from types import SimpleNamespace

import pytest
from asct.core.recipes.configuration import registry as recipe_registry
from asct.core.recipes.configuration.metadata import get_recipe
from asct.core.recipes.configuration.schema import UserConfigDescr, numa_cpu_list_conv, user_cfg_schema


@pytest.mark.parametrize(
    "value,expected",
    [
        ("", []),  # empty string
        ("5", [5]),  # single number string
        ("0,1,2", [0, 1, 2]),  # simple list
        ("3-5", [3, 4, 5]),  # simple range
        ("0,2-4,6", [0, 2, 3, 4, 6]),  # mix of single and range
        (7, [7]),  # non-string single int
        ("1-3,2-4", [1, 2, 3, 2, 3, 4]),  # overlapping ranges, duplicates preserved
    ],
)
def test_numa_cpu_list_conv_valid(value, expected):
    assert numa_cpu_list_conv(value) == expected


@pytest.mark.parametrize("bad_value", ["a", "1-a", "x-y", "1,,2", "1-", "-2"])
def test_numa_cpu_list_conv_invalid_inputs_raise(bad_value):
    with pytest.raises(ValueError):
        numa_cpu_list_conv(bad_value)


@pytest.mark.parametrize(
    "recipe_name, expected_subset",
    [
        (
            "idle-latency",
            {
                "pmu_mode": False,
                "duration": 0.25,
                "iterations": 100000,
                "data_size": None,
                "bw_delay": 0,
                "cycle_base": False,
            },
        ),
        (
            "loaded-latency",
            {
                "phase": "both",
                "injected_nops": [3000, 900, 500, 180, 100, 80, 70, 50, 40, 30, 20, 10, 0],
                "cycle_base": False,
            },
        ),
        (
            "c2c-latency",
            {
                "iterations": 400,
                "number_of_runs": 1,
                "all_cpus": False,
                "hist_bins": 10,
                "heatmap_vmax": 200,
            },
        ),
        (
            "storage-io-depth-sweep",
            {
                "duration": 60,
                "ioengine": "libaio",
                "iodepth": 16,
                "iodepth_sweep_steps": [2**i for i in range(8)],
                "create_temp_file": True,
                "direct": True,
            },
        ),
    ],
)
def test_metadata_default_config_expected_values(recipe_name, expected_subset):
    metadata = get_recipe(recipe_name)

    cfg = metadata.default_config or {}
    for key, expected_value in expected_subset.items():
        assert cfg[key] == expected_value


def test_user_cfg_schema_invalid_field_raises_clear_error():
    with pytest.raises(ValueError, match=r"Unknown user config field\(s\): .*not_a_field"):
        user_cfg_schema("duration", "not_a_field")


def test_user_cfg_schema_allows_field_description_override():
    base = user_cfg_schema("duration")[0]
    custom = user_cfg_schema("duration", overrides={"duration": {"descr": "Custom duration text"}})[0]

    assert base.descr == "Benchmark duration in seconds"
    assert custom.descr == "Custom duration text"
    assert user_cfg_schema("duration")[0].descr == "Benchmark duration in seconds"


def test_user_cfg_schema_override_rejects_unknown_schema_field():
    with pytest.raises(ValueError, match=r"Override field\(s\) not present in this schema: iterations"):
        user_cfg_schema("duration", overrides={"iterations": {"descr": "x"}})


def test_user_config_descr_new_from_preserves_original_path():
    original = UserConfigDescr(name="storage.blocksize", descr="Original")
    updated = original.new_from(descr="Updated")

    assert original.path == ["storage", "blocksize"]
    assert updated.path == ["storage", "blocksize"]
    assert updated.name == "blocksize"
    assert updated.descr == "Updated"


def test_affinity_schema_supports_int_list_or_unset():
    client_affinities_conv = user_cfg_schema("client_affinities")[0].conv
    server_affinity_conv = user_cfg_schema("server_affinity")[0].conv

    assert client_affinities_conv(None) == []
    assert client_affinities_conv(2) == [2]
    assert client_affinities_conv("1-3") == [1, 2, 3]
    assert server_affinity_conv(None) is None
    assert server_affinity_conv("3") == 3


def test_network_schema_constrains_sweep_integer_inputs():
    duration_conv = user_cfg_schema("duration_sweep_steps")[0].conv
    message_size_conv = user_cfg_schema("message_size_sweep_steps")[0].conv
    bandwidth_target_conv = user_cfg_schema("bandwidth_target_bps_sweep_steps")[0].conv

    assert duration_conv("0,3") == [3]
    assert message_size_conv([0, 1200]) == [1200]
    assert bandwidth_target_conv("default,0,1000000") == [None, 0, 1000000]
    assert bandwidth_target_conv([None, -1, 0, 1000000]) == [None, 0, 1000000]


def test_get_recipe_lookup_by_name_and_short_name():
    by_name = get_recipe("idle-latency")
    by_short_name = get_recipe("il")

    assert by_name is not None
    assert by_short_name is not None
    assert by_name.name == "idle-latency"
    assert by_short_name.name == "idle-latency"


def test_get_filtered_recipes_tracks_direct_and_indirect_negative_matches(monkeypatch):
    metadata = [
        SimpleNamespace(name="alpha", tags={"fast"}, depends_on=set()),
        SimpleNamespace(name="beta", tags={"fast", "skip"}, depends_on=set()),
        SimpleNamespace(name="gamma", tags={"fast"}, depends_on={"beta"}),
    ]

    monkeypatch.setattr(recipe_registry, "ASCT_RECIPE_METADATA", metadata)

    filtered = recipe_registry.get_filtered_recipes(metadata, ["fast", "^skip"], add_dependencies=False)

    assert filtered.positive_filter == ["fast"]
    assert filtered.negative_filter == ["skip"]
    assert filtered.filtered_in == ["alpha", "beta", "gamma"]
    assert filtered.filtered_out == ["beta"]
    assert filtered.filtered_out_depends == [("gamma", "beta")]
    assert filtered.filtered_list == ["alpha"]
    assert filtered.complete_list == ["alpha"]


def test_iperf_tcp_user_config_exposes_bandwidth_target_sweep_knob():
    metadata = get_recipe("iperf3-tcp-sweep")
    assert metadata is not None

    assert "server_host" in metadata.user_config
    assert "duration_sweep_steps" in metadata.user_config
    assert "message_size_sweep_steps" in metadata.user_config
    assert "window_sweep_steps" in metadata.user_config
    assert "bandwidth_target_bps_sweep_steps" in metadata.user_config


def test_iperf_udp_user_config_exposes_udp_bandwidth_sweep_knob():
    metadata = get_recipe("iperf3-udp-sweep")
    assert metadata is not None

    assert "server_host" in metadata.user_config
    assert "duration_sweep_steps" in metadata.user_config
    assert "message_size_sweep_steps" in metadata.user_config
    assert "window_sweep_steps" in metadata.user_config
    assert "bandwidth_target_bps_sweep_steps" in metadata.user_config
