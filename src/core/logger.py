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

from __future__ import annotations

import logging
import traceback

from dataclasses import dataclass

from asct.core.term_ui.term_manager import TermManager, TermAnsiClr

_logger = logging.getLogger("ASCT")

debug = _logger.debug
info = _logger.info
warning = _logger.warning
error = _logger.error
critical = _logger.critical

DEFAULT_LOG_LEVEL_CONSOLE = "info"
DEFAULT_LOG_LEVEL_FILE = "info"

# if a log line starts with this tag, it will not be output to terminal (file only)
LOGGER_TAG_ONLY_FILE = "!file!"

_LOG_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


# Formatting for the verbose messages (>= ERROR)
_MESSAGE_FORMAT_LONG_TERM = (
    "{level_clr}▌{levelname}{reset_clr}|{asctime}.{centisecs:02d}|{module}.{funcName}():{lineno}| {message}"
)
_MESSAGE_FORMAT_LONG_FILE = "▌{levelname}|{asctime}.{centisecs:02d}|{module}.{funcName}():{lineno}| {message}"


# Formatting for the less verbose messages (< ERROR)
_MESSAGE_FORMAT_SHORT_TERM = "{level_clr}▌{levelname}{reset_clr}|{asctime}.{centisecs:02d}| {message}"
_MESSAGE_FORMAT_SHORT_FILE = "▌{levelname}|{asctime}.{centisecs:02d}| {message}"

_DATE_FORMAT_SHORT = "%H:%M:%S"
_DATE_FORMAT_LONG = "%b %d %H:%M:%S"


@dataclass(frozen=True)
class DebugLevelFormat:
    message_format: str = _MESSAGE_FORMAT_SHORT_FILE
    date_format: str = _DATE_FORMAT_SHORT


_LOGGING_FORMAT_MAP_TERM = {
    logging.DEBUG: DebugLevelFormat(message_format=_MESSAGE_FORMAT_LONG_TERM, date_format=_DATE_FORMAT_LONG),
    logging.INFO: DebugLevelFormat(message_format=_MESSAGE_FORMAT_SHORT_TERM, date_format=_DATE_FORMAT_SHORT),
    logging.WARNING: DebugLevelFormat(message_format=_MESSAGE_FORMAT_SHORT_TERM, date_format=_DATE_FORMAT_SHORT),
    logging.ERROR: DebugLevelFormat(message_format=_MESSAGE_FORMAT_LONG_TERM, date_format=_DATE_FORMAT_LONG),
    logging.CRITICAL: DebugLevelFormat(message_format=_MESSAGE_FORMAT_LONG_TERM, date_format=_DATE_FORMAT_LONG),
}

_LOGGING_FORMAT_MAP_FILE = {
    logging.DEBUG: DebugLevelFormat(message_format=_MESSAGE_FORMAT_LONG_FILE, date_format=_DATE_FORMAT_LONG),
    logging.INFO: DebugLevelFormat(message_format=_MESSAGE_FORMAT_SHORT_FILE, date_format=_DATE_FORMAT_LONG),
    logging.WARNING: DebugLevelFormat(message_format=_MESSAGE_FORMAT_SHORT_FILE, date_format=_DATE_FORMAT_LONG),
    logging.ERROR: DebugLevelFormat(message_format=_MESSAGE_FORMAT_LONG_FILE, date_format=_DATE_FORMAT_LONG),
    logging.CRITICAL: DebugLevelFormat(message_format=_MESSAGE_FORMAT_LONG_FILE, date_format=_DATE_FORMAT_LONG),
}


class ASCTLogMessageFilter(logging.Filter):
    def __init__(self, is_term):
        super().__init__()
        self._is_term = is_term

    def _update_formatting(self, record):
        level = record.levelno
        record.levelname_short = {
            logging.DEBUG: "DBG",
            logging.INFO: "INFO",
            logging.WARNING: "WARN",
        }.get(level, record.levelname)
        record.reset_clr = f"{TermAnsiClr.RESET}"
        record.level_clr = {
            logging.DEBUG: TermAnsiClr.create_clr_attr(TermAnsiClr.FG_GREEN, TermAnsiClr.BG_BLACK),
            logging.INFO: TermAnsiClr.create_clr_attr(TermAnsiClr.FG_CYAN, TermAnsiClr.BG_BLACK),
            logging.WARNING: TermAnsiClr.create_clr_attr(TermAnsiClr.FG_YELLOW, TermAnsiClr.BG_BLACK),
            logging.ERROR: TermAnsiClr.create_clr_attr(TermAnsiClr.FG_RED, TermAnsiClr.BG_BLACK),
            logging.CRITICAL: TermAnsiClr.create_clr_attr(TermAnsiClr.FG_WHITE, TermAnsiClr.BG_RED),
        }.get(level, "")
        record.centisecs = int(record.msecs / 10)

    def _filter_tagged_msgs(self, record):
        orig_msg = record.getMessage()
        if orig_msg.startswith(LOGGER_TAG_ONLY_FILE):
            if self._is_term:
                return False
            orig_msg = orig_msg[len(LOGGER_TAG_ONLY_FILE) :]
        # getMessage already rendered the message, remove args to avoid another attempt at rendering
        record.msg = orig_msg
        record.args = ()
        return True

    def filter(self, record):
        # 1: extend the fields to include color info
        self._update_formatting(record)
        # 2: check for exclusion tags and filter out incompatible messages
        return self._filter_tagged_msgs(record)


