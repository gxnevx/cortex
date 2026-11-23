"""Aprendizado com as metricas dos nossos posts (bandit suave + insights em pt-BR).

API (docs/METRICAS.md):
    weights(cfg, force=False) -> dict      # pesos em [0.7, 1.3] por categoria, layout, hora, canal...
    weight_for(cfg, dim, value) -> float   # atalho: 1.0 quando nao ha dado
    insights(cfg) -> list[str]             # frases curtas ("Política rende 1,8x a mediana; Humor 0,6x")
    hour_bucket(hour) / duration_bucket(s) # chaves usadas em weights()["hora"] / ["duracao"]

Metrica: views em T+24 h divididas pela mediana da PROPRIA conta naquela rede (funciona em conta pequena).
Sucesso = acima da mediana. Bandit Thompson Beta(1,1) com meia-vida de 14 dias; o peso mistura 75% da media
da posterior com 25% de uma amostra (exploracao) e encolhe para 1.0 quando ha poucos posts.
Cache em data/estado/aprendizado.json.
"""
from __future__ import annotations

import json
import random
import re
import statistics
import threading
import time
import unicodedata
from datetime import datetime
from typing import Any

from . import log, metrics, paths

_log = log.get("learning")
_lock = threading.RLock()

DIMS = ["categoria", "canal", "layout", "hora", "dia_semana", "duracao", "emojis_titulo", "estilo_titulo", "serie",
        "gancho"]
_DAYS = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]
_DAY_NAMES = {"seg": "Segunda", "ter": "Terça", "qua": "Quarta", "qui": "Quinta", "sex": "Sexta",
              "sab": "Sábado", "dom": "Domingo"}
_CAT_NAMES = {"politica": "Política", "humor": "Humor", "games": "Games", "esporte": "Esporte",
              "fofoca": "Fofoca", "celebridades": "Celebridades", "podcast": "Podcast", "polemica": "Polêmica",
              "tecnologia": "Tecnologia", "ciencia": "Ciência", "financas": "Finanças", "musica": "Música",
              "noticias": "Notícias", "crime": "Crime", "educacao": "Educação", "religiao": "Religião",
              "entretenimento": "Entretenimento", "reality": "Reality", "motivacional": "Motivacional"}
_EMOJI_NAMES = {"0": "sem emoji", "1": "1 emoji", "2+": "2 ou mais emojis"}
_STYLE_NAMES = {"pergunta": "em pergunta", "exclamacao": "com exclamação", "caixa_alta": "em caixa alta",
                "neutro": "neutros"}
_HOUR_BUCKETS = [(0, 6), (6, 9), (9, 12), (12, 15), (15, 18), (18, 21), (21, 24)]


def _cfg(cfg: Any, key: str, default: Any) -> Any:
    try:
        v = cfg.get(key, default) if cfg is not None else default
        return default if v is None else v
    except Exception:
        return default


def _cache_path():
    return paths.STATE / "aprendizado.json"


def key(value: Any) -> str:
    """Chave normalizada (minusculas, sem acento): 'Política' -> 'politica'."""
    t = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", t)


def hour_bucket(hour: int | float) -> str:
    h = int(hour) % 24
    for a, b in _HOUR_BUCKETS:
        if a <= h < b:
            return f"{a:02d}-{b:02d}"
    return "00-06"


def duration_bucket(seconds: float | None) -> str | None:
    if not seconds:
        return None
    s = float(seconds)
    if s < 25:
        return "ate 25s"
    if s < 35:
        return "25-35s"
    if s < 45:
        return "35-45s"
    if s <= 60:
        return "45-60s"
    return "acima de 60s"


def title_style(title: str | None) -> str:
    t = metrics.plain(title)
    letters = [c for c in t if c.isalpha()]
    if "?" in t:
        return "pergunta"
    if "!" in t:
        return "exclamacao"
    if len(letters) >= 8 and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        return "caixa_alta"
    return "neutro"


def emoji_bucket(title: str | None) -> str:
    n = metrics.count_emojis(title)
    return "0" if n == 0 else "1" if n == 1 else "2+"


