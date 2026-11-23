"""Metricas publicas dos nossos posts + saude das contas (TikTok e YouTube Shorts).

API (docs/METRICAS.md):
    collect(cfg, max_items=30) -> dict                 # le views/likes nos checkpoints T+2h, 24h, 72h, 7d
    account_health(platform, cfg) -> dict              # {ok, motivo, pausar_ate, nivel, ...}
    volume_factor(platform, cfg) -> float              # 1.0 normal | 0.5 atencao | 0.0 pausa
    summary_rows(cfg, limit=30, dias=7) -> list[dict]  # titulo, rede, idade, views, likes, situacao
    record_reading(post_id, views, ...) -> bool        # leitura vinda de outra fonte (ex.: painel)
    resume(platform) -> None                           # tira a pausa/atencao manualmente

Leitura sempre PUBLICA (sem login, sem chave de API): yt-dlp extrai os metadados da URL do post.
Nunca levanta excecao para quem chama. Tabelas proprias: post_metrics e post_links.
"""
from __future__ import annotations

import difflib
import json
import os
import random
import re
import statistics
import threading
import time
import unicodedata
from datetime import datetime
from typing import Any, Callable

from . import db, log, paths

_log = log.get("metrics")

NOMES = {"youtube": "YouTube", "tiktok": "TikTok"}
DEFAULT_CHECKPOINTS_H = [2, 24, 72, 168]
# ordem de prioridade quando ha muitos itens vencidos: 24h (alarmes) > 72h (aprendizado) > 2h > 7d
_PRIORITY = {24: 0, 72: 1, 2: 2, 168: 3}

