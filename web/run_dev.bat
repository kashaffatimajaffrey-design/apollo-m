@echo off
REM Launch the dev server on a fixed port so the preview tooling can find it.
cd /d "%~dp0"
npm run dev -- --port 3100
