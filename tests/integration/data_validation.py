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


def accept_none(f, is_bare_metal):
    # On bare metal we expect all fields to be filled, so we don't 'accept none'
    if is_bare_metal:
        return f

    def skip_check_for_none(x, n):
        if x is not None:
            f(x, n)

    return skip_check_for_none


def is_str(x, n):
    assert type(x) is str, f"Type check str failed for {n} = {x}"


def is_int(x, n):
    assert type(x) is int, f"Type check int failed for {n} = {x}"


def is_float(x, n):
    assert type(x) is float, f"Type check float failed for {n} = {x}"


def is_bool(x, n):
    assert type(x) is bool, f"Type check bool failed for {n} = {x}"


def is_list(x, n):
    assert type(x) is list, f"Type check list failed for {n} = {x}"


def is_dict(x, n):
    assert type(x) is dict, f"Type check dict failed for {n} = {x}"


def is_value(value):
    def check_value(x, n):
        assert type(x) is type(value), f"Value type check failed for {n} = {x}, found {type(x)}, expected {type(value)}"
        assert x == value, f"Value check failed for {n} = {x} != {value}"

    return check_value


def is_float_str(x, n):
    try:
        float(x)
    except ValueError as err:
        raise AssertionError(f"Value {x} at {n} could not be converted to float") from err


def is_int_str(x, n):
    try:
        int(x)
    except ValueError as err:
        raise AssertionError(f"Value {x} at {n} could not be converted to int") from err


def _json_dfs_check(reference_root, checked_root, path):
    """Validates a dict resulting from a JSON based on a reference dict. The values from the
    reference dict can be:
        none: no check will be done on the checked dict's value
        a function: the function will be called on the checked dict's value at the same position in the dict
        an actual value: the value will be compared with the value in the checked dict at the same position
    """
    for key, ref in reference_root.items():
        full_path = f"{path}[{key}]"
        assert key in checked_root, f"Output JSON doesn't contain the key {full_path}"
        if type(ref) is dict:
            assert type(checked_root[key]) is dict, f"Invalid type for {full_path}: {type(checked_root)}"
            _json_dfs_check(ref, checked_root[key], full_path)
        elif callable(ref):
            ref(checked_root[key], full_path)
        elif ref is not None:
            assert ref == checked_root[key], (
                f"Values differ for key {full_path}: ref '{ref}' - checked '{checked_root[key]}'"
            )


def validate_json(reference_json, checked_json):
    _json_dfs_check(reference_json, checked_json, "")


def _validate_array_data(reference_data, checked_data, data_format):
    assert len(reference_data) == len(checked_data), (
        f"Reference {data_format} has a different number of "
        f"lines ({len(reference_data)}) compared to the checked {data_format} ({len(checked_data)})\n"
        f"checked_data: {checked_data}\nreference_data: {reference_data}"
    )
    for line_idx, ref_line in enumerate(reference_data):
        checked_line = checked_data[line_idx]
        assert len(ref_line) == len(checked_line), (
            f"Reference {data_format} line {line_idx} has a different number of "
            f"columns '({len(ref_line)}) compared to the checked {data_format} ({len(checked_line)})\n"
            f"checked_data: {checked_data}\nreference_data: {reference_data}"
        )
        for col_idx, ref_val in enumerate(ref_line):
            if callable(ref_val):
                ref_val(checked_line[col_idx], f"line: {line_idx}, col: {col_idx}")
            elif ref_val is not None:
                assert ref_val == checked_line[col_idx], (
                    f"Values differ at line: {line_idx}, col: {col_idx}: "
                    f"ref '{ref_val}' - checked '{checked_line[col_idx]}'\n"
                    f"checked_data: {checked_data}\nreference_data: {reference_data}"
                )


def validate_csv(reference_csv, checked_csv):
    _validate_array_data(reference_csv, checked_csv, "csv")


################################
# STDOUT table parsing functions
################################


def _get_column_data_size(line_data, column):
    """Scans a columns of characters (ignoring header), returns how many are non-blank"""
    return len([line[column] for line in line_data[1:] if line[column] != " "])


