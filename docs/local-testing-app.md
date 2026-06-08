# Local Testing App

KCXDocumentor includes a tiny Python stdlib server for early end-to-end testing. It serves any static UI placed in `web/` and exposes JSON APIs that wrap the existing processing, guide-draft, and DOCX scripts.

## UI Standard

The current prototype is a local web console. If this evolves into a thicker Windows client or a full web client, the visual language should still follow the read-only `KCXUIComponents` reference project.

Current local CSS uses the KCXUIComponents semantic token model as the source of truth:

- `--kcx-ui-color-page`
- `--kcx-ui-color-surface`
- `--kcx-ui-color-border`
- `--kcx-ui-color-text`
- `--kcx-ui-color-muted`
- `--kcx-ui-color-primary`
- `--kcx-ui-radius-*`
- `--kcx-ui-shadow-*`

Avoid one-off palettes or component forks. New controls should map to KCXUIComponents-style primitives: panels, buttons, status badges, form fields, top/app shell, and layout grids.

Run it from the repo root:

```bash
python3 scripts/app_server.py --host 127.0.0.1 --port 8765
```

For Docker-based local testing, stop any existing Python server on port `8765`, then run:

```bash
docker compose up -d --build
```

Docker uses the same browser URL as the Python process. The container listens internally on `0.0.0.0:8765`, and Compose maps it to `http://127.0.0.1:8765`.

Open:

```text
http://127.0.0.1:8765
```

The local console is protected with Microsoft Entra MSAL + PKCE when `KCXDOC_AUTH_ENABLED=true`.
Auth settings are loaded from the repo-local ignored `.env` file:

```text
KCXDOC_AUTH_TENANT_ID=543e31cf-f2b9-457e-88af-82a3938c2913
KCXDOC_AUTH_CLIENT_ID=9d5d6572-b583-4df9-8fe6-8f96c71fad58
KCXDOC_AUTH_AUTHORITY=https://login.microsoftonline.com/543e31cf-f2b9-457e-88af-82a3938c2913
KCXDOC_AUTH_REDIRECT_URI=http://127.0.0.1:8765/
KCXDOC_AUTH_POST_LOGOUT_REDIRECT_URI=http://127.0.0.1:8765/
KCXDOC_AUTH_SCOPES=openid profile
```

After sign-in, the browser sends a validated Entra token to the local server and receives a short-lived HttpOnly local session cookie. API routes, screenshot assets, and the video reviewer are protected by that session. Use **Logout** in the header to clear both the MSAL session and the local app session.

If `web/index.html` does not exist yet, static root requests will return a 404 JSON response. The API endpoints still work.

## BA/Trainer Workflow

The console is organized around the shortest safe path to a reviewable guide:

1. Import or select a recording.
2. Import or select a transcript when one exists. Teams sidecar transcripts should be preferred; leaving the transcript blank falls back to local Whisper during processing.
3. Choose **Process Recording** to create a session summary and candidate screenshots.
4. Review frames before guide generation. Approved frames are preferred, rejected frames are excluded from screenshot candidates, and rejected-frame notes are preserved as reviewer guidance.
5. Choose **Create Guide** to generate guide content and prepare the DOCX.
6. Choose **Download DOCX** or use the DOCX download link in the Artifacts tab. Use **Re-run QA** as a secondary status check after guide or screenshot changes.

## Endpoints

Except for `/api/auth-config`, `/api/auth-session`, `/api/logout`, and `/api/health`, API endpoints require authentication when local auth is enabled. Browser requests are handled by the MSAL login flow. Direct `curl` testing must include a valid bearer token or temporarily set `KCXDOC_AUTH_ENABLED=false` in `.env` for local-only diagnostics.

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

`POST /api/delete-session`

Deletes one processed session folder and its matching generated artifacts folder:

- `samples/processed/<sessionId>`
- `artifacts/generated/<sessionId>`

```json
{
  "sessionId": "local-test"
}
```

The endpoint validates `sessionId`, resolves both target directories under their allowed roots, and rejects path traversal or symlink escapes. Generated artifacts remain ignored and untracked.

The prototype UI exposes this cleanup in two places:

- Use **Delete Session** in the selected session header to remove the loaded session.
- Use **Delete** beside a session in the Sessions list to remove stale sessions without loading them first.

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

