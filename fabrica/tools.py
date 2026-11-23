"""Localiza programas externos (ffmpeg, node, Chrome, Claude Code, Ollama)."""
from __future__ import annotations

import functools
import glob
import os
import shutil
import sys
from pathlib import Path

from . import paths

LOCAL = Path(os.environ.get("LOCALAPPDATA", ""))
ROAMING = Path(os.environ.get("APPDATA", ""))
PROGRAMFILES = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
                Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))]

# Pasta tools/ do projeto tem prioridade (permite binarios portateis)
PROJECT_TOOLS = paths.ROOT / "tools"


def _first_existing(candidates) -> str | None:
    for c in candidates:
        if c and Path(c).is_file():
            return str(c)
    return None


@functools.lru_cache(maxsize=None)
def ffmpeg() -> str | None:
    return _first_existing([PROJECT_TOOLS / "ffmpeg.exe"]) or shutil.which("ffmpeg")


@functools.lru_cache(maxsize=None)
def ffprobe() -> str | None:
    return _first_existing([PROJECT_TOOLS / "ffprobe.exe"]) or shutil.which("ffprobe")


@functools.lru_cache(maxsize=None)
def node() -> str | None:
    return shutil.which("node")


@functools.lru_cache(maxsize=None)
def deno() -> str | None:
    venv_deno = Path(sys.executable).parent / "deno.exe"
    return _first_existing([PROJECT_TOOLS / "deno.exe", venv_deno]) or shutil.which("deno")


@functools.lru_cache(maxsize=None)
def chrome() -> str | None:
    cands = [pf / "Google/Chrome/Application/chrome.exe" for pf in PROGRAMFILES]
    cands.append(LOCAL / "Google/Chrome/Application/chrome.exe")
    return _first_existing(cands)


@functools.lru_cache(maxsize=None)
def edge() -> str | None:
    return _first_existing([pf / "Microsoft/Edge/Application/msedge.exe" for pf in PROGRAMFILES])


def _version_key(p: str):
    parts = []
    for piece in Path(p).parts:
        if piece.replace(".", "").isdigit():
            parts.append(tuple(int(x) for x in piece.split(".") if x.isdigit()))
    return parts


@functools.lru_cache(maxsize=None)
def claude() -> str | None:
    """Encontra o executavel do Claude Code (CLI). Prioriza o do PATH, depois o embutido no app desktop."""
    found = shutil.which("claude")
    if found:
        return found
    local_bin = Path.home() / ".local" / "bin" / "claude.exe"
    if local_bin.is_file():
        return str(local_bin)
    # Claude Code embutido no app desktop: %APPDATA%\Claude\claude-code\<versao>\<hash>\claude.exe
    hits = glob.glob(str(ROAMING / "Claude" / "claude-code" / "*" / "*" / "claude.exe"))
    if hits:
        hits.sort(key=_version_key, reverse=True)
        return hits[0]
    npm_cmd = ROAMING / "npm" / "claude.cmd"
    if npm_cmd.is_file():
        return str(npm_cmd)
    return None


@functools.lru_cache(maxsize=None)
def ollama() -> str | None:
    return shutil.which("ollama") or _first_existing([LOCAL / "Programs/Ollama/ollama.exe"])


def python() -> str:
    return sys.executable


def summary() -> dict[str, str | None]:
    return {
        "ffmpeg": ffmpeg(),
        "ffprobe": ffprobe(),
        "node": node(),
        "deno": deno(),
        "chrome": chrome(),
        "edge": edge(),
        "claude": claude(),
        "ollama": ollama(),
    }
