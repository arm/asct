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

import ipaddress
import logging
import subprocess
from types import SimpleNamespace

from asct.core.recipes.configuration.metadata import get_recipe
from asct.core.recipes.impl import iperf3 as iperf3_mod
from asct.core.recipes.impl.iperf3 import DisplayLevel, Iperf3TcpSweep, Iperf3UdpSweep
from asct.core.recipes import recipe_benchmark_base
from asct.core.resources import network_resources as network_resources_mod
from asct.core.resources.network_resources import Iperf3, Iperf3Server, Iperf3ServerConfig
import pytest


def _port_is_available(*_args, **_kwargs):
    return True


def _port_is_unavailable(*_args, **_kwargs):
    return False


def test_iperf3_check_version_warns_below_minimum(caplog):
    resource = Iperf3()
    resource.version = "iperf 2.9"

    caplog.set_level(logging.WARNING, logger="ASCT")

    resource.check_version()

    assert "older than ASCT's oldest supported version" in caplog.text
    assert network_resources_mod.IPERF3_MIN_VERSION in caplog.text

    resource.version = None


def _patch_reporter_output_dir(monkeypatch, output_dir=None):
    if output_dir is None:
        output_dir = "."

    def fake_get_reporter():
        return SimpleNamespace(output_dir=output_dir)

    monkeypatch.setattr(
        recipe_benchmark_base.ub_rep,
        "get_reporter",
        fake_get_reporter,
    )


def test_iperf3_server_resource_startup_with_config(monkeypatch, tmp_path):
    captured = {}

    def noop_setup(_resource):
        return True

    class FakeRunner:
        def __init__(self, cwd=None, suppress_output=False):
            self.cwd = cwd
            self.suppress_output = suppress_output
            self.retcode = None
            self.stderr = ""

        def run(self, spec):
            captured["command"] = spec.make_cmd()

    monkeypatch.setattr(network_resources_mod.Iperf3, "setup", noop_setup)
    monkeypatch.setattr(
        network_resources_mod.Iperf3Server,
        "_is_requested_port_available",
        lambda _self, _requested_port: True,
    )
    monkeypatch.setattr(network_resources_mod, "AsyncRunner", FakeRunner)

    resource = Iperf3Server(
        Iperf3ServerConfig(
            port=5301,
            affinity="2",
            extra_args=["--verbose"],
            cwd=str(tmp_path),
            remote_host="127.0.0.1",
        )
    )

    assert resource.setup() is True
    assert captured["command"] == [
        "iperf3",
        "--server",
        "--port",
        "5301",
        "--affinity",
        "2",
        "--verbose",
    ]


def test_iperf3_server_config_normalizes_values():
    cfg = Iperf3ServerConfig(
        port="5301",
        affinity="2",
        extra_args=("--verbose", 3),
        cwd=123,
        remote_host=ipaddress.IPv4Address("127.0.0.1"),
    )

    assert cfg.port == 5301
    assert cfg.namespace is None
    assert cfg.affinity == 2
    assert cfg.extra_args == ["--verbose", "3"]
    assert cfg.cwd == "123"
    assert cfg.remote_host == "127.0.0.1"


def test_iperf3_server_config_rejects_namespace_for_now():
    with pytest.raises(NotImplementedError, match="Network namespaces are not supported"):
        Iperf3ServerConfig(namespace="ns1")


def test_iperf3_server_resource_teardown_stops_owned_server(monkeypatch, tmp_path):
    stop_calls = []

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

        def stop(self, use_int=False):
            stop_calls.append(use_int)

    monkeypatch.setattr(network_resources_mod.Iperf3, "setup", noop_setup)
    monkeypatch.setattr(
        network_resources_mod.Iperf3Server,
        "_is_requested_port_available",
        lambda _self, _requested_port: True,
    )
    monkeypatch.setattr(network_resources_mod, "AsyncRunner", FakeRunner)

    resource = Iperf3Server(Iperf3ServerConfig(port=5301, cwd=str(tmp_path), remote_host="127.0.0.1"))

    assert resource.setup() is True
    assert resource.applied is True
    assert resource._owns_server is True

    resource.teardown()

    assert stop_calls == [True]
    assert resource._runner is None
    assert resource._owns_server is False
    assert resource.applied is False


