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

import sys

import asct.core.logger as log

from asct.core.cmd.helpers.run_helpers import (
    output,
    write_benchmark_result,
    write_asct_json_header,
)
from asct.core.asct_env import ASCTGlobalSettings as AGS
from asct.core.cache import ASCTCache as cache
from asct.core.managers.ubench_reporter import get_reporter
from asct.core.utility.files import read_json_file
from asct.core.recipes.impl import SystemInfo
from asct.core.recipes.configuration.metadata import ASCT_RUN_RECIPE_METADATA
from asct.core.recipes.configuration.registry import RecipeRegistry
from asct.lib.run.run_helper import (
    execute_benchmarks,
    get_conv_user_config,
    get_execution_context,
    print_user_config,
    setup_benchmarks,
)


def run(args):
    settings = AGS()
    get_reporter().output_dir = args.output_dir_path

    # workaround for https://github.com/python/cpython/issues/71414 which was fixed in late 2024
    # you can't specify a default value with choices - the default value will be a string instead of a list
    if type(args.benchmarks) is str:
        args.benchmarks = [args.benchmarks]

    run_recipe_registry = RecipeRegistry(ASCT_RUN_RECIPE_METADATA)
    filtered_recipes = run_recipe_registry.get_filtered_recipes(args.benchmarks)

    print_detailed_selection = not filtered_recipes.complete_list or args.dry_run

    if not args.quiet:
        print(filtered_recipes.get_description(detailed=print_detailed_selection))

    if not filtered_recipes.complete_list:
        sys.exit(1)

    user_config = {}

    if args.config_file:
        data = read_json_file(args.config_file)
        if data:
            get_conv_user_config(
                data, user_config, filtered_recipes.complete_list, args.config_file, ASCT_RUN_RECIPE_METADATA
            )

    if args.update_config:
        get_conv_user_config(
            args.update_config, user_config, filtered_recipes.complete_list, "--update-config", ASCT_RUN_RECIPE_METADATA
        )

    if user_config:
        print_user_config(user_config)

    if args.dry_run:
        sys.exit(0)

    ctx = get_execution_context(args, settings)

    with ctx as global_lock:
        if global_lock and not global_lock.lock_successful():
            log.critical(global_lock.get_error())
            sys.exit(1)

        # topological sort them based on their dependencies
        filtered_recipes = run_recipe_registry.remove_cached_dependencies(filtered_recipes)
        requested_benchmarks = run_recipe_registry.topological_sort(filtered_recipes.complete_list)

        # Write asct.json before any benchmarks run so the requested list and
        # run metadata are persisted even if the run is interrupted.
        write_asct_json_header(args, requested_benchmarks, user_config)

        # always run sysreport first and pass to the benchmarks to use
        sysreport = SystemInfo()
        try:
            sysreport.run()
            cache().refresh_cache(sysreport)
            cache().save_cache_validator(sysreport)
            write_benchmark_result(args, sysreport.name, sysreport)
        except (RuntimeError, ValueError, OSError, KeyError, TypeError) as exc:
            log.critical(f"Failed to gather system information: {exc}")
            sys.exit(1)

        skipped_benchmarks = {}
        failed_benchmarks = {}
        completed_benchmarks = {sysreport.name: sysreport}

        # sorting the benchmarks by their priority, highest first
        priority_list, skipped_benchmarks = setup_benchmarks(requested_benchmarks, user_config, run_recipe_registry)

        log.debug(f"Executing benchmarks in the following order: {', '.join([name for name, _ in priority_list])}")

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