Runs `scripts/generate_guide_draft.py` against `samples/processed/<sessionId>/procedure_trace.json`. In the local UI this is part of the **Create Guide** workflow.

```json
{
  "sessionId": "local-test"
}
```

The underlying script sends the compact prompt payload to the Azure Function configured in `KCXDOC_REMOTE_API_BASE_URL`. The local app does not call Anthropic or Azure Foundry directly. Provider credentials belong on the Function App only; the production provider setting is `KCXDOC_FOUNDRY_API_KEY`.

For the UI workflow, **Create Guide** now starts a local generation job with `POST /api/generation-jobs` and polls `GET /api/generation-jobs?jobId=<id>`. The local job runs the AI draft, DOCX build, and local QA chain in the background so the browser can show queued/running/building/QA status instead of appearing stuck.

When the remote Azure Function is configured, the generator opts into the queued cloud route. The Function stores the prompt job in Cosmos DB, places a lightweight pointer on the existing Function storage queue, and the queue worker calls Azure Foundry. This protects the shared Foundry TPM limit when multiple workstations create guides at the same time.

When `artifacts/generated/<sessionId>/guide_draft.anthropic.json` includes Claude generation metadata such as `model`, `generatedAt`, and `usage`, the local console surfaces the model, token totals, estimated cost, and timestamp in the Artifacts view and Readiness checks. The `anthropic` filename is a compatibility artifact name for the Claude Messages-format draft.

The selected session's current generation token cost remains visible in the Artifacts tab after the draft metadata is available. Aggregate token reporting lives on the top-level **AI Spend** page in the main navigation, with the current calendar month spend also visible in the header.

Generation usage is persisted in Cosmos DB through the Azure Function. **Delete Session** removes local working artifacts but does not erase historical token/cost reporting.

Set `KCXDOC_REMOTE_API_BASE_URL` to the Function App base URL, such as `https://kcxdocumentor-ai-dev.azurewebsites.net`. If the remote API is unset or unavailable, guide generation and AI Spend reporting fail visibly instead of falling back to stale local data.

To prepare existing legacy SQLite records for a one-time remote migration without making any Azure calls:

```bash
python3 scripts/app_server.py --export-usage-json artifacts/usage/usage-export.json
```

Omit the output path, or pass `-`, to write the export JSON to stdout.

`GET /api/usage-summary?range=<day|week|month|year>`

Returns aggregate generation usage for the local app dashboard. The UI calls this endpoint when the AI Spend page opens, when the range selector changes, and after a draft is generated.

Expected response:

```json
{
  "range": "week",
  "generatedAt": "2026-06-04T15:30:00Z",
  "totals": {
    "documents": 3,
    "attempts": 4,
    "failedAttempts": 1,
    "inputTokens": 42000,
    "outputTokens": 8600,
    "totalTokens": 50600,
    "pageCount": 12,
    "costPerPageUSD": 0.072675,
    "estimatedCostUSD": 0.8721
  },
  "buckets": [
    {
      "label": "2026-W23",
      "totals": {
        "documents": 1,
        "attempts": 2,
        "failedAttempts": 1,
        "inputTokens": 14000,
        "outputTokens": 2800,
        "totalTokens": 16800,
        "pageCount": 4,
        "costPerPageUSD": 0.072675,
        "estimatedCostUSD": 0.2907
      },
      "documents": [
        {
          "sessionId": "blink-rx-part-2",
          "title": "Blink Rx Workflow Guide",
          "generatedAt": "2026-06-04T15:30:00Z",
          "generatedBy": {
            "oid": "00000000-0000-0000-0000-000000000000",
            "name": "Damien James",
            "username": "damien.james@example.com"
          },
          "status": "succeeded",
          "usage": {
            "totalTokens": 16800,
            "pageCount": 4,
            "estimatedCostUSD": 0.2907,
            "costPerPageUSD": 0.072675
          }
        }
      ]
    }
  ]
}
```

Each bucket document entry includes `generatedBy`, `status`, and `errorMessage`. Failed attempts are included in token and cost totals, but they do not increment the successful `documents` count. The response also includes `days` for compatibility when the selected range is `day`. If the endpoint is not available yet, the dashboard leaves usage metrics blank and shows a non-blocking empty state.

`POST /api/build-docx`

Runs `scripts/build_guide_docx.py` against `guide_draft.anthropic.json`. In the local UI this prepares the DOCX surfaced by **Download DOCX** and the Artifacts tab.

