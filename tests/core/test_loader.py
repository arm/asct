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

import os
import json
import tempfile
import shutil
import pytest
import asct.core.sysdiff.diff_rules  # noqa: F401
from asct.core.sysdiff.loader import group_by_first_dot, RecipeRunLoader
from asct.core.sysdiff.diff_rules import RuleBase, Rule
from asct.core.sysdiff.comparators import NumericToleranceComparator
from asct.core.recipes.configuration.metadata import get_recipe
from asct.core.recipes.impl import SystemInfo


def test_group_by_first_dot_basic():
    flat = {"a.b": 1, "a.c": 2, "d": 3, "e.f.g": 4}
    grouped = group_by_first_dot(flat)
    assert grouped["a"] == {"b": 1, "c": 2}
    assert grouped["d"] == 3
    assert grouped["e"] == {"f.g": 4}


def test_group_by_first_dot_no_dot():
    flat = {"foo": 42}
    grouped = group_by_first_dot(flat)
    assert grouped["foo"] == 42


def test_group_by_first_dot_nested():
    flat = {"x.y.z": 99}
    grouped = group_by_first_dot(flat)
    assert grouped["x"] == {"y.z": 99}


@pytest.fixture
def temp_json_dir():
    temp_dir = tempfile.mkdtemp()
    json_path = os.path.join(temp_dir, "asct.json")
    data = {
        "metadata": {
            "cmd_arguments": {"command": "run --foo"},
            "version": "1.0",
            "run_id": "test-run-id",
        },
        "raw": {
            "system-info": {"raw_result": {"os": "Linux", "hostname": "test-host"}, "metadata": {}},
            "loaded-latency": {
                "raw_result": {
                    "Injected NOPs": {"0": 100},
                    "Loaded latency [ns]": {"0": 50.0},
                    "Bandwidth [GB/s]": {"0": 10.0},
                },
                "metadata": {},
            },
        },
    }
    with open(json_path, "w") as f:
        json.dump(data, f)
    yield temp_dir
    shutil.rmtree(temp_dir)


def test_recipe_run_loader_basic(temp_json_dir):
    loader = RecipeRunLoader(temp_json_dir, [], [])
    assert loader.cmd_arguments == "run --foo"
    names = loader.all_recipe_names()
    assert set(names) == {"metadata", "system-info", "loaded-latency"}
    assert loader.get_recipe("system-info") == {
        "os": "Linux",
        "hostname": "test-host",
        "bios_info.release_date": None,
        "bios_info.vendor": None,
        "bios_info.version": None,
        "memory.manufacturer": None,
        "memory.part_number": None,
    }
    assert loader.get_recipe("loaded-latency") == {"100.Loaded latency [ns]": 50.0, "100.Bandwidth [GB/s]": 10.0}
    assert loader.get_recipe("nonexistent") == {}


def test_recipe_run_loader_include_list(temp_json_dir):
    loader = RecipeRunLoader(temp_json_dir, ["system-info", "metadata"], [])
    names = loader.all_recipe_names()
    assert set(names) == {"system-info", "metadata"}
    assert loader.get_recipe("system-info") == {
        "os": "Linux",
        "hostname": "test-host",
        "bios_info.release_date": None,
        "bios_info.vendor": None,
        "bios_info.version": None,
        "memory.manufacturer": None,
        "memory.part_number": None,
    }
    assert loader.get_recipe("loaded-latency") == {}


def test_recipe_run_loader_exclude_list(temp_json_dir):
    loader = RecipeRunLoader(temp_json_dir, [], ["loaded-latency"])
    names = loader.all_recipe_names()
    assert "loaded-latency" not in names
    assert "system-info" in names
    assert loader.get_recipe("loaded-latency") == {}


