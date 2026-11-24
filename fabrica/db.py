"""Banco SQLite: historico de execucoes, videos vistos, cortes e publicacoes."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Iterable

from . import paths
from .models import Candidate, ClipPlan, PostResult, RenderedClip, Trend

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    started REAL, finished REAL,
    trigger TEXT,               -- manual | agendado
    search_mode TEXT, keywords TEXT,
    publish_mode TEXT,
    status TEXT,                -- rodando | ok | erro | parcial
    summary TEXT                -- json
);
CREATE TABLE IF NOT EXISTS trends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT, ts REAL, topic TEXT, source TEXT, score REAL, data TEXT
);
CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,        -- plataforma:id
    platform TEXT, url TEXT, title TEXT, channel TEXT,
    duration REAL, views INTEGER, upload_ts REAL, topic TEXT, score REAL,
    status TEXT,                -- encontrado | processando | processado | falhou | ignorado
    first_seen REAL, last_run TEXT, error TEXT, data TEXT
);
CREATE TABLE IF NOT EXISTS clips (
    id TEXT PRIMARY KEY,
    video_id TEXT, run_id TEXT, created REAL,
    start REAL, "end" REAL, title TEXT, score REAL,
    status TEXT,                -- planejado | renderizado | aprovado | rejeitado | publicado | falhou | expirado
    render_path TEXT, plan TEXT, rendered TEXT
);
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_id TEXT, platform TEXT, ok INTEGER, url TEXT, error TEXT, screenshot TEXT, ts REAL, dry_run INTEGER
);
CREATE INDEX IF NOT EXISTS idx_clips_status ON clips(status);
CREATE INDEX IF NOT EXISTS idx_posts_platform_ts ON posts(platform, ts);
"""


def conn() -> sqlite3.Connection:
    c = getattr(_local, "conn", None)
    if c is None:
        paths.DATA.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(paths.DB_PATH), timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        try:
            c.execute("ALTER TABLE clips ADD COLUMN curador TEXT")   # decisao do editor-chefe
        except sqlite3.OperationalError:
            pass   # ja existe
        _local.conn = c
    return c


