@echo off
cd /d "%~dp0"
echo ===================================================
echo  Opening Google Colab in dedicated PRE profile...
echo ===================================================

set "PROFILE_DIR=%~dp0data\colab_profile"
set "COLAB_URL=https://colab.research.google.com/drive/1TgdpXgPBQ7pKlYO50PsuSX8RcRyu7y9U#scrollTo=HLsprCUNt-MT"

if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="%PROFILE_DIR%" --new-window "%COLAB_URL%"
) else if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" --user-data-dir="%PROFILE_DIR%" --new-window "%COLAB_URL%"
) else if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" (
    start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --user-data-dir="%PROFILE_DIR%" --new-window "%COLAB_URL%"
) else (
    start "" chrome --user-data-dir="%PROFILE_DIR%" --new-window "%COLAB_URL%"
)

echo [SUCCESS] Browser launched!
