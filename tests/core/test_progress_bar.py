# ---------------------------------------------------------------------------------
# SPDX-FileCopyrightText: Copyright (C) 2026 Arm Limited and/or its affiliates
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

import threading

import pytest

from asct.core.term_ui.progress_bar import ASCTAverager, ASCTProgressTrackerAsync, ASCTProgressTrackerContainer


class _BrokenIterator:
    def __iter__(self):
        return self

    def __next__(self):
        raise ValueError("bad step")


def test_progress_iteration_setup_failure_raises_runtime_error():
    tracker = ASCTProgressTrackerContainer()
    tracker._active = True
    tracker._trackers = []
    tracker._max_depth = 1
    tracker._iter_stack = [None]
    tracker._iter_depth = -1
    tracker._avg_step_count = [ASCTAverager()]
    tracker._global_step_index = 0
    tracker._prev_global_step_index = 0

    with pytest.raises(RuntimeError, match="Iteration step setup failure: bad step"):
        next(tracker.iterate(_BrokenIterator()))

    assert tracker._iter_depth == -1


def test_async_progress_wait_until_idle_stops_when_terminated():
    tracker = ASCTProgressTrackerAsync()
    wait_complete = threading.Event()
    tracker._update_queue = None
    tracker._update_thread = None

    waiter = threading.Thread(
        target=lambda: (tracker.wait_until_idle(timeout=5.0), wait_complete.set()),
        daemon=True,
    )
    waiter.start()

    tracker.terminate()

    waiter.join(timeout=1.0)
    assert wait_complete.is_set()
