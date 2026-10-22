@echo off
setlocal DisableDelayedExpansion
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONSTARTUP="
set "PYTHONEXECUTABLE="
set "__PYVENV_LAUNCHER__=C:\Develop\AI\Strata\.venv\Scripts\python.exe"
"C:\Users\yaruo\AppData\Local\Programs\Python\Python312\python.exe" -E -s -B -X utf8 "%~dp0strata_cli.py" %*
set "strata_exit=%errorlevel%"
endlocal & exit /b %strata_exit%
