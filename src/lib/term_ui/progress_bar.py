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

import math
import queue
import time
import threading

from enum import Enum
from functools import reduce
from contextlib import nullcontext

import asct.core.logger as log

from asct.core.datatypes import ASCTSingleton
from asct.core.utility.numeric import ASCTAverager
from asct.core.term_ui.term_manager import TermManager


__all__ = ["get_progress_tracker"]


def get_progress_tracker():
    return ASCTProgressTrackerContainer()


def adjust_string_len_to(current_string, length):
    current_length = len(current_string)
    if current_length > length:
        return current_string[:length]
    return current_string.ljust(length)


def generate_string_rotations(target_string, right_mode=False):
    rotations = [target_string]
    length = len(target_string)
    for _ in range(length - 1):
        if right_mode:
            target_string = target_string[-1] + target_string[:-1]
        else:
            target_string = target_string[1:] + target_string[0]
        rotations += [target_string]
    return rotations


class ASCTProgressTrackerComponent:
    def __init__(self, fixed_length=None, depth=None):
        self._content = ""
        self._fixed_length = fixed_length
        self._depth = depth

    def on_status_text_updated(self, new_text):
        pass

    def on_progress_updated(self, step_idx, max_steps):
        pass

    def on_global_progress_updated(self, step_idx, max_steps):
        pass

    def get_depth(self):
        return self._depth

    def reset(self):
        pass

    def update(self):
        pass

    def get(self):
        return adjust_string_len_to(self._content, self._fixed_length) if self._fixed_length else self._content

    def is_idle(self):
        return True


class ASCTProgressTrackerAnim(ASCTProgressTrackerComponent):
    def __init__(self, anim_chars, update_period=0):
        super().__init__()
        self._anim_chars = anim_chars
        self._anim_len = len(anim_chars)
        self._update_period = update_period
        self._last_update_time = time.time() if update_period > 0 else None
        self._cur_char = 0
        self._content = self._anim_chars[0]

    def update(self):
        if self._update_period > 0:
            current_time = time.time()
            if current_time - self._last_update_time < self._update_period:
                return
            self._last_update_time = current_time
        self._cur_char = (self._cur_char + 1) % self._anim_len
        self._content = self._anim_chars[self._cur_char]


class ASCTProgressTrackerStatusAnim(ASCTProgressTrackerComponent):
    CURSOR_CHR = ("▄", "■", "▀", "■")
    TRANSITION_CHAR_COUNT = 2

    STATE_IDLE = 0
    STATE_ANIM = 1

    def __init__(self, fixed_length, depth):
        super().__init__(fixed_length, depth)
        self._cursor_anim = ASCTProgressTrackerAnim(self.CURSOR_CHR)
        self._target_string = ""
        self._cur_target_char = 0
        self._state = self.STATE_IDLE

    def get_first_string_diff(self, new_text):
        for idx in range(self._cur_target_char):
            if new_text[idx] != self._content[idx]:
                return idx
        return len(self._content)

    def on_status_text_updated(self, new_text):
        self._target_string = new_text[: self._fixed_length].ljust(self._fixed_length)
        self._cur_target_char = self.get_first_string_diff(self._target_string)
        self._state = self.STATE_ANIM

    def update(self):
        if self._state == self.STATE_IDLE:
            return
        self._cursor_anim.update()
        self._content = (
            self._target_string[: self._cur_target_char]
            + self._cursor_anim.get()
            + self._content[self._cur_target_char + 1 :]
        )
        self._cur_target_char += self.TRANSITION_CHAR_COUNT
        if self._cur_target_char >= len(self._target_string) + 1:
            self._state = self.STATE_IDLE
            self._content = self._target_string
            self._cur_target_char = len(self._target_string)

    def is_idle(self):
        return self._state == self.STATE_IDLE


class ASCTProgressTrackerStatusStatic(ASCTProgressTrackerComponent):
    def __init__(self, fixed_length, depth):
        super().__init__(fixed_length, depth)
        self._content = ""

    def on_status_text_updated(self, new_text):
        self._content = new_text


