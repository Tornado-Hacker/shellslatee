@echo off
setlocal
cd /d "%~dp0"

set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat"
if exist "%VCVARS%" (
  call "%VCVARS%" x64 >nul
) else (
  echo [warn] vcvarsall.bat not found; assuming the environment is already configured.
)

set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"

if /I "%~1"=="check" (
  cd src-tauri
  cargo check %2 %3 %4 %5
  exit /b %ERRORLEVEL%
)

if /I "%~1"=="build" (
  npx tauri build %2 %3 %4 %5 -- %6
  exit /b %ERRORLEVEL%
)

if /I "%~1"=="dev" (
  npx tauri dev
  exit /b %ERRORLEVEL%
)

echo usage: build-dev.bat [check^|build^|dev] [extra args...]
exit /b 1
