"""GQL publica da Twitch (a mesma que o site usa, sem login nem chave propria). Nunca levanta.

Verificado em nov/2026: consultas "cruas" (nao persistidas) funcionam para usuario, clipes e
comentarios do VOD por offset (`comments(contentOffsetSeconds: N)`). A paginacao por cursor dos
comentarios exige integridade (falha), entao o chat e lido por amostragem de offsets.
"""
from __future__ import annotations

import json
import re
import threading
import time

import requests

from .. import log

_log = log.get(__name__)

GQL_URL = "https://gql.twitch.tv/gql"
CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"   # client id publico do site twitch.tv
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/131.0.0.0 Safari/537.36")

_local = threading.local()


def _session() -> requests.Session:
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"Client-Id": CLIENT_ID, "User-Agent": _UA, "Content-Type": "text/plain;charset=UTF-8"})
        _local.s = s
    return s


def gql(query: str, timeout: float = 12.0, what: str = "") -> tuple[dict | None, int]:
    """Executa uma consulta. Devolve (data, bytes_recebidos); data=None em erro."""
    try:
        r = _session().post(GQL_URL, data=json.dumps({"query": query}), timeout=timeout)
        size = len(r.content or b"")
        if r.status_code != 200:
            _log.info("twitch gql %s: HTTP %s", what, r.status_code)
            return None, size
        j = r.json()
        if j.get("errors") and not j.get("data"):
            _log.info("twitch gql %s: %s", what, str(j["errors"])[:200])
            return None, size
        return j.get("data") or None, size
    except (requests.RequestException, ValueError) as e:
        _log.info("twitch gql %s falhou: %s", what, str(e)[:150])
        return None, 0


def _q(s: str) -> str:
    """Escapa texto para dentro de aspas na consulta."""
    return json.dumps(str(s))


_LOGIN_RX = re.compile(r"^[a-zA-Z0-9_]{2,30}$")


def iso_ts(s: str | None) -> float | None:
    """'2026-11-23T01:15:22Z' -> epoch."""
    if not s:
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def channels_clips(logins: list[str], day_n: int = 15, week_n: int = 40, timeout: float = 12.0) -> dict[str, dict]:
    """Para cada login: {"login", "nome", "ao_vivo", "espectadores", "clipes_dia": [...], "views_semana": [...]}.

    clipes_dia: [{"id","slug","titulo","views","criado_ts","duracao","vod_id","vod_offset" (inicio do clipe no VOD),
                  "vod_dur","vod_inicio_ts","vod_status" (RECORDED | RECORDING),"vod_titulo"}]
    Consulta em lotes de 5 canais por requisicao."""
    out: dict[str, dict] = {}
    valid = [lg for lg in dict.fromkeys(x.strip().lower() for x in logins) if _LOGIN_RX.match(lg)]
    for i in range(0, len(valid), 5):
        chunk = valid[i: i + 5]
        parts = []
        for k, lg in enumerate(chunk):
            parts.append(
                f'u{k}: user(login: {_q(lg)}) {{ login displayName stream {{ id createdAt viewersCount }} '
                f'dia: clips(first: {int(day_n)}, criteria: {{period: LAST_DAY, sort: VIEWS_DESC}}) '
                '{ edges { node { id slug title viewCount createdAt durationSeconds videoOffsetSeconds '
                'video { id title lengthSeconds createdAt status } } } } '
                f'semana: clips(first: {int(week_n)}, criteria: {{period: LAST_WEEK, sort: VIEWS_DESC}}) '
                '{ edges { node { viewCount } } } }')
        data, _ = gql("query { " + " ".join(parts) + " }", timeout=timeout, what="clipes")
        if not data:
            continue
        for k, lg in enumerate(chunk):
            u = data.get(f"u{k}")
            if not u:
                continue
            clips = []
            for e in ((u.get("dia") or {}).get("edges") or []):
                n = e.get("node") or {}
                v = n.get("video") or {}
                clips.append({
                    "id": str(n.get("id") or ""), "slug": n.get("slug") or "", "titulo": n.get("title") or "",
                    "views": int(n.get("viewCount") or 0), "criado_ts": iso_ts(n.get("createdAt")),
                    "duracao": float(n.get("durationSeconds") or 30),
                    "vod_id": str(v.get("id")) if v.get("id") else None,
                    "vod_offset": float(n["videoOffsetSeconds"]) if n.get("videoOffsetSeconds") is not None else None,
                    "vod_dur": float(v.get("lengthSeconds") or 0) or None,
                    "vod_inicio_ts": iso_ts(v.get("createdAt")),
                    "vod_status": v.get("status"), "vod_titulo": v.get("title") or "",
                })
            week = [int((e.get("node") or {}).get("viewCount") or 0) for e in ((u.get("semana") or {}).get("edges") or [])]
            st = u.get("stream") or {}
            out[lg] = {"login": u.get("login") or lg, "nome": u.get("displayName") or lg, "ao_vivo": bool(st),
                       "espectadores": int(st.get("viewersCount") or 0) if st else 0, "clipes_dia": clips,
                       "views_semana": week}
    return out


def vod_chat_page(vod_id: str, offset: float, timeout: float = 10.0) -> tuple[list[tuple[float, str]] | None, int]:
    """Mensagens do chat gravado a partir de `offset` (uma pagina, ~50 mensagens). (lista, bytes)."""
    vid = str(vod_id).lstrip("v")
    if not vid.isdigit():
        return None, 0
    q = ('query { video(id: %s) { comments(contentOffsetSeconds: %d) { edges { node { contentOffsetSeconds '
         'message { fragments { text } } } } } } }') % (_q(vid), max(0, int(offset)))
    data, size = gql(q, timeout=timeout, what="chat")
    if not data:
        return None, size
    edges = (((data.get("video") or {}).get("comments") or {}).get("edges")) or []
    msgs = []
    for e in edges:
        n = e.get("node") or {}
        t = n.get("contentOffsetSeconds")
        if t is None:
            continue
        txt = "".join(str(f.get("text") or "") for f in ((n.get("message") or {}).get("fragments") or []))
        msgs.append((float(t), txt))
    return msgs, size


def vod_accessible(vod_id: str, timeout: float = 10.0) -> bool | None:
    """O VOD baixa sem login? False = so para inscritos/removido; None = nao deu para saber."""
    vid = str(vod_id).lstrip("v")
    if not vid.isdigit():
        return False
    q = ('{ videoPlaybackAccessToken(id: %s, params: {platform: "web", playerBackend: "mediaplayer", '
         'playerType: "site"}) { value signature } }') % _q(vid)
    data, _ = gql(q, timeout=timeout, what="token")
    tok = (data or {}).get("videoPlaybackAccessToken") or {}
    if not tok.get("value"):
        return None if data is None else False
    try:
        r = _session().get(f"https://usher.ttvnw.net/vod/{vid}.m3u8",
                           params={"allow_source": "true", "allow_audio_only": "true", "platform": "web",
                                   "player": "twitchweb", "sig": tok["signature"], "token": tok["value"]},
                           timeout=timeout)
        if r.status_code == 200 and "#EXTM3U" in r.text[:200]:
            return True
        return False if r.status_code in (403, 404) else None
    except requests.RequestException:
        return None


def ping() -> float | None:
    """Tempo de resposta da GQL (diagnostico)."""
    t = time.time()
    data, _ = gql('query { user(login: "twitch") { id } }', timeout=8, what="ping")
    return (time.time() - t) if data else None
