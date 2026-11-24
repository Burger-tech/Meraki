"""Regression tests for tools/render_log.py.

The tests build small synthetic VIctory logs in memory so they do not depend
on the git-ignored capture fixtures.  They focus on the failure modes found by
the local review: strict queue tokens, interval coverage, wrapped lines and
the distinction between independently sampled counters and dropped work.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
SCRATCH = ROOT / ".local" / "test-render-log"
SCRATCH.mkdir(parents=True, exist_ok=True)


def _load_render_log():
    spec = importlib.util.spec_from_file_location(
        "render_log_under_test", TOOLS / "render_log.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


render_log = _load_render_log()


def _ts(second: int = 0) -> str:
    return f"2026-11-24T04:20:{second:02d}.000000Z"


def queue(
    frame,
    draws=0,
    drawn=0,
    dispatches=0,
    dispatched=0,
    second: int = 0,
    newline: bool = True,
) -> str:
    line = (
        f"{_ts(second)}  INFO victory_gpu::queue: frame presented "
        "(since the last line: draws and dispatches, and those run on the host) "
        f"frame={frame} draws={draws} drawn={drawn} "
        f"dispatches={dispatches} dispatched={dispatched}"
    )
    return line + ("\n" if newline else "")


def host(
    second: int = 0,
    fps="10.0",
    ms="100.0",
    draws="4",
    dropped="0",
    making="0",
    indirect="0",
) -> str:
    return (
        f"{_ts(second)}  INFO victory_gpu::host: {fps} fps, {ms} ms/frame "
        "(0.1 preparing: copies 0.1 ms 0.3 MB, textures 0.0 ms 0.0 MB; "
        "46.6 on the GPU; 0.0 copying back 0.0 MB), "
        f"{draws} draws/frame, dropped {dropped} without a host pipeline "
        f"({making} being made) and {indirect} indirect\n"
    )


def drop_detail(second: int, rate: str, reason: str = "no pipeline set") -> str:
    return (
        f"{_ts(second)}  INFO victory_gpu::host: dropped {rate}/frame "
        f"without a host pipeline: {reason}\n"
    )


def indirect_dropped(second: int) -> str:
    return (
        f"{_ts(second)}  INFO victory_gpu::list: indirect execution dropped "
        '(first time for this signature) stride=16 args=[2] max=4294967295 '
        'address=Some("0x1234") counted=false\n'
    )


def analyze(text: str) -> dict:
    return render_log._analyze("<test>", text.encode("utf-8"), None)


def rendered(result: dict) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        render_log._print_text(result, 10)
    return out.getvalue()


class QueueIntervalTests(unittest.TestCase):
    def test_complete_capture_reports_counter_difference_without_calling_it_dropped(self):
        text = (
            queue(1, 0, 0, 0, 0, 0)
            + queue(2, 3, 2, 0, 0, 1)
            + queue(4, 7, 8, 0, 0, 2)
        )
        result = analyze(text)
        frames = result["frame_intervals"]

        self.assertTrue(frames["complete"])
        self.assertEqual(frames["kind"], "complete_interval_sums")
        self.assertEqual(frames["coverage_start_frame"], 1)
        self.assertEqual(frames["coverage_end_frame"], 4)
        self.assertEqual(frames["coverage_frames"], 4)
        self.assertEqual(frames["totals"]["draws"], 10)
        self.assertEqual(frames["totals"]["drawn"], 10)
        self.assertEqual(frames["unexecuted_draws"], 0)

        text_out = rendered(result)
        self.assertIn("counter difference: draws +0", text_out)
        self.assertIn("not a dropped-draw count", text_out)
        self.assertNotIn("issued minus executed", text_out)
        self.assertNotIn("unexecuted", text_out)

    def test_partial_capture_reports_actual_coverage_not_the_record_frame(self):
        result = analyze(queue(512, 1536, 1536, 256, 256))
        frames = result["frame_intervals"]

        self.assertEqual(frames["first_frame"], 512)
        self.assertEqual(frames["coverage_start_frame"], 257)
        self.assertEqual(frames["coverage_end_frame"], 512)
        self.assertEqual(frames["coverage_frames"], 256)
        self.assertTrue(frames["complete"])
        self.assertFalse(frames["covers_from_frame_1"])
        self.assertIsNone(frames["unexecuted_draws"])
        self.assertIsNone(frames["counter_difference"]["draws"])

        text_out = rendered(result)
        self.assertIn("frames 257 to 512", text_out)
        self.assertNotIn("frames 512 to 512", text_out)
        self.assertIn("earlier frames not covered", text_out)
        self.assertIn("counter difference: n/a", text_out)

    def test_missing_interval_is_reported_and_totals_are_a_lower_bound(self):
        result = analyze(
            queue(2, 3, 2, 0, 0, 0) + queue(8, 12, 12, 0, 0, 1)
        )
        frames = result["frame_intervals"]

        self.assertFalse(frames["complete"])
        self.assertEqual(frames["kind"], "partial_interval_sums")
        self.assertEqual(frames["coverage_start_frame"], 2)
        self.assertEqual(frames["coverage_end_frame"], 8)
        self.assertEqual(frames["coverage_frames"], 5)
        self.assertEqual(frames["gaps"]["frame_count"], 2)
        self.assertEqual(frames["gaps"]["interval_frames"], [4])
        self.assertEqual(frames["totals"]["draws"], 15)
        self.assertIsNone(frames["unexecuted_draws"])

        text_out = rendered(result)
        self.assertIn("covered 5 of 7 frames", text_out)
        self.assertIn("3-4", text_out)
        self.assertIn("partial coverage; lower bound", text_out)
        self.assertTrue(any("coverage are missing" in item for item in result["missing"]))

    def test_repeated_frames_are_reported_and_not_summed(self):
        result = analyze(
            queue(64, 100, 100, 10, 10, 0)
            + queue(64, 100, 0, 10, 0, 1)
        )
        frames = result["frame_intervals"]

        self.assertEqual(frames["duplicate_frames"], [64])
        self.assertEqual(frames["duplicate_count"], 1)
        self.assertEqual(frames["restarts"], 1)
        self.assertFalse(frames["complete"])
        self.assertIsNone(frames["totals"])
        self.assertEqual(frames["coverage_start_frame"], 33)
        self.assertEqual(frames["coverage_end_frame"], 64)

        text_out = rendered(result)
        self.assertIn("overlapping/restarted", text_out)
        self.assertIn("totals: not reported", text_out)
        self.assertNotIn("200", text_out)
        self.assertTrue(any("repeat or restart" in item for item in result["notes"]))

    def test_unterminated_final_queue_record_is_excluded_as_possibly_truncated(self):
        result = analyze(queue(512, 1536, 1536, 256, 25, newline=False))
        frames = result["frame_intervals"]

        self.assertEqual(frames["records_parsed"], 1)
        self.assertEqual(frames["count"], 0)
        self.assertEqual(frames["excluded_unterminated"], 1)
        self.assertIsNone(frames["totals"])
        self.assertIsNone(frames["coverage_start_frame"])

        text_out = rendered(result)
        self.assertNotIn("231", text_out)
        self.assertNotIn("issued minus executed", text_out)
        self.assertIn("possibly truncated", " ".join(result["missing"]))
        self.assertIn("may be truncated", " ".join(result["notes"]))

    def test_wrapped_queue_message_is_joined_before_parsing(self):
        text = (
            f"{_ts(0)}  INFO victory_gpu::queue: frame presented "
            "(since the last line: draws and dispatches, and those run on the host)\n"
            "frame=512 draws=1536 drawn=1536 dispatches=256 dispatched=256\n"
        )
        result = analyze(text)
        frames = result["frame_intervals"]

        self.assertEqual(frames["records_parsed"], 1)
        self.assertEqual(frames["invalid_records"], 0)
        self.assertEqual(frames["totals"]["dispatched"], 256)
        self.assertEqual(result["joined_continuation_lines"], 1)

    def test_wrapped_mid_number_is_joined_instead_of_using_a_prefix(self):
        result = analyze(queue(512, 1536, 1536, 256, 25) + "6\n")
        frames = result["frame_intervals"]

        self.assertEqual(frames["records_parsed"], 1)
        self.assertEqual(frames["totals"]["dispatched"], 256)
        self.assertEqual(result["joined_continuation_lines"], 1)
        self.assertTrue(any("continuation" in item for item in result["notes"]))

    def test_decimal_or_suffixed_queue_counters_are_rejected(self):
        result = analyze(
            queue(512, "1536.9", "1536x", "25.6", "256suffix")
        )
        frames = result["frame_intervals"]

        self.assertEqual(frames["records_parsed"], 0)
        self.assertEqual(frames["candidates"], 1)
        self.assertEqual(frames["invalid_records"], 1)
        self.assertIsNone(frames["totals"])
        self.assertTrue(any("could not be parsed" in item for item in result["missing"]))
        self.assertTrue(any("rejected" in item for item in result["notes"]))

    def test_repeated_keys_and_non_power_of_two_frames_are_rejected(self):
        repeated = (
            f"{_ts(0)}  INFO victory_gpu::queue: frame presented "
            "frame=512 frame=512 draws=1 drawn=1 dispatches=1 dispatched=1\n"
        )
        result = analyze(repeated)
        self.assertEqual(result["frame_intervals"]["records_parsed"], 0)
        self.assertTrue(any("repeated frame" in item for item in result["notes"]))

        result = analyze(queue(100, 1, 1, 0, 0))
        self.assertEqual(result["frame_intervals"]["records_parsed"], 0)
        self.assertTrue(
            any("not a power of two" in item for item in result["notes"])
        )

    def test_huge_integer_counter_is_rejected_without_crashing(self):
        result = analyze(queue(512, "9" * 5000, 1, 1, 1))
        frames = result["frame_intervals"]

        self.assertEqual(frames["records_parsed"], 0)
        self.assertIsNone(frames["totals"])
        self.assertTrue(any("out of range" in item for item in result["notes"]))
        json.dumps(result, allow_nan=False)


class CounterSemanticsTests(unittest.TestCase):
    def test_prefix_difference_is_not_reported_as_a_drop_percentage(self):
        result = analyze(queue(1, 0, 0, 0, 0) + queue(2, 3, 2, 0, 0, 1))
        frames = result["frame_intervals"]

        self.assertEqual(frames["unexecuted_draws"], 1)
        self.assertTrue(frames["counter_difference"]["reported"])
        text_out = rendered(result)
        self.assertIn("counter difference: draws +1", text_out)
        self.assertIn("not a dropped-draw count", text_out)
        self.assertIn("interval-boundary skew", text_out)
        self.assertNotIn("66.7%", text_out)
        self.assertNotIn("unexecuted", text_out)

    def test_executed_exceeding_recorded_is_not_a_negative_drop_count(self):
        result = analyze(queue(4, 7, 8, 0, 0))
        frames = result["frame_intervals"]

        self.assertIsNone(frames["unexecuted_draws"])
        self.assertFalse(frames["covers_from_frame_1"])
        text_out = rendered(result)
        self.assertNotIn("114.3%", text_out)
        self.assertNotIn("counter difference: draws -", text_out)

    def test_indirect_is_labelled_as_dropped_and_quality_checked(self):
        result = analyze(host(indirect="12") + queue(512, 1536, 1536, 256, 256))
        host_section = result["host_samples"]

        self.assertEqual(host_section["nonzero_indirect_samples"], 1)
        self.assertEqual(host_section["stats"]["indirect_per_frame"]["max"], 12.0)
        self.assertTrue(
            any("dropped indirect" in item for item in result["missing"])
        )
        text_out = rendered(result)
        self.assertIn("dropped indirect/frame", text_out)
        self.assertIn(
            "but reports up to 12 dropped indirect/frame", text_out
        )
        self.assertNotIn("reports 0 dropped/frame in every sample\n", text_out)

    def test_indirect_drop_line_is_parsed_separately(self):
        result = analyze(
            host(indirect="12")
            + indirect_dropped(1)
            + queue(512, 1536, 1536, 256, 256)
        )
        self.assertEqual(result["indirect_drops"]["count"], 1)
        self.assertFalse(
            any("dropped indirect" in item for item in result["missing"])
        )
        self.assertIn("Dropped indirect executions", rendered(result))

    def test_rounded_host_counter_is_reconciled_with_detail_rate(self):
        result = analyze(
            host(dropped="0")
            + drop_detail(0, "0.4")
            + queue(512, 1536, 1536, 256, 256)
        )
        reconciliation = result["drop_reasons"]["reconciliation"]

        self.assertEqual(reconciliation["periods_checked"], 1)
        self.assertEqual(reconciliation["mismatches"], [])
        self.assertEqual(reconciliation["below_rounding_threshold"], 0.4)
        text_out = rendered(result)
        self.assertIn("min 0  max 0", text_out)
        self.assertNotIn("min 0.00", text_out)
        self.assertIn("round to the recorded 0 dropped/frame", " ".join(result["notes"]))

    def test_rounded_counter_mismatch_is_reported(self):
        result = analyze(
            host(dropped="1")
            + drop_detail(0, "1.5")
            + queue(512, 1536, 1536, 256, 256)
        )
        reconciliation = result["drop_reasons"]["reconciliation"]
        self.assertEqual(reconciliation["periods_checked"], 1)
        self.assertEqual(len(reconciliation["mismatches"]), 1)
        self.assertTrue(
            any("disagree with the rounded host counter" in item for item in result["notes"])
        )

    def test_out_of_order_timestamps_do_not_produce_a_negative_span(self):
        result = analyze(host(second=10, fps="10.0") + host(second=0, fps="11.0"))
        span = result["run_span"]

        self.assertEqual(span["first"], _ts(0))
        self.assertEqual(span["last"], _ts(10))
        self.assertEqual(span["seconds"], 10.0)
        self.assertTrue(
            any("out of file order" in item for item in result["notes"])
        )
        self.assertNotIn("(-", rendered(result))


class InputHandlingTests(unittest.TestCase):
    def test_wrapped_host_lines_are_joined(self):
        first = (
            f"{_ts(0)}  INFO victory_gpu::host: 13.5 fps, 73.9 ms/frame "
            "(0.1 preparing: copies 0.1 ms 0.3 MB, textures 0.0 ms 0.0 MB; "
            "46.6 on the GPU; 0.0 copying back 0.0 MB),"
        )
        second = (
            "3 draws/frame, dropped 0 without a host pipeline "
            "(0 being made) and 0 indirect"
        )
        result = analyze(first + "\n" + second + "\n" + queue(512, 1, 1, 0, 0))
        self.assertEqual(result["host_samples"]["count"], 1)
        self.assertEqual(result["host_samples"]["first"]["draws_per_frame"], 3.0)
        self.assertEqual(result["joined_continuation_lines"], 1)

    def test_host_line_wrapped_after_the_target_colon_is_joined(self):
        text = (
            f"{_ts(0)}  INFO victory_gpu::host:\n"
            "13.5 fps, 73.9 ms/frame (0.1 preparing: copies 0.1 ms 0.3 MB, "
            "textures 0.0 ms 0.0 MB; 46.6 on the GPU; 0.0 copying back 0.0 MB), "
            "3 draws/frame, dropped 0 without a host pipeline (0 being made) "
            "and 0 indirect\n"
            + queue(512, 1, 1, 0, 0)
        )
        result = analyze(text)
        self.assertEqual(result["host_samples"]["count"], 1)
        self.assertEqual(result["host_samples"]["first"]["fps"], 13.5)
        self.assertEqual(result["joined_continuation_lines"], 1)

    def test_unrecognized_binary_content_is_counted(self):
        result = render_log._analyze("<binary>", b"\x00" * 100, None)
        self.assertEqual(result["unrecognized_lines"], 1)
        self.assertTrue(
            any("did not match the log record format" in item for item in result["notes"])
        )
        self.assertTrue(any("no sampled victory_gpu::host" in item for item in result["missing"]))

    def test_empty_log_reports_missing_evidence(self):
        result = analyze("")
        self.assertTrue(any("log is empty" in item for item in result["missing"]))
        self.assertEqual(result["frame_intervals"]["records_parsed"], 0)
        self.assertEqual(result["host_samples"]["count"], 0)
        self.assertNotIn("line terminator", " ".join(result["notes"]))

    def test_unknown_and_non_text_codecs_are_rejected_cleanly(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            path = Path(directory) / "sample.log"
            path.write_text(queue(512, 1, 1, 0, 0), encoding="utf-8")
            for codec in ("definitely-not-a-codec", "base64_codec"):
                out = io.StringIO()
                err = io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = render_log.main(["--encoding", codec, str(path)])
                self.assertEqual(code, 2)
                self.assertIn("unsupported --encoding", err.getvalue())
                self.assertNotIn("Traceback", err.getvalue())

    def test_json_output_keeps_compatible_keys_and_is_standard_json(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as directory:
            path = Path(directory) / "sample.log"
            path.write_text(
                host(dropped="0") + queue(512, 1536, 1536, 256, 256),
                encoding="utf-8",
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = render_log.main(["--json", str(path)])
            self.assertEqual(code, 0)
            payload = out.getvalue()
            self.assertNotIn("Infinity", payload)
            document = json.loads(payload)
            frames = document["files"][0]["frame_intervals"]
            for key in (
                "kind",
                "count",
                "first_frame",
                "last_frame",
                "totals",
                "unexecuted_draws",
                "unexecuted_dispatches",
                "incomplete_lines",
            ):
                self.assertIn(key, frames)
            self.assertIn("drop_reasons", document["files"][0])
            self.assertEqual(frames["coverage_start_frame"], 257)

    def test_infinite_host_value_is_rejected_without_json_infinity(self):
        result = analyze(host(fps="9" * 400))
        self.assertEqual(result["host_samples"]["count"], 0)
        self.assertTrue(any("out of range" in item for item in result["notes"]))
        payload = json.dumps(result, allow_nan=False)
        self.assertNotIn("Infinity", payload)


if __name__ == "__main__":
    unittest.main()
