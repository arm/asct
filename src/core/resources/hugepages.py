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
from enum import Enum
from dataclasses import dataclass

import asct.core.logger as log

from asct.core.asct_env import ASCTGlobalSettings as AGS
from asct.core.resources.resource_base import Resource
from asct.core.resources.check_sudo import CheckSudo
from asct.core.utility.misc import thread_safe
from asct.core.utility.format import memsize_str


# Note: all classes that manage huge pages use KiB as size units
class HugePageAllocState(Enum):
    READY = 0
    FAILED = 1
    SUCCESS = 2


@dataclass
class HugePageAllocRequest:
    node: int
    page_size: int
    page_count: int
    error: str
    orig_page_size: int = None
    state: HugePageAllocState = HugePageAllocState.READY


@dataclass
class HugePageAllocSizeEntry:
    initial_count: int
    allocated_count: int
    requests: dict[int, HugePageAllocRequest]


@dataclass
class HugePageAllocNodeEntry:
    sizes: dict[int, HugePageAllocSizeEntry]


@dataclass
class HugePageAllocStatus:
    nodes: dict[int, HugePageAllocNodeEntry]
    # quick way to get to a list of requests per requestor
    all_requests: dict[int, list]


NUMA_NODE_SYSFS_DIR = "/sys/devices/system/node"


def get_supported_hugepage_sizes():
    """Return supported huge page sizes per NUMA node.

    Scans /sys/devices/system/node/node<N>/hugepages/ for directories
    matching the pattern ``hugepages-<size>kB`` and extracts the numeric
    size from each entry.

    Returns:
        dict[int, list[int]]: A mapping of NUMA node index to a sorted list
            (largest first) of supported huge page sizes in kB for that node
            (e.g. {0: [1048576, 2048], 1: [1048576, 2048]}).
    """
    node_pattern = re.compile(r"^node(\d+)$")
    size_pattern = re.compile(r"^hugepages-(\d+)kB$")
    sizes_per_node = {}
    try:
        for node_entry in os.listdir(NUMA_NODE_SYSFS_DIR):
            node_match = node_pattern.match(node_entry)
            if not node_match:
                continue
            node_idx = int(node_match.group(1))
            hugepages_dir = os.path.join(NUMA_NODE_SYSFS_DIR, node_entry, "hugepages")
            try:
                sizes = []
                for size_entry in os.listdir(hugepages_dir):
                    size_match = size_pattern.match(size_entry)
                    if size_match:
                        sizes.append(int(size_match.group(1)))
                sizes_per_node[node_idx] = sorted(sizes, reverse=True)
            except FileNotFoundError:
                log.error(f"Hugepages directory '{hugepages_dir}' not found for NUMA node {node_idx}")
    except FileNotFoundError:
        log.error(f"NUMA node sysfs directory '{NUMA_NODE_SYSFS_DIR}' not found")
    return sizes_per_node


