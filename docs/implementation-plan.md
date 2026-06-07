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
10. Ask Claude Sonnet 4.6 to create a structured guide draft from the reviewed trace through the authenticated Azure Function proxy.
11. Render the final guide as DOCX using the local keycentrix document assets.
12. Run deterministic artifact QA and rendered visual QA before the guide is considered usable.

The initial testing surface is a local web console served by the Python stdlib app server. This is a prototype and review surface, not the final product shell. If KCXDocumentor becomes a full web client, thick Windows client, or hybrid desktop app, its visual language should continue to follow the `KCXUIComponents` reference standard.

## Local Desktop Trust Boundary

KCXDocumentor is currently designed as a desktop-local workstation utility with a browser UI, not as a shared web application.

Local workstation endpoints are allowed to operate without Entra bearer-token validation because they only read or write files already mapped to the user's local workstation:

- Recording and transcript import.
- Local recording processing.
- Session listing and session detail.
- Candidate frame thumbnails and inspection images.
- Session video preview.
- Frame review decisions and manual frame extraction.
- Local QA.
- Generated artifact download.

Cloud-backed endpoints remain Entra-authenticated because they leave the workstation or update centralized reporting:

- AI guide draft generation through the Azure Function proxy.
- AI Spend summary reads from Cosmos DB.
- AI usage writes.
- Page-count reporting when performed as a cloud reporting update.
- Any future remote persistence or shared reporting API.

This split intentionally reduces stale-token breakpoints in the desktop workflow. A user should be able to import, process, review screenshots, build the local DOCX, run local QA, and download local files even if their cloud token is expired. Token acquisition should only be required when the app creates an AI guide or reads/writes centralized AI Spend data.

Security controls for this local-trust model:

- Docker must publish the browser port only to `127.0.0.1`.
- The local server must keep path traversal protections, safe filename validation, and session-id validation.
- AI provider keys must remain server-side in Azure Functions, never in the local browser or local `.env`.
- AI/Cosmos calls must continue to require a valid Entra token validated by the Azure Function.
- KCXDocumentor should not be deployed as a multi-user web server without reintroducing full server-side authorization for local artifact endpoints.

## Azure Foundry And BAA Direction

KCXDocumentor should move production AI generation from the first-party Anthropic API key path to Claude Sonnet 4.6 deployed through Microsoft Foundry in Azure. The goal is to keep the current local-first processing boundary while routing the compact prompt payload through Azure services covered by the organization's Microsoft commercial terms and HIPAA BAA posture.

Current target architecture:

- Keep raw recordings, audio, extracted frames, OCR, local traces, generated DOCX files, and QA artifacts on the workstation.
- Keep the desktop app calling only the authenticated Azure Function for AI generation and AI Spend reporting.
- Provision a Microsoft Foundry/Azure AI Services resource in `rg-kcxdocumentor-dev`.
- Deploy `claude-sonnet-4-6` as a Global Standard deployment named `claude-sonnet-4-6`.
- Size the deployment at capacity `80`, which currently yields `80 RPM` and `80,000 TPM` under the available Claude Sonnet 4.6 quota.
- Configure the Function App with `KCXDOC_AI_PROVIDER=azure-foundry`, `KCXDOC_FOUNDRY_RESOURCE_NAME`, `KCXDOC_FOUNDRY_MESSAGES_URL`, `KCXDOC_FOUNDRY_API_KEY`, and `KCXDOC_ANTHROPIC_MODEL=claude-sonnet-4-6`.
- Continue storing usage records in Cosmos DB so AI Spend reporting survives local session deletion.
- Treat the Azure Function as the server-side policy boundary: it validates the signed-in user token, calls Foundry, records success/failure usage, and returns only the guide JSON/report to the local app.

Compliance notes:

- Microsoft documents that Azure HIPAA BAA terms are available through Microsoft Product Terms and the Data Protection Addendum for eligible customers, but Microsoft also states that using Azure does not automatically make the customer application HIPAA compliant.
- Claude models in Foundry are currently preview/global-standard model deployments. Before allowing PHI-bearing production use, KCX should confirm internally that the selected Foundry model deployment, subscription type, region, and marketplace terms are acceptable under its compliance program.
- Foundry Claude does not provide built-in content filtering at deployment time. KCXDocumentor should keep local prompt minimization, reviewer gates, QA checks, and PHI-aware operating rules in place.
- For now, API-key authentication to Foundry is acceptable inside the Function App only. The longer-term preferred state is Entra-based Foundry authentication or managed identity if the Foundry deployment and SDK path support it cleanly for this Function.
- A capacity increase above `80` currently requires a Microsoft/Azure quota request. The attempted capacity `100` update failed because quota was capped at `80` thousand TPM with `10` thousand TPM already in use at the time of the attempt.

## Token-Aware Multi-User Generation Queue

Multiple users can process recordings locally at the same time, but guide generation shares the Azure Foundry Claude deployment limit. The current deployment is `80 RPM / 80,000 TPM`, so the system should coordinate AI calls centrally instead of letting each workstation fire directly at the model.

Implemented direction:

- Keep local recording processing, OCR, frame review, DOCX rendering, and QA on each workstation.
- Submit only the compact reviewed prompt payload to the authenticated Azure Function.
- Use the existing Function App storage account queue for AI generation scheduling. Queue messages contain only a small job pointer, not the prompt payload.
- Store durable generation job records in Cosmos DB with status, owner, session id, title, model, prompt version, token estimate, usage, and failure details.
- Have the queue-trigger Function worker call Azure Foundry, write success/failure usage records, and update the job record.
- Have the local app poll job status so users see `queued`, `generating`, `building DOCX`, `QA`, `succeeded`, or `failed` instead of a silent disabled-button state.
- Keep the older synchronous `/api/generate-draft` route available as a compatibility endpoint while the local app opts into the queued route.

Token controls:

- Estimate request size before submission using a conservative character-count approximation until a provider token-count endpoint is available through the configured Foundry route.
- Use `KCXDOC_FOUNDRY_TPM_LIMIT=80000` and a lower scheduling target such as `KCXDOC_FOUNDRY_TPM_TARGET=70000` so the queue leaves headroom for provider overhead and retries.
- Run one active queued generation at a time until production telemetry shows the average prompt/output size safely supports more concurrency.
- Add segmentation later for traces whose estimated prompt plus expected output exceeds the scheduling target. Segment jobs should produce section-level guide JSON and merge into one final draft before DOCX build.
- Treat HTTP `429` and timeout failures as retryable queue-worker failures with backoff; do not let the browser retry aggressively.

Cost impact:

- Azure Storage Queue usage is tied to the Function storage account. It stores only small job pointer messages and should be negligible at demo volume.
- Cosmos DB usage increases because each AI attempt writes a generation job document and updates it as the job progresses. This is metadata plus compact prompt/result JSON, not video, frames, audio, or DOCX files.
- Under a Cosmos DB for NoSQL free-tier account with low demo volume, this should remain effectively inside the free allowance. It is not a new guaranteed-zero charge if free tier is unavailable, if another free-tier Cosmos account already exists in the subscription, or if prompt/result documents become large enough to consume meaningful RU/storage.
- Raw recordings, screenshots, DOCX artifacts, and QA output remain local and do not add Cosmos storage cost.

## Document Quality Findings

Visual review of the generated DOCX artifacts showed that guide prose has improved, but screenshot selection is still the main publication-quality risk.

Current findings:

- Some regenerated guides still choose screenshots that are only loosely related to the step text because frame selection is timestamp/cadence based.
- Teams or video-player overlays can appear in selected screenshots and can obscure the application.
- Local OCR is now wired through Tesseract, so the system can capture UI text evidence from selected frames; frame scoring still needs to use that evidence to prefer application screens over Teams/title-card frames.
- Slide-deck or glossary recordings are being forced into step-by-step workflow guides, which can create long, low-value documents with repeated slide images.
- Transcript/STT quality is important, but the observed screenshot mismatch is primarily an OCR/frame-selection/content-classification problem rather than a voice-to-text problem.

Required improvements before treating output as customer-ready:

- Add recording content classification: application workflow, slide/reference training, glossary/concepts, or mixed content.
- Generate different document structures by content type instead of always forcing a procedure guide.
- Use real local Tesseract OCR to store recognized UI text per frame with confidence and bounds; treat missing OCR as a reviewer concern.
- Score candidate frames using UI text overlap with the step, OCR confidence, and penalties for Teams/title-card or supporting-tool frames that do not match the current segment context.
- Compress the AI submission payload before generation: preserve full OCR locally, but send only concise visible UI text, bounded OCR snippets, frame evidence scores, and reviewer decisions.
- Continue improving frame scoring with visual-change/dedupe scoring, blur checks, and stronger overlay detection.
- Penalize or reject frames containing Teams join dialogs, meeting controls, presenter overlays, web video playback controls, or production title cards.
- Keep frame review as a required quality gate for externally shared documents until OCR and frame scoring are strong enough to trust automatically.
- Treat missing or low-confidence screenshot evidence as reviewer comments, not visible guide body text.
- Persist rendered page counts after DOCX build and report them to AI Spend as a separate authenticated reporting step so local document creation is not blocked by token state.

Implemented review-gate improvements:

- `procedure_trace.json` now includes `contentClassification` so the pipeline can distinguish application workflows, mixed workflow training, slide/reference training, and meeting-like sources before guide generation.
- Each segment now includes `qualityLabel`, `qualityLabels`, `reviewPriority`, `frameReviewSummary`, and `screenshotGap` so reviewers see why a section needs attention without exposing that language in the customer-facing guide body.
- Candidate screenshots now include `contentType`, `recommendationGroup`, `selectionDecision`, `recommendationReason`, positive signals, and penalties. Frames are grouped as `recommended`, `alternate`, or `system-rejected`.
- System-rejected screenshots are not sent to the AI payload unless a reviewer explicitly approves them. User-rejected screenshots remain excluded and their notes continue to feed reviewer guidance.
- Screenshot gaps are surfaced as structured `screenshotGapTasks` and in the UI readiness checks before guide creation.
- Frames added through the video picker now run local visual scoring and Tesseract OCR when available, are mapped to the selected segment, and carry compact OCR/evidence context into guide generation unless rejected.

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
| AI provider | Claude Sonnet 4.6 through Microsoft Foundry for production; first-party Anthropic only for non-PHI development fallback when explicitly configured | Keeps the model capability while improving Azure/BAA alignment and centralizing provider keys in the Function App |
| UI standard | KCXUIComponents semantic tokens and primitives | Keeps KCXDocumentor aligned with current KCX product UI conventions |
| Local container | Docker Compose with host-mounted folders | Keeps the internal app easy to run while preserving workstation-local recordings and generated artifacts |

## UI Direction

Use `/Users/djames/Documents/AppDev/KCXUIComponents` as a read-only reference for UI decisions. Do not modify that project from KCXDocumentor.

Current local app direction:

- Keep the first testing app as a lightweight local web console.
- Use KCXUIComponents-style semantic CSS tokens: `--kcx-ui-*`.
- Prefer the KCXUIComponents primitive concepts: panels, buttons, status badges, app/top shell, form fields, and layout grids.
- Keep per-session generation metadata visible with the selected session's artifacts, including model, generated timestamp, input/output/total tokens, and estimated cost.
- Provide a separate AI Spend page for aggregate generated-document count and token cost by `day`, `week`, `month`, or `year`, plus a header-level current calendar month spend summary.
- Avoid one-off palettes, component forks, or custom CSS injection patterns.
- If the product moves to a thick Windows client, keep the same information architecture and visual semantics where practical.
- If the product moves to a full web client, consider adopting KCXUIComponents packages or copying the required token/style artifacts locally rather than depending on the reference repo path.

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

## Containerization Direction

Package the internal testing app as a local Docker container for repeatable workstation setup. The container should include the Python app, static web console, document tooling, FFmpeg, Tesseract, and build tools required to compile `whisper.cpp`. It should not bundle Whisper binaries or Whisper model files at image build time.

Whisper should be treated as an external local tool share that the container can populate at runtime:

- `KCXDOC_WHISPER_CLI` points to the mounted `whisper-cli` binary.
- `KCXDOC_WHISPER_MODEL` points to the mounted GGML model.
- The default container mount is `/opt/kcxdocumentor/external/whisper`.
- `KCXDOC_BOOTSTRAP_WHISPER=true` lets the entrypoint fetch the latest `whisper.cpp` release source, build `whisper-cli`, download the configured model, and persist both in the mounted share.
- `KCXDOC_WHISPER_UPDATE=never` disables update checks after the share has been seeded.
- The mounted share must be writable when runtime bootstrap is enabled.

Source and artifact folders must remain host-mappable:

- `samples/raw` maps to a local source recording folder.
- `samples/processed` maps to a local processed-session folder.
- `artifacts` maps to a local generated-output folder.

This keeps large media, generated DOCX files, QA output, and local processing artifacts outside the image and available to the user on Windows and macOS. The Azure Function remains responsible for the Claude provider proxy and persisted AI Spend data.

Compose must bind the app port as `127.0.0.1:8765:8765`. Binding to `0.0.0.0` would expose local recordings, screenshots, generated documents, and local processing controls to the workstation's network, which does not match the desktop-local trust model.

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

The review surface should use the KCXUIComponents visual standard even during the prototype stage so the workflow can graduate into either a web client or Windows client without rethinking the product ergonomics.

The current Blink Rx test showed that Anthropic can produce useful procedure prose, but the generated DOCX is not customer-ready unless the reviewer concerns are handled correctly. Reviewer concerns such as unclear transcript stretches, screenshot approval, UI evidence, source timing, placeholder OCR, and confidence issues must appear in Word comments or reviewer-only fallback sections, not in the visible guide body.

Current frame review behavior:

- Recommended frames appear first and are the only automatically preferred screenshot candidates.
- Alternate frames remain available for human substitution.
- Needs Attention frames are visually de-emphasized and excluded from AI generation unless the reviewer approves one. The internal trace value remains `system-rejected` for compatibility.
- Screenshot gap tasks let reviewers jump directly into video-based frame capture for segments that do not have a trustworthy application screenshot.

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
- Add Docker Compose support with host-mounted `samples/raw`, `samples/processed`, and `artifacts`.
- Keep Whisper external to the image and resolve it through mounted `KCXDOC_WHISPER_CLI` and `KCXDOC_WHISPER_MODEL` paths.
- Add runtime Whisper bootstrap for containers so the mounted share can be seeded with the latest `whisper.cpp` CLI and the configured model without rebuilding the app image.
- Extract audio and low-FPS frame candidates.
- Add local STT command integration.
- Add duplicate frame scoring and OCR.
- Emit procedure trace JSON.

### Phase 3 - Guide Generation

- Define guide draft JSON schema.
- Define and version the Sonnet 4.6 guide prompt.
- Regenerate Claude drafts from the current canonical Blink Rx traces after transcript parser and frame-resolution fixes.
- Move production guide generation to Azure Foundry Claude Sonnet 4.6 by provisioning the Foundry resource/deployment in `rg-kcxdocumentor-dev` and updating the Function App provider settings.
- Generate sectioned user-guide content from procedure traces.
- Render DOCX using local keycentrix assets.
- Include selected screenshots with captions and step references.
- Keep reviewer concerns in DOCX comments rather than visible guide body text.
- Run schema validation and basic forbidden-leak/placeholder QA before accepting generated DOCX output.
- Track generation usage in Cosmos DB through the Azure Function proxy and expose `/api/usage-summary?range=day|week|month|year` using the response shape `{range, generatedAt, totals:{documents,inputTokens,outputTokens,totalTokens,estimatedCostUSD,pageCount,costPerPageUSD}, buckets:[{documents:[{generatedBy,status,usage}]}]}` so the top-level AI Spend page can show document count, generator, pages, and estimated token cost over time even after individual sessions are deleted.

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
- Preserve KCXUIComponents design semantics in the Windows shell through equivalent tokens, spacing, panel, button, status, and form patterns.
