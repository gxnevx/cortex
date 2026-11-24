"""Hashtags e CTA dos posts (YouTube Shorts e TikTok) para o publico brasileiro.

    choose(plan, platform, cfg, video_title=None, channel=None, idioma=None) -> list[str]
    cta(plan, platform, cfg) -> str
    trending(cfg, refresh=False) -> list[dict]
    normalize(tag) -> str | None
    translated_lang(plan, idioma=None) -> str | None

Dados curados em fabrica/dados/hashtags_ptbr.json (nichos com camadas amplas/medias/nicho, entidades,
proibidas, CTAs). Memoria anti-repeticao em data/estado/hashtags_recentes.json e cta_recentes.json.
Detalhes e fontes: docs/HASHTAGS.md.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

from . import paths
from .log import get as get_log

log = get_log(__name__)

DATA_FILE = Path(__file__).resolve().parent / "dados" / "hashtags_ptbr.json"
MEMORY_FILE = paths.STATE / "hashtags_recentes.json"
CTA_MEMORY_FILE = paths.STATE / "cta_recentes.json"
TRENDING_FILE = paths.STATE / "hashtags_trending.json"
TRENDING_TTL_S = 12 * 3600
SHORTS_TAG = "#Shorts"
YT_MAX_TOTAL = 15          # acima de 15 o YouTube pode ignorar todas (regra antiga; a ajuda atual fala em 60)
TT_MAX_TOTAL = 5           # TikTok avisa "maximo de 5 hashtags" (desde ago/2025)

LANG_NAMES = {"en": "inglês", "es": "espanhol", "fr": "francês", "it": "italiano", "de": "alemão",
              "ja": "japonês", "ko": "coreano", "ru": "russo", "zh": "chinês", "ar": "árabe", "nl": "holandês"}

_EMOJI_RE = re.compile(
    r"(?:[0-9#*]️?⃣)|[\U0001F000-\U0001FAFF]|[\U000E0020-\U000E007F]|[☀-➿]"
    r"|[⬅-⬇⬛⬜⭐⭕]|[‍︎️⃣]")


# ---------------------------------------------------------------------------------------- utilidades
def _cfg(cfg: Any, key: str, default: Any = None) -> Any:
    if cfg is None:
        return default
    try:
        v = cfg.get(key, default)
    except Exception:
        return default
    return default if v is None else v


def _truthy(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "sim", "yes", "on")
    return bool(v)


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii")


def norm_text(s: str | None) -> str:
    """'Flávio Bolsonaro: GTA-6!' -> ' flavio bolsonaro gta 6 ' (para casar termos por palavra inteira)."""
    t = re.sub(r"[^a-z0-9]+", " ", _ascii(s or "").lower()).strip()
    return f" {t} " if t else " "


def normalize(tag: Any) -> str | None:
    """'#GTA 6' -> '#gta6'; 'Seleção' -> '#selecao'. Minusculas, sem acento, so [a-z0-9_]."""
    t = _ascii(str(tag or "")).strip().lstrip("#").lower()
    t = re.sub(r"[^a-z0-9_]", "", t).strip("_")
    if len(t) < 2 or t.isdigit():
        return None
    return "#" + t[:40]


def _strip_emojis(text: str) -> str:
    t = _EMOJI_RE.sub("", text or "")
    return re.sub(r"[ \t]{2,}", " ", t).strip()


def _seed(*parts: Any) -> int:
    return int(hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12], 16)


def _read_json(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except OSError as e:
        log.debug("nao consegui gravar %s: %s", path.name, e)


# ---------------------------------------------------------------------------------------- dados
_DATA: dict | None = None
_DATA_MTIME: float = -1.0


def _item(x: Any) -> tuple[str | None, list[str]]:
    """'#tag' -> ('#tag', []); {'tag': '#tag', 'se': [...]} -> ('#tag', [' termo ', ...])."""
    if isinstance(x, dict):
        return normalize(x.get("tag")), [norm_text(k) for k in (x.get("se") or []) if norm_text(k).strip()]
    return normalize(x), []


def load_data(force: bool = False) -> dict:
    """Le o JSON curado (com cache pela data de modificacao) e pre-normaliza tags e termos."""
    global _DATA, _DATA_MTIME
    try:
        mtime = DATA_FILE.stat().st_mtime
    except OSError:
        mtime = 0.0
    if _DATA is not None and not force and mtime == _DATA_MTIME:
        return _DATA
    raw = _read_json(DATA_FILE)
    if not raw:
        log.warning("hashtags: arquivo de dados ausente ou invalido (%s)", DATA_FILE)
    d: dict = dict(raw)
    nichos: dict[str, dict[str, list[tuple[str, list[str]]]]] = {}
    index: dict[str, tuple[str, str]] = {}           # tag -> (nicho, camada)
    for name, tiers in (raw.get("nichos") or {}).items():
        nichos[name] = {}
        for tier in ("amplas", "medias", "nicho"):
            items = [it for it in (_item(x) for x in (tiers or {}).get(tier, [])) if it[0]]
            nichos[name][tier] = items
            for tag, _ in items:
                index.setdefault(tag, (name, tier))
    d["_nichos"] = nichos
    d["_index"] = index
    d["_ents"] = [it for it in (_item(x) for x in raw.get("entidades") or []) if it[0]]
    d["_banned"] = {normalize(t) for t in raw.get("proibidas") or [] if normalize(t)}
    d["_banned_parts"] = [_ascii(s).lower() for s in raw.get("proibidas_trechos") or []]
    d["_banned_prefix"] = [normalize(s) for s in raw.get("proibidas_prefixos") or [] if normalize(s)]
    d["_trad"] = {normalize(k): normalize(v) for k, v in (raw.get("traducoes") or {}).items()
                  if normalize(k) and normalize(v)}
    d.setdefault("regras", {})
    d.setdefault("aliases_categoria", {})
    d.setdefault("cta", {})
    _DATA, _DATA_MTIME = d, mtime
    return d


def _rule(data: dict, key: str, default: Any) -> Any:
    v = (data.get("regras") or {}).get(key, default)
    return default if v is None else v


# ---------------------------------------------------------------------------------------- filtros
def is_banned(tag: str | None, cfg: Any = None, platform: str = "", data: dict | None = None) -> bool:
    """Proibidas: #fyp/#viral e parecidas, de outra rede, pedido de like/seguir, palavrao, xingamento
    partidario, aposta, conteudo adulto, e as da config publicacao.hashtags_proibidas."""
    if not tag:
        return True
    data = data or load_data()
    t = tag.lower()
    body = t[1:]
    extra = {normalize(x) for x in (_cfg(cfg, "publicacao.hashtags_proibidas", []) or []) if normalize(x)}
    if t in data["_banned"] or t in extra:
        return True
    if any(p and p in body for p in data["_banned_parts"]):
        return True
    if any(t.startswith(p) and len(t) > len(p) for p in data["_banned_prefix"]):
        return True
    if t in ("#shorts", "#short"):
        return True  # o #Shorts do YouTube entra separado no fim; no TikTok nunca
    return False


def _clean_tag(tag: Any, cfg: Any, platform: str, data: dict) -> str | None:
    """Normaliza, traduz generica em ingles para PT, barra proibida e tag longa demais (nichada demais)."""
    t = normalize(tag)
    if not t:
        return None
    t = data["_trad"].get(t, t)
    if is_banned(t, cfg, platform, data):
        return None
    body = t[1:]
    if len(body) > int(_rule(data, "tag_max_chars", 22)) or len(body) < int(_rule(data, "tag_min_chars", 2)):
        return None
    return t


def _dedupe(tags: list[str | None]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for t in tags:
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


# ---------------------------------------------------------------------------------------- contexto
def niche_of(plan: Any, data: dict | None = None) -> str:
    """Categoria do plano -> nicho do JSON (esportes -> futebol, entretenimento -> celebridades...)."""
    data = data or load_data()
    cat = re.sub(r"[^a-z]", "", _ascii(str(getattr(plan, "category", "") or "")).lower())
    if not cat:
        return "geral"
    aliases = data.get("aliases_categoria") or {}
    if cat in aliases:
        return aliases[cat]
    if cat in data["_nichos"]:
        return cat
    for alias, name in aliases.items():
        if alias in cat:
            return name
    return "geral"


def translated_lang(plan: Any, idioma: str | None = None) -> str | None:
    """Codigo do idioma original quando o corte e traduzido (LEGENDADO); 'xx' se so a marca indicar."""
    lang = idioma or getattr(plan, "idioma_origem", None)
    if lang:
        code = str(lang).strip().lower()[:2]
        return None if code in ("", "pt") else code
    cat = _ascii(str(getattr(plan, "category", "") or "")).lower()
    if "legendado" in cat or "traduzido" in cat:
        return "xx"
    if " legendado " in norm_text(getattr(plan, "description", "")):
        return "xx"
    if "LEGENDADO" in _ascii(str(getattr(plan, "title", "") or "")).upper():
        return "xx"
    return None


def _plan_text(plan: Any, video_title: str | None, channel: str | None) -> str:
    parts = [getattr(plan, a, "") or "" for a in ("title", "hook", "description", "series", "teaser_text")]
    parts += [video_title or "", channel or ""]
    parts += [str(h).lstrip("#") for h in (getattr(plan, "hashtags", None) or [])]
    return norm_text(" \n ".join(str(p) for p in parts))


def _matches(text_n: str, terms: list[str]) -> bool:
    return any(t in text_n for t in terms)


def _match_entities(text_n: str, data: dict) -> list[str]:
    """Entidades (pessoa, programa, jogo, time) citadas no texto; o termo mais longo vence
    ('flavio bolsonaro' nao vira tambem #bolsonaro)."""
    hits: list[tuple[int, int, str]] = []
    for tag, terms in data["_ents"]:
        for term in terms:
            for m in re.finditer(re.escape(term), text_n):
                hits.append((m.start(), len(term), tag))
    hits.sort(key=lambda h: (-h[1], h[0]))
    spans: list[tuple[int, int]] = []
    found: list[tuple[int, str]] = []
    for pos, ln, tag in hits:
        a, b = pos, pos + ln
        if any(a < y and x < b for x, y in spans):
            continue
        spans.append((a, b))
        if tag not in (t for _, t in found):
            found.append((pos, tag))
    return [t for _, t in sorted(found)]


# ---------------------------------------------------------------------------------------- em alta
def trending(cfg: Any = None, refresh: bool = False) -> list[dict]:
    """Assuntos em alta no Brasil como hashtags: [{'tag': '#gta6', 'termos': [' gta 6 '], 'fonte': ...}].

    Fonte automatica: os assuntos que a propria descoberta ja coletou (Google Trends, Google News, X)
    nas ultimas 48 h, lidos do banco; cache de 12 h em data/estado/hashtags_trending.json.
    A Central Criativa do TikTok (hashtags em alta por pais) nao e acessivel sem login desta maquina
    (a pagina virou um app JS do TikTok One e a API exige assinatura); por isso ela fica de fora.
    Fonte manual: publicacao.hashtags_em_alta (lista de tags que o dono copiar da Central Criativa).
    Qualquer falha devolve so a lista manual.
    """
    items: list[dict] = []
    if _truthy(_cfg(cfg, "publicacao.hashtags_em_alta_auto", True)):
        cache = _read_json(TRENDING_FILE)
        fresh = cache and (time.time() - float(cache.get("ts", 0) or 0)) < TRENDING_TTL_S
        if fresh and not refresh:
            items = [i for i in cache.get("itens") or [] if isinstance(i, dict) and i.get("tag")]
        else:
            try:
                items = _from_local_trends(cfg)
            except Exception as e:  # nunca derruba a publicacao
                log.debug("hashtags em alta indisponiveis: %s", e)
                items = []
            if items:  # lista vazia nao vai para o cache (tenta de novo na proxima)
                _write_json(TRENDING_FILE, {
                    "ts": time.time(), "gerado_em": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "fonte": "tendencias coletadas pela descoberta (tabela trends, ultimas 48 h)",
                    "central_criativa_tiktok": "indisponivel sem login nesta maquina",
                    "itens": items})
    data = load_data()
    for t in _cfg(cfg, "publicacao.hashtags_em_alta", []) or []:
        tag = _clean_tag(t, cfg, "", data)
        if tag:
            body = tag[1:]
            items.append({"tag": tag, "termos": [f" {body} "], "fonte": "config"})
    return items


def _from_local_trends(cfg: Any, hours: float = 48.0, limit: int = 60) -> list[dict]:
    from . import db  # import tardio: o banco so e aberto se precisar

    data = load_data()
    since = time.time() - hours * 3600
    rows = db.conn().execute(
        "SELECT topic, MAX(score) AS s FROM trends WHERE ts >= ? AND topic IS NOT NULL "
        "GROUP BY lower(topic) ORDER BY s DESC LIMIT ?", (since, int(limit))).fetchall()
    out: list[dict] = []
    for r in rows:
        words = norm_text(r["topic"]).split()
        if not 1 <= len(words) <= 3 or len("".join(words)) < 3:
            continue
        tag = _clean_tag("".join(words), cfg, "", data)
        if not tag or len(tag) > 21:
            continue
        out.append({"tag": tag, "termos": [" " + " ".join(words) + " "], "score": float(r["s"] or 0),
                    "fonte": "trends"})
    return out


def _match_trending(text_n: str, cfg: Any) -> list[str]:
    out: list[str] = []
    for it in trending(cfg):
        terms = [t if t.startswith(" ") else norm_text(t) for t in it.get("termos") or []]
        if terms and _matches(text_n, terms):
            out.append(it["tag"])
        elif it.get("fonte") == "config" and len(it["tag"]) > 5 and it["tag"][1:] in text_n.replace(" ", ""):
            out.append(it["tag"])
    return out


# ---------------------------------------------------------------------------------------- memoria
def _hist(path: Path, platform: str) -> list[dict]:
    h = _read_json(path).get(platform) or []
    return [x for x in h if isinstance(x, dict)]


def _remember(path: Path, platform: str, entry: dict, keep: int) -> None:
    mem = _read_json(path)
    h = [x for x in (mem.get(platform) or []) if isinstance(x, dict) and x.get("id") != entry.get("id")]
    h.append(entry)
    mem[platform] = h[-keep:]
    _write_json(path, mem)


def _sig(*parts: Any) -> str:
    return hashlib.sha1(json.dumps(parts, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------------------- escolha
def platform_limit(platform: str, cfg: Any = None, data: dict | None = None) -> int:
    """Quantas hashtags de assunto (sem contar o #Shorts). publicacao.max_hashtags: numero ou
    {youtube: 3, tiktok: 4, instagram: 3}; padrao 5. TikTok no maximo 5; YouTube no maximo 15 no total."""
    data = data or load_data()
    v = _cfg(cfg, "publicacao.max_hashtags", 5)
    if isinstance(v, dict):
        v = v.get(platform, v.get("padrao", 5))
    try:
        n = int(v)
    except (TypeError, ValueError):
        n = 5
    n = max(0, n)
    if platform == "youtube":
        cap = int((data["regras"].get("youtube") or {}).get("hashtags_max_total", YT_MAX_TOTAL))
        return min(n, min(cap, YT_MAX_TOTAL) - (1 if _shorts_on(cfg) else 0))
    cap = int((data["regras"].get("tiktok") or {}).get("hashtags_max_total", TT_MAX_TOTAL))
    return min(n, cap)


def _shorts_on(cfg: Any) -> bool:
    return _truthy(_cfg(cfg, "publicacao.youtube_hashtag_shorts", True))


def _template(n: int) -> list[str]:
    """Vagas por quantidade. 5 = entidade + ampla + 2 medias + nicho."""
    base = ["ent", "amp", "med", "med", "nic"]
    if n <= 3:
        return base[:n]
    if n == 4:
        return ["ent", "amp", "med", "nic"]
    extra = ["amp", "med", "ent", "nic", "med"]
    out = list(base)
    i = 0
    while len(out) < n:
        out.append(extra[i % len(extra)])
        i += 1
    return out


_FALLBACK = {"ent": ("ent", "nic", "amp", "med"), "amp": ("amp", "med", "ent"),
             "med": ("med", "amp", "ent", "nic"), "nic": ("nic", "ent", "med", "amp")}


def choose(plan: Any, platform: str, cfg: Any, video_title: str | None = None, channel: str | None = None,
           idioma: str | None = None) -> list[str]:
    """Hashtags do post, na ordem (as 3 primeiras aparecem acima do titulo no YouTube).

    Mistura: 1 entidade (pessoa, programa, jogo; do cerebro ou detectada no texto) + 1 ampla + 2 medias
    + 1 de nicho (so as que casam com o texto do corte), mais fixas da config e em alta se relevantes.
    Sem categoria conhecida: confia nas hashtags do cerebro e completa com amplas gerais.
    Respeita publicacao.max_hashtags (TikTok ate 5; YouTube ate 15 com o #Shorts no fim), nunca usa
    proibidas e evita repetir o mesmo conjunto dos ultimos posts da rede (memoria em data/estado).
    """
    platform = (platform or "").lower()
    data = load_data()
    n = platform_limit(platform, cfg, data)
    fixed_raw = list(_cfg(cfg, "publicacao.hashtags_fixas", []) or [])
    sig = _sig(platform, n, getattr(plan, "category", None), getattr(plan, "title", ""), getattr(plan, "hook", ""),
               getattr(plan, "description", ""), list(getattr(plan, "hashtags", None) or []),
               getattr(plan, "idioma_origem", None), idioma, video_title, channel, fixed_raw,
               _cfg(cfg, "publicacao.hashtags_proibidas", []), data.get("_meta", {}).get("versao"))
    pid = str(getattr(plan, "id", "") or "")
    hist = _hist(MEMORY_FILE, platform)
    cached = next((h for h in reversed(hist) if pid and h.get("id") == pid and h.get("sig") == sig), None)
    if cached and isinstance(cached.get("tags"), list):
        tags = [t for t in (normalize(x) for x in cached["tags"]) if t][:n]
    else:
        tags = _compose(plan, platform, cfg, data, n, hist, fixed_raw, video_title, channel, idioma) if n > 0 else []
        if pid and _truthy(_cfg(cfg, "publicacao.hashtags_memoria", True)):
            _remember(MEMORY_FILE, platform, {"id": pid, "sig": sig, "ts": round(time.time()), "tags": tags},
                      int(_rule(data, "memoria_posts", 40)))
    if platform == "youtube" and _shorts_on(cfg):
        tags = tags[: YT_MAX_TOTAL - 1] + [SHORTS_TAG]
    elif platform == "youtube":
        tags = tags[:YT_MAX_TOTAL]
    return tags


def _compose(plan: Any, platform: str, cfg: Any, data: dict, n: int, hist: list[dict], fixed_raw: list,
             video_title: str | None, channel: str | None, idioma: str | None) -> list[str]:
    pid = str(getattr(plan, "id", "") or "")
    rng = random.Random(_seed(pid, platform, "tags"))
    text_n = _plan_text(plan, video_title, channel)
    niche = niche_of(plan, data)
    lang = translated_lang(plan, idioma)
    window = int(_rule(data, "rodizio_janela_posts", 12))
    uses: dict[str, int] = {}
    for h in hist[-window:]:
        for t in h.get("tags") or []:
            uses[str(t).lower()] = uses.get(str(t).lower(), 0) + 1

    def rotate(tags: list[str]) -> list[str]:
        keyed = [(uses.get(t, 0), rng.random(), t) for t in tags]
        return [t for _, _, t in sorted(keyed)]

    fixed = _dedupe([_clean_tag(t, cfg, platform, data) for t in fixed_raw])
    brain = _dedupe([_clean_tag(t, cfg, platform, data) for t in (getattr(plan, "hashtags", None) or [])])
    ents = _match_entities(text_n, data)
    trend = [t for t in _match_trending(text_n, cfg) if not is_banned(t, cfg, platform, data)]
    leg = normalize((data.get("extras") or {}).get("legendado")) if lang else None

    if niche == "geral" or niche not in data["_nichos"]:
        geral = data["_nichos"].get("geral") or {}
        amp = rotate([t for t, terms in geral.get("amplas", []) if not terms or _matches(text_n, terms)])
        med = rotate([t for t, terms in geral.get("medias", []) if not terms or _matches(text_n, terms)])
        order = brain + fixed + ents + trend + ([leg] if leg else []) + amp + med
        return _dedupe(order)[:n]

    tiers = data["_nichos"][niche]
    index = data["_index"]

    def tier_pool(tier: str) -> list[str]:
        matched = [t for t, terms in tiers.get(tier, []) if terms and _matches(text_n, terms)]
        plain = [t for t, terms in tiers.get(tier, []) if not terms]
        brain_here = [b for b in brain if index.get(b) == (niche, tier)]
        return _dedupe(brain_here + rotate(matched) + rotate(plain))

    brain_other = [b for b in brain if b in index and index[b][0] != niche]   # tag de outro nicho: vira media
    brain_ent = [b for b in brain if b not in index]                           # desconhecida: pessoa/jogo/programa
    medias = tier_pool("medias")
    pools = {
        "ent": _dedupe(brain_ent + ents + trend),
        "amp": tier_pool("amplas"),
        "med": _dedupe(medias[:2] + brain_other + medias[2:]),
        "nic": _dedupe(([leg] if leg else []) + tier_pool("nicho")),
    }
    # o template limita quantas entidades entram (1 vaga propria + sobra do nicho); o resto vem das camadas
    chosen: list[tuple[str, str]] = []
    used: set[str] = set()
    for slot in _template(n):
        for pool_name in _FALLBACK[slot]:
            tag = next((t for t in pools[pool_name] if t not in used), None)
            if tag:
                chosen.append((tag, pool_name))
                used.add(tag)
                break
    if fixed:  # fixas da config entram logo depois da primeira (o resto e cortado no limite)
        rest = [c for c in chosen if c[0] not in fixed]
        chosen = rest[:1] + [(f, "fix") for f in fixed] + rest[1:]
        chosen = chosen[:n]
    chosen = _avoid_repeat(chosen, pools, hist, data)
    return [t for t, _ in chosen][:n]


def _avoid_repeat(chosen: list[tuple[str, str]], pools: dict[str, list[str]], hist: list[dict],
                  data: dict) -> list[tuple[str, str]]:
    """Se o conjunto for identico a um dos ultimos posts, troca uma ampla/media por outra da mesma camada."""
    k = int(_rule(data, "sem_repetir_conjunto_ultimos", 6))
    recent = [frozenset(str(t).lower() for t in h.get("tags") or []) for h in hist[-k:]]
    cur = frozenset(t for t, _ in chosen)
    if not recent or cur not in recent:
        return chosen
    fallback = None  # se nao der para fugir de todos, pelo menos difere do ultimo post
    for i in range(len(chosen) - 1, -1, -1):
        tag, pool_name = chosen[i]
        if pool_name not in ("amp", "med"):
            continue
        for alt in pools[pool_name]:
            if alt in cur:
                continue
            cand = cur - {tag} | {alt}
            trial = chosen[:i] + [(alt, pool_name)] + chosen[i + 1:]
            if cand not in recent:
                return trial
            if fallback is None and cand != recent[-1]:
                fallback = trial
    return fallback or chosen


# ---------------------------------------------------------------------------------------- CTA
def _series(plan: Any) -> tuple[int | None, int | None]:
    part = getattr(plan, "part", None)
    total = getattr(plan, "parts_total", None)
    try:
        part = int(part) if part else None
        total = int(total) if total else None
    except (TypeError, ValueError):
        return None, None
    if part and ((total and total > 1) or part > 1):
        return part, total
    return None, None


def _pick(pool: list[str], recent: list[str], rng: random.Random) -> str:
    pool = [p for p in pool if p]
    if not pool:
        return ""
    fresh = [p for p in pool if p not in recent]
    if not fresh:  # todas usadas: pega a que saiu ha mais tempo
        last = {p: max(i for i, r in enumerate(recent) if r == p) for p in pool}
        return min(pool, key=lambda p: (last[p], rng.random()))
    return rng.choice(fresh)


def _ask_follow(platform: str, cfg: Any, data: dict) -> bool:
    """publicacao.cta_pedir_seguir: youtube (padrao) | sempre | nunca. No TikTok, pedir follow em troca
    da proxima parte pode tirar o video do Para Voce (regra de manipulacao de engajamento)."""
    default = (data.get("cta") or {}).get("_regras", {}).get("pedir_seguir", "youtube")
    mode = str(_cfg(cfg, "publicacao.cta_pedir_seguir", default) or default).strip().lower()
    if mode in ("sempre", "always", "true", "sim"):
        return True
    if mode in ("nunca", "never", "false", "nao"):
        return False
    return platform == "youtube"


TONES = ("neutro", "polemico", "malicioso", "super_polemico", "modo_besta")


def tone(cfg: Any, plan: Any = None, data: dict | None = None) -> str:
    """Nivel do tom (fabrica/tom.py, conteudo.tom_titulo): neutro | polemico | malicioso (padrao) |
    super_polemico | modo_besta. Em politica e noticias o teto e "polemico": insinuacao e ragebait ali
    viram desinformacao e risco de remocao."""
    data = data or load_data()
    rules = (data.get("cta") or {}).get("_regras") or {}
    try:
        from . import tom as tom_mod
        t = tom_mod.level(cfg)
    except Exception:  # modulo de tom ausente: le a chave direto
        t = _ascii(str(_cfg(cfg, "conteudo.tom_titulo", rules.get("tom_padrao", "malicioso")) or "")).strip().lower()
    t = t if t in TONES else "malicioso"
    if plan is not None:
        cap = (rules.get("nichos_tom_maximo") or {}).get(niche_of(plan, data))
        if cap in TONES and TONES.index(t) > TONES.index(cap):
            return cap
    return t


def tone_capped(plan: Any, data: dict | None = None) -> bool:
    """True se o nicho do plano tem teto de tom (politica, noticias)."""
    data = data or load_data()
    caps = ((data.get("cta") or {}).get("_regras") or {}).get("nichos_tom_maximo") or {}
    return niche_of(plan, data) in caps


def tone_settings(cfg: Any) -> dict:
    """tom.settings(cfg) com reserva (intensidade 0 a 4, palavroes, max_emojis, guia, piso)."""
    try:
        from . import tom as tom_mod
        return tom_mod.settings(cfg)
    except Exception:
        lv = tone(cfg)
        return {"nivel": lv, "intensidade": TONES.index(lv), "max_emojis": 2, "guia": "", "piso": "",
                "palavroes": str(_cfg(cfg, "conteudo.palavroes", "mascarar") or "mascarar")}


def cta(plan: Any, platform: str, cfg: Any) -> str:
    """Chamada para acao do post (ultima linha antes das hashtags). Pode ser "" (30% dos posts sem CTA).

    Serie: "Parte X/Y, continua na parte X+1" (ou "segue pra ver a proxima" no YouTube);
    ultima parte: "Parte Y/Y, a ultima...". Fora de serie: pergunta de escolha do nicho, sem repetir
    nenhuma das ultimas ~10 da rede. Nunca "curte", "deixa o like" ou "segue pra mais".
    Tom (conteudo.tom_titulo): malicioso mistura insinuacao/curiosidade dirigida ao espectador
    ("Comenta o que voce entendeu"), polemico mistura perguntas de lado, neutro so perguntas do nicho.
    Nenhuma frase afirma algo sobre a pessoa do corte (o CTA nao "le" o video).
    """
    platform = (platform or "").lower()
    data = load_data()
    lib = data.get("cta") or {}
    rules = lib.get("_regras") or {}
    emojis = _truthy(_cfg(cfg, "conteudo.emojis", True))
    niche = niche_of(plan, data)
    lang = translated_lang(plan)
    part, total = _series(plan)
    pid = str(getattr(plan, "id", "") or "")
    keep = int(_cfg(cfg, "publicacao.cta_nao_repetir", rules.get("nao_repetir_ultimos", 10)) or 10)
    prob = float(_cfg(cfg, "publicacao.cta_sem_prob", rules.get("prob_sem_cta", 0.3)))
    follow = _ask_follow(platform, cfg, data)
    tom = tone(cfg, plan, data)
    probs = list(rules.get("tom_prob_por_intensidade") or [0.0, 0.5, 0.6, 0.75, 0.9])
    tone_prob = float(probs[min(TONES.index(tom), len(probs) - 1)]) if probs else 0.6
    sig = _sig(platform, niche, part, total, bool(lang), prob, follow, tom, data.get("_meta", {}).get("versao"))
    hist = _hist(CTA_MEMORY_FILE, platform)
    cached = next((h for h in reversed(hist) if pid and h.get("id") == pid and h.get("sig") == sig), None)
    if cached is not None and isinstance(cached.get("texto"), str):
        text = cached["texto"]
    else:
        rng = random.Random(_seed(pid, platform, "cta"))
        recent = [str(h.get("cta")) for h in hist if h.get("cta")][-keep:]   # ultimas N CTAs usadas
        serie = lib.get("serie") or {}
        questions = list((lib.get("por_nicho") or {}).get(niche) or []) + list(lib.get("universal") or [])
        if lang:
            questions = list(lib.get("legendado") or []) + questions
        toned = list((lib.get("tons") or {}).get(tom) or [])
        if toned and rng.random() < tone_prob:  # maioria no tom pedido, o resto pergunta do nicho
            questions = toned
        key = ""
        if part and total and part < total:
            pool = list(serie.get("neutras") or []) + (list(serie.get("seguir") or []) if follow else [])
            pool += list((lib.get("tons_serie") or {}).get(tom) or [])
            key = _pick(pool, recent, rng)
            text = f"Parte {part}/{total}, " + key.format(prox=part + 1) if key else f"Parte {part}/{total}"
        elif part and total:
            key = _pick(list(serie.get("final") or []), recent, rng)
            text = f"Parte {part}/{total}, " + key if key else f"Parte {part}/{total}"
        elif part:
            key = _pick(questions, recent, rng)
            text = f"Parte {part}. {key}".strip()
        elif rng.random() < prob:
            text = ""
        else:
            key = _pick(questions, recent, rng)
            text = key
        if pid and _truthy(_cfg(cfg, "publicacao.hashtags_memoria", True)):
            _remember(CTA_MEMORY_FILE, platform, {"id": pid, "sig": sig, "ts": round(time.time()), "cta": key,
                                                  "texto": text}, max(keep * 3, 30))
    if not emojis:
        text = _strip_emojis(text)
    text = _mask_library_profanity(text)
    return re.sub(r"\s+", " ", text).strip()


def _mask_library_profanity(text: str) -> str:
    """Palavrao de CTA da biblioteca nunca foi dito no corte: sai sempre mascarado (p*to), em qualquer tom."""
    if not text:
        return text
    try:
        from .brain.base import mask_profanity
    except Exception:
        return text
    return mask_profanity(text, "mascarar")
