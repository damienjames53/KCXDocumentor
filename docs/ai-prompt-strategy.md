# AI Prompt Strategy

## Model

KCXDocumentor uses Claude Sonnet 4.6 for the guide-draft implementation path.

The production provider path is Azure Foundry with the deployment name `claude-sonnet-4-6`. This keeps the Claude Messages API behavior while moving guide generation through the Azure Function proxy and the KCX Azure tenant.

The desktop app does not call Anthropic or Azure Foundry directly. It sends compact prompt payloads to the authenticated Azure Function configured in `KCXDOC_REMOTE_API_BASE_URL`. The Function validates the signed-in user, schedules generation through the shared queue, calls Azure Foundry, records success/failure usage, and returns the guide draft result.

Local configuration points to the Azure Function proxy. The Foundry key is configured on the Function App, not in the local app:

```text
KCXDOC_AI_PROVIDER=azure-foundry
KCXDOC_FOUNDRY_RESOURCE_NAME=foundry-kcxdocumentor-dev
KCXDOC_FOUNDRY_MESSAGES_URL=https://foundry-kcxdocumentor-dev.services.ai.azure.com/anthropic/v1/messages
KCXDOC_ANTHROPIC_MODEL=claude-sonnet-4-6
KCXDOC_PROMPT_VERSION=guide-draft-v1
KCXDOC_REMOTE_API_BASE_URL=https://kcxdocumentor-ai-dev.azurewebsites.net
```

Do not commit `.env` or API keys. The local desktop app must never store Anthropic or Foundry provider keys.

Function App provider settings:

```text
KCXDOC_AI_PROVIDER=azure-foundry
KCXDOC_FOUNDRY_RESOURCE_NAME=foundry-kcxdocumentor-dev
KCXDOC_FOUNDRY_MESSAGES_URL=https://foundry-kcxdocumentor-dev.services.ai.azure.com/anthropic/v1/messages
KCXDOC_FOUNDRY_API_KEY=<Function App setting only>
KCXDOC_ANTHROPIC_MODEL=claude-sonnet-4-6
KCXDOC_FOUNDRY_TPM_LIMIT=80000
KCXDOC_FOUNDRY_TPM_TARGET=68000
KCXDOC_TOKEN_COUNT_SAFETY_MULTIPLIER=1.15
```

Current Foundry deployment sizing:

- Resource: `foundry-kcxdocumentor-dev`
- Resource group: `rg-kcxdocumentor-dev`
- Region: `eastus2`
- Deployment: `claude-sonnet-4-6`
- SKU: `GlobalStandard`
- Capacity: `80`
- Effective limits: `80 RPM` and `80,000 TPM`

Attempting capacity `100` failed because the current quota limit is `80` thousand TPM for Claude Sonnet 4.6. Any larger deployment requires a Microsoft/Azure quota increase.

## API Usage Guidance

- Treat Azure Foundry as the production Claude provider.
- Treat the Azure Function as the only approved provider boundary for desktop clients.
- Use the queued generation route for guide creation so multiple workstations share the Foundry TPM limit safely.
- Keep the synchronous Function route only as a compatibility endpoint during migration.
- Use the Azure Foundry Anthropic-compatible Token Count API for pre-flight estimation when available.
- Apply the 15% token safety multiplier before scheduling decisions.
- Fall back to character-count approximation only when Token Count is unavailable.
- Token Count API calls are not treated as billable generation usage in KCXDocumentor reporting.
- Set `max_tokens` to the model ceiling for generation requests.
- Check `stop_reason` after every generation. Record `stop_reason=max_tokens` as `output_token_limit_exceeded`.
- Record successful usage, failed usage, model, prompt version, owner, and failure reason in Cosmos DB through the Function.
- Do not send raw videos, extracted audio, full frame sets, local artifacts, API keys, browser tokens, or local filesystem paths to Foundry.
- Do send compact reviewed context: transcript segments, OCR text, visible UI labels, approved screenshot references, reviewer notes, timing metadata, and source profile.
- Keep Anthropic first-party API use out of the production path unless explicitly approved for non-PHI development testing.

## Billing And Compliance Notes

- Claude on Azure Foundry bills through Azure Marketplace separately from standard Azure credits and some enterprise consumption commitments.
- Confirm the target subscription payment method covers Marketplace charges before switching subscriptions.
- Azure Foundry routing improves Azure tenant alignment, but it does not by itself make KCXDocumentor HIPAA compliant.
- Keep local prompt minimization, reviewer gates, QA checks, and PHI-aware operating rules active.
- For PHI-bearing production use, KCX must confirm that the selected Foundry model deployment, region, subscription type, Marketplace terms, and Microsoft BAA posture are approved by the compliance program.

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
