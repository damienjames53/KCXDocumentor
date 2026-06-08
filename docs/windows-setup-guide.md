# KCXDocumentor Setup Guide For Windows

This guide helps an internal tester install and run the KCXDocumentor Docker build on a Windows workstation. KCXDocumentor processes local screen recordings, reviews candidate screenshots, creates DOCX user guides, and reports AI spend through the cloud API.

## Audience

- Business analysts, trainers, implementation specialists, and documentation reviewers who will test the application.
- IT or technical users who will prepare the workstation folders and Docker runtime.

## What This Setup Provides

- A local KCXDocumentor web console at `http://127.0.0.1:8765`.
- Local access to source recordings and generated DOCX files through Windows folders.
- Runtime Whisper setup in a shared folder so the container image does not bundle speech-to-text binaries or models.
- Authenticated AI guide generation through the Azure Function API.
- AI Spend reporting persisted outside the local workstation.

## Prerequisites

Confirm the workstation has:

- Windows 10 or Windows 11.
- Docker Desktop installed and running.
- Docker Desktop set to Linux containers.
- Internet access for the first start, unless Whisper has already been preseeded.
- A Microsoft account that is allowed to sign in to KCXDocumentor.
- A GitHub account or token with permission to pull the private KCXDocumentor container package.
- The KCXDocumentor setup folder, including `docker-compose.yml` and `.env.example`.

## Folder Layout

Create the local working folders before starting the container:

```powershell
New-Item -ItemType Directory -Force C:\KCXDocumentor\recordings
New-Item -ItemType Directory -Force C:\KCXDocumentor\artifacts\processed
New-Item -ItemType Directory -Force C:\KCXDocumentor\artifacts
New-Item -ItemType Directory -Force C:\KCXDocumentor\external\whisper
```

Use these folders as follows:

| Folder | Purpose |
|---|---|
| `C:\KCXDocumentor\recordings` | KCXDocumentor stores imported source videos and optional transcript files here. |
| `C:\KCXDocumentor\artifacts\processed` | KCXDocumentor writes local processing sessions here. |
| `C:\KCXDocumentor\artifacts` | Generated DOCX files and QA artifacts are written here. |
| `C:\KCXDocumentor\external\whisper` | Runtime Whisper binaries and models are stored here. |

## Configure The Local Environment

In the KCXDocumentor setup folder, copy `.env.example` to `.env`.

```powershell
Copy-Item .env.example .env
```

Open `.env` and confirm these required values are present:

```text
KCXDOC_REMOTE_API_BASE_URL=https://kcxdocumentor-ai-dev.azurewebsites.net

KCXDOC_HOST_RAW_DIR=C:/KCXDocumentor/recordings
KCXDOC_HOST_PROCESSED_DIR=C:/KCXDocumentor/artifacts/processed
KCXDOC_HOST_ARTIFACTS_DIR=C:/KCXDocumentor/artifacts
KCXDOC_HOST_WHISPER_DIR=C:/KCXDocumentor/external/whisper
```

Leave the remaining `.env.example` values as-is unless the project owner gives you a different tenant, app registration, model, or API endpoint.

The app and Docker Compose already provide defaults for:

- Microsoft Entra tenant, client ID, authority, scopes, and local redirect URLs.
- Whisper bootstrap and update behavior.
- Container-internal Whisper paths.
- Claude model and prompt version.

Do not put Anthropic or Azure Foundry provider keys in the local `.env` file. The production Foundry key belongs on the Azure Function App, not on tester workstations.

## Sign In To GitHub Container Registry

The Docker image is published as a private GitHub Container Registry package:

```text
ghcr.io/keycentrix/kcxdocumentor:latest
```

Create or obtain a GitHub classic personal access token with `read:packages`. Then sign in from PowerShell:

```powershell
$env:CR_PAT = "<github-classic-pat-with-read-packages>"
echo $env:CR_PAT | docker login ghcr.io -u <github-user> --password-stdin
Remove-Item Env:\CR_PAT
```

Do not paste the token into screenshots, Teams chats, tickets, or shared documentation.

## Start KCXDocumentor

From the folder that contains the KCXDocumentor setup scripts, run:

```powershell
setup.bat
launch.bat
```

The first start can take several minutes because the container may download and build `whisper.cpp`, then download the configured model into `C:\KCXDocumentor\external\whisper`.

Watch startup progress:

```powershell
docker logs -f kcxdocumentor
```

When startup is complete, open:

```text
http://127.0.0.1:8765
```

## Verify Readiness

Check container status:

```powershell
docker compose ps
```

Check the app health endpoint:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/health | ConvertTo-Json -Depth 6
```

The health output should show:

- `status` is `ok`.
- `ffmpeg` is available.
- `ffprobe` is available.
- `whisper` is available.
- `modelAvailable` is `true`.

If Whisper is not ready, keep the logs open until bootstrap finishes.

## Import A Test Recording

Use the KCXDocumentor UI as the primary way to add test files:

1. Open `http://127.0.0.1:8765`.
2. Sign in with your Microsoft account.
3. On **Workspace**, choose **Import recording**.
4. Select the source video file.
5. Choose **Import**.
6. If a transcript is available, choose **Import transcript**.
7. Select the transcript file.
8. Choose **Import**.

KCXDocumentor copies imported files into the mapped raw working folder automatically:

```text
C:\KCXDocumentor\recordings
```

Manual copy is still acceptable for technical setup or batch preparation. If you copy files manually, place the source recording and any sidecar transcript in the same folder.

Supported test materials include:

- `.mp4` screen recordings.
- Teams `.vtt` transcript files.

## Create A Guide

1. Open `http://127.0.0.1:8765`.
2. Sign in with your Microsoft account.
3. Import the recording if it is not already listed.
4. Import the transcript if one is available.
5. Choose the recording from the **Recording** list.
6. Choose a transcript only when one is available.
7. Set the target application name.
8. Select **Teams Recording** if the source video includes Teams overlays.
9. Choose **Process Recording**.
10. Review candidate screenshots.
11. Reject frames that show meeting overlays, title cards, participant tiles, or irrelevant transitions.
12. Use **Add Candidate** to pause the video and capture a better screenshot when needed.
13. Choose **Create Guide**.
14. Wait for the AI creation progress indicator to finish.
15. Choose **Download DOCX**.

Generated files are stored under:

```text
C:\KCXDocumentor\artifacts\generated
```

## Review The Result

Before sharing a generated guide, confirm:

- The title names the workflow being documented.
- The purpose describes the workflow, not the recording pipeline.
- Steps are written for the reader.
- Screenshots match the step they support.
- Reviewer concerns appear as Word comments when needed.
- The document body does not include prompt text, model reasoning, internal trace language, or prototype wording.

## AI Spend

Use the **AI Spend** page to review usage by day, week, month, or year. The header also shows current calendar month spend.

AI Spend is stored in the cloud and remains available even if local sessions or generated artifacts are deleted.

## Stop Or Restart

Stop the application:

```powershell
docker compose down
```

Restart the application:

```powershell
docker compose up -d
```

Update to the latest private image:

```powershell
docker compose pull
docker compose up -d
```

## Troubleshooting

| Issue | What To Check |
|---|---|
| Docker cannot connect | Confirm Docker Desktop is running and fully started. |
| The browser cannot open the app | Confirm `docker compose ps` shows port `8765`. |
| Sign-in fails | Confirm the Entra app registration allows `http://127.0.0.1:8765/` and the user is allowed to sign in. |
| The app shows no recordings | Confirm the video is in `C:\KCXDocumentor\recordings` and the `.env` path points to that folder. |
| Whisper is unavailable | Check logs and confirm `C:\KCXDocumentor\external\whisper` is writable. |
| Guide creation fails | Check Latest Activity in the UI. The Azure Function API must be reachable and the signed-in user token must be valid. |
| AI Spend does not load | Confirm the Azure Function API is reachable and the user is signed in. |

## Support Notes

- The local app sends compact prompt data to the Azure Function API. It does not send raw videos to Azure Foundry or Anthropic.
- Recordings, extracted frames, and DOCX files remain in the mapped local folders.
- The local workstation should not store Anthropic or Azure Foundry provider keys.
- The browser URL and redirect URI remain `http://127.0.0.1:8765/`.
