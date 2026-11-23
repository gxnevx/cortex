"""Regras de games (gosto do dono): so dois tipos de corte prestam.

1. REACAO forte: rage quit, streamer surtando, briga, susto, xingamento, risada (tem fala que prova isso).
2. CURIOSIDADE completa: easter egg, segredo, teoria. Usa os capitulos do video: cada capitulo e um assunto inteiro
   (com contexto); se for longo, vira Parte 1, 2, 3.
Gameplay solto, sem uma coisa nem outra, nao vira corte.
"""
from __future__ import annotations

import re

from ..models import Candidate, Transcript

STRONG = {"palavrao", "insulto", "acusacao", "emocao", "risada", "surpresa", "polemica"}
_CURIOUS = re.compile(r"easter\s*egg|curiosidad|segredo|escondid|refer[eê]ncia|teoria|detalhe|mist[eé]rio|bizarr|"
                      r"hidden|secret|details?\b|facts?\b|\b(top\s*)?\d{1,2}\s+(coisas|fatos|momentos|things|easter)", re.I)
_SKIP = re.compile(r"^\W*(intro|introdu|abertura|in[ií]cio|come[cç]o|final|fim|encerra|conclus|outro|sponsor|patroc|"
                   r"publi|an[uú]ncio|considera|start|ending|wrap)", re.I)


def is_game(video: Candidate) -> bool:
    ex = video.extra or {}
    if str(ex.get("categoria") or ex.get("categoria_canal") or "").lower() in ("games", "game", "jogos"):
        return True
    return "gaming" in " ".join(str(x).lower() for x in ex.get("categories") or [])


def is_curiosity(video: Candidate) -> bool:
    return bool(_CURIOUS.search(video.title or ""))


def strong_reaction(span: dict | None) -> bool:
    return bool(span and set(span.get("tipos") or ()) & STRONG)


def chapter_windows(video: Candidate, transcript: Transcript, cfg, limit: int) -> list[dict]:
    """Video de curiosidades com capitulos: um corte por capitulo, com assunto e contexto completos."""
    if not (is_game(video) and is_curiosity(video)):
        return []
    dmin = float(cfg.get("corte.duracao_min_s", 15)) if cfg is not None else 15.0
    dmax = float(cfg.get("corte.duracao_max_s", 45)) if cfg is not None else 45.0
    heat = [(float(h["start_time"]), float(h["end_time"]), float(h["value"])) for h in (video.extra or {}).get("heatmap") or []]
    out = []
    for ch in (video.extra or {}).get("chapters") or []:
        a, b = float(ch.get("start_time") or 0), float(ch.get("end_time") or 0)
        name = re.sub(r"^\W*\d{1,2}\W+", "", str(ch.get("title") or "")).strip(" -:|#")
        if not name or _SKIP.match(name) or b - a < dmin or b - a > dmax * 4:
            continue
        text = transcript.slice(a, b, rebase=False).text
        if len(text) < 60:  # sem narracao nao da para entender o contexto
            continue
        hot = [v for s, e, v in heat if e > a and s < b]
        out.append({
            "start": a, "end": b, "title": name[:80], "hook": name[:40].upper(),
            "description": f"{name}. Trecho de \"{(video.title or '')[:90]}\".", "hashtags": ["#games", "#curiosidades"],
            "score": 70 + 25 * (max(hot) if hot else 0.4), "reason": "curiosidade completa (capítulo do vídeo)",
            "category": "games", "tipo": "curiosidade", "series": None, "series_name": name[:60], "part": None, "layout": "blur",
        })
    if len(out) < 2:
        return []
    return sorted(out, key=lambda w: -w["score"])[:limit]
