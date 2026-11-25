"""Mocked tests for tools/test_monitor.py.

These tests never enumerate a real desktop, launch a process, or move a real
window.  They pin the monitor ordering, the no-monitor skip, startup-position
hand-off, the PID-verified non-activating fallback, and handle recreation.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"


def _load_test_monitor():
    spec = importlib.util.spec_from_file_location(
        "test_monitor_under_test", TOOLS / "test_monitor.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    import sys

    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


test_monitor = _load_test_monitor()


def rect(left: int, top: int, right: int, bottom: int):
    return test_monitor.Rect(left, top, right, bottom)


def monitor(
    handle: int,
    left: int,
    top: int,
    right: int,
    bottom: int,
    *,
    primary: bool = False,
    active: bool = True,
    work=None,
):
    desktop = rect(left, top, right, bottom)
    return test_monitor.Monitor(
        handle=handle,
        desktop=desktop,
        work=work or desktop,
        primary=primary,
        active=active,
    )


def window(
    hwnd: int,
    *,
    pid: int = 42,
    width: int = 800,
    height: int = 600,
    visible: bool = True,
    root: bool = True,
    title: str = "",
):
    return test_monitor.WindowInfo(
        hwnd=hwnd,
        pid=pid,
        visible=visible,
        root=root,
        title=title,
        rect=rect(0, 0, width, height),
        client_width=width,
        client_height=height,
    )


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class FakeProcess:
    def __init__(self, pid: int = 42, exit_code=None):
        self.pid = pid
        self.exit_code = exit_code

    def poll(self):
        return self.exit_code


class FakeApi:
    """Scripted window enumeration with no Win32 calls."""

    def __init__(
        self,
        monitors=(),
        *,
        batches=None,
        pid_overrides=None,
        move_ok=True,
        alive=True,
    ):
        self._monitors = list(monitors)
        self._batches = [list(batch) for batch in batches] if batches is not None else None
        self._pid_overrides = dict(pid_overrides or {})
        self._move_ok = move_ok
        self._alive = alive
        self.window_calls = 0
        self.move_attempts = []
        self.moves = []
        self._known_pids = {}
        for batch in self._batches or []:
            for item in batch:
                self._known_pids[item.hwnd] = item.pid

    def list_monitors(self):
        return list(self._monitors)

    def windows_for_pid(self, pid):
        self.window_calls += 1
        if not self._batches:
            return []
        index = min(self.window_calls - 1, len(self._batches) - 1)
        return list(self._batches[index])

    def window_pid(self, hwnd):
        if hwnd in self._pid_overrides:
            return self._pid_overrides[hwnd]
        return self._known_pids.get(hwnd)

    def move_no_activate(self, hwnd, x, y):
        self.move_attempts.append((hwnd, x, y))
        if not self._move_ok:
            return False
        self.moves.append((hwnd, x, y))
        return True

    def process_alive(self, pid):
        return self._alive


class MonitorSelectionTests(unittest.TestCase):
    def test_leftmost_active_non_primary_sorts_by_desktop_x_then_y(self):
        primary = monitor(1, 0, 0, 1920, 1080, primary=True)
        inactive_left = monitor(2, -4000, 0, -2080, 1080, active=False)
        same_x_later_y = monitor(3, -1920, 200, -320, 1200)
        same_x_first_y = monitor(4, -1920, 0, -320, 1000)
        right = monitor(5, 1920, 0, 3840, 1080)

        selected = test_monitor.select_test_monitor(
            [right, same_x_later_y, primary, inactive_left, same_x_first_y]
        )

        self.assertIs(selected, same_x_first_y)

    def test_primary_is_never_selected(self):
        primary = monitor(1, -3000, 0, -1000, 1000, primary=True)
        selected = test_monitor.select_test_monitor([primary])
        self.assertIsNone(selected)

    def test_equal_origin_uses_handle_as_stable_tie_breaker(self):
        high = monitor(20, -1920, 0, -320, 1080)
        low = monitor(10, -1920, 0, -320, 1080)
        self.assertIs(test_monitor.select_test_monitor([high, low]), low)

    def test_placement_uses_work_area_and_margin(self):
        target = monitor(
            7,
            -2560,
            0,
            -640,
            1440,
            work=rect(-2560, 40, -640, 1400),
        )
        plan = test_monitor.plan_test_window([target], margin=16)
        self.assertIsNotNone(plan)
        self.assertEqual((plan.x, plan.y), (-2544, 56))
        self.assertEqual(plan.mode, test_monitor.POST_SHOW_MODE)
        self.assertIn("flash", plan.startup_flash_warning.lower())

    def test_initial_position_plan_has_no_flash_warning(self):
        target = monitor(7, -1920, 0, -320, 1080)
        plan = test_monitor.plan_test_window(
            [target], initial_position_supported=True
        )
        self.assertEqual(plan.mode, test_monitor.INITIAL_POSITION_MODE)
        self.assertIsNone(plan.startup_flash_warning)
        self.assertEqual((plan.x, plan.y), (-1920, 0))

    def test_check_monitors_reports_selection(self):
        primary = monitor(1, 0, 0, 1920, 1080, primary=True)
        target = monitor(2, 1920, 0, 3840, 1080)
        report = test_monitor.check_monitors(FakeApi([primary, target]))
        self.assertTrue(report["ok"])
        self.assertEqual(report["reason"], "selected")
        self.assertEqual(report["selected"]["handle"], 2)
        self.assertIn("flash", report["placement"]["startup_flash_warning"].lower())

    def test_check_monitors_reports_skip_without_target(self):
        report = test_monitor.check_monitors(FakeApi([monitor(1, 0, 0, 1920, 1080, primary=True)]))
        self.assertFalse(report["ok"])
        self.assertEqual(report["reason"], test_monitor.NO_MONITOR_REASON)
        self.assertIsNone(report["selected"])
        self.assertIsNone(report["placement"])


class WindowSelectionTests(unittest.TestCase):
    def test_choose_main_window_uses_largest_visible_root_for_pid(self):
        other_pid = window(1, pid=99, width=3000, height=3000)
        hidden = window(2, width=4000, height=4000, visible=False)
        child = window(3, width=3500, height=3500, root=False)
        small = window(4, width=800, height=600)
        large = window(5, width=1600, height=900)
        selected = test_monitor.choose_main_window(
            [other_pid, hidden, child, small, large], pid=42
        )
        self.assertEqual(selected.hwnd, 5)

    def test_choose_main_window_returns_none_without_candidates(self):
        self.assertIsNone(test_monitor.choose_main_window([], pid=42))
        self.assertIsNone(
            test_monitor.choose_main_window(
                [window(1, width=0, height=0)], pid=42
            )
        )


class PlacementTests(unittest.TestCase):
    def setUp(self):
        self.primary = monitor(1, 0, 0, 1920, 1080, primary=True)
        self.target = monitor(
            2,
            -2560,
            0,
            -640,
            1440,
            work=rect(-2560, 0, -640, 1400),
        )
        self.game = window(10, width=1920, height=1080)
        self.other = window(99, pid=99, width=4000, height=4000)

    def place(
        self, api, *, monitors=None, plan=None, process=None, ready=1.0, settle=0.1
    ):
        clock = FakeClock()
        result = test_monitor.place_process_on_test_monitor(
            42,
            api=api,
            monitors=[self.primary, self.target] if monitors is None else monitors,
            plan=plan,
            process=process or FakeProcess(),
            ready_timeout=ready,
            settle_time=settle,
            poll_interval=0.05,
            clock=clock.now,
            pause=clock.sleep,
        )
        return result, clock

    def test_no_non_primary_monitor_does_not_enumerate_or_move(self):
        api = FakeApi(
            [self.primary],
            batches=[[self.game]],
        )
        result, _clock = self.place(api, monitors=[self.primary])
        self.assertFalse(result.placed)
        self.assertEqual(result.reason, test_monitor.NO_MONITOR_REASON)
        self.assertEqual(api.window_calls, 0)
        self.assertEqual(api.move_attempts, [])

    def test_fallback_moves_pid_window_with_expected_coordinates(self):
        api = FakeApi(
            [self.primary, self.target],
            batches=[[self.other, self.game]],
        )
        result, _clock = self.place(api)

        self.assertTrue(result.placed)
        self.assertTrue(result.settled)
        self.assertEqual(result.reason, "placed")
        self.assertEqual(result.x, -2560)
        self.assertEqual(result.y, 0)
        self.assertEqual(api.moves, [(10, -2560, 0)])
        self.assertEqual(result.moves[0].flags, test_monitor.NO_ACTIVATE_MOVE_FLAGS)

    def test_non_activating_flags_never_include_show_or_activation(self):
        self.assertEqual(
            test_monitor.NO_ACTIVATE_MOVE_FLAGS,
            test_monitor.SWP_NOSIZE
            | test_monitor.SWP_NOZORDER
            | test_monitor.SWP_NOACTIVATE
            | test_monitor.SWP_NOOWNERZORDER,
        )
        self.assertFalse(
            test_monitor.NO_ACTIVATE_MOVE_FLAGS & test_monitor.SWP_SHOWWINDOW
        )

    def test_handle_recreation_is_moved_again(self):
        replacement = window(11, width=1600, height=900)
        api = FakeApi(
            [self.primary, self.target],
            batches=[
                [self.other, self.game],
                [self.other, self.game],
                [self.other, replacement],
                [self.other, replacement],
                [self.other, replacement],
                [self.other, replacement],
                [self.other, replacement],
            ],
        )
        result, _clock = self.place(api, ready=2.0, settle=0.2)

        self.assertTrue(result.placed)
        self.assertTrue(result.handle_recreated)
        self.assertEqual([move.hwnd for move in result.moves], [10, 11])
        self.assertTrue(result.moves[1].recreated)
        self.assertEqual([move[0] for move in api.moves], [10, 11])

    def test_pid_verification_refuses_to_move_other_owner(self):
        api = FakeApi(
            [self.primary, self.target],
            batches=[[self.game]],
            pid_overrides={10: 99},
        )
        result, _clock = self.place(api, ready=0.1, settle=0.1)

        self.assertFalse(result.placed)
        self.assertEqual(result.reason, "pid_verification_failed")
        self.assertIn("does not match launched pid", result.error)
        self.assertEqual(api.move_attempts, [])

    def test_move_failure_is_reported(self):
        api = FakeApi(
            [self.primary, self.target],
            batches=[[self.game]],
            move_ok=False,
        )
        result, _clock = self.place(api, ready=0.1, settle=0.1)

        self.assertFalse(result.placed)
        self.assertEqual(result.reason, "move_failed")
        self.assertEqual(result.moves, [])
        self.assertGreaterEqual(len(api.move_attempts), 1)
        self.assertTrue(all(attempt[0] == 10 for attempt in api.move_attempts))

    def test_process_exit_before_window_is_reported(self):
        api = FakeApi([self.primary, self.target], batches=[[self.game]])
        result, _clock = self.place(
            api,
            process=FakeProcess(exit_code=1),
            ready=1.0,
            settle=0.1,
        )
        self.assertFalse(result.placed)
        self.assertEqual(result.reason, "process_exited")
        self.assertEqual(api.window_calls, 0)

    def test_no_window_until_timeout_is_reported(self):
        api = FakeApi([self.primary, self.target], batches=[[]])
        result, _clock = self.place(api, ready=0.1, settle=0.1)
        self.assertFalse(result.placed)
        self.assertEqual(result.reason, "no_window")
        self.assertGreaterEqual(api.window_calls, 1)


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.primary = monitor(1, 0, 0, 1920, 1080, primary=True)
        self.target = monitor(
            2,
            -2560,
            0,
            -640,
            1440,
            work=rect(-2560, 0, -640, 1400),
        )

    def test_no_target_monitor_skips_visible_launch(self):
        api = FakeApi([self.primary])
        called = []

        def launcher(command, position):
            called.append((command, position))
            return FakeProcess()

        result = test_monitor.launch_on_test_monitor(
            ["game.exe"], api=api, launcher=launcher
        )

        self.assertFalse(result.launched)
        self.assertTrue(result.skipped)
        self.assertEqual(result.reason, test_monitor.NO_MONITOR_REASON)
        self.assertEqual(called, [])
        self.assertIsNone(result.pid)

    def test_initial_position_is_handed_to_supporting_launcher(self):
        api = FakeApi(
            [self.primary, self.target],
            batches=[[window(10)]],
        )
        calls = []
        process = FakeProcess(pid=123)

        def launcher(command, position):
            calls.append((list(command), position))
            return process

        result = test_monitor.launch_on_test_monitor(
            ["game.exe", "--run"],
            api=api,
            launcher=launcher,
            initial_position_supported=True,
        )

        self.assertTrue(result.launched)
        self.assertFalse(result.skipped)
        self.assertEqual(result.pid, 123)
        self.assertEqual(result.reason, "initial_position")
        self.assertEqual(calls, [(["game.exe", "--run"], (-2560, 0))])
        self.assertEqual(api.window_calls, 0)
        self.assertIsNone(result.plan.startup_flash_warning)

    def test_fallback_launch_places_after_show(self):
        api = FakeApi(
            [self.primary, self.target],
            batches=[[window(10, pid=321, width=1920, height=1080)]],
        )
        clock = FakeClock()
        calls = []
        process = FakeProcess(pid=321)

        def launcher(command, position):
            calls.append((list(command), position))
            return process

        result = test_monitor.launch_on_test_monitor(
            ["game.exe"],
            api=api,
            launcher=launcher,
            ready_timeout=1.0,
            settle_time=0.1,
            poll_interval=0.05,
            clock=clock.now,
            pause=clock.sleep,
        )

        self.assertTrue(result.launched)
        self.assertEqual(result.pid, 321)
        self.assertEqual(result.reason, "placed")
        self.assertEqual(calls, [(["game.exe"], None)])
        self.assertTrue(result.placement.placed)
        self.assertEqual(api.moves, [(10, -2560, 0)])
        self.assertIn("flash", result.placement.startup_flash_warning.lower())

    def test_launcher_failure_is_reported_without_placement(self):
        api = FakeApi([self.primary, self.target])

        def launcher(command, position):
            raise OSError("boom")

        result = test_monitor.launch_on_test_monitor(
            ["game.exe"], api=api, launcher=launcher
        )
        self.assertFalse(result.launched)
        self.assertFalse(result.skipped)
        self.assertEqual(result.reason, "launch_failed")
        self.assertIn("boom", result.error)


if __name__ == "__main__":
    unittest.main()


