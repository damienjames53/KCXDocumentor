# Prototype DOCX Rendering Lane

This prototype renders a keycentrix-styled Word guide from local JSON only. It does not call an AI service and does not require the DamienDev or SmartReq repositories after the local document helper and branding assets have been copied into KCXDocumentor.

## Scope

- Input: guide draft JSON or procedure trace JSON.
- Output: `.docx` user guide.
- Styling: `tools/document_lib/keycentrix_docx.py` and `assets/branding/images/`.
- Dependency: `python-docx`.
- Non-goal: audio transcription, frame selection, OCR, summarization, or model calls.

## Run

```bash
python3 -m pip install python-docx
python3 scripts/build_guide_docx.py examples/guide_draft.example.json \
  --output artifacts/generated/prototype-guide.docx
```

The output directory is created automatically.

## Accepted Input Shapes

The renderer accepts a polished guide draft:

```json
{
  "document": {
    "title": "Application User Guide",
    "version": "Draft v0.1",
    "status": "Prototype",
    "owner": "KCXDocumentor"
  },
  "audience": ["Application users"],
  "prerequisites": ["Access to the application"],
  "workflow_overview": ["Open the workflow and complete the required fields."],
  "steps": [
    {
      "title": "Open the customer screen",
      "action": "Select Customers from the navigation menu.",
      "expected_result": "The customer list opens.",
      "visible_ui_text": ["Customers", "Search"],
      "screenshot": "samples/processed/customer-list.webp",
      "screenshot_caption": "Customer list screen"
    }
  ]
}
```

It also accepts the rougher procedure trace shape expected from recording processing:

```json
{
  "session": {
    "app_name": "Target Application",
    "duration_sec": 3600,
    "recorded_at": "2026-06-04T10:00:00-05:00"
  },
  "steps": [
    {
      "start": "00:03:12.400",
      "end": "00:03:48.900",
      "speaker_text": "Click New Customer, then enter the account name.",
      "visible_ui_text": ["New Customer", "Account Name", "Save"],
      "action_hints": ["mouse_click", "form_entry"],
      "candidate_images": ["frames/frame_001.webp", "frames/frame_002.webp"]
    }
  ]
}
```

Image paths may be absolute or relative to the input JSON, repository root, or current working directory. Missing images are skipped; the guide still renders.

## Rendering Rules

- Use `keycentrix` lowercase in generated fixed text.
- Render cover, document control metadata, audience, prerequisites, workflow overview, procedures, expected results, troubleshooting notes, and source metadata.
- Include screenshots only when a referenced image exists locally.
- Keep the visible body suitable for a customer-facing guide: no prompt text, raw JSON, AI reasoning language, prototype placeholders, or internal reference-project names.
- Put reviewer concerns in Word comments instead of visible tags or body sections. This includes source timing, low confidence warnings, screenshot approval concerns, visible UI evidence, and action hints.
- If Word comments are unavailable, render a clearly named `Reviewer Comments` fallback section so QA can distinguish reviewer-only content from the guide body.
- Keep DOCX rendering deterministic so offline fixture tests can compare structure without document-layout variability.

## Reviewer Comments

Reviewer comments are intended for technical writers and application reviewers. They should explain concrete publication concerns, not expose model thought process. Good comments include:

- `Transcript confidence is below publication threshold.`
- `Confirm the screenshot does not include Teams controls.`
- `Source UI evidence: Save; Submit; Confirm`

Do not put these concerns in the guide body. The guide body should remain direct, concise, and instructional.
