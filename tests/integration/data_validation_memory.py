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

from .data_validation import (
    is_int,
    is_float,
    is_int_str,
    is_float_str,
    is_str,
    validate_json,
    validate_csv,
    validate_stdout,
    extract_stdout_table,
)

from asct.core.recipes.configuration.defaults import LOADED_LATENCY_DEFAULT_CONFIG
from asct.core.recipes.impl import (
    CycleLatencySweep,
)

from asct.core.benchspec.memory_benchspec import BandwidthBenchmarkSpec


EXTRA_JSON_ARTIFACTS = {
    "bandwidth-sweep": ["bandwidth-sweep.ubench.json"],
    "latency-sweep": ["latency-presweep.ubench.json", "latency-sweep-summary.ubench.json", "latency-sweep.ubench.json"],
}
EXTRA_PNG_ARTIFACTS = {
    "latency-sweep": ["latency-sweep.png"],
    "bandwidth-sweep": ["bandwidth-sweep.png"],
    "loaded-latency": ["loaded-latency.png"],
}

# Based on https://www.libpng.org/pub/png/spec/1.2/PNG-Structure.html
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

PeakBandwidth_columns = ["Traffic type", "Peak BW [GB/s]", "% of Peak Theoretical"]
CycleLatencySweep_columns = ["Lower Bound", "Upper Bound", "Optimum Datasize", "Latency [ns]"]
BandwidthSweep_columns = ["Datasize Used", "Level", "Bandwidth [GB/s]"]
LoadedLatency_columns = ["Injected NOPs", "Loaded latency [ns]", "Bandwidth [GB/s]", "% of Peak Theoretical BW"]

IdleLatency_results_desc = "Latencies of random memory access at idle (ns)"
PeakBandwidth_results_desc = "Peak memory bandwidth"
CrossNumaBandwidth_results_desc = "Cross-NUMA bandwidths for the system (in GB/s)"
CycleLatencySweep_results_desc = "Latencies at different levels of cache"
BandwidthSweep_results_desc = "Bandwidth at different levels of cache"
LoadedLatency_results_desc = "Loaded latency with background memory activity"


def validate_result(result, benchmark_names, sysreport, output_type, validate_extra_artifacts=True, permissive=False):
    if output_type == "json":
        assert "report.json" in result.json_file_content, "report.json was not found in results"
        validate_json_data(result, benchmark_names, sysreport, validate_extra_artifacts, permissive)
    elif output_type == "csv":
        validate_csv_data(result, benchmark_names, sysreport, validate_extra_artifacts, permissive)
    elif output_type == "stdout":
        validate_stdout_data(result, benchmark_names, sysreport, validate_extra_artifacts, permissive)


def _get_sysreport_root(sysreport):
    """Select the sysreport dict that contains system HW info.

    Some runs may include additional JSON roots (e.g. NetworkInfo) which do not
    contain the keys needed for memory validation.
    """

    if isinstance(sysreport, dict) and "sys_hw" in sysreport:
        return sysreport

    candidates = []

    if isinstance(sysreport, dict):
        for key in ("system-info", "system_info", "sysreport"):
            value = sysreport.get(key)
            if isinstance(value, dict):
                candidates.append(value)

        candidates.extend([v for v in sysreport.values() if isinstance(v, dict)])

    if isinstance(sysreport, list):
        candidates.extend([v for v in sysreport if isinstance(v, dict)])

    for candidate in candidates:
        if "sys_hw" in candidate:
            return candidate

    if isinstance(sysreport, dict) and ("net_dev" in sysreport or "net_ns" in sysreport):
        raise AssertionError(
            "Expected sysreport root containing 'sys_hw' for memory validation, "
            f"but got NetworkInfo-like dict with keys: {sorted(sysreport.keys())}"
        )

    raise AssertionError(
        f"Expected sysreport root containing 'sys_hw' for memory validation, but got: {type(sysreport).__name__}"
    )