class ACSTProgressTrackerTimer(ASCTProgressTrackerComponent):
    def __init__(self, depth=None):
        super().__init__(depth=depth)
        self._start_time = time.time()
        self._last_update_time = self._start_time
        self._time_update(self._start_time, 0)

    def update(self):
        current_time = time.time()
        time_delta = current_time - self._last_update_time
        if time_delta < 1:
            return
        self._time_update(current_time, time_delta)
        self._last_update_time = current_time

    def _time_update(self, current_time, _):
        self._content = self._format_time(current_time - self._start_time)

    def _format_time(self, seconds):
        seconds = int(seconds)
        time_parts = []
        for div in 3600, 60, 1:
            time_val = seconds // div
            seconds -= time_val * div
            time_parts += [f"{time_val:02d}"]
        return ":".join(time_parts)


class ASCTProgressTrackerCountdown(ACSTProgressTrackerTimer):
    def __init__(self, depth):
        self._estimated_time = None
        super().__init__(depth=depth)
        self._sample_count = 0

    def _format_eta(self, estimated_time):
        if estimated_time is None:
            return "-??:??:??"
        estimated_time = max(0, estimated_time)
        return f"-{self._format_time(estimated_time)}"

    def _time_update(self, _, time_delta):
        if self._estimated_time is not None:
            self._estimated_time = max(0, self._estimated_time - time_delta)
        self._content = self._format_eta(self._estimated_time)

    def on_global_progress_updated(self, step_idx, max_steps):
        self._sample_count += 1
        elapsed_time = time.time() - self._start_time
        avg_sample_time = elapsed_time / float(self._sample_count)

        self._estimated_time = (max_steps - step_idx) * avg_sample_time


class ASCTProgressTrackerStep(ASCTProgressTrackerComponent):
    def __init__(self, digit_count, depth, offset=1):
        super().__init__(depth=depth)
        self._steps_digit_count = digit_count
        self._offset = offset
        self._build(0, 0)

    def _build(self, current_step, max_steps):
        if max_steps == 0:
            self._content = "?" * self._steps_digit_count + "/" + "?" * self._steps_digit_count
        current_step = min(current_step + self._offset, max_steps)
        self._content = f"{current_step:0{self._steps_digit_count}d}/{max_steps:0{self._steps_digit_count}d}"

    def on_progress_updated(self, step_idx, max_steps):
        self._build(step_idx, max_steps)


class ASCTProgressTrackerStepPercentage(ASCTProgressTrackerComponent):
    def __init__(self, depth):
        super().__init__(depth=depth)
        self._build(0, 0)

    def _build(self, current_step, max_steps):
        if max_steps == 0:
            self._content = "00.0%"
        elif current_step >= max_steps:
            self._content = " 100%"
        else:
            ratio = 100.0 * current_step / max_steps
            self._content = f"{ratio:04.1f}%"

    def on_progress_updated(self, step_idx, max_steps):
        self._build(step_idx, max_steps)


class ACSTProgressTrackerBar(ASCTProgressTrackerComponent):
    BAR_EMPTY_CHR = "░"
    BAR_HALF_CHR = "▒"
    BAR_FULL_CHR = "▓"

    def __init__(self, length, depth):
        super().__init__(length, depth)
        self._bar_length = length
        self._build(0, 0)

    def _get_bar_filled_amounts(self, current_step, max_steps):
        filled_length = (self._bar_length * current_step) / max_steps
        filled_length_full = math.floor(filled_length)
        filled_length_partial = filled_length - filled_length_full
        if filled_length_partial < 0.15:
            filled_length_partial = 0
        elif filled_length_partial >= 0.85:
            filled_length_partial = 0
            filled_length_full += 1
        else:
            filled_length_partial = 1
        return int(filled_length_full), int(filled_length_partial)

    def _build(self, current_step, max_steps):
        if max_steps == 0:
            self._content = " " * self._bar_length
            return
        full, partial = self._get_bar_filled_amounts(current_step, max_steps)
        empty = self._bar_length - (full + partial)
        self._content = self.BAR_FULL_CHR * full + self.BAR_HALF_CHR * partial + self.BAR_EMPTY_CHR * empty

    def on_progress_updated(self, step_idx, max_steps):
        self._build(step_idx, max_steps)