def test_recipe_run_loader_include_and_exclude(temp_json_dir):
    loader = RecipeRunLoader(temp_json_dir, ["system-info", "loaded-latency"], ["loaded-latency"])
    names = loader.all_recipe_names()
    assert names == ["metadata", "system-info"]  # metadata is always included
    assert loader.get_recipe("system-info") == {
        "os": "Linux",
        "hostname": "test-host",
        "bios_info.release_date": None,
        "bios_info.vendor": None,
        "bios_info.version": None,
        "memory.manufacturer": None,
        "memory.part_number": None,
    }
    assert loader.get_recipe("loaded-latency") == {}


def test_recipe_run_loader_filename_property(temp_json_dir):
    loader = RecipeRunLoader(temp_json_dir, [], [])
    assert loader.run_name == os.path.basename(temp_json_dir)


def test_recipe_run_loader_legacy_format_supports_plain_raw_entries(tmp_path):
    json_path = tmp_path / "asct.json"
    data = {
        "diff": {
            "metadata.cmd_arguments.command": "run memory",
            "metadata.version": "0.5.0",
            "latency-sweep.data.Lower Bound.L1": 128,
            "latency-sweep.data.Upper Bound.L1": 8192,
            "latency-sweep.data.Optimum Datasize.L1": 4096,
            "latency-sweep.data.Latency [ns].L1": 10.0,
        },
        "raw": {
            "system-info": {"os": "Linux", "hostname": "legacy-host"},
            "loaded-latency": {
                "Injected NOPs": {"0": 100},
                "Loaded latency [ns]": {"0": 50.0},
                "Bandwidth [GB/s]": {"0": 10.0},
            },
            "latency-sweep": json.dumps({
                "Lower Bound": {"L1": 128},
                "Upper Bound": {"L1": 8192},
                "Optimum Datasize": {"L1": 4096},
                "Latency [ns]": {"L1": 10.0},
            }),
        },
    }
    with open(json_path, "w") as f:
        json.dump(data, f)

    loader = RecipeRunLoader(str(tmp_path), [], [])

    assert loader.cmd_arguments == "run memory"
    assert loader.raw_data["latency-sweep"]["Lower Bound"]["L1"] == 128
    assert loader.get_recipe("system-info") == {
        "os": "Linux",
        "hostname": "legacy-host",
        "bios_info.release_date": None,
        "bios_info.vendor": None,
        "bios_info.version": None,
        "memory.manufacturer": None,
        "memory.part_number": None,
    }
    assert loader.get_recipe("loaded-latency") == {"100.Loaded latency [ns]": 50.0, "100.Bandwidth [GB/s]": 10.0}
    assert loader.get_recipe("latency-sweep") == {
        "L1.Lower Bound": 128,
        "L1.Upper Bound": 8192,
        "L1.Optimum Datasize": 4096,
        "L1.Latency [ns]": 10.0,
    }
    assert loader.get_recipe("metadata") == {
        "cmd_arguments.command": "run memory",
        "version": "0.5.0",
    }


def test_recipe_run_loader_uses_legacy_bandwidth_sweep_diff_summary_and_decodes_raw_string(tmp_path):
    json_path = tmp_path / "asct.json"
    data = {
        "diff": {
            "metadata.cmd_arguments.command": "run bandwidth-sweep",
            "metadata.version": "0.5.0",
            "bandwidth-sweep.data.L1.Datasize Used": 32832,
            "bandwidth-sweep.data.L1.Bandwidth [GB/s]": 163.93,
        },
        "raw": {
            "bandwidth-sweep": json.dumps({
                "sizes": {"0": 128, "1": 32832},
                "total_bandwidth_mbps": {"0": 1000.0, "1": 2000.0},
            }),
        },
    }
    with open(json_path, "w") as f:
        json.dump(data, f)

    loader = RecipeRunLoader(str(tmp_path), [], [])

    assert loader.raw_data["bandwidth-sweep"]["sizes"]["1"] == 32832
    assert loader.get_recipe("bandwidth-sweep") == {
        "L1.Datasize Used": 32832,
        "L1.Bandwidth [GB/s]": 163.93,
    }


