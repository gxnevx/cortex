"""Trabalho em segundo plano: fechar a janela do CORTEX nao para nada.

- O automatico e os pedidos de corte rodam num processo sem janela; o terminal so acompanha.
- Um "vigia" minimo do Windows (Agendador de Tarefas, menos de 1 s a cada 10 min) religa o automatico se o PC
  reiniciar ou se ele cair, desde que o dono tenha deixado LIGADO.
- Pedidos de corte entram numa fila: um por vez, nunca por cima do que ja esta rodando.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Any

from . import andamento, log, paths

_log = log.get("fundo")
WANTED = paths.STATE / "automatico_ligado.json"   # o dono quer o automatico ligado?
REQUESTS = paths.STATE / "pedidos.json"
WORKER = paths.STATE / "pedidos_lock.json"

_NO_WINDOW, _NEW_GROUP, _BREAKAWAY = 0x08000000, 0x00000200, 0x01000000


def spawn(args: list[str]) -> int:
    """Roda `cortex <args>` sem janela e independente desta. Devolve o PID."""
    exe = paths.ROOT / ".venv" / "Scripts" / "python.exe"
    cmd = [str(exe) if exe.exists() else sys.executable, "-m", "fabrica", *args]
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
           "HF_HUB_DISABLE_TELEMETRY": "1", "CORTEX_FUNDO": "1"}
    paths.LOGS.mkdir(parents=True, exist_ok=True)
    out = open(paths.LOGS / f"segundo_plano_{args[0]}.log", "w", encoding="utf-8")
    kw: dict[str, Any] = dict(cwd=str(paths.ROOT), env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=out, close_fds=True)
    try:
        p = subprocess.Popen(cmd, creationflags=_NO_WINDOW | _NEW_GROUP | _BREAKAWAY, **kw)
    except OSError:  # alguns terminais nao deixam sair do "job" deles
        p = subprocess.Popen(cmd, creationflags=_NO_WINDOW | _NEW_GROUP, **kw)
    finally:
        out.close()
    _log.info("segundo plano: %s (PID %s)", " ".join(args), p.pid)
    return p.pid


# ------------------------------------------------------------------ automatico
def wanted() -> bool:
    return bool((andamento.read_json(WANTED) or {}).get("ligado"))


def set_wanted(on: bool) -> None:
    andamento.write_json(WANTED, {"ligado": bool(on), "ts": time.time()})


def start_autopilot(wait_s: float = 25) -> bool:
    """Liga o automatico em segundo plano (se ja nao estiver) e espera ele dar sinal de vida."""
    from . import autopilot

    set_wanted(True)
    if autopilot.running():
        return True
    spawn(["autopiloto", "--fundo"])
    end = time.time() + wait_s
    while time.time() < end:
        if autopilot.running():
            return True
        time.sleep(0.5)
    return False


def ensure() -> bool:
    """Chamado pelo vigia do Windows: religa o automatico se o dono deixou ligado e ele nao esta rodando."""
    from . import autopilot

    if not wanted() or autopilot.running():
        return False
    _log.warning("vigia: o automatico estava parado; religando")
    spawn(["autopiloto", "--fundo"])
    return True


# --------------------------------------------------------------------- pedidos
def requests() -> list[dict]:
    d = andamento.read_json(REQUESTS)
    return d if isinstance(d, list) else []


def _save(reqs: list[dict]) -> None:
    andamento.write_json(REQUESTS, reqs)


def add_request(req: dict) -> int:
    """Poe um pedido de corte na fila e garante que alguem vai atender. Devolve a posicao."""
    reqs = requests() + [{**req, "ts": time.time()}]
    _save(reqs)
    if not andamento.alive(andamento.read_json(WORKER)):
        spawn(["pedidos"])
    return len(reqs)


def clear_requests() -> int:
    n = len(requests())
    _save([])
    return n


def serve_requests(cfg_loader, runner) -> int:
    """Processo de fundo: atende os pedidos um a um, esperando a vez se ja houver uma rodada."""
    from .publish import guard

    lock = guard.PublishLock()          # so um atendente, mesmo que dois comecem juntos
    lock.path = WORKER.with_suffix(".lock")
    if not lock.acquire():
        return 0
    andamento.write_json(WORKER, andamento.me())
    try:
        while True:
            reqs = requests()
            if not reqs:
                return 0
            while andamento.read():
                time.sleep(10)
            reqs = requests()
            if not reqs:
                return 0
            req, rest = reqs[0], reqs[1:]
            _save(rest)
            rc = runner(cfg_loader(), req)
            if rc == 2:  # outra rodada entrou na frente: devolve o pedido e tenta depois
                _save([req] + requests())
                time.sleep(30)
    finally:
        lock.release()
        try:
            WORKER.unlink()
        except OSError:
            pass
