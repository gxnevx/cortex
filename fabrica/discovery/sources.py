"""Fontes publicas de assuntos em alta (sem API key). Cada fonte devolve list[RawTrend] e nunca levanta.

Verificado em nov/2026 a partir do Brasil:
- Google Trends: pagina https://trends.google.com/trending?geo=BR (JSON embutido "ds:0", ~300 assuntos com
  volume de buscas, categorias e consultas relacionadas) + RSS https://trends.google.com/trending/rss?geo=BR
  (10 assuntos com manchetes). O RSS antigo /trends/trendingsearches/daily/rss da 404.
- Google News RSS pt-BR (topo + secoes) funciona.
- X/Twitter: trends24.in/brazil (24 cartoes por hora) funciona; getdaytrends.com/brazil como reserva.
- Reddit: www/old/api.reddit.com respondem 403 ("blocked by network security") e os feeds .rss 404/429 sem
  login. Usamos o JSON oficial quando der e, senao, o espelho publico arctic-shift.photon-reddit.com
  (comentarios recentes por post = "quentes agora").
"""
from __future__ import annotations

import json
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import quote

from .. import log
from . import net
from .text import clean_topic, norm, short_query, strip_accents

_log = log.get(__name__)


@dataclass
class RawTrend:
    topic: str
    source: str                      # google_trends | google_news | x_trends | reddit
    s: float                         # forca dentro da fonte (0-1)
    kind: str = "short"              # short (assunto curto) | headline (manchete/titulo longo)
    traffic: str | None = None
    volume: float | None = None      # numero bruto (buscas, posts, comentarios)
    related: list[str] = field(default_factory=list)
    url: str | None = None
    category: str | None = None
    started_ts: float | None = None


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def fmt_traffic(v: float | None, unit: str = "") -> str | None:
    if not v:
        return None
    if v >= 1e6:
        txt = f"{v / 1e6:.1f}".rstrip("0").rstrip(".").replace(".", ",") + " mi"
    elif v >= 1e3:
        txt = f"{int(v // 1000)} mil"
    else:
        txt = str(int(v))
    return f"{txt}{unit}"


# ============================================================ Google Trends
# ids de categoria do Google Trends -> temas do projeto
GT_CATEGORIES = {
    1: "autos", 2: "moda", 3: "economia", 4: "entretenimento", 5: "comida", 6: "games", 7: "saude",
    8: "hobbies", 9: "educacao", 10: "politica", 11: "noticias", 13: "pets", 14: "politica", 15: "ciencia",
    16: "compras", 17: "esportes", 18: "tecnologia", 19: "viagem", 20: "clima",
}


def _gt_page(geo: str, hl: str, hours: int) -> list[RawTrend]:
    r = net.get("https://trends.google.com/trending", params={"geo": geo, "hl": hl, "hours": hours},
                timeout=20, what="google_trends")
    if not r:
        return []
    m = re.search(r"AF_initDataCallback\(\{key: 'ds:0'.*?data:(.*?), sideChannel: \{\}\}\);</script>", r.text, re.S)
    if not m:
        _log.info("google_trends: bloco ds:0 nao encontrado na pagina")
        return []
    try:
        items = json.loads(m.group(1))[1] or []
    except (ValueError, IndexError, TypeError) as e:
        _log.info("google_trends: JSON inesperado: %s", e)
        return []
    out: list[RawTrend] = []
    for it in items:
        try:
            topic = str(it[0]).strip()
            vol = float(it[6] or 0)
            ended = bool(it[4])
            started = float(it[3][0]) if it[3] else None
            related = [str(x) for x in (it[9] or []) if str(x).strip() and norm(str(x)) != norm(topic)]
            cats = [c for c in (it[10] or []) if isinstance(c, int)]
        except (IndexError, TypeError, ValueError):
            continue
        if not topic:
            continue
        s = _clamp((math.log10(max(vol, 1.0)) - 2.5) / 3.2)
        if ended:
            s *= 0.85
        out.append(RawTrend(
            topic=topic, source="google_trends", s=s, traffic=(fmt_traffic(vol, "+") or "") + " buscas" if vol else None,
            volume=vol, related=related[:8], category=GT_CATEGORIES.get(cats[0]) if cats else None,
            url=f"https://trends.google.com/trends/explore?geo={geo}&q={quote(topic)}&date=now%201-d",
            started_ts=started,
        ))
    return out