def test_recipe_run_loader_normalizes_legacy_c2c_latency_to_summary_stats(tmp_path):
    json_path = tmp_path / "asct.json"
    data = {
        "diff": {
            "metadata.cmd_arguments.command": "run c2c-latency",
            "metadata.version": "0.5.0",
            "c2c-latency.data.CPUA.0": 19,
            "c2c-latency.data.CPUA.1": 18,
            "c2c-latency.data.CPUB.0": 18,
            "c2c-latency.data.CPUB.1": 19,
            "c2c-latency.data.LATENCY.0": 18.59,
            "c2c-latency.data.LATENCY.1": 24.62,
            "c2c-latency.data.CPUA_NODE.0": 0,
            "c2c-latency.data.CPUA_NODE.1": 0,
            "c2c-latency.data.MEMBIND_NODE.0": 0,
            "c2c-latency.data.MEMBIND_NODE.1": 0,
        },
        "raw": {
            "c2c-latency": {
                "CPUA": {"0": 19, "1": 18},
                "CPUB": {"0": 18, "1": 19},
                "LATENCY": {"0": 18.59, "1": 24.62},
                "CPUA_NODE": {"0": 0, "1": 0},
                "MEMBIND_NODE": {"0": 0, "1": 0},
            },
        },
    }
    with open(json_path, "w") as f:
        json.dump(data, f)

    loader = RecipeRunLoader(str(tmp_path), [], [])

    assert loader.get_recipe("c2c-latency") == {
        "Local.min": 18.59,
        "Local.max": 24.62,
        "Local.mean": pytest.approx(21.605),
        "Local.median": pytest.approx(21.605),
        "Local.p99": pytest.approx(24.5597),
    }


def test_recipe_run_loader_normalizes_legacy_loaded_latency_to_nop_keyed_rows(tmp_path):
    json_path = tmp_path / "asct.json"
    data = {
        "diff": {
            "metadata.cmd_arguments.command": "run loaded-latency",
            "metadata.version": "0.5.0",
            "loaded-latency.data.Injected NOPs.0": 3000,
            "loaded-latency.data.Injected NOPs.1": 900,
            "loaded-latency.data.Injected NOPs.2": 0,
            "loaded-latency.data.Loaded latency [ns].0": 219.233096,
            "loaded-latency.data.Loaded latency [ns].1": 118.406542,
            "loaded-latency.data.Loaded latency [ns].2": 306.570278,
            "loaded-latency.data.Bandwidth [GB/s].0": 1.132399291,
            "loaded-latency.data.Bandwidth [GB/s].1": 4.126208412,
            "loaded-latency.data.Bandwidth [GB/s].2": 77.263320361,
        },
        "raw": {
            "loaded-latency": {
                "Injected NOPs": {"0": 3000, "1": 900, "2": 0},
                "Loaded latency [ns]": {"0": 219.233096, "1": 118.406542, "2": 306.570278},
                "Bandwidth [GB/s]": {"0": 1.132399291, "1": 4.126208412, "2": 77.263320361},
            },
        },
    }
    with open(json_path, "w") as f:
        json.dump(data, f)

    loader = RecipeRunLoader(str(tmp_path), [], [])

    assert loader.get_recipe("loaded-latency") == {
        "3000.Loaded latency [ns]": 219.233096,
        "3000.Bandwidth [GB/s]": 1.132399291,
        "900.Loaded latency [ns]": 118.406542,
        "900.Bandwidth [GB/s]": 4.126208412,
        "0.Loaded latency [ns]": 306.570278,
        "0.Bandwidth [GB/s]": 77.263320361,
    }


