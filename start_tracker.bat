@echo off
setlocal
cd /d "%~dp0"
set "BACKEND_PORT=5051"
set "FRONTEND_PORT=5500"

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.10 or newer, then run this launcher again.
  pause
  exit /b 1
)

python -c "import flask, werkzeug, pymysql" >nul 2>nul
if errorlevel 1 (
  echo Installing the project requirements...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Installation failed. Check your internet connection and try again.
    pause
    exit /b 1
  )
)

powershell -NoProfile -Command "try { $api = Invoke-RestMethod -Uri 'http://127.0.0.1:%BACKEND_PORT%/' -TimeoutSec 1; if ($api.service -eq 'Document Tracker API') { exit 0 } } catch {}; exit 1"
if errorlevel 1 (
  start "Document Tracker Backend - port %BACKEND_PORT%" /D "%~dp0" cmd /k "set PORT=%BACKEND_PORT% && set FRONTEND_ORIGIN=http://127.0.0.1:%FRONTEND_PORT% && python app.py"
)

powershell -NoProfile -Command "try { $page = Invoke-WebRequest -Uri 'http://127.0.0.1:%FRONTEND_PORT%/' -TimeoutSec 1; if ($page.Content.Contains('Never miss an')) { exit 0 } } catch {}; exit 1"
if errorlevel 1 (
  start "Document Tracker Frontend - port %FRONTEND_PORT%" /D "%~dp0" cmd /k "set FRONTEND_PORT=%FRONTEND_PORT% && set BACKEND_PORT=%BACKEND_PORT% && python frontend_server.py"
)

powershell -NoProfile -Command "$apiReady = $false; $pageReady = $false; for ($i = 0; $i -lt 30; $i++) { try { $api = Invoke-RestMethod -Uri 'http://127.0.0.1:%BACKEND_PORT%/api/health' -TimeoutSec 1; $apiReady = ($api.status -eq 'ok') } catch {}; try { $page = Invoke-WebRequest -Uri 'http://127.0.0.1:%FRONTEND_PORT%/' -TimeoutSec 1; $pageReady = $page.Content.Contains('Never miss an') } catch {}; if ($apiReady -and $pageReady) { exit 0 }; Start-Sleep -Milliseconds 500 }; exit 1"
if errorlevel 1 (
  echo The tracker services did not both start. Check the Backend and Frontend windows for a port conflict.
  pause
  exit /b 1
)

start "" "http://127.0.0.1:%FRONTEND_PORT%/"
echo Backend API: http://127.0.0.1:%BACKEND_PORT%
echo Frontend:    http://127.0.0.1:%FRONTEND_PORT%
endlocal