def test_iperf3_server_resource_reuses_existing_default_server(monkeypatch, tmp_path):
    def noop_setup(_resource):
        return True

    class FakeRunner:
        def __init__(self, cwd=None, suppress_output=False):
            self.cwd = cwd
            self.suppress_output = suppress_output
            self.retcode = None
            self.stderr = ""

        def run(self, _spec):
            raise AssertionError("run should not be called when reusing existing server")

    monkeypatch.setattr(network_resources_mod.Iperf3, "setup", noop_setup)
    monkeypatch.setattr(
        network_resources_mod.Iperf3Server,
        "_is_requested_port_available",
        lambda _self, _requested_port: False,
    )
    monkeypatch.setattr(network_resources_mod.Iperf3Server, "_has_existing_local_iperf3_server", lambda _self: True)
    monkeypatch.setattr(
        network_resources_mod.Iperf3Server,
        "_existing_server_matches_requested_config",
        lambda _self: True,
    )
    monkeypatch.setattr(network_resources_mod, "AsyncRunner", FakeRunner)

    resource = Iperf3Server(Iperf3ServerConfig(port=5301, cwd=str(tmp_path), remote_host="127.0.0.1"))

    assert resource.setup() is True
    assert resource.applied is True
    assert resource._runner is None

    # Reused listener is external; teardown must not attempt to stop it.
    resource.teardown()
    assert resource.applied is False


def test_iperf3_server_resource_rejects_reuse_with_explicit_server_settings(monkeypatch, tmp_path):
    def noop_setup(_resource):
        return True

    monkeypatch.setattr(network_resources_mod.Iperf3, "setup", noop_setup)
    monkeypatch.setattr(
        network_resources_mod.Iperf3Server,
        "_is_requested_port_available",
        lambda _self, _requested_port: False,
    )
    monkeypatch.setattr(network_resources_mod.Iperf3Server, "_has_existing_local_iperf3_server", lambda _self: True)
    monkeypatch.setattr(
        network_resources_mod.Iperf3Server,
        "_existing_server_matches_requested_config",
        lambda _self: False,
    )

    resource = Iperf3Server(Iperf3ServerConfig(port=5301, affinity=2, cwd=str(tmp_path), remote_host="127.0.0.1"))

    with pytest.raises(RuntimeError, match="reuse is unsupported"):
        resource.setup()


def test_iperf3_server_resource_rejects_reuse_when_existing_settings_do_not_match_defaults(monkeypatch, tmp_path):
    def noop_setup(_resource):
        return True

    monkeypatch.setattr(network_resources_mod.Iperf3, "setup", noop_setup)
    monkeypatch.setattr(
        network_resources_mod.Iperf3Server,
        "_is_requested_port_available",
        lambda _self, _requested_port: False,
    )
    monkeypatch.setattr(network_resources_mod.Iperf3Server, "_has_existing_local_iperf3_server", lambda _self: True)
    monkeypatch.setattr(
        network_resources_mod.Iperf3Server,
        "_existing_server_matches_requested_config",
        lambda _self: False,
    )

    resource = Iperf3Server(Iperf3ServerConfig(port=5301, cwd=str(tmp_path), remote_host="127.0.0.1"))

    with pytest.raises(RuntimeError, match="reuse is unsupported"):
        resource.setup()


def test_iperf3_server_resource_reuses_existing_matching_server_with_explicit_settings(monkeypatch, tmp_path):
    def noop_setup(_resource):
        return True

    monkeypatch.setattr(network_resources_mod.Iperf3, "setup", noop_setup)
    monkeypatch.setattr(
        network_resources_mod.Iperf3Server,
        "_is_requested_port_available",
        lambda _self, _requested_port: False,
    )
    monkeypatch.setattr(network_resources_mod.Iperf3Server, "_has_existing_local_iperf3_server", lambda _self: True)
    monkeypatch.setattr(
        network_resources_mod.Iperf3Server,
        "_existing_server_matches_requested_config",
        lambda _self: True,
    )

    resource = Iperf3Server(Iperf3ServerConfig(port=5301, affinity=2, cwd=str(tmp_path), remote_host="127.0.0.1"))

    assert resource.setup() is True
    assert resource.applied is True
    assert resource._runner is None


