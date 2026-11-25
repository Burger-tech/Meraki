"""Offline checks for tools/notify.ps1.

Every test runs the sender with -DryRun, which formats and validates the
message but never opens a connection. No real ntfy push happens here.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "notify.ps1"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


def run_notify(*args: str, topic: str | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("NTFY_TOPIC", None)
    if topic is not None:
        env["NTFY_TOPIC"] = topic
    return subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            *args,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=60,
        check=False,
    )


def body_lines(output: str) -> list[str]:
    lines = output.splitlines()
    marker = lines.index("--- body ---")
    return lines[marker + 1 :]


@unittest.skipUnless(POWERSHELL, "PowerShell is not available")
class NotifyDryRunTests(unittest.TestCase):
    def test_full_message_layout(self) -> None:
        result = run_notify(
            "-Context",
            "gameplay",
            "-Outcome",
            "Reached the first mission",
            "-Measurement",
            "58 fps average over two minutes",
            "-Measured",
            "-Blocker",
            "Cutscene audio is silent",
            "-Next",
            "Retrying with audio logging",
            "-DryRun",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Title: Meraki", result.stdout)
        self.assertIn("Priority: 4", result.stdout)
        self.assertIn("DRY RUN - nothing was sent.", result.stdout)
        self.assertEqual(
            body_lines(result.stdout),
            [
                "Gameplay: Reached the first mission",
                "",
                "Measured: 58 fps average over two minutes",
                "Blocked: Cutscene audio is silent",
                "Next: Retrying with audio logging",
            ],
        )

    def test_measurement_defaults_to_estimated(self) -> None:
        result = run_notify("-Outcome", "Loading screen reached", "-Measurement", "about 55 fps", "-DryRun")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            body_lines(result.stdout),
            ["Loading screen reached", "", "Estimated: about 55 fps"],
        )

    def test_minimal_message_has_no_filler_lines(self) -> None:
        result = run_notify("-Outcome", "Offline exporter is ready", "-DryRun")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(body_lines(result.stdout), ["Offline exporter is ready"])

    def test_topic_value_is_never_echoed(self) -> None:
        secret = "meraki-offline-secret-topic"
        result = run_notify("-Context", "offline", "-Outcome", "Panel is ready", "-DryRun", topic=secret)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(secret, result.stdout)
        self.assertNotIn(secret, result.stderr)
        self.assertIn("Topic: set (value hidden)", result.stdout)

    def test_hash_and_path_are_rejected(self) -> None:
        hash_result = run_notify("-Outcome", "Fixed 0xdeadbeef ordering", "-DryRun")
        self.assertNotEqual(hash_result.returncode, 0)
        self.assertIn("raw hash", hash_result.stderr)

        path_result = run_notify("-Outcome", r"Patched C:\Meraki\baseline\victory", "-DryRun")
        self.assertNotEqual(path_result.returncode, 0)
        self.assertIn("file path", path_result.stderr)

    def test_multiline_outcome_is_rejected(self) -> None:
        result = run_notify("-Outcome", "First line\nSecond line", "-DryRun")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("one line", result.stderr)

    def test_missing_topic_blocks_real_send_without_network(self) -> None:
        result = run_notify("-Outcome", "No topic guard")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NTFY_TOPIC is not set", result.stderr)


if __name__ == "__main__":
    unittest.main()