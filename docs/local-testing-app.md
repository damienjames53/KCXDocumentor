# Local Testing App

KCXDocumentor includes a tiny Python stdlib server for early end-to-end testing. It serves any static UI placed in `web/` and exposes JSON APIs that wrap the existing processing, guide-draft, and DOCX scripts.

## UI Standard

The current prototype is a local web console. If this evolves into a thicker Windows client or a full web client, the visual language should still follow the read-only `CustomerAppUI` reference project.

Current local CSS uses the CustomerAppUI semantic token model as the source of truth:

- `--kcx-ui-color-page`
- `--kcx-ui-color-surface`
- `--kcx-ui-color-border`
- `--kcx-ui-color-text`
- `--kcx-ui-color-muted`
- `--kcx-ui-color-primary`
- `--kcx-ui-radius-*`
- `--kcx-ui-shadow-*`

Avoid one-off palettes or component forks. New controls should map to CustomerAppUI-style primitives: panels, buttons, status badges, form fields, top/app shell, and layout grids.

Run it from the repo root:

```bash
python3 scripts/app_server.py --host 127.0.0.1 --port 8765
```

Open:

```text
http://127.0.0.1:8765
```

If `web/index.html` does not exist yet, static root requests will return a 404 JSON response. The API endpoints still work.

## Endpoints

`POST /api/import-recording`

Imports a local recording into `samples/raw` using `multipart/form-data`.

Expected form field:

```text
recording=<video file>
```

The UI accepts common video containers such as MP4, MKV, MOV, WEBM, and AVI. A successful response should include the stored name or path, for example:

```json
{
  "recording": "workflow-sample.mp4"
}
```

`POST /api/import-transcript`

Imports an optional transcript sidecar using `multipart/form-data`.

Expected form field:

```text
transcript=<transcript file>
```

The UI accepts JSON, TXT, VTT, SRT, CSV, and TSV transcript files. A successful response should include the stored transcript path or name:

```json
{
  "transcript": "workflow-sample.vtt"
}
```

`GET /api/transcripts`

Optional endpoint for listing transcript sidecars. The UI works without it, but if present it should return:

```json
{
  "transcripts": ["workflow-sample.vtt"]
}
```

`GET /api/recordings`

Lists files available under `samples/raw`.

`GET /api/sessions`

Lists processed sessions under `samples/processed` and any generated files under `artifacts/generated/<sessionId>`.

`GET /api/session?sessionId=<id>`

Returns a session summary, summaries of known JSON artifacts, and generated output files.

`POST /api/process`

Runs `scripts/process_recording.py`.

```json
{
  "recording": "example.mp4",
  "transcript": "example.vtt",
  "targetApplication": "Enterprise Rx",
  "sourceProfile": "standard",
  "sessionId": "local-test",
  "noMediaTools": false
}
```

The `transcript` property is optional. When provided, it is passed through to `scripts/process_recording.py --transcript` and takes precedence over local STT. When omitted, the processing script extracts narration audio with FFmpeg and runs local `whisper-cli` using the repo-local model at `models/whisper/ggml-base.en.bin`.

Use `"sourceProfile": "teams-recording"` for Microsoft Teams recordings that include title cards, participant rails, or meeting chrome. The local UI also auto-selects this profile when a recording filename looks like a Teams meeting recording.

`POST /api/generate-draft`

Runs `scripts/generate_guide_draft.py` against `samples/processed/<sessionId>/procedure_trace.json`.

```json
{
  "sessionId": "local-test",
  "useAnthropic": false
}
```

When `useAnthropic` is true, the underlying script uses `ANTHROPIC_API_KEY` from the process environment or `.env`. The server does not print environment variables or secrets.

`POST /api/build-docx`

Runs `scripts/build_guide_docx.py` against the selected generated draft.

```json
{
  "sessionId": "local-test",
  "draft": "deterministic"
}
```

The `draft` value must be `deterministic` or `anthropic`.

## Quick Smoke Flow

```bash
curl http://127.0.0.1:8765/api/recordings

curl -X POST http://127.0.0.1:8765/api/import-recording \
  -F 'recording=@samples/incoming/workflow-sample.mp4'

curl -X POST http://127.0.0.1:8765/api/import-transcript \
  -F 'transcript=@samples/incoming/workflow-sample.vtt'

curl -X POST http://127.0.0.1:8765/api/process \
  -H 'Content-Type: application/json' \
  -d '{"recording":"workflow-sample.mp4","transcript":"workflow-sample.vtt","targetApplication":"Enterprise Rx","sessionId":"local-test","noMediaTools":true}'

curl -X POST http://127.0.0.1:8765/api/generate-draft \
  -H 'Content-Type: application/json' \
  -d '{"sessionId":"local-test","useAnthropic":false}'

curl -X POST http://127.0.0.1:8765/api/build-docx \
  -H 'Content-Type: application/json' \
  -d '{"sessionId":"local-test","draft":"deterministic"}'
```

Generated outputs are written under `artifacts/generated/<sessionId>/`.
