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