class LevelBasedFormatter(logging.Formatter):
    def __init__(self, fmt_map=None):
        super().__init__(fmt=_MESSAGE_FORMAT_LONG_FILE, datefmt=_DATE_FORMAT_LONG, style="{")
        if not fmt_map:
            self.formatters = None
        else:
            self.formatters = {
                level: logging.Formatter(fmt.message_format, datefmt=fmt.date_format, style="{")
                for level, fmt in fmt_map.items()
            }

    def format(self, record):
        formatter = self.formatters.get(record.levelno, None) if self.formatters else None
        if formatter is None:
            return super().format(record)
        return formatter.format(record)


class LazyStringProducer:
    def __init__(self, str_gen):
        self.str_gen = str_gen

    def __str__(self):
        return self.str_gen()


LS = LazyStringProducer


@dataclass
class LogTargetConfiguration:
    # -- current state --
    log_level: str  # log level for this handler
    enabled: bool = False  # true if handler is active, false if inactive
    handler: object = None  # handler that is register to the logger
    param: str = None  # type specific param (for file logging - file name)

    # true if requested to turn logger on, false if requested to turn logger off, None if no request was done
    set_enabled: bool | None = None


class LogConfigurator:
    """
    Short lived object used to configure logging in 3-4 steps:
    * configure_console_logging
    * configure_file_logging
    * apply (can be called after each call to configure* or once, after all calls to configure*)
    """

    def __init__(self):
        self._config = {
            "term": LogTargetConfiguration(log_level=DEFAULT_LOG_LEVEL_CONSOLE),
            "file": LogTargetConfiguration(log_level=DEFAULT_LOG_LEVEL_FILE),
        }
        self._null_handler = None

    def _configure_target(self, name, enable, log_level, param):
        target = self._config[name]
        if target.enabled != enable:
            target.set_enabled = enable
            target.log_level = log_level
            target.param = param

    def configure_console_logging(self, enable, log_level):
        self._configure_target("term", enable, log_level, None)
        return self

    def configure_file_logging(self, enable, log_level, file_path):
        self._configure_target("file", enable, log_level, file_path)
        return self

    def apply(self):
        needs_null_handler = True
        for target, config in self._config.items():
            if config.set_enabled is None:
                continue
            handler = None
            if config.set_enabled:
                needs_null_handler = False

                if config.handler is not None:
                    continue

                if target == "term":
                    handler = logging.StreamHandler(stream=TermManager())
                    formatter = LevelBasedFormatter(_LOGGING_FORMAT_MAP_TERM)
                elif target == "file":
                    handler = logging.FileHandler(config.param, delay=True)
                    formatter = LevelBasedFormatter(_LOGGING_FORMAT_MAP_FILE)

                handler.setFormatter(formatter)
                handler.addFilter(ASCTLogMessageFilter(target == "term"))
                handler.setLevel(_LOG_LEVELS[config.log_level])

                _logger.addHandler(handler)
            elif config.handler is not None:
                _logger.removeHandler(config.handler)

            config.handler = handler
            config.enabled = config.set_enabled

        if needs_null_handler and self._null_handler is None:
            self._null_handler = logging.NullHandler()
            _logger.addHandler(self._null_handler)
        elif not needs_null_handler and self._null_handler is not None:
            _logger.removeHandler(self._null_handler)
            self._null_handler = None

        min_level = min(h.level for h in _logger.handlers)
        _logger.setLevel(min_level)
        return self


def get_log_levels():
    return sorted(_LOG_LEVELS.keys(), key=lambda x: int(_LOG_LEVELS[x]))


def is_log_level(level):
    if level not in _LOG_LEVELS:
        raise ValueError(f"Invalid log level: {level}, expected one of {_LOG_LEVELS}")
    return any(_LOG_LEVELS[level] >= h.level for h in _logger.handlers)


def get_stack_trace(max_depth=None, separator="\n"):
    stack_trace = traceback.extract_stack()[:-1]
    if max_depth is not None:
        stack_trace = stack_trace[-max_depth:]
    stack_trace_descr = []
    for frame_summary in stack_trace:
        stack_trace_descr += [f"{frame_summary.name}() {frame_summary.filename}:{frame_summary.lineno}"]
    return separator.join(stack_trace_descr)
