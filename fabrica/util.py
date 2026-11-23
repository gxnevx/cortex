"""Utilitarios genericos usados por todos os modulos."""
from __future__ import annotations

import functools
import hashlib
import re
import shutil
import subprocess
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Sequence, TypeVar

T = TypeVar("T")

# No Windows, evita abrir janelas de console para cada subprocesso
CREATE_NO_WINDOW = 0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0


def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text[:max_len].rstrip("-")) or "sem-nome"


def short_hash(text: str, n: int = 8) -> str:
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()[:n]


def safe_filename(text: str, max_len: int = 80) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text or "").strip()
    return text[:max_len] or "arquivo"


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_ts(seconds: float) -> str:
    """Formata segundos como HH:MM:SS.mmm (usado em ffmpeg/yt-dlp)."""
    seconds = max(0.0, float(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def fmt_bytes(n: float | None) -> str:
    if not n:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def fmt_views(n: int | None) -> str:
    if n is None:
        return "?"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def now_ts() -> float:
    return time.time()


def now_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return datetime.now().strftime(fmt)


def run_id_now() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def run_cmd(
    args: Sequence[str | Path],
    timeout: float | None = None,
    cwd: str | Path | None = None,
    input_text: str | None = None,
    check: bool = False,
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    """Roda um comando externo e devolve stdout/stderr como texto UTF-8 (sem quebrar com acentos)."""
    proc = subprocess.run(
        [str(a) for a in args],
        capture_output=True,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
        input=input_text.encode("utf-8") if input_text is not None else None,
        creationflags=CREATE_NO_WINDOW,
        env=env,
    )
    proc.stdout = proc.stdout.decode("utf-8", "replace") if isinstance(proc.stdout, bytes) else proc.stdout
    proc.stderr = proc.stderr.decode("utf-8", "replace") if isinstance(proc.stderr, bytes) else proc.stderr
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"Comando falhou ({proc.returncode}): {' '.join(map(str, args))[:300]}\n{(proc.stderr or '')[-2000:]}"
        )
    return proc


def retry(times: int = 3, delay: float = 2.0, backoff: float = 2.0, exceptions: tuple = (Exception,)):
    """Decorador simples de retentativa com backoff exponencial."""

    def deco(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            d = delay
            last = None
            for i in range(times):
                try:
                    return fn(*a, **kw)
                except exceptions as e:  # noqa: PERF203
                    last = e
                    if i < times - 1:
                        time.sleep(d)
                        d *= backoff
            raise last  # type: ignore[misc]

        return wrapper

    return deco


def dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def disk_free_gb(path: Path) -> float:
    return shutil.disk_usage(str(path)).free / 1024**3


_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿⬀-⯿⏩-⏺⌚⌛⌨⏏"
    "↩↪⤴⤵〰〽㊗㊙Ⓜ™ℹ↔-↙"
    "︀-️‍⃣\U000E0020-\U000E007F]"
)


def strip_emojis(text: str | None) -> str:
    """Remove emojis (e simbolos pictograficos) mantendo acentos e pontuacao normal."""
    if not text:
        return text or ""
    out = _EMOJI_RE.sub("", text)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return re.sub(r" +([,.!?:;])", r"\1", out).strip()


# Regra do dono: nada de bolinhas nem travessoes longos em texto nenhum
_BANNED_CHARS = {"—": "-", "–": "-", "•": "-", "·": "-", "‧": "-", "●": "-"}


def clean_text(text: str | None, emojis: bool = False) -> str:
    """Texto final para titulo/legenda/descricao: sem bolinhas, sem travessao e (por padrao) sem emojis."""
    if not text:
        return text or ""
    for a, b in _BANNED_CHARS.items():
        text = text.replace(a, b)
    if not emojis:
        text = strip_emojis(text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def chunked(items: Sequence[T], size: int) -> Iterable[Sequence[T]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))
