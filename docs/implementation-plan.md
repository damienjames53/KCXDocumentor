# KCXDocumentor Implementation Plan

## Goal

Create a cost-effective, token-aware Windows documentation pipeline that turns approximately one-hour application walkthrough recordings into polished keycentrix DOCX user guides.

The system should avoid sending video to the AI engine. Instead, local processors create a compact procedure trace containing transcript chunks, timestamps, OCR text, UI-change signals, action hints, and a small set of candidate screenshots.

## MVP Scope

The MVP consumes pre-recorded files rather than recording the screen itself.

1. Import an existing one-hour recording.
2. Extract audio locally.
3. Use a transcript sidecar when one is available; otherwise transcribe speech locally with `whisper.cpp`.
4. Sample video frames locally.
5. Remove duplicate or low-value frames.
6. OCR candidate frames locally.
7. Align transcript segments, UI text, and frame timestamps.
8. Produce `procedure_trace.json`.
9. Review candidate screenshots and transcript risk before any publishable AI draft is generated.
10. Ask Anthropic Claude Sonnet 4.6 to create a structured guide draft from the reviewed trace.
11. Render the final guide as DOCX using the local keycentrix document assets.
12. Run deterministic artifact QA and rendered visual QA before the guide is considered usable.

The initial testing surface is a local web console served by the Python stdlib app server. This is a prototype and review surface, not the final product shell. If KCXDocumentor becomes a full web client, thick Windows client, or hybrid desktop app, its visual language should continue to follow the `CustomerAppUI` reference standard.

## Recommended Stack

| Layer | Recommendation | Reason |
|---|---|---|
| Windows app shell | .NET 8/9, later WinUI 3 | Strong Windows integration and future window capture path |
| MVP orchestration | .NET worker or Python CLI | Python is fastest for early media/CV experiments; .NET should own the future product shell |
| Local STT | `whisper.cpp` | Offline, low-cost, CPU-friendly, MIT licensed engine |
| Video/audio bridge | FFmpeg executable | Practical MVP ingestion bridge; keep packaging/license review explicit |
| Frame analysis | OpenCV | Duplicate removal, blur detection, UI-change scoring |
| OCR | Tesseract | Offline UI text extraction |
| Metadata store | SQLite | Simple local session database |
| Trace format | JSON files plus asset folder | Small, inspectable, easy to replay in tests |
| DOCX rendering | Open XML SDK long term; local `python-docx` helper for prototype | Deterministic document output with local keycentrix styling |
| AI provider | Anthropic Claude Sonnet 4.6 by default | Strong long-context and document-generation fit while keeping provider/model configurable |
| UI standard | CustomerAppUI semantic tokens and primitives | Keeps KCXDocumentor aligned with current KCX product UI conventions |

## UI Direction

Use `/Users/djames/Documents/AppDev/CustomerAppUI` as a read-only reference for UI decisions. Do not modify that project from KCXDocumentor.

Current local app direction:

- Keep the first testing app as a lightweight local web console.
- Use CustomerAppUI-style semantic CSS tokens: `--kcx-ui-*`.
- Prefer the CustomerAppUI primitive concepts: panels, buttons, status badges, app/top shell, form fields, and layout grids.
- Keep per-session generation metadata visible with the selected session's artifacts, including model, generated timestamp, input/output/total tokens, and estimated cost.
- Provide a separate AI Spend page for aggregate generated-document count and token cost by `day`, `week`, `month`, or `year`, plus a header-level current calendar month spend summary.
- Avoid one-off palettes, component forks, or custom CSS injection patterns.
- If the product moves to a thick Windows client, keep the same information architecture and visual semantics where practical.
- If the product moves to a full web client, consider adopting CustomerAppUI packages or copying the required token/style artifacts locally rather than depending on the reference repo path.

## One-Hour Recording Strategy

One-hour recordings must be treated as large source material, not as prompt content.

- Extract speech in local chunks of 30 to 90 seconds.
- Preserve word-level or phrase-level timestamps when available.
- Sample frames at 1 fps initially, then down-select aggressively.
- Keep duplicate-frame rejection before OCR to avoid wasting local CPU.
- Group transcript into action windows, usually 20 to 90 seconds.
- Send the AI only the grouped procedure trace and a limited screenshot candidate list.
- Use a map-reduce generation pattern: summarize segments first, then compose the full guide.
- Include transcript, OCR, frame-selection, and overall confidence for every segment.
- Flag low-confidence stretches for human review instead of letting the AI silently interpolate missing steps.

## Compact Procedure Trace

```json
{
  "schemaVersion": 1,
  "recording": {
    "sourceFile": "samples/raw/example.mp4",
    "durationSeconds": 3600,
    "targetApplication": "Unknown",
    "captureMode": "imported-recording"
  },
  "segments": [
    {
      "id": "seg-0012",
      "start": "00:12:08.200",
      "end": "00:13:02.900",
      "speakerText": "Click New Customer, enter the account name, then save.",
      "confidence": {
        "transcript": 0.92,
        "ocr": 0.87,
        "frameSelection": 0.81,
        "overall": 0.88,
        "needsHumanReview": false,
        "reasons": []
      },
      "visibleUiText": ["New Customer", "Account Name", "Save"],
      "actionHints": ["click", "form-entry", "save"],
      "candidateImages": [
        {
          "path": "samples/processed/session-001/frames/frame-0012.webp",
          "timestamp": "00:12:35.000",
          "reason": "clear-form-state",
          "confidence": 0.81,
          "reviewStatus": "pending"
        }
      ]
    }
  ]
}
```

## Future Capture Scope

After the importer works, add native Windows recording.

- Use Windows.Graphics.Capture to select and capture an application window.
- Record microphone audio with the session.
- Prefer direct capture to the working format to avoid post-recording transcoding.
- Store target application title, process name, window bounds, and monitor scale metadata.
- Add optional cursor/click telemetry if it can be collected without destabilizing capture.

## Human Review Step

Add a lightweight review surface before customer-facing AI guide generation. The review surface should show transcript segments, confidence scores, review reasons, candidate frames, OCR text, approve/reject/swap controls for still images, and reviewer notes for missing or ambiguous context.

This starts as a local web page that reads the processed session bundle and writes reviewer decisions to `frame_review.json` as an overlay. It should not rewrite the raw extraction outputs.

The review surface should use the CustomerAppUI visual standard even during the prototype stage so the workflow can graduate into either a web client or Windows client without rethinking the product ergonomics.

The current Blink Rx test showed that Anthropic can produce useful procedure prose, but the generated DOCX is not customer-ready unless the reviewer concerns are handled correctly. Reviewer concerns such as unclear transcript stretches, screenshot approval, UI evidence, source timing, placeholder OCR, and confidence issues must appear in Word comments or reviewer-only fallback sections, not in the visible guide body.

## Current Test Fixture

Use `Blink Rx Training Part 2 120525.mp4` as the primary optimization fixture until the first demo guide is acceptable.

Canonical processing lanes:

- `blink-rx-part-2-sidecar`: uses the Teams-generated `.vtt` transcript and is the guide-generation lane for this fixture.
- `blink-rx-part-2-whisper`: uses only the MP4 with local `whisper.cpp` transcription. Use it for comparison and for guide generation only when no transcript is available.

Required comparison:

- Run Teams STT versus local Whisper comparison with `npm run blink:compare:stt`.
- Track approximate WER, vocabulary overlap, average aligned-segment similarity, and low-similarity examples.
- Treat the comparison as a product-quality signal, not an academic transcript benchmark.
- Do not produce both sidecar-based and Whisper-based guide DOCX files for the same recording when a transcript sidecar is available.

Current observed baseline for the regenerated Blink Rx lanes:

- Teams STT reference word count: 1,314.
- Local Whisper word count: 1,266.
- Approximate WER against Teams STT: 17.73%.
- Word overlap: 78.53%.
- Word sequence similarity: 84.03%.
- Local Whisper low-confidence segments: 4.

## Publishable Guide Gate

A generated DOCX is not customer-ready just because it exists or passes normal QA. The gate for a customer-facing artifact is:

- Anthropic draft generated from the best available transcript source: sidecar transcript first, local Whisper only when no transcript is available.
- Frame review completed before final generation or DOCX build.
- Approved screenshots embedded in the DOCX; rejected screenshots excluded.
- No visible AI thought process, prompt text, raw JSON, placeholder confidence text, or internal QA language in the guide body.
- Reviewer concerns are Word comments, not visible tags or body paragraphs.
- Strict artifact QA passes.
- Rendered DOCX visual QA passes after screenshots are embedded.
- The visible body reads like a user guide with actionable second-person procedure steps, not a transcript summary.

The older Anthropic Blink artifacts are retained only as evidence. They are not considered customer-ready: one passed strict text QA but was visibly incomplete with only one embedded image, and another had more useful procedures/screenshots but failed strict QA because placeholder-confidence language leaked into the body.

## Milestones

### Phase 1 - Isolated Planning Repo

- Initialize git.
- Copy local document assets from DamienDev.
- Record architecture, document, QA, and model optimization rules.
- Add script skeletons for artifact QA and eval validation.

### Phase 2 - Processing Prototype

- Implement recording import.
- Add local web console import controls for recordings and transcript sidecars.
- Surface FFmpeg/FFprobe readiness in the app before processing.
- Extract audio and low-FPS frame candidates.
- Add local STT command integration.
- Add duplicate frame scoring and OCR.
- Emit procedure trace JSON.

### Phase 3 - Guide Generation

- Define guide draft JSON schema.
- Define and version the Sonnet 4.6 guide prompt.
- Regenerate Anthropic drafts from the current canonical Blink Rx traces after transcript parser and frame-resolution fixes.
- Generate sectioned user-guide content from procedure traces.
- Render DOCX using local keycentrix assets.
- Include selected screenshots with captions and step references.
- Keep reviewer concerns in DOCX comments rather than visible guide body text.
- Run schema validation and basic forbidden-leak/placeholder QA before accepting generated DOCX output.
- Track generation usage in the local SQLite database at `artifacts/usage/generation_usage.sqlite3` and expose `/api/usage-summary?range=day|week|month|year` using the response shape `{range, generatedAt, totals:{documents,inputTokens,outputTokens,totalTokens,estimatedCostUSD}, buckets:[...]}` so the top-level reporting page can show document count and estimated token cost over time even after individual sessions are deleted.

### Phase 4 - QA/Eval Harness

- Add deterministic schema validation.
- Add forbidden-leak and stale-copy scans.
- Add no-placeholder-text strict scans for publishable guides.
- Add golden scenarios for one-hour walkthroughs.
- Add rendered DOCX visual QA workflow.
- Add a customer-readiness review checklist for Anthropic outputs: body prose quality, actionability, screenshot relevance, reviewer-comment placement, and stale-artifact detection.

## Trace Versioning

Every trace includes `schemaVersion`. Future breaking changes should add a migration script under `scripts/migrations/` rather than forcing existing traces to be regenerated from video.

### Phase 5 - Native Windows Capture

- Add WinUI target-window selector.
- Capture selected app window and microphone audio.
- Produce pipeline-native assets without manual transcoding.
- Preserve CustomerAppUI design semantics in the Windows shell through equivalent tokens, spacing, panel, button, status, and form patterns.
