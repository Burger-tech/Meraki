"""Construction and state tests for the real Tk launcher UI.

These tests create a withdrawn Tk root, so no window is shown, focused or
interacted with.  They verify that the polished layout and the diagnostics
panel are wired to the same launcher state used by the process tests.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local" / "test-launcher-ui"
LAUNCHER_PATH = ROOT / "Meraki.pyw"


def _load_launcher():
    loader = importlib.machinery.SourceFileLoader("meraki_launcher_ui", str(LAUNCHER_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


meraki = _load_launcher()


class LauncherUiTests(unittest.TestCase):
    def setUp(self):
        LOCAL.mkdir(parents=True, exist_ok=True)
        self._scratch = tempfile.TemporaryDirectory(prefix="case-", dir=str(LOCAL))
        self.addCleanup(self._scratch.cleanup)
        self.temp = Path(self._scratch.name).resolve()
        try:
            self.root = meraki.tk.Tk()
        except Exception as error:  # no display or Tk missing
            self.skipTest(f"Tk is unavailable: {error}")
        self.root.withdraw()
        self.addCleanup(self._destroy)
        with mock.patch.object(meraki, "detect_title", return_value=""):
            self.app = meraki.Launcher(self.root)
        self.root.update_idletasks()

    def _destroy(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def make_package(self):
        package = self.temp / "package"
        package.mkdir()
        exe = package / "game.exe"
        exe.write_bytes(b"MZ")
        (package / "MicrosoftGame.Config").write_text("<Game />", encoding="utf-8")
        for name in ("common.rpf", "levels.rpf", "audio.rpf"):
            (package / name).write_bytes(b"9FPRpayload")
        return package, exe.resolve()

    def test_window_starts_ready_with_diagnostics_and_a_log_placeholder(self):
        self.assertEqual(self.root.title(), "Meraki")
        self.assertEqual(self.app.status.get(), "Ready. Hardware GPU is the default.")
        self.assertFalse(self.app.warp.get())
        self.assertEqual(self.app.package_state_label.cget("text"), "No package")
        self.assertIn(
            self.app.runtime_state_label.cget("text"),
            {"Not built", "Release only", "Diagnostics ready"},
        )
        self.assertIn("Session output will appear here", self.app.output.get("1.0", "end-1c"))
        self.assertEqual(str(self.app.stop.cget("state")), "disabled")
        self.assertEqual(str(self.app.open_log.cget("state")), "disabled")
        self.assertEqual(str(self.app.open_frames.cget("state")), "disabled")
        self.assertIn("error", self.app.output.tag_names())
        self.assertIn("warn", self.app.output.tag_names())

    def test_package_selection_populates_path_manifest_and_archive_badges(self):
        package, exe = self.make_package()

        self.app.path.set(str(exe))
        self.root.update_idletasks()

        self.assertEqual(self.app.package_var.get(), str(package))
        self.assertEqual(self.app.executable_var.get(), "game.exe")
        self.assertIn("MicrosoftGame.Config", self.app.manifest_var.get())
        self.assertEqual(self.app.package_state_label.cget("text"), "Ready")
        self.assertIn("RPF9", self.app.archive_labels["common.rpf"].cget("text"))
        self.assertIn("RPF9", self.app.archive_labels["levels.rpf"].cget("text"))
        self.assertIn("RPF9", self.app.archive_labels["audio.rpf"].cget("text"))
        self.assertEqual(str(self.app.open_package.cget("state")), "normal")

    def test_missing_archive_is_visible_in_the_package_card(self):
        package, exe = self.make_package()
        (package / "audio.rpf").unlink()

        self.app.path.set(str(exe))
        self.root.update_idletasks()

        self.assertIn("Missing", self.app.archive_labels["audio.rpf"].cget("text"))

    def test_status_band_and_detail_follow_runtime_output(self):
        meraki._set_status(
            self.app, "Running title with WARP...", "Rendering  frame 64", "running")
        self.assertEqual(self.app.status_panel.cget("bg"), meraki.STATUS_TONES["running"]["bg"])
        self.assertEqual(self.app.status_text_frame.cget("bg"),
                         meraki.STATUS_TONES["running"]["bg"])
        self.assertEqual(self.app.status_clock_frame.cget("bg"),
                         meraki.STATUS_TONES["running"]["bg"])
        self.assertEqual(self.app.status_detail_label.cget("fg"),
                         meraki.STATUS_TONES["running"]["muted"])
        self.assertEqual(self.app.detail.get(), "Rendering  frame 64")

        line = ("2026-11-24T06:58:45Z  ERROR victory_gpu::host: device lost\n")
        meraki._append_output(self.app, line)
        meraki._note_chunk(self.app, line)

        self.assertIn("device lost", self.app.output.get("1.0", "end-1c"))
        self.assertIn("device lost", self.app.detail.get())
        self.assertEqual(self.app.status_panel.cget("bg"), meraki.STATUS_TONES["error"]["bg"])
        self.assertIn("error", self.app.output.tag_names("2.0"))

    def test_session_panel_shows_the_log_and_capture_folder(self):
        log = self.temp / "logs" / "launch-1.log"
        log.parent.mkdir()
        log.write_text("session\n", encoding="utf-8")
        frames = log.with_suffix("")
        frames.mkdir()

        self.app.log_path = log
        self.app.frames_path = frames
        meraki._refresh_session_info(self.app)

        self.assertEqual(self.app.log_name_var.get(), "launch-1.log")
        self.assertEqual(self.app.log_path_var.get(), str(log))
        self.assertEqual(self.app.frames_name_var.get(), "launch-1 (folder)")
        self.assertEqual(str(self.app.open_log.cget("state")), "normal")
        self.assertEqual(str(self.app.open_frames.cget("state")), "normal")

        self.app.log_path = None
        self.app.frames_path = None
        meraki._refresh_session_info(self.app)
        self.assertEqual(self.app.log_name_var.get(), "No session yet")
        self.assertEqual(self.app.frames_name_var.get(), "Off")
        self.assertEqual(str(self.app.open_log.cget("state")), "disabled")
        self.assertEqual(str(self.app.open_frames.cget("state")), "disabled")

    def test_running_controls_are_disabled_and_restored(self):
        meraki._set_controls(self.app, False)
        for control in (self.app.entry, self.app.browse, self.app.inspect,
                        self.app.check, self.app.launch, self.app.capture_toggle):
            self.assertEqual(str(control.cget("state")), "disabled")

        meraki._set_controls(self.app, True)
        for control in (self.app.entry, self.app.browse, self.app.inspect,
                        self.app.check, self.app.launch, self.app.capture_toggle):
            self.assertEqual(str(control.cget("state")), "normal")


if __name__ == "__main__":
    unittest.main(verbosity=2)
