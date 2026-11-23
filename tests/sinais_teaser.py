"""Teste offline do teaser (cold open), das citacoes polemicas e da mascara de palavrao.

Uso (na raiz do projeto):
    .venv\\Scripts\\python.exe tests\\sinais_teaser.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from fabrica.brain.base import finalize_plans, mask_profanity, pick_teaser, polemic_spans, short_hook  # noqa: E402
from fabrica.brain.heuristic import HeuristicBrain  # noqa: E402
from fabrica.models import Candidate, Segment, Transcript, Word  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok   " if cond else "  FALHA ") + msg)
    if not cond:
        FAILS.append(msg)


class Cfg(dict):
    def get(self, k, d=None):
        return super().get(k, d)


def words_of(text: str, t0: float, wps: float = 3.0) -> list[Word]:
    out, t = [], t0
    for w in text.split():
        out.append(Word(round(t, 2), round(t + 1 / wps - 0.03, 2), w))
        t += 1 / wps
    return out


def transcript() -> Transcript:
    lines = [
        "Então gente, hoje a gente vai falar sobre política e economia, um assunto que todo mundo gosta.",
        "Eu acho que o governo errou bastante nessa questão do imposto, mas vamos ver o que ele tem a dizer.",
        "Olha, eu discordo totalmente de você, isso não faz sentido nenhum pra mim.",
        "Você é um mentiroso! Porra, para de inventar número que não existe!",
        "Calma, calma, deixa eu terminar o raciocínio, por favor, me deixa falar.",
        "Não, eu não vou deixar, você tá mentindo pro público e todo mundo sabe disso.",
        "Tá bom, então vamos para o próximo assunto, que é a reforma da previdência.",
        "A previdência é um tema complicado, tem muita coisa envolvida e muita gente afetada.",
    ]
    segs, t = [], 0.0
    for ln in lines * 3:
        ws = words_of(ln, t)
        segs.append(Segment(ws[0].start, ws[-1].end, ln, ws))
        t = ws[-1].end + 0.6
    return Transcript(segs, "pt", "whisper")


def main() -> int:
    print("=== mascara de palavrao")
    check(mask_profanity("Porra, que caralho é esse? Foda-se") == "P*rra, que c*ralho é esse? F*da-se",
          mask_profanity("Porra, que caralho é esse? Foda-se"))
    check(mask_profanity("VAI TOMAR NO CU", "mascarar") == "VAI TOMAR NO C*", "cu em caixa alta")
    check(mask_profanity("cuidado com a computação") == "cuidado com a computação", "nao mascara palavras comuns")
    check(mask_profanity("porra mano", "mostrar") == "porra mano", "modo mostrar")
    check(mask_profanity("\"Porra, para\" o clima pesou", "remover") == "\"para\" o clima pesou"
          or "porra" not in mask_profanity("\"Porra, para\" o clima pesou", "remover").lower(), "modo remover")
    check(short_hook('"VOCÊ É UM MENTIROSO" \U0001F633') == '"VOCÊ É UM MENTIROSO" \U0001F633', "gancho mantem aspas")

    print("\n=== trechos polemicos")
    tr = transcript()
    sp = polemic_spans(tr.words()[:120], None)
    for s in sp[:3]:
        print(f"   {s['start']:.2f}-{s['end']:.2f} nota {s['score']}: {s['text']} {s['tipos']}")
    check(bool(sp) and "mentiroso" in sp[0]["text"].lower(), "o mais polemico tem 'mentiroso'")
    check(all(1.45 <= s["end"] - s["start"] <= 3.05 for s in sp), "todos entre 1,5 e 3 s")
    w = tr.words()
    tz = pick_teaser(w, 0, 60, hint_text="você tá mentindo pro público")
    check(tz is not None and "mentindo" in tz["text"], f"teaser pela citacao sugerida: {tz}")
    tz2 = pick_teaser(w, 0, 60, hint_text="frase que ninguem disse aqui nunca")
    check(tz2 is not None and tz2.get("fonte") == "polemico", "citacao inexistente cai no trecho polemico")

    print("\n=== finalize_plans: teaser valido e titulos mascarados")
    cfg = Cfg({"corte.duracao_min_s": 20, "corte.duracao_max_s": 58, "conteudo.palavroes": "mascarar"})
    video = Candidate(id="youtube:teste", platform="youtube", url="u", title="Debate", duration=tr.duration)
    raw = [{"inicio": 5, "fim": 50, "titulo": "\"Porra, para de inventar\" o clima pesou", "gancho": "\"PORRA\"",
            "pontuacao": 80, "motivo": "treta", "teaser_texto": "Você é um mentiroso!", "teaser_inicio": "00:30"}]
    plans = finalize_plans(raw, video, tr, cfg)
    p = plans[0]
    print(f"   corte {p.start:.1f}-{p.end:.1f} | teaser {p.teaser_start}-{p.teaser_end} '{p.teaser_text}'")
    print(f"   titulo: {p.title} | gancho: {p.hook}")
    check(p.teaser_start is not None and p.teaser_start >= p.start + 3.95, "teaser comeca 4 s depois do inicio")
    check(p.teaser_end is not None and p.teaser_end <= p.end and 1.45 <= p.teaser_end - p.teaser_start <= 3.05,
          "teaser dentro do corte com 1,5 a 3 s")
    check("mentiroso" in p.teaser_text.lower(), "teaser = citacao sugerida")
    check("P*rra" in p.title and "porra" not in p.title.lower(), "palavrao mascarado no titulo")

    print("\n=== heuristico: citacao polemica no titulo/gancho")
    cfg2 = Cfg({"corte.duracao_min_s": 20, "corte.duracao_max_s": 58, "conteudo.palavroes": "mascarar",
                "conteudo.emojis": True, "conteudo.titulo_com_citacao": True})
    plans = HeuristicBrain(cfg2).pick_clips(video, tr, cfg2, max_clips=3)
    for p in plans:
        print(f"   {p.start:.1f}-{p.end:.1f} nota {p.score} | {p.title} | {p.hook} | teaser '{p.teaser_text}'")
        for ch in ("\u2022", "\u00b7", "\u2014", "\u2013"):
            check(ch not in p.title + p.hook + p.description, f"sem caractere proibido {ch!r}")
    check(any('"' in p.title for p in plans), "algum titulo com citacao entre aspas")
    check(all(p.teaser_start is not None for p in plans), "todo corte tem teaser")
    check(all("porra" not in (p.title + p.hook).lower() for p in plans), "nenhum palavrao sem mascara")
    print("\n=== saturacao: o momento mais obvio cai para tras")
    from fabrica import signals as sg
    from fabrica.brain import prompts

    v2 = Candidate(id="youtube:sat", platform="youtube", url="u", title="Debate", duration=tr.duration,
                   extra={"comment_marks": [{"t": 17.0, "peso": 9.0, "n": 6, "exemplo": "0:17 mentiroso kkkk"},
                                            {"t": 95.0, "peso": 3.0, "n": 3, "exemplo": "1:35 a previdencia"}]})
    base_w = HeuristicBrain(cfg2).candidate_windows(v2, tr, cfg2, max_clips=3)
    v2.extra["saturacao"] = {"canais": 11, "top_views": 322544, "pular_melhor_momento": True, "multa": 0.7}
    sat_w = HeuristicBrain(cfg2).candidate_windows(v2, tr, cfg2, max_clips=3)
    print(f"   sem saturacao: {[(round(w['start']), w['score']) for w in base_w][:3]}")
    print(f"   saturado     : {[(round(w['start']), w['score']) for w in sat_w][:3]}")
    check(round(base_w[0]["start"]) != round(sat_w[0]["start"]), "o 1o momento mudou quando saturado")
    check(any("2º melhor momento" in w["reason"] for w in sat_w), "motivo explica o 2o melhor momento")
    sig = sg.compute_signals(v2, tr)
    summ = sg.summarize_for_prompt(sig)
    check("ASSUNTO SATURADO" in summ and "comentários" in summ, "resumo do prompt traz saturacao e comentarios")
    v3 = Candidate(id="youtube:en", platform="youtube", url="u", title="Funny moments", extra={"idioma": "en"})
    pr = prompts.clips_prompt(v3, "[00:01] you are a liar", summ, cfg2, 3)
    check("IDIOMA: o vídeo está em INGLÊS" in pr and "teaser_texto" in pr, "prompt de video estrangeiro pede pt-BR")
    for ch in ("\u2022", "\u00b7", "\u2014", "\u2013"):
        check(ch not in pr, f"prompt sem {ch!r}")

    print("\n=== os 5 niveis de tom (fabrica.tom) no heuristico")
    from fabrica.brain import modelos_tom

    print(f"   modelos de titulo: {modelos_tom.count_templates()}")
    check(modelos_tom.count_templates() >= 40, "40+ modelos de titulo")
    for lv in ("neutro", "polemico", "malicioso", "super_polemico", "modo_besta"):
        c = Cfg({"corte.duracao_min_s": 20, "corte.duracao_max_s": 58, "conteudo.emojis": True,
                 "conteudo.tom_titulo": lv, "conteudo.palavroes": "mascarar"})
        ps = HeuristicBrain(c).pick_clips(video, tr, c, max_clips=3)
        for p in ps:
            print(f"   [{lv}] {p.title} | {p.hook}")
            txt = p.title + p.hook + p.description
            check(not any(ch in txt for ch in ("•", "·", "—", "–")), f"{lv}: sem caractere proibido")
            if lv != "modo_besta":
                check("porra" not in txt.lower(), f"{lv}: palavrao mascarado/removido")
        pr = prompts.clips_prompt(video, "[00:01] teste", "", c, 3)
        check(f"TOM ({lv})" in pr and "nunca inventar" in pr, f"{lv}: prompt traz o tom e o piso")

    print("\nRESULTADO:", "tudo ok" if not FAILS else f"{len(FAILS)} falha(s): " + "; ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
