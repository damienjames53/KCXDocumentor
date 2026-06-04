#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

try:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Inches, Pt
    from tools.document_lib.keycentrix_docx import (
        FONT,
        add_bullets,
        add_cover,
        add_header_footer,
        add_metadata_table,
        style_document,
    )
except ImportError as exc:
    raise SystemExit(
        "Missing DOCX dependency. Install python-docx in the active Python environment, "
        "then rerun this command. Example: python3 -m pip install python-docx"
    ) from exc


@dataclass
class GuideStep:
    title: str
    action: str = ""
    expected_result: str = ""
    notes: list[str] = field(default_factory=list)
    ui_text: list[str] = field(default_factory=list)
    action_hints: list[str] = field(default_factory=list)
    transcript: str = ""
    start: str = ""
    end: str = ""
    screenshot: Path | None = None
    screenshot_caption: str = ""
    reviewer_comments: list[str] = field(default_factory=list)


@dataclass
class GuideDraft:
    title: str
    version: str
    status: str
    owner: str
    effective_date: str
    summary: str
    audience: list[str]
    prerequisites: list[str]
    workflow_overview: list[str]
    expected_results: list[str]
    troubleshooting: list[str]
    review_notes: list[str]
    source_metadata: dict[str, str]
    steps: list[GuideStep]


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [stringify_list_item(item) for item in value if stringify_list_item(item)]
    if isinstance(value, tuple):
        return [stringify_list_item(item) for item in value if stringify_list_item(item)]
    text = str(value).strip()
    return [text] if text else []


def stringify_list_item(item: Any) -> str:
    if isinstance(item, dict):
        parts = []
        for key in ("id", "severity", "category", "description", "resolution", "message", "title"):
            value = item.get(key)
            if value is not None and str(value).strip():
                label = key.replace("_", " ").title()
                parts.append(f"{label}: {str(value).strip()}")
        if parts:
            return " | ".join(parts)
    return str(item).strip()


