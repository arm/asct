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
import subprocess
import shlex
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import asct.core.logger as log
from asct.core.benchrunner import AsyncRunner
from asct.core.benchspec.network_benchspec import Iperf3ServerSpec, NetworkingBenchmarkConfig
from asct.core.resources.ext_tool import ExternalToolResource
from asct.core.resources.resource_base import Resource
from asct.lib.networking.network_helpers import (
    DEFAULT_IPERF3_PORT,
    WILDCARD_IPV4,
    check_port_available,
    check_port_value,
    is_local_host,
    resolve_wildcard_host,
)


class Ip(ExternalToolResource):
    def __init__(self):
        """Check availability of the `ip` command-line utility."""
        super().__init__("ip")

    def get_tool_version(self):
        # iproute2 uses `ip -V`; some builds may not support `--version`.
        return subprocess.run(
            [self.tool_name, "-V"],
            text=True,
            capture_output=True,
            check=False,
        )


class Ifconfig(ExternalToolResource):
    def __init__(self):
        """Check availability of the `ifconfig` command-line utility."""
        super().__init__("ifconfig")


IPERF3_MIN_VERSION = "3.0.4"
IPERF3_VERSION_RE = re.compile(r"\b(\d+)\.(\d+)(?:\.(\d+))?\b")


class Iperf3(ExternalToolResource):
    def __init__(self):
        """Check availability of the `iperf3` command-line utility."""
        super().__init__("iperf3")

    def get_tool_version(self):
        result = super().get_tool_version()

        stdout_text = (result.stdout or "").strip()
        if stdout_text:
            first_line = stdout_text.splitlines()[0].strip()
            return subprocess.CompletedProcess(
                args=result.args,
                returncode=0,
                stdout=first_line,
                stderr=result.stderr,
            )

        stderr_text = (result.stderr or "").strip()
        if stderr_text:
            first_line = stderr_text.splitlines()[0].strip()
            return subprocess.CompletedProcess(
                args=result.args,
                returncode=0,
                stdout=first_line,
                stderr=result.stderr,
            )

        return result

    @staticmethod
    def _version_tuple(version: str) -> tuple[int, int, int] | None:
        match = IPERF3_VERSION_RE.search(version)
        if match is None:
            return None
        major, minor, patch = match.groups()
        return int(major), int(minor), int(patch or 0)

    def check_version(self):
        super().check_version()
        detected_version = self._version_tuple(self.version)
        minimum_version = self._version_tuple(IPERF3_MIN_VERSION)
        if detected_version is not None and minimum_version is not None and detected_version < minimum_version:
            log.warning(
                "iperf3 version %s is older than ASCT's oldest supported version %s; "
                "network benchmark results may be incomplete or fail to parse",
                self.version,
                IPERF3_MIN_VERSION,
            )


@dataclass(slots=True)
class Iperf3ServerConfig:
    port: int | None = None
    namespace: str | None = None
    affinity: int | None = None
    extra_args: Sequence[str] = field(default_factory=tuple)
    cwd: str | Path | None = None
    remote_host: str | None = None

    def __post_init__(self) -> None:
        if self.port is not None:
            self.port = check_port_value(self.port, userspace_only=True, raise_on_error=True)

        if self.namespace not in (None, ""):
            # Namespace orchestration is intentionally disabled for now.
            raise NotImplementedError("Network namespaces are not supported yet for iperf3 server management")
        self.namespace = None
        self.affinity = None if self.affinity is None else int(self.affinity)

        if self.extra_args is None:
            self.extra_args = []
        elif isinstance(self.extra_args, str):
            self.extra_args = [self.extra_args]
        else:
            self.extra_args = [str(arg) for arg in self.extra_args]

        self.cwd = None if self.cwd is None else str(self.cwd)
        self.remote_host = None if self.remote_host is None else str(self.remote_host)

    def identity_key(self):
        return (
            self.port,
            self.affinity,
            tuple(self.extra_args),
            self.cwd,
            self.remote_host,
        )


