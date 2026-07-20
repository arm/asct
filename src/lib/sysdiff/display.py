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

import json
import textwrap

import pandas as pd
import asct.core.logger as log


# --- Types ---
MISSING = "<missing>"
SPACE = "     "


class RecipeDisplay:
    @classmethod
    def get_delta(cls, baseline: str, comparator: str) -> str:
        """Compute absolute and percent delta between a and b, handling MISSING and errors."""
        percent_delta = None
        typ = (
            "changed"
            if baseline != MISSING and comparator != MISSING
            else ("added" if baseline == MISSING else "removed")
        )
        try:
            delta = round(float(comparator) - float(baseline), 2)
            percent_delta = round((delta / float(baseline)) * 100, 2)
        except (TypeError, ValueError, ZeroDivisionError):
            delta = typ

        return str(delta), f"{percent_delta}%" if percent_delta is not None else "N/A"

    @classmethod
    def round_if_numeric(cls, val) -> str:
        """If val is numeric (int or float), round it appropriately. Otherwise return as string."""
        try:
            return str(round(val, 2) if "." in str(val) else int(val))
        except (TypeError, ValueError):
            return str(val)

    def get_field(self, recipe: str, run: str, baseline: str, comparator: str, path: str) -> dict:
        """Format a single diff field for display.
        Args:
            recipe (str): Recipe name.
            run (str): Run name.
            baseline (str): Baseline value.
            comparator (str): Comparator value.
            path (str): Field path.
        Returns:
            dict: A dictionary with formatted diff information."""

        path_var = path.replace(recipe + ".", "")
        delta, delta_percent = RecipeDisplay.get_delta(baseline, comparator)
        # for a and b round if numeric
        baseline = RecipeDisplay.round_if_numeric(baseline)
        comparator = RecipeDisplay.round_if_numeric(comparator)

        return {
            "field": f"{recipe}.{path_var}",
            "recipe": recipe,
            "run": run,
            "comparator": str(comparator),
            "delta": delta,
            "delta_percent": delta_percent,
            "baseline": str(baseline),
        }

    def get_rows(self, recipe: str, diff_result: list) -> list[list[str]]:
        """Convert diff results into a list of rows for display.
        Args:
            recipe (str): Recipe name.
            diff_result (list): List of diff results for the recipe.
        Returns:
            List[List[str]]: A list of rows, each row is a list of string values.
        """
        rows = []
        for run in diff_result:
            differences = run.get("changes", [])
            rows.extend(
                self.get_field(recipe, run["run"], entry["baseline"], entry["other"], entry["path"])
                for entry in differences
            )
        return rows

    def to_json_str(self, recipe: str, diff_result: list) -> str:
        """Convert diff results to a JSON string.
        Args:
            recipe (str): Recipe name.
            diff_result (list): List of diff results for the recipe.
        Returns:
            str: JSON string representation of the diff results.
        """
        log.debug(f"Diff result for JSON output: {diff_result}")
        rows = self.get_rows(recipe, diff_result)
        return json.dumps(rows, indent=2)

    def to_csv(self, recipe: str, diff_result: list) -> list:
        """Returns rows for CSV output."""
        log.debug(f"Diff result for CSV output: {diff_result}")
        return self.get_rows(recipe, diff_result)

    def to_stdout(self, recipe: str, diff_result: list) -> list:
        """Returns rows for stdout output."""
        log.debug(f"Diff result for stdout output: {diff_result}")
        return self.get_rows(recipe, diff_result)

    def filter_graph_data(self, data):
        """Return the subset of raw_data to graph. Override in subclasses for recipe-specific filtering."""
        return data

    def to_df(self, recipe, run_name, data: list) -> tuple[str, pd.DataFrame]:
        """Convert recipe result data to a DataFrame."""
        result = (run_name, pd.DataFrame())
        try:
            if isinstance(data, str):
                parsed = json.loads(data)
            else:
                parsed = data
            parsed = self.filter_graph_data(parsed)
            df = pd.DataFrame(parsed)
            result = (run_name, df)
        except (json.JSONDecodeError, ValueError) as e:
            log.debug(f"Failed to parse data for {recipe} in run {run_name}: {e}")
        except (TypeError, KeyError, AttributeError) as e:
            log.debug(f"Unexpected error processing data for {recipe} in run {run_name}: {e}")
        return result


def print_wrapped_row(row_values, widths):
    """Print a single row with text wrapping for each column based on specified widths."""
    # Wrap each field to its column width, limit to 10 lines
    wrapped = [textwrap.wrap(str(val), width=w) or [""] for val, w in zip(row_values, widths, strict=False)]
    max_lines = min(max(len(col) for col in wrapped), 10)

    for i in range(max_lines):
        line = " | ".join((col[i] if i < len(col) else "").ljust(widths[j]) for j, col in enumerate(wrapped))
        print(line)

    # Print ellipsis if any column was truncated
    if any(len(col) > 10 for col in wrapped):
        print(" | ".join(("…" if len(col) > 10 else "").ljust(widths[j]) for j, col in enumerate(wrapped)))


def print_simple_table(title: str, df: pd.DataFrame, field_width: int = 55, base_width: int = 20, run_width: int = 20):
    """Short wrapper: fixed widths, left align, wrap 10 lines, ellipsis if truncated (same as _ variant)."""
    if df.empty:
        return

    df_disp = df.copy()
    df_disp.index = df_disp.index.astype(str).str.replace(".result.", ".", regex=False)

    # set up headers
    headers = ["field", *df_disp.columns]

    # calculate column widths
    widths = [field_width, base_width] + [run_width] * (len(df_disp.columns) - 1)
    sep_len = sum(widths) + 3 * (len(widths) - 1)
    top = "=" * sep_len
    mid = "-" * sep_len

    if title:
        print(f"\n\n{title.title()}")

    # print header
    print(top)
    print_wrapped_row(headers, widths)
    print(top)

    # print rows
    for idx, row in df_disp.iterrows():
        print_wrapped_row([idx] + [str(row[c]) for c in df_disp.columns], widths)
        print(mid)


def print_summary(baseline_run_name, summary, top_n=10):
    """Print a summary of the diff results."""

    print("\nSummary")
    print("=" * 40)
    print(f"{'Stat':<20} | {'Value':<18}")
    print("=" * 40)
    print(f"{'Baseline':<20} | {baseline_run_name:<18}")
    print(f"{'Total # of Benchmarks':<20} | {summary['total_recipes']:<18}")
    print("=" * 40)

    # Top changed benchmarks
    top = summary.get("top_changed", [])[:top_n]
    if top:
        print("\nBenchmarks with Most Differences")
        print("=" * 40)
        print(f"{'Benchmark':<20} | {'Differences':<18}")
        print("=" * 40)
        for bench, diff in top:
            print(f"{bench:<20} | {diff:<18}")
        print("=" * 40)
    else:
        print("\nNo changes detected.")
