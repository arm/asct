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

import pytest

import os
import psutil
import shutil
import signal
import subprocess
import tempfile
import pathlib
from functools import lru_cache

ALL_BENCHMARKS = {
    "memory": [
        ("idle-latency", "il"),
        ("latency-sweep", "ls"),
        ("peak-bandwidth", "pb"),
        ("cross-numa-bandwidth", "cnb"),
        ("bandwidth-sweep", "bs"),
        ("loaded-latency", "ll"),
    ],
    "storage": [
        ("storage-request-size-sweep", "srss"),
        ("storage-io-depth-sweep", "sids"),
        ("storage-process-count-sweep", "spcs"),
        ("storage-access-pattern-sweep", "saps"),
    ],
}


ASCT_TEST_RUN_MODE_PR = "pull_request"
ASCT_TEST_RUN_MODE_RELEASE = "release"
ASCT_TEST_RUN_MODE_SCHEDULE = "schedule"

SYSFS_NODE_BASE = "/sys/devices/system/node"
SYSFS_HP_FILE = "hugepages/hugepages-1048576kB/nr_hugepages"
SYSFS_NODES_ONLINE_FILE = os.path.join(SYSFS_NODE_BASE, "online")

ASCT_LOCK_DIR = "/var/lock/_asct_.lock"


def pytest_addoption(parser):
    parser.addoption(
        "--test-type",
        type=str,
        default=ASCT_TEST_RUN_MODE_PR,
        help="Configuration for running the test suite [pull_request, release, schedule]",
    )
    parser.addoption(
        "--work-dir", type=str, default="test_work_dir", help="Directory to store output data from running the tool"
    )
    parser.addoption(
        "--runner-name", type=str.lower, default="unknown", help="Name of the github runner on which this is ran"
    )
    parser.addoption(
        "--skip-hugepage-delloc",
        action="store_true",
        help="Skip hugepage deallocation and leak checks when hugepages are managed externally",
    )


def runner_is_bare_metal(runner_name):
    return "astra" in runner_name


def pytest_collection_modifyitems(config, items):
    test_type = config.getoption("--test-type")
    skip_on_pr = pytest.mark.skip(reason="this test is skipped with --test-type pull_request")
    for item in items:
        if "skip_on_pr" in item.keywords and test_type == ASCT_TEST_RUN_MODE_PR:
            item.add_marker(skip_on_pr)


@pytest.fixture
def work_dir(request):
    return request.config.getoption("--work-dir")


@pytest.fixture
def is_bare_metal(request):
    runner_name = request.config.getoption("--runner-name")
    return runner_is_bare_metal(runner_name)


@pytest.fixture
def memory_benchmarks():
    return [x[0] for x in ALL_BENCHMARKS["memory"]]


@pytest.fixture
def memory_benchmarks_all_names():
    return ALL_BENCHMARKS["memory"]


@pytest.fixture
def short_memory_benchmark():
    return "cross-numa-bandwidth"


@pytest.fixture
def long_memory_benchmark():
    return "latency-sweep"


@pytest.fixture
def test_work_dir(work_dir):
    tmp_dir = tempfile.TemporaryDirectory(dir=work_dir)
    yield tmp_dir.name


@pytest.fixture
def shorter_test_time(request):
    return request.config.getoption("--test-type") == ASCT_TEST_RUN_MODE_PR


def is_root():
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False


def get_pids_using_lsof(lock_file):
    """Internal helper for get_pids_using_lock that uses lsof to find PIDs using the lock file."""
    pids = set()
    # Check if we are root
    cmd = ["lsof", "-t", lock_file]
    if not is_root():
        cmd = ["sudo", *cmd]

    lines = []
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        print(f"Error running lsof: {e}")
        return pids
    text = result.stdout.strip()
    lines = text.splitlines() if text else []
    for line in lines:
        line = line.strip()
        if line.isdigit():
            pids.add(int(line))

    if result.returncode != 0 and not pids:
        print(f"lsof failed: {result.stderr.strip()}")
    return pids


def get_pids_using_lock(lock_file):
    """Run lsof (with sudo if needed) on the lock file and return a list of PIDs using it."""
    pids = get_pids_using_lsof(lock_file)
    if pids:
        return sorted(pids)

    cmd = ["fuser", lock_file]
    if not is_root():
        cmd = ["sudo", *cmd]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        print(f"Error running fuser: {e}")
        return pids
    for item in result.stdout.split():
        pid_str = ""
        for ch in item:
            if ch.isdigit():
                pid_str += ch
            else:
                break
        if pid_str:
            pids.add(int(pid_str))

    if result.returncode != 0 and not pids:
        print(f"fuser failed: {result.stderr.strip()}")

    return sorted(pids)


