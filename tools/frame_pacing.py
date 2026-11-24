#!/usr/bin/env python3
"""Measure observed frame pacing from VIctory diagnostics logs.

The host present source is the diagnostics-build line emitted by
``Meter::frame`` in ``crates/victory-gpu/src/host.rs`` after every metered host
present call:

    2026-11-24T04:19:40.160536Z  DEBUG victory_gpu::frame: present token=1

Each such line is one host present event.  Its token is
``crate::frame::current()``, the title's frame-origin token from
``crates/victory-gpu/src/frame.rs``.  That counter increments when the title
begins a frame (an origin wait creates a token), independently of host
presents, so token values can repeat, jump forward, or jump backward even when
every present was logged.  Tokens are therefore labels, not present counts: every
valid present line is counted, and token changes are never used to infer
missing presents, extra presents, or run boundaries.

Only present lines are used for observed frame-time percentiles and budget
misses.  Other timestamped lines in the same log mean something different and
are kept separate:

* ``victory_gpu::host: 13.5 fps, 73.9 ms/frame ...`` is a periodic aggregate
  (logged every few seconds), not one frame.
* ``victory_gpu::queue: frame presented ... frame=512 ...`` is a real
  presentation checkpoint, but it is logged only at powers of two.
* ``victory_gpu::frame: frame interval interval=33.333ms`` records the pacing
  configuration passed to ``set_interval``; it is not a presented frame.

FPS is computed from observed present events over elapsed time and is labeled
observed.  Percentiles use linear interpolation between closest ranks (the R-7
method).  A frame is over budget when its interval is strictly greater than the
budget; a frame exactly at the budget is within.  Standard library only.
"""

from __future__ import annotations

import argparse
import codecs
import json
import math
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)"
    r"\s+(?P<level>[A-Za-z]+)\s+"
    r"(?P<target>[A-Za-z0-9_]+(?:::[A-Za-z0-9_]+)*):\s?(?P<rest>.*)$"
)

PRESENT_RE = re.compile(r"\bpresent\b[^\n]*?\btoken=(?P<token>\d+)(?=\s|$)")
INTERVAL_RE = re.compile(
    r"^frame interval\b.*?\binterval=(?P<value>\d+(?:\.\d+)?)"
    r"(?P<unit>ns|µs|μs|us|ms|s)(?=\s|$)"
)
HOST_FPS_MS_RE = re.compile(
    r"(?P<fps>\d+(?:\.\d+)?)\s+fps,\s+"
    r"(?P<ms>\d+(?:\.\d+)?)\s+ms/frame(?=\s|,|$)"
)
QUEUE_FRAME_RE = re.compile(r"(?<![A-Za-z0-9_])frame=(?P<frame>\d+)(?=\s|$)")

MAX_U64 = 2**64 - 1
MAX_UINT_DIGITS = len(str(MAX_U64))
BUDGET_MS = 16.67
BUDGET_EPSILON_MS = 1e-9

_DURATION_MS = {
    "ns": 1e-6,
    "µs": 1e-3,
    "μs": 1e-3,
    "us": 1e-3,
    "ms": 1.0,
    "s": 1000.0,
}


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def _decode_log(data: bytes, forced: str | None) -> tuple[str, str, int]:
    """Return (text, encoding label, replacement-character count)."""
    if forced:
        text = data.decode(forced, errors="replace")
        if text.startswith("\ufeff"):
            text = text[1:]
        return text, f"{forced} (forced)", text.count("\ufffd")

    if not data:
        return "", "empty", 0

    # UTF-32 BOMs begin with the UTF-16 LE BOM, so test them first.
    if data.startswith(codecs.BOM_UTF32_LE):
        text = data[4:].decode("utf-32-le", errors="replace")
        return text, "UTF-32 LE (BOM)", text.count("\ufffd")
    if data.startswith(codecs.BOM_UTF32_BE):
        text = data[4:].decode("utf-32-be", errors="replace")
        return text, "UTF-32 BE (BOM)", text.count("\ufffd")
    if data.startswith(codecs.BOM_UTF8):
        text = data[3:].decode("utf-8", errors="replace")
        return text, "UTF-8 (BOM)", text.count("\ufffd")
    if data.startswith(codecs.BOM_UTF16_LE):
        text = data[2:].decode("utf-16-le", errors="replace")
        return text, "UTF-16 LE (BOM)", text.count("\ufffd")
    if data.startswith(codecs.BOM_UTF16_BE):
        text = data[2:].decode("utf-16-be", errors="replace")
        return text, "UTF-16 BE (BOM)", text.count("\ufffd")

    sample = data[:4096]
    if len(sample) >= 8:
        even = sample[0::2]
        odd = sample[1::2]
        even_zero = even.count(0) / len(even)
        odd_zero = odd.count(0) / len(odd)
        # ASCII-heavy UTF-16 has NULs in one byte lane and almost none in the other.
        if odd_zero > 0.35 and even_zero < 0.05:
            text = data.decode("utf-16-le", errors="replace")
            return text, "UTF-16 LE (no BOM)", text.count("\ufffd")
        if even_zero > 0.35 and odd_zero < 0.05:
            text = data.decode("utf-16-be", errors="replace")
            return text, "UTF-16 BE (no BOM)", text.count("\ufffd")

    text = data.decode("utf-8", errors="replace")
    return text, "UTF-8", text.count("\ufffd")


