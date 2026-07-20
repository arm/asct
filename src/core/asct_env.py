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

import fcntl
import os
import signal
import threading
import subprocess
import time

from enum import Enum
from dataclasses import dataclass
from typing import Callable

from asct.core.managers.resource_manager import ResourceManager

from asct.core import logger as log
from asct.core.utility.misc import retry
from asct.core.datatypes import ASCTSingleton
from asct.core.resources.check_sudo import CheckSudo
from asct.core.resources.check_paranoid_level import CheckParanoidLevel
from asct.core.resources.resource_base import MultiResourceContainer
from asct.core.term_ui.progress_bar import get_progress_tracker


class ProcessMutex:
    def __init__(self, name, retry_count, retry_wait=0.5):
        self._name = name
        self._retry_count = retry_count
        self._retry_wait = retry_wait
        self._lock_file_handle = None
        self._lock_dir_path = os.path.join("/var/lock", f"{self._name}.lock")
        self._error = None

    def __enter__(self):
        if not self.prepare_lock():
            return self

        @retry(retry_count=self._retry_count, retry_wait=self._retry_wait)
        def attempt_lock():
            file_handle = None
            try:
                file_handle = os.open(self._lock_dir_path, flags=os.O_RDONLY)
                fcntl.flock(file_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return file_handle
            except OSError as exc:
                if file_handle:
                    os.close(file_handle)
                log.debug("Unable to acquire application lock: %s", exc)
            return None

        self._lock_file_handle = attempt_lock()
        if not self._lock_file_handle:
            self._error = "Unable to acquire application lock, another instance of ASCT is running"
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        if self._lock_file_handle:
            fcntl.flock(self._lock_file_handle, fcntl.LOCK_UN)
            os.close(self._lock_file_handle)
        return False  # Pass any exception to the caller

    def lock_successful(self):
        return self._lock_file_handle is not None

    def get_error(self):
        return self._error

    def prepare_lock(self):
        lock_dir_mode = 0o444
        lock_dir_umask = 0o333

        if not os.path.exists(self._lock_dir_path):
            old_umask = os.umask(lock_dir_umask)
            os.makedirs(self._lock_dir_path, exist_ok=True, mode=lock_dir_mode)
            os.umask(old_umask)
            return True

        if not os.path.isdir(self._lock_dir_path):
            self._error = f"Lock object {self._lock_dir_path} exists and is a file, please delete manually"
            return False

        return True


class ProcessWatcher(metaclass=ASCTSingleton):
    SIGINT_DEADLINE_SEC = 5.0

    def __init__(self):
        self._lock = threading.RLock()
        self._processes: set[subprocess.Popen] = set()
        self._handler_installed = False
        self._stop_requested = False

    def initialize(self):
        with self._lock:
            if self._handler_installed:
                return
            signal.signal(signal.SIGINT, self._handle_sigint)
            self._handler_installed = True

    def __enter__(self):
        self._lock.acquire()
        if self._stop_requested:
            self._lock.release()
            raise SystemExit(130)
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self._lock.release()
        return False

    def register(self, process: subprocess.Popen):
        with self._lock:
            self._processes.add(process)

    def unregister(self, process: subprocess.Popen | None):
        if process is None:
            return
        with self._lock:
            self._processes.discard(process)

    @property
    def stop_requested(self):
        with self._lock:
            return self._stop_requested

    def _stop_registered_processes(self):
        processes = list(self._processes)
        for process in processes:
            if process.poll() is None:
                try:
                    process.send_signal(signal.SIGINT)
                except (OSError, subprocess.SubprocessError, ValueError) as exc:
                    log.debug("Failed sending SIGINT to process %s: %s", getattr(process, "pid", "?"), exc)

        deadline = time.time() + self.SIGINT_DEADLINE_SEC
        for process in processes:
            if process.poll() is not None:
                self.unregister(process)
                continue
            remaining = deadline - time.time()
            if remaining > 0:
                try:
                    process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    pass
                except (OSError, subprocess.SubprocessError, ValueError) as exc:
                    log.debug("Failed waiting for process %s: %s", getattr(process, "pid", "?"), exc)
            if process.poll() is None:
                try:
                    process.kill()
                except (OSError, subprocess.SubprocessError, ValueError) as exc:
                    log.debug("Failed killing process %s: %s", getattr(process, "pid", "?"), exc)
            self.unregister(process)

    def _handle_sigint(self, _signum, _frame):
        with self._lock:
            self._stop_requested = True
            if self._handler_installed:
                signal.signal(signal.SIGINT, signal.default_int_handler)
                self._handler_installed = False
            log.warning("Ctrl+C received, stopping current run")
            try:
                get_progress_tracker().terminate()
            except (RuntimeError, OSError, ValueError) as exc:
                log.debug("Failed stopping progress tracker on SIGINT: %s", exc)
            self._stop_registered_processes()
        raise SystemExit(130)


class SystemState(metaclass=ASCTSingleton):
    # Singleton pattern to ensure only one instance of SystemState is created.
    def __init__(self):
        self.resource_manager = ResourceManager()  # this is a singleton

    def initialize(self):
        log.debug("Initializing SystemState")
        if ASCTGlobalSettings().enable_pmu:
            self.resource_manager.register(
                MultiResourceContainer(CheckSudo(), CheckParanoidLevel(1), require_all=False), global_scope=True
            )
            self.resource_manager.apply_all(global_scope=True)


@dataclass(frozen=True)
class DebugConfigOption:
    env_var_name: str
    debug_var_name: str
    default: str
    cast_func: Callable[str, str]


class DebugConfig:
    def _to_bool(value):
        if value.lower() in ["1", "yes", "on"]:
            return True
        if value.lower() in ["0", "no", "off"]:
            return False
        raise ValueError(f"'{value}' could not be converted to bool")

    # Debug env vars configuration
    _DEBUG_CONFIG: tuple[DebugConfigOption, ...] = (
        DebugConfigOption(
            env_var_name="ASCT_DEBUG_ENABLE_PMU",
            debug_var_name="enable_pmu",
            default="0",
            cast_func=_to_bool,
        ),
        DebugConfigOption(
            env_var_name="ASCT_DEBUG_DISABLE_HUGEPAGE_RESIZE",
            debug_var_name="disable_hugepage_resize",
            default="0",
            cast_func=_to_bool,
        ),
    )
    # --------------------------------

    def __init__(self):
        self._debug_config = {}

    def read_env_vars(self):
        for conf in self._DEBUG_CONFIG:
            value = os.environ.get(conf.env_var_name, conf.default)
            conv_value = None
            try:
                conv_value = conf.cast_func(value)
            except ValueError as exc:
                log.warning(
                    "Debug environment variable %s couldn't be parsed: %s, reverted to default: %s",
                    conf.env_var_name,
                    exc,
                    conf.default,
                )
                conv_value = conf.cast_func(conf.default)
            log.debug(f"Setting debug option '{conf.debug_var_name}' to '{conv_value}'")
            setattr(self, conf.debug_var_name, conv_value)


class ASCTExecMode(Enum):
    EXEC_MODE_NORMAL = 0
    EXEC_MODE_QUICK = 1
    EXEC_MODE_DEV = 2


class ASCTGlobalSettings(metaclass=ASCTSingleton):
    def __init__(self):
        self._exec_mode = ASCTExecMode.EXEC_MODE_NORMAL
        self._debug_config = DebugConfig()

    def read_env_vars(self):
        self._debug_config.read_env_vars()

    def set_dev_mode(self):
        self._exec_mode = ASCTExecMode.EXEC_MODE_DEV

    def set_quick_mode(self):
        self._exec_mode = ASCTExecMode.EXEC_MODE_QUICK

    def dev_mode(self):
        return self._exec_mode == ASCTExecMode.EXEC_MODE_DEV

    def quick_mode(self):
        return self._exec_mode == ASCTExecMode.EXEC_MODE_QUICK

    def __getattr__(self, name):
        if self._debug_config and hasattr(self._debug_config, name):
            return getattr(self._debug_config, name)
        raise AttributeError(f"{name} not found in ASCTGlobalSettings")
