@echo off
REM ---------------------------------------------------------------------------
REM Pinterest Realism Engine — Session Updater & Login Launcher
REM
REM Use this tool to quickly re-authenticate and save updated sessions after
REM changing passwords or when sessions expire.
REM ---------------------------------------------------------------------------

cd /d "%~dp0"
title PRE Session Manager

:MENU
cls
echo =======================================================================
echo          PINTEREST REALISM ENGINE - SESSION RE-AUTHENTICATOR
echo =======================================================================
echo.
echo   Yesterday's password change requires updating your saved sessions.
echo   Choose which service you want to update:
echo.
echo   [1] Google Flow (ImageFX) - Persistent Browser Profile
echo       Opens Chrome to ImageFX; sign in with your new Google password.
echo.
echo   [2] Google Flow Direct API - Network Session Capturer
echo       Opens interceptor; generate 1 test image to refresh captured token.
echo.
echo   [3] Google Colab Upscaler - Persistent Browser Profile
echo       Opens Chrome to your Colab notebook; sign in with your new Google password.
echo.
echo   [4] Pinterest Account - Persistent Browser Profile
echo       Opens Chrome to Pinterest login; sign in with your new password.
echo.
echo   [5] All-in-One: Open Flow, Colab, and Pinterest windows together
echo.
echo   [0] Exit
echo.
echo =======================================================================
set /p choice="Enter your choice (0-5): "

if "%choice%"=="1" goto FLOW_LOGIN
if "%choice%"=="2" goto FLOW_CAPTURE
if "%choice%"=="3" goto COLAB_LOGIN
if "%choice%"=="4" goto PINTEREST_LOGIN
if "%choice%"=="5" goto ALL_LOGIN
if "%choice%"=="0" goto EXIT
goto MENU

:FLOW_LOGIN
echo.
echo [*] Launching Google Flow browser window...
python scripts\login_google_flow.py
echo [*] Sign into Google with your new password in the opened window.
pause
goto MENU

:FLOW_CAPTURE
echo.
echo [*] Launching Google Flow API Interceptor...
start "PRE Flow Capturer" cmd /k python scripts\capture_flow_session.py
echo [*] Interceptor launched in a new window. Follow the on-screen instructions.
pause
goto MENU

:COLAB_LOGIN
echo.
echo [*] Launching Google Colab browser window...
python scripts\login_colab.py
echo [*] Sign into Google with your new password in the opened window.
pause
goto MENU

:PINTEREST_LOGIN
echo.
echo [*] Launching Pinterest login window...
start "PRE Pinterest Login" cmd /k python scripts\init_pinterest_auth.py
echo [*] Follow the instructions in the opened window, log in, and press ENTER.
pause
goto MENU

:ALL_LOGIN
echo.
echo [*] Launching Google Flow...
python scripts\login_google_flow.py
timeout /t 2 /nobreak >nul
echo [*] Launching Google Colab...
python scripts\login_colab.py
timeout /t 2 /nobreak >nul
echo [*] Launching Pinterest login...
start "PRE Pinterest Login" cmd /k python scripts\init_pinterest_auth.py
echo.
echo [DONE] All windows have been launched on your desktop!
echo Sign into each window with your updated passwords.
pause
goto MENU

:EXIT
exit /b 0
