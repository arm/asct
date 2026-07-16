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

from asct.core.recipes.configuration.metadata import get_recipe
from asct.core.recipes.recipe_base import RecipeBase


class DummyRecipe(RecipeBase):
    def lookup_benchmark_binary(self):
        return None

    def run_function(self):
        return None


# Tests that unpacking of default config from metadata creates an isolated copy for each
# recipe instance, and that the default config values are as expected (ie. override works).
def test_recipe_base_materializes_defaults_from_metadata():
    metadata = get_recipe("storage-io-depth-sweep")
    recipe = DummyRecipe(metadata)

    cfg = recipe._create_default_config()
    assert cfg.duration == 60
    assert cfg.iodepth == 16
    assert cfg.iodepth_sweep_steps == [2**i for i in range(8)]


def test_recipe_base_default_config_isolation_between_instances():
    metadata = get_recipe("storage-request-size-sweep")

    cfg_1 = DummyRecipe(metadata)._create_default_config()
    cfg_1.filenames.append("fio-a.img")
    cfg_1.request_size_sweep_steps.append(256 * 1024)

    cfg_2 = DummyRecipe(metadata)._create_default_config()
    assert cfg_2.filenames == []
    assert cfg_2.request_size_sweep_steps == [4 * 1024, 8 * 1024, 16 * 1024, 32 * 1024, 64 * 1024, 128 * 1024]


def test_recipe_base_deserialize_supports_legacy_plain_raw_result():
    metadata = get_recipe("storage-request-size-sweep")
    recipe = DummyRecipe(metadata)

    recipe.deserialize({"value": {"row0": 1.5}})

    assert recipe._loaded_raw_result == {"value": {"row0": 1.5}}
    assert recipe.result.dataframe.to_dict() == {"value": {"row0": 1.5}}


def test_recipe_base_deserialize_uses_saved_result_desc():
    metadata = get_recipe("storage-request-size-sweep")
    recipe = DummyRecipe(metadata)

    recipe.deserialize({
        "raw_result": {"value": {"row0": 1.5}},
        "metadata": {
            "result_desc": "Saved description",
        },
    })

    assert recipe.result.desc == "Saved description"
