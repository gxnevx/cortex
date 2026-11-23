"""Testes rapidos (sem rede, sem Whisper, sem IA) da legenda e da traducao.

    python tests/legendas_unit.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fabrica import transcribe as T  # noqa: E402
from fabrica import translate as TR  # noqa: E402
from fabrica.models import Segment, Transcript, Word  # noqa: E402


def toks(words, step=0.3):
    return [T._Tok(i * step, i * step + step * 0.9, w) for i, w in enumerate(words)]


def test_postprocess():
    out = T.postprocess_tokens(toks(["Ele", "falou", ",", "tipo", "-assim", "50", "%", "e", "1,000,000", "reais"]))
    txt = " ".join(t.text for t in out)
    assert txt == "Ele falou, tipo assim 50% e 1.000.000 reais", txt
    # numero separado pelo Whisper: "10 000" -> "10.000"
    out = T.postprocess_tokens(toks(["custa", "10", "000", "reais"]))
    assert [t.text for t in out] == ["custa", "10.000", "reais"], [t.text for t in out]
    # laco de alucinacao
    out = T.postprocess_tokens(toks(["que"] * 7 + ["isso"]))
    assert [t.text for t in out] == ["que", "que", "que", "isso"], [t.text for t in out]
    out = T.postprocess_tokens(toks("eu acho que eu acho que eu acho que eu acho que sim".split()))
    assert " ".join(t.text for t in out) == "eu acho que eu acho que sim", [t.text for t in out]
    # repeticao humana curta fica
    out = T.postprocess_tokens(toks("nao nao nao".split()))
    assert len(out) == 3
    # travessao/bolinha nunca aparecem na legenda
    dash = chr(0x2014)
    out = T.postprocess_tokens(toks(["a", dash, "b", chr(0x2022)]))
    assert all(dash not in t.text and chr(0x2022) not in t.text for t in out), [t.text for t in out]
    print("ok postprocess")


def test_hallucinations():
    assert T._is_hallucination("Legendas pela comunidade Amara.org")
    assert T._is_hallucination("Obrigado por assistir!", weak=True)
    assert not T._is_hallucination("Obrigado por assistir!", weak=False)
    assert not T._is_hallucination("se inscreve no canal que hoje tem live")
    p = "Como a comedia mudou a cabeca de Thiago Ventura. AchismosTV."
    assert T._is_hallucination("como a comedia mudou a cabeca", prompt=p, weak=True)
    assert T._is_hallucination("Como a comedia mudou a cabeca de Thiago Ventura", prompt=p)
    assert not T._is_hallucination("como a comedia mudou a cabeca", prompt=p)      # fala real, confiante
    assert not T._is_hallucination("a comedia mudou minha vida inteira", prompt=p, weak=True)
    print("ok hallucinations")


def test_word_timing():
    # primeira palavra depois de pausa "engole" o silencio: inicio puxado para perto do fim
    tk = [T._Tok(0.0, 0.3, "oi"), T._Tok(0.3, 0.6, "gente"), T._Tok(1.0, 3.2, "bom"), T._Tok(3.2, 3.5, "dia")]
    out = T._fix_word_timing(tk)
    assert out[2].start > 2.0, out[2]
    assert all(t.end > t.start for t in out)
    assert all(out[i].end <= out[i + 1].start + 1e-9 for i in range(len(out) - 1))
    print("ok word_timing")


def test_prompt():
    p = T.build_prompt("COMO A COMEDIA MUDOU A CABECA DE THIAGO VENTURA | #ACHISMOS PODCAST #403",
                       "AchismosTV", "Neste episodio o Thiago Ventura conversa com Afonso Padilha.\n"
                       "Siga @achismos https://instagram.com/x\nCupom ACHISMOS na Insider")
    assert "Thiago Ventura" in p and "Afonso Padilha" in p and "#" not in p and "http" not in p, p
    assert "COMEDIA" not in p, p
    assert "Insider" not in p and "Neste" not in p, p
    assert len(p) <= 220
    c = T.clean_prompt("BRUXO X LUCAS: DEBATE POLEMICO!!! | #debate, DebateCast")
    assert "#" not in c and "DebateCast" in c, c
    print("ok prompt", p)


def test_pick_model():
    class C(dict):
        def get(self, k, d=None):
            return super().get(k, d)
    cfg = C({"transcricao.modelo_whisper": "small", "transcricao.modelo_legenda": "large-v3-turbo"})
    assert T.pick_model(cfg, 55) == "large-v3-turbo"
    assert T.pick_model(cfg, 240) == "small"
    assert T.pick_model(cfg, None) == "small"
    assert T.pick_model(cfg, 240, purpose="legenda") == "large-v3-turbo"
    assert T.pick_model(cfg, 55, purpose="selecao") == "small"
    print("ok pick_model")


def test_language_guess():
    assert TR.guess_text_language("you know what I mean, it's just like the best thing that I have ever seen") == "en"
    assert TR.guess_text_language("cara, eu nao sei o que voce ta falando, isso ai e muito estranho mano") == "pt"
    assert TR.guess_text_language("pero que es esto, no sé por qué está muy loco el tipo") == "es"
    tr = Transcript([Segment(0, 2, "I don't know what you are talking about, that is just crazy bro")],
                    language="pt", source="youtube_subs")
    assert TR.detect_language(tr) == "en"
    print("ok language")


def test_distribute():
    seg = Segment(10.0, 14.0, "hello there my friend",
                  [Word(10.0, 10.5, "hello"), Word(10.5, 11.0, "there"), Word(12.5, 13.0, "my"), Word(13.0, 14.0, "friend")])
    ws = TR.distribute_words("e ai meu amigo querido", seg)
    assert len(ws) == 5 and ws[0].start == 10.0 and abs(ws[-1].end - 14.0) < 0.01, ws
    assert all(w.end > w.start for w in ws)
    assert all(ws[i].end <= ws[i + 1].start + 1e-6 for i in range(len(ws) - 1)), ws
    # nenhuma palavra no meio da pausa (11.0 a 12.5)
    assert not any(w.start >= 11.05 and w.end <= 12.45 for w in ws), ws
    print("ok distribute")


def test_to_portuguese_fake_engine():
    calls = []

    def fake(prompt, system, schema):
        items = json.loads(next(ln for ln in prompt.splitlines() if ln.startswith("[{")))
        calls.append(len(items))
        out = [{"id": it["id"], "pt": "porra, " + it["texto"].replace("fuck", "").strip() + " traduzido"} for it in items]
        if len(items) > 1:
            out = out[:-1]          # modelo pequeno "esquece" um id: tem que pedir de novo
        return json.dumps({"traducoes": out})

    TR._ENGINE_CACHE["ollama|False"] = (9e18, TR._Engine("fake", fake, 60))
    try:
        tr = Transcript([Segment(0.0, 1.5, "oh fuck this is it", [Word(0.0, 0.5, "oh"), Word(0.5, 1.5, "fuck")]),
                         Segment(2.0, 3.0, "you know what I mean", []),
                         Segment(3.5, 5.0, "I don't know man, that is crazy", [])], language="en")
        pt = TR.to_portuguese(tr, None, context="teste")
        assert pt is not None and pt.language == "pt" and len(pt.segments) == 3, pt
        for a, b in zip(tr.segments, pt.segments):
            assert (a.start, a.end) == (b.start, b.end)
            assert b.words and b.words[0].start >= a.start and b.words[-1].end <= a.end + 1e-6
            assert " ".join(w.text for w in b.words) == b.text
        # IA devolvendo lixo -> None (pipeline pula o video)
        TR._ENGINE_CACHE["ollama|False"] = (9e18, TR._Engine("fake", lambda p, s, sc: "nao sei", 60))
        assert TR.to_portuguese(tr, None) is None
        assert TR.translate_text("this is the best day of my life", None) == ""
        # sem IA -> None
        TR._ENGINE_CACHE["ollama|False"] = (9e18, None)
        assert TR.to_portuguese(tr, None) is None
        # ja esta em portugues: devolve igual
        trpt = Transcript([Segment(0, 2, "eu nao sei o que voce ta falando cara, isso e muito doido mano")], language="pt")
        assert TR.to_portuguese(trpt, None) is trpt
    finally:
        TR._ENGINE_CACHE.clear()
    print("ok to_portuguese (motor falso)", calls)


def test_engine_order():
    """Claude gasta a cota do dono: so entra se configurado ou com permitir_claude (e Ollama fora)."""
    from fabrica.brain import claude_cli, ollama

    class C(dict):
        def get(self, k, d=None):
            return super().get(k, d)

    saved = (ollama.OllamaBrain.available, claude_cli.ClaudeBrain.available)
    try:
        claude_cli.ClaudeBrain.available = lambda self, refresh=False: True
        ollama.OllamaBrain.available = lambda self, refresh=False: False
        TR._ENGINE_CACHE.clear()
        assert TR.get_engine(C()) is None                                   # padrao: so Ollama
        TR._ENGINE_CACHE.clear()
        assert TR.get_engine(C({"traducao.permitir_claude": True})).name == "claude"
        TR._ENGINE_CACHE.clear()
        assert TR.get_engine(C({"traducao.motor": "claude"})).name == "claude"
        ollama.OllamaBrain.available = lambda self, refresh=False: True
        TR._ENGINE_CACHE.clear()
        e = TR.get_engine(C({"traducao.permitir_claude": True}))
        assert e.name == "ollama", e.name                                    # Ollama no ar: nunca Claude
        TR._ENGINE_CACHE.clear()
        assert TR.get_engine(C({"traducao.motor": "auto"})).name == "ollama"
    finally:
        ollama.OllamaBrain.available, claude_cli.ClaudeBrain.available = saved
        TR._ENGINE_CACHE.clear()
    print("ok engine_order")


if __name__ == "__main__":
    test_postprocess()
    test_hallucinations()
    test_word_timing()
    test_prompt()
    test_pick_model()
    test_language_guess()
    test_distribute()
    test_to_portuguese_fake_engine()
    test_engine_order()
    print("TUDO OK")
