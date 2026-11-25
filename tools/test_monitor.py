"""Place a visible test window on the leftmost active non-primary monitor.

The helper is deliberately Windows-only at call time but import-safe: the
Win32 bindings are created lazily by :class:`RealWindowsApi`, so the pure
selection/reporting logic can be unit tested without a desktop.

Selection
---------
``EnumDisplayMonitors`` supplies the active monitor set.  The primary monitor
is removed, and the remaining monitors are sorted by desktop ``left`` then
``top`` (with the monitor handle as a stable final tie-breaker).  The first
monitor in that order is the target.  If there is no active non-primary
monitor, callers report that condition and skip the visible launch.

Placement
---------
A runtime that accepts an initial window position should receive the target
origin before it shows its window.  The pinned VIctory runtime does not: it
creates a visible top-level window with ``CW_USEDEFAULT`` coordinates, so this
helper's default path launches first and then applies a PID-verified,
non-activating ``SetWindowPos`` move as soon as the window can be enumerated.
It repeats that move when the process replaces its main window handle during
the startup settle period.

Limitation
----------
The fallback move cannot eliminate a brief startup flash: VIctory's window is
already visible before Python can enumerate it.  The move is immediate and
never activates or refocuses the window, but the first frame may appear at the
runtime's default location.  Use a runtime with startup placement support when
a flash-free launch is required.

The helper never changes display settings and never moves a window that is not
owned by the launched PID.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

try:  # Kept import-safe for non-Windows test hosts.
    from ctypes import wintypes
except (ImportError, ValueError):  # pragma: no cover - Python's Windows ctypes
    wintypes = None  # type: ignore[assignment]


SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_NOOWNERZORDER = 0x0200
SWP_SHOWWINDOW = 0x0040

# Move only.  No z-order change, no activation, no owner-z-order change, and
# explicitly no SWP_SHOWWINDOW: the helper must not make another window visible.
NO_ACTIVATE_MOVE_FLAGS = SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOOWNERZORDER

GA_ROOT = 2
MONITORINFOF_PRIMARY = 0x00000001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
STILL_ACTIVE = 259

POST_SHOW_FLASH_WARNING = (
    "VIctory creates its window visible with CW_USEDEFAULT coordinates. The "
    "PID-verified non-activating move runs on the first enumeration poll, so "
    "the window can flash briefly at its default location before settling on "
    "the target monitor. This fallback cannot remove that startup flash."
)

NO_MONITOR_REASON = "no active non-primary monitor; visible launch skipped"
POST_SHOW_MODE = "post_show_move"
INITIAL_POSITION_MODE = "initial_position"


@dataclass(frozen=True)
class Rect:
    """A Win32 rectangle in virtual-desktop coordinates."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def to_list(self) -> list[int]:
        return [self.left, self.top, self.right, self.bottom]


@dataclass(frozen=True)
class Monitor:
    """An active display monitor.

    ``desktop`` is ``rcMonitor`` and ``work`` is ``rcWork``.  ``active`` is
    explicit so mocked monitors and filtered enumerations express the same
    contract as ``EnumDisplayMonitors``.
    """

    handle: int
    desktop: Rect
    work: Rect
    primary: bool = False
    active: bool = True
    device: str = ""

    @property
    def sort_key(self) -> tuple[int, int, int]:
        return (self.desktop.left, self.desktop.top, self.handle)

    def to_dict(self) -> dict[str, Any]:
        return {
            "handle": self.handle,
            "device": self.device,
            "active": self.active,
            "primary": self.primary,
            "desktop": self.desktop.to_list(),
            "work": self.work.to_list(),
            "sort_key": list(self.sort_key),
        }


@dataclass(frozen=True)
class WindowInfo:
    """A visible top-level window observed for one PID."""

    hwnd: int
    pid: int
    visible: bool = True
    root: bool = True
    title: str = ""
    rect: Rect | None = None
    client_width: int = 0
    client_height: int = 0

    @property
    def area(self) -> int:
        return max(0, self.client_width) * max(0, self.client_height)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hwnd": self.hwnd,
            "pid": self.pid,
            "visible": self.visible,
            "root": self.root,
            "title": self.title,
            "rect": self.rect.to_list() if self.rect else None,
            "client": [self.client_width, self.client_height],
            "area": self.area,
        }


