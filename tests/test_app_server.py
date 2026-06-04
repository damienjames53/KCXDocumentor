from __future__ import annotations

import importlib.util
import inspect
import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_SERVER = ROOT / "scripts" / "app_server.py"


def load_app_server():
    if not APP_SERVER.exists():
        pytest.skip("scripts/app_server.py is not implemented yet")

    spec = importlib.util.spec_from_file_location("kcx_app_server_test", APP_SERVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["kcx_app_server_test"] = module
    spec.loader.exec_module(module)
    return module


def find_callable(module: Any, *names: str):
    for name in names:
        candidate = getattr(module, name, None)
        if callable(candidate):
            return candidate
    pytest.skip(f"app server does not expose any of: {', '.join(names)}")


def find_optional_callable(module: Any, *names: str):
    for name in names:
        candidate = getattr(module, name, None)
        if callable(candidate):
            return candidate
    return None


class FakeHandler:
    def __init__(self) -> None:
        self.status: int | None = None
        self.headers: list[tuple[str, str]] = []
        self.wfile = io.BytesIO()

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, key: str, value: str) -> None:
        self.headers.append((key, value))

    def end_headers(self) -> None:
        pass


def invoke_with_supported_kwargs(func: Any, *args: Any, **kwargs: Any) -> Any:
    signature = inspect.signature(func)
    supported = {
        key: value
        for key, value in kwargs.items()
        if key in signature.parameters
    }
    return func(*args, **supported)


def test_json_response_helper_writes_minimal_http_response() -> None:
    module = load_app_server()
    helper = find_callable(module, "send_json", "write_json", "write_json_response")
    handler = FakeHandler()

    invoke_with_supported_kwargs(
        helper,
        handler,
        {"ok": True, "message": "ready"},
        status=202,
        status_code=202,
    )

    assert handler.status == 202
    headers = dict(handler.headers)
    assert headers.get("Content-Type", "").startswith("application/json")
    assert "no-store" in headers.get("Cache-Control", "").lower()
    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert payload == {"ok": True, "message": "ready"}


def test_json_response_builder_is_utf8_bytes_when_exposed() -> None:
    module = load_app_server()
    builder = find_callable(module, "build_json_response", "json_response_bytes")

    response = builder({"status": "ok", "application": "Enterprise Rx"})

    assert isinstance(response, bytes)
    assert json.loads(response.decode("utf-8")) == {
        "status": "ok",
        "application": "Enterprise Rx",
    }


def test_safe_path_helper_accepts_children_and_rejects_traversal(tmp_path: Path) -> None:
    module = load_app_server()
    safe_path = find_callable(module, "safe_join", "resolve_safe_path", "safe_resolve")
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "samples").mkdir()
    (root / "samples" / "demo.mp4").write_bytes(b"placeholder")

    resolved = safe_path(root, "samples/demo.mp4")

    assert Path(resolved).resolve() == (root / "samples" / "demo.mp4").resolve()
    with pytest.raises((PermissionError, ValueError)):
        safe_path(root, "../outside.txt")
    with pytest.raises((PermissionError, ValueError)):
        safe_path(root, str(tmp_path / "outside.txt"))


def test_app_state_lists_processed_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_app_server()
    processed_root = tmp_path / "samples" / "processed"
    session_dir = processed_root / "session-a"
    session_dir.mkdir(parents=True)
    (session_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "sessionId": "session-a",
                "sourceFile": "samples/raw/example.mp4",
                "outputs": {"procedureTrace": "procedure_trace.json"},
            },
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "PROCESSED_ROOT", processed_root)
    monkeypatch.setattr(module, "GENERATED_ROOT", tmp_path / "artifacts" / "generated")

    sessions = module.list_sessions()

    assert len(sessions) == 1
    assert sessions[0]["sessionId"] == "session-a"
    assert sessions[0]["segmentCount"] is None


def test_processing_command_builder_uses_python_and_no_media_tools_when_requested(tmp_path: Path) -> None:
    module = load_app_server()
    builder = find_callable(module, "build_process_command", "build_processing_command")
    recording = tmp_path / "samples" / "raw" / "example.mp4"
    recording.parent.mkdir(parents=True)
    recording.write_bytes(b"placeholder")

    command = invoke_with_supported_kwargs(
        builder,
        recording,
        repo_root=ROOT,
        output_root=tmp_path / "samples" / "processed",
        session_id="demo-session",
        target_application="Enterprise Rx",
        no_media_tools=True,
    )

    command_text = " ".join(str(part) for part in command)
    assert str(APP_SERVER.parent / "process_recording.py") in command_text
    assert "--session-id" in command
    assert "demo-session" in command
    assert "--target-application" in command
    assert "Enterprise Rx" in command
    assert "--no-media-tools" in command
    assert command[0] == sys.executable or command[0].endswith("python") or command[0].endswith("python3")


