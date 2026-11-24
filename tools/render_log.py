#!/usr/bin/env python3
"""Summarize VIctory host performance samples from a runtime log.

Reads a VIctory runtime log (UTF-8 or PowerShell UTF-16) and prints the
sampled ``victory_gpu::host`` performance lines, the interval counters from
``victory_gpu::queue`` "frame presented" lines, and dropped-pipeline counts.
Sampled values stay labelled as samples; a section with no evidence is
reported as missing instead of being shown as zero.

Observed baseline formats (crates/victory-gpu/src/host.rs and queue.rs):

    2026-11-24T04:19:45.393287Z  INFO victory_gpu::host: 13.5 fps, 73.9 ms/frame (0.1 preparing: copies 0.1 ms 0.3 MB, textures 0.0 ms 0.0 MB; 46.6 on the GPU; 0.0 copying back 0.0 MB), 3 draws/frame, dropped 0 without a host pipeline (0 being made) and 0 indirect
    2026-11-24T04:20:49.521064Z  INFO victory_gpu::queue: frame presented (since the last line: draws and dispatches, and those run on the host) frame=512 draws=1536 drawn=1536 dispatches=256 dispatched=256
    2026-11-24T04:24:25.123456Z  INFO victory_gpu::host: dropped 1.5/frame without a host pipeline: no pipeline set
    2026-11-24T04:24:25.123456Z  INFO victory_gpu::list: indirect execution dropped (first time for this signature) stride=16 args=[2] max=4294967295 address=Some("0x1234") counted=false

The last two forms are written only by diagnostics builds.  A queue line is
logged when the presented frame is a power of two, and its counters cover the
frames since the previous queue line: the line for frame 256 covers frames
129 through 256.  ``draws``/``dispatches`` are recorded counters while
``drawn``/``dispatched`` are cumulative host-execution counters sampled at a
slightly different instant, so their difference is reported only for a
complete capture that starts at frame 1 and is never called a dropped count.

Standard library only.
"""

from __future__ import annotations

import argparse
import codecs
import json
import math
import re
import statistics
import sys
from datetime import datetime

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)"
    r"\s+(?P<level>[A-Za-z]+)\s+"
    r"(?P<target>[A-Za-z0-9_]+(?:::[A-Za-z0-9_]+)*):\s?(?P<rest>.*)$"
)

HOST_FPS_RE = re.compile(
    r"(?P<fps>\d+(?:\.\d+)?)\s+fps,\s+"
    r"(?P<ms>\d+(?:\.\d+)?)\s+ms/frame(?=\s|,|$)"
)
HOST_DRAWS_RE = re.compile(r"(?P<draws>\d+(?:\.\d+)?)\s+draws/frame(?=\s|,|$)")
HOST_DROPPED_RE = re.compile(
    r"dropped\s+(?P<dropped>\d+(?:\.\d+)?)\s+without\s+a\s+host\s+pipeline"
    r"\s*\(\s*(?P<making>\d+)\s+being\s+made\s*\)(?=\s|,|$)"
)
HOST_INDIRECT_RE = re.compile(
    r"and\s+(?P<indirect>\d+(?:\.\d+)?)\s+indirect(?=\s|,|$)"
)
DROP_DETAIL_RE = re.compile(
    r"^dropped\s+(?P<rate>\d+(?:\.\d+)?)/frame\s+without\s+a\s+host\s+pipeline:\s*"
    r"(?P<reason>.*)$"
)
DROP_WORD_RE = re.compile(r"\bdrop(?:ped|s)?\b", re.IGNORECASE)

HOST_FIELDS = (
    "fps",
    "ms_per_frame",
    "draws_per_frame",
    "dropped_per_frame",
    "being_made",
    "indirect_per_frame",
)
HOST_FIELD_LABELS = {
    "fps": "fps",
    "ms_per_frame": "ms/frame",
    "draws_per_frame": "draws/frame",
    "dropped_per_frame": "dropped/frame",
    "being_made": "being made",
    "indirect_per_frame": "dropped indirect/frame",
}
# host.rs formats fps/ms with one decimal and the counters as whole numbers.
HOST_FIELD_DIGITS = {
    "fps": 1,
    "ms_per_frame": 1,
    "draws_per_frame": 0,
    "dropped_per_frame": 0,
    "being_made": 0,
    "indirect_per_frame": 0,
}
QUEUE_KEYS = ("frame", "draws", "drawn", "dispatches", "dispatched")
QUEUE_PATTERNS = {
    key: re.compile(r"(?<![A-Za-z0-9_])" + key + r"=(\d+)(?=\s|$)")
    for key in QUEUE_KEYS
}

MAX_U64 = 2**64 - 1
MAX_UINT_DIGITS = len(str(MAX_U64))


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
        # LE stores the high zero byte at odd offsets; BE stores it at even ones.
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
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _to_uint(text: str) -> int | None:
    """Parse an unsigned 64-bit counter without an unbounded int() call."""
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


