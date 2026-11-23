"""Biblioteca de videos de fundo para o layout split (assets/fundos/<categoria>/).

  gameplay   -> Minecraft parkour, Subway Surfers, GTA mega rampa (YouTube, so Creative Commons)
  satisfying -> areia cinetica, sabao...
  asmr       -> slime...
  procedural -> gerados aqui com o ffmpeg (sem direitos autorais): gradientes, fractal, vida, plasma

Todos os fundos sao guardados ja no formato da metade de baixo (9:8, 720x640, 30 fps, sem audio)
para ocupar pouco disco. Creditos (titulo, url, canal, licenca) em assets/fundos/creditos.json.
"""
from __future__ import annotations

import json
import random
import shutil
import time
from pathlib import Path
from typing import Callable

from .. import paths
from ..log import get as get_log
from ..util import dir_size, slugify
from . import ffmpeg as ff

_log = get_log(__name__)

CATEGORIES = ("gameplay", "satisfying", "asmr", "procedural")
BG_W, BG_H, BG_FPS = 720, 640, 30
CREDITS = paths.BACKGROUNDS / "creditos.json"
RECENT = paths.STATE / "fundos_recentes.json"
CC_FILTER = "EgIwAQ%253D%253D"   # filtro "Creative Commons" da busca do YouTube

DEFAULT_WEIGHTS = {"gameplay": 0.6, "satisfying": 0.2, "asmr": 0.1, "procedural": 0.1}

# (categoria, busca, quantos videos)
PACK_QUERIES: list[tuple[str, str, int]] = [
    ("gameplay", "minecraft parkour gameplay", 2),
    ("gameplay", "subway surfers gameplay", 2),
    ("gameplay", "gta 5 mega ramp", 2),
    ("satisfying", "satisfying kinetic sand", 1),
    ("satisfying", "soap cutting asmr", 1),
    ("asmr", "slime asmr no talking", 1),
    # variedade extra (clichês 2023/24 ficam em minoria): corrida de bolinhas, prensa, construcao...
    ("satisfying", "marble race", 1),
    ("satisfying", "hydraulic press satisfying", 1),
    ("gameplay", "minecraft building timelapse", 1),
    ("satisfying", "satisfying slime", 1),
    ("asmr", "asmr cooking no talking", 1),
]

_ENC = ["-c:v", "libx264", "-preset", "medium", "-crf", "29", "-maxrate", "1800k", "-bufsize", "3600k",
        "-pix_fmt", "yuv420p", "-g", "120", "-an", "-movflags", "+faststart"]

# Fundos procedurais (lavfi). Resolucao baixa + ampliacao = rapido e leve.
_PLASMA_V = "(sin(X/16+T*0.8)+sin(Y/11+T*0.45)+sin((X+Y)/20+T*0.3)+sin(hypot(X-120,Y-107)/12-T*0.9))"
PROCEDURAL: dict[str, tuple[str, int]] = {
    "aurora_espiral": (
        f"gradients=s={BG_W}x{BG_H}:r={BG_FPS}:c0=0x7b2ff7:c1=0x00e5ff:c2=0xff2e88:c3=0x1de9b6:c4=0xffd600:"
        "nb_colors=5:speed=0.015:type=spiral,hue=H=2*PI*t/45", 90),
    "fractal_mandelbrot": (
        "mandelbrot=s=360x320:r=30:maxiter=900:start_scale=2.6:end_scale=0.00035:end_pts=2700:"
        "start_x=-0.743643887037158704752191506114774:start_y=0.131825904205311970493132056385139:"
        "outer=normalized_iteration_count:inner=black,"
        f"scale={BG_W}:{BG_H}:flags=lanczos,hue=H=2*PI*t/60:s=1.2", 90),
    "jogo_da_vida": (
        "life=s=180x160:mold=12:r=12:ratio=0.18:death_color=#14002e:life_color=#00ffd0:mold_color=#4a1080,"
        f"fps={BG_FPS},scale={BG_W}:{BG_H}:flags=neighbor,hue=H=2*PI*t/50", 75),
    "plasma": (
        "nullsrc=s=240x214:r=30,"
        f"geq=r='128+110*sin(PI*{_PLASMA_V})':g='128+110*sin(PI*{_PLASMA_V}+2.09)':"
        f"b='128+110*sin(PI*{_PLASMA_V}+4.19)',scale={BG_W}:{BG_H}:flags=bicubic,eq=saturation=0.85", 75),
    "aneis_hipnoticos": (
        "nullsrc=s=360x320:r=30,"
        "geq=lum='128+127*sin(hypot(X-180,Y-160)/7-T*4+3*sin(atan2(Y-160,X-180)*6+T*0.7))':"
        "cb='128+90*sin(T/3)':cr='128+90*cos(T/2.3)',"
        f"scale={BG_W}:{BG_H}:flags=bicubic,hue=H=2*PI*t/24:s=1.5", 75),
    "gradiente_lava": (
        f"gradients=s={BG_W}x{BG_H}:r={BG_FPS}:c0=0xff512f:c1=0xdd2476:c2=0x6a00ff:c3=0x00c9ff:c4=0x92fe9d:"
        "c5=0xf9d423:nb_colors=6:speed=0.02:type=circular,eq=saturation=1.1", 75),
}


