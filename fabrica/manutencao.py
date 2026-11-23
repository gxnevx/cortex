"""Manutencao automatica: copia de seguranca do banco, limpeza, conserto e reinicio da madrugada.

- Todo dia: copia do banco (7 dias guardados), apaga prints, relatorios e amostras velhos.
- Ao ligar: confere o banco; se a queda do PC o corrompeu, volta a ultima copia boa.
- De madrugada: reinicia o automatico (memoria limpa e programa atualizado), se nada estiver rodando.
- 3 envios seguidos falhando numa rede: pausa 12 h e avisa (a pagina pode ter mudado), em vez de insistir.
- Downloads falhando em serie: avisa e, se o dono ligou, atualiza o yt-dlp (com volta se a versao nova nao funcionar).
"""
from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import andamento, db, log, paths

_log = log.get("manutencao")
STATE = paths.STATE / "manutencao.json"
BACKUP = paths.DATA / "backup"


def state() -> dict:
    return andamento.read_json(STATE) or {}


def _save(**kw: Any) -> None:
    andamento.write_json(STATE, {**state(), **kw})


# ------------------------------------------------------------------ banco
def backup(keep: int = 7) -> Path | None:
    """Copia consistente do banco (funciona com o programa usando)."""
    if not paths.DB_PATH.exists():
        return None
    BACKUP.mkdir(parents=True, exist_ok=True)
    dest = BACKUP / f"cortex_{date.today():%Y%m%d}.db"
    tmp = dest.with_suffix(".tmp")
    src = sqlite3.connect(str(paths.DB_PATH), timeout=30)
    try:
        out = sqlite3.connect(str(tmp))
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()
    tmp.replace(dest)
    for old in sorted(BACKUP.glob("cortex_*.db"))[:-keep]:
        old.unlink(missing_ok=True)
    return dest


def _healthy(p: Path) -> bool:
    try:
        c = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True, timeout=10)
        try:
            return c.execute("PRAGMA quick_check").fetchone()[0] == "ok" and \
                c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='posts'").fetchone()[0] == 1
        finally:
            c.close()
    except sqlite3.Error:
        return False


def ensure_db() -> str:
    """Chamar antes de usar o banco. Corrompido: guarda o estragado e volta a ultima copia boa."""
    p = paths.DB_PATH
    if not p.exists() or _healthy(p):
        return "ok"
    good = next((b for b in sorted(BACKUP.glob("cortex_*.db"), reverse=True) if _healthy(b)), None)
    if good is None:
        _log.error("banco com defeito e sem copia boa: nao mexi")
        return "sem copia"
    bad = p.with_name(f"{p.stem}_com_defeito_{datetime.now():%Y%m%d%H%M}{p.suffix}")
    shutil.move(str(p), str(bad))
    for ext in ("-wal", "-shm"):
        Path(str(p) + ext).unlink(missing_ok=True)
    shutil.copy2(good, p)
    _log.error("banco com defeito: voltei a copia de %s (o estragado ficou em %s)", good.stem[-8:], bad.name)
    return "restaurado"


# ------------------------------------------------------------------ limpeza
def _prune(folder: Path, days: float, pattern: str = "*") -> int:
    n = 0
    if folder.exists():
        for f in folder.glob(pattern):
            try:
                if f.is_file() and time.time() - f.stat().st_mtime > days * 86400:
                    f.unlink()
                    n += 1
            except OSError:
                continue
    return n


def daily(cfg: Any, force: bool = False) -> list[str]:
    """Uma vez por dia. Devolve o que precisa da atencao do dono."""
    msgs: list[str] = []
    hoje = date.today().isoformat()
    m = check_downloads(cfg)
    if m and state().get("aviso_download") != hoje:
        _save(aviso_download=hoje)
        msgs.append(m)
    if not force and state().get("dia") == hoje:
        return msgs
    try:
        backup()
    except Exception as e:
        _log.warning("copia do banco: %s", e)
        msgs.append("não consegui fazer a cópia de segurança do banco")
    n = _prune(paths.LOGS / "screenshots", 10) + _prune(paths.LOGS, 21, "*.json") + _prune(paths.REPORTS, 45, "rodada_*")
    am = paths.WORK / "amostras"
    if am.exists():
        n += sum(_prune(d, 7) for d in [am, *[x for x in am.rglob("*") if x.is_dir()]])
    _save(dia=hoje, limpos=n)
    _log.info("manutencao do dia: copia do banco feita, %d arquivo(s) velho(s) apagado(s)", n)
    return msgs


