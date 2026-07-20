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

import argparse
import shutil

from asct.core.recipes.configuration.metadata import (
    get_recipe_descr_as_printable_list,
    ASCT_RUN_RECIPE_METADATA,
    ASCT_REPORT_RECIPE_METADATA,
)

from asct.core.utility.format import format_definition_table


class ASCTCustomHelpFormatter(argparse.RawTextHelpFormatter):
    """
    The default argparse help message has some duplication when you have both a
    short and a long argument version.

    This custom formatter allows us to end up with something like the below:
        --format, -f [stdout,csv,json]
    instead of:
        --format [stdout,csv,json], -f [stdout,csv,json]
    """

    def _format_action_invocation(self, action):
        if not action.option_strings or action.nargs == 0:
            return super()._format_action_invocation(action)
        default = self._get_default_metavar_for_optional(action)
        args_string = self._format_args(action, default)
        return ", ".join(action.option_strings) + " " + args_string


class ASCTCommandHelpAction(argparse.Action):
    """
    Extracts the help from the available subcommands and prints it whenever the help command
    is passed an argument.
    """

    def __call__(self, parser, namespace, values, _=None):
        if not values:
            return
        cmd = values
        cmd_names = namespace.subcommands.choices.keys()
        if cmd not in cmd_names:
            parser.exit(
                1,
                f"Command '{cmd}' does not exist. Available commands: {', '.join(cmd_names)}\n"
                "Please refer to the help page by running 'asct help'\n",
            )
        subp = namespace.subcommands.choices[values]
        print(subp.format_help())
        parser.exit(0)


class ASCTParser(argparse.ArgumentParser):
    """
    Prints a custom message if attempting to run a command that does not exist (in order to make it consistent
    with the error from the asct help command).
    """

    def _check_value(self, action, value):
        if (
            isinstance(action, argparse._SubParsersAction)
            and action.choices is not None
            and value not in action.choices
        ):
            self.exit(
                1,
                f"Command '{value}' does not exist. Available commands: {', '.join(action.choices)}\n"
                "Please refer to the help page by running 'asct help'\n",
            )
        return super()._check_value(action, value)


def get_formatted_benchmark_str(include_all, recipe_metadata):
    all_recipes = {}
    # mention 'all' as a keyword
    if include_all:
        all_recipes["all"] = "Run all available benchmarks\n  Default: no"
    all_recipes.update(get_recipe_descr_as_printable_list(recipe_metadata))

    left_indent = 4
    column_spacing = 3

    total_width = max(shutil.get_terminal_size().columns, 60)

    return format_definition_table(all_recipes.items(), total_width, left_indent, column_spacing)


def print_asct_run_help(print_all=True):
    if print_all:
        print("  Available benchmarks")

    print(get_formatted_benchmark_str(print_all, ASCT_RUN_RECIPE_METADATA), end="")


def print_asct_report_help(print_all=True):
    if print_all:
        print("  Available reports")

    print(get_formatted_benchmark_str(print_all, ASCT_REPORT_RECIPE_METADATA), end="")