# ====================================================================== dados
def dataset(cfg: Any) -> list[dict]:
    """Um registro por post (ok, nao teste) com views em 24 h, razao contra a mediana da conta e caracteristicas."""
    days = float(_cfg(cfg, "metricas.aprendizado.janela_dias", 60))
    since = time.time() - days * 86400
    c = metrics._conn()
    rows = [dict(r) for r in c.execute(
        """SELECT p.id, p.clip_id, p.platform, p.ts, c.title AS clip_title, c.plan, c.rendered, v.channel
           FROM posts p LEFT JOIN clips c ON c.id = p.clip_id LEFT JOIN videos v ON v.id = c.video_id
           WHERE p.ok=1 AND p.dry_run=0 AND p.ts>=? ORDER BY p.ts""", (since,)).fetchall()]
    rmap = metrics.readings_by_post(None, since)
    out: list[dict] = []
    for r in rows:
        rs = rmap.get(int(r["id"]), [])
        v24 = metrics.views_at(rs)
        if v24 is None:
            continue
        try:
            plan = json.loads(r["plan"]) if r.get("plan") else {}
        except Exception:
            plan = {}
        try:
            rend = json.loads(r["rendered"]) if r.get("rendered") else {}
        except Exception:
            rend = {}
        title = plan.get("title") or r.get("clip_title") or ""
        dur = rend.get("duration") or ((plan.get("end") or 0) - (plan.get("start") or 0)) or None
        when = datetime.fromtimestamp(float(r["ts"]))
        serie = bool(plan.get("series")) or int(plan.get("parts_total") or 0) > 1
        feats = {
            "categoria": key(plan.get("category")) or None,
            "canal": (r.get("channel") or "").strip() or None,
            "layout": key(rend.get("layout") or plan.get("layout")) or None,
            "hora": hour_bucket(when.hour),
            "dia_semana": _DAYS[when.weekday()],
            "duracao": duration_bucket(dur),
            "emojis_titulo": emoji_bucket(title),
            "estilo_titulo": title_style(title),
            "serie": "serie" if serie else "avulso",
            "gancho": "com_gancho" if plan.get("teaser_start") is not None else "sem_gancho",
        }
        out.append({"post_id": int(r["id"]), "platform": r["platform"], "ts": float(r["ts"]), "views24": v24,
                    "titulo": title, "features": feats})
    # normaliza pela mediana da propria conta em cada rede
    by_plat: dict[str, list[int]] = {}
    for d in out:
        by_plat.setdefault(d["platform"], []).append(d["views24"])
    med = {p: float(statistics.median(v)) for p, v in by_plat.items()}
    for d in out:
        m = med[d["platform"]]
        d["mediana_rede"] = m
        d["razao"] = (d["views24"] + 1.0) / (m + 1.0)
        d["sucesso"] = 1.0 if d["razao"] > 1.0001 else (0.5 if d["razao"] >= 0.9999 else 0.0)
    return out


# ====================================================================== bandit
def _arm_stats(data: list[dict], dim: str, half_life_d: float, now: float) -> dict[str, dict]:
    arms: dict[str, dict] = {}
    for d in data:
        v = d["features"].get(dim)
        if v is None or v == "":
            continue
        w = 0.5 ** (max(0.0, now - d["ts"]) / 86400.0 / max(0.1, half_life_d))
        a = arms.setdefault(str(v), {"n": 0, "n_eff": 0.0, "s": 0.0, "f": 0.0, "razoes": []})
        a["n"] += 1
        a["n_eff"] += w
        a["s"] += w * d["sucesso"]
        a["f"] += w * (1.0 - d["sucesso"])
        a["razoes"].append(d["razao"])
    return arms


def _arm_weight(a: dict, rng: random.Random, cfg: Any) -> float:
    A = "metricas.aprendizado."
    prior = _cfg(cfg, A + "prior", [1, 1])
    lo = float(_cfg(cfg, A + "peso_min", 0.7))
    hi = float(_cfg(cfg, A + "peso_max", 1.3))
    explore = float(_cfg(cfg, A + "explorar_frac", 0.25))
    gain = float(_cfg(cfg, A + "ganho", 1.2))
    shrink = float(_cfg(cfg, A + "encolher_k", 5))
    alpha = float(prior[0]) + a["s"]
    beta = float(prior[1]) + a["f"]
    mean = alpha / (alpha + beta)
    theta = rng.betavariate(alpha, beta)
    score = (1 - explore) * mean + explore * theta
    raw = min(hi, max(lo, 1.0 + gain * (score - 0.5)))
    conf = a["n_eff"] / (a["n_eff"] + shrink)
    return round(min(hi, max(lo, 1.0 + conf * (raw - 1.0))), 3)