def _find_first_column_with_data_size(line_data, start_index, data_size):
    """Scans the line data right to left starting at column start_index and finds the first
    column which data_size non-blank characters on all lines (except header which can be blank)
    """
    for col in range(start_index, -1, -1):
        if _get_column_data_size(line_data, col) == data_size:
            return col
    return -1


def _find_last_column_with_any_data(line_data, start_column, end_column):
    """Scans the line data left to right and finds the last column of characters which has at least one
    non blank character"""
    last_column = -1
    for col in range(start_column, end_column + 1):
        if _get_column_data_size(line_data, col) > 0:
            last_column = col
        else:
            break
    return last_column


def _extract_rightmost_column_bounds(line_data, end_index):
    """Tries to determine the begin and end index of the table column starting at end_index"""
    header = line_data[0]
    initial_end_index = end_index
    # Find beginning of table column (first column of characters that has only non-blank chars)
    end_index = _find_first_column_with_data_size(line_data, end_index, len(line_data) - 1)
    if end_index < 0:
        return None, None

    has_blank_header = header[end_index] == " "
    # Tiny hack, a blank header is always on the first column
    if has_blank_header:
        # First column is left-aligned for some reason, so
        # adjust end_index to account for that
        return (0, _find_last_column_with_any_data(line_data, end_index, initial_end_index))

    # Find end of data portion of the table column (first column of characters that is all blanks)
    start_index = _find_first_column_with_data_size(line_data, end_index, 0)
    if start_index < 0:
        return (0, end_index)

    # Find beginning of next table column (first column of characters that has only non-blank chars)
    start_index = _find_first_column_with_data_size(line_data, start_index, len(line_data) - 1)
    if start_index < 0:
        return (0, end_index)
    has_blank_header = header[start_index] == " "
    # Another tiny hack, a blank header is always on the first column which is left-aligned, unlike the others
    # and we landed towards the beginning of the first column instead of at the end of a regular column,
    # we need to adjust start_index
    if has_blank_header:
        return (_find_last_column_with_any_data(line_data, start_index, end_index) + 1, end_index)
    return (start_index + 1, end_index)


def _get_column_bounds(line_data):
    end_index = len(line_data[0]) - 1
    bounds = []
    while end_index >= 0:
        start, end = _extract_rightmost_column_bounds(line_data, end_index)
        if start is None:
            return bounds
        bounds = [(start, end), *bounds]
        end_index = start - 1
    return bounds


def _extract_stdout_table_data(line_data):
    """Parses an array of stdout lines which contain a table and return the data as a 2d array.
    Stops on the first empty line.

    For example:
    item = "        Traffic type  Peak BW (GB/s)
    0          ALL Reads           185.9
    1   3:1 Reads-Writes           161.8
    2   2:1 Reads-Writes           158.1
    3   1:1 Reads-Writes           153.6
    4  Stream-triad-like           119.5
    "

    extract_stdout_table_data(item.splitlines())
    [['', 'Traffic type', 'Peak BW (GB/s)'],
     ['0', 'ALL Reads', '185.9'],
     ['1', '3:1 Reads-Writes', '161.8'],
     ['2', '2:1 Reads-Writes', '158.1'],
     ['3', '1:1 Reads-Writes', '153.6'],
     ['4', 'Stream-triad-like', '119.5']]
    """
    # Find the end of the table (first line without content)
    table_end_idx = -1
    for idx, line in enumerate(line_data):
        if not line.strip():
            table_end_idx = idx
            break
    if table_end_idx == -1:
        table_end_idx = len(line_data)
    line_data = line_data[:table_end_idx]

    table_data = []
    column_bounds = _get_column_bounds(line_data)
    for line in line_data:
        table_data += [[line[start : end + 1].strip() for start, end in column_bounds]]
    return table_data


def extract_stdout_table(stdout, table_name):
    """Search for a table name in stdout data, parses it and returns the data as a 2d array"""
    line_data = stdout.splitlines()
    for idx, line in enumerate(line_data):
        if line.strip() == table_name:
            return _extract_stdout_table_data(line_data[idx + 2 :])
    return None


def validate_stdout(reference_table_data, table_data):
    _validate_array_data(reference_table_data, table_data, "stdout")
