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
from dataclasses import asdict, dataclass
import os
import sys
from typing import TYPE_CHECKING

import asct.core.logger as log
from packaging.version import InvalidVersion, Version

from asct.core.asct_env import ASCTGlobalSettings as AGS
from asct.core.cmd.helpers.run_helpers import output, write_benchmark_result
from asct.core.managers.ubench_reporter import get_reporter
from asct.core.recipes.impl import SystemInfo
from asct.core.recipes.configuration.metadata import ASCT_RUN_RECIPE_METADATA
from asct.core.recipes.configuration.registry import RecipeRegistry
from asct.core.utility.files import read_json_file
from asct.lib.run.result_loader import (
    has_valid_saved_recipe,
    load_saved_recipe,
)
from asct.lib.run.run_helper import execute_benchmarks, get_execution_context, print_user_config, setup_benchmarks
from asct.core.utility.misc import flatten_dict

if TYPE_CHECKING:
    from types import SimpleNamespace

MIN_RESUME_VERSION = Version("0.6.0")


@dataclass(frozen=True)
class ManifestData:
    manifest: dict
    metadata: dict
    cmd_arguments: dict
    user_config: dict


def _is_sudo_run() -> bool:
    return os.geteuid() == 0 and os.environ.get("SUDO_USER") is not None


def _parse_manifest_bool(name: str, value: str) -> bool:
    if value == "True":
        return True
    if value == "False":
        return False
    raise ValueError(f"metadata.cmd_arguments.{name} must be 'True' or 'False'")


def _parse_manifest_benchmarks(output_dir: str, value) -> list[str]:
    if isinstance(value, list):
        if all(isinstance(name, str) for name in value):
            return value
        raise TypeError(
            f"Unable to parse manifest in {output_dir}: metadata.cmd_arguments.benchmarks must be a list of strings"
        )
    raise TypeError(f"Unable to parse manifest in {output_dir}: metadata.cmd_arguments.benchmarks must be a list")


MANIFEST_CMD_ARGUMENT_PARSERS = {
    "log_level": str,
    "log_level_console": str,
    "log_level_file": str,
    "log_file": lambda value: None if value == "None" else value,
    "format": str.lower,
    "quiet": lambda value: _parse_manifest_bool("quiet", value),
    "no_cache": lambda value: _parse_manifest_bool("no_cache", value),
    "clear_cache": lambda value: _parse_manifest_bool("clear_cache", value),
    "verbose": lambda value: _parse_manifest_bool("verbose", value),
    "no_progress_bar": lambda value: _parse_manifest_bool("no_progress_bar", value),
    "dev_mode": lambda value: _parse_manifest_bool("dev_mode", value),
    "quick_mode": lambda value: _parse_manifest_bool("quick_mode", value),
}


def _parse_manifest_cmd_arguments(output_dir: str, cmd_arguments: dict) -> dict:
    if not isinstance(cmd_arguments, dict):
        raise TypeError(f"Unable to parse manifest in {output_dir}: metadata.cmd_arguments must be an object")

    parsed_args = {}
    benchmarks = cmd_arguments.get("benchmarks")
    if benchmarks is not None:
        parsed_args["benchmarks"] = _parse_manifest_benchmarks(output_dir, benchmarks)

    for name, parser in MANIFEST_CMD_ARGUMENT_PARSERS.items():
        value = cmd_arguments.get(name)
        if value is None:
            continue
        if not isinstance(value, str):
            raise TypeError(f"Unable to parse manifest in {output_dir}: metadata.cmd_arguments.{name} must be a string")
        try:
            parsed_args[name] = parser(value)
        except ValueError as exc:
            raise RuntimeError(
                f"Unable to parse manifest in {output_dir}: invalid metadata.cmd_arguments.{name} value '{value}'"
            ) from exc

    return parsed_args


