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

import re
import textwrap
from decimal import Decimal, ROUND_HALF_UP


def memsize_str(n, base="binary", unit=None, suffix="", precision=None):
    """
     Output human readable memory size in a bit/byte agnostic way
        e.g. n=1024, base=binary, outputs 1K

        base: 'binary' or 'decimal' - specify whether to use base 2 or 10 aka
            multiples of 1024 or 1000 when calculating kilobytes and so on
            i.e. binary - 1 kibibyte = 1024 bytes
                decimal - 1 kilobyte = 1000 bytes

            choosing 'binary' will automatically insert an 'i' in the unit
            e.g. KiB to specify kibibyte as per IEC 80000-13 standard

            default: binary

        unit: 'B', 'K', 'M', 'G', 'T' - allows you to specify the human readable unit to
            display as e.g. n=512, base=binary, unit='K' becomes 0.5K

            default: if no unit is supplied, the largest available unit is used

        suffix: 'b' or 'B' - can be used to specify units in bits or bytes
            e.g. Mb for data rates, e.g. Mbps aka kilobits per second (usually decimal)
            KiB for binary data sizes aka kibibytes

            default: if no suffix is provided, only 'K', 'M' etc is output

    precision: specify n floating point decimal places to display value to

            default: uses the 'g' general python format specifier
                see https://docs.python.org/3/library/string.html#formatspec

    example usage:

        >>> memsize_str(512)
        '512'

        >>> memsize_str(512, unit='K')
        '0.5K'

        >>> memsize_str(512, unit='K', suffix='B')
        '0.5KiB'

        >>> memsize_str(1024*1024*2)
        '2M'

        >>> memsize_str(1000*1000*2, base="decimal", suffix='b')+"ps"
        '2Mbps'

        >>> memsize_str(1024*1024*2, unit='K')
        '2048K'

        >>> memsize_str(1024*1024+512)
        '1.00049M'

        >>> memsize_str(1024*1024+512, precision=2)
        '1.00M'

        >>> memsize_str(500, base="decimal", unit='K', suffix='B')
        '0.5kB'

        >>> memsize_str(-500, base="decimal", unit='K', suffix='B')
        '-0.5kB'

        >>> memsize_str(-65536, base="binary", suffix='B')
        '-64KiB'

        >>> memsize_str(1000, base="decimal", suffix='b')+"ps"
        '1kbps'
    """
    # Refactor - Change unit function parameter to an enumerated type.
    units = ["B", "K", "M", "G", "T"]  # B here stands for either bits and bytes

    sign = ""
    if n < 0:
        sign = "-"
        n = -n
    valid_suffixes = ["b", "B", "", None]
    if suffix not in valid_suffixes:
        raise ValueError(f"{suffix=} expected to be one of {valid_suffixes}")
    if unit is not None and unit not in units:
        raise ValueError(f"{unit=} expected to be None or in {units}")
    if base not in ["binary", "decimal"]:
        raise ValueError(f"{base=} expected to be 'binary' or 'decimal'")

    iec = ""
    if base == "binary":
        base_n = 1024
        if suffix:
            iec = "i"  # use IEC 80000-13 and insert an i e.g. KiB
    elif base == "decimal":
        base_n = 1000

    factors = {
        "B": base_n**0,
        "K": base_n**1,
        "M": base_n**2,
        "G": base_n**3,
        "T": base_n**4,
    }

    if unit:
        unit = unit.upper()
        value = n / factors[unit]
        # exception to the rule, decimal kB or kb aka 1000 bytes/bits has a lower case 'k'
        if base == "decimal" and unit == "K":
            unit = "k"
        if precision:
            value_str = f"{value:.{precision}f}"
        else:
            value_str = f"{value:g}"
        return f"{sign}{value_str}{unit}{iec}{suffix}"
    # fit into largest available bucket
    for u in reversed(units):
        if n >= factors[u] and n >= base_n:  # don't display 'B' unit as it could be bit or byte
            value = n / factors[u]
            if base == "decimal" and u == "K":
                u = "k"
            if precision:
                value_str = f"{value:.{precision}f}"
            else:
                value_str = f"{value:g}"
            return f"{sign}{value_str}{u}{iec}{suffix}"
    return sign + str(n) + suffix


_DECIMAL = {
    "b": 0,
    "": 0,
    "k": 1,
    "kb": 1,
    "m": 2,
    "mb": 2,
    "g": 3,
    "gb": 3,
}

