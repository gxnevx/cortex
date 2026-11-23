"""Sinais de MOMENTO para videos novos (o "mais repetidos" do YouTube quase nunca existe antes de ~50 dias).

    comment_marks(c, cfg, duration)  -> {"marks": [...], "lidos": n, "com_tempo": k, "tempo_s": x} | None
        horarios citados nos comentarios "top" do YouTube (ex.: "12:34", "1:02:03", "aos 5 minutos").
        Peso por mencao = 1 + sqrt(likes)/5; cluster forte = 3+ mencoes em 60 s (ou peso >= 4);
        citacoes isoladas (2 mencoes ou peso >= 2) entram como fracas (forte=False, ate 5).
        marks: [{"t": s, "peso": w, "n": mencoes, "exemplo": texto, "forte": bool}]
    chat_spikes(c, cfg, info)        -> {"spikes": [...], "amostras": n, "base_msgs": x, ...} | None
        picos do chat gravado: Twitch VOD (GQL publica, por offset) e replay do chat de live do YouTube
        (pagina publica + get_live_chat_replay com seek). Mensagens por 10 s, z-score robusto >= 3,
        mais densidade de risada/emote (KKKK, LUL, KEKW, OMEGALUL...).
        spikes: [{"t": s, "z": z, "msgs": msgs_por_10s, "riso": fracao}]   (t = quando o chat explodiu;
        o momento em si costuma estar 5 a 30 s antes)

Tudo barato e com limite de tempo/tamanho; nunca levanta (loga e devolve None).
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import math
import re
import statistics
import threading
import time

from .. import log
from .text import norm

_log = log.get(__name__)


def _cfg(cfg, key: str, default):
    try:
        return cfg.get(key, default) if cfg is not None else default
    except Exception:  # noqa: BLE001
        return default


# ====================================================================== timestamps em comentarios
# 1:02:03 | 12:34 | 4:56  (nao pega datas 12/11, horas "20h" nem placares "2x1")
_CLOCK = re.compile(r"(?<![\d:/.,])(?:(\d{1,2}):)?(\d{1,3}):(\d{2})(?![\d:/])")
# 1h02 | 1h 2min | 1h02m30s | 2h30
_HMS = re.compile(r"(?<![\w])(\d{1,2})\s?h\s?(\d{1,2})(?:\s?(?:min|m))?(?:\s?(\d{1,2})\s?s)?(?![\w])")
# "aos 5 minutos", "no minuto 12", "minuto 113", "nos 45 min", "em 12min"
_MINUTE = re.compile(r"\b(?:(?:aos?|nos?|em|no minuto|minuto|min)\s+(\d{1,3})\s*(?:minutos?|mins?|m)\b"
                     r"|minuto\s+(\d{1,3})\b)")


_INTRO_RX = re.compile(r"\b(comeca|comeco|inicio|inicia|pula|pular|pulem|skip|intro|abertura)\b")


def parse_timestamps(text: str, duration: float | None = None) -> list[tuple[float, float]]:
    """[(segundos, precisao 0-1)] citados no texto. precisao < 1 para "aos 5 minutos" (vago)."""
    out: list[tuple[float, float]] = []
    if not text:
        return out
    lim = (float(duration) + 5) if duration else 6 * 3600 + 600
    for m in _CLOCK.finditer(text):
        h, mi, s = m.group(1), int(m.group(2)), int(m.group(3))
        if s >= 60:
            continue
        if h is not None:
            if mi >= 60:
                continue
            t = int(h) * 3600 + mi * 60 + s
        else:
            t = mi * 60 + s
        if 5 <= t <= lim:
            out.append((float(t), 1.0))
    low = norm(text)
    for m in _HMS.finditer(low):
        hh, mm, ss = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        if mm < 60 and ss < 60 and hh < 13:
            t = hh * 3600 + mm * 60 + ss
            if 5 <= t <= lim and all(abs(t - x) > 2 for x, _ in out):
                out.append((float(t), 0.9))
    for m in _MINUTE.finditer(low):
        mins = int(m.group(1) or m.group(2))
        t = mins * 60 + 30   # meio do minuto citado
        if 30 <= t <= lim and all(abs(t - x) > 45 for x, _ in out):
            out.append((float(t), 0.6))
    return out


def cluster_marks(mentions: list[tuple[float, float, str]], window: float = 60.0, min_n: int = 3,
                  min_peso: float = 5.0, top: int = 12) -> list[dict]:
    """mentions = [(t, peso, texto)] -> clusters [{"t","peso","n","exemplo"}] (mais fortes primeiro)."""
    ms = sorted(mentions, key=lambda x: x[0])
    used = [False] * len(ms)
    out: list[dict] = []
    while True:
        best = None
        for i in range(len(ms)):
            if used[i]:
                continue
            j_idx = [j for j in range(i, len(ms)) if not used[j] and ms[j][0] - ms[i][0] <= window]
            w = sum(ms[j][1] for j in j_idx)
            if best is None or w > best[0]:
                best = (w, j_idx)
        if best is None:
            break
        w, idx = best
        n = len(idx)
        if n < min_n and w < min_peso:
            break
        for j in idx:
            used[j] = True
        tw = sum(ms[j][1] for j in idx) or 1.0
        t = sum(ms[j][0] * ms[j][1] for j in idx) / tw
        # o comentario citado costuma apontar o INICIO do momento: puxa para a mencao mais cedo forte
        t = min(t, min(ms[j][0] for j in idx) + 15)
        ex = max(idx, key=lambda j: ms[j][1])
        exemplo = re.sub(r"\s+", " ", ms[ex][2]).strip()[:120]
        out.append({"t": round(t, 1), "peso": round(w, 2), "n": n, "exemplo": exemplo})
        if len(out) >= top:
            break
    return out


def fetch_comments(url: str, cfg, max_comments: int = 300, timeout_s: float = 20.0) -> list[dict] | None:
    """Comentarios "top" (so os principais, sem respostas) via yt-dlp, sem login e sem resolver os formatos.
    [{"text", "likes"}] ou None. Roda numa thread com limite de tempo."""
    import yt_dlp

    from ..download import ytdlp_opts

    ea = {"youtube": {"max_comments": [str(max_comments), str(max_comments), "0", "0"], "comment_sort": ["top"],
                      "player_skip": ["js", "configs"], "player_client": ["web"]}}
    opts = ytdlp_opts(cfg, skip_download=True, getcomments=True, extractor_args=ea, ignore_no_formats_error=True,
                      socket_timeout=10, extractor_retries=1, retries=1)
    res: dict = {}

    def work():
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False, process=False)
                ydl.post_extract(info)
            res["c"] = [{"text": str(x.get("text") or ""), "likes": int(x.get("like_count") or 0)}
                        for x in (info or {}).get("comments") or [] if x.get("parent", "root") == "root"]
        except Exception as e:  # noqa: BLE001
            res["e"] = e

    th = threading.Thread(target=work, daemon=True, name="comentarios")
    th.start()
    th.join(timeout_s)
    if th.is_alive():
        _log.info("comentarios de %s passaram de %.0fs; ignorando", url, timeout_s)
        return None
    if "e" in res:
        _log.info("comentarios de %s falharam: %s", url, str(res["e"])[:200])
        return None
    return res.get("c")


def comment_marks(c, cfg, duration: float | None = None) -> dict | None:
    """Le os comentarios top de um video do YouTube e agrupa os horarios citados."""
    if c.platform != "youtube":
        return None
    t0 = time.time()
    n_max = int(_cfg(cfg, "busca.comentarios.max", 300))
    budget = float(_cfg(cfg, "busca.comentarios.tempo_max_s", 22))
    comments = fetch_comments(c.url, cfg, n_max, budget)
    if comments is None:
        return None
    mentions: list[tuple[float, float, str]] = []
    k = 0
    for cm in comments:
        ts = parse_timestamps(cm["text"], duration)
        if not ts:
            continue
        k += 1
        base = 1.0 + math.sqrt(max(0, cm["likes"])) / 5.0
        # comentario-"timeline" (4+ horarios) divide o peso: ele lista temas, nao aponta um momento
        share = 1.0 if len(ts) <= 3 else 3.0 / len(ts)
        skip_intro = bool(_INTRO_RX.search(norm(cm["text"])))
        for t, prec in ts:
            if skip_intro and t < 900:
                continue        # "11:38 comeca" = pular a abertura, nao e momento quente
            mentions.append((t, base * prec * share, cm["text"]))
    min_n = int(_cfg(cfg, "busca.comentarios.cluster_min", 3))
    min_peso = float(_cfg(cfg, "busca.comentarios.peso_min", 4.0))
    allc = cluster_marks(mentions, min_n=1, min_peso=0.0, top=40)
    strong = [dict(m, forte=True) for m in allc if m["n"] >= min_n or m["peso"] >= min_peso][:12]
    # citacoes isoladas (1 a 2 pessoas) entram como sinal fraco: comentario top raramente cita horario
    weak = [dict(m, forte=False) for m in allc
            if not (m["n"] >= min_n or m["peso"] >= min_peso) and (m["n"] >= 2 or m["peso"] >= 2.0)][:5]
    marks = strong + weak
    dt = time.time() - t0
    _log.info("comentarios %s: %d lidos, %d com horario, %d momentos (%.1fs)", c.id, len(comments), k, len(marks), dt)
    return {"marks": marks, "lidos": len(comments), "com_tempo": k, "tempo_s": round(dt, 1)}


# ====================================================================== chat
LAUGH_RX = re.compile(r"(?i)(k{4,}|\bkekw\b|\blul\b|\bomegalul\b|\blmao\b|\bicant\b|\bpepelaugh\b|\bkkk\b|"
                      r"(?:ha){3,}|(?:rs){3,}|\U0001F602|\U0001F923|\U0001F480|:face-with-tears-of-joy:|"
                      r":rolling-on-the-floor-laughing:|:skull:)")


def _measure(msgs: list[tuple[float, str]], off: float, after: bool) -> dict | None:
    """Uma pagina de chat -> densidade (mensagens por 10 s) e fracao de risada."""
    lo, hi = (off - 30, off + 240) if after else (off - 240, off + 30)
    ts = sorted((t, txt) for t, txt in msgs if lo <= t <= hi)
    if not ts:
        return {"t": off, "msgs": 0.0, "riso": 0.0, "n": 0}
    times = [t for t, _ in ts]
    n = len(times)
    span = times[-1] - times[0]
    if n >= 5 and span >= 2:
        rate = 10.0 * (n - 1) / span
    else:
        rate = 10.0 * n / 60.0
    laugh = sum(1 for _, txt in ts if LAUGH_RX.search(txt or "")) / n
    return {"t": statistics.median(times), "msgs": rate, "riso": laugh, "n": n}


def _robust_z(vals: list[float], floor: float) -> tuple[float, float]:
    med = statistics.median(vals)
    mad = statistics.median(abs(v - med) for v in vals)
    return med, max(1.4826 * mad, floor)


def find_spikes(samples: list[dict], z_min: float = 3.0, min_gap: float = 60.0, top: int = 10,
                local_s: float = 600.0) -> tuple[list[dict], dict]:
    """Amostras {"t","msgs","riso"} -> picos [{"t","z","msgs","riso"}] + estatisticas.

    z robusto (mediana/MAD) do log da taxa de mensagens em relacao a base LOCAL (+-10 min): live longa tem
    fases (intervalo calmo, batalha agitada) e o pico precisa se destacar do que esta em volta. Risada/emote
    conta como pico tambem (z da taxa de mensagens de risada, peso 0,8)."""
    ok = sorted((s for s in samples if s is not None), key=lambda s: s["t"])
    if len(ok) < 8:
        return [], {"amostras": len(ok)}
    xs = [math.log1p(s["msgs"]) for s in ok]
    gmed = statistics.median(xs)
    loc = []
    for i, s in enumerate(ok):
        near = [xs[j] for j in range(len(ok)) if j != i and abs(ok[j]["t"] - s["t"]) <= local_s]
        loc.append(statistics.median(near) if len(near) >= 3 else gmed)
    res = [x - lc for x, lc in zip(xs, loc)]
    rmed, rsd = _robust_z(res, floor=0.12)
    ls = [math.log1p(s["msgs"] * s["riso"]) for s in ok]
    lmed, lsd = _robust_z(ls, floor=0.25)
    scored = []
    for i, s in enumerate(ok):
        z = (res[i] - rmed) / rsd
        zl = (ls[i] - lmed) / lsd
        zz = max(z, 0.8 * zl)
        if zz >= z_min and s["msgs"] >= 1.3 * math.expm1(loc[i]):
            scored.append((zz, s))
    scored.sort(key=lambda x: -x[0])
    out: list[dict] = []
    for zz, s in scored:
        if any(abs(s["t"] - o["t"]) < min_gap for o in out):
            continue
        out.append({"t": round(s["t"], 1), "z": round(zz, 1), "msgs": round(s["msgs"], 1), "riso": round(s["riso"], 2)})
        if len(out) >= top:
            break
    return out, {"amostras": len(ok), "base_msgs": round(math.expm1(gmed), 1)}


class _Budget:
    def __init__(self, seconds: float, max_req: int, max_bytes: float):
        self.deadline = time.time() + seconds
        self.req = 0
        self.max_req = max_req
        self.bytes = 0
        self.max_bytes = max_bytes
        self.lock = threading.Lock()

    def take(self) -> bool:
        with self.lock:
            if time.time() > self.deadline or self.req >= self.max_req or self.bytes > self.max_bytes:
                return False
            self.req += 1
            return True

    def add_bytes(self, n: int) -> None:
        with self.lock:
            self.bytes += n

    @property
    def over_bytes(self) -> bool:
        return self.bytes > self.max_bytes


def _sample_chat(fetch, duration: float, budget: _Budget, threads: int, after: bool) -> list[dict]:
    """Amostra o chat em offsets espalhados pelo video e refina em volta dos maiores picos.
    fetch(offset) -> (mensagens [(t, texto)] | None, bytes)."""
    n = int(min(budget.max_req * 0.72, max(8.0, duration / 20.0)))
    step = duration / max(1, n)
    first = [step * (i + 0.5) for i in range(n)]
    results: dict[float, dict] = {}

    def one(off: float):
        if not budget.take():
            return off, None
        msgs, size = fetch(off)
        budget.add_bytes(size)
        if msgs is None:
            return off, None
        return off, _measure(msgs, off, after)

    def run(offsets: list[float]):
        with cf.ThreadPoolExecutor(max_workers=threads, thread_name_prefix="chat") as ex:
            futs = [ex.submit(one, o) for o in offsets]
            for f in cf.as_completed(futs):
                try:
                    off, m = f.result()
                except Exception:  # noqa: BLE001
                    continue
                if m is not None:
                    results[off] = m

    run(first)
    vals = [m for m in results.values()]
    if len(vals) >= 8 and step > 25:
        med = statistics.median(v["msgs"] for v in vals)
        tops = sorted(results.items(), key=lambda kv: -(kv[1]["msgs"] + kv[1]["msgs"] * kv[1]["riso"]))[:6]
        extra = []
        for off, m in tops:
            if m["msgs"] < med * 1.3:
                continue
            for d in (-2 / 3, -1 / 3, 1 / 3, 2 / 3):
                o = off + d * step
                if 0 <= o <= duration:
                    extra.append(o)
        if extra:
            run(extra)
    return list(results.values())


# ---------------------------------------------------------------- YouTube: replay do chat de live
class _YtChat:
    """Le o replay do chat de uma live do YouTube em offsets arbitrarios (seek), como o player faz."""
    API = "https://www.youtube.com/youtubei/v1/live_chat/get_live_chat_replay?key="

    def __init__(self, video_id: str):
        from . import net
        from .youtube import _initial_data

        self.ok = False
        s = net.session()
        r = s.get(f"https://www.youtube.com/watch?v={video_id}&hl=pt-BR&gl=BR", timeout=15)
        html = r.text if r.status_code == 200 else ""
        data = _initial_data(html) or {}
        m = re.search(r"ytcfg\.set\((\{.*?\})\);", html)
        try:
            ycfg = json.loads(m.group(1)) if m else {}
        except ValueError:
            ycfg = {}
        self.key = ycfg.get("INNERTUBE_API_KEY")
        self.ctx = ycfg.get("INNERTUBE_CONTEXT")
        lcr = (((data.get("contents") or {}).get("twoColumnWatchNextResults") or {}).get("conversationBar") or {}) \
            .get("liveChatRenderer") or {}
        try:
            cont = lcr["continuations"][0]["reloadContinuationData"]["continuation"]
        except (KeyError, IndexError, TypeError):
            return
        if not (self.key and self.ctx):
            return
        # pagina inicial do replay -> continuacao do chat COMPLETO (nao so "principais mensagens")
        r2 = s.get("https://www.youtube.com/live_chat_replay?continuation=" + cont, timeout=15)
        d2 = _initial_data(r2.text) if r2.status_code == 200 else None
        lcc = ((d2 or {}).get("continuationContents") or {}).get("liveChatContinuation") or {}
        seek = self._seek(lcc)
        try:
            items = lcc["header"]["liveChatHeaderRenderer"]["viewSelector"]["sortFilterSubMenuRenderer"]["subMenuItems"]
            allc = items[1]["continuation"]["reloadContinuationData"]["continuation"]
            l3, _ = self._post(allc, 0)
            seek = self._seek(l3 or {}) or seek
        except (KeyError, IndexError, TypeError):
            pass
        self.seek = seek
        self.ok = bool(seek)

    @staticmethod
    def _seek(lcc: dict) -> str | None:
        for c in lcc.get("continuations") or []:
            if "playerSeekContinuationData" in c:
                return c["playerSeekContinuationData"].get("continuation")
        return None

    def _post(self, cont: str, off_s: float) -> tuple[dict | None, int]:
        from . import net

        body = {"context": self.ctx, "continuation": cont, "currentPlayerState": {"playerOffsetMs": str(int(off_s * 1000))}}
        try:
            r = net.session().post(self.API + self.key, json=body, timeout=10)
            size = len(r.content or b"")
            if r.status_code != 200:
                return None, size
            return (r.json().get("continuationContents") or {}).get("liveChatContinuation") or {}, size
        except Exception:  # noqa: BLE001
            return None, 0

    def page(self, off_s: float) -> tuple[list[tuple[float, str]] | None, int]:
        lcc, size = self._post(self.seek, off_s)
        if lcc is None:
            return None, size
        out = []
        for a in lcc.get("actions") or []:
            rep = a.get("replayChatItemAction")
            if not rep:
                continue
            try:
                t = int(rep.get("videoOffsetTimeMsec")) / 1000.0
            except (TypeError, ValueError):
                continue
            for it in rep.get("actions") or []:
                item = (it.get("addChatItemAction") or {}).get("item") or {}
                rr = item.get("liveChatTextMessageRenderer") or item.get("liveChatPaidMessageRenderer")
                if not rr:
                    continue
                txt = "".join((x.get("text") or ":" + ((x.get("emoji") or {}).get("shortcuts") or ["?"])[0].strip(":") + ":")
                              for x in (rr.get("message") or {}).get("runs") or [])
                out.append((t, txt))
        return out, size


def chat_spikes(c, cfg, info: dict | None = None) -> dict | None:
    """Picos do chat gravado (Twitch VOD ou live do YouTube). None se nao houver chat ou se nao compensar."""
    info = info or {}
    t0 = time.time()
    dur = float(info.get("duration") or c.duration or 0)
    if dur < 120:
        return None
    budget_s = float(_cfg(cfg, "busca.chat.tempo_max_s", 25))
    max_mb = float(_cfg(cfg, "busca.chat.max_mb", 30))
    z_min = float(_cfg(cfg, "busca.chat.z_min", 3.0))
    src = None
    try:
        if c.platform == "twitch":
            vid = str(info.get("id") or "")
            if not vid:
                m = re.search(r"/videos/(\d+)", c.url or "")
                vid = m.group(1) if m else ""
            if not (vid.startswith("v") or vid.isdigit()) or (c.extra or {}).get("tipo") == "clipe":
                return None
            from . import twitch_gql

            budget = _Budget(budget_s, int(_cfg(cfg, "busca.chat.max_req_twitch", 260)), max_mb * 1e6)
            samples = _sample_chat(lambda off: twitch_gql.vod_chat_page(vid, off), dur, budget, 6, after=True)
            src = "twitch"
        elif c.platform == "youtube":
            subs = info.get("subtitles") or {}
            if "live_chat" not in subs:
                return None
            vid = str(info.get("id") or c.id.split(":", 1)[-1])
            yc = _YtChat(vid)
            if not yc.ok:
                _log.info("chat %s: replay do chat indisponivel", c.id)
                return None
            budget = _Budget(max(5.0, budget_s - (time.time() - t0)),
                             int(_cfg(cfg, "busca.chat.max_req_youtube", 100)), max_mb * 1e6)
            samples = _sample_chat(yc.page, dur, budget, 4, after=False)
            src = "youtube"
        else:
            return None
    except Exception as e:  # noqa: BLE001
        _log.info("chat %s falhou: %s", c.id, str(e)[:200])
        return None
    spikes, stats = find_spikes(samples, z_min=z_min)
    dt = time.time() - t0
    mb = budget.bytes / 1e6
    res = {"spikes": spikes, "fonte": src, "amostras": stats.get("amostras", 0),
           "base_msgs": stats.get("base_msgs"), "requisicoes": budget.req, "mb": round(mb, 1), "tempo_s": round(dt, 1)}
    if budget.over_bytes:
        res["parcial"] = "passou de %.0f MB" % max_mb
    _log.info("chat %s (%s): %d amostras, %d picos, base %.1f msgs/10s, %d req, %.1f MB, %.1fs", c.id, src,
              res["amostras"], len(spikes), stats.get("base_msgs") or 0, budget.req, mb, dt)
    return res
