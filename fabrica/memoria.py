"""Controle de memoria: uma coisa pesada por vez, para o PC nao travar.

Etapas pesadas: "ia" (modelo local do Ollama, ~3 GB), "whisper" (~1,5 GB) e "render" (ffmpeg, ~1 GB).
Antes de cada uma, descarrega as outras e espera haver memoria. O que derruba programas no Windows e a
memoria RESERVADA (RAM + arquivo de paginacao) acabar, entao e ela que manda.
"""
from __future__ import annotations

import ctypes
import gc
import sys
import time
from typing import Any

from . import log

_log = log.get("memoria")

# etapa: (reserva livre minima em GB, RAM disponivel desejada em GB)
NEEDS = {"ia": (3.6, 1.0), "ia_carregada": (0.6, 0.2), "whisper": (2.2, 1.2), "render": (1.6, 0.9)}


_last_low = [0.0]


class LowMemory(RuntimeError):
    """Nao ha memoria para a etapa, mesmo depois de esperar."""


class _Mem(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
        (n, ctypes.c_ulonglong) for n in ("total", "avail", "ctotal", "cfree", "vtotal", "vfree", "ext")]


def status() -> dict:
    """{"ram_livre", "ram_total", "reserva_livre", "reserva_total"} em GB."""
    m = _Mem()
    m.cb = ctypes.sizeof(m)
    try:
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    except Exception:
        return {"ram_livre": 99.0, "ram_total": 99.0, "reserva_livre": 99.0, "reserva_total": 99.0}
    g = 2 ** 30
    return {"ram_livre": m.avail / g, "ram_total": m.total / g, "reserva_livre": m.cfree / g, "reserva_total": m.ctotal / g}


def _get(cfg: Any, key: str, default: Any) -> Any:
    try:
        return cfg.get(key, default) if cfg is not None else default
    except Exception:
        return default


def _url(cfg: Any) -> str:
    return str(_get(cfg, "cerebro.ollama_url", "http://127.0.0.1:11434")).rstrip("/")


def ollama_loaded(cfg: Any = None) -> list[str]:
    import requests

    try:
        return [m.get("name", "") for m in requests.get(_url(cfg) + "/api/ps", timeout=3).json().get("models", [])]
    except Exception:
        return []


def unload_ollama(cfg: Any = None) -> bool:
    """Tira o modelo do CORTEX da memoria (os outros modelos do dono ficam)."""
    import requests

    mine = str(_get(cfg, "cerebro.ollama_modelo", "qwen3:4b-instruct")).strip()
    hit = [n for n in ollama_loaded(cfg) if n.split(":latest")[0] == mine.split(":latest")[0]]
    for name in hit:
        try:
            requests.post(_url(cfg) + "/api/generate", json={"model": name, "keep_alive": 0}, timeout=30)
        except Exception as e:
            _log.debug("descarregar ollama: %s", e)
    for _ in range(20):  # o processo demora alguns segundos para devolver a memoria
        if not hit or not set(hit) & set(ollama_loaded(cfg)):
            break
        time.sleep(0.5)
    return bool(hit)


def unload_whisper() -> None:
    tr = sys.modules.get("fabrica.transcribe")
    if tr is not None:
        try:
            tr.unload_models()
        except Exception as e:
            _log.debug("descarregar whisper: %s", e)
    gc.collect()


def _fits(need: tuple[float, float], soft: bool) -> bool:
    s = status()
    return s["reserva_livre"] >= need[0] and (soft or s["ram_livre"] >= need[1])


def prepare(step: str, cfg: Any = None) -> None:
    """Chamar logo antes de uma etapa pesada. Levanta LowMemory se nao couber depois da espera."""
    if step == "ia":
        mine = str(_get(cfg, "cerebro.ollama_modelo", "qwen3:4b-instruct")).split(":latest")[0]
        if any(n.split(":latest")[0] == mine for n in ollama_loaded(cfg)):
            step = "ia_carregada"
    if step == "ia":
        unload_whisper()
    elif step in ("whisper", "render"):
        unload_ollama(cfg)
    need = NEEDS[step]
    if _fits(need, False):
        return
    if step == "render":
        unload_whisper()
    wait = float(_get(cfg, "autopiloto.espera_memoria_min", 15)) * 60
    if time.time() - _last_low[0] < 1800:   # acabou de faltar memoria: nao espera tudo de novo
        wait = min(wait, 60.0)
    soft_after = min(wait / 3, 60.0)        # RAM e desejo, nao exigencia: espera no maximo 1 min por ela
    t0, told = time.time(), 0.0
    while True:
        waited = time.time() - t0
        if _fits(need, soft=waited > soft_after):
            if waited > 20:
                _log.info("memoria liberada depois de %d s", int(waited))
            return
        s = status()
        if waited >= wait:
            _last_low[0] = time.time()
            raise LowMemory(f"pouca memória no PC ({s['reserva_livre']:.1f} GB de reserva livre, preciso de "
                            f"{need[0]:.1f}). Feche programas pesados (Docker, navegadores) e eu tento de novo.")
        if time.time() - told > 120:
            told = time.time()
            _log.warning("esperando memoria para '%s': reserva livre %.1f GB, RAM livre %.1f GB (feche programas pesados)",
                         step, s["reserva_livre"], s["ram_livre"])
        time.sleep(5)