```json
{
  "sessionId": "local-test"
}
```

`POST /api/qa-docx`

Runs local document QA against the generated DOCX. The UI treats this as a secondary **Re-run QA** status action rather than a required primary step.

```json
{
  "sessionId": "local-test",
  "strict": true
}
```

`GET /api/frame-review?sessionId=<id>`

Loads saved frame curation decisions from `samples/processed/<sessionId>/frame_review.json` and merges them with the session's `frame_scores.json`.

```json
{
  "frameReview": {
    "summary": {
      "totalFrames": 12,
      "approved": 4,
      "rejected": 3,
      "pending": 5
    },
    "frames": [
      {
        "id": "frame-0001",
        "reviewStatus": "approved",
        "reviewNote": "Best screenshot for the first action.",
        "assignedSegmentId": "seg-0001"
      }
    ],
    "decisions": {
      "frame-0001": {
        "status": "approved",
        "note": "Best screenshot for the first action.",
        "assignedSegmentId": "seg-0001"
      }
    }
  }
}
```

`GET /api/session?sessionId=<id>` also exposes `frameReview` and merges review status, notes, and segment assignment into each `procedureTrace.segments[].candidateImages[]` item.

`POST /api/frame-review`

Saves one frame curation decision at a time. The `action` value must be `approve`, `reject`, `pending`, `assign`, or `note`.

```json
{
  "sessionId": "local-test",
  "frameId": "frame-0001",
  "action": "approve",
  "note": "Use this screenshot in the final guide.",
  "assignedSegmentId": "seg-0001"
}
```

The persisted file uses this shape:

```json
{
  "schemaVersion": 1,
  "sessionId": "local-test",
  "frames": {
    "frame-0001": {
      "frameId": "frame-0001",
      "status": "approved",
      "note": "Use this screenshot in the final guide.",
      "assignedSegmentId": "seg-0001"
    }
  }
}
```

Rejected frames should be excluded from AI draft generation and DOCX rendering. Approved frames should be preferred when assigning screenshots to generated guide steps.

`POST /api/extract-frame`

Adds a new screenshot candidate by timestamp during review. The endpoint uses the original recording path and frame crop settings from `manifest.json`, writes a PNG under `frames/candidates/`, appends a `manual-review-extract` record to `frame_scores.json`, and creates a matching `frame_review.json` entry.

```json
{
  "sessionId": "local-test",
  "timestamp": "03:25",
  "frameId": "review-frame-0004",
  "status": "approved",
  "note": "Shows the final confirmation dialog.",
  "assignedSegmentId": "seg-0004"
}
```

`timestamp` accepts seconds, `mm:ss`, or `hh:mm:ss`. `frameId`, `status`, `note`, and `assignedSegmentId` are optional. The UI should reload the session after a successful response so the new candidate appears in the Frames tab.

Example update calls:

```bash
curl -X POST http://127.0.0.1:8765/api/frame-review \
  -H 'Content-Type: application/json' \
  -d '{"sessionId":"local-test","frameId":"frame-0001","action":"reject","note":"Teams title card, not application UI."}'

curl -X POST http://127.0.0.1:8765/api/extract-frame \
  -H 'Content-Type: application/json' \
  -d '{"sessionId":"local-test","timestamp":"03:25","status":"approved","assignedSegmentId":"seg-0004"}'
```

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
  -d '{"sessionId":"local-test"}'

curl -X POST http://127.0.0.1:8765/api/build-docx \
  -H 'Content-Type: application/json' \
  -d '{"sessionId":"local-test"}'

curl -X POST http://127.0.0.1:8765/api/qa-docx \
  -H 'Content-Type: application/json' \
  -d '{"sessionId":"local-test","strict":true}'

curl 'http://127.0.0.1:8765/api/usage-summary?range=week'
```

Generated outputs are written under `artifacts/generated/<sessionId>/`.
Generation usage metadata is retained in JSON artifacts, Cosmos-backed AI Spend reporting, and the local console. It is intentionally omitted from delivered DOCX guides.

Use **Delete Session** in the local UI when a processed recording or generated output has been removed and the stale session still appears in the session list. The control removes the processed session and matching generated artifacts, refreshes the session list, leaves files in `samples/raw` untouched, and preserves Cosmos-backed AI Spend history.
