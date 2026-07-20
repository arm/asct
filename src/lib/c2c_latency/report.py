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

import seaborn as sns
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from os import path
from io import StringIO
from collections import defaultdict
from matplotlib.colors import LinearSegmentedColormap
from rich.console import Console
from rich.table import Table
from rich import box

from asct.core.managers.ubench_reporter import get_reporter


class CoreToCoreLatencyReport:
    def __init__(self, data, top_n=10, node_to_cpus=None, vmax=200, bins=10, round_digits=2):
        """
        Initialize CoreToCoreLatencyReport.
        Args:
            data (pd.DataFrame): Latency measurements.
            top_n (int): Number of top latencies to display.
            node_to_cpus (dict): Node to CPU mapping.
            vmax (float): Maximum latency value for heatmap coloring.
        """

        self.df = data.replace({None: np.nan}).infer_objects(copy=False)
        self.top_n = top_n
        self._node_matrix = pd.DataFrame()
        self.stats = {}
        self.top_latencies = pd.Series(dtype=float)
        self.asymmetry = {}
        self.node_to_cpus = node_to_cpus
        self.heatmap_vmax = vmax
        self.round_digits = round_digits
        if self.node_to_cpus is None:
            self.node_to_cpus = {}

        # Set the distribution bins for histogram generation
        self.histogram_bins = bins

        # Create core → node mapping
        self.core_to_node = {core: node for node, cores in self.node_to_cpus.items() for core in cores}

        # Flatten the latency matrix into long format
        self.node_to_node_df = self.df.copy()

        # Drop NaNs and diagonal (i == j)
        df_mask = self.node_to_node_df["CPUA"] != self.node_to_node_df["CPUB"]
        self.node_to_node_df = self.node_to_node_df[df_mask]
        self.node_to_node_df = self.node_to_node_df.dropna()

        # Map nodes to each core
        self.node_to_node_df["CPUA_NODE"] = self.node_to_node_df["CPUA"].map(self.core_to_node)
        self.node_to_node_df["CPUB_NODE"] = self.node_to_node_df["CPUB"].map(self.core_to_node)

        # Drop rows where node mapping is missing (if any cores are outside the map)
        self.node_to_node_df = self.node_to_node_df.dropna(subset=["CPUA_NODE", "CPUB_NODE"])

        # Convert to integer type for proper indexing
        self.node_to_node_df["CPUA_NODE"] = self.node_to_node_df["CPUA_NODE"].astype(int)
        self.node_to_node_df["CPUB_NODE"] = self.node_to_node_df["CPUB_NODE"].astype(int)

        self.grouped_node_to_node_df = self.node_to_node_df.groupby(["CPUA_NODE", "CPUB_NODE"])["LATENCY"]

        self._summarize()

    @staticmethod
    def _output_dir():
        return get_reporter().current_benchmark_dir()

    def _summarize(self):
        """
        Computes min, max, mean, median, and top N latencies from the 'LATENCY' column.
        """

        latencies = self.df["LATENCY"]
        self.stats = {
            "min": float(latencies.min()),
            "max": float(latencies.max()),
            "mean": float(latencies.mean()),
            "median": float(latencies.median()),
            "p99": float(latencies.quantile(0.99)),
        }

        self.top_latencies = self.df.sort_values(by="LATENCY", ascending=False).head(self.top_n)

    @property
    def node_matrix(self):
        if self._node_matrix.empty:
            self.node_to_node_median_latencies()
        return self._node_matrix

    def node_to_node_median_latencies(self):
        """
        Calculate node-to-node median latencies.
        """

        # Create node-to-node median latency matrix
        nodes = sorted(self.node_to_cpus.keys())
        self._node_matrix = pd.DataFrame(np.nan, index=nodes, columns=nodes)

        for (src_node, tgt_node), latencies in self.grouped_node_to_node_df:
            self._node_matrix.at[src_node, tgt_node] = latencies.median()

    def node_to_node_detailed_summary(self):
        # Create reverse mapping: core → node

        print()
        print("Node-to-Node Latency Statistics (ns):")
        print("-------------------------------------")

        for (src_node, tgt_node), latencies in self.grouped_node_to_node_df:
            median_val = latencies.median()
            min_val = latencies.min()
            max_val = latencies.max()
            mean_val = latencies.mean()

            print(f"\nNode{src_node} → Node{tgt_node}:")
            print(f"   Min:    {min_val:.2f} ns")
            print(f"   Max:    {max_val:.2f} ns")
            print(f"   Mean:   {mean_val:.2f} ns")
            print(f"   Median: {median_val:.2f} ns")

    def generate_heatmap(self, file_name_suffix=""):
        # Pivot flat df into matrix form.
        # Use pivot_table (with aggregation) to handle multiple samples per CPUA/CPUB pair.
        latency_matrix = (
            self.df
            .pivot_table(index="CPUA", columns="CPUB", values="LATENCY", aggfunc="median")
            .astype(float)
            .fillna(np.nan)
        )

        # Create ordered list of CPUs from node-to-cpu mapping
        ordered_indices = [cpu for group in self.node_to_cpus.values() for cpu in group]

        # Reorder the matrix
        grouped_data = latency_matrix.loc[ordered_indices, ordered_indices]

        grouped_data.columns = [f"CPU{i}" for i in grouped_data.columns]
        grouped_data.index = [f"CPU{i}" for i in grouped_data.index]

        cell_width = 1.0
        cell_height = 0.6

        # Get shape of DataFrame
        rows, cols = latency_matrix.shape

        # Dynamically set figure size
        fig_width = cols * cell_width
        fig_height = rows * cell_height

        # Create figure with dynamic size
        plt.figure(figsize=(fig_width, fig_height))

        # Lightened colors (you can also use hex codes for finer control)
        colors = ["#72e239", "#ecd90b", "#f66969"]  # light green, light yellow, light red

        # Create a light gradient
        cmap = LinearSegmentedColormap.from_list("light_gyr", colors)
        norm = None

        sns.heatmap(
            grouped_data,
            annot=True,
            fmt=".1f",
            cmap=cmap,
            linewidths=0.5,
            linecolor="gray",
            mask=grouped_data.isnull(),
            cbar_kws={"label": "Latency (ns)"},
            vmax=self.heatmap_vmax,
            norm=norm,
        )

        # Set axis labels and title
        file_path = path.join(self._output_dir(), f"core_latency_heatmap_{file_name_suffix.lower()}.png")
        plt.title("Core-to-Core Latency Heatmap")
        plt.xlabel("Target Core")
        plt.ylabel("Source Core")
        plt.tight_layout()
        plt.savefig(file_path)
        plt.close()

    def generate_histogram_image(self, file_name_suffix=""):
        plt.figure(figsize=(10, 6))
        latencies = self.df["LATENCY"].dropna()
        if latencies.empty:
            return

        sns.histplot(latencies, bins=self.histogram_bins, kde=True)

        ax = plt.gca()
        marker_styles = (
            ("Min", "min", ":", "tab:blue"),
            ("Max", "max", ":", "tab:orange"),
            ("Mean", "mean", "--", "tab:green"),
            ("Median", "median", "-", "tab:red"),
            ("P99", "p99", "-.", "tab:purple"),
        )
        for label, key, linestyle, color in marker_styles:
            value = self.stats.get(key)
            if value is None or pd.isna(value):
                continue

            ax.axvline(
                float(value),
                linestyle=linestyle,
                linewidth=1.2,
                color=color,
                label=f"{label}: {float(value):.2f}",
            )

        ax.legend()
        plt.title("Distribution of Core-to-Core Latencies")
        plt.xlabel("Latency (ns)")
        plt.ylabel("Frequency")
        file_path = path.join(self._output_dir(), f"core_latency_histogram_{file_name_suffix.lower()}.png")
        plt.tight_layout()
        plt.savefig(file_path)
        plt.close()

    def generate_histogram_to_stdout(self):
        """Generates a text-based histogram of latencies with markers for min, max, mean, median, and P99."""
        latencies = self.df["LATENCY"].dropna().to_numpy(dtype=float)
        if latencies.size == 0:
            return "No latency data available."

        markers: tuple[tuple[str, str], ...] = (
            ("Min", "min"),
            ("Max", "max"),
            ("Mean", "mean"),
            ("Median", "median"),
            ("P99", "p99"),
        )

        marker_items: list[tuple[str, float]] = []
        for label, key in markers:
            value = self.stats.get(key)
            if value is None or pd.isna(value):
                continue
            marker_items.append((label, float(value)))

        bar_width = 20
        counts, bin_edges = np.histogram(latencies, bins=self.histogram_bins)
        max_count = int(counts.max()) if counts.size else 0

        print()
        print()
        print("Latency Distribution (ns):")
        hist_table = Table(title="", box=box.ASCII)
        hist_table.add_column("Range (ns)", justify="left")
        hist_table.add_column("Count", justify="right")
        hist_table.add_column("Bar", justify="left")
        hist_table.add_column("Markers", justify="left")

        bin_to_markers = self._build_bin_to_markers(
            bin_edges=bin_edges,
            marker_items=marker_items,
            n_bins=int(counts.size),
        )

        self._add_histogram_rows(
            table=hist_table,
            counts=counts,
            bin_edges=bin_edges,
            max_count=max_count,
            bar_width=bar_width,
            bin_to_markers=bin_to_markers,
        )

        buffer = StringIO()
        Console(file=buffer, force_terminal=False, color_system=None).print(hist_table)
        print(buffer.getvalue().rstrip() + "\n")
        return None

    @staticmethod
    def _build_bin_to_markers(
        *,
        bin_edges: np.ndarray,
        marker_items: list[tuple[str, float]],
        n_bins: int,
    ) -> dict[int, list[str]]:
        if n_bins <= 0:
            return {}

        bin_to_markers: dict[int, list[str]] = defaultdict(list)
        for label, value in marker_items:
            idx = int(np.searchsorted(bin_edges, value, side="right") - 1)
            idx = max(0, min(idx, n_bins - 1))
            bin_to_markers[idx].append(f"{label}={value:.2f}")

        return dict(bin_to_markers)

    def _add_histogram_rows(
        self,
        table: object,
        counts: np.ndarray,
        bin_edges: np.ndarray,
        max_count: int,
        bar_width: int,
        bin_to_markers: dict[int, list[str]],
    ) -> None:
        for i, (count, edge_start, edge_end) in enumerate(zip(counts, bin_edges[:-1], bin_edges[1:], strict=False)):
            n_blocks = round((float(count) / max_count) * bar_width) if max_count else 0
            bar = "#" * n_blocks
            r = f"{edge_start:8.2f} - {edge_end:8.2f}"
            marker_text = " ".join(bin_to_markers.get(i, []))
            table.add_row(r, str(count), bar, marker_text)

    def to_stdout(self, membind=""):
        print()
        print(f"Core-to-Core Latency Summary (ns): Data Address @ {membind} Numa Node")
        print("=================================================================")
        # Print or use the matrix
        print()
        print("Node-to-Node Median Latency Matrix (ns):")
        print("----------------------------------------")
        print(
            self.node_matrix
            .rename(index=lambda i: f"Node{i}", columns=lambda j: f"Node{j}")
            .round(self.round_digits)
            .fillna("-")
        )

        # print the histogram to stdout
        self.generate_histogram_to_stdout()

        print("\nTop Latency Core Pairs with Median Latency")
        print("------------------------------------------")
        # Print header
        print(f"{'SRC CPU':>9} {'DST CPU':>9}    {'Latency (ns)':>12}")
        print("-" * 35)

        for row in self.top_latencies.itertuples(index=False):
            print(f"{row.CPUA:6}   {row.CPUB:6}   {row.LATENCY:12.2f}")

        self.node_to_node_detailed_summary()

    def get_save_data(self):
        """
        Returns a JSON-serializable representation of the recipe data.

        Returns:
            dict: The recipe data in JSON-serializable dictionary format.
        """
        data = {}
        data["stats"] = self.stats
        data["node_to_node_median_latencies"] = self.node_matrix.round(self.round_digits).to_dict()
        latencies_list = [float(row.LATENCY) for row in self.top_latencies.itertuples(index=False)]

        data["top_latencies"] = {"latencies": latencies_list}
        return data
