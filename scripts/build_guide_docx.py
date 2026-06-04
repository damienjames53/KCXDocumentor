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
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


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


def resolve_asset_path(raw_path: Any, input_path: Path) -> Path | None:
    if raw_path is None:
        return None
    if isinstance(raw_path, dict):
        raw_path = raw_path.get("path") or raw_path.get("file") or raw_path.get("filename")
    if not str(raw_path).strip():
        return None

    candidate = Path(str(raw_path))
    if candidate.is_absolute() and candidate.exists():
        return candidate

    search_roots = [input_path.parent, WORKSPACE, Path.cwd()]
    for root in search_roots:
        resolved = (root / candidate).resolve()
        if resolved.exists():
            return resolved
    return None


def first_existing_image(step: dict[str, Any], input_path: Path) -> tuple[Path | None, str]:
    image_values: list[Any] = []
    for key in ("screenshot", "image", "selected_image", "selected_screenshot", "selectedImage", "selectedScreenshot"):
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
        resolved = resolve_asset_path(value, input_path)
        if resolved:
            caption = text_value(step, "screenshot_caption", "caption", default=resolved.name)
            return resolved, caption
    return None, ""


def normalize_step(step: dict[str, Any], index: int, input_path: Path) -> GuideStep:
    screenshot, caption = first_existing_image(step, input_path)
    transcript = text_value(step, "speaker_text", "speakerText", "transcript", "narration", "description")
    action = text_value(step, "action", "instruction", "intent", "stepTextPlaceholder", default=transcript)
    title = text_value(step, "title", "name", "shellId", default=f"Step {index}")
    expected_result = text_value(step, "expected_result", "expectedResult", "result", "outcome")
    return GuideStep(
        title=title,
        action=action,
        expected_result=expected_result,
        notes=as_list(step.get("notes") or step.get("warnings")),
        ui_text=as_list(pick_value(step, "visible_ui_text", "visibleUiText", "ui_text", "uiText", "ocr_text", "ocrText", "confirmedUiLabels")),
        action_hints=as_list(pick_value(step, "action_hints", "actionHints", "events", "actionHint")),
        transcript=transcript,
        start=text_value(step, "start", "start_time"),
        end=text_value(step, "end", "end_time"),
        screenshot=screenshot,
        screenshot_caption=caption,
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

    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list):
        raw_steps = data.get("procedure_steps")
    if not isinstance(raw_steps, list):
        raw_steps = data.get("segments")
    if not isinstance(raw_steps, list):
        raw_steps = data.get("confirmedSteps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raw_steps = data.get("pendingStepShells")
    if not isinstance(raw_steps, list):
        raise ValueError("Input JSON must contain a steps, procedure_steps, or segments array.")

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
            default=text_value(session, "app_name", default=text_value(metadata, "app_name", default="Not specified")),
        ),
        "Recording Duration": text_value(
            recording,
            "durationSeconds",
            default=text_value(session, "duration_sec", "duration", default=text_value(metadata, "duration", default="Not specified")),
        ),
        "Recorded At": text_value(session, "recorded_at", default=text_value(metadata, "recorded_at", default="Not specified")),
        "Source Recording": text_value(recording, "sourceFile", default=str(input_path)),
        "Input File": str(input_path),
    }

    return GuideDraft(
        title=title,
        version=version,
        status=status,
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
        review_notes=as_list(data.get("review_notes") or document.get("review_notes")),
        source_metadata=source_metadata,
        steps=[normalize_step(step, idx + 1, input_path) for idx, step in enumerate(raw_steps) if isinstance(step, dict)],
    )


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


def render_step(doc: Document, step: GuideStep, index: int) -> None:
    doc.add_heading(f"{index}. {step.title}", level=2)
    add_labeled_paragraph(doc, "Action", step.action)
    add_labeled_paragraph(doc, "Expected result", step.expected_result)
    if step.start or step.end:
        add_labeled_paragraph(doc, "Source timing", " - ".join(part for part in [step.start, step.end] if part))
    if step.ui_text:
        add_labeled_paragraph(doc, "Visible UI text", "; ".join(step.ui_text))
    if step.action_hints:
        add_labeled_paragraph(doc, "Action hints", "; ".join(step.action_hints))
    if step.notes:
        add_labeled_paragraph(doc, "Notes", "; ".join(step.notes))

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
    doc.add_paragraph(draft.summary)

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
        render_step(doc, step, index)

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
        "If a step or screenshot is unclear, return to the source trace and replace placeholder content before publishing.",
    )
    add_optional_bullet_section(doc, "Review Notes", draft.review_notes)

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
