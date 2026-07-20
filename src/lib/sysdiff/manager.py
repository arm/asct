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
import os
import pandas as pd
from collections import defaultdict
import asct.core.logger as log
from asct.core.sysdiff.display import print_simple_table, MISSING, print_summary
from asct.core.sysdiff.registry import get_rules, get_display
from asct.core.sysdiff.loader import RecipeRunLoader
from asct.core.managers.ubench_multi_reporter import get_multi_reporter
import pathlib


def abs_sort_func(x):
    """Sort by absolute values."""
    try:
        x = x.removesuffix("%")  # Remove % for percentage values
        return abs(float(x)) if x != "<same as baseline>" else -1
    except (ValueError, TypeError):
        return 0


class RecipesDiffManager:
    def __init__(self, output_dir: str, run_loaders: list[RecipeRunLoader], sort_by: str = "", ascending: bool = False):
        """Initializes the RecipesDiffManager with a list of RecipeRunLoader instances.
        The first loader in the list is treated as the baseline for comparison.
        Args:
            output_dir (str): Directory to save output files.
            run_loaders (List[RecipeRunLoader]): List of RecipeRunLoader instances to compare.
            sort_by (str, optional): Column name to sort the output DataFrame. Defaults to "".
            ascending (bool, optional): Whether to sort in ascending order. Defaults to False.
        """
        self.run_loaders = run_loaders
        self.baseline = run_loaders[0]
        self.others = run_loaders[1:]
        self._result = None
        self.output_dir = output_dir
        self._grouped = None
        # get the last part of the path for sorting
        self.sort_by = os.path.basename(sort_by) if sort_by else None
        self.ascending = ascending
        self._df = None
        self.name = "RecipesDiffManager"
        self.reporter = get_multi_reporter()
        self.reporter.output_dir = output_dir

    @property
    def result(self) -> dict:
        """
        Returns the result of the diff operation. If the result has not been computed yet,
        it calls `diff_all()` to compute and cache it before returning.
        Returns:
            Any: The result of the diff operation.
        """

        if self._result is None:
            self._result = self.diff_all()
        return self._result

    @staticmethod
    def _apply_rule(rule, baseline: str, other: str, path: str) -> list[dict]:
        """Apply the matching rule's comparator to a and b at the given path."""

        if rule.comparator(baseline, other, path):
            return []  # No differences

        return [{"path": path, "baseline": baseline, "other": other}]

    @staticmethod
    def get_differences(rules: list, a: dict, b: dict) -> list[dict]:
        """Diff two dictionaries a and b using the provided rules."""
        if isinstance(a, dict) and isinstance(b, dict):
            ak, bk = set(a), set(b)
            differences = []
            for k in sorted(ak | bk, key=str):
                va, vb = a.get(k, MISSING), b.get(k, MISSING)
                differences.extend(RecipesDiffManager._apply_rule(rules.get_rule(k), va, vb, k))
            return differences
        raise TypeError("Top-level structures must be dictionaries.")

    def diff_all(self):
        """Compute diffs for all recipes across all runs."""

        # get all the measurement fields
        all_recipes = set(self.baseline.all_recipe_names())
        for r in self.others:
            all_recipes.update(r.all_recipe_names())

        diffs = defaultdict(list)
        for recipe in all_recipes:
            rules = get_rules(recipe)
            base = self.baseline.get_recipe(recipe)
            for run in self.others:
                run_result = run.get_recipe(recipe)
                differences = self.get_differences(rules, base, run_result)
                diffs[recipe].append({
                    "run": run.run_name,
                    "changes": differences,
                })
        return diffs

    @property
    def results_df(self) -> dict:
        """Return a dict of {recipe: DataFrame} with diff rows for each recipe."""

        if self._df is not None:
            return self._df

        self._df = {}
        for recipe, values in self.result.items():
            rows = get_display("default").to_stdout(recipe, values)
            self._df[recipe] = pd.DataFrame(rows)

        return self._df

    def _combined_results_df(self) -> pd.DataFrame:
        """Return a single DataFrame containing all recipe diff rows."""
        result_frames = [df for df in self.results_df.values() if not df.empty]
        if not result_frames:
            return pd.DataFrame()
        return pd.concat(result_frames, ignore_index=True)

    def _sort_df(self, df, base, sort_by=None, ascending=True, sort_func=None, use_delta=False):
        """Sort the DataFrame based on the specified column and order."""

        if df.empty:
            log.debug("No differences found.")
            return df

        # rename columns comparator to value
        if not use_delta:
            df = df.rename(columns={"comparator": "value"})
        else:
            df = df.rename(columns={"delta_percent": "value"})

        # Pivot to wide (runs as columns)
        wide = df.pivot_table(index="field", columns="run", values="value", aggfunc="first")

        # Insert baseline column first
        baseline_series = df.groupby("field")["baseline"].first()
        wide.insert(0, base, baseline_series)

        # Order run columns after baseline
        run_cols = [c for c in wide.columns if c != base]
        preferred = [r.run_name for r in self.others if r.run_name in run_cols]
        remaining = [r for r in sorted(run_cols) if r not in preferred]
        final_cols = [base, *preferred, *remaining]
        wide = wide[final_cols]

        # Fill missing comparison cells
        # ensure that all the runs are present in the columns
        for r in self.others:
            if r.run_name not in wide.columns:
                wide[r.run_name] = "<same as baseline>"

        # Replace NaN with "<same as baseline>" in one step
        wide = wide.fillna("<same as baseline>")
        wide.index.name = "field"

        # Sorting

        if sort_by is None or sort_by == "field":
            wide = wide.sort_index(ascending=ascending)
        elif sort_by in wide.columns:
            sort_by = wide[sort_by].transform(sort_func) if sort_func else wide[sort_by]
            wide = wide.loc[sort_by.sort_values(ascending=ascending).index]

        return wide

    def _compute_summary(self):
        """Compute a summary of the diff results."""
        counts = {}
        total_items = 0
        for recipe, runs in self.result.items():
            n = sum(len(r["changes"]) for r in runs)
            counts[recipe] = n
            total_items += n
        changed = sum(1 for v in counts.values() if v)
        return {
            "total_recipes": len(counts),
            "changed_recipes": changed,
            "top_changed": sorted(((r, c) for r, c in counts.items() if c), key=lambda x: x[1], reverse=True),
        }

    def to_dict(self):
        """Convert the diff results to a dictionary format suitable for JSON serialization."""
        return self._combined_results_df().to_dict(orient="records")

    def to_csv_str(self):
        """Returns the diff results as a CSV string."""
        return self._combined_results_df().to_csv()

    def to_json_str(self):
        """Returns the diff results as a JSON string."""
        return json.dumps(self.to_dict())

    def to_stdout(self):
        """Print results to stdout with optional DataFrame sorting."""

        base_name = self.baseline.run_name

        # Summary (high-level)
        print_summary(base_name, self._compute_summary())

        results_by_recipe = self.results_df
        if not results_by_recipe or all(df.empty for df in results_by_recipe.values()):
            log.debug("\nNo differences found.")
            return

        # report recipes: show changes side by side without delta% since they may not be numeric
        report_recipe = ["system-info", "sysreg", "cmn", "ucie", "dms", "pss"]

        # Main (non-special) recipes: show delta%
        measurement_recipes = {r: v for r, v in self.result.items() if r not in (*report_recipe, "metadata")}

        # Show report recipes first with side-by-side values (no delta%)
        for report in report_recipe:
            spec_df = results_by_recipe.get(report, pd.DataFrame())
            if not spec_df.empty:
                table = self._sort_df(spec_df, base_name)
                if not table.empty:
                    title = f"Differences in {report}"
                    print_simple_table(title, table)

        # Show main recipes with delta percentage
        main_dfs = [df for r, df in results_by_recipe.items() if r in measurement_recipes and not df.empty]
        if main_dfs:
            main_df = pd.concat(main_dfs, ignore_index=True)
            title = f"Measurement delta percentage between {base_name} and comparison runs"
            table = self._sort_df(
                main_df,
                base_name,
                sort_by=self.sort_by,
                ascending=False,
                sort_func=abs_sort_func,
                use_delta=True,
            )
            if self.sort_by:
                title += f" (sorted by {self.sort_by})"
            print_simple_table(title, table)

        # Print metadata table at the end
        meta_df = results_by_recipe.get("metadata", pd.DataFrame())
        if not meta_df.empty:
            table = self._sort_df(meta_df, base_name)
            if not table.empty:
                title = "Differences in metadata"
                print_simple_table(title, table)

        # Graph results
        self.graph()

    def serialize(self):
        return {"sysdiff": self.result}

    def cache_results(self):
        """Dummy Cache the diff results to a file."""
        return

    def graph(self):
        """Graph results using the raw data from each run."""
        graph_df = defaultdict(list)
        for loader in self.run_loaders:
            for recipe in loader.recipes:
                data = loader.raw_data.get(recipe, None)
                display = get_display(recipe)
                graph_df[recipe].append(display.to_df(recipe, loader.run_name, data))

        for recipe, labeled_dfs in graph_df.items():
            if not labeled_dfs:
                continue
            try:
                self.reporter.plot_results(labeled_dfs, recipe_name=recipe)
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                log.warning(f"unable to generate diff plot for '{recipe}': {exc}")


if __name__ == "__main__":
    # Example: python diff_manager_modular.py asct.json asct1.json asct2.json
    import sys

    output_dir = "./"
    run_loaders = [RecipeRunLoader(p, [], []) for p in sys.argv[1:]]
    diff_manager = RecipesDiffManager(output_dir, run_loaders)
    diff_manager.to_stdout()
    pathlib.Path(f"{output_dir}/diff_results.json").write_text(diff_manager.to_json_str())
    pathlib.Path(f"{output_dir}/diff_results.csv").write_text(diff_manager.to_csv_str())
