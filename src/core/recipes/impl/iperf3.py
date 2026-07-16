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

from __future__ import annotations

from dataclasses import dataclass
from enum import Flag, auto
from itertools import product
import ipaddress
import time
from typing import ClassVar

import pandas as pd

from asct.core import benchrunner as br
from asct.core import logger as log
from asct.core.benchspec.network_benchspec import Iperf3BenchSpec, NetworkingBenchmarkConfig
from asct.core.datatypes import Result
from asct.core.recipes.configuration.defaults import IPERF3_SWEEP_DEFAULT_CONFIG
from asct.core.recipes.recipe_benchmark_base import RecipeBenchmarkBase
from asct.core.resources.network_resources import Iperf3, Iperf3Server, Iperf3ServerConfig
from asct.lib.networking.network_helpers import (
    IPERF3_MAX_UDP_PAYLOAD_BYTES,
    LOOPBACK_HOSTNAME,
    LOOPBACK_IPV4,
)


class DisplayLevel(Flag):
    BASIC = auto()
    VERBOSE = auto()
    BOTH = BASIC | VERBOSE


@dataclass(frozen=True)
class InputDisplayField:
    column_name: str
    display_level: DisplayLevel


@dataclass(frozen=True)
class OutputDisplayField:
    column_name: str
    display_level: DisplayLevel


@dataclass(frozen=True)
class ConfigDisplayField:
    key: str
    label: str
    display_level: DisplayLevel


@dataclass
class Iperf3SweepConfig:
    protocol: str
    durations: tuple[int, ...]
    windows: tuple[str | None, ...]
    client_affinities: tuple[int | None, ...]
    message_sizes: tuple[int, ...]
    bandwidth_targets: tuple[int | None, ...]


