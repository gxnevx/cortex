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
CAPTCHA_FILE = "publicacao_captcha.json"


def _state_dir() -> Path:
    d = Path(paths.STATE)
    d.mkdir(parents=True, exist_ok=True)
    return d


class LedgerError(RuntimeError):
    """O registro de posts existe mas esta ilegivel: publicar agora poderia repetir um post."""


def _load(name: str) -> dict:
    f = _state_dir() / name
    if not f.exists() and not f.with_suffix(".bak").exists():
        return {}
    for path in (f, f.with_suffix(".bak")):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return d
        except Exception:
            continue
    if name == CLICKS_FILE:
        raise LedgerError("o registro de posts (data/estado/publicacao_cliques.json) esta ilegivel; confira nas redes o "
                          "ultimo post e apague o arquivo para continuar")
    return {}


def _save(name: str, data: dict) -> None:
    """Grava no disco de verdade (fsync) e guarda a versao anterior: o PC pode cair no meio."""
    f = _state_dir() / name
    tmp = f.with_suffix(f".{os.getpid()}.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(data, indent=1, ensure_ascii=False))
        fh.flush()
        os.fsync(fh.fileno())
    for _ in range(10):
        try:
            if f.exists():
                try:
                    json.loads(f.read_text(encoding="utf-8"))
                    os.replace(f, f.with_suffix(".bak"))
                except ValueError:
                    pass
            os.replace(tmp, f)
            return
        except PermissionError:
            time.sleep(0.05)
    raise OSError(f"nao consegui gravar {f.name}")


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


def clear_click(clip_id: str, platform: str) -> None:
    """So quando a rede confirmou que o video NAO foi recebido (API oficial)."""
    data = _load(CLICKS_FILE)
    if data.pop(_key(clip_id, platform), None) is not None:
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
    old = data.get(platform) or {}
    if float(old.get("ate", 0)) > until:        # ja estava parado por mais tempo: vale a pausa maior
        until, motivo = float(old["ate"]), str(old.get("motivo") or motivo)
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


# ------------------------------------------------------ CAPTCHA (quem resolve e o dono)
def note_captcha(platform: str) -> None:
    data = _load(CAPTCHA_FILE)
    hist = data.setdefault("hist", {})
    hist[platform] = (hist.get(platform, []) + [time.time()])[-50:]
    _save(CAPTCHA_FILE, data)


def captchas_today(platform: str) -> int:
    hist = (_load(CAPTCHA_FILE).get("hist") or {}).get(platform, [])
    return sum(1 for t in hist if time.time() - float(t) < 86400)


def set_waiting(platform: str, msg: str | None) -> None:
    """O painel mostra este aviso enquanto o CORTEX espera o dono."""
    data = _load(CAPTCHA_FILE)
    w = data.setdefault("esperando", {})
    if msg:
        w[platform] = {"msg": msg, "ts": time.time()}
    else:
        w.pop(platform, None)
    _save(CAPTCHA_FILE, data)


def waiting() -> dict[str, str]:
    w = _load(CAPTCHA_FILE).get("esperando") or {}
    return {p: v["msg"] for p, v in w.items() if time.time() - float(v.get("ts", 0)) < 3 * 3600}


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
