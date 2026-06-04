#!/usr/bin/env python3
"""Create a prototype processing session from a workstation recording.

The lane is intentionally useful before the full media/STT stack exists:
it records source metadata, extracts audio/frames when ffprobe/ffmpeg are
available, and always emits deterministic JSON artifacts for downstream
guide-generation prototyping.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "samples" / "processed"
DEFAULT_ASSUMED_DURATION_SECONDS = 3600.0
ACTION_WORDS = {
    "click": "click",
    "select": "select",
    "choose": "select",
    "open": "open",
    "enter": "form-entry",
    "type": "form-entry",
    "save": "save",
    "submit": "submit",
    "review": "review",
    "confirm": "confirm",
    "search": "search",
}


@dataclass(frozen=True)
class Tooling:
    ffprobe: str | None
    ffmpeg: str | None


def main() -> int:
    args = parse_args()
    source = args.recording.expanduser().resolve()
    if not source.exists() or not source.is_file():
        print(f"error: recording does not exist or is not a file: {source}", file=sys.stderr)
        return 2

    output_root = args.output_root.expanduser().resolve()
    tooling = find_tooling(disabled=args.no_media_tools)
    session_id = args.session_id or build_session_id(source)
    session_dir = output_root / session_id

    if session_dir.exists():
        if not args.force:
            print(
                f"error: session already exists: {session_dir}\n"
                "       pass --force to replace it or --session-id to choose another id",
                file=sys.stderr,
            )
            return 2
        shutil.rmtree(session_dir)

    create_session_dirs(session_dir)

    metadata = inspect_media(source, tooling, args.assume_duration_seconds)
    sidecar_text = read_sidecar_transcript(args.transcript)
    transcript = build_transcript(
        metadata=metadata,
        sidecar_text=sidecar_text,
        segment_seconds=args.segment_seconds,
        target_application=args.target_application,
    )

    extracted_audio = maybe_extract_audio(source, session_dir, tooling, args)
    frames = maybe_extract_frames(source, session_dir, tooling, metadata, args)
    frame_scores = score_frames(frames, metadata, args.sample_interval_seconds)
    ocr = build_placeholder_ocr(frame_scores, args.target_application)
    procedure_trace = build_procedure_trace(
        source=source,
        session_id=session_id,
        metadata=metadata,
        transcript=transcript,
        frame_scores=frame_scores,
        ocr=ocr,
        target_application=args.target_application,
        extracted_audio=extracted_audio,
    )

    manifest = {
        "schemaVersion": 1,
        "createdUtc": utc_now(),
        "sessionId": session_id,
        "sourceFile": str(source),
        "sessionDir": str(session_dir),
        "tools": {
            "ffprobe": tooling.ffprobe,
            "ffmpeg": tooling.ffmpeg,
            "mediaToolsDisabled": args.no_media_tools,
        },
        "outputs": {
            "mediaMetadata": "media_metadata.json",
            "transcript": "transcript.json",
            "frameScores": "frame_scores.json",
            "ocr": "ocr.json",
            "procedureTrace": "procedure_trace.json",
            "packageReadme": "package_readme.md",
        },
    }

    write_json(session_dir / "manifest.json", manifest)
    write_json(session_dir / "media_metadata.json", metadata)
    write_json(session_dir / "transcript.json", transcript)
    write_json(session_dir / "frame_scores.json", frame_scores)
    write_json(session_dir / "ocr.json", ocr)
    write_json(session_dir / "procedure_trace.json", procedure_trace)
    write_package_readme(session_dir, manifest, metadata, transcript, frame_scores)

    print(f"KCXDocumentor processing session created: {session_dir}")
    print(f"  session id: {session_id}")
    print(f"  duration: {metadata['durationSeconds']} seconds")
    print(f"  transcript segments: {len(transcript['segments'])}")
    print(f"  frame candidates: {len(frame_scores['frames'])}")
    print("  trace: procedure_trace.json")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a deterministic prototype processing bundle from a recording.",
    )
    parser.add_argument("recording", type=Path, help="Path to a screen recording file.")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Root folder for processed sessions. Defaults to samples/processed.",
    )
    parser.add_argument("--session-id", help="Explicit session id. Defaults to a stable source hash.")
    parser.add_argument(
        "--target-application",
        default="Unknown Application",
        help="Application being documented. Used in placeholder transcript/OCR.",
    )
    parser.add_argument(
        "--transcript",
        type=Path,
        help="Optional plain-text transcript to segment instead of generated placeholders.",
    )
    parser.add_argument(
        "--segment-seconds",
        type=float,
        default=60.0,
        help="Seconds per prototype transcript/procedure segment.",
    )
    parser.add_argument(
        "--sample-interval-seconds",
        type=float,
        default=30.0,
        help="Seconds between prototype frame candidates.",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=120,
        help="Maximum frame candidates to emit or extract.",
    )
    parser.add_argument(
        "--assume-duration-seconds",
        type=float,
        default=DEFAULT_ASSUMED_DURATION_SECONDS,
        help="Duration used when ffprobe cannot determine media length.",
    )
    parser.add_argument(
        "--no-media-tools",
        action="store_true",
        help="Skip ffprobe/ffmpeg calls and emit metadata/frame placeholders only.",
    )
    parser.add_argument(
        "--ffmpeg-timeout-seconds",
        type=float,
        default=45.0,
        help="Per-command timeout for optional ffmpeg extraction calls.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing session directory with the same id.",
    )
    return parser.parse_args()


def find_tooling(disabled: bool) -> Tooling:
    if disabled:
        return Tooling(ffprobe=None, ffmpeg=None)
    return Tooling(ffprobe=shutil.which("ffprobe"), ffmpeg=shutil.which("ffmpeg"))


def build_session_id(source: Path) -> str:
    stat = source.stat()
    seed = f"{source}|{stat.st_size}|{int(stat.st_mtime)}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"{slugify(source.stem)}-{digest}"


def slugify(value: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "-" for char in value)
    slug = "-".join(part for part in slug.split("-") if part)
    return slug[:48] or "recording"


def create_session_dirs(session_dir: Path) -> None:
    for child in [
        session_dir,
        session_dir / "audio",
        session_dir / "frames" / "candidates",
        session_dir / "frames" / "selected",
    ]:
        child.mkdir(parents=True, exist_ok=True)


def inspect_media(source: Path, tooling: Tooling, fallback_duration: float) -> dict[str, Any]:
    base = {
        "schemaVersion": 1,
        "sourceFile": str(source),
        "sourceName": source.name,
        "sourceBytes": source.stat().st_size,
        "durationSeconds": round_positive(fallback_duration),
        "durationSource": "assumed",
        "container": source.suffix.lower().lstrip(".") or "unknown",
        "streams": [],
        "probeAvailable": bool(tooling.ffprobe),
        "probeError": None,
    }

    if not tooling.ffprobe:
        return base

    cmd = [
        tooling.ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(source),
    ]
    result = run_command(cmd, timeout_seconds=30)
    if result["returnCode"] != 0:
        base["probeError"] = result["stderr"] or f"ffprobe exited {result['returnCode']}"
        return base

    try:
        probed = json.loads(result["stdout"])
    except json.JSONDecodeError as exc:
        base["probeError"] = f"ffprobe returned invalid JSON: {exc}"
        return base

    duration = parse_float(probed.get("format", {}).get("duration"))
    if duration and duration > 0:
        base["durationSeconds"] = round_positive(duration)
        base["durationSource"] = "ffprobe"

    base["container"] = probed.get("format", {}).get("format_name") or base["container"]
    base["bitRate"] = parse_int(probed.get("format", {}).get("bit_rate"))
    base["streams"] = [summarize_stream(stream) for stream in probed.get("streams", [])]
    return base


def summarize_stream(stream: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": stream.get("index"),
        "type": stream.get("codec_type"),
        "codec": stream.get("codec_name"),
        "width": stream.get("width"),
        "height": stream.get("height"),
        "durationSeconds": parse_float(stream.get("duration")),
        "frameRate": stream.get("avg_frame_rate"),
        "sampleRate": parse_int(stream.get("sample_rate")),
        "channels": stream.get("channels"),
    }


def read_sidecar_transcript(path: Path | None) -> str | None:
    if not path:
        return None
    transcript_path = path.expanduser().resolve()
    if not transcript_path.exists() or not transcript_path.is_file():
        raise SystemExit(f"transcript does not exist or is not a file: {transcript_path}")
    return transcript_path.read_text(encoding="utf-8").strip()


def build_transcript(
    metadata: dict[str, Any],
    sidecar_text: str | None,
    segment_seconds: float,
    target_application: str,
) -> dict[str, Any]:
    duration = metadata["durationSeconds"]
    segment_count = max(1, math.ceil(duration / max(1.0, segment_seconds)))
    sidecar_chunks = split_text(sidecar_text, segment_count) if sidecar_text else []
    segments = []

    for index in range(segment_count):
        start = index * segment_seconds
        end = min(duration, (index + 1) * segment_seconds)
        text = (
            sidecar_chunks[index]
            if sidecar_chunks
            else placeholder_transcript_text(index, target_application)
        )
        segments.append(
            {
                "id": f"tx-{index + 1:04d}",
                "startSeconds": round_positive(start),
                "endSeconds": round_positive(end),
                "start": format_timestamp(start),
                "end": format_timestamp(end),
                "speaker": "Speaker 1",
                "text": text,
                "source": "sidecar-transcript" if sidecar_text else "deterministic-placeholder",
                "confidence": None if sidecar_text else 0.0,
            }
        )

    return {
        "schemaVersion": 1,
        "source": "sidecar-transcript" if sidecar_text else "deterministic-placeholder",
        "language": "en",
        "durationSeconds": duration,
        "segments": segments,
    }


def split_text(text: str | None, count: int) -> list[str]:
    if not text:
        return []
    words = text.split()
    if not words:
        return []
    chunk_size = max(1, math.ceil(len(words) / count))
    chunks = [" ".join(words[i : i + chunk_size]) for i in range(0, len(words), chunk_size)]
    while len(chunks) < count:
        chunks.append("")
    return chunks[:count]


def placeholder_transcript_text(index: int, target_application: str) -> str:
    step = index + 1
    return (
        f"Prototype narration segment {step} for {target_application}. "
        "Replace this with local speech-to-text output. The speaker is expected to "
        "describe the visible screen, the user action, and the intended result."
    )


def maybe_extract_audio(
    source: Path,
    session_dir: Path,
    tooling: Tooling,
    args: argparse.Namespace,
) -> dict[str, Any]:
    output = session_dir / "audio" / "narration.wav"
    result = {
        "path": str(output.relative_to(session_dir)),
        "created": False,
        "source": "not-created",
        "error": None,
    }
    if not tooling.ffmpeg:
        result["error"] = "ffmpeg not available"
        return result

    cmd = [
        tooling.ffmpeg,
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-hide_banner",
        "-loglevel",
        "error",
        str(output),
    ]
    command = run_command(cmd, timeout_seconds=args.ffmpeg_timeout_seconds)
    if command["returnCode"] == 0 and output.exists():
        result["created"] = True
        result["source"] = "ffmpeg"
    else:
        result["error"] = command["stderr"] or f"ffmpeg exited {command['returnCode']}"
    return result


def maybe_extract_frames(
    source: Path,
    session_dir: Path,
    tooling: Tooling,
    metadata: dict[str, Any],
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    planned = planned_frame_timestamps(
        duration=metadata["durationSeconds"],
        interval=args.sample_interval_seconds,
        max_frames=args.max_frames,
    )
    candidates_dir = session_dir / "frames" / "candidates"
    if not tooling.ffmpeg:
        return [
            {
                "id": f"frame-{index + 1:04d}",
                "timestampSeconds": timestamp,
                "timestamp": format_timestamp(timestamp),
                "path": None,
                "created": False,
                "source": "deterministic-placeholder",
                "error": "ffmpeg not available",
            }
            for index, timestamp in enumerate(planned)
        ]

    extracted: list[dict[str, Any]] = []
    for index, timestamp in enumerate(planned):
        frame_id = f"frame-{index + 1:04d}"
        path = candidates_dir / f"{frame_id}.jpg"
        cmd = [
            tooling.ffmpeg,
            "-y",
            "-ss",
            str(timestamp),
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            "-hide_banner",
            "-loglevel",
            "error",
            str(path),
        ]
        command = run_command(cmd, timeout_seconds=args.ffmpeg_timeout_seconds)
        created = command["returnCode"] == 0 and path.exists()
        extracted.append(
            {
                "id": frame_id,
                "timestampSeconds": timestamp,
                "timestamp": format_timestamp(timestamp),
                "path": str(path.relative_to(session_dir)) if created else None,
                "created": created,
                "source": "ffmpeg" if created else "deterministic-placeholder",
                "error": None if created else command["stderr"] or f"ffmpeg exited {command['returnCode']}",
            }
        )
    return extracted


def planned_frame_timestamps(duration: float, interval: float, max_frames: int) -> list[float]:
    interval = max(1.0, interval)
    max_frames = max(1, max_frames)
    duration = max(1.0, duration)
    timestamps = []
    current = min(2.0, duration / 2)
    while current < duration and len(timestamps) < max_frames:
        timestamps.append(round_positive(current))
        current += interval
    if not timestamps:
        timestamps.append(0.0)
    return timestamps


def score_frames(
    frames: list[dict[str, Any]],
    metadata: dict[str, Any],
    sample_interval: float,
) -> dict[str, Any]:
    scored = []
    duration = max(1.0, metadata["durationSeconds"])
    for index, frame in enumerate(frames):
        timestamp = frame["timestampSeconds"]
        position = min(1.0, timestamp / duration)
        cadence_bonus = 0.05 if index % 2 == 0 else 0.0
        score = round(0.55 + cadence_bonus + (0.15 * (1.0 - abs(0.5 - position))), 3)
        scored.append(
            {
                **frame,
                "score": score,
                "qualitySignals": {
                    "createdImage": frame["created"],
                    "sampleIntervalSeconds": sample_interval,
                    "dedupeState": "not-evaluated-in-prototype",
                    "blurState": "not-evaluated-in-prototype",
                },
                "selectionReason": (
                    "Extracted at regular interval for prototype review."
                    if frame["created"]
                    else "Virtual candidate retained so downstream trace shape is stable."
                ),
            }
        )
    return {
        "schemaVersion": 1,
        "source": "ffmpeg-interval-extract" if any(frame["created"] for frame in frames) else "deterministic-placeholder",
        "frames": scored,
    }


def build_placeholder_ocr(frame_scores: dict[str, Any], target_application: str) -> dict[str, Any]:
    frames = []
    for frame in frame_scores["frames"]:
        frames.append(
            {
                "frameId": frame["id"],
                "timestampSeconds": frame["timestampSeconds"],
                "timestamp": frame["timestamp"],
                "source": "prototype-placeholder",
                "textBlocks": [
                    {
                        "text": target_application,
                        "confidence": 0.0,
                        "bounds": None,
                    },
                    {
                        "text": "Visible UI text pending local OCR",
                        "confidence": 0.0,
                        "bounds": None,
                    },
                ],
            }
        )
    return {"schemaVersion": 1, "source": "prototype-placeholder", "frames": frames}


def build_procedure_trace(
    source: Path,
    session_id: str,
    metadata: dict[str, Any],
    transcript: dict[str, Any],
    frame_scores: dict[str, Any],
    ocr: dict[str, Any],
    target_application: str,
    extracted_audio: dict[str, Any],
) -> dict[str, Any]:
    frame_lookup = frame_scores["frames"]
    ocr_lookup = {frame["frameId"]: frame for frame in ocr["frames"]}
    segments = []

    for index, segment in enumerate(transcript["segments"]):
        candidate_frames = nearest_frames(
            frame_lookup,
            start=segment["startSeconds"],
            end=segment["endSeconds"],
            limit=3,
        )
        visible_text = sorted(
            {
                block["text"]
                for frame in candidate_frames
                for block in ocr_lookup.get(frame["id"], {}).get("textBlocks", [])
                if block.get("text")
            }
        )
        segments.append(
            {
                "id": f"seg-{index + 1:04d}",
                "start": segment["start"],
                "end": segment["end"],
                "startSeconds": segment["startSeconds"],
                "endSeconds": segment["endSeconds"],
                "speakerText": segment["text"],
                "visibleUiText": visible_text,
                "actionHints": infer_action_hints(segment["text"]),
                "candidateImages": [
                    {
                        "frameId": frame["id"],
                        "path": frame["path"],
                        "timestamp": frame["timestamp"],
                        "timestampSeconds": frame["timestampSeconds"],
                        "score": frame["score"],
                        "confidence": frame["score"] if frame["created"] else 0.25,
                        "created": frame["created"],
                        "reason": frame["selectionReason"],
                        "reviewStatus": "pending",
                    }
                    for frame in candidate_frames
                ],
                "confidence": build_segment_confidence(segment, candidate_frames, visible_text),
                "notes": [
                    "Prototype segment generated before local STT/OCR are wired in."
                    if segment["source"] == "deterministic-placeholder"
                    else "Segment derived from sidecar transcript."
                ],
            }
        )

    return {
        "schemaVersion": 1,
        "sessionId": session_id,
        "recording": {
            "sourceFile": str(source),
            "sourceName": source.name,
            "durationSeconds": metadata["durationSeconds"],
            "targetApplication": target_application,
            "captureMode": "imported-recording",
            "audio": extracted_audio,
        },
        "segments": segments,
        "downstreamUse": {
            "intendedConsumer": "AI guide draft generator",
            "tokenStrategy": "Send trace JSON plus only selected candidate images, not source video.",
            "prototypeLimitations": [
                "Transcript may be placeholder text unless --transcript is provided.",
                "OCR is placeholder-only in this lane.",
                "Frame scoring is deterministic interval scoring, not CV-based ranking yet.",
            ],
        },
    }


def build_segment_confidence(
    segment: dict[str, Any],
    candidate_frames: list[dict[str, Any]],
    visible_text: list[str],
) -> dict[str, Any]:
    transcript_confidence = segment["confidence"] if segment["confidence"] is not None else 0.25
    frame_confidence = max((frame["score"] if frame["created"] else 0.25 for frame in candidate_frames), default=0.0)
    ocr_confidence = 0.25 if visible_text else 0.0
    overall = round((transcript_confidence * 0.5) + (ocr_confidence * 0.25) + (frame_confidence * 0.25), 3)
    reasons = []
    if transcript_confidence < 0.7:
        reasons.append("Transcript confidence is below publication threshold.")
    if ocr_confidence < 0.7:
        reasons.append("OCR confidence is below publication threshold or placeholder-only.")
    if frame_confidence < 0.7:
        reasons.append("Frame selection confidence is below publication threshold.")
    return {
        "transcript": transcript_confidence,
        "ocr": ocr_confidence,
        "frameSelection": frame_confidence,
        "overall": overall,
        "needsHumanReview": overall < 0.75,
        "reasons": reasons,
    }


def nearest_frames(
    frames: list[dict[str, Any]],
    start: float,
    end: float,
    limit: int,
) -> list[dict[str, Any]]:
    midpoint = (start + end) / 2
    in_range = [frame for frame in frames if start <= frame["timestampSeconds"] <= end]
    candidates = in_range or frames
    return sorted(
        candidates,
        key=lambda frame: (abs(frame["timestampSeconds"] - midpoint), -frame["score"], frame["id"]),
    )[:limit]


def infer_action_hints(text: str) -> list[str]:
    lowered = text.lower()
    hints = []
    for word, hint in ACTION_WORDS.items():
        if word in lowered and hint not in hints:
            hints.append(hint)
    return hints or ["explain"]


def write_package_readme(
    session_dir: Path,
    manifest: dict[str, Any],
    metadata: dict[str, Any],
    transcript: dict[str, Any],
    frame_scores: dict[str, Any],
) -> None:
    content = f"""# KCXDocumentor Processing Session

- Session id: `{manifest['sessionId']}`
- Source: `{manifest['sourceFile']}`
- Duration: `{metadata['durationSeconds']}` seconds
- Transcript segments: `{len(transcript['segments'])}`
- Frame candidates: `{len(frame_scores['frames'])}`

Primary downstream file: `procedure_trace.json`

This is a prototype processing bundle. When local media tooling is unavailable,
the JSON files preserve the same shape with deterministic placeholders so guide
generation, DOCX rendering, and QA work can proceed independently.
"""
    (session_dir / "package_readme.md").write_text(content, encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_command(cmd: list[str], timeout_seconds: float) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "returnCode": 124,
            "stdout": exc.stdout or "",
            "stderr": f"command timed out after {timeout_seconds} seconds",
        }
    return {
        "returnCode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr.strip(),
    }


def format_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    whole = int(seconds)
    millis = int(round((seconds - whole) * 1000))
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    secs = whole % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def round_positive(value: float) -> float:
    return round(max(0.0, float(value)), 3)


def parse_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


if __name__ == "__main__":
    sys.exit(main())
