"""Twitch, Kick e Rumble via extratores do yt-dlp (sem API key). Nunca levantam: logam e devolvem [].

Twitch (verificado em nov/2026): twitch.tv/<login>/videos?filter=archives&sort=time e
twitch.tv/<login>/clips?filter=clips&range=24hr funcionam em modo flat; a extracao completa de um VOD
traz timestamp, duracao, capitulos (jogos) e se a live ainda esta em andamento.
O yt-dlp NAO informa em que ponto do VOD cada clipe foi feito; estimamos:
    offset ~= criacao_do_clipe - inicio_do_VOD - duracao_do_clipe   (clipes pegam os ~30 s antes do clique)
e marcamos "offset_aprox": True.

Kick: kick.com/<canal>/videos e /clips funcionam em modo flat (yt-dlp avisa que falta "impersonate").
Rumble: rumble.com nao resolve DNS no Brasil (bloqueado desde 2025) - fica como melhor esforco.
"""
from __future__ import annotations

import re
import time

from .. import log

_log = log.get(__name__)


def _flat(url: str, n: int) -> list[dict]:
    import yt_dlp

    from ..download import ytdlp_opts

    opts = ytdlp_opts(None, extract_flat="in_playlist", playlistend=n, skip_download=True,
                      socket_timeout=20, extractor_retries=1, retries=2)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:  # noqa: BLE001
        _log.info("yt-dlp flat falhou em %s: %s", url, str(e)[:200])
        return []
    return [e for e in (info or {}).get("entries") or [] if e]


def _strip_smuggle(url: str) -> str:
    return re.sub(r"#__youtubedl_smuggle=.*$", "", url or "")


# ===================================================================== Twitch
def twitch_channel(login: str, cfg, window_h: float, n_vods: int = 3, n_clips: int = 20,
                   full_vods: int = 2) -> list[dict]:
    """VODs recentes (com clipes populares das ultimas 24 h mapeados) + clipes soltos. Itens 'raw'."""
    try:
        from ..download import fetch_info

        now = time.time()
        vods = _flat(f"https://www.twitch.tv/{login}/videos?filter=archives&sort=time", n_vods)
        clips = _flat(f"https://www.twitch.tv/{login}/clips?filter=clips&range=24hr", n_clips)
        out: list[dict] = []
        vod_items: list[dict] = []
        for i, v in enumerate(vods):
            vid = v.get("id") or ""
            url = v.get("url") or f"https://www.twitch.tv/videos/{vid.lstrip('v')}"
            item = {
                "platform": "twitch", "id": vid, "url": url, "title": v.get("title") or "",
                "channel": login, "channel_url": f"https://www.twitch.tv/{login}",
                "duration": v.get("duration"), "views": v.get("view_count"), "upload_ts": None,
                "is_live": False, "was_live": True, "thumbnail": v.get("thumbnail"), "description": "",
                "extra": {"tipo": "vod", "twitch_clips": []},
            }
            if i < full_vods:
                try:
                    info = fetch_info(url, cfg)
                    item["upload_ts"] = info.get("timestamp")
                    item["duration"] = info.get("duration") or item["duration"]
                    item["is_live"] = bool(info.get("is_live"))
                    item["views"] = info.get("view_count") if info.get("view_count") is not None else item["views"]
                    item["extra"]["chapters"] = [
                        {"start_time": float(c.get("start_time") or 0), "end_time": float(c.get("end_time") or 0),
                         "title": c.get("title") or ""} for c in info.get("chapters") or []]
                    if item["is_live"]:
                        item["extra"]["vod_em_andamento"] = True
                except Exception as e:  # noqa: BLE001
                    _log.info("twitch: VOD %s sem detalhes: %s", url, str(e)[:150])
            vod_items.append(item)
        # deduz inicio dos VODs sem timestamp a partir do seguinte (ordem por data) - so para mapear clipes
        clip_items = []
        for c in clips:
            ts = c.get("timestamp")
            dur = float(c.get("duration") or 30)
            entry = {"offset": None, "duration": dur, "views": int(c.get("view_count") or 0),
                     "title": c.get("title") or "", "url": c.get("url"), "created_ts": ts}
            mapped = None
            if ts:
                for v in vod_items:
                    vts, vdur = v.get("upload_ts"), v.get("duration")
                    if vts and vdur and vts - 60 <= ts <= vts + float(vdur) + 300:
                        mapped = v
                        entry["offset"] = round(max(0.0, ts - vts - dur), 1)
                        entry["offset_aprox"] = True
                        break
            if mapped:
                mapped["extra"]["twitch_clips"].append(entry)
            clip_items.append((c, entry, mapped))
        for v in vod_items:
            v["extra"]["twitch_clips"].sort(key=lambda x: -x["views"])
            end_ts = (v["upload_ts"] or 0) + float(v.get("duration") or 0)
            if v["upload_ts"] and end_ts < now - window_h * 3600:
                continue
            if not v["upload_ts"] and not v["extra"]["twitch_clips"]:
                continue   # sem data e sem clipes: nao da para saber se e recente
            out.append(v)
        # clipes viram candidatos quando o VOD nao esta disponivel (ou ainda esta ao vivo)
        for c, entry, mapped in clip_items:
            if mapped is not None and not mapped.get("is_live") and mapped in out:
                continue
            out.append({
                "platform": "twitch", "id": str(c.get("id")), "url": c.get("url"), "title": c.get("title") or "",
                "channel": login, "channel_url": f"https://www.twitch.tv/{login}", "duration": entry["duration"],
                "views": entry["views"], "upload_ts": entry["created_ts"], "is_live": False, "was_live": False,
                "thumbnail": c.get("thumbnail"), "description": "",
                "extra": {"tipo": "clipe", "vod_url": mapped["url"] if mapped else None,
                          "vod_offset": entry["offset"]},
            })
        _log.info("twitch %s: %d VODs, %d clipes -> %d itens", login, len(vods), len(clips), len(out))
        return out
    except Exception as e:  # noqa: BLE001
        _log.warning("twitch %s falhou: %s", login, e)
        return []


