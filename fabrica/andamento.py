"""O que esta rodando AGORA: um arquivo so, que qualquer janela do CORTEX consegue ler.

Quem trabalha (rodada) grava; quem olha (menu, painel, `cortex status`) le. Se o programa cair, o registro
deixa de valer sozinho: ele guarda o processo dono (PID + hora em que o processo nasceu).
"""
from __future__ import annotations

import contextlib
import ctypes
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from . import paths

FILE = paths.STATE / "andamento.json"
_VIDEO = re.compile(r"^\[(\d+)/(\d+)\]\s+(.*)$")
_cur: dict[str, Any] = {}


# ------------------------------------------------------------------ processos
def born(pid: int) -> float:
    """Hora em que o processo nasceu (0 = nao existe mais). Protege contra PID reaproveitado pelo Windows."""
    try:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = ctypes.c_void_p
        h = k.OpenProcess(0x1000, False, int(pid))
        if not h:
            return 0.0
        try:
            code = ctypes.c_ulong()
            k.GetExitCodeProcess(ctypes.c_void_p(h), ctypes.byref(code))
            if code.value != 259:  # ja terminou
                return 0.0
            ft = [ctypes.c_ulonglong() for _ in range(4)]
            if not k.GetProcessTimes(ctypes.c_void_p(h), *[ctypes.byref(f) for f in ft]):
                return 0.0
            return ft[0].value / 1e7 - 11644473600
        finally:
            k.CloseHandle(ctypes.c_void_p(h))
    except Exception:
        return 0.0


def me() -> dict:
    return {"pid": os.getpid(), "nasceu": round(born(os.getpid()), 2)}


def alive(d: dict | None) -> bool:
    """O processo gravado em d ({"pid", "nasceu"}) ainda e o mesmo e esta vivo?"""
    if not d or not d.get("pid"):
        return False
    b = born(int(d["pid"]))
    if not b:
        return False
    return not d.get("nasceu") or abs(b - float(d["nasceu"])) < 2


def write_json(path: Path, data: Any) -> None:
    """Gravacao atomica (no Windows outra janela pode estar lendo: tenta de novo)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    for _ in range(10):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05)
    with contextlib.suppress(OSError):
        tmp.unlink()


def read_json(path: Path) -> Any:
    for _ in range(3):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except Exception:
            time.sleep(0.03)
    return None


# -------------------------------------------------------------------- registro
def begin(origem: str, assunto: str = "") -> None:
    _cur.clear()
    _cur.update({**me(), "origem": origem, "assunto": assunto, "inicio": time.time(), "etapa": 0, "etapas": 4,
                 "titulo": "", "msg": "", "msg_desde": time.time(), "video": 0, "videos": 0, "video_titulo": "", "prontos": 0})
    write_json(FILE, _cur)


def update(**kw: Any) -> None:
    if not _cur:
        return
    if "msg" in kw and kw["msg"] != _cur.get("msg"):
        _cur["msg_desde"] = time.time()
    _cur.update(kw)
    with contextlib.suppress(Exception):
        write_json(FILE, _cur)


def end() -> None:
    _cur.clear()
    with contextlib.suppress(OSError):
        FILE.unlink()


def read() -> dict | None:
    """Rodada em andamento (de qualquer janela) ou None."""
    d = read_json(FILE)
    return d if alive(d) else None


class Tap:
    """Embrulha o Reporter da rodada: tudo passa adiante e o essencial fica registrado."""

    def __init__(self, rep: Any):
        self._rep = rep

    def __getattr__(self, name: str) -> Any:
        return getattr(self._rep, name)

    def stage(self, n: int, total: int, title: str) -> None:
        update(etapa=n, etapas=total, titulo=title, msg="")
        self._rep.stage(n, total, title)

    def info(self, msg: str) -> None:
        m = _VIDEO.match(msg or "")
        if m:
            update(video=int(m.group(1)), videos=int(m.group(2)), video_titulo=m.group(3).split("  |  ")[0])
        self._rep.info(msg)

    def ok(self, msg: str) -> None:
        if (msg or "").startswith("Corte pronto"):
            update(prontos=_cur.get("prontos", 0) + 1)
        self._rep.ok(msg)

    @contextlib.contextmanager
    def working(self, msg: str):
        update(msg=msg)
        with self._rep.working(msg):
            yield


def describe(d: dict) -> str:
    """Uma linha simples: 'Cortando e editando (video 1 de 2) | Legendando ... | 1 corte pronto'."""
    parts = [d.get("titulo") or "Começando"]
    if d.get("videos"):
        parts[0] += f" (vídeo {d.get('video')} de {d['videos']})"
    if d.get("msg"):
        parts.append(str(d["msg"]).rstrip("."))
    n = int(d.get("prontos") or 0)
    if n:
        parts.append(f"{n} corte{'s' if n > 1 else ''} pronto{'s' if n > 1 else ''}")
    return " | ".join(parts)