def _signature() -> list:
    try:
        r = metrics._conn().execute("SELECT COUNT(*), MAX(ts) FROM post_metrics").fetchone()
        return [int(r[0] or 0), float(r[1] or 0)]
    except Exception:
        return [0, 0.0]


def _compute(cfg: Any, seed: int | None = None) -> dict:
    A = "metricas.aprendizado."
    now = time.time()
    data = dataset(cfg)
    n = len(data)
    min_w = int(_cfg(cfg, A + "min_posts_pesos", 10))
    half = float(_cfg(cfg, A + "meia_vida_dias", 14))
    rng = random.Random(seed)
    out: dict = {"atualizado": now, "n_posts": n, "suficiente": n >= min_w, "metodo": "thompson_beta",
                 "medianas": {}, "detalhes": {}}
    for d in data:
        out["medianas"][d["platform"]] = d["mediana_rede"]
    for dim in DIMS:
        arms = _arm_stats(data, dim, half, now)
        out[dim] = {}
        out["detalhes"][dim] = {}
        for v, a in sorted(arms.items()):
            out["detalhes"][dim][v] = {"n": a["n"], "razao_mediana": round(statistics.median(a["razoes"]), 3),
                                       "sucesso": round(a["s"] / a["n_eff"], 3) if a["n_eff"] else 0.0}
            if n >= min_w:
                out[dim][v] = _arm_weight(a, rng, cfg)
    return out


def weights(cfg: Any, force: bool = False, seed: int | None = None) -> dict:
    """Pesos suaves [0.7, 1.3] por dimensao. Nunca levanta excecao (sem dados -> dicionarios vazios = 1.0).

    {"categoria": {"politica": 1.12, ...}, "layout": {...}, "hora": {"18-21": 1.08, ...}, "canal": {...},
     "dia_semana": {...}, "duracao": {...}, "emojis_titulo": {...}, "estilo_titulo": {...}, "serie": {...},
     "n_posts": int, "suficiente": bool, "atualizado": ts, "metodo": "thompson_beta", "medianas": {rede: views}}
    """
    empty = {d: {} for d in DIMS}
    empty.update({"n_posts": 0, "suficiente": False, "atualizado": 0, "metodo": "thompson_beta", "medianas": {}})
    try:
        with _lock:
            sig = _signature()
            cache = metrics._read_json(_cache_path())
            ttl = float(_cfg(cfg, "metricas.aprendizado.cache_min", 360)) * 60
            fresh = cache.get("assinatura") == sig and time.time() - float(cache.get("gerado") or 0) < ttl
            if not force and fresh and isinstance(cache.get("pesos"), dict):
                return cache["pesos"]
            full = _compute(cfg, seed)
            detalhes = full.pop("detalhes", {})
            cache = {"versao": 1, "assinatura": sig, "gerado": time.time(), "pesos": full, "detalhes": detalhes,
                     "insights": _insights_from(full, detalhes, cfg)}
            metrics._write_json(_cache_path(), cache)
            return full
    except Exception as e:  # noqa: BLE001
        _log.warning("learning.weights: %s", e)
        return empty


def weight_for(cfg: Any, dim: str, value: Any) -> float:
    """Peso de um valor (ex.: weight_for(cfg, "categoria", "Política")). 1.0 quando nao ha dado."""
    try:
        table = weights(cfg).get(dim) or {}
        if dim == "hora" and isinstance(value, (int, float)):
            value = hour_bucket(value)
        if dim == "canal":
            return float(table.get(str(value or "").strip(), 1.0))
        return float(table.get(key(value), table.get(str(value), 1.0)))
    except Exception:  # noqa: BLE001
        return 1.0


# ====================================================================== insights
def _name(dim: str, v: str) -> str:
    if dim == "categoria":
        return _CAT_NAMES.get(v, v[:1].upper() + v[1:])
    if dim == "dia_semana":
        return _DAY_NAMES.get(v, v)
    if dim == "emojis_titulo":
        return _EMOJI_NAMES.get(v, v)
    if dim == "estilo_titulo":
        return _STYLE_NAMES.get(v, v)
    if dim == "hora":
        a, b = v.split("-")
        return f"{int(a)}h-{int(b)}h"
    return metrics.plain(v)


