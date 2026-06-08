#!/usr/bin/env python3
"""Local stdlib HTTP API for KCXDocumentor prototype testing."""

from __future__ import annotations

import argparse
import base64
import hmac
import hashlib
import importlib.util
import json
import math
import mimetypes
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from http.cookies import SimpleCookie
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile

import jwt
from jwt import PyJWKClient


WORKSPACE = Path(__file__).resolve().parents[1]
WEB_ROOT = WORKSPACE / "web"
DOCS_ROOT = WORKSPACE / "docs"
RAW_ROOT = WORKSPACE / "samples" / "raw"
PROCESSED_ROOT = WORKSPACE / "samples" / "processed"
GENERATED_ROOT = WORKSPACE / "artifacts" / "generated"
USAGE_DB_PATH = WORKSPACE / "artifacts" / "usage" / "generation_usage.sqlite3"
DEFAULT_AUTH_CLIENT_ID = "9d5d6572-b583-4df9-8fe6-8f96c71fad58"
DEFAULT_AUTH_TENANT_ID = "543e31cf-f2b9-457e-88af-82a3938c2913"
DEFAULT_AUTH_AUTHORITY = f"https://login.microsoftonline.com/{DEFAULT_AUTH_TENANT_ID}"
DEFAULT_AUTH_SCOPES = "openid profile"
CLOUD_AUTH_API_PATHS = {
    "/api/usage-summary",
    "/api/generate-draft",
    "/api/generation-jobs",
    "/api/migrate-usage",
    "/api/report-page-count",
}
AUTH_SESSION_COOKIE = "KCXDocumentorAuth"
AUTH_SESSION_SECRET = ""
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
FRAME_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,96}$")
SEGMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,96}$")
SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. -]{0,180}$")
RECORDING_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".wmv", ".m4v"}
TRANSCRIPT_EXTENSIONS = {".txt", ".vtt", ".srt", ".json"}
MULTIPART_MAX_BYTES = 3 * 1024 * 1024 * 1024
REDACTION_PATTERNS = [
    re.compile(r"(?i)(anthropic[_-]?api[_-]?key\s*[=:]\s*)[^\s\"']+"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]+"),
]
JWKS_CACHE: dict[str, Any] = {"url": "", "expires": 0.0, "keys": []}
PROCESS_RECORDING_MODULE: Any | None = None
GENERATION_JOBS: dict[str, dict[str, Any]] = {}
GENERATION_JOBS_LOCK = threading.Lock()
GENERATION_EXECUTION_LOCK = threading.Lock()


def utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


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


load_env_file(WORKSPACE / ".env")
AUTH_SESSION_SECRET = os.environ.get("KCXDOC_AUTH_SESSION_SECRET") or hashlib.sha256(os.urandom(32)).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local KCXDocumentor prototype app server.")
    parser.add_argument(
        "--export-usage-json",
        nargs="?",
        const="-",
        metavar="PATH",
        help="Export local SQLite usage records as JSON for remote API migration. Use '-' or omit PATH for stdout.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host interface. Defaults to 127.0.0.1.")
    parser.add_argument("--port", type=int, default=8765, help="Port. Defaults to 8765.")
    args = parser.parse_args()

    if args.export_usage_json is not None:
        payload = export_usage_records_for_remote()
        data = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        if args.export_usage_json == "-":
            sys.stdout.write(data)
        else:
            output_path = Path(args.export_usage_json)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(data, encoding="utf-8")
        return 0

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
            self.require_api_auth(parsed.path)
            if parsed.path == "/api/auth-config":
                self.send_json({"auth": get_auth_config()})
                return
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
            if parsed.path == "/api/usage-summary":
                params = parse_qs(parsed.query)
                self.send_json(read_usage_summary(first_query_value(params, "range") or "day", bearer_token=self.bearer_token()))
                return
            if parsed.path == "/api/generation-jobs":
                params = parse_qs(parsed.query)
                self.send_json({"job": read_local_generation_job(first_query_value(params, "jobId"))})
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
            if parsed.path == "/api/session-video":
                params = parse_qs(parsed.query)
                session_dir = require_session_dir(first_query_value(params, "sessionId"))
                self.serve_session_video(session_dir)
                return
            if parsed.path == "/api/frame-review":
                params = parse_qs(parsed.query)
                session_dir = require_session_dir(first_query_value(params, "sessionId"))
                self.send_json({"frameReview": read_frame_review_view(session_dir)})
                return
            if parsed.path == "/api/user-guide":
                self.serve_user_guide()
                return
            self.serve_static(parsed.path)
        except HttpError as exc:
            self.send_json({"error": exc.message}, status=exc.status)
        except Exception as exc:
            self.send_json({"error": f"Unexpected server error: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            self.require_api_auth(parsed.path)
            if parsed.path == "/api/auth-session":
                self.create_auth_session()
                return
            if parsed.path == "/api/logout":
                self.clear_auth_session()
                return
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
            if parsed.path == "/api/delete-session":
                self.send_json(delete_session_artifacts(body))
                return
            if parsed.path == "/api/frame-review":
                self.send_json(update_frame_review(body))
                return
            if parsed.path == "/api/extract-frame":
                self.send_json(extract_review_frame(body))
                return
            if parsed.path == "/api/generate-draft":
                self.send_json(generate_draft(body, bearer_token=self.bearer_token()))
                return
            if parsed.path == "/api/generation-jobs":
                self.send_json(start_local_generation_job(body, bearer_token=self.bearer_token()), status=HTTPStatus.ACCEPTED)
                return
            if parsed.path == "/api/migrate-usage":
                self.send_json(migrate_usage_records(bearer_token=self.bearer_token()))
                return
            if parsed.path == "/api/build-docx":
                self.send_json(build_docx(body, bearer_token=self.bearer_token()))
                return
            if parsed.path == "/api/report-page-count":
                self.send_json(report_page_count(body, bearer_token=self.bearer_token()))
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

    def require_api_auth(self, path: str) -> None:
        if path not in CLOUD_AUTH_API_PATHS or not get_auth_config().get("enabled"):
            return
        authorization = self.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            raise HttpError(HTTPStatus.UNAUTHORIZED, "Authentication is required.")
        claims = validate_bearer_token(authorization.removeprefix("Bearer ").strip())
        if not claims:
            raise HttpError(HTTPStatus.UNAUTHORIZED, "Authentication token is invalid or expired.")

    def bearer_token(self) -> str:
        authorization = self.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            return authorization.removeprefix("Bearer ").strip()
        return ""

    def create_auth_session(self) -> None:
        authorization = self.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            raise HttpError(HTTPStatus.UNAUTHORIZED, "Authentication is required.")
        claims = validate_bearer_token(authorization.removeprefix("Bearer ").strip())
        if not claims:
            raise HttpError(HTTPStatus.UNAUTHORIZED, "Authentication token is invalid or expired.")
        max_age = max(0, min(int(claims.get("exp", 0) - time_now()), 8 * 60 * 60))
        cookie = build_auth_session_cookie(claims, max_age)
        payload = {
            "authenticated": True,
            "name": claims.get("name") or claims.get("preferred_username") or claims.get("upn") or "Signed in user",
            "expiresInSeconds": max_age,
        }
        data = build_json_response(payload)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def clear_auth_session(self) -> None:
        data = build_json_response({"authenticated": False})
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Set-Cookie", f"{AUTH_SESSION_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax; HttpOnly")
        self.end_headers()
        self.wfile.write(data)

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
        if status == HTTPStatus.UNAUTHORIZED:
            self.send_header("WWW-Authenticate", 'Bearer error="invalid_token"')
        self.end_headers()
        self.wfile.write(data)

    def serve_session_video(self, session_dir: Path) -> None:
        manifest = read_json_if_exists(session_dir / "manifest.json")
        source = session_source_path(manifest)
        self.serve_file(source, inline_name=source.name)

    def serve_session_asset(self, session_dir: Path, raw_asset: str) -> None:
        candidate = safe_join(session_dir, raw_asset)
        if not candidate.is_file():
            generated_candidate = safe_join(GENERATED_ROOT / session_dir.name, raw_asset)
            candidate = generated_candidate if generated_candidate.is_file() else candidate
        if not candidate.is_file():
            raise HttpError(HTTPStatus.NOT_FOUND, "Session asset not found.")

        self.serve_file(candidate, inline_name=candidate.name)

    def serve_user_guide(self) -> None:
        candidate = DOCS_ROOT / "user-guide.docx"
        if not candidate.is_file():
            raise HttpError(HTTPStatus.NOT_FOUND, "User guide DOCX not found.")
        self.serve_file(candidate, inline_name="KCXDocumentor User Guide.docx")

    def serve_file(self, candidate: Path, inline_name: str = "") -> None:
        content_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        file_size = candidate.stat().st_size
        range_header = self.headers.get("Range", "")
        if range_header:
            start, end = parse_byte_range(range_header, file_size)
            length = end - start + 1
            self.send_response(HTTPStatus.PARTIAL_CONTENT)
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            if inline_name:
                self.send_header("Content-Disposition", f'inline; filename="{inline_name}"')
            self.end_headers()
            with candidate.open("rb") as handle:
                handle.seek(start)
                self.wfile.write(handle.read(length))
            return

        data = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        if inline_name:
            self.send_header("Content-Disposition", f'inline; filename="{inline_name}"')
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
    configured_whisper = os.environ.get("KCXDOC_WHISPER_CLI", "").strip()
    whisper = str(Path(configured_whisper).expanduser()) if configured_whisper else shutil.which("whisper-cli")
    whisper_model = Path(
        os.environ.get("KCXDOC_WHISPER_MODEL", "").strip()
        or WORKSPACE / "models" / "whisper" / "ggml-base.en.bin"
    ).expanduser()
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
                "available": bool(whisper and Path(whisper).exists()) if configured_whisper else bool(whisper),
                "path": whisper,
                "modelAvailable": whisper_model.exists(),
                "modelPath": relative_to_workspace(whisper_model) if is_relative_to(whisper_model.resolve(), WORKSPACE) else str(whisper_model),
            },
        },
    }