@dataclass(frozen=True)
class MoveRecord:
    hwnd: int
    pid: int
    x: int
    y: int
    recreated: bool = False
    flags: int = NO_ACTIVATE_MOVE_FLAGS

    def to_dict(self) -> dict[str, Any]:
        return {
            "hwnd": self.hwnd,
            "pid": self.pid,
            "x": self.x,
            "y": self.y,
            "recreated": self.recreated,
            "flags": self.flags,
        }


@dataclass(frozen=True)
class PlacementPlan:
    monitor: Monitor
    x: int
    y: int
    mode: str
    startup_flash_warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "monitor": self.monitor.to_dict(),
            "x": self.x,
            "y": self.y,
            "mode": self.mode,
            "startup_flash_warning": self.startup_flash_warning,
        }


@dataclass
class PlacementResult:
    placed: bool
    reason: str
    monitor: Monitor | None = None
    x: int | None = None
    y: int | None = None
    mode: str | None = None
    moves: list[MoveRecord] = field(default_factory=list)
    handle_recreated: bool = False
    settled: bool = False
    error: str | None = None
    startup_flash_warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "placed": self.placed,
            "reason": self.reason,
            "monitor": self.monitor.to_dict() if self.monitor else None,
            "x": self.x,
            "y": self.y,
            "mode": self.mode,
            "moves": [move.to_dict() for move in self.moves],
            "handle_recreated": self.handle_recreated,
            "settled": self.settled,
            "error": self.error,
            "startup_flash_warning": self.startup_flash_warning,
        }


@dataclass
class LaunchResult:
    launched: bool
    skipped: bool
    reason: str
    command: list[str]
    monitors: list[Monitor] = field(default_factory=list)
    pid: int | None = None
    process: Any | None = field(default=None, repr=False)
    plan: PlacementPlan | None = None
    placement: PlacementResult | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "launched": self.launched,
            "skipped": self.skipped,
            "reason": self.reason,
            "command": self.command,
            "monitors": [monitor.to_dict() for monitor in self.monitors],
            "pid": self.pid,
            "plan": self.plan.to_dict() if self.plan else None,
            "placement": self.placement.to_dict() if self.placement else None,
            "error": self.error,
        }


def select_test_monitor(monitors: Iterable[Monitor]) -> Monitor | None:
    """Return the leftmost active non-primary monitor.

    Ordering is desktop x first, then desktop y, then handle for determinism.
    A primary monitor is never returned, even when it is leftmost.
    """

    candidates = [monitor for monitor in monitors if monitor.active and not monitor.primary]
    if not candidates:
        return None
    return min(candidates, key=lambda monitor: monitor.sort_key)


def placement_origin(monitor: Monitor, margin: int = 0) -> tuple[int, int]:
    """Return the top-left of the monitor's work area, inset by ``margin``."""

    inset = max(0, int(margin))
    return (monitor.work.left + inset, monitor.work.top + inset)


def plan_test_window(
    monitors: Iterable[Monitor],
    *,
    initial_position_supported: bool = False,
    margin: int = 0,
) -> PlacementPlan | None:
    """Select a target and describe how the window should reach it."""

    monitor = select_test_monitor(monitors)
    if monitor is None:
        return None
    x, y = placement_origin(monitor, margin)
    if initial_position_supported:
        return PlacementPlan(monitor=monitor, x=x, y=y, mode=INITIAL_POSITION_MODE)
    return PlacementPlan(
        monitor=monitor,
        x=x,
        y=y,
        mode=POST_SHOW_MODE,
        startup_flash_warning=POST_SHOW_FLASH_WARNING,
    )


def choose_main_window(
    windows: Iterable[WindowInfo], pid: int | None = None
) -> WindowInfo | None:
    """Choose the largest visible root window, optionally restricted to ``pid``."""

    candidates = [
        window
        for window in windows
        if window.visible
        and window.root
        and window.area > 0
        and (pid is None or window.pid == pid)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda window: (window.area, window.hwnd))


def _process_is_alive(process: Any | None, api: "RealWindowsApi", pid: int) -> bool:
    if process is not None and hasattr(process, "poll"):
        return process.poll() is None
    return bool(api.process_alive(pid))


