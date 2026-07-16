# ---------------------------------------------------------------------------------
# SPDX-FileCopyrightText: Copyright (C) 2026 Arm Limited and/or its affiliates
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

from .utils import run_asct, read_file_json
from asct.core.recipes.configuration.metadata import get_recipe_metadata
import pathlib


def verify_config_json(json_file_path, requested_list, custom_updates=None):
    """Verify that the configuration JSON contains one entry for every requested recipe.

    If requested_list is None, verify that the JSON contains one entry for every
    recipe that has a user configuration.
    """
    if custom_updates is None:
        custom_updates = {}

    if not requested_list:
        recipe_metadata = get_recipe_metadata()
        # only consider recipes that can be configured
        requested_list = {recipe_data.name for recipe_data in recipe_metadata if recipe_data.user_config}
    else:
        requested_list = set(requested_list)
    _, data = read_file_json(json_file_path)
    assert set(data.keys()) == requested_list, (
        f"Expected {json_file_path} to contain configuration for {requested_list}, but found {set(data.keys())}"
    )
    for benchmark, updates in custom_updates.items():
        for key, expected_value in updates.items():
            actual_value = data[benchmark][key]
            assert actual_value == expected_value, (
                f"Expected {key} to have value {expected_value} "
                f"in the configuration for {benchmark}, but found {actual_value}"
            )


def verify_output(output, expected_filename, is_default=True):
    expected_str = f"User configuration written to {expected_filename}"
    if is_default:
        expected_str = f"Default configuration written to {expected_filename}"
    assert expected_str in output, f"Expected output to contain '{expected_str}', but got:\n{output}"


def test_config_save_def_filename():
    config_path = "config.json"

    save_result = run_asct("config", ["save"])
    assert save_result.ret_code == 0, (
        f"ASCT failed to generate {config_path}\nstdout:\n{save_result.stdout}\nstderr:\n{save_result.stderr}"
    )
    verify_config_json(config_path, None)
    verify_output(save_result.stderr, config_path, is_default=True)


def test_config_save_refuses_to_overwrite_without_force(tmp_path):
    config_path = str(tmp_path / "user-config.json")

    save_result = run_asct("config", ["save", "--config-file", config_path])
    assert save_result.ret_code == 0, f"Failed to generate {config_path}:\n{save_result.stderr}"

    second_result = run_asct("config", ["save", "--config-file", config_path], assert_on_failure=False)
    assert second_result.ret_code != 0, "Expected config save to fail when the target file already exists"
    assert f"Configuration file {config_path} already exists, use --force to overwrite" in second_result.stderr


def test_config_save_overwrites_with_force(tmp_path):
    config_path = str(tmp_path / "user-config.json")

    save_result = run_asct("config", ["save", "--config-file", config_path])
    assert save_result.ret_code == 0, f"Failed to generate {config_path}:\n{save_result.stderr}"

    benchmark_names = ["loaded-latency", "peak-bandwidth"]
    overwrite_result = run_asct("config", ["save", *benchmark_names, "--config-file", config_path, "--force"])
    assert overwrite_result.ret_code == 0, f"Failed to overwrite {config_path}:\n{overwrite_result.stderr}"

    verify_output(overwrite_result.stderr, config_path)
    verify_config_json(config_path, benchmark_names)


def test_config_check_with_config_file(tmp_path):
    config_path = str(tmp_path / "user-config.json")

    save_result = run_asct("config", ["save", "--config-file", config_path])
    assert save_result.ret_code == 0, f"Failed to generate {config_path}:\n{save_result.stderr}"

    verify_config_json(config_path, None)
    verify_output(save_result.stderr, config_path, is_default=True)

    check_result = run_asct("config", ["check", "--config-file", config_path])
    assert check_result.ret_code == 0, f"Failed to validate {config_path}:\n{check_result.stderr}"
    assert f"User configuration in {config_path} is valid" in check_result.stderr


def test_config_check_fails_with_invalid_json(tmp_path):
    config_path = str(tmp_path / "invalid-config.json")

    # create an invalid JSON file
    pathlib.Path(config_path).write_text("{ invalid json }")

    check_result = run_asct("config", ["check", "--config-file", config_path], assert_on_failure=False)
    assert check_result.ret_code != 0, "Expected config check to fail with invalid JSON"
    assert f"Unable to read the user configuration in {config_path}" in check_result.stderr


def test_config_save_with_names(tmp_path):
    config_path = str(tmp_path / "user-config.json")

    benchmark_names = ["loaded-latency", "peak-bandwidth"]

    save_result = run_asct("config", ["save", *benchmark_names, "--config-file", config_path])
    assert save_result.ret_code == 0, f"Failed to generate {config_path}:\n{save_result.stderr}"

    verify_output(save_result.stderr, config_path)
    verify_config_json(config_path, benchmark_names)


def test_config_save_with_updates(tmp_path):
    config_path = str(tmp_path / "user-config.json")

    # First save a config with all benchmark settings
    save_result = run_asct("config", ["save", "--config-file", config_path])
    assert save_result.ret_code == 0, f"Failed to generate {config_path}:\n{save_result.stderr}"

    # Then update the config to only include one benchmark
    updates = {"loaded-latency": {"duration": 1000}, "peak-bandwidth": {"iterations": 1000}}
    update_result = run_asct(
        "config",
        [
            "save",
            *updates.keys(),
            "--config-file",
            config_path,
            "--force",
            "--update-config",
            *[f"{name}.{key}={value}" for name, updates in updates.items() for key, value in updates.items()],
        ],
    )
    assert update_result.ret_code == 0, f"Failed to update {config_path}:\n{update_result.stderr}"

    verify_output(update_result.stderr, config_path, is_default=False)
    verify_config_json(config_path, updates.keys(), custom_updates=updates)


def test_config_help_uses_save():
    result = run_asct("help", ["config"])

    assert "save" in result.stdout
    assert "write-default" not in result.stdout
    assert "asct config check --config-file my-config.json" in result.stdout
