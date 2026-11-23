"""Historico pequeno de velocidade (views/hora) por canal, em data/estado/canais_hist.json.

Alimentado pela descoberta (abas de canal do YouTube) e pelo vigia (RSS a cada ~10 min). Serve para a
velocidade RELATIVA ao proprio canal (valores absolutos variam 1000x entre canais):

    r = vph_atual / mediana_vph_do_canal (na mesma idade)
    V = clamp(0.5 + log2(r) / 4, 0, 1)        (r = 1 -> 0.5; r = 4 -> 1.0; r = 0.25 -> 0)

A "mesma idade" importa: views/hora cai com o tempo. Usamos observacoes na mesma faixa de idade quando
existem (3+ videos); senao convertemos todas com vph(idade) ~ idade^-0.6. Com menos de 4 videos no
historico, devolve None (o chamador usa a formula absoluta).
"""
from __future__ import annotations

import json
import math
import os
import re
import statistics
import threading
import time

from .. import log, paths

_log = log.get(__name__)

FILE = paths.STATE / "canais_hist.json"
_lock = threading.Lock()
_cache: dict | None = None
_cache_mtime = 0.0

MAX_CANAIS = 400
MAX_VIDEOS = 20
MAX_OBS = 8
BUCKETS = [(0, 6), (6, 24), (24, 72), (72, 168), (168, 24 * 60)]
DECAY = 0.6
MIN_VIDEOS = 4


# ------------------------------------------------------------------ chaves
def key_from_url(url: str | None, platform: str = "youtube") -> str | None:
    """'https://www.youtube.com/@Podpah' -> 'youtube:@podpah'; '/channel/UC..' -> 'youtube:UC..'."""
    if not url:
        return None
    m = re.search(r"/(@[\w.\-]+)", url)
    if m:
        return f"{platform}:{m.group(1).lower()}"
    m = re.search(r"/channel/(UC[\w\-]{22})", url)
    if m:
        return f"{platform}:{m.group(1)}"
    return None


def keys_for(c) -> list[str]:
    """Chaves possiveis do canal de um Candidate (handle e/ou id)."""
    out = []
    k = key_from_url(c.channel_url, c.platform)
    if k:
        out.append(k)
    cid = (c.extra or {}).get("channel_id")
    if cid:
        out.append(f"{c.platform}:{cid}")
    if c.platform in ("twitch", "kick") and c.channel:
        out.append(f"{c.platform}:{c.channel.lower()}")
    return out


# ------------------------------------------------------------------ arquivo
def _load() -> dict:
    global _cache, _cache_mtime
    try:
        mt = FILE.stat().st_mtime
    except OSError:
        mt = 0.0
    if _cache is not None and mt == _cache_mtime:
        return _cache
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            d = {}
    except (OSError, ValueError):
        d = {}
    d.setdefault("canais", {})
    d.setdefault("alias", {})
    _cache, _cache_mtime = d, mt
    return d


def _save(d: dict) -> None:
    global _cache, _cache_mtime
    try:
        FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = FILE.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, FILE)
        _cache, _cache_mtime = d, FILE.stat().st_mtime
    except OSError as e:
        _log.info("nao consegui salvar o historico de canais: %s", e)


def _resolve(d: dict, key: str) -> str:
    return d["alias"].get(key, key)


def record(key: str, items: list[dict], name: str = "", aliases: list[str] | None = None,
           now: float | None = None) -> None:
    """items = [{"id", "pub" (epoch), "views"}]. Guarda uma observacao (agora, views) por video."""
    if not key or not items:
        return
    now = now or time.time()
    with _lock:
        d = _load()
        key = _resolve(d, key)
        for a in aliases or []:
            if a and a != key:
                d["alias"][a] = key
        ch = d["canais"].setdefault(key, {"nome": name, "videos": {}})
        if name:
            ch["nome"] = name
        vids = ch["videos"]
        for it in items:
            vid, pub, views = it.get("id"), it.get("pub"), it.get("views")
            if not vid or not pub or views is None or views < 0:
                continue
            age_h = (now - float(pub)) / 3600
            if age_h < 0.15 or age_h > 24 * 45:
                continue
            v = vids.setdefault(vid, {"pub": float(pub), "obs": []})
            obs = v["obs"]
            if obs and now - obs[-1][0] < 300:
                obs[-1] = [round(now), int(views)]
            else:
                obs.append([round(now), int(views)])
            if len(obs) > MAX_OBS:          # guarda as primeiras (idade baixa) e as mais novas
                v["obs"] = obs[:3] + obs[-(MAX_OBS - 3):]
        if len(vids) > MAX_VIDEOS:
            for vid in sorted(vids, key=lambda k: vids[k]["pub"])[: len(vids) - MAX_VIDEOS]:
                vids.pop(vid, None)
        ch["atualizado"] = round(now)
        if len(d["canais"]) > MAX_CANAIS:
            old = sorted(d["canais"], key=lambda k: d["canais"][k].get("atualizado", 0))
            for k in old[: len(d["canais"]) - MAX_CANAIS]:
                d["canais"].pop(k, None)
            live = set(d["canais"])
            d["alias"] = {a: k for a, k in d["alias"].items() if k in live}
        _save(d)


# ------------------------------------------------------------------ consulta
def _bucket(age_h: float) -> int:
    for i, (a, b) in enumerate(BUCKETS):
        if a <= age_h < b:
            return i
    return len(BUCKETS) - 1


def baseline_vph(key: str, age_h: float, exclude_id: str | None = None) -> tuple[float | None, int]:
    """Mediana de views/hora dos videos do canal na idade `age_h`. (None, n) se o historico for curto."""
    d = _load()
    ch = d["canais"].get(_resolve(d, key))
    if not ch:
        return None, 0
    age_h = max(age_h, 1.0)
    same: list[float] = []
    conv: list[float] = []
    b = _bucket(age_h)
    for vid, v in ch["videos"].items():
        if vid == exclude_id:
            continue
        best_same = None
        best_any = None
        for ts, views in v["obs"]:
            a = (ts - v["pub"]) / 3600
            if a < 0.25:
                continue
            vph = views / a
            if _bucket(a) == b:
                best_same = vph if best_same is None else max(best_same, vph)
            # converte para a idade pedida (vph cai ~ idade^-0.6)
            est = vph * (max(a, 1.0) / age_h) ** DECAY
            if best_any is None or abs(math.log(a / age_h)) < best_any[0]:
                best_any = (abs(math.log(a / age_h)), est)
        if best_same is not None:
            same.append(best_same)
        if best_any is not None:
            conv.append(best_any[1])
    if len(same) >= 3:
        return statistics.median(same), len(same)
    if len(conv) >= MIN_VIDEOS:
        return statistics.median(conv), len(conv)
    return None, len(conv)


def relative_velocity(keys: list[str], vph: float, age_h: float, exclude_id: str | None = None) -> dict | None:
    """{"V": 0-1, "r": razao, "base": mediana, "n": videos} ou None (historico curto)."""
    for k in keys:
        base, n = baseline_vph(k, age_h, exclude_id)
        if base and base > 0:
            r = vph / base
            V = max(0.0, min(1.0, 0.5 + math.log2(max(r, 1e-6)) / 4))
            return {"V": round(V, 3), "r": round(r, 2), "base": round(base, 1), "n": n}
    return None
