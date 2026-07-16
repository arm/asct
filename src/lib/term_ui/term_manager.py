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

import signal
import shutil

from enum import Enum
from threading import Lock

from asct.core.datatypes import ASCTSingleton


class TermCtrlCmd(Enum):
    ESC_SEQ = "\033"
    CLEAR_LINE = "[2K"
    MOVE_UP = "[1A"

    @classmethod
    def create_cmd(cls, *cmds):
        return "".join([cls.ESC_SEQ.value + cmd.value for cmd in cmds])


class TermAnsiClr(Enum):
    # Reset
    RESET = "0"

    # Foreground (30 -> 37)
    FG_BLACK = "30"
    FG_RED = "31"
    FG_GREEN = "32"
    FG_YELLOW = "33"
    FG_BLUE = "34"
    FG_MAGENTA = "35"
    FG_CYAN = "36"
    FG_WHITE = "37"

    # Background (40 -> 47)
    BG_BLACK = "40"
    BG_RED = "41"
    BG_GREEN = "42"
    BG_YELLOW = "43"
    BG_BLUE = "44"
    BG_MAGENTA = "45"
    BG_CYAN = "46"
    BG_WHITE = "47"

    def __str__(self):
        return f"{TermCtrlCmd.ESC_SEQ.value}[{self.value}m"

    @classmethod
    def create_clr_attr(cls, *clrs):
        return f"{TermCtrlCmd.ESC_SEQ.value}[" + ";".join([c.value for c in clrs]) + "m"


class TermManager(metaclass=ASCTSingleton):
    def __init__(self):
        self._output_stream = None
        self._lock = Lock()
        self._clipped_line_length = 0
        self._printable_line_length = 0
        self._needs_line_clear = False
        self._reused_line_data = None
        self._term_cols = shutil.get_terminal_size(fallback=(80, 20)).columns
        self._prev_term_cols = self._term_cols

    def initialize(self, output_stream):
        self._output_stream = output_stream
        signal.signal(signal.SIGWINCH, self.on_term_resize)

    def _write(self, content):
        is_reused_line = content[0] == "\r"

        # there's either a \n or a \r that needs to not be counted, no need to call strip() to calculate this
        self._printable_line_length = len(content) - 1
        self._clipped_line_length = min(self._printable_line_length, self._term_cols)

        if is_reused_line:
            self._reused_line_data = content
            content = content[: self._clipped_line_length]
        else:
            self._reused_line_data = None

        if not is_reused_line and self._needs_line_clear:
            self._output_stream.write(TermCtrlCmd.create_cmd(TermCtrlCmd.CLEAR_LINE) + "\r")
            self._needs_line_clear = False

        self._needs_line_clear = is_reused_line

        self._output_stream.write(TermCtrlCmd.create_cmd(TermCtrlCmd.CLEAR_LINE) + content)
        self._output_stream.flush()

    def write(self, content):
        with self._lock:
            self._write(content)

    def on_term_resize(self, *_):
        with self._lock:
            self._term_cols = shutil.get_terminal_size(fallback=(80, 20)).columns
            if self._reused_line_data:
                # autowrap wrapped the progress bar text and created a new line - try to delete it and go back one line
                if self._clipped_line_length > self._term_cols:
                    self._output_stream.write(TermCtrlCmd.create_cmd(TermCtrlCmd.CLEAR_LINE, TermCtrlCmd.MOVE_UP))
                self._write(self._reused_line_data)
            self._prev_term_cols = self._term_cols
