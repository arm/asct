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

from types import SimpleNamespace

import pandas as pd
import pytest

from asct.core.sysdiff.manager import RecipesDiffManager


def test_get_differences_rejects_non_dict_inputs():
    with pytest.raises(TypeError, match="Top-level structures must be dictionaries"):
        RecipesDiffManager.get_differences(rules=None, a=[], b={})


def test_to_stdout_skips_empty_sorted_report_and_metadata_tables(monkeypatch):
    manager = RecipesDiffManager.__new__(RecipesDiffManager)
    manager.baseline = SimpleNamespace(run_name="baseline")
    manager.others = []
    manager.sort_by = None
    manager.reporter = SimpleNamespace(graph=lambda *_args, **_kwargs: None)
    manager.graph = lambda: None
    manager._compute_summary = lambda: {"total_recipes": 2, "changed_recipes": 2, "top_changed": []}
    manager._result = {
        "system-info": [{"run": "run_b", "changes": [{"path": "x", "baseline": 1, "other": 2}]}],
        "metadata": [{"run": "run_b", "changes": [{"path": "y", "baseline": 1, "other": 2}]}],
    }
    manager._df = {
        "system-info": pd.DataFrame([{"field": "x", "baseline": "1", "run": "run_b", "comparator": "2"}]),
        "metadata": pd.DataFrame([{"field": "y", "baseline": "1", "run": "run_b", "comparator": "2"}]),
    }

    printed_titles = []
    monkeypatch.setattr("asct.core.sysdiff.manager.print_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "asct.core.sysdiff.manager.print_simple_table",
        lambda title, _table: printed_titles.append(title),
    )
    monkeypatch.setattr(manager, "_sort_df", lambda *_args, **_kwargs: pd.DataFrame())

    manager.to_stdout()

    assert printed_titles == []
