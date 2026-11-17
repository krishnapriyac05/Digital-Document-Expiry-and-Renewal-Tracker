@echo off
setlocal
cd /d "%~dp0"
set "PORT=5000"
set "SERVE_FRONTEND=true"

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.10 or newer, then run this launcher again.
  pause
  exit /b 1
)

python -c "import flask, werkzeug" >nul 2>nul
if errorlevel 1 (
  echo Installing the project requirements...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Installation failed. Check your internet connection and try again.
    pause
    exit /b 1
  )
)

echo Starting the Document Tracker.
echo Open http://127.0.0.1:%PORT% in your browser after the server starts.
python app.py
if errorlevel 1 (
  echo The tracker stopped with an error. Read the message above for details.
  pause
)
endlocal
