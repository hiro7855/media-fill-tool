@echo off
rem ---------------------------------------------------------------------------
rem  Double-click to start the Media Assistant local web app, then KEEP THIS
rem  WINDOW OPEN. A browser tab opens automatically at http://127.0.0.1:8765/.
rem  Closing this window stops the service.
rem
rem  This file MUST stay pure ASCII: cmd.exe decodes batch text using the
rem  console OEM codepage, so non-ASCII characters here would be mojibake or
rem  break parsing. The filename itself may be Chinese (NTFS is Unicode).
rem  PYTHONUTF8=1 makes Python emit UTF-8 so Chinese console output is safe.
rem  All real logic lives in src\webapp.py, shared with macOS.
rem ---------------------------------------------------------------------------
chcp 65001 >nul
pushd "%~dp0"
set "PYTHONUTF8=1"

rem Probe for a usable interpreter. We require printed sentinel output rather
rem than trusting the exit code: the Microsoft Store "python" execution alias
rem is a stub that opens the Store and may still exit 0.
set "MFPY="
py -3 -c "print('MFPYOK')" 2>nul | findstr /C:"MFPYOK" >nul && set "MFPY=py -3"
if not defined MFPY (
  python -c "print('MFPYOK')" 2>nul | findstr /C:"MFPYOK" >nul && set "MFPY=python"
)
if not defined MFPY (
  python3 -c "print('MFPYOK')" 2>nul | findstr /C:"MFPYOK" >nul && set "MFPY=python3"
)
if not defined MFPY goto nopython

%MFPY% src\webapp.py --serve
if errorlevel 1 goto failed
popd
exit /b 0

:failed
echo.
echo The service stopped with an error.
echo If it mentioned a missing module (e.g. flask), install dependencies first:
echo     py -3 -m pip install flask requests pillow openpyxl pyyaml
echo Then double-click this file again.
echo.
echo Press any key to close this window.
pause >nul
popd
exit /b 1

:nopython
echo.
echo Python 3.9 or newer was not found.
echo.
echo   1. Install it from https://www.python.org/downloads/
echo   2. During setup, CHECK the box "Add python.exe to PATH"
echo   3. Double-click this file again
echo.
echo Press any key to close this window.
pause >nul
popd
exit /b 1
