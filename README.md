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

