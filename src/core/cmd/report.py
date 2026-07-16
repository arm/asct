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

import traceback

import asct.core.logger as log

from asct.core.cmd.helpers.run_helpers import output, write_asct_json_header, write_benchmark_result
from asct.core.managers.ubench_reporter import get_reporter
from asct.core.utility.files import read_json_file
from asct.core.recipes.configuration.metadata import ASCT_REPORT_RECIPE_METADATA
from asct.core.recipes.configuration.registry import RecipeRegistry
from asct.lib.run.run_helper import setup_benchmarks, teardown_benchmarks, get_conv_user_config, print_user_config
import sys


def run(args):
    get_reporter().output_dir = args.output_dir_path

    # workaround for https://github.com/python/cpython/issues/71414 which was fixed in late 2024
    # you can't specify a default value with choices - the default value will be a string instead of a list
    if type(args.reports) is str:
        args.reports = [args.reports]

    report_recipe_registry = RecipeRegistry(ASCT_REPORT_RECIPE_METADATA)
    filtered_recipes = report_recipe_registry.get_filtered_recipes(args.reports)

    if args.dry_run:
        print(filtered_recipes.get_description(detailed=True))
        sys.exit(0)

    if not filtered_recipes.complete_list:
        print(filtered_recipes.get_description(detailed=True))
        sys.exit(1)

    user_config = {}

    # Handle user config from --detect, --config-file,
    # and --update-config, in that order of precedence.
    if args.detect:
        args.update_config = args.update_config or {}
        args.update_config.setdefault("cmn", {})["detect"] = "true"

    if args.config_file:
        data = read_json_file(args.config_file)
        if data:
            get_conv_user_config(
                data, user_config, filtered_recipes.complete_list, args.config_file, ASCT_REPORT_RECIPE_METADATA
            )

    if args.update_config:
        get_conv_user_config(
            args.update_config,
            user_config,
            filtered_recipes.complete_list,
            "--update-config",
            ASCT_REPORT_RECIPE_METADATA,
        )

    if user_config:
        print_user_config(user_config)

    # Save a manifest for report outputs so view can restore them, but keep the
    # requested benchmark list empty so resume rejects report directories.
    write_asct_json_header(args, [], user_config)

    filtered_recipes = report_recipe_registry.remove_cached_dependencies(filtered_recipes)
    requested_benchmarks = filtered_recipes.complete_list
    skipped_benchmarks = {}
    failed_benchmarks = {}
    completed_benchmarks = {}

    # sorting the benchmarks by their priority, highest first
    priority_list, skipped_benchmarks = setup_benchmarks(requested_benchmarks, user_config, report_recipe_registry)

    log.debug(f"Executing benchmarks in the following order: {', '.join([name for name, _ in priority_list])}")

    if priority_list:
        for benchmark_name, benchmark in priority_list:
            try:
                benchmark.run()
            except (RuntimeError, ValueError, TypeError, OSError, KeyError, AttributeError) as exc:  # noqa: PERF203
                traceback_addon = ""
                if log.is_log_level("debug"):
                    traceback_addon = "\n" + traceback.format_exc()
                failed_benchmarks[benchmark_name] = f"{exc}{traceback_addon}"
            else:
                completed_benchmarks[benchmark_name] = benchmark
                write_benchmark_result(args, benchmark_name, benchmark)

        teardown_benchmarks(priority_list)

    output(
        args,
        completed_benchmarks=completed_benchmarks,
        skipped_benchmarks=skipped_benchmarks,
        failed_benchmarks=failed_benchmarks,
    )
