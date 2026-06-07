@echo off
setlocal

set "KCXDOC_ROOT=%USERPROFILE%\KCXDocumentor"
set "KCXDOC_RECORDINGS=%KCXDOC_ROOT%\recordings"
set "KCXDOC_ARTIFACTS=%KCXDOC_ROOT%\artifacts"
set "KCXDOC_PROCESSED=%KCXDOC_ARTIFACTS%\processed"
set "KCXDOC_WHISPER=%KCXDOC_ROOT%\whisper"
set "KCXDOC_IMAGE=ghcr.io/keycentrix/kcxdocumentor:latest"
set "KCXDOC_CONTAINER=kcxdocumentor"

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

if not exist "%KCXDOC_RECORDINGS%" mkdir "%KCXDOC_RECORDINGS%"
if not exist "%KCXDOC_ARTIFACTS%" mkdir "%KCXDOC_ARTIFACTS%"
if not exist "%KCXDOC_PROCESSED%" mkdir "%KCXDOC_PROCESSED%"
if not exist "%KCXDOC_WHISPER%" mkdir "%KCXDOC_WHISPER%"

for /f %%i in ('docker ps -q -f "name=^/%KCXDOC_CONTAINER%$"') do (
  echo KCXDocumentor is already running.
  start "" "http://localhost:8765"
  exit /b 0
)

for /f %%i in ('docker ps -aq -f "name=^/%KCXDOC_CONTAINER%$"') do (
  docker rm "%KCXDOC_CONTAINER%" >nul
)

docker run -d ^
  --name "%KCXDOC_CONTAINER%" ^
  -p 127.0.0.1:8765:8765 ^
  -v "%KCXDOC_RECORDINGS%:/app/samples/raw" ^
  -v "%KCXDOC_PROCESSED%:/app/samples/processed" ^
  -v "%KCXDOC_ARTIFACTS%:/app/artifacts" ^
  -v "%KCXDOC_WHISPER%:/opt/kcxdocumentor/external/whisper" ^
  -e KCXDOC_AUTH_REDIRECT_URI=http://127.0.0.1:8765/ ^
  -e KCXDOC_AUTH_POST_LOGOUT_REDIRECT_URI=http://127.0.0.1:8765/ ^
  -e KCXDOC_BOOTSTRAP_WHISPER=true ^
  -e KCXDOC_WHISPER_UPDATE=latest ^
  -e KCXDOC_WHISPER_ROOT=/opt/kcxdocumentor/external/whisper ^
  -e KCXDOC_WHISPER_CLI=/opt/kcxdocumentor/external/whisper/bin/whisper-cli ^
  -e KCXDOC_WHISPER_MODEL=/opt/kcxdocumentor/external/whisper/models/ggml-base.en.bin ^
  "%KCXDOC_IMAGE%"

if errorlevel 1 (
  echo KCXDocumentor failed to start.
  exit /b 1
)

echo KCXDocumentor is starting at http://localhost:8765
start "" "http://localhost:8765"
endlocal
