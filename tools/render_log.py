#!/usr/bin/env python3
"""Summarize VIctory host performance samples from a runtime log.

Reads a VIctory runtime log (UTF-8 or PowerShell UTF-16) and prints the
sampled ``victory_gpu::host`` performance lines, the exact interval counters
from ``victory_gpu::queue`` "frame presented" lines, and dropped-pipeline
counts.  Sampled values stay labelled as samples; a section with no evidence
is reported as missing instead of being shown as zero.

Observed baseline formats (crates/victory-gpu/src/host.rs and queue.rs):

    2026-11-24T04:19:45.393287Z  INFO victory_gpu::host: 13.5 fps, 73.9 ms/frame (0.1 preparing: copies 0.1 ms 0.3 MB, textures 0.0 ms 0.0 MB; 46.6 on the GPU; 0.0 copying back 0.0 MB), 3 draws/frame, dropped 0 without a host pipeline (0 being made) and 0 indirect
    2026-11-24T04:20:49.521064Z  INFO victory_gpu::queue: frame presented (since the last line: draws and dispatches, and those run on the host) frame=512 draws=1536 drawn=1536 dispatches=256 dispatched=256
    2026-11-24T04:24:25.123456Z  INFO victory_gpu::host: dropped 1.5/frame without a host pipeline: no pipeline set

The last form is written only by diagnostics builds.  Standard library only.
"""

from __future__ import annotations

import argparse
import codecs
import json
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
    r"(?P<ms>\d+(?:\.\d+)?)\s+ms/frame"
)
HOST_DRAWS_RE = re.compile(r"(?P<draws>\d+(?:\.\d+)?)\s+draws/frame")
HOST_DROPPED_RE = re.compile(
    r"dropped\s+(?P<dropped>\d+(?:\.\d+)?)\s+without\s+a\s+host\s+pipeline"
    r"\s*\(\s*(?P<making>\d+)\s+being\s+made\s*\)"
)
HOST_INDIRECT_RE = re.compile(r"and\s+(?P<indirect>\d+(?:\.\d+)?)\s+indirect")
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
    "indirect_per_frame": "indirect/frame",
}
QUEUE_KEYS = ("frame", "draws", "drawn", "dispatches", "dispatched")


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


def _parse_timestamp(value: str) -> datetime | None:
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _parse_host(rest: str) -> dict:
    sample: dict = {}

    match = HOST_FPS_RE.search(rest)
    if match:
        sample["fps"] = float(match.group("fps"))
        sample["ms_per_frame"] = float(match.group("ms"))

    match = HOST_DRAWS_RE.search(rest)
    if match:
        sample["draws_per_frame"] = float(match.group("draws"))

    match = HOST_DROPPED_RE.search(rest)
    if match:
        sample["dropped_per_frame"] = float(match.group("dropped"))
        sample["being_made"] = int(match.group("making"))

    match = HOST_INDIRECT_RE.search(rest)
    if match:
        sample["indirect_per_frame"] = float(match.group("indirect"))

    return sample


def _parse_queue(rest: str) -> dict:
    fields: dict = {}
    for key in QUEUE_KEYS:
        match = re.search(r"(?<![A-Za-z0-9_])" + key + r"=(\d+)", rest)
        if match:
            fields[key] = int(match.group(1))
    return fields


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
    deltas = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
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
    return ", ".join(parts)


def _stat_line(label: str, values: dict | None, digits: int = 2) -> str:
    if not values:
        return f"  {label:<20} missing"
    return (
        f"  {label:<20} min {_format_number(values['min'], digits)}"
        f"  max {_format_number(values['max'], digits)}"
        f"  mean {_format_number(values['mean'], digits)}"
        f"  median {_format_number(values['median'], digits)}"
    )


