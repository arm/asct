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


def range_up(lo, hi, steps=1, step=2):
    """
    Generate an ascending range of powers of 2, with optional intermediate steps.

    >>> list(range_up(128, 512, steps=2))
    [128, 192.0, 256, 384.0, 512]
    >>> list(range_up(128, 512, step=4))
    [128, 512]
    """
    if steps < 1:
        raise ValueError(f"invalid inter-step count: {steps}")
    if not step > 1:
        raise ValueError(f"invalid step size: {step}")
    d = lo
    while d <= hi:
        yield d
        if steps >= 2:
            for i in range(1, steps):
                m = d * (1.0 + i * ((step - 1.0) / steps))
                if m > hi:
                    return
                yield m
        d *= step


class ASCTAverager:
    """
    Class the maintains the average of a series of elements that are
    added one by one.

    >>> calc = ASCTAverager()
    >>> calc.HasData()
    False
    >>> calc.Add(1)
    >>> calc.Add(2)
    >>> calc.HasData()
    True
    >>> calc.Get()
    1.5
    >>> calc.Add(3)
    >>> calc.Add(4)
    >>> calc.Get()
    2.5
    """

    def __init__(self, initial_values=None):
        self._average = None
        self._sum = float(0)
        self._count = float(0)
        if initial_values:
            self._sum = float(sum(initial_values))
            self._count = float(len(initial_values))
            self._average = self._sum / self._count

    def Add(self, val):
        self._sum += float(val)
        self._count += 1.0
        self._average = self._sum / self._count

    def Get(self):
        return self._average

    def HasData(self):
        return self._average is not None


if __name__ == "__main__":
    import doctest

    doctest.testmod()
