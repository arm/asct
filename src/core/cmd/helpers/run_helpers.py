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

import json
import io
import os
import shutil
import sys
from contextlib import redirect_stdout
from time import time
from uuid import uuid4

import asct.core.logger as log

from collections import defaultdict
from asct.core.recipes.configuration.metadata import ASCT_RECIPE_METADATA
from asct.core.utility.files import write_to_file
from asct.core.utility.format import format_term_definition
from asct.core.utility.misc import flatten_dict
from asct.core.cmd.helpers.version_helpers import get_version
from asct.core.cache import ASCTCache as cache
from asct.lib.output_metadata.fields import get_field_metadata_for_recipes
from asct.core.managers.ubench_reporter import get_reporter
from asct.core.utility.files import hash_saved_recipe_files

# (report_key, recipe, report_csv_file, stdout_header)
ReportOutput = tuple[str, object, str, str]
RECIPE_OUTPUT_ORDER = {recipe.name: idx for idx, recipe in enumerate(ASCT_RECIPE_METADATA)}


def print_failure_table_stdout(skipped_entries, failed_entries):
    for entries in [skipped_entries, failed_entries]:
        if not entries:
            continue
        left_column_width = max(len(line[0]) for line in entries)
        right_column_width = max(shutil.get_terminal_size().columns - left_column_width - 2, 32) - 2
        for name, failure in entries:
            print(
                format_term_definition(name, left_column_width, failure, right_column_width, column_spacing=2), end=""
            )
        print()


def print_failure_table_logging(skipped_entries, failed_entries):
    for idx, entries in enumerate([skipped_entries, failed_entries]):
        if not entries:
            continue
        max_length = max(len(entry[0]) for entry in entries)
        log_func = log.warning if idx == 0 else log.error
        for name, failure in entries:
            if failure:
                log_func(f"{name.ljust(max_length)}: {failure}")
            else:
                log_func(f"{name}")


def print_failures(skipped_benchmarks, failed_benchmarks, use_stdout):
    skipped_entries = []
    failed_entries = []
    if skipped_benchmarks:
        if use_stdout:
            skipped_entries.append(("Skipped benchmark", "Reason"))
        else:
            skipped_entries.append(("Skipped benchmarks", ""))
        for name, reason in skipped_benchmarks.items():
            skipped_entries.append((name, reason))
    if failed_benchmarks:
        if use_stdout:
            failed_entries.append(("Failed benchmark", "Failure"))
        else:
            failed_entries.append(("Failed benchmarks", ""))
        for name, reason in failed_benchmarks.items():
            failed_entries.append((name, reason))
    if skipped_entries or failed_entries:
        if use_stdout:
            print_failure_table_stdout(skipped_entries, failed_entries)
        else:
            print_failure_table_logging(skipped_entries, failed_entries)


def output_stdout(args, completed_benchmarks, skipped_benchmarks, failed_benchmarks):
    if not completed_benchmarks and not skipped_benchmarks and not failed_benchmarks:
        return

    print("\n\n---------------- ASCT Results ----------------\n")
    print_failures(skipped_benchmarks, failed_benchmarks, True)

    for benchmark in completed_benchmarks.values():
        get_reporter().current_benchmark = benchmark.name
        # 45 is the total width of the header line,
        # we subtract the length of the benchmark name and add 2 for spacing
        len_header = 46 - len(benchmark.name)
        print(f"\n{benchmark.name.upper()} {'-' * (len_header)}")

        rendered_stdout = io.StringIO()
        with redirect_stdout(rendered_stdout):
            if args.verbose:
                benchmark.to_stdout_verbose()
            else:
                benchmark.to_stdout()

        content = rendered_stdout.getvalue().strip("\n")
        print()
        if content:
            print(content, end="")
        print("\n\n")


def output_csv(args, completed_benchmarks, skipped_benchmarks, failed_benchmarks):
    for name, benchmark in completed_benchmarks.items():
        # csv is a pure table format, output only title as filename and tables
        out_filepath = os.path.join(args.output_dir, f"{name}.csv")
        csv = benchmark.to_csv_str()
        write_to_file(out_filepath, csv, "w", "CSV")

    print_failures(skipped_benchmarks, failed_benchmarks, False)


def output_json(args, completed_benchmarks, skipped_benchmarks, failed_benchmarks):
    out_filepath = os.path.join(args.output_dir, "report.json")
    # to create a properly nested structure, we first create one huge
    # nested python dictionary and then dump that whole structure to JSON
    # use a defaultdict so we create top level keys if they don't already exist,
    # instead of returning a KeyError
    out_dict = defaultdict(dict)
    for name, benchmark in completed_benchmarks.items():
        # nest the results under "memory" heading and benchmark name as sub-group
        if benchmark._category == "report":
            out_dict[name] = benchmark.to_dict()
        else:
            out_dict[benchmark._category][name] = benchmark.to_dict()

    json_str = json.dumps(out_dict)
    # overwrite any existing file aka "w" open mode
    write_to_file(out_filepath, json_str, "w", "JSON")

    print_failures(skipped_benchmarks, failed_benchmarks, False)


def write_benchmark_output_file(args, benchmark):
    if args.format == "csv":
        out_filepath = os.path.join(args.output_dir, f"{benchmark.name}.csv")
        write_to_file(out_filepath, benchmark.to_csv_str(), "w", "CSV")
    elif args.format == "json":
        out_filepath = os.path.join(args.output_dir, f"{benchmark.name}.json")
        write_to_file(out_filepath, benchmark.to_json_str(), "w", "JSON")


