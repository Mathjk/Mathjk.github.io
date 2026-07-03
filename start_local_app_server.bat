@echo off
cd /d %~dp0
set MYWEB_APP_ROOT=E:\py_code\dist\myweb\myweb_windows11_test\myweb\myapp

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 local_app_server.py
  goto :eof
)

python local_app_server.py
