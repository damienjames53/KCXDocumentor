#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib import error, request


WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_PROMPT_VERSION = "guide-draft-v1"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
SONNET_4_6_INPUT_COST_PER_MILLION = 3.00
SONNET_4_6_OUTPUT_COST_PER_MILLION = 15.00
USAGE_DB_PATH = WORKSPACE / "artifacts" / "usage" / "generation_usage.sqlite3"


class AnthropicDraftError(Exception):
    def __init__(self, message: str, report: dict[str, Any]) -> None:
        super().__init__(message)
        self.report = report


def main() -> int:
    load_env_file(WORKSPACE / ".env")
    args = parse_args()
    trace_path = args.trace.resolve()
    if not trace_path.exists():
        print(f"Trace file not found: {trace_path}", file=sys.stderr)
        return 2

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace = apply_frame_review(trace, trace_path)
    if is_prototype_trace(trace):
        draft = blocked_prototype_draft(trace, args)
        draft = attach_screenshot_references(draft, trace)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(draft, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report_path = write_generation_report(args.output, draft)
        print(f"Trace is not ready for generation (prototype placeholders detected). Wrote blocked draft.")
        print(f"Wrote {args.output.resolve()}")
        print(f"Wrote {report_path.resolve()}")
        return 0
    try:
        draft = generate_with_anthropic(trace, args)
    except AnthropicDraftError as exc:
        failure_path = write_generation_failure(args.output, exc.report)
        print(f"Generation failed: {exc}", file=sys.stderr)
        print(f"Wrote {failure_path.resolve()}", file=sys.stderr)
        return 1
    draft = attach_screenshot_references(draft, trace)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(draft, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path = write_generation_report(args.output, draft)
    print(f"Wrote {args.output.resolve()}")
    print(f"Wrote {report_path.resolve()}")
    return 0


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate guide draft JSON from a procedure trace.")
    parser.add_argument("trace", type=Path, help="Path to procedure_trace.json.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=WORKSPACE / "artifacts" / "generated" / "guide_draft.json",
        help="Output guide draft JSON path.",
    )
    parser.add_argument("--use-anthropic", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--model", default=os.environ.get("KCXDOC_ANTHROPIC_MODEL", DEFAULT_MODEL), help="Anthropic model ID. Defaults to claude-sonnet-4-6.")
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=int(os.environ.get("KCXDOC_ANTHROPIC_MAX_TOKENS", os.environ.get("KCXDOC_MODEL_MAX_OUTPUT_TOKENS", "64000"))),
        help="Maximum output tokens for Anthropic generation.",
    )
    parser.add_argument("--temperature", type=float, default=0.2, help="Generation temperature for Anthropic generation.")
    parser.add_argument("--prompt-version", default=os.environ.get("KCXDOC_PROMPT_VERSION", DEFAULT_PROMPT_VERSION), help="Prompt version recorded in output metadata.")
    return parser.parse_args()


def apply_frame_review(trace: dict[str, Any], trace_path: Path) -> dict[str, Any]:
    session_dir = trace_path.parent
    review_path = session_dir / "frame_review.json"
    frame_scores_path = session_dir / "frame_scores.json"
    if not review_path.exists():
        return trace
    try:
        review = json.loads(review_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return trace

    entries = review.get("frames") if isinstance(review.get("frames"), dict) else {}
    if not entries:
        return trace

    frame_lookup = load_frame_score_lookup(frame_scores_path)
    merged = json.loads(json.dumps(trace))
    segments = merged.get("segments") if isinstance(merged.get("segments"), list) else []
    segment_lookup = {segment.get("id"): segment for segment in segments if isinstance(segment, dict)}
    seen_by_segment = {
        segment.get("id"): {
            image.get("frameId")
            for image in segment.get("candidateImages", [])
            if isinstance(image, dict) and image.get("frameId")
        }
        for segment in segments
        if isinstance(segment, dict)
    }

    for segment in segments:
        if not isinstance(segment, dict):
            continue
        for image in segment.get("candidateImages", []):
            if not isinstance(image, dict):
                continue
            entry = entries.get(image.get("frameId"))
            if isinstance(entry, dict):
                apply_review_entry_to_image(image, entry)

    for frame_id, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        assigned_segment_id = entry.get("assignedSegmentId")
        if not assigned_segment_id or assigned_segment_id not in segment_lookup:
            continue
        if frame_id in seen_by_segment.get(assigned_segment_id, set()):
            continue
        frame = frame_lookup.get(frame_id)
        if not frame:
            continue
        image = frame_score_to_candidate_image(frame)
        apply_review_entry_to_image(image, entry)
        segment_lookup[assigned_segment_id].setdefault("candidateImages", []).append(image)
        seen_by_segment.setdefault(assigned_segment_id, set()).add(frame_id)

    return merged


def load_frame_score_lookup(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    frames = payload.get("frames") if isinstance(payload.get("frames"), list) else []
    return {frame.get("id"): frame for frame in frames if isinstance(frame, dict) and frame.get("id")}


def frame_score_to_candidate_image(frame: dict[str, Any]) -> dict[str, Any]:
    quality = frame.get("qualitySignals") if isinstance(frame.get("qualitySignals"), dict) else {}
    image = {
        "frameId": frame.get("id", ""),
        "path": frame.get("path"),
        "webPath": frame.get("webPath") or frame.get("path"),
        "timestamp": frame.get("timestamp", ""),
        "timestampSeconds": frame.get("timestampSeconds", 0),
        "score": frame.get("score", 0),
        "confidence": frame.get("score", 0),
        "visualQualityScore": quality.get("qualityScore"),
        "blurState": quality.get("blurState"),
        "dedupeState": quality.get("dedupeState"),
        "duplicateOfFrameId": quality.get("duplicateOfFrameId"),
        "created": frame.get("created", False),
        "reason": frame.get("selectionReason", "Added during frame review."),
        "reviewStatus": "pending",
    }
    for key in (
        "frameEvidenceScore",
        "ocrConfidence",
        "ocrRelevanceScore",
        "ocrNonApplication",
        "ocrSupportingTool",
        "ocrClass",
        "ocrClassConfidence",
        "appOcrScore",
        "appTermHits",
        "supportingToolHits",
        "nonApplicationHits",
        "ocrTokenCount",
        "supportingToolAllowed",
        "ocrText",
        "ocrSource",
        "contentType",
        "recommendationGroup",
        "selectionDecision",
        "recommendationReason",
        "selectionReasons",
        "positiveSignals",
        "penalties",
    ):
        if key in frame:
            image[key] = frame.get(key)
    return image


def apply_review_entry_to_image(image: dict[str, Any], entry: dict[str, Any]) -> None:
    image["reviewStatus"] = entry.get("status", image.get("reviewStatus", "pending"))
    image["reviewNote"] = entry.get("note", "")
    image["assignedSegmentId"] = entry.get("assignedSegmentId")
    image["addedByReviewer"] = bool(entry.get("addedByReviewer", image.get("addedByReviewer", False)))


def attach_screenshot_references(draft: dict[str, Any], trace: dict[str, Any]) -> dict[str, Any]:
    segment_lookup = {segment.get("id"): segment for segment in trace.get("segments", []) if isinstance(segment, dict)}
    session_id = trace.get("sessionId", "")
    processed_root = WORKSPACE / "samples" / "processed" / session_id if session_id else None

    timeline_candidates = all_trace_candidates(segment_lookup)
    used_frame_ids: set[str] = set()

    def enrich_step(step: dict[str, Any], index: int, total: int) -> None:
        if step_has_screenshot(step):
            existing_frame_id = existing_step_frame_id(step)
            if existing_frame_id:
                used_frame_ids.add(existing_frame_id)
            return
        candidate = best_candidate_for_step(step, segment_lookup, timeline_candidates, index, total, used_frame_ids)
        if not candidate:
            step["needsHumanReview"] = True
            notes = step.setdefault("reviewNotes", [])
            if isinstance(notes, list):
                notes.append("No candidate screenshot could be assigned from the trace.")
            return
        screenshot = build_screenshot_reference(candidate, {"id": candidate.get("sourceSegmentId", "")}, processed_root)
        step["selectedScreenshot"] = screenshot
        step["screenshot"] = screenshot.get("path", "")
        step["screenshotRef"] = screenshot.get("frameId", "")
        step.setdefault("caption", f"Workflow screen at {screenshot.get('timestamp', 'unknown time')}")
        if screenshot.get("frameId"):
            used_frame_ids.add(str(screenshot["frameId"]))

    steps = iter_draft_steps(draft)
    for index, step in enumerate(steps):
        enrich_step(step, index, len(steps))
    return draft


def existing_step_frame_id(step: dict[str, Any]) -> str:
    selected = step.get("selectedScreenshot") or step.get("selected_screenshot")
    if isinstance(selected, dict):
        return str(selected.get("frameId") or selected.get("id") or "").strip()
    return str(step.get("screenshotRef") or "").strip()


def iter_draft_steps(draft: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    raw_steps = draft.get("steps")
    if isinstance(raw_steps, list):
        steps.extend(step for step in raw_steps if isinstance(step, dict))
    sections = draft.get("sections")
    if isinstance(sections, list):
        for section in sections:
            if isinstance(section, dict) and isinstance(section.get("steps"), list):
                steps.extend(step for step in section["steps"] if isinstance(step, dict))
    return steps


def step_has_screenshot(step: dict[str, Any]) -> bool:
    for key in ("screenshot", "selectedScreenshot", "selected_screenshot"):
        value = step.get(key)
        if isinstance(value, dict) and value.get("path"):
            return True
        if isinstance(value, str) and value.strip():
            return True
    return False


def best_candidate_for_step(
    step: dict[str, Any],
    segment_lookup: dict[str, dict[str, Any]],
    timeline_candidates: list[dict[str, Any]],
    step_index: int,
    step_count: int,
    used_frame_ids: set[str] | None = None,
) -> dict[str, Any] | None:
    used_frame_ids = used_frame_ids or set()
    segment_ids = as_string_list(
        step.get("sourceSegmentId")
        or step.get("sourceSegments")
        or step.get("segments")
        or step.get("segmentId")
    )
    candidates = []
    for segment_id in segment_ids:
        segment = segment_lookup.get(segment_id)
        if not segment:
            continue
        for image in segment.get("candidateImages", []):
            if isinstance(image, dict) and image.get("created") and image.get("path") and image.get("reviewStatus") != "rejected":
                enriched = dict(image)
                enriched["sourceSegmentId"] = segment_id
                candidates.append(enriched)
    if not candidates:
        return timeline_candidate_for_step(timeline_candidates, step_index, step_count, used_frame_ids)
    if not candidates:
        return None
    return best_non_reused_candidate(candidates, used_frame_ids)


def all_trace_candidates(segment_lookup: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    by_frame: dict[str, dict[str, Any]] = {}
    for segment in segment_lookup.values():
        for image in segment.get("candidateImages", []):
            if not isinstance(image, dict) or not image.get("created") or not image.get("path") or image.get("reviewStatus") == "rejected":
                continue
            frame_id = str(image.get("frameId") or image.get("path"))
            enriched = dict(image)
            enriched["sourceSegmentId"] = segment.get("id", "")
            existing = by_frame.get(frame_id)
            if existing is None or screenshot_sort_key(enriched) < screenshot_sort_key(existing):
                by_frame[frame_id] = enriched
    return sorted(by_frame.values(), key=lambda item: (item.get("timestampSeconds") or 0, screenshot_sort_key(item)))


def screenshot_sort_key(image: dict[str, Any]) -> tuple[int, int, int, int, int, float, float, float, float]:
    review_rank = 0 if image.get("reviewStatus") == "approved" else 1
    group = image.get("recommendationGroup") or image.get("selectionDecision")
    group_rank = 0 if group == "recommended" else 2 if group == "system-rejected" else 1
    frame_type_rank = 0 if image.get("ocrClass") == "application" else 2 if image.get("ocrNonApplication") else 1 if image.get("ocrSupportingTool") else 1
    duplicate_rank = 1 if image.get("dedupeState") == "near-duplicate" else 0
    blur_rank = 1 if image.get("blurState") == "blurry" else 0
    return (
        review_rank,
        group_rank,
        frame_type_rank,
        blur_rank,
        -float(image.get("frameEvidenceScore") or image.get("confidence") or 0),
        duplicate_rank,
        -float(image.get("visualQualityScore") or 0),
        -float(image.get("score") or 0),
        float(image.get("timestampSeconds") or 0),
    )


def best_non_reused_candidate(candidates: list[dict[str, Any]], used_frame_ids: set[str]) -> dict[str, Any] | None:
    sorted_candidates = sorted(candidates, key=screenshot_sort_key)
    unused = [
        candidate
        for candidate in sorted_candidates
        if str(candidate.get("frameId") or candidate.get("path") or "") not in used_frame_ids
    ]
    return (unused or sorted_candidates)[0] if sorted_candidates else None


def timeline_candidate_for_step(candidates: list[dict[str, Any]], step_index: int, step_count: int, used_frame_ids: set[str] | None = None) -> dict[str, Any] | None:
    if not candidates:
        return None
    used_frame_ids = used_frame_ids or set()
    available = [
        candidate
        for candidate in candidates
        if str(candidate.get("frameId") or candidate.get("path") or "") not in used_frame_ids
    ] or candidates
    if step_count <= 1:
        return available[0]
    position = step_index / max(1, step_count - 1)
    candidate_index = round(position * (len(available) - 1))
    return available[max(0, min(len(available) - 1, candidate_index))]


def build_screenshot_reference(
    image: dict[str, Any],
    segment: dict[str, Any],
    processed_root: Path | None = None,
) -> dict[str, Any]:
    path = image.get("path") or ""
    resolved_path = str((processed_root / path).resolve()) if processed_root and path else path
    reference = {
        "frameId": image.get("frameId", ""),
        "path": resolved_path,
        "relativePath": path,
        "timestamp": image.get("timestamp", ""),
        "timestampSeconds": image.get("timestampSeconds", 0),
        "score": image.get("score", 0),
        "sourceSegmentId": segment.get("id", ""),
        "reviewStatus": image.get("reviewStatus", "pending"),
    }
    for key in (
        "frameEvidenceScore",
        "visualQualityScore",
        "ocrConfidence",
        "ocrRelevanceScore",
        "ocrClass",
        "appOcrScore",
        "blurState",
        "dedupeState",
        "duplicateOfFrameId",
        "ocrSupportingTool",
        "ocrNonApplication",
        "contentType",
        "recommendationGroup",
        "selectionDecision",
        "recommendationReason",
    ):
        if key in image:
            reference[key] = image.get(key)
    return reference


def as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def generate_with_anthropic(trace: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    remote_api_base_url = os.environ.get("KCXDOC_REMOTE_API_BASE_URL", "").strip().rstrip("/")
    if not remote_api_base_url:
        raise SystemExit("KCXDOC_REMOTE_API_BASE_URL is required; AI generation must run through the Azure Function proxy.")
    return generate_with_remote_proxy(trace, args, remote_api_base_url)


def generate_with_remote_proxy(trace: dict[str, Any], args: argparse.Namespace, base_url: str) -> dict[str, Any]:
    bearer_token = os.environ.get("KCXDOC_REMOTE_API_BEARER_TOKEN", "").strip()
    if not bearer_token:
        raise SystemExit("KCXDOC_REMOTE_API_BEARER_TOKEN is required when KCXDOC_REMOTE_API_BASE_URL is configured.")

    payload = {
        "anthropic": build_anthropic_payload(trace, args),
        "metadata": {
            "sessionId": trace.get("sessionId", ""),
            "title": trace_title(trace),
            "model": args.model,
            "promptVersion": args.prompt_version,
        },
    }
    try:
        if os.environ.get("KCXDOC_REMOTE_GENERATION_MODE", "").strip().lower() == "async":
            return generate_with_remote_job(trace, args, base_url, bearer_token, payload)
        return parse_remote_generation_result(trace, args, post_remote_generation(base_url, bearer_token, payload))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        report = remote_failure_report(trace, args, exc.code, detail)
        raise AnthropicDraftError(report["errorMessage"], report) from exc
    except (TimeoutError, error.URLError, OSError) as exc:
        report = generation_failure_report(
            trace=trace,
            args=args,
            result={},
            error_message=f"Remote AI proxy request failed before a complete response was received: {exc}",
        )
        raise AnthropicDraftError(report["errorMessage"], report) from exc


def post_remote_generation(base_url: str, bearer_token: str, payload: dict[str, Any]) -> dict[str, Any]:
    req = request.Request(
        f"{base_url}/api/generate-draft",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=240) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError:
        raise
    except (TimeoutError, error.URLError, OSError):
        raise


def generate_with_remote_job(
    trace: dict[str, Any],
    args: argparse.Namespace,
    base_url: str,
    bearer_token: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    job = submit_remote_generation_job(base_url, bearer_token, payload)
    job_id = str(job.get("jobId") or "")
    if not job_id:
        report = generation_failure_report(
            trace=trace,
            args=args,
            result={},
            error_message="Remote AI proxy did not return a generation job id.",
        )
        raise AnthropicDraftError(report["errorMessage"], report)
    timeout_seconds = int(os.environ.get("KCXDOC_REMOTE_GENERATION_TIMEOUT_SECONDS", "1200") or 1200)
    poll_seconds = max(1, int(os.environ.get("KCXDOC_REMOTE_GENERATION_POLL_SECONDS", "3") or 3))
    deadline = time.monotonic() + timeout_seconds
    last_job = job
    while time.monotonic() < deadline:
        status = str(last_job.get("status") or "").lower()
        if status == "succeeded":
            return parse_remote_generation_result(trace, args, {
                "anthropicResult": last_job.get("anthropicResult") or {},
                "generationReport": last_job.get("generationReport") or {},
            })
        if status == "failed":
            report = last_job.get("generationReport") if isinstance(last_job.get("generationReport"), dict) else {}
            if report:
                raise AnthropicDraftError(report.get("errorMessage") or "Remote AI generation job failed.", report)
            report = generation_failure_report(
                trace=trace,
                args=args,
                result={},
                error_message=str(last_job.get("errorMessage") or last_job.get("message") or "Remote AI generation job failed."),
            )
            raise AnthropicDraftError(report["errorMessage"], report)
        time.sleep(poll_seconds)
        last_job = read_remote_generation_job(base_url, bearer_token, job_id)
    report = generation_failure_report(
        trace=trace,
        args=args,
        result={},
        error_message=f"Remote AI generation job {job_id} did not finish within {timeout_seconds} seconds.",
    )
    raise AnthropicDraftError(report["errorMessage"], report)


def submit_remote_generation_job(base_url: str, bearer_token: str, payload: dict[str, Any]) -> dict[str, Any]:
    req = request.Request(
        f"{base_url}/api/generation-jobs",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=60) as response:
        result = json.loads(response.read().decode("utf-8"))
    return result.get("job") if isinstance(result.get("job"), dict) else {}


def read_remote_generation_job(base_url: str, bearer_token: str, job_id: str) -> dict[str, Any]:
    req = request.Request(
        f"{base_url}/api/generation-jobs/{job_id}",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {bearer_token}",
        },
        method="GET",
    )
    with request.urlopen(req, timeout=60) as response:
        result = json.loads(response.read().decode("utf-8"))
    return result.get("job") if isinstance(result.get("job"), dict) else {}


def parse_remote_generation_result(trace: dict[str, Any], args: argparse.Namespace, result: dict[str, Any]) -> dict[str, Any]:
    anthropic_result = result.get("anthropicResult") if isinstance(result.get("anthropicResult"), dict) else {}
    generation_report = result.get("generationReport") if isinstance(result.get("generationReport"), dict) else {}
    text = extract_text_response(anthropic_result)
    try:
        draft = json.loads(text)
    except json.JSONDecodeError as exc:
        proxy_report = result.get("generationReport") if isinstance(result.get("generationReport"), dict) else {}
        report = generation_failure_report(
            trace=trace,
            args=args,
            result=anthropic_result,
            error_message=f"Remote AI proxy returned invalid guide JSON: {exc}",
            response_chars=len(text),
        )
        if proxy_report:
            report["generatedAt"] = proxy_report.get("generatedAt") or report["generatedAt"]
            report["usage"] = proxy_report.get("usage") or report["usage"]
            report["generationRunId"] = proxy_report.get("generationRunId") or report["generationRunId"]
            report["model"] = proxy_report.get("model") or report["model"]
            report["provider"] = proxy_report.get("provider") or report["provider"]
            report["promptVersion"] = proxy_report.get("promptVersion") or report["promptVersion"]
        base_url = os.environ.get("KCXDOC_REMOTE_API_BASE_URL", "").strip().rstrip("/")
        bearer_token = os.environ.get("KCXDOC_REMOTE_API_BEARER_TOKEN", "").strip()
        if base_url and bearer_token:
            post_remote_usage_record(base_url, bearer_token, report)
        raise AnthropicDraftError(report.get("errorMessage") or f"Remote AI proxy returned invalid guide JSON: {exc}", report) from exc
    if isinstance(draft, dict) and isinstance(draft.get("guideDraft"), dict):
        wrapper_model = draft.get("model") if isinstance(draft.get("model"), dict) else {}
        draft = draft["guideDraft"]
        draft.setdefault("model", {}).update(wrapper_model)
    draft.setdefault("model", {})
    draft.setdefault("sessionId", trace.get("sessionId", ""))
    draft.setdefault("generatedAt", generation_report.get("generatedAt") or utc_timestamp())
    if generation_report.get("generationRunId"):
        draft["generationRunId"] = generation_report["generationRunId"]
    draft["model"].update(
        {
            "provider": "anthropic",
            "model": args.model,
            "mode": "azure-function-proxy",
            "promptVersion": args.prompt_version,
        }
    )
    draft["usage"] = normalize_anthropic_usage(anthropic_result.get("usage"), args.model)
    draft = enforce_generation_quality_rules(draft, trace)
    return draft


def enforce_generation_quality_rules(draft: dict[str, Any], trace: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(draft))
    normalize_source_recording_metadata(normalized, trace)
    if trace_has_no_usable_transcript(trace):
        return blocked_no_transcript_draft(normalized, trace)
    consolidate_systemic_screenshot_failures(normalized, trace)
    add_round_minute_timestamp_review(normalized)
    ensure_review_001_duration(normalized, trace)
    return normalized


def trace_has_no_usable_transcript(trace: dict[str, Any]) -> bool:
    segments = trace_segments(trace)
    if not segments:
        return True
    has_speaker_text = any(str(segment.get("speakerText") or "").strip() for segment in segments)
    transcript_confidences = [transcript_confidence(segment) for segment in segments]
    explicit_confidences = [confidence for confidence in transcript_confidences if confidence is not None]
    return not has_speaker_text or (bool(explicit_confidences) and all(confidence <= 0 for confidence in explicit_confidences))


_PROTOTYPE_SPEAKER_INDICATORS = (
    "prototype narration segment",
    "replace this with local speech-to-text",
)
_PROTOTYPE_OCR_INDICATORS = (
    "visible ui text pending",
)
_PROTOTYPE_NOTES_INDICATOR = "prototype segment generated before local stt/ocr are wired in"


def is_prototype_segment(segment: dict[str, Any]) -> bool:
    speaker = str(segment.get("speakerText") or "").strip().lower()
    if not speaker or any(ind in speaker for ind in _PROTOTYPE_SPEAKER_INDICATORS):
        return True
    ocr = segment.get("visibleUiText")
    if not ocr or (isinstance(ocr, list) and len(ocr) == 0):
        return True
    if isinstance(ocr, list) and all(any(ind in str(v).lower() for ind in _PROTOTYPE_OCR_INDICATORS) for v in ocr):
        return True
    notes = str(segment.get("notes") or "").strip().lower()
    if _PROTOTYPE_NOTES_INDICATOR in notes:
        return True
    conf = transcript_confidence(segment)
    if conf is not None and conf <= 0.0:
        return True
    return False


def is_prototype_trace(trace: dict[str, Any]) -> bool:
    segments = trace_segments(trace)
    if not segments:
        return False
    prototype_count = sum(1 for seg in segments if is_prototype_segment(seg))
    return prototype_count / len(segments) > 0.80


def blocked_prototype_draft(trace: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    segments = trace_segments(trace)
    recording = trace_recording(trace)
    duration_seconds = safe_float(recording.get("durationSeconds"))
    prototype_count = sum(1 for seg in segments if is_prototype_segment(seg))
    pct = round(100 * prototype_count / len(segments)) if segments else 100
    placeholder_step = {
        "title": "PLACEHOLDER — requires complete trace",
        "instruction": "PLACEHOLDER — requires complete trace",
        "expectedResult": "PLACEHOLDER — requires complete trace",
        "needsHumanReview": True,
        "screenshotDecision": {
            "needsHumanReview": True,
            "reviewNote": "No usable trace content.",
            "screenshotRef": None,
        },
    }
    return {
        "schemaVersion": 1,
        "sessionId": trace.get("sessionId", ""),
        "title": trace_title(trace) or recording_file_name(recording) or "Recording Guide",
        "overallStatus": "BLOCKED — Trace not ready for generation.",
        "status": "BLOCKED — Trace not ready for generation.",
        "purpose": "Trace extraction is required before this recording can be converted into a usable guide.",
        "sourceRecording": explicit_source_recording(recording),
        "sections": [
            {
                "title": "PLACEHOLDER — requires complete trace",
                "body": ["PLACEHOLDER — requires complete trace"],
                "steps": [placeholder_step, placeholder_step, placeholder_step],
            }
        ],
        "steps": [placeholder_step, placeholder_step, placeholder_step],
        "openReviewItems": [
            {
                "id": "review-001",
                "severity": "critical",
                "description": (
                    f"{pct}% of segments ({prototype_count} of {len(segments)}) contain prototype placeholder content. "
                    f"Checks failed: speakerText placeholder or empty, visibleUiText placeholder or empty, "
                    f"transcript confidence 0.0 or prototype notes detected. "
                    f"Recording duration: {format_duration_human(duration_seconds)}. "
                    f"Total segment count: {len(segments)}."
                ),
                "totalSegmentCount": len(segments),
                "recordingDuration": format_duration_human(duration_seconds),
                "resolution": (
                    "Reprocess the recording with real speech-to-text and OCR extraction "
                    "before submitting for guide generation."
                ),
            }
        ],
        "generatedAt": utc_timestamp(),
        "model": {
            "provider": "local",
            "model": args.model,
            "mode": "blocked-preflight",
            "promptVersion": args.prompt_version,
        },
        "usage": {},
    }


def trace_segments(trace: dict[str, Any]) -> list[dict[str, Any]]:
    segments = trace.get("segments") if isinstance(trace.get("segments"), list) else []
    return [segment for segment in segments if isinstance(segment, dict)]


def transcript_confidence(segment: dict[str, Any]) -> float | None:
    confidence = segment.get("confidence")
    if isinstance(confidence, dict):
        if confidence.get("transcript") is None:
            return None
        return safe_float(confidence.get("transcript"))
    if confidence is None:
        return None
    return safe_float(confidence)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def blocked_no_transcript_draft(draft: dict[str, Any], trace: dict[str, Any]) -> dict[str, Any]:
    recording = trace_recording(trace)
    duration_seconds = safe_float(recording.get("durationSeconds"))
    steps = placeholder_steps_for_recording(recording, duration_seconds)
    title = str(draft.get("title") or trace_title(trace) or recording_file_name(recording) or "Recording Guide").strip()
    blocked = {
        **draft,
        "schemaVersion": 1,
        "title": title,
        "overallStatus": "BLOCKED — No transcript available.",
        "status": "BLOCKED — No transcript available.",
        "purpose": "Transcript extraction is required before this recording can be converted into a usable guide.",
        "sourceRecording": explicit_source_recording(recording),
        "sections": [
            {
                "title": "PLACEHOLDER — requires transcript",
                "body": ["PLACEHOLDER — requires transcript"],
                "steps": steps,
            }
        ],
        "steps": steps,
        "openReviewItems": [
            {
                "id": "review-001",
                "severity": "critical",
                "description": (
                    f"No usable transcript was extracted. Segment count: {len(trace_segments(trace))}. "
                    f"Recording duration: {format_duration_human(duration_seconds)}."
                ),
                "totalSegmentCount": len(trace_segments(trace)),
                "recordingDuration": format_duration_human(duration_seconds),
                "resolution": "Reprocess the recording with a usable transcript or local speech-to-text before generating the guide.",
            }
        ],
    }
    return blocked


def placeholder_steps_for_recording(recording: dict[str, Any], duration_seconds: float) -> list[dict[str, Any]]:
    count = 3 if duration_seconds < 1800 else 4 if duration_seconds < 3600 else 5
    return [
        {
            "title": "PLACEHOLDER — requires transcript",
            "instruction": "PLACEHOLDER — requires transcript",
            "expectedResult": "PLACEHOLDER — requires transcript",
            "needsHumanReview": True,
            "screenshotDecision": {
                "needsHumanReview": True,
                "reviewNote": "No transcript available.",
                "screenshotRef": None,
            },
        }
        for _ in range(count)
    ]


def trace_recording(trace: dict[str, Any]) -> dict[str, Any]:
    recording = trace.get("recording") if isinstance(trace.get("recording"), dict) else {}
    source_recording = trace.get("sourceRecording") if isinstance(trace.get("sourceRecording"), dict) else {}
    return {**source_recording, **recording}


def explicit_source_recording(recording: dict[str, Any]) -> dict[str, Any]:
    duration_seconds = safe_float(recording.get("durationSeconds"))
    return {
        "fileName": recording_file_name(recording),
        "sourceFile": str(recording.get("sourceFile") or recording.get("fileName") or recording.get("sourceName") or ""),
        "duration": format_duration_human(duration_seconds),
        "durationSeconds": duration_seconds,
        "captureMode": str(recording.get("captureMode") or "imported-recording"),
    }


def recording_file_name(recording: dict[str, Any]) -> str:
    value = str(recording.get("fileName") or recording.get("sourceName") or recording.get("sourceFile") or "").strip()
    return Path(value).name if value else ""


def format_duration_human(seconds: Any) -> str:
    total_seconds = max(0, int(round(safe_float(seconds))))
    minutes, remaining = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if remaining or not parts:
        parts.append(f"{remaining} second{'s' if remaining != 1 else ''}")
    return " ".join(parts)


def normalize_source_recording_metadata(draft: dict[str, Any], trace: dict[str, Any]) -> None:
    existing = draft.get("sourceRecording") if isinstance(draft.get("sourceRecording"), dict) else {}
    recording = {**trace_recording(trace), **existing}
    draft["sourceRecording"] = explicit_source_recording(recording)


def ensure_review_001_duration(draft: dict[str, Any], trace: dict[str, Any]) -> None:
    recording = trace_recording(trace)
    if recording.get("durationSeconds") is None:
        return
    items = ensure_open_review_items(draft)
    review_001 = next((item for item in items if isinstance(item, dict) and item.get("id") == "review-001"), None)
    if review_001 is None:
        review_001 = {
            "id": "review-001",
            "severity": "info",
            "description": "Recording scope context.",
        }
        items.insert(0, review_001)
    duration = format_duration_human(recording.get("durationSeconds"))
    review_001.setdefault("recordingDuration", duration)
    description = str(review_001.get("description") or "").strip()
    if duration and duration not in description:
        review_001["description"] = f"{description} Recording duration: {duration}.".strip()


def ensure_open_review_items(draft: dict[str, Any]) -> list[dict[str, Any]]:
    items = draft.get("openReviewItems")
    if not isinstance(items, list):
        items = draft.get("reviewItems") if isinstance(draft.get("reviewItems"), list) else []
        draft["openReviewItems"] = items
    return items


def consolidate_systemic_screenshot_failures(draft: dict[str, Any], trace: dict[str, Any]) -> None:
    condition = systemic_screenshot_failure_condition(trace)
    if not condition:
        return
    items = ensure_open_review_items(draft)
    upsert_review_item(
        items,
        {
            "id": "review-002",
            "severity": "critical",
            "description": condition,
            "resolution": "Reviewer should recapture or approve usable application screenshots before publishing.",
        },
    )
    for step in iter_draft_steps(draft):
        step["screenshotDecision"] = {
            "needsHumanReview": True,
            "reviewNote": "See review-002.",
            "screenshotRef": None,
        }


def systemic_screenshot_failure_condition(trace: dict[str, Any]) -> str:
    images = [
        image
        for segment in trace_segments(trace)
        for image in segment.get("candidateImages", [])
        if isinstance(image, dict)
    ]
    if not images:
        return ""
    if all(str(image.get("reviewStatus") or "").lower() == "pending" for image in images):
        return "All candidate screenshots are pending review."
    if all(is_placeholder_ocr_image(image) for image in images):
        return "All candidate screenshots have placeholder-only OCR evidence."
    if all(image_confidence(image) < 0.5 for image in images):
        return "All candidate screenshots are below the confidence threshold."
    return ""


def is_placeholder_ocr_image(image: dict[str, Any]) -> bool:
    source = str(image.get("ocrSource") or image.get("source") or "").lower()
    text = str(image.get("ocrText") or "").strip()
    reason = str(image.get("recommendationReason") or image.get("reason") or "").lower()
    return "placeholder" in source or "placeholder" in reason or not useful_ocr_text(text)


def image_confidence(image: dict[str, Any]) -> float:
    for key in ("frameEvidenceScore", "confidence", "score", "ocrConfidence"):
        if image.get(key) is not None:
            return safe_float(image.get(key))
    return 0.0


def upsert_review_item(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    for index, existing in enumerate(items):
        if isinstance(existing, dict) and existing.get("id") == item.get("id"):
            items[index] = {**existing, **item}
            return
    items.append(item)


def add_round_minute_timestamp_review(draft: dict[str, Any]) -> None:
    timestamps = selected_screenshot_timestamps(draft)
    if len(timestamps) < 2:
        return
    cadence_count = sum(1 for timestamp in timestamps if is_exact_minute_or_half_minute(timestamp))
    if cadence_count / len(timestamps) <= 0.8:
        return
    upsert_review_item(
        ensure_open_review_items(draft),
        {
            "id": "review-003",
            "severity": "critical",
            "description": "Screenshot timestamps appear cadence-based. Frame selection may not reflect actual UI state changes. Reviewer should treat all frame selections as approximate and recapture from source recording.",
            "resolution": "Review selected screenshots against the source recording and recapture frames that do not match the documented step.",
        },
    )


def selected_screenshot_timestamps(draft: dict[str, Any]) -> list[float]:
    timestamps: list[float] = []
    for step in iter_draft_steps(draft):
        for value in screenshot_timestamp_values(step):
            timestamps.append(value)
            break
    return timestamps


def screenshot_timestamp_values(step: dict[str, Any]) -> list[float]:
    values: list[float] = []
    for container_key in ("selectedScreenshot", "selected_screenshot", "screenshotDecision"):
        container = step.get(container_key)
        if isinstance(container, dict):
            for key in ("timestampSeconds", "timestamp_seconds"):
                if container.get(key) is not None:
                    values.append(safe_float(container.get(key)))
            if container.get("timestamp"):
                parsed = parse_timestamp_seconds(str(container["timestamp"]))
                if parsed is not None:
                    values.append(parsed)
    for key in ("timestampSeconds", "timestamp_seconds"):
        if step.get(key) is not None:
            values.append(safe_float(step.get(key)))
    return values


def parse_timestamp_seconds(value: str) -> float | None:
    parts = value.strip().split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        if len(parts) == 2:
            minutes, seconds = parts
            return int(minutes) * 60 + float(seconds)
    except ValueError:
        return None
    return None


def is_exact_minute_or_half_minute(seconds: float) -> bool:
    return abs((seconds % 30)) < 0.001 or abs((seconds % 30) - 30) < 0.001


def build_anthropic_payload(trace: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    system_prompt = (WORKSPACE / "prompts" / "guide_draft_system.md").read_text(encoding="utf-8")
    user_prompt = {
        "task": "Create KCXDocumentor guide draft JSON from this procedure trace.",
        "promptVersion": args.prompt_version,
        "today": date.today().isoformat(),
        "procedureTrace": prepare_trace_for_anthropic(trace),
    }
    return {
        "model": args.model,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "system": system_prompt,
        "messages": [{"role": "user", "content": json.dumps(user_prompt, separators=(",", ":"))}],
    }


def remote_failure_report(trace: dict[str, Any], args: argparse.Namespace, status_code: int, detail: str) -> dict[str, Any]:
    try:
        payload = json.loads(detail)
    except json.JSONDecodeError:
        payload = {}
    report = payload.get("generationReport") if isinstance(payload.get("generationReport"), dict) else {}
    if report:
        return report
    message = payload.get("error") or detail.strip() or f"HTTP {status_code}"
    return generation_failure_report(
        trace=trace,
        args=args,
        result={},
        error_message=f"Remote AI proxy request failed: HTTP {status_code}: {message}",
        response_chars=len(detail),
    )


def post_remote_usage_record(base_url: str, bearer_token: str, report: dict[str, Any]) -> None:
    req = request.Request(
        f"{base_url}/api/usage-records",
        data=json.dumps({"records": [report]}).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=30):
            return
    except (TimeoutError, error.HTTPError, error.URLError, OSError) as exc:
        report["remoteUsageUpdateError"] = str(exc)


def trace_title(trace: dict[str, Any]) -> str:
    recording = trace.get("recording") if isinstance(trace.get("recording"), dict) else {}
    target = str(recording.get("targetApplication") or "").strip()
    source = str(recording.get("sourceName") or recording.get("sourceFile") or "").strip()
    return " - ".join(part for part in (target, source) if part)


def utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_anthropic_usage(usage: Any, model: str) -> dict[str, Any]:
    raw_usage = usage if isinstance(usage, dict) else {}
    input_tokens = int(raw_usage.get("input_tokens") or 0)
    output_tokens = int(raw_usage.get("output_tokens") or 0)
    total_tokens = input_tokens + output_tokens
    return {
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "totalTokens": total_tokens,
        "estimatedCostUSD": estimate_anthropic_cost_usd(input_tokens, output_tokens, model),
    }


def estimate_anthropic_cost_usd(input_tokens: int, output_tokens: int, model: str) -> float:
    # Pricing captured with each artifact so historical runs remain auditable.
    return round(
        (input_tokens / 1_000_000 * SONNET_4_6_INPUT_COST_PER_MILLION)
        + (output_tokens / 1_000_000 * SONNET_4_6_OUTPUT_COST_PER_MILLION),
        6,
    )


def anthropic_http_error_message(status_code: int, detail: str) -> str:
    detail = detail.strip()
    if not detail:
        return f"Anthropic API request failed: HTTP {status_code}."
    try:
        payload = json.loads(detail)
    except json.JSONDecodeError:
        return f"Anthropic API request failed: HTTP {status_code}: {detail}"
    error_payload = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    message = str(error_payload.get("message") or payload.get("message") or detail).strip()
    error_type = str(error_payload.get("type") or payload.get("type") or "").strip()
    if error_type:
        return f"Anthropic API request failed: HTTP {status_code} ({error_type}): {message}"
    return f"Anthropic API request failed: HTTP {status_code}: {message}"


def generation_report_from_draft(draft: dict[str, Any]) -> dict[str, Any]:
    model = draft.get("model") if isinstance(draft.get("model"), dict) else {}
    report = {
        "schemaVersion": 1,
        "status": "succeeded",
        "generatedAt": draft.get("generatedAt", ""),
        "sessionId": draft.get("sessionId", ""),
        "title": draft_title(draft),
        "model": model.get("model", ""),
        "provider": model.get("provider", ""),
        "promptVersion": model.get("promptVersion", ""),
        "usage": draft.get("usage", {}),
    }
    report["generationRunId"] = str(draft.get("generationRunId") or generation_run_id(report))
    return report


def generation_failure_report(
    trace: dict[str, Any],
    args: argparse.Namespace,
    result: dict[str, Any],
    error_message: str,
    response_chars: int = 0,
) -> dict[str, Any]:
    report = {
        "schemaVersion": 1,
        "status": "failed",
        "generatedAt": utc_timestamp(),
        "sessionId": trace.get("sessionId", ""),
        "title": "Failed guide generation",
        "model": args.model,
        "provider": "anthropic",
        "promptVersion": args.prompt_version,
        "usage": normalize_anthropic_usage(result.get("usage"), args.model),
        "errorMessage": error_message,
        "responseChars": response_chars,
    }
    report["generationRunId"] = generation_run_id(report)
    return report


def generation_run_id(report: dict[str, Any]) -> str:
    usage = report.get("usage") if isinstance(report.get("usage"), dict) else {}
    fingerprint = "|".join(
        str(value)
        for value in (
            report.get("sessionId", ""),
            report.get("generatedAt", ""),
            report.get("model", ""),
            report.get("promptVersion", ""),
            usage.get("inputTokens", usage.get("input_tokens", "")),
            usage.get("outputTokens", usage.get("output_tokens", "")),
        )
    )
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]


def draft_title(draft: dict[str, Any]) -> str:
    if str(draft.get("title") or "").strip():
        return str(draft["title"]).strip()
    document = draft.get("document") if isinstance(draft.get("document"), dict) else {}
    return str(document.get("title") or "").strip()


def write_generation_report(draft_path: Path, draft: dict[str, Any]) -> Path:
    report_path = draft_path.parent / "generation_report.json"
    report = generation_report_from_draft(draft)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report_path


def write_generation_failure(draft_path: Path, report: dict[str, Any]) -> Path:
    failure_path = draft_path.parent / "generation_failure.json"
    failure_path.parent.mkdir(parents=True, exist_ok=True)
    failure_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return failure_path


def upsert_usage_record(report: dict[str, Any], db_path: Path | None = None) -> Path:
    db_path = db_path or USAGE_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    run_id = str(report.get("generationRunId") or generation_run_id(report))
    usage = report.get("usage") if isinstance(report.get("usage"), dict) else {}
    status = str(report.get("status") or "succeeded")
    with sqlite3.connect(db_path) as connection:
        ensure_usage_schema(connection)
        connection.execute(
            """
            INSERT INTO generation_usage (
                generation_run_id, generated_at, recorded_at, session_id, title,
                provider, model, prompt_version, input_tokens, output_tokens,
                total_tokens, estimated_cost_usd, page_count, status, error_message, report_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(generation_run_id) DO UPDATE SET
                generated_at = excluded.generated_at,
                recorded_at = excluded.recorded_at,
                session_id = excluded.session_id,
                title = excluded.title,
                provider = excluded.provider,
                model = excluded.model,
                prompt_version = excluded.prompt_version,
                input_tokens = excluded.input_tokens,
                output_tokens = excluded.output_tokens,
                total_tokens = excluded.total_tokens,
                estimated_cost_usd = excluded.estimated_cost_usd,
                page_count = COALESCE(NULLIF(generation_usage.page_count, 0), excluded.page_count),
                status = excluded.status,
                error_message = excluded.error_message,
                report_json = excluded.report_json
            """,
            (
                run_id,
                report.get("generatedAt", ""),
                utc_timestamp(),
                report.get("sessionId", ""),
                report.get("title", ""),
                report.get("provider", ""),
                report.get("model", ""),
                report.get("promptVersion", ""),
                int(usage.get("inputTokens") or usage.get("input_tokens") or 0),
                int(usage.get("outputTokens") or usage.get("output_tokens") or 0),
                int(usage.get("totalTokens") or usage.get("total_tokens") or 0),
                float(usage.get("estimatedCostUSD") or usage.get("estimated_cost_usd") or 0),
                int(report.get("pageCount") or report.get("page_count") or 0),
                status,
                str(report.get("errorMessage") or ""),
                json.dumps(report, sort_keys=True),
            ),
        )
    return db_path


def ensure_usage_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS generation_usage (
            generation_run_id TEXT PRIMARY KEY,
            generated_at TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            session_id TEXT NOT NULL,
            title TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            estimated_cost_usd REAL NOT NULL DEFAULT 0,
            page_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'succeeded',
            error_message TEXT NOT NULL DEFAULT '',
            report_json TEXT NOT NULL
        )
        """
    )
    existing_columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(generation_usage)").fetchall()
    }
    if "status" not in existing_columns:
        connection.execute("ALTER TABLE generation_usage ADD COLUMN status TEXT NOT NULL DEFAULT 'succeeded'")
    if "error_message" not in existing_columns:
        connection.execute("ALTER TABLE generation_usage ADD COLUMN error_message TEXT NOT NULL DEFAULT ''")
    if "page_count" not in existing_columns:
        connection.execute("ALTER TABLE generation_usage ADD COLUMN page_count INTEGER NOT NULL DEFAULT 0")


def prepare_trace_for_anthropic(trace: dict[str, Any]) -> dict[str, Any]:
    prepared = json.loads(json.dumps(trace))
    excluded_frames: list[dict[str, Any]] = []
    review_guidance = normalize_review_guidance(prepared.get("reviewGuidance"))
    segments = prepared.get("segments") if isinstance(prepared.get("segments"), list) else []

    for segment in segments:
        if not isinstance(segment, dict):
            continue
        segment["visibleUiText"] = compact_visible_ui_text(segment.get("visibleUiText"))
        images = segment.get("candidateImages") if isinstance(segment.get("candidateImages"), list) else []
        kept_images = []
        for image in images:
            if not isinstance(image, dict):
                continue
            if str(image.get("reviewStatus", "")).lower() == "rejected":
                excluded = excluded_frame_context(image, segment)
                excluded_frames.append(excluded)
                note = str(image.get("reviewNote") or "").strip()
                if note:
                    review_guidance.append(
                        {
                            "type": "excluded-frame",
                            "frameId": excluded.get("frameId", ""),
                            "sourceSegmentId": excluded.get("sourceSegmentId", ""),
                            "message": note,
                        }
                )
                continue
            if image.get("recommendationGroup") == "system-rejected" and str(image.get("reviewStatus", "")).lower() != "approved":
                excluded = excluded_frame_context(image, segment)
                excluded["exclusionReason"] = image.get("recommendationReason") or "System pre-review rejected this frame."
                excluded_frames.append(excluded)
                continue
            kept_images.append(compact_candidate_image(image))
        segment["candidateImages"] = sorted(kept_images, key=screenshot_sort_key)[:3]

    if excluded_frames:
        prepared["excludedFrames"] = merge_excluded_frames(prepared.get("excludedFrames"), excluded_frames)
    if review_guidance:
        prepared["reviewGuidance"] = review_guidance
    return prepared


def compact_visible_ui_text(value: Any, limit: int = 24) -> list[str]:
    items = as_string_list(value)
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = re.sub(r"\s+", " ", item).strip()
        if not useful_ocr_text(text):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text[:120])
        if len(cleaned) >= limit:
            break
    return cleaned


def compact_candidate_image(image: dict[str, Any]) -> dict[str, Any]:
    kept_keys = (
        "frameId",
        "path",
        "webPath",
        "timestamp",
        "timestampSeconds",
        "score",
        "confidence",
        "frameEvidenceScore",
        "ocrConfidence",
        "ocrRelevanceScore",
        "ocrNonApplication",
        "ocrSupportingTool",
        "ocrClass",
        "ocrClassConfidence",
        "appOcrScore",
        "appTermHits",
        "supportingToolHits",
        "nonApplicationHits",
        "supportingToolAllowed",
        "visualQualityScore",
        "blurState",
        "dedupeState",
        "duplicateOfFrameId",
        "contentType",
        "recommendationGroup",
        "selectionDecision",
        "recommendationReason",
        "selectionReasons",
        "positiveSignals",
        "penalties",
        "created",
        "reviewStatus",
        "assignedSegmentId",
        "reviewNote",
    )
    compact = {key: image.get(key) for key in kept_keys if key in image}
    reason = str(image.get("reason") or "").strip()
    if reason:
        compact["reason"] = reason[:220]
    ocr_text = str(image.get("ocrText") or "").strip()
    if ocr_text:
        compact["ocrText"] = compact_ocr_text(ocr_text)
    return compact


def compact_ocr_text(text: str, limit: int = 360) -> str:
    parts = []
    seen: set[str] = set()
    for raw_part in re.split(r"[\\n\\r|;]+", text):
        part = re.sub(r"\s+", " ", raw_part).strip()
        if not useful_ocr_text(part):
            continue
        key = part.lower()
        if key in seen:
            continue
        seen.add(key)
        parts.append(part)
        if len(" | ".join(parts)) >= limit:
            break
    compact = " | ".join(parts)
    if len(compact) > limit:
        compact = compact[: limit - 1].rstrip() + "…"
    return compact


def useful_ocr_text(text: str) -> bool:
    if not text:
        return False
    if len(text) <= 1:
        return False
    if re.fullmatch(r"[-_=:+*/.,()\\[\\]{}\\d\\s]+", text):
        return False
    return bool(re.search(r"[A-Za-z]{2,}", text))


def normalize_review_guidance(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    if value:
        return [value]
    return []


def excluded_frame_context(image: dict[str, Any], segment: dict[str, Any]) -> dict[str, Any]:
    return {
        "frameId": image.get("frameId", ""),
        "sourceSegmentId": segment.get("id", ""),
        "timestamp": image.get("timestamp", ""),
        "timestampSeconds": image.get("timestampSeconds", 0),
        "reviewStatus": image.get("reviewStatus", "rejected"),
        "reviewNote": image.get("reviewNote", ""),
        "reason": image.get("reason", ""),
    }


def merge_excluded_frames(existing: Any, rejected_frames: list[dict[str, Any]]) -> list[Any]:
    merged = list(existing) if isinstance(existing, list) else []
    merged.extend(rejected_frames)
    return merged


def extract_text_response(result: dict[str, Any]) -> str:
    parts = []
    for block in result.get("content", []):
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
    text = "\n".join(parts).strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    return text


if __name__ == "__main__":
    raise SystemExit(main())