def test_iperf3_server_resource_reports_busy_non_iperf_port(monkeypatch, tmp_path):
    def noop_setup(_resource):
        return True

    monkeypatch.setattr(network_resources_mod.Iperf3, "setup", noop_setup)
    monkeypatch.setattr(
        network_resources_mod.Iperf3Server,
        "_is_requested_port_available",
        lambda _self, _requested_port: False,
    )
    monkeypatch.setattr(network_resources_mod.Iperf3Server, "_has_existing_local_iperf3_server", lambda _self: False)

    resource = Iperf3Server(Iperf3ServerConfig(port=5301, cwd=str(tmp_path), remote_host="127.0.0.1"))

    with pytest.raises(RuntimeError, match="already in use"):
        resource.setup()


def test_iperf3_server_resource_uses_default_wildcard_probe_and_server_cmd(monkeypatch, tmp_path):
    captured = {"check_host": None, "cmd": None}

    def noop_setup(_resource):
        return True

    class FakeRunner:
        def __init__(self, cwd=None, suppress_output=False):
            self.cwd = cwd
            self.suppress_output = suppress_output
            self.retcode = None
            self.stderr = ""

        def run(self, spec):
            captured["cmd"] = spec.make_cmd()

    def fake_check_port_available(host, **_kwargs):
        captured["check_host"] = host
        return True

    monkeypatch.setattr(network_resources_mod.Iperf3, "setup", noop_setup)
    monkeypatch.setattr(
        network_resources_mod,
        "is_local_host",
        lambda host: str(host).strip().lower() in {"localhost", "127.0.0.1"},
    )
    monkeypatch.setattr(network_resources_mod, "check_port_available", fake_check_port_available)
    monkeypatch.setattr(network_resources_mod, "AsyncRunner", FakeRunner)

    resource = Iperf3Server(Iperf3ServerConfig(port=5301, cwd=str(tmp_path), remote_host="localhost"))

    assert resource.setup() is True
    expected_probe_host = str(ipaddress.IPv4Address(0))
    assert captured["check_host"] == expected_probe_host
    assert captured["cmd"] == [
        "iperf3",
        "--server",
        "--port",
        "5301",
    ]


@pytest.mark.parametrize("bad_port", [0, 80, 70000, "bad-port"])
def test_iperf3_server_config_rejects_invalid_port(bad_port):
    with pytest.raises(ValueError, match="invalid port"):
        Iperf3ServerConfig(port=bad_port)


def test_iperf3_server_resource_preserves_unspecified_port():
    resource = Iperf3Server(Iperf3ServerConfig(port=None))

    assert resource.config.port is None


def test_iperf3_server_match_accepts_absolute_or_wrapped_iperf3_command(monkeypatch):
    def fake_run(cmd, text=False, capture_output=False, check=False):
        _ = (text, capture_output, check)
        assert cmd == ["pgrep", "-fa", "iperf3"]
        return SimpleNamespace(
            returncode=0,
            stdout="1234 taskset -c 0 /usr/bin/iperf3 --server --port 5301\n",
            stderr="",
        )

    monkeypatch.setattr(network_resources_mod.subprocess, "run", fake_run)

    resource = Iperf3Server(Iperf3ServerConfig(port=5301))

    assert resource._existing_server_matches_requested_config() is True


def test_iperf3_server_match_allows_requested_affinity_when_server_has_no_affinity(monkeypatch):
    def fake_run(cmd, text=False, capture_output=False, check=False):
        _ = (text, capture_output, check)
        assert cmd == ["pgrep", "-fa", "iperf3"]
        return SimpleNamespace(
            returncode=0,
            stdout="1234 /usr/bin/iperf3 --server --port 5301\n",
            stderr="",
        )

    monkeypatch.setattr(network_resources_mod.subprocess, "run", fake_run)

    resource = Iperf3Server(Iperf3ServerConfig(port=5301, affinity=3))

    assert resource._existing_server_matches_requested_config() is True


