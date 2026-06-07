@echo off
setlocal

set "KCXDOC_IMAGE=ghcr.io/keycentrix/kcxdocumentor:latest"

where docker >nul 2>nul
if errorlevel 1 (
  echo Docker Desktop is not installed or docker.exe is not on PATH.
  exit /b 1
)

docker info >nul 2>nul
if errorlevel 1 (
  echo Docker Desktop is installed but not running.
  exit /b 1
)

echo Pulling %KCXDOC_IMAGE%...
docker pull "%KCXDOC_IMAGE%"
if errorlevel 1 (
  echo Docker image update failed. Confirm GHCR access and try again.
  exit /b 1
)

echo KCXDocumentor image updated.
endlocal
