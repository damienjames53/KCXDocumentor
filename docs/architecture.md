# Architecture

## Pipeline

```text
recording import
  -> audio extraction
  -> local speech-to-text
  -> frame sampling
  -> duplicate/blur/change scoring
  -> OCR
  -> transcript/UI/frame alignment
  -> procedure trace
  -> AI guide draft JSON
  -> DOCX rendering
  -> artifact QA
```

## Session Package

```text
samples/processed/{session-id}/
  audio/
    narration.wav
  frames/
    candidates/
    selected/
  transcript.json
  ocr.json
  frame_scores.json
  procedure_trace.json
  guide_draft.json
  package_readme.md
```

Generated deliverables belong under:

```text
artifacts/generated/{session-id}/
  user_guide.docx
  user_guide_source.json
  selected_screenshots/
```

## Component Responsibilities

| Component | Responsibility |
|---|---|
| Importer | Validate source recording and collect duration/codec metadata |
| Audio worker | Extract normalized mono WAV for STT |
| STT worker | Produce timestamped transcript without AI credits |
| Frame worker | Sample frames and compute local quality/change scores |
| OCR worker | Extract visible UI text from high-value frame candidates |
| Trace builder | Align transcript, UI text, actions, and screenshot candidates |
| AI generator | Produce structured guide JSON from compact traces |
| DOCX renderer | Build final keycentrix Word document |
| QA runner | Validate schemas, generated Office text, and visual render artifacts |