def _parse_host(rest: str) -> tuple[dict, list[str]]:
    sample: dict = {}
    problems: list[str] = []

    match = HOST_FPS_RE.search(rest)
    if match:
        fps = _to_float(match.group("fps"))
        ms = _to_float(match.group("ms"))
        if fps is None or ms is None:
            problems.append("fps or ms/frame is out of range")
        else:
            sample["fps"] = fps
            sample["ms_per_frame"] = ms

    match = HOST_DRAWS_RE.search(rest)
    if match:
        draws = _to_float(match.group("draws"))
        if draws is None:
            problems.append("draws/frame is out of range")
        else:
            sample["draws_per_frame"] = draws

    match = HOST_DROPPED_RE.search(rest)
    if match:
        dropped = _to_float(match.group("dropped"))
        making = _to_uint(match.group("making"))
        if dropped is None or making is None:
            problems.append("dropped/frame or being-made count is out of range")
        else:
            sample["dropped_per_frame"] = dropped
            sample["being_made"] = making

    match = HOST_INDIRECT_RE.search(rest)
    if match:
        indirect = _to_float(match.group("indirect"))
        if indirect is None:
            problems.append("indirect/frame is out of range")
        else:
            sample["indirect_per_frame"] = indirect

    return sample, problems


def _parse_queue(rest: str) -> tuple[dict, list[str]]:
    """Parse a queue record, requiring whole numbers with token boundaries."""
    fields: dict = {}
    problems: list[str] = []
    for key in QUEUE_KEYS:
        matches = QUEUE_PATTERNS[key].findall(rest)
        if not matches:
            continue
        if len(matches) > 1:
            problems.append(f"repeated {key}")
        value = _to_uint(matches[0])
        if value is None:
            problems.append(f"{key} is out of range")
        else:
            fields[key] = value
    return fields, problems


def _summary(values: list[float]) -> dict | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "max": ordered[-1],
        "mean": sum(ordered) / len(ordered),
        "median": statistics.median(ordered),
    }


def _median_spacing(times: list[datetime]) -> float | None:
    ordered = sorted(times)
    deltas = [(b - a).total_seconds() for a, b in zip(ordered, ordered[1:])]
    deltas = [d for d in deltas if d >= 0]
    if not deltas:
        return None
    return statistics.median(deltas)


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
        return f"{seconds:.1f} s"
    minutes = seconds / 60.0
    if minutes < 90:
        return f"{minutes:.1f} min"
    return f"{minutes / 60.0:.1f} h"


def _sample_brief(sample: dict) -> str:
    parts = [f"{_format_number(sample.get('fps'), 1)} fps"]
    parts.append(f"{_format_number(sample.get('draws_per_frame'), 0)} draws/frame")
    if "dropped_per_frame" in sample:
        parts.append(f"dropped {_format_number(sample['dropped_per_frame'], 0)}/frame")
    else:
        parts.append("dropped n/a")
    if sample.get("indirect_per_frame", 0.0) > 0:
        parts.append(
            f"dropped indirect {_format_number(sample['indirect_per_frame'], 0)}/frame"
        )
    return ", ".join(parts)


def _stat_line(
    label: str,
    values: dict | None,
    digits: int = 2,
    mean_digits: int | None = None,
    of_total: int | None = None,
) -> str:
    if not values:
        return f"  {label:<24} missing"
    mean_digits = digits if mean_digits is None else mean_digits
    suffix = ""
    if of_total is not None and values["count"] != of_total:
        suffix = f"  [n={values['count']} of {of_total}]"
    return (
        f"  {label:<24} min {_format_number(values['min'], digits)}"
        f"  max {_format_number(values['max'], digits)}"
        f"  mean {_format_number(values['mean'], mean_digits)}"
        f"  median {_format_number(values['median'], digits)}"
        f"{suffix}"
    )


def _looks_like_record_start(line: str) -> bool:
    return line.startswith("[") or re.match(r"^\d{4}-\d{2}-\d{2}[T ]", line) is not None


def _record_needs_continuation(text: str) -> bool:
    """Whether the record is visibly cut before its expected fields end."""
    match = LINE_RE.match(text)
    if not match:
        return False
    target = match.group("target")
    rest = match.group("rest").rstrip()
    if target == "victory_gpu::host":
        if not rest:
            return True
        if DROP_DETAIL_RE.match(rest):
            return False
        if not HOST_FPS_RE.search(rest):
            return False
        return not (
            HOST_DRAWS_RE.search(rest)
            and HOST_DROPPED_RE.search(rest)
            and HOST_INDIRECT_RE.search(rest)
        )
    if target == "victory_gpu::queue" and "frame presented" in rest:
        counters, problems = _parse_queue(rest)
        return bool(problems) or any(key not in counters for key in QUEUE_KEYS)
    return False


def _continuation_fits(text: str, continuation: str) -> bool:
    """Keep unrelated summary lines from being appended to a log record."""
    if not _record_needs_continuation(text):
        return bool(re.fullmatch(r"\d+", continuation.strip())) and bool(
            re.search(r"=\d+$", text.rstrip())
        )
    match = LINE_RE.match(text)
    if not match:
        return False
    target = match.group("target")
    if target == "victory_gpu::host":
        return any(
            token in continuation
            for token in (
                "fps",
                "ms/frame",
                "draws/frame",
                "dropped",
                "indirect",
                "preparing",
            )
        )
    if target == "victory_gpu::queue":
        return any(key + "=" in continuation for key in QUEUE_KEYS)
    return False