# JSON reference data
def _get_numa_to_numa_json_ref(sysreport):
    data = {}
    numa_count = sysreport["sys_hw"]["n_numa_nodes"]
    for m in range(numa_count):
        key_name = f"Node {m}"
        data[key_name] = {f"Node {n}": is_float for n in range(numa_count)}
    return data


def _get_json_ref_data_idle_latency(sysreport, _data, _permissive):
    return {"idle-latency": _get_numa_to_numa_json_ref(sysreport)}


def _get_json_ref_data_cross_numa_bandwidth(sysreport, _data, _permissive):
    return {"cross-numa-bandwidth": _get_numa_to_numa_json_ref(sysreport)}


def _get_peak_bandwidth_access_descs(sysreport):
    sys_hw = sysreport["sys_hw"]
    access_descs = BandwidthBenchmarkSpec.access_descs
    if sys_hw["arch"].lower().startswith("arm") and "sve" not in sys_hw["cpu_features"]:
        # May need to skip Non-Temporal one if SVE not available
        access_descs = {k: v for k, v in access_descs.items() if "Non-Temporal" not in v.long}
    return access_descs


def _is_peak_bandwidth_available(sysreport):
    return sysreport["memory"].get("peak_theoretical_bw", None) is not None


def _get_json_ref_data_peak_bandwidth(sysreport, _data, _permissive):
    columns = PeakBandwidth_columns
    peak_bw_data = {}
    access_descs = _get_peak_bandwidth_access_descs(sysreport)
    peak_bw_data[columns[0]] = {f"{idx}": traffic_type.long for idx, traffic_type in enumerate(access_descs.values())}
    peak_bw_data[columns[1]] = {f"{idx}": is_float for idx, _ in enumerate(access_descs.values())}
    if _is_peak_bandwidth_available(sysreport):
        peak_bw_data[columns[2]] = {f"{idx}": is_float for idx, _ in enumerate(access_descs.values())}
    return {"peak-bandwidth": peak_bw_data}


def _get_cache_level_names_from_result_json(benchmark_name, data, permissive):
    assert benchmark_name in data, f"{benchmark_name} not found in result data {data}"
    default_level_names = CycleLatencySweep.level_names
    if permissive:
        if benchmark_name == "latency-sweep":
            levels = None
            for column in CycleLatencySweep_columns:
                if not levels:
                    levels = list(data[benchmark_name][column])
                    for level in levels:
                        assert level in default_level_names, (
                            f"Cache level {level} not found in default levels "
                            f"{default_level_names} for {benchmark_name}"
                        )
                else:
                    column_levels = list(data[benchmark_name][column])
                    assert set(levels) == set(column_levels), (
                        f"Cache levels mismatch in {benchmark_name} JSON data: "
                        f"{levels} != {column_levels} for column {column}"
                    )
            assert levels, f"No valid cache levels found for {benchmark_name} JSON data: {data[benchmark_name]}"
            return levels
        if benchmark_name == "bandwidth-sweep":
            level_data = data[benchmark_name]["Level"]
            return [level_data[key] for key in sorted(level_data.keys(), key=int)]
        raise AssertionError(f"Cache level extraction not implemented for {benchmark_name}")
    return default_level_names


def _get_json_ref_data_latency_sweep(_sysreport, data, permissive):
    columns = CycleLatencySweep_columns
    level_names = _get_cache_level_names_from_result_json("latency-sweep", data, permissive)
    return {
        "latency-sweep": {
            columns[0]: dict.fromkeys(level_names, is_int),
            columns[1]: dict.fromkeys(level_names, is_int),
            columns[2]: dict.fromkeys(level_names, is_int),
            columns[3]: dict.fromkeys(level_names, is_float),
        }
    }


def _get_json_ref_data_bandwidth_sweep(_sysreport, data, permissive):
    columns = BandwidthSweep_columns
    level_names = _get_cache_level_names_from_result_json("bandwidth-sweep", data, permissive)
    return {
        "bandwidth-sweep": {
            columns[0]: {f"{idx}": is_int for idx, _ in enumerate(level_names)},
            columns[1]: {f"{idx}": mem_type for idx, mem_type in enumerate(level_names)},
            columns[2]: {f"{idx}": is_float for idx, _ in enumerate(level_names)},
        }
    }


