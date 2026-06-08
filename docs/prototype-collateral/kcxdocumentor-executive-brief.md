# KCXDocumentor - AI-Assisted Documentation From Screen Recordings

Document ID: KCXDOC-BRIEF-001

keycentrix - Executive Prototype Review

KCXDocumentor is a working prototype for turning local screen recordings into reviewable DOCX user guides. The system keeps long recordings, audio, transcript extraction, frame review, and document assembly local to the workstation, while sending only compact prompt data through the authenticated AI route. The prototype is designed for business analysts, trainers, and implementation teams that need to produce consistent customer-facing documentation without manually transcribing hour-long walkthroughs or hunting for screenshots after the fact.

## 1. Purpose

KCXDocumentor reduces the cost and time required to convert workflow walkthroughs into polished documentation. A user imports a recording and optional transcript, processes the video locally, reviews candidate screenshots, creates an AI-assisted guide draft, and downloads a DOCX file for final review.

The current build demonstrates:

- Local video processing through FFmpeg, Whisper, and frame extraction.
- Human-in-the-loop screenshot review before guide generation.
- Authenticated Microsoft Entra sign-in using MSAL + PKCE.
- A serverless Azure Function proxy for Azure Foundry Claude calls.
- Cosmos-backed AI Spend reporting by user, document, tokens, pages, and estimated cost.
- Dockerized deployment using a private GitHub Container Registry image.
- Windows-friendly host folder mapping for recordings, generated guides, and Whisper assets.

## 2. Business Problem

Training and implementation teams frequently record detailed workflow walkthroughs, but turning those recordings into usable documentation is slow and inconsistent. The current manual process requires a person to:

- Rewatch long recordings.
- Identify the meaningful workflow steps.
- Capture usable screenshots.
- Rewrite narrator language into second-person instructions.
- Build a polished Word document.
- Review for customer-facing quality.

For one-hour recordings, this work can consume many hours of BA or trainer time and still produce inconsistent output. KCXDocumentor targets that gap.

## 3. Prototype Scope

The prototype supports the initial documentation workflow:

- Import screen recordings and optional transcript files.
- Process recordings locally into trace data and candidate screenshots.
- Use source profiles such as Teams Recording to reduce overlay-heavy frame selection.
- Review screenshots grouped as Recommended, Alternates, and Needs Attention.
- Approve, reject, or manually capture candidate screenshots from the video.
- Run local OCR and evidence scoring on manually captured frames so selected images carry context into guide generation.
- Generate a structured guide through the authenticated AI proxy.
- Build and download a DOCX guide.
- Run local QA checks.
- Track AI spend centrally, even when local artifacts are removed.

## 4. Governing Principles

- Local-first processing: raw recordings stay on the workstation.
- Token-aware AI use: the model receives compact workflow context, not raw video.
- Human review before publishing: reviewers control screenshot selection and can add notes.
- Customer-facing document quality: internal prompt text, reasoning, and pipeline language are excluded from the guide body.
- Auditable spend: AI usage persists centrally and is attributable to the authenticated user.

## 5. Executive Value

### Time Recovery

KCXDocumentor can materially reduce the time spent converting recordings into draft documentation. The first usable draft can be created from an imported recording, reviewed screenshots, and a guided AI generation step rather than a fully manual writing process.

### Consistency

The generated DOCX follows a repeatable structure: purpose, prerequisites, logical workflow sections, numbered steps, screenshots, appendix metadata, and reviewer comments only where needed.

### Cost Visibility

AI Spend gives leadership visibility into token usage, estimated cost, generated document count, generated pages, and cost per page by day, week, month, or year.

### Safer AI Boundary

The prototype avoids sending raw video to an AI provider. The current AI call uses compact prompt data derived from local processing and review decisions.

## 6. Target Architecture Summary

| Layer | Prototype Path | Executive Value |
|---|---|---|
| Local workstation | Dockerized web app and processing pipeline | Keeps recordings and generated files local |
| Media processing | FFmpeg, Whisper, frame extraction, reviewer selection | Converts long videos into compact documentation context |
| Authentication | Entra ID with MSAL + PKCE | Limits access to approved users |
| AI proxy | Azure Function on consumption plan | Keeps API key server-side and validates user token |
| Usage reporting | Cosmos DB AI Spend records | Preserves group-level cost visibility |
| Distribution | Private GHCR image | Supports controlled internal rollout |

## 7. Pilot Validation

Pilot validation should compare generated guides against manual documentation for the same recordings. Measures should include:

- Time to first usable draft.
- Number of reviewer edits required.
- Screenshot relevance.
- Step completeness.
- Absence of internal AI or pipeline language.
- Cost per guide and cost per page.
- Trainer and BA confidence in final output.

## 8. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Teams overlays pollute screenshots | Source profile, Needs Attention grouping, frame rejection, and manual frame capture |
| Manual screenshots lack context | Added frames run local OCR/evidence scoring and are mapped to the selected segment |
| AI output includes internal language | Prompt rules, DOCX QA checks, and reviewer inspection |
| Poor audio quality weakens transcript | Optional Teams transcript import and local Whisper fallback |
| Users think processing is stuck | UI progress states for recording processing and guide creation |
| Uncontrolled AI spend | Cosmos-backed AI Spend reporting by user and period |
| Local artifacts are shared unintentionally | Individual workstation folders and authenticated local app access |

## 9. Recommended Next Steps

- Run a pilot with real BA/trainer recordings from multiple workflow types.
- Compare transcript-backed runs against local Whisper-only runs.
- Capture reviewer feedback on screenshot selection and guide quality.
- Establish acceptance criteria for publishable documentation.
- Decide whether the next release should add a Windows-native capture client or continue with imported recordings.
- Review Azure Function and Cosmos operational settings for production hardening.

## Document Control Metadata

| Metadata Field | Document Value |
|---|---|
| Document Title | KCXDocumentor - AI-Assisted Documentation From Screen Recordings |
| Document ID | KCXDOC-BRIEF-001 |
| Version | Executive Prototype Review |
| Status | Prototype Build Ready For Internal Demonstration |
| Effective Date | 2026-06-05 |
| Owner | keycentrix Engineering & Product |
| Audience | Executive Team, Product, Training, Implementation, Engineering |
