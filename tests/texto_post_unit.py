"""Teste do texto dos posts (titulo, descricao/legenda, hashtags, CTA). Nao abre navegador, nao publica.

Roda:  .venv\\Scripts\\python.exe tests\\texto_post_unit.py

Gera os posts de 8 cortes de exemplo (politica, games LEGENDADO, humor com palavrao, podcast serie 2/3,
futebol, celebridades, noticias, polemica) para YouTube e TikTok, confere limites e regras e imprime.
Usa banco e memoria temporarios (nao suja data/).
"""
from __future__ import annotations

import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fabrica import paths  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="fab_txt_"))
paths.DB_PATH = TMP / "teste.db"

from fabrica import db, hashtags  # noqa: E402
from fabrica.config import load_config  # noqa: E402
from fabrica.models import ClipPlan, Trend  # noqa: E402
from fabrica.publish import captions  # noqa: E402
from fabrica.publish.captions import build_post_text, split_caption  # noqa: E402

hashtags.MEMORY_FILE = TMP / "hashtags_recentes.json"
hashtags.CTA_MEMORY_FILE = TMP / "cta_recentes.json"
hashtags.TRENDING_FILE = TMP / "hashtags_trending.json"

CFG = load_config()
for k, v in {"publicacao.hashtags_fixas": [], "publicacao.max_hashtags": 5, "publicacao.creditar_fonte": True,
             "publicacao.descricao_rodape": "", "conteudo.emojis": True, "conteudo.palavroes": "mascarar",
             "conteudo.legenda_post_ia": False, "conteudo.tom_titulo": "malicioso",
             "publicacao.hashtags_em_alta": [], "publicacao.hashtags_em_alta_auto": True}.items():
    CFG.set(k, v)

BANNED_CHARS = ("\u2022", "\u00b7", "\u2014", "\u2013")
BANNED_TAGS = {"#fyp", "#foryou", "#viral", "#parati", "#tiktok", "#foryoupage"}


def P(**kw) -> ClipPlan:
    d = dict(id="x-c1", source_id="youtube:abc", start=10, end=50, title="Titulo", hook="", description="",
             hashtags=[], category=None)
    d.update(kw)
    return ClipPlan(**d)


SAMPLES = [
    (P(id="pol-c1", category="politica", title='"Isso não vai passar no Senado" 🏛️ deputado rebate ministro',
       hook='"ISSO NÃO VAI PASSAR"', description="Deputado discute a reforma tributária com o ministro na "
       "Câmara dos Deputados, sessão de ontem.", hashtags=["#politica", "#camaradosdeputados", "#reforma"]),
     "Plenário ao vivo: reforma tributária", "Câmara dos Deputados"),
    (P(id="gta-c1", category="games", title="Streamer gringo fica sem palavras no GTA 6 😳🔥🎮",
       hook="ELE NÃO ACREDITOU", description="Reação ao primeiro minuto de GTA 6 em Vice City.",
       hashtags=["#gta6", "#gaming", "#fyp", "#viral"], idioma_origem="en"),
     "GTA 6 first reaction LIVE", "xQc"),
    (P(id="hum-c1", category="humor", title='"Que porra é essa, mano?" KKKKKK 💀',
       hook='"QUE PORRA É ESSA"', description="Zoeira no stand up de ontem, a plateia não aguentou.",
       hashtags=["humor", "standup", "#porra"]),
     "Stand up completo", "Afonso Padilha"),
    (P(id="pod-c2", category="podcast", title="Ele contou o que aconteceu no hospital (parte 2) 😶",
       hook="O MÉDICO DISSE ISSO", description="Convidado conta a história de quando quase morreu.",
       hashtags=["#podcast", "#podpah", "#historia"], series="hospital", part=2, parts_total=3),
     "PODPAH #900 convidado especial", "Podpah"),
    (P(id="fut-c1", category="esportes", title="Neymar manda a real sobre o Flamengo ⚽",
       hook="A REAL SOBRE O MENGÃO", description="Resenha sobre a final da Libertadores e o mercado da bola.",
       hashtags=["#futebol", "#neymar"]),
     "Resenha com Neymar", "Charla Podcast"),
    (P(id="cel-c1", category="entretenimento", title="A treta da roça pegou fogo em A Fazenda 18 🍿",
       hook="O CLIMA PESOU", description="Discussão entre peões depois da prova de fogo.",
       hashtags=["#afazenda18", "#reality"]),
     "A Fazenda 18: roça", "Record"),
    (P(id="not-c1", category="noticias", title="Dólar dispara e preço da gasolina sobe 🚨",
       hook="SUBIU DE NOVO", description="Entenda o que aconteceu com a economia nesta semana.",
       hashtags=["#noticias", "#economia", "#dolar"]),
     "Jornal da manhã", "Canal de Notícias"),
    (P(id="pol2-c1", category="polemica", title="Ela não deixou ele terminar a frase 😬",
       hook="DEIXA EU FALAR", description="Debate sobre relacionamento num podcast.",
       hashtags=["#polemica", "#relacionamento"]),
     "Debate quente", "Podcast X"),
]


