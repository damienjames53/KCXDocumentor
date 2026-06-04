from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest
from docx import Document
try:
    from PIL import Image
except ImportError:  # pragma: no cover - optional visual QA dependency
    Image = None


ROOT = Path(__file__).resolve().parents[1]
QA_SCRIPT = ROOT / "scripts" / "qa_document_artifacts.py"
DOCX_HELPER = ROOT / "tools" / "document_lib" / "keycentrix_docx.py"
GUIDE_DRAFT_SCRIPT = ROOT / "scripts" / "generate_guide_draft.py"
PROCESS_RECORDING_SCRIPT = ROOT / "scripts" / "process_recording.py"
BUILD_GUIDE_DOCX_SCRIPT = ROOT / "scripts" / "build_guide_docx.py"
COMPARE_TRANSCRIPTS_SCRIPT = ROOT / "scripts" / "compare_transcripts.py"
APP_SERVER_SCRIPT = ROOT / "scripts" / "app_server.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_docx(path: Path, paragraphs: list[str]) -> None:
    doc = Document()
    for paragraph in paragraphs:
        doc.add_paragraph(paragraph)
    doc.save(path)


def run_qa(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(QA_SCRIPT), "--json", str(path)],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )


def test_artifact_qa_accepts_valid_guide_docx(tmp_path: Path) -> None:
    docx_path = tmp_path / "valid-guide.docx"
    write_docx(
        docx_path,
        [
            "keycentrix user guide",
            "Purpose",
            "Intended Audience",
            "Workflow Overview",
            "Step-by-Step Procedures",
            "Expected Results",
            "Troubleshooting",
            "Source Recording",
            "Screenshot reference: frame_0001.webp",
        ],
    )

    result = run_qa(docx_path)

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["passed"] is True
    assert payload["artifacts"][0]["missing_required_terms"] == []


def test_artifact_qa_rejects_forbidden_reference_terms(tmp_path: Path) -> None:
    docx_path = tmp_path / "leaky-guide.docx"
    write_docx(
        docx_path,
        [
            "keycentrix user guide",
            "Purpose",
            "Intended Audience",
            "Workflow Overview",
            "Step-by-Step Procedures",
            "Expected Results",
            "Troubleshooting",
            "Source Recording",
            "Screenshot reference: frame_0001.webp",
            "This draft accidentally mentions SmartReq.",
        ],
    )

    result = run_qa(docx_path)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["passed"] is False
    assert "Reference-project terminology leaked." in payload["artifacts"][0]["forbidden_matches"][0]


