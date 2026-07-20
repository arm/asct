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

    @staticmethod
    def _optional_plot_label(value, default="default"):
        if value is None or pd.isna(value) or value in ("", "None"):
            return default
        return str(value)

    @staticmethod
    def _int_or_default(value, default=0):
        if value is None or pd.isna(value):
            return default
        return int(value)

    @staticmethod
    def _axis_tick_text_style(ax):
        tick_labels = ax.get_xticklabels()
        if not tick_labels:
            return {}
        tick_label = tick_labels[0]
        return {
            "fontsize": tick_label.get_fontsize(),
            "fontfamily": tick_label.get_fontfamily(),
            "fontstyle": tick_label.get_fontstyle(),
            "fontweight": tick_label.get_fontweight(),
        }

    @staticmethod
    def _figure_size_for_points(point_count, min_width=10, min_height=5, width_per_point=1.0, aspect_divisor=5.2):
        fig_width = max(min_width, point_count * width_per_point)
        fig_height = max(min_height, fig_width / aspect_divisor)
        return fig_width, fig_height

    @staticmethod
    def _mean_by_plot_labels(df, grouping_keys, value_columns):
        ordered_labels = df[grouping_keys].drop_duplicates()
        grouped = df.groupby(grouping_keys, sort=False)[value_columns].mean(numeric_only=True).reset_index()
        for column in value_columns:
            if column not in grouped.columns:
                grouped[column] = pd.NA
        return ordered_labels.merge(grouped, on=grouping_keys, how="left")

    @staticmethod
    def _all_values_missing(df, columns):
        return df.empty or df[columns].isna().all().all()

    def _configure_numeric_axis(self, ax, ylabel, formatter=None, labelpad=None, grid_axis=None):
        ax.set_ylabel(ylabel, labelpad=labelpad, fontsize=13)
        ax.yaxis.set_major_locator(ticker.MaxNLocator(nbins=6, min_n_ticks=4))
        if formatter is not None:
            ax.yaxis.set_major_formatter(formatter)
        if grid_axis is not None:
            ax.grid(axis=grid_axis, linestyle="--", alpha=0.5)

    @staticmethod
    def _plot_grouped_bars(ax, x_positions, df, bar_specs, bar_width):
        handles = []
        for spec in bar_specs:
            handle = ax.bar(
                [x + spec.get("offset", 0.0) for x in x_positions],
                df[spec["column"]].fillna(0.0),
                width=bar_width,
                color=spec["color"],
                label=spec["label"],
            )
            handles.append(handle)
        return handles

    @staticmethod
    def _plot_line_series(ax, x_positions, df, line_specs):
        handles = []
        for spec in line_specs:
            (handle,) = ax.plot(
                x_positions,
                df[spec["column"]],
                color=spec["color"],
                marker=spec.get("marker", "o"),
                linewidth=spec.get("linewidth", 2),
                label=spec["label"],
            )
            handles.append(handle)
        return handles

    @staticmethod
    def _annotate_points(ax, x_positions, values, color, y_offset):
        for x_pos, value in zip(x_positions, values, strict=True):
            if pd.notna(value):
                ax.annotate(
                    f"{value:.1f}",
                    (x_pos, value),
                    textcoords="offset points",
                    xytext=(0, y_offset),
                    ha="center",
                    fontsize=7,
                    color=color,
                )

    def _apply_hierarchical_xaxis(self, ax, x_positions, section_labels, point_labels):
        ax.set_xticks(x_positions)
        ax.set_xticklabels(point_labels, rotation=25, ha="right")

        if not x_positions:
            return

        text_style = self._axis_tick_text_style(ax)
        start = 0
        for index in range(1, len(section_labels) + 1):
            is_new_group = index == len(section_labels) or section_labels[index] != section_labels[start]
            if not is_new_group:
                continue
            end = index
            midpoint = (x_positions[start] + x_positions[end - 1]) / 2
            ax.text(
                midpoint,
                -0.24,
                section_labels[start],
                transform=ax.get_xaxis_transform(),
                ha="center",
                va="top",
                bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.85, "pad": 0.6},
                **text_style,
            )
            if end < len(section_labels):
                ax.axvline(end - 0.5, color="#dddddd", linestyle="--", linewidth=1)
            start = end

    def _place_legend_avoiding_axis_overlap(
        self,
        fig,
        legend_axis,
        overlap_axis,
        handles,
        labels,
        initial_anchor=1.02,
        max_anchor=1.40,
        step=0.02,
    ):
        anchor = initial_anchor
        legend = None

        while True:
            if legend is not None:
                legend.remove()
            legend = legend_axis.legend(
                handles,
                labels,
                loc="center left",
                bbox_to_anchor=(anchor, 0.5),
                borderaxespad=0.0,
            )
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            legend_bbox = legend.get_window_extent(renderer).expanded(1.02, 1.08)
            overlap_axis_bbox = overlap_axis.get_tightbbox(renderer).expanded(1.02, 1.08)
            if not legend_bbox.overlaps(overlap_axis_bbox) or anchor >= max_anchor:
                return legend
            anchor += step

    def _add_axis_footer_text(self, ax, text, y_offset=-0.37):
        if not text:
            return

        ax.text(
            0.5,
            y_offset,
            text,
            transform=ax.transAxes,
            ha="center",
            va="top",
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.9, "pad": 0.8},
            **self._axis_tick_text_style(ax),
        )

    # Networking-specific plotting helpers.
    def _build_iperf3_hierarchical_labels(self, df, include_protocol=True):
        varying = {
            "duration_s": df["duration_s"].nunique(dropna=False) > 1 if "duration_s" in df.columns else False,
            "message_size_bytes": (
                df["message_size_bytes"].nunique(dropna=False) > 1 if "message_size_bytes" in df.columns else False
            ),
            "bandwidth_target_bps": (
                df["bandwidth_target_bps"].fillna(0).nunique(dropna=False) > 1
                if "bandwidth_target_bps" in df.columns
                else False
            ),
            "window": (
                df["window"].map(self._optional_plot_label).nunique(dropna=False) > 1
                if "window" in df.columns
                else False
            ),
            "client_affinity": (
                df["client_affinity"].map(self._optional_plot_label).nunique(dropna=False) > 1
                if "client_affinity" in df.columns
                else False
            ),
        }

        if not varying["message_size_bytes"] and not varying["bandwidth_target_bps"]:
            varying["duration_s"] = True

        def build_section_label(row):
            section_parts = []
            if include_protocol:
                section_parts.append(str(row.get("protocol", "unknown")).upper())
            if varying["duration_s"]:
                section_parts.append(f"dur={row.get('duration_s', '?')}s")
            if varying["window"]:
                section_parts.append(f"wnd={self._optional_plot_label(row.get('window', None))}")
            if varying["client_affinity"]:
                section_parts.append(f"aff={self._optional_plot_label(row.get('client_affinity', None))}")
            return "\n".join(section_parts) if section_parts else "default section"

        def build_point_label(row):
            point_parts = []
            if varying["message_size_bytes"]:
                message_size = self._int_or_default(row.get("message_size_bytes", 0))
                point_parts.append(memsize_str(message_size, base="binary", suffix="B"))
            if varying["bandwidth_target_bps"]:
                bitrate = self._int_or_default(row.get("bandwidth_target_bps", 0))
                bitrate_label = "unlimited" if bitrate == 0 else f"{memsize_str(bitrate, base='decimal', suffix='b')}ps"
                point_parts.append(bitrate_label)
            if not point_parts:
                point_parts.append(f"dur={row.get('duration_s', '?')}s")
            return "\n".join(point_parts)

        return pd.DataFrame(
            {
                "section_label": df.apply(build_section_label, axis=1),
                "point_label": df.apply(build_point_label, axis=1),
            },
            index=df.index,
        )

    def _build_iperf3_fixed_context_label(self, df):
        fixed_parts = []

        if "server_host" in df.columns and "port" in df.columns:
            hosts = df["server_host"].dropna().astype(str).unique().tolist()
            ports = df["port"].dropna().astype(int).unique().tolist()
            if len(hosts) == 1 and len(ports) == 1:
                fixed_parts.append(f"server={hosts[0]}:{ports[0]}")

        if "server_affinity" in df.columns:
            normalized = df["server_affinity"].map(self._optional_plot_label)
            affinities = normalized.unique().tolist()
            if len(affinities) == 1:
                fixed_parts.append(f"server_aff={affinities[0]}")

        if not fixed_parts:
            return ""
        return "fixed: " + ", ".join(fixed_parts)

    def _prepare_iperf3_network_usage_data(self, df, required_columns, include_protocol=True):
        plot_df = df.copy()
        labels_df = self._build_iperf3_hierarchical_labels(plot_df, include_protocol=include_protocol)
        plot_df = pd.concat([plot_df, labels_df], axis=1)
        grouped = self._mean_by_plot_labels(plot_df, ["section_label", "point_label"], required_columns)
        return plot_df, grouped

    def plot_iperf3_network_usage(self, df, filename, protocol_label=None):
        throughput_columns = ["sender_mbps", "receiver_mbps"]
        cpu_columns = ["sender_cpu_total_pct", "receiver_cpu_total_pct"]
        required_columns = throughput_columns + cpu_columns
        if df.empty or any(column not in df.columns for column in required_columns):
            return

        plot_df, grouped = self._prepare_iperf3_network_usage_data(
            df, required_columns, include_protocol=protocol_label is None
        )
        if self._all_values_missing(grouped, required_columns):
            return

        outfile = os.path.join(self.current_benchmark_dir(), filename)
        fig_size = self._figure_size_for_points(len(grouped), min_height=7.2, width_per_point=1.6)
        fig, ax_bw = plt.subplots(figsize=fig_size)
        ax_cpu = ax_bw.twinx()
        x_positions = list(range(len(grouped)))
        bar_width = 0.38

        bar_specs = [
            {
                "column": "sender_mbps",
                "label": "sender bandwidth",
                "color": "#2f6690",
                "offset": -bar_width / 2,
            },
            {
                "column": "receiver_mbps",
                "label": "receiver bandwidth",
                "color": "#67a9cf",
                "offset": bar_width / 2,
            },
        ]
        line_specs = [
            {
                "column": "sender_cpu_total_pct",
                "label": "sender CPU total",
                "color": "#ef6f6c",
                "marker": "o",
                "annotation_offset": 7,
            },
            {
                "column": "receiver_cpu_total_pct",
                "label": "receiver CPU total",
                "color": "#d1495b",
                "marker": "s",
                "annotation_offset": -11,
            },
        ]

        bar_handles = self._plot_grouped_bars(ax_bw, x_positions, grouped, bar_specs, bar_width)
        line_handles = self._plot_line_series(ax_cpu, x_positions, grouped, line_specs)
        for spec in line_specs:
            self._annotate_points(
                ax_cpu,
                x_positions,
                grouped[spec["column"]],
                spec["color"],
                spec["annotation_offset"],
            )

        self._configure_numeric_axis(ax_bw, "Bandwidth (Mb/s)", grid_axis="y")
        self._configure_numeric_axis(ax_cpu, "CPU utilization (%)", formatter=self.PERCENT_FORMATTER, labelpad=6)
        self._apply_hierarchical_xaxis(
            ax_bw, x_positions, grouped["section_label"].tolist(), grouped["point_label"].tolist()
        )
        ax_bw.set_xlabel("Per-point values (section headers show shared settings)", labelpad=7)
        self._add_axis_footer_text(ax_bw, self._build_iperf3_fixed_context_label(plot_df))
        ax_bw.set_title(
            f"iperf3 {protocol_label + ' ' if protocol_label else ''}bandwidth and CPU utilization",
            pad=12,
            fontsize=16,
        )

        handles = bar_handles + line_handles
        labels = [spec["label"] for spec in bar_specs + line_specs]
        fig.tight_layout(rect=[0, 0.09, 0.82, 0.985])
        self._place_legend_avoiding_axis_overlap(fig, ax_bw, ax_cpu, handles, labels, initial_anchor=1.02)
        fig.savefig(outfile)
        plt.close(fig)
        log.info("Generated plot saved to %s", outfile)

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
