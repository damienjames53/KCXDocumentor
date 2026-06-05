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
import os
import re
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
DEFAULT_WHISPER_CLI = os.environ.get("KCXDOC_WHISPER_CLI", "").strip() or None
DEFAULT_WHISPER_MODEL = Path(
    os.environ.get("KCXDOC_WHISPER_MODEL", "").strip()
    or REPO_ROOT / "models" / "whisper" / "ggml-base.en.bin"
)
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
SOURCE_PROFILES = {"standard", "teams-recording"}


@dataclass(frozen=True)
class Tooling:
    ffprobe: str | None
    ffmpeg: str | None
    whisper: str | None


def main() -> int:
    args = parse_args()
    source = args.recording.expanduser().resolve()
    if not source.exists() or not source.is_file():
        print(f"error: recording does not exist or is not a file: {source}", file=sys.stderr)
        return 2

    output_root = args.output_root.expanduser().resolve()
    tooling = find_tooling(disabled=args.no_media_tools, whisper_cli=args.whisper_cli)
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

    extracted_audio = maybe_extract_audio(source, session_dir, tooling, args)
    metadata = inspect_media(source, tooling, args.assume_duration_seconds)
    sidecar_transcript = read_sidecar_transcript(args.transcript)
    local_transcript = (
        None
        if sidecar_transcript
        else maybe_transcribe_audio(session_dir, extracted_audio, tooling, args)
    )
    transcript = build_transcript(
        metadata=metadata,
        sidecar_transcript=sidecar_transcript,
        local_transcript=local_transcript,
        segment_seconds=args.segment_seconds,
        target_application=args.target_application,
    )

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
            "whisper": tooling.whisper,
            "mediaToolsDisabled": args.no_media_tools,
            "localSttDisabled": args.no_local_stt,
        },
        "processing": {
            "sourceProfile": args.source_profile,
            "skipStartSeconds": effective_skip_start_seconds(args),
            "frameCropFilter": build_frame_crop_filter(args),
        },
        "outputs": {
            "mediaMetadata": "media_metadata.json",
            "transcript": "transcript.json",
            "frameScores": "frame_scores.json",
            "ocr": "ocr.json",
            "procedureTrace": "procedure_trace.json",
            "packageReadme": "package_readme.md",
        },
        "inputs": {
            "recording": str(source),
            "transcript": sidecar_transcript["path"] if sidecar_transcript else None,
            "localTranscript": local_transcript["path"] if local_transcript else None,
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
        "--source-profile",
        choices=sorted(SOURCE_PROFILES),
        default="standard",
        help="Input recording profile. Use teams-recording to crop Teams chrome from candidate frames.",
    )
    parser.add_argument(
        "--skip-start-seconds",
        type=float,
        default=None,
        help="Ignore early source seconds when selecting frame candidates. Defaults to 60 for teams-recording, otherwise 0.",
    )
    parser.add_argument(
        "--frame-crop-filter",
        default=None,
        help="Optional FFmpeg crop filter for candidate frames. Overrides the source-profile crop.",
    )
    parser.add_argument(
        "--ffmpeg-timeout-seconds",
        type=float,
        default=45.0,
        help="Per-command timeout for optional ffmpeg extraction calls.",
    )
    parser.add_argument(
        "--whisper-cli",
        default=DEFAULT_WHISPER_CLI,
        help="Path to whisper.cpp CLI. Defaults to KCXDOC_WHISPER_CLI or whisper-cli on PATH.",
    )
    parser.add_argument(
        "--whisper-model",
        type=Path,
        default=DEFAULT_WHISPER_MODEL,
        help="Path to a local whisper.cpp GGML model. Defaults to KCXDOC_WHISPER_MODEL or models/whisper/ggml-base.en.bin.",
    )
    parser.add_argument(
        "--whisper-language",
        default="en",
        help="Language code passed to whisper.cpp. Defaults to en.",
    )
    parser.add_argument(
        "--whisper-timeout-seconds",
        type=float,
        default=7200.0,
        help="Timeout for local Whisper transcription.",
    )
    parser.add_argument(
        "--no-local-stt",
        action="store_true",
        help="Skip local Whisper transcription when no sidecar transcript is provided.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing session directory with the same id.",
    )
    return parser.parse_args()


