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

"""
Implementation of various ways to run the benchmarks.  This module should know about running without the details of
the benchmarks
"""

from abc import ABC, abstractmethod
import threading

import os
import subprocess
import time
import signal
from . import logger as log
from .asct_env import ProcessWatcher


class Runner(ABC):
    def __init__(self, cwd):
        self._env = os.environ.copy()
        self._stdout = None
        self._stderr = None
        self._retcode = None
        self._cwd = cwd
        self._current_proc = None

    def update_env(self, env):
        """
        Update the environment variables for the runner.
        :param env: Dictionary of environment variables to update.
        """
        if not isinstance(env, dict):
            raise TypeError("Environment must be a dictionary")
        self._env.update(env)
        return self

    @abstractmethod
    def run(self, bmk_spec):
        raise NotImplementedError("Subclasses must implement the run method")

    @property
    def stdout(self):
        return self._stdout

    @property
    def stderr(self):
        return self._stderr

    @property
    def retcode(self):
        return self._retcode

    @property
    def cwd(self):
        return self._cwd

    @classmethod
    def cmd_format(cls, cmd):
        return " ".join(cmd)

    def execute_command(self, cmd, output_pipe):
        watcher = ProcessWatcher()
        with watcher:
            self._current_proc = subprocess.Popen(
                cmd, stdout=output_pipe, stderr=subprocess.PIPE, env=self._env, cwd=self._cwd, text=True
            )
            watcher.register(self._current_proc)

    # Run the benchmark and collect results
    def run_and_collect_results(self, bmk_spec):
        self.run(bmk_spec)

        if self.retcode != 0:
            raise RuntimeError("Failed running benchmark command")

        return self.collect_results(bmk_spec)

    def collect_results(self, bmk_spec):
        bmk_spec.check_output(self)
        return bmk_spec.process_output(self)


class AsyncRunner(Runner):
    def __init__(self, cwd=None, suppress_output=True):
        super().__init__(cwd)
        self._thread = None
        self._current_proc = None
        self._stop_requested = threading.Event()
        self._lock = threading.Lock()
        self._output_pipe = subprocess.DEVNULL if suppress_output else subprocess.PIPE

    def _run(self, cmd):
        # This is an infinite loop workload, keep it running unless it fails or we call stop()
        while not self._stop_requested.is_set():
            try:
                # Make sure there are no race conditions with stop() (for example: a kill attempt right before
                # self._current_proc gets assigned to a new process, which will result in the kill getting sent
                # to the old process and the thread.join() waiting until the new one finishes)
                with self._lock:
                    if self._stop_requested.is_set():
                        break
                    self.execute_command(cmd, output_pipe=self._output_pipe)
            except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as exc:
                log.error(f"Async command '{self.cmd_format(cmd)}' failed with: {exc}")
                self._retcode = 255
                break
            # communicate() doesn't raise exceptions so it can be moved from under the try/except block
            self._stdout, self._stderr = self._current_proc.communicate()
            self._retcode = self._current_proc.returncode if not self._stop_requested.is_set() else 0
            if self._retcode != 0:
                log.error(f"Async command '{self.cmd_format(cmd)}' failed with retcode {self._retcode}\n{self._stderr}")
                break
        with self._lock:
            ProcessWatcher().unregister(self._current_proc)
            self._current_proc = None

    def run(self, bmk_spec):
        cmd = bmk_spec.make_cmd()
        log.debug(f"async run: ({self.cmd_format(cmd)})")
        self.start(cmd)
        # TODO: better way to wait for the background load to start and ramp up to steady state
        time.sleep(1)
        return self

    def start(self, cmd):
        if self._thread:
            raise AssertionError("AsyncRunner already running")
        self._stop_requested.clear()
        self._thread = threading.Thread(target=lambda: self._run(cmd), daemon=True)
        self._thread.start()

    # Stop the runs.  By default, we kill the process but user can allow the caller an optional to use INT signal
    def stop(self, use_int: bool = False):
        with self._lock:
            self._stop_requested.set()
            if self._current_proc is not None:
                if use_int:
                    self._current_proc.send_signal(signal.SIGINT)
                else:
                    self._current_proc.kill()

        if self._thread is not None:
            self._thread.join()
            self._thread = None


class SyncRunner(Runner):
    def __init__(self, cwd=None):
        super().__init__(cwd)

    def run(self, bmk_spec):
        cmd = bmk_spec.make_cmd()
        if not cmd or not isinstance(cmd, list):
            raise ValueError(f"SyncRunner: cmd must be a list, given {cmd=}")
        try:
            self.execute_command(cmd, output_pipe=subprocess.PIPE)

            self._stdout, self._stderr = self._current_proc.communicate()
            self._retcode = self._current_proc.returncode

            if self._retcode != 0:
                log.error(f"Command [{self.cmd_format(cmd)}] failed with retcode : {self._retcode}")
                if self._stdout:
                    log.error(f"stdout: {self._stdout}")
                if self._stderr:
                    log.error(f"stderr: {self._stderr}")
                raise RuntimeError(
                    f"Command [{self.cmd_format(cmd)}] returned non-zero exit code {self._current_proc.returncode}"
                )

            log.debug("Running [%s]:\n%s\n%s", log.LS(lambda: self.cmd_format(cmd)), self._stdout, self._stderr)

        except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as e:
            log.error(f"Error running command [{self.cmd_format(cmd)}]: {e}")
            self._retcode = 255
        finally:
            ProcessWatcher().unregister(self._current_proc)
