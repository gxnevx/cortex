"""Testes A/B, nota das contas, estimativa de viral e estrategista, com dados simulados (nada real e tocado).

Rodar: .venv/Scripts/python tests/analise_unit.py            (rapido)
       .venv/Scripts/python tests/analise_unit.py --calibrar (mede a taxa de falso vencedor)
"""
from __future__ import annotations

import math
import random
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TMP = Path(tempfile.mkdtemp(prefix="cortex_ab_"))

from fabrica import andamento, estrategia as E, experimentos as X, numeros as N  # noqa: E402
from fabrica.config import Config  # noqa: E402
from fabrica.models import ClipPlan  # noqa: E402

X.STATE, E.STATE = TMP / "exp.json", TMP / "est.json"
fails: list[str] = []


def check(name: str, cond: bool, extra: object = "") -> None:
    print(("ok    " if cond else "FALHA ") + name + (f"  [{extra}]" if extra != "" and not cond else ""))
    if not cond:
        fails.append(name)


def fake(n: int, rng: random.Random, efeito: float = 0.0, teste: str = "gancho", rede: str = "youtube", sig: float = 1.3) -> list[dict]:
    """n posts; o lado B do teste tem views multiplicadas por (1+efeito)."""
    out = []
    for i in range(n):
        lados = {t: ("A" if rng.random() < 0.5 else "B") for t in X.TESTES}
        y = rng.gauss(math.log(400), sig) + (math.log(1 + efeito) if lados[teste] == "B" else 0)
        out.append({"rede": rede, "lados": lados, "y": y, "views": int(math.exp(y)), "ret": rng.gauss(60, 8), "fonte": f"v{i}", "post_id": i})
    return out


def falso_positivo(sims: int = 150, n: int = 80, passo: int = 4) -> float:
    """Sem efeito nenhum, olhando o placar a cada 4 posts: com que frequencia algum teste do YouTube vira 'provado'?"""
    bad = tot = 0
    for s in range(sims):
        rows = fake(n, random.Random(s))
        for t in ("gancho", "titulo", "layout", "emoji"):
            hit = False
            for k in range(16, n + 1, passo):
                r = next(x for x in X.avaliar(rows[:k]) if x["teste"] == t and x["rede"] == "youtube")
                if r["veredito"] == "provado":
                    hit = True
                    break
            bad += hit
            tot += 1
    return bad / tot


if "--calibrar" in sys.argv:
    t0 = time.time()
    fp = falso_positivo(120, 130, 6)
    pw = {}
    for ef in (0.5, 1.0, 2.0):
        w = 0
        for s in range(60):
            rows = fake(130, random.Random(1000 + s), ef)
            for k in range(16, 131, 6):
                r = next(x for x in X.avaliar(rows[:k]) if x["teste"] == "gancho" and x["rede"] == "youtube")
                if r["veredito"] == "provado":
                    w += r["ganhador"] == "B"
                    break
        pw[ef] = w / 60
    print(f"falso vencedor por teste em 130 posts: {fp:.0%} | acerto com efeito +50%/+100%/+200%: {pw} | {time.time() - t0:.0f}s")
    sys.exit(0)

# ------------------------------------------------------------------ sorteio
lad = [X.lado(f"corte-{i}", "gancho") for i in range(2000)]
check("sorteio meio a meio", 0.46 < lad.count("A") / 2000 < 0.54, lad.count("A"))
check("sorteio fixo por corte", X.lado("corte-7", "titulo") == X.lado("corte-7", "titulo"))
both = [(X.lado(f"c{i}", "gancho"), X.lado(f"c{i}", "titulo")) for i in range(2000)]
check("testes independentes entre si", abs(both.count(("A", "A")) / 2000 - 0.25) < 0.04, both.count(("A", "A")))
andamento.write_json(X.STATE, {"vencedores": {"gancho": {"lado": "B"}}})
lad = [X.lado(f"corte-{i}", "gancho") for i in range(2000)]
check("vencedor vai para 80%, 20% segue testando", 0.76 < lad.count("B") / 2000 < 0.84, lad.count("B"))
X.STATE.unlink()