def _get_json_ref_data_loaded_latency(sysreport, _data, _permissive):
    columns = LoadedLatency_columns
    injected_nops = LOADED_LATENCY_DEFAULT_CONFIG["injected_nops"]
    loaded_latency_data = {
        columns[0]: {f"{idx}": nops for idx, nops in enumerate(injected_nops)},
        columns[1]: {f"{idx}": is_float for idx, _ in enumerate(injected_nops)},
        columns[2]: {f"{idx}": is_float for idx, _ in enumerate(injected_nops)},
    }
    if _is_peak_bandwidth_available(sysreport):
        loaded_latency_data[columns[3]] = {f"{idx}": is_float for idx, _ in enumerate(injected_nops)}
    return {"loaded-latency": loaded_latency_data}


# JSON reference data for sweep artifacts
def _get_json_ref_data_sweep(data, is_bandwidth):
    assert "sizes" in data, "sizes not found in bandwidth.ubench data"
    sample_count = len(data["sizes"])
    ref_data = {
        "sizes": {f"{idx}": is_int for idx in range(sample_count)},
        "repetitions": {f"{idx}": is_int for idx in range(sample_count)},
    }
    if is_bandwidth:
        ref_data["total_bandwidth_mbps"] = {f"{idx}": is_float for idx in range(sample_count)}
    else:
        ref_data["average_latency_ns"] = {f"{idx}": is_float for idx in range(sample_count)}
    return ref_data


def _get_json_ref_data_bandwidth_sweep_ubench(_sysreport, data, _permissive):
    return _get_json_ref_data_sweep(data, True)


def _get_json_ref_data_latency_presweep_ubench(_sysreport, data, _permissive):
    return _get_json_ref_data_sweep(data, False)


def _get_json_ref_data_latency_sweep_ubench(_sysreport, data, _permissive):
    return _get_json_ref_data_sweep(data, False)


def _get_json_ref_data_latency_sweep_summary_ubench(_sysreport, _data, _permissive):
    sweet_spot_entry = {
        "LB": is_int,
        "UB": is_int,
        "sweet_spot": {"sizes": is_int, "repetitions": is_int, "average_latency_ns": is_float},
    }
    return dict.fromkeys(CycleLatencySweep.level_names, sweet_spot_entry)


def _get_ref_data(benchmark, data_type, sysreport, result_data, permissive=False):
    benchmark_name = benchmark.replace("-", "_").replace(".", "_")
    func_name = f"_get_{data_type}_ref_data_{benchmark_name}"
    assert func_name in globals(), f"Ref data generation function {func_name} not found, please implement it"
    return globals()[func_name](sysreport, result_data, permissive)


def _validate_ubench_artifacts(result, benchmark_name):
    if benchmark_name in EXTRA_JSON_ARTIFACTS:
        for file_name in EXTRA_JSON_ARTIFACTS[benchmark_name]:
            assert file_name in result.json_file_content, f"{file_name} not found in results"
            artif_data = result.json_file_content[file_name]
            artif_name = file_name.removesuffix(".json")
            ref_data = _get_ref_data(artif_name, "json", None, artif_data)
            validate_json(ref_data, artif_data)
    if benchmark_name in EXTRA_PNG_ARTIFACTS:
        for png_name in EXTRA_PNG_ARTIFACTS[benchmark_name]:
            assert png_name in result.png_file_content, f"{png_name} not found in results"
            assert result.png_file_content[png_name] == _PNG_SIGNATURE, f"{png_name} is not a valid PNG file"