class Iperf3SweepBase(RecipeBenchmarkBase):
    INTER_STEP_BUFFER_S: ClassVar[float] = 1.0
    BENCHMARK_BINARY: ClassVar[str] = "iperf3"
    RECIPE_NAME: ClassVar[str] = "iperf3_sweep"
    # Keep the sweep matrix internal so the experimental recipe follows the
    # fixed script shape rather than exposing pick-and-choose user knobs.
    PROTOCOL: ClassVar[str] = ""
    INPUT_DISPLAY_FIELDS: ClassVar[list[InputDisplayField]] = [
        InputDisplayField("run_index", DisplayLevel.BASIC),
        InputDisplayField("protocol", DisplayLevel.BASIC),
        InputDisplayField("duration_s", DisplayLevel.BASIC),
        InputDisplayField("window", DisplayLevel.BASIC),
        InputDisplayField("client_affinity", DisplayLevel.BASIC),
        InputDisplayField(
            "message_size_bytes",
            DisplayLevel.BASIC,
        ),
        InputDisplayField(
            "bandwidth_target_bps",
            DisplayLevel.BASIC,
        ),
    ]
    OUTPUT_DISPLAY_FIELDS: ClassVar[list[OutputDisplayField]] = [
        OutputDisplayField("sender_mbps", DisplayLevel.BOTH),
        OutputDisplayField("receiver_mbps", DisplayLevel.BOTH),
        OutputDisplayField("sender_cpu_total_pct", DisplayLevel.BASIC),
        OutputDisplayField("receiver_cpu_total_pct", DisplayLevel.BASIC),
        OutputDisplayField("status", DisplayLevel.VERBOSE),
        OutputDisplayField("error_message", DisplayLevel.BOTH),
        OutputDisplayField("sender_cpu_user_pct", DisplayLevel.VERBOSE),
        OutputDisplayField(
            "sender_cpu_system_pct",
            DisplayLevel.VERBOSE,
        ),
        OutputDisplayField(
            "receiver_cpu_user_pct",
            DisplayLevel.VERBOSE,
        ),
        OutputDisplayField(
            "receiver_cpu_system_pct",
            DisplayLevel.VERBOSE,
        ),
    ]
    CONFIG_DISPLAY_FIELDS: ClassVar[list[ConfigDisplayField]] = [
        ConfigDisplayField("iperf3_version", "iperf3 version", DisplayLevel.BOTH),
        ConfigDisplayField("protocols", "protocols", DisplayLevel.BOTH),
        ConfigDisplayField("durations", "durations", DisplayLevel.BOTH),
        ConfigDisplayField("windows", "windows", DisplayLevel.BOTH),
        ConfigDisplayField("message_sizes", "message sizes", DisplayLevel.BOTH),
        ConfigDisplayField("client_affinities", "client affinities", DisplayLevel.BOTH),
        ConfigDisplayField("bandwidth_targets", "bandwidth targets", DisplayLevel.BOTH),
        ConfigDisplayField("number_of_runs", "number of runs", DisplayLevel.BOTH),
        ConfigDisplayField("manage_local_server", "manage local server", DisplayLevel.VERBOSE),
        ConfigDisplayField("inter_step_buffer", "inter-step buffer", DisplayLevel.VERBOSE),
    ]
    RESULT_COLUMN_ORDER: ClassVar[list[str]] = [
        "run_index",
        "protocol",
        "duration_s",
        "window",
        "client_affinity",
        "message_size_bytes",
        "bandwidth_target_bps",
        "sender_mbps",
        "receiver_mbps",
        "sender_cpu_total_pct",
        "sender_cpu_user_pct",
        "sender_cpu_system_pct",
        "receiver_cpu_total_pct",
        "receiver_cpu_user_pct",
        "receiver_cpu_system_pct",
        "status",
        "error_message",
    ]

    def __init__(self, metadata):
        super().__init__(metadata)
        self.depends_on = {"network"}
        self.rows = []
        self._warned_loopback_server_target = False
        self._sweep_config = None

    def lookup_benchmark_binary(self):
        return self.BENCHMARK_BINARY

    def _configured_server_host(self) -> str | None:
        configured = getattr(self._cfg, "server_host", None)
        if configured is None:
            return None
        normalized = str(configured).strip()
        if normalized.lower() in {"", "none", "null", "nil", "~"}:
            return None
        parse_candidate = normalized
        if normalized.startswith("[") and normalized.endswith("]"):
            parse_candidate = normalized[1:-1]

        try:
            parsed = ipaddress.ip_address(parse_candidate)
        except ValueError:
            return normalized or None

        if parsed.version == 6:
            raise NotImplementedError("IPv6 server_host values are not supported yet; use IPv4 or hostname")

        return normalized or None

    def _create_resources(self):
        resources = [Iperf3(), *super()._create_resources()]
        configured = self._configured_server_host()
        # Explicit server_host means the server lifecycle is external; only
        # manage a local server when no server_host is provided.
        if configured is None:
            resources.append(
                Iperf3Server(
                    Iperf3ServerConfig(
                        port=self._cfg.port,
                        affinity=getattr(self._cfg, "server_affinity", None),
                        cwd=self.results_dir,
                        remote_host=configured,
                    )
                )
            )
        return resources

    def _step_config(self, step, step_sequence: int | None = None):
        protocol, duration, window, client_affinity, message_size, bitrate, run_index = step
        effective_message_size = message_size
        if str(protocol).lower() == "udp" and message_size is not None:
            effective_message_size = int(message_size)
            if effective_message_size > IPERF3_MAX_UDP_PAYLOAD_BYTES:
                log.warning(
                    "UDP message size %s exceeds default iperf3 payload guidance (%s). "
                    "Proceeding without clamping; ensure host network settings are tuned accordingly.",
                    effective_message_size,
                    IPERF3_MAX_UDP_PAYLOAD_BYTES,
                )

        configured_host = self._configured_server_host()
        effective_server_host = configured_host or LOOPBACK_IPV4
        if not self._warned_loopback_server_target and str(effective_server_host).strip().lower() in {
            LOOPBACK_HOSTNAME,
            LOOPBACK_IPV4,
        }:
            log.warning(
                "iperf3 server target is loopback (%s); results reflect local endpoint connectivity",
                effective_server_host,
            )
            self._warned_loopback_server_target = True

        config_source = NetworkingBenchmarkConfig.new_from(
            self._cfg,
            server_host=effective_server_host,
            port=self._cfg.port,
        )

        run_id = f"run-{run_index}"
        if step_sequence is not None:
            run_id = f"{run_id}-step-{step_sequence}"

        return NetworkingBenchmarkConfig.new_from(
            config_source,
            protocol=protocol,
            duration=duration,
            window=window,
            client_affinity=client_affinity,
            message_size_bytes=effective_message_size,
            bandwidth_target_bps=bitrate,
            run_id=run_id,
        )

    def _protocol_name(self) -> str:
        protocol = str(self.PROTOCOL).lower()
        if protocol not in {"tcp", "udp"}:
            raise ValueError("Iperf3SweepBase requires PROTOCOL to be set to 'tcp' or 'udp' by a subclass")
        return protocol

    def _sweep_values(self, cfg_field: str, transform=None):
        values = getattr(self._cfg, cfg_field, None) or IPERF3_SWEEP_DEFAULT_CONFIG[cfg_field]
        if transform is None:
            return tuple(values)
        return tuple(transform(x) for x in values)

    def _build_sweep_config(self) -> Iperf3SweepConfig:
        protocol = self._protocol_name()
        durations = self._sweep_values("duration_sweep_steps")
        windows = self._sweep_values(
            "window_sweep_steps",
            transform=lambda x: None if str(x).lower() in ("", "none", "default") else str(x),
        )
        # None/default omits iperf3 -b; explicit targets apply to both TCP and UDP.
        bandwidth_targets = self._sweep_values(
            "bandwidth_target_bps_sweep_steps",
            transform=lambda target: None if target is None else int(target),
        )
        return Iperf3SweepConfig(
            protocol=protocol,
            durations=durations,
            windows=windows,
            client_affinities=self._client_affinity_sweep_values(),
            message_sizes=self._sweep_values("message_size_sweep_steps", transform=int),
            bandwidth_targets=bandwidth_targets,
        )

    def _client_affinity_sweep_values(self) -> tuple[int | None, ...]:
        configured = getattr(self._cfg, "client_affinities", None)
        if configured is None:
            return (None,)
        if isinstance(configured, list) and len(configured) == 0:
            return (None,)
        if isinstance(configured, list):
            return tuple(int(x) for x in configured)
        return (int(configured),)

    def gen_steps(self):
        self._sweep_config = self._build_sweep_config()
        sweep_steps = list(
            product(
                [self._sweep_config.protocol],
                self._sweep_config.durations,
                self._sweep_config.windows,
                self._sweep_config.client_affinities,
                self._sweep_config.message_sizes,
                self._sweep_config.bandwidth_targets,
            )
        )
        return [
            (*step, run_index)
            for run_index in range(1, int(IPERF3_SWEEP_DEFAULT_CONFIG["number_of_runs"]) + 1)
            for step in sweep_steps
        ]

    def get_step_desc(self, step):
        protocol, duration, window, client_affinity, message_size, bitrate, run_index = step
        return (
            f"run={run_index} protocol={protocol} duration={duration}s "
            f"window={window} client_affinity={client_affinity} size={message_size}B bitrate={bitrate}"
        )

    def one_step(self, step):
        protocol, duration, _, client_affinity, _, bitrate, run_index = step
        if self.rows:
            time.sleep(self.INTER_STEP_BUFFER_S)

        cfg = self._step_config(step, step_sequence=len(self.rows) + 1)
        spec = Iperf3BenchSpec(cfg, self.benchmark_binary)
        runner = br.SyncRunner(cwd=self.results_dir)

        try:
            result = runner.run_and_collect_results(spec)
        except RuntimeError as exc:
            result = spec.process_output(runner)
            run = result.runs[0]
            if run.error is not None:
                error_text = (runner.stderr or str(exc)).strip()
                if error_text and (not run.error.message or run.error.message == "Failed to parse iperf3 JSON output."):
                    run.error.message = error_text

        run = result.runs[0]

        iperf3_version = run.setup.tool_version or getattr(run.tool_data, "version", None)
        if iperf3_version and "iperf3_version" not in self.result_metadata:
            self.result_metadata["iperf3_version"] = iperf3_version

        row = run.flat_summary()
        row.update({
            "run_index": run_index,
            "protocol": protocol,
            "duration_s": duration,
            "window": cfg.window,
            "client_affinity": client_affinity,
            "message_size_bytes": cfg.message_size_bytes,
            "bandwidth_target_bps": bitrate,
        })
        self.rows.append(row)

    @property
    def results_desc(self):
        server_affinity = getattr(self._cfg, "server_affinity", None)
        affinity_text = "default" if server_affinity is None else str(server_affinity)
        configured = self._configured_server_host()
        server_text = configured if configured is not None else "default"
        return (
            f"iperf3 networking sweep results: server={server_text}:{self._cfg.port}, server_affinity={affinity_text}"
        )

    @staticmethod
    def _drop_all_empty_columns(df: pd.DataFrame):
        if df.empty:
            return df
        return df.dropna(axis="columns", how="all")

    def _stdout_df(self, verbose: bool = False):
        df = self.get_results_df()
        if df.empty:
            return df

        output_level = DisplayLevel.VERBOSE if verbose else DisplayLevel.BASIC
        if verbose:
            display_df = df.copy()
            for column_name in ("tool", "server_host", "port"):
                if column_name in display_df.columns and display_df[column_name].nunique(dropna=False) <= 1:
                    display_df = display_df.drop(columns=[column_name])
        else:
            display_df = df

        # Keep run parameters visible in both modes and select outputs by requested level.
        summary_columns = [
            field.column_name
            for field in self.INPUT_DISPLAY_FIELDS
            if (field.display_level & DisplayLevel.BASIC) and field.column_name in display_df.columns
        ]
        summary_columns.extend(
            field.column_name
            for field in self.OUTPUT_DISPLAY_FIELDS
            if (field.display_level & output_level) and field.column_name in display_df.columns
        )
        display_df = display_df.loc[:, [col for col in self.RESULT_COLUMN_ORDER if col in summary_columns]].copy()
        if not verbose:
            required_columns = [
                col
                for col in ("sender_mbps", "receiver_mbps", "sender_cpu_total_pct", "receiver_cpu_total_pct")
                if col in display_df.columns
            ]
            if required_columns:
                display_df = display_df.dropna(subset=required_columns, how="any")
        return self._drop_all_empty_columns(display_df)

    def _config_values(self):
        configured_server_host = self._configured_server_host()
        sweep_config = self._sweep_config or self._build_sweep_config()
        tool_version = getattr(Iperf3(), "version", None)
        if not tool_version:
            tool_version = "unknown"
        return {
            "iperf3_version": str(tool_version),
            "client_affinities": ", ".join(
                "default" if affinity is None else str(affinity) for affinity in sweep_config.client_affinities
            ),
            "protocols": sweep_config.protocol,
            "durations": ", ".join(f"{duration}s" for duration in sweep_config.durations),
            "windows": ", ".join("default" if window is None else str(window) for window in sweep_config.windows),
            "message_sizes": ", ".join(f"{size}B" for size in sweep_config.message_sizes),
            "bandwidth_targets": ", ".join(
                "default" if bitrate is None else str(bitrate) for bitrate in sweep_config.bandwidth_targets
            ),
            "number_of_runs": str(int(IPERF3_SWEEP_DEFAULT_CONFIG["number_of_runs"])),
            "manage_local_server": str(configured_server_host is None),
            "inter_step_buffer": f"{self.INTER_STEP_BUFFER_S:.1f}s",
        }

    def _config_lines(self, verbose: bool = False):
        config_level = DisplayLevel.VERBOSE if verbose else DisplayLevel.BASIC
        config_values = self._config_values()
        return [
            (field.label, config_values[field.key])
            for field in self.CONFIG_DISPLAY_FIELDS
            if (field.display_level & config_level) and field.key in config_values
        ]

    def _stdout_text(self, verbose: bool = False) -> str:
        display_df = self._stdout_df(verbose=verbose)
        config_lines = [f"{label}: {value}" for label, value in self._config_lines(verbose=verbose)]

        lines = [
            "",
            "iperf3 sweep configuration",
            "-" * len("iperf3 sweep configuration"),
            *config_lines,
            "",
            self.result.desc,
            "-" * len(self.result.desc),
            display_df.to_string(index=self.print_index, float_format=lambda x: f"{x:.1f}", na_rep="-"),
            "",
        ]
        return "\n".join(lines)

    def to_stdout(self):
        print(self._stdout_text(verbose=False), end="")

    def to_stdout_verbose(self):
        print(self._stdout_text(verbose=True), end="")

    @property
    def dev_mode_data_df(self):
        return pd.DataFrame([
            {
                "run_index": 1,
                "protocol": "tcp",
                "duration_s": 5.0,
                "message_size_bytes": 131072,
                "bandwidth_target_bps": 0,
                "sender_mbps": 9500.0,
                "receiver_mbps": 9450.0,
                "status": "success",
            }
        ])

    def get_results_df(self):
        df = pd.DataFrame(self.rows)
        if df.empty:
            return df
        ordered_columns = [column for column in self.RESULT_COLUMN_ORDER if column in df.columns]
        ordered_columns.extend(column for column in df.columns if column not in ordered_columns)
        return self._drop_all_empty_columns(df.reindex(columns=ordered_columns))

    def get_results(self):
        return Result(desc=self.results_desc, dataframe=self.get_results_df())


class Iperf3TcpSweep(Iperf3SweepBase):
    RECIPE_NAME: ClassVar[str] = "iperf3_tcp_sweep"
    PROTOCOL: ClassVar[str] = "tcp"
    INPUT_DISPLAY_FIELDS: ClassVar[list[InputDisplayField]] = [
        field for field in Iperf3SweepBase.INPUT_DISPLAY_FIELDS if field.column_name != "protocol"
    ]


class Iperf3UdpSweep(Iperf3SweepBase):
    RECIPE_NAME: ClassVar[str] = "iperf3_udp_sweep"
    PROTOCOL: ClassVar[str] = "udp"
    INPUT_DISPLAY_FIELDS: ClassVar[list[InputDisplayField]] = [
        field for field in Iperf3SweepBase.INPUT_DISPLAY_FIELDS if field.column_name != "protocol"
    ]
