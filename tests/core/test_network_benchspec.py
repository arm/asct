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

import json
from pathlib import Path

import pytest

from asct.core.asct_env import ASCTGlobalSettings
from asct.core.benchrunner import Runner
from asct.core.benchspec.network_benchspec import (
    Iperf3BenchSpec,
    Iperf3ServerSpec,
    NetworkingBenchmarkConfig,
)
from asct.core.resources import network_resources as network_resources_mod
from asct.core.resources.network_resources import Iperf3Server, Iperf3ServerConfig


IPERF3_LOCAL_TEST_PORT = 25201


class _RunnerResult:
    def __init__(self, stdout, stderr="", retcode=0, cwd=None):
        self.stdout = stdout
        self.stderr = stderr
        self.retcode = retcode
        self.cwd = cwd


def _patch_server_resource_setup_success(monkeypatch, *, local_host_predicate=None):
    def noop_setup(_resource):
        return True

    class FakeRunner:
        def __init__(self, cwd=None, suppress_output=False):
            self.cwd = cwd
            self.suppress_output = suppress_output
            self.retcode = None
            self.stderr = ""

        def run(self, _spec):
            return None

    def port_is_available(_host, **_kwargs):
        return True

    if local_host_predicate is not None:
        monkeypatch.setattr(network_resources_mod, "is_local_host", local_host_predicate)

    monkeypatch.setattr(network_resources_mod.Iperf3, "setup", noop_setup)
    monkeypatch.setattr(network_resources_mod, "check_port_available", port_is_available)
    monkeypatch.setattr(network_resources_mod, "AsyncRunner", FakeRunner)


def test_iperf3_benchspec_builds_client_command():
    config = NetworkingBenchmarkConfig(
        server_host="192.0.2.5",
        port=5300,
        protocol="tcp",
        duration=3,
        client_affinity=1,
        message_size_bytes=2048,
        bandwidth_target_bps=25000000,
        window="256K",
        extra_args=["--forceflush"],
    )

    spec = Iperf3BenchSpec(config)

    assert spec.make_cmd() == [
        "iperf3",
        "--client",
        "192.0.2.5",
        "--port",
        "5300",
        "--json",
        "--logfile",
        "iperf3-output.json",
        "--affinity",
        "1",
        "--time",
        "3",
        "--length",
        "2048",
        "-b",
        "25000000",
        "--window",
        "256K",
        "--forceflush",
    ]


def test_iperf3_benchspec_builds_client_command_with_timestamp_format():
    spec = Iperf3BenchSpec(
        NetworkingBenchmarkConfig(
            server_host="192.0.2.5",
        )
    )

    assert spec.make_cmd() == [
        "iperf3",
        "--client",
        "192.0.2.5",
        "--port",
        "5201",
        "--json",
        "--logfile",
        "iperf3-output.json",
    ]


def test_iperf3_benchspec_normalizes_integer_duration_string():
    spec = Iperf3BenchSpec(
        NetworkingBenchmarkConfig(
            server_host="192.0.2.5",
            duration="3",
        )
    )

    cmd = spec.make_cmd()
    setup = spec.build_setup(cmd)

    assert cmd[-2:] == ["--time", "3"]
    assert setup.duration_s == 3
    assert isinstance(setup.duration_s, int)


def test_network_benchmark_config_keeps_quick_mode_duration_as_whole_seconds(monkeypatch):
    monkeypatch.setattr(ASCTGlobalSettings(), "quick_mode", lambda: True)

    config = NetworkingBenchmarkConfig(duration=250)

    assert config.duration == 2
    assert isinstance(config.duration, int)


def test_network_benchmark_config_keeps_quick_mode_duration_above_zero(monkeypatch):
    monkeypatch.setattr(ASCTGlobalSettings(), "quick_mode", lambda: True)

    spec = Iperf3BenchSpec(
        NetworkingBenchmarkConfig(
            server_host="192.0.2.5",
            duration=10,
        )
    )

    cmd = spec.make_cmd()
    setup = spec.build_setup(cmd)

    assert cmd[-2:] == ["--time", "1"]
    assert setup.duration_s == 1
    assert isinstance(setup.duration_s, int)


@pytest.mark.parametrize("duration", [0, "0", 0.5, "3.5", True])
def test_iperf3_benchspec_rejects_bad_time_arg_duration(duration):
    with pytest.raises((TypeError, ValueError), match=r"integer|at least 1 second"):
        Iperf3BenchSpec(
            NetworkingBenchmarkConfig(
                server_host="192.0.2.5",
                duration=duration,
            )
        )