def find_tooling(disabled: bool, whisper_cli: str | None = None) -> Tooling:
    whisper = str(Path(whisper_cli).expanduser()) if whisper_cli else shutil.which("whisper-cli")
    if disabled:
        return Tooling(ffprobe=None, ffmpeg=None, whisper=whisper)
    return Tooling(ffprobe=shutil.which("ffprobe"), ffmpeg=shutil.which("ffmpeg"), whisper=whisper)


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


def read_sidecar_transcript(path: Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    transcript_path = path.expanduser().resolve()
    if not transcript_path.exists() or not transcript_path.is_file():
        raise SystemExit(f"transcript does not exist or is not a file: {transcript_path}")
    raw_text = transcript_path.read_text(encoding="utf-8").strip()
    suffix = transcript_path.suffix.lower()
    if suffix == ".json":
        parsed = parse_json_transcript(raw_text)
    elif suffix in {".vtt", ".srt"}:
        parsed = parse_caption_transcript(raw_text)
    else:
        parsed = [{"text": raw_text, "confidence": 0.78}]

    return {
        "path": str(transcript_path),
        "name": transcript_path.name,
        "format": suffix.lstrip(".") or "txt",
        "segments": [segment for segment in parsed if segment.get("text", "").strip()],
    }


def maybe_transcribe_audio(
    session_dir: Path,
    extracted_audio: dict[str, Any],
    tooling: Tooling,
    args: argparse.Namespace,
) -> dict[str, Any] | None:
    if args.no_local_stt:
        return None
    if not extracted_audio.get("created"):
        return None
    if not tooling.whisper:
        return None

    model = args.whisper_model.expanduser().resolve()
    if not model.exists() or not model.is_file():
        return {
            "path": None,
            "name": None,
            "format": "json",
            "source": "local-whisper-error",
            "error": f"Whisper model not found: {model}",
            "segments": [],
        }

    audio_path = session_dir / str(extracted_audio["path"])
    output_base = session_dir / "audio" / "whisper-transcript"
    command = [
        tooling.whisper,
        "-m",
        str(model),
        "-f",
        str(audio_path),
        "-l",
        args.whisper_language,
        "-oj",
        "-ojf",
        "-of",
        str(output_base),
        "--no-prints",
    ]
    result = run_command(command, timeout_seconds=args.whisper_timeout_seconds)
    output_path = output_base.with_suffix(".json")
    if result["returnCode"] != 0 or not output_path.exists():
        return {
            "path": str(output_path.relative_to(session_dir)),
            "name": output_path.name,
            "format": "json",
            "source": "local-whisper-error",
            "error": result["stderr"] or f"whisper-cli exited {result['returnCode']}",
            "segments": [],
        }

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "path": str(output_path.relative_to(session_dir)),
            "name": output_path.name,
            "format": "json",
            "source": "local-whisper-error",
            "error": f"whisper-cli returned invalid JSON: {exc}",
            "segments": [],
        }

    return {
        "path": str(output_path.relative_to(session_dir)),
        "name": output_path.name,
        "format": "json",
        "source": "local-whisper",
        "model": str(model),
        "language": payload.get("result", {}).get("language") or args.whisper_language,
        "error": None,
        "segments": parse_whisper_transcript(payload),
    }


def parse_whisper_transcript(payload: dict[str, Any]) -> list[dict[str, Any]]:
    segments = []
    raw_segments = payload.get("transcription")
    if not isinstance(raw_segments, list):
        return segments

    for index, item in enumerate(raw_segments):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        offsets = item.get("offsets") if isinstance(item.get("offsets"), dict) else {}
        start = milliseconds_to_seconds(offsets.get("from"))
        end = milliseconds_to_seconds(offsets.get("to"))
        segments.append(
            {
                "id": f"whisper-{index + 1:04d}",
                "text": text,
                "startSeconds": start,
                "endSeconds": end,
                "confidence": whisper_segment_confidence(item),
                "speaker": "Speaker 1",
            }
        )
    return segments


def whisper_segment_confidence(segment: dict[str, Any]) -> float:
    tokens = segment.get("tokens") if isinstance(segment.get("tokens"), list) else []
    probabilities = [
        parse_float(token.get("p"))
        for token in tokens
        if isinstance(token, dict) and not str(token.get("text", "")).startswith("[_")
    ]
    probabilities = [value for value in probabilities if value is not None]
    if not probabilities:
        return 0.74
    return round(min(1.0, max(0.0, sum(probabilities) / len(probabilities))), 3)