def test_iperf3_server_match_accepts_server_affinity_from_combined_affinity_arg(monkeypatch):
    def fake_run(cmd, text=False, capture_output=False, check=False):
        _ = (text, capture_output, check)
        assert cmd == ["pgrep", "-fa", "iperf3"]
        return SimpleNamespace(
            returncode=0,
            stdout="1234 /usr/bin/iperf3 --server --port 5301 --affinity 1,3\n",
            stderr="",
        )

    monkeypatch.setattr(network_resources_mod.subprocess, "run", fake_run)

    resource = Iperf3Server(Iperf3ServerConfig(port=5301, affinity=3))

    assert resource._existing_server_matches_requested_config() is True


def test_iperf3_server_port_probe_uses_standard_port_check(monkeypatch):
    captured = {"check_host": None, "check_port": None}

    def fake_check_port_available(host, **kwargs):
        captured["check_host"] = host
        captured["check_port"] = kwargs.get("port")
        return True

    monkeypatch.setattr(network_resources_mod, "check_port_available", fake_check_port_available)

    resource = Iperf3Server(Iperf3ServerConfig(port=5301))

    assert resource._is_requested_port_available(5301) is True
    expected_probe_host = str(ipaddress.IPv4Address(0))
    assert captured["check_host"] == expected_probe_host
    assert captured["check_port"] == 5301


def test_iperf3_server_setup_uses_standard_port_probe(monkeypatch, tmp_path):
    captured = {"check_host": None, "server_cmd": None}

    def noop_setup(_resource):
        return True

    class FakeRunner:
        def __init__(self, cwd=None, suppress_output=False):
            self.cwd = cwd
            self.suppress_output = suppress_output
            self.retcode = None
            self.stderr = ""

        def run(self, spec):
            captured["server_cmd"] = spec.make_cmd()

    def fake_check_port_available(host, **_kwargs):
        captured["check_host"] = host
        return True

    monkeypatch.setattr(network_resources_mod.Iperf3, "setup", noop_setup)
    monkeypatch.setattr(network_resources_mod, "check_port_available", fake_check_port_available)
    monkeypatch.setattr(network_resources_mod, "AsyncRunner", FakeRunner)

    resource = Iperf3Server(Iperf3ServerConfig(port=5301, cwd=str(tmp_path), remote_host="127.0.0.1"))

    assert resource.setup() is True
    expected_probe_host = str(ipaddress.IPv4Address(0))
    assert captured["check_host"] == expected_probe_host
    assert captured["server_cmd"][:2] == ["iperf3", "--server"]


def test_iperf3_recipe_uses_default_server_target_when_unspecified():
    recipe = Iperf3TcpSweep(get_recipe("iperf3-tcp-sweep"))
    recipe.initialize_config()

    assert recipe.results_desc == "iperf3 networking sweep results: server=default:5202, server_affinity=default"
    assert "server" not in dict(recipe._config_lines())

    step_cfg = recipe._step_config(("tcp", 10, None, None, 131072, None, 1))
    assert step_cfg.server_host == "127.0.0.1"
    assert step_cfg.port == 5202


def test_iperf3_recipe_preserves_explicit_remote_server_target():
    recipe = Iperf3UdpSweep(get_recipe("iperf3-udp-sweep"))
    recipe.initialize_config({"server_host": "198.51.100.9", "port": 5300})

    assert recipe.results_desc == "iperf3 networking sweep results: server=198.51.100.9:5300, server_affinity=default"
    assert "server" not in dict(recipe._config_lines())

    step_cfg = recipe._step_config(("udp", 10, None, None, 131072, 0, 1))
    assert step_cfg.server_host == "198.51.100.9"
    assert step_cfg.port == 5300


def test_iperf3_config_uses_tool_resource_version_fallback(monkeypatch):
    recipe = Iperf3TcpSweep(get_recipe("iperf3-tcp-sweep"))
    recipe.initialize_config()

    monkeypatch.setattr(iperf3_mod.Iperf3(), "version", "iperf 3.19", raising=False)
    recipe.result_metadata.pop("iperf3_version", None)

    config_lines = dict(recipe._config_lines())
    assert config_lines["iperf3 version"] == "iperf 3.19"


