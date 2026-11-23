"""Testes offline de fabrica.metrics e fabrica.learning (banco TEMPORARIO, nada de rede).

Rode: .venv\\Scripts\\python.exe tests\\metricas_unit.py
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
TMP_ROOT = Path(tempfile.mkdtemp(prefix="cortex_met_"))


def fresh_env(name: str) -> None:
    """Banco + pasta de estado novos (temporarios) para cada cenario."""
    from fabrica import db

    old = getattr(db._local, "conn", None)
    if old is not None:
        old.close()
        db._local.conn = None
    d = TMP_ROOT / name
    d.mkdir(parents=True, exist_ok=True)
    paths.DATA = d
    paths.DB_PATH = d / "fabrica_teste.db"
    paths.STATE = d / "estado"
    assert paths.DB_PATH != REAL_DB


fresh_env("inicio")

from fabrica import db, learning, metrics  # noqa: E402
from fabrica.config import Config  # noqa: E402
from fabrica.models import Candidate, ClipPlan, PostResult, RenderedClip  # noqa: E402

BANNED = ["\U00002022", "\U000000B7", "\U00002014", "\U00002013"]
NOW = time.time()
H = 3600.0


def cfg_with(**over) -> Config:
    data = {"publicacao": {"plataformas": ["youtube", "tiktok"]}, "metricas": {"perfis": {}}}
    for k, v in over.items():
        cur = data
        parts = k.split("__")
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = v
    return Config(data)


def add_clip(cid, title, category="politica", layout="full", dur=40.0, channel="Canal A", series=None):
    plan = ClipPlan(id=cid, source_id=f"youtube:{cid}", start=0.0, end=dur, title=title, category=category,
                    layout=layout, series=series, part=1 if series else None, parts_total=2 if series else None,
                    hashtags=["#teste"], score=70)
    db.save_plan(plan, "run_teste")
    db.save_rendered(RenderedClip(plan=plan, path=f"{cid}.mp4", duration=dur, layout=layout))
    db.upsert_video(Candidate(id=f"youtube:{cid}", platform="youtube", url=f"https://youtu.be/{cid}",
                              title="video fonte", channel=channel))


def add_post(cid, platform, ts, url=None, ok=True, dry=False) -> int:
    db.save_post(PostResult(clip_id=cid, platform=platform, ok=ok, url=url, ts=ts, dry_run=dry))
    return int(db.conn().execute("SELECT MAX(id) FROM posts").fetchone()[0])


# ---------------------------------------------------------------------------------------------- testes
def test_checkpoints():
    cps = [2, 24, 72, 168]
    f = metrics._due_checkpoint
    assert f(1, cps, set()) is None
    assert f(2.5, cps, set()) == 2
    assert f(3, cps, {"2h"}) is None
    assert f(6, cps, set()) == 2
    assert f(7, cps, set()) is None            # 2h atrasado demais: espera o de 24h
    assert f(30, cps, {"2h"}) == 24
    assert f(80, cps, {"24h"}) == 72
    assert f(170, cps, set()) == 168
    assert f(260, cps, set()) is None
    assert metrics.label(168) == "7d" and metrics.label(24) == "24h"
    print("ok checkpoints")


def test_classify_and_urls():
    c = metrics.classify_error
    cases = {
        "ERROR: [youtube] a: Video unavailable. This video has been removed by the uploader": "removido",
        "ERROR: [youtube] a: Video unavailable. This video contains content from SME, who has blocked it on "
        "copyright grounds": "direitos",
        "ERROR: [youtube] a: Private video. Sign in if you've been granted access to this video": "privado",
        "ERROR: [youtube] a: Sign in to confirm you\U00002019re not a bot. Use --cookies": "bloqueado",
        "ERROR: [youtube] a: Sign in to confirm your age. This video may be inappropriate": "restrito",
        "ERROR: [TikTok] 7: Unexpected response from webpage request; please report this issue": "bloqueado",
        "ERROR: [TikTok] 7: Video not available, status code 10204": "removido",
        "This video has been removed for violating YouTube's Community Guidelines": "violacao",
        "HTTP Error 404: Not Found": "removido",
        "Read timed out": "erro",
    }
    for msg, want in cases.items():
        assert c(msg) == want, (msg, c(msg), want)
    assert metrics.normalize_video_url("youtube", "https://youtube.com/shorts/mTt3C_rZNZI?feature=x") == \
        "https://www.youtube.com/shorts/mTt3C_rZNZI"
    assert metrics.normalize_video_url("tiktok", "https://www.tiktok.com/@podpah/video/7601549938912136466") == \
        "https://www.tiktok.com/@podpah/video/7601549938912136466"
    assert metrics.normalize_video_url("tiktok", "https://www.tiktok.com/tiktokstudio/content") is None
    assert metrics._profile_from_post_url("tiktok", "https://www.tiktok.com/@podpah") == "https://www.tiktok.com/@podpah"
    assert metrics.profile_url("youtube", "@Podpah") == "https://www.youtube.com/@Podpah"
    assert metrics.text_similarity("Fulano PERDEU a linha no podcast \U0001F602 (Parte 1/2)",
                                   "fulano perdeu a linha no podcast #podcast #humor") > 0.9
    assert metrics.text_similarity("Fulano perdeu a linha", "receita de bolo de cenoura") < 0.4
    print("ok classificacao de erros e URLs")


def test_collect_fake():
    fresh_env("coleta")
    cfg = cfg_with(metricas__perfis__tiktok="@cortex_teste")
    add_clip("yt-ok", "Deputado se irrita no plenario \U0001F525")
    add_clip("yt-rm", "Corte que foi removido")
    add_clip("tt-perfil", "Fulano perdeu a linha no podcast \U0001F602", category="humor")
    add_clip("tt-blq", "Corte bloqueado")
    add_clip("tt-blq2", "Outro corte bloqueado")
    p1 = add_post("yt-ok", "youtube", NOW - 24.5 * H, "https://youtube.com/shorts/AAAAAAAAAAA")
    p2 = add_post("yt-rm", "youtube", NOW - 2.1 * H, "https://youtube.com/shorts/REMOVIDO000")
    p3 = add_post("tt-perfil", "tiktok", NOW - 2.3 * H, None)
    add_post("tt-blq", "tiktok", NOW - 2.8 * H, "https://www.tiktok.com/@cortex_teste/video/111111111")
    add_post("tt-blq2", "tiktok", NOW - 2.9 * H, "https://www.tiktok.com/@cortex_teste/video/222222222")
    add_post("yt-ok", "youtube", NOW - 30 * H, "https://youtube.com/shorts/BBBBBBBBBBB", dry=True)  # teste: ignora
    add_post("yt-ok", "tiktok", NOW - 30 * H, None, ok=False)                                      # falhou: ignora

    calls = []

    def fake_extract(url, cfg, platform, *, flat=False, n=10, light=True, lang=None, timeout=None):
        calls.append(url)
        if flat:
            assert url == "https://www.tiktok.com/@cortex_teste", url
            return {"entries": [
                {"id": "999000999", "title": "outro video qualquer", "timestamp": NOW - 30 * H, "view_count": 5},
                {"id": "777000777", "title": "Fulano perdeu a linha no podcast \U0001F602 #humor #podcast",
                 "timestamp": NOW - 2.3 * H - 120, "view_count": 321, "like_count": 12, "comment_count": 2,
                 "repost_count": 1},
            ]}
        if "AAAAAAAAAAA" in url:
            return {"id": "AAAAAAAAAAA", "view_count": 1234, "like_count": 50, "comment_count": 3,
                    "availability": "public", "timestamp": NOW - 24.5 * H, "uploader_id": "@cortex_teste"}
        if "REMOVIDO000" in url:
            raise metrics.ReadError("removido", "Video unavailable. This video has been removed")
        if "111111111" in url or "222222222" in url:
            raise metrics.ReadError("bloqueado", "Unexpected response from webpage request")
        raise AssertionError(f"chamada inesperada: {url}")

    orig = metrics._extract
    metrics._extract = fake_extract
    try:
        res = metrics.collect(cfg, max_items=30)
    finally:
        metrics._extract = orig
    print("   resultado:", json.dumps({k: v for k, v in res.items() if k != "mensagens"}, ensure_ascii=False))
    assert res["ok"] and res["devidos"] == 5, res
    assert res["lidos"] == 3 and res["problemas"] == 1 and res["bloqueados"] == 1 and res["pulados"] == 1, res
    rows = {r["post_id"]: dict(r) for r in db.conn().execute("SELECT * FROM post_metrics").fetchall()}
    assert rows[p1]["views"] == 1234 and rows[p1]["checkpoint"] == "24h" and rows[p1]["status"] == "ok"
    assert rows[p2]["status"] == "removido" and rows[p2]["checkpoint"] == "2h"
    assert rows[p3]["views"] == 321 and rows[p3]["shares"] == 1 and rows[p3]["fonte"] == "perfil"
    link = dict(db.conn().execute("SELECT * FROM post_links WHERE post_id=?", (p3,)).fetchone())
    assert link["url"] == "https://www.tiktok.com/@cortex_teste/video/777000777" and link["metodo"] == "perfil", link
    assert res["saude"]["youtube"] == "atencao", res["saude"]  # post removido -> atencao
    assert metrics.volume_factor("youtube", cfg) == 0.5
    st = json.loads((paths.STATE / "metricas_estado.json").read_text(encoding="utf-8"))
    assert st["bloqueio_ate"]["tiktok"] > NOW
    # 2a rodada logo em seguida: nada vencido (backoff e TikTok em espera), nenhuma chamada nova
    n_calls = len(calls)
    metrics._extract = fake_extract
    try:
        res2 = metrics.collect(cfg, max_items=30)
    finally:
        metrics._extract = orig
    assert res2["lidos"] == 0 and len(calls) == n_calls, (res2, calls)
    rows = metrics.summary_rows(cfg)
    assert {"titulo", "rede", "idade", "views", "likes", "situacao"} <= set(rows[0]), rows[0]
    sit = {r["post_id"]: r["situacao"] for r in rows}
    assert sit[p2] == "removido/indisponível", sit
    for r in rows:
        print(f"   {r['rede']:8} {r['idade']:>6} {r['views']:>7} {r['likes']:>6}  {r['titulo'][:34]:34}  {r['situacao']}")
        for ch in BANNED:
            assert all(ch not in str(v) for v in r.values())
    print("ok collect (extrator falso), links, bloqueio do TikTok e resumo")


def test_collect_never_raises():
    orig = metrics.due_items
    metrics.due_items = lambda cfg, now=None: (_ for _ in ()).throw(RuntimeError("banco quebrado"))
    try:
        res = metrics.collect(cfg_with())
    finally:
        metrics.due_items = orig
    assert res["ok"] is False and "banco quebrado" in res["mensagens"][0]
    print("ok collect nunca levanta excecao")


def test_health_rules():
    # A) 3 posts seguidos com < 10 views em 24 h -> pausa 72 h
    fresh_env("saude_zero")
    cfg = cfg_with()
    pids = []
    for i, age in enumerate([30, 28, 26]):
        add_clip(f"z{i}", f"corte {i}")
        pid = add_post(f"z{i}", "youtube", NOW - age * H, f"https://youtube.com/shorts/ZZZZZZZZZZ{i}")
        assert metrics.record_reading(pid, views=3, likes=0, ts=NOW - (age - 24) * H)
        pids.append(pid)
    h = metrics.account_health("youtube", cfg)
    assert h["nivel"] == "pausa" and h["ok"] is False and h["pausar_ate"] > NOW + 71 * H, h
    assert metrics.volume_factor("youtube", cfg) == 0.0
    assert metrics.account_health("tiktok", cfg)["nivel"] == "normal"
    data = json.loads((paths.STATE / "saude_contas.json").read_text(encoding="utf-8"))
    assert data["youtube"]["pausar_ate"] > NOW
    print("   pausa:", h["motivo"])
    metrics.resume("youtube")
    h = metrics.account_health("youtube", cfg)
    assert h["nivel"] == "normal", h  # os mesmos 3 posts nao disparam de novo
    # um 4o post ainda quase zerado -> nova trinca -> pausa de novo
    add_clip("z3", "corte 3")
    pid = add_post("z3", "youtube", NOW - 25 * H, "https://youtube.com/shorts/ZZZZZZZZZZ3")
    metrics.record_reading(pid, views=1, ts=NOW - 1 * H)
    assert metrics.account_health("youtube", cfg)["nivel"] == "pausa"

    # B) queda forte contra a mediana da conta -> atencao (0.5); depois de um ciclo inteiro -> pausa
    fresh_env("saude_queda")
    for i in range(8):
        add_clip(f"b{i}", f"base {i}")
        pid = add_post(f"b{i}", "tiktok", NOW - (200 - i * 10) * H)
        metrics.record_reading(pid, views=1000 + i, ts=NOW - (200 - i * 10 - 24) * H)
    for i in range(5):
        add_clip(f"q{i}", f"queda {i}")
        pid = add_post(f"q{i}", "tiktok", NOW - (100 - i * 15) * H)
        metrics.record_reading(pid, views=50, ts=NOW - (100 - i * 15 - 24) * H)
    h = metrics.account_health("tiktok", cfg)
    assert h["nivel"] == "atencao" and h["ok"] is True and h["pausar_ate"] is None, h
    assert metrics.volume_factor("tiktok", cfg) == 0.5
    print("   atencao:", h["motivo"])
    data = json.loads((paths.STATE / "saude_contas.json").read_text(encoding="utf-8"))
    data["tiktok"]["atencao_desde"] = NOW - 70 * H   # simula que a atencao ja dura um ciclo
    data["tiktok"]["gatilho_queda"] = []             # e a queda continua com posts novos
    (paths.STATE / "saude_contas.json").write_text(json.dumps(data), encoding="utf-8")
    metrics._HEALTH_CACHE.clear()                    # editamos o json na mao: descarta o cache de 60 s
    h = metrics.account_health("tiktok", cfg)
    assert h["nivel"] == "pausa", h
    print("   2 ciclos:", h["motivo"])
    t = time.perf_counter()
    for _ in range(200):                             # chamadas repetidas (policy) usam o cache
        metrics.volume_factor("tiktok", cfg)
    assert time.perf_counter() - t < 0.5
    print("ok saude da conta (pausa, atencao, retomada, 2 ciclos)")


def test_learning():
    fresh_env("aprendizado")
    cfg = cfg_with()
    import random as _r

    rng = _r.Random(7)
    specs = [("politica", 2.0), ("humor", 0.5), ("games", 1.0)]
    n = 0
    for k in range(12):
        for cat, mult in specs:
            n += 1
            plat = "youtube" if n % 2 else "tiktok"
            base = 200 if plat == "youtube" else 600
            layout = "full" if cat == "politica" else ("split" if k % 2 else "blur")
            emoji = "\U0001F525" * (k % 3)
            title = f"{cat} corte {k}{'?' if k % 4 == 0 else ''} {emoji}"
            add_clip(f"l{n}", title, category=cat, layout=layout, dur=30 + (k % 3) * 10,
                     channel="Canal Politico" if cat == "politica" else "Canal Humor",
                     series="serie x" if k % 5 == 0 else None)
            # horarios variados; politica mais a noite
            hour_off = (k * 7 + (3 if cat == "politica" else 0)) % 24
            ts = NOW - (24 * (k + 2) + hour_off) * H
            pid = add_post(f"l{n}", plat, ts)
            views = int(base * mult * rng.uniform(0.8, 1.25))
            metrics.record_reading(pid, views=views, likes=views // 20, ts=ts + 24.2 * H)
            if n == 15:
                few = learning.insights(cfg)
                assert "Ainda não há dados suficientes" in few[0], few
    w = learning.weights(cfg, force=True, seed=1)
    assert w["n_posts"] == 36 and w["suficiente"], w["n_posts"]
    for dim in learning.DIMS:
        for v, x in w[dim].items():
            assert 0.7 <= x <= 1.3, (dim, v, x)
    assert w["categoria"]["politica"] > 1.05 > 0.95 > w["categoria"]["humor"], w["categoria"]
    assert learning.weight_for(cfg, "categoria", "Política") == w["categoria"]["politica"]
    assert learning.weight_for(cfg, "categoria", "inexistente") == 1.0
    assert learning.weight_for(cfg, "hora", 13) == w["hora"].get("12-15", 1.0)
    print("   pesos categoria:", w["categoria"], "| layout:", w["layout"])
    ins = learning.insights(cfg)
    print("   insights:")
    for line in ins:
        print("     -", line)
        for ch in BANNED:
            assert ch not in line, line
        assert metrics.count_emojis(line) == 0, line
    assert any("Política rende" in x and "Humor" in x for x in ins), ins
    cache = json.loads((paths.STATE / "aprendizado.json").read_text(encoding="utf-8"))
    assert cache["pesos"]["n_posts"] == 36
    print("ok aprendizado (bandit, pesos em [0.7, 1.3], insights)")


def test_style_of_sources():
    for f in ["fabrica/metrics.py", "fabrica/learning.py", "docs/METRICAS.md"]:
        p = ROOT / f
        if not p.exists():
            continue
        txt = p.read_text(encoding="utf-8")
        for ch in BANNED:
            assert ch not in txt, (f, repr(ch))
    print("ok estilo (sem caracteres proibidos)")


if __name__ == "__main__":
    try:
        test_checkpoints()
        test_classify_and_urls()
        test_collect_fake()
        test_collect_never_raises()
        test_health_rules()
        test_learning()
        test_style_of_sources()
        print("TODOS OK")
    finally:
        try:
            c = getattr(db._local, "conn", None)
            if c is not None:
                c.close()
                db._local.conn = None
        except Exception:
            pass
        shutil.rmtree(TMP_ROOT, ignore_errors=True)