def _run_placement(
    *,
    pid: int,
    plan: PlacementPlan,
    api: Any,
    process: Any | None,
    ready_timeout: float,
    settle_time: float,
    poll_interval: float,
    clock: Callable[[], float],
    pause: Callable[[float], None],
) -> PlacementResult:
    start = clock()
    ready_deadline = start + max(0.0, float(ready_timeout))
    settle_deadline: float | None = None
    active_hwnd: int | None = None
    last_placed_hwnd: int | None = None
    handle_recreated = False
    moves: list[MoveRecord] = []
    last_error: str | None = None
    moved_any = False

    while True:
        now = clock()
        # Check before enumerating so a process that exits without a window is
        # reported quickly instead of waiting out the readiness timeout.
        if not _process_is_alive(process, api, pid):
            if moves:
                return PlacementResult(
                    placed=active_hwnd is not None,
                    reason="process_exited_after_move" if active_hwnd else "process_exited",
                    monitor=plan.monitor,
                    x=plan.x,
                    y=plan.y,
                    mode=plan.mode,
                    moves=moves,
                    handle_recreated=handle_recreated,
                    settled=settle_deadline is not None and now >= settle_deadline,
                    error=last_error,
                    startup_flash_warning=plan.startup_flash_warning,
                )
            return PlacementResult(
                placed=False,
                reason="process_exited",
                monitor=plan.monitor,
                x=plan.x,
                y=plan.y,
                mode=plan.mode,
                moves=moves,
                handle_recreated=handle_recreated,
                settled=False,
                error=last_error,
                startup_flash_warning=plan.startup_flash_warning,
            )

        main = choose_main_window(api.windows_for_pid(pid), pid)
        if main is not None and main.hwnd != active_hwnd:
            owner = api.window_pid(main.hwnd)
            if owner != pid:
                last_error = (
                    f"refusing to move hwnd {main.hwnd}: owner pid {owner!r} "
                    f"does not match launched pid {pid}"
                )
                active_hwnd = None
            else:
                ok = bool(api.move_no_activate(main.hwnd, plan.x, plan.y))
                if ok:
                    recreated = last_placed_hwnd is not None and main.hwnd != last_placed_hwnd
                    handle_recreated = handle_recreated or recreated
                    moves.append(
                        MoveRecord(
                            hwnd=main.hwnd,
                            pid=pid,
                            x=plan.x,
                            y=plan.y,
                            recreated=recreated,
                        )
                    )
                    last_placed_hwnd = main.hwnd
                    active_hwnd = main.hwnd
                    settle_deadline = now + max(0.0, float(settle_time))
                    moved_any = True
                    last_error = None
                else:
                    last_error = f"SetWindowPos failed for hwnd {main.hwnd}"
                    active_hwnd = None
        elif main is None:
            # Keep the last successful placement plausible during a handle
            # swap, but do not claim a new handle was placed.
            active_hwnd = None

        if active_hwnd is not None and settle_deadline is not None and now >= settle_deadline:
            return PlacementResult(
                placed=True,
                reason="placed",
                monitor=plan.monitor,
                x=plan.x,
                y=plan.y,
                mode=plan.mode,
                moves=moves,
                handle_recreated=handle_recreated,
                settled=True,
                error=None,
                startup_flash_warning=plan.startup_flash_warning,
            )

        if now >= ready_deadline:
            if moved_any:
                return PlacementResult(
                    placed=active_hwnd is not None,
                    reason="placement_settle_timeout" if active_hwnd is not None else "placement_lost",
                    monitor=plan.monitor,
                    x=plan.x,
                    y=plan.y,
                    mode=plan.mode,
                    moves=moves,
                    handle_recreated=handle_recreated,
                    settled=False,
                    error=last_error,
                    startup_flash_warning=plan.startup_flash_warning,
                )
            reason = "no_window"
            if last_error:
                reason = (
                    "pid_verification_failed"
                    if "does not match launched pid" in last_error
                    else "move_failed"
                )
            return PlacementResult(
                placed=False,
                reason=reason,
                monitor=plan.monitor,
                x=plan.x,
                y=plan.y,
                mode=plan.mode,
                moves=moves,
                handle_recreated=handle_recreated,
                settled=False,
                error=last_error,
                startup_flash_warning=plan.startup_flash_warning,
            )

        pause(max(0.001, float(poll_interval)))