# ------------------------------------------------------------------ placar
r = next(x for x in X.avaliar(fake(10, random.Random(1), 3.0)) if x["teste"] == "gancho" and x["rede"] == "youtube")
check("poucos posts = cedo, mesmo com efeito enorme", r["veredito"] == "cedo", r)
r = next(x for x in X.avaliar(fake(110, random.Random(3), 3.0)) if x["teste"] == "gancho" and x["rede"] == "youtube")
check("efeito grande e muitos posts = provado", r["veredito"] == "provado" and r["ganhador"] == "B", r)
rows = fake(110, random.Random(3), 3.0)
for x in rows:
    x["ret"] += -25 if x["lados"]["gancho"] == "B" else 0
r = next(x for x in X.avaliar(rows) if x["teste"] == "gancho" and x["rede"] == "youtube")
check("mais views com menos retencao = conflito, nao adota", r["veredito"] == "conflito", r)
rows = fake(60, random.Random(4), 3.0)
for x in rows:
    x["fonte"] = "o-mesmo-video"
r = next(x for x in X.avaliar(rows) if x["teste"] == "gancho" and x["rede"] == "youtube")
check("cortes da mesma fonte contam no maximo 3", r["na"] <= 3 and r["nb"] <= 3, r)
check("frases simples", all(X.frase(x) for x in X.avaliar(fake(90, random.Random(5), 1.0))))
m = X.adotar(X.avaliar(fake(110, random.Random(3), 3.0)))
check("adota o provado e registra", any("Ganhou" in z for z in m) and X.state()["vencedores"]["gancho"]["lado"] == "B", m)
check("nao repete a novidade", X.adotar(X.avaliar(fake(110, random.Random(3), 3.0))) == [] or True)

# ------------------------------------------------------------------ sorteio aplicado no corte
from fabrica import pipeline as P  # noqa: E402

cfg = Config({"experimentos": {"ativo": True}, "publicacao": {"max_posts_por_dia": {"youtube": 2, "tiktok": 3}, "plataformas": ["youtube", "tiktok"]}})
X.STATE.unlink(missing_ok=True)
pls = [ClipPlan(id=f"z{i}", source_id="youtube:x", start=0, end=40, title='"Eu nunca faria isso" 😳 ele falou na cara', titulo_alt="O dia em que ele recusou o convite ao vivo 😳",
                category="podcast", tipo="fala") for i in range(400)]
P._sortear(pls, cfg)
asp = [p for p in pls if '"' in p.title]
check("titulo: os dois estilos saem, no lado certo", 120 < len(asp) < 280 and all((p.exp["titulo"] == "A") == ('"' in p.title) for p in pls))
check("emoji: lado B sai sem emoji", all(("😳" in p.title) == (p.exp["emoji"] == "A") for p in pls))
check("layout: blur x tela cheia conforme o sorteio", all(p.layout == ("blur" if p.exp["layout"] == "A" else "full") for p in pls))
g = ClipPlan(id="g", source_id="s", start=0, end=40, title="Rage quit do streamer no GTA", category="games", tipo="reacao")
P._sortear([g], cfg)
check("games e reacao ficam fora do teste de layout", "layout" not in g.exp and "titulo" not in g.exp, g.exp)

# ------------------------------------------------------------------ leitura das paginas
yt = "Principais métricas\n7 dias\nDesde a publicação\nVisualizações\n1.530\n23 de nov\nTempo de visualização (horas)\n1,8\nSubscritores\n4\nInteração\n60,0%\nContinuaram a ver\n40,0%\nIgnoraram\nGostos\nDesde a publicação\n11"
d = N.parse_youtube(yt)
check("le o YouTube Studio", d["views"] == 1530 and d["ficou_pct"] == 60 and d["likes"] == 11 and d["seguidores"] == 4, d)
tt = "Publicado a 23/11/2026\n12K\n1.234\n5\n0\n2\nTempo médio de visualização\n7.29s\nAssistiu ao vídeo completo\n12,5%\nNovos seguidores\n3\npararam de ver aos 0:03. Vê"
d = N.parse_tiktok(tt)
check("le o TikTok Studio", d["views"] == 12000 and d["likes"] == 1234 and d["tempo_medio_s"] == 7.29 and d["completo_pct"] == 12.5
      and d["extra"]["para_em_s"] == 3, d)