def _split_lines(text: str) -> list[str]:
    if not text:
        return []
    lines = re.split(r"\r\n|\n|\r", text)
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _ends_with_newline(text: str) -> bool:
    return text.endswith(("\n", "\r"))


def _parse_timestamp(value: str) -> datetime | None:
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _coerce_timestamp(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"invalid timestamp {value!r}: {error}") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_uint(text: str) -> int | None:
    """Parse an unsigned 64-bit value without an unbounded int() call."""
    if not text or len(text) > MAX_UINT_DIGITS:
        return None
    value = int(text)
    if value > MAX_U64:
        return None
    return value


def _to_float(text: str) -> float | None:
    try:
        value = float(text)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _continuation_fits(previous: str, continuation: str) -> bool:
    match = LINE_RE.match(previous)
    if not match:
        return False
    target = match.group("target")
    rest = match.group("rest")
    if target == "victory_gpu::host":
        return any(
            token in continuation
            for token in ("fps", "ms/frame", "draws/frame", "dropped", "preparing", "indirect")
        )
    if target == "victory_gpu::queue" and "frame presented" in rest:
        return "=" in continuation and any(
            key + "=" in continuation
            for key in ("frame", "draws", "drawn", "dispatches", "dispatched")
        )
    return False


def _logical_records(text: str) -> tuple[list[dict], int, int, list[str]]:
    """Join wrapped continuation lines onto the record they continue."""
    lines = _split_lines(text)
    ends = _ends_with_newline(text)
    records: list[dict] = []
    unrecognized = 0
    examples: list[str] = []

    for index, raw_line in enumerate(lines):
        line = _strip_ansi(raw_line)
        if not line.strip():
            continue
        if LINE_RE.match(line):
            records.append(
                {
                    "text": line,
                    "terminated": index < len(lines) - 1 or ends,
                    "order": len(records),
                }
            )
            continue
        if records and _continuation_fits(records[-1]["text"], line):
            records[-1]["text"] += " " + line.strip()
            records[-1]["terminated"] = index < len(lines) - 1 or ends
            continue
        unrecognized += 1
        if len(examples) < 3:
            examples.append(line[:200])
    return records, unrecognized, len(lines), examples


def _percentile(ordered: list[float], q: float) -> float | None:
    """Linear interpolation between closest ranks (R-7)."""
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _frame_summary(values: list[float]) -> dict | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "p50": _percentile(ordered, 0.50),
        "p95": _percentile(ordered, 0.95),
        "p99": _percentile(ordered, 0.99),
        "max": ordered[-1],
        "mean": sum(ordered) / len(ordered),
    }


def _value_summary(values: list[float]) -> dict | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "median": statistics.median(ordered),
        "mean": sum(ordered) / len(ordered),
        "max": ordered[-1],
    }