def _logical_records(text: str) -> tuple[list[dict], list[str], list[str]]:
    """Join wrapped continuation lines onto the record they continue.

    A physical line that is neither blank nor a timestamped record is joined to
    the preceding record when that record is visibly incomplete, or when it is
    a bare numeric fragment continuing a counter.  This handles terminal wraps
    that split a counter or the start of a host sample without swallowing
    unrelated summary text.  Returns the logical records, unrecognized
    non-blank lines, and the physical lines.
    """
    lines = _split_lines(text)
    ends = _ends_with_newline(text)
    records: list[dict] = []
    unrecognized: list[str] = []
    pending: dict | None = None

    def flush() -> None:
        nonlocal pending
        if pending is not None:
            records.append(pending)
            pending = None

    for index, raw_line in enumerate(lines):
        line = _strip_ansi(raw_line)
        if not line.strip():
            flush()
            continue
        if LINE_RE.match(line):
            flush()
            pending = {
                "text": line,
                "terminated": index < len(lines) - 1 or ends,
                "continuations": 0,
            }
            continue
        if (
            pending is not None
            and not _looks_like_record_start(line)
            and _continuation_fits(pending["text"], line)
        ):
            pending["text"] += line.lstrip()
            pending["continuations"] += 1
            pending["terminated"] = index < len(lines) - 1 or ends
            continue
        flush()
        unrecognized.append(line)
    flush()
    return records, unrecognized, lines


def _format_ranges(ranges: list[tuple[int, int]]) -> str:
    parts = []
    for start, end in ranges:
        parts.append(str(start) if start == end else f"{start}-{end}")
    return ", ".join(parts)


def _summarize_intervals(records: list[dict]) -> dict:
    """Validate queue records and describe the coverage they actually have."""
    parsed = len(records)
    suspect = [record for record in records if not record.get("_terminated", True)]
    included = [record for record in records if record.get("_terminated", True)]

    ordered = sorted(
        included,
        key=lambda record: (
            record["_time"].timestamp() if record.get("_time") is not None else -1e99,
            record.get("_order", 0),
        ),
    )
    restarts = sum(
        1
        for previous, current in zip(ordered, ordered[1:])
        if current["frame"] <= previous["frame"]
    )

    by_frame: dict[int, list[dict]] = {}
    for record in included:
        by_frame.setdefault(record["frame"], []).append(record)
    duplicate_frames = sorted(
        frame for frame, group in by_frame.items() if len(group) > 1
    )
    duplicate_count = sum(
        len(group) - 1 for group in by_frame.values() if len(group) > 1
    )
    unique = {frame: group[0] for frame, group in by_frame.items()}

    frames = sorted(unique)
    intervals: list[dict] = []
    gap_ranges: list[tuple[int, int]] = []
    previous_end: int | None = None
    for frame in frames:
        start = frame // 2 + 1
        end = frame
        if previous_end is not None and start > previous_end + 1:
            gap_ranges.append((previous_end + 1, start - 1))
        record = unique[frame]
        intervals.append(
            {
                "frame": frame,
                "start_frame": start,
                "end_frame": end,
                "draws": record["draws"],
                "drawn": record["drawn"],
                "dispatches": record["dispatches"],
                "dispatched": record["dispatched"],
                "timestamp": record["timestamp"],
                "terminated": record.get("_terminated", True),
            }
        )
        previous_end = end

    missing_interval_frames: list[int] = []
    for start, end in gap_ranges:
        frame = 1
        while frame <= end:
            if frame // 2 + 1 >= start and frame <= end:
                missing_interval_frames.append(frame)
            frame *= 2

    coverage_start = intervals[0]["start_frame"] if intervals else None
    coverage_end = intervals[-1]["end_frame"] if intervals else None
    coverage_frames = sum(
        interval["end_frame"] - interval["start_frame"] + 1 for interval in intervals
    )
    missing_frames = sum(end - start + 1 for start, end in gap_ranges)

    complete = bool(
        included
        and not gap_ranges
        and not duplicate_frames
        and not restarts
        and not suspect
    )
    totals: dict | None = None
    if included and not duplicate_frames and not restarts:
        totals = {
            "draws": sum(record["draws"] for record in unique.values()),
            "drawn": sum(record["drawn"] for record in unique.values()),
            "dispatches": sum(record["dispatches"] for record in unique.values()),
            "dispatched": sum(record["dispatched"] for record in unique.values()),
        }
    if totals is None:
        kind = "unavailable_interval_sums"
    elif complete:
        kind = "complete_interval_sums"
    else:
        kind = "partial_interval_sums"

    fully_covered_from_start = complete and coverage_start == 1
    difference_draws = (
        totals["draws"] - totals["drawn"] if fully_covered_from_start and totals else None
    )
    difference_dispatches = (
        totals["dispatches"] - totals["dispatched"]
        if fully_covered_from_start and totals
        else None
    )

    return {
        "kind": kind,
        "complete": complete,
        "count": len(included),
        "records_parsed": parsed,
        "candidates": 0,
        "invalid_records": 0,
        "excluded_unterminated": len(suspect),
        "first_frame": frames[0] if frames else None,
        "last_frame": frames[-1] if frames else None,
        "coverage_start_frame": coverage_start,
        "coverage_end_frame": coverage_end,
        "coverage_frames": coverage_frames,
        "covers_from_frame_1": coverage_start == 1,
        "contiguous": bool(included) and not gap_ranges and not duplicate_frames,
        "gaps": {
            "interval_count": len(missing_interval_frames),
            "frame_count": missing_frames,
            "ranges": [_format_ranges([item]) for item in gap_ranges],
            "interval_frames": missing_interval_frames,
        },
        "duplicate_frames": duplicate_frames,
        "duplicate_count": duplicate_count,
        "restarts": restarts,
        "intervals": intervals,
        "totals": totals,
        "unexecuted_draws": difference_draws,
        "unexecuted_dispatches": difference_dispatches,
        "counter_difference": {
            "kind": "independent_counter_difference",
            "meaning": (
                "draws recorded minus draws executed on the host; the counters "
                "are sampled at different instants and this is not a dropped-draw count"
            ),
            "reported": fully_covered_from_start,
            "draws": difference_draws,
            "dispatches": difference_dispatches,
        },
        "first_timestamp": intervals[0]["timestamp"] if intervals else None,
        "last_timestamp": intervals[-1]["timestamp"] if intervals else None,
        "incomplete_lines": 0,
    }


