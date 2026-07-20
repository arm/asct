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
Implementation of algorithm useful to sweep data.
Currently used by latency sweep but generally can also be used for sweeping cutoff values
or other parameters
"""

import os
import shutil

import numpy as np
import pandas as pd

from sklearn.cluster import KMeans
from . import logger as log
from asct.core.managers import ubench_reporter as ub_rep


class SweepAlgorithm:
    L1_L2_x_start = 8e4
    L1_L2_x_finish = 3e5
    L2_LLC_x_start = 1e6
    L2_LLC_x_finish = 8e6
    LLC_RAM_x_start = 2e7
    LLC_RAM_x_finish = 1e8

    def __init__(self, MIN_DATA_SIZE, MAX_DATA_SIZE, level_names):
        """
        Initialize the SweepAlgorithm with minimum and maximum data sizes.

        Parameters:
        min_data_size (int): Minimum data size to consider.
        max_data_size (int): Maximum data size to consider.
        """
        self.MIN_DATA_SIZE = MIN_DATA_SIZE
        self.MAX_DATA_SIZE = MAX_DATA_SIZE
        self.level_names = level_names

    def scaled_sigmoid(self, x, x_min, x_start, x_finish, x_max, y_min, y_max):
        """
        Computes a scaled sigmoid function ensuring:
        - y(x_min) = y_min
        - y(x_start) starts increasing
        - y(x_finish) finishes increasing
        - y(x_large) = y_max

        Parameters:
        x (float or np.array): Input x values
        y_min (float): Minimum y value
        y_max (float): Maximum y value
        x_min (float): x where y = y_min
        x_start (float): x where y starts increasing
        x_finish (float): x where y finishes increasing
        x_large (float): x where y = y_max

        Returns:
        float or np.array: Computed y values
        """
        # Standard sigmoid transition
        x0 = (x_start + x_finish) / 2  # Midpoint of transition
        k = 8 / (x_finish - x_start)  # Steepness factor

        # Compute sigmoid function
        s = 1 / (1 + np.exp(-k * (x - x0)))

        # Normalize the sigmoid so that it starts at y_min and ends at y_max
        s_min = 1 / (1 + np.exp(-k * (x_min - x0)))  # Value at x_min
        s_max = 1 / (1 + np.exp(-k * (x_max - x0)))  # Value at x_large

        if np.isclose(s_min, s_max):
            # If the range is too small, return a constant value
            raise ValueError(f"Scaled sigmoid cannot be computed: s_min ({s_min}) and s_max ({s_max}) are too close.")

        # Normalize to match the y_min and y_max range
        s_scaled = (s - s_min) / (s_max - s_min)

        return y_min + (y_max - y_min) * s_scaled

    # Define the final precise piecewise sigmoid function
    def modeled_cpm(self, x):
        """Piecewise sigmoid function with precise transitions and fixed y-values"""

        # L1 to L2 Transition (~8e4 to ~3e5) - Goes from 2^2 (4) to 2^4 (16)
        # L1_L2 = 4 + (16 - 4) / (1 + np.exp(-0.000025 * (x - 1.9e5)))
        L1_L2_x_min = 0
        L1_L2_x_max = 5e5
        L1_value = 4
        L2_value = 16
        L1_L2 = self.scaled_sigmoid(
            x, L1_L2_x_min, self.L1_L2_x_start, self.L1_L2_x_finish, L1_L2_x_max, L1_value, L2_value
        )

        # L2 to LLC Transition (~1e6 to ~8e6) - Goes from 2^4 (16) to 2^6 (64)
        # L2_LLC = 16 + (64 - 16) / (1 + np.exp(-0.000006 * (x - 4.5e6)))
        L2_LLC_x_max = 1e7
        L3_value = 64
        L2_LLC = self.scaled_sigmoid(
            x, L1_L2_x_max, self.L2_LLC_x_start, self.L2_LLC_x_finish, L2_LLC_x_max, L2_value, L3_value
        )

        # LLC to RAM Transition (~2e7 to ~2e8) - Goes from 2^6 (64) to 2^8 (256)
        # LLC_RAM = 64 + (256 - 64) / (1 + np.exp(-0.0000006 * (x - 1.1e8)))
        LLC_RAM_x_max = 2e8
        RAM_value = 256
        LLC_RAM = self.scaled_sigmoid(
            x, L2_LLC_x_max, self.LLC_RAM_x_start, self.LLC_RAM_x_finish, LLC_RAM_x_max, L3_value, RAM_value
        )

        # Apply transitions at the appropriate ranges
        if x <= L1_L2_x_max:
            return L1_L2  # Transitioning from L1 to L2
        if x <= L2_LLC_x_max:
            return L2_LLC  # Transitioning from L2 to LLC
        if x <= LLC_RAM_x_max:
            return LLC_RAM  # Transitioning from LLC to RAM
        return RAM_value  # RAM Plateau (2^8)

    def plot_models(self):
        # Generate x values for plotting
        x_values = np.logspace(3, 9, 1000)
        y_values = [self.modeled_cpm(x) for x in x_values]

        # Plot the modeled curve
        ub_rep.get_reporter().plot_graph(x_values, y_values)

        # Compute scaled sigmoid transitions
        L1DMPI = [
            self.scaled_sigmoid(dsize, 0, self.L1_L2_x_start, self.L1_L2_x_finish, self.MAX_DATA_SIZE, 0, 1)
            for dsize in x_values
        ]
        L2MPI = [
            self.scaled_sigmoid(dsize, 0, self.L2_LLC_x_start, self.L2_LLC_x_finish, self.MAX_DATA_SIZE, 0, 1.2)
            for dsize in x_values
        ]
        LLMPI = [
            self.scaled_sigmoid(dsize, 0, self.LLC_RAM_x_start, self.LLC_RAM_x_finish, self.MAX_DATA_SIZE, 0, 1)
            for dsize in x_values
        ]

        # Plot the curve
        ub_rep.get_reporter().plot_modeled_misses(x_values, L1DMPI, L2MPI, LLMPI)

    def compute_new_data_sizes_pmu(self, df):
        """
        Compute new data sizes for the next iteration of the memory sweep.

        Parameters:
        df (pd.DataFrame): DataFrame containing the current results with columns
        'sizes', 'L1DMPI', 'L2MPI', and 'LLMPI'.

        Returns:
        list: List of new data sizes to probe.
        """
        new_sizes = []
        bounds = {}
        misses_level_names = ["L1DMPI", "L2MPI", "LLMPI"]
        iterate_misses_level_names = [None, *misses_level_names, None]

        if misses_level_names - set(df.columns):
            raise ValueError(f"DataFrame is missing required columns: {misses_level_names - set(df.columns)}")

        for level_name, plateau_name, next_plateau_name in zip(
            self.level_names, iterate_misses_level_names[:-1], iterate_misses_level_names[1:], strict=False
        ):
            self.explore_plateau(df, new_sizes, bounds, plateau_name, next_plateau_name, level_name)

        return new_sizes, bounds

    def compute_new_data_sizes_cpm(self, df, cpm_metric, bounds_df, log_scale):
        if cpm_metric not in df.columns:
            raise ValueError(f"DataFrame is missing required column: {cpm_metric}")
        refined_df = df.copy()
        refined_df = refined_df.sort_values(by="sizes").reset_index(drop=True)

        # Run K Mean will add the y_cluster column
        # Ignore the return values for the moment
        def refinement_logics(cpm_metric, size_metric, bounds_df):
            _, clusters_center, cluster_variation = self.run_kmeans_y(refined_df, cpm_metric)

            log.debug("%s", log.LS(lambda: f"cluster center: {clusters_center.flatten().tolist()}"))
            log.debug("cluster variation: %s", cluster_variation)

            # the two columns will be used to compute the cpm difference between prev and next size
            # shift elements down and fill the first one with the original first
            cluster_medians = refined_df.groupby("y_cluster")[cpm_metric].median().rename("cluster_median")

            if log.is_log_level("debug"):
                # Save file to compare against last iteration
                dump_current_step(cpm_metric, size_metric)

            delta = 0.05

            results = []
            for y_cluster, median in cluster_medians.items():
                # set lower bound to delta of real_median, so (1-delta)*real_median
                # so log2 of that is log2(1-delta) + log2(real_median)
                lower_bound = np.log2(1 - delta) + median
                # set upper bound to delta of real_median, so (1+delta)*real_median
                # so log2 of that is log2(1+delta) + log2(real_median)
                upper_bound = np.log2(1 + delta) + median
                LB_size_max_less = refined_df.loc[refined_df[cpm_metric] < lower_bound, size_metric].max()
                UB_size_min_large = refined_df.loc[refined_df[cpm_metric] > upper_bound, size_metric].min()
                LB_size_min_large = refined_df.loc[refined_df[cpm_metric] >= lower_bound, size_metric].min()
                UB_size_max_less = refined_df.loc[refined_df[cpm_metric] <= upper_bound, size_metric].max()
                results.append({
                    "y_cluster": y_cluster,
                    "cluster_median": median,
                    "LB_size_max_less": LB_size_max_less,
                    "UB_size_min_large": UB_size_min_large,
                    "LB_size_min_large": LB_size_min_large,
                    "UB_size_max_less": UB_size_max_less,
                })
            data_sizes_df = pd.DataFrame(results).set_index("y_cluster")

            # Compute the midpoint
            data_sizes_df["left_new_size"] = (
                data_sizes_df["LB_size_max_less"] + data_sizes_df["LB_size_min_large"]
            ) / 2
            data_sizes_df["right_new_size"] = (
                data_sizes_df["UB_size_max_less"] + data_sizes_df["UB_size_min_large"]
            ) / 2

            data_sizes_df["level_name"] = self.level_names[: len(data_sizes_df)]

            # Print results (optional)
            data_sizes_df["cnt_LB"] = data_sizes_df[["LB_size_max_less", "LB_size_min_large"]].max(axis=1)
            data_sizes_df["cnt_UB"] = data_sizes_df[["UB_size_max_less", "UB_size_min_large"]].min(axis=1)

            if log.is_log_level("debug"):
                for idx, row in data_sizes_df.iterrows():
                    log.debug(f"Cluster {idx} - Median: {cluster_medians[idx]}")
                    log.debug(
                        f"Minimum size for cluster {idx} where "
                        + f"{cpm_metric} < (1-{delta})*{cluster_medians[idx]}: {row['LB_size_max_less']}"
                    )
                    log.debug(
                        f"Maximum size for cluster {idx} where "
                        + f"{cpm_metric} >= {cluster_medians[idx]}: {row['LB_size_min_large']}"
                    )
                    log.debug(
                        f"Maximum size for cluster {idx} where "
                        + f"{cpm_metric} <= {cluster_medians[idx]}: {row['UB_size_max_less']}"
                    )
                    log.debug(
                        f"Minimum size for cluster {idx} where "
                        + f"{cpm_metric} > (1+{delta}*{cluster_medians[idx]}: {row['UB_size_min_large']}"
                    )

            combined_df = data_sizes_df.merge(bounds_df, on="level_name", how="left")
            ub_fix_mask = combined_df["cnt_UB"] > combined_df["UB"]
            lb_fix_mask = combined_df["cnt_LB"] < combined_df["LB"]
            combined_df.loc[ub_fix_mask, "UB"] = combined_df.loc[ub_fix_mask, "cnt_UB"]
            combined_df.loc[lb_fix_mask, "LB"] = combined_df.loc[lb_fix_mask, "cnt_LB"]
            combined_df["UB_gap"] = 2 ** combined_df["UB_size_min_large"] - 2 ** combined_df["UB_size_max_less"]
            combined_df["LB_gap"] = 2 ** combined_df["LB_size_min_large"] - 2 ** combined_df["LB_size_max_less"]
            combined_df["UB_gap_%"] = 100 * combined_df["UB_gap"] / (2 ** combined_df["UB"])
            combined_df["LB_gap_%"] = 100 * combined_df["LB_gap"] / (2 ** combined_df["LB"])
            try_left_mask = (combined_df["left_new_size"] < combined_df["LB"]) & (combined_df["LB_gap_%"] > 1)
            try_right_mask = (combined_df["right_new_size"] > combined_df["UB"]) & (combined_df["UB_gap_%"] > 1)
            left_new_sizes = combined_df.loc[try_left_mask, ["left_new_size"]].stack().reset_index(drop=True)
            right_new_sizes = combined_df.loc[try_right_mask, ["right_new_size"]].stack().reset_index(drop=True)

            bounds_df.update(combined_df[["level_name", "LB", "UB"]].set_index("level_name"))
            # Compute the remaining percentage and ETA as the process can take a while
            log.debug("%s", combined_df)

            return right_new_sizes, left_new_sizes

        def dump_current_step(cpm_metric, size_metric):
            output_dir = ub_rep.get_reporter().current_benchmark_dir()
            current_path = os.path.join(output_dir, "cnt_cpm_explore.png")
            previous_path = os.path.join(output_dir, "prev_cpm_explore.png")
            if os.path.exists(current_path):
                shutil.copyfile(current_path, previous_path)
            ub_rep.get_reporter().plot_perf_data(
                refined_df,
                size_metric,
                cpm_metric,
                None,
                "Latency per Access",
                result_type="cnt_cpm_explore",
                log_scale=False,
            )
            from scipy.integrate import trapezoid  # ruff:ignore[import-outside-top-level]

            integral_value = trapezoid(refined_df[cpm_metric], refined_df[size_metric])
            log.debug(f"Integral of {cpm_metric} over {size_metric}: {integral_value}")

        # Gradient based method, not used for now.  We can remove after K-Mean method is stablized.
        def refinement_logics_gradient(cpm_metric, size_metric, bounds_df):
            _, clusters_center, cluster_variation = self.run_kmeans_y(refined_df, cpm_metric)
            log.debug("%s", log.LS(lambda: f"cluster center: {clusters_center.flatten().tolist()}"))
            log.debug("cluster variation: %s", cluster_variation)
            # the two columns will be used to compute the cpm difference between prev and next size
            # shift elements down and fill the first one with the original first
            cluster_medians = refined_df.groupby("y_cluster")[cpm_metric].median().rename("cluster_median")
            if log.is_log_level("debug"):
                for c in cluster_medians:
                    log.debug(f"cluster {c} median {cluster_medians[c]}")

            # For LB, try to find min data sizes such that CPM >= median
            refined_df["prev_cpm"] = refined_df[cpm_metric].shift(1).fillna(refined_df[cpm_metric].iloc[0])
            refined_df["prev_sizes"] = refined_df[size_metric].shift(1).fillna(refined_df[size_metric].iloc[0] / 2)
            # shift elements up and fill the last one with the original last
            refined_df["next_cpm"] = refined_df[cpm_metric].shift(-1).fillna(refined_df[cpm_metric].iloc[-1])
            refined_df["next_sizes"] = refined_df[size_metric].shift(-1).fillna(refined_df[size_metric].iloc[-1] + 1)

            refined_df["rel_y_change_prev"] = (refined_df[cpm_metric] - refined_df["prev_cpm"]) / (
                refined_df[size_metric] - refined_df["prev_sizes"]
            )
            refined_df["rel_y_change_next"] = (refined_df["next_cpm"] - refined_df[cpm_metric]) / (
                refined_df["next_sizes"] - refined_df[size_metric]
            )
            refined_df.loc[refined_df["rel_y_change_prev"] < 0, "rel_y_change_prev"] = 0
            refined_df.loc[refined_df["rel_y_change_next"] < 0, "rel_y_change_next"] = 0
            refined_df["atan_prev"] = np.arctan(refined_df["rel_y_change_prev"])
            refined_df["atan_next"] = np.arctan(refined_df["rel_y_change_next"])
            refined_df["atan_next_inc"] = refined_df["atan_next"] - refined_df["atan_prev"]
            # average to next size
            refined_df["right_new_sizes"] = (refined_df[size_metric] + refined_df[size_metric].shift(-1)) / 2
            refined_df["left_new_sizes"] = (refined_df[size_metric] + refined_df[size_metric].shift(1)) / 2

            if log.is_log_level("debug"):
                log.debug(f"ave slopes {refined_df[['y_cluster', 'rel_y_change_next']].groupby('y_cluster').mean()}")
                dump_current_step(cpm_metric, size_metric)

            # Step 1: Apply condition to filter rows where cpm is increasing (so getting out of the plateaus)
            inc_filter = refined_df[(refined_df["atan_next"] - refined_df["atan_prev"]) > 0.5]

            # Step 2: Compute max `size_metric` per `y_cluster`, true end of the plateau
            max_sizes = inc_filter.groupby("y_cluster")[size_metric].transform("max")

            # Step 3: Compute selected dataframe
            ubs_df = refined_df[refined_df[size_metric].isin(max_sizes)].copy()
            if len(ubs_df) == len(self.level_names) - 1:
                # Only try to refine bounds if we have enough information
                ubs_df["level_name"] = self.level_names[: len(ubs_df)]
                combined_df = ubs_df.merge(bounds_df, on="level_name", how="left")
                # fix_mask = combined_df[size_metric] > combined_df['UB']
                fix_mask = combined_df[cpm_metric] < combined_df["UB_cpm_metric"]
                combined_df.loc[fix_mask, "UB"] = combined_df.loc[fix_mask, size_metric]
                right_new_sizes = (
                    combined_df.loc[fix_mask, ["left_new_sizes", "right_new_sizes"]].stack().reset_index(drop=True)
                )
                bounds_df.update(
                    combined_df[["level_name", "LB", "UB", cpm_metric]]
                    .set_index("level_name")
                    .rename(columns={cpm_metric: "UB_cpm_metric"})
                )
            else:
                # Otherwise just collect all sizes
                right_new_sizes = ubs_df[["left_new_sizes", "right_new_sizes"]].stack().reset_index(drop=True)

            # F F F F F T T T - find the first T counting from the left
            # check for diff == 1 means flip from false (left) to true (current)
            # ub_mask = (ub_mask.astype(int).diff(1) == 1).fillna(0).astype(bool)
            # LB is aobut looking for first increase of angle prev - next (drop), from the right
            lb_mask = (refined_df["atan_prev"] - refined_df["atan_next"]) > 0.05
            # T T T T F F F F F - find the first T counting from the right
            # check for diff == 1 means flip from false (right) to true (current)
            lb_mask = (lb_mask.astype(int).diff(-1) == 1).fillna(0).astype(bool)

            return right_new_sizes, []

        # Compute relative changes
        all_sizes = refined_df["sizes"]
        if log_scale:
            log_cpm_metric = f"log_{cpm_metric}"
            refined_df["log_sizes"] = np.log2(all_sizes)
            refined_df[log_cpm_metric] = np.log2(refined_df[cpm_metric])
            right_new_sizes, left_new_sizes = refinement_logics(
                cpm_metric=log_cpm_metric, size_metric="log_sizes", bounds_df=bounds_df
            )
            right_new_sizes = [np.exp2(v) for v in right_new_sizes]
            left_new_sizes = [np.exp2(v) for v in left_new_sizes]
        else:
            right_new_sizes, left_new_sizes = refinement_logics(cpm_metric, size_metric="sizes")
        right_new_sizes = [int(v) for v in right_new_sizes]
        left_new_sizes = [int(v) for v in left_new_sizes]
        return sorted((set(right_new_sizes) | set(left_new_sizes)) - set(all_sizes))

    def explore_plateau(self, df, new_sizes, bounds, plateau_name, next_plateau_name, level_name):
        current_lb = self.MIN_DATA_SIZE
        current_ub = self.MAX_DATA_SIZE

        # Define thresholds for determining plateaus
        current_plateau_threshold = 0.95
        next_plateau_threshold = 0.05

        # Identify current plateaus and transitions
        plateau_mask = (
            df[plateau_name] >= current_plateau_threshold if plateau_name else pd.Series(True, index=df.index)
        )
        plateau_mask = (
            plateau_mask & (df[next_plateau_name] < next_plateau_threshold) if next_plateau_name else plateau_mask
        )
        current_plateau = df[plateau_mask]

        if not current_plateau.empty and plateau_name:
            # Only explore LB if plateau_name is provided
            current_lb = current_plateau["sizes"].min()
            before_current_plateau = df[df["sizes"] < current_lb]
            current_too_small = before_current_plateau["sizes"].max() if not before_current_plateau.empty else 0
            if current_too_small < current_lb - 1:
                explore_lb_size = int((current_lb + current_too_small) / 2)
                new_sizes.append(explore_lb_size)

        if not current_plateau.empty and next_plateau_name:
            # Only explore UB if next_plateau_name is provided
            current_ub = current_plateau["sizes"].max()
            after_current_plateau = df[df["sizes"] > current_ub]
            current_too_large = (
                after_current_plateau["sizes"].min() if not after_current_plateau.empty else self.MAX_DATA_SIZE
            )
            if current_too_large > current_ub + 1:
                explore_ub_size = int((current_ub + current_too_large) / 2)
                new_sizes.append(explore_ub_size)
        bounds[level_name] = {"LB": int(current_lb), "UB": int(current_ub)}

    def explore_plateau_endpoints(
        self, f, x_min, x_max, growth_factor=2, changed_threshold=0.08, unchanged_threshold=0.05
    ):
        """
        Explores plateau end points using exponential search and binary refinement.

        Parameters:
        f (function): The unknown function to evaluate.
        x_min (float): Minimum x value to start exploration.
        x_max (float): Maximum x value to stop exploration.
        growth_factor (float): Factor for exponential step increase.
        diff_threshold (float): Threshold for detecting a plateau end.
        max_refinements (int): Number of iterations for binary refinement.

        Returns:
        list: Explored (x, y) values.
        """
        # Phase 1: Exponential Sweep
        x = x_min
        explored_points = []

        while x < x_max:
            y = f(x)
            explored_points.append((x, float(y)))  # Ensure y is float
            x *= growth_factor  # Exponential step increase

        while True:
            new_points = set()

            for i in range(1, len(explored_points) - 1):
                x_prev, y_prev = explored_points[i - 1]
                x_curr, y_curr = explored_points[i]
                x_next, y_next = explored_points[i + 1]

                # Compute relative changes
                rel_y_change_prev = abs((y_curr - y_prev) / y_prev) if y_prev != 0 else 0
                rel_y_change_next = abs((y_next - y_curr) / y_curr) if y_curr != 0 else 0

                # If plateau-like before and sharp increase after, refine
                if rel_y_change_prev < unchanged_threshold and rel_y_change_next > changed_threshold:
                    x_mid = (x_curr + x_next) / 2
                    y_mid = f(x_mid)
                    log.debug(
                        "Adding Right edge %s, %s with rel prev %s and rel next %s",
                        x_mid,
                        y_mid,
                        rel_y_change_prev,
                        rel_y_change_next,
                    )
                    new_points.add((x_mid, y_mid))

                if rel_y_change_next < unchanged_threshold and rel_y_change_prev > changed_threshold:
                    x_mid = (x_curr + x_prev) / 2
                    y_mid = f(x_mid)
                    log.debug(
                        "Adding Left edge %s, %s with rel prev %s and rel next %s",
                        x_mid,
                        y_mid,
                        rel_y_change_prev,
                        rel_y_change_next,
                    )
                    new_points.add((x_mid, y_mid))

            # Stop refinement if no new points were added
            if not new_points:
                break

            # Update explored points with new refined data
            explored_points = sorted(set(explored_points) | new_points, key=lambda p: p[0])

        return explored_points

    def run_test(self):
        # Example usage with the precise_piecewise_sigmoid function
        explored_x_values = self.explore_plateau_endpoints(
            self.modeled_cpm, x_min=self.MIN_DATA_SIZE, x_max=self.MAX_DATA_SIZE
        )

        # Extract x and y values for plotting
        x_values, y_values = zip(*explored_x_values, strict=False)

        # Plot the results and save as PNG
        ub_rep.get_reporter().plot_test_results(explored_x_values, x_values, y_values)

    def run_kmeans_y(self, df, y_column="log_ll_average_latency", k=4):
        """
        Run K-Means clustering on a specified y-value column.

        Parameters:
            df (pd.DataFrame): The input DataFrame containing the y-values.
            y_column (str): The column name for clustering.
            k (int): The number of clusters.

        Returns:
            pd.DataFrame: The DataFrame with an additional 'y_cluster' column.
            np.ndarray: The cluster centers.
        """

        # Extract y-values and reshape for clustering
        y_values = df[y_column].values.reshape(-1, 1)

        # Apply K-Means clustering
        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
        df["y_cluster"] = kmeans.fit_predict(y_values)
        # Get original cluster centers
        original_centroids = kmeans.cluster_centers_

        # Sort the centroids and get the new cluster order
        sorted_indices = np.argsort(original_centroids.flatten()).tolist()  # Order indices based on centroid values
        new_cluster_order = {old_label: new_label for new_label, old_label in enumerate(sorted_indices)}

        # Reassign clusters based on sorted centroids
        df["y_cluster"] = df["y_cluster"].map(new_cluster_order)
        centroids = original_centroids[sorted_indices]

        # Compute median for each y_cluster
        cluster_medians = df.groupby("y_cluster")[y_column].median().rename("cluster_median")
        log.debug("Cluster medians: %s", cluster_medians)

        df = df.join(cluster_medians, on="y_cluster")
        df["absolute_deviation"] = abs(df[y_column] - df["cluster_median"])

        # Compute variation (variance) per cluster using Pandas vectorized operations
        df["squared_distance"] = (df[y_column] - df["y_cluster"].map(lambda x: centroids[x][0])) ** 2
        cluster_variation = (
            df
            .groupby("y_cluster")["squared_distance"]
            .mean()
            .reset_index()
            .rename(columns={"squared_distance": "cluster_variation"})
        )

        return df, kmeans.cluster_centers_, cluster_variation
