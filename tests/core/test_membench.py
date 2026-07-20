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
Simple tests of src/core/membench.py utilities
"""

from types import SimpleNamespace

import pytest
from asct.core.recipes.impl.memory_load_latency import IdleLatency, LoadedLatency
from asct.core.resources.hugepages import (
    HugePageAllocNodeEntry,
    HugePageAllocRequest,
    HugePageAllocSizeEntry,
    HugePageAllocState,
    HugePageAllocStatus,
    HugePageManager,
    HugepageUtility,
    PreallocatedHugepageImpl,
)


def test_that_always_passes():
    assert True


@pytest.mark.skip(reason="test for testing the testing infrastructure, enable for experiments")
def test_that_always_fails():
    assert False  # ruff:ignore[assert-false]


def test_loaded_latency_extrapolate_total_bw_accounts_for_other_numa_nodes(monkeypatch):
    recipe = LoadedLatency.__new__(LoadedLatency)
    monkeypatch.setattr(
        LoadedLatency,
        "cpu_list_per_node",
        property(lambda _self: {0: [0, 1, 2, 3], 1: [4, 5]}),
    )
    monkeypatch.setattr(LoadedLatency, "default_numa_node", property(lambda _self: 0))

    assert recipe.extrapolate_total_bw(60) == 100


def test_cross_numa_diff_data_is_keyed_by_run_node_then_mem_node():
    recipe = IdleLatency.__new__(IdleLatency)
    recipe._loaded_raw_result = {
        "Node 0": {"Node 0": 10, "Node 1": 20},
        "Node 1": {"Node 0": 30, "Node 1": 40},
    }

    assert recipe.get_diff_data() == {
        "Node 0": {"Node 0": 10, "Node 1": 30},
        "Node 1": {"Node 0": 20, "Node 1": 40},
    }


def test_hugepage_allocate_uses_unique_ready_page_counts_in_descending_order(monkeypatch):
    manager = HugePageManager()
    request_large_a = HugePageAllocRequest(node=0, page_size=2048, page_count=5, error=None)
    request_large_b = HugePageAllocRequest(node=0, page_size=2048, page_count=5, error=None)
    request_small = HugePageAllocRequest(node=0, page_size=2048, page_count=3, error=None)
    request_failed = HugePageAllocRequest(
        node=0, page_size=2048, page_count=9, error="prefailed", state=HugePageAllocState.FAILED
    )
    size_entry = HugePageAllocSizeEntry(
        initial_count=10,
        allocated_count=0,
        requests={
            1: request_large_a,
            2: request_large_b,
            3: request_small,
            4: request_failed,
        },
    )
    manager._alloc_status = HugePageAllocStatus(
        nodes={0: HugePageAllocNodeEntry(sizes={2048: size_entry})},
        all_requests={},
    )

    monkeypatch.setattr(manager, "_preverify", lambda: None)
    monkeypatch.setattr(manager, "_get_hugepage_settings", lambda: None)
    monkeypatch.setattr(manager, "_log_reallocations", lambda: None)

    calls = []

    def fake_allocate_huge_page(node_idx, size_kb, initial_count, page_count):
        calls.append((node_idx, size_kb, initial_count, page_count))
        if page_count == 5:
            raise MemoryError("too many pages")

    monkeypatch.setattr(HugepageUtility, "_allocate_huge_page", fake_allocate_huge_page)

    manager._allocate()

    assert calls == [(0, 2048, 10, 5), (0, 2048, 10, 3)]
    assert request_large_a.state == HugePageAllocState.FAILED
    assert request_large_b.state == HugePageAllocState.FAILED
    assert request_small.state == HugePageAllocState.SUCCESS
    assert request_failed.state == HugePageAllocState.FAILED
    assert size_entry.allocated_count == 13


def test_preallocated_hugepage_setup_accepts_existing_pages(monkeypatch):
    request = PreallocatedHugepageImpl({0: {1048576: 1}})
    request._available_page_sizes = {0: [1048576, 2048]}

    monkeypatch.setattr("asct.core.resources.hugepages.AGS", lambda: SimpleNamespace(disable_hugepage_resize=False))
    monkeypatch.setattr(
        HugepageUtility, "_read_free_hugepage_count", lambda node, size_kb: {(0, 1048576): 1}[node, size_kb]
    )

    request.setup()

    assert request.applied
    assert request.get_page_size() == 1048576 * 1024


def test_preallocated_hugepage_setup_uses_smaller_preallocated_pages(monkeypatch):
    request = PreallocatedHugepageImpl({0: {1048576: 1}})
    request._available_page_sizes = {0: [1048576, 2048]}
    free_pages = {
        (0, 1048576): 0,
        (0, 2048): 512,
    }

    monkeypatch.setattr("asct.core.resources.hugepages.AGS", lambda: SimpleNamespace(disable_hugepage_resize=False))
    monkeypatch.setattr(HugepageUtility, "_read_free_hugepage_count", lambda node, size_kb: free_pages[node, size_kb])

    request.setup()

    assert request.applied
    assert request.get_page_size() == 2048 * 1024
    assert request._requests[0].page_count == 512


def test_preallocated_hugepage_setup_raises_without_suitable_pages(monkeypatch):
    request = PreallocatedHugepageImpl({0: {1048576: 1}})
    request._available_page_sizes = {0: [1048576, 2048]}
    free_pages = {
        (0, 1048576): 0,
        (0, 2048): 511,
    }

    monkeypatch.setattr("asct.core.resources.hugepages.AGS", lambda: SimpleNamespace(disable_hugepage_resize=False))
    monkeypatch.setattr(HugepageUtility, "_read_free_hugepage_count", lambda node, size_kb: free_pages[node, size_kb])

    with pytest.raises(MemoryError, match="No preallocated hugepages available"):
        request.setup()


def test_preallocated_hugepage_checks_free_pages(monkeypatch):
    request = PreallocatedHugepageImpl({0: {2048: 2}})
    request._available_page_sizes = {0: [2048]}

    monkeypatch.setattr("asct.core.resources.hugepages.AGS", lambda: SimpleNamespace(disable_hugepage_resize=False))
    monkeypatch.setattr(HugepageUtility, "_read_allocated_hugepage_count", lambda _node, _size_kb: 2)
    monkeypatch.setattr(HugepageUtility, "_read_free_hugepage_count", lambda _node, _size_kb: 1)

    with pytest.raises(MemoryError, match="No preallocated hugepages available"):
        request.setup()
