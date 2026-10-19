@echo off
setlocal
set "STRATAMOD_INSTALL_PRIOR_POLICY_PRESENT=0"
set "STRATAMOD_INSTALL_PRIOR_POLICY_VALUE="
if defined PSExecutionPolicyPreference set "STRATAMOD_INSTALL_PRIOR_POLICY_PRESENT=1"
if defined PSExecutionPolicyPreference set "STRATAMOD_INSTALL_PRIOR_POLICY_VALUE=%PSExecutionPolicyPreference%"
set "stratamodInstallMode="
if "%~1"=="" goto run
if /I "%~1"=="--check" goto check
echo Only --check is accepted. 1>&2
exit /b 2
:check
if not "%~2"=="" exit /b 2
set "stratamodInstallMode=-Check"
:run
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0Install-StrataMod.ps1" %stratamodInstallMode%
exit /b %errorlevel%