def _gt_rss(geo: str) -> list[RawTrend]:
    r = net.get("https://trends.google.com/trending/rss", params={"geo": geo}, timeout=15, what="google_trends_rss")
    if not r:
        return []
    try:
        from lxml import etree

        root = etree.fromstring(r.content)
    except Exception as e:  # noqa: BLE001
        _log.info("google_trends rss: XML invalido: %s", e)
        return []
    ns = {"ht": "https://trends.google.com/trending/rss"}
    out = []
    for item in root.iter("item"):
        topic = (item.findtext("title") or "").strip()
        if not topic:
            continue
        traffic = (item.findtext("ht:approx_traffic", namespaces=ns) or "").strip()
        vol = float(re.sub(r"[^\d]", "", traffic) or 0)
        news = []
        url = None
        for ni in item.findall("ht:news_item", ns):
            t = (ni.findtext("ht:news_item_title", namespaces=ns) or "").strip()
            if t:
                news.append(t)
            url = url or (ni.findtext("ht:news_item_url", namespaces=ns) or "").strip() or None
        out.append(RawTrend(topic=topic, source="google_trends",
                            s=_clamp((math.log10(max(vol, 1.0)) - 2.5) / 3.2),
                            traffic=(fmt_traffic(vol, "+") + " buscas") if vol else None, volume=vol,
                            related=news[:5], url=url))
    return out


def google_trends(cfg) -> list[RawTrend]:
    """Assuntos mais buscados no Google (BR) nas ultimas 24 h."""
    try:
        geo = str(cfg.get("busca.pais", "BR") or "BR").upper()
        hl = "pt-BR" if str(cfg.get("busca.idioma", "pt")).startswith("pt") else str(cfg.get("busca.idioma"))
        hours = int(cfg.get("busca.google_trends_horas", 24))
        page = _gt_page(geo, hl, hours)
        rss = _gt_rss(geo)
        by_norm = {norm(t.topic): t for t in page}
        for t in rss:  # RSS traz manchetes: junta no item da pagina
            k = norm(t.topic)
            if k in by_norm:
                p = by_norm[k]
                p.related = (t.related + p.related)[:10]
                p.url = t.url or p.url
            else:
                page.append(t)
        page.sort(key=lambda t: -t.s)
        out = page[: int(cfg.get("busca.google_trends_max", 60))]
        _log.info("google_trends: %d assuntos (pagina=%d, rss=%d)", len(out), len(by_norm), len(rss))
        return out
    except Exception as e:  # noqa: BLE001
        _log.warning("google_trends falhou: %s", e)
        return []


# ============================================================ Google News
GN_SECTIONS = {
    "topo": (None, None),
    "brasil": ("NATION", "noticias"),
    "entretenimento": ("ENTERTAINMENT", "entretenimento"),
    "esportes": ("SPORTS", "esportes"),
    "tecnologia": ("TECHNOLOGY", "tecnologia"),
    "mundo": ("WORLD", "noticias"),
    "economia": ("BUSINESS", "economia"),
}


