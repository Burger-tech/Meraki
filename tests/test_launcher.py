"""Standard-library regression tests for the Meraki launcher.

The launcher module is a ``.pyw`` graphical application.  These tests load it
with lightweight stand-ins for the Tk modules, so no display, window, runtime
process or game is ever created.  They cover command routing, the archive
header report and the opt-in diagnostic capture environment.
"""

from __future__ import annotations

import codecs
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
SCRATCH = LOCAL / "test-launcher"
LAUNCHER_PATH = ROOT / "Meraki.pyw"


def _load_launcher():
    """Load Meraki.pyw with stub Tk modules so importing needs no display."""

    class Widget:
        def __init__(self, *args, **kwargs):
            pass

    class Variable:
        def __init__(self, value=None):
            self.value = value

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    tk = types.ModuleType("tkinter")
    filedialog = types.ModuleType("tkinter.filedialog")
    messagebox = types.ModuleType("tkinter.messagebox")
    ttk = types.ModuleType("tkinter.ttk")

    tk.Tk = Widget
    tk.StringVar = Variable
    tk.BooleanVar = Variable
    tk.Text = Widget
    tk.filedialog = filedialog
    tk.messagebox = messagebox
    tk.ttk = ttk

    filedialog.askopenfilename = lambda *args, **kwargs: ""
    messagebox.showerror = lambda *args, **kwargs: None
    messagebox.askyesno = lambda *args, **kwargs: False
    for name in ("Frame", "Label", "Entry", "Button", "Checkbutton", "Scrollbar"):
        setattr(ttk, name, Widget)

    modules = {
        "tkinter": tk,
        "tkinter.filedialog": filedialog,
        "tkinter.messagebox": messagebox,
        "tkinter.ttk": ttk,
    }
    with mock.patch.dict(sys.modules, modules):
        loader = importlib.machinery.SourceFileLoader("meraki_launcher", str(LAUNCHER_PATH))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
    return module


meraki = _load_launcher()


class ScratchMixin:
    """Create every test file under .local so no reference drive is touched."""

    def setUp(self):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        self._scratch = tempfile.TemporaryDirectory(prefix="case-", dir=str(SCRATCH))
        self.temp = Path(self._scratch.name).resolve()

    def tearDown(self):
        self._scratch.cleanup()

    def make_package(self, exe_name="game.exe"):
        package = self.temp / "package"
        package.mkdir()
        exe = package / exe_name
        exe.write_bytes(b"MZ")
        return package, exe.resolve()


