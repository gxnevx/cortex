"""Ranking de clipes: filtro, escolha, ajuste dos trechos, montagem e fila. Sem internet e sem Claude.

Roda:  .venv\\Scripts\\python.exe tests\\ranking_unit.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fabrica import paths  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="cortex_rk_"))
paths.DB_PATH = TMP / "t.db"
paths.STATE = TMP
paths.TMP = TMP / "tmp"
paths.RENDERS = TMP / "renders"
from fabrica import autopilot, db, exclusivas, metrics, pipeline, ranking, revisao, tools, uso_ia  # noqa: E402
from fabrica.config import Config  # noqa: E402
from fabrica.editor import ranking as montagem  # noqa: E402
from fabrica.models import ClipPlan, PostResult, RenderedClip  # noqa: E402
from fabrica.publish import captions  # noqa: E402

ranking.STATE = TMP / "ranking.json"
metrics._conn()
revisao.STATE = TMP / "revisoes.json"
uso_ia._FILE = TMP / "uso.json"
fails: list[str] = []


def check(name: str, cond: bool, extra: object = "") -> None:
    print(("ok    " if cond else "FALHA ") + name + (f"  [{extra}]" if extra and not cond else ""))
    if not cond:
        fails.append(name)


cfg = Config({"busca": {"canais_bloqueados": ["canalproibido"]}, "ranking": {"views_min": 800, "nota_minima": 65, "hora": 8, "tentativas_dia": 2},
              "cerebro": {"claude_max_chamadas_dia": 60}, "publicacao": {"plataformas": ["youtube", "tiktok", "instagram"], "redes_exclusivas": ["instagram"],
              "repetir_sem_exclusivo": True, "contas": {"youtube": {"handle": "@y"}, "tiktok": {"handle": "@t"}, "instagram": {"handle": "@t"}}},
              "edicao": {"encoder": "libx264", "qualidade": "rapida", "logo_marca_dagua": ""}})
AGORA = time.time()


def cl(i: int, views: int = 5000, login: str | None = None, titulo: str = "olha isso", **kw) -> dict:
    return {"id": f"c{i}", "url": f"https://www.twitch.tv/x/clip/c{i}", "titulo": titulo, "onde": "Twitch", "views": views, "dur": 20.0, "ts": AGORA - 3600 * (i + 1),
            "login": login or f"canal{i}", "nome": login or f"Canal{i}", "bio": "", "jogo": "Grand Theft Auto VI", **kw}


# ------------------------------------------------------------------ filtro
d: dict = {}
check("clipe normal serve", ranking._serve(cl(1), cfg, d))
check("pouca view nao serve", not ranking._serve(cl(1, 500), cfg, d))
check("velho nao serve", not ranking._serve({**cl(1), "ts": AGORA - 9 * 86400}, cfg, d))
check("sem data nao serve", not ranking._serve({**cl(1), "ts": 0}, cfg, d))
check("titulo sexual nao serve", not any(ranking._serve(cl(1, titulo=t), cfg, d) for t in ("QUER LEITINHO?", "secsu", "NUDE no gta", "sorteio", "+18")))
check("titulo comum passa", all(ranking._serve(cl(1, titulo=t), cfg, d) for t in ("N PODE SOCAR QUEM?", "passou aqui", "ANALISE", "kkkkk")))
check("canal bloqueado pelo dono nunca entra", not ranking._serve(cl(1, login="alanzoka"), cfg, d))
check("canal bloqueado na config nunca entra", not ranking._serve(cl(1, login="canalproibido"), cfg, d))
check("canal que nao autoriza corte nao entra", not ranking._serve(cl(1, bio="Não autorizo o uso dos meus vídeos em outro canal."), cfg, d))
check("ja usado ou recusado nao volta", not ranking._serve(cl(1), cfg, {"usados": {"c1": AGORA}}) and not ranking._serve(cl(1), cfg, {"recusados": {"c1": [AGORA, "x"]}}))
u = ranking._unicos([cl(1, 100, "a"), {**cl(2, 900, "a"), "ts": AGORA - 7200 - 30}, cl(3, 50, "b")])
check("mesmo momento clipado duas vezes: fica o mais visto", [x["id"] for x in u] == ["c2", "c3"], [x["id"] for x in u])
ts = ranking.temas(cfg, [cl(i) for i in range(8)] + [{**cl(20 + i, 900), "jogo": "Minecraft"} for i in range(3)])
check("lista por assunto, o mais visto na frente", [(t["tema"], len(t["clipes"])) for t in ts] == [("GTA 6", 8), ("MINECRAFT", 3)], ts and [t["tema"] for t in ts])
ranking._grava({"recusados": {"z1": [AGORA, "proibido: nudez", "canal3"], "z2": [AGORA, "proibido: sexo", "canal3"], "z3": [AGORA, "nota 40", "canal4"], "z4": [AGORA, "nota 40", "canal4"]}})
ids = [c["id"] for c in ranking.candidatos(cfg, [cl(i) for i in range(6)])]
check("canal com 2 proibidos na semana fica de fora, nota baixa nao conta", "c3" not in ids and "c4" in ids, ids)
ranking._grava({"bons": [{**cl(2), "nota": 80}]})
check("aprovado guardado nao e olhado de novo", "c2" not in [c["id"] for c in ranking.candidatos(cfg, [cl(i) for i in range(4)])])
ranking._grava({"bons": [{**cl(2), "ts": AGORA - 8 * 86400}, cl(3)], "usados": {"c3": AGORA}})
check("aprovado velho ou ja usado sai da reserva", ranking._mem()["bons"] == [])
ranking._grava({})
check("fala sexual ou de aposta derruba antes do Claude", all(ranking.FORA_FALA.search(t) for t in ("olha a piroca dele", "faz o pix", "ele tá pelado")) and not ranking.FORA_FALA.search("caiu no pau da barraca, que pinta boa"))
lt: list = []
misto = [cl(i, 9000 - i) for i in range(20)] + [{**cl(40 + i, 500 - i), "jogo": "Minecraft"} for i in range(6)]
vs: set = set()
while len(lt) < ranking.LOTE:
    c_ = ranking._proximo(misto, vs, lt, [])
    vs.add(c_["id"])
    lt.append(c_)
check("um assunto nao toma o lote inteiro", sum(c["jogo"] == "Minecraft" for c in lt) == 3, [c["jogo"] for c in lt])
check("no maximo 3 do mesmo canal por lote", ranking._proximo([cl(9, login="a")], set(), [cl(i, login="a") for i in range(3)], []) is None)

# ------------------------------------------------------------------ trecho
W = [(1.0, 1.4, "Olha"), (1.4, 1.9, "isso"), (2.0, 2.6, "aqui."), (5.0, 5.5, "Meu"), (5.5, 6.2, "Deus"), (6.3, 6.9, "caiu"), (6.9, 7.4, "tudo."), (9.0, 9.5, "Nossa.")]
a = ranking.ajustar(1.2, 6.5, W, 20.0)
check("nao comeca no meio da palavra e fecha a frase", a is not None and 0.9 <= a[0] < 1.0 and 7.4 < a[1] < 8.0, a)
a = ranking.ajustar(0.0, 19.0, W, 20.0)
check("trecho longo demais: guarda o desfecho", a is not None and a[1] - a[0] <= ranking.MAX_S + 0.01 and a[1] == 19.0, a)
a = ranking.ajustar(6.9, 7.4, W, 20.0)
check("trecho curto abre antes", a is not None and a[1] - a[0] >= ranking.MIN_S and a[1] > 7.4, a)
check("clipe menor que o minimo nao serve", ranking.ajustar(0.0, 3.0, [], 3.0) is None)
check("sem fala nenhuma vale o pedido", ranking.ajustar(2.0, 9.0, [], 20.0) == (2.0, 9.0))
check("nome na tela", ranking.nome_ok("Acabou a vibe!") == "ACABOU A VIBE" and ranking.nome_ok("kkkk") == "" and ranking.nome_ok("Momento engraçado") == ""
      and ranking.nome_ok("a") == "" and ranking.nome_ok("Quer leitinho") == "" and ranking.nome_ok("nome comprido demais para a tela") == "")

# ------------------------------------------------------------------ julgamento
itens = [{**cl(i, 1000 * (10 - i)), "words": [], "segs": [], "arquivo": "x"} for i in range(7)]
dec = {i + 1: {"i": i + 1, "proibido": "", "nota": 70 + i, "inicio": 2, "fim": 9, "nome": f"Nome numero {i}", "legendado": False} for i in range(7)}
dec[2]["proibido"], dec[3]["nota"], dec[4]["nome"] = "nudez", 40, "kkk"
bons, fora = ranking.avaliar(itens, dec, cfg)
check("proibido, nota baixa e sem nome ficam fora", [b["id"] for b in bons] == ["c0", "c4", "c5", "c6"] and len(fora) == 3, [b["id"] for b in bons])
check("com menos de 5 bons nao ha ranking", ranking.escolher(bons) is None)
dec[2]["proibido"], dec[3]["nota"], dec[4]["nome"] = "", 71, "Caiu a ponte"
bons, _ = ranking.avaliar(itens, dec, cfg)
esc = ranking.escolher(bons) or []
check("posicao e pelas views", [c["pos"] for c in esc] == [1, 2, 3, 4, 5] and all(x["views"] >= y["views"] for x, y in zip(esc, esc[1:])))
check("no maximo 2 do mesmo canal", ranking.escolher([{**b, "login": "um"} for b in bons]) is None)
check("sem resposta do Claude sobre um clipe ele nao entra nem e recusado", ranking.avaliar(itens[:1], {}, cfg) == ([], []))
f5 = [{**b, "jogo": "Minecraft"} if i < 2 else b for i, b in enumerate(bons)]
check("um jogo com 5 bons vira o assunto", (ranking.fechar(bons, False) or ("",))[0] == "GTA 6")
check("sem 5 do mesmo jogo so fecha misturando", ranking.fechar(f5[:6], False) is None and (ranking.fechar(f5[:6], True) or ("",))[0] == "LIVE")
check("com 4 nao fecha nem misturando", ranking.fechar(f5[:4], True) is None)
seq = [c["pos"] for c in ranking.ordem(esc)]
check("o 1º lugar e o ultimo e o 2º fica no meio", seq[-1] == 1 and seq[1] == 2 and sorted(seq) == [1, 2, 3, 4, 5], seq)

# ------------------------------------------------------------------ quando
hoje9 = datetime.now().replace(hour=9, minute=0)
ranking._grava({})
check("de madrugada nao faz", not ranking.na_hora(cfg, hoje9.replace(hour=6)))
check("de manha faz", ranking.na_hora(cfg, hoje9))
ranking._grava({"feitos": [{"dia": hoje9.date().isoformat(), "tema": "GTA 6", "id": "x"}]})
check("no maximo 1 por dia", not ranking.na_hora(cfg, hoje9.replace(hour=20)))
check("no dia seguinte faz de novo", ranking.na_hora(cfg, hoje9 + timedelta(days=1)))
p0, ranking.placar = ranking.placar, lambda: {"youtube": {"n": 8, "n_normal": 9, "views": 5, "normal": 100, "razao": 0.06}}
check("rende bem menos que o normal: 1 a cada 3 dias", not ranking.na_hora(cfg, hoje9 + timedelta(days=1)) and ranking.na_hora(cfg, hoje9 + timedelta(days=3)))
ranking.placar = p0
ranking._grava({"tentativas": [hoje9.timestamp()]})
check("tentou agora ha pouco: espera 4 h", not ranking.na_hora(cfg, hoje9.replace(hour=11)) and ranking.na_hora(cfg, hoje9.replace(hour=14)))
ranking._grava({"tentativas": [hoje9.timestamp(), hoje9.replace(hour=14).timestamp()]})
check("no maximo 2 tentativas no dia", not ranking.na_hora(cfg, hoje9.replace(hour=22)))
ranking._grava({})
check("desligado na config", not ranking.na_hora(Config({"ranking": {"ativo": False}}), hoje9))
uso_ia.registrar("claude")
h0, uso_ia.hoje = uso_ia.hoje, lambda m: 58
check("sem cota do Claude espera", not ranking.na_hora(cfg, hoje9))
uso_ia.hoje = h0

# ------------------------------------------------------------------ montagem de verdade (videos sinteticos)
ff = tools.ffmpeg()
fontes = []
for i, (cor, tam) in enumerate([("red", "1280x720"), ("green", "1280x720"), ("blue", "1280x960"), ("white", "640x360"), ("gray", "1280x720")]):
    f = TMP / f"src{i}.mp4"
    cm = {0: "bt709", 1: "smpte170m", 2: "bt470bg"}.get(i)       # cada clipe da vida real vem com uma matriz de cor
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", f"color={cor}:s={tam}:r=60:d=12", "-f", "lavfi", "-i", "sine=f=300:d=12", "-c:v", "libx264",
                    *(["-colorspace", cm, "-color_primaries", cm, "-color_trc", cm] if cm else []),
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(f)], check=True)
    fontes.append(f)
its = [{**cl(i, 1000 * (9 - i) + 317), "pos": i + 1, "arquivo": str(fontes[i]), "ini": 1.0, "fim": 6.0 + 0.1 * i, "nome_tela": f"MOMENTO NUMERO {i + 1}", "nota": 70 + i,
        "legendado": i % 2 == 0, "words": [(1.2, 1.6, "isso"), (1.7, 2.1, "caiu")], "segs": []} for i in range(5)]
plano, video = ranking._plano("GTA 6", its, "20261125-140000")
check("titulo sem promessa falsa", "GTA 6" in plano.title and plano.tipo == "ranking" and "mais vist" not in plano.title.lower(), plano.title)
check("credita todo mundo", all(f"Canal{i}" in video.channel for i in range(5)) and "Twitch" in video.channel, video.channel)
rc = montagem.render(ranking.ordem(its), "GTA 6", plano, cfg, paths.RENDERS / f"{plano.id}.mp4")
plano.end = rc.duration
check("duas versoes, duracao certa", set(rc.variants) == {"youtube", "tiktok"} and abs(rc.duration - sum(c["fim"] - c["ini"] for c in its)) < 0.1, rc.duration)
check("itens guardados na ordem em que aparecem", [x["pos"] for x in plano.itens][-1] == 1 and plano.itens[0]["t0"] == 0 and abs(plano.itens[-1]["t1"] - rc.duration) < 0.05)
check("legenda so nos que nao vieram legendados", len(montagem.legendas(ranking.ordem(its)).segments) == 2)
leg = montagem.legendas(ranking.ordem(its)).segments[0]
check("legenda no tempo do video final", any(x["t0"] <= leg.start <= x["t1"] and abs(leg.start - x["t0"] - 0.2) < 0.05 for x in plano.itens), leg.start)


def quadro(t: float):
    import numpy as np

    r = subprocess.run([ff, "-v", "error", "-ss", f"{t}", "-i", rc.path, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    return np.frombuffer(r.stdout, np.uint8).reshape(1920, 1080, 3).astype(int)


amarelos: list = []
for x in plano.itens:
    q = quadro((x["t0"] + x["t1"]) / 2)
    i = x["pos"] - 1
    if i in (0, 1, 2):      # cor viva: acha a faixa do video e confere o centro
        canal = {0: 0, 1: 1, 2: 2}[i]
        col = q[:, 540, canal]
        faixa = [y for y in range(640, 1290) if col[y] > col[640:1290].max() * 0.9]
        meio = (faixa[0] + faixa[-1]) / 2
        check(f"video do {x['pos']}º exatamente no centro", abs(meio - 959.5) <= 2, meio)
    y = montagem.LISTA_Y + i * montagem.LINHA + montagem.LINHA // 2
    pix = q[y, 1007].tolist()
    amarelos.append(pix)
    check(f"linha do {x['pos']}º marcada em amarelo", pix[0] > 200 and pix[1] > 180 and pix[2] < 90, pix)
check("o amarelo e o mesmo em todos os momentos", all(abs(p[k] - amarelos[0][k]) <= 12 for p in amarelos for k in range(3)), amarelos)
for rede, arr in (("youtube", "@y"), ("tiktok", "@canal.bem.mais.comprido")):
    from PIL import Image as _I

    lg = TMP / "lg.png"
    _I.new("RGBA", (100, 60), (255, 255, 255, 255)).save(lg)
    hd = _I.new("RGBA", (40 + 14 * len(arr), 50), (0, 0, 0, 0))
    hd.paste((255, 255, 255, 255), (12, 10, 28 + 14 * len(arr), 40))
    hd.save(TMP / "hd.png")
    from fabrica.editor.overlays import Brand

    m_ = _I.open(montagem._marca(Brand(lg, (100, 60), {rede: (TMP / "hd.png", hd.width, hd.height, 20)}), rede, TMP))
    bb = m_.getchannel("A").getbbox()
    check(f"marca do {rede} sem sobra de um lado", bb[0] == 0 and m_.width - bb[2] <= 1 and m_.width % 2 == 0, (bb, m_.size))
pretos = subprocess.run([ff, "-hide_banner", "-i", rc.path, "-vf", "blackdetect=d=0.06:pix_th=0.05", "-f", "null", "-"], capture_output=True, text=True).stderr
check("sem tela preta entre os momentos", "black_start" not in pretos)
check("views sem arredondar para cima", [montagem.views_txt(v) for v in (982, 3317, 2670, 10137, 1000, 31999, 156000, 2_350_000)] ==
      ["982", "3,3 mil", "2,6 mil", "10,1 mil", "1 mil", "31,9 mil", "156 mil", "2,3 mi"], [montagem.views_txt(v) for v in (982, 3317, 2670, 10137, 1000, 31999, 156000, 2_350_000)])

# ------------------------------------------------------------------ fila, revisao e post
db.upsert_video(video, status="processado")
db.save_plan(plano, "run")
db.save_rendered(rc)
db.conn().execute("UPDATE clips SET status='aprovado', curador='ranking' WHERE id=?", (plano.id,))
db.conn().commit()
outro = ClipPlan(id="normal", source_id="s", start=0, end=40, title="Corte normal", score=99.0)
f = TMP / "n.mp4"
f.write_bytes(b"x")
normal = RenderedClip(plan=outro, path=str(f), duration=40, layout="full")
fila = autopilot.queue(cfg)
check("ranking entra na fila com os itens", [c.plan.id for c in fila] == [plano.id] and len(fila[0].plan.itens) == 5)
check("ranking na frente da fila", [c.plan.id for c in pipeline.publish_order([normal, rc])] == [plano.id, "normal"])
check("Instagram nao tira o ranking das outras", exclusivas.candidatos("instagram", cfg, [rc, normal], guardar=0)[0].plan.id == "normal"
      and all(c.plan.id != plano.id for c in exclusivas.candidatos("instagram", cfg, [rc, normal], guardar=0)))
db.save_post(PostResult(plano.id, "youtube", True, url="u", ts=time.time()))
check("depois que saiu, o Instagram pode repetir", [c.plan.id for c in exclusivas.candidatos("instagram", cfg, [rc], guardar=0)] == [plano.id])
check("regras da revisao aceitam ranking com pouca fala", revisao.regras(rc, "isso caiu") is None, revisao.regras(rc, "isso caiu"))
pr = revisao._prompt(rc, "x")
check("revisao do ranking mostra cada momento", "RANKING" in pr and all(x["nome"] in pr for x in plano.itens) and '{"entende_sozinho":0' in pr)
img = revisao.folha(rc)
check("revisao olha 10 quadros", img is not None and img.stat().st_size > 5000)
from PIL import Image  # noqa: E402

check("folha 5 x 2 com todos os quadros", img is not None and Image.open(img).size[0] > 1500 and min(Image.open(img).convert("L").resize((5, 2)).tobytes()) > 8,
      img and list(Image.open(img).convert("L").resize((5, 2)).tobytes()))
for rede in ("youtube", "tiktok", "instagram"):
    t, texto = captions.build_post_text(plano, rede, cfg, video_title=video.title, channel=video.channel)
    check(f"{rede}: texto com credito, lista e pergunta", "Fonte: Canal" in texto and "Momento numero 1" in texto and any(q in texto for q in ranking.PERGUNTAS)
          and 'Fonte: ' in texto and '""' not in texto, texto)
db.conn().execute("UPDATE clips SET created=? WHERE id=?", (time.time() - 73 * 3600, plano.id))
check("ranking da semana vence em 3 dias", ranking.vencer() == 1 and db.conn().execute("SELECT status FROM clips WHERE id=?", (plano.id,)).fetchone()[0] == "publicado")

# ------------------------------------------------------------------ producao inteira com Claude e internet de mentira
ranking._grava({})
clipes = [cl(i, 9000 - 100 * i) for i in range(12)]
ranking.listar = lambda c: clipes
ranking.preparar = lambda c, pasta, cf, i: {**c, "arquivo": str(fontes[i % 5]), "dur": 12.0, "folha": "x", "segs": [], "words": [(2.0, 2.4, "caiu.")]}
ranking.conferir = lambda itens, pasta, cf: {i + 1: {"i": i + 1, "ok": True, "nome": c["nome_tela"]} for i, c in enumerate(itens)}
ranking.triar = lambda cs, pasta, cf: None
ranking._baixa = lambda c, pasta, cf: fontes[0] if c["id"] != "sumiu" else None
pedidos: list[int] = []


def julga(tema, lote, cf):
    pedidos.append(len(lote))
    return {i + 1: {"i": i + 1, "proibido": "" if i % 2 or len(pedidos) > 1 else "nudez", "nota": 80, "inicio": 1, "fim": 7, "nome": f"Queda {c['id']}", "legendado": True} for i, c in enumerate(lote)}


ranking.julgar = julga
from fabrica import ui  # noqa: E402

r = ranking.produzir(cfg, ui.Reporter(quiet=True))
check("producao: 5 bons em 10 olhados, 1 chamada do Claude", r["ok"] and pedidos == [10] and len(r["itens"]) == 5, r)
m = ranking._mem()
check("guarda usados, recusados e o feito do dia", len(m["usados"]) == 5 and len(m["recusados"]) == 5 and m["feitos"][0]["id"] == r["id"] and m["bons"] == [])
check("esta aprovado e na fila", [c.plan.id for c in autopilot.queue(cfg)] == [r["id"]] and not ranking.na_hora(cfg, datetime.now().replace(hour=23)))
ranking._grava({})
ranking.julgar = lambda *a: None
r = ranking.produzir(cfg, ui.Reporter(quiet=True))
check("sem Claude nao sai nada", not r["ok"] and "Claude" in r["motivo"] and not ranking._mem().get("feitos"), r)
ranking.julgar = lambda tema, lote, cf: {i + 1: {"i": i + 1, "proibido": "nudez", "nota": 80, "inicio": 1, "fim": 7, "nome": "Queda livre"} for i in range(len(lote))}
ranking._grava({})
r = ranking.produzir(cfg, ui.Reporter(quiet=True))
check("sem 5 bons nao sai nada", not r["ok"] and "0 clipe" in r["motivo"], r)
# 3 aprovados numa tentativa e 2 na outra: fecha 5 sem olhar de novo os primeiros
ranking._grava({})
ranking.julgar = lambda tema, lote, cf: {i + 1: {"i": i + 1, "proibido": "", "nota": 80 if c["id"] in ("c0", "c1", "c2") else 20, "inicio": 1, "fim": 7, "nome": f"Queda {c['id']}"} for i, c in enumerate(lote)}
r = ranking.produzir(Config({**cfg.data, "ranking": {**cfg.data["ranking"], "consultas": 1}}), ui.Reporter(quiet=True))
m = ranking._mem()
check("3 bons ficam guardados, sem arquivo pesado", not r["ok"] and sorted(b["id"] for b in m["bons"]) == ["c0", "c1", "c2"] and not any("arquivo" in b or "folha" in b for b in m["bons"]), r)
m["bons"].append({**m["bons"][0], "id": "sumiu", "login": "outro", "nome_tela": "SUMIU DA TWITCH", "nota": 99})
ranking._grava(m)
db.conn().execute("DELETE FROM clips")
db.conn().commit()
ranking.julgar = lambda tema, lote, cf: {i + 1: {"i": i + 1, "proibido": "", "nota": 75, "inicio": 1, "fim": 7, "nome": f"Queda {c['id']}"} for i, c in enumerate(lote)}
r = ranking.produzir(cfg, ui.Reporter(quiet=True))
check("na outra tentativa fecha com os guardados; clipe apagado na Twitch sai", r["ok"] and "SUMIU DA TWITCH" not in [x["nome"] for x in r["itens"]]
      and len({"QUEDA C0", "QUEDA C1", "QUEDA C2"} & {x["nome"] for x in r["itens"]}) == 3, r.get("itens") or r)
# conferencia: pedaco que nao mostra o que o nome diz sai, o nome errado e trocado
ranking._grava({})
ranking.conferir = lambda itens, pasta, cf: {i + 1: {"i": i + 1, "ok": c["id"] != "c1", "nome": "Nome certo" if c["id"] == "c0" else c["nome_tela"], "motivo": "corredor vazio"} for i, c in enumerate(itens)}
db.conn().execute("DELETE FROM clips")
db.conn().commit()
r = ranking.produzir(cfg, ui.Reporter(quiet=True))
nomes = [x["nome"] for x in r.get("itens") or []]
check("pedaco reprovado na conferencia sai e o nome e corrigido", r["ok"] and "QUEDA C1" not in nomes and "NOME CERTO" in nomes and "c1" in ranking._mem()["recusados"], nomes)
ranking._grava({})
ranking.conferir = lambda *a: None
r = ranking.produzir(cfg, ui.Reporter(quiet=True))
check("sem a conferencia nao monta, mas guarda os aprovados", not r["ok"] and "conferir" in r["motivo"] and len(ranking._mem()["bons"]) >= 5, r)
# triagem: capa ruim nem e baixada
ranking._grava({})
muitos = [cl(i, 9000 - 10 * i) for i in range(30)]
ranking.listar = lambda c: muitos
ranking.triar = lambda cs, pasta, cf: {c["id"]: (90 if c["id"] in ("c25", "c26") else 10 if int(c["id"][1:]) < 10 else 50) for c in cs}
olhados: list[str] = []
prep0 = ranking.preparar
ranking.preparar = lambda c, pasta, cf, i: olhados.append(c["id"]) or prep0(c, pasta, cf, i)
ranking.julgar = lambda tema, lote, cf: {i + 1: {"i": i + 1, "proibido": "", "nota": 10, "inicio": 1, "fim": 7, "nome": "Queda livre"} for i in range(len(lote))}
ranking.produzir(cfg, ui.Reporter(quiet=True))
check("capa boa primeiro, capa ruim nunca", olhados[:2] == ["c25", "c26"] and not any(f"c{i}" in olhados for i in range(10)), olhados)

print(f"\n{'TUDO CERTO' if not fails else str(len(fails)) + ' FALHA(S): ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
