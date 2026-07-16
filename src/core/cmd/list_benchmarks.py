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

import csv
import json
import io
import os

from asct.core.cmd.helpers.help_helpers import print_asct_run_help
from asct.core.recipes.configuration.metadata import get_recipe_descr_as_dict, get_recipe_descr_as_list
from asct.core.resources.output_folder import OutputFolder
from asct.core.utility.files import write_to_file


def write_benchmark_list_json(output_dir):
    benchmark_list = get_recipe_descr_as_dict()
    json_str = json.dumps(benchmark_list)
    out_filepath = os.path.join(output_dir, "benchmark_list.json")
    write_to_file(out_filepath, json_str, "w", "JSON")


def write_benchmark_list_csv(output_dir):
    benchmark_data = [["category", "benchmark", "description"]]
    benchmark_data += get_recipe_descr_as_list()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(benchmark_data)
    csv_string = output.getvalue()
    output.close()
    out_filepath = os.path.join(output_dir, "benchmark_list.csv")
    write_to_file(out_filepath, csv_string, "w", "CSV")


def output_benchmark_list(output_format, output_dir):
    if output_format == "stdout":
        print_asct_run_help(False)
        return

    output_folder_resource = OutputFolder(output_dir, True)
    output_folder_resource.setup()

    if output_format == "json":
        write_benchmark_list_json(output_dir)
    elif output_format == "csv":
        write_benchmark_list_csv(output_dir)

    output_folder_resource.teardown()


def run(cli_args):
    output_benchmark_list(cli_args.format, cli_args.output_dir)
