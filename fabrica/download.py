"""Download via yt-dlp (API Python) + ffmpeg.

    ytdlp_opts(cfg, **extra) -> dict
    fetch_info(url, cfg) -> dict
    enrich_candidate(c, cfg, deep=True) -> Candidate   # deep: + comment_marks e chat_spikes
    download_platform_subtitles(c, cfg, dest_dir) -> Path | None
    download_audio(c, cfg, dest_dir, start=None, end=None) -> Path
    download_sections(c, sections, cfg, dest_dir, max_height=1080) -> list[Path]
    download_video(c, cfg, dest_dir, max_height=1080) -> Path

Notas:
- JS do YouTube resolvido com Node (yt-dlp-ejs instalado no .venv; deno nao e necessario).
- Se o YouTube pedir "Sign in to confirm you're not a bot", levantamos BotCheckError (subclasse de
  NeedsUserAction) com instrucao em pt-BR para rodar `cortex login youtube`.
- Trechos (download_sections) sao cortados pelo ffmpeg direto das URLs da plataforma com seek preciso
  (re-encode H.264/AAC), entao o arquivo i comeca exatamente em sections[i][0]. Para HLS (Twitch) montamos
  uma playlist local so com os segmentos do trecho (funciona ate em VOD de live em andamento).
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import urljoin

from . import log, paths, tools
from .models import Candidate, NeedsUserAction
from .util import run_cmd, slugify

_log = log.get(__name__)

PT_LANGS = ("pt-orig", "pt-BR", "pt", "pt-PT")


class BotCheckError(NeedsUserAction):
    """O YouTube bloqueou o acesso anonimo (anti-robo)."""


class DownloadFailed(RuntimeError):
    pass


BOT_MSG = ("O YouTube pediu para confirmar que voce nao e um robo e bloqueou o download. "
           "Rode `cortex login youtube`, entre na sua conta no navegador que abrir e tente de novo "
           "(os cookies do navegador logado sao exportados para o yt-dlp).")
AGE_MSG = ("Este video tem restricao de idade e so baixa com login. Rode `cortex login youtube` "
           "para exportar os cookies da sua conta e tente de novo.")


# ======================================================================= opcoes do yt-dlp
class _YtdlpLogger:
    """Manda as mensagens do yt-dlp para o log do projeto (nada no terminal)."""

    def debug(self, msg):
        if msg.startswith("[debug] "):
            return
        _log.debug("yt-dlp: %s", msg)

    def info(self, msg):
        _log.debug("yt-dlp: %s", msg)

    def warning(self, msg):
        _log.info("yt-dlp aviso: %s", msg)

    def error(self, msg):
        _log.warning("yt-dlp erro: %s", msg)


def _cfg_get(cfg, key: str, default):
    try:
        return cfg.get(key, default) if cfg is not None else default
    except Exception:  # noqa: BLE001
        return default


def _js_runtimes() -> dict:
    node = tools.node()
    if node:
        return {"node": {"path": node}}
    deno = tools.deno()
    if deno:
        return {"deno": {"path": deno}}
    _log.warning("Nem Node nem Deno encontrados: o YouTube pode nao liberar os formatos de video")
    return {}


_cookie_lock = threading.Lock()


def _cookiefile() -> str | None:
    """Copia de cookies.txt por thread: o yt-dlp regrava o arquivo ao terminar e nao queremos
    corromper o original nem ter duas threads escrevendo no mesmo arquivo."""
    src = paths.COOKIES_TXT
    if not src.is_file():
        return None
    try:
        paths.TMP.mkdir(parents=True, exist_ok=True)
        dst = paths.TMP / f"ck_{os.getpid()}_{threading.get_ident()}.txt"
        with _cookie_lock:
            if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
                shutil.copyfile(src, dst)
        return str(dst)
    except OSError as e:
        _log.info("nao consegui copiar cookies.txt: %s", e)
        return str(src)


def _cleanup_cookie_copies() -> None:
    try:
        now = time.time()
        for f in glob.glob(str(paths.TMP / "ck_*.txt")):
            if now - os.path.getmtime(f) > 86400:
                os.remove(f)
    except OSError:
        pass


_cleanup_cookie_copies()


def ytdlp_opts(cfg, **extra) -> dict:
    """Opcoes base do yt-dlp (silencioso, com retentativas, Node como runtime JS e cookies se existirem)."""
    opts: dict = {
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
        "logger": _YtdlpLogger(),
        "retries": int(_cfg_get(cfg, "download.tentativas", 5)),
        "fragment_retries": 10,
        "extractor_retries": 3,
        "file_access_retries": 3,
        "socket_timeout": float(_cfg_get(cfg, "download.timeout_s", 30)),
        "concurrent_fragment_downloads": int(_cfg_get(cfg, "download.fragmentos_paralelos", 6)),
        "noplaylist": True,
        "windowsfilenames": True,
        "overwrites": True,
        "js_runtimes": _js_runtimes(),
        "color": {"stdout": "never", "stderr": "never"},
    }
    ff = tools.ffmpeg()
    if ff:
        opts["ffmpeg_location"] = str(Path(ff).parent)
    if _cfg_get(cfg, "download.usar_cookies", False):   # desligado: com a conta logada o YouTube nao entrega os formatos
        ck = _cookiefile()
        if ck:
            opts["cookiefile"] = ck
    opts.update(extra)
    return opts


def _raise_friendly(e: Exception) -> None:
    msg = str(e)
    low = msg.lower()
    if "not a bot" in low or "sign in to confirm you" in low and "age" not in low:
        raise BotCheckError(BOT_MSG) from e
    if "confirm your age" in low or "age-restricted" in low or "inappropriate for some users" in low:
        raise NeedsUserAction(AGE_MSG) from e


# ======================================================================= info (com cache)
_INFO_CACHE: dict[str, tuple[float, dict]] = {}
_INFO_LOCK = threading.Lock()
_INFO_TTL = 25 * 60   # URLs de midia do YouTube expiram em ~6 h; 25 min e seguro


def fetch_info(url: str, cfg, *, fresh: bool = False) -> dict:
    """Metadados completos (formatos, legendas, heatmap...). Levanta BotCheckError/DownloadFailed."""
    import yt_dlp

    now = time.time()
    if not fresh:
        with _INFO_LOCK:
            hit = _INFO_CACHE.get(url)
            if hit and now - hit[0] < _INFO_TTL:
                return hit[1]
    opts = ytdlp_opts(cfg, skip_download=True)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            info = ydl.sanitize_info(info)
    except yt_dlp.utils.DownloadError as e:
        _raise_friendly(e)
        raise DownloadFailed(f"nao consegui ler o video {url}: {_short_err(e)}") from e
    if not info:
        raise DownloadFailed(f"yt-dlp nao devolveu dados para {url}")
    with _INFO_LOCK:
        _INFO_CACHE[url] = (now, info)
        if len(_INFO_CACHE) > 40:
            for k, _ in sorted(_INFO_CACHE.items(), key=lambda kv: kv[1][0])[:10]:
                _INFO_CACHE.pop(k, None)
    return info


def _short_err(e: Exception) -> str:
    s = re.sub(r"^ERROR:\s*", "", str(e)).strip()
    return s.splitlines()[0][:300] if s else type(e).__name__


# ======================================================================= enriquecimento
def _sub_langs(info: dict) -> tuple[list[str], list[str]]:
    manual = [k for k in (info.get("subtitles") or {}) if k not in ("live_chat", "rechat", "danmaku")]
    auto = list((info.get("automatic_captions") or {}).keys())
    return manual, auto


def _has_useful_subs(info: dict) -> bool:
    """Legenda manual em pt, legenda automatica original (pt-orig ou <idioma>-orig) ou manual no idioma original.
    Traducoes automaticas (pt a partir de outro idioma) nao contam."""
    manual, auto = _sub_langs(info)
    lang = (info.get("language") or "").split("-")[0] or None
    pt_manual = any(k.split("-")[0] == "pt" for k in manual)
    pt_auto = "pt-orig" in auto or (lang == "pt" and any(k in ("pt", "pt-BR") for k in auto))
    orig = bool(lang) and (f"{lang}-orig" in auto or any(k.split("-")[0] == lang for k in manual))
    return bool(pt_manual or pt_auto or orig)


def enrich_candidate(c: Candidate, cfg, deep: bool = True) -> Candidate:
    """Completa o candidato com os dados da pagina do video (views, likes, duracao, heatmap, capitulos,
    legendas). Altera e devolve o mesmo objeto. Levanta BotCheckError/DownloadFailed.

    deep=True (padrao, video que vai ser processado): le tambem os sinais de momento, em paralelo e com
    limite de ~25 s: extra["comment_marks"] (horarios citados nos comentarios top do YouTube, se
    busca.ler_comentarios) e extra["chat_spikes"] (picos do chat gravado da Twitch/live do YouTube, se
    busca.ler_chat). A descoberta ampla chama com deep=False."""
    info = fetch_info(c.url, cfg)
    c.title = info.get("title") or c.title
    c.channel = info.get("channel") or info.get("uploader") or c.channel
    c.channel_url = info.get("channel_url") or info.get("uploader_url") or c.channel_url
    if info.get("duration"):
        c.duration = float(info["duration"])
    for attr, key in (("views", "view_count"), ("likes", "like_count"), ("comments", "comment_count")):
        if info.get(key) is not None:
            setattr(c, attr, int(info[key]))
    ts_list = [t for t in (info.get("release_timestamp"), info.get("timestamp")) if t]
    if ts_list:
        c.upload_ts = float(min(ts_list))   # inicio da live / publicacao (o que vier primeiro)
    elif info.get("upload_date"):
        try:
            from datetime import datetime, timezone

            c.upload_ts = datetime.strptime(info["upload_date"], "%Y%m%d").replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            pass
    status = info.get("live_status")
    c.is_live = status == "is_live" or bool(info.get("is_live"))
    c.was_live = status in ("was_live", "post_live") or bool(info.get("was_live"))
    c.thumbnail = info.get("thumbnail") or c.thumbnail
    if info.get("description"):
        c.description = info["description"][:3000]
    c.extra = dict(c.extra or {})
    c.extra["heatmap"] = [
        {"start_time": float(h["start_time"]), "end_time": float(h["end_time"]), "value": float(h["value"])}
        for h in (info.get("heatmap") or []) if h.get("start_time") is not None
    ]
    c.extra["chapters"] = [
        {"start_time": float(ch.get("start_time") or 0), "end_time": float(ch.get("end_time") or 0),
         "title": ch.get("title") or ""}
        for ch in (info.get("chapters") or [])
    ]
    manual, auto = _sub_langs(info)
    c.has_subtitles = _has_useful_subs(info)
    c.extra["subtitle_langs"] = {"manual": manual[:20],
                                 "auto": [k for k in auto if k.endswith("-orig") or k.startswith("pt")][:10]}
    c.extra["language"] = info.get("language")
    c.extra["live_status"] = status
    if info.get("channel_follower_count"):
        c.extra["channel_followers"] = int(info["channel_follower_count"])
    if info.get("channel_id"):
        c.extra["channel_id"] = str(info["channel_id"])
    if info.get("categories"):
        c.extra["categories"] = list(info["categories"])[:5]
    if info.get("tags"):
        c.extra["tags"] = list(info["tags"])[:20]
    if status == "post_live":
        c.extra["aviso"] = "live terminou ha pouco e o YouTube ainda esta processando (so as ultimas 2 h baixam)"
    c.extra["enriched"] = True
    if deep:
        try:
            _moment_signals(c, info, cfg)
        except Exception as e:  # noqa: BLE001  (sinais extras nunca derrubam o enriquecimento)
            _log.info("sinais de momento de %s falharam: %s", c.id, e)
    return c


# ======================================================================= sinais de momento (comentarios/chat)
_MOMENT_CACHE: dict[str, tuple[float, dict]] = {}
_MOMENT_LOCK = threading.Lock()
_MOMENT_TTL = 45 * 60


def _moment_signals(c: Candidate, info: dict, cfg) -> None:
    """Preenche extra["comment_marks"] e extra["chat_spikes"] (cache de 45 min por video)."""
    from .discovery import momentos

    with _MOMENT_LOCK:
        hit = _MOMENT_CACHE.get(c.id)
    if hit and time.time() - hit[0] < _MOMENT_TTL:
        c.extra.update(hit[1])
        return
    want_cm = (bool(_cfg_get(cfg, "busca.ler_comentarios", True)) and c.platform == "youtube"
               and not c.is_live and (c.comments is None or c.comments > 0))
    want_chat = bool(_cfg_get(cfg, "busca.ler_chat", True)) and (
        (c.platform == "youtube" and "live_chat" in (info.get("subtitles") or {}))
        or (c.platform == "twitch" and str(info.get("id") or "").startswith("v")))
    if not (want_cm or want_chat):
        return
    t0 = time.time()
    found: dict = {}
    jobs: dict[str, threading.Thread] = {}

    def run_cm():
        r = momentos.comment_marks(c, cfg, duration=c.duration)
        if r is not None:
            found["comment_marks"] = r["marks"]
            found["top_comments"] = r.get("top") or []
            found["comentarios_info"] = {k: r[k] for k in ("lidos", "com_tempo", "tempo_s")}

    def run_chat():
        r = momentos.chat_spikes(c, cfg, info)
        if r is not None:
            found["chat_spikes"] = r["spikes"]
            found["chat_info"] = {k: v for k, v in r.items() if k != "spikes"}

    if want_cm:
        jobs["cm"] = threading.Thread(target=run_cm, daemon=True, name="sinal-coment")
    if want_chat:
        jobs["chat"] = threading.Thread(target=run_chat, daemon=True, name="sinal-chat")
    for th in jobs.values():
        th.start()
    limit = float(_cfg_get(cfg, "busca.sinais_tempo_max_s", 28))
    for th in jobs.values():
        th.join(max(0.1, limit - (time.time() - t0)))
    res = dict(found)   # copia: thread atrasada nao altera depois
    c.extra.update(res)
    with _MOMENT_LOCK:
        _MOMENT_CACHE[c.id] = (time.time(), res)
        if len(_MOMENT_CACHE) > 60:
            for k, _ in sorted(_MOMENT_CACHE.items(), key=lambda kv: kv[1][0])[:20]:
                _MOMENT_CACHE.pop(k, None)
    _log.info("sinais de momento %s: %d marcas de comentario, %d picos de chat (%.1fs)", c.id,
              len(res.get("comment_marks") or []), len(res.get("chat_spikes") or []), time.time() - t0)


# ======================================================================= legendas
def _subtitle_options(info: dict) -> list[tuple[str, str, str, bool]]:
    """[(lang, ext, url, is_auto)] em ordem de preferencia. Faixas traduzidas automaticamente (tlang) ficam
    por ultimo: o YouTube costuma responder 429 para elas."""
    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    lang = (info.get("language") or "").split("-")[0]
    order: list[tuple[dict, list[str], str, bool]] = [
        (auto, ["pt-orig"], "json3", True),
        (subs, ["pt-BR", "pt", "pt-PT"], "json3", False),
        (subs, ["pt-BR", "pt", "pt-PT"], "vtt", False),
    ]
    if lang == "pt":
        order.append((auto, ["pt", "pt-BR"], "json3", True))
    if lang and lang != "pt":
        order += [(auto, [f"{lang}-orig"], "json3", True), (subs, [lang], "json3", False), (subs, [lang], "vtt", False)]
    order += [(auto, ["pt-orig"], "vtt", True)]
    if lang != "pt":
        order.append((auto, ["pt-BR", "pt"], "json3", True))   # traducao automatica (ultimo recurso)
    out, seen = [], set()
    for table, langs, ext, is_auto in order:
        for lg in langs:
            for tr in table.get(lg) or []:
                if tr.get("ext") == ext and tr.get("url") and (lg, ext, is_auto) not in seen:
                    seen.add((lg, ext, is_auto))
                    out.append((lg, ext, tr["url"], is_auto))
    if not out:
        for table, is_auto in ((subs, False), (auto, True)):
            for lg, tracks in table.items():
                if lg.split("-")[0] == "pt":
                    for tr in tracks:
                        if tr.get("ext") in ("json3", "vtt", "srt") and tr.get("url"):
                            out.append((lg, tr["ext"], tr["url"], is_auto))
                            break
    return out


def _valid_sub(data: bytes, ext: str) -> bool:
    if not data or len(data) < 20:
        return False
    if ext == "json3":
        try:
            return bool(json.loads(data.decode("utf-8", "replace")).get("events"))
        except ValueError:
            return False
    if ext == "vtt":
        return data.lstrip(b"\xef\xbb\xbf").startswith(b"WEBVTT")
    return True


def download_platform_subtitles(c: Candidate, cfg, dest_dir) -> Path | None:
    """Baixa a legenda da plataforma (prefere .json3 automatica pt-orig/pt = tempo por palavra; senao .vtt).
    Devolve None se nao houver legenda util."""
    import yt_dlp

    from .discovery import net

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    info = fetch_info(c.url, cfg)
    options = _subtitle_options(info)
    if not options:
        return None
    stem = slugify(c.id, 40)
    for lang, ext, url, is_auto in options[:4]:
        out = dest / f"{stem}.{lang}.{ext}"
        r = net.get(url, timeout=30, retries=1, what="legenda")
        if r is not None and _valid_sub(r.content, ext):
            out.write_bytes(r.content)
            _log.info("legenda %s (%s, %s) salva em %s", lang, ext, "auto" if is_auto else "manual", out.name)
            return out
    # reserva: deixa o yt-dlp baixar a primeira opcao (ele sabe lidar com clientes/tokens especiais)
    lang, ext, _url, is_auto = options[0]
    _log.info("download direto da legenda falhou; tentando pelo yt-dlp (%s %s)", lang, ext)
    tmpl = str(dest / f"{stem}.%(ext)s")
    opts = ytdlp_opts(cfg, skip_download=True, writesubtitles=not is_auto, writeautomaticsub=is_auto,
                      subtitleslangs=[lang], subtitlesformat=ext, outtmpl={"default": tmpl, "subtitle": tmpl})
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([c.url])
    except yt_dlp.utils.DownloadError as e:
        _raise_friendly(e)
        _log.info("legenda pelo yt-dlp falhou: %s", _short_err(e))
        return None
    out = dest / f"{stem}.{lang}.{ext}"
    for f in sorted(dest.glob(f"{stem}*.{ext}"), key=lambda p: -p.stat().st_mtime):
        if _valid_sub(f.read_bytes(), ext):
            if f != out:
                f.replace(out)
            return out
    return None


# ======================================================================= selecao de formatos
def _av_format_spec(platform: str, max_height: int) -> str:
    h = int(max_height)
    if platform in ("twitch", "kick"):
        return f"b[height<={h}]/b"
    # HLS primeiro: so baixamos os segmentos do trecho (5x mais rapido que seek em https no YouTube)
    hls = (f"bv*[height<={h}][vcodec^=avc1][protocol^=m3u8]+ba[protocol^=m3u8]"
           f"/bv*[height<={h}][protocol^=m3u8]+ba[protocol^=m3u8]/")
    return (hls + f"bv*[height<={h}][vcodec^=avc1]+ba[acodec^=mp4a]/bv*[height<={h}][vcodec^=vp]+ba"
            f"/bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b")


def _audio_format_spec(platform: str) -> str:
    if platform in ("twitch", "kick"):
        # sem faixa so de audio (Kick): a variante de menor resolucao, com audio
        return "ba[vcodec=none]/Audio_Only/audio_only/w[acodec!=none]/worst"
    return "ba[abr<=80][vcodec=none]/wa[abr>=40][vcodec=none]/ba[vcodec=none]/wa/worst"


def _select(info: dict, spec: str, cfg) -> list[dict]:
    """Aplica o seletor de formatos do yt-dlp sobre um info ja extraido."""
    import yt_dlp

    fmts = info.get("formats") or [info]
    with yt_dlp.YoutubeDL(ytdlp_opts(cfg)) as ydl:
        selector = ydl.build_format_selector(spec)
        ctx = {
            "formats": fmts,
            "has_merged_format": any("none" not in (f.get("acodec"), f.get("vcodec")) for f in fmts),
            "incomplete_formats": (all(f.get("vcodec") == "none" for f in fmts)
                                   or all(f.get("acodec") == "none" for f in fmts)),
        }
        chosen = list(selector(ctx))
    if not chosen:
        raise DownloadFailed("nenhum formato compativel encontrado")
    f = chosen[0]
    return list(f.get("requested_formats") or [f])


def _platform(c: Candidate, info: dict | None = None) -> str:
    if c.platform and c.platform != "outro":
        return c.platform
    key = ((info or {}).get("extractor_key") or "").lower()
    for p in ("youtube", "twitch", "kick", "rumble"):
        if p in key:
            return p
    return "outro"


# ======================================================================= ffmpeg helpers
def _ff_headers(fmt: dict, info: dict) -> list[str]:
    hdrs = fmt.get("http_headers") or info.get("http_headers") or {}
    if not hdrs:
        return []
    return ["-headers", "".join(f"{k}: {v}\r\n" for k, v in hdrs.items())]


def _hls_snapshot(m3u8_url: str, headers: dict, start: float, end: float, work: Path,
                  tag: str = "") -> tuple[Path, float] | None:
    """Baixa a media playlist, guarda so os segmentos de [start, end] (com folga) e fecha com ENDLIST.
    Devolve (playlist local, deslocamento de start dentro dela). Funciona para VOD e live em andamento."""
    from .discovery import net

    r = net.get(m3u8_url, headers=headers, timeout=30, retries=2, what="m3u8")
    if r is None:
        return None
    text = r.text
    if "#EXT-X-STREAM-INF" in text:   # veio a master playlist: pega a primeira variante
        for line in text.splitlines():
            if line and not line.startswith("#"):
                return _hls_snapshot(urljoin(m3u8_url, line.strip()), headers, start, end, work, tag)
        return None
    header: list[str] = []
    segs: list[tuple[float, float, list[str]]] = []   # (ini, dur, linhas)
    pending: list[str] = []
    t = 0.0
    dur = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF:"):
            try:
                dur = float(line[8:].split(",")[0])
            except ValueError:
                dur = 0.0
            pending.append(line)
        elif line.startswith("#EXT-X-MAP:"):
            m = re.search(r'URI="([^"]+)"', line)
            if m:
                line = line.replace(m.group(1), urljoin(m3u8_url, m.group(1)))
            header.append(line)
        elif line.startswith("#EXT-X-KEY:"):
            m = re.search(r'URI="([^"]+)"', line)
            if m:
                line = line.replace(m.group(1), urljoin(m3u8_url, m.group(1)))
            pending.append(line)
        elif line.startswith("#EXT-X-ENDLIST"):
            continue
        elif line.startswith("#EXT-X-PLAYLIST-TYPE") or line.startswith("#EXT-X-MEDIA-SEQUENCE") \
                or line.startswith("#EXT-X-DISCONTINUITY-SEQUENCE"):
            continue
        elif line.startswith("#EXTM3U") or line.startswith("#EXT-X-VERSION") or line.startswith("#EXT-X-TARGETDURATION") \
                or line.startswith("#EXT-X-INDEPENDENT-SEGMENTS"):
            header.append(line)
        elif line.startswith("#"):
            if line.startswith(("#EXT-X-DISCONTINUITY", "#EXT-X-BYTERANGE", "#EXT-X-PROGRAM-DATE-TIME")):
                pending.append(line)
            # outras tags proprietarias (ex.: #EXT-X-TWITCH-*) sao ignoradas
        else:
            d = dur if dur is not None else 0.0
            segs.append((t, d, pending + [urljoin(m3u8_url, line)]))
            t += d
            pending, dur = [], None
    if not segs:
        return None
    first = next((i for i, (s0, d, _) in enumerate(segs) if s0 + d > start), None)
    if first is None:
        raise DownloadFailed(f"trecho {start:.0f}s esta alem do fim do video ({t:.0f}s)")
    first = max(0, first - 1)   # um segmento de folga antes
    last = next((i for i, (s0, _, _) in enumerate(segs) if s0 >= end), len(segs))
    last = min(len(segs), last + 1)
    sel = segs[first:last]
    if "#EXTM3U" not in header:
        header.insert(0, "#EXTM3U")
    out = ["#EXTM3U"] + [h for h in header if h != "#EXTM3U"] + ["#EXT-X-PLAYLIST-TYPE:VOD", "#EXT-X-MEDIA-SEQUENCE:0"]
    if not any(h.startswith("#EXT-X-TARGETDURATION") for h in header):
        out.append(f"#EXT-X-TARGETDURATION:{int(max(d for _, d, _ in sel)) + 1}")
    for _, _, lines in sel:
        out.extend(lines)
    out.append("#EXT-X-ENDLIST")
    work.mkdir(parents=True, exist_ok=True)
    tag = re.sub(r"[^\w]", "", str(tag or "x"))[:20]
    pl = work / f"trecho_{tag}_{int(start * 1000)}_{int(end * 1000)}.m3u8"
    pl.write_text("\n".join(out) + "\n", encoding="utf-8")
    return pl, max(0.0, start - sel[0][0])


def _probe(path: Path) -> dict:
    fp = tools.ffprobe()
    if not fp:
        return {}
    r = run_cmd([fp, "-v", "error", "-show_entries", "format=duration,start_time:stream=codec_type,codec_name,width,height",
                 "-of", "json", str(path)], timeout=60)
    try:
        return json.loads(r.stdout or "{}")
    except ValueError:
        return {}


def _check_output(path: Path, expected: float, need_video: bool = True) -> float:
    """Confere com ffprobe: existe, tem audio(+video) e a duracao bate (+-0.5 s, ou mais curto se o video acabou)."""
    if not path.is_file() or path.stat().st_size < 1000:
        raise DownloadFailed(f"arquivo nao gerado: {path.name}")
    pr = _probe(path)
    kinds = {s.get("codec_type") for s in pr.get("streams") or []}
    if need_video and "video" not in kinds:
        raise DownloadFailed(f"{path.name} saiu sem video")
    if "audio" not in kinds:
        _log.warning("%s saiu sem audio", path.name)
    try:
        dur = float((pr.get("format") or {}).get("duration") or 0)
    except ValueError:
        dur = 0.0
    if expected and dur > expected + 0.6:
        raise DownloadFailed(f"{path.name}: duracao {dur:.2f}s maior que a pedida ({expected:.2f}s)")
    return dur


def _encoder_args(cfg) -> list[str]:
    enc = str(_cfg_get(cfg, "download.encoder_trechos", "libx264"))
    if enc == "h264_amf":
        return ["-c:v", "h264_amf", "-quality", "quality", "-rc", "cqp", "-qp_i", "18", "-qp_p", "20"]
    return ["-c:v", "libx264", "-preset", str(_cfg_get(cfg, "download.preset_trechos", "veryfast")),
            "-crf", str(_cfg_get(cfg, "download.crf_trechos", 18))]


def _ffmpeg_section(info: dict, fmts: list[dict], start: float, end: float, out: Path, cfg, work: Path) -> None:
    ff = tools.ffmpeg()
    if not ff:
        raise DownloadFailed("ffmpeg nao encontrado no PATH")
    dur = end - start
    args = [ff, "-hide_banner", "-nostdin", "-y", "-loglevel", "error"]
    maps: list[str] = []
    for i, f in enumerate(fmts):
        proto = f.get("protocol") or ""
        url = f["url"]
        if proto.startswith("m3u8"):
            hdrs = f.get("http_headers") or info.get("http_headers") or {}
            snap = _hls_snapshot(url, hdrs, start, end, work, tag=f"{i}_{f.get('format_id')}")
            if not snap:
                raise DownloadFailed("nao consegui ler a playlist HLS")
            pl, off = snap
            args += ["-protocol_whitelist", "file,http,https,tcp,tls,crypto", "-allowed_extensions", "ALL"]
            args += ["-ss", f"{off:.3f}", "-i", str(pl)]
        else:
            args += _ff_headers(f, info) + ["-ss", f"{start:.3f}", "-i", url]
        has_v = f.get("vcodec") not in (None, "none")
        has_a = f.get("acodec") not in (None, "none")
        if len(fmts) == 1:
            maps = ["-map", "0:v:0", "-map", "0:a:0?"]
        else:
            if has_v and not any(m.endswith(":v:0") for m in maps):
                maps += ["-map", f"{i}:v:0"]
            elif has_a:
                maps += ["-map", f"{i}:a:0"]
    if len(fmts) > 1 and not any(":a:" in m for m in maps):
        maps += ["-map", "1:a:0?"]
    args += ["-t", f"{dur:.3f}"] + maps + _encoder_args(cfg) + [
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", str(out)]
    timeout = max(180.0, dur * 8)
    r = run_cmd(args, timeout=timeout)
    if r.returncode != 0:
        raise DownloadFailed(f"ffmpeg falhou ({r.returncode}): {(r.stderr or '').strip()[-400:]}")


def _ytdlp_ranges(c: Candidate, start: float, end: float, out: Path, cfg, spec: str) -> None:
    """Reserva: deixa o yt-dlp cortar (download_ranges + re-encode nas pontas)."""
    import yt_dlp
    from yt_dlp.utils import download_range_func

    tmpl = str(out.with_suffix("")) + ".%(ext)s"
    opts = ytdlp_opts(cfg, format=spec, outtmpl=tmpl, merge_output_format="mp4",
                      download_ranges=download_range_func(None, [(start, end)]), force_keyframes_at_cuts=True,
                      external_downloader_args={"ffmpeg_o": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                                                             "-c:a", "aac", "-b:a", "192k"]})
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([c.url])
    except yt_dlp.utils.DownloadError as e:
        _raise_friendly(e)
        raise DownloadFailed(_short_err(e)) from e
    got = sorted(out.parent.glob(out.stem + ".*"), key=lambda p: -p.stat().st_mtime)
    got = [g for g in got if g.suffix in (".mp4", ".mkv", ".webm")]
    if not got:
        raise DownloadFailed("yt-dlp nao gerou o trecho")
    if got[0] != out:
        got[0].replace(out)


def download_sections(c: Candidate, sections: list[tuple[float, float]], cfg, dest_dir,
                      max_height: int = 1080) -> list[Path]:
    """Um mp4 (H.264 + AAC) por trecho; o arquivo i comeca exatamente em sections[i][0] do original."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    work = dest / "_hls"
    info = fetch_info(c.url, cfg)
    platform = _platform(c, info)
    spec = _av_format_spec(platform, max_height)
    total = float(info.get("duration") or c.duration or 0) or None
    outs: list[Path] = []
    for idx, (s, e) in enumerate(sections):
        s = max(0.0, float(s))
        e = float(e)
        if total and not info.get("is_live"):
            e = min(e, total)
        if e - s < 0.5:
            raise DownloadFailed(f"trecho invalido: {s:.1f}-{e:.1f}s")
        out = dest / f"{slugify(c.id, 40)}_t{idx + 1:02d}_{int(s)}-{int(e)}.mp4"
        t0 = time.time()
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                if attempt < 2:
                    inf = info if attempt == 0 else fetch_info(c.url, cfg, fresh=True)
                    _ffmpeg_section(inf, _select(inf, spec, cfg), s, e, out, cfg, work)
                else:
                    _log.info("usando yt-dlp download_ranges como reserva para %s", out.name)
                    _ytdlp_ranges(c, s, e, out, cfg, spec)
                got = _check_output(out, e - s)
                _log.info("trecho %d (%.1f-%.1fs) ok: %.2fs em %.1fs -> %s", idx + 1, s, e, got, time.time() - t0,
                          out.name)
                last_err = None
                break
            except NeedsUserAction:
                raise
            except Exception as ex:  # noqa: BLE001
                last_err = ex
                _log.warning("trecho %d tentativa %d falhou: %s", idx + 1, attempt + 1, ex)
                out.unlink(missing_ok=True)
        if last_err is not None:
            raise DownloadFailed(f"nao consegui baixar o trecho {s:.0f}-{e:.0f}s de {c.id}: {last_err}")
        outs.append(out)
    shutil.rmtree(work, ignore_errors=True)
    return outs