@pytest.mark.parametrize("bad_port", [0, 80, 70000, "bad-port"])
def test_iperf3_benchspec_rejects_bad_port(bad_port):
    with pytest.raises(ValueError, match="invalid port"):
        Iperf3BenchSpec(
            NetworkingBenchmarkConfig(
                server_host="192.0.2.5",
                port=bad_port,
            )
        )


def test_iperf3_benchspec_builds_udp_client_command():
    spec = Iperf3BenchSpec(
        NetworkingBenchmarkConfig(
            server_host="192.0.2.5",
            protocol="udp",
            bandwidth_target_bps=25000000,
        )
    )

    assert spec.make_cmd() == [
        "iperf3",
        "--client",
        "192.0.2.5",
        "--port",
        "5201",
        "--json",
        "--logfile",
        "iperf3-output.json",
        "--udp",
        "-b",
        "25000000",
    ]


def test_iperf3_benchspec_processes_output_into_benchmark_run(tmp_path):
    config = NetworkingBenchmarkConfig(server_host="198.51.100.9", duration=5, run_id="run-1")
    spec = Iperf3BenchSpec(config)
    output = json.dumps({
        "version": "3.17.1",
        "start": {},
        "end": {
            "sum_sent": {"bits_per_second": 64000000},
            "sum_received": {"bits_per_second": 62000000},
        },
    })
    logfile = Path(tmp_path) / "run-1.iperf3.json"
    logfile.write_text(output, encoding="utf-8")

    result = spec.process_output(_RunnerResult(stdout="", cwd=str(tmp_path)))
    result_df = result.to_dataframe()

    assert (
        result.to_dict()["runs"][0]["setup"]["command"]
        == "iperf3 --client 198.51.100.9 --port 5201 --json --logfile run-1.iperf3.json --time 5"
    )
    assert result.runs[0].measurements.throughput.sender_mbps == pytest.approx(64.0)
    assert result.runs[0].setup.path.server_host.ip == "198.51.100.9"
    assert result.runs[0].notes == []
    assert result_df.loc[0, "sender_mbps"] == pytest.approx(64.0)
    assert result_df.loc[0, "server_host"] == "198.51.100.9"


def test_iperf3_benchspec_json_error_is_reported_as_run_error(tmp_path):
    config = NetworkingBenchmarkConfig(server_host="198.51.100.9", run_id="run-err")
    spec = Iperf3BenchSpec(config)
    output = json.dumps({
        "version": "3.16",
        "start": {},
        "end": {},
        "error": "socket buffer size not set correctly",
    })
    logfile = Path(tmp_path) / "run-err.iperf3.json"
    logfile.write_text(output, encoding="utf-8")

    result = spec.process_output(_RunnerResult(stdout="", cwd=str(tmp_path)))
    run = result.runs[0]

    assert run.status.value == "error"
    assert run.error is not None
    assert run.error.message == "socket buffer size not set correctly"


def test_iperf3_benchspec_stderr_timeout_is_forwarded_as_error_message():
    config = NetworkingBenchmarkConfig(server_host="198.51.100.9")
    spec = Iperf3BenchSpec(config)
    result = spec.process_output(
        _RunnerResult(
            stdout="",
            stderr="control socket has closed unexpectedly\niperf3: error - unable to connect to server",
            retcode=1,
        )
    )
    run = result.runs[0]

    assert run.status.value == "error"
    assert run.error is not None
    assert run.error.message == "control socket has closed unexpectedly"


def test_iperf3_benchspec_check_output_accepts_json_logfile_without_stdout(tmp_path):
    spec = Iperf3BenchSpec(NetworkingBenchmarkConfig(server_host="198.51.100.9", run_id="run-2"))
    logfile = Path(tmp_path) / "run-2.iperf3.json"
    logfile.write_text("{}", encoding="utf-8")

    spec.check_output(_RunnerResult(stdout="", cwd=str(tmp_path)))


def test_iperf3_server_benchspec_builds_server_command():
    spec = Iperf3ServerSpec(
        config=NetworkingBenchmarkConfig(
            port=IPERF3_LOCAL_TEST_PORT,
            network_namespace="ns1",
            server_affinity=2,
            extra_args=["--verbose"],
        )
    )

    assert spec.make_cmd() == [
        "ip",
        "netns",
        "exec",
        "ns1",
        "iperf3",
        "--server",
        "--port",
        str(IPERF3_LOCAL_TEST_PORT),
        "--affinity",
        "2",
        "--verbose",
    ]


def test_iperf3_benchspec_rejects_udp_only_invalid_tcp_options():
    spec = Iperf3BenchSpec(
        NetworkingBenchmarkConfig(
            server_host="192.0.2.5",
            protocol="udp",
            zerocopy=True,
        )
    )

    with pytest.raises(ValueError, match="zerocopy"):
        spec.make_cmd()


