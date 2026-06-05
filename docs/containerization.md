# KCXDocumentor Container Runbook

KCXDocumentor can run as a local Docker container while keeping recordings, processed sessions, generated artifacts, and Whisper assets outside the image.

## Design

- The image includes the Python app, static web console, document tooling, FFmpeg, Tesseract, and build tools needed to compile `whisper.cpp`.
- The image does **not** include `whisper-cli` or Whisper model files at build time.
- At container startup, the entrypoint can fetch the latest `whisper.cpp` release source, build `whisper-cli`, and download the configured model into the mounted Whisper share.
- Host folders are mounted into the container:
  - `samples/raw` -> `/app/samples/raw`
  - `samples/processed` -> `/app/samples/processed`
  - `artifacts` -> `/app/artifacts`
  - external Whisper share -> `/opt/kcxdocumentor/external/whisper`

This keeps large recordings and generated documents on the local workstation filesystem and avoids rebuilding the image when Whisper binaries or models change.

## Expected Whisper Share

The mounted Whisper folder uses this shape after startup:

```text
external/whisper/
  .whispercpp-version
  bin/
    whisper-cli
  models/
    ggml-base.en.bin
```

By default `KCXDOC_BOOTSTRAP_WHISPER=true`, so the container creates this layout automatically when the mounted share is writable and the container has internet access. The first start can take several minutes because it compiles `whisper.cpp`.

The runtime bootstrap uses:

```text
KCXDOC_BOOTSTRAP_WHISPER=true
KCXDOC_WHISPER_UPDATE=latest
KCXDOC_WHISPER_ROOT=/opt/kcxdocumentor/external/whisper
KCXDOC_WHISPER_MODEL_NAME=ggml-base.en.bin
KCXDOC_WHISPER_MODEL_URL=https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin
```

Set `KCXDOC_BOOTSTRAP_WHISPER=false` when running in an offline enterprise environment and preseed the mounted share yourself. Set `KCXDOC_WHISPER_UPDATE=never` to reuse an existing binary/model without checking for a newer release.

## Host Folder Mapping

Default Compose mappings use repo-local folders. Override them in `.env` when you want workstation-local folders:

```text
KCXDOC_HOST_RAW_DIR=C:\KCXDocumentor\samples\raw
KCXDOC_HOST_PROCESSED_DIR=C:\KCXDocumentor\samples\processed
KCXDOC_HOST_ARTIFACTS_DIR=C:\KCXDocumentor\artifacts
KCXDOC_HOST_WHISPER_DIR=C:\KCXDocumentor\external\whisper
KCXDOC_BOOTSTRAP_WHISPER=true
KCXDOC_WHISPER_UPDATE=latest
```

On macOS or Linux, use native paths:

```text
KCXDOC_HOST_RAW_DIR=/Users/djames/KCXDocumentor/samples/raw
KCXDOC_HOST_PROCESSED_DIR=/Users/djames/KCXDocumentor/samples/processed
KCXDOC_HOST_ARTIFACTS_DIR=/Users/djames/KCXDocumentor/artifacts
KCXDOC_HOST_WHISPER_DIR=/Users/djames/KCXDocumentor/external/whisper
KCXDOC_BOOTSTRAP_WHISPER=true
KCXDOC_WHISPER_UPDATE=latest
```

## Run

Build locally:

```bash
docker compose build
docker compose up -d
```

Or pull the private GitHub Container Registry image after authenticating to GHCR:

```bash
echo <github-classic-pat-with-read-packages> | docker login ghcr.io -u damienjames53 --password-stdin
docker compose pull
docker compose up -d
```

The image name is:

```text
ghcr.io/damienjames53/kcxdocumentor:dev
```

Watch first-start bootstrap logs:

```bash
docker compose logs -f kcxdocumentor
```

Open:

```text
http://127.0.0.1:8765
```

The browser port does not change when running in Docker. The app listens on `0.0.0.0:8765` inside the container, and Compose maps it back to the host as `127.0.0.1:8765`.

Check readiness:

```bash
curl http://127.0.0.1:8765/api/health
```

Expected healthy container response includes:

```json
{
  "status": "ok",
  "workspace": "/app",
  "rawRoot": "samples/raw",
  "processedRoot": "samples/processed",
  "generatedRoot": "artifacts/generated",
  "tools": {
    "ffmpeg": { "available": true, "path": "/usr/bin/ffmpeg" },
    "ffprobe": { "available": true, "path": "/usr/bin/ffprobe" },
    "whisper": {
      "available": true,
      "modelAvailable": true,
      "path": "/opt/kcxdocumentor/external/whisper/bin/whisper-cli",
      "modelPath": "/opt/kcxdocumentor/external/whisper/models/ggml-base.en.bin"
    }
  }
}
```

Check container status:

```bash
docker compose ps
```

Expected service mapping:

```text
0.0.0.0:8765->8765/tcp
```

Do not run the Docker socket path as a command. This is an internal Docker API file:

```text
/Users/<user>/.docker/run/docker.sock
```

If Compose reports that this socket is missing, Docker Desktop is not running or has not finished starting.

## Notes

- The app still uses the Azure Function proxy for Anthropic and AI Spend.
- The browser redirect URI remains `http://127.0.0.1:8765/`.
- Generated DOCX files are written to the mounted artifacts folder.
- AI usage reporting persists in Cosmos DB and is not lost when local artifacts are deleted.
- Whisper binaries and models persist in the mounted Whisper folder, so rebuilding the KCXDocumentor image does not force a new Whisper download.