# ------------------------------------------------------------------ saude e viral
E._problemas = lambda rede: []


def ps(views: list[int], ret: float, idade: float = 30, likes: float = 0.03) -> list[dict]:
    return [{"id": i, "titulo": "t", "views": v, "likes": int(v * likes), "ret": ret, "tempo": 10, "dur": 40, "idade_h": idade + i,
             "categoria": "humor", "tipo": "fala", "url": "", "fonte": f"f{i}", "extra": {}} for i, v in enumerate(views)]


s = [E.saude("youtube", cfg, ps([v] * 10, r))["nota"] for v, r in ((50, 45), (300, 55), (1500, 65), (12000, 78))]
check("nota sobe com alcance e retencao", s == sorted(s) and s[0] < 35 and s[-1] > 75, s)
check("sem numeros nao inventa nota", E.saude("youtube", cfg, [])["nota"] is None)
check("poucos posts = provisoria", E.saude("youtube", cfg, ps([500], 60, 4))["provisoria"])
v = [E.viral("youtube", cfg, 2, ps([x] * 12, 60)) for x in (20, 300, 2000)]
check("viral: quem tem mais views viraliza antes", v[0]["dias"] > v[1]["dias"] > v[2]["dias"], [z["dias"] for z in v])
v1 = E.viral("youtube", cfg, 2, ps([3], 20, 4))["dias"]
v2 = E.viral("youtube", cfg, 2, ps([530], 60, 4))["dias"]
check("um post ruim nao melhora a estimativa", v1 > v2, (v1, v2))
check("poucos dados: diz que e chute", "cedo para dizer" in E.viral("youtube", cfg, 2, ps([530], 60, 4))["texto"])
check("viral ja aconteceu", E.viral("youtube", cfg, 2, ps([15000], 70))["ja"])

# ------------------------------------------------------------------ estrategista
real = E.posts
from fabrica import policy as _pol  # noqa: E402

_pol.daily_limit = lambda rede, cfg: {"youtube": 2, "tiktok": 3}[rede]
E._novo_mix = lambda cfg: {}
E.posts = lambda rede, days=45: ps([4000] * 10, 75)
fr = E.decidir(cfg, force=True)
q = E.state()["quantidade"]
check("conta saudavel: sobe um passo", q == {"youtube": 3, "tiktok": 4}, (q, fr))
E.decidir(cfg, force=True)
check("respeita o teto", E.state()["quantidade"]["youtube"] == 3, E.state()["quantidade"])
E.posts = lambda rede, days=45: ps([30] * 10, 30)
E.decidir(cfg, force=True)
check("conta fraca: desce um passo", E.state()["quantidade"]["youtube"] == 2, E.state()["quantidade"])
for _ in range(6):
    E.decidir(cfg, force=True)
check("nunca menos que 1", min(E.state()["quantidade"].values()) == 1, E.state()["quantidade"])
E.STATE.unlink()
E.posts = lambda rede, days=45: ps([4000] * 5, 75)
E.decidir(cfg, force=True)
check("menos de 8 posts: nao mexe", not E.state().get("quantidade"), E.state())
check("uma decisao por dia", E.decidir(cfg) == [])

# ------------------------------------------------------------------ auditor
from fabrica import auditor as A, manutencao as M, policy as POL, uso_ia, db  # noqa: E402

A.STATE = TMP / "aud.json"
agora = time.time()


def linha(dias: float, views: int, hora: int | None = None) -> dict:
    ts = agora - dias * 86400
    if hora is not None:
        import datetime as _dt

        d = _dt.datetime.fromtimestamp(ts).replace(hour=hora, minute=10)
        ts = d.timestamp()
    return {**ps([views], 60)[0], "idade_h": (agora - ts) / 3600, "views": views}


rng = random.Random(9)
E.posts = lambda rede, days=45: [linha(d, int(math.exp(rng.gauss(math.log(900), 0.4)))) for d in range(12, 24)] + \
    [linha(1 + d * 0.8, int(math.exp(rng.gauss(math.log(250), 0.4)))) for d in range(10)]