def milliseconds_to_seconds(value: Any) -> float | None:
    parsed = parse_float(value)
    if parsed is None:
        return None
    return parsed / 1000.0


def parse_json_transcript(raw_text: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return [{"text": raw_text, "confidence": 0.6}]

    raw_segments = payload.get("segments") if isinstance(payload, dict) else payload
    if not isinstance(raw_segments, list):
        text = payload.get("text") if isinstance(payload, dict) else None
        return [{"text": str(text or raw_text), "confidence": parse_confidence(payload.get("confidence") if isinstance(payload, dict) else None)}]

    segments = []
    for index, item in enumerate(raw_segments):
        if isinstance(item, str):
            segments.append({"text": item, "confidence": 0.78})
            continue
        if not isinstance(item, dict):
            continue
        text = item.get("text") or item.get("speakerText") or item.get("transcript") or ""
        start = parse_float(item.get("startSeconds"))
        end = parse_float(item.get("endSeconds"))
        segments.append(
            {
                "id": item.get("id") or f"sidecar-{index + 1:04d}",
                "text": str(text),
                "startSeconds": start,
                "endSeconds": end,
                "confidence": parse_confidence(item.get("confidence")),
                "speaker": item.get("speaker") or "Speaker 1",
            }
        )
    return segments


def parse_caption_transcript(raw_text: str) -> list[dict[str, Any]]:
    segments = []
    current_start: float | None = None
    current_end: float | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_start, current_end, current_lines
        text = " ".join(clean_caption_text(line) for line in current_lines if line.strip()).strip()
        if text:
            segments.append(
                {
                    "text": text,
                    "startSeconds": current_start,
                    "endSeconds": current_end,
                    "confidence": 0.78,
                }
            )
        current_start = None
        current_end = None
        current_lines = []

    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.upper() == "WEBVTT" or stripped.isdigit():
            if not stripped:
                flush()
            continue
        if "-->" in stripped:
            if current_start is not None or current_end is not None:
                flush()
            else:
                current_lines = []
            left, right = stripped.split("-->", 1)
            current_start = parse_caption_timestamp(left.strip())
            current_end = parse_caption_timestamp(right.split()[0].strip())
            continue
        current_lines.append(stripped)
    flush()
    return segments or [{"text": strip_caption_noise(raw_text), "confidence": 0.6}]


def build_transcript(
    metadata: dict[str, Any],
    sidecar_transcript: dict[str, Any] | None,
    local_transcript: dict[str, Any] | None,
    segment_seconds: float,
    target_application: str,
) -> dict[str, Any]:
    duration = metadata["durationSeconds"]
    segment_count = max(1, math.ceil(duration / max(1.0, segment_seconds)))
    transcript_source = choose_transcript_source(sidecar_transcript, local_transcript)
    source_segments = transcript_source.get("segments", []) if transcript_source else []
    if source_segments:
        segment_count = choose_source_segment_count(source_segments, segment_count)
    source_chunks = split_source_segments(source_segments, segment_count, duration, segment_seconds) if source_segments else []
    segments = []

    for index in range(segment_count):
        start = index * segment_seconds
        end = min(duration, (index + 1) * segment_seconds)
        source_chunk = source_chunks[index] if source_chunks else None
        text = source_chunk["text"] if source_chunk else placeholder_transcript_text(index, target_application)
        segment_start = source_chunk.get("startSeconds") if source_chunk and source_chunk.get("startSeconds") is not None else start
        segment_end = source_chunk.get("endSeconds") if source_chunk and source_chunk.get("endSeconds") is not None else end
        segments.append(
            {
                "id": f"tx-{index + 1:04d}",
                "startSeconds": round_positive(segment_start),
                "endSeconds": round_positive(segment_end),
                "start": format_timestamp(segment_start),
                "end": format_timestamp(segment_end),
                "speaker": source_chunk.get("speaker", "Speaker 1") if source_chunk else "Speaker 1",
                "text": text,
                "source": transcript_source["source"] if source_chunk and transcript_source else "deterministic-placeholder",
                "confidence": source_chunk["confidence"] if source_chunk else 0.0,
            }
        )

    source_transcript = (
        {
            "name": transcript_source.get("name"),
            "path": transcript_source.get("path"),
            "format": transcript_source.get("format"),
            "source": transcript_source.get("source"),
            "model": transcript_source.get("model"),
            "error": transcript_source.get("error"),
        }
        if transcript_source
        else None
    )

    return {
        "schemaVersion": 1,
        "source": transcript_source["source"] if source_segments and transcript_source else "deterministic-placeholder",
        "sourceTranscript": source_transcript,
        "language": transcript_source.get("language", "en") if transcript_source else "en",
        "durationSeconds": duration,
        "segments": segments,
    }


def choose_transcript_source(
    sidecar_transcript: dict[str, Any] | None,
    local_transcript: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if sidecar_transcript and sidecar_transcript.get("segments"):
        return {**sidecar_transcript, "source": "sidecar-transcript"}
    if local_transcript and local_transcript.get("segments"):
        return local_transcript
    return None


def split_source_segments(
    source_segments: list[dict[str, Any]],
    count: int,
    duration: float,
    segment_seconds: float,
) -> list[dict[str, Any]]:
    if not source_segments:
        return []
    if any(segment.get("startSeconds") is not None for segment in source_segments):
        return split_timed_source_segments(source_segments, count, duration, segment_seconds)

    text = " ".join(str(segment.get("text", "")).strip() for segment in source_segments)
    confidence = min((parse_confidence(segment.get("confidence")) for segment in source_segments), default=0.78)
    words = text.split()
    if not words:
        return []
    chunk_size = max(1, math.ceil(len(words) / count))
    chunks = [
        {"text": " ".join(words[i : i + chunk_size]), "confidence": confidence, "speaker": "Speaker 1"}
        for i in range(0, len(words), chunk_size)
    ]
    while len(chunks) < count:
        chunks.append({"text": "", "confidence": confidence, "speaker": "Speaker 1"})
    return chunks[:count]


def split_timed_source_segments(
    source_segments: list[dict[str, Any]],
    count: int,
    duration: float,
    segment_seconds: float,
) -> list[dict[str, Any]]:
    chunks = [
        {
            "textParts": [],
            "confidenceValues": [],
            "speaker": "Speaker 1",
            "startSeconds": index * segment_seconds,
            "endSeconds": min(duration, (index + 1) * segment_seconds),
        }
        for index in range(count)
    ]
    for segment in source_segments:
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        start = parse_float(segment.get("startSeconds"))
        end = parse_float(segment.get("endSeconds"))
        if start is None and end is None:
            continue
        anchor = start if start is not None else end
        if anchor is None:
            continue
        index = max(0, min(count - 1, int(anchor // max(1.0, segment_seconds))))
        chunk = chunks[index]
        chunk["textParts"].append(text)
        chunk["confidenceValues"].append(parse_confidence(segment.get("confidence")))
        if segment.get("speaker"):
            chunk["speaker"] = segment.get("speaker")
        if start is not None:
            chunk["startSeconds"] = min(chunk["startSeconds"], start)
        if end is not None:
            chunk["endSeconds"] = max(chunk["endSeconds"], end)

    normalized = []
    for chunk in chunks:
        confidence_values = chunk.pop("confidenceValues")
        text_parts = chunk.pop("textParts")
        normalized.append(
            {
                **chunk,
                "text": " ".join(text_parts),
                "confidence": min(confidence_values) if confidence_values else 0.0,
            }
        )
    return normalized


def choose_source_segment_count(source_segments: list[dict[str, Any]], default_count: int) -> int:
    if default_count <= 4:
        return default_count

    timed_count = sum(1 for segment in source_segments if segment.get("startSeconds") is not None)
    if timed_count:
        return max(1, min(default_count, timed_count))

    word_count = sum(len(str(segment.get("text", "")).split()) for segment in source_segments)
    transcript_sized_count = max(1, math.ceil(word_count / 120))
    return max(1, min(default_count, transcript_sized_count))


def normalize_source_segments(source_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for segment in source_segments:
        normalized.append(
            {
                "text": str(segment.get("text", "")).strip(),
                "startSeconds": segment.get("startSeconds"),
                "endSeconds": segment.get("endSeconds"),
                "confidence": parse_confidence(segment.get("confidence")),
                "speaker": segment.get("speaker") or "Speaker 1",
            }
        )
    return normalized


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
    skip_start_seconds = effective_skip_start_seconds(args)
    planned = planned_frame_timestamps(
        duration=metadata["durationSeconds"],
        interval=args.sample_interval_seconds,
        max_frames=args.max_frames,
        start_seconds=skip_start_seconds,
    )
    candidates_dir = session_dir / "frames" / "candidates"
    crop_filter = build_frame_crop_filter(args)
    if not tooling.ffmpeg:
        return [
            {
                "id": f"frame-{index + 1:04d}",
                "timestampSeconds": timestamp,
                "timestamp": format_timestamp(timestamp),
                "path": None,
                "webPath": None,
                "created": False,
                "source": "deterministic-placeholder",
                "sourceProfile": args.source_profile,
                "cropFilter": crop_filter,
                "error": "ffmpeg not available",
            }
            for index, timestamp in enumerate(planned)
        ]

    extracted: list[dict[str, Any]] = []
    for index, timestamp in enumerate(planned):
        frame_id = f"frame-{index + 1:04d}"
        path = candidates_dir / f"{frame_id}.png"
        cmd = [
            tooling.ffmpeg,
            "-y",
            "-ss",
            str(timestamp),
            "-i",
            str(source),
            "-frames:v",
            "1",
        ]
        if crop_filter:
            cmd.extend(["-vf", crop_filter])
        cmd.extend(
            [
            "-hide_banner",
            "-loglevel",
            "error",
            str(path),
            ]
        )
        command = run_command(cmd, timeout_seconds=args.ffmpeg_timeout_seconds)
        created = command["returnCode"] == 0 and path.exists()
        extracted.append(
            {
                "id": frame_id,
                "timestampSeconds": timestamp,
                "timestamp": format_timestamp(timestamp),
                "path": str(path.relative_to(session_dir)) if created else None,
                "webPath": str(path.relative_to(session_dir)).replace("\\", "/") if created else None,
                "created": created,
                "source": "ffmpeg" if created else "deterministic-placeholder",
                "sourceProfile": args.source_profile,
                "cropFilter": crop_filter,
                "error": None if created else command["stderr"] or f"ffmpeg exited {command['returnCode']}",
            }
        )
    return extracted


def effective_skip_start_seconds(args: argparse.Namespace) -> float:
    if args.skip_start_seconds is not None:
        return round_positive(args.skip_start_seconds)
    if args.source_profile == "teams-recording":
        return 60.0
    return 0.0


def build_frame_crop_filter(args: argparse.Namespace) -> str | None:
    if args.frame_crop_filter:
        return args.frame_crop_filter
    if args.source_profile == "teams-recording":
        return "crop=iw*0.872:ih*0.874:0:ih*0.063"
    return None


def planned_frame_timestamps(duration: float, interval: float, max_frames: int, start_seconds: float = 0.0) -> list[float]:
    interval = max(1.0, interval)
    max_frames = max(1, max_frames)
    duration = max(1.0, duration)
    timestamps = []
    current = min(max(2.0, start_seconds), duration / 2 if start_seconds >= duration else duration)
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
                        "webPath": frame.get("webPath") or frame["path"],
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
            "transcript": transcript.get("sourceTranscript"),
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


def parse_confidence(value: Any) -> float:
    if isinstance(value, dict):
        value = value.get("overall") or value.get("transcript")
    parsed = parse_float(value)
    if parsed is None:
        return 0.78
    return min(1.0, max(0.0, parsed))


def parse_caption_timestamp(value: str) -> float | None:
    normalized = value.replace(",", ".")
    parts = normalized.split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return (int(hours) * 3600) + (int(minutes) * 60) + float(seconds)
        if len(parts) == 2:
            minutes, seconds = parts
            return (int(minutes) * 60) + float(seconds)
    except ValueError:
        return None
    return None


def strip_caption_noise(raw_text: str) -> str:
    cleaned = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.upper() == "WEBVTT" or stripped.isdigit() or "-->" in stripped:
            continue
        if is_caption_cue_identifier(stripped):
            continue
        cleaned.append(clean_caption_text(stripped))
    return " ".join(cleaned)


def clean_caption_text(text: str) -> str:
    without_voice_tags = re.sub(r"</?v(?:\s+[^>]*)?>", "", text)
    without_tags = re.sub(r"<[^>]+>", "", without_voice_tags)
    return " ".join(without_tags.split())


def is_caption_cue_identifier(text: str) -> bool:
    if " " in text or "-->" in text:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9._:-]+(?:/[A-Za-z0-9._:-]+)?", text))


def parse_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


if __name__ == "__main__":
    sys.exit(main())
