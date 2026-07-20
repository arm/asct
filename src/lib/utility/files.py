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

import json
import sys
import hashlib


import asct.core.logger as log


def write_to_file(filepath: str, data: str, mode: str, fmt: str | None = None):
    """
    Writes data to a file within the 'data/' directory, creates the data/
    directory if it doesn't already exist

        filepath: path of file to write to
        data: string to be written to file

        mode: python open mode e.g. "w" for write, "a" for append
            see https://docs.python.org/3/library/functions.html#open

        fmt: string containing the format used in info message
            e.g. f"{fmt} output written to: ..."

            if None (default), no message is sent to info

    """
    try:
        with open(filepath, mode) as file:
            file.write(data)
    except PermissionError:
        log.critical(
            f"{filepath} already exists, but we don't have permission to edit - please remove before continuing"
        )
        sys.exit(1)
    except OSError as e:
        log.critical(f"[{e}] Error outputting to {filepath}")
        sys.exit(1)

    if fmt:
        log.info(f"{fmt} output written to: {filepath}")


def read_json_file(path):
    try:
        return json.load(open(path, "rt"))
    except (OSError, json.JSONDecodeError) as exc:
        log.error(f"Unable to read JSON from {path}: {exc}")
        return None


def read_json_stdout(output):
    try:
        return json.loads(output)
    except (TypeError, json.JSONDecodeError) as exc:
        log.error(f"Unable to read JSON from output: {exc}")
        return None


def hash_saved_recipe_files(file_payloads: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for filename in sorted(file_payloads):
        digest.update(filename.encode())
        digest.update(b"\0")
        digest.update(file_payloads[filename])
        digest.update(b"\0")
    return digest.hexdigest()
