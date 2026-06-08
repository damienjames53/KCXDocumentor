---
title: "KCXDocumentor"
subtitle: "Turning workflow recordings into reviewable user guides"
author: "keycentrix"
date: "2026-06-05"
---

# KCXDocumentor

Turning long workflow recordings into reviewable DOCX user guides.

**Executive prototype review**

---

# The Problem

Training and implementation teams already create useful walkthrough recordings.

But converting those recordings into documentation still requires manual effort:

- Rewatch the recording.
- Identify meaningful workflow steps.
- Capture usable screenshots.
- Rewrite narration into customer-facing instructions.
- Build and QA a Word document.

---

# Why It Matters

Manual documentation work is expensive because it uses scarce BA, trainer, and implementation time.

KCXDocumentor targets a repeatable operational gap:

- One-hour recordings can take many hours to document manually.
- Output quality varies by author.
- Screenshot selection is tedious.
- AI costs need to be visible and controlled.

---

# What KCXDocumentor Does

KCXDocumentor turns an imported recording into a reviewable DOCX guide.

1. Import the recording and optional transcript.
2. Process video, audio, and candidate screenshots locally.
3. Review and approve screenshots.
4. Generate an AI-assisted guide through the authenticated proxy.
5. Download a DOCX and review it for publishing.

---

# Local-First Architecture

Raw video stays on the workstation.

The AI receives compact context:

- Transcript segments.
- Timing metadata.
- Reviewer-approved screenshots.
- OCR/action signals.
- Reviewer notes.

This keeps the AI boundary smaller, cheaper, and easier to govern.

---

# Human Quality Gate

KCXDocumentor is not a blind automation tool.

Reviewers can:

- Reject Teams overlays and irrelevant frames.
- Capture a better frame from the source video.
- Add review notes for uncertain terms or steps.
- Keep screenshots aligned to the steps they support.

---

# Current Build

The prototype already includes:

- Dockerized local application.
- Windows-friendly folder mapping.
- Runtime Whisper setup.
- Microsoft Entra sign-in with MSAL + PKCE.
- Azure Function proxy for Azure Foundry Claude.
- Cosmos-backed AI Spend reporting.
- Private GitHub Container Registry distribution.

---

# Executive Visibility

AI Spend makes usage visible.

Leadership can review:

- Documents generated.
- Input and output tokens.
- Estimated cost.
- Pages generated.
- Cost per page.
- User attribution.
- Current calendar month spend.

---

# What Success Looks Like

The pilot should prove:

- Time to first usable guide decreases.
- Screenshots support the right steps.
- Output avoids internal AI and pipeline language.
- Trainers and BAs trust the draft as a starting point.
- Cost per guide and cost per page are predictable.

---

# Recommended Pilot

Run real internal recordings through the tool:

- Teams recordings with transcripts.
- Recordings without transcripts using local Whisper.
- Multiple workflows and recording lengths.
- Reviewer-led screenshot approval.
- Side-by-side comparison against manual documentation.

---

# Ask

Approve KCXDocumentor for internal pilot use with BAs and trainers.

Pilot focus:

- Documentation quality.
- Reviewer workflow.
- Screenshot relevance.
- Cost visibility.
- Windows workstation setup.
- Readiness for broader internal rollout.
