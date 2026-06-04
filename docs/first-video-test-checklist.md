# First Video Test Checklist

Use this checklist for the first real recording before attempting a full one-hour workstation capture.

## 1. Prepare the Sample

- Start with a 3 to 10 minute recording, not the one-hour source.
- Prefer MP4 or MKV with clear microphone narration.
- Place the video in `samples/raw/`.
- If available, place a plain-text transcript sidecar next to it or anywhere local.
- Use a target application name that should appear in the generated guide, such as `Enterprise Rx`.

## 2. Confirm Local Tools

Run:

```bash
ffmpeg -version
ffprobe -version
.venv/bin/python -m pytest tests/test_app_server.py tests/test_prototype_scripts.py
```

Expected:

- `ffmpeg` and `ffprobe` are installed and visible on `PATH`.
- Tests do not require a real video, network access, Anthropic, OCR, or local STT.
- Skipped app-server tests are acceptable only for helper surfaces that have not been implemented yet.

## 3. Process the Short Video

With a transcript sidecar:

```bash
.venv/bin/python scripts/process_recording.py samples/raw/SHORT_SAMPLE.mp4 \
  --transcript samples/raw/SHORT_SAMPLE-transcript.txt \
  --target-application "Enterprise Rx" \
  --session-id first-video-short \
  --force
```

Without a transcript sidecar:

```bash
.venv/bin/python scripts/process_recording.py samples/raw/SHORT_SAMPLE.mp4 \
  --target-application "Enterprise Rx" \
  --session-id first-video-short \
  --force
```

Expected outputs in `samples/processed/first-video-short/`:

- `manifest.json`
- `media_metadata.json`
- `transcript.json`
- `frame_scores.json`
- `ocr.json`
- `procedure_trace.json`

## 4. Inspect the Trace Before AI

Check:

- `media_metadata.json` reports `durationSource: ffprobe`.
- `transcript.json` uses `sidecar-transcript` if a sidecar was provided.
- `procedure_trace.json` has reasonable segment timestamps.
- Segments include confidence fields and review reasons.
- Candidate frames are bounded and do not explode token or storage cost.
- Placeholder transcript or placeholder OCR keeps `needsHumanReview` true.

## 5. Generate a Draft

Deterministic first:

```bash
.venv/bin/python scripts/generate_guide_draft.py \
  samples/processed/first-video-short/procedure_trace.json \
  --output artifacts/generated/first-video-short/guide_draft.deterministic.json
```

Anthropic Sonnet 4.6 only after the trace looks sane:

```bash
.venv/bin/python scripts/generate_guide_draft.py \
  samples/processed/first-video-short/procedure_trace.json \
  --output artifacts/generated/first-video-short/guide_draft.anthropic.json \
  --use-anthropic
```

Expected:

- The draft converts first-person narration into second-person user-guide steps.
- The model does not invent UI labels that are absent from transcript or OCR.
- Low-confidence or missing-visual sections remain flagged for review.

## 6. Build and QA the DOCX

```bash
.venv/bin/python scripts/build_guide_docx.py \
  artifacts/generated/first-video-short/guide_draft.deterministic.json \
  --output artifacts/generated/first-video-short/user_guide.deterministic.docx

.venv/bin/python scripts/qa_document_artifacts.py \
  artifacts/generated/first-video-short/user_guide.deterministic.docx \
  --json

.venv/bin/python scripts/qa_document_artifacts.py \
  artifacts/generated/first-video-short/user_guide.deterministic.docx \
  --json \
  --strict
```

Expected:

- Normal QA passes for a structurally valid guide.
- Strict QA fails if placeholder narration, placeholder OCR, forbidden reference-project terms, or unresolved prototype text leaks into the guide.
- A strict failure is acceptable for the first run if the guide is clearly still a review draft.

## 7. Decide Whether to Try the One-Hour Recording

Move to the one-hour source only when:

- The short sample processes without command failures.
- The trace is compact enough to review.
- Transcript alignment is understandable.
- Candidate frames are useful enough to support the steps.
- DOCX rendering succeeds.
- QA results match the actual readiness state.

If any of those fail, fix the shortest failing lane first: transcript, frame extraction, guide draft, DOCX rendering, or QA.
