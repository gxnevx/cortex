"""Escolha dos videos pelo Claude, cota por parte do dia e idade por assunto. Sem internet e sem chamar a IA.

Roda:  .venv\\Scripts\\python.exe tests\\escolha_unit.py
"""
from __future__ import annotations

import json
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

paths.STATE = Path(tempfile.mkdtemp(prefix="cortex_es_"))
from fabrica import brain, escolha, uso_ia  # noqa: E402
from fabrica.config import Config  # noqa: E402
from fabrica.discovery import candidates  # noqa: E402
from fabrica.models import Candidate  # noqa: E402

uso_ia._FILE = paths.STATE / "uso_ia.json"
fails: list[str] = []


def check(name: str, cond: bool, extra: object = "") -> None:
    print(("ok    " if cond else "FALHA ") + name + (f"  [{extra}]" if extra and not cond else ""))
    if not cond:
        fails.append(name)


class Raw:
    def __init__(self, cat: str | None):
        self.category, self.topics = cat, {}


def cand(i: int, titulo: str, canal: str, score: float, cat: str | None = None):
    c = Candidate(id=f"youtube:v{i}", platform="youtube", url="", title=titulo, channel=canal, channel_url=None, duration=3600.0, views=50000,
                  upload_ts=time.time() - 7200, is_live=False, was_live=False, thumbnail=None, description="", topic=None, extra={})
    c.score = score
    return c, Raw(cat)


class Falso:
    name = "claude"
    resposta: object = {}
    pedidos: list = []

    def _run(self, p, s, **k):
        Falso.pedidos.append(p)
        if isinstance(Falso.resposta, Exception):
            raise Falso.resposta
        return json.dumps(Falso.resposta)


class SemClaude:
    name = "ollama"


cfg = Config({"cerebro": {"claude_max_chamadas_dia": 40}, "busca": {"janela_horas": 48, "janela_horas_nicho": {"podcast": 120, "humor": 120, "viral": 100}}})
escolha.historico_canais = lambda: {"Canal 3": (2, 1), "Canal 4": (0, 5), "Canal 5": (0, 2)}
pre = [cand(i, f"Conversa numero {i}", f"Canal {i}", 90 - i, "podcast") for i in range(20)] + [cand(50 + i, f"Votação {i}", f"Jornal {i}", 99, "politica") for i in range(20)]
pre.sort(key=lambda x: -x[0].score)
li = escolha.lista(pre)
check("lista: no maximo 6 de politica", sum(r.category == "politica" for _, r in li) == 6, [r.category for _, r in li])
mesmo = [cand(i, f"t {i}", "Igual", 50, "humor") for i in range(6)]
check("lista: no maximo 2 por canal", len(escolha.lista(mesmo)) == 2)

gta = [cand(i, f"GTA 6 momento {i}", f"C{i}", 99, "games") for i in range(30)]
casa = [cand(100 + i, f"Papo {i}", f"P{i}", 20, "podcast") for i in range(4)]
for _, r in casa:
    r.big_channel = True
li = escolha.lista(gta + casa)
check("lista: um assunto nao toma tudo, e canal acompanhado entra mesmo com numero menor", sum(r.category == "games" for _, r in li) == 5 and sum(r.category == "podcast" for _, r in li) == 4,
      [c.title for c, _ in li])

brain.get_brain = lambda *a, **k: Falso()
Falso.resposta = {"videos": [{"n": 12, "nota": 70, "motivo": "boa"}, {"n": 10, "nota": 88, "motivo": "otima"}, {"n": 10, "nota": 90}, {"n": 1, "nota": 40},
                             {"n": 999, "nota": 90}, {"n": "x", "nota": 90}, {"n": 11, "nota": 61}]}
out = escolha.escolher(pre, cfg)
check("escolhidos em ordem de nota, sem repetir, sem numero errado, sem nota baixa", [c.extra["ia_nota"] for c, _ in out] == [88, 70, 61], [c.extra for c, _ in out])
p = Falso.pedidos[-1]
check("conta para o Claude o que cada canal ja rendeu", "Canal 3 (2 de 3)" in p and "Canal 4 (0 de 5)" in p and "Canal 5 (0" not in p, p[:600])
c = out[0][0]
c.score = 60
check("nota final pesa mais a escolha", abs(escolha.nota_final(c) - (0.35 * 60 + 0.65 * 88)) < 0.1)
check("sem escolha, nota dos numeros", escolha.nota_final(cand(1, "a", "b", 33)[0]) == 33)
Falso.resposta = RuntimeError("caiu")
check("sem resposta: segue como antes", escolha.escolher(pre, cfg) is None)
Falso.resposta = {"videos": [{"n": 1, "nota": 90}]}
check("so 1 escolhido: segue como antes", escolha.escolher(pre, cfg) is None)
brain.get_brain = lambda *a, **k: SemClaude()
check("sem Claude: segue como antes", escolha.escolher(pre, cfg) is None)

