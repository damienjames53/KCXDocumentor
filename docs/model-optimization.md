# Model Optimization Notes

## Core Principle

Never ask the AI model to understand a one-hour video directly. The model should receive a compact, local-first representation of the workflow.

## Token Controls

- Use local transcription, OCR, and frame selection before model calls.
- Chunk transcript by action windows, not arbitrary token length alone.
- Compress repeated narration and duplicate UI states.
- Preserve exact UI labels from OCR and transcript.
- Send only 1 to 3 candidate screenshots per step.
- Prefer structured JSON outputs before prose generation.
- Cache segment summaries by source hash and prompt version.
- Record model, prompt version, trace schema version, and QA score for every generated guide.

## Generation Pattern

1. Segment analysis: summarize local action windows into compact structured notes.
2. Step extraction: convert notes into ordered procedure steps.
3. Screenshot selection: choose the best stills from local candidates.
4. Guide draft: produce guide JSON with sections, steps, captions, cautions, and open questions.
5. DOCX render: deterministic local rendering from guide JSON.
6. QA pass: deterministic scan plus optional AI judge against rubric.

## Local Model Choices

Recommended local speech-to-text order:

1. `whisper.cpp` for enterprise-friendly offline MVP transcription.
2. `faster-whisper` when GPU batch processing is available and Python packaging is acceptable.
3. `Vosk` for very low-resource fallback transcription where accuracy tradeoffs are acceptable.

## Cost Guardrails

- Default to local-only STT.
- Do not submit raw audio or video to an AI provider for normal operation.
- Do not send OCR text for unchanged screens.
- Do not send screenshots until after local down-selection.
- Keep a maximum prompt budget per one-hour recording and fail with an actionable report if exceeded.