class Iperf3Server(Resource):
    """Resource that keeps a local iperf3 server running for benchmark clients."""

    def __init__(self, config: Iperf3ServerConfig):
        super().__init__()
        self.config = config
        self._runner = None
        self._owns_server = False

    @staticmethod
    def _is_iperf3_server_command(args: list[str]) -> bool:
        if "--server" not in args:
            return False
        return any(os.path.basename(str(arg)) == "iperf3" for arg in args)

    def _is_requested_port_available(self, requested_port: int) -> bool:
        return check_port_available(WILDCARD_IPV4, port=requested_port)

    def _has_existing_local_iperf3_server(self):
        cfg = self.config
        probe_host = resolve_wildcard_host(cfg.remote_host if cfg.remote_host not in (None, "") else "")
        probe_port = DEFAULT_IPERF3_PORT if cfg.port is None else int(cfg.port)
        cmd = [
            "iperf3",
            "--client",
            str(probe_host),
            "--port",
            str(probe_port),
            "--bytes",
            "1",
            "--json",
        ]

        try:
            result = subprocess.run(cmd, text=True, capture_output=True, check=False)
        except OSError as exc:
            log.debug(f"Failed to inspect existing listener on port {cfg.port}: {exc}")
            return False

        if result.returncode != 0:
            log.debug(
                "Failed to probe existing iperf3 listener on port %s: %s",
                cfg.port,
                (result.stderr or result.stdout).strip(),
            )
            return False

        stdout = result.stdout or ""
        return '"start"' in stdout and '"connected"' in stdout

    def _existing_server_matches_requested_config(self):
        """Best-effort check whether an existing local iperf3 server matches requested settings."""
        cfg = self.config

        def _actual_opt_value(args: list[str], key: str) -> str | None:
            if key in args:
                idx = args.index(key)
                if idx + 1 < len(args):
                    return args[idx + 1]
            return None

        def _affinity_compatible(requested: str | None, actual: str | None) -> bool:
            if requested is None:
                return actual is None
            if actual is None:
                # Client-side affinity can steer server CPU even when the
                # server process was started without --affinity.
                return True

            actual_tokens = [token.strip() for token in str(actual).split(",") if token.strip()]
            return requested in actual_tokens

        cmd = ["pgrep", "-fa", "iperf3"]

        try:
            result = subprocess.run(cmd, text=True, capture_output=True, check=False)
        except OSError as exc:
            log.debug(f"Failed to inspect running iperf3 servers: {exc}")
            return False

        if result.returncode != 0:
            log.debug("Failed to inspect running iperf3 servers: %s", (result.stderr or result.stdout).strip())
            return False

        requested_affinity = None if cfg.affinity is None else str(cfg.affinity)
        requested_port = DEFAULT_IPERF3_PORT if cfg.port is None else int(cfg.port)
        requested_extra_args = [str(arg) for arg in cfg.extra_args]

        for raw_line in (result.stdout or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue

            # pgrep -fa prints: "<pid> <command...>"
            parts = line.split(maxsplit=1)
            if len(parts) < 2:
                continue

            try:
                args = shlex.split(parts[1])
            except ValueError:
                continue

            if not self._is_iperf3_server_command(args):
                continue

            port_arg = _actual_opt_value(args, "--port")
            if port_arg is None:
                actual_port = DEFAULT_IPERF3_PORT
            else:
                try:
                    actual_port = int(port_arg)
                except ValueError:
                    actual_port = -1

            if actual_port != requested_port:
                continue

            # Bind host is intentionally not strict-matched here. Reachability
            # is already validated by _has_existing_local_iperf3_server() using
            # the requested probe target, which is what matters for reuse.

            actual_affinity = _actual_opt_value(args, "--affinity")
            if not _affinity_compatible(requested_affinity, actual_affinity):
                continue

            if any(extra not in args for extra in requested_extra_args):
                continue

            return True

        return False

    def setup(self):
        cfg = self.config
        probe_host = resolve_wildcard_host(cfg.remote_host if cfg.remote_host not in (None, "") else "")
        if not is_local_host(str(probe_host)):
            raise NotImplementedError("Remote iperf3 server management is not implemented yet")

        Iperf3().setup()

        requires_managed_server = cfg.affinity is not None or bool(cfg.extra_args)
        requested_port = DEFAULT_IPERF3_PORT if cfg.port is None else int(cfg.port)

        if not self._is_requested_port_available(requested_port):
            if self._has_existing_local_iperf3_server():
                if requires_managed_server:
                    if self._existing_server_matches_requested_config():
                        log.warning(
                            "iperf3 server port %s is already in use by an existing matching iperf3 server; reusing it",
                            requested_port,
                        )
                        self._owns_server = False
                        self.applied = True
                        return True
                    raise RuntimeError(
                        f"iperf3 server port {requested_port} is already in use by an existing iperf3 server; "
                        "reuse is unsupported with explicit server settings"
                    )

                if self._existing_server_matches_requested_config():
                    log.warning(
                        "iperf3 server port %s is already in use by an existing iperf3 server; reusing it",
                        requested_port,
                    )
                    self._owns_server = False
                    self.applied = True
                    return True

                raise RuntimeError(
                    f"iperf3 server port {requested_port} is already in use by an existing iperf3 server; "
                    "reuse is unsupported with requested server settings"
                )
            raise RuntimeError(f"iperf3 server port {requested_port} is already in use; please choose another port")

        server_spec = Iperf3ServerSpec(
            config=NetworkingBenchmarkConfig(
                port=cfg.port,
                network_namespace=cfg.namespace,
                server_affinity=cfg.affinity,
                extra_args=cfg.extra_args,
            )
        )
        self._runner = AsyncRunner(cwd=cfg.cwd, suppress_output=True)
        self._runner.run(server_spec)

        if self._runner.retcode not in (None, 0):
            raise RuntimeError(f"iperf3 server failed to start: {self._runner.stderr}")

        self._owns_server = True
        self.applied = True
        return True

    def teardown(self):
        if self._owns_server and self._runner is not None:
            self._runner.stop(use_int=True)
            self._runner = None
        self._owns_server = False
        self.applied = False

    def _identity(self):
        return self.config.identity_key()

    def __eq__(self, value):
        if type(self) is not type(value):
            return False
        return self._identity() == value._identity()

    def __hash__(self):
        return hash((type(self), *self._identity()))
