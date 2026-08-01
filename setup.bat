@echo off
REM Thin wrapper so Windows users have a single double-clickable entry
REM point. All real logic lives in setup.py.
cd /d "%~dp0"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 setup.py %*
    goto :done
)

where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python setup.py %*
    goto :done
)

echo [FAIL] Python 3 not found on PATH. Install it from https://www.python.org/ and re-run setup.bat.
pause
exit /b 1

:done
pause
