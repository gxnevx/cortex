"""Agendamento automatico via Agendador de Tarefas do Windows (sem servico extra rodando)."""
from __future__ import annotations

import json
import re

from . import log, paths
from .util import run_cmd

_log = log.get("scheduler")

TASK_FOLDER = "\\CORTEX\\"
TASK_PREFIX = "Rodada_"
AUTOSTART_NAME = "PilotoAutomatico"


def _ps(script: str, timeout: float = 60):
    return run_cmd(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
                   timeout=timeout)


def _valid_time(t: str) -> bool:
    return bool(re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", t.strip()))


def install(horarios: list[str]) -> list[str]:
    """Cria uma tarefa diaria para cada horario. Roda so com o usuario logado (o navegador precisa aparecer).

    - StartWhenAvailable: se o PC estava desligado no horario, roda assim que ligar.
    - WakeToRun: acorda o PC da suspensao para rodar.
    - Limite de 3 h por rodada; nao inicia uma nova se a anterior ainda estiver rodando.
    """
    horarios = [h.strip() for h in horarios if _valid_time(h)]
    if not horarios:
        raise ValueError("Nenhum horario valido (use HH:MM, ex.: 09:00).")
    remove_all(keep_autostart=True)
    bat = paths.ROOT / "cortex.bat"
    created = []
    for h in horarios:
        name = TASK_PREFIX + h.replace(":", "h")
        script = f"""
$ErrorActionPreference = 'Stop'
$a = New-ScheduledTaskAction -Execute '{bat}' -Argument 'rodar --agendado' -WorkingDirectory '{paths.ROOT}'
$t = New-ScheduledTaskTrigger -Daily -At '{h}'
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 3) -MultipleInstances IgnoreNew
$p = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskPath '{TASK_FOLDER}' -TaskName '{name}' -Action $a -Trigger $t -Settings $s -Principal $p -Description 'CORTEX - rodada automatica' -Force | Out-Null
"""
        r = _ps(script)
        if r.returncode != 0:
            raise RuntimeError(f"Falha ao criar tarefa {h}: {r.stderr.strip()[-400:]}")
        created.append(h)
        _log.info("Tarefa agendada: %s", h)
    return created


def install_autostart() -> None:
    """Vigia minimo: ao entrar no Windows e a cada 10 min confere (em menos de 1 s, sem janela) se o automatico
    que voce deixou ligado esta rodando; se caiu, liga de novo. Desligado por voce = ele nao faz nada."""
    exe = paths.ROOT / ".venv" / "Scripts" / "pythonw.exe"
    script = f"""
$ErrorActionPreference = 'Stop'
$a = New-ScheduledTaskAction -Execute '{exe}' -Argument '-m fabrica vigia' -WorkingDirectory '{paths.ROOT}'
$t1 = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\\$env:USERNAME"
$t1.Delay = 'PT2M'
$t2 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Minutes 10)
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$p = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskPath '{TASK_FOLDER}' -TaskName '{AUTOSTART_NAME}' -Action $a -Trigger @($t1,$t2) -Settings $s -Principal $p -Description 'CORTEX - religa o automatico se ele cair' -Force | Out-Null
"""
    r = _ps(script)
    if r.returncode != 0:
        raise RuntimeError(f"Falha ao ligar o inicio automatico: {r.stderr.strip()[-400:]}")
    _log.info("Vigia do automatico ligado")


def remove_autostart() -> bool:
    r = _ps(f"Unregister-ScheduledTask -TaskPath '{TASK_FOLDER}' -TaskName '{AUTOSTART_NAME}' -Confirm:$false")
    return r.returncode == 0


def autostart_enabled() -> bool:
    r = _ps(f"if (Get-ScheduledTask -TaskPath '{TASK_FOLDER}' -TaskName '{AUTOSTART_NAME}' -ErrorAction SilentlyContinue) {{ 'sim' }}")
    return "sim" in (r.stdout or "")


def remove_all(keep_autostart: bool = False) -> int:
    keep = f" | Where-Object {{ $_.TaskName -ne '{AUTOSTART_NAME}' }}" if keep_autostart else ""
    r = _ps(f"""
$ts = @(Get-ScheduledTask -TaskPath '{TASK_FOLDER}' -ErrorAction SilentlyContinue{keep})
if ($ts.Count -gt 0) {{ $ts | Unregister-ScheduledTask -Confirm:$false; $ts.Count }} else {{ 0 }}
""")
    try:
        return int((r.stdout or "0").strip().splitlines()[-1])
    except Exception:
        return 0


def status() -> list[dict]:
    r = _ps(f"""
$ts = Get-ScheduledTask -TaskPath '{TASK_FOLDER}' -ErrorAction SilentlyContinue
$out = @()
foreach ($t in $ts) {{
  $i = $t | Get-ScheduledTaskInfo
  $out += [pscustomobject]@{{ nome=$t.TaskName; estado="$($t.State)"; proxima="$($i.NextRunTime)"; ultima="$($i.LastRunTime)"; resultado=$i.LastTaskResult }}
}}
$out | ConvertTo-Json -Compress
""")
    txt = (r.stdout or "").strip()
    if not txt:
        return []
    try:
        data = json.loads(txt)
        return data if isinstance(data, list) else [data]
    except Exception:
        return []


def run_now() -> bool:
    """Dispara a primeira tarefa agendada imediatamente (teste)."""
    tasks = [t for t in status() if str(t.get("nome", "")).startswith(TASK_PREFIX)]
    if not tasks:
        return False
    r = _ps(f"Start-ScheduledTask -TaskPath '{TASK_FOLDER}' -TaskName '{tasks[0]['nome']}'")
    return r.returncode == 0
