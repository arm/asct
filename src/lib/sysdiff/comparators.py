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

from typing import Any, ClassVar


class Comparator:
    # List of path tuples or key names to ignore globally
    ignore_keys: ClassVar[set[str]] = set()

    def __call__(self, a: Any, b: Any, path: Any) -> bool:
        # Default: just compare for equality, unless ignored
        if self.should_ignore(path):
            return True
        return a == b

    @classmethod
    def should_ignore(cls, path: str) -> bool:
        """
        Checks if the given path should be ignored based on the ignore_keys.
        """
        # Check for exact path match as dot-separated string or any single key match
        if path in cls.ignore_keys or any(str(k) in cls.ignore_keys for k in path.split(".")):
            return True

        for key in cls.ignore_keys:
            # Support wildcard suffix match (e.g., "metadata.*" matches "metadata.result")
            if (key.endswith("*") and key[:-1] in path) or path.startswith(key + "."):
                return True

        return False

    @classmethod
    def add_ignore_key(cls, key: str):
        """
        Adds a key to the list of ignored keys.
        """
        cls.ignore_keys.add(key)


class NumericToleranceComparator(Comparator):
    def __init__(self, abs_tolerance=None, percent_tolerance=None):
        """
        Initializes the comparator with optional absolute and percentage tolerances.

        Args:
            abs_tolerance (float, optional): The absolute tolerance value for comparisons. Defaults to None.
            percent_tolerance (float, optional): The percentage tolerance value for comparisons. Defaults to None.
        """
        self.abs_tolerance = abs_tolerance
        self.percent_tolerance = percent_tolerance

    def __call__(self, a, b, path):
        """
        Compares two values `a` and `b` at a given `path`, considering optional absolute and percentage tolerances.

        Parameters:
            a: The first value to compare.
            b: The second value to compare.
            path: The path or key associated with the values being compared.

        Returns:
            bool: True if the values are considered equal (within tolerances or ignored by path), False otherwise.

        """
        if self.should_ignore(path):
            return True

        # Attempt to convert to float and compare with tolerances
        try:
            fa, fb = float(a), float(b)
            if fa == fb:
                return True

            diff = abs(fb - fa)
            # Check absolute tolerance
            if self.abs_tolerance is not None and diff <= self.abs_tolerance:
                return True
            # Check percentage tolerance
            if self.percent_tolerance is not None:
                denom = abs(fa) if fa != 0 else (abs(fb) if fb != 0 else 1.0)
                if denom and (diff / denom * 100.0) <= self.percent_tolerance:
                    return True
            return False
        except (TypeError, ValueError):
            return a == b


class IgnoreNodeComparator(Comparator):
    """A comparator that always ignores differences (returns no diffs)."""

    def __call__(self, a, b, path):  # ruff:ignore[unused-method-argument]
        return True
