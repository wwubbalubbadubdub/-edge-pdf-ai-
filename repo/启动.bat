@echo off
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"
if "%~1"=="" (
  echo 用法：把一个 PDF 文件拖到这个 bat（或桌面快捷方式）上。
  echo.
  pause
  exit /b 1
)
start "" "%ROOT%python\pythonw.exe" "%ROOT%app\launcher.pyw" "%~1"