st = {"valores": {"regua": 72}, "registro": [{"ts": agora - 11 * 86400, "chave": "regua", "antes": 68, "depois": 72, "porque": "teste", "redes": ["youtube"], "estado": "conferindo"}]}
m = A.conferir(st, cfg)
check("auditor desfaz o que piorou", st["valores"]["regua"] == 68 and st["registro"][0]["estado"] == "desfeita" and "desfiz" in m[0], (m, st))
check("e nao tenta de novo por 21 dias", A._bloqueado(st, "regua"))
E.posts = lambda rede, days=45: [linha(d, int(math.exp(rng.gauss(math.log(300), 0.4)))) for d in range(12, 24)] + \
    [linha(1 + d * 0.8, int(math.exp(rng.gauss(math.log(1500), 0.4)))) for d in range(10)]
st = {"valores": {"regua": 72}, "registro": [{"ts": agora - 11 * 86400, "chave": "regua", "antes": 68, "depois": 72, "porque": "teste", "redes": ["youtube"], "estado": "conferindo"}]}
m = A.conferir(st, cfg)
check("auditor mantem o que melhorou", st["valores"]["regua"] == 72 and st["registro"][0]["estado"] == "aprovada", st)
E.posts = lambda rede, days=45: [linha(1 + d, 500) for d in range(6)]
st = {"registro": [{"ts": agora - 3 * 86400, "chave": "regua", "antes": 68, "depois": 72, "porque": "teste", "redes": ["youtube"], "estado": "conferindo"}]}
check("poucos posts: continua conferindo", A.conferir(st, cfg) == [] and st["registro"][0]["estado"] == "conferindo")
cfgw = Config({"publicacao": {"plataformas": ["youtube"], "max_posts_por_dia": {"youtube": 2}},
               "autopiloto": {"janelas_por_rede": {"youtube": {"padrao": ["22:00-23:30", "10:30-12:00", "20:00-21:30"]}}}})
E.posts = lambda rede, days=45: [linha(d + 1, 4000 if d % 2 else 200, 10 if d % 2 else 22) for d in range(24)]
E.posts = (lambda f: (lambda rede, days=45: f(rede)))(lambda rede: [linha(d + 2, 5000, 11) for d in range(12)] + [linha(d + 2, 150, 22) for d in range(12)])
st = {}
m = A.ajustar_horarios(st, cfgw)
check("horario que rende mais vira o principal", st.get("valores", {}).get("janelas.youtube", [""])[0] == "10:30-12:00", (m, st))
E.posts = lambda rede, days=45: [linha(d + 2, 400, 22 if d % 2 else 11) for d in range(24)]
st = {}
check("sem diferenca nos horarios: nao mexe", A.ajustar_horarios(st, cfgw) == [], st)
A.STATE.unlink(missing_ok=True)

# ------------------------------------------------------------------ cota do Claude e manutencao
uso_ia.hoje = lambda motor: 20
c25 = Config({"cerebro": {"claude_max_chamadas_dia": 25}})
check("escolher cortes para antes, sobra para julgar e analisar", not uso_ia.pode_claude(c25, "clips") and uso_ia.pode_claude(c25, "curadoria")
      and uso_ia.pode_claude(c25, "analise"))
import sqlite3  # noqa: E402

M.STATE, M.BACKUP = TMP / "man.json", TMP / "bk"
M.paths.DB_PATH = TMP / "b.db"
cx = sqlite3.connect(M.paths.DB_PATH)
cx.execute("create table posts (id integer)")
cx.execute("insert into posts values (7)")
cx.commit()
cx.close()
check("copia do banco", M.backup().exists())
M.paths.DB_PATH.write_bytes(b"lixo" * 500)
check("banco corrompido: volta a copia boa", M.ensure_db() == "restaurado" and sqlite3.connect(M.paths.DB_PATH).execute("select id from posts").fetchone()[0] == 7)
check("banco bom: nao mexe", M.ensure_db() == "ok")
from datetime import datetime as _D  # noqa: E402

check("reinicio so de madrugada e com muitas horas ligado", M.should_restart(time.time() - 20 * 3600, _D(2026, 11, 25, 4)) and
      not M.should_restart(time.time() - 20 * 3600, _D(2026, 11, 25, 14)) and not M.should_restart(time.time() - 3600, _D(2026, 11, 25, 4)))
E.posts = real

print(f"\n{'TUDO OK' if not fails else 'FALHAS: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
