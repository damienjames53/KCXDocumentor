#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any
from urllib import error, request


WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_PROMPT_VERSION = "guide-draft-v1"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"


def main() -> int:
    load_env_file(WORKSPACE / ".env")
    args = parse_args()
    trace_path = args.trace.resolve()
    if not trace_path.exists():
        print(f"Trace file not found: {trace_path}", file=sys.stderr)
        return 2

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace = apply_frame_review(trace, trace_path)
    if args.use_anthropic:
        draft = generate_with_anthropic(trace, args)
    else:
        draft = generate_deterministic_draft(trace, args)
    draft = attach_screenshot_references(draft, trace)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(draft, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {args.output.resolve()}")
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
    parser.add_argument("--use-anthropic", action="store_true", help="Call Anthropic Messages API instead of deterministic local generation.")
    parser.add_argument("--model", default=os.environ.get("KCXDOC_ANTHROPIC_MODEL", DEFAULT_MODEL), help="Anthropic model ID. Defaults to claude-sonnet-4-6.")
    parser.add_argument("--max-tokens", type=int, default=8000, help="Maximum output tokens for Anthropic generation.")
    parser.add_argument("--temperature", type=float, default=0.2, help="Generation temperature for Anthropic generation.")
    parser.add_argument("--prompt-version", default=os.environ.get("KCXDOC_PROMPT_VERSION", DEFAULT_PROMPT_VERSION), help="Prompt version recorded in output metadata.")
    return parser.parse_args()


def generate_deterministic_draft(trace: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    recording = trace.get("recording", {})
    app = recording.get("targetApplication") or "Application"
    segments = trace.get("segments", [])
    review_flags = build_review_flags(segments)

    return {
        "schemaVersion": 1,
        "sessionId": trace.get("sessionId", ""),
        "title": f"{app} User Guide",
        "audience": "Application users",
        "purpose": "Provide a reviewed procedure guide generated from a compact local procedure trace.",
        "status": "Prototype",
        "owner": "KCXDocumentor",
        "sourceRecording": {
            "sourceFile": recording.get("sourceFile", "Not specified"),
            "durationSeconds": recording.get("durationSeconds", 0),
            "targetApplication": app,
        },
        "model": {
            "provider": "local-deterministic",
            "model": "none",
            "mode": "no-ai-fallback",
            "promptVersion": args.prompt_version,
        },
        "sections": [
            {
                "title": "Purpose",
                "body": ["Use this draft as a reviewable starting point before publishing customer-facing documentation."],
            },
            {
                "title": "Workflow Overview",
                "body": ["Follow the extracted procedure steps in sequence and resolve any review flags before publishing."],
            },
        ],
        "steps": [draft_step_from_segment(segment, index + 1) for index, segment in enumerate(segments)],
        "reviewFlags": review_flags,
    }


def draft_step_from_segment(segment: dict[str, Any], index: int) -> dict[str, Any]:
    confidence = segment.get("confidence", {})
    image = first_candidate_image(segment)
    ui_terms = segment.get("visibleUiText") or []
    return {
        "title": f"Review procedure segment {index}",
        "instruction": normalize_instruction(segment.get("speakerText", "")),
        "expectedResult": "The documented screen or workflow state is visible and ready for the next step.",
        "uiTerms": ui_terms,
        "confidence": confidence.get("overall", 0.0),
        "needsHumanReview": confidence.get("needsHumanReview", True),
        "screenshot": image.get("path") or "",
        "selectedScreenshot": build_screenshot_reference(image, segment),
        "caption": f"Candidate screenshot at {image.get('timestamp', segment.get('start', 'unknown time'))}",
        "sourceSegmentId": segment.get("id"),
    }


def normalize_instruction(text: str) -> str:
    text = " ".join(str(text).split())
    if not text:
        return "Review the source segment and write the missing user action."
    text = text.replace("I click", "Click").replace("I select", "Select").replace("I open", "Open")
    text = text.replace("we click", "Click").replace("we select", "Select").replace("we open", "Open")
    return text[0].upper() + text[1:]


def first_candidate_image(segment: dict[str, Any]) -> dict[str, Any]:
    images = segment.get("candidateImages") or []
    usable = [image for image in images if isinstance(image, dict) and image.get("reviewStatus") != "rejected"]
    approved = [image for image in usable if image.get("reviewStatus") == "approved"]
    if approved:
        return sorted(approved, key=lambda item: -float(item.get("score") or 0))[0]
    if usable:
        return sorted(usable, key=lambda item: -float(item.get("score") or 0))[0]
    return {}


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
    return {
        "frameId": frame.get("id", ""),
        "path": frame.get("path"),
        "webPath": frame.get("webPath") or frame.get("path"),
        "timestamp": frame.get("timestamp", ""),
        "timestampSeconds": frame.get("timestampSeconds", 0),
        "score": frame.get("score", 0),
        "confidence": frame.get("score", 0),
        "created": frame.get("created", False),
        "reason": frame.get("selectionReason", "Added during frame review."),
        "reviewStatus": "pending",
    }


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

    def enrich_step(step: dict[str, Any], index: int, total: int) -> None:
        if step_has_screenshot(step):
            return
        candidate = best_candidate_for_step(step, segment_lookup, timeline_candidates, index, total)
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
        step.setdefault("caption", f"Candidate screenshot at {screenshot.get('timestamp', 'unknown time')}")

    steps = iter_draft_steps(draft)
    for index, step in enumerate(steps):
        enrich_step(step, index, len(steps))
    return draft


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
) -> dict[str, Any] | None:
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
        return timeline_candidate_for_step(timeline_candidates, step_index, step_count)
    if not candidates:
        return None
    return sorted(candidates, key=screenshot_sort_key)[0]


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


def screenshot_sort_key(image: dict[str, Any]) -> tuple[int, float, float]:
    review_rank = 0 if image.get("reviewStatus") == "approved" else 1
    return (review_rank, -float(image.get("score") or 0), float(image.get("timestampSeconds") or 0))


def timeline_candidate_for_step(candidates: list[dict[str, Any]], step_index: int, step_count: int) -> dict[str, Any] | None:
    if not candidates:
        return None
    if step_count <= 1:
        return candidates[0]
    position = step_index / max(1, step_count - 1)
    candidate_index = round(position * (len(candidates) - 1))
    return candidates[max(0, min(len(candidates) - 1, candidate_index))]


def build_screenshot_reference(
    image: dict[str, Any],
    segment: dict[str, Any],
    processed_root: Path | None = None,
) -> dict[str, Any]:
    path = image.get("path") or ""
    resolved_path = str((processed_root / path).resolve()) if processed_root and path else path
    return {
        "frameId": image.get("frameId", ""),
        "path": resolved_path,
        "relativePath": path,
        "timestamp": image.get("timestamp", ""),
        "timestampSeconds": image.get("timestampSeconds", 0),
        "score": image.get("score", 0),
        "sourceSegmentId": segment.get("id", ""),
        "reviewStatus": image.get("reviewStatus", "pending"),
    }


def as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def build_review_flags(segments: list[dict[str, Any]]) -> list[dict[str, str]]:
    flags = []
    for segment in segments:
        confidence = segment.get("confidence") or {}
        if confidence.get("needsHumanReview"):
            flags.append(
                {
                    "severity": "review",
                    "segmentId": segment.get("id", ""),
                    "message": "; ".join(confidence.get("reasons") or ["Segment confidence requires human review."]),
                }
            )
    return flags


def generate_with_anthropic(trace: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY is required when --use-anthropic is set.")

    system_prompt = (WORKSPACE / "prompts" / "guide_draft_system.md").read_text(encoding="utf-8")
    user_prompt = {
        "task": "Create KCXDocumentor guide draft JSON from this procedure trace.",
        "promptVersion": args.prompt_version,
        "today": date.today().isoformat(),
        "procedureTrace": trace,
    }
    payload = {
        "model": args.model,
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "system": system_prompt,
        "messages": [{"role": "user", "content": json.dumps(user_prompt, separators=(",", ":"))}],
    }
    req = request.Request(
        ANTHROPIC_MESSAGES_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=180) as response:
            result = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Anthropic API request failed: HTTP {exc.code}: {detail}") from exc

    text = extract_text_response(result)
    draft = json.loads(text)
    if isinstance(draft, dict) and isinstance(draft.get("guideDraft"), dict):
        wrapper_model = draft.get("model") if isinstance(draft.get("model"), dict) else {}
        draft = draft["guideDraft"]
        draft.setdefault("model", {}).update(wrapper_model)
    draft.setdefault("model", {})
    draft["model"].update(
        {
            "provider": "anthropic",
            "model": args.model,
            "mode": "messages-api",
            "promptVersion": args.prompt_version,
        }
    )
    return draft


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