def place_process_on_test_monitor(
    pid: int,
    *,
    api: Any | None = None,
    monitors: Iterable[Monitor] | None = None,
    plan: PlacementPlan | None = None,
    process: Any | None = None,
    margin: int = 0,
    ready_timeout: float = 15.0,
    settle_time: float = 0.75,
    poll_interval: float = 0.05,
    clock: Callable[[], float] = time.monotonic,
    pause: Callable[[float], None] = time.sleep,
) -> PlacementResult:
    """Move an existing process's main window to the selected test monitor.

    The move is applied only after verifying that the remembered window handle
    still belongs to ``pid``.  If the process replaces that handle during the
    settle period, the new main window is moved too.  This function never
    changes display settings and never activates or moves unrelated windows.
    """

    backend = api if api is not None else RealWindowsApi()
    if plan is None:
        available = list(monitors) if monitors is not None else list(backend.list_monitors())
        plan = plan_test_window(available)
        if plan is None:
            return PlacementResult(
                placed=False,
                reason=NO_MONITOR_REASON,
                startup_flash_warning=None,
            )
    elif plan.mode == INITIAL_POSITION_MODE:
        return PlacementResult(
            placed=True,
            reason="initial_position",
            monitor=plan.monitor,
            x=plan.x,
            y=plan.y,
            mode=plan.mode,
            settled=True,
        )

    return _run_placement(
        pid=int(pid),
        plan=plan,
        api=backend,
        process=process,
        ready_timeout=ready_timeout,
        settle_time=settle_time,
        poll_interval=poll_interval,
        clock=clock,
        pause=pause,
    )


def _default_launcher(
    command: Sequence[str], initial_position: tuple[int, int] | None
) -> Any:
    if initial_position is not None:
        raise ValueError(
            "the default launcher cannot pass an initial window position; "
            "supply launcher(command, (x, y)) for a runtime that supports it"
        )
    return subprocess.Popen(list(command))


def launch_on_test_monitor(
    command: Sequence[str],
    *,
    api: Any | None = None,
    launcher: Callable[[Sequence[str], tuple[int, int] | None], Any] | None = None,
    initial_position_supported: bool = False,
    margin: int = 0,
    ready_timeout: float = 15.0,
    settle_time: float = 0.75,
    poll_interval: float = 0.05,
    clock: Callable[[], float] = time.monotonic,
    pause: Callable[[float], None] = time.sleep,
) -> LaunchResult:
    """Launch ``command`` only when an active non-primary monitor exists.

    With ``initial_position_supported=True`` the supplied ``launcher`` receives
    ``(x, y)`` and is responsible for applying it before showing the window.
    Otherwise the process is launched first and :func:`place_process_on_test_monitor`
    applies the immediate PID-verified fallback move.
    """

    backend = api if api is not None else RealWindowsApi()
    monitors = list(backend.list_monitors())
    plan = plan_test_window(
        monitors,
        initial_position_supported=initial_position_supported,
        margin=margin,
    )
    if plan is None:
        return LaunchResult(
            launched=False,
            skipped=True,
            reason=NO_MONITOR_REASON,
            command=list(command),
            monitors=monitors,
        )

    launch = launcher or _default_launcher
    try:
        process = launch(
            list(command),
            (plan.x, plan.y) if plan.mode == INITIAL_POSITION_MODE else None,
        )
    except Exception as error:  # noqa: BLE001 - report launcher failures, do not crash callers
        return LaunchResult(
            launched=False,
            skipped=False,
            reason="launch_failed",
            command=list(command),
            monitors=monitors,
            plan=plan,
            error=str(error),
        )

    pid = int(getattr(process, "pid"))
    if plan.mode == INITIAL_POSITION_MODE:
        placement = PlacementResult(
            placed=True,
            reason="initial_position",
            monitor=plan.monitor,
            x=plan.x,
            y=plan.y,
            mode=plan.mode,
            settled=True,
        )
    else:
        placement = place_process_on_test_monitor(
            pid,
            api=backend,
            plan=plan,
            process=process,
            ready_timeout=ready_timeout,
            settle_time=settle_time,
            poll_interval=poll_interval,
            clock=clock,
            pause=pause,
        )

    return LaunchResult(
        launched=True,
        skipped=False,
        reason=placement.reason,
        command=list(command),
        monitors=monitors,
        pid=pid,
        process=process,
        plan=plan,
        placement=placement,
    )


