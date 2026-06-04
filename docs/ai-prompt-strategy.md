# AI Prompt Strategy

## Model

KCXDocumentor uses Anthropic Claude Sonnet 4.6 for the guide-draft implementation path.

Official Anthropic docs list the Claude API model ID as `claude-sonnet-4-6`. The current model overview positions Sonnet 4.6 as the best speed/intelligence balance, with text and image input, a 1M token context window, and Claude API pricing of $3/input MTok and $15/output MTok.

Configuration lives in ignored `.env`:

```text
ANTHROPIC_API_KEY=
KCXDOC_AI_PROVIDER=anthropic
KCXDOC_ANTHROPIC_MODEL=claude-sonnet-4-6
KCXDOC_PROMPT_VERSION=guide-draft-v1
```

Do not commit `.env`.

## Prompt Contract

The model receives a compact `procedure_trace.json`, not raw video.

The prompt must clearly separate:

- narrator evidence: what the speaker said or did
- visible UI evidence: exact UI labels from OCR
- inferred guide action: what the user should do
- uncertainty: low-confidence transcript, OCR, or frame selection

Narration is not final guide prose. The model must convert first-person narration into second-person imperative user-guide instructions.

## Confidence Handling

- `confidence.overall < 0.75` means the step needs human review.
- Low transcript confidence should produce a review flag.
- Low OCR confidence should avoid invented UI labels.
- Low frame-selection confidence should avoid claiming a screenshot is final.

## Output

The output must be valid guide draft JSON matching `schemas/guide_draft.schema.json`.

The model must not output raw trace JSON, prompt text, internal reasoning, environment metadata, API keys, or source-project names.