def test_iperf3_benchspec_rejects_reverse_and_bidirectional():
    spec = Iperf3BenchSpec(
        NetworkingBenchmarkConfig(
            server_host="192.0.2.5",
            reverse=True,
            bidirectional=True,
        )
    )

    with pytest.raises(ValueError, match="reverse and bidirectional"):
        spec.make_cmd()


def test_iperf3_benchspec_uses_client_affinity():
    spec = Iperf3BenchSpec(NetworkingBenchmarkConfig(server_host="198.51.100.10", client_affinity=5))

    assert spec.make_cmd() == [
        "iperf3",
        "--client",
        "198.51.100.10",
        "--port",
        "5201",
        "--json",
        "--logfile",
        "iperf3-output.json",
        "--affinity",
        "5",
    ]


def test_iperf3_benchspec_keeps_client_affinity_zero():
    spec = Iperf3BenchSpec(NetworkingBenchmarkConfig(server_host="198.51.100.10", client_affinity=0))

    assert spec.make_cmd() == [
        "iperf3",
        "--client",
        "198.51.100.10",
        "--port",
        "5201",
        "--json",
        "--logfile",
        "iperf3-output.json",
        "--affinity",
        "0",
    ]


def test_iperf3_benchspec_uses_combined_client_and_server_affinity():
    spec = Iperf3BenchSpec(
        NetworkingBenchmarkConfig(
            server_host="198.51.100.10",
            client_affinity=4,
            server_affinity=7,
        )
    )

    assert spec.make_cmd() == [
        "iperf3",
        "--client",
        "198.51.100.10",
        "--port",
        "5201",
        "--json",
        "--logfile",
        "iperf3-output.json",
        "--affinity",
        "4,7",
    ]


def test_iperf3_server_benchspec_keeps_server_affinity_zero():
    spec = Iperf3ServerSpec(config=NetworkingBenchmarkConfig(port=IPERF3_LOCAL_TEST_PORT, server_affinity=0))

    assert spec.make_cmd() == [
        "iperf3",
        "--server",
        "--port",
        str(IPERF3_LOCAL_TEST_PORT),
        "--affinity",
        "0",
    ]


def test_iperf3_server_benchspec_omits_port_flag_when_port_not_set():
    spec = Iperf3ServerSpec(config=NetworkingBenchmarkConfig(server_affinity=0))

    assert spec.make_cmd() == [
        "iperf3",
        "--server",
        "--affinity",
        "0",
    ]


def test_iperf3_server_benchspec_can_explicitly_use_default_port_flag():
    spec = Iperf3ServerSpec(config=NetworkingBenchmarkConfig(port=5201))

    assert spec.make_cmd() == [
        "iperf3",
        "--server",
        "--port",
        "5201",
    ]


def test_iperf3_benchspec_nonzero_runner_exit_raises_before_parse(monkeypatch):
    class _FailingRunner(Runner):
        def __init__(self):
            super().__init__(cwd=None)

        def run(self, _bmk_spec):
            self._stdout = '{"end": {"sum_sent": {"bits_per_second": 1}}}'
            self._stderr = "boom"
            self._retcode = 1
            return self

    spec = Iperf3BenchSpec(NetworkingBenchmarkConfig(server_host="198.51.100.9"))
    parse_calls = {"count": 0}

    def fail_if_called(**_kwargs):
        parse_calls["count"] += 1
        raise AssertionError("parser should not be called on non-zero runner exit")

    monkeypatch.setattr(spec.parser, "parse", fail_if_called)

    with pytest.raises(RuntimeError, match="Failed running benchmark command"):
        _FailingRunner().run_and_collect_results(spec)

    assert parse_calls["count"] == 0


@pytest.mark.parametrize(
    ("remote_host", "local_host_predicate"),
    [
        ("localhost", None),
        ("10.0.0.10", lambda host: str(host).strip() == "10.0.0.10"),
    ],
)
def test_iperf3_server_resource_allows_local_targets(monkeypatch, tmp_path, remote_host, local_host_predicate):
    _patch_server_resource_setup_success(monkeypatch, local_host_predicate=local_host_predicate)

    resource = Iperf3Server(Iperf3ServerConfig(remote_host=remote_host, cwd=str(tmp_path)))

    assert resource.setup() is True


def test_iperf3_server_resource_rejects_nonlocal_remote_host():
    resource = Iperf3Server(Iperf3ServerConfig(remote_host="198.51.100.10"))

    with pytest.raises(NotImplementedError, match="Remote iperf3 server management"):
        resource.setup()