# ------------------------------------------------------------------ protecoes
def breaker(platform: str, cfg: Any) -> str | None:
    """3 envios reais seguidos falhando (nao por login, captcha ou limite): para de insistir por 12 h."""
    rows = db.conn().execute("SELECT ok, error, ts FROM posts WHERE platform=? AND dry_run=0 ORDER BY ts DESC LIMIT 3", (platform,)).fetchall()
    if len(rows) < 3 or any(r["ok"] for r in rows) or time.time() - rows[0]["ts"] > 3600:
        return None
    if any(str(r["error"] or "").startswith(("ACAO_NECESSARIA", "LIMITE_DIARIO")) for r in rows):
        return None
    from .publish import guard

    if guard.paused_until(platform):
        return None
    msg = "3 envios falharam seguidos; a página da rede pode ter mudado. Veja os prints em logs/screenshots"
    guard.pause_platform(platform, msg, cfg, hours=12)
    return f"{platform}: {msg}"


def check_downloads(cfg: Any, min_fail: int = 5) -> str | None:
    """Os ultimos videos falharam todos no download? Normalmente e o YouTube que mudou algo."""
    rows = db.conn().execute("SELECT status, error FROM videos WHERE status IN ('processado','falhou','ignorado') "
                             "ORDER BY rowid DESC LIMIT ?", (min_fail,)).fetchall()
    bad = [r for r in rows if r["status"] != "processado" and any(
        k in str(r["error"] or "").lower() for k in ("baixar", "download", "format is not available", "nao consegui ler", "http error"))]
    if len(rows) < min_fail or len(bad) < min_fail:
        return None
    if cfg.get("manutencao.atualizar_ytdlp", False):
        if andamento.read():
            return None         # rodada em uso: troca o baixador quando ela terminar
        if time.time() >= float(state().get("ytdlp_depois") or 0):
            return update_ytdlp()
    return "os últimos vídeos não baixaram: o YouTube pode ter mudado e o baixador (yt-dlp) precisa de atualização"


def _pip(*args: str) -> bool:
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q", *args], capture_output=True, text=True,
                       timeout=900, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        _log.warning("pip: %s", (r.stderr or "")[-300:])
    return r.returncode == 0


def _ytdlp_version() -> str:
    """Versao instalada, lida num processo novo (vazio = nao abre)."""
    r = subprocess.run([sys.executable, "-c", "import yt_dlp, yt_dlp.version as v; yt_dlp.YoutubeDL({'quiet': True}); print(v.__version__)"],
                       capture_output=True, text=True, timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.stdout.strip().splitlines()[-1] if r.returncode == 0 and r.stdout.strip() else ""


def update_ytdlp() -> str | None:
    """Atualiza o yt-dlp com as pecas que ele exige na versao exata (por isso o [default]) e volta se a nova nao abrir."""
    old = _ytdlp_version()
    try:
        ok = _pip("-U", "yt-dlp[default]")
    except subprocess.TimeoutExpired:
        ok = False
    new = _ytdlp_version()
    if not new or (not ok and new != old):
        _save(ytdlp_depois=time.time() + 2 * 86400)
        if old and _pip(f"yt-dlp[default]=={old}") and _ytdlp_version() == old:
            return "a atualização do baixador deu errado e voltei para a versão anterior"
        return "a atualização do baixador deu errado e não consegui voltar a versão anterior"
    if not ok:      # sem internet, por exemplo: nada mudou, tenta de novo mais tarde
        _save(ytdlp_depois=time.time() + 6 * 3600)
        return None
    if new == old:
        _save(ytdlp_depois=time.time() + 12 * 3600)
        return "os vídeos não estão baixando e o baixador (yt-dlp) já está na última versão; tento de novo em 12 h"
    _save(ytdlp_depois=time.time() + 2 * 86400, reiniciar_ts=time.time())      # so vale depois de reabrir o programa
    _log.info("yt-dlp atualizado: %s -> %s", old, new)
    return None


def should_restart(started: float, now: datetime | None = None) -> bool:
    """Reinicio da madrugada (ligado ha mais de 18 h, entre 3h e 6h) ou logo apos trocar o baixador."""
    now = now or datetime.now()
    if started < float(state().get("reiniciar_ts") or 0) <= time.time():
        return True
    return time.time() - started > 18 * 3600 and 3 <= now.hour < 6
