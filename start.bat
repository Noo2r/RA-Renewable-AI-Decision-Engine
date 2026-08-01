@echo off
REM Thin wrapper so Windows users have a single double-clickable entry
REM point. All real logic lives in start.py.
cd /d "%~dp0"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 start.py %*
    goto :eof
)

where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python start.py %*
    goto :eof
)

echo [FAIL] Python 3 not found on PATH. Install it from https://www.python.org/ and re-run start.bat.
pause
exit /b 1
