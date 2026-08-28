@echo off
setlocal
set "ROOT=%~dp0.."
if not exist "%ROOT%\.venv\Scripts\python.exe" (
  echo Shared environment not found. Run scripts\bootstrap.ps1 first. 1>&2
  exit /b 1
)
"%ROOT%\.venv\Scripts\python.exe" %*
