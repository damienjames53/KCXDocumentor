# KCXDocumentor User Guide

This guide walks through the local KCXDocumentor prototype from recording selection through DOCX download, QA review, and AI Spend tracking.

## Before You Start

Confirm the local app server is running:

```bash
.venv/bin/python scripts/app_server.py --host 127.0.0.1 --port 8765
```

Open the console:

```text
http://127.0.0.1:8765
```

Use recordings from:

```text
samples/raw/
```

Optional transcript files, such as Teams `.vtt` exports, should also be placed in `samples/raw/`.

## Create A Guide

1. Open the **Workspace** page.
2. In **Recording**, choose the screen recording you want to process.
3. In **Transcript**, choose a transcript when one is available.
4. Leave the transcript blank when you want KCXDocumentor to use local Whisper transcription.
5. Set **Target Application** to the application being documented, such as `Blink Rx`.
6. Use **Source Profile**:
   - `Standard` for ordinary screen recordings.
   - `Teams Recording` for Teams recordings with meeting overlays, title cards, or participant chrome.
7. Choose **Process Recording**.
8. Wait for the session to appear in the session list for the selected recording.
9. Open the **Frames** review area.
10. Approve screenshots that clearly show the application state needed for a step.
11. Reject screenshots that show Teams overlays, title cards, irrelevant transitions, or confusing UI states.
12. Use **Add Candidate** when the automatic candidates missed an important screen.
13. In the video picker, pause on the desired frame and capture it.
14. Add a short reviewer note when a frame, term, or step needs human verification.
15. Choose **Create Guide**.
16. Keep the page open while the AI progress message is active.
17. When guide creation finishes, choose **Download DOCX**.
18. Open the DOCX and review it as a customer-facing draft.

**Create Guide** performs the AI draft, DOCX build, and local QA check as one chained action. **Download DOCX** becomes useful after that workflow succeeds.

## Review The Result

Check the generated guide for:

- A specific title that names the workflow.
- A purpose written for the reader, not for the pipeline.
- Clear section headings when the recording covers more than one workflow.
- Second-person instructions, such as "Select Save" instead of "I clicked Save."
- Screenshots that match the step they support.
- Word comments for reviewer concerns instead of inline AI notes in the body.
- No hidden chain-of-thought, prompt text, or internal pipeline language.

Use **Re-run QA** after changing screenshot approvals or regenerating the guide. QA is local and does not use AI tokens.

## If Guide Creation Fails

If the AI call fails, the workflow stops and the Latest Activity area shows the failure reason. When Anthropic returned token usage before the failure, KCXDocumentor records that usage in AI Spend.

Common examples:

- The model returned incomplete JSON.
- The response exceeded the available output budget.
- The API request failed.
- The source trace is missing or invalid.

When a failed AI attempt includes usage data, it is stored in:

```text
artifacts/usage/generation_usage.sqlite3
```

The failed session may also have:

```text
artifacts/generated/<sessionId>/generation_failure.json
```

Failed attempts count toward AI Spend but do not count as successful documents.

## Use AI Spend

1. Choose **AI Spend** in the top navigation.
2. Use **Day**, **Week**, **Month**, or **Year** to change the reporting range.
3. Review:
   - **Documents**: successful generated documents.
   - **Tokens**: total input and output tokens across successful and failed AI attempts.
   - **Input / Output**: token direction for cost analysis.
   - **Estimated Cost**: estimated Anthropic cost for the selected range.
4. Check the header **Current Month Spend** for calendar-month visibility without opening the report page.

AI Spend persists even when sessions or generated artifacts are deleted. This is intentional so usage reporting remains auditable.

## Delete Old Sessions

Use **Delete Session** when a processed session is stale or tied to deleted local material.

Deleting a session removes:

```text
samples/processed/<sessionId>
artifacts/generated/<sessionId>
```

Deleting a session does not remove:

```text
samples/raw/
artifacts/usage/generation_usage.sqlite3
```

## Recommended First Test

For the current Blink Rx test material:

1. Select `Blink Rx Training Part 1 112125.mp4`.
2. Select `Blink Rx Training Part 1 112125-en-US.vtt`.
3. Set the target application to `Blink Rx`.
4. Use `Teams Recording` if the source includes Teams overlays.
5. Process the recording.
6. Review and reject overlay-heavy frames.
7. Create the guide.
8. Download and review the DOCX.
9. Open **AI Spend** and confirm the successful generation appears in the current month.

Repeat without the transcript to compare local Whisper output against the Teams transcript.