def test_artifact_qa_strict_mode_rejects_prototype_placeholders(tmp_path: Path) -> None:
    docx_path = tmp_path / "placeholder-guide.docx"
    write_docx(
        docx_path,
        [
            "keycentrix user guide",
            "Purpose",
            "Intended Audience",
            "Workflow Overview",
            "Step-by-Step Procedures",
            "Expected Results",
            "Troubleshooting",
            "Source Recording",
            "Prototype narration segment 1",
        ],
    )

    result = subprocess.run(
        [sys.executable, str(QA_SCRIPT), "--json", "--strict", str(docx_path)],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert "Prototype placeholder narration leaked." in payload["artifacts"][0]["forbidden_matches"][0]


def test_document_helper_can_build_minimal_docx_shell(tmp_path: Path) -> None:
    helper = load_module(DOCX_HELPER, "keycentrix_docx_test")
    output = tmp_path / "helper-guide.docx"

    doc = Document()
    helper.style_document(doc)
    helper.add_header_footer(doc, "Prototype Guide", "KCXDocumentor")
    helper.add_cover(
        doc,
        title="Prototype Guide",
        version="Version 0.1",
        status="Prototype",
        summary="Generated from local temporary test content.",
    )
    helper.add_section(
        doc,
        1,
        "Purpose",
        paragraphs=["Validate local DOCX creation without AI or external tools."],
    )
    doc.save(output)

    assert output.exists()
    with ZipFile(output) as package:
        assert "word/document.xml" in package.namelist()


def test_build_guide_docx_accepts_section_based_anthropic_shape(tmp_path: Path) -> None:
    input_path = tmp_path / "section-draft.json"
    output_path = tmp_path / "section-guide.docx"
    input_path.write_text(
        json.dumps(
            {
                "title": "SendKey User Guide",
                "meta": {
                    "draftStatus": "requires-human-review",
                    "sessionId": "sendkey-demo",
                    "targetApplication": "SendKey",
                },
                "introduction": {
                    "text": "SendKey provides communication methods for application users.",
                },
                "sections": [
                    {
                        "title": "Overview of Communication Methods",
                        "steps": [
                            {
                                "instruction": "Note that SendKey supports fax, SMS messaging, email, and voice messaging.",
                                "visibleUiText": ["SendKey"],
                                "reviewNotes": ["Confirm labels against OCR before publishing."],
                            }
                        ],
                    }
                ],
                "openReviewItems": [
                    {
                        "id": "review-001",
                        "severity": "blocking",
                        "description": "Screenshots require human approval.",
                        "resolution": "Approve candidate frames.",
                    }
                ],
                "model": {"provider": "anthropic"},
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(BUILD_GUIDE_DOCX_SCRIPT), str(input_path), "--output", str(output_path)],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert output_path.exists()
    doc = Document(output_path)
    text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    assert "Overview of Communication Methods" in text
    assert "Note that SendKey supports fax" in text
    assert "Screenshots require human approval" not in text
    with ZipFile(output_path) as package:
        comments_xml = package.read("word/comments.xml").decode("utf-8")
    assert "Screenshots require human approval" in comments_xml


def test_build_guide_docx_converts_markdown_bold_to_word_runs(tmp_path: Path) -> None:
    input_path = tmp_path / "bold-draft.json"
    output_path = tmp_path / "bold-guide.docx"
    input_path.write_text(
        json.dumps(
            {
                "title": "Bold Guide",
                "summary": "Use **Blink RX** safely.",
                "workflow_overview": ["Open the **Interfaces** tab."],
                "steps": [
                    {
                        "title": "Configure Blink",
                        "instruction": "Set **Customer Type** to **Blink**.",
                        "expectedResult": "The **AR account** is selected.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(BUILD_GUIDE_DOCX_SCRIPT), str(input_path), "--output", str(output_path)],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    doc = Document(output_path)
    paragraph_text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    assert "**" not in paragraph_text
    bold_run_text = {
        run.text
        for paragraph in doc.paragraphs
        for run in paragraph.runs
        if run.bold
    }
    assert {"Blink RX", "Interfaces", "Customer Type", "Blink", "AR account"}.issubset(bold_run_text)


def test_build_guide_docx_places_reviewer_concerns_in_comments_not_body(tmp_path: Path) -> None:
    input_path = tmp_path / "review-draft.json"
    output_path = tmp_path / "review-guide.docx"
    input_path.write_text(
        json.dumps(
            {
                "title": "Clean Review Guide",
                "summary": "Use this guide to complete the sample workflow.",
                "audience": ["Application users"],
                "workflow_overview": ["Complete the workflow in the order shown."],
                "expected_results": ["The workflow is completed successfully."],
                "steps": [
                    {
                        "title": "Save the record",
                        "instruction": "Select Save to finish updating the record.",
                        "expectedResult": "The record is saved.",
                        "reviewNotes": ["Confirm the screenshot does not include Teams controls."],
                        "visibleUiText": ["Save", "Teams"],
                        "confidence": {
                            "needsHumanReview": True,
                            "reasons": ["Transcript confidence is below publication threshold."],
                        },
                    }
                ],
                "openReviewItems": [
                    {
                        "id": "review-001",
                        "severity": "warning",
                        "description": "Screenshot selection requires approval.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(BUILD_GUIDE_DOCX_SCRIPT), str(input_path), "--output", str(output_path)],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    doc = Document(output_path)
    body_text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    assert "Select Save to finish updating the record." in body_text
    assert "Confirm the screenshot does not include Teams controls." not in body_text
    assert "Transcript confidence is below publication threshold." not in body_text
    assert "Source UI evidence" not in body_text
    with ZipFile(output_path) as package:
        comments_xml = package.read("word/comments.xml").decode("utf-8")
    assert "Confirm the screenshot does not include Teams controls." in comments_xml
    assert "Transcript confidence is below publication threshold." in comments_xml


def test_build_guide_docx_cleans_redundant_step_headings_and_source_recording_metadata(tmp_path: Path) -> None:
    input_path = tmp_path / "blink-draft.json"
    output_path = tmp_path / "blink-guide.docx"
    input_path.write_text(
        json.dumps(
            {
                "title": "Blink Rx User Guide",
                "summary": "Use this guide to complete the Blink Rx workflow.",
                "sourceRecording": {
                    "sourceFile": "samples/raw/Blink Rx Training Part 2 120525.mp4",
                    "targetApplication": "Blink Rx",
                    "durationSeconds": 1242,
                },
                "sections": [
                    {
                        "title": "Submit a Refill Request",
                        "steps": [
                            {
                                "title": "Step 5 — Submit a Refill Request: Step 14",
                                "instruction": "Select Submit to send the refill request.",
                                "expectedResult": "The refill request is submitted.",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(BUILD_GUIDE_DOCX_SCRIPT), str(input_path), "--output", str(output_path)],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    doc = Document(output_path)
    body_text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    table_text = "\n".join(cell.text for table in doc.tables for row in table.rows for cell in row.cells)
    assert "1. Submit a Refill Request" in body_text
    assert "Submit a Refill Request: Step 14" not in body_text
    assert "Application\nBlink Rx" in table_text
    assert "Application\nNot specified" not in table_text


def test_build_guide_docx_uses_document_metadata_from_anthropic_draft(tmp_path: Path) -> None:
    input_path = tmp_path / "document-metadata-draft.json"
    output_path = tmp_path / "document-metadata-guide.docx"
    input_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "sessionId": "blink-rx-part-2-sidecar",
                "document": {
                    "title": "Blink Rx Workflow Guide",
                    "targetApplication": "Blink Rx",
                    "durationSeconds": 1241.601,
                    "sourceRecording": "Blink Rx Training Part 2 120525.mp4",
                },
                "sections": [
                    {
                        "title": "Submit a Refill Request",
                        "steps": [
                            {
                                "title": "Initiate the refill request",
                                "instruction": "Set the refill initiation flag to true.",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(BUILD_GUIDE_DOCX_SCRIPT), str(input_path), "--output", str(output_path)],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    doc = Document(output_path)
    table_text = "\n".join(cell.text for table in doc.tables for row in table.rows for cell in row.cells)
    assert "Application\nBlink Rx" in table_text
    assert "Recording Duration\n00:20:42" in table_text
    assert "Recording Duration\n1241.601" not in table_text
    assert "Source Recording\nBlink Rx Training Part 2 120525.mp4" in table_text


def test_build_guide_docx_replaces_internal_purpose_and_prerequisite_language(tmp_path: Path) -> None:
    input_path = tmp_path / "customer-safe-draft.json"
    output_path = tmp_path / "customer-safe-guide.docx"
    input_path.write_text(
        json.dumps(
            {
                "title": "Blink Rx Workflow Guide",
                "summary": "This guide was generated from a local procedure trace.",
                "document": {
                    "description": "This guide covers refill requests and pharmacy profile plan template configuration in Blink Rx.",
                    "targetApplication": "Blink Rx",
                },
                "prerequisites": [
                    "Confirm access to the target application and review the source recording context before publishing."
                ],
                "steps": [
                    {
                        "title": "Open the refill workflow",
                        "instruction": "Open the refill request workflow.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(BUILD_GUIDE_DOCX_SCRIPT), str(input_path), "--output", str(output_path)],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    doc = Document(output_path)
    body_text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    assert "This guide covers refill requests and pharmacy profile plan template configuration in Blink Rx." in body_text
    assert "generated from a local procedure trace" not in body_text
    assert "before publishing" not in body_text
    assert "application reviewer" not in body_text
    assert "You have access to Blink Rx and the permissions needed to complete this workflow." in body_text


def test_build_guide_docx_omits_generation_metadata_from_delivered_docx(tmp_path: Path) -> None:
    input_path = tmp_path / "usage-draft.json"
    output_path = tmp_path / "usage-guide.docx"
    input_path.write_text(
        json.dumps(
            {
                "generatedAt": "2026-06-04T16:34:09Z",
                "model": "claude-sonnet-4-6",
                "usage": {
                    "input_tokens": 12847,
                    "output_tokens": 3201,
                    "totalTokens": 16048,
                    "estimatedCostUSD": 0.086,
                },
                "guideDraft": {
                    "title": "Blink Rx Workflow Guide",
                    "summary": "This guide covers refill requests in Blink Rx.",
                    "sourceRecording": {"targetApplication": "Blink Rx"},
                    "steps": [
                        {
                            "title": "Open the refill workflow",
                            "instruction": "Open the refill request workflow.",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(BUILD_GUIDE_DOCX_SCRIPT), str(input_path), "--output", str(output_path)],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    doc = Document(output_path)
    headings = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    table_text = "\n".join(cell.text for table in doc.tables for row in table.rows for cell in row.cells)
    assert "Appendix: Generation Metadata" not in headings
    assert "Input Tokens" not in table_text
    assert "Output Tokens" not in table_text
    assert "Total Tokens" not in table_text
    assert "Estimated Cost" not in table_text


def test_build_guide_docx_adds_reviewer_comments_for_ambiguous_terms_without_body_pollution(tmp_path: Path) -> None:
    input_path = tmp_path / "ambiguous-terms-draft.json"
    output_path = tmp_path / "ambiguous-terms-guide.docx"
    input_path.write_text(
        json.dumps(
            {
                "title": "Blink Rx Workflow Guide",
                "summary": "This guide covers the Blink Rx refill workflow.",
                "sourceRecording": {"targetApplication": "Blink Rx"},
                "steps": [
                    {
                        "title": "Confirm required checkbox selections",
                        "instruction": "Select all required checkboxes before choosing PV1 and PDR.",
                        "expectedResult": "The refill request is ready for review.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(BUILD_GUIDE_DOCX_SCRIPT), str(input_path), "--output", str(output_path)],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    doc = Document(output_path)
    body_text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    assert "Select all required checkboxes before choosing PV1 and PDR." in body_text
    assert "Verify that 'PV1'" not in body_text
    assert "Verify the exact required checkbox labels" not in body_text
    with ZipFile(output_path) as package:
        comments_xml = package.read("word/comments.xml").decode("utf-8")
    assert "Verify that 'PV1' is the correct UI term" in comments_xml
    assert "Verify that 'PDR' is the correct UI term" in comments_xml
    assert "Verify the exact required checkbox labels" in comments_xml


def test_build_guide_docx_routes_dark_meeting_frame_to_reviewer_comment(tmp_path: Path) -> None:
    if Image is None:
        pytest.skip("Pillow is not installed")
    image_path = tmp_path / "teams-card.png"
    Image.new("RGB", (320, 180), color=(0, 0, 0)).save(image_path)
    input_path = tmp_path / "dark-frame-draft.json"
    output_path = tmp_path / "dark-frame-guide.docx"
    input_path.write_text(
        json.dumps(
            {
                "title": "Dark Frame Guide",
                "summary": "Use this guide to complete the workflow.",
                "steps": [
                    {
                        "title": "Understand the template setting",
                        "instruction": "Review the plan template behavior.",
                        "screenshot": str(image_path),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(BUILD_GUIDE_DOCX_SCRIPT), str(input_path), "--output", str(output_path)],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    doc = Document(output_path)
    body_text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    assert "Candidate screenshot" not in body_text
    assert "No screenshot was available" not in body_text
    assert "non-application Teams or meeting frame" not in body_text
    with ZipFile(output_path) as package:
        comments_xml = package.read("word/comments.xml").decode("utf-8")
        document_xml = package.read("word/document.xml").decode("utf-8")
    assert "non-application Teams or meeting frame" in comments_xml
    assert "teams-card.png" not in document_xml


def test_build_guide_docx_preserves_detailed_review_guidance_in_comments(tmp_path: Path) -> None:
    input_path = tmp_path / "review-guidance-draft.json"
    output_path = tmp_path / "review-guidance-guide.docx"
    input_path.write_text(
        json.dumps(
            {
                "title": "Guidance Comment Guide",
                "summary": "Use this guide to complete the workflow.",
                "reviewGuidance": [
                    {
                        "id": "review-021",
                        "severity": "warning",
                        "description": "Verify segment seg-0021 because the narrator describes the pharmacy profile template quickly.",
                        "resolution": "Review the live application if the selected frame does not show the template fields.",
                    }
                ],
                "steps": [
                    {
                        "title": "Review the pharmacy profile template",
                        "instruction": "Review the pharmacy profile template fields.",
                        "expectedResult": "The profile template is ready for review.",
                        "reviewerGuidance": [
                            "Segment seg-0021 has low transcript confidence; confirm plan-template terminology before publishing."
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(BUILD_GUIDE_DOCX_SCRIPT), str(input_path), "--output", str(output_path)],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    doc = Document(output_path)
    body_text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    assert "low transcript confidence" not in body_text
    assert "review-021" not in body_text
    with ZipFile(output_path) as package:
        comments_xml = package.read("word/comments.xml").decode("utf-8")
    assert "Segment seg-0021 has low transcript confidence" in comments_xml
    assert "review-021" in comments_xml
    assert "pharmacy profile template" in comments_xml


def test_docx_builder_resolves_processed_session_frame_assets(tmp_path: Path) -> None:
    module = load_module(BUILD_GUIDE_DOCX_SCRIPT, "build_guide_docx_asset_roots")
    session_dir = tmp_path / "samples" / "processed" / "demo-session"
    image_path = session_dir / "frames" / "candidates" / "frame-0001.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"not-a-real-png")
    draft_path = tmp_path / "artifacts" / "generated" / "demo-session" / "guide_draft.json"
    draft_path.parent.mkdir(parents=True)

    resolved = module.resolve_asset_path("frames/candidates/frame-0001.png", draft_path, [session_dir])

    assert resolved == image_path.resolve()


def test_artifact_qa_reports_reviewer_comments_and_body_cleanliness(tmp_path: Path) -> None:
    input_path = tmp_path / "commented-draft.json"
    output_path = tmp_path / "commented-guide.docx"
    input_path.write_text(
        json.dumps(
            {
                "title": "Commented Guide",
                "summary": "Use this guide to complete the workflow.",
                "audience": ["Application users"],
                "workflow_overview": ["Complete the documented task."],
                "expected_results": ["The task is complete."],
                "steps": [
                    {
                        "title": "Review and save",
                        "instruction": "Review the record and select Save.",
                        "expectedResult": "The record is saved.",
                        "reviewNotes": ["Visible UI text pending local OCR should be resolved before release."],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    build = subprocess.run(
        [sys.executable, str(BUILD_GUIDE_DOCX_SCRIPT), str(input_path), "--output", str(output_path)],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert build.returncode == 0, build.stdout + build.stderr

    result = subprocess.run(
        [sys.executable, str(QA_SCRIPT), "--json", "--strict", str(output_path)],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    artifact = payload["artifacts"][0]
    assert artifact["body_clean"] is True
    assert artifact["reviewer_comment_count"] >= 1
    assert any("reviewer comments" in warning.lower() for warning in artifact["warnings"])


def test_artifact_qa_rejects_prompt_or_reasoning_leaks_in_comments(tmp_path: Path) -> None:
    input_path = tmp_path / "leaky-comment-draft.json"
    output_path = tmp_path / "leaky-comment-guide.docx"
    input_path.write_text(
        json.dumps(
            {
                "title": "Leaky Comment Guide",
                "summary": "Use this guide to complete the workflow.",
                "audience": ["Application users"],
                "workflow_overview": ["Complete the documented task."],
                "expected_results": ["The task is complete."],
                "steps": [
                    {
                        "title": "Review and save",
                        "instruction": "Review the record and select Save.",
                        "expectedResult": "The record is saved.",
                        "reviewNotes": ["The system prompt should decide this action."],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    build = subprocess.run(
        [sys.executable, str(BUILD_GUIDE_DOCX_SCRIPT), str(input_path), "--output", str(output_path)],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    assert build.returncode == 0, build.stdout + build.stderr

    result = subprocess.run(
        [sys.executable, str(QA_SCRIPT), "--json", str(output_path)],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert "Internal prompt terminology leaked." in payload["artifacts"][0]["forbidden_matches"][0]


def test_compact_procedure_trace_contract_for_one_hour_recordings(tmp_path: Path) -> None:
    trace_path = tmp_path / "procedure_trace.json"
    trace = {
        "session": {
            "app_name": "Sample Enterprise App",
            "duration_sec": 3600,
            "recorded_at": "2026-06-04T10:00:00-05:00",
        },
        "steps": [
            {
                "start": "00:02:10.000",
                "end": "00:03:05.250",
                "speaker_text": "Open the customer record and click Save.",
                "visible_ui_text": ["Customer", "Save"],
                "action_hints": ["open_record", "mouse_click"],
                "candidate_images": ["frames/frame_000130.webp"],
                "confidence": {
                    "transcript": 0.91,
                    "ocr": 0.84,
                    "frameSelection": 0.88,
                    "overall": 0.88,
                    "needsHumanReview": False,
                    "reasons": [],
                },
            }
        ],
    }
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    loaded = json.loads(trace_path.read_text(encoding="utf-8"))

    assert loaded["session"]["duration_sec"] >= 3600
    assert len(json.dumps(loaded)) < 1200
    assert loaded["steps"][0]["speaker_text"]
    assert loaded["steps"][0]["confidence"]["overall"] >= 0.75
    assert loaded["steps"][0]["visible_ui_text"] == ["Customer", "Save"]
    assert loaded["steps"][0]["candidate_images"][0].endswith(".webp")


def test_guide_draft_generator_requires_anthropic_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_module(GUIDE_DRAFT_SCRIPT, "generate_guide_draft_anthropic_required")
    trace = {
        "schemaVersion": 1,
        "recording": {
            "sourceFile": "samples/raw/example.mp4",
            "durationSeconds": 3600,
            "targetApplication": "Enterprise Rx",
            "captureMode": "imported-recording",
        },
        "segments": [
            {
                "id": "seg-0001",
                "start": "00:00:00.000",
                "end": "00:01:00.000",
                "speakerText": "I click Save to finish the record.",
                "visibleUiText": ["Save"],
                "actionHints": ["click", "save"],
                "candidateImages": [{"path": "", "timestamp": "00:00:30.000", "reason": "candidate", "reviewStatus": "pending"}],
                "confidence": {
                    "overall": 0.42,
                    "needsHumanReview": True,
                    "reasons": ["Transcript confidence is below publication threshold."],
                },
            }
        ],
    }
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY is required"):
        module.generate_with_anthropic(
            trace,
            type(
                "Args",
                (),
                {
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 100,
                    "temperature": 0.2,
                    "prompt_version": "guide-draft-v1",
                },
            )(),
        )


def test_prepare_trace_for_anthropic_prunes_rejected_frames_and_preserves_review_guidance() -> None:
    module = load_module(GUIDE_DRAFT_SCRIPT, "generate_guide_draft_prepare_trace")
    trace = {
        "schemaVersion": 1,
        "reviewGuidance": [{"type": "existing", "message": "Confirm terminology."}],
        "segments": [
            {
                "id": "seg-0001",
                "candidateImages": [
                    {
                        "frameId": "frame-approved",
                        "path": "frames/frame-approved.png",
                        "timestamp": "00:01:00.000",
                        "timestampSeconds": 60.0,
                        "created": True,
                        "reviewStatus": "approved",
                    },
                    {
                        "frameId": "frame-rejected",
                        "path": "frames/frame-rejected.png",
                        "timestamp": "00:01:30.000",
                        "timestampSeconds": 90.0,
                        "created": True,
                        "reviewStatus": "rejected",
                        "reviewNote": "Do not use this Teams title card.",
                    },
                ],
            }
        ],
    }

    prepared = module.prepare_trace_for_anthropic(trace)
    candidate_ids = [
        image["frameId"]
        for segment in prepared["segments"]
        for image in segment["candidateImages"]
    ]

    assert candidate_ids == ["frame-approved"]
    assert trace["segments"][0]["candidateImages"][1]["frameId"] == "frame-rejected"
    assert prepared["excludedFrames"][0]["frameId"] == "frame-rejected"
    assert prepared["excludedFrames"][0]["sourceSegmentId"] == "seg-0001"
    assert "Do not use this Teams title card." in json.dumps(prepared["reviewGuidance"])
    assert "Confirm terminology." in json.dumps(prepared["reviewGuidance"])


def test_anthropic_payload_excludes_rejected_frame_candidates_but_keeps_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_module(GUIDE_DRAFT_SCRIPT, "generate_guide_draft_payload_contract")
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"title": "Guide", "steps": []}),
                        }
                    ],
                    "usage": {"input_tokens": 12847, "output_tokens": 3201},
                }
            ).encode("utf-8")

    def fake_urlopen(req, timeout):
        payload = json.loads(req.data.decode("utf-8"))
        user_prompt = json.loads(payload["messages"][0]["content"])
        captured["procedureTrace"] = user_prompt["procedureTrace"]
        return FakeResponse()

    trace = {
        "sessionId": "demo-session",
        "segments": [
            {
                "id": "seg-0001",
                "candidateImages": [
                    {
                        "frameId": "keep-me",
                        "path": "frames/keep-me.png",
                        "created": True,
                        "reviewStatus": "pending",
                    },
                    {
                        "frameId": "reject-me",
                        "path": "frames/reject-me.png",
                        "created": True,
                        "reviewStatus": "rejected",
                        "reviewNote": "Rejected because it shows meeting controls.",
                    },
                ],
            }
        ],
    }
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(module.request, "urlopen", fake_urlopen)

    draft = module.generate_with_anthropic(
        trace,
        type(
            "Args",
            (),
            {
                "model": "claude-sonnet-4-6",
                "max_tokens": 100,
                "temperature": 0.2,
                "prompt_version": "guide-draft-v1",
            },
        )(),
    )

    procedure_trace = captured["procedureTrace"]
    candidate_ids = [
        image["frameId"]
        for segment in procedure_trace["segments"]
        for image in segment["candidateImages"]
    ]
    assert candidate_ids == ["keep-me"]
    assert procedure_trace["excludedFrames"][0]["frameId"] == "reject-me"
    assert "Rejected because it shows meeting controls." in json.dumps(procedure_trace["reviewGuidance"])
    assert draft["generatedAt"].endswith("Z")
    assert draft["model"]["model"] == "claude-sonnet-4-6"
    assert draft["usage"] == {
        "inputTokens": 12847,
        "outputTokens": 3201,
        "totalTokens": 16048,
        "estimatedCostUSD": 0.086556,
    }


def test_generation_report_is_written_next_to_anthropic_draft(tmp_path: Path) -> None:
    module = load_module(GUIDE_DRAFT_SCRIPT, "generate_guide_draft_generation_report")
    draft_path = tmp_path / "session" / "guide_draft.anthropic.json"
    module.USAGE_DB_PATH = tmp_path / "usage" / "generation_usage.sqlite3"
    draft_path.parent.mkdir(parents=True)
    draft = {
        "generatedAt": "2026-06-04T16:34:09Z",
        "sessionId": "demo-session",
        "document": {"title": "Blink Rx Workflow Guide"},
        "model": {
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "promptVersion": "guide-draft-v1",
        },
        "usage": {
            "inputTokens": 12847,
            "outputTokens": 3201,
            "totalTokens": 16048,
            "estimatedCostUSD": 0.086556,
        },
    }

    report_path = module.write_generation_report(draft_path, draft)

    assert report_path == draft_path.parent / "generation_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    expected = {
        "schemaVersion": 1,
        "status": "succeeded",
        "generatedAt": "2026-06-04T16:34:09Z",
        "sessionId": "demo-session",
        "title": "Blink Rx Workflow Guide",
        "model": "claude-sonnet-4-6",
        "provider": "anthropic",
        "promptVersion": "guide-draft-v1",
        "usage": {
            "inputTokens": 12847,
            "outputTokens": 3201,
            "totalTokens": 16048,
            "estimatedCostUSD": 0.086556,
        },
    }
    expected["generationRunId"] = module.generation_run_id(expected)
    assert report == expected
    with sqlite3.connect(module.USAGE_DB_PATH) as connection:
        row = connection.execute(
            """
            SELECT generation_run_id, session_id, input_tokens, output_tokens,
                   total_tokens, estimated_cost_usd, status, error_message
            FROM generation_usage
            """
        ).fetchone()
    assert row == (
        expected["generationRunId"],
        "demo-session",
        12847,
        3201,
        16048,
        0.086556,
        "succeeded",
        "",
    )


def test_anthropic_invalid_json_records_failed_usage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_module(GUIDE_DRAFT_SCRIPT, "generate_guide_draft_failed_usage")
    module.USAGE_DB_PATH = tmp_path / "usage" / "generation_usage.sqlite3"
    trace_path = tmp_path / "procedure_trace.json"
    output_path = tmp_path / "generated" / "guide_draft.anthropic.json"
    trace_path.write_text(
        json.dumps({"schemaVersion": 1, "sessionId": "failed-session", "segments": []}),
        encoding="utf-8",
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "content": [{"type": "text", "text": '{"title":"Unfinished"'}],
                    "usage": {"input_tokens": 2000, "output_tokens": 500},
                }
            ).encode("utf-8")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(module.request, "urlopen", lambda req, timeout: FakeResponse())
    monkeypatch.setattr(sys, "argv", ["generate_guide_draft.py", str(trace_path), "--output", str(output_path)])

    result = module.main()

    assert result == 1
    assert not output_path.exists()
    failure_path = output_path.parent / "generation_failure.json"
    failure = json.loads(failure_path.read_text(encoding="utf-8"))
    assert failure["status"] == "failed"
    assert failure["sessionId"] == "failed-session"
    assert failure["usage"] == {
        "inputTokens": 2000,
        "outputTokens": 500,
        "totalTokens": 2500,
        "estimatedCostUSD": 0.0135,
    }
    assert "invalid guide JSON" in failure["errorMessage"]
    with sqlite3.connect(module.USAGE_DB_PATH) as connection:
        row = connection.execute(
            """
            SELECT session_id, total_tokens, estimated_cost_usd, status, error_message
            FROM generation_usage
            """
        ).fetchone()
    assert row[0] == "failed-session"
    assert row[1] == 2500
    assert row[2] == 0.0135
    assert row[3] == "failed"
    assert "invalid guide JSON" in row[4]


def test_app_server_summarizes_generation_usage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = load_module(APP_SERVER_SCRIPT, "app_server_generation_summary")
    processed_root = tmp_path / "processed"
    generated_root = tmp_path / "generated"
    session_dir = processed_root / "demo-session"
    generated_dir = generated_root / "demo-session"
    session_dir.mkdir(parents=True)
    generated_dir.mkdir(parents=True)
    (session_dir / "manifest.json").write_text(json.dumps({"createdUtc": "2026-06-04T16:00:00Z"}), encoding="utf-8")
    (session_dir / "procedure_trace.json").write_text(
        json.dumps(
            {
                "sessionId": "demo-session",
                "recording": {"targetApplication": "Blink Rx", "durationSeconds": 1241.601},
                "segments": [],
            }
        ),
        encoding="utf-8",
    )
    (generated_dir / "generation_report.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "generatedAt": "2026-06-04T16:34:09Z",
                "model": "claude-sonnet-4-6",
                "provider": "anthropic",
                "promptVersion": "guide-draft-v1",
                "usage": {
                    "inputTokens": 12847,
                    "outputTokens": 3201,
                    "totalTokens": 16048,
                    "estimatedCostUSD": 0.086556,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "PROCESSED_ROOT", processed_root)
    monkeypatch.setattr(module, "GENERATED_ROOT", generated_root)
    monkeypatch.setattr(module, "WORKSPACE", tmp_path)

    session = module.read_session(session_dir)

    assert session["generation"] == {
        "model": "claude-sonnet-4-6",
        "provider": "anthropic",
        "promptVersion": "guide-draft-v1",
        "generatedAt": "2026-06-04T16:34:09Z",
        "inputTokens": 12847,
        "outputTokens": 3201,
        "totalTokens": 16048,
        "estimatedCostUSD": 0.086556,
        "status": "succeeded",
        "errorMessage": "",
    }


def test_process_recording_accepts_sidecar_transcript_without_media_tools(tmp_path: Path) -> None:
    recording = tmp_path / "sample.mp4"
    transcript = tmp_path / "sample-transcript.txt"
    output_root = tmp_path / "processed"
    session_id = "sidecar-demo"
    recording.write_bytes(b"not a real video")
    transcript.write_text(
        "Open the customer record. Click Save after reviewing the address. Confirm the success message.",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(PROCESS_RECORDING_SCRIPT),
            str(recording),
            "--no-media-tools",
            "--transcript",
            str(transcript),
            "--output-root",
            str(output_root),
            "--session-id",
            session_id,
            "--target-application",
            "Enterprise Rx",
            "--assume-duration-seconds",
            "120",
            "--segment-seconds",
            "60",
            "--max-frames",
            "4",
        ],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    session_dir = output_root / session_id
    transcript_payload = json.loads((session_dir / "transcript.json").read_text(encoding="utf-8"))
    trace_payload = json.loads((session_dir / "procedure_trace.json").read_text(encoding="utf-8"))

    assert transcript_payload["source"] == "sidecar-transcript"
    assert len(transcript_payload["segments"]) == 2
    assert all(segment["source"] == "sidecar-transcript" for segment in transcript_payload["segments"])
    assert "Click Save" in " ".join(segment["text"] for segment in transcript_payload["segments"])
    assert trace_payload["recording"]["targetApplication"] == "Enterprise Rx"
    assert len(trace_payload["segments"]) == 2
    assert trace_payload["segments"][0]["confidence"]["transcript"] >= 0.7
    assert trace_payload["segments"][0]["confidence"]["ocr"] < 0.7
    assert trace_payload["segments"][0]["confidence"]["frameSelection"] < 0.7
    assert trace_payload["segments"][0]["confidence"]["needsHumanReview"] is True


def test_caption_parser_ignores_teams_cue_ids_and_voice_tags() -> None:
    module = load_module(PROCESS_RECORDING_SCRIPT, "process_recording_caption_parser")
    raw_text = """WEBVTT

724b054c-5275-4678-b67e-a50dcb6dc1a2/45-0
00:00:12.796 --> 00:00:18.129
<v Tina Drake>And today we're going to cover the last
of Blink. Um,</v>

724b054c-5275-4678-b67e-a50dcb6dc1a2/45-1
00:00:18.129 --> 00:00:23.956
<v Tina Drake>so you know she's going to run through
what was remaining.</v>
"""

    segments = module.parse_caption_transcript(raw_text)

    assert len(segments) == 2
    assert segments[0]["text"] == "And today we're going to cover the last of Blink. Um,"
    assert segments[1]["text"] == "so you know she's going to run through what was remaining."
    assert "724b054c" not in " ".join(segment["text"] for segment in segments)
    assert "<v" not in " ".join(segment["text"] for segment in segments)


def test_timed_transcript_segments_are_bucketed_across_recording() -> None:
    module = load_module(PROCESS_RECORDING_SCRIPT, "process_recording_timed_buckets")

    chunks = module.split_source_segments(
        [
            {"text": "Open the first screen.", "startSeconds": 5.0, "endSeconds": 9.0, "confidence": 0.9},
            {"text": "Review the middle workflow.", "startSeconds": 75.0, "endSeconds": 90.0, "confidence": 0.8},
            {"text": "Confirm the final result.", "startSeconds": 125.0, "endSeconds": 135.0, "confidence": 0.7},
        ],
        count=3,
        duration=180.0,
        segment_seconds=60.0,
    )

    assert [chunk["text"] for chunk in chunks] == [
        "Open the first screen.",
        "Review the middle workflow.",
        "Confirm the final result.",
    ]
    assert chunks[0]["startSeconds"] == 0.0
    assert chunks[2]["endSeconds"] == 180.0


def test_compare_transcripts_reports_overlap_and_examples() -> None:
    module = load_module(COMPARE_TRANSCRIPTS_SCRIPT, "compare_transcripts_metrics")

    report = module.compare_transcripts(
        {
            "source": "sidecar-transcript",
            "segments": [
                {"id": "tx-0001", "startSeconds": 0, "endSeconds": 60, "confidence": 0.78, "text": "Open the refill request."},
                {"id": "tx-0002", "startSeconds": 60, "endSeconds": 120, "confidence": 0.78, "text": "Click submit to save."},
            ],
        },
        {
            "source": "local-whisper",
            "segments": [
                {"id": "tx-0001", "startSeconds": 0, "endSeconds": 60, "confidence": 0.88, "text": "Open the refill request."},
                {"id": "tx-0002", "startSeconds": 60, "endSeconds": 120, "confidence": 0.6, "text": "Click save."},
            ],
        },
        example_count=1,
    )

    assert report["reference"]["source"] == "sidecar-transcript"
    assert report["candidate"]["source"] == "local-whisper"
    assert report["comparison"]["wordOverlap"] > 0.5
    assert report["comparison"]["averageAlignedSimilarity"] > 0.7
    assert len(report["examples"]) == 1


def test_whisper_json_segments_include_offsets_and_confidence() -> None:
    module = load_module(PROCESS_RECORDING_SCRIPT, "process_recording_whisper_parser")
    payload = {
        "result": {"language": "en"},
        "transcription": [
            {
                "offsets": {"from": 1200, "to": 5400},
                "text": " Click Save to finish the workflow.",
                "tokens": [
                    {"text": "[_BEG_]", "p": 0.1},
                    {"text": " Click", "p": 0.9},
                    {"text": " Save", "p": 0.8},
                    {"text": ".", "p": 0.7},
                ],
            }
        ],
    }

    segments = module.parse_whisper_transcript(payload)

    assert segments == [
        {
            "id": "whisper-0001",
            "text": "Click Save to finish the workflow.",
            "startSeconds": 1.2,
            "endSeconds": 5.4,
            "confidence": 0.8,
            "speaker": "Speaker 1",
        }
    ]


def test_build_transcript_prefers_local_whisper_when_no_sidecar() -> None:
    module = load_module(PROCESS_RECORDING_SCRIPT, "process_recording_whisper_transcript")
    transcript = module.build_transcript(
        metadata={"durationSeconds": 30.0},
        sidecar_transcript=None,
        local_transcript={
            "source": "local-whisper",
            "name": "whisper-transcript.json",
            "path": "audio/whisper-transcript.json",
            "format": "json",
            "model": "models/whisper/ggml-base.en.bin",
            "language": "en",
            "error": None,
            "segments": [
                {
                    "text": "Open the order screen and select New.",
                    "startSeconds": 0.0,
                    "endSeconds": 12.0,
                    "confidence": 0.87,
                    "speaker": "Speaker 1",
                }
            ],
        },
        segment_seconds=60.0,
        target_application="Enterprise Rx",
    )

    assert transcript["source"] == "local-whisper"
    assert transcript["sourceTranscript"]["source"] == "local-whisper"
    assert transcript["sourceTranscript"]["path"] == "audio/whisper-transcript.json"
    assert transcript["segments"][0]["source"] == "local-whisper"
    assert transcript["segments"][0]["confidence"] == 0.87
    assert "Open the order screen" in transcript["segments"][0]["text"]


def test_teams_recording_profile_skips_intro_and_crops_frames() -> None:
    module = load_module(PROCESS_RECORDING_SCRIPT, "process_recording_teams_profile")
    args = type("Args", (), {"source_profile": "teams-recording", "skip_start_seconds": None, "frame_crop_filter": None})()

    assert module.effective_skip_start_seconds(args) == 60.0
    assert module.build_frame_crop_filter(args).startswith("crop=")
    assert module.planned_frame_timestamps(300.0, 30.0, 3, start_seconds=60.0) == [60.0, 90.0, 120.0]


def test_generate_draft_attaches_screenshot_references_to_model_steps() -> None:
    module = load_module(GUIDE_DRAFT_SCRIPT, "generate_guide_draft_screenshots")
    draft = {
        "sections": [
            {
                "title": "Approve Fax",
                "steps": [
                    {
                        "instruction": "Select the fax row.",
                        "sourceSegments": ["seg-0002"],
                    }
                ],
            }
        ]
    }
    trace = {
        "sessionId": "demo-session",
        "segments": [
            {
                "id": "seg-0002",
                "candidateImages": [
                    {
                        "frameId": "frame-0002",
                        "path": "frames/candidates/frame-0002.jpg",
                        "timestamp": "00:01:00.000",
                        "timestampSeconds": 60.0,
                        "score": 0.81,
                        "created": True,
                        "reviewStatus": "pending",
                    }
                ],
            }
        ],
    }

    enriched = module.attach_screenshot_references(draft, trace)
    step = enriched["sections"][0]["steps"][0]

    assert step["screenshotRef"] == "frame-0002"
    assert step["selectedScreenshot"]["frameId"] == "frame-0002"
    assert step["selectedScreenshot"]["path"].endswith("samples/processed/demo-session/frames/candidates/frame-0002.jpg")


def test_generate_draft_distributes_screenshots_when_model_omits_source_segments() -> None:
    module = load_module(GUIDE_DRAFT_SCRIPT, "generate_guide_draft_screenshot_distribution")
    draft = {
        "steps": [
            {"instruction": "First action."},
            {"instruction": "Second action."},
            {"instruction": "Third action."},
        ]
    }
    trace = {
        "sessionId": "demo-session",
        "segments": [
            {
                "id": "seg-0001",
                "candidateImages": [
                    {
                        "frameId": "frame-0001",
                        "path": "frames/candidates/frame-0001.jpg",
                        "timestampSeconds": 60.0,
                        "score": 0.7,
                        "created": True,
                    }
                ],
            },
            {
                "id": "seg-0002",
                "candidateImages": [
                    {
                        "frameId": "frame-0002",
                        "path": "frames/candidates/frame-0002.jpg",
                        "timestampSeconds": 120.0,
                        "score": 0.7,
                        "created": True,
                    }
                ],
            },
            {
                "id": "seg-0003",
                "candidateImages": [
                    {
                        "frameId": "frame-0003",
                        "path": "frames/candidates/frame-0003.jpg",
                        "timestampSeconds": 180.0,
                        "score": 0.7,
                        "created": True,
                    }
                ],
            },
        ],
    }

    enriched = module.attach_screenshot_references(draft, trace)

    assert [step["screenshotRef"] for step in enriched["steps"]] == ["frame-0001", "frame-0002", "frame-0003"]


def test_generate_draft_applies_frame_review_file_to_trace(tmp_path: Path) -> None:
    module = load_module(GUIDE_DRAFT_SCRIPT, "generate_guide_draft_frame_review")
    trace_path = tmp_path / "procedure_trace.json"
    (tmp_path / "frame_scores.json").write_text(
        json.dumps(
            {
                "frames": [
                    {
                        "id": "review-frame-0001",
                        "path": "frames/candidates/review-frame-0001.png",
                        "webPath": "frames/candidates/review-frame-0001.png",
                        "timestamp": "00:02:00.000",
                        "timestampSeconds": 120.0,
                        "score": 0.9,
                        "created": True,
                        "selectionReason": "Added by reviewer.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "frame_review.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "frames": {
                    "frame-0001": {"status": "rejected", "note": "Teams title card."},
                    "review-frame-0001": {
                        "status": "approved",
                        "note": "Use this dialog.",
                        "assignedSegmentId": "seg-0001",
                        "addedByReviewer": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    trace = {
        "sessionId": "review-demo",
        "segments": [
            {
                "id": "seg-0001",
                "candidateImages": [
                    {
                        "frameId": "frame-0001",
                        "path": "frames/candidates/frame-0001.png",
                        "timestampSeconds": 30.0,
                        "score": 0.7,
                        "created": True,
                        "reviewStatus": "pending",
                    }
                ],
            }
        ],
    }
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    reviewed = module.apply_frame_review(trace, trace_path)
    images = reviewed["segments"][0]["candidateImages"]

    assert images[0]["reviewStatus"] == "rejected"
    assert images[0]["reviewNote"] == "Teams title card."
    assert images[1]["frameId"] == "review-frame-0001"
    assert images[1]["reviewStatus"] == "approved"
    assert images[1]["reviewNote"] == "Use this dialog."


@pytest.mark.parametrize(
    "relative_path",
    [
        "scripts/process_recording.py",
        "scripts/build_guide_docx.py",
        "scripts/generate_guide_draft.py",
    ],
)
def test_future_prototype_scripts_have_smoke_test_hooks(relative_path: str) -> None:
    script = ROOT / relative_path
    if not script.exists():
        pytest.skip(f"{relative_path} is not implemented yet")

    help_result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert help_result.returncode == 0
    help_text = help_result.stdout + help_result.stderr
    assert ("--input" in help_text or "recording" in help_text or "trace" in help_text)
    assert ("--output" in help_text or "--output-root" in help_text)
    if relative_path.endswith("process_recording.py"):
        assert "--no-media-tools" in help_text
        assert "--whisper-model" in help_text
        assert "--no-local-stt" in help_text
