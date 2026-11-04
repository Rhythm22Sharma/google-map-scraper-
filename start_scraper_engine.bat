@echo off
title Start Google Maps Scraper Engine
echo ========================================================
echo   Starting Google Maps Scraper Engine (Docker)...
echo   Host Port: 8085 (avoiding Apache on 8080)
echo ========================================================
cd /d "%~dp0\googlemaps_scraper\google-maps-scraper-kit"
docker compose up -d
echo.
echo Container Status:
docker ps
echo.
echo If Docker gave an error, please ensure Docker Desktop is open.
pause
