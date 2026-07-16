#!/usr/bin/env python
# ---------------------------------------------------------------------------------
# SPDX-FileCopyrightText: Copyright (C) 2024-2026 Arm Limited and/or its affiliates
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

# This file has been modified.

"""
Colorize text output using ANSI escape codes.
"""

import os

_STATE = {"color_enabled": True}


def colorize(s, c=None, invert=False):
    """
    Add ANSI color escape codes around a string, e.g. to put it into a different color.

    >>> colorize('Hello!')
    'Hello!'
    >>> set_color_enabled(False); colorize('Hello!', c="red"); set_color_enabled(True)
    'Hello!'
    >>> import os; os.environ["NO_COLOR"] = "1"; colorize('Hello!', c="red"); x=os.environ.pop("NO_COLOR")
    'Hello!'
    >>> print(colorize(True))
    \x1b[32mTrue\x1b[0m
    >>> print(colorize(False))
    \x1b[31mFalse\x1b[0m
    >>> print(colorize(None))
    \x1b[36m<unknown>\x1b[0m
    >>> print(colorize(0))
    0
    >>> print(colorize(1))
    1
    >>> print(colorize(100))
    100
    >>> print(colorize("should be red", c="red"))
    \x1b[31mshould be red\x1b[0m
    >>> print(colorize("should be green", c="green"))
    \x1b[32mshould be green\x1b[0m
    >>> print(colorize("should be yellow", c="yellow"))
    \x1b[33mshould be yellow\x1b[0m
    >>> print(colorize("should be blue", c="blue"))
    \x1b[34mshould be blue\x1b[0m
    >>> print(colorize("should be magenta", c="magenta"))
    \x1b[35mshould be magenta\x1b[0m
    >>> print(colorize("should be cyan", c="cyan"))
    \x1b[36mshould be cyan\x1b[0m
    >>> print(colorize(True, c=None, invert=True))
    \x1b[31mTrue\x1b[0m
    >>> print(colorize(False, c=None, invert=True))
    \x1b[32mFalse\x1b[0m
    """
    if not _STATE["color_enabled"]:
        return s
    if os.environ.get("NO_COLOR", ""):
        # http://no-color.org
        return s
    if c is None:
        if s is None:
            s = "<unknown>"
            c = "cyan"
        elif isinstance(s, bool):
            if s != invert:
                c = "green"
            else:
                c = "red"
        else:
            c = "white"
    if c != "white":
        cc = {"red": 31, "green": 32, "yellow": 33, "blue": 34, "magenta": 35, "cyan": 36}
        s = "\x1b[{:d}m".format(cc[c]) + str(s) + "\x1b[0m"
    return s


def set_color_enabled(enabled):
    _STATE["color_enabled"] = enabled