def test_recording_import_helper_copies_to_raw_root_without_path_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_app_server()
    importer = find_optional_callable(module, "import_recording", "copy_imported_recording", "save_uploaded_recording")
    if importer is None:
        pytest.skip("app server does not expose a recording import/upload helper yet")

    raw_root = tmp_path / "samples" / "raw"
    raw_root.mkdir(parents=True)
    source = tmp_path / "source" / "training clip.mp4"
    source.parent.mkdir()
    source.write_bytes(b"fake video bytes")
    monkeypatch.setattr(module, "RAW_ROOT", raw_root)

    result = invoke_with_supported_kwargs(importer, source, raw_root=raw_root, filename="training clip.mp4")
    imported_path = Path(result["path"] if isinstance(result, dict) and "path" in result else result)

    assert imported_path.resolve().parent == raw_root.resolve()
    assert imported_path.name.endswith(".mp4")
    assert imported_path.read_bytes() == b"fake video bytes"

    outside = tmp_path / "outside.mp4"
    with pytest.raises((PermissionError, ValueError, module.HttpError if hasattr(module, "HttpError") else Exception)):
        invoke_with_supported_kwargs(importer, source, raw_root=raw_root, filename="../outside.mp4")
    assert not outside.exists()


def test_transcript_command_builder_includes_sidecar_when_helper_supports_it(tmp_path: Path) -> None:
    module = load_app_server()
    builder = find_callable(module, "build_process_command", "build_processing_command")
    if "transcript" not in inspect.signature(builder).parameters and "transcript_path" not in inspect.signature(builder).parameters:
        pytest.skip("process command builder does not expose transcript sidecar support yet")

    recording = tmp_path / "samples" / "raw" / "example.mp4"
    transcript = tmp_path / "samples" / "raw" / "example.txt"
    recording.parent.mkdir(parents=True)
    recording.write_bytes(b"placeholder")
    transcript.write_text("Click Save to finish the workflow.", encoding="utf-8")

    command = invoke_with_supported_kwargs(
        builder,
        recording,
        repo_root=ROOT,
        output_root=tmp_path / "samples" / "processed",
        session_id="demo-session",
        target_application="Enterprise Rx",
        no_media_tools=True,
        transcript=transcript,
        transcript_path=transcript,
    )

    command_text = " ".join(str(part) for part in command)
    assert "--transcript" in command
    assert str(transcript) in command_text


def test_processing_command_builder_can_enable_teams_recording_profile(tmp_path: Path) -> None:
    module = load_app_server()
    builder = find_callable(module, "build_process_command", "build_processing_command")
    recording = tmp_path / "samples" / "raw" / "teams.mp4"
    recording.parent.mkdir(parents=True)
    recording.write_bytes(b"placeholder")

    command = invoke_with_supported_kwargs(
        builder,
        recording,
        repo_root=ROOT,
        output_root=tmp_path / "samples" / "processed",
        target_application="SendKey",
        source_profile="teams-recording",
    )

    assert "--source-profile" in command
    assert "teams-recording" in command


def test_health_or_tooling_helper_reports_expected_local_dependencies() -> None:
    module = load_app_server()
    checker = find_optional_callable(module, "get_health", "health_check", "check_tooling", "get_tooling_status")
    if checker is None:
        pytest.skip("app server does not expose a health/tooling helper yet")

    status = checker()

    assert isinstance(status, dict)
    serialized = json.dumps(status).lower()
    assert "ffmpeg" in serialized
    assert "ffprobe" in serialized
    assert "whisper" in serialized
    assert "modelavailable" in serialized
    if "anthropic" in serialized or "api" in serialized:
        assert "sk-ant-" not in serialized
    assert "ok" in status or "ready" in status or "tools" in status or "dependencies" in status


