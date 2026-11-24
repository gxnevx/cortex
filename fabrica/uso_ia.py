"""Contador de uso de IA por dia (Claude e Ollama) e teto diario do Claude.

O Claude roda pela assinatura do dono (Claude Code): cada chamada consome a cota dele.
No modo economico, o CORTEX usa o Ollama local (gratis) sempre que da, e o Claude so para
escolher os cortes, ate um teto diario (cerebro.claude_max_chamadas_dia).
"""
from __future__ import annotations

import json
import threading
from datetime import date

from . import log, paths

_log = log.get("uso_ia")
_FILE = paths.STATE / "uso_ia.json"
_lock = threading.Lock()


def _load() -> dict:
    try:
        d = json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:
        d = {}
    today = date.today().isoformat()
    if d.get("dia") != today:  # virou o dia: zera o contador do dia (mantem o total)
        d = {"dia": today, "hoje": {}, "total": d.get("total", {})}
    return d


def registrar(motor: str, tarefa: str = "", segundos: float = 0.0) -> None:
    """Conta uma chamada de IA (motor = 'claude' | 'ollama')."""
    with _lock:
        d = _load()
        h = d["hoje"].setdefault(motor, {"chamadas": 0, "segundos": 0.0, "tarefas": {}})
        h["chamadas"] += 1
        h["segundos"] = round(h["segundos"] + float(segundos or 0), 1)
        if tarefa:
            h["tarefas"][tarefa] = h["tarefas"].get(tarefa, 0) + 1
        d["total"][motor] = d["total"].get(motor, 0) + 1
        try:
            paths.STATE.mkdir(parents=True, exist_ok=True)
            _FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError as e:
            _log.debug("uso_ia: %s", e)


def hoje(motor: str) -> int:
    return int(_load()["hoje"].get(motor, {}).get("chamadas", 0))


def teto_claude(cfg) -> int:
    return int(cfg.get("cerebro.claude_max_chamadas_dia", 25)) if cfg is not None else 25


RESERVA = {"clips": 14, "bordas": 12, "fino": 9, "curadoria": 8, "revisao": 1, "analise": 0}     # chamadas guardadas para o que vem depois


def pode_claude(cfg, tarefa: str | None = None) -> bool:
    """Ainda ha cota do Claude hoje para esta tarefa? Escolher cortes para antes, para sobrar para julgar e analisar."""
    return hoje("claude") < teto_claude(cfg) - (RESERVA.get(tarefa or "", 0) if teto_claude(cfg) >= 12 else 0)


def resumo(cfg=None) -> str:
    d = _load()["hoje"]
    c = d.get("claude", {}).get("chamadas", 0)
    o = d.get("ollama", {}).get("chamadas", 0)
    teto = teto_claude(cfg)
    return f"Claude {c}/{teto} | Ollama {o}"