class RuntimeCommandTests(ScratchMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.target = self.temp / "target"
        (self.target / "diag").mkdir(parents=True)
        (self.target / "release").mkdir(parents=True)
        self.package, self.exe = self.make_package()

    def _runtime(self, profile):
        path = self.target / profile / "victory.exe"
        path.write_bytes(b"MZ")
        return path

    def test_launch_uses_diagnostic_runtime_and_execute_flag(self):
        diag = self._runtime("diag")
        self._runtime("release")

        with mock.patch.object(meraki, "TARGET", self.target):
            command = meraki.runtime_command("launch", self.exe)

        self.assertEqual(command, [str(diag), "run", str(self.exe), "--execute"])

    def test_check_prefers_diagnostic_runtime(self):
        diag = self._runtime("diag")
        release = self._runtime("release")

        with mock.patch.object(meraki, "TARGET", self.target):
            self.assertEqual(
                meraki.runtime_command("check", self.exe),
                [str(diag), "run", str(self.exe)],
            )

        diag.unlink()
        with mock.patch.object(meraki, "TARGET", self.target):
            self.assertEqual(
                meraki.runtime_command("check", self.exe),
                [str(release), "run", str(self.exe)],
            )

    def test_inspect_uses_the_available_runtime(self):
        diag = self._runtime("diag")

        with mock.patch.object(meraki, "TARGET", self.target):
            self.assertEqual(
                meraki.runtime_command("inspect", self.exe),
                [str(diag), "inspect", str(self.exe)],
            )

        diag.unlink()
        release = self._runtime("release")
        with mock.patch.object(meraki, "TARGET", self.target):
            self.assertEqual(
                meraki.runtime_command("inspect", self.exe),
                [str(release), "inspect", str(self.exe)],
            )

    def test_launch_refuses_a_release_only_build(self):
        self._runtime("release")

        with mock.patch.object(meraki, "TARGET", self.target):
            with self.assertRaisesRegex(ValueError, "Build the diagnostics runtime"):
                meraki.runtime_command("launch", self.exe)

    def test_missing_runtime_is_reported_for_every_action(self):
        with mock.patch.object(meraki, "TARGET", self.target):
            for action in ("inspect", "check", "launch"):
                with self.subTest(action=action):
                    with self.assertRaisesRegex(ValueError, "Build the diagnostics runtime"):
                        meraki.runtime_command(action, self.exe)


class ArchiveReportTests(ScratchMixin, unittest.TestCase):
    def test_reports_detected_unrecognized_and_missing_archives(self):
        package, _ = self.make_package()
        (package / "common.rpf").write_bytes(b"9FPR" + b"payload")
        (package / "levels.rpf").write_bytes(b"9FP")

        report = meraki.archive_report(package)

        self.assertEqual(
            report,
            "Package archives\n"
            "  common.rpf: RPF9 header detected\n"
            "  levels.rpf: Unrecognized header\n"
            "  audio.rpf: Missing\n\n",
        )

    def test_open_error_is_included_verbatim(self):
        package, _ = self.make_package()
        (package / "common.rpf").write_bytes(b"9FPR")
        (package / "audio.rpf").write_bytes(b"9FPR")
        try:
            (package / "levels.rpf").mkdir()
        except OSError:
            self.skipTest("could not create a directory for the open-error case")

        try:
            with (package / "levels.rpf").open("rb"):
                pass
        except OSError as error:
            expected = str(error)
        else:
            self.skipTest("opening a directory for reading unexpectedly succeeded")

        report = meraki.archive_report(package)

        self.assertIn(f"  levels.rpf: {expected}\n", report)
        self.assertIn("  common.rpf: RPF9 header detected\n", report)
        self.assertIn("  audio.rpf: RPF9 header detected\n", report)


class _Variable:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Control:
    def __init__(self):
        self.states = []

    def configure(self, **kwargs):
        if "state" in kwargs:
            self.states.append(kwargs["state"])


class _Text(_Control):
    def __init__(self):
        super().__init__()
        self.content = ""

    def delete(self, *args):
        self.content = ""

    def insert(self, *args):
        self.content += args[-1]

    def see(self, *args):
        pass


class _Process:
    def poll(self):
        return 0


def _launcher_stub(exe, capture):
    """Build the attributes Launcher.start touches without creating a window."""

    stub = types.SimpleNamespace(
        root=None,
        process=None,
        reader=None,
        stopping=False,
        log_path=None,
        path=_Variable(str(exe)),
        capture=_Variable(capture),
        output=_Text(),
        entry=_Control(),
        browse=_Control(),
        inspect=_Control(),
        check=_Control(),
        launch=_Control(),
        capture_toggle=_Control(),
        open_log=_Control(),
        stop=_Control(),
        status=_Variable("Ready."),
        polls=0,
    )

    def poll():
        stub.polls += 1

    stub.poll = poll
    return stub


class CaptureEnvironmentTests(ScratchMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.target = self.temp / "target"
        (self.target / "diag").mkdir(parents=True)
        (self.target / "release").mkdir(parents=True)
        self.package, self.exe = self.make_package()

    def _run(self, action="launch", capture=False, environ=None, profiles=("diag",)):
        for profile in profiles:
            path = self.target / profile / "victory.exe"
            path.write_bytes(b"MZ")

        local = self.temp / "local"
        logs = local / "logs"
        calls = []
        errors = []

        def fake_popen(command, **kwargs):
            calls.append(
                {
                    "command": [str(part) for part in command],
                    "env": dict(kwargs["env"]),
                    "cwd": kwargs["cwd"],
                    "stdin": kwargs["stdin"],
                    "stderr": kwargs["stderr"],
                    "creationflags": kwargs.get("creationflags"),
                }
            )
            return _Process()

        messagebox = meraki.messagebox
        original_error = messagebox.showerror

        def showerror(*args, **kwargs):
            errors.append(args[1] if len(args) > 1 else "")

        fake_subprocess = types.SimpleNamespace(
            Popen=fake_popen,
            STDOUT=meraki.subprocess.STDOUT,
            DEVNULL=meraki.subprocess.DEVNULL,
            CREATE_NO_WINDOW=getattr(meraki.subprocess, "CREATE_NO_WINDOW", 0),
        )
        stub = _launcher_stub(self.exe, capture)
        environ = environ or {}

        try:
            messagebox.showerror = showerror
            with mock.patch.object(meraki, "TARGET", self.target), mock.patch.object(
                meraki, "LOCAL", local
            ), mock.patch.object(meraki, "LOGS", logs), mock.patch.object(
                meraki, "subprocess", fake_subprocess
            ), mock.patch.dict(os.environ, environ):
                meraki.Launcher.start(stub, action)
        finally:
            messagebox.showerror = original_error

        if stub.reader is not None:
            stub.reader.close()
        return stub, calls, errors, local, logs

    def test_capture_defaults_to_off_and_strips_inherited_victory_environment(self):
        stub, calls, errors, local, logs = self._run(
            capture=False,
            environ={
                "VICTORY_CAPTURE": "stale",
                "VICTORY_GAME_DIR": "stale",
                "VICTORY_UNRELATED": "stale",
                "MERAKI_TEST_SENTINEL": "kept",
            },
        )

        self.assertEqual(errors, [])
        self.assertEqual(len(calls), 1)
        env = calls[0]["env"]
        self.assertNotIn("VICTORY_CAPTURE", env)
        self.assertNotIn("VICTORY_UNRELATED", env)
        self.assertEqual(env["VICTORY_GAME_DIR"], str(self.exe.parent))
        self.assertEqual(env["MERAKI_TEST_SENTINEL"], "kept")
        self.assertEqual(env["VICTORY_D3D12_WARP"], "1")
        self.assertEqual(env["VICTORY_CACHE_DIR"], str(local / "cache"))
        self.assertEqual(env["VICTORY_DATA_DIR"], str(local / "data"))
        self.assertEqual(env["TMP"], str(local / "tmp"))
        self.assertEqual(env["TEMP"], str(local / "tmp"))
        self.assertEqual(env["NO_COLOR"], "1")
        self.assertEqual(stub.polls, 1)

        log_files = list(logs.glob("launch-*.log"))
        self.assertEqual(len(log_files), 1)
        log = log_files[0]
        self.assertEqual(stub.log_path, log)
        self.assertFalse(log.with_suffix("").exists())
        self.assertFalse(log.read_bytes().startswith(b"Diagnostic frames:"))
        self.assertIsNone(stub.frames_path)
        self.assertIsNotNone(stub.started_at)

    def test_capture_on_creates_frame_folder_and_sets_environment(self):
        stub, calls, errors, local, logs = self._run(
            capture=True,
            environ={"VICTORY_CAPTURE": "stale"},
        )

        self.assertEqual(errors, [])
        self.assertEqual(len(calls), 1)
        env = calls[0]["env"]
        log = stub.log_path
        frames = log.with_suffix("")

        self.assertEqual(env["VICTORY_CAPTURE"], str(frames))
        self.assertTrue(frames.is_dir())
        self.assertEqual(
            log.read_text(encoding="utf-8").splitlines()[0],
            f"Diagnostic frames: {frames}",
        )
        self.assertEqual(set(logs.iterdir()), {log, frames})
        self.assertEqual(stub.frames_path, frames)

    def test_capture_is_only_applied_to_launch(self):
        stub, calls, errors, local, logs = self._run(
            action="check",
            capture=True,
            profiles=("release",),
        )

        self.assertEqual(errors, [])
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0]["command"],
            [str(self.target / "release" / "victory.exe"), "run", str(self.exe)],
        )
        self.assertNotIn("VICTORY_CAPTURE", calls[0]["env"])
        log = stub.log_path
        self.assertFalse(log.with_suffix("").exists())
        self.assertIsNone(stub.frames_path)

    def test_start_reports_a_missing_runtime_without_spawning(self):
        stub, calls, errors, local, logs = self._run(
            action="launch",
            capture=True,
            profiles=(),
        )

        self.assertEqual(calls, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("Build the diagnostics runtime", errors[0])
        self.assertEqual(stub.polls, 0)


class _RunningProcess:
    def __init__(self, pid=4242):
        self.pid = pid
        self.code = None
        self.terminated = 0

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated += 1


class _Root:
    def __init__(self):
        self.scheduled = []
        self.cancelled = []
        self.destroyed = False

    def after(self, delay, callback, *args):
        token = f"timer-{len(self.scheduled)}"
        self.scheduled.append((delay, callback, args, token))
        return token

    def after_cancel(self, token):
        self.cancelled.append(token)

    def destroy(self):
        self.destroyed = True


class _Reader:
    def __init__(self, data=b""):
        self.data = data
        self.closed = False

    def read(self, _size):
        data, self.data = self.data, b""
        return data

    def close(self):
        self.closed = True


def _stop_stub(process, reader=None):
    """Build the state the stop and close methods touch."""

    stub = types.SimpleNamespace(
        root=_Root(),
        process=process,
        reader=reader,
        stopping=False,
        closing=False,
        stop_timer=None,
        status=_Variable("Running."),
        stop=_Control(),
        output=_Text(),
        entry=_Control(),
        browse=_Control(),
        inspect=_Control(),
        check=_Control(),
        launch=_Control(),
        capture_toggle=_Control(),
        open_log=_Control(),
        decoder=codecs.getincrementaldecoder("utf-8")(errors="replace"),
        log_path=None,
    )
    # Bind the helpers the flow methods call on themselves.
    stub.terminate = lambda: meraki.Launcher.terminate(stub)
    stub.poll = lambda: meraki.Launcher.poll(stub)
    stub._force_stop = lambda process: meraki.Launcher._force_stop(stub, process)
    stub._cancel_stop_timer = lambda: meraki.Launcher._cancel_stop_timer(stub)
    stub._finish_close = lambda: meraki.Launcher._finish_close(stub)
    return stub


class StopFlowTests(unittest.TestCase):
    def test_stop_posts_close_and_forces_termination_after_the_grace_period(self):
        process = _RunningProcess()
        stub = _stop_stub(process)
        posts = []

        def post(hwnd):
            posts.append(hwnd)
            return True

        with mock.patch.object(meraki, "find_visible_window", return_value=0x1234) as find, mock.patch.object(
            meraki, "post_system_close", side_effect=post
        ):
            meraki.Launcher.terminate(stub)

        find.assert_called_once_with(process.pid)
        self.assertEqual(posts, [0x1234])
        self.assertTrue(stub.stopping)
        self.assertEqual(stub.status.get(), "Stopping...")
        self.assertEqual(stub.stop.states, ["disabled"])
        self.assertEqual(len(stub.root.scheduled), 1)
        delay, callback, args, token = stub.root.scheduled[0]
        self.assertEqual(delay, meraki.CLOSE_GRACE_MS)
        self.assertEqual(process.terminated, 0)

        callback(*args)
        self.assertEqual(process.terminated, 1)
        self.assertIsNone(stub.stop_timer)
        self.assertEqual(stub.root.cancelled, [])

    def test_stop_without_a_window_terminates_immediately(self):
        process = _RunningProcess()
        stub = _stop_stub(process)

        with mock.patch.object(meraki, "find_visible_window", return_value=None), mock.patch.object(
            meraki, "post_system_close"
        ) as post:
            meraki.Launcher.terminate(stub)

        post.assert_not_called()
        self.assertTrue(stub.stopping)
        self.assertEqual(process.terminated, 1)
        self.assertEqual(stub.root.scheduled, [])
        self.assertIsNone(stub.stop_timer)

    def test_stop_forces_termination_when_the_close_cannot_be_posted(self):
        process = _RunningProcess()
        stub = _stop_stub(process)

        with mock.patch.object(meraki, "find_visible_window", return_value=7), mock.patch.object(
            meraki, "post_system_close", return_value=False
        ):
            meraki.Launcher.terminate(stub)

        self.assertEqual(process.terminated, 1)
        self.assertEqual(stub.root.scheduled, [])

    def test_stop_is_idempotent_while_the_title_is_closing(self):
        process = _RunningProcess()
        stub = _stop_stub(process)
        posts = []

        with mock.patch.object(meraki, "find_visible_window", return_value=9), mock.patch.object(
            meraki, "post_system_close", side_effect=lambda hwnd: posts.append(hwnd) or True
        ):
            meraki.Launcher.terminate(stub)
            meraki.Launcher.terminate(stub)

        self.assertEqual(posts, [9])
        self.assertEqual(len(stub.root.scheduled), 1)
        self.assertEqual(process.terminated, 0)

    def test_stale_grace_callback_does_not_stop_a_new_run(self):
        old = _RunningProcess()
        stub = _stop_stub(old)

        with mock.patch.object(meraki, "find_visible_window", return_value=3), mock.patch.object(
            meraki, "post_system_close", return_value=True
        ):
            meraki.Launcher.terminate(stub)

        _delay, callback, args, _token = stub.root.scheduled[0]
        new = _RunningProcess(pid=77)
        stub.process = new
        stub.stopping = False
        callback(*args)

        self.assertEqual(old.terminated, 0)
        self.assertEqual(new.terminated, 0)


class CloseFlowTests(unittest.TestCase):
    def test_confirmed_close_posts_close_and_destroys_after_exit(self):
        process = _RunningProcess()
        reader = _Reader(b"last output")
        stub = _stop_stub(process, reader)
        posts = []

        with mock.patch.object(meraki, "find_visible_window", return_value=9), mock.patch.object(
            meraki, "post_system_close", side_effect=lambda hwnd: posts.append(hwnd) or True
        ), mock.patch.object(meraki.messagebox, "askyesno", return_value=True):
            meraki.Launcher.close(stub)

        self.assertTrue(stub.closing)
        self.assertFalse(stub.root.destroyed)
        self.assertEqual(posts, [9])
        self.assertEqual(process.terminated, 0)

        process.code = 0
        meraki.Launcher.poll(stub)
        self.assertFalse(stub.root.destroyed)
        _delay, callback, args, _token = stub.root.scheduled[-1]
        callback(*args)

        self.assertTrue(stub.root.destroyed)
        self.assertTrue(reader.closed)
        self.assertIsNone(stub.reader)
        self.assertIsNone(stub.process)
        self.assertEqual(stub.status.get(), "Stopped.")
        self.assertEqual(stub.root.cancelled, ["timer-0"])

    def test_confirmed_close_without_a_window_terminates_immediately(self):
        process = _RunningProcess()
        stub = _stop_stub(process, _Reader(b""))

        with mock.patch.object(meraki.messagebox, "askyesno", return_value=True), mock.patch.object(
            meraki, "find_visible_window", return_value=None
        ), mock.patch.object(meraki, "post_system_close") as post:
            meraki.Launcher.close(stub)

        post.assert_not_called()
        self.assertEqual(process.terminated, 1)
        self.assertFalse(stub.root.destroyed)

        process.code = 1
        meraki.Launcher.poll(stub)
        self.assertTrue(stub.root.destroyed)

    def test_cancelled_close_leaves_the_title_running(self):
        process = _RunningProcess()
        stub = _stop_stub(process)

        with mock.patch.object(meraki.messagebox, "askyesno", return_value=False), mock.patch.object(
            meraki, "find_visible_window"
        ) as find, mock.patch.object(meraki, "post_system_close") as post:
            meraki.Launcher.close(stub)

        find.assert_not_called()
        post.assert_not_called()
        self.assertFalse(stub.closing)
        self.assertFalse(stub.root.destroyed)
        self.assertEqual(process.terminated, 0)

    def test_close_without_a_process_destroys_the_window(self):
        reader = _Reader()
        stub = _stop_stub(None, reader)

        meraki.Launcher.close(stub)

        self.assertTrue(stub.root.destroyed)
        self.assertTrue(reader.closed)
        self.assertIsNone(stub.reader)


class PollCleanupTests(unittest.TestCase):
    def test_normal_exit_reenables_controls_and_clears_the_process(self):
        process = _RunningProcess()
        process.code = 7
        reader = _Reader(b"")
        stub = _stop_stub(process, reader)

        meraki.Launcher.poll(stub)

        self.assertIsNone(stub.process)
        self.assertIsNone(stub.reader)
        self.assertTrue(reader.closed)
        self.assertEqual(stub.status.get(), "Runtime exited with code 7.")
        self.assertFalse(stub.root.destroyed)
        self.assertEqual(stub.stop.states[-1], "disabled")
        for control in (
            stub.entry,
            stub.browse,
            stub.inspect,
            stub.check,
            stub.launch,
            stub.capture_toggle,
        ):
            self.assertEqual(control.states[-1], "normal")


class _Function:
    def __init__(self, impl):
        self.impl = impl

    def __call__(self, *args):
        return self.impl(*args)


def _window_api(windows):
    """Fake user32 surface for ``find_visible_window`` and ``post_system_close``."""

    def enum(callback, _param):
        for hwnd in windows:
            if not callback(hwnd, 0):
                return 0
        return 1

    def get_pid(hwnd, pointer):
        pointer.contents.value = windows[hwnd][0]

    def visible(hwnd):
        return windows[hwnd][1]

    def ancestor(hwnd, _kind):
        return windows[hwnd][2]

    return types.SimpleNamespace(
        EnumWindows=_Function(enum),
        GetWindowThreadProcessId=_Function(get_pid),
        IsWindowVisible=_Function(visible),
        GetAncestor=_Function(ancestor),
        PostMessageW=_Function(lambda *args: 1),
    )


class WindowApiTests(unittest.TestCase):
    def test_lookup_returns_only_a_visible_top_level_window_of_the_pid(self):
        windows = {
            10: (111, True, 10),
            20: (4242, False, 20),
            30: (4242, True, 99),
            40: (4242, True, 40),
        }

        with mock.patch.object(meraki.ctypes, "WinDLL", return_value=_window_api(windows)):
            self.assertEqual(meraki.find_visible_window(4242), 40)

    def test_lookup_returns_none_without_a_match(self):
        windows = {10: (111, True, 10), 20: (4242, False, 20)}

        with mock.patch.object(meraki.ctypes, "WinDLL", return_value=_window_api(windows)):
            self.assertIsNone(meraki.find_visible_window(4242))

    def test_post_system_close_uses_the_close_command(self):
        calls = []
        api = _window_api({})
        api.PostMessageW = _Function(lambda *args: calls.append(args) or 1)

        with mock.patch.object(meraki.ctypes, "WinDLL", return_value=api):
            self.assertTrue(meraki.post_system_close(0x55))

        self.assertEqual(calls, [(0x55, meraki.WM_SYSCOMMAND, meraki.SC_CLOSE, 0)])


class ArchiveStatusTests(ScratchMixin, unittest.TestCase):
    def test_reports_each_archive_state(self):
        package, _ = self.make_package()
        (package / "common.rpf").write_bytes(b"9FPRpayload")
        (package / "levels.rpf").write_bytes(b"9FP")
        (package / "audio.rpf").mkdir()

        rows = meraki.archive_status(package)

        self.assertEqual([name for name, _state, _detail in rows],
                         ["common.rpf", "levels.rpf", "audio.rpf"])
        self.assertEqual(rows[0], ("common.rpf", "ok", "RPF9 header detected"))
        self.assertEqual(rows[1], ("levels.rpf", "unknown", "Unrecognized header"))
        self.assertEqual(rows[2][0:2], ("audio.rpf", "error"))


class RuntimeStateTests(ScratchMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.target = self.temp / "target"
        (self.target / "diag").mkdir(parents=True)
        (self.target / "release").mkdir(parents=True)

    def test_reports_missing_diagnostic_and_release_builds(self):
        with mock.patch.object(meraki, "TARGET", self.target):
            self.assertEqual(meraki.runtime_state(), ("missing", "Not built"))

            release = self.target / "release" / "victory.exe"
            release.write_bytes(b"MZ")
            self.assertEqual(meraki.runtime_state(), ("release", "Release only"))

            diag = self.target / "diag" / "victory.exe"
            diag.write_bytes(b"MZ")
            self.assertEqual(meraki.runtime_state(), ("diag", "Diagnostics ready"))


class StatusDescriptionTests(unittest.TestCase):
    def test_frame_line_becomes_a_rendering_status(self):
        detail, tone = meraki.describe_log_chunk(
            "2026-11-24T06:58:45Z  INFO victory_gpu::queue: frame presented frame=64\n")

        self.assertEqual(detail, "Rendering  \u00b7  frame 64")
        self.assertEqual(tone, "running")

    def test_fps_line_reports_frame_pacing(self):
        detail, tone = meraki.describe_log_chunk(
            "2026-11-24T06:58:51Z  INFO victory_gpu::host: 15.5 fps, 64.6 ms/frame "
            "(39.3 on the GPU), 3 draws/frame\n")

        self.assertEqual(detail, "15.5 FPS  \u00b7  64.6 ms/frame")
        self.assertEqual(tone, "running")

    def test_error_line_strips_the_timestamp_and_chooses_the_error_tone(self):
        detail, tone = meraki.describe_log_chunk(
            "2026-11-24T06:58:45Z  ERROR victory_gpu::host: device lost\n")

        self.assertEqual(detail, "device lost")
        self.assertEqual(tone, "error")

    def test_import_and_presentation_lines_are_summarised(self):
        detail, _tone = meraki.describe_log_chunk(
            "2026-11-24T06:58:44Z  INFO victory_loader::windows: imports bound "
            "hle=88 host=427 missing=0\n")
        self.assertEqual(detail, "Imports bound  \u00b7  0 missing")

        detail, _tone = meraki.describe_log_chunk(
            "2026-11-24T06:58:45Z  INFO victory_gpu::host: presenting to a window "
            "width=3840 height=2160 format=28\n")
        self.assertEqual(detail, "Presenting  \u00b7  3840x2160")

    def test_warning_is_shown_without_switching_the_band_to_running(self):
        detail, tone = meraki.describe_log_chunk(
            "2026-11-24T06:58:46Z  WARN victory_gpu::queue: levels after the black frame\n")

        self.assertEqual(detail, "levels after the black frame")
        self.assertIsNone(tone)

    def test_long_detail_is_truncated(self):
        detail, _tone = meraki.describe_log_chunk("x" * 400 + "\n")

        self.assertEqual(len(detail), 160)
        self.assertTrue(detail.endswith("..."))

    def test_log_line_tags_mark_errors_warnings_and_progress(self):
        self.assertEqual(meraki._line_tag("2026-01-01T00:00:00Z  ERROR x: bad"), "error")
        self.assertEqual(meraki._line_tag("2026-01-01T00:00:00Z  WARN x: careful"), "warn")
        self.assertEqual(meraki._line_tag("2026-01-01T00:00:00Z  INFO x: frame presented"), "ok")


class _Widget:
    def __init__(self):
        self.options = {}

    def configure(self, **kwargs):
        self.options.update(kwargs)


class StatusHelperTests(unittest.TestCase):
    def test_set_status_updates_the_text_detail_and_colours(self):
        stub = types.SimpleNamespace(
            status=_Variable("Ready."),
            detail=_Variable(""),
            status_panel=_Widget(),
            status_title=_Widget(),
            status_detail_label=_Widget(),
            status_clock_label=_Widget(),
            status_accent=_Widget(),
        )

        meraki._set_status(stub, "Running title with WARP...", "Rendering  \u00b7  frame 64", "running")

        self.assertEqual(stub.status.get(), "Running title with WARP...")
        self.assertEqual(stub.detail.get(), "Rendering  \u00b7  frame 64")
        self.assertEqual(stub.status_panel.options["bg"], meraki.STATUS_TONES["running"]["bg"])
        self.assertEqual(stub.status_title.options["fg"], meraki.STATUS_TONES["running"]["fg"])
        self.assertEqual(stub.status_accent.options["bg"], meraki.STATUS_TONES["running"]["accent"])

    def test_controls_are_disabled_and_reenabled_together(self):
        stub = types.SimpleNamespace(
            entry=_Control(), browse=_Control(), inspect=_Control(), check=_Control(),
            launch=_Control(), capture_toggle=_Control())

        meraki._set_controls(stub, False)
        for control in (stub.entry, stub.browse, stub.inspect, stub.check,
                        stub.launch, stub.capture_toggle):
            self.assertEqual(control.states, ["disabled"])

        meraki._set_controls(stub, True)
        for control in (stub.entry, stub.browse, stub.inspect, stub.check,
                        stub.launch, stub.capture_toggle):
            self.assertEqual(control.states, ["disabled", "normal"])



if __name__ == "__main__":
    unittest.main(verbosity=2)