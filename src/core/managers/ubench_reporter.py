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
import re
import matplotlib.pyplot as plt
from matplotlib import ticker
import json
import pandas as pd
import seaborn as sns
from asct.core.utility.format import memsize_str
from asct.core.datatypes import ASCTSingleton
from scipy.interpolate import interp1d
from asct.core import logger as log
import itertools


__all__ = ["get_reporter"]


def get_reporter():
    return UbenchReporter()


class UbenchReporter(metaclass=ASCTSingleton):
    PLOT_TLBMPI = False
    LATENCY_SWEEP_TYPE = "latency-sweep"
    LATENCY_PRESWEEP_TYPE = "latency-presweep"
    LATENCY_SWEEP_SUMMARY_TYPE = "latency-sweep-summary"
    BANDWIDTH_SWEEP_TYPE = "bandwidth-sweep"
    LOADED_LATENCY_TYPE = "loaded-latency"
    MEMSIZE_FORMATTER = plt.FuncFormatter(lambda x, _: memsize_str(x, suffix="B", precision=0))
    MEMRATE_FORMATTER = plt.FuncFormatter(lambda x, _: memsize_str(x, suffix="B", precision=1) + "/s")
    IOPS_FORMATTER = plt.FuncFormatter(lambda x, _: f"{x:,.2f} kops")
    TIME_FORMATTER = ticker.ScalarFormatter()
    PERCENT_FORMATTER = ticker.PercentFormatter(xmax=100)

    def __init__(self):
        self._output_dir = None
        self._current_benchmark = None

    @property
    def output_dir(self):
        return self._output_dir

    @output_dir.setter
    def output_dir(self, o):
        self._output_dir = o

    @property
    def current_benchmark(self):
        return self._current_benchmark

    @current_benchmark.setter
    def current_benchmark(self, name):
        self._current_benchmark = name

    def current_benchmark_dir(self):
        """Return (and create) the output subdirectory for the current benchmark."""
        path = os.path.join(self._output_dir, "raw", self._current_benchmark)
        os.makedirs(path, exist_ok=True)
        return path

    def _latency_sweep_dir(self):
        """Return the latency-sweep recipe subdirectory (used for cross-benchmark reads)."""
        return os.path.join(self._output_dir, "raw", self.LATENCY_SWEEP_TYPE)

    def _pmu_dir(self):
        """Return (and create) the pmu_data subdirectory for the current benchmark."""
        path = os.path.join(self.current_benchmark_dir(), "pmu_data")
        os.makedirs(path, exist_ok=True)
        return path

    def cmp_report_generation(self, args):
        pass

    def read_ubench_json_if_exists(self, bench_type):
        json_file = os.path.join(self._latency_sweep_dir(), f"{bench_type}.ubench.json")
        if os.path.exists(json_file):
            return pd.read_json(json_file)
        return None

    def write_ubench_df_to_json(self, df, bench_type):
        df.to_json(os.path.join(self.current_benchmark_dir(), f"{bench_type}.ubench.json"))

    def read_latency_presweep_results(self):
        return self.read_ubench_json_if_exists(self.LATENCY_PRESWEEP_TYPE)

    def write_latency_presweep_results(self, df):
        self.write_ubench_df_to_json(df, self.LATENCY_PRESWEEP_TYPE)

    def read_latency_sweep_results(self):
        return self.read_ubench_json_if_exists(self.LATENCY_SWEEP_TYPE)

    def write_latency_sweep_results(self, df):
        self.write_ubench_df_to_json(df, self.LATENCY_SWEEP_TYPE)

    def read_latency_sweep_summary(self):
        summary_json_file = os.path.join(self._latency_sweep_dir(), f"{self.LATENCY_SWEEP_SUMMARY_TYPE}.ubench.json")
        if os.path.exists(summary_json_file):
            with open(summary_json_file, "r") as f:
                return json.load(f)
        return None

    def write_latency_sweep_summary(self, bench_summary_dict):
        summary_json_path = os.path.join(self.current_benchmark_dir(), f"{self.LATENCY_SWEEP_SUMMARY_TYPE}.ubench.json")
        with open(summary_json_path, "w") as f:
            json.dump(bench_summary_dict, f, indent=4)

    def write_bandwidth_sweep_results(self, df):
        self.write_ubench_df_to_json(df, self.BANDWIDTH_SWEEP_TYPE)

    def plot_test_results(self, explored_x_values, x_values, y_values):
        plt.figure(figsize=(10, 5))
        plt.scatter(x_values, y_values, color="blue", s=10, label="Explored Points")
        self.finish_plot(
            out_png="plateau_exploration.png",
            xvar_name="Data Sizes",
            yvar_name="Cycles per access (power of 2)",
            title="Explored Plateau End Points",
            yscale_base=2,
            xformatter=self.MEMSIZE_FORMATTER,
        )

        # Output first 10 explored x values for verification
        log.debug("First 10 explored x-values: %s", explored_x_values[:10])

    def plot_storage_io_bw_rate(self, combined_df, filename):
        y_vals = ["Read BW (MB/s)", "Write BW (MB/s)"]
        # Note that for fio, MB/s means MiB/s
        # Convert to B/s from MiB/s for plotting
        self.plot_storage_io_data(combined_df, 1024 * 1024, filename, self.MEMRATE_FORMATTER, "Bandwidth", y_vals)

    def plot_storage_io_io_rate(self, combined_df, filename):
        y_vals = ["Read Thruput (kops)", "Write Thruput (kops)"]
        self.plot_storage_io_data(combined_df, 1.0, filename, self.IOPS_FORMATTER, "Thruput", y_vals)

    def plot_storage_io_cpu_util(self, combined_df, filename):
        y_vals = [
            "CPU usr (%)",
            "CPU sys (%)",
            "CPU iowait (%)",
            "CPU irq (%)",
            "CPU soft (%)",
        ]
        self.plot_storage_io_data(combined_df, 1.0, filename, self.PERCENT_FORMATTER, "CPU Util.", y_vals)

    def plot_storage_io_data(self, combined_df, y_scaling, filename, yformatter, y_axis_label, y_vals):
        if not y_vals:
            log.warning("No y-values provided for plotting storage IO data.")
            return

        outfile = os.path.join(self.current_benchmark_dir(), filename)
        plt.figure(figsize=(10, 5))
        bottom = pd.Series(0, index=combined_df.index)

        plotted_any = False
        for y_val in y_vals:
            if y_val not in combined_df.columns:
                log.warning(f"Column '{y_val}' not found in DataFrame. Skipping this value.")
                continue
            plot_values = y_scaling * combined_df[y_val]
            plt.bar(
                combined_df.index,
                plot_values,
                width=0.5,
                bottom=bottom,
                label=self.strip_units(y_val),
            )
            bottom += plot_values
            plotted_any = True

        plt.grid(axis="y", linestyle="--", alpha=0.5)
        if plotted_any:
            plt.xticks(combined_df.index)  # Only show actual data points if any were plotted
            self.scale_and_label(
                xvar_name=combined_df.index.name,
                yvar_name=y_axis_label,
                title=f"{y_axis_label} vs {combined_df.index.name}",
                xscale_base=None,
                yscale_base=None,
                legend_loc="lower center",
                xformatter=None,
                yformatter=yformatter,
                legend_opts={"bbox_to_anchor": (0.5, 1.02), "ncol": len(y_vals), "borderaxespad": 0.0},
            )
            self.tighten_and_save(outfile)
            log.info(f"Generated plot saved to {outfile}")
        else:
            log.warning(f"No valid y-values were plotted; skipping plot generation of {outfile}")

    def strip_units(self, metric_name_with_unit):
        return re.sub(r" \(.+\)$", "", metric_name_with_unit)

    # Also plot the latency distribution CDF with x-axis being latency and y-axis being cumulative probability
    # We will have multiple lines, each line for a block size with data points from mean_percentiles_dict which
    # is a dictionary with key as percentile and value as latency in ns
    def plot_storage_latency_distribution(self, combined_df, mean_latency_ns_percentiles_dict_colname, filename):
        mean_latency_percentile_dicts = combined_df[mean_latency_ns_percentiles_dict_colname]
        if not mean_latency_percentile_dicts.any():
            return
        outfile = os.path.join(self.current_benchmark_dir(), filename)
        plt.figure(figsize=(10, 7))
        for block_size, mean_latency_ns_percentiles_dict in zip(
            combined_df.index, mean_latency_percentile_dicts, strict=False
        ):
            if mean_latency_ns_percentiles_dict is None:
                # Empty percentile data. This can happen for read data of pure write runs, etc.
                continue
            percentiles = sorted(mean_latency_ns_percentiles_dict.keys())
            # Convert latencies to microseconds for plotting
            latencies_us = [mean_latency_ns_percentiles_dict[p] / 1000.0 for p in percentiles]
            plt.plot(latencies_us, percentiles, marker="o", label=f"{combined_df.index.name} {block_size}")

        plt.grid(axis="y", linestyle="--", alpha=0.5)

        self.scale_and_label(
            xvar_name="Latency (us)",
            yvar_name="Cumulative Probability",
            title="Storage I/O Latency Distribution",
            xscale_base=None,
            yscale_base=None,
            legend_loc="lower right",
            xformatter=None,
            yformatter=self.PERCENT_FORMATTER,
        )
        self.tighten_and_save(outfile)
        log.info(f"Generated plot saved to {outfile}")

    def plot_model_graph(self, x_values, y_values):
        plt.figure(figsize=(10, 5))
        plt.plot(x_values, y_values, "b-", label="Piecewise Sigmoid cycles per memory access")
        self.finish_plot(
            out_png="cpm_model.png",
            xvar_name="Data Sizes",
            yvar_name="Cycles per access (power of 2)",
            title="Piecewise Sigmoid Model for Cycles per Memory Access",
            yscale_base=2,
            xformatter=self.MEMSIZE_FORMATTER,
        )

    def finish_plot(
        self,
        out_png,
        xvar_name,
        yvar_name,
        title,
        yscale_base=None,
        xformatter=None,
        yformatter=None,
        legend_loc="upper left",
    ):
        self.scale_and_label(
            xvar_name,
            yvar_name,
            title,
            xscale_base=2,
            yscale_base=yscale_base,
            legend_loc=legend_loc,
            xformatter=xformatter,
            yformatter=yformatter,
        )
        self.tighten_and_save(out_png)

    def scale_and_label(
        self,
        xvar_name,
        yvar_name,
        title,
        xscale_base,
        yscale_base,
        legend_loc=None,
        xformatter=None,
        yformatter=None,
        legend_opts=None,
        ylim_headroom=0.05,
        title_pad=40,
        n_minor_per_major=4,
    ):
        if xscale_base:
            plt.xscale("log", base=xscale_base)
            xmin, x_max = plt.gca().get_xlim()
            x_major = [t for t in plt.gca().xaxis.get_majorticklocs() if xmin <= t <= x_max]
            # for log xscale, show minor ticks between each major pair at equal log intervals.
            x_minor = [
                left + (right - left) * frac
                for left, right in itertools.pairwise(x_major)
                for frac in (i / (n_minor_per_major + 1) for i in range(1, n_minor_per_major + 1))
            ]
            plt.gca().set_xticks(x_minor, minor=True)
            plt.gca().xaxis.set_minor_formatter(ticker.NullFormatter())
            plt.gca().xaxis.grid(which="minor", color="#e8e8e8", alpha=0.9, linewidth=0.8)

        if yscale_base:
            plt.yscale("log", base=yscale_base)
        if xformatter is not None:
            plt.gca().xaxis.set_major_formatter(xformatter)
        if yformatter is not None:
            plt.gca().yaxis.set_major_formatter(yformatter)
        plt.xlabel(xvar_name)
        plt.ylabel(yvar_name)
        plt.title(title, pad=title_pad)
        ymin, ymax = plt.gca().get_ylim()
        plt.gca().set_ylim(ymin, ymax + (ymax - ymin) * ylim_headroom)
        legend_kwargs = dict(legend_opts or {})
        if legend_loc is not None:
            legend_kwargs.setdefault("loc", legend_loc)  # Set default location if not provided in legend_opts
        plt.gca().legend(**legend_kwargs)
        plt.grid(True)

    def tighten_and_save(self, out_png, title_space=0.97):
        plt.tight_layout(rect=[0, 0, 1, title_space])  # Leave space for title
        plt.savefig(out_png)
        plt.close()

    def plot_modeled_misses(self, x_values, L1DMPI, L2MPI, LLMPI):
        plt.figure(figsize=(10, 5))
        plt.plot(x_values, L1DMPI, "-", label="L1DMPI")
        plt.plot(x_values, L2MPI, "-", label="L2MPI")
        plt.plot(x_values, LLMPI, "-", label="LLMPI")

        self.finish_plot(
            out_png=os.path.join(self._pmu_dir(), "misses_model.png"),
            xvar_name="Data Sizes",
            yvar_name="Misses Per Instruction (MPI)",
            title="L1DMPI, L2MPI, and LLMPI Sigmoid Models",
            xformatter=self.MEMSIZE_FORMATTER,
        )

    def report_results_box(self, dfs, log_scale=True, comparison_label=None):
        # combined_df = pd.concat(dfs, keys=range(len(dfs)), names=['run', 'index'])
        combined_df = pd.concat(dfs)
        combined_df.reset_index(level=0, inplace=True)

        ylabel_suffix = "(%diff)" if comparison_label else ""
        title_suffix = f" ({comparison_label})" if comparison_label else ""

        plt.figure(figsize=(10, 5))
        sns.boxplot(x="sizes", y="cycles_per_rep", data=combined_df)
        self.finish_plot(
            out_png="cpi_box.png",
            xvar_name="Data Sizes",
            yvar_name=f"Cycles {ylabel_suffix}",
            title=f"Cycles per loop vs. Data Sizes (Box Plot){title_suffix}",
            yscale_base=(10 if log_scale else None),
            xformatter=self.MEMSIZE_FORMATTER,
        )

        plt.figure(figsize=(10, 5))
        sns.boxplot(x="sizes", y="cycles_per_mem", data=combined_df)
        plt.gca().yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0f}"))
        plt.xticks(rotation=90)
        self.finish_plot(
            out_png="cpm_box.png",
            xvar_name="Data Sizes",
            yvar_name=f"Cycles per Memory Access {ylabel_suffix}",
            title=f"Cycles per Memory Access vs. Data Sizes (Box Plot){title_suffix}",
            yscale_base=2,
        )

        misses_events = ["L1DMPI", "L2MPI", "LLMPI"]
        if self.PLOT_TLBMPI:
            misses_events += ["TLBMPI"]

        for misses_event in misses_events:
            plt.figure(figsize=(10, 5))
            sns.boxplot(x="sizes", y=misses_event, data=combined_df[["sizes", misses_event]])
            plt.xticks(rotation=90)
            self.finish_plot(
                out_png=f"{misses_event}_box.png",
                xvar_name="Data Sizes",
                yvar_name=f"Misses per Memory Access {ylabel_suffix}",
                title=f"{misses_event} per Memory Access vs. Data Sizes (Box Plot){title_suffix}",
                yscale_base=(10 if log_scale else None),
                xformatter=self.MEMSIZE_FORMATTER,
            )

    def plot_latency_sweep_results(self, df, latency_metric, latency_unit, cache_size_dict, legend_loc="upper left"):
        self.plot_perf_data(
            df,
            x_metric="sizes",
            y_metric=latency_metric,
            alt_y_metric=f"PMU_rd_latency [{latency_unit}]",
            ytype=f"Latency per Access [{latency_unit}]",
            result_type=self.LATENCY_SWEEP_TYPE,
            cache_size_dict=cache_size_dict,
            legend_loc=legend_loc,
            yformatter=self.TIME_FORMATTER,
            log_scale=True,
        )

        self.plot_misses(df, self.LATENCY_SWEEP_TYPE, legend_loc=legend_loc)

    def plot_loaded_latency_results(self, df, latency_unit, acceptable_increase):
        result_type = self.LOADED_LATENCY_TYPE
        peak_bw_column_name = "% of Peak Theoretical BW"
        latency_column_name = f"Loaded latency [{latency_unit}]"
        outfile = os.path.join(self.current_benchmark_dir(), f"{result_type}.png")
        plt.figure(figsize=(10, 5))

        if peak_bw_column_name in df.columns:
            # Plot using peak bandwidth as X-axis
            x_values = df[peak_bw_column_name]
            x_label = peak_bw_column_name
            x_formatter = self.PERCENT_FORMATTER
            title = f"Latency per Access [{latency_unit}] vs. % of Peak Theoretical BW"
        else:
            # Fallback: use index
            x_values = df.index
            x_label = "Sample index"
            x_formatter = None
            title = f"Latency per Access [{latency_unit}]"

        plt.plot(
            x_values,
            df[latency_column_name],
            marker="o",
            linestyle="-",
            color="blue",
            label=latency_column_name,
        )

        min_latency = df[latency_column_name].min()
        # Calculate the acceptable increase in latency
        acceptable_latency = min_latency * (1 + acceptable_increase)

        # Plot the minimum latency line
        plt.axhline(
            y=min_latency,
            color="lightgray",
            linestyle="--",
            label=f"Minimum latency ({min_latency:.2f} {latency_unit})",
        )
        # Plot the acceptable latency line
        plt.axhline(
            y=acceptable_latency,
            color="black",
            linestyle="--",
            label=f"Acceptable latency ({acceptable_increase * 100:.2f}% increase, "
            f"{acceptable_latency:.2f} {latency_unit})",
        )

        if peak_bw_column_name in df.columns:
            # Compute the corresponding peak bandwidth using interpolation
            interpolated_curve = interp1d(
                df[latency_column_name],
                df[peak_bw_column_name],
                kind="linear",
                fill_value="extrapolate",
                assume_sorted=False,
            )
            acceptable_peak_bw = interpolated_curve(acceptable_latency)
            plt.axvline(
                x=acceptable_peak_bw,
                color="red",
                linestyle="--",
                label=f"Acceptable % Peak BW load ({acceptable_peak_bw:.2f}%)",
            )
            # Set x-axis ranging from 0% to 100%
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
        log.info(f"Generated plot saved to {outfile}")

    def plot_bandwidth_sweep_results(self, df, rate_unit, cache_size_dict, legend_loc="lower left"):
        if rate_unit == "B/cycle":
            per_unit = "/cycle"
            df["total_bandwidth [B/cycle]"] = df["total_bandwidth_bpc"]
        else:
            per_unit = "/s"
            # total_bandwidth and PMU_bw [MB/s] are both in MB/s
            # Convert them back to B/s for plotting
            df["total_bandwidth [B/s]"] = df["total_bandwidth_mbps"] * 1e6
            if "PMU_bw [MB/s]" in df.columns:
                df["PMU_bw [B/s]"] = df["PMU_bw [MB/s]"] * 1e6
        self.plot_perf_data(
            df,
            x_metric="sizes",
            y_metric=f"total_bandwidth [B{per_unit}]",
            alt_y_metric=f"PMU_bw [B{per_unit}]",
            ytype=f"Memory Rate [{per_unit}]",
            result_type=self.BANDWIDTH_SWEEP_TYPE,
            cache_size_dict=cache_size_dict,
            legend_loc=legend_loc,
            yformatter=self.MEMRATE_FORMATTER,
            log_scale=False,
        )

        self.plot_misses(df, self.BANDWIDTH_SWEEP_TYPE, legend_loc=legend_loc)

    def plot_misses(self, df, _result_type, legend_loc):
        misses_events = ["L1_Rd_Misses", "L2_Rd_Misses", "LL_Rd_Misses"]
        if self.PLOT_TLBMPI:
            misses_events += ["TLB_Misses"]
        # Plot L2MPI and LLMPI together
        valid_misses_events = [e for e in misses_events if e in df.columns]
        if valid_misses_events and "L1_Rd" in df.columns:
            plt.figure(figsize=(10, 5))
            for misses_event in valid_misses_events:
                plt.plot(
                    df["sizes"],
                    df[misses_event] / df["L1_Rd"],
                    marker="o",
                    linestyle="-",
                    label=f"{misses_event} per read",
                )
            self.finish_plot(
                out_png=os.path.join(self._pmu_dir(), "misses.png"),
                xvar_name="Data Sizes",
                yvar_name="Misses per Memory Access",
                title="Miss events vs. Data Sizes",
                xformatter=self.MEMSIZE_FORMATTER,
                yformatter=None,
                legend_loc=legend_loc,
            )

    def plot_perf_data(
        self,
        df,
        x_metric,
        y_metric,
        alt_y_metric,
        ytype,
        result_type,
        cache_size_dict=None,
        legend_loc="upper left",
        yformatter=None,
        log_scale=True,
        show_labels=False,
    ):
        outfile = os.path.join(self.current_benchmark_dir(), f"{result_type}.png")
        plt.figure(figsize=(10, 5))
        # Convert x values to log10 scale for plotting

        plt.plot(df[x_metric], df[y_metric], marker="o", linestyle="-", color="blue", label=y_metric)
        if alt_y_metric in df.columns:
            # PMU measured latency also available
            plt.plot(df[x_metric], df[alt_y_metric], marker="o", linestyle="-", color="green", label=alt_y_metric)

        if "y_cluster" in df.columns:
            plt.plot(df[x_metric], df["y_cluster"], marker="o", linestyle="-", color="yellow", label="cluster")

        # Add x labels at data points with 2 significant digits
        if show_labels:
            for x, y in zip(df[x_metric], df[y_metric], strict=False):
                plt.text(x, y, f"{x:.2g}", fontsize=8, ha="right", va="bottom")
        # Plot vertical lines for different cache sizes and label them with cache level and size in human readable
        # format
        if cache_size_dict:
            for cache_level, cache_size in cache_size_dict.items():
                plt.axvline(
                    x=cache_size,
                    color="red",
                    linestyle="--",
                    label=f"{cache_level} cache size ({memsize_str(cache_size, suffix='B')})",
                )
                # Now add the label just beside the line with a bit offset to the right
                plt.text(
                    cache_size * 1.05,
                    plt.ylim()[1] * 0.9,
                    f"{cache_level} ({memsize_str(cache_size, suffix='B')})",
                    color="red",
                    fontsize=10,
                    rotation=90,
                    va="top",
                    ha="left",
                )

        self.scale_and_label(
            xvar_name="Data Sizes",
            yvar_name=y_metric,
            title=f"{ytype} vs. Data Sizes",
            xscale_base=2,
            yscale_base=(2 if log_scale else None),
            legend_loc=legend_loc,
            xformatter=self.MEMSIZE_FORMATTER,
            yformatter=yformatter,
        )

        # Need to create secondary y-axis for the difference plot
        if alt_y_metric in df.columns:
            diff = (df[alt_y_metric] - df[y_metric]) / df[y_metric] * 100
            ax1 = plt.gca()
            ax2 = ax1.twinx()
            ax2.plot(df[x_metric], diff, alpha=0.5, color="red", label="% Diff")
            ax2.set_ylabel("% Difference")
            ax2.legend(loc="upper right")

        self.tighten_and_save(outfile)
        log.info(f"Generated plot saved to {outfile}")

    # Logics to compute delta between two dataframes with consideration of small values
    # This will be used for supporting sysdiff feature.
    @staticmethod
    def compute_delta(df, cmp_df, median_faction=0.01):
        merged_df = pd.merge(df, cmp_df, on="sizes", suffixes=("", "_cmp"))
        delta = {}
        for column in df.columns:
            if column != "sizes" and column in cmp_df.columns:
                # Use max of the value and epsilon to avoid division by very small numbers
                median_value = (merged_df[column].median() + merged_df[f"{column}_cmp"].median()) / 2
                epsilon = median_faction * median_value  # 1% of the median value
                mask = (merged_df[f"{column}_cmp"] > epsilon) | (merged_df[column] > epsilon)
                current_delta = pd.Series(0.0, index=merged_df.index)
                current_delta.loc[mask] = (
                    (merged_df.loc[mask, column] - merged_df.loc[mask, f"{column}_cmp"])
                    / merged_df.loc[mask, f"{column}_cmp"]
                    * 100
                )
                delta[column] = current_delta
        delta["sizes"] = merged_df["sizes"]
        return pd.DataFrame(delta)