def _j(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


# ------------------------------------------------------------------ runs
def start_run(run_id: str, trigger: str, search_mode: str, keywords: list[str] | None, publish_mode: str) -> None:
    # so existe uma rodada por vez (RunLock): o que ficou "rodando" foi interrompido (reinicio, queda)
    conn().execute("UPDATE runs SET status='interrompida', finished=? WHERE status='rodando' AND id<>?", (time.time(), run_id))
    conn().execute(
        "INSERT OR REPLACE INTO runs (id, started, trigger, search_mode, keywords, publish_mode, status) VALUES (?,?,?,?,?,?,?)",
        (run_id, time.time(), trigger, search_mode, _j(keywords or []), publish_mode, "rodando"),
    )
    conn().commit()


def finish_run(run_id: str, status: str, summary: dict) -> None:
    conn().execute("UPDATE runs SET finished=?, status=?, summary=? WHERE id=?",
                   (time.time(), status, _j(summary), run_id))
    conn().commit()


def last_runs(n: int = 10) -> list[sqlite3.Row]:
    return conn().execute("SELECT * FROM runs ORDER BY started DESC LIMIT ?", (n,)).fetchall()


# ---------------------------------------------------------------- trends
def save_trends(run_id: str, trends: Iterable[Trend]) -> None:
    now = time.time()
    conn().executemany(
        "INSERT INTO trends (run_id, ts, topic, source, score, data) VALUES (?,?,?,?,?,?)",
        [(run_id, now, t.topic, t.source, t.score, _j(t.to_dict())) for t in trends],
    )
    conn().commit()


# ---------------------------------------------------------------- videos
def video_seen(video_id: str) -> bool:
    r = conn().execute("SELECT status FROM videos WHERE id=?", (video_id,)).fetchone()
    return r is not None and r["status"] in ("processado", "processando", "ignorado")


def upsert_video(c: Candidate, status: str = "encontrado", run_id: str | None = None, error: str | None = None) -> None:
    conn().execute(
        """INSERT INTO videos (id, platform, url, title, channel, duration, views, upload_ts, topic, score,
                               status, first_seen, last_run, error, data)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET status=excluded.status, views=excluded.views, score=excluded.score,
               last_run=excluded.last_run, error=excluded.error, data=excluded.data""",
        (c.id, c.platform, c.url, c.title, c.channel, c.duration, c.views, c.upload_ts, c.topic, c.score,
         status, time.time(), run_id, error, _j(c.to_dict())),
    )
    conn().commit()


def set_video_status(video_id: str, status: str, error: str | None = None) -> None:
    conn().execute("UPDATE videos SET status=?, error=? WHERE id=?", (status, error, video_id))
    conn().commit()


def release_stuck() -> int:
    """Videos que ficaram 'processando' porque o programa caiu: voltam para a busca."""
    rows = conn().execute("SELECT id FROM videos WHERE status='processando'").fetchall()
    for r in rows:
        conn().execute("UPDATE videos SET status=? WHERE id=?",
                       ("ignorado" if bump_attempt(r["id"]) >= MAX_VIDEO_ATTEMPTS else "encontrado", r["id"]))
    conn().commit()
    return len(rows)


MAX_VIDEO_ATTEMPTS = 2


def bump_attempt(video_id: str) -> int:
    """Conta as tentativas que nao chegaram ao fim (falha ou queda do PC)."""
    c = conn()
    c.execute("CREATE TABLE IF NOT EXISTS video_attempts (id TEXT PRIMARY KEY, n INTEGER)")
    c.execute("INSERT INTO video_attempts (id, n) VALUES (?, 1) ON CONFLICT(id) DO UPDATE SET n = n + 1", (video_id,))
    c.commit()
    return int(c.execute("SELECT n FROM video_attempts WHERE id=?", (video_id,)).fetchone()[0])


# ----------------------------------------------------------------- clips
def save_plan(plan: ClipPlan, run_id: str) -> None:
    conn().execute(
        """INSERT OR REPLACE INTO clips (id, video_id, run_id, created, start, "end", title, score, status, plan)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (plan.id, plan.source_id, run_id, time.time(), plan.start, plan.end, plan.title, plan.score,
         "planejado", _j(plan.to_dict())),
    )
    conn().commit()


def save_rendered(rc: RenderedClip) -> None:
    conn().execute(
        """UPDATE clips SET status='renderizado', render_path=?, rendered=?, title=?, score=?, plan=? WHERE id=?""",
        (rc.path, _j(rc.to_dict()), rc.plan.title, rc.plan.score, _j(rc.plan.to_dict()), rc.plan.id),
    )
    conn().commit()


def set_clip_status(clip_id: str, status: str) -> None:
    conn().execute("UPDATE clips SET status=? WHERE id=?", (status, clip_id))
    conn().commit()


def update_clip_plan(plan: ClipPlan) -> None:
    """Salva edicoes manuais (titulo/descricao) feitas na revisao."""
    row = conn().execute("SELECT rendered FROM clips WHERE id=?", (plan.id,)).fetchone()
    rendered = None
    if row and row["rendered"]:
        d = json.loads(row["rendered"])
        d["plan"] = plan.to_dict()
        rendered = _j(d)
    conn().execute("UPDATE clips SET plan=?, title=?, rendered=COALESCE(?, rendered) WHERE id=?",
                   (_j(plan.to_dict()), plan.title, rendered, plan.id))
    conn().commit()


def clips_today_from_channel(channel: str) -> int:
    """Quantos cortes ja foram feitos hoje do mesmo canal-fonte (regra anti-repost)."""
    if not channel:
        return 0
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    r = conn().execute(
        """SELECT COUNT(*) FROM clips c JOIN videos v ON c.video_id = v.id
           WHERE v.channel = ? AND c.created >= ? AND c.status NOT IN ('planejado', 'falhou', 'rejeitado')""",
        (channel, start)).fetchone()
    return int(r[0])


def update_render_path(clip_id: str, new_path: str) -> None:
    """Atualiza o caminho do video (ex.: depois de arquivar no OneDrive)."""
    row = conn().execute("SELECT rendered FROM clips WHERE id=?", (clip_id,)).fetchone()
    rendered = None
    if row and row["rendered"]:
        d = json.loads(row["rendered"])
        d["path"] = new_path
        thumb = d.get("thumbnail")
        if thumb:
            from pathlib import Path

            d["thumbnail"] = str(Path(new_path).with_name(Path(thumb).name))
        rendered = _j(d)
    conn().execute("UPDATE clips SET render_path=?, rendered=COALESCE(?, rendered) WHERE id=?",
                   (new_path, rendered, clip_id))
    conn().commit()


def clips_by_status(*statuses: str) -> list[RenderedClip]:
    q = f"SELECT rendered FROM clips WHERE status IN ({','.join('?' * len(statuses))}) AND rendered IS NOT NULL ORDER BY score DESC"
    out = []
    for r in conn().execute(q, statuses).fetchall():
        try:
            out.append(RenderedClip.from_dict(json.loads(r["rendered"])))
        except Exception:
            pass
    return out


def clip_overview(limit: int = 60) -> list[dict]:
    """Ultimos cortes com a situacao em palavras: na fila, postado (links), descartado..."""
    out = []
    for r in conn().execute("SELECT * FROM clips ORDER BY created DESC LIMIT ?", (limit,)).fetchall():
        try:
            rd = json.loads(r["rendered"] or "{}") or {}
        except Exception:
            rd = {}
        posts = [dict(p) for p in conn().execute(
            "SELECT platform, ok, url, error FROM posts WHERE clip_id=? AND dry_run=0 ORDER BY ts", (r["id"],)).fetchall()]
        done = [p for p in posts if p["ok"] and not str(p["error"] or "").startswith("INCERTO")]
        st = {"planejado": "não terminou", "renderizado": "pronto, esperando", "aprovado": "na fila para postar",
              "rejeitado": "descartado", "publicado": "postado", "falhou": "falhou", "expirado": "passou da validade"}.get(
            r["status"], r["status"])
        if done and r["status"] in ("renderizado", "aprovado"):
            st = "postado em " + ", ".join(p["platform"] for p in done) + ", falta o resto"
        elif any(str(p["error"] or "").startswith("INCERTO") for p in posts):
            st = "conferir na rede se saiu"
        if r["curador"] and r["status"] == "rejeitado":
            st = str(r["curador"])
        path = rd.get("path") or r["render_path"] or ""
        out.append({"id": r["id"], "title": r["title"], "score": r["score"] or 0, "created": r["created"], "status": r["status"],
                    "situacao": st, "path": path, "thumbnail": rd.get("thumbnail") or "", "duration": rd.get("duration") or 0,
                    "existe": bool(path) and Path(path).exists(), "posts": done})
    return out


def clip_rows(limit: int = 100) -> list[sqlite3.Row]:
    return conn().execute("SELECT * FROM clips ORDER BY created DESC LIMIT ?", (limit,)).fetchall()


# ----------------------------------------------------------------- posts
def save_post(r: PostResult) -> None:
    conn().execute(
        "INSERT INTO posts (clip_id, platform, ok, url, error, screenshot, ts, dry_run) VALUES (?,?,?,?,?,?,?,?)",
        (r.clip_id, r.platform, int(r.ok), r.url, r.error, r.screenshot, r.ts or time.time(), int(r.dry_run)),
    )
    conn().commit()


def posts_today(platform: str) -> int:
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    r = conn().execute("SELECT COUNT(*) AS n FROM posts WHERE platform=? AND ok=1 AND dry_run=0 AND ts>=?",
                       (platform, start)).fetchone()
    return int(r["n"])


def already_posted(clip_id: str, platform: str) -> bool:
    r = conn().execute("SELECT 1 FROM posts WHERE clip_id=? AND platform=? AND ok=1 AND dry_run=0",
                       (clip_id, platform)).fetchone()
    return r is not None


def has_uncertain_post(clip_id: str) -> bool:
    """Algum envio deste corte ficou sem confirmacao (erro 'INCERTO: ...')?"""
    return conn().execute("SELECT 1 FROM posts WHERE clip_id=? AND dry_run=0 AND error LIKE 'INCERTO%'",
                          (clip_id,)).fetchone() is not None


def failed_attempts(clip_id: str, platform: str) -> int:
    """Tentativas reais que falharam (login, captcha, limite e falta de internet nao contam)."""
    return int(conn().execute(
        """SELECT COUNT(*) FROM posts WHERE clip_id=? AND platform=? AND ok=0 AND dry_run=0
           AND error NOT LIKE 'ACAO_NECESSARIA%' AND error NOT LIKE 'LIMITE_DIARIO%'
           AND error NOT LIKE '%sem conex%' AND error NOT LIKE '%ERR_INTERNET%' AND error NOT LIKE '%ERR_NAME%'
           AND error NOT LIKE '%navegador%'""", (clip_id, platform)).fetchone()[0])


def recent_posts(days: int = 7) -> list[sqlite3.Row]:
    since = (datetime.now() - timedelta(days=days)).timestamp()
    return conn().execute("SELECT * FROM posts WHERE ts>=? ORDER BY ts DESC", (since,)).fetchall()


def stats() -> dict:
    c = conn()
    return {
        "execucoes": c.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
        "videos": c.execute("SELECT COUNT(*) FROM videos").fetchone()[0],
        "cortes": c.execute("SELECT COUNT(*) FROM clips").fetchone()[0],
        "aguardando_revisao": c.execute("SELECT COUNT(*) FROM clips WHERE status='renderizado'").fetchone()[0],
        "publicados": c.execute("SELECT COUNT(*) FROM posts WHERE ok=1 AND dry_run=0").fetchone()[0],
        "falhas_post": c.execute("SELECT COUNT(*) FROM posts WHERE ok=0 AND dry_run=0").fetchone()[0],
    }
