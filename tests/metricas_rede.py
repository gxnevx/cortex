"""Teste COM REDE de fabrica.metrics: posts FALSOS num banco TEMPORARIO apontando para videos PUBLICOS reais
de criadores brasileiros (Podpah) no YouTube Shorts e no TikTok. Nada e publicado, nada de login.

Rode: .venv\\Scripts\\python.exe tests\\metricas_rede.py
O banco real (data/fabrica.db) e o estado real (data/estado) nunca sao tocados.
"""
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fabrica import paths  # noqa: E402

REAL_DB = paths.DB_PATH
TMP = Path(tempfile.mkdtemp(prefix="cortex_metrede_"))
paths.DATA = TMP
paths.DB_PATH = TMP / "fabrica_teste.db"
paths.STATE = TMP / "estado"
assert paths.DB_PATH != REAL_DB

from fabrica import db, learning, metrics  # noqa: E402
from fabrica.config import load_config  # noqa: E402
from fabrica.models import ClipPlan, PostResult, RenderedClip  # noqa: E402

YT_CHANNEL = "@Podpah"
TT_VIDEO = "https://www.tiktok.com/@podpah/video/7601549938912136466"   # "geral tem um amigo assim"
TT_PROFILE = "https://www.tiktok.com/@podpah"
NOW = time.time()
H = 3600.0


def add(cid, title, platform, ts, url, category="humor"):
    plan = ClipPlan(id=cid, source_id=f"youtube:{cid}", start=0, end=40, title=title, category=category,
                    layout="full", score=70)
    db.save_plan(plan, "run_rede")
    db.save_rendered(RenderedClip(plan=plan, path=f"{cid}.mp4", duration=40, layout="full"))
    db.save_post(PostResult(clip_id=cid, platform=platform, ok=True, url=url, ts=ts, dry_run=False))
    return int(db.conn().execute("SELECT MAX(id) FROM posts").fetchone()[0])


def main():
    cfg = load_config()                       # config real, so leitura
    cfg.set("metricas.perfis.youtube", YT_CHANNEL)   # so em memoria
    t0 = time.time()
    shorts = metrics._extract(f"https://www.youtube.com/{YT_CHANNEL}/shorts", cfg, "youtube", flat=True, n=6,
                              lang="pt").get("entries") or []
    print(f"Shorts publicos de {YT_CHANNEL}: {len(shorts)} ({time.time() - t0:.1f} s)")
    assert len(shorts) >= 2, "nao consegui listar os Shorts"

    # A) post com link direto do Short (checkpoint 24 h vencido)
    pa = add("rede-yt-link", shorts[0]["title"], "youtube", NOW - 24.5 * H,
             f"https://youtube.com/shorts/{shorts[0]['id']}")
    # B) post SEM link: resolve pelo perfil (titulo + horario +-15 min). O horario real vem de 1 leitura.
    pb = None
    for e in shorts[1:4]:  # escolhe um Short cuja idade caia num checkpoint
        info1 = metrics._extract(f"https://www.youtube.com/shorts/{e['id']}", cfg, "youtube")
        ts = info1.get("timestamp")
        if not ts:
            continue
        age_h = (NOW - float(ts)) / H
        if metrics._due_checkpoint(age_h, metrics.checkpoints_h(cfg), set()) is None:
            continue
        pb = add("rede-yt-perfil", info1.get("title") or e["title"], "youtube", float(ts) + 120, None)
        print(f"Short para resolver pelo perfil: {e['id']} (idade {age_h:.0f} h)")
        break
    # C) TikTok com link do video e D) TikTok so com o perfil
    pc = add("rede-tt-link", "geral tem um amigo assim", "tiktok", NOW - 24.5 * H, TT_VIDEO)
    pd = add("rede-tt-perfil", "geral tem um amigo assim", "tiktok", NOW - 2.5 * H, TT_PROFILE)

    t1 = time.time()
    res = metrics.collect(cfg, max_items=30)
    dt = time.time() - t1
    print("collect:", json.dumps(res, ensure_ascii=False))
    assert dt < 75, f"coleta lenta demais: {dt:.1f} s"

    rows = {r["post_id"]: dict(r) for r in db.conn().execute("SELECT * FROM post_metrics").fetchall()}
    links = {r["post_id"]: dict(r) for r in db.conn().execute("SELECT * FROM post_links").fetchall()}
    for pid, nome in [(pa, "YouTube link"), (pb, "YouTube via perfil"), (pc, "TikTok link"), (pd, "TikTok perfil")]:
        if pid is None:
            continue
        r = rows.get(pid)
        lk = links.get(pid) or {}
        if r:
            print(f"  {nome:20} views={r['views']} likes={r['likes']} comments={r['comments']} shares={r['shares']} "
                  f"status={r['status']} checkpoint={r['checkpoint']} url={r['url']}")
        else:
            print(f"  {nome:20} sem leitura: {lk.get('ultimo_erro')}")
    assert rows.get(pa) and (rows[pa]["views"] or 0) > 0, "YouTube nao devolveu views"
    if pb is not None and pb in rows:
        assert (rows[pb]["views"] or 0) > 0 and links[pb]["metodo"] == "perfil"
        print("  resolucao pelo perfil do YouTube: OK")
    tt_ok = bool(rows.get(pc) and rows[pc]["views"])
    print(f"  TikTok: {'views lidas' if tt_ok else 'NAO leu (veja o motivo acima)'}")

    for p in ("youtube", "tiktok"):
        h = metrics.account_health(p, cfg)
        print(f"  saude {p}: {h['nivel']} ({h['motivo']}) fator={metrics.volume_factor(p, cfg)}")
    w = learning.weights(cfg, force=True)
    print("  aprendizado:", w["n_posts"], "posts;", learning.insights(cfg)[0])
    for r in metrics.summary_rows(cfg):
        print(f"  {r['rede']:8} {r['idade']:>6} {r['views']:>8} {r['likes']:>7}  {r['titulo'][:30]:30}  {r['situacao']}")
    print("TESTE DE REDE OK" + ("" if tt_ok else " (TikTok bloqueado nesta maquina)"))


if __name__ == "__main__":
    try:
        main()
    finally:
        try:
            c = getattr(db._local, "conn", None)
            if c is not None:
                c.close()
                db._local.conn = None
        except Exception:
            pass
        shutil.rmtree(TMP, ignore_errors=True)