def _format_number(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if digits == 0:
        return f"{int(round(value)):,}"
    return f"{value:,.{digits}f}"


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    seconds = max(0.0, seconds)
    if seconds < 90:
        return f"{seconds:.2f} s"
    minutes = seconds / 60.0
    if minutes < 90:
        return f"{minutes:.2f} min"
    return f"{minutes / 60.0:.2f} h"

def _window_description(
    start: float | None,
    end: float | None,
    start_time: datetime | None,
    end_time: datetime | None,
    from_frame: int | None,
    to_frame: int | None,
) -> str:
    parts: list[str] = []
    if start is not None:
        parts.append(f"start {start:g} s after first present event")
    if end is not None:
        parts.append(f"end {end:g} s after first present event")
    if start_time is not None:
        parts.append(f"start at/after {_format_timestamp(start_time)}")
    if end_time is not None:
        parts.append(f"end at/before {_format_timestamp(end_time)}")
    if from_frame is not None:
        parts.append(f"title token >= {from_frame}")
    if to_frame is not None:
        parts.append(f"title token <= {to_frame}")
    return "; ".join(parts) if parts else "whole captured present-event stream"


def _analyze(
    path: str,
    data: bytes,
    forced_encoding: str | None = None,
    *,
    start: float | None = None,
    end: float | None = None,
    start_time: str | datetime | None = None,
    end_time: str | datetime | None = None,
    from_frame: int | None = None,
    to_frame: int | None = None,
    budget_ms: float = BUDGET_MS,
) -> dict:
    text, encoding, replacements = _decode_log(data, forced_encoding)
    records, unrecognized, line_count, unrecognized_examples = _logical_records(text)

    if start is not None and (not math.isfinite(start) or start < 0):
        raise ValueError("--start must be a finite, non-negative number of seconds")
    if end is not None and (not math.isfinite(end) or end < 0):
        raise ValueError("--end must be a finite, non-negative number of seconds")
    if start is not None and end is not None and end < start:
        raise ValueError("--end must not be earlier than --start")
    if from_frame is not None and from_frame < 0:
        raise ValueError("--from-frame must be non-negative")
    if to_frame is not None and to_frame < 0:
        raise ValueError("--to-frame must be non-negative")
    if from_frame is not None and to_frame is not None and to_frame < from_frame:
        raise ValueError("--to-frame must not be smaller than --from-frame")
    if not math.isfinite(budget_ms) or budget_ms <= 0:
        raise ValueError("--budget-ms must be a finite, positive number")

    start_dt = _coerce_timestamp(start_time)
    end_dt = _coerce_timestamp(end_time)

    per_frame: list[dict] = []
    host_samples: list[dict] = []
    checkpoints: list[dict] = []
    configured: list[dict] = []
    timestamps: list[datetime] = []

    present_candidates = 0
    present_invalid = 0
    present_excluded = 0
    interval_candidates = 0
    interval_invalid = 0
    host_candidates = 0
    host_invalid = 0
    checkpoint_candidates = 0
    checkpoint_invalid = 0
    checkpoint_excluded = 0
    invalid_timestamps = 0
    invalid_examples: list[str] = []

    def invalid(line: str, reason: str) -> None:
        if len(invalid_examples) < 5:
            invalid_examples.append(f"{reason}: {line[:200]}")

    for record in records:
        line = record["text"]
        match = LINE_RE.match(line)
        if not match:
            invalid(line, "record did not match the log format")
            continue

        timestamp_text = match.group("ts")
        timestamp = _parse_timestamp(timestamp_text)
        if timestamp is None:
            invalid_timestamps += 1
            invalid(line, "invalid timestamp")
            continue
        timestamps.append(timestamp)

        target = match.group("target")
        rest = match.group("rest").rstrip()

        if target == "victory_gpu::frame":
            if re.search(r"\bpresent\b", rest):
                present_candidates += 1
                tokens = PRESENT_RE.findall(rest)
                if len(tokens) != 1:
                    present_invalid += 1
                    invalid(line, "present line lacks exactly one token")
                    continue
                token = _to_uint(tokens[0])
                if token is None:
                    present_invalid += 1
                    invalid(line, "present token is out of range")
                    continue
                if not record["terminated"]:
                    present_excluded += 1
                    continue
                per_frame.append(
                    {
                        "token": token,
                        "timestamp": timestamp,
                        "ts_text": timestamp_text,
                        "order": record["order"],
                    }
                )
                continue

            if rest.startswith("frame interval") or "interval=" in rest:
                interval_candidates += 1
                interval_match = INTERVAL_RE.match(rest)
                if not interval_match:
                    interval_invalid += 1
                    invalid(line, "frame interval line could not be parsed")
                    continue
                value = _to_float(interval_match.group("value"))
                factor = _DURATION_MS.get(interval_match.group("unit"))
                if value is None or factor is None:
                    interval_invalid += 1
                    invalid(line, "frame interval value is out of range")
                    continue
                milliseconds = value * factor
                if not math.isfinite(milliseconds) or milliseconds <= 0:
                    interval_invalid += 1
                    invalid(line, "frame interval is not positive")
                    continue
                configured.append(
                    {
                        "ms": milliseconds,
                        "timestamp": timestamp_text,
                        "time": timestamp,
                    }
                )
                continue
            continue

        if target == "victory_gpu::host":
            host_match = HOST_FPS_MS_RE.search(rest)
            if not host_match:
                if "fps" in rest and "ms/frame" in rest:
                    host_candidates += 1
                    host_invalid += 1
                    invalid(line, "host performance line could not be parsed")
                continue
            host_candidates += 1
            fps = _to_float(host_match.group("fps"))
            milliseconds = _to_float(host_match.group("ms"))
            if fps is None or milliseconds is None or fps < 0 or milliseconds < 0:
                host_invalid += 1
                invalid(line, "host fps or ms/frame is out of range")
                continue
            host_samples.append(
                {
                    "timestamp": timestamp_text,
                    "time": timestamp,
                    "fps": fps,
                    "ms_per_frame": milliseconds,
                }
            )
            continue

        if target == "victory_gpu::queue" and "frame presented" in rest:
            checkpoint_candidates += 1
            frames = QUEUE_FRAME_RE.findall(rest)
            if len(frames) != 1:
                checkpoint_invalid += 1
                invalid(line, "frame-presented line lacks exactly one frame")
                continue
            frame = _to_uint(frames[0])
            if frame is None or frame < 1:
                checkpoint_invalid += 1
                invalid(line, "frame-presented frame is out of range")
                continue
            if not record["terminated"]:
                checkpoint_excluded += 1
                continue
            checkpoints.append(
                {
                    "frame": frame,
                    "timestamp": timestamp_text,
                    "time": timestamp,
                }
            )
            continue

    out_of_order = sum(
        1 for previous, current in zip(timestamps, timestamps[1:]) if current < previous
    )

    ordered_timestamps = sorted(timestamps)
    run_first = ordered_timestamps[0] if ordered_timestamps else None
    run_last = ordered_timestamps[-1] if ordered_timestamps else None
    run_span_seconds = (
        (run_last - run_first).total_seconds()
        if run_first is not None and run_last is not None
        else None
    )

    # The relative-window base is the first present timestamp in the log.
    base_time: datetime | None = None
    if per_frame:
        base_time = min(event["timestamp"] for event in per_frame)
    elif checkpoints:
        base_time = min(item["time"] for item in checkpoints)

    notes: list[str] = []
    missing: list[str] = []

    lower = start_dt
    upper = end_dt
    relative_unresolved = False
    if start is not None:
        if base_time is None:
            relative_unresolved = True
        else:
            candidate = base_time + timedelta(seconds=start)
            lower = candidate if lower is None else max(lower, candidate)
    if end is not None:
        if base_time is None:
            relative_unresolved = True
        else:
            candidate = base_time + timedelta(seconds=end)
            upper = candidate if upper is None else min(upper, candidate)
    if lower is not None and upper is not None and lower > upper:
        raise ValueError("the selected window starts after it ends")
    if relative_unresolved:
        notes.append(
            "relative --start/--end could not be applied because the log has no "
            "timestamped present events"
        )

    selected = [
        event
        for event in per_frame
        if (lower is None or event["timestamp"] >= lower)
        and (upper is None or event["timestamp"] <= upper)
        and (from_frame is None or event["token"] >= from_frame)
        and (to_frame is None or event["token"] <= to_frame)
    ]
    selected.sort(key=lambda event: (event["timestamp"], event["order"]))
    measured = None
    if selected:
        first = selected[0]
        last = selected[-1]
        measured = {
            "events": len(selected),
            "first_token": first["token"],
            "last_token": last["token"],
            "first_timestamp": first["ts_text"],
            "last_timestamp": last["ts_text"],
            "duration_s": (last["timestamp"] - first["timestamp"]).total_seconds(),
        }

    observed_intervals: list[float] = []
    zero_or_negative_timestamps = 0
    interval_duration = 0.0
    window_duration = None
    token_repeats = 0
    token_forward_jumps = 0
    token_backward_jumps = 0
    if len(selected) >= 2:
        window_duration = (
            selected[-1]["timestamp"] - selected[0]["timestamp"]
        ).total_seconds()
        for previous, current in zip(selected, selected[1:]):
            # Token values are title frame-origin labels, not present counts.
            # A repeat, forward jump, or backward jump still follows a logged
            # present, so the interval between the two events remains measurable.
            delta = current["token"] - previous["token"]
            if delta == 0:
                token_repeats += 1
            elif delta > 1:
                token_forward_jumps += 1
            elif delta < 0:
                token_backward_jumps += 1
            seconds = (current["timestamp"] - previous["timestamp"]).total_seconds()
            if seconds <= 0:
                zero_or_negative_timestamps += 1
                continue
            observed_intervals.append(seconds * 1000.0)
            interval_duration += seconds

    observed_fps = (
        len(observed_intervals) / interval_duration if interval_duration > 0 else None
    )

    frame_ms = _frame_summary(observed_intervals)
    misses = sum(
        1 for value in observed_intervals if value > budget_ms + BUDGET_EPSILON_MS
    )
    budget = {
        "ms": budget_ms,
        "samples": len(observed_intervals),
        "misses": misses,
        "within": len(observed_intervals) - misses,
        "miss_rate": (
            misses / len(observed_intervals) if observed_intervals else None
        ),
    }

    host_fps = _value_summary([sample["fps"] for sample in host_samples])
    host_ms = _value_summary([sample["ms_per_frame"] for sample in host_samples])

    checkpoint_fps = None
    checkpoint_first = None
    checkpoint_last = None
    if checkpoints:
        ordered_checkpoints = sorted(
            checkpoints, key=lambda item: (item["time"], item["frame"])
        )
        checkpoint_first = ordered_checkpoints[0]
        checkpoint_last = ordered_checkpoints[-1]
        checkpoint_frames = 0
        checkpoint_seconds = 0.0
        previous = ordered_checkpoints[0]
        for current in ordered_checkpoints[1:]:
            seconds = (current["time"] - previous["time"]).total_seconds()
            delta = current["frame"] - previous["frame"]
            if seconds > 0 and delta > 0:
                checkpoint_frames += delta
                checkpoint_seconds += seconds
            previous = current
        if checkpoint_seconds > 0:
            checkpoint_fps = checkpoint_frames / checkpoint_seconds

    interval_values: list[dict] = []
    for item in configured:
        for entry in interval_values:
            if abs(entry["ms"] - item["ms"]) < 1e-9:
                entry["count"] += 1
                break
        else:
            interval_values.append(
                {
                    "ms": item["ms"],
                    "fps": 1000.0 / item["ms"],
                    "count": 1,
                    "first_timestamp": item["timestamp"],
                }
            )
    interval_values.sort(key=lambda entry: (-entry["count"], entry["ms"]))

    if not line_count:
        missing.append("log is empty")
    if not timestamps:
        missing.append("no timestamped VIctory log records")
    if present_candidates == 0:
        missing.append(
            "no victory_gpu::frame 'present token=N' lines; observed host present "
            "times are unavailable (requires a diagnostics build with debug logging "
            "for victory_gpu::frame)"
        )
    elif not per_frame:
        missing.append(
            f"{present_candidates} victory_gpu::frame present candidate(s) could not "
            "be parsed as complete present records"
        )
    if present_excluded:
        missing.append(
            f"{present_excluded} final present record(s) had no line terminator and "
            "were excluded as possibly truncated"
        )
    if per_frame and not selected:
        missing.append("the selected window contains no present events")
    elif len(selected) == 1:
        missing.append(
            "the selected window has only one present event; no present intervals are "
            "available"
        )
    elif len(selected) >= 2 and not observed_intervals:
        missing.append(
            "no measurable present intervals in the selected window; timestamps did "
            "not advance between present events, so frame-time percentiles and "
            "budget misses are unavailable"
        )
    if not host_samples:
        notes.append("no victory_gpu::host aggregate fps/ms samples")
    if not checkpoints:
        notes.append("no sparse victory_gpu::queue 'frame presented' checkpoints")
    if not configured:
        notes.append("no victory_gpu::frame 'frame interval' pacing configuration")

    if host_samples:
        notes.append(
            "host fps/ms samples are periodic aggregate averages and were not used "
            "for frame-time percentiles or budget misses"
        )
    if checkpoints:
        notes.append(
            "frame-presented checkpoints are real presentation events but are logged "
            "only at powers of two; they are not a dense present stream"
        )
    if configured:
        notes.append(
            "frame interval lines record pacing configuration; they are not frames"
        )
    if per_frame:
        notes.append(
            "present tokens are frame::current() title frame-origin labels, not host "
            "present counts; every valid present line is one host present event, even "
            "when token values repeat, jump forward or jump backward"
        )
    if token_repeats:
        noun = "event" if token_repeats == 1 else "events"
        notes.append(
            f"{token_repeats} adjacent present {noun} repeated the previous token "
            "label; each was still counted as a present"
        )
    if token_forward_jumps or token_backward_jumps:
        parts = []
        if token_forward_jumps:
            parts.append(f"{token_forward_jumps} token label(s) jumped forward")
        if token_backward_jumps:
            parts.append(f"{token_backward_jumps} token label(s) jumped backward")
        notes.append(
            " and ".join(parts)
            + "; token labels were not used to infer missing or extra presents"
        )
    if zero_or_negative_timestamps:
        notes.append(
            f"{zero_or_negative_timestamps} interval(s) had non-increasing timestamps "
            "and could not be measured"
        )
    if out_of_order:
        notes.append(
            f"{out_of_order} timestamped line(s) are out of file order; sizing uses "
            "the earliest and latest timestamps and pacing uses timestamp order"
        )
    if present_invalid:
        notes.append(
            f"{present_invalid} present line(s) had a missing or invalid token"
        )
    if interval_invalid:
        notes.append(f"{interval_invalid} frame interval line(s) were invalid")
    if host_invalid:
        notes.append(f"{host_invalid} host performance line(s) were invalid")
    if checkpoint_invalid:
        notes.append(f"{checkpoint_invalid} frame-presented checkpoint(s) were invalid")
    if checkpoint_excluded:
        notes.append(
            f"{checkpoint_excluded} final checkpoint(s) had no line terminator and "
            "were excluded as possibly truncated"
        )
    if invalid_timestamps:
        notes.append(f"{invalid_timestamps} record(s) had invalid timestamps")
    if unrecognized:
        notes.append(
            f"{unrecognized} non-blank line(s) did not match the log record format "
            "and were not used"
        )
    if text and not _ends_with_newline(text):
        notes.append(
            "log does not end with a line terminator; its final record may be truncated"
        )
    if replacements:
        notes.append(
            f"{replacements} Unicode replacement character(s) during decoding; text "
            "may be incomplete"
        )
    if observed_intervals:
        notes.append(
            "a frame exactly at the budget is counted as within; only intervals "
            "strictly greater than the budget are misses"
        )

    sources = {
        "per_frame": {
            "kind": "per_frame_present_events",
            "count": len(per_frame),
            "candidates": present_candidates,
            "invalid": present_invalid,
            "excluded_unterminated": present_excluded,
        },
        "host_samples": {
            "kind": "sampled_periodic_average",
            "count": len(host_samples),
            "candidates": host_candidates,
            "invalid": host_invalid,
            "stats": {"fps": host_fps, "ms_per_frame": host_ms},
        },
        "frame_checkpoints": {
            "kind": "sparse_power_of_two_presentations",
            "count": len(checkpoints),
            "candidates": checkpoint_candidates,
            "invalid": checkpoint_invalid,
            "excluded_unterminated": checkpoint_excluded,
            "first_frame": checkpoint_first["frame"] if checkpoint_first else None,
            "last_frame": checkpoint_last["frame"] if checkpoint_last else None,
            "first_timestamp": checkpoint_first["timestamp"] if checkpoint_first else None,
            "last_timestamp": checkpoint_last["timestamp"] if checkpoint_last else None,
            "coarse_observed_fps": checkpoint_fps,
        },
        "configured_intervals": {
            "kind": "pacing_configuration_not_frames",
            "count": len(configured),
            "candidates": interval_candidates,
            "invalid": interval_invalid,
            "values": interval_values,
        },
    }

    pacing = {
        "count": len(selected),
        "observed_intervals": len(observed_intervals),
        "window_duration_s": window_duration,
        "interval_duration_s": interval_duration,
        "observed_fps": observed_fps,
        "first_token": selected[0]["token"] if selected else None,
        "last_token": selected[-1]["token"] if selected else None,
        "first_timestamp": selected[0]["ts_text"] if selected else None,
        "last_timestamp": selected[-1]["ts_text"] if selected else None,
        "tokens": {
            "distinct": len({event["token"] for event in selected}),
            "repeats": token_repeats,
            "forward_jumps": token_forward_jumps,
            "backward_jumps": token_backward_jumps,
        },
        "zero_or_negative_timestamps": zero_or_negative_timestamps,
        "frame_ms": frame_ms,
        "budget": budget,
    }

    return {
        "path": path,
        "bytes": len(data),
        "lines": line_count,
        "encoding": encoding,
        "replacement_characters": replacements,
        "timestamped_lines": len(timestamps),
        "out_of_order_timestamp_lines": out_of_order,
        "run_span": {
            "first": _format_timestamp(run_first) if run_first else None,
            "last": _format_timestamp(run_last) if run_last else None,
            "seconds": run_span_seconds,
        },
        "sources": sources,
        "window": {
            "description": _window_description(
                start, end, start_dt, end_dt, from_frame, to_frame
            ),
            "base_timestamp": _format_timestamp(base_time) if base_time else None,
            "start_timestamp": _format_timestamp(lower) if lower else None,
            "end_timestamp": _format_timestamp(upper) if upper else None,
            "from_frame": from_frame,
            "to_frame": to_frame,
            "applied": bool(
                lower is not None
                or upper is not None
                or from_frame is not None
                or to_frame is not None
            ),
            "measured": measured,
        },
        "pacing": pacing,
        "missing": missing,
        "notes": notes,
        "unparsed_examples": invalid_examples + unrecognized_examples,
    }

def _print_text(result: dict) -> None:
    print(f"=== {result['path']} ===")
    print(
        f"  {result['bytes']:,} bytes | {result['lines']:,} lines | "
        f"encoding {result['encoding']} | "
        f"{result['timestamped_lines']:,} timestamped"
    )
    span = result["run_span"]
    if span["first"] and span["last"]:
        print(
            f"  timestamps {span['first']} to {span['last']} "
            f"({_format_duration(span['seconds'])})"
        )
    else:
        print("  timestamps: missing")

    sources = result["sources"]
    per_frame = sources["per_frame"]
    print()
    print("Timestamp sources (kept separate)")
    print(
        f"  present events: {per_frame['count']:,} of "
        f"{per_frame['candidates']:,} candidate(s) "
        "(victory_gpu::frame DEBUG; one per metered host present call)"
    )
    print(
        f"  host aggregate samples:   {sources['host_samples']['count']:,} "
        "(periodic averages, not frame times)"
    )
    print(
        f"  sparse frame checkpoints: {sources['frame_checkpoints']['count']:,} "
        "(frame presented, powers of two only)"
    )
    print(
        f"  configured intervals:     {sources['configured_intervals']['count']:,} "
        "(pacing requests, not frames)"
    )

    window = result["window"]
    print()
    print("Selected window")
    print(f"  request: {window['description']}")
    if window["base_timestamp"]:
        print(
            f"  relative base: {window['base_timestamp']} "
            "(first present/checkpoint timestamp)"
        )
    measured = window["measured"]
    if measured:
        print(
            f"  measured: {measured['first_timestamp']} to "
            f"{measured['last_timestamp']} "
            f"({_format_duration(measured['duration_s'])})"
        )
        print(
            f"  tokens: {measured['first_token']} to "
            f"{measured['last_token']} | {measured['events']:,} present event(s)"
        )
    else:
        print("  measured: no events in the selected window")

    pacing = result["pacing"]
    print()
    print("Frame pacing (host present events only)")
    if per_frame["count"] == 0:
        print("  MISSING: no victory_gpu::frame 'present token=N' lines")
        print(
            "  Host present timestamps require a diagnostics build with debug "
            "logging for victory_gpu::frame"
        )
        print(
            "  (for example VICTORY_LOG=info,victory_gpu::frame=debug). Host fps/ms "
            "lines are periodic averages,"
        )
        print(
            "  and sparse 'frame presented' lines are checkpoints; neither can "
            "produce frame-time percentiles."
        )
    elif pacing["count"] == 0:
        print("  MISSING: the selected window contains no present events")
    elif pacing["count"] == 1:
        print("  MISSING: only one present event in the window; no intervals")
    else:
        print(
            f"  events: {pacing['count']:,} | observed intervals: "
            f"{pacing['observed_intervals']:,}"
        )
        print(
            f"  observed: {_format_duration(pacing['window_duration_s'])} | "
            f"observed FPS: {_format_number(pacing['observed_fps'], 2)} "
            "(present intervals / elapsed time)"
        )
        frame_ms = pacing["frame_ms"]
        if frame_ms:
            print(
                f"  observed present interval ms: min {_format_number(frame_ms['min'])} | "
                f"p50 {_format_number(frame_ms['p50'])} | "
                f"p95 {_format_number(frame_ms['p95'])} | "
                f"p99 {_format_number(frame_ms['p99'])} | "
                f"max {_format_number(frame_ms['max'])} | "
                f"mean {_format_number(frame_ms['mean'])} "
                f"(n={frame_ms['count']:,})"
            )
        else:
            print("  frame time ms: MISSING (no measurable present intervals)")
        budget = pacing["budget"]
        if budget["samples"]:
            miss_word = "miss" if budget["misses"] == 1 else "misses"
            print(
                f"  {budget['ms']:.2f} ms budget: {budget['misses']:,} {miss_word} of "
                f"{budget['samples']:,} observed intervals "
                f"({_format_number((budget['miss_rate'] or 0.0) * 100.0, 1)}%) | "
                f"{budget['within']:,} within"
            )
        else:
            print("  budget: unavailable (no measurable present intervals)")

    host = sources["host_samples"]
    print()
    print("Host aggregate samples (SAMPLED: periodic averages, NOT per-frame)")
    if not host["count"]:
        print("  missing: no victory_gpu::host fps lines")
    else:
        print(f"  samples: {host['count']:,}")
        fps = host["stats"]["fps"]
        milliseconds = host["stats"]["ms_per_frame"]
        if fps:
            print(
                f"  fps: min {_format_number(fps['min'], 1)} | "
                f"median {_format_number(fps['median'], 1)} | "
                f"mean {_format_number(fps['mean'], 1)} | "
                f"max {_format_number(fps['max'], 1)}"
            )
        if milliseconds:
            print(
                f"  ms/frame: min {_format_number(milliseconds['min'], 1)} | "
                f"median {_format_number(milliseconds['median'], 1)} | "
                f"mean {_format_number(milliseconds['mean'], 1)} | "
                f"max {_format_number(milliseconds['max'], 1)}"
            )
        print("  these samples are interval averages; they are not frame samples")

    checkpoints = sources["frame_checkpoints"]
    print()
    print("Sparse frame checkpoints ('frame presented'; powers of two only)")
    if not checkpoints["count"]:
        print("  missing: no victory_gpu::queue frame-presented lines")
    else:
        print(
            f"  count: {checkpoints['count']:,} | frames "
            f"{checkpoints['first_frame']} to {checkpoints['last_frame']} | "
            f"{checkpoints['first_timestamp']} to {checkpoints['last_timestamp']}"
        )
        if checkpoints["coarse_observed_fps"] is not None:
            print(
                "  coarse observed FPS: "
                f"{_format_number(checkpoints['coarse_observed_fps'], 2)} "
                "(queue present counter delta over checkpoint span)"
            )
        print(
            "  real presentation events, but too sparse for frame-time percentiles"
        )

    configured = sources["configured_intervals"]
    print()
    print("Configured frame interval (pacing request; not a frame)")
    if not configured["values"]:
        print("  missing: no victory_gpu::frame frame-interval lines")
    else:
        for item in configured["values"][:5]:
            print(
                f"  {item['ms']:.3f} ms ({item['fps']:.2f} fps) x{item['count']} "
                f"at {item['first_timestamp']}"
            )
        if len(configured["values"]) > 5:
            print(
                f"  ... {len(configured['values']) - 5} more distinct interval(s)"
            )

    print()
    print("Data quality")
    if result["missing"]:
        for item in result["missing"]:
            print(f"  MISSING: {item}")
    else:
        print("  missing: none")
    for item in result["notes"]:
        print(f"  NOTE: {item}")

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Measure observed host present pacing from VIctory diagnostics logs: "
            "selected time windows, observed FPS, frame-time percentiles and budget "
            "misses."
        )
    )
    parser.add_argument(
        "logs",
        nargs="+",
        metavar="LOG",
        help="runtime log path (UTF-8 or UTF-16); '-' reads standard input",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit a JSON document instead of text"
    )
    parser.add_argument(
        "--encoding",
        default=None,
        help="force a Python codec name instead of detecting the encoding",
    )
    parser.add_argument(
        "--start",
        type=float,
        default=None,
        metavar="SEC",
        help="window start in seconds after the first present timestamp",
    )
    parser.add_argument(
        "--end",
        type=float,
        default=None,
        metavar="SEC",
        help="window end in seconds after the first present timestamp",
    )
    parser.add_argument(
        "--start-time",
        default=None,
        metavar="ISO",
        help="window start at or after an absolute timestamp",
    )
    parser.add_argument(
        "--end-time",
        default=None,
        metavar="ISO",
        help="window end at or before an absolute timestamp",
    )
    parser.add_argument(
        "--from-frame",
        type=int,
        default=None,
        metavar="N",
        help="include only present events whose title frame token is >= N",
    )
    parser.add_argument(
        "--to-frame",
        type=int,
        default=None,
        metavar="N",
        help="include only present events whose title frame token is <= N",
    )
    parser.add_argument(
        "--budget-ms",
        type=float,
        default=BUDGET_MS,
        metavar="MS",
        help=f"frame budget in milliseconds (default {BUDGET_MS:g})",
    )
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    if args.encoding:
        try:
            codecs.lookup(args.encoding)
            b"x".decode(args.encoding, errors="replace")
        except (LookupError, ValueError) as error:
            print(
                f"error: unsupported --encoding {args.encoding!r}: {error}",
                file=sys.stderr,
            )
            return 2

    for name, value in (
        ("--start", args.start),
        ("--end", args.end),
        ("--budget-ms", args.budget_ms),
    ):
        if value is not None and (not math.isfinite(value) or value < 0):
            print(
                f"error: {name} must be a finite, non-negative number",
                file=sys.stderr,
            )
            return 2
    if args.budget_ms <= 0:
        print("error: --budget-ms must be positive", file=sys.stderr)
        return 2
    if args.start is not None and args.end is not None and args.end < args.start:
        print("error: --end must not be earlier than --start", file=sys.stderr)
        return 2
    if (
        args.from_frame is not None
        and args.to_frame is not None
        and args.to_frame < args.from_frame
    ):
        print(
            "error: --to-frame must not be smaller than --from-frame",
            file=sys.stderr,
        )
        return 2

    try:
        start_time = _coerce_timestamp(args.start_time)
        end_time = _coerce_timestamp(args.end_time)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if start_time is not None and end_time is not None and end_time < start_time:
        print("error: --end-time must not be earlier than --start-time", file=sys.stderr)
        return 2

    results: list[dict] = []
    failed = False

    for path in args.logs:
        try:
            if path == "-":
                data = sys.stdin.buffer.read()
                display = "<stdin>"
            else:
                with open(path, "rb") as handle:
                    data = handle.read()
                display = path
        except OSError as error:
            print(f"error: cannot read {path}: {error}", file=sys.stderr)
            failed = True
            continue

        try:
            results.append(
                _analyze(
                    display,
                    data,
                    args.encoding,
                    start=args.start,
                    end=args.end,
                    start_time=start_time,
                    end_time=end_time,
                    from_frame=args.from_frame,
                    to_frame=args.to_frame,
                    budget_ms=args.budget_ms,
                )
            )
        except (ValueError, OverflowError) as error:
            print(f"error: cannot analyze {display}: {error}", file=sys.stderr)
            failed = True

    if args.json:
        try:
            json.dump({"files": results}, sys.stdout, indent=2, allow_nan=False)
        except ValueError as error:
            print(f"error: could not serialize report: {error}", file=sys.stderr)
            return 1
        sys.stdout.write("\n")
    else:
        for index, result in enumerate(results):
            if index:
                print()
            _print_text(result)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
