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

"""Minimal iperf3 JSON parser for the experimental iperf3 recipe."""

from __future__ import annotations

from dataclasses import replace
import json

from asct.lib.networking.benchmark_model import (
    BenchmarkError,
    BenchmarkParser,
    BenchmarkRun,
    CpuUtilizationMetrics,
    Iperf3Data,
    MeasurementSet,
    NetworkBenchmarkParams,
    RunStatus,
    ThroughputMetrics,
    ToolSpecificData,
)


class Iperf3Parser(BenchmarkParser):
    PARSE_ERROR_MESSAGE = "Failed to parse iperf3 JSON output."

    @staticmethod
    def _compact_error_message(message: str | None, max_len: int = 140) -> str | None:
        if message is None:
            return None
        text = str(message).strip()
        if not text:
            return None

        first_line = next((line.strip() for line in text.splitlines() if line.strip()), text)
        if len(first_line) <= max_len:
            return first_line
        return f"{first_line[: max_len - 3].rstrip()}..."

    @staticmethod
    def _safe_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _get_dict(parent: dict[str, object], key: str) -> dict[str, object]:
        value = parent.get(key, {})
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _parse_json_object(raw_stdout: str) -> tuple[dict[str, object] | None, str | None]:
        try:
            result_json = json.loads(raw_stdout)
        except json.JSONDecodeError as exc:
            return None, str(exc)

        if not isinstance(result_json, dict):
            return None, "iperf3 JSON output was not an object."

        return result_json, None

    def parse(
        self,
        *,
        raw_stdout: str,
        raw_stderr: str,
        setup: NetworkBenchmarkParams,
        retcode: int | None = None,
    ) -> BenchmarkRun:
        def build_error(message: str) -> BenchmarkError:
            return BenchmarkError(
                message=message,
                retcode=retcode,
                stdout=raw_stdout,
                stderr=raw_stderr,
            )

        result_json, parse_error = self._parse_json_object(raw_stdout)
        # Start as error; switch to success only after validation.
        status = RunStatus.ERROR
        run_setup = setup
        measurements = MeasurementSet()
        error_message = self._compact_error_message(raw_stderr) or self.PARSE_ERROR_MESSAGE
        error = build_error(error_message)
        notes = [error_message]
        tool_data = ToolSpecificData(
            tool=setup.tool,
            raw_output=raw_stdout,
            parsed_extra={"parse_error": parse_error} if parse_error else {},
        )

        if result_json is not None:
            start_block = self._get_dict(result_json, "start")
            end_block = self._get_dict(result_json, "end")
            parsed_version = result_json.get("version") or start_block.get("version")
            run_setup = replace(setup, tool_version=parsed_version)
            tool_data = Iperf3Data(
                raw_output=raw_stdout,
                raw_json=result_json,
                version=parsed_version,
                test_start_block=start_block,
                test_end_block=end_block,
            )

            iperf_error = result_json.get("error")
            if isinstance(iperf_error, str) and iperf_error.strip():
                status = RunStatus.ERROR
                error_message = self._compact_error_message(iperf_error) or self.PARSE_ERROR_MESSAGE
                error = build_error(error_message)
                notes = [error_message]
            else:
                status = RunStatus.SUCCESS
                error = None
                notes = []
                sum_sent = self._get_dict(end_block, "sum_sent")
                sum_received = self._get_dict(end_block, "sum_received")
                cpu_block = self._get_dict(end_block, "cpu_utilization_percent")

                sender_bps = self._safe_float(sum_sent.get("bits_per_second"))
                receiver_bps = self._safe_float(sum_received.get("bits_per_second"))
                measurements = MeasurementSet(
                    throughput=ThroughputMetrics(
                        sender_bps=sender_bps,
                        receiver_bps=receiver_bps,
                        sender_mbps=sender_bps / 1e6 if sender_bps is not None else None,
                        receiver_mbps=receiver_bps / 1e6 if receiver_bps is not None else None,
                    ),
                    cpu_utilization=CpuUtilizationMetrics(
                        sender_total_pct=self._safe_float(cpu_block.get("host_total")),
                        sender_user_pct=self._safe_float(cpu_block.get("host_user")),
                        sender_system_pct=self._safe_float(cpu_block.get("host_system")),
                        receiver_total_pct=self._safe_float(cpu_block.get("remote_total")),
                        receiver_user_pct=self._safe_float(cpu_block.get("remote_user")),
                        receiver_system_pct=self._safe_float(cpu_block.get("remote_system")),
                    ),
                )

        return BenchmarkRun(
            status=status,
            setup=run_setup,
            measurements=measurements,
            error=error,
            tool_data=tool_data,
            notes=notes,
        )