# ------------------------------------------------------------------ biblioteca
def _list(cat: str) -> list[Path]:
    d = paths.BACKGROUNDS / cat
    if not d.exists():
        return []
    return sorted(p for p in d.iterdir() if p.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov")
                  and p.stat().st_size > 10_000 and not p.name.startswith("_"))


def library() -> dict[str, list[Path]]:
    return {c: _list(c) for c in CATEGORIES}


def library_size_mb() -> float:
    return dir_size(paths.BACKGROUNDS) / 1024 / 1024


def generate_procedural(force: bool = False, names: list[str] | None = None,
                        on_event: Callable[[str], None] | None = None) -> list[Path]:
    out_dir = paths.BACKGROUNDS / "procedural"
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    for name, (graph, dur) in PROCEDURAL.items():
        if names and name not in names:
            continue
        dest = out_dir / f"{name}.mp4"
        if dest.exists() and not force:
            continue
        if on_event:
            on_event(f"Gerando fundo procedural '{name}'...")
        tmp = out_dir / f"_{name}.mp4"
        try:
            ff.run(["-f", "lavfi", "-i", graph, "-t", str(dur), "-r", str(BG_FPS), *_ENC, str(tmp)], timeout=900)
            tmp.replace(dest)
            made.append(dest)
        except Exception as e:  # noqa: BLE001
            _log.warning("Falha ao gerar fundo %s: %s", name, str(e)[-300:])
            tmp.unlink(missing_ok=True)
    return made


def ensure_library(cfg=None, on_event: Callable[[str], None] | None = None) -> dict[str, list[Path]]:
    """Garante as pastas; se nao houver fundos procedurais, gera. Devolve {categoria: [arquivos]}."""
    for c in CATEGORIES:
        (paths.BACKGROUNDS / c).mkdir(parents=True, exist_ok=True)
    if not _list("procedural"):
        generate_procedural(on_event=on_event)
    return library()