# ------------------------------------------------------------------ via rapida
brain.get_brain = lambda *a, **k: Falso()
Falso.resposta = {"videos": [{"n": 1, "nota": 82}, {"n": 2, "nota": 60}]}
rap = [cand(1, "Câmara vota ajuste fiscal no senado", "Jornal", 90)[0], cand(2, "Humorista conta a pior noite da vida", "Canal A", 80)[0], cand(3, "Streamer surta", "Canal B", 70)[0]]
rap[0].extra["categoria_canal"] = "politica"
r = escolha.rapida(rap, cfg)
check("via rapida: sem jornal e so o que tem nota alta", [x.id for x in r] == ["youtube:v2"], [x.id for x in r])
n = len(Falso.pedidos)
check("via rapida so com politica: nem chama o Claude", escolha.rapida(rap[:1], cfg) == [] and len(Falso.pedidos) == n)
brain.get_brain = lambda *a, **k: SemClaude()
check("via rapida sem Claude: espera", escolha.rapida(rap, cfg) == [])

# ------------------------------------------------------------------ cota por parte do dia
def usar(n: int) -> None:
    uso_ia._FILE.write_text(json.dumps({"dia": uso_ia.date.today().isoformat(), "hoje": {"claude": {"chamadas": n, "segundos": 0, "tarefas": {}}}, "total": {}}), encoding="utf-8")


check("cota cresce ao longo do dia", [uso_ia.liberado(cfg, h) for h in (3, 9, 15, 20)] == [20, 24, 28, 40], [uso_ia.liberado(cfg, h) for h in (3, 9, 15, 20)])
real = uso_ia.liberado
uso_ia.liberado = lambda c, hora=None: 16
usar(16)
check("de madrugada para de produzir", not uso_ia.pode_claude(cfg, "clips") and not uso_ia.pode_claude(cfg, "escolha"))
check("mas julga e revisa o que ja tem", all(uso_ia.pode_claude(cfg, t) for t in ("bordas", "fino", "curadoria", "revisao", "analise")))
usar(15)
check("antes do limite, produz", uso_ia.pode_claude(cfg, "clips"))
uso_ia.liberado = lambda c, hora=None: 40
usar(28)
check("guarda cota para julgar no fim do dia", not uso_ia.pode_claude(cfg, "clips") and uso_ia.pode_claude(cfg, "fino") and uso_ia.pode_claude(cfg, "revisao"))
usar(39)
check("ultima chamada e da analise", not uso_ia.pode_claude(cfg, "revisao") and uso_ia.pode_claude(cfg, "analise"))
usar(40)
check("teto do dia vale para tudo", not uso_ia.pode_claude(cfg, "analise"))
uso_ia.liberado = real

# ------------------------------------------------------------------ idade do video por assunto
check("noticia 48 h, podcast e humor mais", (candidates.janela_h(cfg, "noticias"), candidates.janela_h(cfg, "podcast"), candidates.janela_h(cfg, "entretenimento")) == (48, 120, 120))
check("viral da semana", candidates.janela_h(cfg, None, True) == 100 and candidates.janela_h(cfg, None) == 48)

# ------------------------------------------------------------------ video longo rende mais candidatos por chamada
from fabrica.brain import prompts  # noqa: E402

check("candidatos: curto a IA decide, longo pede varios", (prompts.candidatos(32, 5), prompts.candidatos(59, 6), prompts.candidatos(203, 10), prompts.candidatos(203, 3)) == (None, (3, 6), (5, 8), None),
      (prompts.candidatos(32, 5), prompts.candidatos(59, 6), prompts.candidatos(203, 10)))
