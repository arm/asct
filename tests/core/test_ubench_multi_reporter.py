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

import matplotlib

matplotlib.use("Agg")

import pytest
import pandas as pd

from unittest.mock import MagicMock
from asct.core.managers.ubench_multi_reporter import MultiUbenchReporter

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _dfs(*col_lists):
    """Build labeled_dfs from a list of column-name lists."""
    return [(f"run{i}", pd.DataFrame(columns=cols)) for i, cols in enumerate(col_lists)]


# ---------------------------------------------------------------------------
# _pick_latency_schemas
# ---------------------------------------------------------------------------


class TestPickLatencySchemas:
    def test_ns_only(self):
        dfs = _dfs(["sizes", "average_latency"], ["sizes", "average_latency_ns"])
        dfs = [(label, MultiUbenchReporter._rename_latency_sweep_df_columns(df)) for label, df in dfs]
        result = MultiUbenchReporter._pick_latency_schemas(dfs)
        assert result == [("average_latency_ns", "ns")]

    def test_cycle_only(self):
        dfs = _dfs(["sizes", "average_latency_cyc"], ["sizes", "average_latency_cyc"])
        result = MultiUbenchReporter._pick_latency_schemas(dfs)
        assert result == [("average_latency_cyc", "cycle")]

    def test_cycle_and_ns(self):
        dfs = _dfs(
            ["sizes", "average_latency_cyc", "average_latency_ns"],
            ["sizes", "average_latency_cyc", "average_latency_ns"],
        )
        result = MultiUbenchReporter._pick_latency_schemas(dfs)
        assert ("average_latency_cyc", "cycle") in result
        assert ("average_latency_ns", "ns") in result

    def test_legacy_average_latency(self):
        dfs = _dfs(["sizes", "average_latency_ns"], ["sizes", "average_latency_ns"])
        result = MultiUbenchReporter._pick_latency_schemas(dfs)
        assert result == [("average_latency_ns", "ns")]

    def test_mixed_datasets_raises(self):
        # One df has ns, the other doesn't — no consistent unit
        dfs = _dfs(["sizes", "average_latency_ns"], ["sizes"])
        with pytest.raises(ValueError, match="Mixed latency units"):
            MultiUbenchReporter._pick_latency_schemas(dfs)

    def test_no_latency_columns_raises(self):
        dfs = _dfs(["sizes"], ["sizes"])
        with pytest.raises(ValueError, match="Mixed latency units"):
            MultiUbenchReporter._pick_latency_schemas(dfs)


# ---------------------------------------------------------------------------
# _pick_loaded_latency_units
# ---------------------------------------------------------------------------


class TestPickLoadedLatencyUnits:
    def test_ns_only(self):
        dfs = _dfs(["Loaded latency [ns]"], ["Loaded latency [ns]"])
        assert MultiUbenchReporter._pick_loaded_latency_units(dfs) == ["ns"]

    def test_cycle_only(self):
        dfs = _dfs(["Loaded latency [cycle]"], ["Loaded latency [cycle]"])
        assert MultiUbenchReporter._pick_loaded_latency_units(dfs) == ["cycle"]

    def test_both_units(self):
        dfs = _dfs(
            ["Loaded latency [ns]", "Loaded latency [cycle]"],
            ["Loaded latency [ns]", "Loaded latency [cycle]"],
        )
        result = MultiUbenchReporter._pick_loaded_latency_units(dfs)
        assert "ns" in result
        assert "cycle" in result

    def test_mixed_datasets_raises(self):
        dfs = _dfs(["Loaded latency [ns]"], ["Loaded latency [cycle]"])
        with pytest.raises(ValueError, match="Mixed loaded-latency units"):
            MultiUbenchReporter._pick_loaded_latency_units(dfs)

    def test_no_latency_columns_raises(self):
        dfs = _dfs(["sizes"], ["sizes"])
        with pytest.raises(ValueError, match="Mixed loaded-latency units"):
            MultiUbenchReporter._pick_loaded_latency_units(dfs)


