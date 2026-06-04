# Testing and QA Strategy

This strategy borrows SmartReq's split between deterministic tests and AI regression evaluations.

## Release Gates

| Gate | Blocks Release? | Reason |
|---|---|---|
| Procedure trace schema validation | Yes | The AI and DOCX renderer need stable inputs |
| Local STT smoke test | Yes for processing changes | Prevents broken transcription pipelines |
| Frame selection QA | Yes for screenshot changes | Prevents blurry, duplicate, or irrelevant stills |
| OCR extraction smoke test | Yes for UI-text changes | Keeps visible UI text available for grounding |
| DOCX artifact QA | Yes | Prevents internal prompt/source leakage and missing sections |
| Strict placeholder QA | Yes for publishable guides | Prevents prototype transcript/OCR placeholders from shipping |
| Golden scenario evals | Yes for prompt/model changes | Prevents guide-quality regressions |
| One-hour sample performance budget | Yes before pilot | The real input size is around one hour |
| PHI/sensitive text redaction checks | Yes before enterprise pilot | Screen recordings can contain regulated or confidential data |

## Deterministic Coverage

Add tests for:

- imported recording metadata extraction
- audio extraction command generation
- transcript segment normalization
- timestamp conversion
- duplicate frame rejection
- blur and transition-frame rejection
- OCR payload structure
- procedure trace schema
- segment confidence thresholds
- low-confidence failure-mode flags
- guide draft schema
- DOCX export success
- generated DOCX text extraction
- forbidden internal text and secret-name scans
- reviewer comments are present for low-confidence publication concerns
- reviewer concerns do not appear in the visible guide body
- screenshot file existence and dimensions

## AI Regression Evals

Golden scenarios should be stored under `tests/evals/`.

Each scenario should include:

| Field | Purpose |
|---|---|
| `id` | Stable scenario ID |
| `recordingProfile` | Approximate duration, app type, and narration style |
| `expectedWorkflow` | Workflow the guide should identify |
| `requiredSections` | Sections the generated guide must include |
| `requiredUiTerms` | UI labels expected from OCR/transcript |
| `forbiddenEchoes` | Sensitive or internal values that must not appear |
| `qualityChecks` | Scenario-specific expectations |

## Document Artifact QA

The QA script should scan DOCX artifacts for:

- missing required guide sections
- internal prompt leakage in the body or reviewer comments
- environment metadata leakage
- secret names
- raw JSON payload leakage
- stale product or project terminology
- missing source/recording metadata
- missing screenshot references when steps require visuals
- prototype placeholder narration or OCR text in the visible body when `--strict` is used
- reviewer comment presence so unresolved concerns can be tracked before customer release

The visible DOCX body should read like a finished user guide. Low-confidence transcript notes, screenshot approval concerns, OCR evidence, and source timing belong in Word comments. If comments are unavailable in the runtime, they may appear only in a clearly named reviewer-only fallback section.

## Visual QA

Rendered DOCX QA should be added when document generation starts.

- Render DOCX to PDF or page images.
- Check that logo, title, headings, tables, and screenshots appear.
- Verify screenshots do not overflow the page.
- Store rendered QA output in `artifacts/qa/`.
