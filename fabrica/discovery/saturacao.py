"""Checagem de saturacao: quantos canais ja postaram cortes do mesmo assunto HOJE.

Uma busca do YouTube filtrada por "Hoje" (todos os tipos) com o assunto/titulo do video-fonte. Conta canais
distintos (fora o proprio canal da fonte) com titulo que bate com o assunto ou que fala em "corte(s)"; os
Shorts da prateleira vem sem canal e sao resolvidos pelo oEmbed (rapido). Regra da estrategia:

    >= 8 canais e o concorrente mais visto com > 100 mil views  ->  saturado
    => Candidate.extra["saturacao"] = {"canais", "top_views", "top_titulo", "top_canal", "consulta",
                                        "pular_melhor_momento": True, "multa": 0.7}
       nota x0.7 (scoring) e o cerebro corta o 2o/3o melhor momento (dica no prompt / heuristico).

Custo: 1 busca (~0,7 s) + ate 12 oEmbeds em paralelo. So para os poucos melhores candidatos.
"""
from __future__ import annotations

import concurrent.futures as cf
import re
import time
from urllib.parse import urlencode

from .. import log
from . import net
from . import youtube as yt
from .text import norm

_log = log.get(__name__)

_STOP = set("""a o e de da do das dos em no na nos nas um uma uns umas com sem por para pra pro que se ao aos as os
ou mas mais muito muita isso esse essa este esta ele ela eles elas eu voce voces vc meu minha seu sua nosso
foi ser ter tem tava esta estao vai vou vamos ja nao sim quem qual como quando onde porque pq tudo todo toda
podcast podcasts ep episodio episode ao vivo live completo completa parte part oficial official cortes corte
video videos react reage reagindo reacao novo nova hoje agora feat ft vs x the of and you""".split())
_CUT_RX = re.compile(r"\bcortes?\b|\bclips?\b|\bmelhores momentos\b")


def _cfg(cfg, key, default):
    try:
        return cfg.get(key, default) if cfg is not None else default
    except Exception:  # noqa: BLE001
        return default


def keywords(text: str, channel: str = "", n: int = 5) -> list[str]:
    """Palavras que identificam o assunto (sem acento, sem palavras vazias, sem o nome do canal)."""
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)|#\w+", " ", text or "")
    t = norm(t)
    chan = set(norm(channel).split())
    out: list[str] = []
    for w in re.findall(r"[a-z0-9]+", t):
        if len(w) < 3 or w in _STOP or w in chan or w.isdigit():
            continue
        if w not in out:
            out.append(w)
        if len(out) >= n:
            break
    return out


def build_query(c) -> tuple[str, list[str]]:
    kws = keywords(c.title or "", c.channel or "")
    topic = (c.topic or "").strip()
    if topic and len(topic) <= 40:
        tk = keywords(topic, "", 4)
        rest = [w for w in kws if w not in tk][: max(0, 4 - len(tk))]
        q = " ".join(tk + rest) if tk else topic
        return q.strip(), list(dict.fromkeys(tk + kws))
    q = " ".join(kws[:5])
    if len(kws) < 3 and c.channel:
        q = (norm(re.sub(r"\[[^\]]*\]", "", c.channel)).split() or [""])[0] + " " + q
    return q.strip(), kws


def _walk(o, out: list) -> None:
    if isinstance(o, dict):
        for k, v in o.items():
            if k in ("videoRenderer", "lockupViewModel", "shortsLockupViewModel", "reelItemRenderer") and isinstance(v, dict):
                out.append((k, v))
                continue
            _walk(v, out)
    elif isinstance(o, list):
        for x in o:
            _walk(x, out)


def _short_item(v: dict) -> dict | None:
    """Short da prateleira: id, titulo e views (vem no texto de acessibilidade)."""
    try:
        cmd = (v.get("onTap") or {}).get("innertubeCommand") or {}
        vid = ((cmd.get("reelWatchEndpoint") or {}).get("videoId")) or v.get("videoId")
        if not vid:
            return None
        acc = str(v.get("accessibilityText") or "")
        m = re.match(r"^(.*?),\s*([\d.,]+\s*(?:mil|mi|bi)?)\s*(?:de\s+)?visualiza", acc)
        title = m.group(1) if m else acc.split(",")[0]
        from .text import parse_count

        views = parse_count(m.group(2)) if m else None
        return {"id": vid, "title": title, "views": views, "channel": "", "short": True}
    except Exception:  # noqa: BLE001
        return None


def _oembed_author(vid: str) -> str:
    r = net.get("https://www.youtube.com/oembed", params={"url": f"https://www.youtube.com/shorts/{vid}",
                                                         "format": "json"}, timeout=8, what="oembed")
    try:
        return str(r.json().get("author_name") or "") if r is not None else ""
    except ValueError:
        return ""


