# KCXDocumentor

KCXDocumentor is an isolated experiment for turning Windows workstation screen recordings into high-quality keycentrix user guides.

The product direction is token-aware by design: local processing converts long recordings into a compact procedure trace, then the AI layer receives only transcript segments, visible UI text, timing metadata, and a small set of candidate still images.

## Current Planning Assumption

- Initial samples are approximately one hour each.
- MVP consumes existing recordings.
- Later versions should capture the target Windows application window directly.
- Local speech-to-text should be used where possible to avoid AI transcription credits.
- DOCX output should follow the local keycentrix document rules and assets copied into this repo.

## Repo Layout

- `docs/` - implementation plan, architecture, document rules, testing, and model optimization notes.
- `schemas/` - JSON contracts for procedure traces and guide drafts.
- `assets/branding/` - copied keycentrix branding assets from DamienDev for isolated local builds.
- `tools/document_lib/` - copied and localized document helper code.
- `scripts/` - QA and eval helpers for generated artifacts.
- `tests/evals/` - golden-scenario fixture structure for AI/document regression tests.
- `samples/raw/` - local-only recording inputs; ignored by git.
- `samples/processed/` - local-only derived media and traces; ignored by git.
- `artifacts/generated/` - local generated DOCX/PDF outputs; ignored by git.
- `artifacts/qa/` - local rendered QA outputs; ignored by git.

## Reference Projects

The implementation plan was informed by read-only inspection of:

- `/Users/djames/Documents/DamienDev`
- `/Users/djames/Documents/AppDev/SmartReq`

Do not modify those projects from this repository.

## Prototype Flow

The first prototype is designed to work even before FFmpeg, Whisper, OCR, or an AI provider is wired in.

Install the Python prototype dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[test]"
```

```bash
.venv/bin/python scripts/process_recording.py samples/raw/example.mp4 --no-media-tools --target-application "Enterprise Rx" --session-id prototype-demo --force
.venv/bin/python scripts/generate_guide_draft.py samples/processed/prototype-demo/procedure_trace.json --output artifacts/generated/prototype-demo/guide_draft.anthropic.json
.venv/bin/python scripts/build_guide_docx.py artifacts/generated/prototype-demo/guide_draft.anthropic.json --output artifacts/generated/prototype-demo/user_guide.anthropic.docx
.venv/bin/python scripts/qa_document_artifacts.py artifacts/generated/prototype-demo/user_guide.anthropic.docx
npm run eval:validate
npm run eval:offline
```

The same flow is also available through `npm run prototype:process`, `npm run prototype:draft`, `npm run prototype:docx`, and `npm run prototype:qa`.

See `docs/prototype-runbook.md` for the current run criteria.

## Local Testing App

Start the local browser console:

```bash
.venv/bin/python scripts/app_server.py --host 127.0.0.1 --port 8765
```

Then open `http://127.0.0.1:8765`.

The local console is protected with Microsoft Entra MSAL + PKCE. The current local app registration settings live in ignored `.env` keys:

```text
KCXDOC_AUTH_ENABLED=true
KCXDOC_AUTH_TENANT_ID=543e31cf-f2b9-457e-88af-82a3938c2913
KCXDOC_AUTH_CLIENT_ID=9d5d6572-b583-4df9-8fe6-8f96c71fad58
KCXDOC_AUTH_REDIRECT_URI=http://127.0.0.1:8765/
```

Use **Logout** in the header to end the MSAL session and clear the local protected-media session.

The app lists recordings from `samples/raw/`, processes a selected recording into `samples/processed/`, generates Anthropic guide drafts, builds DOCX files, and runs DOCX QA checks.

For step-by-step operator instructions, see `docs/user-guide.md`.

## Dockerized Local App

The app can also run in Docker while keeping recordings and generated files on the host filesystem:

```bash
docker compose build
docker compose up -d
```

Then open `http://127.0.0.1:8765`.

The image does not bundle Whisper at build time. By default the container bootstraps latest `whisper.cpp` into the mounted Whisper share at first startup, then reuses that folder:

```text
KCXDOC_HOST_RAW_DIR=C:\KCXDocumentor\samples\raw
KCXDOC_HOST_PROCESSED_DIR=C:\KCXDocumentor\samples\processed
KCXDOC_HOST_ARTIFACTS_DIR=C:\KCXDocumentor\artifacts
KCXDOC_HOST_WHISPER_DIR=C:\KCXDocumentor\external\whisper
KCXDOC_BOOTSTRAP_WHISPER=true
KCXDOC_WHISPER_UPDATE=latest
```

The browser URL remains `http://127.0.0.1:8765`; Docker maps the container's internal `8765` port to the same host port. Use `docker compose ps` and `docker compose logs -f kcxdocumentor` for status.

See `docs/containerization.md` for runtime Whisper bootstrap behavior, offline/preseeded options, health-check output, and macOS path examples.
