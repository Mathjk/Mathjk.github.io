@echo off
setlocal EnableExtensions

set HOST=127.0.0.1
set PORT=8765

if defined GPU_DASHBOARD_DIR call :try_dir "%GPU_DASHBOARD_DIR%" && goto :eof
call :try_dir "%~dp0..\gpu-dashboard" && goto :eof
call :try_dir "%~dp0..\..\gpu-dashboard" && goto :eof
call :try_dir "%USERPROFILE%\gpu-dashboard" && goto :eof
call :try_dir "E:\py_code\dist\myweb\myweb_windows11_test\gpu-dashboard" && goto :eof
call :try_dir "E:\py_code\dist\myweb\myweb_windows11_test\myweb\gpu-dashboard" && goto :eof

echo GPU Dashboard directory was not found.
echo.
echo Set GPU_DASHBOARD_DIR to the Windows directory that contains app.py or start.cmd.
echo Example:
echo   setx GPU_DASHBOARD_DIR "E:\path\to\gpu-dashboard"
echo.
pause
exit /b 1

:try_dir
set DASH_DIR=%~1
if not exist "%DASH_DIR%\" exit /b 1

if exist "%DASH_DIR%\start.cmd" (
  start "GPU Dashboard" /D "%DASH_DIR%" "%DASH_DIR%\start.cmd"
  exit /b 0
)

if exist "%DASH_DIR%\start.bat" (
  start "GPU Dashboard" /D "%DASH_DIR%" "%DASH_DIR%\start.bat"
  exit /b 0
)

if exist "%DASH_DIR%\app.py" (
  where py >nul 2>nul
  if not errorlevel 1 (
    start "GPU Dashboard" /D "%DASH_DIR%" py -3 app.py --host %HOST% --port %PORT%
    exit /b 0
  )

  where python >nul 2>nul
  if not errorlevel 1 (
    start "GPU Dashboard" /D "%DASH_DIR%" python app.py --host %HOST% --port %PORT%
    exit /b 0
  )
)

exit /b 1
