@echo off
title MSRIT AI - Startup
color 0A

echo.
echo ==========================================
echo          MSRIT AI - STARTING
echo ==========================================
echo.

cd /d C:\dev\async-msrit-ai

REM ==================================================
REM 1. PostgreSQL
REM ==================================================

echo [1/4] Checking PostgreSQL...

docker ps --filter "name=msrit-db" --filter "status=running" | findstr "msrit-db" >nul

if %errorlevel% neq 0 (
    echo PostgreSQL is not running. Starting msrit-db...
    docker start msrit-db
) else (
    echo PostgreSQL is already running.
)

REM ==================================================
REM 2. Ollama
REM ==================================================

echo.
echo [2/4] Checking Ollama...

curl -s http://127.0.0.1:11434/api/tags >nul

if %errorlevel% neq 0 (
    echo Ollama is not running.
    echo Starting Ollama...

    start "" "ollama" serve

    echo Waiting for Ollama...

    :WAIT_OLLAMA
    timeout /t 2 /nobreak >nul
    curl -s http://127.0.0.1:11434/api/tags >nul

    if %errorlevel% neq 0 goto WAIT_OLLAMA

    echo Ollama is ready.
) else (
    echo Ollama is already running.
)

REM ==================================================
REM 3. FastAPI
REM ==================================================

echo.
echo [3/4] Checking MSRIT AI backend...

curl -s http://127.0.0.1:8000 >nul

if %errorlevel% equ 0 (
    echo MSRIT AI backend is already running.
) else (
    echo Starting MSRIT AI backend...

    start "MSRIT AI Backend" cmd /k "cd /d C:\dev\async-msrit-ai && .\venv\Scripts\python.exe -m uvicorn backend.main:app"

    echo Waiting for FastAPI...

    :WAIT_FASTAPI
    timeout /t 2 /nobreak >nul
    curl -s http://127.0.0.1:8000 >nul

    if %errorlevel% neq 0 goto WAIT_FASTAPI

    echo FastAPI is ready.
)

REM ==================================================
REM 4. Open browser
REM ==================================================

echo.
echo [4/4] Opening MSRIT AI...

start "" "http://127.0.0.1:8000"

echo.
echo ==========================================
echo       MSRIT AI IS READY!
echo ==========================================
echo.
echo Browser: http://127.0.0.1:8000
echo.
echo You can close this startup window.
echo.
pause