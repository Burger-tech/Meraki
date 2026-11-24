"""Standard-library regression tests for the Meraki launcher.

The launcher module is a ``.pyw`` graphical application.  These tests load it
with lightweight stand-ins for the Tk modules, so no display, window, runtime
process or game is ever created.  They cover command routing, the archive
header report and the opt-in diagnostic capture environment.
"""

from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main(verbosity=2)