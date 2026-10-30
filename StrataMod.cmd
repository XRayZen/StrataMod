@echo off
cd /d "%~dp0"
"%~dp0..\Strata\.venv\Scripts\python.exe" -B -X utf8 -m local_runtime.normal_runtime %*
exit /b %errorlevel%