class ASCTProgressTracker:
    def __init__(self):
        self._components = []
        self._async = False
        self._template = ""
        self._extra_logging_tag = ""
        self._max_depth = 0

    def initialize(self, max_depth, extra_log_tag=""):
        self._components = self._create_components()
        self._max_depth = max_depth
        self._extra_logging_tag = extra_log_tag
        self._post_init()

    def _post_init(self):
        pass

    def _create_components(self):
        return []

    def _for_every_comp(self, func):
        for comp in self._components:
            func(comp)

    def _assemble_output(self):
        output = self._template.format(*[x.get() for x in self._components])
        return self._format_output(output)

    def _format_output(self, output):
        return output

    def _can_notify_child(self, child, depth):
        return child.get_depth() == depth

    def _notify_status_updated(self, text, step_index, step_count, global_step_index, global_step_count, step_depth):
        if text:
            self._for_every_comp(
                lambda c: c.on_status_text_updated(text) if self._can_notify_child(c, step_depth) else None
            )

        if step_index is None:
            return

        self._for_every_comp(
            lambda c: c.on_progress_updated(step_index, step_count) if self._can_notify_child(c, step_depth) else None
        )
        if global_step_index:
            self._for_every_comp(lambda c: c.on_global_progress_updated(global_step_index, global_step_count))

    def update_status(self, text, step_index, step_count, global_step_index, global_step_count, step_depth):
        self._on_status_updated(text, step_index, step_count, global_step_index, global_step_count, step_depth)

    def set_slow_mode(self):
        pass

    def set_fast_mode(self):
        pass

    def terminate(self):
        pass

    def wait_until_idle(self, timeout=None):
        pass


class ASCTProgressTrackerAsync(ASCTProgressTracker):
    class Events(Enum):
        NONE = 0
        UPDATE = 1
        SET_UPDATE_PERIOD = 3
        QUIT = 4

    class Defs(Enum):
        UPDATE_PERIOD_FAST = 0.1
        UPDATE_PERIOD_SLOW = 1.0

    def __init__(self):
        super().__init__()
        self._async = True
        self._template = "│{}│ ASCT ║{}│{}║ [{}] {} » ║{}({})║ {}"
        self._update_queue = None
        self._update_period = self.Defs.UPDATE_PERIOD_FAST
        self._update_thread = None
        self._pending_update_period = 0
        self._update_event = nullcontext()
        self._pause_event = nullcontext()
        self._update_mutex = nullcontext()
        self._terminated = False

    def _create_components(self):
        return [
            ASCTProgressTrackerAnim(generate_string_rotations("▄■▀■"), 0.25),
            ACSTProgressTrackerTimer(),
            ASCTProgressTrackerCountdown(1),
            ASCTProgressTrackerStep(2, 0),
            ASCTProgressTrackerStatusAnim(20, 0),
            ACSTProgressTrackerBar(16, 1),
            ASCTProgressTrackerStepPercentage(1),
            ASCTProgressTrackerStatusStatic(32, 1),
        ]

    def _post_init(self):
        self._terminated = False
        self._update_queue = queue.Queue()
        self._update_mutex = threading.Lock()

        def component_update():
            while True:
                event_type = self.Events.NONE

                try:
                    event_type = self._update_queue.get(timeout=self._update_period.value)
                except queue.Empty:
                    pass

                if event_type == self.Events.QUIT:
                    break

                if event_type == self.Events.SET_UPDATE_PERIOD:
                    self._update_period = self._pending_update_period
                    continue

                output = ""
                with self._update_mutex:
                    self._for_every_comp(lambda x: x.update())
                    output = self._assemble_output()

                TermManager().write(output)

        self._update_thread = threading.Thread(target=component_update, daemon=True)
        self._update_thread.start()

    def _format_output(self, output):
        return "\r" + output

    def _on_status_updated(self, text, step_index, step_count, global_step_index, global_step_count, step_depth):
        with self._update_mutex:
            self._notify_status_updated(text, step_index, step_count, global_step_index, global_step_count, step_depth)
        self._update_queue.put(self.Events.UPDATE)

    def _set_update_period(self, period):
        if not self._async or self._update_period == period:
            return
        self._pending_update_period = period
        self._update_queue.put(self.Events.SET_UPDATE_PERIOD)
        self._wait_until(lambda: self._update_period == self._pending_update_period)

    def terminate(self):
        if not self._async:
            return
        self._terminated = True
        if self._update_queue is not None:
            self._update_queue.put(self.Events.QUIT)
        if self._update_thread is not None:
            self._update_thread.join()

    def _wait_until(self, f, timeout=None):
        start_time = time.time() if timeout else None
        while True:
            if self._terminated:
                return False
            if start_time and time.time() - start_time >= timeout:
                return False
            if f():
                break
            time.sleep(0.05)
        return True

    def wait_until_idle(self, timeout=None):
        self._wait_until(lambda: all(c.is_idle() for c in self._components), timeout)