def tags_of(text: str) -> list[str]:
    return text.rstrip().split("\n")[-1].split()


def n_emojis(s: str) -> int:
    return len(captions._ONE_EMOJI_RE.findall(s))


def check_common(title: str, text: str, platform: str) -> None:
    assert not any(c in title + text for c in BANNED_CHARS), (title, text)
    assert "<" not in title + text and ">" not in title + text
    assert "porra" not in (title + text).lower(), (title, text)
    tags = tags_of(text)
    assert tags and all(t.startswith("#") for t in tags), text
    assert len(tags) == len({t.lower() for t in tags}), tags
    assert not (set(t.lower() for t in tags) & BANNED_TAGS), tags
    for t in tags:
        if t != "#Shorts":
            assert re.fullmatch(r"#[a-z0-9_]{2,22}", t), t
    for bad in ("curte e segue", "deixa o like", "sininho"):
        assert bad not in text.lower(), text
    if platform == "youtube":
        assert len(title) <= 100, (len(title), title)
        assert len(text) <= 5000
        assert tags[-1] == "#Shorts" and len(tags) <= 15 and len(tags) <= 5 + 1, tags
        assert n_emojis(title) <= 2, title
    else:
        assert len(text) <= 2200
        assert len(tags) <= 5 and "#Shorts" not in tags and "#shorts" not in [t.lower() for t in tags], tags
        assert text.startswith(title), (title, text)
        assert split_caption(text)[1] == tags


def test_samples() -> dict:
    out = {}
    for plan, vt, ch in SAMPLES:
        for plat in ("youtube", "tiktok"):
            t, d = build_post_text(plan, plat, CFG, video_title=vt, channel=ch)
            check_common(t, d, plat)
            out[(plan.id, plat)] = (t, d)
            # mesma chamada de novo = mesmo texto (memoria por corte, nao gira a cada chamada)
            assert build_post_text(plan, plat, CFG, video_title=vt, channel=ch) == (t, d), plan.id
    # regras especificas
    yt_gta, tt_gta = out[("gta-c1", "youtube")], out[("gta-c1", "tiktok")]
    for t, d in (yt_gta, tt_gta):
        assert t.count("(LEGENDADO)") == 1 and t.endswith("(LEGENDADO)"), t
        tg = tags_of(d)
        assert "#gta6" in tg and any(x in tg for x in ("#games", "#gamer", "#jogos")), tg
        assert "#legendado" in d, d
        assert "Original em inglês, com legenda em português." in d, d
    assert n_emojis(yt_gta[0]) == 2, yt_gta[0]                     # 3 emojis no plano -> 2 no titulo
    t_hum, d_hum = out[("hum-c1", "youtube")]
    assert "p*rra" in t_hum, t_hum
    assert "#porra" not in d_hum.lower(), d_hum
    for plat in ("youtube", "tiktok"):
        t, d = out[("pod-c2", plat)]
        assert t.count("Parte") + t.count("parte") == 1 and t.endswith("(Parte 2/3)"), t
        assert "Parte 2/3, " in d, d                                 # CTA de serie
    assert "#podpah" in tags_of(out[("pod-c2", "tiktok")][1])
    assert "Fonte: Podpah" in out[("pod-c2", "youtube")][1]
    fut = tags_of(out[("fut-c1", "tiktok")][1])
    assert "#neymar" in fut and ("#futebol" in fut or "#futebolbrasileiro" in fut), fut
    pol = tags_of(out[("pol-c1", "youtube")][1])
    assert pol[0] == "#reforma" or "#camaradosdeputados" in pol, pol
    # gancho em CAPS que repete o titulo nao entra; o que nao repete vira frase normal
    assert '"ISSO NÃO VAI PASSAR"' not in out[("pol-c1", "youtube")][1]
    assert "O médico disse isso" in out[("pod-c2", "youtube")][1], out[("pod-c2", "youtube")][1]
    print("ok 8 cortes x 2 redes: limites, emojis, palavrao, LEGENDADO, Parte X/Y, hashtags, fonte")
    return out