def pick_value(source: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = source.get(key)
        if value is not None:
            return value
    return None


def text_value(source: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = source.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def resolve_asset_path(raw_path: Any, input_path: Path, asset_roots: list[Path] | None = None) -> Path | None:
    if raw_path is None:
        return None
    if isinstance(raw_path, dict):
        raw_path = raw_path.get("path") or raw_path.get("relativePath") or raw_path.get("file") or raw_path.get("filename")
    if not str(raw_path).strip():
        return None

    candidate = Path(str(raw_path))
    if candidate.is_absolute() and candidate.exists():
        return candidate

    search_roots = [input_path.parent, *(asset_roots or []), WORKSPACE, Path.cwd()]
    for root in search_roots:
        resolved = (root / candidate).resolve()
        if resolved.exists():
            return resolved
    return None


def first_existing_image(step: dict[str, Any], input_path: Path, asset_roots: list[Path] | None = None) -> tuple[Path | None, str]:
    image_values: list[Any] = []
    for key in ("screenshot", "screenshotRef", "image", "selected_image", "selected_screenshot", "selectedImage", "selectedScreenshot"):
        if step.get(key):
            image_values.append(step[key])
    candidate_images = pick_value(step, "candidate_images", "candidateImages")
    if isinstance(candidate_images, list):
        image_values.extend(candidate_images)
    elif candidate_images:
        image_values.append(candidate_images)
    screenshots = step.get("screenshots")
    if isinstance(screenshots, list):
        image_values.extend(screenshots)
    elif screenshots:
        image_values.append(screenshots)

    for value in image_values:
        resolved = resolve_asset_path(value, input_path, asset_roots)
        if resolved:
            caption = text_value(step, "screenshot_caption", "caption", default=resolved.name)
            return resolved, caption
    return None, ""


def normalize_step(step: dict[str, Any], index: int, input_path: Path, asset_roots: list[Path] | None = None) -> GuideStep:
    screenshot, caption = first_existing_image(step, input_path, asset_roots)
    transcript = text_value(step, "speaker_text", "speakerText", "transcript", "narration", "description")
    action = text_value(step, "action", "instruction", "intent", "stepTextPlaceholder", "body", default=transcript)
    title = text_value(step, "title", "name", "shellId", default=f"Step {index}")
    expected_result = text_value(step, "expected_result", "expectedResult", "result", "outcome")
    notes = as_list(step.get("notes") or step.get("warnings") or step.get("reviewNotes"))
    ui_text = as_list(pick_value(step, "visible_ui_text", "visibleUiText", "ui_text", "uiText", "ocr_text", "ocrText", "confirmedUiLabels"))
    action_hints = as_list(pick_value(step, "action_hints", "actionHints", "events", "actionHint", "actionHints"))
    reviewer_comments = list(notes)
    if step.get("needsHumanReview") is True:
        reviewer_comments.append("This step was flagged for human review by the draft generator.")
    confidence = step.get("confidence")
    if isinstance(confidence, dict):
        reasons = as_list(confidence.get("reasons"))
        if confidence.get("needsHumanReview") is True:
            reviewer_comments.append("Source confidence requires human review.")
        reviewer_comments.extend(reasons)
    if step.get("reviewStatus") == "rejected":
        reviewer_comments.append("The selected screenshot was rejected during frame review and should be replaced.")
    if ui_text:
        reviewer_comments.append(f"Source UI evidence: {'; '.join(ui_text)}")
    if action_hints:
        reviewer_comments.append(f"Source action hints: {'; '.join(action_hints)}")
    if step.get("screenshotReviewStatus") not in (None, "", "approved"):
        reviewer_comments.append(f"Screenshot review status: {step.get('screenshotReviewStatus')}")
    return GuideStep(
        title=title,
        action=action,
        expected_result=expected_result,
        notes=notes,
        ui_text=ui_text,
        action_hints=action_hints,
        transcript=transcript,
        start=text_value(step, "start", "start_time"),
        end=text_value(step, "end", "end_time"),
        screenshot=screenshot,
        screenshot_caption=caption,
        reviewer_comments=reviewer_comments,
    )


def normalize_input(data: dict[str, Any], input_path: Path) -> GuideDraft:
    if isinstance(data.get("guideDraft"), dict):
        wrapped_model = data.get("model") if isinstance(data.get("model"), dict) else {}
        data = data["guideDraft"]
        data.setdefault("model", {}).update(wrapped_model)

    document = data.get("document") if isinstance(data.get("document"), dict) else {}
    session = data.get("session") if isinstance(data.get("session"), dict) else {}
    recording = data.get("recording") if isinstance(data.get("recording"), dict) else {}
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}

    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list):
        raw_steps = data.get("procedure_steps")
    if not isinstance(raw_steps, list):
        raw_steps = data.get("segments")
    if not isinstance(raw_steps, list):
        raw_steps = data.get("confirmedSteps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raw_steps = data.get("pendingStepShells")
    if not isinstance(raw_steps, list) or not raw_steps:
        raw_steps = flatten_section_steps(data)
    if not isinstance(raw_steps, list):
        raise ValueError("Input JSON must contain a steps, procedure_steps, or segments array.")

    asset_roots = infer_asset_roots(data, input_path)
    title = text_value(
        document,
        "title",
        default=text_value(
            data,
            "title",
            default=text_value(
                data,
                "title",
                default=f"{text_value(recording, 'targetApplication', default=text_value(session, 'app_name', default='Application'))} User Guide",
            ),
        ),
    )
    version = text_value(document, "version", default=text_value(data, "version", default="Draft v0.1"))
    status = text_value(document, "status", default=text_value(data, "status", default="Prototype"))
    owner = text_value(document, "owner", default=text_value(data, "owner", default="KCXDocumentor"))
    effective_date = text_value(
        document,
        "effective_date",
        default=text_value(data, "effective_date", default=date.today().isoformat()),
    )
    summary = text_value(
        document,
        "summary",
        default=text_value(data, "summary", "purpose", default="This guide was generated from a local procedure trace."),
    )

    source_metadata = {
        "Application": text_value(
            recording,
            "targetApplication",
            default=text_value(meta, "targetApplication", default=text_value(session, "app_name", default=text_value(metadata, "app_name", default="Not specified"))),
        ),
        "Recording Duration": text_value(
            recording,
            "durationSeconds",
            default=text_value(session, "duration_sec", "duration", default=text_value(metadata, "duration", default="Not specified")),
        ),
        "Recorded At": text_value(session, "recorded_at", default=text_value(metadata, "recorded_at", default="Not specified")),
        "Source Recording": text_value(recording, "sourceFile", default=text_value(meta, "sessionId", default=str(input_path))),
        "Input File": str(input_path),
    }

    review_notes = (
        as_list(data.get("review_notes") or document.get("review_notes"))
        + as_list(data.get("warnings"))
        + as_list(data.get("assumptions"))
        + as_list(data.get("openReviewItems"))
    )
    summary = text_value(
        data.get("introduction") if isinstance(data.get("introduction"), dict) else {},
        "text",
        default=summary,
    )

    return GuideDraft(
        title=title,
        version=version,
        status=text_value(meta, "draftStatus", default=status),
        owner=owner,
        effective_date=effective_date,
        summary=summary,
        audience=as_list(data.get("audience") or document.get("audience") or ["Application users"]),
        prerequisites=as_list(data.get("prerequisites") or document.get("prerequisites")),
        workflow_overview=as_list(
            data.get("workflow_overview")
            or data.get("overview")
            or document.get("workflow_overview")
            or section_body(data, "Workflow Overview")
        ),
        expected_results=as_list(data.get("expected_results") or document.get("expected_results")),
        troubleshooting=as_list(data.get("troubleshooting") or document.get("troubleshooting")),
        review_notes=review_notes,
        source_metadata=source_metadata,
        steps=[normalize_step(step, idx + 1, input_path, asset_roots) for idx, step in enumerate(raw_steps) if isinstance(step, dict)],
    )


def infer_asset_roots(data: dict[str, Any], input_path: Path) -> list[Path]:
    roots: list[Path] = []
    for session_id in candidate_session_ids(data, input_path):
        processed_dir = WORKSPACE / "samples" / "processed" / session_id
        if processed_dir.exists():
            roots.append(processed_dir)
    source_recording = data.get("sourceRecording") if isinstance(data.get("sourceRecording"), dict) else {}
    source_file = text_value(source_recording, "sourceFile")
    if source_file:
        source_path = Path(source_file)
        if source_path.exists():
            roots.append(source_path.parent)
    return roots


def candidate_session_ids(data: dict[str, Any], input_path: Path) -> list[str]:
    ids = [
        text_value(data, "sessionId"),
        text_value(data.get("session") if isinstance(data.get("session"), dict) else {}, "sessionId", "id"),
        input_path.parent.name if input_path.parent.name else "",
    ]
    return list(dict.fromkeys(session_id for session_id in ids if session_id))


def flatten_section_steps(data: dict[str, Any]) -> list[dict[str, Any]]:
    sections = data.get("sections")
    if not isinstance(sections, list):
        return []
    flattened: list[dict[str, Any]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        section_title = text_value(section, "title", default="Guide Section")
        steps = section.get("steps")
        if isinstance(steps, list) and steps:
            for step in steps:
                if not isinstance(step, dict):
                    continue
                enriched = dict(step)
                step_number = text_value(enriched, "stepNumber", default=str(len(flattened) + 1))
                enriched.setdefault("title", f"{section_title}: Step {step_number}")
                flattened.append(enriched)
            continue
        body_items = as_list(section.get("body") or section.get("bullets") or section.get("summary"))
        for item in body_items:
            flattened.append({"title": section_title, "instruction": item})
    return flattened


def section_body(data: dict[str, Any], title: str) -> list[str]:
    sections = data.get("sections")
    if not isinstance(sections, list):
        return []
    for section in sections:
        if not isinstance(section, dict):
            continue
        if str(section.get("title", "")).strip().lower() == title.lower():
            return as_list(section.get("body")) + as_list(section.get("bullets"))
    return []


def add_labeled_paragraph(doc: Document, label: str, value: str) -> None:
    if not value:
        return
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(3)
    label_run = paragraph.add_run(f"{label}: ")
    label_run.bold = True
    label_run.font.name = FONT
    value_run = paragraph.add_run(value)
    value_run.font.name = FONT


def add_optional_bullet_section(doc: Document, title: str, items: list[str]) -> None:
    if not items:
        return
    doc.add_heading(title, level=1)
    add_bullets(doc, items)


def add_required_bullet_section(doc: Document, title: str, items: list[str], fallback: str) -> None:
    doc.add_heading(title, level=1)
    add_bullets(doc, items or [fallback])


def add_reviewer_comment(doc: Document, paragraph: Any, comments: list[str]) -> bool:
    clean_comments = [comment.strip() for comment in comments if comment and comment.strip()]
    if not clean_comments or not paragraph.runs or not hasattr(doc, "add_comment"):
        return False
    try:
        doc.add_comment(
            paragraph.runs,
            text="\n".join(clean_comments),
            author="KCXDocumentor Reviewer",
            initials="KCX",
        )
    except Exception:
        return False
    return True


def add_fallback_reviewer_section(doc: Document, comments: list[str]) -> None:
    if not comments:
        return
    doc.add_heading("Reviewer Comments", level=1)
    add_bullets(doc, comments)


def render_step(doc: Document, step: GuideStep, index: int) -> list[str]:
    heading = doc.add_heading(f"{index}. {step.title}", level=2)
    step_comments = list(dict.fromkeys(step.reviewer_comments))
    if step.start or step.end:
        step_comments.append(f"Source timing: {' - '.join(part for part in [step.start, step.end] if part)}")
    if not add_reviewer_comment(doc, heading, step_comments):
        fallback_comments = [f"Step {index}: {comment}" for comment in step_comments]
    else:
        fallback_comments = []

    add_labeled_paragraph(doc, "Action", step.action)
    add_labeled_paragraph(doc, "Expected result", step.expected_result)

    if step.screenshot:
        picture_p = doc.add_paragraph()
        picture_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        try:
            picture_p.add_run().add_picture(str(step.screenshot), width=Inches(6.1))
        except Exception as exc:
            add_labeled_paragraph(doc, "Screenshot unavailable", f"{step.screenshot} ({exc})")
        else:
            caption = doc.add_paragraph(step.screenshot_caption or f"Step {index} screenshot")
            caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in caption.runs:
                run.italic = True
                run.font.name = FONT
                run.font.size = Pt(8.8)
    else:
        fallback_comments.append(f"Step {index}: No screenshot was available for this procedure step.")

    return fallback_comments


def render_docx(draft: GuideDraft, output_path: Path) -> None:
    doc = Document()
    style_document(doc)
    add_header_footer(doc, draft.title, "keycentrix confidential")
    add_cover(doc, draft.title, draft.version, draft.status, draft.summary)
    add_metadata_table(
        doc,
        [
            ("Owner", draft.owner),
            ("Effective Date", draft.effective_date),
            ("Status", draft.status),
            ("Version", draft.version),
        ],
    )

    doc.add_heading("Purpose", level=1)
    purpose_p = doc.add_paragraph(draft.summary)
    fallback_comments: list[str] = []
    if draft.review_notes and not add_reviewer_comment(doc, purpose_p, draft.review_notes):
        fallback_comments.extend(draft.review_notes)

    add_optional_bullet_section(doc, "Intended Audience", draft.audience)
    add_required_bullet_section(
        doc,
        "Prerequisites",
        draft.prerequisites,
        "Confirm access to the target application and review the source recording context before publishing.",
    )
    add_required_bullet_section(
        doc,
        "Workflow Overview",
        draft.workflow_overview,
        "Follow the extracted procedure steps in order, then validate the expected result with an application reviewer.",
    )

    doc.add_heading("Step-by-Step Procedures", level=1)
    for index, step in enumerate(draft.steps, start=1):
        fallback_comments.extend(render_step(doc, step, index))

    add_required_bullet_section(
        doc,
        "Expected Results",
        draft.expected_results,
        "The user can complete the documented workflow without watching the original recording.",
    )
    add_required_bullet_section(
        doc,
        "Troubleshooting Notes",
        draft.troubleshooting,
        "If the workflow does not match the current application behavior, verify the step with an application reviewer.",
    )
    add_fallback_reviewer_section(doc, fallback_comments)

    doc.add_heading("Appendix: Source Recording Metadata", level=1)
    add_metadata_table(doc, list(draft.source_metadata.items()))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a keycentrix-styled DOCX guide from guide draft JSON or procedure_trace JSON."
    )
    parser.add_argument("input", nargs="?", type=Path, help="Path to guide draft JSON or procedure_trace JSON.")
    parser.add_argument(
        "--input",
        dest="input_option",
        type=Path,
        help="Path to guide draft JSON or procedure_trace JSON. Equivalent to the positional input.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=WORKSPACE / "artifacts" / "generated" / "prototype-guide.docx",
        help="Output DOCX path. Defaults to artifacts/generated/prototype-guide.docx.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw_input = args.input_option or args.input
    if raw_input is None:
        print("Input file is required. Pass a positional input or --input.", file=sys.stderr)
        return 2
    input_path = raw_input.resolve()
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 2

    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
        draft = normalize_input(data, input_path)
        render_docx(draft, args.output.resolve())
    except Exception as exc:
        print(f"Failed to render DOCX: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
