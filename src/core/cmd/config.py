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

import os
import json
import sys

import asct.core.logger as log

from asct.core.recipes.configuration.metadata import get_recipe_metadata, get_recipe_metadata_for_names
from asct.core.recipes.configuration.registry import get_filtered_recipes
from asct.core.utility.files import read_json_file, write_to_file
from asct.lib.run.run_helper import get_conv_user_config


def write_default(args):
    if not args.config_file:
        args.config_file = "config.json"

    if os.path.exists(args.config_file) and not args.force:
        log.warning(f"Configuration file {args.config_file} already exists, use --force to overwrite")
        sys.exit(1)

    default_config = {}

    if type(args.filter) is str:
        args.filter = [args.filter]

    filtered_recipes = get_filtered_recipes(get_recipe_metadata(), args.filter, add_dependencies=False)

    for metadata in get_recipe_metadata_for_names(filtered_recipes.complete_list):
        default_user_config = metadata.get_default_user_config()
        if not default_user_config:
            continue
        default_config[metadata.name] = default_user_config

    if args.update_config:
        get_conv_user_config(
            args.update_config, default_config, filtered_recipes.complete_list, "--update-config", get_recipe_metadata()
        )

    json_str = json.dumps(default_config, indent=4)
    out_descr = "Default configuration"
    if args.update_config:
        out_descr = "User configuration"
    write_to_file(args.config_file, json_str, "w")

    log.info(f"{out_descr} written to {args.config_file}")


def check(args):
    user_config = read_json_file(args.config_file)

    if user_config is None:
        log.critical(f"Unable to read the user configuration in {args.config_file}")
        sys.exit(1)

    if not user_config:
        log.critical(f"User configuration in {args.config_file} is empty")
        sys.exit(1)

    try:
        get_conv_user_config(
            user_config, {}, user_config.keys(), args.config_file, get_recipe_metadata(), just_check=True
        )
    except ValueError as exc:
        log.critical(f"{exc}")
        sys.exit(1)

    log.info(f"User configuration in {args.config_file} is valid")