def test_rotation() -> None:
    """Mesmo nicho em sequencia: conjunto nunca igual ao anterior e CTA sem repetir em 10 posts."""
    sets, ctas = [], []
    for i in range(14):
        p = P(id=f"rot-c{i}", category="humor", title=f"Ele caiu da cadeira no meio do show {i} 💀",
              description="Zoeira no palco.", hashtags=["#humor"])
        tags = hashtags.choose(p, "tiktok", CFG)
        assert 3 <= len(tags) <= 5, tags
        if sets:
            assert set(tags) != set(sets[-1]), (tags, sets[-1])
        sets.append(tags)
        c = hashtags.cta(p, "tiktok", CFG)
        if c:
            ctas.append(c)
    for i, c in enumerate(ctas):
        assert c not in ctas[max(0, i - 10):i], (c, ctas)
    assert len(ctas) >= 6, ctas
    print(f"ok rodizio: {len({frozenset(s) for s in sets})} conjuntos diferentes em 14 posts, "
          f"{len(ctas)} CTAs sem repetir")


def test_tone() -> None:
    lib = hashtags.load_data()["cta"]
    mal = set(lib["tons"]["malicioso"])
    got = []
    for i in range(20):
        got.append(hashtags.cta(P(id=f"tom-c{i}", category="humor", title="x"), "youtube", CFG))
    assert any(c in mal for c in got), got                           # malicioso aparece
    pol = [hashtags.cta(P(id=f"tomp-c{i}", category="politica", title="x"), "youtube", CFG) for i in range(15)]
    assert not any(c in mal for c in pol), pol                       # politica sempre neutra
    CFG.set("conteudo.tom_titulo", "neutro")
    neu = [hashtags.cta(P(id=f"tomn-c{i}", category="humor", title="x"), "tiktok", CFG) for i in range(15)]
    assert not any(c in mal for c in neu), neu
    CFG.set("conteudo.tom_titulo", "malicioso")
    # serie: no TikTok nao pede follow (padrao), no YouTube pode
    s_tt = [hashtags.cta(P(id=f"ser-c{i}", category="humor", part=1, parts_total=2), "tiktok", CFG) for i in range(12)]
    assert all(c.startswith("Parte 1/2, ") and "segue" not in c and "inscreve" not in c for c in s_tt), s_tt
    s_yt = [hashtags.cta(P(id=f"sery-c{i}", category="humor", part=1, parts_total=2), "youtube", CFG) for i in range(12)]
    assert all(c.startswith("Parte 1/2, ") for c in s_yt), s_yt
    last = hashtags.cta(P(id="serf-c1", category="humor", part=2, parts_total=2), "tiktok", CFG)
    assert last.startswith("Parte 2/2, "), last
    # modo_besta: ragebait; palavrao dito no corte fica sem mascara, palavrao da biblioteca de CTA nao
    CFG.set("conteudo.tom_titulo", "modo_besta")
    besta = set(lib["tons"]["modo_besta"])
    got = [hashtags.cta(P(id=f"bes-c{i}", category="humor", title="x"), "tiktok", CFG) for i in range(25)]
    assert any(c.replace("p*to", "puto") in besta for c in got), got
    assert not any(" puto" in c for c in got), got
    t, d = build_post_text(P(id="bes-t1", category="humor", title='"Que porra é essa" KKKKKK 💀🔥😭',
                             hook='"QUE PORRA"'), "youtube", CFG)
    assert "porra" in t and n_emojis(t) == 3, t                       # modo_besta: 3 emojis, sem mascara
    tp, _ = build_post_text(P(id="bes-p1", category="politica", title="Que porra de votação foi essa"),
                            "youtube", CFG)
    assert "p*rra" in tp, tp                                          # politica: teto polemico, mascara
    pol = [hashtags.cta(P(id=f"besp-c{i}", category="politica", title="x"), "tiktok", CFG) for i in range(15)]
    assert not any(c.replace("p*to", "puto") in besta for c in pol), pol
    CFG.set("conteudo.tom_titulo", "neutro")
    tn, _ = build_post_text(P(id="neu-t1", category="humor", title="Que porra é essa 😭💀"), "youtube", CFG)
    assert "porra" not in tn.lower() and "p*rra" not in tn and n_emojis(tn) == 1, tn
    CFG.set("conteudo.tom_titulo", "malicioso")
    print("ok tom: 5 niveis, politica com teto polemico, serie sem pedir follow no TikTok, modo_besta e neutro")


