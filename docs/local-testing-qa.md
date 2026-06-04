# Local App Testing and QA

The local app should remain a thin stdlib server around the existing prototype pipeline. Tests should exercise helper functions directly instead of starting a long-lived HTTP process, so local development stays fast and does not require real video, FFmpeg, Whisper, Tesseract, OpenCV, Anthropic, or network access.

## Test Contract

`tests/test_app_server.py` is written as a future-facing contract for `scripts/app_server.py`. Until the server exists, the tests skip cleanly. Once implemented, the server should expose small helpers that can be tested without binding a port:

- `send_json`, `write_json`, or `write_json_response` to serialize JSON HTTP responses.
- `build_json_response` or `json_response_bytes` for pure JSON byte creation, if used.
- `safe_join`, `resolve_safe_path`, or `safe_resolve` to prevent path traversal outside the configured repo roots.
- `AppState` with `list_sessions` or `sessions` for processed-session discovery.
- `build_process_command` or `build_processing_command` for constructing the `scripts/process_recording.py` command without running it.

The preferred server design is a small `http.server` application with pure helper functions for file/path/session behavior. Request handlers should delegate to those helpers so pytest can cover behavior without needing a browser or background process.

## QA Expectations

Local app QA should prove these behaviors before the first video testing pass:

- JSON responses are UTF-8, use `application/json`, and include `Cache-Control: no-store`.
- User-supplied paths cannot escape the intended raw sample, processed sample, artifact, or repo-local roots.
- Session listing reads processed bundles from `samples/processed` and reports whether key outputs exist.
- Process command construction is deterministic and can enable `--no-media-tools` for smoke testing.
- Tests do not invoke FFmpeg, Anthropic, OCR, transcription, or long-running server loops.

Run the focused lane with:

```bash
.venv/bin/python -m pytest tests/test_app_server.py
```

Run the full local QA suite with:

```bash
.venv/bin/python -m pytest
npm run eval:fixtures
npm run eval:offline
```

Do not modify `/Users/djames/Documents/DamienDev` or `/Users/djames/Documents/AppDev/SmartReq` while building this lane. Those repositories are reference-only for this project.
