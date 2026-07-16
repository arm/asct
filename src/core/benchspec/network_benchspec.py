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

"""Minimal networking benchspecs for the experimental iperf3 recipe."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence
import shlex

import asct.core.logger as log
from asct.core.benchspec.benchspec import ASCTBenchmarkConfig, ProgramSpec
from asct.lib.networking.benchmark_model import (
    BenchmarkTool,
    HostInfo,
    NetworkBenchmarkParams,
    NetworkingBenchmarkResults,
    NetworkPathInfo,
    Protocol,
)
from asct.lib.networking.iperf3_parser import Iperf3Parser
from asct.lib.networking.network_helpers import DEFAULT_IPERF3_PORT, check_port_value


class NetworkingBenchmarkConfig(ASCTBenchmarkConfig):
    """Thin config wrapper for experimental networking benchmark settings."""

    def _get_adjusted_duration(self, original_duration):
        error_message = "network benchmark duration must be a whole integer number of seconds"
        if isinstance(original_duration, bool):
            raise TypeError(error_message)

        try:
            original_whole_seconds = int(original_duration)
        except (TypeError, ValueError) as exc:
            raise ValueError(error_message) from exc

        if not isinstance(original_duration, str) and original_whole_seconds != original_duration:
            raise ValueError(error_message)

        if original_whole_seconds <= 0:
            raise ValueError("network benchmark duration must be at least 1 second")

        adjusted_duration = int(super()._get_adjusted_duration(original_whole_seconds))
        return max(adjusted_duration, 1)


@dataclass(slots=True)
class Iperf3ClientConfig:
    server_host: Any = None
    port: int | None = None
    protocol: str | Protocol = Protocol.UNKNOWN.value
    duration: int | None = None
    window: str | None = None
    client_affinity: int | None = None
    server_affinity: int | None = None
    message_size_bytes: int | None = None
    bandwidth_target_bps: int | None = None
    network_namespace: str | None = None
    reverse: bool = False
    bidirectional: bool = False
    zerocopy: bool = False
    extra_args: Sequence[str] = field(default_factory=tuple)
    notes: Sequence[str] = field(default_factory=tuple)
    run_id: str | None = None

    @classmethod
    def from_config(cls, config):
        return cls(**{
            field_name: getattr(config, field_name)
            for field_name in cls.__dataclass_fields__
            if hasattr(config, field_name)
        })

    def __post_init__(self) -> None:
        if self.port is not None:
            self.port = check_port_value(self.port, userspace_only=True, raise_on_error=True)

        if self.duration is not None:
            if isinstance(self.duration, bool):
                raise TypeError("iperf3 --time duration must be a positive integer number of seconds")
            try:
                duration = int(self.duration)
            except (TypeError, ValueError) as exc:
                raise ValueError("iperf3 --time duration must be a positive integer number of seconds") from exc
            # Fractional or zero-second runs can produce invalid timing results.
            if duration <= 0 or (not isinstance(self.duration, str) and duration != self.duration):
                raise ValueError("iperf3 --time duration must be a positive integer number of seconds")
            self.duration = duration

        self.client_affinity = None if self.client_affinity is None else int(self.client_affinity)
        self.server_affinity = None if self.server_affinity is None else int(self.server_affinity)
        self.message_size_bytes = None if self.message_size_bytes is None else int(self.message_size_bytes)
        self.bandwidth_target_bps = None if self.bandwidth_target_bps is None else int(self.bandwidth_target_bps)
        self.network_namespace = None if self.network_namespace in (None, "") else str(self.network_namespace)
        self.extra_args = tuple(str(arg) for arg in (self.extra_args or ()))
        self.notes = tuple(str(note) for note in (self.notes or ()))
        self.run_id = None if self.run_id is None else str(self.run_id)


class NetworkingBenchmarkSpec(ProgramSpec):
    tool = BenchmarkTool.OTHER

    def __init__(self, parser, config):
        super().__init__(config)
        self.parser = parser

    def _protocol(self) -> Protocol:
        protocol_name = str(getattr(self.config, "protocol", Protocol.UNKNOWN.value)).lower()
        return Protocol._value2member_map_.get(protocol_name, Protocol.UNKNOWN)

    def _port(self) -> int:
        port = getattr(self.config, "port", None)
        return DEFAULT_IPERF3_PORT if port is None else port

    def build_setup(self, cmd: list[str]) -> NetworkBenchmarkParams:
        return NetworkBenchmarkParams(
            tool=self.tool,
            command=shlex.join(cmd),
            args=cmd[1:],
            path=NetworkPathInfo(
                client_host=HostInfo(ip=None),
                server_host=HostInfo(ip=str(getattr(self.config, "server_host", None) or "") or None),
                protocol=self._protocol(),
                port=self._port(),
            ),
            duration_s=getattr(self.config, "duration", None),
            message_size_bytes=getattr(self.config, "message_size_bytes", None),
            notes=list(getattr(self.config, "notes", []) or []),
        )

    def process_output(self, runner):
        cmd = self.make_cmd()
        return NetworkingBenchmarkResults(
            runs=[
                self.parser.parse(
                    raw_stdout=runner.stdout or "",
                    raw_stderr=runner.stderr or "",
                    setup=self.build_setup(cmd),
                    retcode=runner.retcode,
                )
            ]
        )


class Iperf3BenchSpec(NetworkingBenchmarkSpec):
    tool = BenchmarkTool.IPERF3
    DEFAULT_JSON_LOGFILE = "iperf3-output.json"

    def __init__(self, config, executable: str = "iperf3"):
        super().__init__(parser=Iperf3Parser(), config=Iperf3ClientConfig.from_config(config))
        self.executable = executable

    def _json_logfile_name(self) -> str:
        run_id = getattr(self.config, "run_id", None)
        if run_id:
            return f"{run_id}.iperf3.json"
        return self.DEFAULT_JSON_LOGFILE

    def _json_logfile_path(self, runner) -> Path | None:
        if not getattr(runner, "cwd", None):
            return None
        return Path(runner.cwd) / self._json_logfile_name()

    def _validate_client_options(self, protocol: Protocol) -> None:
        if getattr(self.config, "reverse", False) and getattr(self.config, "bidirectional", False):
            raise ValueError("iperf3 client mode does not allow reverse and bidirectional together")
        if protocol is Protocol.UDP and getattr(self.config, "zerocopy", False):
            raise ValueError("iperf3 zerocopy is only supported for TCP client runs")

    def make_cmd(self):
        server_host = getattr(self.config, "server_host", None)
        if not server_host:
            raise ValueError("Iperf3BenchSpec requires config.server_host")

        cmd = []
        namespace = getattr(self.config, "network_namespace", None)
        if namespace:
            cmd.extend(["ip", "netns", "exec", str(namespace)])

        cmd.extend([
            self.executable,
            "--client",
            str(server_host),
            "--port",
            str(self._port()),
            "--json",
            "--logfile",
            self._json_logfile_name(),
        ])

        client_affinity = getattr(self.config, "client_affinity", None)
        server_affinity = getattr(self.config, "server_affinity", None)
        if client_affinity is not None:
            affinity_arg = str(client_affinity)
            if server_affinity is not None:
                affinity_arg = f"{affinity_arg},{server_affinity}"
            cmd.extend(["--affinity", affinity_arg])

        protocol = self._protocol()
        if protocol is Protocol.UDP:
            cmd.append("--udp")
        elif protocol not in (Protocol.TCP, Protocol.UNKNOWN):
            raise ValueError(f"iperf3 client mode does not support protocol {protocol.value}")

        self._validate_client_options(protocol)

        duration = getattr(self.config, "duration", None)
        if duration is not None:
            cmd.extend(["--time", str(duration)])

        message_size_bytes = getattr(self.config, "message_size_bytes", None)
        if message_size_bytes is not None:
            cmd.extend(["--length", str(message_size_bytes)])

        bandwidth_target_bps = getattr(self.config, "bandwidth_target_bps", None)
        if bandwidth_target_bps is not None:
            cmd.extend([
                "-b",
                str(int(bandwidth_target_bps)),
            ])

        window = getattr(self.config, "window", None)
        if window is not None:
            cmd.extend(["--window", str(window)])

        extra_args = getattr(self.config, "extra_args", None) or []
        cmd.extend(str(arg) for arg in extra_args)

        log.debug("%s", log.LS(lambda: " ".join(cmd)))
        return cmd

    def check_output(self, runner):
        logfile_path = self._json_logfile_path(runner)
        if logfile_path is not None and logfile_path.exists():
            return
        super().check_output(runner)

    def process_output(self, runner):
        raw_stdout = runner.stdout or ""
        logfile_path = self._json_logfile_path(runner)
        if logfile_path is not None and logfile_path.exists():
            raw_stdout = logfile_path.read_text(encoding="utf-8")

        cmd = self.make_cmd()
        return NetworkingBenchmarkResults(
            runs=[
                self.parser.parse(
                    raw_stdout=raw_stdout,
                    raw_stderr=runner.stderr or "",
                    setup=self.build_setup(cmd),
                    retcode=runner.retcode,
                )
            ]
        )


class Iperf3ServerSpec(ProgramSpec):
    def __init__(self, config=None, executable: str = "iperf3"):
        super().__init__(config)
        self.executable = executable

    def make_cmd(self):
        cmd = []
        namespace = getattr(self.config, "network_namespace", None) if self.config is not None else None
        if namespace:
            cmd.extend(["ip", "netns", "exec", str(namespace)])

        cmd.extend([self.executable, "--server"])
        port = None if self.config is None else getattr(self.config, "port", None)
        if port is not None:
            cmd.extend(["--port", str(port)])

        if self.config is not None:
            affinity = getattr(self.config, "server_affinity", None)
            if affinity is not None:
                cmd.extend(["--affinity", str(affinity)])

        extra_args = [] if self.config is None else getattr(self.config, "extra_args", None) or []
        cmd.extend(str(arg) for arg in extra_args)

        log.debug("%s", log.LS(lambda: " ".join(cmd)))
        return cmd

    def check_output(self, runner):
        if runner.retcode not in (None, 0):
            raise RuntimeError("iperf3 server failed to start")