# status de uma leitura gravada em post_metrics
STATUS_OK = "ok"
PROBLEM_STATUSES = ("removido", "privado", "restrito", "direitos", "violacao")
SITUACAO = {
    "ok": "ok",
    "removido": "removido/indisponível",
    "privado": "privado",
    "restrito": "restrito",
    "direitos": "direitos autorais",
    "violacao": "removido por violação",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS post_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER, clip_id TEXT, platform TEXT,
    ts REAL, idade_h REAL, checkpoint TEXT,
    views INTEGER, likes INTEGER, comments INTEGER, shares INTEGER,
    status TEXT, detalhe TEXT, fonte TEXT, url TEXT
);
CREATE INDEX IF NOT EXISTS idx_post_metrics_post ON post_metrics(post_id, ts);
CREATE INDEX IF NOT EXISTS idx_post_metrics_plat ON post_metrics(platform, ts);
CREATE TABLE IF NOT EXISTS post_links (
    post_id INTEGER PRIMARY KEY, clip_id TEXT, platform TEXT,
    url TEXT, video_id TEXT, canal TEXT, upload_ts REAL, metodo TEXT,
    tentativas INTEGER DEFAULT 0, proxima_tentativa REAL DEFAULT 0,
    ultimo_erro TEXT, atualizado REAL
);
"""
_schema_done: set[str] = set()
_state_lock = threading.RLock()


# ====================================================================== utilidades
def _cfg(cfg: Any, key: str, default: Any) -> Any:
    try:
        v = cfg.get(key, default) if cfg is not None else default
        return default if v is None else v
    except Exception:
        return default


def _conn():
    c = db.conn()
    key = f"{id(c)}:{paths.DB_PATH}"
    if key not in _schema_done:
        c.executescript(SCHEMA)
        _schema_done.add(key)
    return c


def checkpoints_h(cfg: Any) -> list[int]:
    try:
        cps = sorted({int(x) for x in _cfg(cfg, "metricas.checkpoints_h", DEFAULT_CHECKPOINTS_H)})
        return [c for c in cps if c > 0] or list(DEFAULT_CHECKPOINTS_H)
    except Exception:
        return list(DEFAULT_CHECKPOINTS_H)


def label(h: int) -> str:
    return f"{h // 24}d" if h >= 168 and h % 24 == 0 else f"{h}h"


def _now() -> float:
    return time.time()


def _read_json(path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, path)
    except Exception as e:
        _log.warning("nao consegui gravar %s: %s", path.name, e)


def _health_path():
    return paths.STATE / "saude_contas.json"


def _state_path():
    return paths.STATE / "metricas_estado.json"


_EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF\U000E0020-\U000E007F\U00002600-\U000027BF\U00002190-\U000021FF\U00002B00-\U00002BFF"
                       r"\U0000200D\U0000FE0E\U0000FE0F\U000020E3]")


def count_emojis(text: str | None) -> int:
    return len([m for m in _EMOJI_RE.findall(text or "") if m not in "\U0000200D\U0000FE0E\U0000FE0F\U000020E3"])


def plain(text: str | None) -> str:
    """Texto para terminal: sem emojis e sem os caracteres proibidos pelo dono."""
    t = _EMOJI_RE.sub("", text or "")
    for a in ("\U00002014", "\U00002013", "\U00002022", "\U000000B7"):
        t = t.replace(a, "-")
    return re.sub(r"\s+", " ", t).strip()


def _norm_text(text: str | None) -> str:
    t = re.sub(r"#\w+", " ", text or "")
    t = re.sub(r"\(?\s*\b(parte|part|pt\.?)\s*\d+\s*(/\s*\d+)?\s*\)?", " ", t, flags=re.I)
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def text_similarity(a: str | None, b: str | None) -> float:
    """0..1: parecido entre o titulo que postamos e o titulo/legenda lido na rede."""
    na, nb = _norm_text(a), _norm_text(b)
    if not na or not nb:
        return 0.0
    ratio = difflib.SequenceMatcher(None, na[:80], nb[:80]).ratio()
    ta = {w for w in na.split() if len(w) > 2}
    tb = set(nb.split())
    overlap = len(ta & tb) / len(ta) if ta else 0.0
    return max(ratio, overlap)


def fmt_num(n: int | None) -> str:
    if n is None:
        return "?"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} mi".replace(".", ",")
    if n >= 100_000:
        return f"{n / 1000:.0f} mil"
    if n >= 1000:
        return f"{n / 1000:.1f} mil".replace(".", ",")
    return str(int(n))


def fmt_ratio(x: float) -> str:
    return f"{x:.1f}x".replace(".", ",")


def fmt_age(hours: float) -> str:
    if hours < 1:
        return f"{max(1, int(hours * 60))} min"
    if hours < 48:
        return f"{int(hours)} h"
    return f"{int(hours // 24)} d"


# ====================================================================== URLs
_YT_ID_RE = re.compile(r"(?:youtu\.be/|/shorts/|[?&]v=|/video/|/embed/)([\w-]{11})")
_TT_ID_RE = re.compile(r"/video/(\d{8,})")
_TT_HANDLE_RE = re.compile(r"tiktok\.com/@([\w.]+)", re.I)
_TT_PROFILE_RE = re.compile(r"tiktok\.com/@([\w.]+)/?(?:[?#].*)?$", re.I)
_YT_PROFILE_RE = re.compile(r"youtube\.com/(@[\w.-]+|channel/UC[\w-]{20,}|c/[\w.-]+)", re.I)


def video_id_from_url(platform: str, url: str | None) -> str | None:
    if not url:
        return None
    m = (_YT_ID_RE if platform == "youtube" else _TT_ID_RE).search(url)
    return m.group(1) if m else None


def normalize_video_url(platform: str, url: str | None) -> str | None:
    vid = video_id_from_url(platform, url)
    if not vid:
        return None
    if platform == "youtube":
        return f"https://www.youtube.com/shorts/{vid}"
    m = _TT_HANDLE_RE.search(url or "")
    return f"https://www.tiktok.com/@{m.group(1) if m else '_'}/video/{vid}"


def profile_url(platform: str, handle_or_url: str | None) -> str | None:
    """'@fulano' / 'fulano' / URL do perfil -> URL do perfil que o yt-dlp entende."""
    h = (handle_or_url or "").strip()
    if not h:
        return None
    if platform == "tiktok":
        m = _TT_HANDLE_RE.search(h)
        name = m.group(1) if m else h.lstrip("@").strip("/")
        return f"https://www.tiktok.com/@{name}" if re.fullmatch(r"[\w.]+", name) else None
    m = _YT_PROFILE_RE.search(h)
    if m:
        return f"https://www.youtube.com/{m.group(1)}"
    name = h.lstrip("@").strip("/")
    return f"https://www.youtube.com/@{name}" if re.fullmatch(r"[\w.-]+", name) else None


def _profile_from_post_url(platform: str, url: str | None) -> str | None:
    if not url:
        return None
    if platform == "tiktok":
        m = _TT_PROFILE_RE.search(url)
        return profile_url("tiktok", m.group(1)) if m else None
    if video_id_from_url("youtube", url):
        return None
    m = _YT_PROFILE_RE.search(url)
    return profile_url("youtube", m.group(1)) if m else None


# ====================================================================== yt-dlp
class ReadError(Exception):
    def __init__(self, status: str, msg: str):
        super().__init__(msg)
        self.status = status


_ERR_RULES: list[tuple[str, re.Pattern]] = [
    ("bloqueado", re.compile(r"not a bot|confirm you.?re not|impersonat|unexpected response from webpage|captcha|"
                             r"too many requests|http error 429|rate.?limit|http error 403|please wait|\bwaf\b|"
                             r"unable to extract secondary user id|failed to parse json", re.I)),
    ("direitos", re.compile(r"copyright|direitos autorais|blocked it on copyright|copyright claim", re.I)),
    ("violacao", re.compile(r"violat|terms of service|community guidelines|diretrizes|account .*terminated|"
                            r"conta .*encerrada", re.I)),
    ("privado", re.compile(r"private video|video is private|status code 10216|v.deo privado", re.I)),
    ("restrito", re.compile(r"confirm your age|age.?restricted|inappropriate for some users|"
                            r"not made this video available in your country|not available in your country", re.I)),
    ("removido", re.compile(r"removed by the uploader|has been removed|video unavailable|this video is unavailable|"
                            r"no longer available|video not available|status code 10204|does not exist|"
                            r"post not found|item doesn.?t exist|couldn.?t find|v.deo indispon|not found", re.I)),
]


def classify_error(msg: str) -> str:
    low = msg or ""
    for status, rx in _ERR_RULES:
        if rx.search(low):
            return status
    return "erro"


def _short(msg: Any, n: int = 160) -> str:
    s = re.sub(r"^ERROR:\s*", "", str(msg or "")).strip()
    s = re.sub(r"\[[\w:]+\]\s*", "", s.splitlines()[0] if s else "")
    s = re.sub(r";?\s*please report this issue.*$", "", s, flags=re.I)
    return plain(s)[:n] or "erro desconhecido"


def _call_with_timeout(fn: Callable[[], Any], timeout: float) -> Any:
    """Roda fn numa thread daemon; se passar do tempo, desiste (nao trava o autopiloto)."""
    box: dict = {}

    def run() -> None:
        try:
            box["r"] = fn()
        except BaseException as e:  # noqa: BLE001
            box["e"] = e

    th = threading.Thread(target=run, daemon=True, name="metricas-ytdlp")
    th.start()
    th.join(max(1.0, timeout))
    if th.is_alive():
        raise ReadError("erro", f"tempo esgotado ({int(timeout)} s)")
    if "e" in box:
        raise box["e"]
    return box.get("r")


def _ydl_opts(cfg: Any, platform: str, *, flat: bool = False, n: int = 10, light: bool = True,
              lang: str | None = None) -> dict:
    from . import download

    extra: dict = {"skip_download": True, "ignore_no_formats_error": True, "check_formats": False,
                   "socket_timeout": float(_cfg(cfg, "metricas.timeout_rede_s", 15)),
                   "retries": 1, "extractor_retries": 1}
    ea: dict = {}
    if light and platform == "youtube":
        ea["youtube"] = {"skip": ["dash", "hls", "translated_subs"], "player_client": ["web"]}
    if lang and platform == "youtube":
        ea.setdefault("youtube", {})["lang"] = [lang]
    if ea:
        extra["extractor_args"] = ea
    if flat:
        extra.update(extract_flat="in_playlist", playlistend=int(n), noplaylist=False)
    opts = download.ytdlp_opts(cfg, **extra)
    if not _cfg(cfg, "metricas.usar_cookies", False):
        opts.pop("cookiefile", None)  # leitura publica: sem a sessao do dono
    return opts


def _extract(url: str, cfg: Any, platform: str, *, flat: bool = False, n: int = 10, light: bool = True,
             lang: str | None = None, timeout: float | None = None) -> dict:
    """Metadados publicos via yt-dlp (1 chamada). Levanta ReadError(status, msg)."""
    import yt_dlp

    timeout = float(timeout or _cfg(cfg, "metricas.timeout_item_s", 25))

    def work() -> dict:
        opts = _ydl_opts(cfg, platform, flat=flat, n=n, light=light, lang=lang)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False, process=flat)
            if not flat and isinstance(info, dict) and info.get("_type") in ("url", "url_transparent") \
                    and info.get("url") and info.get("url") != url:
                info = ydl.extract_info(info["url"], download=False, process=False)
            if flat and isinstance(info, dict):
                info = dict(info)
                info["entries"] = list(info.get("entries") or [])[: int(n)]
        return info or {}

    try:
        info = _call_with_timeout(work, timeout)
    except ReadError:
        raise
    except Exception as e:  # DownloadError, rede etc.
        msg = _short(e, 300)
        raise ReadError(classify_error(str(e)), msg) from e
    if not isinstance(info, dict) or not info:
        raise ReadError("erro", "yt-dlp não devolveu dados")
    return info


def _info_status(info: dict) -> tuple[str, str]:
    """Status a partir dos metadados de um video que abriu."""
    av = str(info.get("availability") or "").lower()
    if av == "private":
        return "privado", "vídeo privado"
    if av in ("needs_auth", "premium_only", "subscriber_only"):
        return "restrito", f"acesso restrito ({av})"
    if av == "unlisted":
        return "restrito", "vídeo não listado"
    try:
        if int(info.get("age_limit") or 0) >= 18:
            return "restrito", "restrição de idade"
    except (TypeError, ValueError):
        pass
    blob = " ".join(str(info.get(k) or "") for k in ("title", "description"))[:3000].lower()
    if re.search(r"conte[uú]do (removido|bloqueado) por direitos|copyright claim|muted due to copyright", blob):
        return "direitos", "aviso de direitos autorais nos metadados"
    return STATUS_OK, ""


def _int(v: Any) -> int | None:
    try:
        return None if v is None else int(v)
    except (TypeError, ValueError):
        return None


# ====================================================================== banco: leituras
def _insert_reading(post: dict, *, views: int | None, likes: int | None, comments: int | None,
                    shares: int | None, status: str, detalhe: str, fonte: str, url: str | None,
                    checkpoint: str | None, ts: float | None = None) -> None:
    ts = ts or _now()
    idade_h = max(0.0, (ts - float(post["ts"])) / 3600.0)
    c = _conn()
    c.execute("""INSERT INTO post_metrics (post_id, clip_id, platform, ts, idade_h, checkpoint, views, likes,
                 comments, shares, status, detalhe, fonte, url) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (post["id"], post["clip_id"], post["platform"], ts, round(idade_h, 3), checkpoint, views, likes,
               comments, shares, status, detalhe, fonte, url))
    c.commit()
    _HEALTH_CACHE.clear()  # leitura nova: a saude precisa ser reavaliada


