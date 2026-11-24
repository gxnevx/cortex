"""Estilo com imagens e musica: momentos, credito, sorteio e trilha. Sem internet.

Roda:  .venv\\Scripts\\python.exe tests\\ilustra_unit.py
"""
from __future__ import annotations

import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fabrica import paths  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="cortex_il_"))
paths.STATE = TMP
from fabrica import bordas, ilustra  # noqa: E402
from fabrica.config import Config  # noqa: E402
from fabrica.models import ClipPlan, RenderedClip, Segment, Transcript, Word  # noqa: E402
from fabrica.publish import captions  # noqa: E402

fails: list[str] = []


def check(name: str, cond: bool, extra: object = "") -> None:
    print(("ok    " if cond else "FALHA ") + name + (f"  [{extra}]" if extra and not cond else ""))
    if not cond:
        fails.append(name)


TXT = "oi gente hoje o Trump falou do filme Barney e depois a Demi Lovato chegou no Brasil e o Trump riu muito com todo mundo ali no fim".split()
ws = [Word(i * 1.0, i * 1.0 + 0.8, w) for i, w in enumerate(TXT)]
caps = Transcript([Segment(0, 30, " ".join(TXT), ws)], "pt", "x")
im = [{"palavra": "Trump", "busca": "Donald Trump"}, {"palavra": "Demi Lovato", "busca": "Demi Lovato"}, {"palavra": "Barney", "busca": "Barney"},
      {"palavra": "Xuxa", "busca": "Xuxa"}]
ms = ilustra.momentos(im, ws, 30)
check("entra na hora da palavra, inclusive nome composto", [(m["palavra"], m["t"]) for m in ms] == [("Trump", 4.0), ("Barney", 8.0), ("Demi Lovato", 12.0)], ms)
check("palavra que nao foi dita nao entra", all(m["palavra"] != "Xuxa" for m in ms))
check("nada no comeco nem no fim", ilustra.momentos([{"palavra": "oi"}, {"palavra": "fim"}], ws, 28) == [])
check("folga entre imagens", ilustra.momentos([{"palavra": "Trump"}, {"palavra": "falou"}], ws, 30)[0]["palavra"] == "Trump" and len(ilustra.momentos([{"palavra": "Trump"}, {"palavra": "falou"}], ws, 30)) == 1)
ilustra.buscar = lambda t: {"arquivo": "x.jpg", "artigo": t, "autor": "Fulano", "licenca": "CC BY 4.0"} if "Xuxa" not in t else None
check("2 ou mais imagens: aplica", len(ilustra.preparar(im, ws, 30)) == 3)
check("so 1 imagem: fica simples", ilustra.preparar(im[:1], ws, 30) == [])
check("credito uma vez por autor", ilustra.credito(ilustra.preparar(im, ws, 30)) == "Imagens: Fulano (CC BY 4.0), via Wikimedia Commons", ilustra.credito(ilustra.preparar(im, ws, 30)))
check("so licenca livre", all(ilustra.LIVRES.match(x) for x in ("CC BY-SA 4.0", "CC BY 2.0", "CC0", "Public domain", "CC BY-SA 3.0 br"))
      and not any(ilustra.LIVRES.match(x) for x in ("Fair use", "CC BY-NC 4.0", "CC BY-ND 2.0", "Copyrighted", "")))
check("artigo tem que ser sobre o termo", ilustra._parecido("Jensen Huang", "Jensen Huang") and not ilustra._parecido("Barney", "Dinossauro") and not ilustra._parecido("Demi Lovato", "Lady Gaga"))
check("download so da Wikimedia", not ilustra._baixa("https://exemplo.com/a.jpg", TMP / "a.jpg"))

# ------------------------------------------------------------------ sorteio e credito no post
aplicou: list = []
ilustra.aplicar = lambda f, m, d, c, cfg, centro_y=960: aplicou.append(Path(f).name)
cfg = Config({})


def corte(lado: str, **kw):
    p = ClipPlan(id="c", source_id="s", start=0, end=30, title="Demi Lovato e o Barney no Brasil 😳", hook="X", description="", hashtags=[])
    p.imagens, p.exp, p.category, p.fala = [dict(x) for x in im], {"imagens": lado}, "humor", " ".join(TXT)
    return RenderedClip(plan=p, path="a_youtube.mp4", duration=30, layout=kw.get("layout", "blur"), variants={"youtube": "a_youtube.mp4", "tiktok": "a_tiktok.mp4"})


r = corte("B")
check("lado B: aplica em todas as versoes", ilustra.no_corte(r, r.plan, caps, cfg, False) and sorted(aplicou) == ["a_tiktok.mp4", "a_youtube.mp4"] and len(r.plan.imagens) == 3, aplicou)
for rede in ("youtube", "tiktok", "instagram"):
    _, texto = captions.build_post_text(r.plan, rede, Config({"publicacao": {"creditar_fonte": True}}), video_title="v", channel="Canal")
    check(f"credito no post do {rede}", "Wikimedia Commons" in texto, texto)
aplicou.clear()
a = corte("A")
check("lado A: continua simples, mas fica no teste", not ilustra.no_corte(a, a.plan, caps, cfg, False) and aplicou == [] and a.plan.exp.get("imagens") == "A" and a.plan.imagens == [])
for nome, k in (("react", {"layout": "react"}), ("versao longa", {})):
    x = corte("B", **k)
    check(f"{nome}: fora do teste", not ilustra.no_corte(x, x.plan, caps, cfg, nome == "versao longa") and "imagens" not in x.plan.exp)
p = r.plan.__class__.from_dict(r.plan.to_dict())
check("plano guarda as imagens", p.imagens == r.plan.imagens)
t = Transcript([Segment(float(i * 5), float(i * 5 + 5), f"frase {i}.", []) for i in range(80)], "pt", "x")
q = ClipPlan(id="p", source_id="s", start=100, end=140, title="t", hook="h", description="", hashtags=[])
q = bordas.aplicar([q], {1: {"serve": True, "inicio": 100, "fim": 140, "imagens": [{"palavra": "Barney", "busca": "Barney"}, "lixo", {"x": 1}]}}, [(1, q)], t, 28, 58)[0]
check("sugestao vem da conferencia do corte", q.imagens == [{"palavra": "Barney", "busca": "Barney"}], q.imagens)

# ------------------------------------------------------------------ musica
w = wave.open(str(ilustra.trilha(TMP / "m.wav", 6, "leve", 3)))
check("trilha do tamanho certo", abs(w.getnframes() / w.getframerate() - 6.5) < 0.1)
check("trilha diferente por corte", ilustra.trilha(TMP / "a.wav", 4, "leve", 1).read_bytes() != ilustra.trilha(TMP / "b.wav", 4, "tensa", 2).read_bytes())

print("\n" + ("TUDO OK" if not fails else "FALHAS: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
