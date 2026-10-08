@echo off
rem ==========================================================================
rem  BusinessPOS - code-sign one file with SSL.com eSigner (CodeSignTool).
rem    build\sign.bat <file>
rem  Does nothing (exit 0) unless signing is configured, so unsigned builds
rem  work exactly as before. Configure by setting:
rem    BPOS_CODESIGNTOOL_DIR  folder containing CodeSignTool.bat
rem    ES_USERNAME, ES_PASSWORD, ES_TOTP_SECRET   eSigner account
rem    ES_CREDENTIAL_ID       optional; needed only with several certificates
rem  The build workflow sets these for releases when the GitHub secrets exist.
rem  See docs\CODE-SIGNING.md.
rem ==========================================================================
setlocal
if "%~1"=="" (
    echo sign.bat: no file given
    exit /b 1
)
if not defined BPOS_CODESIGNTOOL_DIR exit /b 0

set "TARGET=%~f1"
set "OUTDIR=%~dp1signed-%RANDOM%"
set "CRED="
if defined ES_CREDENTIAL_ID set "CRED=-credential_id=%ES_CREDENTIAL_ID%"

echo Signing %~nx1 ...
mkdir "%OUTDIR%" || exit /b 1
pushd "%BPOS_CODESIGNTOOL_DIR%" || exit /b 1
call CodeSignTool.bat sign -username="%ES_USERNAME%" -password="%ES_PASSWORD%" %CRED% -totp_secret="%ES_TOTP_SECRET%" -input_file_path="%TARGET%" -output_dir_path="%OUTDIR%"
set "RC=%ERRORLEVEL%"
popd
if not "%RC%"=="0" goto :fail
if not exist "%OUTDIR%\%~nx1" goto :fail
move /y "%OUTDIR%\%~nx1" "%TARGET%" >nul || goto :fail
rmdir /s /q "%OUTDIR%" 2>nul
exit /b 0

:fail
echo ERROR: signing %~nx1 failed.
rmdir /s /q "%OUTDIR%" 2>nul
exit /b 1
