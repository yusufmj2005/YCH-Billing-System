@echo off
rem ==========================================================================
rem  BusinessPOS - build the Windows installer
rem    1. build + test + validate the application (build_app.bat)
rem    2. compile installer\installer.iss with Inno Setup 6
rem  Output: installer_output\BusinessPOS-Setup.exe
rem ==========================================================================
setlocal
cd /d "%~dp0\.."

call build\build_app.bat nopause || goto :fail

set "ISCC="
for %%P in ("%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe" "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe") do (
    if exist %%P set "ISCC=%%~P"
)
if not defined ISCC (
    where iscc >nul 2>nul && set "ISCC=iscc"
)
if not defined ISCC (
    echo ERROR: Inno Setup 6 was not found. Install it from https://jrsoftware.org/isinfo.php
    echo        or run:  winget install JRSoftware.InnoSetup
    goto :fail
)

set /p APPVER=<build\version.tmp
echo Compiling installer for version %APPVER% ...
"%ISCC%" /Q /DMyAppVersion=%APPVER% installer\installer.iss || goto :fail

if not exist "installer_output\BusinessPOS-Setup.exe" (
    echo ERROR: installer_output\BusinessPOS-Setup.exe was not produced.
    goto :fail
)
echo.
echo SUCCESS: installer_output\BusinessPOS-Setup.exe
if /i not "%~1"=="nopause" if /i not "%BPOS_NOPAUSE%"=="1" pause
exit /b 0

:fail
echo.
echo INSTALLER BUILD FAILED.
if /i not "%~1"=="nopause" if /i not "%BPOS_NOPAUSE%"=="1" pause
exit /b 1
