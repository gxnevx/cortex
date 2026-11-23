@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
title CORTEX - Instalacao
echo.
echo   ==============================================
echo     CORTEX  -  instalacao / reparo
echo   ==============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [X] Python nao encontrado. Instale o Python 3.11+ em https://www.python.org/downloads/
  echo     e marque "Add python.exe to PATH". Depois rode este arquivo de novo.
  pause
  exit /b 1
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [!] ffmpeg nao encontrado. Instalando pelo winget...
  winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
  echo     Feche e abra o terminal depois da instalacao do ffmpeg.
)

where node >nul 2>nul
if errorlevel 1 (
  echo [!] Node.js nao encontrado - o YouTube pode recusar downloads sem ele.
  echo     Instale com:  winget install OpenJS.NodeJS.LTS
)

if not exist ".venv\Scripts\python.exe" (
  echo [*] Criando ambiente Python em .venv ...
  python -m venv .venv
  if errorlevel 1 (
    echo [X] Falha ao criar o ambiente Python.
    pause
    exit /b 1
  )
)

echo [*] Instalando/atualizando dependencias (pode levar alguns minutos)...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
".venv\Scripts\python.exe" -m pip install -r requirements.txt -q
if errorlevel 1 (
  echo [X] Falha ao instalar dependencias. Veja a mensagem acima.
  pause
  exit /b 1
)

echo [*] Preparando pastas, fontes e fundos procedurais...
set "PYTHONUTF8=1"
".venv\Scripts\python.exe" -m fabrica fundos gerar

echo.
echo [OK] Tudo pronto! Para abrir: de dois cliques em cortex.bat
echo.

if /i "%~1"=="--sem-atalho" goto :fim
choice /C SN /M "Criar atalho 'CORTEX' na Area de Trabalho"
if !errorlevel! equ 1 (
  powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\CORTEX.lnk'); $s.TargetPath='%~dp0cortex.bat'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%SystemRoot%\System32\imageres.dll,18'; $s.Save()"
  echo [OK] Atalho criado.
)
:fim
endlocal
exit /b 0
