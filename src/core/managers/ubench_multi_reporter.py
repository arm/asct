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

import os
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from asct.core.managers.ubench_reporter import UbenchReporter, log

__all__ = ["MultiUbenchReporter", "get_multi_reporter"]


def get_multi_reporter():
    return MultiUbenchReporter()


class MultiUbenchReporter(UbenchReporter):
    """Multi dataset variant of UbenchReporter.

    Each plotting method mirrors the original single-DF signature except that
    the first argument after `self` is now a list of (label, df) tuples.
    """

    def plot_results(self, labeled_dfs, recipe_name, acceptable_increase=0.15):
        """Plot results for a given recipe using the appropriate method."""

        if not labeled_dfs or not any(isinstance(df, pd.DataFrame) and not df.empty for _, df in labeled_dfs):
            log.debug(f"No valid dataframes to plot for {recipe_name}. Skipping.")
            return

        if recipe_name == self.LATENCY_SWEEP_TYPE:
            labeled_dfs = [(label, self._rename_latency_sweep_df_columns(df)) for label, df in labeled_dfs]
            latency_metrics = self._pick_latency_schemas(labeled_dfs)
            for latency_metric, latency_unit in latency_metrics:
                self.plot_latency_sweep_results(labeled_dfs, latency_metric, latency_unit)

            # Misses plot for all provided dataframes
            self.plot_misses(labeled_dfs, self.LATENCY_SWEEP_TYPE)
        elif recipe_name == self.BANDWIDTH_SWEEP_TYPE:
            rate_units = self._pick_bandwidth_sweep_rate_units(labeled_dfs)
            for idx, rate_unit in enumerate(rate_units):
                self.plot_bandwidth_sweep_results(labeled_dfs, rate_unit, idx == 0)
        elif recipe_name == self.LOADED_LATENCY_TYPE:
            latency_units = self._pick_loaded_latency_units(labeled_dfs)
            for latency_unit in latency_units:
                self.plot_loaded_latency_results(labeled_dfs, latency_unit, acceptable_increase)
        else:
            log.debug(f"Skipping unknown plot type: {recipe_name}")

    @staticmethod
    def _pick_latency_schemas(labeled_dfs):
        has_cycle = all("average_latency_cyc" in df.columns for _, df in labeled_dfs)
        has_lat_ns = all("average_latency_ns" in df.columns for _, df in labeled_dfs)

        metric_names = []

        if has_cycle:
            metric_names.append(("average_latency_cyc", "cycle"))

        # One or the other, should not have both
        if has_lat_ns:
            metric_names.append(("average_latency_ns", "ns"))

        if not metric_names:
            raise ValueError(
                "Mixed latency units detected across datasets. Use a consistent setting: "
                "either all cycle-based (cycle_base=true) or all nanosecond-based (cycle_base=false)."
            )

        return metric_names

    @staticmethod
    def _rename_latency_sweep_df_columns(df):
        """Normalize legacy latency-sweep columns for mixed-version plotting."""
        if "average_latency_ns" not in df.columns and "average_latency" in df.columns:
            df = df.rename(columns={"average_latency": "average_latency_ns"})
        return df

    @staticmethod
    def _pick_loaded_latency_units(labeled_dfs):
        has_cycle = all("Loaded latency [cycle]" in df.columns for _, df in labeled_dfs)
        has_ns = all("Loaded latency [ns]" in df.columns for _, df in labeled_dfs)

        unit_names = []

        if has_cycle:
            unit_names.append("cycle")
        if has_ns:
            unit_names.append("ns")

        if not unit_names:
            raise ValueError(
                "Mixed loaded-latency units detected across datasets. Use a consistent setting: "
                "either all cycle-based (cycle_base=true) or all nanosecond-based (cycle_base=false)."
            )
        return unit_names

    @staticmethod
    def _pick_bandwidth_sweep_rate_units(labeled_dfs):
        units = set()
        unit_to_column_name_map = {
            "B/cycle": {"total_bandwidth_bpc"},
            "B/s": {"total_bandwidth", "total_bandwidth_mbps"},
        }
        for unit, column_names in unit_to_column_name_map.items():
            if all(any(col in df.columns for col in column_names) for _, df in labeled_dfs):
                units.add(unit)
        if not units:
            raise ValueError(
                "Mixed bandwidth units detected across datasets. Use a consistent setting: "
                "either all cycle-based (cycle_base=true) or all nanosecond-based (cycle_base=false)."
            )
        return list(units)

    @staticmethod
    def _pick_pmu_latency_metric(labeled_dfs, latency_unit):
        metric = f"PMU_rd_latency [{latency_unit}]"
        if all(metric in df.columns for _, df in labeled_dfs):
            return metric
        if all("PMU_lat [ns]" in df.columns for _, df in labeled_dfs):
            return "PMU_lat [ns]"
        return None

    def plot_latency_sweep_results(self, labeled_dfs, latency_metric, latency_unit):
        """Plot latency sweep results for multiple dataframes.

        labeled_dfs: list[tuple[str, pandas.DataFrame]] where each df has the
        columns required by the original single-dataset implementation.
        """
        pmu_latency_metric = self._pick_pmu_latency_metric(labeled_dfs, latency_unit)

        # Use the multi perf data plotter
        self.plot_perf_data(
            labeled_dfs,
            x_metric="sizes",
            y_metric=latency_metric,
            alt_y_metric=pmu_latency_metric,
            ytype=f"Latency per Access [{latency_unit}]",
            result_type=f"{self.LATENCY_SWEEP_TYPE}_{latency_unit}",
            yformatter=self.TIME_FORMATTER,
            log_scale=True,
        )

    def plot_bandwidth_sweep_results(self, labeled_dfs, rate_unit, plot_misses=True):
        """Plot bandwidth results for multiple dataframes.

        Each dataframe must contain at least:
          - sizes
          - total_bandwidth_bpc or total_bandwidth_mbps
        Optionally:
          - PMU_bw [MB/s]
        """
        unit_name = rate_unit.lower().replace("/", "_per_")  # b/sec -> b_per_sec
        converted = []
        for label, df in labeled_dfs:
            df_local = df.copy()
            if rate_unit == "B/cycle":
                if "total_bandwidth_bpc" not in df_local.columns:
                    log.debug("Skipping dataset '%s' (missing 'total_bandwidth_bpc').", label)
                    continue
                df_local["total_bandwidth [B/cycle]"] = df_local["total_bandwidth_bpc"]
            else:
                if "total_bandwidth_mbps" in df_local.columns:
                    df_local["total_bandwidth [B/s]"] = df_local["total_bandwidth_mbps"] * 1e6
                elif "total_bandwidth" in df_local.columns:
                    df_local["total_bandwidth [B/s]"] = df_local["total_bandwidth"] * 1e6
                else:
                    log.debug("Skipping dataset '%s' (missing bandwidth columns for v2/legacy).", label)
                    continue
                if "PMU_bw [MB/s]" in df_local.columns:
                    df_local["PMU_bw [B/s]"] = df_local["PMU_bw [MB/s]"] * 1e6
            converted.append((label, df_local))

        if not converted:
            log.debug("No valid datasets to plot for bandwidth.")
            return

        self.plot_perf_data(
            converted,
            x_metric="sizes",
            y_metric=f"total_bandwidth [{rate_unit}]",
            alt_y_metric=f"PMU_bw [{rate_unit}]",
            ytype=f"Memory Rate [{rate_unit}]",
            result_type=f"{self.BANDWIDTH_SWEEP_TYPE}_{unit_name}",
            yformatter=self.MEMRATE_FORMATTER,
            log_scale=False,
        )

        if plot_misses:
            self.plot_misses(converted, self.BANDWIDTH_SWEEP_TYPE)

    def plot_loaded_latency_results(self, labeled_dfs, latency_unit, acceptable_increase):
        """Multi-dataset version of plot_loaded_latency_results.

        labeled_dfs: list[(label, df)]
        """
        result_type = self.LOADED_LATENCY_TYPE
        peak_bw_column_name = "% of Peak Theoretical BW"
        latency_column_name = f"Loaded latency [{latency_unit}]"
        outfile = os.path.join(self._output_dir, f"{result_type}_{latency_unit}.png")
        all_have_peak_bw = all(peak_bw_column_name in df.columns for _, df in labeled_dfs)
        if not all_have_peak_bw:
            missing = [label for label, df in labeled_dfs if peak_bw_column_name not in df.columns]
            if missing:
                log.debug(
                    "Missing '%s' in datasets %s. Falling back to index-based X-axis.",
                    peak_bw_column_name,
                    missing,
                )

        plt.figure(figsize=(10, 5))

        # Track global minimum latency across datasets
        min_latency = float("inf")

        # Determine axis labeling once (same across datasets)
        if all_have_peak_bw:
            x_label = peak_bw_column_name
            x_formatter = self.PERCENT_FORMATTER
            title = f"Latency per Access [{latency_unit}] vs. % of Peak Theoretical BW"
        else:
            x_label = "Sample index"
            x_formatter = None
            title = f"Latency per Access [{latency_unit}]"

        # Plot each dataset; capture line colors for later vertical markers
        label_colors = {}
        for label, df in labeled_dfs:
            if latency_column_name not in df.columns:
                log.debug("Skipping '%s' (missing column '%s').", label, latency_column_name)
                continue

            if all_have_peak_bw:
                x_values = df[peak_bw_column_name]
            else:
                x_values = range(len(df))

            line = plt.plot(
                x_values,
                df[latency_column_name],
                marker="o",
                linestyle="-",
                label=f"{label}:{latency_column_name}",
            )[0]
            label_colors[label] = line.get_color()

            current_min = df[latency_column_name].min()
            min_latency = min(min_latency, current_min)

        if not (min_latency < float("inf")):
            log.debug("No valid latency data found; aborting plot.")
            plt.close()
            return

        acceptable_latency = min_latency * (1 + acceptable_increase)

        # Horizontal reference lines (global across datasets)
        plt.axhline(
            y=min_latency,
            color="lightgray",
            linestyle="--",
            label=f"Minimum latency ({min_latency:.2f} {latency_unit})",
        )
        plt.axhline(
            y=acceptable_latency,
            color="black",
            linestyle="--",
            label=f"Acceptable latency ({acceptable_increase * 100:.2f}% increase,"
            f" {acceptable_latency:.2f} {latency_unit})",
        )

        # Per-dataset vertical acceptable BW markers (only if using % peak BW axis)
        if all_have_peak_bw:
            for label, df in labeled_dfs:
                if not (latency_column_name in df.columns and peak_bw_column_name in df.columns):
                    continue

                try:
                    # Per-dataset acceptable latency: dataset minimum scaled.
                    dataset_min_latency = df[latency_column_name].min()
                    acceptable_latency_local = dataset_min_latency * (1 + acceptable_increase)

                    latencies = df[latency_column_name].to_numpy()
                    peak_bw_pct = df[peak_bw_column_name].to_numpy()
                    order = np.argsort(latencies)
                    lat_sorted = latencies[order]
                    bw_sorted = peak_bw_pct[order]
                    # Perform interpolation for local acceptable latency.
                    acceptable_peak_bw = float(
                        np.interp(
                            acceptable_latency_local,
                            lat_sorted,
                            bw_sorted,
                            left=bw_sorted[0],
                            right=bw_sorted[-1],
                        )
                    )

                    vcolor = label_colors.get(label, "red")
                    plt.axvline(
                        x=acceptable_peak_bw,
                        color=vcolor,
                        linestyle="--",
                        alpha=0.5,
                        label=f"{label} acceptable % Peak BW ({acceptable_peak_bw:.2f}%)",
                    )
                except (ValueError, TypeError, IndexError) as e:
                    log.debug("Interpolation failed for '%s': %s", label, e)
            plt.xlim(0, 100)

        self.scale_and_label(
            xvar_name=x_label,
            yvar_name=latency_column_name,
            title=title,
            xscale_base=None,
            yscale_base=None,
            legend_loc="upper left",
            xformatter=x_formatter,
            yformatter=self.TIME_FORMATTER,
        )
        self.tighten_and_save(outfile)
        log.info("Generated loaded-latency plot saved to %s", outfile)

    def plot_perf_data(
        self,
        labeled_dfs,
        x_metric,
        y_metric,
        alt_y_metric,
        ytype,
        result_type,
        yformatter=None,
        log_scale=True,
        show_labels=False,
    ):
        """Multi-dataset version of plot_perf_data.

        labeled_dfs: list[(label, df)]
        Other parameters mirror the single-DF version.
        """
        outfile = os.path.join(self._output_dir, f"{result_type}.png")
        plt.figure(figsize=(10, 5))

        # Primary axis lines (y_metric & optional alt_y_metric & optional cluster)
        for label, df in labeled_dfs:
            if x_metric not in df.columns or y_metric not in df.columns:
                log.debug(
                    "Skipping dataset '%s' because required columns (%s, %s) are missing.",
                    label,
                    x_metric,
                    y_metric,
                )
                continue
            plt.plot(
                df[x_metric],
                df[y_metric],
                marker="o",
                linestyle="-",
                label=f"{label}:{y_metric}",
            )
            if alt_y_metric in df.columns:
                plt.plot(
                    df[x_metric],
                    df[alt_y_metric],
                    marker="o",
                    linestyle="-",
                    label=f"{label}:{alt_y_metric}",
                )
            if "y_cluster" in df.columns:
                plt.plot(
                    df[x_metric],
                    df["y_cluster"],
                    marker="o",
                    linestyle="-",
                    label=f"{label}:cluster",
                )
            if show_labels:
                for x, y in zip(df[x_metric], df[y_metric], strict=False):
                    plt.text(x, y, f"{x:.2g}", fontsize=8, ha="right", va="bottom")

        # Scaling & axis formatting identical to original
        self.scale_and_label(
            xvar_name="Data Sizes",
            yvar_name=y_metric,
            title=f"{ytype} vs. Data Sizes",
            xscale_base=2,
            yscale_base=(2 if log_scale else None),
            legend_loc="upper left",
            xformatter=self.MEMSIZE_FORMATTER,
            yformatter=yformatter,
        )

        # Twin axis for percentage difference of alt_y_metric vs y_metric
        any_alt = any(alt_y_metric in df.columns for _, df in labeled_dfs)
        if any_alt:
            ax1 = plt.gca()
            ax2 = ax1.twinx()
            for label, df in labeled_dfs:
                if alt_y_metric in df.columns and y_metric in df.columns:
                    # Avoid division by zero; mask zeros
                    base = df[y_metric]
                    diff = (df[alt_y_metric] - base) / base.replace(0, float("nan")) * 100
                    ax2.plot(df[x_metric], diff, alpha=0.5, marker="x", linestyle="--", label=f"{label} % Diff")
            ax2.set_ylabel("% Difference")
            ax2.legend(loc="upper right")

        self.tighten_and_save(outfile)
        log.info(f"Generated plot saved to {outfile}")

    def plot_misses(self, labeled_dfs, result_type):
        """Multi-dataset version of plot_misses.

        labeled_dfs: list[(label, df)]
        result_type: string used for output naming like original.
        """
        misses_events = ["L1_Rd_Misses", "L2_Rd_Misses", "LL_Rd_Misses"]
        if self.PLOT_TLBMPI:
            misses_events += ["TLB_Misses"]

        # Determine whether any dataframe has valid events & L1_Rd
        any_valid = False
        for _, df in labeled_dfs:
            if "L1_Rd" in df.columns and any(e in df.columns for e in misses_events):
                any_valid = True
                break
        if not any_valid:
            log.debug("No datasets contain required miss columns; skipping misses plot.")
            return

        plt.figure(figsize=(10, 5))
        for label, df in labeled_dfs:
            if "L1_Rd" not in df.columns:
                continue
            valid_events = [e for e in misses_events if e in df.columns]
            for misses_event in valid_events:
                plt.plot(
                    df["sizes"],
                    df[misses_event] / df["L1_Rd"],
                    marker="o",
                    linestyle="-",
                    label=f"{label}:{misses_event} per read",
                )

        self.finish_plot(
            out_png=os.path.join(self._output_dir, f"misses_{result_type}.png"),
            xvar_name="Data Sizes",
            yvar_name="Misses per Memory Access",
            title="Miss events vs. Data Sizes",
            xformatter=self.MEMSIZE_FORMATTER,
        )