# ===================================================================== Kick
def kick_channel(slug: str, cfg, window_h: float, n: int = 4, n_clips: int = 20) -> list[dict]:
    """VODs recentes da Kick com os clipes populares mapeados (mesma chave extra["twitch_clips"] usada pela
    Twitch, para o pipeline/sinais tratarem igual) + clipes soltos de VOD indisponivel/ao vivo."""
    try:
        now = time.time()
        vods = []
        for v in _flat(f"https://kick.com/{slug}/videos", n):
            ts = v.get("timestamp")
            dur = float(v.get("duration") or 0)
            vods.append({
                "platform": "kick", "id": str(v.get("id")), "url": _strip_smuggle(v.get("url") or ""),
                "title": v.get("title") or "", "channel": slug, "channel_url": f"https://kick.com/{slug}",
                "duration": dur or None, "views": v.get("view_count"), "upload_ts": ts,
                "is_live": dur == 0, "was_live": True, "thumbnail": v.get("thumbnail"), "description": "",
                "extra": {"tipo": "vod", "twitch_clips": [], **({"vod_em_andamento": True} if dur == 0 else {})},
            })
        clips = _flat(f"https://kick.com/{slug}/clips", n_clips)
        loose = []
        for c in clips:
            ts = c.get("timestamp")
            if not ts or ts < now - max(window_h, 24) * 3600:
                continue
            cdur = float(c.get("duration") or 30)
            entry = {"offset": None, "duration": cdur, "views": int(c.get("view_count") or 0),
                     "title": c.get("title") or "", "url": c.get("url"), "created_ts": ts}
            mapped = None
            for v in vods:
                vts, vdur = v["upload_ts"], v["duration"]
                if vts and vdur and vts - 60 <= ts <= vts + vdur + 300:
                    entry["offset"] = round(max(0.0, ts - vts - cdur), 1)
                    entry["offset_aprox"] = True
                    v["extra"]["twitch_clips"].append(entry)
                    mapped = v
                    break
            if mapped is None or mapped["is_live"]:
                loose.append({
                    "platform": "kick", "id": str(c.get("id")), "url": c.get("url") or "", "title": c.get("title") or "",
                    "channel": slug, "channel_url": f"https://kick.com/{slug}", "duration": cdur,
                    "views": entry["views"], "upload_ts": ts, "is_live": False, "was_live": False,
                    "thumbnail": c.get("thumbnail"), "description": "", "extra": {"tipo": "clipe"},
                })
        out = []
        for v in vods:
            v["extra"]["twitch_clips"].sort(key=lambda x: -x["views"])
            if v["upload_ts"] and v["upload_ts"] + float(v["duration"] or 0) < now - window_h * 3600:
                continue
            out.append(v)
        _log.info("kick %s: %d VODs, %d clipes -> %d itens", slug, len(vods), len(clips), len(out) + len(loose))
        return out + loose
    except Exception as e:  # noqa: BLE001
        _log.warning("kick %s falhou: %s", slug, e)
        return []


# ===================================================================== Rumble
def rumble_channel(name: str, cfg, window_h: float, n: int = 8) -> list[dict]:
    try:
        now = time.time()
        url = name if name.startswith("http") else f"https://rumble.com/c/{name}"
        out = []
        for v in _flat(url, n):
            ts = v.get("timestamp")
            if ts and ts < now - window_h * 3600:
                continue
            out.append({
                "platform": "rumble", "id": str(v.get("id")), "url": v.get("url") or "", "title": v.get("title") or "",
                "channel": name, "channel_url": url, "duration": v.get("duration"), "views": v.get("view_count"),
                "upload_ts": ts, "is_live": v.get("live_status") == "is_live",
                "was_live": v.get("live_status") == "was_live", "thumbnail": v.get("thumbnail"), "description": "",
                "extra": {},
            })
        return out
    except Exception as e:  # noqa: BLE001
        _log.warning("rumble %s falhou: %s", name, e)
        return []
