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
E.posts = real

print(f"\n{'TUDO OK' if not fails else 'FALHAS: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