class HugePageSizeResolver:
    def __init__(self):
        self._available_page_sizes = None

    def _get_available_page_sizes(self):
        if not self._available_page_sizes:
            self._available_page_sizes = get_supported_hugepage_sizes()
        return self._available_page_sizes

    @staticmethod
    def _has_enough_free_pages(node, size_kb, count):
        try:
            free_count = HugepageUtility._read_free_hugepage_count(node, size_kb)
        except (OSError, ValueError) as exc:
            raise MemoryError(
                f"Unable to read free hugepages for size {memsize_str(size_kb * 1024)} on NUMA node {node}: {exc}"
            ) from exc
        if free_count >= count:
            return True
        log.debug(
            f"Hugepage request for {count} page(s) of size {memsize_str(size_kb * 1024)} "
            f"on NUMA node {node} cannot be satisfied by {free_count} free page(s)"
        )
        return False

    def _adjust_to_available_size(self, node, size_kb, count, valid_func=lambda _node, _size_kb, _count: True):
        """Adjust a page size and count to use an available hugepage size.

        If the requested size is available, returns it unchanged. Otherwise,
        selects the largest available size smaller than the requested one and
        scales the page count to cover the same total memory. ``valid_func``
        takes ``(node, size_kb, count)`` and returns whether the candidate is
        valid.

        Args:
            node: NUMA node index.
            size_kb: Requested page size in kB.
            count: Requested number of pages.
            valid_func: Callable that validates a size and count for a node.
        Returns:
            tuple[int, int]: (adjusted_size_kb, adjusted_count).

        Raises:
            MemoryError: If no suitable page size is available on the node.
        """
        available_sizes = self._get_available_page_sizes().get(node, [])
        if size_kb in available_sizes and valid_func(node, size_kb, count):
            return size_kb, count

        # Find the largest available size smaller than requested.
        # available_sizes is sorted largest-first, so the first
        # entry smaller than size_kb is the best fallback.
        fallback = None
        if not AGS().disable_hugepage_resize:
            for avail_size in available_sizes:
                if avail_size < size_kb and size_kb % avail_size == 0:
                    adjusted_count = count * (size_kb // avail_size)
                    if valid_func(node, avail_size, adjusted_count):
                        fallback = avail_size
                        break
        if fallback is None:
            if available_sizes:
                raise MemoryError(
                    f"No suitable hugepage size available on NUMA node {node} "
                    f"for requested size {memsize_str(size_kb * 1024)} "
                    f"(available: {', '.join(f'{memsize_str(s * 1024)}' for s in available_sizes)})"
                )
            raise MemoryError(f"Hugepages are not enabled for NUMA node {node} on this system")
        scale_factor = size_kb // fallback
        adjusted_count = count * scale_factor
        log.debug(
            f"Hugepage size {memsize_str(size_kb * 1024)} not available on NUMA node {node}, "
            f"using {memsize_str(fallback * 1024)} with {adjusted_count} pages instead"
        )
        return fallback, adjusted_count

    def adjust_to_available_size(self, node, size_kb, count):
        return self._adjust_to_available_size(node, size_kb, count)

    def adjust_to_available_free_size(self, node, size_kb, count):
        return self._adjust_to_available_size(
            node,
            size_kb,
            count,
            self._has_enough_free_pages,
        )


class HugepageUtility:
    @classmethod
    def _get_hugepage_node_path(cls, node):
        return os.path.join(NUMA_NODE_SYSFS_DIR, f"node{node}")

    @classmethod
    def _get_hugepage_sysfs_path(cls, node, size_kb):
        return os.path.join(cls._get_hugepage_node_path(node), f"hugepages/hugepages-{size_kb}kB/nr_hugepages")

    @classmethod
    def _read_allocated_hugepage_count(cls, node, size_kb):
        sysfs_path = cls._get_hugepage_sysfs_path(node, size_kb)
        return int(Resource._get_sysfile_value(sysfs_path))

    @classmethod
    def _read_free_hugepage_count(cls, node, size_kb):
        sysfs_path = os.path.join(cls._get_hugepage_node_path(node), f"hugepages/hugepages-{size_kb}kB/free_hugepages")
        return int(Resource._get_sysfile_value(sysfs_path))

    @classmethod
    def _write_hugepage_info(cls, node, size_kb, page_count):
        # Directly write the amount of requested pages to
        # /sys/devices/system/node/node[0-N]/hugepages/hugepages-<size>/nr_hugepages
        # as we need to control per-node huge page settings, more information below:
        # https://www.kernel.org/doc/html/v5.16/admin-guide/mm/hugetlbpage.html?highlight=numa
        sysfs_path = cls._get_hugepage_sysfs_path(node, size_kb)
        Resource._set_sysfile_value(sysfs_path, f"{page_count}")

    @classmethod
    def _allocate_huge_page(cls, node_idx, size_kb, initial_count, added_count):
        count = initial_count + added_count
        cls._write_hugepage_info(node_idx, size_kb, count)
        if cls._read_allocated_hugepage_count(node_idx, size_kb) != count:
            raise MemoryError(
                f"Failed to allocate {added_count} huge pages with size {memsize_str(size_kb * 1024)} "
                f"on NUMA node {node_idx} (already allocated: {initial_count} pages)"
            )


class HugePageManager(HugePageSizeResolver):
    """This singleton follows this linear state transition
    [Creation] -> [request_allocation] x n -> [Pre-Validation] -> [Allocation] -> [request_deallocation] x n -> [Done]
                  |     alloc_done = False  ||         alloc_done = True       ||
    """

    def __init__(self):
        super().__init__()
        self._alloc_done = False
        self._alloc_status = HugePageAllocStatus(nodes={}, all_requests={})

    @thread_safe
    def request_allocation(self, requestor, request_info):
        """
        Requests pages to be allocated during setup

        Args:
            request_info - a dictionary where request_info[node][page_size_in_kb] = page_count
        """
        self._get_available_page_sizes()
        self._update_alloc_status_with_request(requestor, request_info)

    def _update_alloc_status_with_request(self, requestor, request_info):
        if self._alloc_done:
            raise AssertionError(
                "Invalid allocation request - requesting an allocation after allocation stage completed"
            )
        alloc_status = self._alloc_status
        for node, sizes in request_info.items():
            if node not in alloc_status.nodes:
                alloc_status.nodes[node] = HugePageAllocNodeEntry(sizes={})
            for page_size_in_kb, count in sizes.items():
                adjusted_size, adjusted_count = self.adjust_to_available_size(node, page_size_in_kb, count)
                orig_page_size = page_size_in_kb if adjusted_size != page_size_in_kb else None

                if adjusted_size not in alloc_status.nodes[node].sizes:
                    alloc_status.nodes[node].sizes[adjusted_size] = HugePageAllocSizeEntry(
                        initial_count=0, allocated_count=0, requests={}
                    )
                request = HugePageAllocRequest(
                    node=node,
                    page_size=adjusted_size,
                    page_count=adjusted_count,
                    orig_page_size=orig_page_size,
                    state=HugePageAllocState.READY,
                    error=None,
                )

                requestor_id = id(requestor)
                alloc_status.nodes[node].sizes[adjusted_size].requests[requestor_id] = request
                if requestor_id not in alloc_status.all_requests:
                    alloc_status.all_requests[requestor_id] = []
                alloc_status.all_requests[requestor_id].append(request)

    def _get_hugepage_settings(self):
        """
        Updates self._alloc_status with the current status.

        Reads system files at:
        /sys/devices/system/node/node[0-N]/hugepages/hugepages-<size>kB/nr_hugepages.
        """
        for node, node_data in self._alloc_status.nodes.items():
            for size_kb, entry in node_data.sizes.items():
                try:
                    allocated_count = HugepageUtility._read_allocated_hugepage_count(node, size_kb)
                except (OSError, ValueError) as exc:  # ruff:ignore[try-except-in-loop]
                    self._set_request_state(
                        node, size_kb, HugePageAllocState.FAILED, f"Unable to read current hugepage config: {exc}"
                    )
                else:
                    entry.initial_count = allocated_count

    def _set_request_state(self, node, size_kb, state, error=None, request_filter=None):
        nodes = [node] if node is not None else self._alloc_status.nodes.keys()
        for node_idx in nodes:
            node_data = self._alloc_status.nodes[node_idx]
            sizes = [size_kb] if size_kb is not None else node_data.sizes.keys()
            for current_size_kb in sizes:
                requests = node_data.sizes[current_size_kb].requests
                for req in requests.values():
                    if request_filter and not request_filter(req):
                        continue
                    req.state = state
                    if error:
                        req.error = error

    def _preverify(self):
        for node_idx, node_data in self._alloc_status.nodes.items():
            node_path = HugepageUtility._get_hugepage_node_path(node_idx)
            if not os.path.exists(node_path):
                self._set_request_state(
                    node_idx, None, HugePageAllocState.FAILED, f"Requested NUMA sysfs path '{node_path}' not found"
                )
                continue
            for size_kb in node_data.sizes:
                sysfs_path = HugepageUtility._get_hugepage_sysfs_path(node_idx, size_kb)
                if not os.path.exists(sysfs_path):
                    self._set_request_state(
                        node_idx,
                        size_kb,
                        HugePageAllocState.FAILED,
                        f"Requested huge page sysfs path '{sysfs_path}' not found",
                    )
                elif not os.access(sysfs_path, os.W_OK):
                    self._set_request_state(
                        node_idx,
                        size_kb,
                        HugePageAllocState.FAILED,
                        f"sysfs file '{sysfs_path}' is not writeable - please run asct using sudo",
                    )

    def _log_reallocations(self):
        """Log all unique hugepage size reallocations across all nodes."""
        seen = set()
        for node_data in self._alloc_status.nodes.values():
            for size_data in node_data.sizes.values():
                for req in size_data.requests.values():
                    if req.orig_page_size is not None:
                        key = (req.orig_page_size, req.page_size, req.page_count)
                        if key not in seen:
                            seen.add(key)
                            orig_count = req.page_count // (req.orig_page_size // req.page_size)
                            log.warning(
                                f"Unable to find {orig_count} hugepage(s) of size "
                                f"{memsize_str(req.orig_page_size * 1024)}, "
                                f"using {req.page_count} hugepage(s) of size "
                                f"{memsize_str(req.page_size * 1024)} instead"
                            )

    def _allocate(self):
        self._preverify()
        self._get_hugepage_settings()
        self._log_reallocations()
        for node_idx, node_data in self._alloc_status.nodes.items():
            for size_kb, size_data in node_data.sizes.items():
                # step 1: collect all unique page counts for all the requestors which
                # weren't invalidated by _preverify
                page_counts = {
                    req.page_count for req in size_data.requests.values() if req.state == HugePageAllocState.READY
                }
                # step 2: sort the unique page counts from largest to smallest
                page_counts = sorted(page_counts, reverse=True)
                # step 3: try to allocate the largest page count and update the requests that were fulfilled
                for page_count in page_counts:
                    try:
                        HugepageUtility._allocate_huge_page(node_idx, size_kb, size_data.initial_count, page_count)
                    except (MemoryError, OSError, ValueError) as exc:  # ruff:ignore[try-except-in-loop]
                        self._set_request_state(
                            node_idx,
                            size_kb,
                            HugePageAllocState.FAILED,
                            f"{exc}",
                            lambda r, failed_page_count=page_count: r.page_count == failed_page_count,
                        )
                    else:
                        size_data.allocated_count = size_data.initial_count + page_count
                        self._set_request_state(
                            node_idx,
                            size_kb,
                            HugePageAllocState.SUCCESS,
                            "",
                            lambda r, allocated_page_count=page_count: r.page_count <= allocated_page_count,
                        )
                        break

    @thread_safe
    def acquire(self, requestor):
        """
        First requestor to call acquire() triggers the allocation, the rest will
        verify if the allocations succeded and, if not, raise a MemoryError using the same message
        """
        requestor_id = id(requestor)
        if not self._alloc_done:
            self._allocate()
            self._alloc_done = True

        if requestor_id not in self._alloc_status.all_requests:
            raise AssertionError("acquire() called without calling request_allocation")

        # Check if all requests associated with this requestor have been successful, if not -> throw exception
        success = all(x.state == HugePageAllocState.SUCCESS for x in self._alloc_status.all_requests[requestor_id])
        if not success:
            # on failure, just pass the error message from the first request that failed
            for req in filter(
                lambda r: r.state == HugePageAllocState.FAILED, self._alloc_status.all_requests[requestor_id]
            ):
                raise MemoryError(f"{req.error}")

    @thread_safe
    def release(self, requestor):
        if not self._alloc_done:
            raise AssertionError(
                "Invalid allocation release - releasing a huge page allocation before allocation stage completed"
            )
        requestor_id = id(requestor)
        if requestor_id not in self._alloc_status.all_requests:
            raise AssertionError("release() called twice for the same requestor")

        requestor_id = id(requestor)
        for request in self._alloc_status.all_requests[requestor_id]:
            node = request.node
            size_kb = request.page_size
            size_info = self._alloc_status.nodes[node].sizes[size_kb]
            del size_info.requests[requestor_id]

            # if there are no more registered allocs and there was
            # a successful allocation for this node/page, resize to original size
            if not size_info.requests and size_info.allocated_count > size_info.initial_count:
                try:
                    HugepageUtility._write_hugepage_info(node, size_kb, size_info.initial_count)
                except (OSError, ValueError) as exc:
                    log.error(f"Unable to deallocate a hugepage: {exc}")
        del self._alloc_status.all_requests[requestor_id]


class HugepageImpl(Resource):
    _huge_page_manager = HugePageManager()

    def __init__(self, request_info):
        super().__init__()
        HugepageImpl._huge_page_manager.request_allocation(self, request_info)

    def setup(self):
        HugepageImpl._huge_page_manager.acquire(self)

    def teardown(self):
        HugepageImpl._huge_page_manager.release(self)

    def get_page_size(self):
        # Assumes all requests for this resource are for the same page size (which is currently the only usage pattern)
        request = HugepageImpl._huge_page_manager._alloc_status.all_requests[id(self)][0]
        return request.page_size * 1024


class PreallocatedHugepageImpl(Resource, HugePageSizeResolver):
    def __init__(self, request_info):
        Resource.__init__(self)
        HugePageSizeResolver.__init__(self)
        self._request_info = request_info
        self._requests = []

    def _resolve_request(self, node, size_kb, count):
        try:
            adjusted_size, adjusted_count = self.adjust_to_available_free_size(node, size_kb, count)
        except MemoryError as exc:
            raise MemoryError(
                f"No preallocated hugepages available to satisfy request for {count} page(s) of size "
                f"{memsize_str(size_kb * 1024)} on NUMA node {node}"
            ) from exc

        if adjusted_size != size_kb:
            log.warning(
                f"Unable to find preallocated hugepage(s) of size {memsize_str(size_kb * 1024)}, "
                f"using {adjusted_count} preallocated hugepage(s) of size "
                f"{memsize_str(adjusted_size * 1024)} instead"
            )
        return HugePageAllocRequest(
            node=node,
            page_size=adjusted_size,
            page_count=adjusted_count,
            orig_page_size=size_kb if adjusted_size != size_kb else None,
            error=None,
            state=HugePageAllocState.SUCCESS,
        )

    def setup(self):
        self._requests = []
        self._get_available_page_sizes()
        for node, sizes in self._request_info.items():
            for page_size_in_kb, count in sizes.items():
                self._requests.append(self._resolve_request(node, page_size_in_kb, count))
        self.applied = True

    def teardown(self):
        pass

    def get_page_size(self):
        # Assumes all requests for this resource are for the same page size (which is currently the only usage pattern)
        return self._requests[0].page_size * 1024


class HugepageNoOp(Resource):
    def __init__(self, _):
        super().__init__()

    def setup(self):
        pass

    def teardown(self):
        pass

    def get_page_size(self):
        return 0


def Hugepage(requested_size):
    if AGS().dev_mode():
        return HugepageNoOp(requested_size)
    using_sudo = True
    try:
        CheckSudo().setup()
    except RuntimeError:
        using_sudo = False
    return HugepageImpl(requested_size) if using_sudo else PreallocatedHugepageImpl(requested_size)
