@echo off
setlocal enabledelayedexpansion
title Verified Decision-Maker Discovery Agent
cd /d "%~dp0"

echo ========================================================
echo     VERIFIED DECISION-MAKER DISCOVERY AGENT
echo   (Founders, CEOs, MDs, HR Directors, Recruitment Heads)
echo ========================================================
echo.
echo [Strict Policy]: ZERO-GUESSING (Only 100%% Verified Emails)
echo.

set /p COMPANY_NAME="Enter Company Name: "
if "%COMPANY_NAME%"=="" (
    echo [ERROR] Company name cannot be blank.
    pause
    exit /b 1
)

set /p WEBSITE_URL="Enter Company Website URL (optional, leave blank to auto-resolve): "
set /p CITY_NAME="Enter City / Region (optional): "

echo.
echo Running discovery engine for "%COMPANY_NAME%"...
python scripts\people_agent.py --company "%COMPANY_NAME%" --website "%WEBSITE_URL%" --city "%CITY_NAME%" --dry-run

echo.
pause