def _analyze(path: str, data: bytes, forced_encoding: str | None) -> dict:
    text, encoding, replacements = _decode_log(data, forced_encoding)
    lines = _split_lines(text)

    host_samples: list[dict] = []
    queue_lines: list[dict] = []
    drop_details: list[dict] = []
    drop_warnings: dict[str, dict] = {}
    unparsed: list[str] = []
    timestamps: list[datetime] = []
    timestamp_texts: list[str] = []
    host_candidates = 0
    queue_candidates = 0
    incomplete_queue = 0

    for raw_line in lines:
        line = _strip_ansi(raw_line)
        if not line.strip():
            continue

        match = LINE_RE.match(line)
        if not match:
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
            detail = DROP_DETAIL_RE.match(rest)
            if detail:
                drop_details.append(
                    {
                        "timestamp": ts_text,
                        "rate": float(detail.group("rate")),
                        "reason": detail.group("reason").strip() or "(no reason)",
                    }
                )
                continue

            if HOST_FPS_RE.search(rest):
                host_candidates += 1
                sample = _parse_host(rest)
                if "fps" in sample and "ms_per_frame" in sample:
                    sample["timestamp"] = ts_text
                    sample["_time"] = timestamp
                    host_samples.append(sample)
                else:
                    unparsed.append(line)
                continue

        elif target == "victory_gpu::queue" and "frame presented" in rest:
            queue_candidates += 1
            counters = _parse_queue(rest)
            if all(key in counters for key in QUEUE_KEYS):
                counters["timestamp"] = ts_text
                counters["_time"] = timestamp
                queue_lines.append(counters)
            else:
                incomplete_queue += 1
                unparsed.append(line)
            continue

        if level in ("WARN", "ERROR") and DROP_WORD_RE.search(rest):
            signature = re.sub(r"0x[0-9a-fA-F]+", "0x...", rest)
            signature = re.sub(r"\b\d+\b", "N", signature)
            entry = drop_warnings.setdefault(
                signature, {"message": rest, "count": 0}
            )
            entry["count"] += 1

    # Keep the internal datetime out of the JSON/text payloads.
    host_times = []
    for sample in host_samples:
        when = sample.pop("_time", None)
        if when is not None:
            host_times.append(when)
    for line in queue_lines:
        line.pop("_time", None)

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

    frame_sums = {
        key: sum(line[key] for line in queue_lines)
        for key in ("draws", "drawn", "dispatches", "dispatched")
    }
    frames = [line["frame"] for line in queue_lines]

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

    if not queue_lines:
        missing.append(
            "no victory_gpu::queue 'frame presented' lines; exact interval "
            "draw/dispatch counts are unavailable"
        )
    elif incomplete_queue:
        missing.append(
            f"{incomplete_queue} 'frame presented' line(s) lacked one or more counters"
        )

    if host_samples and field_counts["dropped_per_frame"]:
        dropped_stats = stats["dropped_per_frame"]
        if dropped_stats and dropped_stats["max"] > 0 and not drop_details:
            missing.append(
                "host samples report dropped frames, but no diagnostic "
                "drop-reason lines are present"
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
    if queue_candidates != len(queue_lines) and queue_candidates:
        notes.append(
            f"parsed {len(queue_lines)} of {queue_candidates} frame-presented candidates"
        )

    first_ts = timestamps[0] if timestamps else None
    last_ts = timestamps[-1] if timestamps else None
    span_seconds = (
        (last_ts - first_ts).total_seconds()
        if first_ts is not None and last_ts is not None
        else None
    )

    return {
        "path": path,
        "bytes": len(data),
        "lines": len(lines),
        "encoding": encoding,
        "replacement_characters": replacements,
        "timestamped_lines": len(timestamps),
        "run_span": {
            "first": timestamp_texts[0] if timestamp_texts else None,
            "last": timestamp_texts[-1] if timestamp_texts else None,
            "seconds": span_seconds,
        },
        "host_samples": {
            "count": len(host_samples),
            "first": host_samples[0] if host_samples else None,
            "last": host_samples[-1] if host_samples else None,
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
            "stats": stats,
        },
        "frame_intervals": {
            "count": len(queue_lines),
            "first_frame": min(frames) if frames else None,
            "last_frame": max(frames) if frames else None,
            "first_timestamp": queue_lines[0]["timestamp"] if queue_lines else None,
            "last_timestamp": queue_lines[-1]["timestamp"] if queue_lines else None,
            "totals": frame_sums if queue_lines else None,
            "unexecuted_draws": (
                frame_sums["draws"] - frame_sums["drawn"] if queue_lines else None
            ),
            "unexecuted_dispatches": (
                frame_sums["dispatches"] - frame_sums["dispatched"]
                if queue_lines
                else None
            ),
            "incomplete_lines": incomplete_queue,
        },
        "drop_reasons": {
            "line_count": len(drop_details),
            "reasons": reason_list,
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
        print(
            f"  samples: {host['count']} | median spacing "
            f"{_format_number(spacing, 2)} s"
        )
        for field in HOST_FIELDS:
            print(
                _stat_line(
                    HOST_FIELD_LABELS[field],
                    host["stats"][field],
                    0 if field in ("draws_per_frame", "being_made") else 2,
                )
            )
        dropped = host["stats"]["dropped_per_frame"]
        if dropped:
            print(
                "  dropped/frame samples above zero: "
                f"{host['nonzero_dropped_samples']} of {host['count']}"
            )
        first = host["first"]
        last = host["last"]
        lowest = host["lowest_fps"]
        if first:
            print(f"  first sample: {first['timestamp']}  {_sample_brief(first)}")
        if lowest:
            print(f"  lowest fps:  {lowest['timestamp']}  {_sample_brief(lowest)}")
        if last:
            print(f"  last sample:  {last['timestamp']}  {_sample_brief(last)}")

    frames_section = result["frame_intervals"]
    print()
    print("Exact frame-interval counters ('frame presented'; logged at powers of two)")
    if not frames_section["count"]:
        print("  MISSING: no frame-presented lines")
    else:
        totals = frames_section["totals"]
        draws = totals["draws"]
        drawn = totals["drawn"]
        percent = (drawn / draws * 100.0) if draws else None
        print(
            f"  intervals: {frames_section['count']} | frames "
            f"{frames_section['first_frame']} to {frames_section['last_frame']}"
        )
        print(
            f"  draws issued: {draws:,} | executed on host: {drawn:,} | "
            f"issued minus executed: {draws - drawn:,}"
            + (f" ({percent:.1f}% executed)" if percent is not None else "")
        )
        print(
            f"  dispatches issued: {totals['dispatches']:,} | executed on host: "
            f"{totals['dispatched']:,} | issued minus executed: "
            f"{totals['dispatches'] - totals['dispatched']:,}"
        )
        print(
            f"  interval span: {frames_section['first_timestamp']} to "
            f"{frames_section['last_timestamp']}"
        )
        print(
            "  NOTE: these are interval sums only; frames after "
            f"{frames_section['last_frame']} are not covered."
        )

    details = result["drop_reasons"]
    print()
    print("Dropped-pipeline detail (diagnostics builds only)")
    if not details["line_count"]:
        dropped = host["stats"]["dropped_per_frame"]
        if dropped and dropped["max"] == 0:
            print(
                "  no detail lines; the rounded host counter reports 0 "
                "dropped/frame in every sample"
            )
        elif dropped:
            print("  MISSING: no detail lines, but sampled dropped/frame is non-zero")
        else:
            print("  MISSING: no detail lines and no sampled dropped/frame counter")
    else:
        print(
            f"  detail lines: {details['line_count']} | distinct reasons: "
            f"{len(details['reasons'])}"
        )
        for item in details["reasons"][:max_reasons]:
            print(
                f"  - {item['reason']} | lines {item['lines']} | "
                f"max {_format_number(item['max_per_frame'], 1)}/frame | "
                f"mean {_format_number(item['mean_per_frame'], 2)}/frame"
            )
        hidden = len(details["reasons"]) - max_reasons
        if hidden > 0:
            print(f"  ... {hidden} more reason(s) omitted (use --max-drop-reasons)")

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
            "Summarize VIctory host fps/draw samples, exact frame-interval "
            "counters, and dropped-pipeline counts from a runtime log."
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

        results.append(_analyze(display, data, args.encoding))

    if args.json:
        json.dump(_build_document(results), sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        for index, result in enumerate(results):
            if index:
                print()
            _print_text(result, max(0, args.max_drop_reasons))

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
