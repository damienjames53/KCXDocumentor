# Prototype Processing Lane

This lane turns an imported workstation recording into a local session bundle for downstream guide-generation prototyping.

It is intentionally useful before the complete OCR and CV stack exists. If `ffprobe` or `ffmpeg` are installed, the script uses them for media metadata, audio extraction, and interval frame extraction. When no transcript sidecar is provided, it runs local `whisper-cli` against the extracted narration audio when a local model is available. If media or STT tools are not available, it still emits deterministic placeholder JSON with the same shape so the AI guide draft, DOCX rendering, and QA work can continue.

The local app server exposes the same lane for initial video testing:

- `GET /api/health` reports whether `ffmpeg`, `ffprobe`, `whisper-cli`, and the local Whisper model are available.
- `GET /api/recordings` lists supported recordings in `samples/raw/`.
- `GET /api/transcripts` lists `.txt`, `.vtt`, `.srt`, and `.json` transcript sidecars in `samples/raw/`.
- `POST /api/import-recording` imports a multipart `file` upload into `samples/raw/`.
- `POST /api/import-transcript` imports a multipart `file` upload into `samples/raw/`.
- `POST /api/process` accepts `recording`, optional `transcript`, `targetApplication`, `sourceProfile`, `sessionId`, `force`, and `noMediaTools`.

Uploads are filename-validated and restricted to plain file names under `samples/raw/`. For very large one-hour recordings, directly copying the file into `samples/raw/` is still the most reliable local workflow until the prototype server grows a streaming upload worker.

## Command

```bash
python3 scripts/process_recording.py samples/raw/example.mp4
```

Useful options:

```bash
python3 scripts/process_recording.py samples/raw/example.mp4 \
  --target-application "Enterprise Rx" \
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
frame_review.json
package_readme.md
audio/narration.wav
frames/candidates/frame-0001.png
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

When `ffmpeg` is available, candidate frames are extracted as browser-friendly `.png` files under `frames/candidates/`. PNG is used because UI screenshots embed reliably in DOCX and preserve application text better than compressed JPEG. Frame records include both `path` and `webPath` values relative to the session directory so the app can serve them through `/api/session?sessionId={id}&asset={path}`.

## Frame Review Overlay

Reviewer frame decisions are stored in `frame_review.json` as a session-local overlay instead of rewriting the original trace artifacts. This keeps the raw extraction reproducible while allowing a reviewer to approve useful screenshots, reject Teams chrome or title cards, add notes, and assign a candidate to a transcript segment.

The local app exposes:

- `GET /api/frame-review?sessionId=<id>` to read merged frame candidates and saved decisions.
- `POST /api/frame-review` with `action: approve|reject|pending|assign|note` to update one candidate.
- `POST /api/extract-frame` with a timestamp to add a PNG candidate from the source recording.

Additional frames created through `/api/extract-frame` are appended to `frame_scores.json` with `source: manual-review-extract`, use the session crop filter from `manifest.json`, and receive a matching pending or approved `frame_review.json` entry.

## Teams Recording Profile

Teams recordings often include title cards, participant rails, letterboxing, and meeting overlays that are not useful in a training document. Use the Teams profile for those sources:

```bash
python3 scripts/process_recording.py samples/raw/teams-recording.mp4 \
  --target-application "Blink Rx" \
  --source-profile teams-recording
```

The Teams profile currently:

- skips the first 60 seconds for frame selection
- crops candidate screenshots with `crop=iw*0.872:ih*0.874:0:ih*0.063`
- records the crop and source profile in `manifest.json` and `frame_scores.json`

Use `--skip-start-seconds` or `--frame-crop-filter` when a Teams recording needs different cleanup.

## Local Whisper Transcription

When `--transcript` is not supplied, the processing lane attempts local transcription with `whisper.cpp`:

```bash
python3 scripts/process_recording.py samples/raw/example.mp4 \
  --target-application "Enterprise Rx" \
  --whisper-model models/whisper/ggml-base.en.bin
```

The default model path is `models/whisper/ggml-base.en.bin`, or `KCXDOC_WHISPER_MODEL` when that environment variable is set. The generated Whisper JSON is stored at `audio/whisper-transcript.json`, and normalized transcript segments are written into `transcript.json` with `source: local-whisper`.

Useful options:

- `--whisper-cli` points to a specific `whisper-cli` binary. If omitted, the script uses `KCXDOC_WHISPER_CLI` or `whisper-cli` on `PATH`.
- `--whisper-language` defaults to `en`.
- `--whisper-timeout-seconds` defaults to `7200` for long recordings.
- `--no-local-stt` skips Whisper and keeps deterministic placeholder transcript output.

## Transcript Sidecars

The processing lane can still use a sidecar transcript when one is available. Sidecars take precedence over local Whisper output:

- `.txt` is chunked by word count across the recording duration.
- `.vtt` and `.srt` captions are parsed into timestamped text segments when timestamps are present.
- `.json` can be either a list of segments or an object with `segments`. Segment fields can include `text`, `speakerText`, `startSeconds`, `endSeconds`, `speaker`, and `confidence`.

Sidecar-derived segments receive usable prototype confidence instead of placeholder confidence. They still remain reviewable because OCR and computer-vision scoring are not complete yet.

## One-Hour Sample Defaults

The current defaults are tuned for roughly one-hour recordings:

- assumed duration: `3600` seconds if probing fails
- transcript segment size: `60` seconds
- frame candidate interval: `30` seconds
- max frame candidates: `120`

That produces about 60 procedure-sized transcript segments and up to 120 frame candidates. This is intentionally compact enough to test token-aware summarization without sending raw video or every extracted frame to an AI model.

## Current Prototype Limits

This script performs local media extraction and local Whisper transcription, but OCR, visual dedupe, blur scoring, and AI summarization remain prototype lanes. It creates the local processing package those lanes will consume.

Next implementation steps:

- replace placeholder OCR with Tesseract frame OCR
- replace deterministic frame scoring with OpenCV duplicate, blur, and UI-change scoring
- add a review step for selecting final screenshots before DOCX rendering