_BINARY = {
    "kib": 1,
    "mib": 2,
    "gib": 3,
}

_NUM_UNIT_RE = re.compile(
    r"""(?ix)
    ^
    ([+-]?(?:\d+(?:\.\d*)?|\.\d+))   # number
    ([a-z]+)?                        # optional unit
    $
    """,
    re.IGNORECASE,
)


def str_memsize(size_str):
    """
    Parse memory-size strings like '1024KiB', '1.5 MB', '2gb', '4096'
    and return the size in bytes as an int.

    Accepted units (case-insensitive), supports up to GB/GiB:
        - IEC: KiB, MiB, GiB
        - SI:  kB/KB (and k, m, g with or without 'B')
        - B or no unit = bytes

    example usage:

        >>> str_memsize("512")
        512

        >>> str_memsize("1024KiB")
        1048576

        >>> str_memsize("512KB")
        512000

        >>> str_memsize("0.5MB")
        500000

        >>> str_memsize("0.75GiB")
        805306368
    """
    match = _NUM_UNIT_RE.fullmatch(size_str)
    if not match:
        raise ValueError(f"Invalid size string: {size_str}")

    num_str, unit = match.groups()
    unit = (unit or "b").lower()

    multiplier = 1
    if unit in _DECIMAL:
        multiplier = 1000 ** _DECIMAL[unit]
    elif unit in _BINARY:
        multiplier = 1024 ** _BINARY[unit]
    else:
        raise ValueError(f"Unknown unit {unit} in {size_str}")
    return int((Decimal(num_str) * multiplier).to_integral_value(ROUND_HALF_UP))


_TIME_PATTERN = re.compile(
    r"""(?ix)
    ^                # start of string
    (\d+(?:\.\d+)?)  # capture group 1: a number
                     #   - \d+       → one or more digits
                     #   - (?:\.\d+)? → optional decimal part (e.g. ".25")
    ([smh]?)         # capture group 2: optional unit
                     #   - [smh]    → either 's', 'm', or 'h'
                     #   - ?        → zero or one occurrence (unit is optional)
    $                # end of string
    """,
    re.IGNORECASE,
)

_TIME_UNITS_SECONDS = {"s": 1, "m": 60, "h": 3600}


def str_time(time_str):
    match = _TIME_PATTERN.match(time_str)

    if not match:
        raise ValueError(f"Invalid time format: {time_str}")

    value, unit = match.groups()
    value = float(value)
    unit = (unit or "s").lower()
    return value * _TIME_UNITS_SECONDS[unit]


def format_term_definition(
    name, name_width, definition, definition_width, definition_indent=0, column_spacing=0, definition_left_align=True
):
    """
    Basic formatting function that returns a multiline string which can be used for a 2 column definition

    >>> print(format_term_definition("test", 10, "This is a test of a definition that "
    ...                              "will be split into multiple lines", 16, 0, 2), end="")
    test        This is a test
                of a definition
                that will be
                split into
                multiple lines
    """
    content = ""
    wrapped_lines = [
        segment
        for line in definition.splitlines()
        for segment in textwrap.wrap(line, definition_width - definition_indent, break_on_hyphens=False)
    ]
    for idx, line in enumerate(wrapped_lines):
        if idx == 0:
            fill_content = " " * (name_width - len(name))
            if definition_left_align:
                content += name + fill_content
            else:
                content += fill_content + name
            content += " " * (column_spacing + definition_indent) + line
        else:
            content += " " * (name_width + column_spacing + definition_indent) + line
        content += "\n"
    return content


def format_definition_table(table_data, total_width, left_indent, column_spacing, definition_left_align=True):
    """
    Uses format_term_definition to create a 'table' with two columns where one contains the defined terms
    and the other the definition
    """
    left_column_width = max(left_indent + len(r[0]) for r in table_data)
    right_column_width = total_width - left_column_width - column_spacing

    formatted_str = ""
    left_indent_str = " " * left_indent

    for item, descr in table_data:
        if item == "-" and descr == "-":
            formatted_str += "-" * left_column_width + "+" * column_spacing + "-" * right_column_width + "\n"
        elif item == " " and descr == " ":
            formatted_str += "\n"
        else:
            formatted_str += format_term_definition(
                left_indent_str + item,
                left_column_width,
                descr,
                right_column_width,
                column_spacing,
                definition_left_align,
            )
    return formatted_str


if __name__ == "__main__":
    import doctest

    doctest.testmod()
