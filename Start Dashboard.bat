@echo off
title FloodX 2.0 — Live Dashboard
cd /d "%~dp0"
echo Starting FloodX 2.0 API server...
echo NOTE: The dashboard screens on ONE reading, then updates live from ESP32.
echo       (Optional CSV replay: python fastapi_server.py --demo)
start "" http://127.0.0.1:8000/v2
python fastapi_server.py --host 0.0.0.0 --port 8000
pause