def test_iperf3_config_always_uses_tool_resource_version(monkeypatch):
    recipe = Iperf3TcpSweep(get_recipe("iperf3-tcp-sweep"))
    recipe.initialize_config()

    recipe.result_metadata["iperf3_version"] = "iperf 9.99"
    monkeypatch.setattr(iperf3_mod.Iperf3(), "version", "iperf 3.16", raising=False)

    config_lines = dict(recipe._config_lines())
    assert config_lines["iperf3 version"] == "iperf 3.16"


def test_iperf3_resource_version_reads_stderr_when_stdout_empty(monkeypatch):
    resource = Iperf3()

    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["iperf3", "--version"],
            returncode=1,
            stdout="",
            stderr="iperf 3.16 (cJSON 1.7.15)\nLinux host kernel-info",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = resource.get_tool_version()
    assert result.returncode == 0
    assert result.stdout == "iperf 3.16 (cJSON 1.7.15)"


def test_iperf3_resource_version_reads_first_line_from_stdout(monkeypatch):
    resource = Iperf3()

    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["iperf3", "--version"],
            returncode=0,
            stdout="iperf 3.16 (cJSON 1.7.15)\nLinux host kernel-info",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = resource.get_tool_version()
    assert result.returncode == 0
    assert result.stdout == "iperf 3.16 (cJSON 1.7.15)"


@pytest.mark.parametrize("token", ["None", "none", "null", "~", ""])
def test_iperf3_recipe_treats_unset_server_host_tokens_as_local(monkeypatch, token):
    recipe = Iperf3TcpSweep(get_recipe("iperf3-tcp-sweep"))
    recipe.initialize_config({"server_host": token})
    _patch_reporter_output_dir(monkeypatch)
    recipe._pre_setup()

    resources = recipe._create_resources()

    assert any(isinstance(resource, Iperf3Server) for resource in resources)


@pytest.mark.parametrize("server_host", ["localhost", "10.0.0.10", "198.51.100.9"])
def test_iperf3_recipe_treats_explicit_server_target_as_external(monkeypatch, server_host):
    recipe = Iperf3TcpSweep(get_recipe("iperf3-tcp-sweep"))
    recipe.initialize_config({"server_host": server_host})
    _patch_reporter_output_dir(monkeypatch)
    recipe._pre_setup()

    resources = recipe._create_resources()

    assert not any(isinstance(resource, Iperf3Server) for resource in resources)


def test_iperf3_recipe_preserves_explicit_localhost_target():
    recipe = Iperf3TcpSweep(get_recipe("iperf3-tcp-sweep"))
    recipe.initialize_config({"server_host": "localhost"})

    step_cfg = recipe._step_config(("tcp", 10, None, None, 131072, None, 1))
    assert step_cfg.server_host == "localhost"
    assert recipe.results_desc == "iperf3 networking sweep results: server=localhost:5202, server_affinity=default"


def test_iperf3_recipe_rejects_ipv6_server_host():
    recipe = Iperf3TcpSweep(get_recipe("iperf3-tcp-sweep"))
    recipe.initialize_config({"server_host": "::1"})

    with pytest.raises(NotImplementedError, match="IPv6 server_host values are not supported yet"):
        recipe._step_config(("tcp", 10, None, None, 131072, None, 1))


def test_iperf3_udp_step_config_preserves_oversized_message_size():
    recipe = Iperf3UdpSweep(get_recipe("iperf3-udp-sweep"))
    recipe.initialize_config()

    step_cfg = recipe._step_config(("udp", 10, None, None, 100000, 0, 1))

    assert step_cfg.message_size_bytes == 100000


@pytest.mark.parametrize(
    ("recipe_cls", "recipe_name", "protocol", "expected_bitrate"),
    [
        (Iperf3TcpSweep, "iperf3-tcp-sweep", "tcp", None),
        (Iperf3UdpSweep, "iperf3-udp-sweep", "udp", None),
    ],
)
def test_iperf3_recipe_generates_protocol_specific_steps(recipe_cls, recipe_name, protocol, expected_bitrate):
    recipe = recipe_cls(get_recipe(recipe_name))
    recipe.initialize_config()

    steps = recipe.gen_steps()
    assert steps
    assert all(step[0] == protocol for step in steps)
    assert all(step[5] == expected_bitrate for step in steps)
    assert {step[3] for step in steps} == {None}