def _upsert_link(post: dict, **fields: Any) -> None:
    c = _conn()
    row = c.execute("SELECT * FROM post_links WHERE post_id=?", (post["id"],)).fetchone()
    data = dict(row) if row else {"post_id": post["id"], "clip_id": post["clip_id"], "platform": post["platform"],
                                  "tentativas": 0, "proxima_tentativa": 0}
    data.update({k: v for k, v in fields.items()})
    data["atualizado"] = _now()
    cols = ["post_id", "clip_id", "platform", "url", "video_id", "canal", "upload_ts", "metodo", "tentativas",
            "proxima_tentativa", "ultimo_erro", "atualizado"]
    c.execute(f"INSERT OR REPLACE INTO post_links ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
              [data.get(k) for k in cols])
    c.commit()


def _link_rows() -> dict[int, dict]:
    return {int(r["post_id"]): dict(r) for r in _conn().execute("SELECT * FROM post_links").fetchall()}


def _post_row(post_id: int) -> dict | None:
    r = _conn().execute("SELECT id, clip_id, platform, url, ts FROM posts WHERE id=?", (post_id,)).fetchone()
    return dict(r) if r else None


def _due_checkpoint(age_h: float, cps: list[int], done: set[str]) -> int | None:
    """Maior checkpoint ja alcancado e ainda nao lido. Checkpoints velhos demais sao pulados."""
    reached = [c for c in cps if c <= age_h]
    if not reached:
        return None
    c = max(reached)
    if label(c) in done:
        return None
    is_last = c == cps[-1]
    if is_last and age_h > c * 1.5:
        return None  # passou muito do ultimo checkpoint
    if not is_last and age_h > c * 2.5 + 1:
        return None  # leitura atrasada demais: espera o proximo checkpoint
    return c


