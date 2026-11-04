@echo off
chcp 65001 >nul
title Rajasthan Private Schools Scraper - Lead Generator
color 0B
echo ==============================================================================
echo       RAJASTHAN PRIVATE SCHOOLS GOOGLE MAPS SCRAPER & EMAIL CRAWLER
echo ==============================================================================
echo.
cd /d "%~dp0"

echo [1/3] Checking Scraper Engine Docker Container...
docker ps >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Docker Desktop is not running!
    echo Please start Docker Desktop and run this script again.
    pause
    exit /b 1
)

echo [2/3] Starting Scraper Engine on Port 8080...
if exist "googlemaps_scraper\google-maps-scraper-kit" (
    cd "googlemaps_scraper\google-maps-scraper-kit"
) else if exist "Google-Map-Scrapper-main\googlemaps_scraper\google-maps-scraper-kit" (
    cd "Google-Map-Scrapper-main\googlemaps_scraper\google-maps-scraper-kit"
)
docker compose up -d
cd /d "%~dp0"

echo [3/3] Launching Rajasthan Schools Scraper Pipeline...
echo.
python rajasthan_schools_scraper.py %*

echo.
echo ==============================================================================
echo Scraping finished. Check 'Rajasthan_Private_Schools.xlsx' in this folder!
echo ==============================================================================
pause

