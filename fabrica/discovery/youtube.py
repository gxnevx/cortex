"""YouTube sem API: busca e abas de canal lendo o ytInitialData das paginas publicas (hl=pt-BR, gl=BR).

Por que nao so o yt-dlp? Na busca "flat" o yt-dlp nao traz a data de publicacao (so com
`approximate_date`, que entende apenas ingles) e as visualizacoes vem vazias quando o YouTube responde
com o layout novo (lockupViewModel). Lendo a pagina direto temos "ha 3 horas", "116 mil visualizacoes",
selo AO VIVO etc. Se o parser falhar, caimos no yt-dlp flat como reserva.

Verificado em nov/2026: /feed/trending e /feed/explore NAO listam mais videos (o YouTube removeu a
pagina Em alta); /results?sp=... com filtros de data/ordem por visualizacoes funciona.
"""
from __future__ import annotations

import base64
import json
import re
import time
from urllib.parse import quote, urlencode

from .. import log
from . import net
from .text import parse_age, parse_clock, parse_count

_log = log.get(__name__)

# ------------------------------------------------------------------ filtros de busca (parametro sp)
SORT_RELEVANCE, SORT_DATE, SORT_VIEWS = None, 2, 3
DATE_HOUR, DATE_TODAY, DATE_WEEK, DATE_MONTH = 1, 2, 3, 4
TYPE_VIDEO = 1
DUR_SHORT, DUR_LONG, DUR_MEDIUM = 1, 2, 3   # <4 min, >20 min, 4-20 min


def _varint(n: int) -> bytes:
    out = b""
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out += bytes([b | 0x80])
        else:
            return out + bytes([b])


def build_sp(sort: int | None = None, date: int | None = None, typ: int | None = TYPE_VIDEO,
             duration: int | None = None, live: bool = False) -> str:
    """Monta o protobuf do parametro sp (mesmo formato dos filtros do site)."""
    f = b""
    if date:
        f += b"\x08" + _varint(date)
    if typ:
        f += b"\x10" + _varint(typ)
    if duration:
        f += b"\x18" + _varint(duration)
    if live:
        f += b"\x40\x01"
    out = b""
    if sort is not None:
        out += b"\x08" + _varint(sort)
    if f:
        out += b"\x12" + _varint(len(f)) + f
    return base64.b64encode(out).decode()


# ------------------------------------------------------------------ leitura do ytInitialData
_INITIAL_RE = [re.compile(r"var ytInitialData = (\{.*?\});</script>", re.S),
               re.compile(r'window\["ytInitialData"\] = (\{.*?\});', re.S)]


def _initial_data(html: str) -> dict | None:
    for rx in _INITIAL_RE:
        m = rx.search(html)
        if m:
            try:
                return json.loads(m.group(1))
            except ValueError:
                continue
    return None


def _text(o) -> str:
    if not o:
        return ""
    if isinstance(o, str):
        return o
    if isinstance(o, dict):
        if "simpleText" in o:
            return o["simpleText"]
        if "runs" in o:
            return "".join(r.get("text", "") for r in o["runs"])
        if "content" in o:
            return str(o["content"])
    return ""


_SKIP_KEYS = {"reelShelfRenderer", "shelfRenderer", "gridShelfViewModel", "horizontalCardListRenderer",
              "secondarySearchContainerRenderer", "shortsLockupViewModel", "reelItemRenderer"}


def _walk(o, out: list, skip_shelves: bool):
    if isinstance(o, dict):
        for k, v in o.items():
            if skip_shelves and k in _SKIP_KEYS:
                continue
            if k in ("videoRenderer", "gridVideoRenderer", "lockupViewModel") and isinstance(v, dict):
                out.append((k, v))
                continue
            _walk(v, out, skip_shelves)
    elif isinstance(o, list):
        for x in o:
            _walk(x, out, skip_shelves)


def _find_key(o, key: str, out: list | None = None) -> list[dict]:
    out = [] if out is None else out
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key and isinstance(v, dict):
                out.append(v)
            else:
                _find_key(v, key, out)
    elif isinstance(o, list):
        for x in o:
            _find_key(x, key, out)
    return out


def _handle_from(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"/(@[\w.\-]+)", url)
    return m.group(1) if m else None