def search_today(query: str, max_shorts: int = 12) -> list[dict]:
    """Resultados de HOJE (videos + Shorts) com canal e views. Nunca levanta."""
    try:
        sp = yt.build_sp(None, yt.DATE_TODAY, typ=None)
        r = net.get("https://www.youtube.com/results?" + urlencode({"search_query": query, "hl": "pt-BR", "gl": "BR",
                                                                    "sp": sp}), timeout=15, what="saturacao")
        data = yt._initial_data(r.text) if r is not None else None
        if not data:
            return []
        items = yt._parse_items(data, skip_shelves=False)
        found: list = []
        _walk(data, found)
        shorts = [s for s in (_short_item(v) for k, v in found if k in ("shortsLockupViewModel", "reelItemRenderer")) if s]
        seen = {i["id"] for i in items}
        shorts = [s for s in shorts if s["id"] not in seen][:max_shorts]
        # Shorts (e as vezes o layout novo da busca) vem sem o nome do canal: o oEmbed resolve rapido
        todo = (shorts + [i for i in items if not i.get("channel")])[: max_shorts + 10]
        if todo:
            with cf.ThreadPoolExecutor(max_workers=6, thread_name_prefix="oembed") as ex:
                for s, a in zip(todo, ex.map(lambda s: _oembed_author(s["id"]), todo)):
                    s["channel"] = a
        return items + shorts
    except Exception as e:  # noqa: BLE001
        _log.info("busca de saturacao falhou (%s): %s", query, e)
        return []


def check(c, cfg) -> dict | None:
    """Mede a saturacao do assunto do candidato. Devolve o dict de extra["saturacao"] (ou None se falhar)."""
    t0 = time.time()
    q, kws = build_query(c)
    if len(q) < 4:
        return None
    res = search_today(q)
    if not res:
        return None
    src = norm(re.sub(r"\[[^\]]*\]", "", c.channel or "")).strip()
    vid_src = c.id.split(":", 1)[-1]
    kset = set(kws)
    chans: dict[str, dict] = {}
    for it in res:
        if it.get("id") == vid_src or it.get("is_live") or it.get("upcoming"):
            continue
        ch = norm(re.sub(r"\[[^\]]*\]", "", it.get("channel") or "")).strip()
        if not ch or (src and (ch == src or ch.startswith(src + " "))):
            continue
        tw = set(re.findall(r"[a-z0-9]+", norm(it.get("title") or "")))
        related = len(kset & tw) >= min(2, len(kset)) or bool(_CUT_RX.search(norm(it.get("title") or "")))
        if not related:
            continue
        v = int(it.get("views") or 0)
        cur = chans.get(ch)
        if cur is None or v > cur["views"]:
            chans[ch] = {"views": v, "title": it.get("title") or "", "channel": it.get("channel") or ""}
    n = len(chans)
    top = max(chans.values(), key=lambda x: x["views"]) if chans else None
    n_min = int(_cfg(cfg, "busca.saturacao.canais_min", 8))
    v_min = int(_cfg(cfg, "busca.saturacao.top_views_min", 100_000))
    sat = bool(top and n >= n_min and top["views"] > v_min)
    out = {"canais": n, "top_views": top["views"] if top else 0, "top_titulo": (top or {}).get("title", "")[:100],
           "top_canal": (top or {}).get("channel", ""), "consulta": q, "pular_melhor_momento": sat,
           "multa": float(_cfg(cfg, "busca.saturacao.multa", 0.7)), "tempo_s": round(time.time() - t0, 1),
           "checado_ts": round(time.time())}
    _log.info("saturacao %s ('%s'): %d canais hoje, top %s views -> %s (%.1fs)", c.id, q, n, out["top_views"],
              "SATURADO" if sat else "ok", out["tempo_s"])
    return out


def apply(cands: list, cfg, max_checks: int | None = None) -> int:
    """Checa os `max_checks` primeiros candidatos (em paralelo) e grava extra["saturacao"]. Devolve quantos
    ficaram saturados. Nao mexe na nota (o scoring aplica a multa ao recalcular)."""
    if not bool(_cfg(cfg, "busca.saturacao.ativa", True)) or not cands:
        return 0
    k = int(max_checks if max_checks is not None else _cfg(cfg, "busca.saturacao.max_checagens", 3))
    todo = [c for c in cands[:k] if c.platform in ("youtube", "twitch", "kick")]
    if not todo:
        return 0
    n_sat = 0
    with cf.ThreadPoolExecutor(max_workers=3, thread_name_prefix="saturacao") as ex:
        for c, res in zip(todo, ex.map(lambda c: check(c, cfg), todo)):
            if res is not None:
                c.extra = dict(c.extra or {})
                c.extra["saturacao"] = res
                n_sat += int(res["pular_melhor_momento"])
    return n_sat
