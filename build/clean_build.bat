@echo off
rem Removes previous build output. Never touches business data
rem (%LOCALAPPDATA%\BusinessPOS) or the .venv folder.
setlocal
cd /d "%~dp0\.."
echo Cleaning previous build output...
if exist "build\pyinstaller" rmdir /s /q "build\pyinstaller"
if exist "dist" rmdir /s /q "dist"
if exist "installer_output" rmdir /s /q "installer_output"
if exist "build\version_info.txt" del /q "build\version_info.txt"
for /d /r "app" %%d in (__pycache__) do if exist "%%d" rmdir /s /q "%%d"
for /d /r "tests" %%d in (__pycache__) do if exist "%%d" rmdir /s /q "%%d"
echo Clean complete.
if /i not "%~1"=="nopause" if /i not "%BPOS_NOPAUSE%"=="1" pause
exit /b 0
