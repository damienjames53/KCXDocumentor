@echo off
setlocal

set "KCXDOC_ROOT=%USERPROFILE%\KCXDocumentor"
set "KCXDOC_RECORDINGS=%KCXDOC_ROOT%\recordings"
set "KCXDOC_ARTIFACTS=%KCXDOC_ROOT%\artifacts"
set "KCXDOC_PROCESSED=%KCXDOC_ARTIFACTS%\processed"
set "KCXDOC_WHISPER=%KCXDOC_ROOT%\whisper"
set "KCXDOC_IMAGE=ghcr.io/keycentrix/kcxdocumentor:latest"

where docker >nul 2>nul
if errorlevel 1 (
  echo Docker Desktop is not installed or docker.exe is not on PATH.
  echo Install Docker Desktop, start it, then run setup.bat again.
  exit /b 1
)

docker info >nul 2>nul
if errorlevel 1 (
  echo Docker Desktop is installed but not running.
  echo Start Docker Desktop and wait for it to finish initializing, then run setup.bat again.
  exit /b 1
)

if not exist "%KCXDOC_RECORDINGS%" mkdir "%KCXDOC_RECORDINGS%"
if not exist "%KCXDOC_ARTIFACTS%" mkdir "%KCXDOC_ARTIFACTS%"
if not exist "%KCXDOC_PROCESSED%" mkdir "%KCXDOC_PROCESSED%"
if not exist "%KCXDOC_WHISPER%" mkdir "%KCXDOC_WHISPER%"

echo Pulling %KCXDOC_IMAGE%...
docker pull "%KCXDOC_IMAGE%"
if errorlevel 1 (
  echo Docker image pull failed. Confirm GHCR access and try again.
  exit /b 1
)

echo KCXDocumentor setup complete.
echo Recordings folder: %KCXDOC_RECORDINGS%
echo Artifacts folder:  %KCXDOC_ARTIFACTS%
endlocal
