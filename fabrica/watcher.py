"""Vigia da VIA RAPIDA: acha momentos explodindo AGORA nos canais monitorados (barato, a cada ~10 min).

    poll(cfg) -> list[Candidate]      # nunca levanta; loga e devolve []

Fontes (todas sem login):
- YouTube: RSS de cada canal (https://www.youtube.com/feeds/videos.xml?channel_id=...), handle -> id resolvido
  uma vez e guardado em data/estado/vigia.json. Cada leitura alimenta o historico de velocidade do canal
  (data/estado/canais_hist.json).
- Twitch: GQL publica (clipes das ultimas 24 h com o offset exato no VOD + clipes da semana para a mediana).
- Kick: clipes via yt-dlp (como a descoberta).

Gatilhos (docs/ideias/estrategia_conteudo.md, secao 4.3):
- clipe da Twitch com >= twitch_views_min (1500) views em <= 3 h, ou >= multiplicador_mediana (3) x a
  mediana dos clipes do canal em 7 dias;
- clipe da Kick com >= kick_views_min (1000) views em <= 24 h;
- upload do YouTube nas primeiras 6 h com >= yt_vph_min (5000) views/hora, ou >= 3x a mediana do canal.

Cada Candidate devolvido tem extra["via_rapida"]=True, extra["motivo_via_rapida"] (pt-BR) e extra["janela"]:
[inicio, fim] na linha do tempo do video ORIGINAL quando o momento e conhecido (clipe da Twitch com VOD
acessivel: offset do clipe com 40 s de contexto antes e 30 s depois), ou None (o proprio clipe vira a fonte;
upload do YouTube). Nunca devolve o mesmo clipe/video duas vezes em 48 h (data/estado/vigia.json).

Config (busca.via_rapida.*): ativa (true), intervalo_min (10), twitch_views_min (1500), kick_views_min (1000),
yt_vph_min (5000), multiplicador_mediana (3), twitch_idade_max_h (3), kick_idade_max_h (24),
yt_idade_max_h (6), contexto_antes_s (40), contexto_depois_s (30), tempo_max_s (50), max_resultados (6),
checar_saturacao (true).
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import math
import os
import statistics
import threading
import time
import xml.etree.ElementTree as ET

from . import log, paths
from .models import Candidate

_log = log.get(__name__)

STATE_FILE = paths.STATE / "vigia.json"
_lock = threading.Lock()
DEDUPE_H = 48

NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "media": "http://search.yahoo.com/mrss/"}


def _cfg(cfg, key: str, default):
    try:
        v = cfg.get(key, default) if cfg is not None else default
        return default if v is None else v
    except Exception:  # noqa: BLE001
        return default


def _vr(cfg, key: str, default):
    return _cfg(cfg, f"busca.via_rapida.{key}", default)


def _fmult(cfg, name: str) -> float:
    """Fonte estrangeira: gatilhos de views multiplicados (busca.estrangeiro.multiplicador_via_rapida, 3)."""
    from .discovery import canais

    if name.lower().lstrip("@") in {x.lstrip("@") for x in canais.FOREIGN_NAMES}:
        return float(_cfg(cfg, "busca.estrangeiro.multiplicador_via_rapida", 3))
    return 1.0


def interval_min(cfg) -> float:
    """Intervalo sugerido entre leituras (busca.via_rapida.intervalo_min, padrao 10)."""
    return float(_vr(cfg, "intervalo_min", 10))


def _fmt_n(n: float) -> str:
    if n >= 1e6:
        return f"{n / 1e6:.1f}".replace(".", ",") + " mi"
    if n >= 1e3:
        return f"{n / 1e3:.1f}".rstrip("0").rstrip(".").replace(".", ",") + " mil"
    return str(int(n))


def _fmt_age(h: float) -> str:
    return f"{int(round(h * 60))} min" if h < 1 else f"{h:.1f} h".replace(".", ",")


# ====================================================================== estado
def _load_state() -> dict:
    try:
        d = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            d = {}
    except (OSError, ValueError):
        d = {}
    for k in ("vistos", "yt_ids", "vod_ok", "janelas", "det"):
        d.setdefault(k, {})
    now = time.time()
    d["vistos"] = {k: v for k, v in d["vistos"].items() if now - float(v) < DEDUPE_H * 3600 * 1.5}
    d["vod_ok"] = {k: v for k, v in d["vod_ok"].items() if now - float(v[1]) < 6 * 3600}
    d["det"] = {k: v for k, v in d["det"].items() if now - float(v.get("ts", 0)) < 6 * 3600}
    d["janelas"] = {k: [w for w in v if now - float(w[2]) < DEDUPE_H * 3600] for k, v in d["janelas"].items()}
    d["janelas"] = {k: v for k, v in d["janelas"].items() if v}
    return d


def _save_state(d: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=0), encoding="utf-8")
        os.replace(tmp, STATE_FILE)
    except OSError as e:
        _log.info("vigia: nao consegui salvar o estado: %s", e)


def _seen(state: dict, key: str, now: float) -> bool:
    ts = state["vistos"].get(key)
    return ts is not None and now - float(ts) < DEDUPE_H * 3600


# ====================================================================== canais
def _channels(cfg) -> dict[str, list[tuple[str, bool, str | None]]]:
    """{"youtube": [(handle, monitorado, categoria)], "twitch": [...], "kick": [...]} sem os bloqueados."""
    from .discovery import canais, filtros
    from .discovery.candidates import _blocked_list, _is_blocked_name, _platform_jobs, _yt_handle, languages

    fontes = _cfg(cfg, "busca.fontes", {}) or {}
    blocked = _blocked_list(cfg)
    out: dict[str, list] = {"youtube": [], "twitch": [], "kick": []}
    if fontes.get("youtube", True):
        seen: set[str] = set()
        mon = ((_cfg(cfg, "busca.canais_monitorados", {}) or {}).get("youtube")) or []
        for h in mon:
            hh = _yt_handle(h)
            if hh.lower() not in seen and not _is_blocked_name(hh, blocked):
                seen.add(hh.lower())
                out["youtube"].append((hh, True, None))
        if _cfg(cfg, "busca.usar_canais_sugeridos", True):
            skip_tv = "tv_aberta" in filtros.categories(cfg)
            for h, cat, _tabs in canais.YOUTUBE[: int(_cfg(cfg, "busca.max_canais_sugeridos", 60))]:
                if h.lower() in seen or _is_blocked_name(h, blocked) or (skip_tv and filtros.is_tv_handle(h)):
                    continue
                seen.add(h.lower())
                out["youtube"].append((h, False, cat))
            if "en" in languages(cfg):
                for h, cat, _tabs, _perm, _nota in canais.YOUTUBE_EN:
                    if h.lower() not in seen and not _is_blocked_name(h, blocked):
                        seen.add(h.lower())
                        out["youtube"].append((h, False, cat))
    out["twitch"] = _platform_jobs(cfg, "twitch", canais.TWITCH)
    out["kick"] = _platform_jobs(cfg, "kick", canais.KICK)
    return out


# ====================================================================== YouTube (RSS)
def _resolve_ids(handles: list[str], state: dict, deadline: float, max_new: int = 30) -> dict[str, str]:
    """handle -> UC id (cache permanente; canal inexistente fica marcado por 7 dias)."""
    from .discovery import historico
    from .discovery import youtube as yt

    ids = state["yt_ids"]
    now = time.time()
    out: dict[str, str] = {}
    todo = []
    for h in handles:
        k = h.lower()
        if k.startswith("channel/"):
            out[h] = h.split("/", 1)[1]
            continue
        hit = ids.get(k)
        if hit and hit[0]:
            out[h] = hit[0]
        elif hit and not hit[0] and now - float(hit[1]) < 7 * 86400:
            continue
        else:
            todo.append(h)
    todo = todo[:max_new]

    def one(h: str):
        if time.time() > deadline:
            return h, None, [], {}
        items, info = yt.channel_tab(h, "videos", max_results=30)
        return h, info.get("id") if info.get("exists") else "", items, info

    if todo:
        with cf.ThreadPoolExecutor(max_workers=6, thread_name_prefix="vigia-id") as ex:
            for h, cid, items, info in ex.map(one, todo):
                if cid is None:
                    continue
                ids[h.lower()] = [cid, round(now)]
                if cid:
                    out[h] = cid
                    # semente do historico de velocidade (views e idade aproximada dos ultimos videos)
                    obs = [{"id": it["id"], "pub": it.get("upload_ts"), "views": it.get("views")} for it in items
                           if it.get("views") and it.get("upload_ts") and not it.get("is_live")]
                    try:
                        historico.record(f"youtube:{cid}", obs, info.get("title") or "",
                                         [historico.key_from_url(info.get("url")) or "", f"youtube:{h.lower()}"])
                    except Exception:  # noqa: BLE001
                        pass
    return out


def _parse_rss(text: str) -> tuple[str, list[dict]]:
    root = ET.fromstring(text)
    title = (root.findtext("a:title", default="", namespaces=NS) or "").strip()
    out = []
    from .discovery.twitch_gql import iso_ts

    for e in root.findall("a:entry", NS):
        vid = e.findtext("yt:videoId", default="", namespaces=NS)
        link = (e.find("a:link", NS).get("href") if e.find("a:link", NS) is not None else "") or ""
        st = e.find("media:group/media:community/media:statistics", NS)
        views = int(st.get("views")) if st is not None and (st.get("views") or "").isdigit() else None
        out.append({"id": vid, "title": (e.findtext("a:title", default="", namespaces=NS) or "").strip(),
                    "link": link, "pub": iso_ts(e.findtext("a:published", default="", namespaces=NS)),
                    "views": views, "short": "/shorts/" in link,
                    "thumb": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                    "descricao": (e.findtext("media:group/media:description", default="", namespaces=NS) or "")[:500]})
    return title, out


def _youtube(chans: list[tuple[str, bool, str | None]], state: dict, cfg, deadline: float, now: float) -> list[dict]:
    from .discovery import historico, net

    vph_min = float(_vr(cfg, "yt_vph_min", 5000))
    mult = float(_vr(cfg, "multiplicador_mediana", 3))
    max_age = float(_vr(cfg, "yt_idade_max_h", 6))
    min_views = int(_vr(cfg, "yt_views_min", 1000))
    rel_floor = float(_vr(cfg, "yt_vph_min_relativo", 800))
    meta = {h: (mon, cat) for h, mon, cat in chans}
    ids = _resolve_ids([h for h, _, _ in chans], state, deadline)
    hits: list[dict] = []
    stats = {"canais": len(ids), "rss_ok": 0, "videos": 0}

    def one(h: str, cid: str):
        if time.time() > deadline:
            return h, cid, None
        r = net.get("https://www.youtube.com/feeds/videos.xml", params={"channel_id": cid}, timeout=10, what="rss")
        if r is None:
            return h, cid, None
        try:
            return h, cid, _parse_rss(r.text)
        except ET.ParseError:
            return h, cid, None

    with cf.ThreadPoolExecutor(max_workers=8, thread_name_prefix="vigia-rss") as ex:
        results = list(ex.map(lambda kv: one(*kv), ids.items()))
    for h, cid, res in results:
        if not res:
            continue
        stats["rss_ok"] += 1
        name, entries = res
        key = f"youtube:{cid}"
        obs = [{"id": e["id"], "pub": e["pub"], "views": e["views"]} for e in entries
               if not e["short"] and e["views"] is not None and e["pub"]]
        for e in entries:
            if e["short"] or e["views"] is None or not e["pub"]:
                continue
            age_h = (now - e["pub"]) / 3600
            if age_h > max_age or age_h < 0.05 or e["views"] < min_views:
                continue
            stats["videos"] += 1
            vph = e["views"] / max(age_h, 0.25)
            base, n = historico.baseline_vph(key, age_h, exclude_id=e["id"])
            r = (vph / base) if base else None
            fm = _fmult(cfg, h)
            why = None
            if vph >= vph_min * fm:
                why = f"upload com {_fmt_n(vph)} views/hora em {_fmt_age(age_h)} ({_fmt_n(e['views'])} views)"
            elif r is not None and r >= mult and vph >= rel_floor * fm:
                why = (f"upload {str(round(r, 1)).replace('.', ',')}x mais rapido que o normal do canal "
                       f"({_fmt_n(e['views'])} views em {_fmt_age(age_h)})")
            if not why:
                continue
            mon, cat = meta.get(h, (False, None))
            hits.append({"kind": "youtube", "key": f"youtube:{e['id']}", "why": why, "mon": mon, "cat": cat,
                         "handle": h, "thr": (vph_min * fm, mult, rel_floor * fm), "base": base,
                         "prio": 1.0 + min(3.0, (r or vph / vph_min)), "entry": e, "channel": name,
                         "channel_url": f"https://www.youtube.com/channel/{cid}", "cid": cid,
                         "vph": round(vph), "r": round(r, 2) if r else None, "age_h": round(age_h, 2)})
        try:
            historico.record(key, obs, name, [f"youtube:{h.lower()}"], now=now)
        except Exception:  # noqa: BLE001
            pass
    _log.info("vigia youtube: %d canais, %d RSS lidos, %d uploads recentes, %d gatilhos", stats["canais"],
              stats["rss_ok"], stats["videos"], len(hits))
    return hits


def _yt_details(vid: str) -> dict:
    """Pagina do video (1 requisicao): ao vivo agora? agendado? duracao? {} se falhar."""
    import re

    from .discovery import net

    r = net.get(f"https://www.youtube.com/watch?v={vid}", params={"hl": "pt-BR", "gl": "BR"}, timeout=12,
                what="detalhe")
    if r is None:
        return {}
    t = r.text
    m = re.search(r'"lengthSeconds":"(\d+)"', t)
    return {"live": '"isLiveNow":true' in t,
            "upcoming": '"isUpcoming":true' in t,
            "duration": float(m.group(1)) if m and m.group(1) != "0" else None}


def _fix_live_speed(h: dict) -> None:
    """Live gravada: o RSS data a publicacao no FIM da transmissao, mas as views vem desde o inicio.
    Recalcula views/hora com a idade real (idade + duracao) e cancela o gatilho se nao se sustentar."""
    det = h.get("det") or {}
    d = det.get("duration")
    if not d or det.get("live") or d / 3600 <= h["age_h"] * 0.5:
        return
    age_eff = h["age_h"] + d / 3600
    views = h["entry"]["views"]
    vph = views / max(age_eff, 0.25)
    vmin, mult, floor = h.get("thr") or (5000, 3, 800)
    r = (vph / h["base"]) if h.get("base") else None
    if vph >= vmin:
        h["why"] = f"live com {_fmt_n(vph)} views/hora desde o inicio ({_fmt_n(views)} views em {_fmt_age(age_eff)})"
    elif r is not None and r >= mult and vph >= floor:
        h["why"] = (f"live {str(round(r, 1)).replace('.', ',')}x mais vista que o normal do canal "
                    f"({_fmt_n(views)} views em {_fmt_age(age_eff)})")
    else:
        h["cancelado"] = True
        return
    h["vph"], h["r"], h["age_h"] = round(vph), (round(r, 2) if r else None), round(age_eff, 2)


# ====================================================================== Twitch (GQL)
def _twitch(chans: list[tuple[str, bool, str | None]], cfg, now: float) -> list[dict]:
    from .discovery import twitch_gql

    if not chans:
        return []
    vmin = int(_vr(cfg, "twitch_views_min", 1500))
    mult = float(_vr(cfg, "multiplicador_mediana", 3))
    max_age = float(_vr(cfg, "twitch_idade_max_h", 3))
    floor = int(_vr(cfg, "twitch_views_piso", 200))
    meta = {lg.lower(): (mon, cat) for lg, mon, cat in chans}
    data = twitch_gql.channels_clips([lg for lg, _, _ in chans])
    hits: list[dict] = []
    for lg, d in data.items():
        week = d.get("views_semana") or []
        med7 = statistics.median(week) if len(week) >= 5 else None
        fm = _fmult(cfg, lg)
        for cl in d.get("clipes_dia") or []:
            if not cl.get("criado_ts"):
                continue
            age_h = (now - cl["criado_ts"]) / 3600
            if age_h > max_age:
                continue
            v = cl["views"]
            why = None
            if v >= vmin * fm:
                why = f"clipe da Twitch com {_fmt_n(v)} views em {_fmt_age(age_h)}"
            elif med7 and v >= mult * med7 and v >= floor * fm:
                why = (f"clipe da Twitch com {_fmt_n(v)} views em {_fmt_age(age_h)} "
                       f"({str(round(v / med7, 1)).replace('.', ',')}x a mediana da semana)")
            if not why:
                continue
            mon, cat = meta.get(lg, (False, None))
            same_vod = [x for x in d["clipes_dia"] if x.get("vod_id") and x.get("vod_id") == cl.get("vod_id")
                        and x.get("vod_offset") is not None]
            hits.append({"kind": "twitch", "key": f"twitch_clip:{cl['id']}", "why": why, "mon": mon, "cat": cat,
                         "prio": 3.0 + min(3.0, v / max(vmin, 1)) + (1.0 if d.get("ao_vivo") else 0.0),
                         "clip": cl, "login": d.get("login") or lg, "nome": d.get("nome") or lg,
                         "ao_vivo": d.get("ao_vivo"), "vod_clips": same_vod, "med7": med7})
    _log.info("vigia twitch: %d canais lidos, %d gatilhos", len(data), len(hits))
    return hits


# ====================================================================== Kick (yt-dlp)
def _kick(chans: list[tuple[str, bool, str | None]], cfg, now: float, deadline: float) -> list[dict]:
    from .discovery.platforms import _flat

    if not chans:
        return []
    vmin = int(_vr(cfg, "kick_views_min", 1000))
    max_age = float(_vr(cfg, "kick_idade_max_h", 24))
    hits: list[dict] = []

    def one(item):
        slug, mon, cat = item
        if time.time() > deadline:
            return item, []
        return item, _flat(f"https://kick.com/{slug}/clips", 20)

    with cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="vigia-kick") as ex:
        for (slug, mon, cat), clips in ex.map(one, chans):
            for c in clips:
                ts = c.get("timestamp")
                v = int(c.get("view_count") or 0)
                if not ts or not c.get("url"):
                    continue
                age_h = (now - float(ts)) / 3600
                if age_h > max_age or v < vmin * _fmult(cfg, slug):
                    continue
                why = f"clipe da Kick com {_fmt_n(v)} views em {_fmt_age(age_h)}"
                hits.append({"kind": "kick", "key": f"kick_clip:{c.get('id')}", "why": why, "mon": mon, "cat": cat,
                             "prio": 2.5 + min(3.0, v / max(vmin, 1)) * (1.0 if age_h < 3 else 0.6),
                             "clip": c, "slug": slug, "age_h": age_h})
    _log.info("vigia kick: %d canais, %d gatilhos", len(chans), len(hits))
    return hits


# ====================================================================== candidatos
def _overlaps(state: dict, vod: str, a: float, b: float) -> bool:
    for wa, wb, _ in state["janelas"].get(vod, []):
        ov = min(b, wb) - max(a, wa)
        if ov > 0.5 * min(b - a, wb - wa):
            return True
    return False


def _vod_ok(state: dict, vod_id: str) -> bool:
    from .discovery import twitch_gql

    hit = state["vod_ok"].get(vod_id)
    if hit is not None:
        return bool(hit[0])
    ok = twitch_gql.vod_accessible(vod_id)
    if ok is not None:
        state["vod_ok"][vod_id] = [bool(ok), round(time.time())]
    return bool(ok)


def _make(hit: dict, state: dict, cfg, now: float) -> Candidate | None:
    before = float(_vr(cfg, "contexto_antes_s", 40))
    after = float(_vr(cfg, "contexto_depois_s", 30))
    base_extra = {"via_rapida": True, "motivo_via_rapida": hit["why"], "prioridade": round(hit["prio"], 2),
                  "origem": ["vigia"], "vigia_ts": round(now), "monitorado": bool(hit.get("mon"))}
    if hit.get("cat"):
        base_extra["categoria_canal"] = hit["cat"]
    if hit["kind"] == "youtube":
        e = hit["entry"]
        ex = dict(base_extra, janela=None, channel_id=hit["cid"], vph=hit["vph"], tipo="upload")
        if hit.get("r"):
            ex["velocidade_rel"] = {"r": hit["r"]}
        return Candidate(id=f"youtube:{e['id']}", platform="youtube", url=f"https://www.youtube.com/watch?v={e['id']}",
                         title=e["title"], channel=hit["channel"], channel_url=hit["channel_url"], duration=None,
                         views=e["views"], upload_ts=e["pub"], thumbnail=e["thumb"], description=e["descricao"],
                         extra=ex)
    if hit["kind"] == "twitch":
        cl, login = hit["clip"], hit["login"]
        clip_url = f"https://www.twitch.tv/{login}/clip/{cl['slug']}"
        reserva = {"url": clip_url, "id": f"twitch:{cl['id']}", "duracao": cl["duracao"], "titulo": cl["titulo"]}
        vod = cl.get("vod_id")
        if vod and cl.get("vod_offset") is not None and _vod_ok(state, vod):
            off = float(cl["vod_offset"])
            a = max(0.0, off - before)
            b = off + float(cl["duracao"]) + after
            if cl.get("vod_dur"):
                b = min(b, float(cl["vod_dur"]))
            if _overlaps(state, vod, a, b):
                return None          # outro clipe do mesmo lance ja foi para a via rapida
            state["janelas"].setdefault(vod, []).append([a, b, round(now)])
            clips = [{"offset": float(x["vod_offset"]), "duration": float(x["duracao"]), "views": int(x["views"]),
                      "title": x["titulo"], "url": f"https://www.twitch.tv/{login}/clip/{x['slug']}"}
                     for x in hit.get("vod_clips") or []]
            clips.sort(key=lambda x: -x["views"])
            live = cl.get("vod_status") == "RECORDING"
            ex = dict(base_extra, janela=[round(a, 1), round(b, 1)], tipo="vod", twitch_clips=clips,
                      clip_url=clip_url, clip_reserva=reserva)
            if live:
                ex["vod_em_andamento"] = True
            return Candidate(id=f"twitch:v{vod}", platform="twitch", url=f"https://www.twitch.tv/videos/{vod}",
                             title=cl.get("vod_titulo") or cl["titulo"], channel=login,
                             channel_url=f"https://www.twitch.tv/{login}", duration=cl.get("vod_dur"),
                             upload_ts=cl.get("vod_inicio_ts"), is_live=False, was_live=True,
                             description=f"Clipe: {cl['titulo']}", topic=None, extra=ex)
        # sem VOD (ou so para inscritos): o proprio clipe e a fonte
        ex = dict(base_extra, janela=None, tipo="clipe", vod_url=(f"https://www.twitch.tv/videos/{vod}" if vod else None),
                  vod_offset=cl.get("vod_offset"), clip_url=clip_url)
        return Candidate(id=f"twitch:{cl['id']}", platform="twitch", url=clip_url, title=cl["titulo"], channel=login,
                         channel_url=f"https://www.twitch.tv/{login}", duration=cl["duracao"], views=cl["views"],
                         upload_ts=cl["criado_ts"], extra=ex)
    if hit["kind"] == "kick":
        c, slug = hit["clip"], hit["slug"]
        ex = dict(base_extra, janela=None, tipo="clipe", clip_url=c.get("url"))
        return Candidate(id=f"kick:{c.get('id')}", platform="kick", url=c.get("url"), title=c.get("title") or "",
                         channel=slug, channel_url=f"https://kick.com/{slug}",
                         duration=float(c["duration"]) if c.get("duration") else None,
                         views=int(c.get("view_count") or 0), upload_ts=float(c["timestamp"]),
                         thumbnail=c.get("thumbnail"), extra=ex)
    return None


def _tag(c: Candidate, hit: dict) -> None:
    """extra["idioma"], extra["estrangeiro"] e extra["categoria"] (nicho)."""
    from .discovery import canais, nichos
    from .discovery.text import detect_lang

    name = (c.channel_url or "").lower().rstrip("/").rsplit("/", 1)[-1]
    name = {"login": hit.get("login"), "slug": hit.get("slug")}.get("login") or hit.get("slug") or name
    foreign = str(name or "").lower() in canais.FOREIGN_NAMES or \
        any(str(hn).lower() in canais.FOREIGN_NAMES for hn in (hit.get("handle"),) if hn)
    lang = detect_lang(f"{c.title} {c.description[:200]}")
    c.extra["idioma"] = (lang if lang and lang != "pt" else "en") if foreign else (lang or "pt")
    c.extra["estrangeiro"] = c.extra["idioma"] != "pt"
    c.extra["categoria"] = nichos.niche_for(c, hit.get("cat"))


def _blocked(c: Candidate, cfg, monitored: bool) -> str | None:
    from .discovery import filtros
    from .discovery.candidates import _blocked, _blocked_list
    from .discovery.text import norm

    blocked_words = [norm(str(w)) for w in _cfg(cfg, "busca.palavras_bloqueadas", []) or [] if norm(str(w))]
    if _blocked({"title": c.title, "channel": c.channel, "channel_url": c.channel_url}, _blocked_list(cfg),
                blocked_words):
        return "bloqueado"
    hb = filtros.hard_block(c.title, c.channel, c.channel_url)
    if hb:
        return hb
    cats = filtros.categories(cfg)
    if monitored:
        return filtros.skip_reason(c.title, "", None, c.description, active=cats)
    return filtros.skip_reason(c.title, c.channel, c.channel_url, c.description, active=cats)


# ====================================================================== principal
def poll(cfg) -> list[Candidate]:
    """Uma leitura do vigia (<= ~60 s). Devolve os momentos novos explodindo, mais urgentes primeiro."""
    try:
        return _poll(cfg)
    except Exception as e:  # noqa: BLE001
        _log.warning("vigia falhou: %s", e)
        return []


def _poll(cfg) -> list[Candidate]:
    if not bool(_vr(cfg, "ativa", True)):
        return []
    t0 = time.time()
    now = t0
    deadline = t0 + float(_vr(cfg, "tempo_max_s", 50))
    with _lock:
        state = _load_state()
    chans = _channels(cfg)
    hits: list[dict] = []
    ex = cf.ThreadPoolExecutor(max_workers=3, thread_name_prefix="vigia")
    futs = {ex.submit(_youtube, chans["youtube"], state, cfg, deadline, now): "youtube",
            ex.submit(_twitch, chans["twitch"], cfg, now): "twitch",
            ex.submit(_kick, chans["kick"], cfg, now, deadline): "kick"}
    try:
        for f in cf.as_completed(futs, timeout=max(1.0, deadline - time.time() + 5)):
            try:
                hits += f.result()
            except Exception as e:  # noqa: BLE001
                _log.warning("vigia %s falhou: %s", futs[f], e)
    except cf.TimeoutError:
        _log.warning("vigia passou do tempo; seguindo com o que chegou")
    ex.shutdown(wait=False, cancel_futures=True)

    hits.sort(key=lambda h: -h["prio"])
    # uploads do YouTube: confere se ja terminou (live em andamento ainda nao da corte) e pega a duracao
    yt_hits = [h for h in hits if h["kind"] == "youtube" and not _seen(state, h["key"], now)][:12]
    for h in yt_hits:                       # detalhes ja lidos (duracao) valem 6 h; ao vivo/agendado sempre de novo
        det = state["det"].get(h["entry"]["id"])
        if det and not det.get("live") and not det.get("upcoming"):
            h["det"] = det
    todo = [h for h in yt_hits if "det" not in h]
    if todo and time.time() < deadline + 5:
        with cf.ThreadPoolExecutor(max_workers=5, thread_name_prefix="vigia-det") as ex2:
            for h, det in zip(todo, ex2.map(lambda h: _yt_details(h["entry"]["id"]), todo)):
                h["det"] = det
                if det:
                    state["det"][h["entry"]["id"]] = dict(det, ts=round(now))
    for h in yt_hits:
        _fix_live_speed(h)
    dmin = float(_cfg(cfg, "busca.duracao_min_s", 90))
    live_ok = bool(_vr(cfg, "incluir_ao_vivo", False))
    out: list[Candidate] = []
    skipped: dict[str, int] = {}
    max_n = int(_vr(cfg, "max_resultados", 6))
    for h in hits:
        if _seen(state, h["key"], now):
            skipped["ja visto"] = skipped.get("ja visto", 0) + 1
            continue
        det = h.get("det") or {}
        if h.get("cancelado"):
            skipped["live longa (velocidade normal)"] = skipped.get("live longa (velocidade normal)", 0) + 1
            continue
        if det.get("upcoming") or (det.get("live") and not live_ok):
            skipped["ao vivo ainda"] = skipped.get("ao vivo ainda", 0) + 1
            continue                              # sem marcar como visto: volta quando a live acabar
        if det.get("duration") and det["duration"] < dmin:
            state["vistos"][h["key"]] = round(now)
            skipped["curto"] = skipped.get("curto", 0) + 1
            continue
        c = _make(h, state, cfg, now)
        state["vistos"][h["key"]] = round(now)   # mesmo bloqueado/repetido: nao reavalia por 48 h
        if c is not None and det.get("duration"):
            c.duration = det["duration"]
        if c is not None and det.get("live"):
            c.is_live = True
            c.extra["ao_vivo_agora"] = True
        if c is not None:
            _tag(c, h)
        if c is None:
            skipped["mesmo lance"] = skipped.get("mesmo lance", 0) + 1
            continue
        why = _blocked(c, cfg, h["mon"])
        if why:
            skipped[why] = skipped.get(why, 0) + 1
            continue
        if any(o.id == c.id and o.extra.get("janela") == c.extra.get("janela") for o in out):
            continue
        out.append(c)
        if len(out) >= max_n:
            break

    # nota + saturacao (so YouTube: clipe de live e fresco demais para ja estar saturado)
    try:
        from .discovery import saturacao, scoring

        if bool(_vr(cfg, "checar_saturacao", True)) and time.time() < deadline:
            yts = [c for c in out if c.platform == "youtube"][:3]
            saturacao.apply(yts, cfg, max_checks=3)
        fmin = float(_cfg(cfg, "busca.estrangeiro.nota_minima_via_rapida", 55))
        for c in out:
            scoring.score_candidate(c, now=now, monitored=bool(c.extra.get("monitorado")), big_channel=True,
                                    category=c.extra.get("categoria_canal"))
            c.reasons = [c.extra["motivo_via_rapida"]] + [r for r in c.reasons if r != c.extra["motivo_via_rapida"]]
            c.reasons = c.reasons[:8]
        weak = [c for c in out if c.extra.get("estrangeiro") and c.score < fmin]
        if weak:
            skipped["estrangeiro abaixo da nota"] = len(weak)
            out = [c for c in out if c not in weak]
    except Exception as e:  # noqa: BLE001
        _log.info("vigia: nota/saturacao falhou: %s", e)

    state["ultimo"] = {"ts": round(now), "gatilhos": len(hits), "novos": len(out), "tempo_s": round(time.time() - t0, 1),
                       "descartes": skipped}
    with _lock:
        _save_state(state)
    _log.info("vigia: %d gatilhos, %d novos (%s) em %.1fs: %s", len(hits), len(out), skipped or "sem descartes",
              time.time() - t0, "; ".join(f"{c.channel}: {c.extra.get('motivo_via_rapida')}" for c in out) or "nada")
    return out


def last_status() -> dict:
    """Resumo da ultima leitura (para a interface)."""
    try:
        return dict(_load_state().get("ultimo") or {})
    except Exception:  # noqa: BLE001
        return {}