# ------------------------------------------------------------------ escolha
def _recent() -> list[str]:
    try:
        return json.loads(RECENT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def _remember(p: Path) -> None:
    try:
        r = [x for x in _recent() if x != p.name][-7:] + [p.name]
        RECENT.parent.mkdir(parents=True, exist_ok=True)
        RECENT.write_text(json.dumps(r), encoding="utf-8")
    except OSError:
        pass


def pick(cfg=None, duration: float = 60.0, category: str | None = None,
         rng: random.Random | None = None) -> tuple[Path, float] | None:
    """Escolhe (arquivo, offset em s). None se a biblioteca estiver vazia."""
    rng = rng or random.Random()
    lib = library()
    allowed = list(cfg.get("edicao.fundo_categorias", list(CATEGORIES)) if cfg is not None else CATEGORIES)
    allowed = [c for c in allowed if c in CATEGORIES] or list(CATEGORIES)
    weights = dict(DEFAULT_WEIGHTS)
    if cfg is not None and isinstance(cfg.get("edicao.fundo_pesos"), dict):
        weights.update({k: float(v) for k, v in cfg.get("edicao.fundo_pesos").items() if k in CATEGORIES})
    if category and lib.get(category):
        cats = [category]
    else:
        cats = [c for c in allowed if lib.get(c)]
        if not cats:
            cats = [c for c in CATEGORIES if lib.get(c)]
    if not cats:
        return None
    recent_list = _recent()
    if recent_list and len(cats) > 1:   # evita a mesma categoria duas vezes seguidas
        last_cat = next((c for c in cats if any(f.name == recent_list[-1] for f in lib[c])), None)
        if last_cat:
            weights[last_cat] = weights.get(last_cat, 0.1) * 0.25
    cat = rng.choices(cats, weights=[max(0.001, weights.get(c, 0.1)) for c in cats])[0]
    files = lib[cat]
    recent = set(recent_list)
    fresh = [f for f in files if f.name not in recent] or files
    f = rng.choice(fresh)
    try:
        bdur = ff.probe(f)["duration"]
    except Exception:  # noqa: BLE001
        bdur = 0.0
    offset = rng.uniform(0, bdur - duration - 0.5) if bdur > duration + 1 else 0.0
    _remember(f)
    return f, round(offset, 2)


# ------------------------------------------------------------------ pacote inicial (YouTube CC)
def _load_credits() -> list[dict]:
    try:
        return json.loads(CREDITS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def _save_credits(items: list[dict]) -> None:
    CREDITS.parent.mkdir(parents=True, exist_ok=True)
    CREDITS.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def credits() -> list[dict]:
    return _load_credits()


BLOCKED = paths.BACKGROUNDS / "bloqueados.json"


def _blocked() -> set[str]:
    try:
        return set(json.loads(BLOCKED.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        return set()


def remove_background(name_or_id: str, block: bool = True) -> bool:
    """Apaga um fundo (arquivo + credito). Com block=True o video nunca mais e baixado."""
    creds = _load_credits()
    keep, removed = [], False
    for c in creds:
        if c.get("id") == name_or_id or Path(c.get("arquivo", "")).name == name_or_id:
            (paths.BACKGROUNDS / c["arquivo"]).unlink(missing_ok=True)
            if block:
                b = _blocked()
                b.add(c["id"])
                BLOCKED.write_text(json.dumps(sorted(b)), encoding="utf-8")
            removed = True
        else:
            keep.append(c)
    if removed:
        _save_credits(keep)
    return removed


def _ydl_opts(**extra) -> dict:
    from .. import tools

    opts = {"quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True,
            "socket_timeout": 30, "retries": 3}
    node = tools.node()
    if node:
        opts["js_runtimes"] = {"node": {"path": node}}
    opts.update(extra)
    return opts


def _search_cc(query: str, limit: int = 15) -> list[dict]:
    import urllib.parse

    import yt_dlp

    url = (f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}"
           f"&sp={CC_FILTER}")
    with yt_dlp.YoutubeDL(_ydl_opts(extract_flat="in_playlist", playlistend=limit)) as y:
        info = y.extract_info(url, download=False)
    return [e for e in (info.get("entries") or []) if e and e.get("id")]


def detect_bars(path: Path, start: float = 5.0, dur: float = 25.0) -> tuple[int, int, int, int] | None:
    """Detecta tarjas pretas (cropdetect). Devolve (w, h, x, y) da area util ou None se nao houver."""
    import re

    try:
        _rc, err = ff.run(["-ss", f"{start:.1f}", "-i", str(path), "-t", f"{dur:.1f}", "-an",
                           "-vf", "cropdetect=limit=24:round=2:reset=0", "-f", "null", "-"], timeout=300)
        info = ff.probe(path)
    except Exception:  # noqa: BLE001
        return None
    m = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", err)
    if not m:
        return None
    w, h, x, y = (int(v) for v in m[-1])
    if w >= info["width"] - 8 and h >= info["height"] - 8:
        return None
    if w < info["width"] * 0.3 or h < info["height"] * 0.3:
        return None   # quase tudo preto: provavelmente cena escura, nao tarja
    return w, h, x, y


def _reencode(src: Path, dest: Path, vertical: bool) -> None:
    bars = detect_bars(src)
    pre = f"crop={bars[0]}:{bars[1]}:{bars[2]}:{bars[3]}," if bars else ""
    if bars:
        vertical = bars[1] > bars[0] * 1.2
    # recorta o centro no formato 9:8 (metade de baixo do split)
    if vertical:   # gameplay de celular: personagem fica abaixo do meio
        crop = "crop=iw:iw*8/9:0:(ih-iw*8/9)*0.62"
    else:
        crop = "crop='min(iw,ih*9/8)':'min(ih,iw*8/9)'"
    ff.run(["-i", str(src), "-vf", f"{pre}{crop},scale={BG_W}:{BG_H}:flags=bicubic,fps={BG_FPS},setsar=1",
            *_ENC, str(dest)], timeout=1800)


def fix_black_bars(on_event: Callable[[str], None] | None = None) -> list[Path]:
    """Revisa a biblioteca e remove tarjas pretas de fundos ja salvos (re-encoda so os afetados)."""
    fixed = []
    for cat in CATEGORIES:
        if cat == "procedural":
            continue
        for f in _list(cat):
            bars = detect_bars(f, start=10.0, dur=30.0)
            if not bars:
                continue
            if on_event:
                on_event(f"Removendo tarjas pretas de {f.name}")
            tmp = f.with_name("_" + f.name)
            w, h, x, y = bars
            ff.run(["-i", str(f), "-vf", f"crop={w}:{h}:{x}:{y},crop='min(iw,ih*9/8)':'min(ih,iw*8/9)',"
                    f"scale={BG_W}:{BG_H}:flags=bicubic,setsar=1", *_ENC, str(tmp)], timeout=1800)
            tmp.replace(f)
            fixed.append(f)
    return fixed


def download_pack(cfg=None, max_total_mb: float = 500, seg_s: float = 180,
                  queries: list[tuple[str, str, int]] | None = None,
                  on_event: Callable[[str], None] | None = None) -> list[dict]:
    """Monta a biblioteca inicial com videos Creative Commons do YouTube.

    So aceita videos cujo campo `license` diga Creative Commons. Baixa so o video (<=720p) de um
    trecho de `seg_s` segundos, re-encoda compacto sem audio e registra os creditos.
    """
    import yt_dlp
    from yt_dlp.utils import download_range_func

    from .style import sanitize_text, strip_emojis

    _say = on_event or (lambda m: _log.info(m))

    def say(m: str) -> None:   # mensagens ao usuario sem emoji/travessao (titulos do YouTube tem)
        _say(sanitize_text(strip_emojis(m)))
    ensure_library(cfg)
    creds = _load_credits()
    have_ids = {c.get("id") for c in creds} | _blocked()
    tmp_dir = paths.TMP / "fundos_dl"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    added: list[dict] = []
    rng = random.Random()
    for cat, query, want in (queries or PACK_QUERIES):
        if library_size_mb() >= max_total_mb - 15:
            say("Limite de espaco da biblioteca atingido.")
            break
        have_q = sum(1 for c in creds if c.get("query") == query)
        if have_q >= want:
            continue
        say(f"Buscando fundos Creative Commons: '{query}'...")
        try:
            entries = _search_cc(query)
        except Exception as e:  # noqa: BLE001
            say(f"Busca falhou ({query}): {str(e)[:200]}")
            continue
        used_channels = {c.get("channel") for c in creds if c.get("query") == query}
        entries.sort(key=lambda e: (e.get("channel") in used_channels, rng.random()))
        for e in entries:
            if have_q >= want or library_size_mb() >= max_total_mb - 15:
                break
            vid = e["id"]
            if vid in have_ids:
                continue
            dur = e.get("duration") or 0
            if dur and dur < 60:
                continue
            url = f"https://www.youtube.com/watch?v={vid}"
            try:
                with yt_dlp.YoutubeDL(_ydl_opts()) as y:
                    info = y.extract_info(url, download=False)
            except Exception as ex:  # noqa: BLE001
                _log.info("info falhou %s: %s", vid, ex)
                continue
            lic = str(info.get("license") or "")
            if "creative commons" not in lic.lower():
                _log.info("Ignorado (licenca '%s'): %s", lic, url)
                continue
            dur = float(info.get("duration") or dur or 0)
            if dur < 60:
                continue
            seg = min(seg_s, max(60.0, dur - 20))
            lo = min(30.0, max(0.0, dur - seg - 1))
            hi = max(lo, dur - seg - 30)
            start = rng.uniform(lo, hi) if hi > lo else lo
            end = min(dur, start + seg)
            for f in tmp_dir.glob("*"):
                f.unlink(missing_ok=True)
            say(f"  baixando {seg:.0f}s de '{(info.get('title') or vid)[:60]}' ({info.get('channel')})")
            try:
                opts = _ydl_opts(
                    format="bv*[vcodec!*=av01]/bv*", format_sort=["res:720", "fps:30"],
                    outtmpl=str(tmp_dir / "src.%(ext)s"), download_ranges=download_range_func(None, [(start, end)]),
                    force_keyframes_at_cuts=False, overwrites=True)
                with yt_dlp.YoutubeDL(opts) as y:
                    y.download([url])
                src = next((f for f in tmp_dir.glob("src.*") if f.suffix not in (".part", ".ytdl")), None)
                if not src:
                    raise RuntimeError("download nao gerou arquivo")
                si = ff.probe(src)
                name = f"{slugify(query, 24)}-{vid}".replace("--", "-")
                dest = paths.BACKGROUNDS / cat / f"{name}.mp4"
                _reencode(src, dest, si["height"] > si["width"] * 1.2)
                di = ff.probe(dest)
                item = {
                    "id": vid, "arquivo": f"{cat}/{dest.name}", "categoria": cat, "query": query,
                    "titulo": info.get("title"), "url": url, "canal": info.get("channel") or info.get("uploader"),
                    "canal_url": info.get("channel_url"), "licenca": lic,
                    "trecho_original": [round(start, 1), round(end, 1)], "duracao": round(di["duration"], 1),
                    "tamanho_mb": round(dest.stat().st_size / 1024 / 1024, 1), "baixado_em": time.strftime("%Y-%m-%d"),
                }
                creds.append(item)
                added.append(item)
                have_ids.add(vid)
                have_q += 1
                _save_credits(creds)
                say(f"  ok: {dest.name} ({item['tamanho_mb']} MB, {lic})")
            except Exception as ex:  # noqa: BLE001
                say(f"  falhou {vid}: {str(ex)[-200:]}")
            finally:
                for f in tmp_dir.glob("*"):
                    f.unlink(missing_ok=True)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return added
