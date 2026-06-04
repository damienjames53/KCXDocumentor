from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest
from docx import Document


ROOT = Path(__file__).resolve().parents[1]
QA_SCRIPT = ROOT / "scripts" / "qa_document_artifacts.py"
DOCX_HELPER = ROOT / "tools" / "document_lib" / "keycentrix_docx.py"
GUIDE_DRAFT_SCRIPT = ROOT / "scripts" / "generate_guide_draft.py"
PROCESS_RECORDING_SCRIPT = ROOT / "scripts" / "process_recording.py"
BUILD_GUIDE_DOCX_SCRIPT = ROOT / "scripts" / "build_guide_docx.py"
COMPARE_TRANSCRIPTS_SCRIPT = ROOT / "scripts" / "compare_transcripts.py"


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


def test_deterministic_guide_draft_generator_preserves_review_flags(tmp_path: Path) -> None:
    trace_path = tmp_path / "procedure_trace.json"
    output_path = tmp_path / "guide_draft.json"
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
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(GUIDE_DRAFT_SCRIPT), str(trace_path), "--output", str(output_path)],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    draft = json.loads(output_path.read_text(encoding="utf-8"))
    assert draft["model"]["provider"] == "local-deterministic"
    assert draft["model"]["promptVersion"] == "guide-draft-v1"
    assert draft["steps"][0]["instruction"].startswith("Click Save")
    assert draft["steps"][0]["needsHumanReview"] is True
    assert draft["reviewFlags"][0]["segmentId"] == "seg-0001"


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