# ---------------------------------------------------------------------------
# _pick_bandwidth_sweep_rate_units
# ---------------------------------------------------------------------------


class TestPickBandwidthSweepRateUnits:
    def test_bps_via_mbps(self):
        dfs = _dfs(["sizes", "total_bandwidth_mbps"], ["sizes", "total_bandwidth_mbps"])
        result = MultiUbenchReporter._pick_bandwidth_sweep_rate_units(dfs)
        assert "B/s" in result
        assert "B/cycle" not in result

    def test_bps_via_legacy(self):
        dfs = _dfs(["sizes", "total_bandwidth"], ["sizes", "total_bandwidth"])
        result = MultiUbenchReporter._pick_bandwidth_sweep_rate_units(dfs)
        assert "B/s" in result

    def test_bpc(self):
        dfs = _dfs(["sizes", "total_bandwidth_bpc"], ["sizes", "total_bandwidth_bpc"])
        result = MultiUbenchReporter._pick_bandwidth_sweep_rate_units(dfs)
        assert "B/cycle" in result
        assert "B/s" not in result

    def test_both_units(self):
        dfs = _dfs(
            ["sizes", "total_bandwidth_mbps", "total_bandwidth_bpc"],
            ["sizes", "total_bandwidth_mbps", "total_bandwidth_bpc"],
        )
        result = MultiUbenchReporter._pick_bandwidth_sweep_rate_units(dfs)
        assert "B/s" in result
        assert "B/cycle" in result

    def test_mixed_datasets_raises(self):
        # One df has mbps, other has bpc only
        dfs = _dfs(["sizes", "total_bandwidth_mbps"], ["sizes", "total_bandwidth_bpc"])
        with pytest.raises(ValueError, match="Mixed bandwidth units"):
            MultiUbenchReporter._pick_bandwidth_sweep_rate_units(dfs)

    def test_no_bandwidth_columns_raises(self):
        dfs = _dfs(["sizes"], ["sizes"])
        with pytest.raises(ValueError, match="Mixed bandwidth units"):
            MultiUbenchReporter._pick_bandwidth_sweep_rate_units(dfs)


# ---------------------------------------------------------------------------
# _pick_pmu_latency_metric
# ---------------------------------------------------------------------------


class TestPickPmuLatencyMetric:
    def test_returns_versioned_metric_when_present(self):
        dfs = _dfs(["PMU_rd_latency [ns]"], ["PMU_rd_latency [ns]"])
        assert MultiUbenchReporter._pick_pmu_latency_metric(dfs, "ns") == "PMU_rd_latency [ns]"

    def test_falls_back_to_legacy_pmu_lat(self):
        dfs = _dfs(["PMU_lat [ns]"], ["PMU_lat [ns]"])
        assert MultiUbenchReporter._pick_pmu_latency_metric(dfs, "ns") == "PMU_lat [ns]"

    def test_versioned_preferred_over_legacy(self):
        dfs = _dfs(["PMU_rd_latency [cycle]", "PMU_lat [ns]"], ["PMU_rd_latency [cycle]", "PMU_lat [ns]"])
        assert MultiUbenchReporter._pick_pmu_latency_metric(dfs, "cycle") == "PMU_rd_latency [cycle]"

    def test_returns_none_when_no_pmu_columns(self):
        dfs = _dfs(["sizes"], ["sizes"])
        assert MultiUbenchReporter._pick_pmu_latency_metric(dfs, "ns") is None

    def test_returns_none_when_only_partial_datasets_have_pmu(self):
        # Not all datasets have the metric, so None is returned
        dfs = _dfs(["PMU_rd_latency [ns]"], ["sizes"])
        assert MultiUbenchReporter._pick_pmu_latency_metric(dfs, "ns") is None


# ---------------------------------------------------------------------------
# Fixtures for instance-method tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def reporter(tmp_path):
    """Fresh MultiUbenchReporter instance with a temporary output directory."""
    MultiUbenchReporter._inst = None
    r = MultiUbenchReporter()
    r.output_dir = str(tmp_path)
    yield r
    MultiUbenchReporter._inst = None