def due_items(cfg: Any, now: float | None = None) -> list[dict]:
    """Posts (ok, nao teste) com checkpoint vencido, ja na ordem de prioridade."""
    now = now or _now()
    cps = checkpoints_h(cfg)
    since = now - (cps[-1] * 1.5 + 1) * 3600
    c = _conn()
    posts = [dict(r) for r in c.execute(
        "SELECT id, clip_id, platform, url, ts FROM posts WHERE ok=1 AND dry_run=0 AND ts>=? ORDER BY ts DESC",
        (since,)).fetchall()]
    if not posts:
        return []
    done: dict[int, set[str]] = {}
    for r in c.execute("SELECT post_id, checkpoint FROM post_metrics WHERE checkpoint IS NOT NULL AND post_id IN "
                       f"({','.join(str(int(p['id'])) for p in posts)})").fetchall():
        done.setdefault(int(r["post_id"]), set()).add(r["checkpoint"])
    links = _link_rows()
    out = []
    for p in posts:
        if p.get("platform") not in NOMES or not p.get("ts"):
            continue
        age_h = (now - float(p["ts"])) / 3600.0
        cp = _due_checkpoint(age_h, cps, done.get(int(p["id"]), set()))
        if cp is None:
            continue
        link = links.get(int(p["id"])) or {}
        if float(link.get("proxima_tentativa") or 0) > now:
            continue
        p["checkpoint_h"] = cp
        p["idade_h"] = age_h
        p["link"] = link
        out.append(p)
    out.sort(key=lambda p: (_PRIORITY.get(p["checkpoint_h"], 9), -float(p["ts"])))
    return out


# ====================================================================== resolucao de URL
def _clip_title(clip_id: str | None) -> str:
    if not clip_id:
        return ""
    try:
        r = _conn().execute("SELECT title, plan FROM clips WHERE id=?", (clip_id,)).fetchone()
        if not r:
            return ""
        t = r["title"] or ""
        if not t and r["plan"]:
            t = (json.loads(r["plan"]) or {}).get("title") or ""
        return t
    except Exception:
        return ""


def _guess_profile(platform: str, cfg: Any, post: dict) -> str | None:
    own = _profile_from_post_url(platform, post.get("url"))
    if own:
        return own
    conf = _cfg(cfg, f"metricas.perfis.{platform}", "")
    if conf:
        return profile_url(platform, str(conf))
    # deduz pelos outros posts da mesma rede (link com @ ou canal lido antes)
    c = _conn()
    for r in c.execute("SELECT url, canal FROM post_links WHERE platform=? AND url IS NOT NULL ORDER BY atualizado DESC "
                       "LIMIT 20", (platform,)).fetchall():
        if platform == "tiktok":
            m = _TT_HANDLE_RE.search(r["url"] or "")
            if m and m.group(1) != "_":
                return profile_url("tiktok", m.group(1))
        elif r["canal"]:
            return profile_url("youtube", r["canal"])
    for r in c.execute("SELECT url FROM posts WHERE platform=? AND ok=1 AND url IS NOT NULL ORDER BY ts DESC LIMIT 20",
                       (platform,)).fetchall():
        u = r["url"] or ""
        m = _TT_HANDLE_RE.search(u) if platform == "tiktok" else _YT_PROFILE_RE.search(u)
        if m:
            return profile_url(platform, m.group(1))
    return None


def _match_entry(entries: list[dict], post_ts: float, title: str, used: set[str], tol_s: float,
                 platform: str) -> dict | None:
    best, best_score = None, 0.0
    in_window = []
    for e in entries:
        vid = str(e.get("id") or video_id_from_url(platform, e.get("url")) or "")
        if not vid or vid in used:
            continue
        sim = max(text_similarity(title, e.get("title")), text_similarity(title, e.get("description")))
        ts = e.get("timestamp")
        if ts:
            if abs(float(ts) - post_ts) > tol_s:
                continue
            in_window.append(e)
            score = 1.0 + sim
            if sim < 0.35:
                score = 0.5  # horario bate, texto nao: so vale se for o unico na janela
        else:
            if sim < 0.6:
                continue
            score = sim
        if score > best_score:
            best, best_score = e, score
    if best is not None and best_score == 0.5 and len(in_window) > 1:
        return None
    return best


def _resolve(post: dict, cfg: Any, cache: dict, used: set[str]) -> tuple[str | None, dict | None, str]:
    """(url do video, entrada da listagem do perfil ou None, metodo)."""
    platform = post["platform"]
    link = post.get("link") or {}
    if link.get("url") and video_id_from_url(platform, link["url"]):
        return link["url"], None, "link"  # ja conferido numa leitura anterior
    direct = normalize_video_url(platform, post.get("url"))
    if direct:
        return direct, None, "post"
    prof = _guess_profile(platform, cfg, post)
    if not prof:
        raise ReadError("sem_link", f"sem link do vídeo e sem perfil (defina metricas.perfis.{platform})")
    listing_url = prof + "/shorts" if platform == "youtube" else prof
    if listing_url not in cache:
        try:
            info = _extract(listing_url, cfg, platform, flat=True, n=int(_cfg(cfg, "metricas.itens_perfil", 12)),
                            lang="pt" if platform == "youtube" else None)
            cache[listing_url] = list(info.get("entries") or [])
        except ReadError as e:
            cache[listing_url] = e
    got = cache[listing_url]
    if isinstance(got, ReadError):
        raise ReadError(got.status if got.status == "bloqueado" else "sem_link",
                        f"não consegui listar o perfil: {got}")
    tol = float(_cfg(cfg, "metricas.tolerancia_match_min", 15)) * 60
    e = _match_entry(got, float(post["ts"]), _clip_title(post.get("clip_id")), used, tol, platform)
    if not e:
        raise ReadError("sem_link", "não achei o vídeo entre os últimos do perfil")
    vid = str(e.get("id") or video_id_from_url(platform, e.get("url")))
    if platform == "youtube":
        url = f"https://www.youtube.com/shorts/{vid}"
    else:
        m = _TT_HANDLE_RE.search(prof)
        url = f"https://www.tiktok.com/@{m.group(1) if m else '_'}/video/{vid}"
    return url, e, "perfil"