def _analyze(path: str, data: bytes, forced_encoding: str | None) -> dict:
    text, encoding, replacements = _decode_log(data, forced_encoding)
    records, unrecognized, lines = _logical_records(text)

    host_samples: list[dict] = []
    queue_records: list[dict] = []
    drop_details: list[dict] = []
    indirect_drops: list[dict] = []
    drop_warnings: dict[str, dict] = {}
    unparsed: list[str] = []
    timestamps: list[datetime] = []
    timestamp_texts: list[str] = []
    host_candidates = 0
    queue_candidates = 0
    queue_invalid = 0
    queue_errors: list[str] = []
    host_empty = 0
    host_problems: list[str] = []
    unterminated_host = 0
    joined_continuations = 0
    last_host_index: int | None = None

    for order, record in enumerate(records):
        joined_continuations += record["continuations"]
        line = record["text"]
        match = LINE_RE.match(line)
        if not match:
            # _logical_records only keeps lines that matched, but stay defensive.
            unparsed.append(line[:200])
            continue

        ts_text = match.group("ts")
        timestamp = _parse_timestamp(ts_text)
        if timestamp is not None:
            timestamps.append(timestamp)
            timestamp_texts.append(ts_text)
        level = match.group("level").upper()
        target = match.group("target")
        rest = match.group("rest").rstrip()

        if target == "victory_gpu::host":
            if not rest:
                host_candidates += 1
                host_empty += 1
                unparsed.append(line[:200])
                continue

            detail = DROP_DETAIL_RE.match(rest)
            if detail:
                rate = _to_float(detail.group("rate"))
                if rate is None:
                    host_problems.append(
                        f"{ts_text}: drop-detail rate is out of range"
                    )
                    continue
                drop_details.append(
                    {
                        "timestamp": ts_text,
                        "rate": rate,
                        "reason": detail.group("reason").strip() or "(no reason)",
                        "_host": last_host_index,
                    }
                )
                continue

            if HOST_FPS_RE.search(rest):
                host_candidates += 1
                sample, problems = _parse_host(rest)
                if problems:
                    host_problems.append(f"{ts_text}: " + "; ".join(problems))
                if "fps" in sample and "ms_per_frame" in sample:
                    sample["timestamp"] = ts_text
                    sample["_time"] = timestamp
                    sample["_terminated"] = record["terminated"]
                    host_samples.append(sample)
                    last_host_index = len(host_samples) - 1
                    if not record["terminated"]:
                        unterminated_host += 1
                else:
                    unparsed.append(line[:200])
                continue

        elif target == "victory_gpu::queue" and "frame presented" in rest:
            queue_candidates += 1
            counters, problems = _parse_queue(rest)
            missing_keys = [key for key in QUEUE_KEYS if key not in counters]
            if problems or missing_keys:
                queue_invalid += 1
                reason = "; ".join(problems) if problems else "missing counters"
                queue_errors.append(f"{ts_text}: {reason}")
                unparsed.append(line[:200])
                continue
            frame = counters["frame"]
            if frame < 1 or frame & (frame - 1):
                queue_invalid += 1
                queue_errors.append(f"{ts_text}: frame={frame} is not a power of two")
                unparsed.append(line[:200])
                continue
            counters["timestamp"] = ts_text
            counters["_time"] = timestamp
            counters["_order"] = order
            counters["_terminated"] = record["terminated"]
            queue_records.append(counters)
            continue

        elif target == "victory_gpu::list" and "indirect execution dropped" in rest:
            indirect_drops.append(
                {"timestamp": ts_text, "detail": rest[:240]}
            )
            continue

        if level in ("WARN", "ERROR") and DROP_WORD_RE.search(rest):
            signature = re.sub(r"0x[0-9a-fA-F]+", "0x...", rest)
            signature = re.sub(r"\b\d+\b", "N", signature)
            entry = drop_warnings.setdefault(
                signature, {"message": rest, "count": 0}
            )
            entry["count"] += 1

    # Keep the internal datetimes out of the JSON/text payloads.
    host_times: list[datetime] = []
    host_time_index: list[tuple[datetime, int]] = []
    for index, sample in enumerate(host_samples):
        when = sample.pop("_time", None)
        sample.pop("_terminated", None)
        if when is not None:
            host_times.append(when)
            host_time_index.append((when, index))
    for record in queue_records:
        record.pop("_time", None)
        record.pop("_order", None)

    field_counts = {
        field: sum(1 for sample in host_samples if field in sample)
        for field in HOST_FIELDS
    }
    stats = {
        field: _summary(
            [float(sample[field]) for sample in host_samples if field in sample]
        )
        for field in HOST_FIELDS
    }

    drop_reasons: dict[str, dict] = {}
    for detail in drop_details:
        entry = drop_reasons.setdefault(
            detail["reason"],
            {"reason": detail["reason"], "lines": 0, "rates": []},
        )
        entry["lines"] += 1
        entry["rates"].append(detail["rate"])
    reason_list = []
    for entry in drop_reasons.values():
        rates = entry["rates"]
        reason_list.append(
            {
                "reason": entry["reason"],
                "lines": entry["lines"],
                "max_per_frame": max(rates),
                "mean_per_frame": sum(rates) / len(rates),
            }
        )
    reason_list.sort(key=lambda item: (-item["max_per_frame"], item["reason"]))

    # Reconcile rounded host counters with the detail rates of the same period.
    period_rates: dict[int, list[float]] = {}
    for detail in drop_details:
        host_index = detail.pop("_host", None)
        if host_index is not None:
            period_rates.setdefault(host_index, []).append(detail["rate"])
    periods_checked = 0
    mismatches: list[str] = []
    below_threshold: float | None = None
    for host_index, rates in period_rates.items():
        sample = host_samples[host_index]
        if "dropped_per_frame" not in sample:
            continue
        periods_checked += 1
        total = sum(rates)
        rounded = int(round(total))
        if abs(rounded - sample["dropped_per_frame"]) > 0.5:
            mismatches.append(
                f"{sample['timestamp']} (detail {total:.1f}/frame, "
                f"counter {_format_number(sample['dropped_per_frame'], 0)}/frame)"
            )
        elif rounded == 0 and total > 0:
            below_threshold = max(below_threshold or 0.0, total)

    intervals = _summarize_intervals(queue_records)
    intervals["candidates"] = queue_candidates
    intervals["invalid_records"] = queue_invalid
    intervals["incomplete_lines"] = queue_invalid

    host_by_time = sorted(host_time_index, key=lambda item: item[0])
    earliest = host_samples[host_by_time[0][1]] if host_by_time else None
    latest = host_samples[host_by_time[-1][1]] if host_by_time else None

    missing: list[str] = []
    notes: list[str] = []

    if not lines:
        missing.append("log is empty")
    if not host_samples:
        missing.append(
            "no sampled victory_gpu::host performance lines; fps, draws/frame and "
            "dropped-pipeline counts are unavailable"
        )
    else:
        absent = [
            HOST_FIELD_LABELS[field]
            for field in HOST_FIELDS
            if field_counts[field] == 0
        ]
        if absent:
            missing.append("host samples lack: " + ", ".join(absent))
        partial = [
            HOST_FIELD_LABELS[field]
            for field in HOST_FIELDS
            if 0 < field_counts[field] < len(host_samples)
        ]
        if partial:
            notes.append(
                "some host samples lack: "
                + ", ".join(partial)
                + f" (of {len(host_samples)} samples)"
            )

    if queue_candidates == 0:
        missing.append(
            "no victory_gpu::queue 'frame presented' lines; interval "
            "draw/dispatch counts are unavailable"
        )
    elif not queue_records:
        missing.append(
            f"{queue_candidates} 'frame presented' line(s) could not be parsed as "
            "complete interval records"
        )
    else:
        if queue_invalid:
            missing.append(
                f"{queue_invalid} 'frame presented' line(s) lacked complete, valid "
                "whole-number counters"
            )
        if intervals["excluded_unterminated"]:
            missing.append(
                f"{intervals['excluded_unterminated']} final queue record(s) had no "
                "line terminator and were excluded as possibly truncated"
            )
        if intervals["gaps"]["frame_count"]:
            ranges = ", ".join(intervals["gaps"]["ranges"][:3])
            missing.append(
                f"{intervals['gaps']['frame_count']:,} frame(s) of interval coverage "
                f"are missing ({intervals['gaps']['interval_count']} queue "
                f"interval(s): {ranges})"
            )

    if intervals["duplicate_frames"] or intervals["restarts"]:
        frames = ", ".join(str(frame) for frame in intervals["duplicate_frames"][:5])
        notes.append(
            "queue records repeat or restart frames ("
            + (f"duplicate frame(s): {frames}; " if frames else "")
            + f"restarts: {intervals['restarts']}); interval totals are not summed"
        )

    if host_samples and field_counts["dropped_per_frame"]:
        dropped_stats = stats["dropped_per_frame"]
        if dropped_stats and dropped_stats["max"] > 0 and not drop_details:
            missing.append(
                "host samples report dropped frames, but no diagnostic "
                "drop-reason lines are present"
            )
    if host_samples and field_counts["indirect_per_frame"]:
        indirect_stats = stats["indirect_per_frame"]
        nonzero = sum(
            1 for sample in host_samples if sample.get("indirect_per_frame", 0.0) > 0
        )
        if nonzero and not indirect_drops:
            missing.append(
                "host samples report dropped indirect executions in "
                f"{nonzero} sample(s), but no victory_gpu::list "
                "'indirect execution dropped' lines are present"
            )
        if indirect_stats and indirect_stats["max"] > 0 and not drop_details:
            notes.append(
                "dropped indirect executions are counted separately from "
                "dropped host pipelines"
            )

    if drop_details:
        if not host_samples:
            notes.append(
                f"{len(drop_details)} drop-detail line(s) have no sampled host line "
                "to reconcile against"
            )
        else:
            notes.append(
                f"rounded-counter reconciliation: {periods_checked} period(s) "
                f"checked, {len(mismatches)} mismatch(es)"
            )
            if mismatches:
                notes.append(
                    "detail rates disagree with the rounded host counter: "
                    + "; ".join(mismatches[:3])
                )
            if below_threshold:
                notes.append(
                    "drop-detail rates up to "
                    f"{below_threshold:.1f}/frame round to the recorded "
                    "0 dropped/frame"
                )

    if unterminated_host:
        notes.append(
            f"{unterminated_host} host record(s) have no final line terminator; "
            "their values may be truncated"
        )
    if host_empty:
        notes.append(
            f"{host_empty} victory_gpu::host line(s) had no message text after the target"
        )
    if host_problems:
        notes.append(
            f"{len(host_problems)} host record(s) had invalid values: "
            + "; ".join(host_problems[:3])
        )
    if queue_errors:
        notes.append(
            f"{len(queue_errors)} queue record(s) were rejected: "
            + "; ".join(queue_errors[:3])
        )
    if joined_continuations:
        notes.append(
            f"{joined_continuations} wrapped continuation line(s) were joined to "
            "the preceding record"
        )
    if unrecognized:
        notes.append(
            f"{len(unrecognized)} non-blank line(s) did not match the log record "
            "format and were not used"
        )
    if text and not _ends_with_newline(text):
        notes.append(
            "log does not end with a line terminator; its final record may be truncated"
        )
    if replacements:
        notes.append(
            f"{replacements} Unicode replacement character(s) during decoding; "
            "text may be incomplete"
        )
    if unparsed:
        notes.append(f"{len(unparsed)} host/queue line(s) could not be parsed")
    if host_candidates != len(host_samples) and host_candidates:
        notes.append(
            f"parsed {len(host_samples)} of {host_candidates} host performance candidates"
        )

    out_of_order = sum(
        1 for previous, current in zip(timestamps, timestamps[1:]) if current < previous
    )
    if out_of_order:
        notes.append(
            f"{out_of_order} timestamped line(s) are out of file order; the run "
            "span uses the earliest and latest timestamps"
        )

    spanned = sorted(zip(timestamps, timestamp_texts), key=lambda item: item[0])
    earliest_ts = spanned[0] if spanned else None
    latest_ts = spanned[-1] if spanned else None
    span_seconds = (
        (latest_ts[0] - earliest_ts[0]).total_seconds()
        if earliest_ts is not None and latest_ts is not None
        else None
    )

    return {
        "path": path,
        "bytes": len(data),
        "lines": len(lines),
        "encoding": encoding,
        "replacement_characters": replacements,
        "timestamped_lines": len(timestamps),
        "out_of_order_timestamp_lines": out_of_order,
        "unrecognized_lines": len(unrecognized),
        "joined_continuation_lines": joined_continuations,
        "run_span": {
            "first": earliest_ts[1] if earliest_ts else None,
            "last": latest_ts[1] if latest_ts else None,
            "seconds": span_seconds,
        },
        "host_samples": {
            "kind": "sampled_periodic_average",
            "count": len(host_samples),
            "first": host_samples[0] if host_samples else None,
            "last": host_samples[-1] if host_samples else None,
            "earliest": earliest,
            "latest": latest,
            "lowest_fps": (
                min(host_samples, key=lambda sample: sample.get("fps", float("inf")))
                if host_samples
                else None
            ),
            "median_spacing_seconds": _median_spacing(host_times),
            "field_counts": field_counts,
            "nonzero_dropped_samples": sum(
                1
                for sample in host_samples
                if sample.get("dropped_per_frame", 0.0) > 0
            ),
            "nonzero_indirect_samples": sum(
                1
                for sample in host_samples
                if sample.get("indirect_per_frame", 0.0) > 0
            ),
            "stats": stats,
        },
        "frame_intervals": intervals,
        "drop_reasons": {
            "kind": "diagnostics_detail",
            "line_count": len(drop_details),
            "reasons": reason_list,
            "reconciliation": {
                "periods_checked": periods_checked,
                "mismatches": mismatches,
                "below_rounding_threshold": below_threshold,
            },
        },
        "indirect_drops": {
            "kind": "first_per_signature_detail",
            "count": len(indirect_drops),
            "examples": indirect_drops[:3],
        },
        "drop_warnings": sorted(
            drop_warnings.values(), key=lambda item: (-item["count"], item["message"])
        ),
        "missing": missing,
        "notes": notes,
        "unparsed_examples": unparsed[:3],
    }