def validate_json_data(result, benchmark_names, sysreport, validate_extra_artifacts, permissive):
    json_report = result.json_file_content["report.json"]
    assert "memory" in json_report, f"memory entry not found in results for {benchmark_names}"

    for benchmark in benchmark_names:
        mem_data = json_report["memory"]
        ref_data = _get_ref_data(benchmark, "json", sysreport, mem_data, permissive)
        validate_json(ref_data, mem_data)
        if validate_extra_artifacts:
            _validate_ubench_artifacts(result, benchmark)


# CSV reference data
def _get_csv_ref_data_peak_bandwidth(sysreport, _data, _permissive):
    # if peak theoretical bw is unavailable: remove "% of Peak Theoretical" column
    columns = PeakBandwidth_columns if _is_peak_bandwidth_available(sysreport) else PeakBandwidth_columns[:-1]
    ref_array = [["", *columns]]

    access_descs = _get_peak_bandwidth_access_descs(sysreport)
    for idx, traffic_type in enumerate(access_descs.values()):
        ref_array += [[f"{idx}", traffic_type.long] + [is_float_str] * (len(columns) - 1)]
    return ref_array


def _get_numa_to_numa_array_ref(sysreport):
    numa_count = sysreport["sys_hw"]["n_numa_nodes"]
    ref_csv = [[""] + [f"Node {idx}" for idx in range(numa_count)]]
    for idx in range(numa_count):
        ref_csv += [[f"Node {idx}"] + [is_float_str] * numa_count]
    return ref_csv


def _get_csv_ref_data_idle_latency(sysreport, _data, _permissive):
    return _get_numa_to_numa_array_ref(sysreport)


def _get_csv_ref_data_cross_numa_bandwidth(sysreport, _data, _permissive):
    return _get_numa_to_numa_array_ref(sysreport)


def _get_cache_level_names_from_result_csv(benchmark_name, mode, data, permissive):
    default_level_names = CycleLatencySweep.level_names
    target_column_idx = {
        "latency-sweep": {
            "csv": 0,
            "stdout": 0,
        },
        "bandwidth-sweep": {
            "csv": 2,
            "stdout": 1,
        },
    }
    col_index = target_column_idx[benchmark_name][mode]
    if permissive:
        assert len(data) > 1, f"CSV data is empty for {benchmark_name}"
        levels = [line[col_index] for line in data[1:]]
        for level in levels:
            assert level in default_level_names, (
                f"Cache level {level} in the CSV data not found "
                f"in default levels {default_level_names} for {benchmark_name}"
            )
        return levels
    return default_level_names


def _get_csv_ref_data_latency_sweep(_sysreport, data, permissive):
    level_names = _get_cache_level_names_from_result_csv("latency-sweep", "csv", data, permissive)
    ref_array = [["", *CycleLatencySweep_columns]]
    ref_array += [[mem_type, is_int_str, is_int_str, is_int_str, is_float_str] for mem_type in level_names]
    return ref_array


def _get_csv_ref_data_bandwidth_sweep(_sysreport, data, permissive):
    level_names = _get_cache_level_names_from_result_csv("bandwidth-sweep", "csv", data, permissive)
    ref_array = [["", *BandwidthSweep_columns]]
    ref_array += [[f"{idx}", is_int_str, mem_type, is_float_str] for idx, mem_type in enumerate(level_names)]
    return ref_array


def _get_csv_ref_data_loaded_latency(sysreport, _data, _permissive):
    # if peak theoretical bw is unavailable: remove "% of Peak Theoretical" column
    columns = LoadedLatency_columns if _is_peak_bandwidth_available(sysreport) else LoadedLatency_columns[:-1]
    ref_array = [["", *columns]]
    ref_array += [
        ([f"{idx}", f"{nops}"] + [is_float_str] * (len(columns) - 1))
        for idx, nops in enumerate(LOADED_LATENCY_DEFAULT_CONFIG["injected_nops"])
    ]
    return ref_array


