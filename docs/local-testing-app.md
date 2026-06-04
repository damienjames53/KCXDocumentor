# Local Testing App

KCXDocumentor includes a tiny Python stdlib server for early end-to-end testing. It serves any static UI placed in `web/` and exposes JSON APIs that wrap the existing processing, guide-draft, and DOCX scripts.

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
  "targetApplication": "Enterprise Rx",
  "sessionId": "local-test",
  "noMediaTools": true
}
```

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

curl -X POST http://127.0.0.1:8765/api/process \
  -H 'Content-Type: application/json' \
  -d '{"recording":"example.mp4","targetApplication":"Enterprise Rx","sessionId":"local-test","noMediaTools":true}'

curl -X POST http://127.0.0.1:8765/api/generate-draft \
  -H 'Content-Type: application/json' \
  -d '{"sessionId":"local-test","useAnthropic":false}'

curl -X POST http://127.0.0.1:8765/api/build-docx \
  -H 'Content-Type: application/json' \
  -d '{"sessionId":"local-test","draft":"deterministic"}'
```

Generated outputs are written under `artifacts/generated/<sessionId>/`.
