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
            }
        ],
    }
    trace_path.write_text(json.dumps(trace), encoding="utf-8")

    loaded = json.loads(trace_path.read_text(encoding="utf-8"))

    assert loaded["session"]["duration_sec"] >= 3600
    assert len(json.dumps(loaded)) < 1200
    assert loaded["steps"][0]["speaker_text"]
    assert loaded["steps"][0]["visible_ui_text"] == ["Customer", "Save"]
    assert loaded["steps"][0]["candidate_images"][0].endswith(".webp")


@pytest.mark.parametrize(
    "relative_path",
    [
        "scripts/process_recording.py",
        "scripts/build_guide_docx.py",
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
    assert ("--input" in help_text or "recording" in help_text)
    assert ("--output" in help_text or "--output-root" in help_text)
    if relative_path.endswith("process_recording.py"):
        assert "--no-media-tools" in help_text