# ======================================================================= audio e video inteiro
def download_audio(c: Candidate, cfg, dest_dir, start: float | None = None, end: float | None = None) -> Path:
    """Audio leve para o Whisper. Video inteiro: o yt-dlp baixa a faixa de audio mais leve (m4a/webm ~50 kbps
    no YouTube; Audio_Only HLS na Twitch, convertido para Opus mono 32 kbps se ficar grande).
    start/end opcionais (tempos do original) baixam so um pedaco via ffmpeg (Opus mono 16 kHz)."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    info = fetch_info(c.url, cfg)
    platform = _platform(c, info)
    fmts = _select(info, _audio_format_spec(platform), cfg)
    f = fmts[0]
    ff = tools.ffmpeg()
    if not ff:
        raise DownloadFailed("ffmpeg nao encontrado no PATH")
    total = float(info.get("duration") or c.duration or 0)
    partial = start is not None or end is not None
    s = max(0.0, float(start or 0))
    e = float(end) if end else total
    enc = ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "32k", "-application", "voip"]
    proto = f.get("protocol") or ""
    t0 = time.time()
    live = bool(info.get("is_live"))
    has_video = f.get("vcodec") != "none"   # None = desconhecido (Kick): trata como video
    # so ha formato com video (Kick, clipes): o ffmpeg le a stream e grava so o audio (nao enche o disco)
    stream_only_audio = has_video
    if not partial and not live and not stream_only_audio:
        out = _ytdlp_audio(c, cfg, dest, f.get("format_id") or "ba", enc)
    else:
        if not e:
            raise DownloadFailed("video ao vivo sem duracao conhecida: informe start/end")
        name = f"_audio_{int(s)}-{int(e)}" if partial else "_audio"
        out = dest / f"{slugify(c.id, 40)}{name}.opus"
        args = [ff, "-hide_banner", "-nostdin", "-y", "-loglevel", "error"]
        if proto.startswith("m3u8"):
            snap = _hls_snapshot(f["url"], f.get("http_headers") or {}, s, e, dest / "_hls", tag="audio")
            if not snap:
                raise DownloadFailed("nao consegui ler a playlist HLS do audio")
            pl, off = snap
            args += ["-protocol_whitelist", "file,http,https,tcp,tls,crypto", "-allowed_extensions", "ALL",
                     "-ss", f"{off:.3f}", "-i", str(pl)]
        else:
            args += _ff_headers(f, info) + ["-ss", f"{s:.3f}", "-i", f["url"]]
        r = run_cmd(args + ["-t", f"{e - s:.3f}"] + enc + [str(out)], timeout=max(900.0, (e - s)))
        shutil.rmtree(dest / "_hls", ignore_errors=True)
        if r.returncode != 0:
            raise DownloadFailed(f"ffmpeg (audio) falhou: {(r.stderr or '')[-300:]}")
    if not out.is_file() or out.stat().st_size < 1000:
        raise DownloadFailed("audio nao foi gerado")
    _log.info("audio de %s pronto em %.1fs (%.1f MB): %s", c.id, time.time() - t0, out.stat().st_size / 1e6, out.name)
    return out


def _ytdlp_audio(c: Candidate, cfg, dest: Path, format_id: str, enc: list[str]) -> Path:
    import yt_dlp

    base = dest / f"{slugify(c.id, 40)}_audio"
    for old in dest.glob(base.name + ".*"):
        old.unlink(missing_ok=True)
    opts = ytdlp_opts(cfg, format=format_id, outtmpl=str(base) + ".%(ext)s")
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([c.url])
    except yt_dlp.utils.DownloadError as e:
        _raise_friendly(e)
        raise DownloadFailed(_short_err(e)) from e
    raws = [p for p in dest.glob(base.name + ".*") if not p.name.endswith((".part", ".ytdl", ".m3u8"))]
    if not raws:
        raise DownloadFailed("yt-dlp nao gerou o audio")
    raw = max(raws, key=lambda p: p.stat().st_size)
    # arquivo grande (ex.: Audio_Only 160 kbps da Twitch): comprime para Opus mono 32 kbps
    if raw.stat().st_size > float(_cfg_get(cfg, "download.audio_max_mb", 120)) * 1e6:
        out = base.with_name(base.name + "_16k.opus")
        r = run_cmd([tools.ffmpeg(), "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-i", str(raw)]
                    + enc + [str(out)], timeout=7200)
        if r.returncode == 0 and out.is_file():
            raw.unlink(missing_ok=True)
            return out
        _log.warning("conversao do audio falhou (%s); usando o original", (r.stderr or "")[-200:])
    return raw


def download_video(c: Candidate, cfg, dest_dir, max_height: int = 1080) -> Path:
    """Video inteiro (para videos curtos). MP4, de preferencia H.264 + AAC."""
    import yt_dlp

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    info = fetch_info(c.url, cfg)
    platform = _platform(c, info)
    dur = float(info.get("duration") or 0)
    max_s = float(_cfg_get(cfg, "download.video_inteiro_max_s", 1800))
    if info.get("is_live") or (dur and dur > max_s):
        _log.info("video longo/ao vivo (%.0fs): baixando como trecho", dur)
        return download_sections(c, [(0.0, min(dur or max_s, max_s))], cfg, dest, max_height)[0]
    base = dest / slugify(c.id, 40)
    opts = ytdlp_opts(cfg, format=_av_format_spec(platform, max_height), outtmpl=str(base) + ".%(ext)s",
                      merge_output_format="mp4", format_sort=["vcodec:h264", "acodec:aac"] if platform == "youtube" else [])
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([c.url])
    except yt_dlp.utils.DownloadError as e:
        _raise_friendly(e)
        raise DownloadFailed(f"nao consegui baixar {c.url}: {_short_err(e)}") from e
    got = [p for p in dest.glob(base.name + ".*") if p.suffix in (".mp4", ".mkv", ".webm", ".mov")]
    if not got:
        raise DownloadFailed("yt-dlp nao gerou o video")
    out = max(got, key=lambda p: p.stat().st_mtime)
    if out.suffix != ".mp4":
        mp4 = out.with_suffix(".mp4")
        r = run_cmd([tools.ffmpeg(), "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-i", str(out),
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k",
                     "-movflags", "+faststart", str(mp4)], timeout=3600)
        if r.returncode == 0:
            out.unlink(missing_ok=True)
            out = mp4
    return out
