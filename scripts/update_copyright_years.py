#!/usr/bin/env python3

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
Update Arm copyright headers across the repo.

Assumptions:
- Only touch files that already have the standard Arm header block.
- Only rewrite lines that match the exact Arm copyright format:
    "# Copyright (C) YEAR[[-YEAR]]. Arm Limited or its affiliates. All rights reserved."

Behavior:
- Single year less than current:
    2020  -> 2020-2025
- Single year equal to current:
    2025  -> unchanged
- Range ending before current:
    2018-2023 -> 2018-2025
- Range already ending at current:
    2018-2025 -> unchanged
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path

CURRENT_YEAR = datetime.datetime.now(datetime.timezone.utc).date().year

# File extensions we care about
FILE_EXTENSIONS = {".py", ".c", ".cpp", ".h", ".sh"}

# Marker line from the copyright header to avoid touching random stuff
HEADER_MARKER = "SPDX-FileCopyrightText: Copyright (C)"

# Match the Arm-style copyright line exactly
COPYRIGHT_RE = re.compile(
    r"^(?P<prefix>\s*# Copyright \(C\) )"
    r"(?P<year_start>\d{4})"
    r"(?:-(?P<year_end>\d{4}))?"
    r"(?P<suffix>\. Arm Limited and\/or its affiliates\.)\s*$"
)


def is_extensionless_script(path: Path) -> bool:
    """
    Treat files with no suffix as scripts if they begin with a shebang (#!).
    """
    if path.suffix:
        return False

    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            first_line = f.readline()
    except OSError:
        return False

    return first_line.startswith("#!")


def compute_new_year_segment(year_start: int, year_end: int | None) -> str | None:
    """
    Given the existing year or year-range, decide what the new year segment should be.

    Returns:
        - A new year/year-range string (e.g. "2018-2025") if it should change.
        - None if no change is needed or we decide not to touch it.
    """
    # Single year
    if year_end is None:
        if year_start == CURRENT_YEAR:
            # Already correct: "Copyright (C) CURRENT_YEAR."
            return None
        if year_start < CURRENT_YEAR:
            # Origin year -> origin-current
            return f"{year_start}-{CURRENT_YEAR}"
        # Future or weird - leave it alone
        return None

    # Range: year_start-year_end
    if year_end >= CURRENT_YEAR:
        # Already at or beyond current year; don't touch
        return None

    if year_start > CURRENT_YEAR:
        # Nonsense range like 2030-2040 in 2025; skip
        return None

    # Normal case: 2018-2023 -> 2018-2025
    return f"{year_start}-{CURRENT_YEAR}"


def update_file(path: Path) -> bool:
    """
    Update the copyright line in a single file if needed.

    Returns True if the file was modified.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    # Only look near the top
    max_scan = min(40, len(lines))
    head = lines[:max_scan]

    # Bail if the Arm header marker isn't even present
    if not any(HEADER_MARKER in line for line in head):
        return False

    changed = False

    for i in range(max_scan):
        m = COPYRIGHT_RE.match(lines[i])
        if not m:
            continue

        year_start = int(m.group("year_start"))
        year_end_str = m.group("year_end")
        year_end = int(year_end_str) if year_end_str is not None else None

        new_year_segment = compute_new_year_segment(year_start, year_end)
        if new_year_segment is None:
            # Nothing to do
            break

        new_line = f"{m.group('prefix')}{new_year_segment}{m.group('suffix')}"
        if new_line != lines[i]:
            lines[i] = new_line
            changed = True
        break  # Only touch the first matching copyright line

    if changed:
        # Preserve trailing newline if it existed
        new_text = "\n".join(lines)
        if text.endswith("\n"):
            new_text += "\n"
        path.write_text(new_text, encoding="utf-8")

    return changed


def main() -> int:
    root = Path.cwd()
    updated: list[Path] = []

    for file in root.rglob("*"):
        if not file.is_file():
            continue
        # Accept known extensions OR extensionless scripts with a shebang
        if file.suffix not in FILE_EXTENSIONS and not is_extensionless_script(file):
            continue

        try:
            if update_file(file):
                updated.append(file.relative_to(root))
        except (OSError, UnicodeError) as exc:
            print(f"Error processing {file}: {exc}")

    if updated:
        print("Updated copyright headers in:")
        for f in updated:
            print(f"  {f}")
    else:
        print("No files needed updating.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