def _print_text(result: dict, max_reasons: int) -> None:
    print(f"=== {result['path']} ===")
    print(
        f"  {result['bytes']:,} bytes | {result['lines']:,} lines | "
        f"encoding {result['encoding']} | {result['timestamped_lines']:,} timestamped"
    )

    span = result["run_span"]
    if span["first"] and span["last"]:
        print(
            f"  timestamps {span['first']} to {span['last']} "
            f"({_format_duration(span['seconds'])})"
        )
    else:
        print("  timestamps: missing")

    host = result["host_samples"]
    print()
    print("Host performance samples (SAMPLED: periodic runtime averages, not totals)")
    if not host["count"]:
        print("  MISSING: no victory_gpu::host fps lines")
    else:
        spacing = host["median_spacing_seconds"]
        if spacing is None:
            print(f"  samples: {host['count']} | sample spacing: n/a")
        else:
            print(
                f"  samples: {host['count']} | median sample spacing "
                f"{spacing:.2f} s"
            )
        print(
            "  source precision: 1 decimal for fps/ms; whole numbers for draws, "
            "dropped, being made and indirect"
        )
        print(
            "  means and medians average those rounded samples; they are not exact "
            "runtime totals"
        )
        for field in HOST_FIELDS:
            print(
                _stat_line(
                    HOST_FIELD_LABELS[field],
                    host["stats"][field],
                    HOST_FIELD_DIGITS[field],
                    mean_digits=1,
                    of_total=host["count"],
                )
            )
        dropped = host["stats"]["dropped_per_frame"]
        if dropped:
            print(
                "  dropped/frame samples above zero: "
                f"{host['nonzero_dropped_samples']} of {host['count']}"
            )
        indirect = host["stats"]["indirect_per_frame"]
        if indirect:
            print(
                "  dropped indirect/frame samples above zero: "
                f"{host['nonzero_indirect_samples']} of {host['count']}"
            )
        earliest = host["earliest"]
        latest = host["latest"]
        lowest = host["lowest_fps"]
        if host["count"] == 1 and earliest:
            print(f"  only sample: {earliest['timestamp']}  {_sample_brief(earliest)}")
        else:
            if earliest:
                print(
                    f"  earliest sample: {earliest['timestamp']}  "
                    f"{_sample_brief(earliest)}"
                )
            if lowest:
                print(f"  lowest fps:      {lowest['timestamp']}  {_sample_brief(lowest)}")
            if latest:
                print(
                    f"  latest sample:   {latest['timestamp']}  "
                    f"{_sample_brief(latest)}"
                )

    frames = result["frame_intervals"]
    print()
    print(
        "Frame-interval counters ('frame presented'; logged at powers of two, "
        "each covering the frames since the previous line)"
    )
    if not frames["records_parsed"]:
        if not frames["candidates"]:
            print("  MISSING: no frame-presented lines")
        else:
            print(
                f"  MISSING: {frames['candidates']} frame-presented line(s) could "
                "not be parsed as complete records"
            )
    else:
        print(
            f"  records: {frames['records_parsed']} parsed | {frames['count']} "
            f"included | {frames['excluded_unterminated']} excluded (no terminator) "
            f"| {frames['invalid_records']} invalid"
        )
        if frames["coverage_start_frame"] is None:
            print("  coverage: unavailable (no included intervals)")
        else:
            expected = (
                frames["coverage_end_frame"] - frames["coverage_start_frame"] + 1
            )
            print(
                f"  coverage: frames {frames['coverage_start_frame']} to "
                f"{frames['coverage_end_frame']} | covered "
                f"{frames['coverage_frames']:,} of {expected:,} frames "
                f"| starts at frame 1: "
                f"{'yes' if frames['covers_from_frame_1'] else 'no'}"
            )
        gap_text = "none"
        if frames["gaps"]["frame_count"]:
            ranges = ", ".join(frames["gaps"]["ranges"][:3])
            gap_text = (
                f"{frames['gaps']['interval_count']} interval(s), "
                f"{frames['gaps']['frame_count']:,} frame(s): {ranges}"
            )
        duplicate_text = "none"
        if frames["duplicate_frames"]:
            listed = ", ".join(str(frame) for frame in frames["duplicate_frames"][:5])
            duplicate_text = f"{frames['duplicate_count']} extra record(s), frame {listed}"
        if frames["coverage_start_frame"] is None:
            print("  continuity: n/a")
        else:
            if frames["gaps"]["frame_count"]:
                continuity_label = "gapped"
            elif frames["duplicate_frames"] or frames["restarts"]:
                continuity_label = "overlapping/restarted"
            else:
                continuity_label = "contiguous"
            print(
                f"  continuity: {continuity_label} "
                f"| gaps: {gap_text} | duplicates: {duplicate_text} "
                f"| restarts: {frames['restarts']}"
            )
        totals = frames["totals"]
        if totals is None:
            print(
                "  totals: not reported (duplicate, restarted or unusable intervals)"
            )
        else:
            if not frames["complete"]:
                label = "partial coverage; lower bound"
            elif frames["covers_from_frame_1"]:
                label = "complete"
            else:
                label = (
                    f"complete for frames {frames['coverage_start_frame']}-"
                    f"{frames['coverage_end_frame']}; earlier frames not covered"
                )
            print(f"  totals ({label}):")
            print(
                f"    draws       recorded {totals['draws']:,} | "
                f"executed on host {totals['drawn']:,}"
            )
            print(
                f"    dispatches  recorded {totals['dispatches']:,} | "
                f"executed on host {totals['dispatched']:,}"
            )
            if frames["unexecuted_draws"] is not None:
                qualifier = (
                    "independently sampled counters; not a dropped-draw count"
                )
                if frames["unexecuted_draws"] or frames["unexecuted_dispatches"]:
                    qualifier += "; may reflect interval-boundary skew"
                print(
                    "  counter difference: draws "
                    f"{frames['unexecuted_draws']:+,} | dispatches "
                    f"{frames['unexecuted_dispatches']:+,} ({qualifier})"
                )
            else:
                print(
                    "  counter difference: n/a (reported only for a complete "
                    "capture starting at frame 1)"
                )
        if frames["first_frame"] is None:
            print("  record frames: unavailable")
        else:
            print(
                f"  record frames: {frames['first_frame']} to "
                f"{frames['last_frame']} | interval log times: "
                f"{frames['first_timestamp']} to {frames['last_timestamp']}"
            )

    details = result["drop_reasons"]
    print()
    print("Dropped-pipeline detail (diagnostics builds only)")
    if not details["line_count"]:
        dropped = host["stats"]["dropped_per_frame"]
        indirect = host["stats"]["indirect_per_frame"]
        reporting = host["field_counts"]["dropped_per_frame"]
        where = (
            "every sample"
            if reporting == host["count"]
            else f"{reporting} of {host['count']} samples that report it"
        )
        if dropped:
            if dropped["max"] == 0:
                message = (
                    "no detail lines; the rounded host counter reports 0 "
                    f"dropped/frame in {where}"
                )
                if indirect and indirect["max"] > 0:
                    message += (
                        ", but reports up to "
                        f"{_format_number(indirect['max'], 0)} dropped indirect/frame"
                    )
                print("  " + message)
            else:
                print("  MISSING: no detail lines, but sampled dropped/frame is non-zero")
        else:
            print("  n/a: no sampled dropped/frame counter")
    else:
        print(
            f"  detail lines: {details['line_count']} | distinct reasons: "
            f"{len(details['reasons'])}"
        )
        for item in details["reasons"][:max_reasons]:
            print(
                f"  - {item['reason']} | lines {item['lines']} | "
                f"max {_format_number(item['max_per_frame'], 1)}/frame | "
                f"mean {_format_number(item['mean_per_frame'], 1)}/frame"
            )
        hidden = len(details["reasons"]) - max_reasons
        if hidden > 0:
            print(f"  ... {hidden} more reason(s) omitted (use --max-drop-reasons)")
        reconciliation = details["reconciliation"]
        print(
            f"  rounded-counter reconciliation: "
            f"{reconciliation['periods_checked']} period(s) checked, "
            f"{len(reconciliation['mismatches'])} mismatch(es)"
        )

    indirect_drops = result["indirect_drops"]
    if indirect_drops["count"]:
        print()
        print(
            f"Dropped indirect executions ({indirect_drops['count']} "
            "first-per-signature line(s))"
        )
        for example in indirect_drops["examples"]:
            print(f"  - {example['timestamp']}  {example['detail']}")

    warnings = result["drop_warnings"]
    if warnings:
        print()
        print(f"Other drop-related warnings ({sum(item['count'] for item in warnings)})")
        for item in warnings[:5]:
            print(f"  - {item['message']} (x{item['count']})")

    print()
    print("Data quality")
    if result["missing"]:
        for item in result["missing"]:
            print(f"  MISSING: {item}")
    else:
        print("  missing: none")
    for item in result["notes"]:
        print(f"  NOTE: {item}")


def _build_document(results: list[dict]) -> dict:
    return {"files": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize VIctory host fps/draw samples, frame-interval counters, "
            "and dropped-pipeline counts from a runtime log."
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
        "--max-drop-reasons",
        type=int,
        default=10,
        metavar="N",
        help="show at most N distinct dropped-pipeline reasons (default 10)",
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
            results.append(_analyze(display, data, args.encoding))
        except (LookupError, ValueError, OverflowError) as error:
            print(f"error: cannot analyze {display}: {error}", file=sys.stderr)
            failed = True

    if args.json:
        try:
            json.dump(_build_document(results), sys.stdout, indent=2, allow_nan=False)
        except ValueError as error:
            print(f"error: could not serialize report: {error}", file=sys.stderr)
            return 1
        sys.stdout.write("\n")
    else:
        for index, result in enumerate(results):
            if index:
                print()
            _print_text(result, max(0, args.max_drop_reasons))

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
