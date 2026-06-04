# Prototype QA Lane

This lane validates the prototype without requiring ffmpeg, local speech models, OCR engines, or AI credits. It focuses on contracts that should remain stable while processing and DOCX generation scripts are still being built.

## Goals

- Prove that generated Office artifacts can be scanned for required guide sections and leaked internal text.
- Keep procedure trace data small, structured, and suitable for one-hour recording inputs.
- Provide smoke tests that run on temporary files only.
- Allow future processing and DOCX scripts to be tested as soon as they exist, without changing the QA lane.

## Current Smoke Coverage

The pytest suite in `tests/test_prototype_scripts.py` covers:

- `scripts/qa_document_artifacts.py` accepts a valid temporary DOCX guide.
- The same QA script rejects temporary DOCX content with forbidden internal/source-project terms.
- The local document helper can create a branded DOCX shell from temporary content.
- A compact procedure trace fixture validates expected fields for transcript segments, UI text, action hints, and candidate stills.
- Optional prototype scripts are discovered by known path once they are added.

## Expected Future Script Contracts

Processing scripts should accept local fixture paths and support a dry-run or metadata-only mode. They should not require ffmpeg, Whisper, OCR, or an AI provider for smoke tests.

Recommended script behavior:

- Read from a temporary input directory.
- Write deterministic JSON to a temporary output directory.
- Accept `--dry-run`, `--input`, and `--output` arguments where practical.
- Return exit code `0` for valid fixtures.
- Avoid network calls unless explicitly enabled by an environment variable.

DOCX scripts should accept a compact guide or procedure trace JSON and write a DOCX file without calling AI.

Recommended script behavior:

- Accept `--input` and `--output`.
- Use local branding assets from `assets/branding`.
- Include required guide sections checked by `scripts/qa_document_artifacts.py`.
- Reference selected screenshots by local path or stable relative path.

## Run

```bash
python -m pip install -e ".[test]"
python -m pytest
```