def test_recipe_run_loader_normalizes_loaded_latency_for_editable_050_version(tmp_path):
    json_path = tmp_path / "asct.json"
    data = {
        "diff": {
            "metadata.cmd_arguments.command": "run loaded-latency",
            "metadata.version": "0.5.0+editable.b154756",
            "loaded-latency.data.Injected NOPs.0": 3000,
            "loaded-latency.data.Injected NOPs.1": 0,
            "loaded-latency.data.Loaded latency [ns].0": 219.233096,
            "loaded-latency.data.Loaded latency [ns].1": 306.570278,
            "loaded-latency.data.Bandwidth [GB/s].0": 1.132399291,
            "loaded-latency.data.Bandwidth [GB/s].1": 77.263320361,
        },
        "raw": {
            "loaded-latency": {
                "Injected NOPs": {"0": 3000, "1": 0},
                "Loaded latency [ns]": {"0": 219.233096, "1": 306.570278},
                "Bandwidth [GB/s]": {"0": 1.132399291, "1": 77.263320361},
            },
        },
    }
    with open(json_path, "w") as f:
        json.dump(data, f)

    loader = RecipeRunLoader(str(tmp_path), [], [])

    assert loader.get_recipe("loaded-latency") == {
        "3000.Loaded latency [ns]": 219.233096,
        "3000.Bandwidth [GB/s]": 1.132399291,
        "0.Loaded latency [ns]": 306.570278,
        "0.Bandwidth [GB/s]": 77.263320361,
    }


def test_recipe_run_loader_normalizes_legacy_system_info_fields(tmp_path):
    json_path = tmp_path / "asct.json"
    data = {
        "diff": {
            "metadata.cmd_arguments.command": "run system-info",
            "metadata.version": "0.5.0",
            "system-info.data.sys_info.manufacturer": None,
            "system-info.data.memory.total_size": 16589582336,
            "system-info.data.sys_hw.cpu_features.0": "fpu",
            "system-info.data.sys_hw.cpu_features.1": "vme",
            "system-info.data.sys_hw.caches.L1D 48K 12-way 64b-line": 10,
            "system-info.data.sys_hw.caches.L1I 32K 8-way 64b-line": 10,
            "system-info.data.sys_hw.caches.L2U 1.25M 10-way 64b-line": 10,
            "system-info.data.sys_hw.caches.L3U 24M 12-way 64b-line": 1,
        },
        "raw": {
            "system-info": {
                "sys_info": {
                    "manufacturer": None,
                    "product_name": None,
                    "version": None,
                    "serial": None,
                    "uuid": None,
                },
                "memory": {
                    "total_size": 16589582336,
                    "n_channels": None,
                    "type_str": None,
                    "speed": None,
                    "data_width": None,
                    "peak_theoretical_bw": None,
                },
                "sys_hw": {
                    "cpu_features": ["fpu", "vme"],
                    "caches": {
                        "L1D 48K 12-way 64b-line": 10,
                        "L1I 32K 8-way 64b-line": 10,
                        "L2U 1.25M 10-way 64b-line": 10,
                        "L3U 24M 12-way 64b-line": 1,
                    },
                },
            },
        },
    }
    with open(json_path, "w") as f:
        json.dump(data, f)

    loader = RecipeRunLoader(str(tmp_path), [], [])

    recipe = loader.get_recipe("system-info")

    assert recipe["bios_info.release_date"] is None
    assert recipe["bios_info.vendor"] is None
    assert recipe["bios_info.version"] is None
    assert recipe["memory.manufacturer"] is None
    assert recipe["memory.part_number"] is None
    assert recipe["memory.total_size"] == 16589582336
    assert recipe["sys_hw.cpu_features.0"] == "fpu"
    assert recipe["sys_hw.cpu_features.1"] == "vme"
    assert recipe["sys_hw.cache_size_dict.L1"] == pytest.approx(49152.0)
    assert recipe["sys_hw.cache_size_dict.L2"] == pytest.approx(1310720.0)
    assert recipe["sys_hw.cache_size_dict.L3"] == pytest.approx(25165824.0)
    assert recipe["sys_hw.caches.L1D 48K 12-way 64b-line"] == 10
    assert recipe["sys_hw.caches.L1I 32K 8-way 64b-line"] == 10
    assert recipe["sys_hw.caches.L2U 1.25M 10-way 64b-line"] == 10
    assert recipe["sys_hw.caches.L3U 24M 12-way 64b-line"] == 1
    assert recipe["sys_info.manufacturer"] is None