def get_auth_config() -> dict[str, Any]:
    tenant_id = os.environ.get("KCXDOC_AUTH_TENANT_ID", DEFAULT_AUTH_TENANT_ID).strip()
    client_id = os.environ.get("KCXDOC_AUTH_CLIENT_ID", DEFAULT_AUTH_CLIENT_ID).strip()
    authority = os.environ.get("KCXDOC_AUTH_AUTHORITY", f"https://login.microsoftonline.com/{tenant_id}").rstrip("/")
    enabled = bool_env("KCXDOC_AUTH_ENABLED", True)
    return {
        "enabled": enabled,
        "tenantId": tenant_id,
        "clientId": client_id,
        "authority": authority,
        "redirectUri": os.environ.get("KCXDOC_AUTH_REDIRECT_URI", "").strip() or None,
        "postLogoutRedirectUri": os.environ.get("KCXDOC_AUTH_POST_LOGOUT_REDIRECT_URI", "").strip() or None,
        "scopes": split_scopes(os.environ.get("KCXDOC_AUTH_SCOPES", DEFAULT_AUTH_SCOPES)),
    }


def bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def split_scopes(raw_scopes: str) -> list[str]:
    scopes = [scope.strip() for scope in re.split(r"[\s,]+", raw_scopes or "") if scope.strip()]
    return scopes or split_scopes(DEFAULT_AUTH_SCOPES)


def validate_bearer_token(token: str) -> dict[str, Any]:
    config = get_auth_config()
    if not token:
        return {}
    try:
        signing_key = get_jwk_client(config["tenantId"]).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=config["clientId"],
            issuer=token_issuers(config["tenantId"]),
            options={"require": ["exp", "iat", "iss", "aud"]},
            leeway=60,
        )
    except (jwt.PyJWTError, OSError, ValueError):
        return {}


