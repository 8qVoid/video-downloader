@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run Start Downloader.cmd first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -U --pre -r requirements.txt
if errorlevel 1 (
    echo Update failed. Check your internet connection.
) else (
    echo Downloader components updated.
)
pause