def _read_manifest(output_dir: str) -> dict:
    manifest = read_json_file(os.path.join(output_dir, "asct.json"))
    if manifest is None:
        raise RuntimeError(f"Unable to parse manifest in {output_dir}: missing or unreadable asct.json")
    if not isinstance(manifest, dict):
        raise TypeError(f"Unable to parse manifest in {output_dir}: asct.json must contain a JSON object")
    return manifest


def _get_manifest_version(output_dir: str, manifest: dict, metadata: dict) -> str:
    version = metadata.get("version")
    if version is not None:
        return version

    diff = manifest.get("diff")
    if isinstance(diff, dict):
        version = diff.get("metadata.version")
        if version is not None:
            return version
        diff_metadata = diff.get("metadata")
        if isinstance(diff_metadata, dict) and diff_metadata.get("version") is not None:
            return diff_metadata["version"]

    raise TypeError(f"Unable to parse manifest in {output_dir}: metadata.version is missing")


def read_manifest_data(output_dir: str) -> ManifestData:
    manifest = _read_manifest(output_dir)
    metadata = manifest.get("metadata", {})
    if not isinstance(metadata, dict):
        raise TypeError(f"Unable to parse manifest in {output_dir}: metadata must be an object")

    user_config = metadata.get("user_config", {})
    if not isinstance(user_config, dict):
        raise TypeError(f"Unable to parse manifest in {output_dir}: metadata.user_config must be an object")

    return ManifestData(
        manifest=manifest,
        metadata=metadata,
        cmd_arguments=_parse_manifest_cmd_arguments(output_dir, metadata.get("cmd_arguments", {})),
        user_config=user_config,
    )


def read_run_manifest(output_dir: str) -> tuple[list[str], dict, dict, bool]:
    manifest_data = read_manifest_data(output_dir)
    version_str = _get_manifest_version(output_dir, manifest_data.manifest, manifest_data.metadata)
    try:
        manifest_version = Version(Version(version_str).base_version)
    except InvalidVersion as exc:
        raise RuntimeError(
            f"Unable to parse manifest in {output_dir}: unable to parse ASCT version '{version_str}'"
        ) from exc
    if manifest_version < MIN_RESUME_VERSION:
        raise RuntimeError(
            f"Unable to parse manifest in {output_dir}: ASCT version '{version_str}' is not supported for resume"
            f" (minimum supported version is {MIN_RESUME_VERSION})"
        )

    if "is_sudo" not in manifest_data.metadata:
        raise TypeError(f"Unable to parse manifest in {output_dir}: metadata.is_sudo is missing")
    manifest_is_sudo = manifest_data.metadata["is_sudo"]
    if not isinstance(manifest_is_sudo, bool):
        raise TypeError(f"Unable to parse manifest in {output_dir}: metadata.is_sudo must be a boolean")

    requested_benchmarks = manifest_data.cmd_arguments.get("benchmarks")
    if not isinstance(requested_benchmarks, list):
        raise TypeError(f"Unable to parse manifest in {output_dir}: missing metadata.cmd_arguments.benchmarks list")
    if not requested_benchmarks:
        raise RuntimeError(f"Unable to resume from {output_dir}: no requested benchmarks found in the manifest file")

    return requested_benchmarks, manifest_data.user_config, manifest_data.cmd_arguments, manifest_is_sudo


def _verify_resume_manifest_sudo_status(output_dir: str, manifest_is_sudo: bool) -> None:
    current_is_sudo = _is_sudo_run()
    if current_is_sudo == manifest_is_sudo:
        return
    action = "run the resume command with sudo" if manifest_is_sudo else "run the resume command as a regular user"
    raise RuntimeError(f"Unable to resume from {output_dir}: sudo status does not match the original run; {action}")


def _get_resume_run_state(output_dir: str) -> tuple[list[str], dict, list[str]]:
    requested_benchmarks, user_config, _manifest_args, manifest_is_sudo = read_run_manifest(output_dir)
    _verify_resume_manifest_sudo_status(output_dir, manifest_is_sudo)
    benchmarks_to_run = [
        benchmark_name
        for benchmark_name in requested_benchmarks
        if not has_valid_saved_recipe(output_dir, benchmark_name)
    ]
    return requested_benchmarks, user_config, benchmarks_to_run