# ====================================================================== leitura de um item
def _read_item(post: dict, cfg: Any, cache: dict, used: set[str]) -> str:
    """Le um post vencido. Devolve 'ok' | 'problema' | status de falha ('bloqueado', 'erro', 'sem_link')."""
    platform = post["platform"]
    cp = label(int(post["checkpoint_h"]))
    url, entry, how = _resolve(post, cfg, cache, used)
    metodo = how if how != "link" else ((post.get("link") or {}).get("metodo") or "link")
    info: dict | None = None
    if entry is not None and entry.get("view_count") is not None and platform == "tiktok":
        info, fonte = entry, "perfil"
    else:
        fonte = "yt-dlp"
        try:
            try:
                info = _extract(url, cfg, platform, light=True)
            except ReadError as e:
                # YouTube: erro generico ou "indisponivel" no cliente leve -> confirma com o cliente padrao
                if platform != "youtube" or e.status not in ("erro", *PROBLEM_STATUSES):
                    raise
                info = _extract(url, cfg, platform, light=False)
        except ReadError as e:
            if e.status not in PROBLEM_STATUSES or how == "perfil":
                raise
            # o video sumiu/foi bloqueado: isso E uma leitura (alimenta a saude da conta)
            _insert_reading(post, views=None, likes=None, comments=None, shares=None, status=e.status,
                            detalhe=str(e), fonte=fonte, url=url, checkpoint=cp)
            _upsert_link(post, url=url, video_id=video_id_from_url(platform, url), metodo=metodo, tentativas=0,
                         proxima_tentativa=0, ultimo_erro=str(e))
            return "problema"
    if how == "perfil":  # confere o horario do video escolhido pela legenda
        tol = float(_cfg(cfg, "metricas.tolerancia_match_min", 15)) * 60
        ts = info.get("timestamp")
        if ts and abs(float(ts) - float(post["ts"])) > tol:
            used.add(str(info.get("id") or ""))
            raise ReadError("sem_link", "o vídeo parecido do perfil não bate com o horário do post")
    status, detalhe = _info_status(info)
    views = _int(info.get("view_count"))
    _insert_reading(post, views=views, likes=_int(info.get("like_count")), comments=_int(info.get("comment_count")),
                    shares=_int(info.get("repost_count")), status=status, detalhe=detalhe, fonte=fonte, url=url,
                    checkpoint=cp)
    canal = info.get("uploader_id") or info.get("channel_url") or info.get("uploader") or None
    vid = str(info.get("id") or video_id_from_url(platform, url) or "")
    used.add(vid)
    _upsert_link(post, url=url, video_id=vid, canal=canal, upload_ts=info.get("timestamp"), metodo=metodo,
                 tentativas=0, proxima_tentativa=0, ultimo_erro=None)
    return "ok" if status == STATUS_OK else "problema"


def _register_failure(post: dict, cfg: Any, status: str, msg: str) -> None:
    link = post.get("link") or {}
    n = int(link.get("tentativas") or 0) + 1
    base = float(_cfg(cfg, "metricas.reintentar_min", 45)) * 60
    wait = min(base * (2 ** min(n - 1, 3)), 6 * 3600)
    _upsert_link(post, tentativas=n, proxima_tentativa=_now() + wait, ultimo_erro=f"{status}: {msg}"[:300])


def _load_state() -> dict:
    return _read_json(_state_path())


def collect(cfg: Any, max_items: int = 30) -> dict:
    """Le as metricas publicas dos posts com checkpoint vencido (T+2h, 24h, 72h, 7d). Nunca levanta excecao.

    Retorna {"ok", "devidos", "lidos", "problemas", "falhas", "bloqueados", "pulados", "tempo_s",
             "saude": {rede: nivel}, "mensagens": [str]}.
    """
    t0 = _now()
    res: dict = {"ok": True, "devidos": 0, "lidos": 0, "problemas": 0, "falhas": 0, "bloqueados": 0,
                 "pulados": 0, "tempo_s": 0.0, "saude": {}, "mensagens": []}
    platforms_seen: set[str] = set()
    try:
        if not _cfg(cfg, "metricas.ativo", True):
            res["mensagens"].append("Métricas desligadas (metricas.ativo: false).")
            return res
        items = due_items(cfg)
        res["devidos"] = len(items)
        budget = float(_cfg(cfg, "metricas.tempo_max_s", 60))
        with _state_lock:
            state = _load_state()
        blocked_until: dict = dict(state.get("bloqueio_ate") or {})
        cache: dict = {}
        used = {str(r["video_id"]) for r in _link_rows().values() if r.get("video_id")}
        done_calls = 0
        for i, post in enumerate(items):
            plat = post["platform"]
            platforms_seen.add(plat)
            if done_calls >= max_items or _now() - t0 > budget:
                res["pulados"] += len(items) - i
                res["mensagens"].append(f"{len(items) - i} leitura(s) ficaram para a próxima rodada (limite de "
                                        f"{'tempo' if _now() - t0 > budget else 'itens'}).")
                break
            if float(blocked_until.get(plat) or 0) > _now():
                res["pulados"] += 1
                continue
            if done_calls:
                time.sleep(random.uniform(0.4, 1.2))  # gentil com as plataformas
            done_calls += 1
            try:
                out = _read_item(post, cfg, cache, used)
                if out == "ok":
                    res["lidos"] += 1
                else:
                    res["problemas"] += 1
                    res["lidos"] += 1
            except ReadError as e:
                res["falhas"] += 1
                _register_failure(post, cfg, e.status, str(e))
                if e.status == "bloqueado":
                    res["bloqueados"] += 1
                    hours = float(_cfg(cfg, "metricas.pausa_bloqueio_h", 6))
                    blocked_until[plat] = _now() + hours * 3600
                    res["mensagens"].append(f"Leitura do {NOMES.get(plat, plat)} bloqueada pela rede ({e}); "
                                            f"tento de novo em {int(hours)} h.")
                    _log.warning("metricas: leitura do %s bloqueada: %s", plat, e)
                else:
                    _log.info("metricas: post %s (%s) sem leitura: %s", post["id"], plat, e)
            except Exception as e:  # noqa: BLE001 - nunca derruba o autopiloto
                res["falhas"] += 1
                _register_failure(post, cfg, "erro", _short(e))
                _log.warning("metricas: falha inesperada no post %s: %s", post.get("id"), e)
        with _state_lock:
            state = _load_state()
            state["bloqueio_ate"] = {k: v for k, v in blocked_until.items() if float(v or 0) > _now()}
            state["ultima_coleta"] = _now()
            _write_json(_state_path(), state)
    except Exception as e:  # noqa: BLE001
        res["ok"] = False
        res["mensagens"].append(f"Falha ao coletar métricas: {_short(e)}")
        _log.warning("metricas: coleta falhou: %s", e)
    finally:
        try:
            plats = set(_cfg(cfg, "publicacao.plataformas", ["youtube", "tiktok"])) | platforms_seen
            for p in sorted(plats):
                h = account_health(p, cfg)
                res["saude"][p] = h.get("nivel", "normal")
                if h.get("mudou") and h.get("nivel") != "normal":
                    res["mensagens"].append(f"{NOMES.get(p, p)}: {h.get('motivo')}")
        except Exception as e:  # noqa: BLE001
            _log.debug("saude apos coleta: %s", e)
        res["tempo_s"] = round(_now() - t0, 1)
        if res["lidos"] or res["falhas"]:
            _log.info("metricas: %s lidas, %s falhas, %s bloqueadas em %.1f s", res["lidos"], res["falhas"],
                      res["bloqueados"], res["tempo_s"])
    return res


