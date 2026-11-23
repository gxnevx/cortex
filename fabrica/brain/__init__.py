"""Cerebro: escolhe assuntos e cortes.

    get_brain(cfg, force=None) -> Brain
    Brain.rank_trends(trends, cfg, limit=15) -> list[Trend]
    Brain.pick_clips(video, transcript, cfg, max_clips=None) -> list[ClipPlan]
    Brain.status() -> str

motor (cerebro.motor): auto | claude | ollama | heuristico
auto = Claude (se logado) -> Ollama (servidor + modelo) -> heuristico (sempre funciona).
"""
from __future__ import annotations

from .. import log
from .base import Brain, BrainUnavailable, clear_cache, extract_json, finalize_plans, finalize_trends
from .claude_cli import ClaudeBrain
from .heuristic import HeuristicBrain
from .ollama import OllamaBrain

logger = log.get(__name__)

__all__ = ["Brain", "BrainUnavailable", "ClaudeBrain", "OllamaBrain", "HeuristicBrain", "get_brain",
           "clear_cache", "extract_json", "finalize_plans", "finalize_trends", "normalize_motor"]

_ALIASES = {
    "auto": "auto", "automatico": "auto", "automático": "auto", "": "auto",
    "claude": "claude", "claude_code": "claude", "claude-code": "claude",
    "ollama": "ollama", "local": "ollama", "ia_local": "ollama",
    "heuristico": "heuristico", "heurístico": "heuristico", "heuristica": "heuristico", "heurística": "heuristico",
    "heuristic": "heuristico", "sem_ia": "heuristico", "nenhum": "heuristico", "none": "heuristico", "offline": "heuristico",
}


def normalize_motor(m) -> str:
    return _ALIASES.get(str(m or "auto").strip().lower(), "auto")


def get_brain(cfg, force: str | None = None, refresh: bool = False, tarefa: str | None = None) -> Brain:
    """Escolhe o motor. Nunca levanta excecao: no pior caso devolve o heuristico (com o motivo em status()).

    tarefa (modo economico, cerebro.estrategia = "economica"):
      "trends" -> so IA local (Ollama), gratis: ranquear assuntos e uma tarefa simples;
      "clips"  -> Claude (modelo leve, ex.: haiku) enquanto houver cota do dia; depois Ollama.
    """
    motor = normalize_motor(force or (cfg.get("cerebro.motor", "auto") if cfg is not None else "auto"))
    chain = {
        "auto": ["claude", "ollama"],
        "claude": ["claude"],          # escolhido explicitamente: se falhar, vai direto pro heuristico
        "ollama": ["ollama"],
        "heuristico": [],
    }[motor]
    economica = str(cfg.get("cerebro.estrategia", "economica") if cfg is not None else "economica") == "economica"
    if motor == "auto" and economica:
        from .. import uso_ia

        if tarefa == "trends" or not uso_ia.pode_claude(cfg, tarefa):
            chain = ["ollama"]
    notes: list[str] = []
    for m in chain:
        try:
            b: Brain = ClaudeBrain(cfg) if m == "claude" else OllamaBrain(cfg)
            if b.available(refresh=refresh):
                b.notes = notes
                return b
            notes.append(b.status())
        except Exception as e:  # checagem nunca derruba o pipeline
            logger.debug("checagem do motor %s falhou: %s", m, e)
            notes.append(f"{m}: erro na checagem ({e}).")
    h = HeuristicBrain(cfg)
    h.notes = notes
    return h