def load_asct_run_args(args: SimpleNamespace) -> None:
    run_dir = getattr(args, "run_dir", None)
    if not isinstance(run_dir, str) or not run_dir:
        raise TypeError("Resume requires a run_dir")
    if not os.path.isdir(run_dir):
        raise RuntimeError(f"Specified run directory '{run_dir}' does not exist")

    _requested_benchmarks, _user_config, manifest_args, manifest_is_sudo = read_run_manifest(run_dir)
    _verify_resume_manifest_sudo_status(run_dir, manifest_is_sudo)
    format_override = getattr(args, "format", None)

    for name, value in manifest_args.items():
        if name == "format" and format_override is not None:
            continue
        setattr(args, name, value)

    if format_override is not None:
        args.format = format_override
    elif getattr(args, "format", None) is None:
        args.format = "stdout"

    args.output_dir = run_dir
    args.output_dir_path = run_dir


def check_hw_match(output_dir: str, system_info):
    saved_system_info = load_saved_recipe(output_dir, "system-info")
    if saved_system_info is None or not getattr(saved_system_info, "ready", False):
        raise RuntimeError(f"saved system-info results in {output_dir} are missing or invalid")
    current_hw = flatten_dict(asdict(system_info.sys_hw))
    saved_hw = flatten_dict(asdict(saved_system_info.sys_hw))

    for key in sorted(set(current_hw) | set(saved_hw)):
        current_value = current_hw.get(key, "<missing>")
        saved_value = saved_hw.get(key, "<missing>")
        if current_value != saved_value:
            raise RuntimeError(f"hardware changes detected after run: {key}:{current_value} (was {saved_value})")

    return saved_system_info


def run(args):
    settings = AGS()
    get_reporter().output_dir = args.output_dir_path

    try:
        requested_benchmarks, user_config, benchmarks_to_run = _get_resume_run_state(args.output_dir_path)
    except (RuntimeError, TypeError) as exc:
        log.critical(str(exc))
        sys.exit(1)

    if user_config:
        print_user_config(user_config)

    run_recipe_registry = RecipeRegistry(ASCT_RUN_RECIPE_METADATA)
    completed_benchmarks = {}

    try:
        current_system_info = SystemInfo()
        current_system_info.run()
        system_info = check_hw_match(args.output_dir_path, current_system_info)
    except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError, KeyError) as exc:
        log.critical(str(exc))
        sys.exit(1)

    for benchmark_name in requested_benchmarks:
        if benchmark_name in benchmarks_to_run:
            continue
        try:
            completed_benchmarks[benchmark_name] = load_saved_recipe(args.output_dir_path, benchmark_name)
        except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError) as exc:
            log.warning(f"Unable to restore saved results for '{benchmark_name}', benchmark will be rerun: {exc}")
            benchmarks_to_run.append(benchmark_name)

    ctx = get_execution_context(args, settings)

    skipped_benchmarks = {}
    failed_benchmarks = {}

    with ctx as global_lock:
        if global_lock and not global_lock.lock_successful():
            log.critical(global_lock.get_error())
            sys.exit(1)

        completed_benchmarks[system_info.name] = system_info

        priority_list, skipped_benchmarks = setup_benchmarks(benchmarks_to_run, user_config, run_recipe_registry)

        log.debug(
            f"Executing memory benchmarks in the following order: {', '.join([name for name, _ in priority_list])}"
        )

        execute_benchmarks(
            args,
            priority_list,
            completed_benchmarks,
            failed_benchmarks,
            write_benchmark_result=write_benchmark_result,
        )

    output(
        args,
        completed_benchmarks=completed_benchmarks,
        skipped_benchmarks=skipped_benchmarks,
        failed_benchmarks=failed_benchmarks,
    )
