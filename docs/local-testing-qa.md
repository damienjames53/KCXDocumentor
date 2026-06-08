# Local App Testing and QA

The local app should remain a thin stdlib server around the existing prototype pipeline. Tests should exercise helper functions directly instead of starting a long-lived HTTP process, so local development stays fast and does not require real video, FFmpeg, Whisper, Tesseract, OpenCV, Azure Foundry, Anthropic, or network access.

## Test Contract

`tests/test_app_server.py` is written as a future-facing contract for `scripts/app_server.py`. Until the server exists, the tests skip cleanly. Once implemented, the server should expose small helpers that can be tested without binding a port:

- `send_json`, `write_json`, or `write_json_response` to serialize JSON HTTP responses.
- `build_json_response` or `json_response_bytes` for pure JSON byte creation, if used.
- `safe_join`, `resolve_safe_path`, or `safe_resolve` to prevent path traversal outside the configured repo roots.
- `AppState` with `list_sessions` or `sessions` for processed-session discovery.
- `build_process_command` or `build_processing_command` for constructing the `scripts/process_recording.py` command without running it.
- `import_recording`, `copy_imported_recording`, or `save_uploaded_recording` when the UI gains a real import/upload path.
- `get_health`, `health_check`, `check_tooling`, or `get_tooling_status` when the API exposes local dependency readiness.

The preferred server design is a small `http.server` application with pure helper functions for file/path/session behavior. Request handlers should delegate to those helpers so pytest can cover behavior without needing a browser or background process.

## QA Expectations

Local app QA should prove these behaviors before the first video testing pass:

- JSON responses are UTF-8, use `application/json`, and include `Cache-Control: no-store`.
- User-supplied paths cannot escape the intended raw sample, processed sample, artifact, or repo-local roots.
- Session listing reads processed bundles from `samples/processed` and reports whether key outputs exist.
- Process command construction is deterministic and can enable `--no-media-tools` for smoke testing.
- Recording import/upload helpers copy media into `samples/raw` without allowing path traversal or arbitrary overwrite behavior.
- Transcript sidecar support can be tested without media tools, and should keep the text source marked as `sidecar-transcript`.
- Health/tooling checks should report FFmpeg and FFprobe readiness, and should include remote API readiness once that surface is added, without calling external services.
- Tests do not invoke FFmpeg, Azure Foundry, Anthropic, OCR, transcription, or long-running server loops.

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

## First Video Bias

The first actual-video pass should prefer fast evidence over completeness. Use a short clip, a transcript sidecar if one is available, and strict QA to prove the pipeline blocks placeholder or low-confidence output from being treated as publishable. Full one-hour recordings should wait until the short clip produces a coherent trace, candidate frames, guide draft, DOCX, and QA report.
