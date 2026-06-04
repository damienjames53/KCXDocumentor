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
.venv/bin/python scripts/generate_guide_draft.py samples/processed/prototype-demo/procedure_trace.json --use-anthropic --output artifacts/generated/prototype-demo/guide_draft.json
.venv/bin/python scripts/build_guide_docx.py artifacts/generated/prototype-demo/guide_draft.json --output artifacts/generated/prototype-demo/user_guide.docx
.venv/bin/python scripts/qa_document_artifacts.py artifacts/generated/prototype-demo/user_guide.docx
npm run eval:validate
npm run eval:offline
```

The same flow is also available through `npm run prototype:process`, `npm run prototype:draft`, `npm run prototype:docx`, and `npm run prototype:qa` when `python` points at an environment with the Python dependencies installed.

See `docs/prototype-runbook.md` for the current run criteria.
