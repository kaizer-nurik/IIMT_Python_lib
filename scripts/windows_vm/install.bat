@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\OEM\bootstrap.ps1
exit /b %ERRORLEVEL%