def _line(dim: str, best: str, rb: float, worst: str, rw: float) -> str:
    b, w = _name(dim, best), _name(dim, worst)
    xb, xw = metrics.fmt_ratio(rb), metrics.fmt_ratio(rw)
    if dim == "categoria":
        return f"{b} rende {xb} a mediana; {w} {xw}"
    if dim == "canal":
        return f"Cortes de {b} rendem {xb} a mediana; de {w} {xw}"
    if dim == "layout":
        return f"Layout {b} rende {xb} a mediana; {w} {xw}"
    if dim == "hora":
        return f"Postar entre {b} rende {xb} a mediana; entre {w} {xw}"
    if dim == "dia_semana":
        return f"{b} rende {xb} a mediana; {w} {xw}"
    if dim == "duracao":
        return f"Cortes de {b} rendem {xb} a mediana; de {w} {xw}"
    if dim == "emojis_titulo":
        return f"Títulos com {b} rendem {xb} a mediana; com {w} {xw}"
    if dim == "estilo_titulo":
        return f"Títulos {b} rendem {xb} a mediana; {w} {xw}"
    if dim == "serie":
        nb = "Séries (Parte 1, 2...)" if best == "serie" else "Cortes avulsos"
        nw = "séries" if worst == "serie" else "avulsos"
        return f"{nb} rendem {xb} a mediana; {nw} {xw}"
    if dim == "gancho":
        nb = "Cortes com gancho de abertura" if best == "com_gancho" else "Cortes sem gancho de abertura"
        nw = "com gancho" if worst == "com_gancho" else "sem gancho"
        return f"{nb} rendem {xb} a mediana; {nw} {xw}"
    return f"{b} rende {xb} a mediana; {w} {xw}"


def _insights_from(pesos: dict, detalhes: dict, cfg: Any) -> list[str]:
    A = "metricas.aprendizado."
    need = int(_cfg(cfg, A + "min_posts_insights", 20))
    min_grp = int(_cfg(cfg, A + "min_posts_grupo", 3))
    n = int(pesos.get("n_posts") or 0)
    meds = pesos.get("medianas") or {}
    med_txt = ", ".join(f"{metrics.NOMES.get(p, p)} {metrics.fmt_num(int(m))} views" for p, m in sorted(meds.items()))
    if n < need:
        out = [f"Ainda não há dados suficientes para aprender: {n} de {need} posts com leitura de 24 h."]
        if n:
            out.append(f"Mediana em 24 h até agora: {med_txt}.")
        return out
    lines: list[tuple[float, str]] = []
    for dim in DIMS:
        groups = [(v, d) for v, d in (detalhes.get(dim) or {}).items() if d.get("n", 0) >= min_grp]
        if len(groups) < 2:
            continue
        groups.sort(key=lambda kv: kv[1]["razao_mediana"], reverse=True)
        (bv, bd), (wv, wd) = groups[0], groups[-1]
        rb, rw = float(bd["razao_mediana"]), float(wd["razao_mediana"])
        if rb < max(0.01, rw) * 1.25:
            continue  # diferenca pequena demais para virar conclusao
        lines.append((rb / max(0.05, rw), _line(dim, bv, rb, wv, rw)))
    lines.sort(key=lambda t: t[0], reverse=True)
    out = [f"{n} posts com leitura de 24 h. Mediana em 24 h: {med_txt}."]
    out += [t for _, t in lines[: int(_cfg(cfg, A + "max_insights", 8))]]
    if len(out) == 1:
        out.append("Nenhuma diferença clara entre categorias, layouts ou horários até agora.")
    return out


def insights(cfg: Any) -> list[str]:
    """Frases curtas em pt-BR sobre o que rende mais (pede >= 20 posts com leitura de 24 h)."""
    try:
        weights(cfg)  # atualiza o cache se preciso
        cache = metrics._read_json(_cache_path())
        ins = cache.get("insights")
        if isinstance(ins, list) and ins:
            return [metrics.plain(x) for x in ins]
        return _insights_from(cache.get("pesos") or {}, cache.get("detalhes") or {}, cfg)
    except Exception as e:  # noqa: BLE001
        _log.warning("learning.insights: %s", e)
        return ["Não consegui calcular o aprendizado agora."]
