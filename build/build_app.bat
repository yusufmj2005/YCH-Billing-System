@echo off
rem ==========================================================================
rem  BusinessPOS - build the standalone Windows application
rem    1. clean previous build      4. build with PyInstaller
rem    2. install/check deps         5. validate output + packaged self-test
rem    3. run automated tests
rem  Output: dist\BusinessPOS\BusinessPOS.exe
rem  Developer machine only; end users install BusinessPOS-Setup.exe.
rem ==========================================================================
setlocal
cd /d "%~dp0\.."
set "PY=.venv\Scripts\python.exe"

echo [1/5] Cleaning previous build...
call build\clean_build.bat nopause || goto :fail

echo [2/5] Checking Python environment and dependencies...
if not exist "%PY%" (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3.12 -m venv .venv || py -3 -m venv .venv
    ) else (
        python -m venv .venv
    )
)
if not exist "%PY%" (
    echo ERROR: Python 3.11+ is required on the BUILD machine to create .venv.
    goto :fail
)
rem Exact pinned versions so every release is built from the same libraries.
"%PY%" -m pip install --disable-pip-version-check -q -r requirements-lock.txt || goto :fail

echo [3/5] Running automated tests...
"%PY%" -m pytest -q || goto :fail

echo [4/5] Building executable with PyInstaller...
"%PY%" tools\write_version_info.py > build\version.tmp || goto :fail
"%PY%" -m PyInstaller --noconfirm --clean --distpath dist --workpath build\pyinstaller BusinessPOS.spec || goto :fail

echo [5/5] Validating output...
if not exist "dist\BusinessPOS\BusinessPOS.exe" (
    echo ERROR: dist\BusinessPOS\BusinessPOS.exe was not produced.
    goto :fail
)
start "" /wait "dist\BusinessPOS\BusinessPOS.exe" --self-test
if errorlevel 1 (
    echo ERROR: The packaged application self-test failed. See %TEMP%\BusinessPOS-selftest.log
    type "%TEMP%\BusinessPOS-selftest.log"
    goto :fail
)
type "%TEMP%\BusinessPOS-selftest.log"
echo.
echo SUCCESS: dist\BusinessPOS\BusinessPOS.exe
if /i not "%~1"=="nopause" if /i not "%BPOS_NOPAUSE%"=="1" pause
exit /b 0

:fail
echo.
echo BUILD FAILED.
if /i not "%~1"=="nopause" if /i not "%BPOS_NOPAUSE%"=="1" pause
exit /b 1