def _gn_feed(section: str, geo: str, n: int) -> list[RawTrend]:
    import feedparser

    topic_id, cat = GN_SECTIONS.get(section, (None, None))
    qs = f"hl=pt-BR&gl={geo}&ceid={geo}:pt-419"
    url = (f"https://news.google.com/rss/headlines/section/topic/{topic_id}?{qs}" if topic_id
           else f"https://news.google.com/rss?{qs}")
    r = net.get(url, timeout=15, what=f"google_news/{section}")
    if not r:
        return []
    feed = feedparser.parse(r.content)
    out = []
    base = 0.95 if section == "topo" else 0.8
    step = 0.03 if section == "topo" else 0.04
    for i, e in enumerate(feed.entries[:n]):
        title = (e.get("title") or "").strip()
        src = ((e.get("source") or {}).get("title") or "").strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3].strip()
        if not title:
            continue
        related = []
        desc = e.get("summary") or ""
        if "<li" in desc:
            for m in re.finditer(r"<a [^>]*>(.*?)</a>", desc):
                t = re.sub(r"<[^>]+>", "", m.group(1)).strip()
                if t and norm(t) != norm(title):
                    related.append(t)
        s = _clamp(base - step * i + 0.03 * min(5, len(related)))
        out.append(RawTrend(topic=title, source="google_news", s=s, kind="headline", related=related[:5],
                            url=e.get("link"), category=cat, volume=float(len(related) + 1)))
    return out


def google_news(cfg) -> list[RawTrend]:
    """Manchetes em destaque no Google Noticias (pt-BR)."""
    try:
        geo = str(cfg.get("busca.pais", "BR") or "BR").upper()
        sections = cfg.get("busca.google_news_secoes", ["topo", "brasil", "entretenimento", "esportes", "tecnologia"])
        out: list[RawTrend] = []
        for sec in sections or []:
            out.extend(_gn_feed(str(sec), geo, 15 if sec == "topo" else 8))
        _log.info("google_news: %d manchetes", len(out))
        return out
    except Exception as e:  # noqa: BLE001
        _log.warning("google_news falhou: %s", e)
        return []


# ============================================================ X / Twitter
_X_COUNTRY = {"BR": "brazil", "PT": "portugal", "US": "united-states"}


def _trends24(country: str) -> list[RawTrend]:
    from bs4 import BeautifulSoup

    r = net.get(f"https://trends24.in/{country}/", timeout=15, what="trends24")
    if not r:
        return []
    soup = BeautifulSoup(r.content, "lxml")
    cards = soup.select(".list-container")[:24]
    if not cards:
        return []
    stats: dict[str, dict] = {}
    for ci, card in enumerate(cards):  # cartao 0 = hora mais recente
        for rank, li in enumerate(card.select("li"), 1):
            a = li.select_one("a.trend-link") or li.select_one("a")
            if not a:
                continue
            name = a.get_text(strip=True)
            if not name:
                continue
            cnt_el = li.select_one(".tweet-count")
            cnt = 0
            if cnt_el is not None:
                raw = (cnt_el.get("data-count") or "").strip()
                cnt = int(raw) if raw.isdigit() else 0
            st = stats.setdefault(norm(name) or name, {"name": name, "hours": 0, "best": 99, "latest": None, "count": 0})
            st["hours"] += 1
            st["best"] = min(st["best"], rank)
            st["count"] = max(st["count"], cnt)
            if ci == 0:
                st["latest"] = rank
            elif ci <= 2 and st["latest"] is None:
                st["latest"] = rank + 5  # estava no topo ha 1-2 horas
    out = []
    for st in stats.values():
        rl = st["latest"]
        s = (0.45 * (1 - (min(rl, 50) - 1) / 50) if rl else 0.0) + 0.35 * min(1.0, st["hours"] / 10) \
            + 0.2 * _clamp((math.log10(st["count"]) - 3) / 3 if st["count"] else 0)
        if not rl and st["hours"] < 3:
            continue
        out.append(RawTrend(topic=clean_topic(st["name"]), source="x_trends", s=_clamp(s),
                            traffic=(fmt_traffic(st["count"]) + " posts") if st["count"] else None,
                            volume=float(st["count"] or 0),
                            url=f"https://x.com/search?q={quote(st['name'])}",
                            related=[st["name"]] if st["name"].startswith("#") else []))
    out.sort(key=lambda t: -t.s)
    return out[:40]


