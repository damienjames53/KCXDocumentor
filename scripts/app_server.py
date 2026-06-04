#!/usr/bin/env python3
"""Local stdlib HTTP API for KCXDocumentor prototype testing."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


WORKSPACE = Path(__file__).resolve().parents[1]
WEB_ROOT = WORKSPACE / "web"
RAW_ROOT = WORKSPACE / "samples" / "raw"
PROCESSED_ROOT = WORKSPACE / "samples" / "processed"
GENERATED_ROOT = WORKSPACE / "artifacts" / "generated"
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,180}$")
RECORDING_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".wmv", ".m4v"}
TRANSCRIPT_EXTENSIONS = {".txt", ".vtt", ".srt", ".json"}
MULTIPART_MAX_BYTES = 3 * 1024 * 1024 * 1024
REDACTION_PATTERNS = [
    re.compile(r"(?i)(anthropic[_-]?api[_-]?key\s*[=:]\s*)[^\s\"']+"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]+"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local KCXDocumentor prototype app server.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface. Defaults to 127.0.0.1.")
    parser.add_argument("--port", type=int, default=8765, help="Port. Defaults to 8765.")
    args = parser.parse_args()

    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    PROCESSED_ROOT.mkdir(parents=True, exist_ok=True)
    GENERATED_ROOT.mkdir(parents=True, exist_ok=True)

    server = ThreadingHTTPServer((args.host, args.port), KCXDocumentorHandler)
    print(f"KCXDocumentor local app server listening on http://{args.host}:{args.port}")
    print("Serving static files from web/ and JSON APIs under /api/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping KCXDocumentor local app server.")
    finally:
        server.server_close()
    return 0


class KCXDocumentorHandler(BaseHTTPRequestHandler):
    server_version = "KCXDocumentorLocal/0.1"

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/recordings":
                self.send_json({"recordings": list_recordings()})
                return
            if parsed.path == "/api/transcripts":
                self.send_json({"transcripts": list_transcripts()})
                return
            if parsed.path == "/api/sessions":
                self.send_json({"sessions": list_sessions()})
                return
            if parsed.path == "/api/health":
                self.send_json(get_health())
                return
            if parsed.path == "/api/session":
                params = parse_qs(parsed.query)
                session_id = first_query_value(params, "sessionId")
                session_dir = require_session_dir(session_id)
                asset = first_query_value(params, "asset")
                if asset:
                    self.serve_session_asset(session_dir, asset)
                    return
                self.send_json({"session": read_session(session_dir)})
                return
            self.serve_static(parsed.path)
        except HttpError as exc:
            self.send_json({"error": exc.message}, status=exc.status)
        except Exception as exc:
            self.send_json({"error": f"Unexpected server error: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/import-recording":
                self.send_json(import_upload(self, kind="recording"))
                return
            if parsed.path == "/api/import-transcript":
                self.send_json(import_upload(self, kind="transcript"))
                return
            body = self.read_json_body()
            if parsed.path == "/api/process":
                self.send_json(process_recording(body))
                return
            if parsed.path == "/api/generate-draft":
                self.send_json(generate_draft(body))
                return
            if parsed.path == "/api/build-docx":
                self.send_json(build_docx(body))
                return
            if parsed.path == "/api/qa-docx":
                self.send_json(qa_docx(body))
                return
            raise HttpError(HTTPStatus.NOT_FOUND, "Unknown API endpoint.")
        except HttpError as exc:
            self.send_json({"error": exc.message}, status=exc.status)
        except json.JSONDecodeError:
            self.send_json({"error": "Request body must be valid JSON."}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"error": f"Unexpected server error: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise HttpError(HTTPStatus.BAD_REQUEST, "Request body must be a JSON object.")
        return payload

    def serve_static(self, raw_path: str) -> None:
        if raw_path in ("", "/"):
            raw_path = "/index.html"
        relative = unquote(raw_path).lstrip("/")
        if not relative:
            relative = "index.html"
        candidate = (WEB_ROOT / relative).resolve()
        if not is_relative_to(candidate, WEB_ROOT) or not candidate.is_file():
            raise HttpError(HTTPStatus.NOT_FOUND, "Static file not found.")

        content_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        data = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = build_json_response(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def serve_session_asset(self, session_dir: Path, raw_asset: str) -> None:
        candidate = safe_join(session_dir, raw_asset)
        if not candidate.is_file():
            generated_candidate = safe_join(GENERATED_ROOT / session_dir.name, raw_asset)
            candidate = generated_candidate if generated_candidate.is_file() else candidate
        if not candidate.is_file():
            raise HttpError(HTTPStatus.NOT_FOUND, "Session asset not found.")

        content_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        data = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args: Any) -> None:
        message = redact(fmt % args)
        sys.stderr.write(f"{self.address_string()} - {message}\n")


class HttpError(Exception):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def list_recordings() -> list[dict[str, Any]]:
    recordings = []
    for path in sorted(RAW_ROOT.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file() or path.name.startswith(".") or path.suffix.lower() not in RECORDING_EXTENSIONS:
            continue
        recordings.append(describe_raw_file(path))
    return recordings


def list_transcripts() -> list[dict[str, Any]]:
    transcripts = []
    for path in sorted(RAW_ROOT.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file() or path.name.startswith(".") or path.suffix.lower() not in TRANSCRIPT_EXTENSIONS:
            continue
        transcripts.append(describe_raw_file(path))
    return transcripts


def describe_raw_file(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "relativePath": str(path.relative_to(RAW_ROOT)),
        "sizeBytes": stat.st_size,
        "modifiedUtc": utc_from_timestamp(stat.st_mtime),
        "extension": path.suffix.lower(),
    }


def get_health() -> dict[str, Any]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    whisper = shutil.which("whisper-cli")
    whisper_model = WORKSPACE / "models" / "whisper" / "ggml-base.en.bin"
    return {
        "status": "ok",
        "workspace": str(WORKSPACE),
        "rawRoot": relative_to_workspace(RAW_ROOT),
        "processedRoot": relative_to_workspace(PROCESSED_ROOT),
        "generatedRoot": relative_to_workspace(GENERATED_ROOT),
        "tools": {
            "ffmpeg": {
                "available": bool(ffmpeg),
                "path": ffmpeg,
            },
            "ffprobe": {
                "available": bool(ffprobe),
                "path": ffprobe,
            },
            "whisper": {
                "available": bool(whisper),
                "path": whisper,
                "modelAvailable": whisper_model.exists(),
                "modelPath": relative_to_workspace(whisper_model),
            },
        },
    }


def list_sessions() -> list[dict[str, Any]]:
    sessions = []
    for path in sorted(PROCESSED_ROOT.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        sessions.append(summarize_session(path))
    return sessions


def process_recording(body: dict[str, Any]) -> dict[str, Any]:
    recording = require_recording_path(body.get("recording"))
    transcript = optional_transcript_path(body.get("transcript"))
    target_application = string_value(body.get("targetApplication"), "Unknown Application")
    session_id = optional_session_id(body.get("sessionId"))
    no_media_tools = bool(body.get("noMediaTools", False))
    source_profile = string_value(body.get("sourceProfile"), "standard")
    force = bool(body.get("force", False))

    command = build_process_command(
        recording,
        session_id=session_id,
        target_application=target_application,
        transcript=transcript,
        no_media_tools=no_media_tools,
        source_profile=source_profile,
        force=force,
    )

    result = run_command(command)
    resolved_session_id = session_id or infer_session_id_from_stdout(result.get("stdout", ""))
    response: dict[str, Any] = {"command": command_summary(command), "result": result, "sessionId": resolved_session_id}
    if result["returnCode"] == 0 and resolved_session_id:
        session_dir = PROCESSED_ROOT / resolved_session_id
        if session_dir.exists():
            response["session"] = read_session(session_dir)
    return response


def generate_draft(body: dict[str, Any]) -> dict[str, Any]:
    session_dir = require_session_dir(body.get("sessionId"))
    use_anthropic = bool(body.get("useAnthropic", False))
    trace_path = session_dir / "procedure_trace.json"
    if not trace_path.exists():
        raise HttpError(HTTPStatus.NOT_FOUND, "Session does not contain procedure_trace.json.")

    mode = "anthropic" if use_anthropic else "deterministic"
    output = GENERATED_ROOT / session_dir.name / f"guide_draft.{mode}.json"
    command = [
        sys.executable,
        str(WORKSPACE / "scripts" / "generate_guide_draft.py"),
        str(trace_path),
        "--output",
        str(output),
    ]
    if use_anthropic:
        command.append("--use-anthropic")

    result = run_command(command)
    response = {"command": command_summary(command), "draft": relative_to_workspace(output), "result": result}
    if output.exists():
        response["draftSummary"] = read_json_summary(output)
    return response


def build_docx(body: dict[str, Any]) -> dict[str, Any]:
    session_dir = require_session_dir(body.get("sessionId"))
    draft = string_value(body.get("draft"), "deterministic")
    if draft not in {"deterministic", "anthropic"}:
        raise HttpError(HTTPStatus.BAD_REQUEST, "draft must be 'deterministic' or 'anthropic'.")

    draft_path = GENERATED_ROOT / session_dir.name / f"guide_draft.{draft}.json"
    if not draft_path.exists():
        raise HttpError(HTTPStatus.NOT_FOUND, f"Draft not found: {relative_to_workspace(draft_path)}")

    output = GENERATED_ROOT / session_dir.name / f"user_guide.{draft}.docx"
    command = [
        sys.executable,
        str(WORKSPACE / "scripts" / "build_guide_docx.py"),
        str(draft_path),
        "--output",
        str(output),
    ]
    result = run_command(command)
    response = {"command": command_summary(command), "docx": relative_to_workspace(output), "result": result}
    if output.exists():
        response["docxSizeBytes"] = output.stat().st_size
    return response


def qa_docx(body: dict[str, Any]) -> dict[str, Any]:
    session_dir = require_session_dir(body.get("sessionId"))
    draft = string_value(body.get("draft"), "deterministic")
    strict = bool(body.get("strict", False))
    if draft not in {"deterministic", "anthropic"}:
        raise HttpError(HTTPStatus.BAD_REQUEST, "draft must be 'deterministic' or 'anthropic'.")

    docx_path = GENERATED_ROOT / session_dir.name / f"user_guide.{draft}.docx"
    if not docx_path.exists():
        raise HttpError(HTTPStatus.NOT_FOUND, f"DOCX not found: {relative_to_workspace(docx_path)}")

    command = [
        sys.executable,
        str(WORKSPACE / "scripts" / "qa_document_artifacts.py"),
        str(docx_path),
        "--json",
    ]
    if strict:
        command.append("--strict")
    result = run_command(command)
    parsed = {}
    if result["stdout"]:
        try:
            parsed = json.loads(result["stdout"])
        except json.JSONDecodeError:
            parsed = {"raw": result["stdout"]}
    return {
        "command": command_summary(command),
        "docx": relative_to_workspace(docx_path),
        "strict": strict,
        "passed": result["returnCode"] == 0,
        "result": result,
        "qa": parsed,
    }


def read_session(session_dir: Path) -> dict[str, Any]:
    summary = summarize_session(session_dir)
    files = {}
    for name in ["manifest.json", "media_metadata.json", "transcript.json", "frame_scores.json", "ocr.json", "procedure_trace.json"]:
        path = session_dir / name
        if path.exists():
            files[name] = read_json_summary(path)
    summary["files"] = files
    trace = read_json_if_exists(session_dir / "procedure_trace.json")
    if trace:
        summary["procedureTrace"] = trace
    generated_dir = GENERATED_ROOT / session_dir.name
    summary["generated"] = list_generated_files(generated_dir)
    return summary


def summarize_session(session_dir: Path) -> dict[str, Any]:
    manifest = read_json_if_exists(session_dir / "manifest.json")
    trace = read_json_if_exists(session_dir / "procedure_trace.json")
    recording = trace.get("recording", {}) if isinstance(trace.get("recording"), dict) else {}
    stat = session_dir.stat()
    return {
        "sessionId": session_dir.name,
        "relativePath": relative_to_workspace(session_dir),
        "createdUtc": manifest.get("createdUtc") or utc_from_timestamp(stat.st_ctime),
        "modifiedUtc": utc_from_timestamp(stat.st_mtime),
        "targetApplication": recording.get("targetApplication") or "Unknown Application",
        "durationSeconds": recording.get("durationSeconds"),
        "segmentCount": len(trace.get("segments", [])) if isinstance(trace.get("segments"), list) else None,
        "generated": list_generated_files(GENERATED_ROOT / session_dir.name),
    }


def list_generated_files(generated_dir: Path) -> list[dict[str, Any]]:
    if not generated_dir.exists() or not generated_dir.is_dir():
        return []
    files = []
    for path in sorted(generated_dir.iterdir(), key=lambda item: item.name.lower()):
        if not path.is_file() or path.name.startswith("."):
            continue
        stat = path.stat()
        files.append(
            {
                "name": path.name,
                "relativePath": relative_to_workspace(path),
                "sizeBytes": stat.st_size,
                "modifiedUtc": utc_from_timestamp(stat.st_mtime),
            }
        )
    return files


def run_command(command: list[str]) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    completed = subprocess.run(
        command,
        cwd=WORKSPACE,
        env=env,
        text=True,
        capture_output=True,
        timeout=900,
        check=False,
    )
    return {
        "returnCode": completed.returncode,
        "stdout": redact(completed.stdout.strip()),
        "stderr": redact(completed.stderr.strip()),
    }


def build_json_response(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")


def send_json(handler: Any, payload: dict[str, Any], status: int | HTTPStatus = HTTPStatus.OK) -> None:
    data = build_json_response(payload)
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(data)


def safe_join(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    if not is_relative_to(candidate, root):
        raise PermissionError(f"Path escapes root: {relative_path}")
    return candidate


def build_process_command(
    recording: Path,
    repo_root: Path = WORKSPACE,
    output_root: Path = PROCESSED_ROOT,
    session_id: str | None = None,
    target_application: str = "Unknown Application",
    transcript: Path | None = None,
    no_media_tools: bool = False,
    source_profile: str = "standard",
    force: bool = False,
) -> list[str]:
    command = [
        sys.executable,
        str(repo_root / "scripts" / "process_recording.py"),
        str(recording),
        "--output-root",
        str(output_root),
        "--target-application",
        target_application,
    ]
    if transcript:
        command.extend(["--transcript", str(transcript)])
    if source_profile and source_profile != "standard":
        command.extend(["--source-profile", source_profile])
    if session_id:
        command.extend(["--session-id", session_id])
    if no_media_tools:
        command.append("--no-media-tools")
    if force:
        command.append("--force")
    return command


def command_summary(command: list[str]) -> list[str]:
    return [relative_to_workspace(Path(part)) if looks_like_workspace_path(part) else part for part in command]


def require_recording_path(raw_value: Any) -> Path:
    value = string_value(raw_value, "")
    if not value:
        raise HttpError(HTTPStatus.BAD_REQUEST, "recording is required.")
    filename = validate_safe_filename(value, RECORDING_EXTENSIONS, "recording")
    candidate = (RAW_ROOT / filename).resolve()
    if not is_relative_to(candidate, RAW_ROOT) or not candidate.is_file():
        raise HttpError(HTTPStatus.NOT_FOUND, "Recording not found in samples/raw.")
    return candidate


def optional_transcript_path(raw_value: Any) -> Path | None:
    value = string_value(raw_value, "")
    if not value:
        return None
    filename = validate_safe_filename(value, TRANSCRIPT_EXTENSIONS, "transcript")
    candidate = (RAW_ROOT / filename).resolve()
    if not is_relative_to(candidate, RAW_ROOT) or not candidate.is_file():
        raise HttpError(HTTPStatus.NOT_FOUND, "Transcript not found in samples/raw.")
    return candidate


def require_session_dir(raw_value: Any) -> Path:
    session_id = require_session_id(raw_value)
    session_dir = (PROCESSED_ROOT / session_id).resolve()
    if not is_relative_to(session_dir, PROCESSED_ROOT) or not session_dir.is_dir():
        raise HttpError(HTTPStatus.NOT_FOUND, "Session not found in samples/processed.")
    return session_dir


def require_session_id(raw_value: Any) -> str:
    session_id = string_value(raw_value, "")
    if not SESSION_ID_RE.match(session_id):
        raise HttpError(HTTPStatus.BAD_REQUEST, "sessionId is required and may only contain letters, numbers, dots, underscores, and hyphens.")
    return session_id


def optional_session_id(raw_value: Any) -> str | None:
    if raw_value is None or str(raw_value).strip() == "":
        return None
    return require_session_id(raw_value)


def first_query_value(params: dict[str, list[str]], key: str) -> str:
    values = params.get(key) or []
    return values[0] if values else ""


def import_upload(handler: KCXDocumentorHandler, kind: str) -> dict[str, Any]:
    allowed_extensions = RECORDING_EXTENSIONS if kind == "recording" else TRANSCRIPT_EXTENSIONS
    form = parse_multipart_upload(handler)
    uploaded = form.get(kind) or form.get("file")
    if not uploaded or not isinstance(uploaded, dict):
        raise HttpError(HTTPStatus.BAD_REQUEST, f"Multipart upload must include a file field named '{kind}' or 'file'.")

    original_name = string_value(uploaded.get("filename"), "")
    filename = validate_safe_filename(original_name, allowed_extensions, kind)
    payload = uploaded.get("content")
    if not isinstance(payload, bytes) or not payload:
        raise HttpError(HTTPStatus.BAD_REQUEST, "Uploaded file is empty.")

    target = unique_raw_path(filename)
    target.write_bytes(payload)

    return {
        kind: describe_raw_file(target),
        "originalName": original_name,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def parse_multipart_upload(handler: KCXDocumentorHandler) -> dict[str, Any]:
    content_type = handler.headers.get("Content-Type", "")
    boundary = multipart_boundary(content_type)
    if not boundary:
        raise HttpError(HTTPStatus.BAD_REQUEST, "Content-Type must be multipart/form-data with a boundary.")

    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        raise HttpError(HTTPStatus.BAD_REQUEST, "Multipart upload is empty.")
    if length > MULTIPART_MAX_BYTES:
        raise HttpError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Multipart upload is too large for the local prototype server.")

    body = handler.rfile.read(length)
    delimiter = b"--" + boundary
    fields: dict[str, Any] = {}
    for raw_part in body.split(delimiter):
        part = raw_part.strip()
        if not part or part == b"--":
            continue
        if part.endswith(b"--"):
            part = part[:-2].strip()
        header_bytes, separator, content = part.partition(b"\r\n\r\n")
        if not separator:
            continue
        headers = parse_part_headers(header_bytes)
        disposition = headers.get("content-disposition", "")
        params = parse_content_disposition(disposition)
        name = params.get("name")
        if not name:
            continue
        if content.endswith(b"\r\n"):
            content = content[:-2]
        filename = params.get("filename")
        if filename is not None:
            fields[name] = {"filename": filename, "content": content}
        else:
            fields[name] = content.decode("utf-8", errors="replace")
    return fields


def multipart_boundary(content_type: str) -> bytes | None:
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part.split("=", 1)[1].strip().strip('"')
            return boundary.encode("utf-8") if boundary else None
    return None


def parse_part_headers(header_bytes: bytes) -> dict[str, str]:
    headers = {}
    for line in header_bytes.decode("utf-8", errors="replace").split("\r\n"):
        key, separator, value = line.partition(":")
        if separator:
            headers[key.strip().lower()] = value.strip()
    return headers


def parse_content_disposition(value: str) -> dict[str, str]:
    params = {}
    for part in value.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        key, raw = part.split("=", 1)
        params[key.strip().lower()] = raw.strip().strip('"')
    return params


def validate_safe_filename(raw_filename: str, allowed_extensions: set[str], kind: str) -> str:
    filename = Path(raw_filename).name.strip()
    if filename != raw_filename.strip() or not filename or filename in {".", ".."}:
        raise HttpError(HTTPStatus.BAD_REQUEST, f"{kind} filename must be a plain file name.")
    if not SAFE_FILENAME_RE.match(filename):
        raise HttpError(HTTPStatus.BAD_REQUEST, f"{kind} filename contains unsupported characters.")
    if Path(filename).suffix.lower() not in allowed_extensions:
        allowed = ", ".join(sorted(allowed_extensions))
        raise HttpError(HTTPStatus.BAD_REQUEST, f"{kind} file extension must be one of: {allowed}.")
    return filename


def unique_raw_path(filename: str) -> Path:
    candidate = (RAW_ROOT / filename).resolve()
    if not is_relative_to(candidate, RAW_ROOT):
        raise HttpError(HTTPStatus.BAD_REQUEST, "Upload path escapes samples/raw.")
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    for index in range(2, 1000):
        alternate = (RAW_ROOT / f"{stem}-{index}{suffix}").resolve()
        if not is_relative_to(alternate, RAW_ROOT):
            raise HttpError(HTTPStatus.BAD_REQUEST, "Upload path escapes samples/raw.")
        if not alternate.exists():
            return alternate
    raise HttpError(HTTPStatus.CONFLICT, "Could not choose a unique upload filename.")


def save_uploaded_recording(source: Path, raw_root: Path = RAW_ROOT, filename: str | None = None) -> dict[str, Any]:
    source_path = Path(source).resolve()
    if not source_path.is_file():
        raise ValueError(f"Source recording does not exist: {source}")
    safe_name = validate_safe_filename(filename or source_path.name, RECORDING_EXTENSIONS, "recording")
    target = (raw_root / safe_name).resolve()
    if not is_relative_to(target, raw_root):
        raise PermissionError("Upload path escapes raw root.")
    if target.exists():
        stem = target.stem
        suffix = target.suffix
        for index in range(2, 1000):
            alternate = (raw_root / f"{stem}-{index}{suffix}").resolve()
            if not alternate.exists():
                target = alternate
                break
    target.write_bytes(source_path.read_bytes())
    return {"path": str(target), "name": target.name}


def infer_session_id_from_stdout(stdout: str) -> str | None:
    for line in stdout.splitlines():
        if "session id:" in line.lower():
            return line.split(":", 1)[1].strip()
    return None


def read_json_summary(path: Path) -> dict[str, Any]:
    data = read_json_if_exists(path)
    if not data:
        return {}
    summary: dict[str, Any] = {"relativePath": relative_to_workspace(path)}
    for key in ["schemaVersion", "sessionId", "title", "status", "createdUtc"]:
        if key in data:
            summary[key] = data[key]
    if isinstance(data.get("segments"), list):
        summary["segmentCount"] = len(data["segments"])
    if isinstance(data.get("steps"), list):
        summary["stepCount"] = len(data["steps"])
    if isinstance(data.get("reviewFlags"), list):
        summary["reviewFlagCount"] = len(data["reviewFlags"])
    return summary


def read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def relative_to_workspace(path: Path) -> str:
    resolved = path.resolve()
    if is_relative_to(resolved, WORKSPACE):
        return str(resolved.relative_to(WORKSPACE))
    return str(resolved)


def looks_like_workspace_path(value: str) -> bool:
    try:
        return is_relative_to(Path(value).resolve(), WORKSPACE)
    except OSError:
        return False


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return False
    return True


def string_value(value: Any, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def utc_from_timestamp(timestamp: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def redact(text: str) -> str:
    redacted = text
    for pattern in REDACTION_PATTERNS:
        redacted = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]" if match.groups() else "[REDACTED]", redacted)
    return redacted


if __name__ == "__main__":
    raise SystemExit(main())
