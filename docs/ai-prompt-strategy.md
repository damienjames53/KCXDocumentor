# AI Prompt Strategy

## Model

KCXDocumentor uses Claude Sonnet 4.6 for the guide-draft implementation path.

The production provider path is Azure Foundry with the deployment name `claude-sonnet-4-6`. This keeps the Claude Messages API behavior while moving guide generation through the Azure Function proxy and the KCX Azure tenant.

Local configuration points to the Azure Function proxy. The Foundry key is configured on the Function App, not in the local app:

```text
KCXDOC_AI_PROVIDER=azure-foundry
KCXDOC_FOUNDRY_RESOURCE_NAME=foundry-kcxdocumentor-dev
KCXDOC_FOUNDRY_MESSAGES_URL=https://foundry-kcxdocumentor-dev.services.ai.azure.com/anthropic/v1/messages
KCXDOC_ANTHROPIC_MODEL=claude-sonnet-4-6
KCXDOC_PROMPT_VERSION=guide-draft-v1
KCXDOC_REMOTE_API_BASE_URL=https://kcxdocumentor-ai-dev.azurewebsites.net
```

Do not commit `.env` or API keys. The local desktop app must never call Foundry or Anthropic directly.

Current Foundry deployment sizing:

- Resource: `foundry-kcxdocumentor-dev`
- Resource group: `rg-kcxdocumentor-dev`
- Region: `eastus2`
- Deployment: `claude-sonnet-4-6`
- SKU: `GlobalStandard`
- Capacity: `80`
- Effective limits: `80 RPM` and `80,000 TPM`

Attempting capacity `100` failed because the current quota limit is `80` thousand TPM for Claude Sonnet 4.6. Any larger deployment requires a Microsoft/Azure quota increase.

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
