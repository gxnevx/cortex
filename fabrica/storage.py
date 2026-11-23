"""Controle de espaco em disco: o PC tem pouco espaco livre, entao a fabrica se limpa sozinha."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from . import db, log, paths
from .config import Config
from .util import dir_size, disk_free_gb, fmt_bytes

_log = log.get("storage")


class DiskFullError(RuntimeError):
    pass


def free_gb() -> float:
    return disk_free_gb(paths.ROOT)


def check_free_space(cfg: Config, need_gb: float = 0.0) -> None:
    """Levanta DiskFullError se o disco estiver abaixo do minimo configurado."""
    minimo = float(cfg.get("armazenamento.espaco_minimo_livre_gb", 2))
    livre = free_gb()
    if livre - need_gb < minimo:
        raise DiskFullError(
            f"Pouco espaco em disco: {livre:.1f} GB livres (minimo configurado: {minimo} GB). "
            "Libere espaco no C: ou rode 'fabrica limpar'."
        )


def _rm(p: Path) -> int:
    size = dir_size(p) if p.is_dir() else (p.stat().st_size if p.exists() else 0)
    try:
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()
    except OSError as e:
        _log.warning("Nao consegui apagar %s: %s", p, e)
        return 0
    return size


def cleanup(cfg: Config, aggressive: bool = False) -> dict:
    """Apaga temporarios, brutos antigos e renders velhos ja publicados/rejeitados.

    Cortes aguardando revisao so sao apagados quando passam do prazo (viram 'expirado').
    """
    freed = 0
    now = time.time()
    keep_days = float(cfg.get("armazenamento.manter_renders_dias", 3))

    # 0) arquiva os publicados no OneDrive (se ativo) antes de apagar qualquer coisa
    try:
        archive_to_onedrive(cfg)
    except Exception as e:  # pragma: no cover
        _log.warning("Arquivo no OneDrive falhou: %s", e)

    # 1) temporarios e brutos
    for d in (paths.TMP, paths.DOWNLOADS):
        if d.exists():
            for child in d.iterdir():
                age_h = (now - child.stat().st_mtime) / 3600
                if aggressive or age_h > 6:
                    freed += _rm(child)
    execs = paths.WORK / "execucoes"
    if execs.exists():
        for child in execs.iterdir():
            age_h = (now - child.stat().st_mtime) / 3600
            if aggressive or age_h > 12:
                freed += _rm(child)

    # 2) renders
    status_by_path: dict[str, str] = {}
    for row in db.clip_rows(limit=5000):
        if row["render_path"]:
            status_by_path[str(Path(row["render_path"]).resolve()).lower()] = row["status"]
            try:  # versoes por rede seguem o status do corte
                import json as _json

                for v in ((_json.loads(row["rendered"] or "{}") or {}).get("variants") or {}).values():
                    if v:
                        status_by_path[str(Path(v).resolve()).lower()] = row["status"]
            except Exception:
                pass
            if row["status"] == "renderizado" and (now - (row["created"] or now)) / 86400 > keep_days * 2:
                db.set_clip_status(row["id"], "expirado")
                status_by_path[str(Path(row["render_path"]).resolve()).lower()] = "expirado"
    if paths.RENDERS.exists():
        for f in paths.RENDERS.iterdir():
            if not f.is_file():
                continue
            age_d = (now - f.stat().st_mtime) / 86400
            key = str(f.with_suffix(".mp4").resolve()).lower()
            st = status_by_path.get(key, "orfao")
            if st in ("publicado", "rejeitado", "expirado", "falhou", "orfao") and (aggressive or age_d > keep_days):
                freed += _rm(f)

    # 3) limite total da pasta work
    limit = float(cfg.get("armazenamento.limite_gb", 4)) * 1024**3
    total = dir_size(paths.WORK)
    if total > limit and paths.RENDERS.exists():
        files = sorted([f for f in paths.RENDERS.iterdir() if f.is_file()], key=lambda f: f.stat().st_mtime)
        for f in files:
            if total <= limit:
                break
            key = str(f.with_suffix(".mp4").resolve()).lower()
            if status_by_path.get(key) in ("renderizado", "aprovado") and not aggressive:
                continue  # nao apaga o que esta na fila ou aguardando revisao
            if status_by_path.get(key, "orfao") == "orfao" and now - f.stat().st_mtime < 6 * 3600:
                continue  # pode estar sendo editado agora
            sz = _rm(f)
            freed += sz
            total -= sz

    _log.info("Limpeza: %s liberados", fmt_bytes(freed))
    return {"liberado": freed, "liberado_txt": fmt_bytes(freed), "livre_gb": round(free_gb(), 2),
            "work_txt": fmt_bytes(dir_size(paths.WORK))}


# ================================================================== OneDrive
def onedrive_root(cfg: Config) -> Path | None:
    """Pasta do CORTEX dentro do OneDrive (ex.: C:\\Users\\voce\\OneDrive\\CORTEX)."""
    import os

    if not cfg.get("armazenamento.onedrive.ativo", True):
        return None
    base = cfg.get("armazenamento.onedrive.pasta", "auto")
    if base in (None, "", "auto"):
        base = os.environ.get("OneDrive") or os.environ.get("OneDriveConsumer")
    if not base or not Path(base).exists():
        return None
    return Path(base) / str(cfg.get("armazenamento.onedrive.subpasta", "CORTEX"))


def onedrive_running() -> bool:
    from .util import run_cmd

    try:
        r = run_cmd(["tasklist", "/FI", "IMAGENAME eq OneDrive.exe", "/NH"], timeout=15)
        return "OneDrive.exe" in (r.stdout or "")
    except Exception:
        return False


def free_local_copy(path: Path) -> bool:
    """Marca como 'somente online': depois de subir para a nuvem, o OneDrive apaga a copia local."""
    from .util import run_cmd

    args = ["attrib", "+U", "-P", str(path)]
    if path.is_dir():
        args += ["/S", "/D"]
    try:
        return run_cmd(args, timeout=60).returncode == 0
    except Exception:
        return False


def release_published(clip_id: str, path: str, cfg: Config) -> str:
    """Corte ja publicado em todas as redes: tira do PC na hora.

    armazenamento.apagar_apos_publicar:
      "onedrive" (padrao) -> move para OneDrive\\CORTEX\\cortes e marca 'somente online' (sobra copia na nuvem)
      "apagar"            -> apaga o video e a miniatura
      "manter"            -> deixa no PC (a limpeza normal apaga depois de alguns dias)
    """
    from datetime import datetime

    mode = str(cfg.get("armazenamento.apagar_apos_publicar", "onedrive"))
    # versoes por rede (logo + @ de cada rede): ja foram postadas, nao precisam ir para a nuvem
    try:
        import json as _json

        row = db.conn().execute("SELECT rendered FROM clips WHERE id=?", (clip_id,)).fetchone()
        variants = (_json.loads(row["rendered"]) or {}).get("variants") or {} if row and row["rendered"] else {}
        for v in variants.values():
            if v and Path(v).exists() and Path(v).resolve() != Path(path).resolve():
                if mode != "manter":
                    Path(v).unlink(missing_ok=True)
    except Exception as e:
        _log.debug("variantes: %s", e)
    src = Path(path)
    if mode == "manter" or not src.exists():
        return "mantido"
    root = onedrive_root(cfg) if mode == "onedrive" else None
    thumb = src.with_suffix(".jpg")
    if mode == "onedrive" and root is None:
        _log.warning("pasta do OneDrive nao encontrada: guardei o video no PC (%s)", src.name)
        return "mantido"
    try:
        if root:
            dest_dir = root / "cortes" / datetime.now().strftime("%Y-%m")
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / src.name
            shutil.move(str(src), str(dest))
            if thumb.exists():
                shutil.move(str(thumb), str(dest_dir / thumb.name))
            db.update_render_path(clip_id, str(dest))
            free_local_copy(dest)
            _log.info("Publicado e liberado do PC: %s -> OneDrive", src.name)
            return "onedrive"
        src.unlink(missing_ok=True)
        thumb.unlink(missing_ok=True)
        _log.info("Publicado e apagado do PC: %s", src.name)
        return "apagado"
    except OSError as e:
        _log.warning("Nao consegui liberar %s: %s", src.name, e)
        return "erro"


def archive_to_onedrive(cfg: Config) -> dict:
    """Move cortes ja publicados para o OneDrive (liberando o disco) e espelha os relatorios.

    Os arquivos continuam acessiveis em OneDrive\\CORTEX (no PC e no celular).
    """
    from datetime import datetime

    root = onedrive_root(cfg)
    if not root:
        return {"ativo": False}
    moved, freed = 0, 0
    min_age_h = float(cfg.get("armazenamento.onedrive.arquivar_apos_horas", 1))
    now = time.time()
    statuses = ("publicado",) if cfg.get("armazenamento.onedrive.arquivar", "publicados") == "publicados" \
        else ("publicado", "renderizado", "aprovado", "rejeitado")
    for row in db.clip_rows(limit=5000):
        if row["status"] not in statuses or not row["render_path"]:
            continue
        src = Path(row["render_path"])
        if not src.exists() or str(src).lower().startswith(str(root).lower()):
            continue
        if (now - src.stat().st_mtime) / 3600 < min_age_h:
            continue
        dest_dir = root / "cortes" / datetime.fromtimestamp(row["created"] or now).strftime("%Y-%m")
        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            size = src.stat().st_size
            dest = dest_dir / src.name
            shutil.move(str(src), str(dest))
            thumb = src.with_suffix(".jpg")
            if thumb.exists():
                shutil.move(str(thumb), str(dest_dir / thumb.name))
            db.update_render_path(row["id"], str(dest))
            free_local_copy(dest)
            moved += 1
            freed += size
        except OSError as e:
            _log.warning("Nao consegui arquivar %s: %s", src.name, e)
    # relatorios (pequenos): espelha para ver no celular
    try:
        rep_dir = root / "relatorios"
        rep_dir.mkdir(parents=True, exist_ok=True)
        for f in paths.REPORTS.glob("*.html"):
            dst = rep_dir / f.name
            if not dst.exists() or dst.stat().st_mtime < f.stat().st_mtime:
                shutil.copy2(f, dst)
    except OSError as e:
        _log.debug("espelho de relatorios: %s", e)
    if moved:
        _log.info("OneDrive: %s corte(s) arquivados (%s liberados no PC apos a sincronizacao)", moved, fmt_bytes(freed))
    return {"ativo": True, "pasta": str(root), "movidos": moved, "liberado_txt": fmt_bytes(freed),
            "sincronizando": onedrive_running()}


def usage() -> dict:
    return {
        "livre_gb": round(free_gb(), 2),
        "work": fmt_bytes(dir_size(paths.WORK)),
        "renders": fmt_bytes(dir_size(paths.RENDERS)),
        "fundos": fmt_bytes(dir_size(paths.BACKGROUNDS)),
        "modelos": fmt_bytes(dir_size(paths.MODELS)),
        "navegador": fmt_bytes(dir_size(paths.BROWSER_PROFILE)),
    }
