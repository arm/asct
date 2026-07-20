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

from contextlib import nullcontext
import traceback
import asct.core.logger as log
from asct.core.asct_env import ProcessMutex, ProcessWatcher
from asct.core.managers.ubench_reporter import get_reporter
from asct.core.term_ui.progress_bar import get_progress_tracker
from asct.core.utility.misc import create_dict_path, flatten_dict
from asct.core.recipes.configuration.metadata import get_recipe
from asct.core.recipes.configuration.schema import UserConfigDescr
from asct.core.asct_env import ASCTGlobalSettings as AGS


def setup_benchmarks(benchmark_name_list, user_config, recipe_registry):
    """Sets up the benchmarks and returns a list of all the benchmarks
    that can move to execution and a dict of skipped benchmark names and a description
    why they were skipped
    """
    settings = AGS()
    skipped_benchmarks = {}
    skipped_dependents = set()
    benchmark_list = recipe_registry.get_recipes(benchmark_name_list)
    for stage in ["setup", "alloc"]:
        for benchmark_name, benchmark in benchmark_list:
            if ProcessWatcher().stop_requested:
                raise SystemExit(130)
            if benchmark_name in skipped_benchmarks:
                continue
            try:
                if stage == "setup":
                    cfg = user_config[benchmark_name] if user_config and benchmark_name in user_config else None
                    benchmark.initialize_config(cfg, pmu_mode=settings.enable_pmu)
                    benchmark.setup()
                else:
                    benchmark.allocate_resources()
            except (RuntimeError, ValueError, TypeError, OSError, KeyError, MemoryError, AttributeError) as exc:
                if ProcessWatcher().stop_requested:
                    raise SystemExit(130) from exc
                traceback_addon = ""
                if log.is_log_level("debug"):
                    traceback_addon = "\n" + traceback.format_exc()
                skipped_benchmarks[benchmark_name] = f"{exc}{traceback_addon}"
                # If the benchmark that failed setup was added as a dependency, check to see what benchmarks also need
                # to be removed
                skipped_dependents.update(
                    recipe_registry.get_dependents(benchmark_name, [n for n, b in benchmark_list])
                )

            for dep in [dep for dep in skipped_dependents if dep not in skipped_benchmarks]:
                skipped_benchmarks[dep] = "A dependency of this benchmark was skipped"

    return [(n, b) for n, b in benchmark_list if n not in skipped_benchmarks], skipped_benchmarks


def teardown_benchmarks(benchmark_list):
    """Tears down the benchmarks"""
    for benchmark_name, benchmark in benchmark_list:
        try:
            benchmark.teardown()
        except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as exc:  # ruff:ignore[try-except-in-loop]
            log.warning(f"Failed to teardown benchmark {benchmark_name}: {exc}")


def get_execution_context(args, settings):
    if args.dev_mode:
        settings.set_dev_mode()
        return nullcontext()

    if args.quick_mode:
        settings.set_quick_mode()
    return ProcessMutex("_asct_", retry_count=5, retry_wait=0.5)


def execute_benchmarks(args, priority_list, completed_benchmarks, failed_benchmarks, write_benchmark_result=None):
    if not priority_list:
        return

    get_progress_tracker().initialize(2, not args.quiet, not args.no_progress_bar, bool(args.log_file))
    try:
        for benchmark_name, benchmark in get_progress_tracker().iterate(priority_list, lambda _, elem: f"{elem[0]}"):
            if ProcessWatcher().stop_requested:
                raise SystemExit(130)
            get_reporter().current_benchmark = benchmark_name
            try:
                benchmark.run()
            except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as exc:
                if ProcessWatcher().stop_requested:
                    raise SystemExit(130) from exc
                traceback_addon = ""
                if log.is_log_level("debug"):
                    traceback_addon = "\n" + traceback.format_exc()
                failed_benchmarks[benchmark_name] = f"{exc}{traceback_addon}"
            else:
                completed_benchmarks[benchmark_name] = benchmark
                if write_benchmark_result is not None:
                    write_benchmark_result(args, benchmark_name, benchmark)
    finally:
        get_progress_tracker().wait_until_idle()
        get_progress_tracker().terminate()
        teardown_benchmarks(priority_list)