def test_iperf3_recipe_uses_client_affinities_from_config():
    recipe = Iperf3UdpSweep(get_recipe("iperf3-udp-sweep"))
    recipe.initialize_config({"client_affinities": [2, 4]})

    steps = recipe.gen_steps()
    assert {step[3] for step in steps} == {2, 4}


def test_iperf3_step_config_uses_unique_run_ids_for_affinity_sweep():
    recipe = Iperf3UdpSweep(get_recipe("iperf3-udp-sweep"))
    recipe.initialize_config({"client_affinities": [0, 1]})

    steps = recipe.gen_steps()
    cfgs = [recipe._step_config(step, step_sequence=index + 1) for index, step in enumerate(steps)]
    run_ids = [cfg.run_id for cfg in cfgs]

    assert len(run_ids) == len(set(run_ids))
    assert all(run_id.startswith("run-1-step-") for run_id in run_ids)


@pytest.mark.parametrize(
    ("recipe_cls", "recipe_name"),
    [(Iperf3TcpSweep, "iperf3-tcp-sweep"), (Iperf3UdpSweep, "iperf3-udp-sweep")],
)
def test_iperf3_output_hides_protocol_column_and_keeps_window(recipe_cls, recipe_name):
    recipe = recipe_cls(get_recipe(recipe_name))
    column_names = [field.column_name for field in recipe.INPUT_DISPLAY_FIELDS]

    assert "protocol" not in column_names
    assert "window" in column_names


def test_iperf3_output_cpu_columns_by_display_level():
    recipe = Iperf3UdpSweep(get_recipe("iperf3-udp-sweep"))
    basic_output_columns = [
        field.column_name for field in recipe.OUTPUT_DISPLAY_FIELDS if field.display_level & DisplayLevel.BASIC
    ]
    verbose_output_columns = [
        field.column_name for field in recipe.OUTPUT_DISPLAY_FIELDS if field.display_level & DisplayLevel.VERBOSE
    ]

    assert "sender_cpu_total_pct" in basic_output_columns
    assert "receiver_cpu_total_pct" in basic_output_columns
    assert "sender_cpu_total_pct" not in verbose_output_columns
    assert "receiver_cpu_total_pct" not in verbose_output_columns


def test_iperf3_tcp_recipe_applies_duration_and_window_sweeps_from_config():
    recipe = Iperf3TcpSweep(get_recipe("iperf3-tcp-sweep"))
    recipe.initialize_config({"duration_sweep_steps": [3, 5], "window_sweep_steps": ["256K", "1M"]})

    steps = recipe.gen_steps()
    durations = {step[1] for step in steps}
    windows = {step[2] for step in steps}

    assert durations == {3, 5}
    assert windows == {"256K", "1M"}


@pytest.mark.parametrize(
    ("recipe_cls", "recipe_name"),
    [(Iperf3TcpSweep, "iperf3-tcp-sweep"), (Iperf3UdpSweep, "iperf3-udp-sweep")],
)
def test_iperf3_recipe_allows_default_and_explicit_bandwidth_targets(recipe_cls, recipe_name):
    recipe = recipe_cls(get_recipe(recipe_name))
    recipe.initialize_config({"bandwidth_target_bps_sweep_steps": [None, 1_000_000_000]})

    bitrates = {step[5] for step in recipe.gen_steps()}

    assert bitrates == {None, 1_000_000_000}


def test_iperf3_udp_recipe_applies_duration_and_bitrate_sweeps_from_config():
    recipe = Iperf3UdpSweep(get_recipe("iperf3-udp-sweep"))
    recipe.initialize_config({"duration_sweep_steps": [3, 8], "bandwidth_target_bps_sweep_steps": [1_000_000_000]})

    steps = recipe.gen_steps()
    durations = {step[1] for step in steps}
    bitrates = {step[5] for step in steps}

    assert durations == {3, 8}
    assert bitrates == {1_000_000_000}