def check_monitors(api: Any | None = None, margin: int = 0) -> dict[str, Any]:
    """Return a JSON-friendly monitor and placement report."""

    backend = api if api is not None else RealWindowsApi()
    monitors = list(backend.list_monitors())
    plan = plan_test_window(monitors, margin=margin)
    return {
        "ok": plan is not None,
        "reason": "selected" if plan else NO_MONITOR_REASON,
        "monitors": [monitor.to_dict() for monitor in monitors],
        "selected": plan.monitor.to_dict() if plan else None,
        "placement": plan.to_dict() if plan else None,
    }


class _MONITORINFO(ctypes.Structure):
    if wintypes is not None:
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]


class RealWindowsApi:
    """Small lazy Win32 binding used by the placement helper."""

    def __init__(self) -> None:
        if sys.platform != "win32" or wintypes is None:
            raise RuntimeError("test-window placement requires Windows")
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._enum_proc_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HANDLE, wintypes.LPARAM
        )
        self._monitor_proc_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HANDLE,
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.RECT),
            wintypes.LPARAM,
        )
        self._bind()
        self._try_enable_dpi_awareness()

    def _bind(self) -> None:
        u = self._user32
        u.EnumDisplayMonitors.argtypes = [
            wintypes.HDC,
            ctypes.POINTER(wintypes.RECT),
            self._monitor_proc_type,
            wintypes.LPARAM,
        ]
        u.EnumDisplayMonitors.restype = wintypes.BOOL
        u.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MONITORINFO)]
        u.GetMonitorInfoW.restype = wintypes.BOOL
        u.EnumWindows.argtypes = [self._enum_proc_type, wintypes.LPARAM]
        u.EnumWindows.restype = wintypes.BOOL
        u.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        u.GetAncestor.restype = wintypes.HWND
        u.IsWindow.argtypes = [wintypes.HWND]
        u.IsWindow.restype = wintypes.BOOL
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.IsWindowVisible.restype = wintypes.BOOL
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetWindowTextW.restype = ctypes.c_int
        u.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.GetClientRect.restype = wintypes.BOOL
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.GetWindowRect.restype = wintypes.BOOL
        u.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        u.SetWindowPos.restype = wintypes.BOOL
        self._kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL

    def _try_enable_dpi_awareness(self) -> None:
        # Placement uses physical virtual-desktop coordinates.  This changes
        # only this process's DPI awareness, never system display settings.
        try:
            set_context = self._user32.SetProcessDpiAwarenessContext
            set_context.argtypes = [wintypes.HANDLE]
            set_context.restype = wintypes.BOOL
            set_context(wintypes.HANDLE(-4))  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        except (AttributeError, OSError, ValueError):
            pass

    def list_monitors(self) -> list[Monitor]:
        monitors: list[Monitor] = []

        def visit(hmonitor: int, _hdc: int, _rect: Any, _data: int) -> bool:
            info = _MONITORINFO()
            info.cbSize = ctypes.sizeof(_MONITORINFO)
            if not self._user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                return True
            desktop = Rect(
                info.rcMonitor.left,
                info.rcMonitor.top,
                info.rcMonitor.right,
                info.rcMonitor.bottom,
            )
            work = Rect(
                info.rcWork.left,
                info.rcWork.top,
                info.rcWork.right,
                info.rcWork.bottom,
            )
            monitors.append(
                Monitor(
                    handle=int(hmonitor),
                    desktop=desktop,
                    work=work,
                    primary=bool(info.dwFlags & MONITORINFOF_PRIMARY),
                    active=True,
                )
            )
            return True

        callback = self._monitor_proc_type(visit)
        if not self._user32.EnumDisplayMonitors(None, None, callback, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        return monitors

    def windows_for_pid(self, pid: int) -> list[WindowInfo]:
        found: list[WindowInfo] = []

        def visit(hwnd: int, _data: int) -> bool:
            if not self._user32.IsWindowVisible(hwnd):
                return True
            if int(self._user32.GetAncestor(hwnd, GA_ROOT) or 0) != int(hwnd):
                return True
            owner_pid = self.window_pid(hwnd)
            if owner_pid != pid:
                return True
            rect = self.window_rect(hwnd)
            client = wintypes.RECT()
            if self._user32.GetClientRect(hwnd, ctypes.byref(client)):
                client_width = client.right - client.left
                client_height = client.bottom - client.top
            else:
                client_width = client_height = 0
            title = ctypes.create_unicode_buffer(512)
            self._user32.GetWindowTextW(hwnd, title, len(title))
            found.append(
                WindowInfo(
                    hwnd=int(hwnd),
                    pid=owner_pid,
                    visible=True,
                    root=True,
                    title=title.value,
                    rect=rect,
                    client_width=client_width,
                    client_height=client_height,
                )
            )
            return True

        callback = self._enum_proc_type(visit)
        if not self._user32.EnumWindows(callback, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        return found

    def window_pid(self, hwnd: int) -> int | None:
        if not self._user32.IsWindow(wintypes.HWND(hwnd)):
            return None
        pid = wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        return int(pid.value) or None

    def window_rect(self, hwnd: int) -> Rect | None:
        rect = wintypes.RECT()
        if not self._user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            return None
        return Rect(rect.left, rect.top, rect.right, rect.bottom)

    def move_no_activate(self, hwnd: int, x: int, y: int) -> bool:
        # HWND_TOP is ignored because SWP_NOZORDER is set.  Passing None keeps
        # the existing z-order.  SWP_NOACTIVATE prevents a visible test run
        # from stealing focus during placement.
        return bool(
            self._user32.SetWindowPos(
                wintypes.HWND(hwnd),
                None,
                int(x),
                int(y),
                0,
                0,
                NO_ACTIVATE_MOVE_FLAGS,
            )
        )

    def process_alive(self, pid: int) -> bool:
        handle = self._kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
        )
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not self._kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == STILL_ACTIVE
        finally:
            self._kernel32.CloseHandle(handle)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python tools/test_monitor.py",
        description="Audit or use the leftmost active non-primary test monitor.",
    )
    sub = parser.add_subparsers(dest="command_name", required=True)

    check = sub.add_parser("check", help="report monitors and skip status")
    check.add_argument("--margin", type=int, default=0)

    place = sub.add_parser("place", help="move an existing PID's main window")
    place.add_argument("--pid", type=int, required=True)
    place.add_argument("--margin", type=int, default=0)
    place.add_argument("--ready-timeout", type=float, default=15.0)
    place.add_argument("--settle", type=float, default=0.75)
    place.add_argument("--poll", type=float, default=0.05)

    launch = sub.add_parser("launch", help="launch only when a target monitor exists")
    launch.add_argument("--margin", type=int, default=0)
    launch.add_argument("--ready-timeout", type=float, default=15.0)
    launch.add_argument("--settle", type=float, default=0.75)
    launch.add_argument("--poll", type=float, default=0.05)
    launch.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.command_name == "check":
            report = check_monitors(margin=args.margin)
            print(json.dumps(report, indent=2))
            return 0 if report["ok"] else 2

        if args.command_name == "place":
            result = place_process_on_test_monitor(
                args.pid,
                margin=args.margin,
                ready_timeout=args.ready_timeout,
                settle_time=args.settle,
                poll_interval=args.poll,
            )
            print(json.dumps(result.to_dict(), indent=2))
            return 0 if result.placed else 2 if result.reason == NO_MONITOR_REASON else 1

        command = list(args.command)
        if command and command[0] == "--":
            command = command[1:]
        if not command:
            raise SystemExit("launch requires: -- <command> [args...]")
        result = launch_on_test_monitor(
            command,
            margin=args.margin,
            ready_timeout=args.ready_timeout,
            settle_time=args.settle,
            poll_interval=args.poll,
        )
        print(json.dumps(result.to_dict(), indent=2))
        if result.skipped:
            return 2
        return 0 if result.placement and result.placement.placed else 1
    except (OSError, RuntimeError, ValueError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, indent=2))
        return 1


if __name__ == "__main__":  # pragma: no cover - CLI smoke path
    raise SystemExit(main())