longo, curto = cand(1, "Podcast", "C", 50)[0], cand(2, "Esquete", "C", 50)[0]
longo.duration, curto.duration = 203 * 60, 12 * 60
pl, pc = (prompts.clips_prompt(x, "[00:01] teste", "", Config({}), n) for x, n in ((longo, 10), (curto, 3)))
check("pedido do video longo e do curto", "De 5 a 8 candidatos" in pl and "De 5 a 8" not in pc and "no máximo 3" in pc)

# ------------------------------------------------------------------ abertura: frase inteira que se entende sozinha, ou nada (caso real de 24/11)
from fabrica import pipeline  # noqa: E402
from fabrica.models import ClipPlan, Segment, Transcript, Word  # noqa: E402


def legenda(*partes: tuple[float, str]) -> Transcript:
    """Cada parte comeca no segundo dado, 0,3 s por palavra."""
    out = []
    for t0, txt in partes:
        ws = [Word(t0 + k * 0.3, t0 + k * 0.3 + 0.28, w) for k, w in enumerate(txt.split())]
        out.append(Segment(ws[0].start, ws[-1].end, txt, ws))
    return Transcript(out, "pt", "whisper")


def abre(leg: Transcript, a: float, b: float) -> str:
    return (pipeline.gancho_inteiro(leg, a, b) or {}).get("text", "")


fome = legenda((0, "Ninguém conseguia me cuidar"), (2, "Às vezes eu passo fome em casa"), (6, "porque meu tio voltava antes"),
               (8, "Ele é um pouco mais vagabundo"), (9.9, "Ele volta antes"), (12, "Tio, eu vou morrer."), (14, "Com 5 anos, sozinho em casa, mano?"))
check("abertura: frase solta com 'ele' nao abre", abre(fome, 8.0, 10.5) == "", abre(fome, 8.0, 10.5))
check("abertura: frase inteira abre", abre(fome, 12.0, 13.1) == "Tio, eu vou morrer.", abre(fome, 12.0, 13.1))
check("abertura: pedaco vira a frase inteira", abre(fome, 14.3, 15.7) == "Com 5 anos, sozinho em casa, mano?", abre(fome, 14.3, 15.7))
longa = legenda((0, "começo qualquer do assunto."), (5, "engenharia é o seguinte, mano. É uma coisa que ninguém nunca entendeu direito desde o começo da faculdade"))
check("abertura: nao leva o comeco da frase seguinte", abre(longa, 5.0, 6.8) == "engenharia é o seguinte, mano.", abre(longa, 5.0, 6.8))
check("abertura: pedaco de frase longa nao abre", abre(longa, 8.0, 10.0) == "", abre(longa, 8.0, 10.0))
corta = legenda((0, "começo do assunto aqui."), (5, "Peguei uma nova."), (6.1, "A nova ela vem..."), (9, "Não, pelo amor de Deus."))
check("abertura: frase que fica no ar nao fecha", abre(corta, 5.0, 7.3) in ("", "Peguei uma nova."), abre(corta, 5.0, 7.3))
cfg0 = Config({"edicao": {"cold_open": True}})
pl0 = ClipPlan(id="fome", source_id="s", start=100, end=118, title="Aos 5 anos ficou sozinho em casa e passava fome", teaser_start=108.0, teaser_end=110.4,
               teaser_text="Ele é um pouco mais vagabundo", tipo="fala")
pipeline.refine_with_captions(pl0, fome, cfg0)
check("abertura: sugestao solta nao vai para o video", "vagabundo" not in pl0.teaser_text, pl0.teaser_text)
pl1 = ClipPlan(id="fome2", source_id="s", start=100, end=118, title="Aos 5 anos ficou sozinho em casa e passava fome", teaser_start=112.0, teaser_end=113.2,
               teaser_text="Tio, eu vou morrer", tipo="fala")
pipeline.refine_with_captions(pl1, fome, cfg0)
check("abertura: sugestao boa continua abrindo", pl1.teaser_text == "Tio, eu vou morrer." and abs(pl1.teaser_start - 112.0) < 0.1, (pl1.teaser_text, pl1.teaser_start))
pl2 = ClipPlan(id="fome3", source_id="s", start=100, end=118, title="Reage ao caso", teaser_start=108.0, teaser_end=110.4, teaser_text="Ele é um pouco mais vagabundo", tipo="reacao")
pipeline.refine_with_captions(pl2, fome, cfg0)
check("abertura: em react a sugestao solta tambem cai", "vagabundo" not in pl2.teaser_text, pl2.teaser_text)

print("\n" + ("TUDO OK" if not fails else "FALHAS: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
