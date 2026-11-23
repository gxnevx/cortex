"""find_candidates: procura videos-fonte para os assuntos em alta / palavras-chave e canais monitorados.

Fluxo: buscas (YouTube) + abas de canais (YouTube) + VODs/clipes (Twitch/Kick/Rumble) em paralelo
-> junta e filtra com o que ja se sabe -> nota preliminar -> enriquece os melhores (yt-dlp, paralelo)
-> filtra de novo com dados exatos -> nota final -> diversidade (max N por canal) -> top `limit`.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import threading
import time
from dataclasses import dataclass, field

from .. import log, paths
from ..models import Candidate, NeedsUserAction, Trend
from . import canais, filtros, historico, nichos, saturacao, scoring
from . import youtube as yt
from .text import detect_lang, lang_code, match_score, norm, pt_score, short_query

_log = log.get(__name__)


@dataclass
class _Topic:
    label: str
    queries: list[str]
    weight: float = 1.0           # 0-1 (nota do trend / 100; palavra-chave = 1)
    category: str | None = None
    kind: str = "trend"           # trend | keyword


@dataclass
class _Raw:
    data: dict
    origins: set[str] = field(default_factory=set)   # busca | canal | twitch | kick | rumble
    topics: dict[str, float] = field(default_factory=dict)   # assunto -> match
    big_channel: bool = False
    monitored: bool = False
    category: str | None = None


# ------------------------------------------------------------------ canais invalidos (cache)
_INVALID_FILE = paths.STATE / "canais_invalidos.json"
_inv_lock = threading.Lock()


def _load_invalid() -> dict:
    try:
        d = json.loads(_INVALID_FILE.read_text(encoding="utf-8"))
        now = time.time()
        return {k: v for k, v in d.items() if now - float(v) < 7 * 86400}
    except (OSError, ValueError):
        return {}


def _mark_invalid(key: str) -> None:
    with _inv_lock:
        d = _load_invalid()
        d[key] = time.time()
        try:
            _INVALID_FILE.parent.mkdir(parents=True, exist_ok=True)
            _INVALID_FILE.write_text(json.dumps(d, indent=1), encoding="utf-8")
        except OSError:
            pass


# ------------------------------------------------------------------ helpers
def _yt_handle(h: str) -> str:
    h = str(h).strip()
    if h.startswith("http"):
        return h
    if h.startswith("UC") and len(h) == 24:
        return "channel/" + h
    return h if h.startswith("@") else "@" + h


def _topics_from(cfg, trends: list[Trend] | None, keywords: list[str] | None) -> list[_Topic]:
    topics: list[_Topic] = []
    for kw in keywords or []:
        kw = str(kw).strip()
        if kw:
            topics.append(_Topic(label=kw, queries=[kw], weight=1.0, kind="keyword"))
    n = int(cfg.get("busca.max_trends_busca", 8))
    for t in (trends or [])[:n]:
        qs = [q for q in (t.queries or []) if q and q.strip()] or [t.topic]
        qs = [short_query(q) if len(q) > 70 else q for q in qs][:2]
        topics.append(_Topic(label=t.topic, queries=qs, weight=max(0.2, min(1.0, (t.score or 50) / 100)),
                             category=t.category, kind="trend"))
    return topics


def _blocked(raw: dict, blocked_channels: list[str], blocked_words: list[str]) -> bool:
    title = " " + norm(raw.get("title") or "") + " "
    for w in blocked_words:
        if w and f" {w} " in title:
            return True
    ch = norm(raw.get("channel") or "")
    url = (raw.get("channel_url") or "").lower()
    for b in blocked_channels:
        if not b:
            continue
        if b.startswith("@"):
            if url.rstrip("/").endswith("/" + b) or f"/{b}/" in url:
                return True
        elif b == ch or norm(b) == ch:
            return True
    return False


def _blocked_list(cfg) -> list[str]:
    """canais_bloqueados do config + bloqueio fixo (handles em minusculas com @, nomes normalizados)."""
    out = []
    for b in list(cfg.get("busca.canais_bloqueados", []) or []) + list(canais.HARD_BLOCK):
        b = str(b).strip()
        if b:
            out.append(b.lower() if b.startswith("@") else norm(b))
    return out


def _is_blocked_name(name: str, blocked: list[str]) -> bool:
    n = name.strip()
    return (n.lower() in blocked) or (norm(n) in blocked) or (("@" + n.lstrip("@").lower()) in blocked)


def _cand_from_raw(r: _Raw) -> Candidate:
    d = r.data
    platform = d.get("platform") or "youtube"
    vid = d["id"]
    url = d.get("url") or (f"https://www.youtube.com/watch?v={vid}" if platform == "youtube" else "")
    extra = dict(d.get("extra") or {})
    if d.get("concurrent"):
        extra["assistindo_agora"] = d["concurrent"]
    if d.get("published_text"):
        extra["publicado_txt"] = d["published_text"]
    extra["origem"] = sorted(r.origins)
    if r.category:
        extra["categoria_canal"] = r.category
    best_topic = max(r.topics.items(), key=lambda kv: kv[1])[0] if r.topics else None
    return Candidate(
        id=f"{platform}:{vid}", platform=platform, url=url, title=d.get("title") or "",
        channel=d.get("channel") or "", channel_url=d.get("channel_url"),
        duration=float(d["duration"]) if d.get("duration") else None,
        views=int(d["views"]) if d.get("views") is not None else None,
        upload_ts=float(d["upload_ts"]) if d.get("upload_ts") else None,
        is_live=bool(d.get("is_live")), was_live=bool(d.get("was_live")),
        thumbnail=d.get("thumbnail"), description=(d.get("description") or "")[:1000],
        topic=best_topic, extra=extra,
    )


# ------------------------------------------------------------------ coleta
class _Collector:
    def __init__(self):
        self.items: dict[str, _Raw] = {}
        self.lock = threading.Lock()

    def add(self, data: dict, origin: str, topic: str | None = None, match: float = 0.0,
            big: bool = False, monitored: bool = False, category: str | None = None) -> None:
        if not data or not data.get("id"):
            return
        key = f"{data.get('platform', 'youtube')}:{data['id']}"
        with self.lock:
            r = self.items.get(key)
            if r is None:
                r = self.items[key] = _Raw(data=dict(data))
            else:
                # completa campos que faltavam
                for k, v in data.items():
                    if r.data.get(k) in (None, "", 0) and v not in (None, ""):
                        r.data[k] = v
            r.origins.add(origin)
            if topic:
                r.topics[topic] = max(r.topics.get(topic, 0.0), match)
            r.big_channel |= big
            r.monitored |= monitored
            r.category = r.category or category


def _search_jobs(topics: list[_Topic], window_h: float) -> list[tuple[str, str, _Topic]]:
    date = yt.DATE_TODAY if window_h <= 24 else yt.DATE_WEEK
    jobs = []
    for tp in topics:
        for i, q in enumerate(tp.queries):
            jobs.append((q, yt.build_sp(yt.SORT_VIEWS, date), tp))      # mais vistos na janela
            if i == 0:
                jobs.append((q, yt.build_sp(None, yt.DATE_TODAY), tp))  # relevancia, de hoje
                if tp.kind == "keyword" and date != yt.DATE_TODAY:
                    jobs.append((q, yt.build_sp(None, date), tp))       # relevancia, na janela
    return jobs


def languages(cfg) -> list[str]:
    """Idiomas aceitos (busca.idiomas, padrao ["pt", "en"]). Sem busca.estrangeiro.ativo, so "pt"."""
    langs = [str(x).lower()[:3] for x in (cfg.get("busca.idiomas", ["pt", "en"]) or ["pt"])]
    if "pt" not in langs:
        langs.insert(0, "pt")
    if not bool(cfg.get("busca.estrangeiro.ativo", True)):
        return ["pt"]
    if bool(cfg.get("busca.estrangeiro.exige_claude", True)):
        try:
            from ..brain import get_brain

            if get_brain(cfg, tarefa="clips").name != "claude":
                return ["pt"]   # a IA local erra muito em outra lingua
        except Exception:
            return ["pt"]
    return langs


def foreign_on(cfg) -> bool:
    return any(lg != "pt" for lg in languages(cfg))


def _channel_jobs(cfg) -> list[tuple[str, tuple[str, ...], bool, bool, str | None]]:
    """(handle, abas, canal_grande, monitorado, categoria)"""
    invalid = _load_invalid()
    blocked = _blocked_list(cfg)
    jobs: dict[str, tuple] = {}
    mon = (cfg.get("busca.canais_monitorados", {}) or {}).get("youtube") or []
    for h in mon:
        hh = _yt_handle(h)
        if not _is_blocked_name(hh, blocked):
            jobs[hh.lower()] = (hh, ("streams", "videos"), True, True, None)
    if cfg.get("busca.usar_canais_sugeridos", True):
        n = int(cfg.get("busca.max_canais_sugeridos", 60))
        skip_tv = "tv_aberta" in filtros.categories(cfg)
        for h, cat, tabs in canais.YOUTUBE[:n]:
            if (skip_tv and filtros.is_tv_handle(h)) or _is_blocked_name(h, blocked):
                continue
            if h.lower() not in jobs and f"yt:{h.lower()}" not in invalid:
                jobs[h.lower()] = (h, tabs, True, False, cat)
        if "en" in languages(cfg):
            for h, cat, tabs, _perm, _nota in canais.YOUTUBE_EN:
                if _is_blocked_name(h, blocked) or h.lower() in jobs or f"yt:{h.lower()}" in invalid:
                    continue
                jobs[h.lower()] = (h, tabs, True, False, cat)
    return list(jobs.values())


def _platform_jobs(cfg, name: str, curated: list[tuple[str, str]]) -> list[tuple[str, bool, str | None]]:
    if not (cfg.get("busca.fontes", {}) or {}).get(name, False):
        return []
    blocked = _blocked_list(cfg)
    mon = (cfg.get("busca.canais_monitorados", {}) or {}).get(name) or []
    jobs = {str(m).strip().lower(): (str(m).strip(), True, None) for m in mon if str(m).strip()}
    if cfg.get("busca.usar_canais_sugeridos", True):
        extra = {"twitch": canais.TWITCH_EN, "kick": canais.KICK_EN}.get(name, []) if "en" in languages(cfg) else []
        for login, cat in list(curated) + list(extra):
            jobs.setdefault(login.lower(), (login, False, cat))
    return [j for j in jobs.values() if not _is_blocked_name(j[0], blocked)]


# ------------------------------------------------------------------ videos virais (nao so podcast/live)
_PUBLISHERS = ("rockstar games", "playstation", "xbox", "nintendo", "ea sports", "ubisoft", "activision",
               "netflix", "prime video", "disney", "hbo", "warner", "sony pictures", "universal pictures",
               "vevo", "riot games", "epic games")


def _viral_queries(cfg, trends: list[Trend] | None) -> list[tuple[str, str]]:
    """(consulta, tema) para videos virais de qualquer formato (gameplay, easter egg, compilado, meme, react),
    em pt e, se busca.idiomas tiver "en", em ingles. Temas: busca.virais.temas + assuntos de games/humor."""
    if not bool(cfg.get("busca.virais.ativo", True)):
        return []
    temas = [str(t) for t in (cfg.get("busca.virais.temas", ["GTA 6"]) or []) if str(t).strip()]
    for t in trends or []:
        if (t.category or "") in ("games", "humor") and t.topic not in temas and len(t.topic) <= 40:
            temas.append(t.topic)
    pt_suf = list(cfg.get("busca.virais.sufixos_pt", ["easter egg", "polêmica", "momentos engraçados"]) or [])
    en_suf = list(cfg.get("busca.virais.sufixos_en", ["easter eggs", "funny moments"]) or [])
    en = "en" in languages(cfg)
    out: list[tuple[str, str]] = []
    for tema in temas:
        out += [(f"{tema} {sfx}", tema) for sfx in pt_suf]
        if en:
            out += [(f"{tema} {sfx}", tema) for sfx in en_suf]
    for q in cfg.get("busca.virais.consultas", []) or []:
        out.append((str(q), str(q)))
    return out[: int(cfg.get("busca.virais.max_consultas", 10))]


def _tag(c: Candidate, r: "_Raw", topics: list) -> None:
    """extra["idioma"] (pt, en, es...), extra["estrangeiro"] e extra["categoria"] (nicho) em todo candidato."""
    ex = c.extra = dict(c.extra or {})
    lang = lang_code(ex.get("language"))
    name = (c.channel_url or "").lower().rstrip("/").rsplit("/", 1)[-1]
    if not lang:
        if name in canais.FOREIGN_NAMES or norm(c.channel).replace(" ", "") in canais.FOREIGN_NAMES:
            lang = detect_lang(f"{c.title} {c.description[:300]}") or "en"
        else:
            lang = detect_lang(f"{c.title} {c.description[:300]}") or "pt"
    ex["idioma"] = lang
    ex["estrangeiro"] = lang != "pt"
    if lang != "pt":
        perm = canais.PERMISSAO_EN.get(name) or canais.PERMISSAO_EN.get(norm(c.channel).replace(" ", ""))
        if perm:
            ex["permite_cortes"] = perm
    trend_cat = next((tp.category for tp in topics if tp.label == c.topic), None)
    ex["categoria"] = nichos.niche_for(c, r.category, trend_cat)


def _best_match(text: str, topics: list[_Topic]) -> tuple[str | None, float]:
    best, bm = None, 0.0
    for tp in topics:
        for q in [tp.label] + tp.queries:
            m = match_score(text, q)
            if m > bm:
                best, bm = tp.label, m
    return best, bm


# ------------------------------------------------------------------ principal
def find_candidates(cfg, trends: list[Trend] | None = None, keywords: list[str] | None = None, limit: int = 15,
                    exclude_ids=None) -> list[Candidate]:
    """Videos-fonte ordenados por potencial (Candidate.score 0-100, Candidate.reasons em pt-BR)."""
    t0 = time.time()
    exclude = set(exclude_ids or [])
    window_h = float(cfg.get("busca.janela_horas", 48))
    dmin = float(cfg.get("busca.duracao_min_s", 90))
    dmax = float(cfg.get("busca.duracao_max_s", 21600))
    vmin = int(cfg.get("busca.views_minimas", 5000))
    include_live = bool(cfg.get("busca.incluir_ao_vivo", False))
    max_per_channel = int(cfg.get("busca.max_por_canal", 2))
    blocked_ch = _blocked_list(cfg)
    blocked_words = [norm(str(w)) for w in cfg.get("busca.palavras_bloqueadas", []) or [] if norm(str(w))]
    fontes = cfg.get("busca.fontes", {}) or {}
    skip_cats = filtros.categories(cfg)
    langs = languages(cfg)
    foreign = foreign_on(cfg)
    # busca.somente_portugues vale so quando as fontes estrangeiras estao desligadas
    only_pt = bool(cfg.get("busca.somente_portugues", True)) and not foreign
    foreign_min = float(cfg.get("busca.estrangeiro.nota_minima", 75))

    def skip_cat(c: Candidate, r: _Raw) -> str | None:
        ex_ = c.extra or {}
        hb = filtros.hard_block(c.title, c.channel, c.channel_url)
        if hb:
            return hb
        cats = skip_cats
        if r.monitored:   # canal escolhido pelo usuario: so vale o filtro por titulo/categoria
            reason = filtros.skip_reason(c.title, "", None, c.description, ex_.get("categories"), ex_.get("tags"),
                                         active=cats)
        else:
            reason = filtros.skip_reason(c.title, c.channel, c.channel_url, c.description, ex_.get("categories"),
                                         ex_.get("tags"), active=cats)
        return reason

    # modo: se nada foi passado, segue busca.modo
    if trends is None and not keywords:
        mode = str(cfg.get("busca.modo", "trends"))
        kws = list(cfg.get("busca.palavras_chave", []) or [])
        if mode in ("palavra_chave", "misto") and kws:
            keywords = kws
        if mode in ("trends", "misto") or not keywords:
            from .trends import collect_trends

            trends = collect_trends(cfg)
            # sem cerebro para ranquear: prioriza assuntos dos temas do usuario (busca.temas)
            temas = {norm(str(x)) for x in cfg.get("busca.temas", []) or []}
            temas |= {"politica" if "polemica" in temas else "", "esportes" if "esporte" in temas else ""} - {""}
            if temas:
                trends = sorted(trends, key=lambda t: -(t.score or 0) * (
                    1.0 if (not t.category or norm(t.category) in temas) else 0.6))
    keyword_mode = bool(keywords) and not trends
    topics = _topics_from(cfg, trends, keywords)
    col = _Collector()
    now = time.time()

    workers = int(cfg.get("busca.threads", 6))
    ex = cf.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="busca")
    futs: list[cf.Future] = []

    # 1) buscas no YouTube
    def do_search(q: str, sp: str, tp: _Topic):
        for it in yt.search(q, sp, max_results=20):
            text = f"{it.get('title', '')} {it.get('description', '')[:300]}"
            m = max(match_score(text, q), match_score(text, tp.label))
            it["platform"] = "youtube"
            col.add(it, "busca", tp.label, m)

    if fontes.get("youtube", True):
        for q, sp, tp in _search_jobs(topics, window_h):
            futs.append(ex.submit(do_search, q, sp, tp))

    # 1b) virais de qualquer formato (mais vistos de hoje e da semana), pt e en
    def do_viral(q: str, sp: str, tema: str):
        for it in yt.search(q, sp, max_results=15):
            text = f"{it.get('title', '')} {it.get('description', '')[:300]}"
            m = max(match_score(text, q), match_score(text, tema))
            it["platform"] = "youtube"
            col.add(it, "viral", tema, m)

    if fontes.get("youtube", True) and not keyword_mode:
        for q, tema in _viral_queries(cfg, trends):
            futs.append(ex.submit(do_viral, q, yt.build_sp(yt.SORT_VIEWS, yt.DATE_TODAY), tema))
            futs.append(ex.submit(do_viral, q, yt.build_sp(yt.SORT_VIEWS, yt.DATE_WEEK), tema))

    # 2) canais do YouTube (monitorados + sugeridos)
    hist_obs: list[tuple] = []   # (chave, itens, nome, apelidos) para o historico de velocidade

    def do_channel(handle: str, tabs, big: bool, mon: bool, cat):
        for tab in tabs:
            items, info = yt.channel_tab(handle, tab, max_results=12)
            if not info.get("exists"):
                if not mon and tab == tabs[0]:
                    _mark_invalid(f"yt:{handle.lower()}")
                    _log.info("canal sugerido %s nao existe (ignorado por 7 dias)", handle)
                return
            if info.get("id"):
                obs = [{"id": it["id"], "pub": it.get("upload_ts"), "views": it.get("views")} for it in items
                       if it.get("views") and it.get("upload_ts") and not it.get("is_live")]
                als = [historico.key_from_url(info.get("url")), f"youtube:{handle.lower()}" if handle.startswith("@") else None]
                hist_obs.append((f"youtube:{info['id']}", obs, info.get("title") or "", [x for x in als if x]))
            for it in items:
                if it.get("upcoming"):
                    continue
                age = it.get("age_s")
                if age is not None and age > window_h * 3600:
                    continue
                it["platform"] = "youtube"
                topic, m = _best_match(f"{it.get('title', '')}", topics)
                col.add(it, "canal", topic if m >= 0.5 else None, m, big=big, monitored=mon, category=cat)

    if fontes.get("youtube", True):
        for job in _channel_jobs(cfg):
            futs.append(ex.submit(do_channel, *job))

    # 3) Twitch / Kick / Rumble
    from . import platforms as P

    def do_platform(fn, name: str, login: str, mon: bool, cat):
        for it in fn(login, cfg, window_h):
            topic, m = _best_match(it.get("title", ""), topics)
            col.add(it, name, topic if m >= 0.5 else None, m, big=True, monitored=mon, category=cat)

    for login, mon, cat in _platform_jobs(cfg, "twitch", canais.TWITCH):
        futs.append(ex.submit(do_platform, P.twitch_channel, "twitch", login, mon, cat))
    for slug, mon, cat in _platform_jobs(cfg, "kick", canais.KICK):
        futs.append(ex.submit(do_platform, P.kick_channel, "kick", slug, mon, cat))
    for name, mon, cat in _platform_jobs(cfg, "rumble", []):
        futs.append(ex.submit(do_platform, P.rumble_channel, "rumble", name, mon, cat))

    budget = float(cfg.get("busca.tempo_max_coleta_s", 100))
    try:
        for f in cf.as_completed(futs, timeout=budget):
            try:
                f.result()
            except Exception as e:  # noqa: BLE001
                _log.warning("tarefa de busca falhou: %s", e)
    except cf.TimeoutError:
        _log.warning("busca de videos passou de %.0fs; seguindo com o que ja chegou", budget)
    ex.shutdown(wait=False, cancel_futures=True)
    t_collect = time.time() - t0
    for key, obs, name, als in list(hist_obs):
        try:
            historico.record(key, obs, name, als, now=now)
        except Exception as e:  # noqa: BLE001
            _log.info("historico de %s falhou: %s", key, e)

    # ---------------------------------------------------------- filtro preliminar
    with col.lock:
        raws = list(col.items.values())
    pre: list[tuple[Candidate, _Raw]] = []
    dropped: dict[str, int] = {}

    def drop(why: str):
        dropped[why] = dropped.get(why, 0) + 1

    for r in raws:
        d = r.data
        c = _cand_from_raw(r)
        is_clip = (c.extra or {}).get("tipo") == "clipe"
        if c.id in exclude:
            drop("ja usado")
            continue
        if d.get("upcoming"):
            drop("agendado")
            continue
        if c.is_live and not include_live:
            drop("ao vivo")
            continue
        if c.upload_ts and now - c.upload_ts > window_h * 3600 + (c.duration or 0) * (1 if c.was_live else 0):
            drop("antigo")
            continue
        if c.duration is not None:
            if is_clip:
                if c.duration < 15:
                    drop("clipe curto")
                    continue
            elif c.duration < dmin or c.duration > dmax:
                drop("duracao")
                continue
        if c.platform == "youtube" and c.views is not None and c.views < vmin and not c.is_live:
            drop("poucas views")
            continue
        if is_clip and (c.views or 0) < int(cfg.get("busca.twitch_clipe_views_min", 300)):
            drop("clipe pouco visto")
            continue
        if c.platform in ("twitch", "kick") and not is_clip:
            tw = sum(int(x.get("views") or 0) for x in (c.extra or {}).get("twitch_clips") or [])
            if (c.views or 0) + tw < max(200, vmin // 20) and not r.monitored:
                drop("poucas views")
                continue
        if _blocked(d, blocked_ch, blocked_words):
            drop("bloqueado")
            continue
        cat_skip = skip_cat(c, r)
        if cat_skip:
            drop(f"categoria:{cat_skip}")
            continue
        if keyword_mode and "busca" not in r.origins:
            # em modo palavra-chave, video de canal so entra se falar do assunto
            if not r.topics or max(r.topics.values()) < 0.5:
                drop("fora do assunto")
                continue
        if any(o in r.origins for o in ("busca", "viral")) and not (r.big_channel or r.monitored):
            mt = max(r.topics.values()) if r.topics else 0
            if mt < 0.34:
                drop("fora do assunto")
                continue
            lg = detect_lang(f"{c.title} {c.description[:200]}")
            if (lg and lg not in langs) or (not lg and pt_score(c.title) < -0.5 and not foreign):
                drop("idioma")
                continue
        if "viral" in r.origins and any(p in norm(c.channel) for p in _PUBLISHERS):
            drop("trailer/conteudo oficial")
            continue
        pre.append((c, r))

    def ctx(r: _Raw, c: Candidate) -> dict:
        topic, m = (max(r.topics.items(), key=lambda kv: kv[1]) if r.topics else (None, 0.0))
        tw = next((tp.weight for tp in topics if tp.label == topic), None)
        return dict(now=now, window_h=window_h, match=m, match_topic=topic,
                    trend_score=(tw * 100) if tw is not None and not keyword_mode else None,
                    big_channel=r.big_channel, monitored=r.monitored, category=r.category)

    for c, r in pre:
        scoring.score_candidate(c, **ctx(r, c))
    pre.sort(key=lambda cr: -cr[0].score)

    # diversidade antes de enriquecer (evita gastar tempo com 5 videos do mesmo canal)
    per_ch: dict[str, int] = {}
    shortlist: list[tuple[Candidate, _Raw]] = []
    n_enrich = int(cfg.get("busca.max_enriquecer", max(limit * 2, limit + 8)))
    for c, r in pre:
        key = norm(c.channel) or c.channel_url or c.id
        if per_ch.get(key, 0) >= max_per_channel + 1:
            continue
        per_ch[key] = per_ch.get(key, 0) + 1
        shortlist.append((c, r))
        if len(shortlist) >= n_enrich:
            break

    # ---------------------------------------------------------- enriquecimento (yt-dlp)
    from .. import download

    stop = threading.Event()
    bot_warned = [False]

    def enrich(cr: tuple[Candidate, _Raw]):
        c, r = cr
        if stop.is_set():
            return cr, None
        try:
            download.enrich_candidate(c, cfg, deep=False)
            return cr, True
        except NeedsUserAction as e:
            if not bot_warned[0]:
                bot_warned[0] = True
                _log.warning("%s", e)
            stop.set()
            return cr, None
        except Exception as e:  # noqa: BLE001
            _log.info("nao consegui detalhar %s: %s", c.id, str(e)[:200])
            return cr, False

    enriched: list[tuple[Candidate, _Raw]] = []
    t1 = time.time()
    ebudget = float(cfg.get("busca.tempo_max_enriquecer_s", 90))
    ex2 = cf.ThreadPoolExecutor(max_workers=int(cfg.get("busca.threads_enriquecer", 4)), thread_name_prefix="enriq")
    futs2 = [ex2.submit(enrich, cr) for cr in shortlist]
    done_ids = set()
    try:
        for f in cf.as_completed(futs2, timeout=ebudget):
            cr, ok = f.result()
            done_ids.add(cr[0].id)
            if ok is False:
                drop("indisponivel")
                continue
            enriched.append(cr)
    except cf.TimeoutError:
        _log.warning("detalhamento passou de %.0fs; usando dados parciais", ebudget)
        stop.set()
    ex2.shutdown(wait=False, cancel_futures=True)
    for cr in shortlist:   # os que nao deu tempo entram com os dados da busca
        if cr[0].id not in done_ids:
            enriched.append(cr)

    # ---------------------------------------------------------- filtro final + nota
    final: list[Candidate] = []
    for c, r in enriched:
        ex_ = c.extra or {}
        is_clip = ex_.get("tipo") == "clipe"
        if ex_.get("enriched"):
            if c.platform == "youtube" and c.is_live and not include_live:
                drop("ao vivo")
                continue
            if ex_.get("live_status") in ("is_upcoming",):
                drop("agendado")
                continue
            if c.duration is not None and not is_clip and (c.duration < dmin or c.duration > dmax):
                drop("duracao")
                continue
            if c.upload_ts and now - c.upload_ts > window_h * 3600 + ((c.duration or 0) if c.was_live else 0):
                drop("antigo")
                continue
            if c.platform == "youtube" and c.views is not None and c.views < vmin:
                drop("poucas views")
                continue
            cat_skip = skip_cat(c, r)
            if cat_skip:
                drop(f"categoria:{cat_skip}")
                continue
            lang = lang_code(ex_.get("language")) or ""
            if lang and lang != "pt" and (only_pt or lang not in langs) and not r.monitored:
                drop("idioma")
                continue
            # topico pode ser recalculado com a descricao completa
            if trends or keywords:
                topic, m = _best_match(f"{c.title} {c.description[:500]}", topics)
                if topic and m >= 0.6 and m > max(r.topics.values() or [0]):
                    r.topics[topic] = m
                    c.topic = topic
        _tag(c, r, topics)
        scoring.score_candidate(c, **ctx(r, c))
        if c.extra.get("estrangeiro") and c.score < foreign_min:
            drop("estrangeiro abaixo da nota")
            continue
        final.append(c)

    final.sort(key=lambda c: -c.score)
    # saturacao: os poucos melhores passam por uma busca "Hoje" (8+ canais cortando = nota x0.7 e 2o/3o momento)
    try:
        t2 = time.time()
        n_sat = saturacao.apply(final, cfg)
        if n_sat:
            for c in final[: int(cfg.get("busca.saturacao.max_checagens", 3))]:
                r = next((rr for cc, rr in enriched if cc is c), None)
                if r is not None and (c.extra or {}).get("saturacao", {}).get("pular_melhor_momento"):
                    scoring.score_candidate(c, **ctx(r, c))
            final.sort(key=lambda c: -c.score)
        _log.info("saturacao: %d saturado(s) entre os melhores (%.1fs)", n_sat, time.time() - t2)
    except Exception as e:  # noqa: BLE001
        _log.info("checagem de saturacao falhou: %s", e)
    eligible: list[Candidate] = []
    per_ch = {}
    seen_titles: set[tuple[str, str]] = set()
    for c in final:
        key = norm(c.channel) or c.channel_url or c.id
        if per_ch.get(key, 0) >= max_per_channel:
            continue
        # mesma live publicada em duas plataformas / repetida no canal: fica so a melhor
        tkey = (key, norm(c.title)[:40])
        if tkey in seen_titles:
            continue
        seen_titles.add(tkey)
        per_ch[key] = per_ch.get(key, 0) + 1
        eligible.append(c)
    mix = cfg.get("busca.mix_nichos", nichos.DEFAULT_MIX)
    out = nichos.select_mix(eligible, limit, mix if isinstance(mix, dict) else nichos.DEFAULT_MIX)
    _log.info("find_candidates: %d brutos, %d pre, %d detalhados -> %d (coleta %.1fs, detalhe %.1fs, total %.1fs)"
              " descartes=%s", len(raws), len(pre), len(enriched), len(out), t_collect, time.time() - t1,
              time.time() - t0, dropped)
    return out
