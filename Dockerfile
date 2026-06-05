FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    KCXDOC_CONTAINER=1 \
    KCXDOC_BOOTSTRAP_WHISPER=true \
    KCXDOC_WHISPER_ROOT=/opt/kcxdocumentor/external/whisper \
    KCXDOC_WHISPER_CLI=/opt/kcxdocumentor/external/whisper/bin/whisper-cli \
    KCXDOC_WHISPER_MODEL=/opt/kcxdocumentor/external/whisper/models/ggml-base.en.bin

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        curl \
        ffmpeg \
        tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY assets ./assets
COPY docs ./docs
COPY prompts ./prompts
COPY schemas ./schemas
COPY scripts ./scripts
COPY tools ./tools
COPY web ./web
COPY docker/entrypoint.sh /usr/local/bin/kcxdocumentor-entrypoint

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir . \
    && chmod +x /usr/local/bin/kcxdocumentor-entrypoint

RUN mkdir -p \
    /app/samples/raw \
    /app/samples/processed \
    /app/artifacts/generated \
    /app/artifacts/qa \
    /app/artifacts/usage \
    /opt/kcxdocumentor/external/whisper/bin \
    /opt/kcxdocumentor/external/whisper/models

EXPOSE 8765

ENTRYPOINT ["kcxdocumentor-entrypoint"]
CMD ["python", "scripts/app_server.py", "--host", "0.0.0.0", "--port", "8765"]