def test_frame_review_actions_persist_and_merge_into_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_app_server()
    processed_root = tmp_path / "samples" / "processed"
    session_dir = processed_root / "review-session"
    session_dir.mkdir(parents=True)
    (session_dir / "manifest.json").write_text(json.dumps({"schemaVersion": 1, "sessionId": "review-session"}), encoding="utf-8")
    (session_dir / "frame_scores.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "frames": [
                    {
                        "id": "frame-0001",
                        "timestampSeconds": 12.0,
                        "timestamp": "00:12",
                        "path": "frames/candidates/frame-0001.png",
                        "webPath": "frames/candidates/frame-0001.png",
                        "created": True,
                        "score": 0.8,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (session_dir / "procedure_trace.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "segments": [
                    {
                        "id": "seg-0001",
                        "candidateImages": [
                            {
                                "frameId": "frame-0001",
                                "reviewStatus": "pending",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "PROCESSED_ROOT", processed_root)
    monkeypatch.setattr(module, "GENERATED_ROOT", tmp_path / "artifacts" / "generated")

    result = module.update_frame_review(
        {
            "sessionId": "review-session",
            "frameId": "frame-0001",
            "action": "approve",
            "note": "Good application state.",
            "assignedSegmentId": "seg-0001",
        }
    )

    assert result["frameReview"]["summary"]["approved"] == 1
    review_file = json.loads((session_dir / "frame_review.json").read_text(encoding="utf-8"))
    assert review_file["frames"]["frame-0001"]["status"] == "approved"
    assert review_file["frames"]["frame-0001"]["note"] == "Good application state."
    assert review_file["frames"]["frame-0001"]["assignedSegmentId"] == "seg-0001"

    session = module.read_session(session_dir)
    image = session["procedureTrace"]["segments"][0]["candidateImages"][0]
    assert image["reviewStatus"] == "approved"
    assert image["reviewNote"] == "Good application state."
    assert session["frameReview"]["frames"][0]["assignedSegmentId"] == "seg-0001"


def test_frame_review_accepts_ui_status_and_review_note_aliases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_app_server()
    processed_root = tmp_path / "samples" / "processed"
    session_dir = processed_root / "review-session"
    session_dir.mkdir(parents=True)
    (session_dir / "frame_scores.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "frames": [
                    {
                        "id": "frame-0001",
                        "timestampSeconds": 12.0,
                        "path": "frames/candidates/frame-0001.png",
                        "created": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "PROCESSED_ROOT", processed_root)

    module.update_frame_review(
        {
            "sessionId": "review-session",
            "frameId": "frame-0001",
            "reviewStatus": "approved",
            "reviewNote": "Use this screenshot in the guide.",
            "assignedSegmentId": "seg-0001",
        }
    )

    review_file = json.loads((session_dir / "frame_review.json").read_text(encoding="utf-8"))
    assert review_file["frames"]["frame-0001"]["status"] == "approved"
    assert review_file["frames"]["frame-0001"]["note"] == "Use this screenshot in the guide."
    assert review_file["frames"]["frame-0001"]["assignedSegmentId"] == "seg-0001"


def test_frame_review_rejects_unknown_or_unsafe_frame_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_app_server()
    processed_root = tmp_path / "samples" / "processed"
    session_dir = processed_root / "review-session"
    session_dir.mkdir(parents=True)
    (session_dir / "frame_scores.json").write_text(json.dumps({"schemaVersion": 1, "frames": []}), encoding="utf-8")
    monkeypatch.setattr(module, "PROCESSED_ROOT", processed_root)

    with pytest.raises(module.HttpError):
        module.update_frame_review({"sessionId": "review-session", "frameId": "../frame", "action": "approve"})
    with pytest.raises(module.HttpError):
        module.update_frame_review({"sessionId": "review-session", "frameId": "frame-9999", "action": "approve"})


def test_extract_review_frame_adds_candidate_and_review_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_app_server()
    processed_root = tmp_path / "samples" / "processed"
    session_dir = processed_root / "extract-session"
    session_dir.mkdir(parents=True)
    source = tmp_path / "samples" / "raw" / "demo.mov"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fake video")
    (session_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "sessionId": "extract-session",
                "sourceFile": str(source),
                "processing": {"frameCropFilter": "crop=iw:ih:0:0"},
            }
        ),
        encoding="utf-8",
    )
    (session_dir / "frame_scores.json").write_text(json.dumps({"schemaVersion": 1, "frames": []}), encoding="utf-8")
    monkeypatch.setattr(module, "PROCESSED_ROOT", processed_root)
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)

    def fake_run_command(command: list[str]) -> dict[str, Any]:
        Path(command[-1]).write_bytes(b"png")
        return {"returnCode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(module, "run_command", fake_run_command)

    result = module.extract_review_frame(
        {
            "sessionId": "extract-session",
            "timestamp": "01:02",
            "frameId": "review-frame-0007",
            "reviewStatus": "approved",
            "reviewNote": "Use this dialog.",
            "segmentId": "seg-0002",
        }
    )

    assert result["frame"]["id"] == "review-frame-0007"
    assert result["frame"]["timestampSeconds"] == 62.0
    assert (session_dir / "frames" / "candidates" / "review-frame-0007.png").read_bytes() == b"png"
    frame_scores = json.loads((session_dir / "frame_scores.json").read_text(encoding="utf-8"))
    assert frame_scores["frames"][0]["source"] == "manual-review-extract"
    assert frame_scores["frames"][0]["cropFilter"] == "crop=iw:ih:0:0"
    review = json.loads((session_dir / "frame_review.json").read_text(encoding="utf-8"))
    assert review["frames"]["review-frame-0007"]["status"] == "approved"
    assert review["frames"]["review-frame-0007"]["note"] == "Use this dialog."
    assert review["frames"]["review-frame-0007"]["assignedSegmentId"] == "seg-0002"