def test_limits_and_config() -> None:
    many = P(id="many-c1", category="games", hashtags=[f"#tag{i}" for i in range(30)], title="GTA 6 travou tudo")
    CFG.set("publicacao.max_hashtags", 40)
    yt = hashtags.choose(many, "youtube", CFG)
    tt = hashtags.choose(many, "tiktok", CFG)
    assert len(yt) <= 15 and yt[-1] == "#Shorts", yt
    assert len(tt) <= 5, tt
    CFG.set("publicacao.max_hashtags", {"youtube": 3, "tiktok": 4})
    assert len(hashtags.choose(P(id="d-c1", category="games", title="GTA 6"), "youtube", CFG)) == 4
    assert len(hashtags.choose(P(id="d-c1", category="games", title="GTA 6"), "tiktok", CFG)) == 4
    CFG.set("publicacao.max_hashtags", 5)
    CFG.set("publicacao.youtube_hashtag_shorts", False)
    assert "#Shorts" not in hashtags.choose(P(id="e-c1", category="games", title="GTA 6"), "youtube", CFG)
    CFG.set("publicacao.youtube_hashtag_shorts", True)
    # proibidas e normalizacao
    assert hashtags.normalize("Seleção Brasileira") == "#selecaobrasileira"
    for bad in ("#FYP", "#viral", "#ForaLula", "#lulaladrao", "#tiktok", "#porra"):
        assert hashtags.is_banned(hashtags.normalize(bad)), bad
    # sem categoria: confia nas hashtags do cerebro e completa com amplas gerais
    g = hashtags.choose(P(id="g-c1", hashtags=["podcast", "humor", "gta 6"], title="Sem nicho"), "tiktok", CFG)
    assert g[:3] == ["#podcast", "#humor", "#gta6"] and len(g) == 5, g
    # palavrao: mostrar / remover
    CFG.set("conteudo.palavroes", "remover")
    t, _ = build_post_text(P(id="pal-c1", title="Que porra foi essa 😳"), "youtube", CFG)
    assert "porra" not in t.lower() and "p*rra" not in t, t
    CFG.set("conteudo.palavroes", "mascarar")
    # emojis desligados
    CFG.set("conteudo.emojis", False)
    t, d = build_post_text(SAMPLES[1][0], "tiktok", CFG, *SAMPLES[1][1:])
    assert n_emojis(t + d) == 0, (t, d)
    CFG.set("conteudo.emojis", True)
    # (LEGENDADO) ja no titulo (o pipeline poe) nao duplica, e marcar_legendado false nao acrescenta
    p = P(id="leg-c1", title="Reação ao trailer (LEGENDADO)", idioma_origem="en")
    t, _ = build_post_text(p, "youtube", CFG)
    assert t.count("LEGENDADO") == 1 and t.endswith("(LEGENDADO)"), t
    CFG.set("conteudo.marcar_legendado", False)
    t, _ = build_post_text(P(id="leg-c2", title="Reação ao trailer", idioma_origem="es"), "youtube", CFG)
    assert "LEGENDADO" not in t, t
    CFG.set("conteudo.marcar_legendado", True)
    # titulo enorme + legendado + serie: corta o texto, nunca os sufixos
    p = P(id="big-c1", title="Muito texto " * 20 + "🔥", idioma_origem="en", part=1, parts_total=3)
    t, _ = build_post_text(p, "youtube", CFG)
    assert len(t) <= 100 and t.endswith("(LEGENDADO) (Parte 1/3)"), t
    t, _ = build_post_text(P(id="pf-c1", title="A treta (parte 3, final) 😬", part=3, parts_total=3), "youtube", CFG)
    assert t.endswith("(Parte 3/3)") and "final" not in t and t.count("arte") == 1, t
    print("ok limites (15 YouTube, 5 TikTok, por rede), proibidas, palavrao, emojis off, sufixos")


