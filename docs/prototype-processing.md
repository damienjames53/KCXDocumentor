# Prototype Processing Lane

This lane turns an imported workstation recording into a local session bundle for downstream guide-generation prototyping.

It is intentionally useful before the complete STT, OCR, and CV stack exists. If `ffprobe` or `ffmpeg` are installed, the script uses them for media metadata, audio extraction, and interval frame extraction. If they are not installed, it still emits deterministic placeholder JSON with the same shape so the AI guide draft, DOCX rendering, and QA work can continue.

## Command

```bash
python3 scripts/process_recording.py samples/raw/example.mp4
```

Useful options:

```bash
python3 scripts/process_recording.py samples/raw/example.mp4 \
  --target-application "Enterprise Rx" \
  --transcript samples/raw/example-transcript.txt \
  --segment-seconds 60 \
  --sample-interval-seconds 30 \
  --max-frames 120
```

For no-tool deterministic testing:

```bash
python3 scripts/process_recording.py samples/raw/example.mp4 --no-media-tools
```

By default, output is written under:

```text
samples/processed/{session-id}/
```

The session id is stable for the source path, file size, and modified time. Use `--session-id` for a human-readable fixed id, or `--force` to replace an existing session.

## Outputs

Each session contains:

```text
manifest.json
media_metadata.json
transcript.json
frame_scores.json
ocr.json
procedure_trace.json
package_readme.md
audio/narration.wav
frames/candidates/
frames/selected/
```

`procedure_trace.json` is the primary downstream contract. It contains:

- recording metadata
- transcript-aligned procedure segments
- visible UI text placeholders
- action hints inferred from transcript text
- candidate frame references
- token strategy notes for the guide generator

When media tools are missing, candidate images have `created: false` and `path: null`. That is expected. Downstream prototype code should rely on the JSON shape first and treat image files as optional until the frame-selection lane matures.

## One-Hour Sample Defaults

The current defaults are tuned for roughly one-hour recordings:

- assumed duration: `3600` seconds if probing fails
- transcript segment size: `60` seconds
- frame candidate interval: `30` seconds
- max frame candidates: `120`

That produces about 60 procedure-sized transcript segments and up to 120 frame candidates. This is intentionally compact enough to test token-aware summarization without sending raw video or every extracted frame to an AI model.

## Current Prototype Limits

This script does not perform local Whisper transcription, OCR, visual dedupe, blur scoring, or AI summarization yet. It creates the local processing package those lanes will consume.

Next implementation steps:

- replace placeholder transcript generation with `whisper.cpp` output ingestion
- replace placeholder OCR with Tesseract frame OCR
- replace deterministic frame scoring with OpenCV duplicate, blur, and UI-change scoring
- add a review step for selecting final screenshots before DOCX rendering
