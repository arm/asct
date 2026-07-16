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
import os
import sys

import asct.core.logger as log

from asct.core.benchspec.benchspec import ASCTBenchmarkConfig
from asct.core.cmd.helpers.run_helpers import output_csv, output_json, output_stdout, sort_for_output
from asct.core.cmd.resume import read_manifest_data
from asct.core.utility.files import read_json_file
from asct.lib.run.result_loader import (
    has_valid_saved_recipe,
    load_saved_recipe,
    read_saved_recipe_artifacts,
    recreate_recipe,
)

OUTPUT_HANDLERS = {
    "stdout": output_stdout,
    "csv": output_csv,
    "json": output_json,
}


def _read_legacy_summary_file(run_dir: str, recipe_name: str):
    summary_path = os.path.join(run_dir, f"{recipe_name}-summary.ubench.json")
    if not os.path.isfile(summary_path):
        return None
    return read_json_file(summary_path)


def _read_legacy_bandwidth_sweep_file(run_dir: str):
    for filename in ("bandwidth-sweep.ubench.json", "bandwidth.ubench.json"):
        file_path = os.path.join(run_dir, filename)
        if os.path.isfile(file_path):
            return read_json_file(file_path)
    return None


def _parse_legacy_json_string(raw_entry):
    if not isinstance(raw_entry, str):
        return raw_entry
    try:
        return json.loads(raw_entry)
    except json.JSONDecodeError:
        return raw_entry


def _build_legacy_latency_sweep_payload(raw_entry, legacy_summary):
    if not isinstance(legacy_summary, dict):
        return raw_entry

    raw_sweep_data = {"sweep_data": _parse_legacy_json_string(raw_entry)}

    metric_key = "average_latency_ns"
    metric_column = "Latency [ns]"
    if any(
        isinstance(level_data, dict)
        and isinstance(level_data.get("sweet_spot"), dict)
        and "average_latency" in level_data["sweet_spot"]
        for level_data in legacy_summary.values()
    ):
        metric_key = "average_latency"
        metric_column = "Latency [ns]"
    elif not any(
        isinstance(level_data, dict)
        and isinstance(level_data.get("sweet_spot"), dict)
        and metric_key in level_data["sweet_spot"]
        for level_data in legacy_summary.values()
    ):
        metric_key = "average_latency_cyc"
        metric_column = "Latency [cycle]"

    summary = {
        "Lower Bound": {},
        "Upper Bound": {},
        "Optimum Datasize": {},
        metric_column: {},
    }
    for level, level_data in legacy_summary.items():
        if not isinstance(level_data, dict):
            continue
        sweet_spot = level_data.get("sweet_spot", {})
        if not isinstance(sweet_spot, dict):
            continue
        summary["Lower Bound"][level] = level_data.get("LB")
        summary["Upper Bound"][level] = level_data.get("UB")
        summary["Optimum Datasize"][level] = sweet_spot.get("sizes")
        summary[metric_column][level] = sweet_spot.get(metric_key)

    raw_sweep_data["summary"] = summary
    return {"raw_result": raw_sweep_data}


def _build_legacy_bandwidth_sweep_payload(raw_entry, legacy_sweep_data, legacy_latency_summary):
    sweep_data = legacy_sweep_data if isinstance(legacy_sweep_data, dict) else _parse_legacy_json_string(raw_entry)
    if not isinstance(sweep_data, dict):
        return raw_entry
    if not isinstance(legacy_latency_summary, dict):
        return {"raw_result": {"sweep_data": sweep_data}}

    if "total_bandwidth_mbps" in sweep_data or "total_bandwidth" in sweep_data:
        metric_key = "total_bandwidth_mbps" if "total_bandwidth_mbps" in sweep_data else "total_bandwidth"
        metric_column = "Bandwidth [GB/s]"

        def metric_transform(value):
            return value / 1e3 if value is not None else value

    else:
        metric_key = "total_bandwidth_bpc"
        metric_column = "Bandwidth [B/cycle]"

        def metric_transform(value):
            return value

    sizes = sweep_data.get("sizes", {})
    metric_values = sweep_data.get(metric_key, {})
    if not isinstance(sizes, dict) or not isinstance(metric_values, dict):
        return {"raw_result": {"sweep_data": sweep_data}}

    summary = {
        "Datasize Used": {},
        "Level": {},
        metric_column: {},
    }
    for index, (level, level_data) in enumerate(legacy_latency_summary.items()):
        if not isinstance(level_data, dict):
            continue
        sweet_spot = level_data.get("sweet_spot", {})
        if not isinstance(sweet_spot, dict):
            continue
        sweet_spot_size = sweet_spot.get("sizes")
        matching_key = next((key for key, value in sizes.items() if value == sweet_spot_size), None)
        if matching_key is None:
            continue
        row_key = str(index)
        summary["Datasize Used"][row_key] = sweet_spot_size
        summary["Level"][row_key] = level
        summary[metric_column][row_key] = metric_transform(metric_values.get(matching_key))

    return {"raw_result": {"sweep_data": sweep_data, "summary": summary}}