def test_trending() -> None:
    db.save_trends("teste", [Trend(topic="Ronaldinho Gaúcho", source="google_trends", score=90)])
    items = hashtags.trending(CFG, refresh=True)
    assert any(i["tag"] == "#ronaldinhogaucho" for i in items), items
    assert hashtags.TRENDING_FILE.is_file()
    p = P(id="tr-c1", title="Ronaldinho Gaúcho conta tudo", hashtags=["#resenha"])
    assert "#ronaldinhogaucho" in hashtags.choose(p, "tiktok", CFG)
    p2 = P(id="tr-c2", title="Outro assunto qualquer", hashtags=["#resenha"])
    assert "#ronaldinhogaucho" not in hashtags.choose(p2, "tiktok", CFG)    # so se for relevante
    CFG.set("publicacao.hashtags_em_alta", ["#blackfriday"])
    p3 = P(id="tr-c3", title="Comprei tudo na Black Friday", category="humor")
    assert "#blackfriday" in hashtags.choose(p3, "tiktok", CFG), hashtags.choose(p3, "tiktok", CFG)
    CFG.set("publicacao.hashtags_em_alta", [])
    print("ok em alta: tendencias do banco (cache 12 h) e lista manual, so quando relevantes")


def test_ai_polish() -> None:
    plan = P(id="ai-c1", category="humor", title="Ele errou o nome da namorada no palco 💀", hook="ERROU O NOME",
             description="Comediante troca o nome da namorada em show.")
    CFG.set("conteudo.legenda_post_ia", True)
    orig = captions._ask_ai
    try:
        captions._AI_CACHE.clear()
        captions._ask_ai = lambda *a, **k: {"linha": "Fulano trocou o nome da namorada no meio do show 😏",
                                           "pergunta": "Comenta o que você entendeu 😏"}
        t, d = build_post_text(plan, "youtube", CFG)
        assert "Fulano trocou o nome da namorada no meio do show" in d, d
        # insinuacao inventada (traicao nao esta no corte) e pedido de follow: rejeitados -> texto padrao
        captions._AI_CACHE.clear()
        captions._ask_ai = lambda *a, **k: {"linha": "Será que ele traiu ela? 🫢", "pergunta": "Segue pra mais"}
        t2, d2 = build_post_text(plan, "youtube", CFG)
        assert "traiu" not in d2 and "Segue pra mais" not in d2, d2
        captions._AI_CACHE.clear()

        def boom(*a, **k):
            raise RuntimeError("sem cerebro")
        captions._ask_ai = boom
        t3, d3 = build_post_text(plan, "tiktok", CFG)
        assert t3 and d3.startswith(t3)
    finally:
        captions._ask_ai = orig
        CFG.set("conteudo.legenda_post_ia", False)
        captions._AI_CACHE.clear()
    assert captions._grounded("Ele foi preso ontem", "o cara foi preso na operacao")
    assert not captions._grounded("Ele foi preso ontem", "briga no reality")
    print("ok IA opcional: aceita texto valido, recusa insinuacao sem base e pedido de follow, reserva sem IA")


def main() -> int:
    t0 = time.time()
    out = test_samples()
    test_rotation()
    test_tone()
    test_limits_and_config()
    test_trending()
    test_ai_polish()
    print("\n================ AMOSTRAS ================")
    for (pid, plat), (t, d) in out.items():
        print(f"\n--- {pid} [{plat}] titulo ({len(t)} car.):\n{t}\n--- texto ({len(d)} car.):\n{d}")
    print(f"\nTudo ok em {time.time() - t0:.1f} s")
    try:
        db.conn().close()
    except Exception:
        pass
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