def _labeled_df(label, data: dict) -> tuple:
    return label, pd.DataFrame(data)


# ---------------------------------------------------------------------------
# plot_latency_sweep_results
# ---------------------------------------------------------------------------


class TestPlotLatencySweepResults:
    def test_result_type_and_log_scale(self, reporter):
        reporter.plot_perf_data = MagicMock()
        dfs = [_labeled_df("run0", {"sizes": [1024], "average_latency_ns": [10.0]})]
        reporter.plot_latency_sweep_results(dfs, "average_latency_ns", "ns")
        kw = reporter.plot_perf_data.call_args[1]
        assert kw["result_type"] == "latency-sweep_ns"
        assert kw["log_scale"] is True

    def test_output_file_is_valid_png(self, reporter, tmp_path):
        dfs = [_labeled_df("run0", {"sizes": [1024, 2048], "average_latency_ns": [10.0, 12.0]})]
        reporter.plot_latency_sweep_results(dfs, "average_latency_ns", "ns")
        out = tmp_path / "latency-sweep_ns.png"
        assert out.exists()
        assert out.read_bytes()[:8] == _PNG_SIGNATURE


# ---------------------------------------------------------------------------
# plot_bandwidth_sweep_results
# ---------------------------------------------------------------------------


class TestPlotBandwidthSweepResults:
    def test_converts_mbps_to_bps_and_encodes_result_type(self, reporter):
        reporter.plot_perf_data = MagicMock()
        reporter.plot_misses = MagicMock()
        dfs = [_labeled_df("run0", {"sizes": [1024], "total_bandwidth_mbps": [100.0]})]
        reporter.plot_bandwidth_sweep_results(dfs, "B/s", plot_misses=False)
        kw = reporter.plot_perf_data.call_args[1]
        assert kw["result_type"] == "bandwidth-sweep_b_per_s"
        _, df = reporter.plot_perf_data.call_args[0][0][0]
        assert df["total_bandwidth [B/s]"].iloc[0] == pytest.approx(100.0 * 1e6)

    def test_skips_dataset_missing_required_column(self, reporter):
        reporter.plot_perf_data = MagicMock()
        reporter.plot_misses = MagicMock()
        # B/cycle requested but only mbps column present
        dfs = [_labeled_df("run0", {"sizes": [1024], "total_bandwidth_mbps": [100.0]})]
        reporter.plot_bandwidth_sweep_results(dfs, "B/cycle", plot_misses=False)
        reporter.plot_perf_data.assert_not_called()

    def test_output_file_is_valid_png(self, reporter, tmp_path):
        dfs = [_labeled_df("run0", {"sizes": [1024, 2048], "total_bandwidth_mbps": [100.0, 200.0]})]
        reporter.plot_bandwidth_sweep_results(dfs, "B/s", plot_misses=False)
        out = tmp_path / "bandwidth-sweep_b_per_s.png"
        assert out.exists()
        assert out.read_bytes()[:8] == _PNG_SIGNATURE


# ---------------------------------------------------------------------------
# plot_loaded_latency_results
# ---------------------------------------------------------------------------


class TestPlotLoadedLatencyResults:
    def test_output_file_is_valid_png(self, reporter, tmp_path):
        dfs = [_labeled_df("run0", {"Loaded latency [ns]": [5.0, 10.0, 15.0]})]
        reporter.plot_loaded_latency_results(dfs, "ns", 0.15)
        out = tmp_path / "loaded-latency_ns.png"
        assert out.exists()
        assert out.read_bytes()[:8] == _PNG_SIGNATURE

    def test_no_file_written_when_no_latency_data(self, reporter, tmp_path):
        # All datasets missing the latency column -> early return, no file
        dfs = [_labeled_df("run0", {"other_col": [1.0, 2.0]})]
        reporter.plot_loaded_latency_results(dfs, "ns", 0.15)
        assert not (tmp_path / "loaded-latency_ns.png").exists()