def _discover_saved_recipe_names(run_dir: str, manifest: dict | None = None) -> tuple[list[str], dict | None]:
    raw_dir = os.path.join(run_dir, "raw")
    if os.path.isdir(raw_dir):
        recipe_names = []
        for entry in sorted(os.listdir(raw_dir)):
            recipe_dir = os.path.join(raw_dir, entry)
            if not os.path.isdir(recipe_dir):
                continue
            if any(
                os.path.isfile(os.path.join(recipe_dir, filename))
                for filename in ("data.json", "metadata.json", "summary.json")
            ):
                recipe_names.append(entry)
        if recipe_names:
            return recipe_names, None

    if manifest is None:
        manifest = read_json_file(os.path.join(run_dir, "asct.json"))
    if manifest is None:
        raise RuntimeError(f"Unable to view results from {run_dir}: missing or unreadable asct.json")
    if not isinstance(manifest, dict):
        raise TypeError(f"Unable to view results from {run_dir}: asct.json must contain a JSON object")

    legacy_raw = manifest.get("raw")
    if isinstance(legacy_raw, dict):
        recipe_names = [name for name in legacy_raw if isinstance(name, str)]
        if recipe_names:
            return recipe_names, legacy_raw

    raise TypeError(
        f"Unable to view results from {run_dir}: no saved recipe directories and no legacy raw results in asct.json"
    )


def _load_legacy_saved_recipe(run_dir: str, recipe_name: str, raw_entry):
    if recipe_name == "latency-sweep":
        legacy_summary = _read_legacy_summary_file(run_dir, recipe_name)
        if legacy_summary is not None:
            raw_entry = _build_legacy_latency_sweep_payload(raw_entry, legacy_summary)
    elif recipe_name == "bandwidth-sweep":
        legacy_sweep_data = _read_legacy_bandwidth_sweep_file(run_dir)
        legacy_latency_summary = _read_legacy_summary_file(run_dir, "latency-sweep")
        if legacy_sweep_data is not None:
            raw_entry = _build_legacy_bandwidth_sweep_payload(raw_entry, legacy_sweep_data, legacy_latency_summary)
    recipe = recreate_recipe(recipe_name, raw_entry)
    recipe._loaded_from_saved_output = True
    return recipe


def _apply_view_user_config(recipe, user_config: dict, saved_metadata: dict | None = None):
    recipe_config = user_config.get(recipe.name) if isinstance(user_config, dict) else None
    saved_config = saved_metadata.get("config") if isinstance(saved_metadata, dict) else None

    cfg = ASCTBenchmarkConfig().update_with_dict(recipe._metadata.default_config or {})
    if isinstance(saved_config, dict):
        cfg.update_with_dict(saved_config)
    if isinstance(recipe_config, dict):
        cfg.update_with_dict(recipe_config)
    recipe._cfg = cfg


def run(args):
    if args.format in ("csv", "json") and not getattr(args, "output_dir", None):
        log.critical(f"'asct view --format {args.format}' requires --output-dir")
        sys.exit(1)

    manifest = None
    user_config = {}
    try:
        manifest_data = read_manifest_data(args.run_dir)
        manifest = manifest_data.manifest
        user_config = manifest_data.user_config
    except (RuntimeError, TypeError):
        pass

    try:
        recipe_names, legacy_raw = _discover_saved_recipe_names(args.run_dir, manifest)
    except (RuntimeError, TypeError) as exc:
        log.critical(str(exc))
        sys.exit(1)

    completed_benchmarks = {}
    for benchmark_name in recipe_names:
        try:
            if legacy_raw is not None:
                recipe = _load_legacy_saved_recipe(args.run_dir, benchmark_name, legacy_raw[benchmark_name])
                saved_metadata = None
            else:
                if not has_valid_saved_recipe(args.run_dir, benchmark_name):
                    continue
                saved_metadata = read_saved_recipe_artifacts(args.run_dir, benchmark_name).metadata
                recipe = load_saved_recipe(args.run_dir, benchmark_name)
            _apply_view_user_config(recipe, user_config, saved_metadata)
            completed_benchmarks[benchmark_name] = recipe
        except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError) as exc:
            log.warning(f"Unable to load saved results for '{benchmark_name}': {exc}")

    completed_benchmarks = sort_for_output(completed_benchmarks)
    OUTPUT_HANDLERS[args.format](args, completed_benchmarks, {}, {})