class ASCTProgressTrackerSync(ASCTProgressTracker):
    def __init__(self):
        super().__init__()
        self._template = "{} [{}] {} > ({}) {}"

    def _create_components(self):
        return [
            ACSTProgressTrackerTimer(),
            ASCTProgressTrackerStep(2, 0),
            ASCTProgressTrackerStatusStatic(None, 0),
            ASCTProgressTrackerStep(2, 1),
            ASCTProgressTrackerStatusStatic(None, 1),
        ]

    def _on_status_updated(self, text, step_index, step_count, global_step_index, global_step_count, step_depth):
        if not self._components:
            return
        self._notify_status_updated(text, step_index, step_count, global_step_index, global_step_count, step_depth)
        self._for_every_comp(lambda c: c.update())
        if step_depth != self._max_depth - 1:
            return
        output = self._assemble_output()
        log.info(output)

    def _format_output(self, output):
        return self._extra_logging_tag + output


class ASCTProgressTrackerContainer(metaclass=ASCTSingleton):
    """
    Container that creates one or two instances of ASCTProgressTracker progress bars in the following scenarios:
    * quiet mode: no tracker instantiated
    * term: enabled and interactive - one instance that uses async pushes to stderr via TermManager
        * file: enabled - plus one instance that uses logging and logging filters to only push to file
        * file: disabled - no additional instance
    * term: enabled and non interactive:
        * file: enabled/ file: disabled - single instance that uses logging to push to both
    * term: disabled
        * file: enabled - single instance that uses logging to push to file

    Nots:
        - for now, file logging is never disabled unless quiet=True
        - logging to file and stderr is controlled by logger.py, so we need a single instance of the progress bar
        that use logging and async=False to push data and it the logging system will make sure it ends up
        in both places

    ASCTProgressTrackerContainer forwards messages to all instances of ASCTProgressTracker so they will all show
    the same state, just in different formats.
    """

    class IterationState:
        def __init__(self, iterable, depth):
            self.iterator = iter(iterable)
            self.is_sized = hasattr(iterable, "__len__")
            self.step_idx = 0
            self.step_count = len(iterable) if self.is_sized else 0
            self.depth = depth

    def __init__(self):
        self._trackers = None
        self._max_depth = 0
        self._global_step_index = 0
        self._prev_global_step_index = 0
        self._avg_step_count = None
        self._active = False
        self._iter_stack = None
        self._iter_depth = -1

    def initialize(self, max_depth, enable_terminal, terminal_async, enable_file):
        self._trackers = []

        self._active = enable_terminal or enable_file

        if not self._active:
            return

        self._active = enable_terminal or enable_file
        self._max_depth = max_depth
        self._iter_stack = [None] * max_depth
        self._avg_step_count = [ASCTAverager() for x in range(max_depth)]

        if enable_terminal:
            term_tracker = ASCTProgressTrackerAsync() if terminal_async else ASCTProgressTrackerSync()
            term_tracker.initialize(max_depth)
            self._trackers.append(term_tracker)

        # the sync tracker will use log.info which will output to both terminal and file (if enabled)
        # so there's no reason to create one for file output
        if enable_terminal and not terminal_async:
            return

        # if terminal output is not enabled or it is using the async mode, we need one more sync component
        # that uses log.info - the 'tag' will make sure that log.info only outputs these messages to a file
        if enable_file:
            term_tracker = ASCTProgressTrackerSync()
            term_tracker.initialize(max_depth, extra_log_tag=log.LOGGER_TAG_ONLY_FILE)
            self._trackers.append(term_tracker)

    def _get_estimated_step_count_per_depth(self, depth):
        if not self._avg_step_count[depth].HasData():
            if self._iter_stack[depth]:
                return max(self._iter_stack[depth].step_count, 1)
            return 1
        return self._avg_step_count[depth].Get()

    def _get_estimated_global_step_count(self):
        estimated_step_count = [self._get_estimated_step_count_per_depth(d) for d in range(self._max_depth)]
        return reduce(lambda a, b: a * b, estimated_step_count)

    def _for_every_tracker(self, func):
        for tracker in self._trackers:
            func(tracker)

    def _for_every_async_tracker(self, func):
        tracker_found = False
        for tracker in self._trackers:
            if tracker._async:
                func(tracker)
                tracker_found = True
        return tracker_found

    def _update_children_status(self, text, step_index, step_count, global_step_index, global_step_count, step_depth):
        self._for_every_tracker(
            lambda x: x.update_status(text, step_index, step_count, global_step_index, global_step_count, step_depth)
        )

    def iterate(self, iterable, text_gen=None):
        # bail quickly
        if not self._active:
            for item in iterable:
                yield item
            return

        current_text = None
        iter_state = self._on_enter_iteration_block(iterable)

        while True:
            try:
                item = next(iter_state.iterator)
            except StopIteration:
                break
            except Exception as exc:
                self._on_exit_iteration_block()
                raise RuntimeError(f"Iteration step setup failure: {exc}") from exc

            if text_gen is not None:
                try:
                    current_text = text_gen(iter_state.step_idx, item)
                except Exception:  # ruff:ignore[blind-except] - ensure we run on_exit_iteration_block on any exception
                    current_text = f"Step {iter_state.step_idx}"

            if not iter_state.is_sized:
                iter_state.step_count = iter_state.step_idx + 1

            global_step_index = None
            global_step_count = self._get_estimated_global_step_count()
            if self._global_step_index != self._prev_global_step_index:
                global_step_index = self._global_step_index
                self._prev_global_step_index = self._global_step_index

            self._update_children_status(
                current_text,
                iter_state.step_idx,
                iter_state.step_count,
                global_step_index,
                global_step_count,
                self._iter_depth,
            )

            iter_state.step_idx += 1

            yield item

            if self._iter_depth == self._max_depth - 1:
                self._global_step_index += 1

        # show completion of the last step
        if iter_state.is_sized and self._for_every_async_tracker(
            lambda x: x.update_status(
                current_text,
                iter_state.step_idx,
                iter_state.step_count,
                global_step_index,
                global_step_count,
                self._iter_depth,
            )
        ):
            time.sleep(0.25)

        self._on_exit_iteration_block()

    def wait_until_idle(self, timeout=None):
        self._for_every_async_tracker(lambda x: x.wait_until_idle(timeout))

    def terminate(self):
        self._for_every_tracker(lambda x: x.terminate())

    def set_slow_mode(self):
        self._for_every_async_tracker(lambda x: x.set_slow_mode())

    def set_fast_mode(self):
        self._for_every_async_tracker(lambda x: x.set_fast_mode())

    @property
    def _iter_state(self):
        return self._iter_stack[self._iter_depth]

    def _on_exit_iteration_block(self):
        self._avg_step_count[self._iter_depth].Add(self._iter_state.step_idx)
        self._iter_stack[self._iter_depth] = None
        self._iter_depth -= 1

    def _on_enter_iteration_block(self, iterable):
        self._iter_depth += 1
        self._iter_stack[self._iter_depth] = self.IterationState(iterable, self._iter_depth)
        return self._iter_stack[self._iter_depth]

    def break_from_iteration(self):
        self._on_exit_iteration_block()
