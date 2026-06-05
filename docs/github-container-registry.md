# GitHub Container Registry

KCXDocumentor publishes its Docker image to GitHub Container Registry as a private package:

```text
ghcr.io/damienjames53/kcxdocumentor:dev
```

The publishing workflow is:

```text
.github/workflows/publish-container.yml
```

## Visibility

The repository is public, but the container package should remain private. GitHub's Container Registry documentation states that the first publish of a package defaults to private visibility. The workflow pushes the image with `packages: write`; do not change the package visibility to public in GitHub package settings.

## Pull Access

GitHub Container Registry requires authentication for private packages.

For local pulls, use a classic GitHub personal access token with `read:packages`:

```bash
echo <github-classic-pat-with-read-packages> | docker login ghcr.io -u damienjames53 --password-stdin
docker pull ghcr.io/damienjames53/kcxdocumentor:dev
```

Then run:

```bash
docker compose up -d
```

## Build Behavior

The GHCR image still does not bundle Whisper binaries or models at image build time. Runtime startup can bootstrap latest `whisper.cpp` into the mounted external Whisper share, as described in `docs/containerization.md`.

## Documentation Sources

- GitHub publishing Docker images: https://docs.github.com/actions/tutorials/publish-packages/publish-docker-images
- GitHub Container Registry: https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry
