@echo off
setlocal
chcp 65001 >nul
set "ROOT=%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "HF_HUB_DISABLE_SYMLINKS_WARNING=1"
set "HF_HUB_DISABLE_TELEMETRY=1"
title CORTEX - Central Operacional de Recortes, Tendencias e EXposicao
pushd "%ROOT%"
if not exist "%ROOT%.venv\Scripts\python.exe" (
  echo [!] Ambiente ainda nao instalado. Rodando instalar.bat...
  call "%ROOT%instalar.bat" --sem-atalho || (popd & exit /b 1)
)
"%ROOT%.venv\Scripts\python.exe" -m fabrica %*
set "RC=%ERRORLEVEL%"
popd
endlocal & exit /b %RC%
