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

"""Minimal networking benchmark data model for the experimental iperf3 recipe."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import time
from typing import Any

import pandas as pd


class BenchmarkTool(str, Enum):
    IPERF3 = "iperf3"
    OTHER = "other"


class Protocol(str, Enum):
    TCP = "tcp"
    UDP = "udp"
    UNKNOWN = "unknown"


class RunStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"


@dataclass(slots=True)
class Serializable:
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TimeInfo(Serializable):
    timestamp_utc: float = field(default_factory=time.time)


@dataclass(slots=True)
class HostInfo(Serializable):
    hostname: str | None = None
    ip: str | None = None


@dataclass(slots=True)
class NetworkPathInfo(Serializable):
    client_host: HostInfo = field(default_factory=HostInfo)
    server_host: HostInfo = field(default_factory=HostInfo)
    protocol: Protocol = Protocol.UNKNOWN
    port: int | None = None


@dataclass(slots=True)
class NetworkBenchmarkParams(TimeInfo):
    tool: BenchmarkTool = BenchmarkTool.OTHER
    tool_version: str | None = None
    command: str | None = None
    args: list[str] = field(default_factory=list)
    path: NetworkPathInfo = field(default_factory=NetworkPathInfo)
    duration_s: float | None = None
    message_size_bytes: int | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BenchmarkError(TimeInfo):
    message: str | None = None
    retcode: int | None = None
    stdout: str | None = None
    stderr: str | None = None


@dataclass(slots=True)
class ThroughputMetrics(Serializable):
    sender_bps: float | None = None
    receiver_bps: float | None = None
    sender_mbps: float | None = None
    receiver_mbps: float | None = None


@dataclass(slots=True)
class CpuUtilizationMetrics(Serializable):
    sender_total_pct: float | None = None
    sender_user_pct: float | None = None
    sender_system_pct: float | None = None
    receiver_total_pct: float | None = None
    receiver_user_pct: float | None = None
    receiver_system_pct: float | None = None


@dataclass(slots=True)
class MeasurementSet(Serializable):
    throughput: ThroughputMetrics = field(default_factory=ThroughputMetrics)
    cpu_utilization: CpuUtilizationMetrics = field(default_factory=CpuUtilizationMetrics)


@dataclass(slots=True)
class ToolSpecificData(Serializable):
    tool: BenchmarkTool = BenchmarkTool.OTHER
    raw_output: str | None = None
    raw_json: dict[str, Any] | None = None
    parsed_extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Iperf3Data(ToolSpecificData):
    tool: BenchmarkTool = BenchmarkTool.IPERF3
    version: str | None = None
    test_start_block: dict[str, Any] = field(default_factory=dict)
    test_end_block: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BenchmarkRun(TimeInfo):
    run_id: str | None = None
    status: RunStatus = RunStatus.SUCCESS
    setup: NetworkBenchmarkParams = field(default_factory=NetworkBenchmarkParams)
    measurements: MeasurementSet = field(default_factory=MeasurementSet)
    error: BenchmarkError | None = None
    tool_data: ToolSpecificData = field(default_factory=ToolSpecificData)
    notes: list[str] = field(default_factory=list)

    def flat_summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status.value,
            "tool": self.setup.tool.value,
            "protocol": self.setup.path.protocol.value,
            "server_host": self.setup.path.server_host.ip,
            "client_host": self.setup.path.client_host.ip,
            "port": self.setup.path.port,
            "duration_s": self.setup.duration_s,
            "message_size_bytes": self.setup.message_size_bytes,
            "sender_bps": self.measurements.throughput.sender_bps,
            "receiver_bps": self.measurements.throughput.receiver_bps,
            "sender_mbps": self.measurements.throughput.sender_mbps,
            "receiver_mbps": self.measurements.throughput.receiver_mbps,
            "sender_cpu_total_pct": self.measurements.cpu_utilization.sender_total_pct,
            "sender_cpu_user_pct": self.measurements.cpu_utilization.sender_user_pct,
            "sender_cpu_system_pct": self.measurements.cpu_utilization.sender_system_pct,
            "receiver_cpu_total_pct": self.measurements.cpu_utilization.receiver_total_pct,
            "receiver_cpu_user_pct": self.measurements.cpu_utilization.receiver_user_pct,
            "receiver_cpu_system_pct": self.measurements.cpu_utilization.receiver_system_pct,
            "error_message": self.error.message if self.error else None,
            "retcode": self.error.retcode if self.error else None,
        }


@dataclass(slots=True)
class NetworkingBenchmarkResults(Serializable):
    runs: list[BenchmarkRun] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"runs": [run.to_dict() for run in self.runs]}

    def to_dataframe(self):
        return pd.DataFrame([run.flat_summary() for run in self.runs])


class BenchmarkParser:
    def parse(
        self,
        *,
        raw_stdout: str,
        raw_stderr: str,
        setup: NetworkBenchmarkParams,
        retcode: int | None = None,
    ) -> BenchmarkRun:
        raise NotImplementedError("Subclasses must implement parse().")