def _parse_video_renderer(r: dict, now: float) -> dict | None:
    vid = r.get("videoId")
    if not vid:
        return None
    title = _text(r.get("title"))
    nav = (((r.get("navigationEndpoint") or {}).get("commandMetadata") or {}).get("webCommandMetadata") or {}).get("url", "")
    if "/shorts/" in nav:
        return None
    published = _text(r.get("publishedTimeText"))
    views_txt = _text(r.get("viewCountText")) or _text(r.get("shortViewCountText"))
    badges = json.dumps(r.get("badges") or []) + json.dumps(r.get("thumbnailOverlays") or [])
    is_live = "BADGE_STYLE_TYPE_LIVE_NOW" in badges or '"style": "LIVE"' in badges or "assistindo" in views_txt.lower() \
        or "watching" in views_txt.lower()
    upcoming = bool(r.get("upcomingEventData"))
    owner = r.get("ownerText") or r.get("longBylineText") or r.get("shortBylineText") or {}
    ch_url = None
    for run in owner.get("runs") or []:
        be = (run.get("navigationEndpoint") or {}).get("browseEndpoint") or {}
        if be.get("canonicalBaseUrl"):
            ch_url = "https://www.youtube.com" + be["canonicalBaseUrl"]
        elif be.get("browseId"):
            ch_url = "https://www.youtube.com/channel/" + be["browseId"]
        if ch_url:
            break
    age = parse_age(published)
    desc = " ".join(_text(s.get("snippetText")) for s in r.get("detailedMetadataSnippets") or [])
    thumbs = ((r.get("thumbnail") or {}).get("thumbnails") or [])
    return {
        "id": vid, "title": title, "channel": _text(owner), "channel_url": ch_url,
        "duration": parse_clock(_text(r.get("lengthText"))),
        "views": None if is_live else parse_count(views_txt),
        "concurrent": parse_count(views_txt) if is_live else None,
        "age_s": age, "upload_ts": (now - age) if age is not None else (now if is_live else None),
        "is_live": is_live, "was_live": "transmitid" in published.lower() or "streamed" in published.lower(),
        "upcoming": upcoming, "published_text": published, "description": desc,
        "thumbnail": thumbs[-1]["url"] if thumbs else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
    }


def _parse_lockup(v: dict, now: float, channel: str = "", channel_url: str | None = None) -> dict | None:
    if v.get("contentType") != "LOCKUP_CONTENT_TYPE_VIDEO":
        return None
    vid = v.get("contentId")
    if not vid:
        return None
    md = (v.get("metadata") or {}).get("lockupMetadataViewModel") or {}
    title = _text(md.get("title"))
    parts: list[str] = []
    for row in ((md.get("metadata") or {}).get("contentMetadataViewModel") or {}).get("metadataRows") or []:
        for p in row.get("metadataParts") or []:
            t = _text(p.get("text"))
            if t:
                parts.append(t)
    badges = [(str(b.get("text") or ""), str(b.get("badgeStyle") or ""))
              for b in _find_key(v.get("contentImage") or {}, "thumbnailBadgeViewModel")]
    duration = next((parse_clock(t) for t, _ in badges if re.match(r"^\d+(:\d{1,2}){1,2}$", t)), None)
    is_live = any("LIVE" in st for _, st in badges) or any(("assistindo" in p.lower() or "watching" in p.lower())
                                                            for p in parts)
    upcoming = any(p.lower().startswith(("programado", "estreia", "scheduled", "premieres")) for p in parts)
    views = None
    concurrent = None
    age = None
    published = ""
    for p in parts:
        pl = p.lower()
        if "assistindo" in pl or "watching" in pl:
            concurrent = parse_count(p)
        elif "visualiza" in pl or "views" in pl or re.match(r"^[\d.,]+\s*(mil|mi|bi|k|m)?$", pl.strip()):
            views = parse_count(p) if views is None else views
        elif parse_age(p) is not None:
            age = parse_age(p)
            published = p
    # channel do lockup (busca/home) quando existir
    if not channel:
        for row in ((md.get("metadata") or {}).get("contentMetadataViewModel") or {}).get("metadataRows") or []:
            for p in row.get("metadataParts") or []:
                runs = ((p.get("text") or {}).get("commandRuns") or [])
                if runs:
                    be = (((runs[0].get("onTap") or {}).get("innertubeCommand") or {}).get("browseEndpoint") or {})
                    if be.get("browseId"):
                        channel = _text(p.get("text"))
                        channel_url = "https://www.youtube.com" + be.get("canonicalBaseUrl", "/channel/" + be["browseId"])
                        break
            if channel:
                break
    return {
        "id": vid, "title": title, "channel": channel, "channel_url": channel_url, "duration": duration,
        "views": views, "concurrent": concurrent, "age_s": age,
        "upload_ts": (now - age) if age is not None else (now if is_live else None),
        "is_live": is_live, "was_live": "transmitid" in published.lower() or "streamed" in published.lower(),
        "upcoming": upcoming, "published_text": published, "description": "",
        "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
    }


def _parse_items(data: dict, channel: str = "", channel_url: str | None = None, skip_shelves: bool = True) -> list[dict]:
    now = time.time()
    found: list = []
    _walk(data, found, skip_shelves)
    out, seen = [], set()
    for kind, r in found:
        try:
            item = _parse_lockup(r, now, channel, channel_url) if kind == "lockupViewModel" else _parse_video_renderer(r, now)
        except Exception as e:  # noqa: BLE001
            _log.debug("item do YouTube ignorado: %s", e)
            item = None
        if item and item["id"] not in seen:
            if channel and not item.get("channel"):
                item["channel"], item["channel_url"] = channel, channel_url
            seen.add(item["id"])
            out.append(item)
    return out


