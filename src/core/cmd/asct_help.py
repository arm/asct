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

from asct.core.cmd.helpers.help_helpers import print_asct_run_help


def print_help(parser):
    default_help = parser.format_help()
    print(default_help)
    print("Use `asct help <command>` for more information on a particular command e.g. `asct help run`\n")
    # we want to manually display benchmark options - the default is bad
    # and doesn't give the level of detail we want
    print_asct_run_help()


def run(cli_args):
    if not hasattr(cli_args, "parser"):
        raise AssertionError("parser missing from help.run cli args")
    print_help(cli_args.parser)
