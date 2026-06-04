# Prototype Runbook

## Objective

Get a local prototype running that can prove the end-to-end shape without requiring AI credits, FFmpeg, Whisper, OCR, or real one-hour samples on day one.

## Target Flow

1. Place a recording or placeholder file in `samples/raw/`.
2. Run the processing script to create a session package under `samples/processed/`.
3. Use the generated `procedure_trace.json` to build a guide draft or DOCX.
4. Run deterministic QA and eval checks.

## Prototype Principle

The prototype should degrade gracefully. If local media tools are missing, it should still emit deterministic synthetic metadata and trace files so the document and QA lanes can be developed independently.

## Expected Commands

```bash
python scripts/process_recording.py samples/raw/example.mp4
python scripts/build_guide_docx.py samples/processed/<session>/procedure_trace.json artifacts/generated/<session>/user_guide.docx
python scripts/qa_document_artifacts.py artifacts/generated/<session>/user_guide.docx
npm run eval:validate
npm run eval:offline
```

## Done Criteria

- A placeholder or real recording produces a session folder.
- A `procedure_trace.json` exists and follows `schemas/procedure_trace.schema.json`.
- A DOCX guide is generated with local keycentrix assets.
- The DOCX can be scanned by `scripts/qa_document_artifacts.py`.
- The existing offline eval checks still pass.

