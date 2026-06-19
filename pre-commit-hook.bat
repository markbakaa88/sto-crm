@echo off
rem Windows command script fallback/equivalent for git hook or manual execution
where python3 >nul 2>nul
if %ERRORLEVEL% equ 0 (
    python3 check_whitespace.py %*
    exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    python check_whitespace.py %*
    exit /b %ERRORLEVEL%
)

where py >nul 2>nul
if %ERRORLEVEL% equ 0 (
    py check_whitespace.py %*
    exit /b %ERRORLEVEL%
)

echo Error: Python interpreter not found. Cannot run whitespace validation. >&2
exit /b 1
