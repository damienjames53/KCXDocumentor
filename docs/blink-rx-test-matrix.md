# Blink Rx Test Matrix

Use `Blink Rx Training Part 2 120525.mp4` as the primary optimization fixture until the first demo guide is acceptable.

## Raw Inputs

- Recording: `samples/raw/Blink Rx Training Part 2 120525.mp4`
- Teams STT sidecar: `samples/raw/Newleaf and General Pharmacy Industry Training Sessions.vtt`
- Target application: `Blink Rx`
- Source profile: `teams-recording`

The Teams sidecar is the preferred guide-generation input for this recording. The no-sidecar lane uses local `whisper-cli` and `models/whisper/ggml-base.en.bin` only for fallback testing and STT comparison.

## Canonical Sessions

| Lane | Session ID | Purpose |
| --- | --- | --- |
| Teams STT | `blink-rx-part-2-sidecar` | Uses the Teams-generated `.vtt` transcript. |
| Local Whisper | `blink-rx-part-2-whisper` | Uses only the MP4 and local Whisper transcription. Use for comparison and for guide generation only when no transcript is available. |

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

This is not a legal or academic transcript benchmark. It is a product-quality signal for whether local Whisper is good enough when no sidecar transcript is available.

## Guide Generation Commands

Because this Blink recording has a Teams transcript sidecar, generate only the sidecar-based Anthropic guide:

```bash
npm run blink:draft:sidecar
npm run blink:docx:sidecar
npm run blink:qa:sidecar
```

Equivalent direct commands:

```bash
.venv/bin/python scripts/generate_guide_draft.py \
  samples/processed/blink-rx-part-2-sidecar/procedure_trace.json \
  --output artifacts/generated/blink-rx-part-2-sidecar/guide_draft.anthropic.json

.venv/bin/python scripts/build_guide_docx.py \
  artifacts/generated/blink-rx-part-2-sidecar/guide_draft.anthropic.json \
  --output artifacts/generated/blink-rx-part-2-sidecar/user_guide.anthropic.docx
```

If a future recording has no transcript sidecar, process it without `--transcript` so the session uses local Whisper, then generate the Anthropic guide from that Whisper-backed session. Do not create both sidecar and Whisper guide versions for the same recording when a transcript is available.

## Anthropic Readiness Gate

The older Anthropic Blink artifacts under `artifacts/generated/blink-rx-training-part-2-*` are evidence from earlier runs, not customer-ready deliverables.

Current review finding:

- The non-Teams-profile Anthropic DOCX passed strict text QA but was visibly incomplete and contained only one embedded image.
- The Teams-profile Anthropic DOCX had more useful procedure structure and five screenshots, but failed strict QA because placeholder-confidence language leaked into the visible body.

The next Anthropic pass for this Blink fixture must be generated from the sidecar session after frame review:

- `blink-rx-part-2-sidecar`

Use `blink-rx-part-2-whisper` for guide generation only if the Teams transcript sidecar is removed or unavailable.

Acceptance criteria:

- Strict QA passes.
- Rendered visual QA passes.
- Screenshots are embedded and relevant to each step.
- The visible body reads like a customer-facing user guide, not a transcript or internal QA report.
- Low-confidence transcript issues, unclear UI labels, screenshot concerns, and source timing appear as Word comments only.
- No visible AI thought process, raw trace content, placeholder confidence text, or internal reviewer tags appear in body text.
- Purpose text describes the user workflow, not the local trace, AI pipeline, or recording-processing method.
- Prerequisites contain only customer/user prerequisites. Reviewer or publishing instructions belong in Word comments or internal review notes.
- Source Recording Metadata renders duration in a human-readable format such as `00:20:41`, not raw seconds.
- Ambiguous UI language such as `required checkboxes` and unexplained terms such as `PV1` or `PDR` are either clearly defined in body text or routed to Word comments for reviewer verification.
- DOCX step headings are concise action/state titles. They must not include duplicated section names, redundant `Step N` suffixes, or headings like `Step 5 — Submit a Refill Request: Step 14`.
- The appendix must identify the target application as Blink Rx when the source recording or draft metadata provides it.
- Reviewer guidance remains detailed enough to route production review, including segment IDs, timestamp ranges, low-confidence reasons, and screenshot gaps, but appears only in Word comments or the fallback Reviewer Comments section.
- Anthropic drafts should organize the workflow into logical application sections rather than forcing one flat sequence of transcript-sized chunks.

## Review Rules

- Reject Teams title cards, participant rails, meeting overlays, and production-intro graphics in the Frames tab.
- Approve screenshots that show the application state needed for a procedure step.
- Add reviewer notes for missing context, poor transcript confidence, or ambiguous UI state.
- Build DOCX only after the frame review pass, because approved/rejected choices influence screenshot selection.