def build_auth_session_cookie(claims: dict[str, Any], max_age: int) -> str:
    payload = {
        "aud": claims.get("aud", ""),
        "iss": claims.get("iss", ""),
        "sub": claims.get("sub") or claims.get("oid") or "",
        "exp": min(int(claims.get("exp", 0) or 0), int(time_now()) + max_age),
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii").rstrip("=")
    signature = hmac.new(AUTH_SESSION_SECRET.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{AUTH_SESSION_COOKIE}={encoded}.{signature}; Path=/; Max-Age={max_age}; SameSite=Lax; HttpOnly"


def validate_auth_session_cookie(cookie_header: str) -> bool:
    if not cookie_header:
        return False
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header)
    except Exception:
        return False
    morsel = cookie.get(AUTH_SESSION_COOKIE)
    if not morsel or "." not in morsel.value:
        return False
    encoded, signature = morsel.value.rsplit(".", 1)
    expected = hmac.new(AUTH_SESSION_SECRET.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        padded = encoded + ("=" * (-len(encoded) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return False
    config = get_auth_config()
    return (
        payload.get("aud") == config["clientId"]
        and payload.get("iss") in token_issuers(config["tenantId"])
        and int(payload.get("exp", 0) or 0) > time_now()
    )


def time_now() -> int:
    return int(time.time())


def get_jwk_client(tenant_id: str) -> PyJWKClient:
    jwks_url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
    cached_client = JWKS_CACHE.get("client")
    if cached_client and JWKS_CACHE.get("url") == jwks_url:
        return cached_client
    client = PyJWKClient(jwks_url)
    JWKS_CACHE["url"] = jwks_url
    JWKS_CACHE["client"] = client
    return client


def token_issuers(tenant_id: str) -> list[str]:
    return [
        f"https://login.microsoftonline.com/{tenant_id}/v2.0",
        f"https://sts.windows.net/{tenant_id}/",
    ]


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
            generated_transcript = persist_generated_transcript_sidecar(recording, session_dir)
            if generated_transcript:
                response["generatedTranscript"] = generated_transcript
            response["session"] = read_session(session_dir)
    return response


def persist_generated_transcript_sidecar(recording: Path, session_dir: Path) -> dict[str, Any] | None:
    transcript_path = session_dir / "transcript.json"
    if not transcript_path.exists():
        return None
    transcript = read_json_if_exists(transcript_path)
    if transcript.get("source") != "local-whisper":
        return None
    if not isinstance(transcript.get("segments"), list) or not transcript["segments"]:
        return None

    sidecar_name = f"{recording.stem}.whisper-transcript.json"
    sidecar_path = RAW_ROOT / sidecar_name
    sidecar_payload = {
        **transcript,
        "recordingName": recording.name,
        "recordingPath": str(recording),
        "sourceSessionId": session_dir.name,
        "sourceSessionTranscript": relative_to_workspace(transcript_path),
    }
    sidecar_path.write_text(json.dumps(sidecar_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return describe_raw_file(sidecar_path)


def start_local_generation_job(body: dict[str, Any], bearer_token: str = "") -> dict[str, Any]:
    session_dir = require_session_dir(body.get("sessionId"))
    job_id = uuid.uuid4().hex
    token_estimate = estimate_generation_tokens(session_dir)
    job = {
        "jobId": job_id,
        "sessionId": session_dir.name,
        "status": "queued",
        "phase": "queued",
        "message": "Queued.",
        "createdAt": utc_timestamp(),
        "updatedAt": utc_timestamp(),
        "tokenEstimate": token_estimate,
        "result": {},
        "error": "",
    }
    with GENERATION_JOBS_LOCK:
        GENERATION_JOBS[job_id] = job
    thread = threading.Thread(
        target=run_local_generation_job,
        args=(job_id, {"sessionId": session_dir.name}, bearer_token),
        name=f"kcxdoc-generation-{job_id[:8]}",
        daemon=True,
    )
    thread.start()
    return {"job": public_generation_job(job)}


def read_local_generation_job(job_id: str | None) -> dict[str, Any]:
    if not job_id:
        raise HttpError(HTTPStatus.BAD_REQUEST, "jobId is required.")
    with GENERATION_JOBS_LOCK:
        job = GENERATION_JOBS.get(job_id)
    if not job:
        raise HttpError(HTTPStatus.NOT_FOUND, "Generation job was not found on this workstation.")
    return public_generation_job(job)


def run_local_generation_job(job_id: str, body: dict[str, Any], bearer_token: str) -> None:
    update_local_generation_job(job_id, status="queued", phase="queued", message="Queued.")
    with GENERATION_EXECUTION_LOCK:
        try:
            update_local_generation_job(job_id, status="running", phase="draft", message="Generating section 1 of 1.")
            draft = generate_draft(body, bearer_token=bearer_token)
            ensure_command_success(draft, "AI draft generation")
            update_local_generation_job(
                job_id,
                status="running",
                phase="docx",
                message="Building DOCX.",
                result={"draft": draft},
            )
            docx = build_docx(body, bearer_token=bearer_token)
            ensure_command_success(docx, "DOCX build")
            update_local_generation_job(
                job_id,
                status="running",
                phase="qa",
                message="QA.",
                result={"draft": draft, "docx": docx},
            )
            qa = qa_docx(body)
            ensure_command_success(qa, "DOCX QA")
            update_local_generation_job(
                job_id,
                status="succeeded",
                phase="complete",
                message="Succeeded.",
                completedAt=utc_timestamp(),
                result={"draft": draft, "docx": docx, "qa": qa},
            )
        except Exception as exc:  # noqa: BLE001 - stored for UI diagnostics without leaking a traceback.
            update_local_generation_job(
                job_id,
                status="failed",
                phase="failed",
                message="Failed.",
                error=str(exc),
                completedAt=utc_timestamp(),
            )


def ensure_command_success(payload: dict[str, Any], label: str) -> None:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    if result and int(result.get("returnCode", 0) or 0) != 0:
        failure_summary = payload.get("failureSummary") if isinstance(payload.get("failureSummary"), dict) else {}
        message = (
            failure_summary.get("errorMessage")
            or result.get("stderr")
            or result.get("stdout")
            or f"{label} failed."
        )
        raise RuntimeError(f"{label} failed: {message}")


def update_local_generation_job(job_id: str, **updates: Any) -> None:
    with GENERATION_JOBS_LOCK:
        job = GENERATION_JOBS.get(job_id)
        if not job:
            return
        result_updates = updates.pop("result", None)
        if isinstance(result_updates, dict):
            merged_result = dict(job.get("result") or {})
            merged_result.update(result_updates)
            job["result"] = merged_result
        job.update(updates)
        job["updatedAt"] = utc_timestamp()


def public_generation_job(job: dict[str, Any]) -> dict[str, Any]:
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    return {
        "jobId": job.get("jobId", ""),
        "sessionId": job.get("sessionId", ""),
        "status": job.get("status", ""),
        "phase": job.get("phase", ""),
        "message": job.get("message", ""),
        "createdAt": job.get("createdAt", ""),
        "updatedAt": job.get("updatedAt", ""),
        "completedAt": job.get("completedAt", ""),
        "tokenEstimate": job.get("tokenEstimate", {}),
        "error": job.get("error", ""),
        "draft": result.get("draft"),
        "docx": result.get("docx"),
        "qa": result.get("qa"),
    }


def estimate_generation_tokens(session_dir: Path) -> dict[str, Any]:
    trace_path = session_dir / "procedure_trace.json"
    prompt_path = WORKSPACE / "prompts" / "guide_draft_system.md"
    trace_chars = len(trace_path.read_text(encoding="utf-8")) if trace_path.exists() else 0
    prompt_chars = len(prompt_path.read_text(encoding="utf-8")) if prompt_path.exists() else 0
    safety_multiplier = float(os.environ.get("KCXDOC_TOKEN_COUNT_SAFETY_MULTIPLIER", "1.15") or 1.15)
    estimated_input_tokens = math.ceil(math.ceil((trace_chars + prompt_chars) / 4) * safety_multiplier)
    expected_output_tokens = int(os.environ.get("KCXDOC_MODEL_MAX_OUTPUT_TOKENS", os.environ.get("KCXDOC_ANTHROPIC_MAX_TOKENS", "64000")) or 64000)
    tpm_limit = int(os.environ.get("KCXDOC_FOUNDRY_TPM_LIMIT", "80000") or 80000)
    scheduling_target = int(os.environ.get("KCXDOC_FOUNDRY_TPM_TARGET", "68000") or 68000)
    return {
        "method": "chars_per_4",
        "safetyMultiplier": safety_multiplier,
        "traceCharacters": trace_chars,
        "systemPromptCharacters": prompt_chars,
        "estimatedInputTokens": estimated_input_tokens,
        "expectedOutputTokens": expected_output_tokens,
        "estimatedTotalTokens": estimated_input_tokens + expected_output_tokens,
        "tpmLimit": tpm_limit,
        "schedulingTargetTokens": scheduling_target,
        "overSchedulingTarget": estimated_input_tokens + expected_output_tokens > scheduling_target,
    }


def generate_draft(body: dict[str, Any], bearer_token: str = "") -> dict[str, Any]:
    session_dir = require_session_dir(body.get("sessionId"))
    trace_path = session_dir / "procedure_trace.json"
    if not trace_path.exists():
        raise HttpError(HTTPStatus.NOT_FOUND, "Session does not contain procedure_trace.json.")

    output = GENERATED_ROOT / session_dir.name / "guide_draft.anthropic.json"
    failure_path = output.parent / "generation_failure.json"
    if failure_path.exists():
        failure_path.unlink()
    command = [
        sys.executable,
        str(WORKSPACE / "scripts" / "generate_guide_draft.py"),
        str(trace_path),
        "--output",
        str(output),
    ]

    extra_env = {}
    if remote_api_base_url():
        if not bearer_token:
            raise HttpError(HTTPStatus.UNAUTHORIZED, "A signed-in user bearer token is required to create guides through the AI proxy.")
        extra_env["KCXDOC_REMOTE_API_BEARER_TOKEN"] = bearer_token
        extra_env["KCXDOC_REMOTE_GENERATION_MODE"] = "async"
    result = run_command(command, extra_env=extra_env)
    response = {"command": command_summary(command), "draft": relative_to_workspace(output), "result": result}
    if output.exists():
        response["draftSummary"] = read_json_summary(output)
    failure_summary = read_json_if_exists(failure_path) if result["returnCode"] != 0 else {}
    if failure_summary:
        response["failureSummary"] = failure_summary
    return response


def build_docx(body: dict[str, Any], bearer_token: str = "") -> dict[str, Any]:
    session_dir = require_session_dir(body.get("sessionId"))
    draft_path = GENERATED_ROOT / session_dir.name / "guide_draft.anthropic.json"
    if not draft_path.exists():
        raise HttpError(HTTPStatus.NOT_FOUND, f"Draft not found: {relative_to_workspace(draft_path)}")

    output = GENERATED_ROOT / session_dir.name / "user_guide.anthropic.docx"
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
        page_count = estimate_docx_page_count(output)
        response["pageCount"] = page_count
        generation_report_path = draft_path.parent / "generation_report.json"
        generation_report = write_generation_report_page_count(generation_report_path, page_count)
        update_usage_page_count(session_dir.name, page_count, generation_run_id=generation_report.get("generationRunId"))
        if remote_api_base_url() and generation_report and bearer_token:
            response["usageUpdate"] = update_remote_usage_page_count(generation_report, page_count, bearer_token=bearer_token)
        elif remote_api_base_url() and generation_report:
            response["usageUpdateSkipped"] = "Page count reporting requires an authenticated cloud request and does not block local DOCX creation."
    return response


def report_page_count(body: dict[str, Any], bearer_token: str = "") -> dict[str, Any]:
    session_dir = require_session_dir(body.get("sessionId"))
    docx_path = GENERATED_ROOT / session_dir.name / "user_guide.anthropic.docx"
    report_path = GENERATED_ROOT / session_dir.name / "generation_report.json"
    if not docx_path.exists():
        raise HttpError(HTTPStatus.NOT_FOUND, f"DOCX not found: {relative_to_workspace(docx_path)}")
    if not report_path.exists():
        raise HttpError(HTTPStatus.NOT_FOUND, f"Generation report not found: {relative_to_workspace(report_path)}")

    page_count = estimate_docx_page_count(docx_path)
    generation_report = write_generation_report_page_count(report_path, page_count)
    update_usage_page_count(session_dir.name, page_count, generation_run_id=generation_report.get("generationRunId"))
    usage_update = update_remote_usage_page_count(generation_report, page_count, bearer_token=bearer_token)
    return {
        "sessionId": session_dir.name,
        "docx": relative_to_workspace(docx_path),
        "generationReport": relative_to_workspace(report_path),
        "pageCount": page_count,
        "usageUpdate": usage_update,
    }


def qa_docx(body: dict[str, Any]) -> dict[str, Any]:
    session_dir = require_session_dir(body.get("sessionId"))
    strict = bool(body.get("strict", False))
    docx_path = GENERATED_ROOT / session_dir.name / "user_guide.anthropic.docx"
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


def delete_session_artifacts(body: dict[str, Any]) -> dict[str, Any]:
    session_id = require_session_id(body.get("sessionId"))
    session_dir = require_child_dir(PROCESSED_ROOT, session_id, "processed session")
    generated_dir = optional_child_dir(GENERATED_ROOT, session_id, "generated artifacts")
    if not session_dir.is_dir():
        raise HttpError(HTTPStatus.NOT_FOUND, "Session not found in samples/processed.")

    deleted: list[str] = []
    shutil.rmtree(session_dir)
    deleted.append(relative_to_workspace(session_dir))
    if generated_dir and generated_dir.exists():
        shutil.rmtree(generated_dir)
        deleted.append(relative_to_workspace(generated_dir))

    return {
        "sessionId": session_id,
        "deleted": deleted,
        "sessions": list_sessions(),
    }


def read_session(session_dir: Path) -> dict[str, Any]:
    summary = summarize_session(session_dir)
    files = {}
    for name in ["manifest.json", "media_metadata.json", "transcript.json", "frame_scores.json", "ocr.json", "procedure_trace.json", "frame_review.json"]:
        path = session_dir / name
        if path.exists():
            files[name] = read_json_summary(path)
    summary["files"] = files
    trace = read_json_if_exists(session_dir / "procedure_trace.json")
    if trace:
        summary["procedureTrace"] = apply_frame_review_to_trace(trace, read_frame_review(session_dir))
    summary["frameReview"] = read_frame_review_view(session_dir)
    generated_dir = GENERATED_ROOT / session_dir.name
    summary["generated"] = list_generated_files(generated_dir)
    generation = read_generation_summary(generated_dir)
    if generation:
        summary["generation"] = generation
    return summary


def summarize_session(session_dir: Path) -> dict[str, Any]:
    manifest = read_json_if_exists(session_dir / "manifest.json")
    trace = read_json_if_exists(session_dir / "procedure_trace.json")
    recording = trace.get("recording", {}) if isinstance(trace.get("recording"), dict) else {}
    source_file = string_value(recording.get("sourceFile") or manifest.get("sourceFile"), "")
    source_name = string_value(recording.get("sourceName") or Path(source_file).name, "")
    stat = session_dir.stat()
    generated_dir = GENERATED_ROOT / session_dir.name
    generated = list_generated_files(generated_dir)
    generated_mtime = latest_file_mtime(generated_dir)
    modified_timestamp = max(stat.st_mtime, generated_mtime or 0)
    review = read_frame_review(session_dir)
    review_summary = summarize_frame_review(review, merge_frame_review(session_dir, review))
    generation = read_generation_summary(generated_dir)
    return {
        "sessionId": session_dir.name,
        "relativePath": relative_to_workspace(session_dir),
        "createdUtc": manifest.get("createdUtc") or utc_from_timestamp(stat.st_ctime),
        "modifiedUtc": utc_from_timestamp(modified_timestamp),
        "targetApplication": recording.get("targetApplication") or "Unknown Application",
        "sourceFile": source_file,
        "sourceName": source_name,
        "durationSeconds": recording.get("durationSeconds"),
        "segmentCount": len(trace.get("segments", [])) if isinstance(trace.get("segments"), list) else None,
        "frameReview": review_summary,
        "generated": generated,
        **({"generation": generation} if generation else {}),
    }


def read_generation_summary(generated_dir: Path) -> dict[str, Any]:
    for name in ("generation_report.json", "generation_failure.json", "guide_draft.anthropic.json"):
        data = read_json_if_exists(generated_dir / name)
        summary = generation_summary_from_json(data)
        if summary:
            return summary
    return {}


def read_usage_summary(range_name: str = "day", bearer_token: str = "") -> dict[str, Any]:
    normalized_range = range_name if range_name in {"day", "week", "month", "year"} else "day"
    return read_remote_usage_summary(normalized_range, bearer_token=bearer_token)


def read_local_usage_summary(range_name: str = "day") -> dict[str, Any]:
    normalized_range = range_name if range_name in {"day", "week", "month", "year"} else "day"
    reports = collect_generation_reports()
    buckets: dict[str, dict[str, Any]] = {}
    for report in reports:
        bucket_key = usage_bucket_key(report.get("generatedAt", ""), normalized_range)
        bucket = buckets.setdefault(bucket_key, empty_usage_bucket(bucket_key))
        add_usage_to_bucket(bucket, report)

    ordered_buckets = [buckets[key] for key in sorted(buckets)]
    totals = empty_usage_totals()
    for bucket in ordered_buckets:
        add_totals(totals, bucket["totals"])

    return {
        "range": normalized_range,
        "generatedAt": utc_now(),
        "totals": totals,
        "buckets": ordered_buckets,
        "days": ordered_buckets if normalized_range == "day" else [],
    }


def read_remote_usage_summary(range_name: str, bearer_token: str = "") -> dict[str, Any]:
    base_url = remote_api_base_url()
    if not base_url:
        raise HttpError(HTTPStatus.BAD_REQUEST, "KCXDOC_REMOTE_API_BASE_URL is required for AI spend reporting.")
    if not bearer_token:
        raise HttpError(HTTPStatus.UNAUTHORIZED, "A signed-in user bearer token is required for AI spend reporting.")
    summary = fetch_remote_usage_summary(base_url, range_name, bearer_token=bearer_token)
    return normalize_usage_summary_response(summary, range_name)


def remote_api_base_url() -> str:
    return os.environ.get("KCXDOC_REMOTE_API_BASE_URL", "").strip().rstrip("/")


def fetch_remote_usage_summary(base_url: str, range_name: str, timeout_seconds: float = 5.0, bearer_token: str = "") -> dict[str, Any]:
    url = f"{base_url}/api/usage-summary?{urlencode({'range': range_name})}"
    headers = {"Accept": "application/json"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        message = remote_error_message(detail) or f"Remote usage summary failed: HTTP {exc.code}"
        raise HttpError(HTTPStatus(exc.code), message) from exc
    except URLError as exc:
        raise HttpError(HTTPStatus.BAD_GATEWAY, f"Remote usage summary failed: {exc}") from exc
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Remote usage summary must be a JSON object.")
    return payload


def remote_error_message(detail: str) -> str:
    payload = safe_json_loads(detail)
    if isinstance(payload, dict):
        return str(payload.get("error") or payload.get("message") or "").strip()
    return detail.strip()


def safe_json_loads(value: str) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None


def migrate_usage_records(bearer_token: str = "") -> dict[str, Any]:
    if not bearer_token:
        raise HttpError(HTTPStatus.UNAUTHORIZED, "A signed-in user bearer token is required to migrate AI usage.")
    base_url = remote_api_base_url()
    if not base_url:
        raise HttpError(HTTPStatus.BAD_REQUEST, "KCXDOC_REMOTE_API_BASE_URL is required to migrate AI usage.")
    payload = export_usage_records_for_remote()
    records = payload.get("records") if isinstance(payload.get("records"), list) else []
    if not records:
        return {
            "exported": 0,
            "imported": 0,
            "message": "No local SQLite usage records were available to migrate.",
        }
    result = post_remote_usage_records(base_url, records, timeout_seconds=30.0, bearer_token=bearer_token)
    return {
        "exported": len(records),
        "imported": int(result.get("imported") or 0),
        "remote": result,
    }


def update_remote_usage_page_count(report: dict[str, Any], page_count: int, bearer_token: str = "") -> dict[str, Any]:
    if page_count <= 0:
        return {"updated": False, "reason": "Page count was not available."}
    base_url = remote_api_base_url()
    if not base_url:
        raise RuntimeError("KCXDOC_REMOTE_API_BASE_URL is required to update AI usage page counts.")
    if not bearer_token:
        raise RuntimeError("A signed-in user bearer token is required to update AI usage page counts.")
    updated_report = {
        **report,
        "pageCount": page_count,
    }
    usage = updated_report.get("usage") if isinstance(updated_report.get("usage"), dict) else {}
    updated_report["usage"] = {
        **usage,
        "pageCount": page_count,
    }
    return post_remote_usage_records(base_url, [updated_report], bearer_token=bearer_token)


def write_generation_report_page_count(report_path: Path, page_count: int) -> dict[str, Any]:
    report = read_json_if_exists(report_path)
    if not report:
        return {}
    usage = report.get("usage") if isinstance(report.get("usage"), dict) else {}
    updated_usage = {
        **usage,
        "pageCount": page_count,
        "costPerPageUSD": cost_per_page(
            usage.get("estimatedCostUSD")
            or usage.get("estimated_cost_usd")
            or report.get("estimatedCostUSD")
            or report.get("estimated_cost_usd"),
            page_count,
        ),
    }
    updated_report = {
        **report,
        "pageCount": page_count,
        "usage": updated_usage,
    }
    report_path.write_text(
        json.dumps(updated_report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return updated_report


def post_remote_usage_records(base_url: str, records: list[dict[str, Any]], timeout_seconds: float = 15.0, bearer_token: str = "") -> dict[str, Any]:
    url = f"{base_url}/api/usage-records"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    request = Request(
        url,
        data=json.dumps({"records": records}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise OSError(f"Remote usage update failed: HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise OSError(f"Remote usage update failed: {exc}") from exc
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Remote usage update must return a JSON object.")
    return payload


def normalize_usage_summary_response(summary: dict[str, Any], range_name: str) -> dict[str, Any]:
    normalized_range = str(summary.get("range") or range_name)
    if normalized_range not in {"day", "week", "month", "year"}:
        normalized_range = range_name if range_name in {"day", "week", "month", "year"} else "day"
    buckets = summary.get("buckets")
    if not isinstance(buckets, list):
        raise ValueError("Remote usage summary is missing buckets.")
    totals = summary.get("totals")
    if not isinstance(totals, dict):
        raise ValueError("Remote usage summary is missing totals.")
    normalized = {
        **summary,
        "range": normalized_range,
        "generatedAt": str(summary.get("generatedAt") or utc_now()),
        "totals": normalize_usage_totals(totals),
        "buckets": buckets,
    }
    days = summary.get("days")
    normalized["days"] = days if isinstance(days, list) else (buckets if normalized_range == "day" else [])
    return normalized


def normalize_usage_totals(totals: dict[str, Any]) -> dict[str, Any]:
    normalized = empty_usage_totals()
    for key in ("documents", "attempts", "failedAttempts", "inputTokens", "outputTokens", "totalTokens", "pageCount"):
        normalized[key] = int(totals.get(key) or 0)
    normalized["estimatedCostUSD"] = round(float(totals.get("estimatedCostUSD") or 0), 6)
    if totals.get("costPerPageUSD"):
        normalized["costPerPageUSD"] = round(float(totals.get("costPerPageUSD") or 0), 6)
    else:
        normalized["costPerPageUSD"] = cost_per_page(normalized["estimatedCostUSD"], normalized["pageCount"])
    return normalized


def export_usage_records_for_remote(db_path: Path | None = None) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "exportedAt": utc_now(),
        "source": "local-sqlite",
        "records": read_usage_db_records(db_path),
    }


def collect_generation_reports() -> list[dict[str, Any]]:
    reports_by_id: dict[str, dict[str, Any]] = {}
    for report in read_usage_db_records():
        reports_by_id[report["generationRunId"]] = report

    if not GENERATED_ROOT.exists() or not GENERATED_ROOT.is_dir():
        return list(reports_by_id.values())
    for session_dir in sorted(GENERATED_ROOT.iterdir(), key=lambda item: item.name.lower()):
        if not session_dir.is_dir() or session_dir.name.startswith("."):
            continue
        data = read_json_if_exists(session_dir / "generation_report.json")
        if not data:
            data = read_json_if_exists(session_dir / "generation_failure.json")
        if not data:
            data = read_json_if_exists(session_dir / "guide_draft.anthropic.json")
        report = generation_report_record_from_json(data, session_dir.name)
        if report:
            if not report.get("pageCount"):
                docx_path = session_dir / "user_guide.anthropic.docx"
                if docx_path.is_file() and str(report.get("status") or "succeeded") != "failed":
                    page_count = estimate_docx_page_count(docx_path)
                    report["pageCount"] = page_count
                    update_usage_page_count(session_dir.name, page_count, generation_run_id=report.get("generationRunId"))
            existing = reports_by_id.get(report["generationRunId"])
            if existing and not existing.get("pageCount") and report.get("pageCount"):
                existing["pageCount"] = report["pageCount"]
            else:
                reports_by_id.setdefault(report["generationRunId"], report)
    return list(reports_by_id.values())


def read_usage_db_records(db_path: Path | None = None) -> list[dict[str, Any]]:
    db_path = db_path or USAGE_DB_PATH
    if not db_path.exists() or not db_path.is_file():
        return []
    try:
        with sqlite3.connect(db_path) as connection:
            ensure_usage_schema(connection)
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT generation_run_id, generated_at, session_id, title, provider,
                       model, prompt_version, input_tokens, output_tokens, total_tokens,
                       estimated_cost_usd, page_count, status, error_message
                FROM generation_usage
                ORDER BY generated_at, generation_run_id
                """
            ).fetchall()
    except sqlite3.Error:
        return []
    return [
        {
            "generationRunId": row["generation_run_id"],
            "generatedAt": row["generated_at"],
            "sessionId": row["session_id"],
            "title": row["title"],
            "provider": row["provider"],
            "model": row["model"],
            "promptVersion": row["prompt_version"],
            "inputTokens": row["input_tokens"],
            "outputTokens": row["output_tokens"],
            "totalTokens": row["total_tokens"],
            "estimatedCostUSD": row["estimated_cost_usd"],
            "pageCount": row["page_count"],
            "status": row["status"],
            "errorMessage": row["error_message"],
        }
        for row in rows
    ]


def ensure_usage_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS generation_usage (
            generation_run_id TEXT PRIMARY KEY,
            generated_at TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            session_id TEXT NOT NULL,
            title TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            estimated_cost_usd REAL NOT NULL DEFAULT 0,
            page_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'succeeded',
            error_message TEXT NOT NULL DEFAULT '',
            report_json TEXT NOT NULL
        )
        """
    )
    existing_columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(generation_usage)").fetchall()
    }
    if "status" not in existing_columns:
        connection.execute("ALTER TABLE generation_usage ADD COLUMN status TEXT NOT NULL DEFAULT 'succeeded'")
    if "error_message" not in existing_columns:
        connection.execute("ALTER TABLE generation_usage ADD COLUMN error_message TEXT NOT NULL DEFAULT ''")
    if "page_count" not in existing_columns:
        connection.execute("ALTER TABLE generation_usage ADD COLUMN page_count INTEGER NOT NULL DEFAULT 0")


def generation_report_record_from_json(data: dict[str, Any], fallback_session_id: str = "") -> dict[str, Any]:
    summary = generation_summary_from_json(data)
    if not summary:
        return {}
    record = {
        **summary,
        "sessionId": data.get("sessionId") or fallback_session_id,
        "title": data.get("title") or nested_title(data),
        "status": data.get("status") or summary.get("status") or "succeeded",
        "errorMessage": data.get("errorMessage") or summary.get("errorMessage") or "",
        "generatedBy": normalize_generated_by(data.get("generatedBy") or data.get("user")),
    }
    record["generationRunId"] = data.get("generationRunId") or generation_run_id_from_record(record)
    return record


def generation_run_id_from_record(record: dict[str, Any]) -> str:
    usage_values = (
        record.get("inputTokens", ""),
        record.get("outputTokens", ""),
    )
    fingerprint = "|".join(
        str(value)
        for value in (
            record.get("sessionId", ""),
            record.get("generatedAt", ""),
            record.get("model", ""),
            record.get("promptVersion", ""),
            *usage_values,
        )
    )
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]


def update_usage_page_count(session_id: str, page_count: int, generation_run_id: str | None = None) -> None:
    if page_count <= 0:
        return
    try:
        USAGE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(USAGE_DB_PATH) as connection:
            ensure_usage_schema(connection)
            if generation_run_id:
                cursor = connection.execute(
                    "UPDATE generation_usage SET page_count = ? WHERE generation_run_id = ?",
                    (page_count, generation_run_id),
                )
                if cursor.rowcount:
                    return
            connection.execute(
                """
                UPDATE generation_usage
                SET page_count = ?
                WHERE generation_run_id = (
                    SELECT generation_run_id
                    FROM generation_usage
                    WHERE session_id = ? AND status != 'failed'
                    ORDER BY generated_at DESC, recorded_at DESC
                    LIMIT 1
                )
                """,
                (page_count, session_id),
            )
    except sqlite3.Error:
        return


def estimate_docx_page_count(docx_path: Path) -> int:
    try:
        with ZipFile(docx_path) as package:
            app_pages = docx_app_page_count(package)
            document_xml = package.read("word/document.xml")
    except (BadZipFile, KeyError, OSError):
        return 0

    try:
        root = ET.fromstring(document_xml)
    except ET.ParseError:
        return max(app_pages, 0)

    ns = {
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    }
    text = " ".join(node.text or "" for node in root.findall(".//w:t", ns))
    words = len(re.findall(r"\b\w+\b", text))
    images = len(root.findall(".//a:blip", ns))
    page_breaks = len(root.findall(".//w:br[@w:type='page']", ns))
    section_count = len(root.findall(".//w:sectPr", ns))
    estimated = max(
        1,
        math.ceil((words / 430) + (images * 0.45) + page_breaks + max(0, section_count - 1) * 0.35),
    )
    if app_pages > 1:
        return max(app_pages, estimated)
    return estimated


def docx_app_page_count(package: ZipFile) -> int:
    try:
        root = ET.fromstring(package.read("docProps/app.xml"))
    except (KeyError, ET.ParseError):
        return 0
    pages = root.find("{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}Pages")
    try:
        return int((pages.text if pages is not None else "0") or 0)
    except ValueError:
        return 0


def nested_title(data: dict[str, Any]) -> str:
    document = data.get("document") if isinstance(data.get("document"), dict) else {}
    return str(document.get("title") or "")


def usage_bucket_key(generated_at: str, range_name: str) -> str:
    from datetime import datetime, timezone

    try:
        parsed = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        parsed = datetime.now(tz=timezone.utc)
    if range_name == "week":
        year, week, _ = parsed.isocalendar()
        return f"{year}-W{week:02d}"
    if range_name == "month":
        return parsed.strftime("%Y-%m")
    if range_name == "year":
        return parsed.strftime("%Y")
    return parsed.strftime("%Y-%m-%d")


def empty_usage_bucket(label: str) -> dict[str, Any]:
    return {"label": label, "totals": empty_usage_totals(), "documents": []}


def empty_usage_totals() -> dict[str, Any]:
    return {
        "documents": 0,
        "attempts": 0,
        "failedAttempts": 0,
        "inputTokens": 0,
        "outputTokens": 0,
        "totalTokens": 0,
        "pageCount": 0,
        "estimatedCostUSD": 0.0,
        "costPerPageUSD": 0.0,
    }


def add_usage_to_bucket(bucket: dict[str, Any], report: dict[str, Any]) -> None:
    status = str(report.get("status") or "succeeded")
    failed = status == "failed"
    totals = {
        "documents": 0 if failed else 1,
        "attempts": 1,
        "failedAttempts": 1 if failed else 0,
        "inputTokens": report.get("inputTokens") or 0,
        "outputTokens": report.get("outputTokens") or 0,
        "totalTokens": report.get("totalTokens") or 0,
        "pageCount": 0 if failed else int(report.get("pageCount") or 0),
        "estimatedCostUSD": report.get("estimatedCostUSD") or 0.0,
    }
    totals["costPerPageUSD"] = cost_per_page(totals["estimatedCostUSD"], totals["pageCount"])
    add_totals(bucket["totals"], totals)
    bucket["documents"].append(
        {
            "sessionId": report.get("sessionId", ""),
            "title": report.get("title", ""),
            "model": report.get("model", ""),
            "generatedAt": report.get("generatedAt", ""),
            "status": status,
            "errorMessage": report.get("errorMessage", ""),
            "generatedBy": normalize_generated_by(report.get("generatedBy") or report.get("user")),
            "usage": {
                "inputTokens": totals["inputTokens"],
                "outputTokens": totals["outputTokens"],
                "totalTokens": totals["totalTokens"],
                "estimatedCostUSD": totals["estimatedCostUSD"],
                "pageCount": totals["pageCount"],
                "costPerPageUSD": totals["costPerPageUSD"],
            },
        }
    )


def normalize_generated_by(value: Any) -> dict[str, str]:
    source = value if isinstance(value, dict) else {}
    username = str(source.get("username") or source.get("upn") or source.get("email") or "").strip()
    name = str(source.get("name") or source.get("displayName") or username).strip()
    return {
        "oid": str(source.get("oid") or source.get("id") or source.get("sub") or "").strip(),
        "name": name,
        "username": username,
    }


def add_totals(target: dict[str, Any], source: dict[str, Any]) -> None:
    target["documents"] = int(target.get("documents") or 0) + int(source.get("documents") or 0)
    target["attempts"] = int(target.get("attempts") or 0) + int(source.get("attempts") or 0)
    target["failedAttempts"] = int(target.get("failedAttempts") or 0) + int(source.get("failedAttempts") or 0)
    target["inputTokens"] = int(target.get("inputTokens") or 0) + int(source.get("inputTokens") or 0)
    target["outputTokens"] = int(target.get("outputTokens") or 0) + int(source.get("outputTokens") or 0)
    target["totalTokens"] = int(target.get("totalTokens") or 0) + int(source.get("totalTokens") or 0)
    target["pageCount"] = int(target.get("pageCount") or 0) + int(source.get("pageCount") or 0)
    target["estimatedCostUSD"] = round(float(target.get("estimatedCostUSD") or 0) + float(source.get("estimatedCostUSD") or 0), 6)
    target["costPerPageUSD"] = cost_per_page(target["estimatedCostUSD"], target["pageCount"])


def cost_per_page(cost: Any, page_count: Any) -> float:
    pages = int(page_count or 0)
    if pages <= 0:
        return 0.0
    return round(float(cost or 0) / pages, 6)


def generation_summary_from_json(data: dict[str, Any]) -> dict[str, Any]:
    if not data:
        return {}
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    model = data.get("model")
    if isinstance(model, dict):
        model_name = str(model.get("model") or model.get("id") or model.get("name") or "")
        provider = str(model.get("provider") or "")
        prompt_version = str(model.get("promptVersion") or "")
    else:
        model_name = str(model or "")
        provider = str(data.get("provider") or "")
        prompt_version = str(data.get("promptVersion") or "")
    input_tokens = number_or_none(first_present(usage, "inputTokens", "input_tokens", "cacheReadInputTokens", "cache_read_input_tokens"))
    output_tokens = number_or_none(first_present(usage, "outputTokens", "output_tokens"))
    total_tokens = number_or_none(first_present(usage, "totalTokens", "total_tokens"))
    if total_tokens is None and (input_tokens is not None or output_tokens is not None):
        total_tokens = int(input_tokens or 0) + int(output_tokens or 0)
    estimated_cost = number_or_none(first_present(usage, "estimatedCostUSD", "estimated_cost_usd", "costUSD", "cost_usd"))
    page_count = number_or_none(first_present(data, "pageCount", "page_count", "pages"))
    if page_count is None:
        page_count = number_or_none(first_present(usage, "pageCount", "page_count", "pages"))
    generated_at = str(data.get("generatedAt") or data.get("generated_at") or data.get("createdUtc") or data.get("createdAt") or "")
    if not any((model_name, generated_at, total_tokens is not None, estimated_cost is not None)):
        return {}
    return {
        "title": str(data.get("title") or nested_title(data) or ""),
        "model": model_name,
        "provider": provider,
        "promptVersion": prompt_version,
        "generatedAt": generated_at,
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "totalTokens": total_tokens,
        "estimatedCostUSD": estimated_cost,
        "pageCount": int(page_count or 0),
        "status": str(data.get("status") or "succeeded"),
        "errorMessage": str(data.get("errorMessage") or ""),
    }


def first_present(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def number_or_none(value: Any) -> int | float | None:
    if value in (None, ""):
        return None
    try:
        number = float(str(value).replace("$", "").replace(",", ""))
    except ValueError:
        return None
    if number.is_integer():
        return int(number)
    return number


def update_frame_review(body: dict[str, Any]) -> dict[str, Any]:
    session_dir = require_session_dir(body.get("sessionId"))
    action = normalize_frame_review_action(body)
    frame_id = require_frame_id(body.get("frameId"))
    if action not in {"approve", "reject", "pending", "assign", "note"}:
        raise HttpError(HTTPStatus.BAD_REQUEST, "action must be approve, reject, pending, assign, or note.")
    require_known_frame(session_dir, frame_id)

    review = read_frame_review(session_dir)
    entry = ensure_review_entry(review, frame_id)
    entry["updatedUtc"] = utc_now()

    if action in {"approve", "reject", "pending"}:
        entry["status"] = "approved" if action == "approve" else "rejected" if action == "reject" else "pending"
    elif action == "assign":
        segment_id = optional_segment_id(body.get("segmentId") or body.get("assignedSegmentId"))
        entry["assignedSegmentId"] = segment_id
    elif action == "note":
        entry["note"] = string_value(body.get("note") or body.get("reviewNote"), "")

    if ("note" in body or "reviewNote" in body) and action != "note":
        entry["note"] = string_value(body.get("note") or body.get("reviewNote"), "")
    if ("segmentId" in body or "assignedSegmentId" in body) and action != "assign":
        entry["assignedSegmentId"] = optional_segment_id(body.get("segmentId") or body.get("assignedSegmentId"))

    save_frame_review(session_dir, review)
    return {"sessionId": session_dir.name, "frameReview": read_frame_review_view(session_dir)}


def normalize_frame_review_action(body: dict[str, Any]) -> str:
    action = string_value(body.get("action"), "").lower()
    if action:
        return {"approved": "approve", "rejected": "reject"}.get(action, action)
    status = string_value(body.get("reviewStatus") or body.get("status"), "").lower()
    return {"approved": "approve", "rejected": "reject", "pending": "pending"}.get(status, "")


def extract_review_frame(body: dict[str, Any]) -> dict[str, Any]:
    session_dir = require_session_dir(body.get("sessionId"))
    timestamp_seconds = parse_timestamp_value(body.get("timestampSeconds", body.get("timestamp")))
    frame_id = optional_frame_id(body.get("frameId")) or next_review_frame_id(session_dir)
    assigned_segment_id = optional_segment_id(body.get("segmentId") or body.get("assignedSegmentId"))
    if (session_dir / "frames" / "candidates" / f"{frame_id}.png").exists():
        raise HttpError(HTTPStatus.CONFLICT, f"Frame already exists: {frame_id}")

    manifest = read_json_if_exists(session_dir / "manifest.json")
    source = session_source_path(manifest)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HttpError(HTTPStatus.SERVICE_UNAVAILABLE, "ffmpeg is required to extract an additional frame.")

    candidates_dir = session_dir / "frames" / "candidates"
    candidates_dir.mkdir(parents=True, exist_ok=True)
    output = safe_join(candidates_dir, f"{frame_id}.png")
    crop_filter = manifest.get("processing", {}).get("frameCropFilter") if isinstance(manifest.get("processing"), dict) else None
    command = [ffmpeg, "-y", "-ss", str(timestamp_seconds), "-i", str(source), "-frames:v", "1"]
    if crop_filter:
        command.extend(["-vf", str(crop_filter)])
    command.extend(["-hide_banner", "-loglevel", "error", str(output)])
    result = run_command(command)
    if result["returnCode"] != 0 or not output.exists():
        raise HttpError(HTTPStatus.INTERNAL_SERVER_ERROR, result["stderr"] or f"ffmpeg exited {result['returnCode']}")

    frame = build_review_frame_record(session_dir, frame_id, timestamp_seconds, crop_filter)
    frame = enrich_review_frame_record(session_dir, frame, assigned_segment_id)
    append_frame_score(session_dir, frame)

    review = read_frame_review(session_dir)
    entry = ensure_review_entry(review, frame_id)
    entry["status"] = string_value(body.get("reviewStatus") or body.get("status"), "pending").lower()
    if entry["status"] not in {"approved", "rejected", "pending"}:
        entry["status"] = "pending"
    entry["note"] = string_value(body.get("note") or body.get("reviewNote"), entry.get("note", ""))
    entry["assignedSegmentId"] = assigned_segment_id
    entry["addedByReviewer"] = True
    entry["updatedUtc"] = utc_now()
    save_frame_review(session_dir, review)

    return {
        "sessionId": session_dir.name,
        "frame": {**frame, **entry},
        "command": command_summary(command),
        "result": result,
        "frameReview": read_frame_review_view(session_dir),
    }


def read_frame_review_view(session_dir: Path) -> dict[str, Any]:
    review = read_frame_review(session_dir)
    frames = merge_frame_review(session_dir, review)
    return {
        **review,
        "decisions": review.get("frames", {}),
        "summary": summarize_frame_review(review, frames),
        "frames": frames,
    }


def read_frame_review(session_dir: Path) -> dict[str, Any]:
    data = read_json_if_exists(session_dir / "frame_review.json")
    if not data:
        return {
            "schemaVersion": 1,
            "sessionId": session_dir.name,
            "updatedUtc": None,
            "frames": {},
        }
    frames = data.get("frames")
    if not isinstance(frames, dict):
        data["frames"] = {}
    data.setdefault("schemaVersion", 1)
    data.setdefault("sessionId", session_dir.name)
    data.setdefault("updatedUtc", None)
    return data


def save_frame_review(session_dir: Path, review: dict[str, Any]) -> None:
    review["schemaVersion"] = 1
    review["sessionId"] = session_dir.name
    review["updatedUtc"] = utc_now()
    write_json_file(session_dir / "frame_review.json", review)


def merge_frame_review(session_dir: Path, review: dict[str, Any]) -> list[dict[str, Any]]:
    frame_scores = read_json_if_exists(session_dir / "frame_scores.json")
    frames = frame_scores.get("frames", []) if isinstance(frame_scores.get("frames"), list) else []
    entries = review.get("frames", {}) if isinstance(review.get("frames"), dict) else {}
    merged = []
    for frame in frames:
        if not isinstance(frame, dict) or not frame.get("id"):
            continue
        entry = entries.get(frame["id"], {}) if isinstance(entries.get(frame["id"]), dict) else {}
        merged.append(
            {
                **frame,
                "reviewStatus": entry.get("status", "pending"),
                "reviewNote": entry.get("note", ""),
                "assignedSegmentId": entry.get("assignedSegmentId"),
                "addedByReviewer": bool(entry.get("addedByReviewer", frame.get("source") == "manual-review-extract")),
                "reviewUpdatedUtc": entry.get("updatedUtc"),
            }
        )
    return merged


def summarize_frame_review(review: dict[str, Any], frames: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    entries = review.get("frames", {}) if isinstance(review.get("frames"), dict) else {}
    frame_list = frames or []
    if not frame_list and entries:
        frame_list = [{"reviewStatus": entry.get("status", "pending")} for entry in entries.values() if isinstance(entry, dict)]
    counts = {"approved": 0, "rejected": 0, "pending": 0}
    for frame in frame_list:
        status = frame.get("reviewStatus") or frame.get("status") or "pending"
        counts[status if status in counts else "pending"] += 1
    return {
        "totalFrames": len(frame_list),
        "approved": counts["approved"],
        "rejected": counts["rejected"],
        "pending": counts["pending"],
        "updatedUtc": review.get("updatedUtc"),
    }


def apply_frame_review_to_trace(trace: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    entries = review.get("frames", {}) if isinstance(review.get("frames"), dict) else {}
    if not entries:
        return trace
    merged = json.loads(json.dumps(trace))
    segments = merged.get("segments", []) if isinstance(merged.get("segments"), list) else []
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
            entry = entries.get(image.get("frameId"), {})
            if not isinstance(entry, dict):
                continue
            image["reviewStatus"] = entry.get("status", image.get("reviewStatus", "pending"))
            image["reviewNote"] = entry.get("note", "")
            image["assignedSegmentId"] = entry.get("assignedSegmentId")

    frame_lookup = load_frame_score_lookup(session_dir_from_trace(merged))
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
        image["reviewStatus"] = entry.get("status", image.get("reviewStatus", "pending"))
        image["reviewNote"] = entry.get("note", "")
        image["assignedSegmentId"] = assigned_segment_id
        image["addedByReviewer"] = bool(entry.get("addedByReviewer", image.get("addedByReviewer", False)))
        segment_lookup[assigned_segment_id].setdefault("candidateImages", []).append(image)
        seen_by_segment.setdefault(assigned_segment_id, set()).add(frame_id)
    return merged


def session_dir_from_trace(trace: dict[str, Any]) -> Path:
    session_id = str(trace.get("sessionId") or "")
    if session_id and SESSION_ID_RE.fullmatch(session_id):
        return PROCESSED_ROOT / session_id
    return PROCESSED_ROOT


def load_frame_score_lookup(session_dir: Path) -> dict[str, dict[str, Any]]:
    payload = read_json_if_exists(session_dir / "frame_scores.json")
    frames = payload.get("frames") if isinstance(payload.get("frames"), list) else []
    return {frame.get("id"): frame for frame in frames if isinstance(frame, dict) and frame.get("id")}


def frame_score_to_candidate_image(frame: dict[str, Any]) -> dict[str, Any]:
    quality = frame.get("qualitySignals") if isinstance(frame.get("qualitySignals"), dict) else {}
    image = {
        "frameId": frame.get("id", ""),
        "path": frame.get("path"),
        "webPath": frame.get("webPath") or frame.get("path"),
        "timestamp": frame.get("timestamp", ""),
        "timestampSeconds": frame.get("timestampSeconds", 0),
        "score": frame.get("score", 0),
        "confidence": frame.get("confidence", frame.get("score", 0)),
        "visualQualityScore": frame.get("visualQualityScore", quality.get("qualityScore")),
        "blurState": frame.get("blurState", quality.get("blurState")),
        "dedupeState": frame.get("dedupeState", quality.get("dedupeState")),
        "duplicateOfFrameId": frame.get("duplicateOfFrameId", quality.get("duplicateOfFrameId")),
        "created": frame.get("created", False),
        "reason": frame.get("reason") or frame.get("selectionReason", "Added during frame review."),
        "reviewStatus": "pending",
    }
    for key in REVIEW_FRAME_EVIDENCE_KEYS:
        if key in frame:
            image[key] = frame.get(key)
    return image


def ensure_review_entry(review: dict[str, Any], frame_id: str) -> dict[str, Any]:
    frames = review.setdefault("frames", {})
    entry = frames.setdefault(
        frame_id,
        {
            "frameId": frame_id,
            "status": "pending",
            "note": "",
            "assignedSegmentId": None,
            "addedByReviewer": False,
            "updatedUtc": None,
        },
    )
    if not isinstance(entry, dict):
        entry = {"frameId": frame_id, "status": "pending", "note": "", "assignedSegmentId": None}
        frames[frame_id] = entry
    entry.setdefault("frameId", frame_id)
    entry.setdefault("status", "pending")
    entry.setdefault("note", "")
    entry.setdefault("assignedSegmentId", None)
    return entry


def require_known_frame(session_dir: Path, frame_id: str) -> dict[str, Any]:
    frame_scores = read_json_if_exists(session_dir / "frame_scores.json")
    for frame in frame_scores.get("frames", []) if isinstance(frame_scores.get("frames"), list) else []:
        if isinstance(frame, dict) and frame.get("id") == frame_id:
            return frame
    raise HttpError(HTTPStatus.NOT_FOUND, f"Frame not found in session: {frame_id}")


def append_frame_score(session_dir: Path, frame: dict[str, Any]) -> None:
    path = session_dir / "frame_scores.json"
    frame_scores = read_json_if_exists(path)
    frame_scores.setdefault("schemaVersion", 1)
    frame_scores.setdefault("source", "ffmpeg-interval-extract")
    frames = frame_scores.setdefault("frames", [])
    if not isinstance(frames, list):
        frames = []
        frame_scores["frames"] = frames
    frames.append(frame)
    frames.sort(key=lambda item: item.get("timestampSeconds", 0) if isinstance(item, dict) else 0)
    write_json_file(path, frame_scores)


def enrich_review_frame_record(session_dir: Path, frame: dict[str, Any], assigned_segment_id: str | None) -> dict[str, Any]:
    processor = load_process_recording_module()
    if not processor:
        return frame

    enriched = dict(frame)
    visual = processor.evaluate_frame_visual_quality(enriched, session_dir)
    duplicate_of = nearest_existing_duplicate(processor, session_dir, str(visual.get("averageHash") or ""))
    visual["dedupeState"] = "near-duplicate" if duplicate_of else "unique"
    visual["duplicateOfFrameId"] = duplicate_of
    enriched["qualitySignals"] = {
        "createdImage": True,
        "sampleIntervalSeconds": None,
        **visual,
    }
    enriched["selectionReason"] = processor.frame_selection_reason(visual, duplicate_of)
    enriched["score"] = processor.clamp01(0.68 + (float(visual.get("qualityScore") or 0) * 0.24) - (0.12 if duplicate_of else 0.0))

    trace = read_json_if_exists(session_dir / "procedure_trace.json")
    target_application = (
        trace.get("recording", {}).get("targetApplication")
        if isinstance(trace.get("recording"), dict)
        else None
    ) or "Unknown"
    segment = segment_context_for_review_frame(trace, assigned_segment_id, enriched)
    ocr_frame = ocr_review_frame(processor, session_dir, enriched, target_application)
    append_ocr_frame(session_dir, ocr_frame)

    candidate = processor.build_candidate_image(enriched, ocr_frame, segment, str(target_application))
    candidate = processor.assign_frame_recommendation_groups([candidate])[0]
    for key in REVIEW_FRAME_EVIDENCE_KEYS:
        if key in candidate:
            enriched[key] = candidate.get(key)
    enriched["manualReviewEnriched"] = True
    enriched["manualReviewEnrichedUtc"] = utc_now()
    return enriched


REVIEW_FRAME_EVIDENCE_KEYS = (
    "confidence",
    "frameEvidenceScore",
    "ocrConfidence",
    "ocrRelevanceScore",
    "ocrNonApplication",
    "ocrSupportingTool",
    "ocrClass",
    "ocrClassConfidence",
    "appOcrScore",
    "appTermHits",
    "supportingToolHits",
    "nonApplicationHits",
    "ocrTokenCount",
    "supportingToolAllowed",
    "visualQualityScore",
    "blurState",
    "dedupeState",
    "duplicateOfFrameId",
    "ocrText",
    "ocrSource",
    "contentType",
    "recommendationGroup",
    "selectionDecision",
    "recommendationReason",
    "selectionReasons",
    "positiveSignals",
    "penalties",
    "reason",
)


def load_process_recording_module() -> Any | None:
    global PROCESS_RECORDING_MODULE
    if PROCESS_RECORDING_MODULE is not None:
        return PROCESS_RECORDING_MODULE
    path = WORKSPACE / "scripts" / "process_recording.py"
    spec = importlib.util.spec_from_file_location("kcxdocumentor_process_recording", path)
    if not spec or not spec.loader:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    PROCESS_RECORDING_MODULE = module
    return module


def nearest_existing_duplicate(processor: Any, session_dir: Path, average_hash: str) -> str | None:
    if not average_hash:
        return None
    frame_scores = read_json_if_exists(session_dir / "frame_scores.json")
    prior_hashes = []
    for frame in frame_scores.get("frames", []) if isinstance(frame_scores.get("frames"), list) else []:
        quality = frame.get("qualitySignals") if isinstance(frame.get("qualitySignals"), dict) else {}
        prior_hash = quality.get("averageHash")
        if frame.get("id") and prior_hash:
            prior_hashes.append((str(frame["id"]), str(prior_hash)))
    return processor.nearest_visual_duplicate(average_hash, prior_hashes)


def segment_context_for_review_frame(trace: dict[str, Any], assigned_segment_id: str | None, frame: dict[str, Any]) -> dict[str, Any]:
    segments = trace.get("segments") if isinstance(trace.get("segments"), list) else []
    if assigned_segment_id:
        for segment in segments:
            if isinstance(segment, dict) and segment.get("id") == assigned_segment_id:
                return segment_to_processor_context(segment)
    timestamp = float(frame.get("timestampSeconds") or 0)
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        start = float(segment.get("startSeconds") or 0)
        end = float(segment.get("endSeconds") or start)
        if start <= timestamp <= end:
            return segment_to_processor_context(segment)
    return {
        "text": "",
        "start": frame.get("timestamp", ""),
        "end": frame.get("timestamp", ""),
        "startSeconds": timestamp,
        "endSeconds": timestamp,
        "confidence": 0.75,
    }


def segment_to_processor_context(segment: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": segment.get("speakerText") or segment.get("text") or "",
        "start": segment.get("start", ""),
        "end": segment.get("end", ""),
        "startSeconds": segment.get("startSeconds", 0),
        "endSeconds": segment.get("endSeconds", 0),
        "confidence": segment.get("confidence", {}).get("transcript", 0.75) if isinstance(segment.get("confidence"), dict) else 0.75,
    }


def ocr_review_frame(processor: Any, session_dir: Path, frame: dict[str, Any], target_application: str) -> dict[str, Any]:
    tesseract = shutil.which("tesseract")
    if not tesseract:
        return processor.build_placeholder_ocr_frame(frame, target_application, "tesseract not available for manual review frame")

    language = os.environ.get("KCXDOC_OCR_LANGUAGE", "eng")
    psm = os.environ.get("KCXDOC_OCR_PSM", "6")
    timeout_seconds = processor.parse_float(os.environ.get("KCXDOC_OCR_TIMEOUT_SECONDS")) or 45.0
    result = processor.run_tesseract_ocr(
        tesseract,
        session_dir / str(frame.get("path") or ""),
        language=language,
        psm=str(psm),
        timeout_seconds=timeout_seconds,
    )
    text_blocks = result.get("textBlocks") or []
    if not text_blocks:
        return processor.build_placeholder_ocr_frame(frame, target_application, result.get("error") or "no text detected")
    return {
        "frameId": frame["id"],
        "timestampSeconds": frame["timestampSeconds"],
        "timestamp": frame["timestamp"],
        "source": "tesseract",
        "language": language,
        "pageSegmentationMode": str(psm),
        "confidence": processor.average_block_confidence(text_blocks),
        "combinedText": " ".join(block["text"] for block in text_blocks),
        "textBlocks": text_blocks,
        "error": None,
    }


def append_ocr_frame(session_dir: Path, ocr_frame: dict[str, Any]) -> None:
    path = session_dir / "ocr.json"
    payload = read_json_if_exists(path) or {"schemaVersion": 1, "source": "tesseract", "frames": []}
    payload.setdefault("schemaVersion", 1)
    frames = payload.setdefault("frames", [])
    if not isinstance(frames, list):
        frames = []
        payload["frames"] = frames
    frame_id = ocr_frame.get("frameId")
    frames[:] = [frame for frame in frames if not isinstance(frame, dict) or frame.get("frameId") != frame_id]
    frames.append(ocr_frame)
    frames.sort(key=lambda item: item.get("timestampSeconds", 0) if isinstance(item, dict) else 0)
    if any(isinstance(frame, dict) and frame.get("source") == "tesseract" for frame in frames):
        payload["source"] = "tesseract"
    write_json_file(path, payload)


def build_review_frame_record(session_dir: Path, frame_id: str, timestamp_seconds: float, crop_filter: str | None) -> dict[str, Any]:
    relative_path = Path("frames") / "candidates" / f"{frame_id}.png"
    return {
        "id": frame_id,
        "timestampSeconds": timestamp_seconds,
        "timestamp": format_timestamp(timestamp_seconds),
        "path": str(relative_path),
        "webPath": str(relative_path).replace("\\", "/"),
        "created": True,
        "source": "manual-review-extract",
        "sourceProfile": "review",
        "cropFilter": crop_filter,
        "error": None,
        "score": 0.9,
        "qualitySignals": {
            "createdImage": True,
            "sampleIntervalSeconds": None,
            "dedupeState": "not-evaluated-review-add",
            "blurState": "not-evaluated-review-add",
        },
        "selectionReason": "Added by reviewer at a requested timestamp.",
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


def latest_file_mtime(root: Path) -> float | None:
    if not root.exists() or not root.is_dir():
        return None
    timestamps = [path.stat().st_mtime for path in root.iterdir() if path.is_file() and not path.name.startswith(".")]
    return max(timestamps) if timestamps else None


def run_command(command: list[str], extra_env: dict[str, str] | None = None) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if extra_env:
        env.update(extra_env)
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


def parse_byte_range(range_header: str, file_size: int) -> tuple[int, int]:
    match = re.match(r"^bytes=(\d*)-(\d*)$", range_header.strip())
    if not match:
        raise HttpError(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, "Unsupported Range header.")
    start_text, end_text = match.groups()
    if not start_text and not end_text:
        raise HttpError(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, "Invalid Range header.")
    if start_text:
        start = int(start_text)
        end = int(end_text) if end_text else file_size - 1
    else:
        suffix_length = int(end_text)
        if suffix_length <= 0:
            raise HttpError(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, "Invalid suffix range.")
        start = max(0, file_size - suffix_length)
        end = file_size - 1
    if start >= file_size or end < start:
        raise HttpError(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, "Requested range is outside the file.")
    return start, min(end, file_size - 1)


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
    session_dir = require_child_dir(PROCESSED_ROOT, session_id, "Session")
    if not session_dir.is_dir():
        raise HttpError(HTTPStatus.NOT_FOUND, "Session not found in samples/processed.")
    return session_dir


def require_child_dir(root: Path, child_name: str, label: str) -> Path:
    root = root.resolve()
    child = (root / child_name).resolve()
    if not is_relative_to(child, root):
        raise HttpError(HTTPStatus.BAD_REQUEST, f"{label} path escapes its allowed root.")
    return child


def optional_child_dir(root: Path, child_name: str, label: str) -> Path | None:
    root = root.resolve()
    child = (root / child_name).resolve()
    if not is_relative_to(child, root):
        raise HttpError(HTTPStatus.BAD_REQUEST, f"{label} path escapes its allowed root.")
    return child


def require_session_id(raw_value: Any) -> str:
    session_id = string_value(raw_value, "")
    if not SESSION_ID_RE.match(session_id):
        raise HttpError(HTTPStatus.BAD_REQUEST, "sessionId is required and may only contain letters, numbers, dots, underscores, and hyphens.")
    return session_id


def optional_session_id(raw_value: Any) -> str | None:
    if raw_value is None or str(raw_value).strip() == "":
        return None
    return require_session_id(raw_value)


def require_frame_id(raw_value: Any) -> str:
    frame_id = string_value(raw_value, "")
    if not FRAME_ID_RE.match(frame_id):
        raise HttpError(HTTPStatus.BAD_REQUEST, "frameId is required and may only contain letters, numbers, dots, underscores, and hyphens.")
    return frame_id


def optional_frame_id(raw_value: Any) -> str | None:
    if raw_value is None or str(raw_value).strip() == "":
        return None
    return require_frame_id(raw_value)


def optional_segment_id(raw_value: Any) -> str | None:
    if raw_value is None or str(raw_value).strip() == "":
        return None
    segment_id = string_value(raw_value, "")
    if not SEGMENT_ID_RE.match(segment_id):
        raise HttpError(HTTPStatus.BAD_REQUEST, "segmentId may only contain letters, numbers, dots, underscores, and hyphens.")
    return segment_id


def parse_timestamp_value(raw_value: Any) -> float:
    if isinstance(raw_value, (int, float)):
        return round_positive(float(raw_value))
    value = string_value(raw_value, "")
    if not value:
        raise HttpError(HTTPStatus.BAD_REQUEST, "timestampSeconds or timestamp is required.")
    if re.match(r"^\d+(\.\d+)?$", value):
        return round_positive(float(value))
    parts = value.split(":")
    if not 2 <= len(parts) <= 3:
        raise HttpError(HTTPStatus.BAD_REQUEST, "timestamp must be seconds, mm:ss, or hh:mm:ss.")
    try:
        numbers = [float(part) for part in parts]
    except ValueError as exc:
        raise HttpError(HTTPStatus.BAD_REQUEST, "timestamp must contain numeric values.") from exc
    if len(numbers) == 2:
        minutes, seconds = numbers
        total = (minutes * 60) + seconds
    else:
        hours, minutes, seconds = numbers
        total = (hours * 3600) + (minutes * 60) + seconds
    return round_positive(total)


def round_positive(value: float) -> float:
    if value < 0:
        raise HttpError(HTTPStatus.BAD_REQUEST, "timestamp must be zero or greater.")
    return round(value, 3)


def session_source_path(manifest: dict[str, Any]) -> Path:
    inputs = manifest.get("inputs", {})
    input_recording = inputs.get("recording") if isinstance(inputs, dict) else ""
    raw = string_value(manifest.get("sourceFile") or input_recording, "")
    if not raw:
        raise HttpError(HTTPStatus.NOT_FOUND, "Session manifest does not include a source recording path.")
    source = Path(raw).expanduser().resolve()
    if not source.is_file():
        raise HttpError(HTTPStatus.NOT_FOUND, f"Source recording not found: {source}")
    return source


def next_review_frame_id(session_dir: Path) -> str:
    frame_scores = read_json_if_exists(session_dir / "frame_scores.json")
    existing = {
        frame.get("id")
        for frame in frame_scores.get("frames", [])
        if isinstance(frame, dict) and isinstance(frame.get("id"), str)
    }
    for index in range(1, 10000):
        frame_id = f"review-frame-{index:04d}"
        if frame_id not in existing and not (session_dir / "frames" / "candidates" / f"{frame_id}.png").exists():
            return frame_id
    raise HttpError(HTTPStatus.CONFLICT, "Could not choose a unique review frame id.")


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


def write_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


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


def utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def format_timestamp(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    whole_seconds = int(seconds)
    hours = whole_seconds // 3600
    minutes = (whole_seconds % 3600) // 60
    remaining = whole_seconds % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{remaining:02d}"
    return f"{minutes:02d}:{remaining:02d}"


def redact(text: str) -> str:
    redacted = text
    for pattern in REDACTION_PATTERNS:
        redacted = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]" if match.groups() else "[REDACTED]", redacted)
    return redacted


if __name__ == "__main__":
    raise SystemExit(main())
