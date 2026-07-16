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
Various utility and helper functions
"""

import functools
import threading
import time
from pathlib import Path


def flatten_dict(d, parent_key="", sep=".", unroll_lists=True):
    """
    Flatten nested dicts into a single flat dict with dot notation to retain nested structure

    >>> flatten_dict({"a": 1, "b": {"c": 2, "d": {"e": 3}}})
    {'a': 1, 'b.c': 2, 'b.d.e': 3}

    >>> flatten_dict({"a": [{"b": 1}, {"c": 2}], "d": [3, 4]})
    {'a.0.b': 1, 'a.1.c': 2, 'd.0': 3, 'd.1': 4}

    >>> flatten_dict({"a": [{"b": 1}, {"c": 2}], "d": [3, 4]}, unroll_lists=False)
    {'a': [{'b': 1}, {'c': 2}], 'd': [3, 4]}

    """
    items = {}
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.update(flatten_dict(v, new_key, sep=sep, unroll_lists=unroll_lists))
        elif isinstance(v, list) and unroll_lists:
            for i, value in enumerate(v):
                list_key = f"{new_key}{sep}{i}"
                if isinstance(value, dict):
                    items.update(flatten_dict(value, list_key, sep=sep, unroll_lists=unroll_lists))
                else:
                    items[list_key] = value
        else:
            items[new_key] = v
    return items


def unflatten_dict(d, sep="."):
    """
    Expand a flat dict with separated keys into a nested dict.

    >>> unflatten_dict({"a": 1, "b.c": 2, "b.d.e": 3})
    {'a': 1, 'b': {'c': 2, 'd': {'e': 3}}}
    """
    result = {}
    for key, value in d.items():
        if not isinstance(key, str) or sep not in key:
            result[key] = value
            continue
        create_dict_path(result, key.split(sep), value)
    return result


def create_dict_path(dest, key_path, value):
    """
    Creates a path in the dest dictionary based on key_path which is
    a list of path components (keys)

    >>> dest = {}
    >>> create_dict_path(dest, ["this", "is", "a", "test"], 10)
    >>> dest
    {'this': {'is': {'a': {'test': 10}}}}
    """
    if not key_path:
        return
    for comp in key_path[:-1]:
        if comp not in dest or type(dest[comp]) is not dict:
            dest[comp] = {}
        dest = dest[comp]
    dest[key_path[-1]] = value


def retry(retry_count, retry_wait=None):
    """
    Utility decorator that retries a function until it returns a non-None value
    (at most retry_count times).
    The decorator passes the return value to the caller.
    """

    def retry_decorator(func):
        @functools.wraps(func)
        def retry_wrapper(*args, **kwargs):
            for _ in range(retry_count + 1):
                result = func(*args, **kwargs)
                if result:
                    return result
                if retry_wait:
                    time.sleep(retry_wait)
            return None

        return retry_wrapper

    return retry_decorator


def thread_safe(func):
    """Decorator making sure that the decorated function can only be called serially"""
    lock = threading.Lock()

    def wrapper(*args, **kwargs):
        with lock:
            return func(*args, **kwargs)

    return wrapper


def enable_sysreg(sysreg_base_path: str) -> bool:
    """Checks if sysreg driver is available"""
    try:
        base = Path(sysreg_base_path)
    except TypeError:
        return False

    return base.is_dir()


if __name__ == "__main__":
    import doctest

    doctest.testmod()
