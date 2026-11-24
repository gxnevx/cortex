"""Nada sai sem revisao, titulo verdadeiro, comeco e fim conferidos. Sem internet e sem IA de verdade.

Roda:  .venv\\Scripts\\python.exe tests\\revisao_unit.py
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fabrica import paths  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="cortex_rev_"))
paths.DB_PATH = TMP / "t.db"
paths.STATE = TMP
from fabrica import auditor, bordas, curadoria, db, honesto, pipeline, revisao, storage  # noqa: E402
from fabrica.config import Config  # noqa: E402
from fabrica.models import ClipPlan, PostResult, RenderedClip, Segment, Transcript  # noqa: E402
from fabrica.publish import guard  # noqa: E402
import fabrica.publish as publish  # noqa: E402

revisao.STATE = TMP / "revisoes.json"
guard._state_dir = lambda: TMP
storage.release_published = lambda *a, **k: "mantido"
auditor.get = lambda k: None
fails: list[str] = []


def check(name: str, cond: bool, extra: object = "") -> None:
    print(("ok    " if cond else "FALHA ") + name + (f"  [{extra}]" if extra and not cond else ""))
    if not cond:
        fails.append(name)


cfg = Config({"publicacao": {"plataformas": ["youtube", "tiktok"], "aquecimento": {"ativo": False}, "max_posts_por_dia": {"youtube": 9, "tiktok": 9}},
              "curadoria": {"nota_minima": 68}, "corte": {"duracao_min_s": 28, "duracao_max_s": 58}})
FALA = ("Eu acho que quem trai uma vez trai sempre. Vai do caráter de cada pessoa. Mas perdoaria uma traição? Dialogando certinho talvez chegaria num "
        "acordo. Eu não traio ninguém, sou uma pessoa diferente, o filme vai bater dois bilhões isso aqui, e no final ia dar um pé na bunda, né.")


def clip(i: int, titulo: str = '"Quem trai uma vez trai sempre" 😳', tela: str = '"QUEM TRAI UMA VEZ"', dur: float = 45, nota: float = 80, **kw) -> RenderedClip:
    f = TMP / f"c{i}.mp4"
    f.write_bytes(b"x")
    p = ClipPlan(id=f"c{i}", source_id=kw.pop("src", f"s{i}"), start=0, end=dur, title=titulo, hook=tela, description="", hashtags=[])
    p.score, p.fala, p.category, p.tipo = nota, kw.pop("fala", FALA), kw.pop("cat", "polemica"), "fala"
    for k, v in kw.items():
        setattr(p, k, v)
    return RenderedClip(plan=p, path=str(f), duration=dur, layout="blur")


# ------------------------------------------------------------------ texto honesto
check("frase dita vale, com numero e 'pra' diferentes", honesto.existe("VAI BATER 2 BILHÕES", FALA) and honesto.existe("ia dar um pé na bunda né", FALA))
check("frase que nao foi dita nao vale", not honesto.existe("QUER FAZER O POVO DE OTÁRIO", FALA))
check("tira final inventado", honesto.limpa_titulo('"Stream, enfim" 😳 e a mesa TRAVOU') == '"Stream, enfim" 😳' and honesto.limpa_titulo('"Oi" a mesa rachou 😳') == '"Oi" 😳')
check("titulo normal fica igual", honesto.limpa_titulo("Ela atirou em plena rua por uma joia 😳") == "Ela atirou em plena rua por uma joia 😳")
p = clip(1, '"Você é um ladrão" e a mesa TRAVOU', '"POVO DE OTÁRIO"').plan
m = honesto.arruma_plano(p, FALA)
check("antes de editar: tela e titulo viram verdade", not honesto.falsas(p.hook, FALA) and not honesto.falsas(p.title, FALA) and "TRAVOU" not in p.title, (p.title, p.hook, m))
from fabrica.brain import heuristic, modelos_tom as mt  # noqa: E402

check("finais prontos sao so perguntas", all(s.endswith("?") or s == "se discordar, comenta" or "ver defender" in s for n in range(5) for k in ("polemica", "games")
                                              for s in mt.suffixes_for(k, n)))
check("modelos sem apoio na fala sao perguntas", all(t.endswith("?") for t in mt._pool(mt.AGGRESSIVE_TITLES, "polemica", "nada")[1])
      and all(s.endswith("?") for v in heuristic.POLEMIC_SUFFIX.values() for s in v))

# ------------------------------------------------------------------ editor-chefe
salvo: dict[str, str] = {}
db.set_clip_status = lambda i, s: salvo.__setitem__(i, s)
db.update_clip_plan = lambda pl: None
curadoria._ask_claude = lambda items, c: None
curadoria._retry[0] = 0
r = curadoria.curate(cfg, [clip(2, nota=99, cat="games")])
check("sem o Claude ninguem e aprovado, nem com nota 99", r == {"aprovados": [], "descartados": []} and not salvo, (r, salvo))
check("e todos esperam", curadoria._retry[0] > time.time() and curadoria.pending(cfg) == [])
boa = {"nota": 85, "fatal": False, "sozinho": True, "inicio": True, "fim": True, "titulo_ok": True, "motivo": "bom", "titulo": ""}
for nome, muda, passa in (("bom passa", {}, True), ("nao faz sentido sozinho", {"sozinho": False}, False), ("comeca no meio", {"inicio": False}, False),
                          ("corta antes do fim", {"fim": False}, False), ("titulo falso sem troca", {"titulo_ok": False}, False),
                          ("titulo falso com troca boa", {"titulo_ok": False, "titulo": "Ele perdoaria uma traição? A resposta dele 😳"}, True),
                          ("nota baixa", {"nota": 55}, False)):
    curadoria._ask_claude = lambda items, c, m=muda: {1: {**boa, **m}}
    x = clip(3, nota=75)
    r = curadoria.curate(cfg, [x])
    check(f"editor-chefe: {nome}", bool(r["aprovados"]) == passa, r)
curadoria._ask_claude = lambda items, c: {1: boa}
r = curadoria.curate(cfg, [clip(4, tela='"POVO DE OTÁRIO DEMAIS"')])
check("tela com frase falsa cai na regra, mesmo com o Claude gostando", not r["aprovados"] and "não está na fala" in r["descartados"][0][1], r)

# ------------------------------------------------------------------ revisao final
resp: dict = {}
pedidos: list[str] = []


def falso(c, fala, cf):
    pedidos.append(c.plan.id)
    return resp.get("v")


revisao.perguntar = falso
tudo = {k: 9 for k in revisao.MINIMOS} | {"nota": 80, "motivo": "ok"}
resp["v"] = tudo
c = clip(10)
check("revisao aprova e lembra", revisao.garantir(c, cfg)["ok"] and revisao.garantir(c, cfg)["ok"] and pedidos == ["c10"], pedidos)
c.plan.title = '"Quem trai uma vez trai sempre" você concorda?'
revisao.garantir(c, cfg)
check("mudou o titulo: revisa de novo", pedidos == ["c10", "c10"])
for k, minimo in revisao.MINIMOS.items():
    resp["v"] = {**tudo, k: minimo - 1}
    check(f"revisao reprova por {k}", not revisao.garantir(clip(20 + len(pedidos)), cfg)["ok"])
resp["v"] = None
e = clip(60)
r = revisao.garantir(e, cfg)
check("sem o Claude: espera, nao posta e nao reprova", r["espera"] and not r["ok"] and revisao.estado(e) is None)
revisao._espera[0] = 0
check("regra: final inventado", not revisao.garantir(clip(61, '"Quem trai uma vez trai sempre" e a mesa TRAVOU'), cfg)["ok"])
check("regra: curto demais", not revisao.garantir(clip(62, dur=12), cfg)["ok"])

check("item sem nota conta como falta", "nota" in revisao.faltas({k: 9 for k in revisao.MINIMOS if k != "nota"})[0])

# portao unico: publish_clips nunca manda o que nao passou
mandou: list = []
publish.check_login = lambda pl, cf=None, deep=False: True


def lote(clips, cf, platforms=None, dry_run=False, on_event=None):
    mandou.extend(x.plan.id for x in clips)
    return [PostResult(x.plan.id, pl, True, url="u", ts=time.time()) for x in clips for pl in platforms]


publish.publish_batch = lote


class Rep:
    def __getattr__(self, n):
        return lambda *a, **k: None


resp["v"] = {**tudo, "entende_sozinho": 2, "motivo": "aleatório"}
salvo.clear()
pipeline.publish_clips(cfg, [clip(70)], False, Rep())
check("portao: reprovado nao sai e deixa a fila", mandou == [] and salvo.get("c70") == "rejeitado", (mandou, salvo))
resp["v"] = None
salvo.clear()
pipeline.publish_clips(cfg, [clip(71)], False, Rep())
check("portao: sem revisao nao sai, mas continua na fila", mandou == [] and salvo == {}, (mandou, salvo))
revisao._espera[0] = 0
resp["v"] = tudo
pipeline.publish_clips(cfg, [clip(72)], False, Rep())
check("portao: aprovado sai", mandou == ["c72"])
mandou.clear()
resp["v"] = None
pipeline.publish_clips(cfg, [clip(73)], False, Rep(), revisado_pelo_dono=True)
check("o dono escolheu na mao: a revisao e dele", mandou == ["c73"])
resp["v"] = {**tudo, "termina_bem": 1}
partes = [clip(80 + k, part=k, parts_total=3, series="x", src="s") for k in (1, 2, 3)]
db.clips_by_status = lambda s: partes[1:]
salvo.clear()
revisao.filtrar([partes[0]], cfg)
check("parte reprovada leva as seguintes", salvo == {"c81": "rejeitado", "c82": "rejeitado", "c83": "rejeitado"}, salvo)

# ------------------------------------------------------------------ comeco e fim
seg = [Segment(float(i * 5), float(i * 5 + 5), f"frase {i}.", []) for i in range(80)]
t = Transcript(seg, "pt", "x")


def plano(a: float, b: float, i: int = 1, **kw) -> ClipPlan:
    x = ClipPlan(id=f"p{i}", source_id="s", start=a, end=b, title="Título original do corte", hook="TELA", description="", hashtags=[])
    x.score = kw.pop("score", 70)
    return x


def ap(ps, dec):
    return bordas.aplicar(ps, dec, [(i, x) for i, x in enumerate(ps, 1)], t, 28, 58)


r = ap([plano(100, 130)], {1: {"serve": True, "inicio": 85, "fim": 130}})
check("recua o comeco", len(r) == 1 and (r[0].start, r[0].end) == (85, 130), r)
check("nao serve: sai antes de editar", ap([plano(100, 130)], {1: {"serve": False}}) == [])
r = ap([plano(100, 130)], {1: {"serve": True, "inicio": 100, "fim": 300}})
check("pedido absurdo e ignorado", (r[0].start, r[0].end) == (100, 130))
r = ap([plano(100, 150)], {1: {"serve": True, "partes": [[60, 110], [110, 160], [160, 205]], "titulo": "Ele conta a história inteira do assalto 😳", "tela": "A HISTÓRIA INTEIRA"}})
check("historia longa vira 3 partes continuas", [(x.part, x.parts_total, x.start, x.end) for x in r] == [(1, 3, 60, 110), (2, 3, 110, 160), (3, 3, 160, 205)]
      and len({x.id for x in r}) == 3 and len({x.series for x in r}) == 1, [(x.part, x.start, x.end) for x in r])
r = ap([plano(100, 130, 1, score=60), plano(140, 175, 2, score=90)], {1: {"serve": True, "inicio": 115, "fim": 160}, 2: {"serve": True, "inicio": 140, "fim": 175}})
check("um em cima do outro: fica o de nota maior", [x.id for x in r] == ["p2"], [x.id for x in r])
check("sem resposta: fica como veio", [(x.start, x.end) for x in ap([plano(100, 130)], {})] == [(100, 130)])

# ------------------------------------------------------------------ ajuste fino por frase
from fabrica.models import Word  # noqa: E402

txt = ("sobra de outro assunto. O Fulano contou que foi assaltado ontem. Ele correu atras do ladrao. O ladrao caiu da moto. A policia chegou na hora. "
       "Todo mundo aplaudiu. Vamos para o intervalo agora.").split()
ws, x = [], 0.0
for w in txt:
    ws.append(Word(x, x + 0.9, w))
    x += 1.0
wide = Transcript([Segment(0, x, " ".join(txt), ws)], "pt", "x")
fr = bordas.frases(wide, 1000.0)
check("quebra em frases inteiras", [f[2].split()[0] for f in fr] == ["sobra", "O", "Ele", "O", "A", "Todo", "Vamos"], fr)
semp = Transcript([Segment(0, 60, "x", [Word(i * 1.0, i + 0.5, "rima") for i in range(50)])], "pt", "x")
check("rap sem pontuacao tambem quebra", len(bordas.frases(semp, 0)) >= 3)


def um(d, **kw):
    q = plano(1000, 1030)
    q.teaser_start, q.teaser_end = None, None
    for k, v in kw.items():
        setattr(q, k, v)
    return q, bordas.aplicar_fino([(1, q, fr)], {1: d}, 24, 58, 62)


bom = {"serve": True, "primeira": 1, "ultima": 5, "nota": 80, "titulo": "Fulano contou como correu atrás do ladrão 😳", "tela": '"o ladrao caiu da moto"', "motivo": "boa"}
q, f = um(bom)
check("comeca e termina em frase inteira", f == {} and abs(q.start - 1003.88) < 0.01 and abs(q.end - (1000 + fr[5][1] - 1000 + 0.3)) < 0.01, (q.start, q.end, f))
check("nota e textos guardados", q.editor["nota"] == 80 and q.hook == '"O LADRAO CAIU DA MOTO"' and "Fulano" in q.title, (q.editor, q.hook, q.title))
check("nota baixa nem edita", "nota 50" in um({**bom, "nota": 50})[1].get("p1", ""))
check("nao serve: nem edita", um({**bom, "serve": False})[1] != {})
check("curto demais: nem edita", um({**bom, "primeira": 3, "ultima": 3})[1] != {})
check("numero absurdo: fica como estava", um({**bom, "ultima": 99})[1] == {})
check("sem resposta: fica como estava", bordas.aplicar_fino([(1, plano(1000, 1030), fr)], {}, 24, 58, 62) == {})
pts = [plano(1000, 1030, k) for k in (1, 2)]
for k, y in enumerate(pts, 1):
    y.part, y.parts_total, y.series = k, 2, "h"
f = bordas.aplicar_fino([(1, pts[0], fr), (2, pts[1], fr)], {1: bom, 2: {**bom, "serve": False}}, 24, 58, 62)
check("serie: cai uma, caem todas", set(f) == {"p1", "p2"}, f)
check("texto na tela nunca corta palavra", bordas.curto('Lula não chama de "ajuste", vai chamar de plano de desenvolvimento') == "Lula não chama de ajuste, vai chamar" or
      bordas.curto('Lula não chama de "ajuste", vai chamar de plano de desenvolvimento').split()[-1] in ("chamar", "ajuste"), bordas.curto('Lula não chama de "ajuste", vai chamar de plano de desenvolvimento'))
curadoria._ask_claude = lambda items, c: (_ for _ in ()).throw(AssertionError("nao devia chamar o Claude"))
z = clip(90, nota=75)
z.plan.editor = {"nota": 80, "motivo": "boa"}
check("editor-chefe usa a nota ja dada, sem nova chamada", curadoria.curate(cfg, [z])["aprovados"] != [])
z = clip(91, nota=60)
z.plan.editor = {"nota": 63, "motivo": "morno"}
check("nota ja dada baixa: descarta", curadoria.curate(cfg, [z])["descartados"] != [])
from fabrica.discovery import nichos  # noqa: E402


class C:
    def __init__(self, cat, s):
        self.extra, self.score = {"categoria": cat}, s


sel = nichos.select_mix([C("politica", 99), C("noticias", 98), C("politica", 97), C("podcast", 60), C("humor", 59), C("games", 58)], 4, {"podcast": 0.35, "humor": 0.3, "games": 0.2, "politica": 0.15})
check("no maximo 1 de politica ou noticia por rodada", sum(s.extra["categoria"] in ("politica", "noticias") for s in sel) == 1, [s.extra for s in sel])

# ------------------------------------------------------------------ meio da tela
from fabrica.editor import layouts, react  # noqa: E402

for w, h in ((1920, 1080), (1280, 720), (1440, 1080)):
    x, y, fw, fh = layouts.blur_video_box({"width": w, "height": h})
    check(f"video {w}x{h} no meio exato", abs((y + fh / 2) - 960) <= 1 and abs((x + fw / 2) - 540) <= 1, (x, y, fw, fh))
b = layouts.blur_video_box({"width": 1920, "height": 1080, "blur_ar": 1.78})
check("telejornal: quadro inteiro e no meio", b[2] == 1080 and abs(b[3] - 607) <= 2 and abs(b[1] + b[3] / 2 - 960) <= 1, b)
check("react no meio", abs((react.SCREEN_TOP + react.SEAM + react.CAM_H) / 2 - 960) <= 2, (react.SCREEN_TOP, react.SEAM + react.CAM_H))

print("\n" + ("TUDO OK" if not fails else "FALHAS: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
