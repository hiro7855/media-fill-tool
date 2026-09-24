@echo off
rem ---------------------------------------------------------------------------
rem  Double-click ONCE to install the Python packages the assistant needs.
rem  After it finishes, use 启动媒介助手.bat to run the tool.
rem  Pure ASCII on purpose (cmd.exe decodes batch text as OEM codepage).
rem ---------------------------------------------------------------------------
chcp 65001 >nul
pushd "%~dp0"
set "PYTHONUTF8=1"

set "MFPY="
py -3 -c "print('MFPYOK')" 2>nul | findstr /C:"MFPYOK" >nul && set "MFPY=py -3"
if not defined MFPY (
  python -c "print('MFPYOK')" 2>nul | findstr /C:"MFPYOK" >nul && set "MFPY=python"
)
if not defined MFPY (
  python3 -c "print('MFPYOK')" 2>nul | findstr /C:"MFPYOK" >nul && set "MFPY=python3"
)
if not defined MFPY goto nopython

echo Installing dependencies, please wait...
%MFPY% -m pip install --upgrade pip
%MFPY% -m pip install -r requirements.txt
if errorlevel 1 goto failed

echo.
echo Done. You can now double-click 启动媒介助手.bat to start the tool.
echo Press any key to close this window.
pause >nul
popd
exit /b 0

:failed
echo.
echo Installation failed. Check your network, then run this file again.
echo Press any key to close this window.
pause >nul
popd
exit /b 1

:nopython
echo.
echo Python 3.9 or newer was not found.
echo   1. Install it from https://www.python.org/downloads/
echo   2. During setup, CHECK the box "Add python.exe to PATH"
echo   3. Double-click this file again
echo.
echo Press any key to close this window.
pause >nul
popd
exit /b 1