# ------------------------------------------------------------------ API publica do modulo
def search(query: str, sp: str | None = None, max_results: int = 25) -> list[dict]:
    """Busca no YouTube (pagina publica). Nunca levanta; [] em caso de erro."""
    try:
        params = {"search_query": query, "hl": "pt-BR", "gl": "BR"}
        if sp:
            params["sp"] = sp
        r = net.get("https://www.youtube.com/results?" + urlencode(params), timeout=20, what="youtube_search")
        items: list[dict] = []
        if r:
            data = _initial_data(r.text)
            if data:
                items = _parse_items(data)
        if not items:
            items = _ytdlp_flat(f"https://www.youtube.com/results?search_query={quote(query)}"
                                + (f"&sp={quote(sp)}" if sp else ""), max_results)
        return items[:max_results]
    except Exception as e:  # noqa: BLE001
        _log.warning("busca no YouTube falhou (%s): %s", query, e)
        return []


def channel_tab(handle_or_url: str, tab: str = "videos", max_results: int = 30) -> tuple[list[dict], dict]:
    """Videos de uma aba do canal (videos | streams). Devolve (itens, info_do_canal). Nunca levanta.

    info_do_canal = {"exists": bool, "title": str, "url": str, "id": "UC..."}"""
    info = {"exists": False, "title": "", "url": None, "id": None}
    try:
        h = handle_or_url.strip()
        if h.startswith("http"):
            base = h.rstrip("/")
            base = re.sub(r"/(videos|streams|featured|shorts|live)$", "", base)
        else:
            base = "https://www.youtube.com/" + (h if h.startswith("@") or h.startswith("channel/") else "@" + h)
        url = f"{base}/{tab}?hl=pt-BR&gl=BR"
        r = net.session().get(url, timeout=20)
        if r.status_code == 404:
            return [], info
        if r.status_code != 200:
            _log.info("canal %s/%s: HTTP %s", base, tab, r.status_code)
            return [], info
        data = _initial_data(r.text)
        if not data:
            return [], info
        meta = (data.get("metadata") or {}).get("channelMetadataRenderer") or {}
        info.update(exists=True, title=meta.get("title") or "", id=meta.get("externalId"),
                    url=meta.get("vanityChannelUrl") or (base if "@" in base else None) or meta.get("channelUrl"))
        # so a aba pedida: se o canal nao tem a aba, o YouTube devolve a inicial (descartamos)
        tabs = (((data.get("contents") or {}).get("twoColumnBrowseResultsRenderer") or {}).get("tabs") or [])
        sel = None
        for t in tabs:
            tr = t.get("tabRenderer") or {}
            if tr.get("selected"):
                sel = tr
                break
        if sel is None:
            return [], info
        turl = (((sel.get("endpoint") or {}).get("commandMetadata") or {}).get("webCommandMetadata") or {}).get("url", "")
        if not turl.endswith("/" + tab):
            return [], info
        items = _parse_items(sel, channel=info["title"], channel_url=info["url"], skip_shelves=False)
        return items[:max_results], info
    except Exception as e:  # noqa: BLE001
        _log.warning("canal do YouTube %s falhou: %s", handle_or_url, e)
        return [], info


def _ytdlp_flat(url: str, n: int) -> list[dict]:
    """Reserva: yt-dlp flat (sem data de publicacao)."""
    try:
        import yt_dlp

        from ..download import ytdlp_opts

        opts = ytdlp_opts(None, extract_flat="in_playlist", playlistend=n, skip_download=True)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        out = []
        for e in info.get("entries") or []:
            if not e or not e.get("id") or "/shorts/" in (e.get("url") or ""):
                continue
            out.append({
                "id": e["id"], "title": e.get("title") or "", "channel": e.get("channel") or e.get("uploader") or "",
                "channel_url": e.get("channel_url") or e.get("uploader_url"), "duration": e.get("duration"),
                "views": e.get("view_count"), "concurrent": e.get("concurrent_view_count"), "age_s": None,
                "upload_ts": e.get("timestamp"), "is_live": e.get("live_status") == "is_live",
                "was_live": e.get("live_status") == "was_live", "upcoming": e.get("live_status") == "is_upcoming",
                "published_text": "", "description": e.get("description") or "",
                "thumbnail": f"https://i.ytimg.com/vi/{e['id']}/hqdefault.jpg",
            })
        return out
    except Exception as e:  # noqa: BLE001
        _log.info("yt-dlp flat falhou para %s: %s", url[:100], e)
        return []
