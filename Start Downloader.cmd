@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Setting up Video Downloader for the first time...
    python -m venv .venv
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -c "import yt_dlp, deno, imageio_ffmpeg, curl_cffi" >nul 2>nul
if errorlevel 1 (
    echo Installing free downloader components. This can take a few minutes...
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo Setup or launch failed. Check the message above, then press any key.
pause >nul
exit /b 1
