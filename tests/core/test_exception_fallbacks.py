# ---------------------------------------------------------------------------------
# SPDX-FileCopyrightText: Copyright (C) 2026 Arm Limited and/or its affiliates
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

import pytest

from asct.core.sysdiff.comparators import NumericToleranceComparator
from asct.core.sysdiff.display import RecipeDisplay
from asct.core.utility import files


def test_read_json_file_returns_none_for_invalid_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not-json")

    assert files.read_json_file(path) is None


def test_read_json_stdout_returns_none_for_invalid_input():
    assert files.read_json_stdout(object()) is None
    assert files.read_json_stdout("{not-json") is None


def test_write_to_file_exits_for_oserror(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.open", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(SystemExit):
        files.write_to_file(str(tmp_path / "out.json"), "{}", "w")


def test_recipe_display_non_numeric_fallbacks():
    assert RecipeDisplay.get_delta("before", "after") == ("changed", "N/A")
    assert RecipeDisplay.get_delta("0", "1") == ("changed", "N/A")
    assert RecipeDisplay.round_if_numeric("abc") == "abc"


def test_numeric_tolerance_comparator_non_numeric_fallback():
    comparator = NumericToleranceComparator(abs_tolerance=1)

    assert comparator("same", "same", "recipe.field") is True
    assert comparator("left", "right", "recipe.field") is False