# STDOUT reference data
def _get_stdout_ref_data_peak_bandwidth(sysreport, data, _permissive):
    # if peak theoretical bw is unavailable: remove "% of Peak Theoretical" column
    columns = PeakBandwidth_columns if _is_peak_bandwidth_available(sysreport) else PeakBandwidth_columns[:-1]
    table_name = PeakBandwidth_results_desc
    ref_array = [columns]
    access_descs = _get_peak_bandwidth_access_descs(sysreport)
    for traffic_type in access_descs.values():
        ref_array += [[traffic_type.long] + [is_float_str] * (len(columns) - 1)]
    return PeakBandwidth_results_desc, ref_array, extract_stdout_table(data, table_name)


def _get_stdout_ref_data_idle_latency(sysreport, data, _permissive):
    table_name = IdleLatency_results_desc
    return table_name, _get_numa_to_numa_array_ref(sysreport), extract_stdout_table(data, table_name)


def _get_stdout_ref_data_cross_numa_bandwidth(sysreport, data, _permissive):
    table_name = CrossNumaBandwidth_results_desc
    return table_name, _get_numa_to_numa_array_ref(sysreport), extract_stdout_table(data, table_name)


def _get_stdout_ref_data_latency_sweep(_sysreport, data, permissive):
    table_name = CycleLatencySweep_results_desc
    parsed_data = extract_stdout_table(data, table_name)
    level_names = _get_cache_level_names_from_result_csv("latency-sweep", "stdout", parsed_data, permissive)
    ref_array = [["", *CycleLatencySweep_columns]]
    ref_array += [[mem_type, is_str, is_str, is_str, is_float_str] for mem_type in level_names]
    return table_name, ref_array, parsed_data


def _get_stdout_ref_data_bandwidth_sweep(_sysreport, data, permissive):
    table_name = BandwidthSweep_results_desc
    parsed_data = extract_stdout_table(data, table_name)
    level_names = _get_cache_level_names_from_result_csv("bandwidth-sweep", "stdout", parsed_data, permissive)
    ref_array = [BandwidthSweep_columns]
    ref_array += [[is_str, mem_type, is_float_str] for idx, mem_type in enumerate(level_names)]
    return table_name, ref_array, parsed_data


def _get_stdout_ref_data_loaded_latency(sysreport, data, _permissive):
    # if peak theoretical bw is unavailable: remove "% of Peak Theoretical" column
    columns = LoadedLatency_columns if _is_peak_bandwidth_available(sysreport) else LoadedLatency_columns[:-1]
    table_name = LoadedLatency_results_desc
    injected_nops = LOADED_LATENCY_DEFAULT_CONFIG["injected_nops"]
    ref_array = [columns]
    ref_array += [([f"{nops}"] + [is_float_str] * (len(columns) - 1)) for nops in injected_nops]
    return table_name, ref_array, extract_stdout_table(data, table_name)


def validate_csv_data(result, benchmark_names, sysreport, validate_extra_artifacts, permissive):
    for benchmark in benchmark_names:
        file_name = f"{benchmark}.csv"
        assert file_name in result.csv_file_content, f"{file_name} not found in results"
        assert len(result.raw_file_content[file_name]) > 0, f"{file_name} is empty"
        assert result.csv_file_content[file_name], f"{file_name} didn't contain any CSV data"
        ref_data = _get_ref_data(benchmark, "csv", sysreport, result.csv_file_content[file_name], permissive)
        validate_csv(ref_data, result.csv_file_content[file_name])
        if validate_extra_artifacts:
            _validate_ubench_artifacts(result, benchmark)


def validate_stdout_data(result, benchmark_names, sysreport, validate_extra_artifacts, permissive):
    sysreport = _get_sysreport_root(sysreport)
    for benchmark in benchmark_names:
        _, ref_stdout_data, parsed_stdout_data = _get_ref_data(
            benchmark, "stdout", sysreport, result.stdout, permissive
        )
        if not ref_stdout_data:
            continue
        validate_stdout(ref_stdout_data, parsed_stdout_data)
        if validate_extra_artifacts:
            _validate_ubench_artifacts(result, benchmark)