def record_reading(post_id: int, views: int | None, likes: int | None = None, comments: int | None = None,
                   shares: int | None = None, status: str = STATUS_OK, fonte: str = "externo",
                   ts: float | None = None, cfg: Any = None) -> bool:
    """Grava uma leitura vinda de outra fonte (ex.: painel do TikTok Studio lido pelo publicador)."""
    try:
        post = _post_row(int(post_id))
        if not post:
            return False
        ts = ts or _now()
        age_h = (ts - float(post["ts"])) / 3600.0
        done = {r["checkpoint"] for r in _conn().execute(
            "SELECT checkpoint FROM post_metrics WHERE post_id=? AND checkpoint IS NOT NULL", (post_id,)).fetchall()}
        cp = _due_checkpoint(age_h, checkpoints_h(cfg), done)
        _insert_reading(post, views=_int(views), likes=_int(likes), comments=_int(comments), shares=_int(shares),
                        status=status if status in (STATUS_OK, *PROBLEM_STATUSES) else STATUS_OK, detalhe="",
                        fonte=fonte, url=None, checkpoint=label(cp) if cp else None, ts=ts)
        return True
    except Exception as e:  # noqa: BLE001
        _log.warning("record_reading: %s", e)
        return False


# ====================================================================== consultas para saude/aprendizado
def readings_by_post(platform: str | None = None, since_post_ts: float = 0.0) -> dict[int, list[dict]]:
    q = ("SELECT m.* FROM post_metrics m JOIN posts p ON p.id = m.post_id WHERE p.ok=1 AND p.dry_run=0 AND p.ts>=?")
    args: list = [since_post_ts]
    if platform:
        q += " AND m.platform=?"
        args.append(platform)
    out: dict[int, list[dict]] = {}
    for r in _conn().execute(q + " ORDER BY m.ts", args).fetchall():
        out.setdefault(int(r["post_id"]), []).append(dict(r))
    return out


def views_at(readings: list[dict], target_h: float = 24.0, lo: float = 20.0, hi: float = 96.0) -> int | None:
    """Views do post perto de T+target_h (leituras ok com idade entre lo e hi; a mais proxima do alvo)."""
    ok = [r for r in readings if r.get("status") == STATUS_OK and r.get("views") is not None
          and lo <= float(r.get("idade_h") or 0) <= hi]
    if not ok:
        return None
    return int(min(ok, key=lambda r: abs(float(r["idade_h"]) - target_h))["views"])


def platform_posts(platform: str, days: float = 30.0) -> list[dict]:
    """Posts (ok, nao teste) da rede nos ultimos `days` dias com views em 24 h e status mais recente."""
    since = _now() - days * 86400
    posts = [dict(r) for r in _conn().execute(
        "SELECT id, clip_id, ts FROM posts WHERE platform=? AND ok=1 AND dry_run=0 AND ts>=? ORDER BY ts",
        (platform, since)).fetchall()]
    rmap = readings_by_post(platform, since)
    for p in posts:
        rs = rmap.get(int(p["id"]), [])
        p["views24"] = views_at(rs)
        p["ultimo_status"] = rs[-1]["status"] if rs else None
        p["problemas"] = [r for r in rs if r.get("status") in PROBLEM_STATUSES]
    return posts


def account_median(platform: str, days: float = 30.0) -> float | None:
    vals = [p["views24"] for p in platform_posts(platform, days) if p["views24"] is not None]
    return float(statistics.median(vals)) if vals else None


# ====================================================================== saude da conta
_HEALTH_CACHE: dict[tuple, tuple[float, dict]] = {}


def _load_health() -> dict:
    return _read_json(_health_path())


def _event(ps: dict, nivel: str, motivo: str) -> None:
    hist = list(ps.get("historico") or [])
    hist.append({"ts": _now(), "quando": datetime.now().strftime("%Y-%m-%d %H:%M"), "nivel": nivel, "motivo": motivo})
    ps["historico"] = hist[-30:]


def _set_pause(ps: dict, cfg: Any, motivo: str) -> None:
    now = _now()
    h = float(_cfg(cfg, "metricas.saude.pausa_h", 72))
    after = float(_cfg(cfg, "metricas.saude.atencao_pos_pausa_h", 120))
    ps["pausar_ate"] = max(float(ps.get("pausar_ate") or 0), now + h * 3600)
    ps["atencao_ate"] = max(float(ps.get("atencao_ate") or 0), ps["pausar_ate"] + after * 3600)
    ps["atencao_desde"] = ps["pausar_ate"]
    ps["motivo_pausa"] = motivo
    ps["motivo_atencao"] = "retomada depois de uma pausa: volume reduzido"
    _event(ps, "pausa", motivo)


