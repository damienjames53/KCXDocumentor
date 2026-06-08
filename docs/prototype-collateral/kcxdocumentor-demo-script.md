# KCXDocumentor Demo Script and Storyboard

Proposed 3 to 5 minute executive demo flow with on-screen captions and narration.

## Demo Objective

Show that KCXDocumentor is a working internal prototype that can transform local screen recordings into reviewable DOCX user guides while preserving local processing, authenticated AI access, reviewer control, and AI spend visibility.

Recommended length: 3 to 5 minutes.

## Production Notes

- Keep the recording focused on the documentation workflow, not implementation details.
- Use a real source recording and show the import process.
- Emphasize that raw video stays local.
- Show frame approval/rejection because this is the human quality gate.
- Show Add from Video and explain that added frames are OCR-enriched locally and mapped to the selected segment.
- Show AI Spend to demonstrate cost visibility.
- Close with the pilot ask: validate guide quality with trainers and BAs using real workflow recordings.

## Storyboard

| Segment | Visual | On-screen caption | Narration |
|---|---|---|---|
| Opening | KCXDocumentor workspace | Long workflow recordings should not require hours of manual documentation work. | KCXDocumentor turns recorded workflow walkthroughs into structured DOCX guides using local processing, reviewer-selected screenshots, and controlled AI generation. |
| Scene 1 - Import | Import recording and transcript controls | Users import recordings directly from the browser UI. | A BA or trainer imports a screen recording and, when available, a Teams transcript. The app copies the files into the mapped local working folder automatically. |
| Scene 2 - Process Recording | Processing status and session creation | Media processing stays local. | FFmpeg, Whisper, and frame extraction run on the workstation. The app creates a compact trace and candidate screenshots without sending raw video to the AI provider. |
| Scene 3 - Review Frames | Frame reviewer with Recommended, Alternates, Needs Attention, and Add from Video | Reviewers decide which screenshots are eligible for the guide. | The reviewer rejects Teams overlays or irrelevant frames and can pause the video to capture a better screenshot. Added frames run local OCR, are mapped to the selected segment, and rejected frames are not sent into the AI guide context. |
| Scene 4 - Create Guide | AI generation progress state | The guide is generated from compact reviewed context. | KCXDocumentor sends only compact prompt data through the authenticated Azure Function proxy. The Azure Foundry key stays server-side. |
| Scene 5 - Download DOCX | Download DOCX and generated guide | The output is a reviewable Word guide. | The resulting DOCX contains reader-facing steps, selected screenshots, and reviewer comments where human validation is needed. |
| Scene 6 - AI Spend | AI Spend page | Leadership gets cost and usage visibility. | The AI Spend page shows documents, tokens, pages, cost per page, current month spend, and which authenticated user generated each guide. |
| Close | Pilot readiness summary | Pilot ask: validate quality against real BA and trainer workflows. | The next step is to run representative recordings through the tool, compare against manual documentation, and decide what hardening is needed for a broader rollout. |

## Demo Close

KCXDocumentor is ready to be tested with internal trainers and business analysts. The pilot should focus on output quality, screenshot relevance, reviewer workflow, cost per finished page, and the handoff from generated draft to publishable guide.
