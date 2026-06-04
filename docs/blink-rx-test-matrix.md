# Blink Rx Test Matrix

Use `Blink Rx Training Part 2 120525.mp4` as the primary optimization fixture until the first demo guide is acceptable.

## Raw Inputs

- Recording: `samples/raw/Blink Rx Training Part 2 120525.mp4`
- Teams STT sidecar: `samples/raw/Newleaf and General Pharmacy Industry Training Sessions.vtt`
- Target application: `Blink Rx`
- Source profile: `teams-recording`

The Teams sidecar is the reference STT for transcript comparison. The no-sidecar lane uses local `whisper-cli` and `models/whisper/ggml-base.en.bin`.

## Canonical Sessions

| Lane | Session ID | Purpose |
| --- | --- | --- |
| Teams STT | `blink-rx-part-2-sidecar` | Uses the Teams-generated `.vtt` transcript. |
| Local Whisper | `blink-rx-part-2-whisper` | Uses only the MP4 and local Whisper transcription. |

## Processing Commands

```bash
npm run blink:process:sidecar
npm run blink:process:whisper
```

Expected processing output:

- `samples/processed/blink-rx-part-2-sidecar/transcript.json` has `source: sidecar-transcript`.
- `samples/processed/blink-rx-part-2-whisper/transcript.json` has `source: local-whisper`.
- Both sessions use the Teams crop profile and should produce the same frame candidate count.

## STT Comparison

```bash
npm run blink:compare:stt
```

The report is written to:

```text
artifacts/qa/blink-rx-part-2-stt-comparison.json
```

Use the report to track:

- approximate word error rate, using Teams STT as the reference
- vocabulary overlap
- average time-aligned segment similarity
- low-similarity examples that may affect guide generation

This is not a legal or academic transcript benchmark. It is a product-quality signal for whether local Whisper is good enough to produce customer-facing guide drafts without a sidecar transcript.

## Guide Generation Commands

Run deterministic generation first:

```bash
npm run blink:draft:sidecar
npm run blink:docx:sidecar
npm run blink:qa:sidecar

npm run blink:draft:whisper
npm run blink:docx:whisper
npm run blink:qa:whisper
```

Use Anthropic only after transcript quality and frame review look sane:

```bash
.venv/bin/python scripts/generate_guide_draft.py \
  samples/processed/blink-rx-part-2-sidecar/procedure_trace.json \
  --output artifacts/generated/blink-rx-part-2-sidecar/guide_draft.anthropic.json \
  --use-anthropic

.venv/bin/python scripts/generate_guide_draft.py \
  samples/processed/blink-rx-part-2-whisper/procedure_trace.json \
  --output artifacts/generated/blink-rx-part-2-whisper/guide_draft.anthropic.json \
  --use-anthropic
```

## Anthropic Readiness Gate

The older Anthropic Blink artifacts under `artifacts/generated/blink-rx-training-part-2-*` are evidence from earlier runs, not customer-ready deliverables.

Current review finding:

- The non-Teams-profile Anthropic DOCX passed strict text QA but was visibly incomplete and contained only one embedded image.
- The Teams-profile Anthropic DOCX had more useful procedure structure and five screenshots, but failed strict QA because placeholder-confidence language leaked into the visible body.

The next Anthropic pass must be generated from the canonical sessions in this matrix after frame review:

- `blink-rx-part-2-sidecar`
- `blink-rx-part-2-whisper`

Acceptance criteria:

- Strict QA passes.
- Rendered visual QA passes.
- Screenshots are embedded and relevant to each step.
- The visible body reads like a customer-facing user guide, not a transcript or internal QA report.
- Low-confidence transcript issues, unclear UI labels, screenshot concerns, and source timing appear as Word comments only.
- No visible AI thought process, raw trace content, placeholder confidence text, or internal reviewer tags appear in body text.

## Review Rules

- Reject Teams title cards, participant rails, meeting overlays, and production-intro graphics in the Frames tab.
- Approve screenshots that show the application state needed for a procedure step.
- Add reviewer notes for missing context, poor transcript confidence, or ambiguous UI state.
- Build DOCX only after the frame review pass, because approved/rejected choices influence screenshot selection.