def write_benchmark_result(args, benchmark_name, benchmark):
    if getattr(benchmark, "_loaded_from_saved_output", False):
        write_benchmark_output_file(args, benchmark)
        return

    cache().save(benchmark)
    save_benchmark_result(args, benchmark_name, benchmark)
    write_benchmark_output_file(args, benchmark)


def _is_sudo_run() -> bool:
    return os.geteuid() == 0 and os.environ.get("SUDO_USER") is not None


def _make_run_metadata(args, user_config=None, requested_benchmarks=None):
    cmd_arguments = flatten_dict({k: str(v) for k, v in vars(args).items()})
    if requested_benchmarks is not None:
        cmd_arguments["benchmarks"] = list(requested_benchmarks)
    metadata = {
        "run_id": str(uuid4()),
        "timestamp": time(),
        "version": get_version(),
        "is_sudo": _is_sudo_run(),
        "cmd_arguments": cmd_arguments,
    }
    if user_config:
        metadata["user_config"] = user_config
    return metadata


def write_asct_json_header(args, requested_benchmarks, user_config=None):
    """Write asct.json before the run starts, recording run metadata."""
    run_metadata = _make_run_metadata(args, user_config, requested_benchmarks)
    out = {"metadata": run_metadata}
    out_filepath = os.path.join(args.output_dir, "asct.json")
    write_to_file(out_filepath, json.dumps(out), "w")
    return run_metadata


def write_fields_metadata_file(output_dir, *recipe_names):
    raw_dir = os.path.join(output_dir, "raw")
    saved_recipe_names = {"system-info", *recipe_names}
    if os.path.isdir(raw_dir):
        for entry in os.listdir(raw_dir):
            if os.path.isdir(os.path.join(raw_dir, entry)):
                saved_recipe_names.add(entry)

    ordered_recipe_names = sorted(
        saved_recipe_names,
        key=lambda recipe_name: (RECIPE_OUTPUT_ORDER.get(recipe_name, len(RECIPE_OUTPUT_ORDER)), recipe_name),
    )
    fields_filepath = os.path.join(output_dir, "asct-fields.json")
    write_to_file(fields_filepath, json.dumps(get_field_metadata_for_recipes(ordered_recipe_names)), "w")


def save_benchmark_result(args, name, recipe):
    data = recipe.serialize()
    if data is None or not isinstance(data, dict):
        return

    recipe_dir = os.path.join(args.output_dir, "raw", name)
    os.makedirs(recipe_dir, exist_ok=True)

    raw_result = data.get("raw_result", {})
    metadata = data.get("metadata", {})
    summary = None
    if isinstance(raw_result, dict) and "summary" in raw_result:
        summary = raw_result["summary"]
        raw_result = {key: value for key, value in raw_result.items() if key != "summary"}

    file_payloads = {"data.json": json.dumps(raw_result)}
    write_to_file(os.path.join(recipe_dir, "data.json"), file_payloads["data.json"], "w")
    if metadata:
        file_payloads["metadata.json"] = json.dumps(metadata)
        write_to_file(os.path.join(recipe_dir, "metadata.json"), file_payloads["metadata.json"], "w")
    if summary is not None:
        file_payloads["summary.json"] = json.dumps(summary)
        write_to_file(os.path.join(recipe_dir, "summary.json"), file_payloads["summary.json"], "w")

    write_to_file(
        os.path.join(recipe_dir, ".hash"),
        hash_saved_recipe_files({filename: payload.encode() for filename, payload in file_payloads.items()}),
        "w",
    )

    write_fields_metadata_file(args.output_dir, name)


def sort_for_output(data):
    if data is not None and isinstance(data, dict):
        # Keep recipe output aligned with ASCT_RECIPE_METADATA declaration order.
        data = dict(
            sorted(data.items(), key=lambda item: (RECIPE_OUTPUT_ORDER.get(item[0], len(RECIPE_OUTPUT_ORDER)), item[0]))
        )
    return data


def output(
    args,
    completed_benchmarks=None,
    skipped_benchmarks=None,
    failed_benchmarks=None,
):
    if completed_benchmarks is None:
        completed_benchmarks = {}
    if skipped_benchmarks is None:
        skipped_benchmarks = {}
    if failed_benchmarks is None:
        failed_benchmarks = {}

    # Sort recipes by ASCT_RECIPE_METADATA order for consistent output across formats
    completed_benchmarks = sort_for_output(completed_benchmarks)
    skipped_benchmarks = sort_for_output(skipped_benchmarks)
    failed_benchmarks = sort_for_output(failed_benchmarks)

    # this just dispatches to output_{stdout,csv,json} functions in a single line
    # we already validated the args.format selections/choices with argparse
    getattr(sys.modules[__name__], f"output_{args.format}")(
        args, completed_benchmarks, skipped_benchmarks, failed_benchmarks
    )


def output_diff(args, diff_results):
    if args.format == "json":
        out_filepath = os.path.join(args.output_dir, "diff.json")
        write_to_file(out_filepath, diff_results.to_json_str(), "w", "JSON")
    elif args.format == "csv":
        out_filepath = os.path.join(args.output_dir, "diff.csv")
        write_to_file(out_filepath, diff_results.to_csv_str(), "w", "CSV")
    else:
        getattr(diff_results, f"to_{args.format}")()
