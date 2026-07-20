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

from asct.core.benchspec.benchspec import ProgramSpec
import json
import pandas as pd
import os


class StorageBenchSpec(ProgramSpec):
    """
    Class to capture how to run and process output a Storage I/O benchmark (fio).
    """

    def __init__(self, config):
        self.blocksize = config.blocksize
        self.readwrite = config.rw_pattern
        # Use readwrite pattern as the name of the job following the golden command provided by InfraLob team
        self.name = self.readwrite
        self.iodepth = config.iodepth
        self.ioengine = config.ioengine
        self.numjobs = config.numjobs
        self.runtime = config.duration
        self.rwmixread = config.rwmixread
        self.direct = config.direct
        self.cpus_allowed = config.target_cpus
        self.filenames = config.filenames

    # Convert floating point runtime to time string accepted by fio
    @property
    def runtime_str(self):
        runtime = self.runtime
        if runtime >= 1:
            return f"{int(runtime)}s"
        if runtime >= 1e-3:
            return f"{int(runtime * 1e3)}ms"
        if runtime >= 1e-6:
            return f"{int(runtime * 1e6)}us"
        return f"{int(runtime * 1e9)}ns"

    def make_cmd(self):
        """
        Create the command line to run fio with the specified parameters.

        Returns:
            list: Command line as a list of strings.
        """
        cmd = [
            "fio",
            f"--name={self.name}",
            f"--filename={':'.join(self.filenames)}",
            f"--readwrite={self.readwrite}",
            f"--blocksize={self.blocksize}",
            f"--ioengine={self.ioengine}",
            f"--iodepth={self.iodepth}",
            f"--numjobs={self.numjobs}",
            f"--runtime={self.runtime_str}",
            f"--direct={1 if self.direct else 0}",
            f"--cpus_allowed={','.join(map(str, self.cpus_allowed))}",
            "--cpus_allowed_policy=split",
            "--time_based",
            "--output-format=json",
            f"--output={self.name}.json",
        ]
        if self.rwmixread is not None:
            cmd.append(f"--rwmixread={self.rwmixread}")
        return cmd

    def check_output(self, runner):
        # Skip check as fio output is in files
        pass

    def process_output(self, runner):
        """
        Process the output from fio and extract relevant metrics.

        Args:
            runner: Runner object which provides execution context such as `cwd`.
        """
        r = super().process_output(runner)
        # Read the output JSON file from current directory
        with open(os.path.join(runner.cwd, f"{self.name}.json"), "r") as f:
            r.json_data = json.load(f)
        json_data = r.json_data
        # Below will aggregate metrics across all jobs but still separately for read and write
        metrics = {
            "read": {
                "bw_bytes_per_sec": 0,
                "iops_per_sec": 0,
                "mean_latencies_ns_list": [],
                "mean_latencies_ns": 0,
                "latencies_sample_counts": [],
                "total_latency_count": 0,
                "latency_ns_percentiles_dfs": [],
                "mean_latency_ns_percentiles_dict": None,
            },
            "write": {
                "bw_bytes_per_sec": 0,
                "iops_per_sec": 0,
                "mean_latencies_ns_list": [],
                "mean_latencies_ns": 0,
                "latencies_sample_counts": [],
                "total_latency_count": 0,
                "latency_ns_percentiles_dfs": [],
                "mean_latency_ns_percentiles_dict": None,
            },
        }
        all_accesses = ["read", "write"]

        job_start_ms_list = [job["job_start"] for job in json_data["jobs"]]
        # Take the max runtime across all accesses for each job to ensure capturing all accesses
        run_times_ms_list = [max(job[op]["runtime"] for op in all_accesses) for job in json_data["jobs"]]
        job_end_ms_list = [start + dur for start, dur in zip(job_start_ms_list, run_times_ms_list, strict=False)]

        for operation in all_accesses:
            for job_index, job in enumerate(json_data["jobs"]):
                job_operation = job[operation]
                metrics[operation]["iops_per_sec"] += job_operation["iops"]
                metrics[operation]["bw_bytes_per_sec"] += job_operation["bw_bytes"]
                clat_ns = job_operation["clat_ns"]
                metrics[operation]["mean_latencies_ns_list"].append(clat_ns["mean"])
                metrics[operation]["latencies_sample_counts"].append(clat_ns["N"])
                if "percentile" in clat_ns:
                    # Append the dataframe to the list to be concatenated later
                    metrics[operation]["latency_ns_percentiles_dfs"].append(
                        # index is the percentile, value is the latency in ns
                        pd.DataFrame.from_dict(
                            clat_ns["percentile"], orient="index", columns=[f"Latency_{job_index} (ns)"]
                        )
                    )

            if metrics[operation]["latency_ns_percentiles_dfs"]:
                lat_ns_percentiles_df = pd.concat(metrics[operation]["latency_ns_percentiles_dfs"], axis=1)
                lat_ns_percentiles_df.index = lat_ns_percentiles_df.index.astype(float)
                # Convert to dictionary for easier serialization done by the DataRegistry class
                metrics[operation]["mean_latency_ns_percentiles_dict"] = lat_ns_percentiles_df.mean(axis=1).to_dict()
            else:
                metrics[operation]["mean_latency_ns_percentiles_dict"] = None

            # Compute the weighted average latency using mean_latencies_ns and latencies_sample_counts
            latencies_ns = metrics[operation]["mean_latencies_ns_list"]
            sample_counts = metrics[operation]["latencies_sample_counts"]
            total_count = metrics[operation]["total_latency_count"] = sum(sample_counts)

            if total_count > 0:
                weighted_sum_ns = sum(value * count for value, count in zip(latencies_ns, sample_counts, strict=False))
                metrics[operation]["mean_latency_ns"] = weighted_sum_ns / total_count
            else:
                metrics[operation]["mean_latency_ns"] = 0

        r.read_mean_latency_ns_percentiles_dict = metrics["read"]["mean_latency_ns_percentiles_dict"]
        r.write_mean_latency_ns_percentiles_dict = metrics["write"]["mean_latency_ns_percentiles_dict"]
        r.read_bw_bytes_per_sec = metrics["read"]["bw_bytes_per_sec"]
        r.write_bw_bytes_per_sec = metrics["write"]["bw_bytes_per_sec"]
        r.read_iops_per_sec = metrics["read"]["iops_per_sec"]
        r.write_iops_per_sec = metrics["write"]["iops_per_sec"]
        r.read_latency_sample_counts = sum(metrics["read"]["latencies_sample_counts"])
        r.read_mean_latency_ns = metrics["read"]["mean_latency_ns"]
        r.write_latency_sample_counts = sum(metrics["write"]["latencies_sample_counts"])
        r.write_mean_latency_ns = metrics["write"]["mean_latency_ns"]
        # Will capture the lastest start and earliest end time across all jobs for steady state duration
        r.run_start_ms = max(job_start_ms_list) if job_start_ms_list else 0
        # Take the earliest end time across all jobs
        r.run_end_ms = min(job_end_ms_list) if job_end_ms_list else 0
        return r
