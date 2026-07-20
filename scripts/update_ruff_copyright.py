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

import datetime
import pathlib
import re

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
PYPROJECT = PROJECT_ROOT / "pyproject.toml"

BEGIN_MARKER = "# BEGIN AUTO-GENERATED RUFF COPYRIGHT"
END_MARKER = "# END AUTO-GENERATED RUFF COPYRIGHT"


def build_notice_regex() -> str:
    current_year = datetime.datetime.now(datetime.timezone.utc).date().year
    year_pattern = rf"(?:20\d{{2}}-{current_year}|{current_year})"

    header_template = """# ---------------------------------------------------------------------------------
# SPDX-FileCopyrightText: Copyright (C) {YEAR_PATTERN} Arm Limited and/or its affiliates
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
# ---------------------------------------------------------------------------------"""

    # Put a literal marker in the text first
    header = header_template.format(YEAR_PATTERN="{YEAR_PATTERN}")

    # Escape for regex semantics (not TOML)
    header = header.replace("\\", r"\\").replace(".", r"\.").replace("(", r"\(").replace(")", r"\)")

    # Now swap the placeholder with the actual year regex (unescaped)
    header = header.replace("{YEAR_PATTERN}", year_pattern)

    # Anchor at start, multiline + dot-all
    return rf"(?ms)^{header}"


def update_pyproject(pyproject_path: pathlib.Path, pattern: str) -> None:
    text = pyproject_path.read_text(encoding="utf-8")

    block = f"{BEGIN_MARKER}\n[tool.ruff.lint.flake8-copyright]\nnotice-rgx = '''{pattern}'''\n{END_MARKER}"

    regex = re.compile(
        rf"{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}",
        re.DOTALL,
    )

    match = regex.search(text)
    if match:
        # Replace the region manually, no template semantics
        new_text = text[: match.start()] + block + text[match.end() :]
    else:
        # If markers not present, append at end
        new_text = text.rstrip() + "\n\n" + block + "\n"

    pyproject_path.write_text(new_text, encoding="utf-8")


def main() -> int:
    pattern = build_notice_regex()
    update_pyproject(PYPROJECT, pattern)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
