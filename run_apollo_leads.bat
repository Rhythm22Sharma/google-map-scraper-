@echo off
setlocal
cd /d "%~dp0"
echo ========================================================
echo        TALTRA - APOLLO LEAD GENERATION ENGINE
echo ========================================================
echo.
echo How many verified leads would you like to fetch?
echo (Each verified contact uses 1 Apollo email credit)
set /p LEADS_COUNT="Enter number of leads (default 10): "
if "%LEADS_COUNT%"=="" set LEADS_COUNT=10

echo.
echo Target Country (e.g., India, United States, United Kingdom, or leave blank for all):
set /p TARGET_COUNTRY="Enter country name (optional): "

echo.
echo Running Apollo Prospector for %LEADS_COUNT% leads...
python scripts\apollo_prospector.py %LEADS_COUNT% "%TARGET_COUNTRY%"

echo.
pause