def kill_process(pid, is_parent):
    """Kill processes by process handle (with sudo if needed)."""
    descr = "parent" if is_parent else "child"
    try:
        if is_root():
            os.kill(pid, signal.SIGKILL)
            print(f"Killed {descr} process {pid}")
        else:
            # Use sudo kill if not root
            result = subprocess.run(
                ["sudo", "kill", "-9", str(pid)],  # ruff:ignore[start-process-with-partial-path]
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                print(f"Killed {descr} process {pid}")
            else:
                print(f"Failed to kill {descr} process {pid}: {result.stderr.strip()}")
    except ProcessLookupError:
        print(f"The {descr} process {pid} no longer exists")
    except PermissionError:
        print(f"Permission denied to kill {descr} process {pid}")
    except (OSError, subprocess.SubprocessError) as e:
        print(f"Unexpected error while killing {descr} process {pid}: {e}")


def kill_process_tree(pid):
    """Kill a process and all of its children (with sudo if needed)."""
    try:
        proc = psutil.Process(pid)
        children = proc.children(recursive=True)

        # Kill children first
        for child in children:
            kill_process(child.pid, False)

        # Kill the parent
        kill_process(pid, True)

    except psutil.NoSuchProcess:
        print(f"The parent process {pid} no longer exists")
    except psutil.AccessDenied:
        print(f"Permission denied to inspect/kill parent process {pid}")
    except (psutil.Error, OSError) as e:
        print(f"Unexpected error while handling parent process {pid}: {e}")


def delete_lock_dir(path):
    """
    Delete the lock directory (with sudo if not root).
    """
    path = os.path.realpath(path)

    if is_root():
        shutil.rmtree(path)
        print(f"Deleted lock directory {path}")
    else:
        # Use sudo rm -rf for directories requiring elevated privileges
        result = subprocess.run(
            ["sudo", "rm", "-rf", path],  # ruff:ignore[start-process-with-partial-path]
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            print(f"Deleted lock directory {path}")
        else:
            raise RuntimeError(f"Failed to delete {path}: {result.stderr.strip()}")


def read_int(path):
    with open(path, "r") as f:
        return int(f.read().strip())


def write_int(path, value, use_sudo):
    """
    Write an integer value to a sysfs file.
    If use_sudo=True, writes via `sudo tee` to bypass permissions.
    """
    if use_sudo:
        subprocess.run(
            ["sudo", "tee", path],  # ruff:ignore[start-process-with-partial-path]
            input=f"{value}\n".encode(),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        pathlib.Path(path).write_text(f"{value}\n")


@lru_cache(maxsize=1)
def get_max_numa_node_index():
    try:
        # gets the max from the online node info which can have one of the following formats:
        # - single value: 0
        # - range: 0-3
        # - comma separated list of the two above: 0,2-4,6
        max_numa_node_idx = 0
        with pathlib.Path(SYSFS_NODES_ONLINE_FILE).open("rt", encoding="utf-8") as sysfs_nodes_file:
            active_nodes_string = sysfs_nodes_file.read().strip()
        for item in active_nodes_string.split(","):
            cur_node_idx = 0
            if "-" in item:
                cur_node_idx = int(item.split("-")[1])
            else:
                cur_node_idx = int(item)
            max_numa_node_idx = max(max_numa_node_idx, cur_node_idx)
        return max_numa_node_idx
    except (OSError, ValueError, TypeError, IndexError) as e:
        print(f"Unable to determine max numa node, reverting to 0: {e}")
        return 0


def free_all_1g_hugepages():
    """
    Frees all 1GiB hugepages per NUMA node by setting their counters to 0.
    Prints a message only if a deallocation took place.
    """
    use_sudo = not is_root()

    for node_id in range(get_max_numa_node_index() + 1):
        node_dir = os.path.join(SYSFS_NODE_BASE, f"node{node_id}")
        if not os.path.exists(node_dir):
            continue

        nr_path = os.path.join(node_dir, SYSFS_HP_FILE)
        if not os.path.exists(nr_path):
            continue

        try:
            count = read_int(nr_path)
            if count > 0:
                write_int(nr_path, 0, use_sudo=use_sudo)
                print(f"Deallocated {count} 1GiB hugepages from NUMA node{node_id}")
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            raise RuntimeError(f"Error deallocating huge page on NUMA node{node_id}: {e}") from e


def check_1g_hugepage_leaks():
    for node_id in range(get_max_numa_node_index() + 1):
        node_dir = os.path.join(SYSFS_NODE_BASE, f"node{node_id}")
        if not os.path.exists(node_dir):
            continue
        nr_path = os.path.join(node_dir, SYSFS_HP_FILE)
        if not os.path.exists(nr_path):
            continue
        count = read_int(nr_path)
        if count != 0:
            raise AssertionError(f"Huge pages leak found: {count} 1GiB pages on NUMA node {node_id}")


# Per test session setup/teardown
@pytest.fixture(scope="session", autouse=True)
def setup_environment(request):
    # setup: clean locks and deallocate all huge pages
    if os.path.exists(ASCT_LOCK_DIR):
        print("ASCT lock dir found, looking for active ASCT processes...")
        pids = get_pids_using_lock(ASCT_LOCK_DIR)
        if pids:
            for pid in pids:
                kill_process_tree(pid)
        else:
            print("No active ASCT process found!")

        print("Deleting lock file...")
        delete_lock_dir(ASCT_LOCK_DIR)
    skip_hugepage_delloc = request.config.getoption("--skip-hugepage-delloc")
    if not skip_hugepage_delloc:
        free_all_1g_hugepages()
    yield
    # teardown: deallocate all huge pages
    if not skip_hugepage_delloc:
        free_all_1g_hugepages()


# Per test setup/teardown
@pytest.fixture(autouse=True)
def setup_teardown_test(request):
    # setup: no-op
    yield
    # teardown: check if any huge pages are still allocated
    if not request.config.getoption("--skip-hugepage-delloc"):
        check_1g_hugepage_leaks()


@pytest.fixture
def storage_benchmarks():
    return [x[0] for x in ALL_BENCHMARKS["storage"]]


@pytest.fixture
def storage_benchmarks_all_names():
    return ALL_BENCHMARKS["storage"]
