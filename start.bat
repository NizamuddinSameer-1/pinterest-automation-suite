@echo off
REM ---------------------------------------------------------------------------
REM Pinterest Realism Engine — start all 4 live windows
REM
REM   double-click it, or from PowerShell:  .\start.bat
REM
REM   1. backend      python -u run.py                 -> http://127.0.0.1:8000
REM   2. frontend     npm run dev (vite)              -> http://localhost:3000
REM   3. gen watcher  python -u -m scripts.watch_generations  -> Flow 4-var logs
REM   4. pub watcher  python -u -m scripts.watch_runs         -> Publish logs
REM
REM Why 4? Publish and generation are DIFFERENT processes:
REM   - publish  = data\publish_runs\<run_id>\status.json  (browser posting)
REM   - gen      = data\outputs\<job_id>\status.json + bg_log.txt  (Flow images)
REM Old start.bat only watched publish, so generation stayed dark.
REM
REM -u = unbuffered, so logs appear live line-by-line (not batched).
REM /d = start's directory flag (avoids the 4-quote cmd /k bug with spaces).
REM ---------------------------------------------------------------------------

cd /d "%~dp0"
echo Starting PRE from %CD%
echo.

REM Kill stale runs so "runs old" can't happen (port 8000 / 3000 still bound)
echo Cleaning stale python/node on 8000/3000 (if any)...
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":8000" ^| findstr LISTENING') do taskkill /F /PID %%p >nul 2>&1
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":3000" ^| findstr LISTENING') do taskkill /F /PID %%p >nul 2>&1
timeout /t 1 /nobreak >nul

echo [1/4] backend  (http://127.0.0.1:8000/docs)
start "PRE backend  (python -u run.py)" cmd /k python -u run.py
timeout /t 4 /nobreak >nul

echo [2/4] frontend (http://localhost:3000)
REM /d avoids the "cd /d ... && npm" 4-quote bug with spaces in the path
start "PRE frontend (vite)" /d "%~dp0frontend" cmd /k npm run dev
timeout /t 3 /nobreak >nul

echo [3/5] unified watcher (GEN + PUB with progress bars)  -- SEE THIS ONE
start "PRE watcher (LIVE progress)" cmd /k python -u -m scripts.watch_all

echo [4/5] generation watcher (Flow 4-var, legacy)
start "PRE gen watcher (Flow)" cmd /k python -u -m scripts.watch_generations

echo [5/5] publish watcher (browser posting, legacy)
start "PRE publish watcher" cmd /k python -u -m scripts.watch_runs

timeout /t 3 /nobreak >nul
start "" http://localhost:3000

echo.
echo   backend   http://127.0.0.1:8000/docs   (live logs in its window, -u unbuffered)
echo   frontend  http://localhost:3000
echo   UNIFIED   python -u -m scripts.watch_all  (NEW — shows BOTH with bars, where it is stuck)
echo   gen logs  follow data\outputs\*\bg_log.txt
echo   pub logs  follow data\publish_runs\*\log.txt
echo.
echo *** WATCH THE "LIVE progress" WINDOW — it shows bars for Generate AND Publish ***
echo     If it says "GEN ... 0/4  Running scene director..." you know it's stuck on LLM
echo     If it says "GEN ... 37%  1 media named" you know Flow is rendering
echo     If it says "PUB ... 2/4" you know browser is posting
echo This launcher can be closed; the 5 windows keep running. Close a window to stop that piece.
echo If a window says "port already in use", close all 5 and re-run start.bat.
echo.
pause
