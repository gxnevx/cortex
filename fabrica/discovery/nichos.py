"""Nicho de cada candidato (Candidate.extra["categoria"]) e mistura balanceada (busca.mix_nichos).

Nichos: politica, games, humor, podcast, futebol, celebridades, noticias, outros.
Mistura: cotas proporcionais aos pesos (padrao {politica: 0.3, games: 0.35, humor: 0.35}); o que sobrar vai
para os melhores restantes. A ordem final intercala os nichos (os N primeiros ja saem misturados).
"""
from __future__ import annotations

from .text import norm

NICHES = ["politica", "games", "humor", "podcast", "futebol", "celebridades", "noticias", "outros"]
DEFAULT_MIX = {"politica": 0.3, "games": 0.35, "humor": 0.35}
_MAP = {"politica": "politica", "games": "games", "humor": "humor", "entretenimento": "humor", "podcast": "podcast",
        "esportes": "futebol", "esporte": "futebol", "futebol": "futebol", "celebridades": "celebridades",
        "noticias": "noticias", "reality": "celebridades", "financas": "podcast", "outros": "outros"}
# palavras extras em ingles (fontes estrangeiras)
_EN_EXTRA = {
    "humor": ["funny", "prank", "comedy", "fails", "meme", "memes", "roast", "skit", "hilarious", "irl"],
    "games": ["easter egg", "easter eggs", "speedrun", "walkthrough", "gameplay", "trailer reaction", "glitch"],
    "celebridades": ["drama", "celebrity", "rapper", "beef", "diss", "kardashian", "drake", "kanye"],
    "noticias": ["breaking", "news", "update"],
    "politica": ["election", "congress", "senate", "president", "democrat", "republican"],
    "futebol": ["soccer", "premier league", "champions league", "messi", "ronaldo"],
}


def map_cat(cat: str | None) -> str | None:
    if not cat:
        return None
    return _MAP.get(norm(str(cat)).strip())


def keyword_cat(text: str) -> tuple[str | None, int]:
    """Nicho pelas palavras do texto (sem o tom "polemica")."""
    from ..brain.heuristic import CATEGORY_KEYWORDS

    t = " " + norm(text) + " "
    best, best_n = None, 0
    for cat, kws in CATEGORY_KEYWORDS.items():
        if cat == "polemica":
            continue
        kws = list(kws) + _EN_EXTRA.get(map_cat(cat) or "", [])
        n = sum(1 for kw in kws if kw in t)
        if cat == "esportes" and n == 1 and " gol" in t and "futebol" not in t:
            n = 0
        if n > best_n:
            best, best_n = map_cat(cat), n
    return best, best_n


def niche_for(c, channel_cat: str | None = None, trend_cat: str | None = None) -> str:
    ex = c.extra or {}
    text = " ".join([c.title or "", c.topic or "", (c.description or "")[:300], " ".join(ex.get("tags") or [])[:200]])
    kc, n = keyword_cat(text)
    if kc and n >= 2:
        return kc
    for cat in (channel_cat, ex.get("categoria_canal"), trend_cat):
        m = map_cat(cat)
        if m:
            return m
    return kc or "outros"


def select_mix(cands: list, limit: int, mix: dict | None = None) -> list:
    """cands ja ordenados por nota. Cotas por nicho, completa com os melhores restantes e intercala."""
    if not cands:
        return []
    mix = {map_cat(k) or k: float(v) for k, v in (mix or DEFAULT_MIX).items() if float(v or 0) > 0}
    if not mix:
        return cands[:limit]
    tot = sum(mix.values())
    quota = {k: max(1, round(v / tot * limit)) for k, v in mix.items()}
    chosen: list = []
    used: set[int] = set()
    count: dict[str, int] = {}
    for i, c in enumerate(cands):
        k = (c.extra or {}).get("categoria") or "outros"
        if k in quota and count.get(k, 0) < quota[k] and len(chosen) < limit:
            chosen.append(c)
            used.add(i)
            count[k] = count.get(k, 0) + 1
    for i, c in enumerate(cands):
        if len(chosen) >= limit:
            break
        if i not in used:
            chosen.append(c)
            used.add(i)
    # intercala (stride): cada nicho anda proporcional ao peso; fora da mistura peso pequeno
    rank: dict[str, int] = {}
    keyed = []
    for c in sorted(chosen, key=lambda c: -c.score):
        k = (c.extra or {}).get("categoria") or "outros"
        w = mix.get(k, 0.12 * tot)
        r = rank.get(k, 0)
        rank[k] = r + 1
        keyed.append(((r + 0.5) / w, -c.score, c))
    keyed.sort(key=lambda x: (x[0], x[1]))
    return [c for _, _, c in keyed]