def _getdaytrends(country: str) -> list[RawTrend]:
    from bs4 import BeautifulSoup

    r = net.get(f"https://getdaytrends.com/{country}/", timeout=15, what="getdaytrends")
    if not r:
        return []
    soup = BeautifulSoup(r.content, "lxml")
    table = soup.select_one("table")
    if not table:
        return []
    out = []
    for rank, tr in enumerate(table.select("tr"), 1):
        a = tr.select_one("td.main a")
        if not a:
            continue
        name = a.get_text(strip=True)
        desc = tr.select_one("td.main .desc")
        cnt = None
        if desc:
            from .text import parse_count

            cnt = parse_count(desc.get_text(" ", strip=True))
        s = 0.45 * (1 - (min(rank, 50) - 1) / 50) + 0.15 + 0.2 * _clamp((math.log10(cnt) - 3) / 3 if cnt else 0)
        out.append(RawTrend(topic=clean_topic(name), source="x_trends", s=_clamp(s),
                            traffic=(fmt_traffic(cnt) + " posts") if cnt else None, volume=float(cnt or 0),
                            url=f"https://x.com/search?q={quote(name)}"))
    return out[:40]


def x_trends(cfg) -> list[RawTrend]:
    """Trending topics do X no Brasil (via trends24.in, reserva getdaytrends.com)."""
    try:
        country = _X_COUNTRY.get(str(cfg.get("busca.pais", "BR")).upper(), "brazil")
        out = _trends24(country)
        if not out:
            out = _getdaytrends(country)
        _log.info("x_trends: %d assuntos", len(out))
        return out
    except Exception as e:  # noqa: BLE001
        _log.warning("x_trends falhou: %s", e)
        return []


# ============================================================ Reddit
REDDIT_SUBS = {
    "brasil": "noticias", "futebol": "esportes", "gamesEcultura": "games", "conversas": "entretenimento",
    "brasilivre": "politica",
}
_ARCTIC = "https://arctic-shift.photon-reddit.com/api"
_reddit_official_blocked = False


def _clean_reddit_title(t: str) -> str:
    t = re.sub(r"^\s*\[[^\]]{1,40}\]\s*", "", t or "")
    return re.sub(r"\s+", " ", t).strip()


def _reddit_official(sub: str) -> list[RawTrend] | None:
    """None = bloqueado (usar espelho)."""
    global _reddit_official_blocked
    if _reddit_official_blocked:
        return None
    try:
        r = net.session().get(f"https://www.reddit.com/r/{sub}/hot.json", params={"limit": 25, "raw_json": 1},
                              headers={"User-Agent": net.UA_BOT}, timeout=12, allow_redirects=False)
    except Exception as e:  # noqa: BLE001
        _log.info("reddit oficial %s: %s", sub, e)
        return None
    if r.status_code != 200 or "json" not in (r.headers.get("content-type") or ""):
        _reddit_official_blocked = True
        _log.info("reddit oficial bloqueado (HTTP %s); usando arctic-shift", r.status_code)
        return None
    out = []
    try:
        children = r.json()["data"]["children"]
    except (ValueError, KeyError, TypeError):
        return None
    for ch in children:
        d = ch.get("data") or {}
        if d.get("stickied"):
            continue
        act = (d.get("score") or 0) + 2 * (d.get("num_comments") or 0)
        out.append(RawTrend(topic=_clean_reddit_title(d.get("title", "")), source="reddit", kind="headline",
                            s=_clamp(math.log10(act + 1) / 4), volume=float(d.get("num_comments") or 0),
                            traffic=f"{d.get('num_comments') or 0} comentarios",
                            url="https://www.reddit.com" + (d.get("permalink") or ""), category=REDDIT_SUBS.get(sub)))
    return out


