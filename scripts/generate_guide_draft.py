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
    if args.use_anthropic:
        draft = generate_with_anthropic(trace, args)
    else:
        draft = generate_deterministic_draft(trace, args)

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
    for image in images:
        if isinstance(image, dict) and image.get("reviewStatus") != "rejected":
            return image
    return {}


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
