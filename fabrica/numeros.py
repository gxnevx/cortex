"""Numeros de cada post, lidos nas paginas do PROPRIO canal (YouTube Studio, TikTok Studio e perfil do Instagram). So leitura.

Guarda uma linha por leitura em post_numeros: views, curtidas, comentarios, compartilhamentos, % que continuou
assistindo, tempo medio, % que viu ate o fim, novos seguidores. E a base dos testes A/B (experimentos.py) e do
analista (analista.py).
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from . import db, log, metrics

_log = log.get("numeros")

SCHEMA = """
CREATE TABLE IF NOT EXISTS post_numeros (
    id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER, clip_id TEXT, platform TEXT, ts REAL, idade_h REAL,
    views INTEGER, likes INTEGER, comments INTEGER, shares INTEGER,
    ficou_pct REAL, tempo_medio_s REAL, completo_pct REAL, seguidores INTEGER, extra TEXT
);
CREATE INDEX IF NOT EXISTS idx_post_numeros ON post_numeros(post_id, ts);
"""


def _conn():
    c = db.conn()
    c.executescript(SCHEMA)
    return c


# ------------------------------------------------------------------ leitura de texto
def num(s: Any) -> float | None:
    """'1.234' -> 1234 | '1,2 mil' -> 1200 | '12K' -> 12000 | '60,0%' -> 60.0 | '7.29s' -> 7.29"""
    t = str(s or "").strip().lower().replace(" ", " ")
    m = re.match(r"^([\d.,]+)\s*(mil|mi|milh[õo]es|k|m|b)?\s*[%s]?$", t)
    if not m:
        return None
    raw, suf = m.group(1), m.group(2)
    if suf or t.endswith(("%", "s")):                 # decimal
        raw = raw.replace(".", "").replace(",", ".") if "," in raw else raw
    elif re.fullmatch(r"\d{1,3}([.,]\d{3})+", raw):   # milhar
        raw = re.sub(r"[.,]", "", raw)
    else:
        raw = raw.replace(",", ".")
    try:
        v = float(raw)
    except ValueError:
        return None
    return v * {"mil": 1e3, "k": 1e3, "mi": 1e6, "m": 1e6, "milhões": 1e6, "milhoes": 1e6, "b": 1e9}.get(suf or "", 1)


def _after(lines: list[str], rx: str, skip: str = r"^(desde a publica|since published|últimos|ultimos)", start: int = 0) -> float | None:
    """Primeiro numero logo depois de um rotulo."""
    for i in range(start, len(lines)):
        if re.search(rx, lines[i], re.I):
            for x in lines[i + 1:i + 4]:
                if re.search(skip, x, re.I):
                    continue
                v = num(x)
                if v is not None:
                    return v
                break
    return None


def _before(lines: list[str], rx: str) -> float | None:
    """Numero na linha imediatamente antes do rotulo ('60,0%' / 'Continuaram a ver')."""
    for i in range(1, len(lines)):
        if re.search(rx, lines[i], re.I):
            v = num(lines[i - 1])
            if v is not None:
                return v
    return None


def parse_youtube(text: str) -> dict:
    L = [x.strip() for x in (text or "").split("\n") if x.strip()]
    top = next((i for i, x in enumerate(L) if re.search(r"principais m[eé]tricas|key metrics", x, re.I)), 0)
    views = _after(L, r"^(visualiza[cç][oõ]es|views)$", start=top)
    horas = _after(L, r"^(tempo de visualiza[cç][aã]o|tempo de exibi[cç][aã]o|watch time) \((horas|hours)\)", start=top)
    out = {"views": views, "likes": _after(L, r"^(gostos|marca[cç][oõ]es .?gostei.?|curtidas|likes)$", start=top),
           "seguidores": _after(L, r"^(subscritores|inscritos|subscribers)$", start=top),
           "ficou_pct": _before(L, r"^(continuaram a ver|continuaram assistindo|stayed to watch|assistiram|viewed)")}
    if views and horas is not None and horas > 0:
        out["tempo_medio_s"] = round(horas * 3600 / views, 1)
    feed = _after(L, r"^(feed do shorts|shorts feed)$", start=top)
    if feed is not None:
        out["extra"] = {"feed_60min": feed}
    return out


def parse_tiktok(text: str) -> dict:
    L = [x.strip() for x in (text or "").split("\n") if x.strip()]
    out: dict = {}
    for i, x in enumerate(L):
        if re.search(r"^(publicado|posted)\b", x, re.I):
            vals = []
            for y in L[i + 1:i + 6]:
                v = num(y)
                if v is None:
                    break
                vals.append(v)
            for k, v in zip(("views", "likes", "comments", "shares", "salvos"), vals):
                out[k] = v
            break
    out["tempo_medio_s"] = _after(L, r"^(tempo m[eé]dio|average watch)")
    out["completo_pct"] = _after(L, r"^(assistiu ao v[ií]deo completo|assistiram ao v[ií]deo completo|watched full)")
    out["seguidores"] = _after(L, r"^(novos seguidores|new followers)")
    m = re.search(r"(?:aos|at|em)\s+(\d+):(\d\d)\.", text or "")
    extra = {"para_em_s": int(m.group(1)) * 60 + int(m.group(2))} if m else {}
    if out.pop("salvos", None) is not None:
        pass
    if extra:
        out["extra"] = extra
    return out


def parse_instagram(grade: str, hover: str = "") -> dict:
    """Cartao do reel no perfil: visualizacoes; com o mouse em cima: curtidas e comentarios."""
    v = [x for x in (num(t) for t in (grade or "").split("\n")) if x is not None]
    h = [x for x in (num(t) for t in (hover or "").split("\n")) if x is not None]
    out: dict = {"views": v[0] if v else None}
    if len(h) >= 2:
        out["likes"], out["comments"] = h[0], h[1]
    return out


def _read_instagram(page: Any, code: str, cfg: Any, cache: dict) -> dict:
    """Le a aba Reels do perfil uma vez por varredura."""
    from .publish import instagram

    want = instagram.handle(cfg)
    if not want:
        return {}
    if "grade" not in cache:
        cache["grade"] = {r["code"]: r["text"] for r in instagram.list_reels(page, want)}
    if code not in cache["grade"]:
        return {}
    hover = ""
    try:
        a = page.locator(f'a[href*="/reel/{code}"]').first
        a.scroll_into_view_if_needed(timeout=4000)
        a.hover(timeout=4000)
        page.wait_for_timeout(900)
        hover = a.inner_text() or ""
    except Exception as e:
        _log.debug("curtidas do instagram: %s", e)
    return parse_instagram(cache["grade"][code], hover)


# ------------------------------------------------------------------ coleta
def due(cfg: Any, now: float | None = None) -> list[dict]:
    """Posts que precisam de leitura nova: de 2 em 2 h no comeco, depois de 6 em 6 h, depois 1 vez por dia."""
    now = now or time.time()
    c = _conn()
    out = []
    for p in c.execute("SELECT id, clip_id, platform, url, ts FROM posts WHERE ok=1 AND dry_run=0 AND url IS NOT NULL AND ts>=?",
                       (now - 10 * 86400,)).fetchall():
        age = (now - p["ts"]) / 3600
        last = c.execute("SELECT MAX(ts) t FROM post_numeros WHERE post_id=?", (p["id"],)).fetchone()["t"] or 0
        every = 2 if age < 8 else 6 if age < 60 else 24
        if age >= 1 and now - last >= every * 3600:
            out.append({**dict(p), "idade_h": age})
    out.sort(key=lambda x: x["idade_h"])
    return out[: int(cfg.get("metricas.max_por_varredura", 10))]


def _save(post: dict, d: dict) -> None:
    f = lambda k: (int(d[k]) if d.get(k) is not None else None)  # noqa: E731
    _conn().execute(
        "INSERT INTO post_numeros (post_id, clip_id, platform, ts, idade_h, views, likes, comments, shares, ficou_pct,"
        " tempo_medio_s, completo_pct, seguidores, extra) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (post["id"], post["clip_id"], post["platform"], time.time(), round(post["idade_h"], 2), f("views"), f("likes"),
         f("comments"), f("shares"), d.get("ficou_pct"), d.get("tempo_medio_s"), d.get("completo_pct"), f("seguidores"),
         json.dumps(d.get("extra") or {}, ensure_ascii=False)))
    if d.get("views") is not None:   # alimenta tambem a saude da conta e o aprendizado
        metrics.record_reading(post["id"], f("views"), f("likes"), f("comments"), f("shares"), fonte="studio")


def collect(cfg: Any) -> dict:
    """Le as paginas do canal (navegador do CORTEX, fora da tela). Nunca junto com uma publicacao."""
    from .publish import browser, guard

    todo = due(cfg)
    res = {"devidos": len(todo), "lidos": 0, "falhas": 0}
    todo = [p for p in todo if not guard.paused_until(p["platform"])]
    if not todo:
        return res
    lock = guard.PublishLock()
    if not lock.acquire():
        return res
    try:
        with browser.BrowserSession(cfg) as s:
            page = s.new_page()
            ig: dict = {}
            todo.sort(key=lambda p: p["platform"] == "instagram")      # o perfil do Instagram e lido uma vez so, no fim
            for p in todo:
                vid = metrics.video_id_from_url(p["platform"], p["url"])
                if not vid:
                    continue
                try:
                    if p["platform"] == "youtube":
                        page.goto(f"https://studio.youtube.com/video/{vid}/analytics/tab-overview/period-default",
                                  wait_until="domcontentloaded")
                        data = _wait_parse(page, parse_youtube)
                    elif p["platform"] == "instagram":
                        data = _read_instagram(page, vid, cfg, ig)
                    else:
                        page.goto(f"https://www.tiktok.com/tiktokstudio/analytics/{vid}", wait_until="domcontentloaded")
                        data = _wait_parse(page, parse_tiktok)
                    if data.get("views") is None:
                        res["falhas"] += 1
                        _log.info("sem numeros ainda: %s %s", p["platform"], vid)
                        continue
                    _save(p, data)
                    res["lidos"] += 1
                    _log.info("%s: %s views, %s curtidas, %s", p["platform"], int(data["views"]), int(data.get("likes") or 0),
                              f"{data['ficou_pct']:.0f}% continuaram vendo" if data.get("ficou_pct") is not None
                              else f"tempo medio {data.get('tempo_medio_s') or 0:.0f} s")
                except Exception as e:
                    res["falhas"] += 1
                    _log.info("leitura de %s %s falhou: %s", p["platform"], vid, str(e)[:150])
    except Exception as e:
        _log.warning("numeros: %s", str(e)[:200])
    finally:
        lock.release()
    return res


def _wait_parse(page: Any, fn) -> dict:
    """Espera a pagina carregar os numeros (ate ~20 s)."""
    d: dict = {}
    for _ in range(10):
        page.wait_for_timeout(2000)
        d = fn(page.inner_text("body") or "")
        if d.get("views") is not None and (d.get("ficou_pct") is not None or d.get("tempo_medio_s") is not None):
            page.wait_for_timeout(1200)
            return fn(page.inner_text("body") or "") or d
    return d


# ------------------------------------------------------------------ consultas
def latest(days: float = 30) -> list[dict]:
    """Ultima leitura de cada post, com o corte junto."""
    rows = _conn().execute(
        """SELECT p.id, p.clip_id, p.platform, p.url, p.ts AS post_ts, n.*, c.title, c.plan, c.rendered
           FROM posts p JOIN post_numeros n ON n.id = (SELECT id FROM post_numeros WHERE post_id = p.id ORDER BY ts DESC LIMIT 1)
           LEFT JOIN clips c ON c.id = p.clip_id
           WHERE p.ok=1 AND p.dry_run=0 AND p.ts>=? ORDER BY p.ts DESC""", (time.time() - days * 86400,)).fetchall()
    return [dict(r) for r in rows]


def at_age(post_id: int, target_h: float, tol: float = 0.4) -> dict | None:
    """Leitura mais perto de uma idade (24 h, por exemplo), com folga."""
    rows = [dict(r) for r in _conn().execute("SELECT * FROM post_numeros WHERE post_id=?", (post_id,)).fetchall()]
    ok = [r for r in rows if target_h * (1 - tol) <= r["idade_h"] <= target_h * (1 + tol)]
    return min(ok, key=lambda r: abs(r["idade_h"] - target_h)) if ok else None