def _set_attention(ps: dict, cfg: Any, motivo: str) -> bool:
    """Liga a atencao (72 h). Se a atencao ja durava um ciclo inteiro e o problema continua -> PAUSA.
    Devolve True quando virou pausa."""
    now = _now()
    h = float(_cfg(cfg, "metricas.saude.atencao_h", 72))
    prev_end = float(ps.get("atencao_ate") or 0)
    continuous = prev_end >= now - 24 * 3600  # atencao ativa ou acabou ha menos de 1 dia
    since = float(ps.get("atencao_desde") or 0) if continuous else 0.0
    if continuous and 0 < since <= now - h * 3600 * 0.9 and _cfg(cfg, "metricas.saude.atencao_vira_pausa", True):
        _set_pause(ps, cfg, f"atenção por 2 ciclos seguidos: {motivo}")
        return True
    ps["atencao_desde"] = since or now
    ps["atencao_ate"] = max(prev_end, now + h * 3600)
    ps["motivo_atencao"] = motivo
    _event(ps, "atencao", motivo)
    return False


def _evaluate(platform: str, cfg: Any, ps: dict) -> None:
    """Aplica as regras da pesquisa (docs/ideias/algoritmo_e_riscos.md 1.5) e atualiza ps."""
    S = "metricas.saude."
    posts = platform_posts(platform, 30)
    with24 = [p for p in posts if p["views24"] is not None and p["ultimo_status"] in (STATUS_OK, None)]
    nome = NOMES.get(platform, platform)

    # 1) N posts seguidos com quase zero views em 24 h -> PAUSA 72 h
    k = int(_cfg(cfg, S + "posts_seguidos_quase_zero", 3))
    thr = int(_cfg(cfg, S + "views_quase_zero", 10))
    last = with24[-k:]
    if k > 0 and len(last) == k and all(p["views24"] < thr for p in last):
        ids = [int(p["id"]) for p in last]
        if ids != ps.get("gatilho_quase_zero"):
            ps["gatilho_quase_zero"] = ids
            _set_pause(ps, cfg, f"{k} posts seguidos com menos de {thr} views em 24 h no {nome} "
                                f"(possível distribuição limitada)")

    # 2) post removido/indisponivel/privado/restrito ou com aviso de direitos -> ATENCAO; 2+ em 7 dias -> PAUSA
    week = _now() - 7 * 86400
    probs: dict[int, dict] = {}
    for p in posts:
        for r in p["problemas"]:
            if float(r["ts"]) >= week:
                probs[int(p["id"])] = r
    seen = set(int(x) for x in ps.get("problemas_vistos") or [])
    new = [pid for pid in probs if pid not in seen]
    if new:
        ps["problemas_vistos"] = sorted(seen | set(new))[-200:]
        r = probs[new[-1]]
        desc = SITUACAO.get(r["status"], r["status"])
        motivo = f"post {desc} no {nome}" + (f" ({plain(r.get('detalhe'))[:80]})" if r.get("detalhe") else "")
        if len(probs) >= int(_cfg(cfg, S + "problemas_7d_para_pausa", 2)):
            _set_pause(ps, cfg, f"{len(probs)} posts com problema em 7 dias no {nome} (último: {desc})")
        else:
            _set_attention(ps, cfg, motivo)

    # 3) queda forte contra a mediana da propria conta -> ATENCAO (volume pela metade)
    n_last = int(_cfg(cfg, S + "queda_ultimos", 5))
    frac = float(_cfg(cfg, S + "queda_fracao_mediana", 0.20))
    base_min = int(_cfg(cfg, S + "queda_base_min", 5))
    if n_last > 0 and len(with24) >= n_last + base_min:
        base = [p["views24"] for p in with24[:-n_last]]
        med = statistics.median(base)
        last = with24[-n_last:]
        if med > 0 and all(p["views24"] < frac * med for p in last):
            ids = [int(p["id"]) for p in last]
            if ids != ps.get("gatilho_queda"):
                ps["gatilho_queda"] = ids
                _set_attention(ps, cfg, f"últimos {n_last} posts abaixo de {int(frac * 100)}% da mediana da conta "
                                        f"({int(med)} views em 24 h) no {nome}")

    # 4) a partir do dia 15: N posts seguidos abaixo do piso absoluto -> ATENCAO
    floors = _cfg(cfg, S + "views_24h_baixo", {"tiktok": 200, "youtube": 150}) or {}
    floor = floors.get(platform) if isinstance(floors, dict) else None
    min_day = int(_cfg(cfg, S + "baixo_a_partir_do_dia", 15))
    n_low = int(_cfg(cfg, S + "posts_seguidos_baixo", 5))
    if floor and n_low > 0 and len(with24) >= n_low:
        try:
            from . import policy

            age = policy.account_age_days(platform, cfg)
        except Exception:
            age = None
        last = with24[-n_low:]
        if age is not None and age >= min_day and all(p["views24"] < float(floor) for p in last):
            ids = [int(p["id"]) for p in last]
            if ids != ps.get("gatilho_baixo"):
                ps["gatilho_baixo"] = ids
                _set_attention(ps, cfg, f"{n_low} posts seguidos com menos de {int(floor)} views em 24 h "
                                        f"no {nome} (conta com {age} dias)")
    ps["posts_avaliados"] = len(with24)