def test_recipe_run_loader_normalizes_legacy_cmn_register_fields(tmp_path):
    json_path = tmp_path / "asct.json"
    data = {
        "diff": {
            "metadata.cmd_arguments.command": "run cmn",
            "metadata.version": "0.5.0",
            "cmn.data.0.cmn(0).cfg.example.raw_value": "0x58f",
            "cmn.data.0.cmn(0).cfg.example.pmccntr": "0x58f",
        },
        "raw": {
            "cmn": {
                "system_type": "test-system",
                "instances": [
                    {
                        "id": 0,
                        "summary": {},
                        "registers": [
                            {
                                "node": "cmn(0).cfg",
                                "reg_name": "example",
                                "value": "0x58f",
                                "fields": [
                                    {
                                        "field_name": "pmccntr",
                                        "value": "0x58f",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
        },
    }
    with open(json_path, "w") as f:
        json.dump(data, f)

    loader = RecipeRunLoader(str(tmp_path), [], [])

    assert loader.get_recipe("cmn") == {
        "0.cmn(0).cfg.example.raw_value": "0x58f",
        "0.cmn(0).cfg.example.pmccntr": "0x58f",
    }


@pytest.mark.parametrize("recipe", ["ucie", "dms", "pss"])
def test_recipe_run_loader_normalizes_legacy_ip_register_fields(tmp_path, recipe):
    json_path = tmp_path / "asct.json"
    data = {
        "diff": {
            "metadata.cmd_arguments.command": f"run {recipe}",
            "metadata.version": "0.5.0",
            f"{recipe}.data.instance0.GLOBAL_REG.example.raw_value": "0x4",
            f"{recipe}.data.instance0.GLOBAL_REG.example.enabled": "0x1",
        },
        "raw": {recipe: {}},
    }
    with open(json_path, "w") as f:
        json.dump(data, f)

    loader = RecipeRunLoader(str(tmp_path), [], [])

    assert loader.get_recipe(recipe) == {
        "instance0.GLOBAL_REG.example.raw_value": "0x4",
        "instance0.GLOBAL_REG.example.enabled": "0x1",
    }


def test_system_info_deserialize_derives_cache_size_dict_from_caches():
    recipe = SystemInfo(get_recipe("system-info"))

    recipe.deserialize({
        "sys_hw": {
            "caches": {
                "L1D 48K 12-way 64b-line": 10,
                "L1I 32K 8-way 64b-line": 10,
                "L2U 1.25M 10-way 64b-line": 10,
                "L3U 24M 12-way 64b-line": 1,
            },
        },
    })

    cache_size_dict = recipe.to_dict()["sys_hw"]["cache_size_dict"]
    assert cache_size_dict["L1"] == pytest.approx(49152.0)
    assert cache_size_dict["L2"] == pytest.approx(1310720.0)
    assert cache_size_dict["L3"] == pytest.approx(25165824.0)


def test_recipe_run_loader_normalizes_current_system_info_cpu_features_list(tmp_path):
    json_path = tmp_path / "asct.json"
    data = {
        "metadata": {
            "cmd_arguments": {"command": "run system-info"},
            "version": "0.5.0",
        },
        "raw": {
            "system-info": {
                "raw_result": {
                    "sys_hw": {
                        "cpu_features": ["fpu", "vme"],
                    },
                },
                "metadata": {},
            },
        },
    }
    with open(json_path, "w") as f:
        json.dump(data, f)

    loader = RecipeRunLoader(str(tmp_path), [], [])

    assert loader.get_recipe("system-info") == {
        "bios_info.release_date": None,
        "bios_info.vendor": None,
        "bios_info.version": None,
        "memory.manufacturer": None,
        "memory.part_number": None,
        "sys_hw.cpu_features.0": "fpu",
        "sys_hw.cpu_features.1": "vme",
    }


def test_recipe_run_loader_reads_split_recipe_metadata_file(tmp_path):
    json_path = tmp_path / "asct.json"
    data = {
        "metadata": {
            "cmd_arguments": {"command": "run loaded-latency"},
            "version": "0.5.1",
        },
    }
    with open(json_path, "w") as f:
        json.dump(data, f)

    recipe_dir = tmp_path / "raw" / "loaded-latency"
    recipe_dir.mkdir(parents=True)
    with open(recipe_dir / "data.json", "w") as f:
        json.dump(
            {
                "Injected NOPs": {"0": 0},
                "Loaded latency [ns]": {"0": 12.5},
                "Bandwidth [GB/s]": {"0": 42.0},
            },
            f,
        )
    with open(recipe_dir / "metadata.json", "w") as f:
        json.dump({"description": "saved loaded latency", "config": {"cycle_base": False}}, f)

    loader = RecipeRunLoader(str(tmp_path), [], [])

    assert loader.raw_data["loaded-latency"]["metadata"] == {
        "description": "saved loaded latency",
        "config": {"cycle_base": False},
    }
    assert loader.raw_data["loaded-latency"]["raw_result"]["Injected NOPs"] == {"0": 0}


def test_recipe_run_loader_rebuilds_current_split_summary_recipes(tmp_path):
    json_path = tmp_path / "asct.json"
    data = {
        "metadata": {
            "cmd_arguments": {"command": "diff"},
            "version": "0.5.1",
        },
    }
    with open(json_path, "w") as f:
        json.dump(data, f)

    latency_dir = tmp_path / "raw" / "latency-sweep"
    latency_dir.mkdir(parents=True)
    with open(latency_dir / "data.json", "w") as f:
        json.dump({"sweep_data": {"sizes": {"0": 128, "1": 256}}}, f)
    with open(latency_dir / "summary.json", "w") as f:
        json.dump(
            {
                "Lower Bound": {"L1": 128},
                "Upper Bound": {"L1": 256},
                "Optimum Datasize": {"L1": 192},
                "Latency [ns]": {"L1": 8.5},
            },
            f,
        )

    bandwidth_dir = tmp_path / "raw" / "bandwidth-sweep"
    bandwidth_dir.mkdir(parents=True)
    with open(bandwidth_dir / "data.json", "w") as f:
        json.dump({"sweep_data": {"sizes": {"0": 128, "1": 256}}}, f)
    with open(bandwidth_dir / "summary.json", "w") as f:
        json.dump(
            {
                "Datasize Used": {"0": 128},
                "Level": {"0": "L1"},
                "Bandwidth [GB/s]": {"0": 42.0},
            },
            f,
        )

    loader = RecipeRunLoader(str(tmp_path), [], [])

    assert loader.get_recipe("latency-sweep") == {
        "L1.Lower Bound": 128,
        "L1.Upper Bound": 256,
        "L1.Optimum Datasize": 192,
        "L1.Latency [ns]": 8.5,
    }
    assert loader.get_recipe("bandwidth-sweep") == {
        "L1.Datasize Used": 128,
        "L1.Bandwidth [GB/s]": 42.0,
    }


def test_recipe_run_loader_normalizes_current_raw_only_diff_shapes(tmp_path):
    json_path = tmp_path / "asct.json"
    data = {
        "metadata": {
            "cmd_arguments": {"command": "diff"},
            "version": "0.5.1",
        },
    }
    with open(json_path, "w") as f:
        json.dump(data, f)

    peak_dir = tmp_path / "raw" / "peak-bandwidth"
    peak_dir.mkdir(parents=True)
    with open(peak_dir / "data.json", "w") as f:
        json.dump(
            {
                "Traffic type": {"0": "All Reads"},
                "Peak BW [GB/s]": {"0": 71.7},
            },
            f,
        )

    loaded_dir = tmp_path / "raw" / "loaded-latency"
    loaded_dir.mkdir(parents=True)
    with open(loaded_dir / "data.json", "w") as f:
        json.dump(
            {
                "Injected NOPs": {"0": 0, "1": 10},
                "Loaded latency [ns]": {"0": 306.5, "1": 120.0},
                "Bandwidth [GB/s]": {"0": 77.2, "1": 22.1},
            },
            f,
        )

    c2c_dir = tmp_path / "raw" / "c2c-latency"
    c2c_dir.mkdir(parents=True)
    with open(c2c_dir / "data.json", "w") as f:
        json.dump(
            {
                "CPUA": {"0": 0, "1": 0},
                "CPUB": {"0": 1, "1": 2},
                "LATENCY": {"0": 10.0, "1": 20.0},
                "CPUA_NODE": {"0": 0, "1": 0},
                "MEMBIND_NODE": {"0": 0, "1": 1},
            },
            f,
        )

    loader = RecipeRunLoader(str(tmp_path), [], [])

    assert loader.get_recipe("peak-bandwidth") == {
        "All Reads.Peak BW [GB/s]": 71.7,
    }
    assert loader.get_recipe("loaded-latency") == {
        "0.Loaded latency [ns]": 306.5,
        "0.Bandwidth [GB/s]": 77.2,
        "10.Loaded latency [ns]": 120.0,
        "10.Bandwidth [GB/s]": 22.1,
    }
    assert loader.get_recipe("c2c-latency") == {
        "Local.min": 10.0,
        "Local.max": 10.0,
        "Local.mean": 10.0,
        "Local.median": 10.0,
        "Local.p99": 10.0,
        "Remote.min": 20.0,
        "Remote.max": 20.0,
        "Remote.mean": 20.0,
        "Remote.median": 20.0,
        "Remote.p99": 20.0,
    }


def test_recipe_run_loader_rejects_incompatible_metadata_version(tmp_path):
    json_path = tmp_path / "asct.json"
    data = {
        "metadata": {
            "cmd_arguments": {"command": "run --foo"},
            "version": "0.3.9",
        },
        "raw": {},
    }
    with open(json_path, "w") as f:
        json.dump(data, f)

    with pytest.raises(RuntimeError, match=r"ASCT version '0\.3\.9' results are not supported"):
        RecipeRunLoader(str(tmp_path), [], [])


class CustomPeakBandwidthRule(RuleBase):
    """Rules for comparing peak bandwidth results."""

    def __init__(self):
        super().__init__([
            Rule("result.Peak BW [GB/s].*", NumericToleranceComparator(abs_tolerance=0.5)),
            Rule("result.% of Peak Theoretical.*", NumericToleranceComparator(percent_tolerance=5)),
        ])


def test_peak_bandwidth_rule_applied():
    data1 = {"result.Peak BW [GB/s].1": 100.0}
    data2 = {"result.Peak BW [GB/s].1": 100.5}
    data3 = {"result.Peak BW [GB/s].1": 100.6}
    data4 = {"result.% of Peak Theoretical.1": 100.0}
    data5 = {"result.% of Peak Theoretical.1": 105.0}
    data6 = {"result.% of Peak Theoretical.1": 106.0}

    rules = CustomPeakBandwidthRule()
    path = "result.Peak BW [GB/s]"
    rule = rules.get_rule(path)
    assert isinstance(rule.comparator, NumericToleranceComparator)

    # Now use the comparator to compare the values
    val1 = data1["result.Peak BW [GB/s].1"]
    val2 = data2["result.Peak BW [GB/s].1"]

    # Should be considered equal within absolute tolerance of 0.5
    assert rule.comparator(val1, val2, path)

    # Should not be considered equal as difference is 0.6 > 0.5
    val3 = data3["result.Peak BW [GB/s].1"]
    assert not rule.comparator(val1, val3, path)

    # Test the percentage tolerance rule
    path = "result.% of Peak Theoretical"
    rule = rules.get_rule(path)

    assert isinstance(rule.comparator, NumericToleranceComparator)

    # Should be considered equal within 5% tolerance
    val4 = data4["result.% of Peak Theoretical.1"]
    val5 = data5["result.% of Peak Theoretical.1"]
    assert rule.comparator(val4, val5, path)

    # Should not be considered equal as difference is >5%
    val6 = data6["result.% of Peak Theoretical.1"]
    assert not rule.comparator(val4, val6, path)
