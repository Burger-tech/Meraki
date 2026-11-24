"""Focused tests for tools/frame_pacing.py.

The tests use synthetic VIctory logs so they do not depend on git-ignored
captures.  They pin the source contract the tool relies on: host.rs logs one
``victory_gpu::frame: present token=N`` line per metered host present call, and
the token is frame.rs's title frame-origin counter, not a host-present count.
Every valid present line is therefore counted, including repeated, skipped, or
backward tokens.  Host fps/ms lines remain periodic aggregates, ``frame
presented`` lines remain sparse checkpoints, and ``frame interval`` lines
remain pacing configuration.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
SCRATCH = ROOT / ".local" / "test-frame-pacing"
SCRATCH.mkdir(parents=True, exist_ok=True)


def _load_frame_pacing():
    spec = importlib.util.spec_from_file_location(
        "frame_pacing_under_test", TOOLS / "frame_pacing.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


frame_pacing = _load_frame_pacing()

BASE = datetime(2026, 11, 24, 4, 20, 0, tzinfo=timezone.utc)


def stamp(offset: float) -> str:
    return (BASE + timedelta(seconds=offset)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def present(token: int, offset: float, newline: bool = True) -> str:
    line = f"{stamp(offset)}  DEBUG victory_gpu::frame: present token={token}"
    return line + ("\n" if newline else "")


def present_series(times: list[float], start_token: int = 1) -> str:
    return "".join(
        present(start_token + index, when) for index, when in enumerate(times)
    )


def stream(count: int = 301, fps: float = 60.0) -> str:
    return present_series([index / fps for index in range(count)])


def host(offset: float = 0.0, fps: str = "13.5", ms: str = "73.9") -> str:
    return (
        f"{stamp(offset)}  INFO victory_gpu::host: {fps} fps, {ms} ms/frame "
        "(0.1 preparing: copies 0.1 ms 0.3 MB, textures 0.0 ms 0.0 MB; "
        "46.6 on the GPU; 0.0 copying back 0.0 MB), 3 draws/frame, "
        "dropped 0 without a host pipeline (0 being made) and 0 indirect\n"
    )


def checkpoint(frame: int, offset: float, draws: int = 0) -> str:
    return (
        f"{stamp(offset)}  INFO victory_gpu::queue: frame presented "
        "(since the last line: draws and dispatches, and those run on the host) "
        f"frame={frame} draws={draws} drawn={draws} dispatches=0 dispatched=0\n"
    )


def configured(offset: float = 0.0, interval: str = "33.333ms") -> str:
    return (
        f"{stamp(offset)}  INFO victory_gpu::frame: frame interval "
        f"interval={interval}\n"
    )


def analyze(text: str, **kwargs) -> dict:
    return frame_pacing._analyze("<test>", text.encode("utf-8"), None, **kwargs)


def rendered(result: dict) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        frame_pacing._print_text(result)
    return out.getvalue()


OBSOLETE_TOKEN_KEYS = (
    "frames_analyzed",
    "elapsed_fps",
    "window_fps",
    "gap_intervals",
    "gap_frames",
    "gap_ranges",
    "duplicate_tokens",
    "restarts",
)


class PerFrameMeasurementTests(unittest.TestCase):
    def test_60fps_stream_reports_observed_fps_and_percentiles(self):
        result = analyze(stream(301, 60.0))
        pacing = result["pacing"]

        self.assertEqual(result["sources"]["per_frame"]["kind"], "per_frame_present_events")
        self.assertEqual(result["sources"]["per_frame"]["count"], 301)
        self.assertEqual(pacing["count"], 301)
        self.assertEqual(pacing["observed_intervals"], 300)
        self.assertAlmostEqual(pacing["observed_fps"], 60.0, delta=0.01)
        self.assertAlmostEqual(pacing["window_duration_s"], 5.0, delta=1e-5)
        self.assertAlmostEqual(pacing["frame_ms"]["p50"], 1000.0 / 60.0, delta=0.002)
        self.assertEqual(pacing["frame_ms"]["count"], 300)
        self.assertEqual(pacing["budget"]["misses"], 0)
        self.assertEqual(result["missing"], [])

        text_out = rendered(result)
        self.assertIn("observed FPS: 60.00", text_out)
        self.assertIn("present intervals / elapsed time", text_out)
        self.assertIn("observed intervals: 300", text_out)
        self.assertIn("observed present interval ms:", text_out)
        self.assertIn("p50 16.67", text_out)
        self.assertIn("16.67 ms budget: 0 misses", text_out)

    def test_known_interval_distribution_uses_linear_percentiles(self):
        result = analyze(present_series([0.010, 0.020, 0.040, 0.070, 0.110]))
        frame_ms = result["pacing"]["frame_ms"]

        self.assertEqual(frame_ms["count"], 4)
        self.assertEqual(result["pacing"]["observed_intervals"], 4)
        self.assertAlmostEqual(result["pacing"]["observed_fps"], 40.0, delta=0.01)
        self.assertAlmostEqual(frame_ms["min"], 10.0)
        self.assertAlmostEqual(frame_ms["p50"], 25.0)
        self.assertAlmostEqual(frame_ms["p95"], 38.5)
        self.assertAlmostEqual(frame_ms["p99"], 39.7)
        self.assertAlmostEqual(frame_ms["max"], 40.0)
        self.assertAlmostEqual(frame_ms["mean"], 25.0)
        self.assertEqual(result["pacing"]["budget"]["misses"], 3)
        self.assertEqual(result["pacing"]["budget"]["within"], 1)

    def test_budget_is_strictly_greater_than_the_limit(self):
        result = analyze(present_series([0.0, 0.01667, 0.03335]))
        budget = result["pacing"]["budget"]

        self.assertEqual(budget["samples"], 2)
        self.assertEqual(budget["misses"], 1)
        self.assertEqual(budget["within"], 1)

    def test_custom_budget_changes_the_miss_count(self):
        result = analyze(
            present_series([0.010, 0.020, 0.040, 0.070, 0.110]),
            budget_ms=20.0,
        )
        self.assertEqual(result["pacing"]["budget"]["ms"], 20.0)
        self.assertEqual(result["pacing"]["budget"]["misses"], 2)

    def test_two_events_with_a_token_gap_are_one_observed_interval(self):
        result = analyze(present(1, 0.0) + present(5, 4.0 / 60.0))
        pacing = result["pacing"]

        self.assertEqual(pacing["count"], 2)
        self.assertEqual(pacing["observed_intervals"], 1)
        self.assertAlmostEqual(pacing["observed_fps"], 15.0, delta=0.01)
        self.assertEqual(pacing["frame_ms"]["count"], 1)
        self.assertAlmostEqual(pacing["frame_ms"]["p50"], 1000.0 * 4.0 / 60.0, delta=0.01)
        self.assertEqual(pacing["budget"]["samples"], 1)
        self.assertEqual(pacing["budget"]["misses"], 1)
        for key in OBSOLETE_TOKEN_KEYS:
            self.assertNotIn(key, pacing)
        self.assertEqual(result["missing"], [])

    def test_duplicate_timestamps_have_no_measurable_interval(self):
        text = present(1, 0.0) + present(1, 0.0)
        result = analyze(text)
        pacing = result["pacing"]

        self.assertEqual(pacing["count"], 2)
        self.assertEqual(pacing["observed_intervals"], 0)
        self.assertEqual(pacing["zero_or_negative_timestamps"], 1)
        self.assertIsNone(pacing["observed_fps"])
        self.assertIsNone(pacing["frame_ms"])
        self.assertEqual(pacing["budget"]["samples"], 0)
        self.assertTrue(
            any("no measurable present intervals" in item for item in result["missing"])
        )

    def test_uniform_intervals_have_equal_percentiles(self):
        result = analyze(present_series([0.0, 0.010, 0.020, 0.030, 0.040]))
        frame_ms = result["pacing"]["frame_ms"]

        self.assertAlmostEqual(frame_ms["p50"], 10.0)
        self.assertAlmostEqual(frame_ms["p95"], 10.0)
        self.assertAlmostEqual(frame_ms["p99"], 10.0)
        self.assertAlmostEqual(frame_ms["max"], 10.0)


class WindowSelectionTests(unittest.TestCase):
    def test_relative_seconds_window_selects_expected_frames(self):
        result = analyze(stream(601, 60.0), start=2.0, end=3.0)
        measured = result["window"]["measured"]
        pacing = result["pacing"]

        self.assertEqual(measured["events"], 61)
        self.assertEqual(measured["first_token"], 121)
        self.assertEqual(measured["last_token"], 181)
        self.assertAlmostEqual(measured["duration_s"], 1.0, places=6)
        self.assertEqual(pacing["observed_intervals"], 60)
        self.assertAlmostEqual(pacing["observed_fps"], 60.0, delta=0.01)
        self.assertIn("start 2 s after first present event", result["window"]["description"])
        self.assertIn("end 3 s after first present event", result["window"]["description"])

    def test_token_bounds_select_events_inclusively(self):
        result = analyze(stream(601, 60.0), from_frame=101, to_frame=201)
        measured = result["window"]["measured"]
        pacing = result["pacing"]

        self.assertEqual(measured["events"], 101)
        self.assertEqual(measured["first_token"], 101)
        self.assertEqual(measured["last_token"], 201)
        self.assertEqual(pacing["observed_intervals"], 100)
        self.assertAlmostEqual(pacing["window_duration_s"], 100.0 / 60.0, delta=1e-5)

    def test_absolute_time_window_selects_expected_frames(self):
        result = analyze(
            stream(601, 60.0),
            start_time=stamp(2.0),
            end_time=stamp(3.0),
        )
        measured = result["window"]["measured"]

        self.assertEqual(measured["first_token"], 121)
        self.assertEqual(measured["last_token"], 181)
        self.assertEqual(measured["events"], 61)

    def test_combined_time_and_token_bounds_intersect(self):
        result = analyze(
            stream(601, 60.0),
            start=2.0,
            end=5.0,
            from_frame=241,
            to_frame=301,
        )
        measured = result["window"]["measured"]

        self.assertEqual(measured["first_token"], 241)
        self.assertEqual(measured["last_token"], 301)
        self.assertEqual(measured["events"], 61)
        self.assertEqual(result["pacing"]["observed_intervals"], 60)
        self.assertAlmostEqual(measured["duration_s"], 1.0, places=6)

    def test_window_with_no_events_reports_missing(self):
        result = analyze(stream(301, 60.0), start=100.0, end=200.0)

        self.assertIsNone(result["window"]["measured"])
        self.assertEqual(result["pacing"]["count"], 0)
        self.assertTrue(
            any("selected window contains no present events" in item for item in result["missing"])
        )
        self.assertIn("MISSING: the selected window contains no present events", rendered(result))

    def test_relative_window_without_present_events_is_not_applied(self):
        result = analyze(host(0.0) + host(5.0), start=1.0, end=2.0)

        self.assertIsNone(result["window"]["base_timestamp"])
        self.assertFalse(result["window"]["applied"])
        self.assertTrue(
            any(
                "relative --start/--end could not be applied" in item
                for item in result["notes"]
            )
        )

    def test_invalid_window_ranges_are_rejected(self):
        with self.assertRaises(ValueError):
            analyze(stream(10), start=2.0, end=1.0)
        with self.assertRaises(ValueError):
            analyze(stream(10), from_frame=5, to_frame=4)
        with self.assertRaises(ValueError):
            analyze(stream(10), start=-1.0)
        with self.assertRaises(ValueError):
            analyze(stream(10), budget_ms=0.0)


class SourceSeparationTests(unittest.TestCase):
    def test_host_only_does_not_create_frame_times(self):
        text = host(0.0, "13.5", "73.9") + host(5.0, "14.5", "68.8")
        result = analyze(text)
        pacing = result["pacing"]

        self.assertEqual(result["sources"]["per_frame"]["count"], 0)
        self.assertEqual(result["sources"]["host_samples"]["count"], 2)
        self.assertEqual(pacing["count"], 0)
        self.assertIsNone(pacing["frame_ms"])
        self.assertEqual(pacing["budget"]["samples"], 0)
        self.assertTrue(
            any("no victory_gpu::frame 'present token=N' lines" in item for item in result["missing"])
        )
        text_out = rendered(result)
        self.assertIn("Host aggregate samples (SAMPLED", text_out)
        self.assertIn("NOT per-frame", text_out)
        self.assertIn("no victory_gpu::frame 'present token=N' lines", text_out)

    def test_configured_interval_is_not_counted_as_a_frame(self):
        result = analyze(configured(0.0, "33.333ms") + configured(1.0, "16.667ms"))
        configured_source = result["sources"]["configured_intervals"]

        self.assertEqual(result["sources"]["per_frame"]["count"], 0)
        self.assertEqual(configured_source["count"], 2)
        self.assertEqual(len(configured_source["values"]), 2)
        milliseconds = sorted(item["ms"] for item in configured_source["values"])
        self.assertAlmostEqual(milliseconds[0], 16.667, places=3)
        self.assertAlmostEqual(milliseconds[1], 33.333, places=3)
        self.assertTrue(
            any("no victory_gpu::frame 'present token=N' lines" in item for item in result["missing"])
        )
        self.assertIn("pacing request", rendered(result))

    def test_checkpoints_are_sparse_not_per_frame(self):
        text = (
            checkpoint(1, 0.0)
            + checkpoint(2, 1.0 / 60.0)
            + checkpoint(4, 3.0 / 60.0)
            + checkpoint(8, 7.0 / 60.0)
        )
        result = analyze(text)
        checkpoints = result["sources"]["frame_checkpoints"]

        self.assertEqual(checkpoints["count"], 4)
        self.assertEqual(result["sources"]["per_frame"]["count"], 0)
        self.assertIn("coarse_observed_fps", checkpoints)
        self.assertNotIn("coarse_elapsed_fps", checkpoints)
        self.assertAlmostEqual(checkpoints["coarse_observed_fps"], 60.0, delta=0.01)
        self.assertTrue(
            any("no victory_gpu::frame 'present token=N' lines" in item for item in result["missing"])
        )
        text_out = rendered(result)
        self.assertIn("too sparse for frame-time percentiles", text_out)
        self.assertIn("coarse observed FPS: 60.00", text_out)

    def test_host_milliseconds_are_not_used_for_frame_percentiles(self):
        text = stream(61, 60.0) + host(2.0, "10.0", "100.0")
        result = analyze(text)

        self.assertEqual(result["sources"]["host_samples"]["count"], 1)
        self.assertAlmostEqual(result["pacing"]["frame_ms"]["p50"], 1000.0 / 60.0, delta=0.002)
        self.assertNotAlmostEqual(result["pacing"]["frame_ms"]["p50"], 100.0)
        self.assertTrue(
            any("host fps/ms samples are periodic aggregate averages" in item for item in result["notes"])
        )

    def test_mixed_sources_report_each_count_separately(self):
        text = (
            stream(61, 60.0)
            + host(2.0)
            + checkpoint(64, 2.0)
            + configured(0.0)
        )
        result = analyze(text)
        sources = result["sources"]

        self.assertEqual(sources["per_frame"]["count"], 61)
        self.assertEqual(sources["host_samples"]["count"], 1)
        self.assertEqual(sources["frame_checkpoints"]["count"], 1)
        self.assertEqual(sources["configured_intervals"]["count"], 1)

    def test_configured_fps_is_derived_from_milliseconds(self):
        result = analyze(configured(0.0, "16.667ms"))
        value = result["sources"]["configured_intervals"]["values"][0]

        self.assertAlmostEqual(value["fps"], 1000.0 / 16.667, places=3)
        self.assertAlmostEqual(value["fps"], 60.0, places=2)


class PresentEventSemanticsTests(unittest.TestCase):
    def test_repeated_token_is_counted_as_a_present(self):
        result = analyze(
            present(1, 0.0) + present(1, 1.0 / 60.0) + present(2, 2.0 / 60.0)
        )
        pacing = result["pacing"]

        self.assertEqual(pacing["count"], 3)
        self.assertEqual(pacing["observed_intervals"], 2)
        self.assertAlmostEqual(pacing["observed_fps"], 60.0, delta=0.01)
        self.assertAlmostEqual(pacing["frame_ms"]["p50"], 1000.0 / 60.0, delta=0.002)
        self.assertEqual(pacing["tokens"]["repeats"], 1)
        self.assertEqual(pacing["tokens"]["forward_jumps"], 0)
        self.assertEqual(pacing["tokens"]["backward_jumps"], 0)
        self.assertTrue(
            any("repeated the previous token label" in item for item in result["notes"])
        )
        self.assertIn("observed FPS: 60.00", rendered(result))

    def test_forward_token_gap_is_one_observed_interval(self):
        result = analyze(
            present(1, 0.0) + present(2, 1.0 / 60.0) + present(5, 4.0 / 60.0)
        )
        pacing = result["pacing"]

        self.assertEqual(pacing["count"], 3)
        self.assertEqual(pacing["observed_intervals"], 2)
        self.assertAlmostEqual(pacing["observed_fps"], 30.0, delta=0.01)
        self.assertEqual(pacing["frame_ms"]["count"], 2)
        self.assertAlmostEqual(pacing["frame_ms"]["p50"], 1000.0 * 2.0 / 60.0, delta=0.01)
        self.assertEqual(pacing["budget"]["samples"], 2)
        self.assertEqual(pacing["budget"]["misses"], 1)
        self.assertEqual(pacing["budget"]["within"], 1)
        self.assertEqual(pacing["tokens"]["forward_jumps"], 1)
        self.assertEqual(pacing["tokens"]["distinct"], 3)
        self.assertNotIn("unknown_gap_intervals", pacing["budget"])
        for key in OBSOLETE_TOKEN_KEYS:
            self.assertNotIn(key, pacing)

        text_out = rendered(result)
        self.assertIn("observed FPS: 30.00", text_out)
        self.assertNotIn("missing present event", text_out)
        self.assertNotIn("token gap", text_out)

    def test_backward_token_jump_is_counted_as_a_present(self):
        result = analyze(
            present(10, 0.0) + present(2, 1.0 / 60.0) + present(3, 2.0 / 60.0)
        )
        pacing = result["pacing"]

        self.assertEqual(pacing["count"], 3)
        self.assertEqual(pacing["observed_intervals"], 2)
        self.assertAlmostEqual(pacing["observed_fps"], 60.0, delta=0.01)
        self.assertEqual(pacing["tokens"]["backward_jumps"], 1)
        self.assertEqual(pacing["tokens"]["forward_jumps"], 0)
        self.assertTrue(
            any("jumped backward" in item for item in result["notes"])
        )
        for key in OBSOLETE_TOKEN_KEYS:
            self.assertNotIn(key, pacing)

    def test_alternating_tokens_do_not_split_runs(self):
        result = analyze(
            present(1, 0.0)
            + present(2, 1.0 / 60.0)
            + present(1, 2.0 / 60.0)
            + present(2, 3.0 / 60.0)
        )
        pacing = result["pacing"]

        self.assertEqual(pacing["count"], 4)
        self.assertEqual(pacing["observed_intervals"], 3)
        self.assertAlmostEqual(pacing["observed_fps"], 60.0, delta=0.01)
        self.assertAlmostEqual(pacing["window_duration_s"], 3.0 / 60.0, delta=1e-5)
        self.assertEqual(pacing["tokens"]["backward_jumps"], 1)
        self.assertNotIn("restarts", pacing)

    def test_zero_token_is_a_valid_present(self):
        result = analyze(present(0, 0.0) + present(0, 1.0 / 60.0))
        pacing = result["pacing"]

        self.assertEqual(pacing["count"], 2)
        self.assertEqual(pacing["observed_intervals"], 1)
        self.assertAlmostEqual(pacing["observed_fps"], 60.0, delta=0.01)
        self.assertEqual(pacing["tokens"]["repeats"], 1)
        self.assertEqual(result["sources"]["per_frame"]["invalid"], 0)

    def test_text_reports_only_observed_fps(self):
        text = rendered(analyze(stream(301, 60.0)))
        self.assertIn("observed FPS: 60.00", text)
        self.assertIn("present intervals / elapsed time", text)
        self.assertNotIn("elapsed FPS", text)
        self.assertNotIn("frame-number deltas", text)

    def test_notes_do_not_claim_loss_or_continuity_from_tokens(self):
        result = analyze(
            present(1, 0.0) + present(1, 1.0 / 60.0) + present(7, 4.0 / 60.0)
        )
        notes = " ".join(result["notes"]).lower()

        for phrase in ("token gap", "missing present", "restart", "duplicate token", "not joined"):
            self.assertNotIn(phrase, notes)
        self.assertIn("frame::current() title frame-origin labels", notes)

    def test_duplicate_timestamps_do_not_claim_a_measured_interval(self):
        result = analyze(present(1, 0.0) + present(1, 0.0))
        text = rendered(result)

        self.assertIn("observed intervals: 0", text)
        self.assertIn("MISSING (no measurable present intervals)", text)
        self.assertIn("non-increasing timestamps", " ".join(result["notes"]))


class MissingDataAndQualityTests(unittest.TestCase):
    def test_unterminated_final_present_line_is_excluded(self):
        text = present(1, 0.0) + present(2, 1.0 / 60.0, newline=False)
        result = analyze(text)

        self.assertEqual(result["sources"]["per_frame"]["count"], 1)
        self.assertEqual(result["sources"]["per_frame"]["excluded_unterminated"], 1)
        self.assertTrue(
            any("no line terminator" in item for item in result["missing"])
        )
        self.assertTrue(any("does not end with a line terminator" in item for item in result["notes"]))

    def test_invalid_present_token_is_rejected(self):
        text = present(1, 0.0) + f"{stamp(0.01)}  DEBUG victory_gpu::frame: present token=abc\n"
        result = analyze(text)

        self.assertEqual(result["sources"]["per_frame"]["candidates"], 2)
        self.assertEqual(result["sources"]["per_frame"]["count"], 1)
        self.assertEqual(result["sources"]["per_frame"]["invalid"], 1)
        self.assertTrue(any("missing or invalid token" in item for item in result["notes"]))

    def test_huge_token_is_rejected_without_crashing(self):
        text = f"{stamp(0.0)}  DEBUG victory_gpu::frame: present token={'9' * 5000}\n"
        result = analyze(text)

        self.assertEqual(result["sources"]["per_frame"]["count"], 0)
        self.assertEqual(result["sources"]["per_frame"]["invalid"], 1)
        json.dumps(result, allow_nan=False)

    def test_empty_log_reports_missing_evidence(self):
        result = analyze("")

        self.assertTrue(any("log is empty" in item for item in result["missing"]))
        self.assertEqual(result["sources"]["per_frame"]["count"], 0)
        self.assertIsNone(result["pacing"]["frame_ms"])

    def test_utf16_log_is_decoded(self):
        data = stream(61, 60.0).encode("utf-16")
        result = frame_pacing._analyze("<utf16>", data, None)

        self.assertIn("UTF-16", result["encoding"])
        self.assertEqual(result["sources"]["per_frame"]["count"], 61)
        self.assertEqual(result["pacing"]["observed_intervals"], 60)
        self.assertAlmostEqual(result["pacing"]["observed_fps"], 60.0, delta=0.01)

    def test_out_of_order_timestamps_are_sorted_for_pacing(self):
        text = present(2, 1.0 / 60.0) + present(1, 0.0)
        result = analyze(text)

        self.assertEqual(result["out_of_order_timestamp_lines"], 1)
        self.assertEqual(result["pacing"]["observed_intervals"], 1)
        self.assertAlmostEqual(result["pacing"]["observed_fps"], 60.0, delta=0.01)
        self.assertTrue(any("out of file order" in item for item in result["notes"]))

    def test_wrapped_host_line_is_joined_before_parsing(self):
        text = (
            f"{stamp(0.0)}  INFO victory_gpu::host: 13.5 fps, 73.9 ms/frame "
            "(0.1 preparing: copies 0.1 ms 0.3 MB, textures 0.0 ms 0.0 MB; "
            "46.6 on the GPU; 0.0 copying back 0.0 MB),"
            "\n3 draws/frame, dropped 0 without a host pipeline "
            "(0 being made) and 0 indirect\n"
        )
        result = analyze(text)

        self.assertEqual(result["sources"]["host_samples"]["count"], 1)
        self.assertAlmostEqual(result["sources"]["host_samples"]["stats"]["fps"]["max"], 13.5)

    def test_non_frame_summary_lines_are_not_counted_as_frames(self):
        text = (
            f"{stamp(0.0)}  INFO victory_gpu::device: graphics virtual memory "
            "flags=0 page_table_pages=4 preserved_bytes=0\n"
            f"{stamp(0.1)}  INFO victory_gpu::host: presenting to a window "
            "width=3840 height=2160 format=28\n"
        )
        result = analyze(text)

        self.assertEqual(result["sources"]["per_frame"]["count"], 0)
        self.assertEqual(result["sources"]["host_samples"]["count"], 0)
        self.assertTrue(any("no victory_gpu::frame 'present token=N' lines" in item for item in result["missing"]))


class SourceContractTests(unittest.TestCase):
    def _source(self, name: str) -> str:
        path = ROOT / "baseline" / "crates" / "victory-gpu" / "src" / name
        if not path.exists():
            self.skipTest(f"baseline source is not checked out: {path}")
        return path.read_text(encoding="utf-8")

    def test_host_logs_after_each_metered_present_call(self):
        host = self._source("host.rs")

        self.assertRegex(
            host,
            r"p\.swap_chain\.Present\([^;]*\);\s*p\.meter\.frame\(p\.hwnd\);",
        )
        self.assertRegex(
            host,
            r'tracing::debug!\(\s*target:\s*"victory_gpu::frame",\s*'
            r'token\s*=\s*crate::frame::current\(\),\s*"present"\s*\)',
        )
        self.assertNotIn("FRAME.fetch_add", host)

    def test_token_is_the_title_frame_origin_counter(self):
        frame = self._source("frame.rs")

        self.assertRegex(frame, r"static FRAME: AtomicU64 = AtomicU64::new\(0\);")
        self.assertEqual(frame.count("FRAME.fetch_add(1, Ordering::Relaxed)"), 1)
        self.assertRegex(
            frame,
            re.compile(
                r"if\s+origin\s*&&\s*\(hr\s*==\s*S_OK\s*\|\|\s*"
                r"flags\s*&\s*TOKEN_ON_TIMEOUT\s*!=\s*0\)\s*\{.*?"
                r"FRAME\.fetch_add\(1,\s*Ordering::Relaxed\)",
                re.S,
            ),
        )
        self.assertRegex(
            frame,
            r"pub\(crate\)\s+fn\s+current\(\)\s*->\s*u64\s*\{\s*"
            r"FRAME\.load\(Ordering::Relaxed\)\s*\}",
        )


class CliTests(unittest.TestCase):
    def _write(self, text: str, name: str = "sample.log") -> Path:
        directory = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_json_cli_reports_stable_keys(self):
        path = self._write(stream(61, 60.0) + host(2.0) + configured(0.0))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = frame_pacing.main(["--json", str(path)])
        self.assertEqual(code, 0)
        payload = out.getvalue()
        self.assertNotIn("Infinity", payload)
        document = json.loads(payload)
        result = document["files"][0]
        pacing = result["pacing"]

        self.assertEqual(result["sources"]["per_frame"]["count"], 61)
        self.assertEqual(pacing["observed_intervals"], 60)
        self.assertAlmostEqual(pacing["observed_fps"], 60.0, delta=0.01)
        self.assertEqual(pacing["budget"]["ms"], 16.67)
        self.assertAlmostEqual(pacing["frame_ms"]["p50"], 1000.0 / 60.0, delta=0.002)
        for key in ("sources", "window", "pacing", "missing", "notes"):
            self.assertIn(key, result)
        for key in OBSOLETE_TOKEN_KEYS:
            self.assertNotIn(key, pacing)

    def test_text_cli_emits_observed_fps_and_budget(self):
        path = self._write(stream(301, 60.0))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = frame_pacing.main([str(path)])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("observed FPS: 60.00", text)
        self.assertIn("observed intervals: 300", text)
        self.assertIn("16.67 ms budget", text)

    def test_cli_window_flags_are_applied(self):
        path = self._write(stream(601, 60.0))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = frame_pacing.main(["--start", "2", "--end", "3", str(path)])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("start 2 s after first present event", text)
        self.assertIn("tokens: 121 to 181", text)

    def test_cli_gap_text_does_not_claim_missing_presents(self):
        path = self._write(
            present(1, 0.0) + present(2, 1.0 / 60.0) + present(5, 4.0 / 60.0)
        )
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = frame_pacing.main([str(path)])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("observed FPS: 30.00", text)
        self.assertNotIn("missing present", text)
        self.assertNotIn("token gap", text)

    def test_cli_invalid_budget_returns_usage_error(self):
        path = self._write(stream(10))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = frame_pacing.main(["--budget-ms", "0", str(path)])
        self.assertEqual(code, 2)
        self.assertIn("--budget-ms must be positive", err.getvalue())

    def test_cli_invalid_window_returns_usage_error(self):
        path = self._write(stream(10))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = frame_pacing.main(["--start", "2", "--end", "1", str(path)])
        self.assertEqual(code, 2)
        self.assertIn("--end must not be earlier", err.getvalue())

    def test_cli_invalid_timestamp_returns_usage_error(self):
        path = self._write(stream(10))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = frame_pacing.main(["--start-time", "not-a-time", str(path)])
        self.assertEqual(code, 2)
        self.assertIn("invalid timestamp", err.getvalue())

    def test_cli_unknown_encoding_returns_usage_error(self):
        path = self._write(stream(10))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = frame_pacing.main(["--encoding", "definitely-not-a-codec", str(path)])
        self.assertEqual(code, 2)
        self.assertIn("unsupported --encoding", err.getvalue())

    def test_cli_missing_file_returns_failure(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = frame_pacing.main([str(SCRATCH / "does-not-exist.log")])
        self.assertEqual(code, 1)
        self.assertIn("cannot read", err.getvalue())

    def test_cli_host_only_json_keeps_frame_statistics_missing(self):
        path = self._write(host(0.0) + host(5.0))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = frame_pacing.main(["--json", str(path)])
        self.assertEqual(code, 0)
        result = json.loads(out.getvalue())["files"][0]

        self.assertEqual(result["sources"]["per_frame"]["count"], 0)
        self.assertIsNone(result["pacing"]["frame_ms"])
        self.assertEqual(result["pacing"]["budget"]["samples"], 0)
        self.assertTrue(
            any("no victory_gpu::frame 'present token=N' lines" in item for item in result["missing"])
        )


if __name__ == "__main__":
    unittest.main()