def account_health(platform: str, cfg: Any) -> dict:
    """Saude da conta numa rede: {ok, motivo, pausar_ate, nivel, ...}. Nunca levanta excecao.

    nivel: "normal" | "atencao" (volume pela metade) | "pausa" (nada de posts ate pausar_ate).
    ok = False so quando nivel == "pausa". A pausa fica salva em data/estado/saude_contas.json.
    """
    platform = (platform or "").lower()
    base = {"ok": True, "motivo": "conta saudável", "pausar_ate": None, "nivel": "normal", "rede": platform,
            "atencao_ate": None, "mudou": False, "posts_avaliados": 0}
    try:
        ck = (platform, str(paths.DB_PATH), str(paths.STATE))
        hit = _HEALTH_CACHE.get(ck)
        ttl = float(_cfg(cfg, "metricas.saude.cache_s", 60))
        if hit and _now() - hit[0] < ttl:
            nivel_c = hit[1]["nivel"]
            until = hit[1].get("pausar_ate") or hit[1].get("atencao_ate") or 0
            if nivel_c == "normal" or until > _now():  # a pausa/atencao nao venceu no meio do cache
                return dict(hit[1], mudou=False)
        with _state_lock:
            data = _load_health()
            ps = dict(data.get(platform) or {})
            before = json.dumps(ps, sort_keys=True, default=str)
            prev = ps.get("ultimo_nivel", "normal")
            if _cfg(cfg, "metricas.saude.ativo", True):
                _evaluate(platform, cfg, ps)
            now = _now()
            if float(ps.get("pausar_ate") or 0) > now:
                nivel, motivo = "pausa", ps.get("motivo_pausa") or "pausa"
            elif float(ps.get("atencao_ate") or 0) > now:
                nivel, motivo = "atencao", ps.get("motivo_atencao") or "atenção"
            else:
                nivel = "normal"
                n = int(ps.get("posts_avaliados") or 0)
                motivo = "conta saudável" if n else "sem leituras de 24 h ainda"
            ps["ultimo_nivel"] = nivel
            if json.dumps(ps, sort_keys=True, default=str) != before:  # so grava quando algo mudou
                data[platform] = ps
                _write_json(_health_path(), data)
        out = dict(base)
        out.update({"ok": nivel != "pausa", "motivo": plain(motivo), "nivel": nivel, "mudou": nivel != prev,
                    "pausar_ate": float(ps["pausar_ate"]) if nivel == "pausa" else None,
                    "atencao_ate": float(ps["atencao_ate"]) if float(ps.get("atencao_ate") or 0) > now else None,
                    "posts_avaliados": int(ps.get("posts_avaliados") or 0)})
        _HEALTH_CACHE[ck] = (_now(), dict(out))
        if out["mudou"]:
            (_log.warning if nivel != "normal" else _log.info)("saude %s: %s (%s)", platform, nivel, out["motivo"])
        return out
    except Exception as e:  # noqa: BLE001
        _log.warning("account_health(%s): %s", platform, e)
        base["motivo"] = f"não consegui avaliar a saúde da conta: {_short(e, 80)}"
        return base


def volume_factor(platform: str, cfg: Any) -> float:
    """Multiplicador do limite diario: 1.0 normal | 0.5 atencao | 0.0 pausa (erro -> 1.0)."""
    try:
        nivel = account_health(platform, cfg).get("nivel", "normal")
        if nivel == "pausa":
            return 0.0
        if nivel == "atencao":
            return float(_cfg(cfg, "metricas.saude.fator_atencao", 0.5))
        return 1.0
    except Exception:  # noqa: BLE001
        return 1.0


def resume(platform: str) -> None:
    """Retomada manual (ex.: `cortex retomar tiktok`): tira pausa e atencao; os gatilhos antigos nao disparam de novo."""
    _HEALTH_CACHE.clear()
    with _state_lock:
        data = _load_health()
        ps = dict(data.get(platform) or {})
        ps["pausar_ate"] = 0
        ps["atencao_ate"] = 0
        ps["atencao_desde"] = 0
        _event(ps, "normal", "retomada manual")
        data[platform] = ps
        _write_json(_health_path(), data)


# ====================================================================== resumo para CLI/relatorio
def summary_rows(cfg: Any, limit: int = 30, dias: float = 7) -> list[dict]:
    """Linhas para tabela: titulo, rede, idade, views, likes, situacao (texto) + url, post_id e numeros crus."""
    rows: list[dict] = []
    try:
        now = _now()
        c = _conn()
        posts = [dict(r) for r in c.execute(
            """SELECT p.id, p.clip_id, p.platform, p.url, p.ts, c.title FROM posts p LEFT JOIN clips c ON c.id = p.clip_id
               WHERE p.ok=1 AND p.dry_run=0 AND p.ts>=? ORDER BY p.ts DESC LIMIT ?""",
            (now - dias * 86400, int(limit))).fetchall()]
        if not posts:
            return rows
        rmap = readings_by_post(None, now - dias * 86400)
        links = _link_rows()
        medians = {p: account_median(p) for p in {x["platform"] for x in posts}}
        first_cp = checkpoints_h(cfg)[0]
        for p in posts:
            rs = rmap.get(int(p["id"]), [])
            last = rs[-1] if rs else None
            link = links.get(int(p["id"])) or {}
            age_h = (now - float(p["ts"])) / 3600
            v24 = views_at(rs)
            if last and last["status"] in PROBLEM_STATUSES:
                sit = SITUACAO.get(last["status"], last["status"])
            elif not last:
                if age_h < first_cp:
                    sit = f"aguardando 1ª leitura ({first_cp} h)"
                elif link.get("ultimo_erro"):
                    sit = "sem leitura: " + plain(str(link["ultimo_erro"]).split(": ", 1)[-1])[:50]
                else:
                    sit = "aguardando leitura"
            else:
                med = medians.get(p["platform"])
                if v24 is not None and med and med > 0:
                    r = (v24 + 1) / (med + 1)
                    sit = (f"acima da mediana ({fmt_ratio(r)})" if r >= 1.2 else
                           f"abaixo da mediana ({fmt_ratio(r)})" if r <= 0.8 else "na média da conta")
                else:
                    sit = "ok"
            views = last.get("views") if last else None
            likes = last.get("likes") if last else None
            rows.append({
                "titulo": plain(p.get("title") or p.get("clip_id") or "")[:60],
                "rede": NOMES.get(p["platform"], p["platform"]),
                "idade": fmt_age(age_h),
                "views": fmt_num(views),
                "likes": fmt_num(likes),
                "situacao": sit,
                "url": link.get("url") or p.get("url"),
                "post_id": int(p["id"]),
                "views_n": views, "likes_n": likes, "views_24h": v24, "idade_h": round(age_h, 1),
            })
    except Exception as e:  # noqa: BLE001
        _log.warning("summary_rows: %s", e)
    return rows