def _reddit_arctic(sub: str, hours: float = 12, top: int = 6) -> list[RawTrend]:
    after = int(time.time() - hours * 3600)
    r = net.get(f"{_ARCTIC}/comments/search", params={"subreddit": sub, "after": after, "limit": 100,
                                                      "sort": "desc", "fields": "link_id,created_utc"},
                headers={"User-Agent": net.UA_BOT}, timeout=20, what=f"arctic/{sub}")
    if not r:
        return []
    try:
        data = r.json().get("data") or []
    except ValueError:
        return []
    if not data:
        return []
    cnt = Counter(str(x.get("link_id", "")).split("_")[-1] for x in data if x.get("link_id"))
    span_h = max(0.5, (data[0].get("created_utc", 0) - data[-1].get("created_utc", 0)) / 3600)
    ids = [k for k, _ in cnt.most_common(top)]
    if not ids:
        return []
    r2 = net.get(f"{_ARCTIC}/posts/ids", params={"ids": ",".join(ids), "fields": "id,title,created_utc,permalink"},
                 headers={"User-Agent": net.UA_BOT}, timeout=20, what=f"arctic/{sub}/posts")
    posts = {}
    if r2:
        try:
            posts = {p["id"]: p for p in r2.json().get("data") or []}
        except (ValueError, KeyError, TypeError):
            posts = {}
    out = []
    for pid in ids:
        p = posts.get(pid)
        if not p:
            continue
        c = cnt[pid]
        per_h = c / span_h
        title = _clean_reddit_title(p.get("title", ""))
        if not title:
            continue
        out.append(RawTrend(topic=title, source="reddit", kind="headline",
                            s=_clamp(0.25 + 0.6 * math.log10(per_h + 1) / math.log10(15)),
                            volume=float(c), traffic=f"{c} comentarios recentes",
                            url=f"https://www.reddit.com/r/{sub}/comments/{pid}", category=REDDIT_SUBS.get(sub)))
    return out


def reddit(cfg) -> list[RawTrend]:
    """Posts mais quentes de subreddits brasileiros."""
    try:
        import concurrent.futures as cf

        subs = cfg.get("busca.reddit_subs", list(REDDIT_SUBS)) or []

        def one(sub: str) -> list[RawTrend]:
            got = _reddit_official(sub)
            return _reddit_arctic(sub) if got is None else got

        out: list[RawTrend] = []
        if subs:
            first = one(subs[0])  # descobre se o oficial esta bloqueado antes de paralelizar
            out.extend(first)
            with cf.ThreadPoolExecutor(max_workers=3) as ex:
                for got in ex.map(one, subs[1:]):
                    out.extend(got)
        _log.info("reddit: %d posts", len(out))
        return out
    except Exception as e:  # noqa: BLE001
        _log.warning("reddit falhou: %s", e)
        return []


SOURCES = {
    "google_trends": google_trends,
    "google_news": google_news,
    "x_trends": x_trends,
    "reddit": reddit,
}

# peso de cada fonte na nota final
SOURCE_WEIGHT = {"google_trends": 1.0, "x_trends": 0.9, "google_news": 0.8, "reddit": 0.6}

GENERIC_TOPICS = {strip_accents(w) for w in """
morte renda tempo jogo jogos hoje previsao resultado resultados noticias noticia video videos ao vivo clima
climatempo placar tabela classificacao horario onde assistir brasil
""".split()}


def topic_is_specific(topic: str) -> bool:
    n = norm(topic)
    if n in GENERIC_TOPICS:
        return False
    toks = [t for t in n.split() if t not in GENERIC_TOPICS]
    if not toks:
        return False
    if len(toks) == 1:
        return len(toks[0]) >= 6
    return True


__all__ = ["RawTrend", "SOURCES", "SOURCE_WEIGHT", "short_query", "topic_is_specific"]