def _convert_user_config_leaf(settings_descr, path, top_value, source_str):
    settings_descr_obj = settings_descr
    for path_elem in path[1:]:
        if path_elem not in settings_descr_obj:
            raise ValueError(f"Invalid config path: {'.'.join(path)} in {source_str}")
        settings_descr_obj = settings_descr_obj[path_elem]

    if type(settings_descr_obj) is not UserConfigDescr:
        raise ValueError(f"Invalid config path: {'.'.join(path)} in {source_str}")

    try:
        return settings_descr_obj.conv(top_value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Incorrect format for user config path {'.'.join(path)} in {source_str}: {exc}") from exc


def _is_non_default_user_config_value(defaults, path, conv_value):
    # Look for the value in 'defaults' using the same path
    # (path[0] is the benchmark which 'defaults' doesn't include, so start from path[1])
    # and if they're the same, they're not added
    default_value = None
    default_value_found = False

    if path[1] in defaults:
        default_value = defaults[path[1]]
        default_value_found = True
        for path_part in path[2:]:
            if path_part not in default_value:
                default_value_found = False
                break
            default_value = default_value[path_part]

    return not default_value_found or conv_value != default_value


# Updates a dict with user settings where the values have been converted
# from the raw value present in either the --update-config arg or a JSON file
def get_conv_user_config(settings, dest_dict, requested_benchmarks, source_str, recipe_metadata, just_check=False):
    if not settings:
        return

    def handle_config_error(message, exc=None):
        if just_check:
            if exc is not None:
                raise ValueError(message) from exc
            raise ValueError(message)
        log.warning(f"{message}, setting ignored")

    # requested_name can either be a short name or a full name
    for requested_name, benchmark_settings in settings.items():
        # get_recipe will return the recipe object for either the short name or the full name
        recipe = get_recipe(requested_name, recipe_metadata)

        if not recipe:
            handle_config_error(f"Unknown benchmark '{requested_name}' in {source_str}")
            continue

        # get full name for recipe in case short name was used - that's the main way of identifying benchmarks
        # and requested_benchmarks is always a list of full names
        requested_name = recipe.name

        if requested_name not in requested_benchmarks and not just_check:
            handle_config_error(f"Benchmark '{requested_name}' in {source_str} was not requested")
            continue

        settings_descr = recipe.user_config
        defaults = recipe.get_default_user_config()

        if not settings_descr:
            continue

        # look for all the 'leaves' in the user settings tree (which comes from argparse and is a nested dict
        # of string:string) and create a new 'dict' where the path are the same but the leaves are converted
        # from string using the conversion function from the recipe_info for each benchmark
        dict_stack = [((requested_name,), benchmark_settings)]
        while dict_stack:
            path, top_value = dict_stack.pop()
            if type(top_value) is not dict:  # leaf node - attempt to convert the value after validating the path
                # using the recipe info UserConfigDescr object
                try:
                    conv_value = _convert_user_config_leaf(settings_descr, path, top_value, source_str)
                except (ValueError, TypeError) as exc:
                    handle_config_error(str(exc), exc)
                    continue

                if just_check:
                    continue

                if not _is_non_default_user_config_value(defaults, path, conv_value):
                    log.debug(
                        f"Requested config value {'.'.join(path)} is the same as the default, so it will be ignored"
                    )
                    continue
                create_dict_path(dest_dict, path, conv_value)
            else:
                for key, value in top_value.items():
                    dict_stack.append(((*path, key), value))


def print_user_config(user_config):
    log.warning("Using custom configuration for the following benchmarks:")
    for benchmark, config in user_config.items():
        log.warning(f"» {benchmark}")
        for k, v in flatten_dict(config, unroll_lists=False).items():
            log.warning(f"  {k}: {v}")
