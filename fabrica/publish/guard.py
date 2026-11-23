"""Travas de seguranca da publicacao (CORTEX).

1. Registro de cliques em Publicar (`data/estado/publicacao_cliques.json`): gravado ANTES do clique
   final. Se o programa cair ou a confirmacao nao aparecer, o mesmo corte nunca e reenviado para a
   mesma rede (um post duplicado e pior que um post a menos).
2. Pausa depois de captcha/verificacao/limite (`data/estado/publicacao_pausas.json`): a rede fica
   parada por `publicacao.pausa_apos_bloqueio_h` horas (padrao 24) ou ate o dono refazer o login
   (`cortex login <rede>` limpa a pausa). Nunca tentamos de novo em loop.
3. Uma publicacao por vez no PC (`data/estado/publicando.lock`): dois processos nunca dirigem o
   navegador ao mesmo tempo.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .. import paths
from ..log import get as get_log

log = get_log(__name__)

CLICKS_FILE = "publicacao_cliques.json"
PAUSES_FILE = "publicacao_pausas.json"
LOCK_FILE = "publicando.lock"


def _state_dir() -> Path:
    d = Path(paths.STATE)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load(name: str) -> dict:
    try:
        return json.loads((_state_dir() / name).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(name: str, data: dict) -> None:
    f = _state_dir() / name
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, f)


# ------------------------------------------------------- cliques em Publicar
def _key(clip_id: str, platform: str) -> str:
    return f"{platform}|{clip_id}"


def mark_publish_click(clip_id: str, platform: str, extra: dict | None = None) -> None:
    """Grava que vamos clicar em Publicar AGORA (chamar imediatamente antes do clique)."""
    data = _load(CLICKS_FILE)
    cutoff = time.time() - 60 * 86400
    data = {k: v for k, v in data.items() if float(v.get("ts", 0)) >= cutoff}
    data[_key(clip_id, platform)] = {"ts": time.time(), "estado": "clicado", **(extra or {})}
    _save(CLICKS_FILE, data)


def mark_publish_result(clip_id: str, platform: str, estado: str, url: str | None = None) -> None:
    """estado: confirmado | incerto."""
    data = _load(CLICKS_FILE)
    k = _key(clip_id, platform)
    entry = data.get(k) or {"ts": time.time()}
    entry.update({"estado": estado, "url": url, "fim": time.time()})
    data[k] = entry
    _save(CLICKS_FILE, data)


def publish_clicked(clip_id: str, platform: str) -> dict | None:
    """Registro do clique em Publicar desse corte nessa rede (None = nunca clicamos)."""
    return _load(CLICKS_FILE).get(_key(clip_id, platform))


# ------------------------------------------------------------- pausas
def pause_platform(platform: str, motivo: str, cfg: Any = None, hours: float | None = None) -> float:
    if hours is None:
        try:
            hours = float(cfg.get("publicacao.pausa_apos_bloqueio_h", 24)) if cfg is not None else 24.0
        except Exception:
            hours = 24.0
    until = time.time() + max(0.0, hours) * 3600
    data = _load(PAUSES_FILE)
    data[platform] = {"ate": until, "motivo": motivo[:300], "desde": time.time()}
    _save(PAUSES_FILE, data)
    log.warning("%s pausado ate %s: %s", platform, time.strftime("%d/%m %H:%M", time.localtime(until)), motivo)
    return until


def paused_until(platform: str) -> tuple[float, str] | None:
    e = _load(PAUSES_FILE).get(platform)
    if not e:
        return None
    if float(e.get("ate", 0)) <= time.time():
        return None
    return float(e["ate"]), str(e.get("motivo", ""))


def clear_pause(platform: str) -> bool:
    data = _load(PAUSES_FILE)
    if platform in data:
        data.pop(platform)
        _save(PAUSES_FILE, data)
        return True
    return False


# ---------------------------------------------------------------- trava
class PublishLock:
    """Trava entre processos (Windows: msvcrt.locking; outros: fcntl). Nao bloqueia: acquire() -> bool."""

    def __init__(self) -> None:
        self.path = _state_dir() / LOCK_FILE
        self.fh = None

    def acquire(self) -> bool:
        try:
            self.fh = open(self.path, "a+b")
            self.fh.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            if self.fh:
                self.fh.close()
            self.fh = None
            return False

    def release(self) -> None:
        if not self.fh:
            return
        try:
            self.fh.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            self.fh.close()
        except OSError:
            pass
        self.fh = None

    def __enter__(self) -> "PublishLock":
        return self

    def __exit__(self, *exc) -> None:
        self.release()
