@echo off
setlocal

set "KCXDOC_CONTAINER=kcxdocumentor"

where docker >nul 2>nul
if errorlevel 1 (
  echo Docker Desktop is not installed or docker.exe is not on PATH.
  exit /b 1
)

for /f %%i in ('docker ps -q -f "name=^/%KCXDOC_CONTAINER%$"') do (
  docker stop "%KCXDOC_CONTAINER%"
  echo KCXDocumentor stopped.
  exit /b 0
)

echo KCXDocumentor is not running.
endlocal
