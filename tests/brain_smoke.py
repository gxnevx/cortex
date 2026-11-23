"""Smoke test do cerebro + transcricao + sinais.

Rode (na pasta do projeto):
    .venv\\Scripts\\python.exe tests\\brain_smoke.py
Opcoes: --sem-rede (so testes offline)  --sem-whisper  --sem-ollama  --manter (nao apaga os arquivos baixados)

O que testa:
  1. parser de legendas (.json3 / .vtt rolante do YouTube / .srt) com amostras sinteticas
  2. pos-processamento comum (encaixe em palavras, series contiguas, sobreposicao, pontuacao minima)
  3. extracao robusta de JSON + parser da saida do Claude Code (subprocess simulado)
  4. Claude Code real: deteccao de "Not logged in"
  5. legendas reais de um video brasileiro (yt-dlp) -> HeuristicBrain.pick_clips + rank_trends
  6. Ollama com gemma3:270m (so o encanamento JSON; qualidade ruim e esperada)
  7. faster-whisper (small) num trecho de 60 s: tempo por palavra + velocidade
"""
from __future__ import annotations

import json
import shutil
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from fabrica import paths, signals, tools  # noqa: E402
from fabrica.config import load_config  # noqa: E402
from fabrica.models import Candidate, ClipPlan, Transcript, Trend, Word  # noqa: E402

ARGS = set(sys.argv[1:])
OFFLINE = "--sem-rede" in ARGS
TEST_DIR = paths.TMP / "brain_smoke"
VIDEO_ID = "zKhmQeobLCA"            # debate curto (8 min) com legenda automatica pt e "mais repetidos"
FALLBACK_SEARCH = "podcast polêmica debate"
RESULTS: list[tuple[str, bool, str]] = []
CTX: dict = {}


def step(name: str):
    def deco(fn):
        def run():
            print(f"\n=== {name} ===", flush=True)
            t0 = time.time()
            try:
                info = fn() or ""
                RESULTS.append((name, True, f"{info} ({time.time() - t0:.1f}s)"))
                print(f"--> OK {info}", flush=True)
            except SkipTest as e:
                RESULTS.append((name, True, f"pulado: {e}"))
                print(f"--> PULADO: {e}", flush=True)
            except Exception as e:
                traceback.print_exc()
                RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
                print(f"--> FALHOU: {e}", flush=True)
        return run
    return deco


class SkipTest(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


FORBIDDEN = ("\u2022", "\u00b7", "\u2014", "\u2013")      # bolinha, ponto medio, travessao, meia-risca


def n_emojis(text: str) -> int:
    from fabrica.brain.base import _ONE_EMOJI

    return len(_ONE_EMOJI.findall(text or ""))


def check_plans(plans: list[ClipPlan], tr: Transcript, cfg, allow_single_short=False):
    from fabrica.brain.base import emojis_enabled

    dmin = cfg.get("corte.duracao_min_s", 20)
    dmax = cfg.get("corte.duracao_max_s", 58)
    emo = emojis_enabled(cfg)
    words = tr.words()
    ids = set()
    for p in plans:
        check(p.id not in ids, f"id repetido {p.id}")
        ids.add(p.id)
        for field in (p.title, p.hook, p.description, p.reason, p.series or ""):
            check(not any(c in field for c in FORBIDDEN), f"{p.id}: caractere proibido em {field!r}")
        if emo:
            check(n_emojis(p.title) <= 2 and n_emojis(p.hook) <= 1, f"{p.id}: emojis demais {p.title!r} {p.hook!r}")
        else:
            check(n_emojis(p.title + p.hook + p.description) == 0, f"{p.id}: emoji com conteudo.emojis=false")
        check(0 <= p.start < p.end <= tr.duration + 0.6, f"{p.id}: fora da transcricao {p.start}-{p.end}")
        check(dmin * 0.8 - 0.01 <= p.duration <= dmax + 0.01 or allow_single_short, f"{p.id}: duracao {p.duration:.1f}")
        for w in words:   # nunca corta palavra no meio
            if w.end - w.start < 0.06:
                continue
            check(not (w.start + 0.03 < p.start < w.end - 0.03), f"{p.id}: inicio corta '{w.text}' {w.start}-{w.end}")
            check(not (w.start + 0.03 < p.end < w.end - 0.03), f"{p.id}: fim corta '{w.text}' {w.start}-{w.end}")
        check(all(h.startswith("#") and " " not in h for h in p.hashtags), f"hashtags {p.hashtags}")
    # sem sobreposicao (partes da serie sao contiguas)
    srt = sorted(plans, key=lambda p: p.start)
    for a, b in zip(srt, srt[1:]):
        check(b.start >= a.end - 0.01, f"sobreposicao {a.id} {a.start}-{a.end} x {b.id} {b.start}-{b.end}")
    series: dict[str, list[ClipPlan]] = {}
    for p in plans:
        if p.series:
            series.setdefault(p.series, []).append(p)
    for name, ps in series.items():
        ps.sort(key=lambda p: p.part)
        check([p.part for p in ps] == list(range(1, len(ps) + 1)), f"partes {name}: {[p.part for p in ps]}")
        for a, b in zip(ps, ps[1:]):
            check(abs(b.start - a.end) < 0.01, f"serie {name} nao contigua: {a.end} -> {b.start}")
        check(all(p.parts_total == len(ps) for p in ps), "parts_total errado")


def show_plans(plans: list[ClipPlan], tr: Transcript | None = None):
    for p in plans:
        sp = f" série '{p.series}' {p.part}/{p.parts_total}" if p.series else ""
        print(f"  [{p.start:7.2f}-{p.end:7.2f}] {p.duration:5.1f}s nota {p.score:5.1f} {p.category} {p.layout}{sp}")
        print(f"     título: {p.title}")
        print(f"     gancho: {p.hook} | {' '.join(p.hashtags)}")
        print(f"     motivo: {p.reason[:120]}")
        if tr is not None:
            txt = tr.slice(p.start, p.end, rebase=False).text
            print(f"     texto : {txt[:110]} … {txt[-70:]}")


def synthetic_transcript(total: float = 600.0) -> Transcript:
    """Fala sintetica: frases de 12 palavras (0,4 s cada) com pausa de 0,6 s."""
    from fabrica.transcribe import transcript_from_words

    vocab = ["isso", "aqui", "e", "muito", "serio", "gente", "voce", "acredita", "nessa", "historia", "cara", "mentira"]
    words, t, i = [], 0.5, 0
    while t < total:
        for k in range(12):
            txt = vocab[(i + k) % len(vocab)] + ("." if k == 11 else "")
            words.append(Word(round(t, 3), round(t + 0.33, 3), txt))
            t += 0.4
        t += 0.6
        i += 1
    return transcript_from_words(words)


def ytdlp_base() -> dict:
    node = tools.node()
    opts = {"quiet": True, "no_warnings": True, "noprogress": True}
    if node:
        opts["js_runtimes"] = {"node": {"path": node}}
    return opts


# ----------------------------------------------------------------------------------------
@step("1. parser de legendas (amostras)")
def t_parse_samples():
    from fabrica.transcribe import parse_subtitles

    TEST_DIR.mkdir(parents=True, exist_ok=True)
    vtt = TEST_DIR / "a.pt.vtt"
    vtt.write_text(
        "WEBVTT\nKind: captions\nLanguage: pt\n\n"
        "00:00:00.120 --> 00:00:01.270 align:start position:0%\n \n"
        "A<00:00:00.199><c> gente</c><00:00:00.280><c> tem</c><00:00:00.399><c> um</c><00:00:00.480><c> projeto.</c>\n\n"
        "00:00:01.270 --> 00:00:01.280 align:start position:0%\nA gente tem um projeto.\n \n\n"
        "00:00:01.280 --> 00:00:02.909 align:start position:0%\nA gente tem um projeto.\n"
        "&gt;&gt; Mentira<00:00:01.719><c> kkkk</c><00:00:02.120><c> absurdo!</c>\n\n"
        "00:00:02.909 --> 00:00:02.919 align:start position:0%\n&gt;&gt; Mentira kkkk absurdo!\n \n", encoding="utf-8")
    tv = parse_subtitles(vtt)
    wv = [w.text for w in tv.words()]
    check(wv == ["A", "gente", "tem", "um", "projeto.", "Mentira", "kkkk", "absurdo!"], f"vtt palavras {wv}")
    check(abs(tv.words()[1].start - 0.199) < 0.002, "tempo por palavra do vtt")
    check(len(tv.segments) == 2 and tv.segments[1].text.startswith(">>"), f"segmentos vtt {[s.text for s in tv.segments]}")
    srt = TEST_DIR / "b.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:03,500\n<i>Olá pessoal,</i> tudo bem?\n\n"
                   "2\n00:00:04,000 --> 00:00:06,000\n[Risos]\nNão acredito nisso!\n", encoding="utf-8")
    ts = parse_subtitles(srt)
    check([w.text for w in ts.words()] == ["Olá", "pessoal,", "tudo", "bem?", "Não", "acredito", "nisso!"], "srt")
    check("[Risos]" in ts.text, "anotacao [Risos] deve ficar no texto")
    j3 = TEST_DIR / "c.pt.json3"
    j3.write_text(json.dumps({"events": [
        {"tStartMs": 0, "dDurationMs": 9000, "id": 1},
        {"tStartMs": 100, "dDurationMs": 3000, "wWinId": 1, "segs": [{"utf8": "Cala"}, {"utf8": " a", "tOffsetMs": 300},
                                                                      {"utf8": " boca!", "tOffsetMs": 500}]},
        {"tStartMs": 1500, "dDurationMs": 200, "wWinId": 1, "aAppend": 1, "segs": [{"utf8": "\n"}]},
        {"tStartMs": 1600, "dDurationMs": 3000, "wWinId": 1, "segs": [{"utf8": ">> Sim."}]},
        {"tStartMs": 2000, "dDurationMs": 3000, "wWinId": 1, "segs": [{"utf8": "Você"}, {"utf8": " viu?", "tOffsetMs": 200}]},
    ]}), encoding="utf-8")
    tj = parse_subtitles(j3)
    wj = [(w.text, w.start) for w in tj.words()]
    check([w for w, _ in wj] == ["Cala", "a", "boca!", "Sim.", "Você", "viu?"], f"json3 {wj}")
    check(wj[3][1] < 2.0, "json3: evento sem tOffset limitado pelo proximo evento")
    return f"vtt {len(wv)} palavras, srt {len(ts.words())}, json3 {len(wj)}"


@step("2. pós-processamento (encaixe, séries, sobreposição, nota mínima)")
def t_finalize():
    from fabrica.brain.base import finalize_plans

    cfg = load_config()
    tr = synthetic_transcript(600)
    video = Candidate(id="youtube:abcdefghijk", platform="youtube", url="u", title="Debate Pesado: Teste!", duration=600)
    raw = [
        {"inicio": "00:40", "fim": "03:20", "titulo": "ASSUNTO LONGO 🔥", "pontuacao": 90, "hashtags": "#Debate #Polêmica"},
        {"inicio": "05:00", "fim": "06:00", "titulo": "Série A 😳", "pontuacao": 80, "serie": "Série A", "parte": 1},
        {"inicio": "05:58", "fim": "07:00", "titulo": "Série A 😳", "pontuacao": 80, "serie": "Série A", "parte": 2},
        {"inicio": "03:10", "fim": "04:00", "titulo": "sobreposto", "pontuacao": 70},
        {"inicio": "08:20", "fim": "09:00", "titulo": "nota baixa", "pontuacao": 30},
        {"inicio": "07:30", "fim": "07:40", "titulo": "curto demais", "pontuacao": 75},
        {"inicio": "lixo", "fim": None, "titulo": "invalido"},
    ]
    cfg.set("execucao.cortes_por_video", 10)        # numero fixo (auto limitaria a 3 num video de 10 min)
    plans = finalize_plans(raw, video, tr, cfg, max_clips=10)
    show_plans(plans)
    check_plans(plans, tr, cfg)
    check(any(p.series and p.parts_total and p.parts_total >= 2 for p in plans), "deveria virar serie")
    check(not any(p.title == "nota baixa" for p in plans), "nota baixa deveria cair")
    check(sum(1 for p in plans if p.series and p.series.startswith("S")) >= 2, "serie A (2+ partes) do motor")
    check(any(p.title == "sobreposto" for p in plans), "sobreposicao pequena deveria ser aparada, nao descartada")
    check(all(p.id.startswith("debate-pesado-teste-") for p in plans), "id")
    check(any("(parte 2" in p.title for p in plans) and any(", final)" in p.title for p in plans), "titulo de serie")
    # regra de emojis/pontuacao: com e sem conteudo.emojis
    dirty = [{"inicio": "00:20", "fim": "01:00", "titulo": "ELE FALOU \u2014 e pesou \U0001F633\U0001F525\U0001F525\U0001F480",
              "gancho": "O CLIMA PESOU \U0001F62C\U0001F525", "descricao": "\u2022 contexto \u00b7 debate \u2013 x",
              "pontuacao": 90}]
    for flag in (True, False):
        cfg.set("conteudo.emojis", flag)
        dp = finalize_plans(dirty, video, tr, cfg)
        print(f"  conteudo.emojis={flag}: {dp[0].title!r} | {dp[0].hook!r} | {dp[0].description!r}")
        check_plans(dp, tr, cfg)
    cfg.set("conteudo.emojis", True)
    # so nota baixa -> mantem o melhor
    only_low = finalize_plans([{"inicio": 30, "fim": 70, "titulo": "x", "pontuacao": 20},
                               {"inicio": 100, "fim": 140, "titulo": "y", "pontuacao": 10}], video, tr, cfg)
    check(len(only_low) == 1 and only_low[0].title == "x", "mantem pelo menos o melhor")
    # limite
    lim = finalize_plans(raw, video, tr, cfg, max_clips=2)
    check(sum(1 for _ in lim) <= 2, "max_clips")
    return f"{len(plans)} cortes válidos"


@step("3. JSON robusto + saída do Claude Code simulada")
def t_json_and_claude_mock():
    from fabrica.brain import claude_cli
    from fabrica.brain.base import BrainUnavailable, extract_json

    check(extract_json('```json\n{"cortes": [{"inicio": "01:00"}]}\n```\nEspero ter ajudado!')["cortes"][0]["inicio"] == "01:00", "fence")
    check(extract_json('Claro! Aqui está: {"a": [1, 2,],} fim')["a"] == [1, 2], "virgula sobrando")
    check(extract_json('{"cortes": [{"inicio": "00:10", "fim": "00:50"}, {"inicio": "01:0')["cortes"][0]["fim"] == "00:50", "cortado")
    check(extract_json("[{'inicio': 1, 'ok': True}]")[0]["ok"] is True, "estilo python")

    # resposta de sucesso simulada
    answer = ("Aqui estão os cortes:\n```json\n" + json.dumps({"cortes": [
        {"inicio": "01:05", "fim": "01:52", "titulo": "ELE FALOU MESMO \u2014 sem filtro 😳🔥", "gancho": "O CLIMA PESOU 😬",
         "descricao": "\u2022 Debate \u00b7 podcast", "hashtags": ["#politica", "podcast"], "pontuacao": 88, "motivo": "treta",
         "categoria": "Política", "serie": None, "parte": None, "layout": "full"},
        {"inicio": "04:00", "fim": "06:30", "titulo": "Assunto longo 👀", "pontuacao": 77, "serie": "longo", "parte": None},
    ]}, ensure_ascii=False) + "\n```\nQualquer coisa me avise.")
    ok_stdout = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": answer})
    check("ELE FALOU" in claude_cli.parse_cli_output(ok_stdout), "parse sucesso")
    bad_stdout = json.dumps({"type": "result", "subtype": "success", "is_error": True,
                             "result": "Not logged in \u00b7 Please run /login"})
    try:
        claude_cli.parse_cli_output(bad_stdout)
        raise AssertionError("deveria detectar nao logado")
    except BrainUnavailable as e:
        check("/login" in str(e), "mensagem de login")

    # ClaudeBrain.pick_clips com subprocess falso
    calls = []

    class FakeProc:
        returncode = 0
        stdout = ok_stdout
        stderr = ""

    def fake_run_cmd(args, timeout=None, cwd=None, input_text=None, check=False, env=None):
        calls.append({"args": list(map(str, args)), "cwd": str(cwd), "stdin": input_text})
        return FakeProc()

    orig = claude_cli.run_cmd
    claude_cli.run_cmd = fake_run_cmd
    try:
        cfg = load_config()
        brain = claude_cli.ClaudeBrain(cfg)
        brain.exe = brain.exe or "claude.exe"
        tr = synthetic_transcript(480)
        video = Candidate(id="youtube:xyz", platform="youtube", url="u", title="Podcast X", duration=480)
        plans = brain.pick_clips(video, tr, cfg, max_clips=6)
    finally:
        claude_cli.run_cmd = orig
    show_plans(plans)
    check_plans(plans, tr, cfg)
    check(plans and plans[0].title.startswith("ELE FALOU"), "plano do claude")
    check(plans[0].category == "politica" and plans[0].layout == "full", "normalizacao")
    a = calls[0]["args"]
    check("-p" in a and "--output-format" in a and "--tools" in a and a[a.index("--tools") + 1] == "", "flags")
    check(calls[0]["cwd"] == str(paths.STATE), "cwd = paths.STATE")
    check("[01:0" in calls[0]["stdin"] or "[00:" in calls[0]["stdin"], "transcricao carimbada no stdin")
    CTX["claude_flags"] = " ".join(x if x else '""' for x in a[1:a.index("--system-prompt") + 1]) + ' "<...>"'
    return f"{len(plans)} cortes do Claude simulado; flags: {CTX['claude_flags']}"


@step("4. Claude Code real (deve detectar 'não logado')")
def t_claude_real():
    from fabrica.brain import ClaudeBrain, get_brain
    from fabrica.brain.base import BrainUnavailable

    cfg = load_config()
    b = ClaudeBrain(cfg)
    if not b.exe:
        raise SkipTest("Claude Code não encontrado")
    ok = b.available(refresh=True)
    print("  auth status ->", ok, "|", b.status())
    try:
        out = b._run("Responda só: ok", "Responda só com a palavra ok.", timeout=120)
        print("  -p respondeu:", out[:80])
        logged = True
    except BrainUnavailable as e:
        print("  -p ->", e)
        logged = False
    check(ok == logged, "auth status e -p discordam")
    br = get_brain(cfg, force="claude")
    print("  get_brain(force=claude) ->", br.name, "|", br.status())
    if not logged:
        check(br.name == "heuristico" and "/login" in br.status(), "fallback com mensagem de login")
    return "logado" if logged else "não logado detectado (mensagem: faça /login)"


def _download_test_video() -> dict:
    """Legendas (json3 + vtt) e metadados do video de teste; procura outro se ele sumir."""
    import yt_dlp

    TEST_DIR.mkdir(parents=True, exist_ok=True)
    vid = VIDEO_ID
    info = None
    try:
        with yt_dlp.YoutubeDL(ytdlp_base()) as y:
            info = y.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
    except Exception as e:
        print("  video padrão indisponível:", e)
    if info is None or not any(k.startswith("pt") for k in (info.get("automatic_captions") or {})):
        with yt_dlp.YoutubeDL({**ytdlp_base(), "extract_flat": True}) as y:
            res = y.extract_info(f"ytsearch10:{FALLBACK_SEARCH}", download=False)
        for e in res.get("entries") or []:
            if 240 <= (e.get("duration") or 0) <= 1200:
                with yt_dlp.YoutubeDL(ytdlp_base()) as y:
                    info = y.extract_info(e["url"], download=False)
                if any(k.startswith("pt") for k in (info.get("automatic_captions") or {})):
                    vid = info["id"]
                    break
    check(info is not None, "nenhum video de teste")
    caps = info.get("automatic_captions") or {}
    subs = info.get("subtitles") or {}
    lang = next((l for l in ("pt-orig", "pt", "pt-BR") if l in caps), None)
    use_auto = lang is not None
    if not use_auto:
        lang = next((l for l in subs if l.startswith("pt")), None)
    check(lang, "video sem legenda pt")
    files = {}
    for fmt in ("json3", "vtt"):
        opts = {**ytdlp_base(), "skip_download": True, "writeautomaticsub": use_auto, "writesubtitles": not use_auto,
                "subtitleslangs": [lang], "subtitlesformat": fmt, "outtmpl": str(TEST_DIR / "%(id)s.%(ext)s")}
        with yt_dlp.YoutubeDL(opts) as y:
            y.extract_info(f"https://www.youtube.com/watch?v={vid}", download=True)
        hits = list(TEST_DIR.glob(f"{vid}.*.{fmt}"))
        if hits:
            files[fmt] = hits[0]
    return {"id": vid, "info": info, "files": files}


@step("5. legendas reais + HeuristicBrain")
def t_real_heuristic():
    from fabrica.brain import HeuristicBrain, get_brain
    from fabrica.transcribe import parse_subtitles

    if OFFLINE:
        raise SkipTest("--sem-rede")
    d = _download_test_video()
    info = d["info"]
    check("json3" in d["files"], "json3 nao baixou")
    tj = parse_subtitles(d["files"]["json3"])
    print(f"  vídeo: {info['title']} ({info.get('channel')}) {info.get('duration')}s")
    print(f"  json3: {len(tj.segments)} segmentos, {len(tj.words())} palavras, {tj.duration:.0f}s")
    if "vtt" in d["files"]:
        tv = parse_subtitles(d["files"]["vtt"])
        ja = {(w.text, round(w.start, 1)) for w in tj.words()}
        same = sum(1 for w in tv.words() if (w.text, round(w.start, 1)) in ja)
        print(f"  vtt  : {len(tv.segments)} segmentos, {len(tv.words())} palavras; {same} iguais ao json3")
        check(abs(len(tv.words()) - len(tj.words())) <= max(10, 0.02 * len(tj.words())), "vtt e json3 muito diferentes")
    for s in tj.segments[:4]:
        print(f"    [{s.start:6.2f}-{s.end:6.2f}] {s.text}")
    check(len(tj.words()) > 100 and max(s.end - s.start for s in tj.segments) <= 12.5, "segmentacao")
    c = Candidate(id=f"youtube:{d['id']}", platform="youtube", url=f"https://www.youtube.com/watch?v={d['id']}",
                  title=info["title"], channel=info.get("channel") or "", duration=info.get("duration"),
                  views=info.get("view_count"), topic="Bolsa Família" if d["id"] == VIDEO_ID else None,
                  description=info.get("description") or "",
                  extra={"heatmap": info.get("heatmap") or [], "chapters": info.get("chapters") or []})
    CTX["video"], CTX["transcript"] = c, tj
    cfg = load_config()
    sig = signals.compute_signals(c, tj)
    print("  sinais:", signals.describe(sig))
    print("  " + signals.summarize_for_prompt(sig, max_items=5).replace("\n", "\n  "))
    t0 = time.time()
    plans = HeuristicBrain(cfg).pick_clips(c, tj, cfg)
    print(f"  pick_clips em {time.time() - t0:.2f}s")
    show_plans(plans, tj)
    check(plans, "heuristico nao achou cortes")
    check_plans(plans, tj, cfg)
    trends = [Trend("Bolsa Família", "google_trends", 70, "50 mil+", ["Debate sobre Bolsa Família esquenta"]),
              Trend("resultado mega-sena", "google_trends", 95, "500 mil+"),
              Trend("GTA 6", "youtube", 60), Trend("gta 6 trailer", "reddit", 50),
              Trend("Flamengo x Palmeiras", "x_trends", 80), Trend("previsão do tempo", "google_trends", 90),
              Trend("Virginia e Zé Felipe", "google_news", 55, related=["separação"]),
              Trend("Casimiro reage", "twitch", 40)]
    ranked = HeuristicBrain(cfg).rank_trends(trends, cfg, limit=5)
    for t in ranked:
        print(f"  tema {t.score:5.1f} {t.category}: {t.topic} -> {t.queries} ({t.reason})")
    check(ranked and "mega" not in ranked[0].topic.lower(), "loteria nao pode liderar")
    check(sum(1 for t in ranked if "gta" in t.topic.lower()) == 1, "GTA 6 duplicado deveria ser unido")
    check(all(2 <= len(t.queries) <= 3 for t in ranked), "queries")
    br = get_brain(cfg, force="heuristico")
    check(br.name == "heuristico", "force heuristico")
    return f"{len(plans)} cortes; {len(ranked)} temas"


@step("6. Ollama (gemma3:270m, encanamento JSON)")
def t_ollama():
    from fabrica.brain import OllamaBrain
    from fabrica.brain.base import extract_json, list_from_json
    from fabrica.brain import prompts

    if "--sem-ollama" in ARGS:
        raise SkipTest("--sem-ollama")
    if not tools.ollama():
        raise SkipTest("Ollama não instalado")
    cfg = load_config()
    cfg.set("cerebro.ollama_modelo", "gemma3:270m")
    cfg.set("cerebro.timeout_s", 180)
    b = OllamaBrain(cfg)
    was_up = b.server_up()
    t0 = time.time()
    ok = b.available(refresh=True)
    print(f"  disponível={ok} em {time.time() - t0:.1f}s | {b.status()} (servidor já estava no ar: {was_up})")
    CTX["ollama_started"] = ok and not was_up
    check(ok, "ollama/gemma3:270m indisponivel")
    # modelo configurado padrao (qwen3:4b) nao existe -> mensagem clara
    miss = OllamaBrain(load_config())
    miss.model = "modelo-inexistente:1b"
    check(not miss.available(refresh=True) and "ollama pull" in miss.status(), "mensagem de modelo faltando")
    print("  modelo ausente ->", miss.status())
    tr = CTX.get("transcript") or synthetic_transcript(420)
    video = CTX.get("video") or Candidate(id="youtube:synthetic", platform="youtube", url="u", title="Teste", duration=420)
    part = tr.slice(0, 420, rebase=False)
    # chamada crua: o JSON do schema volta valido?
    t0 = time.time()
    raw = b.chat(prompts.clips_prompt(video, part.text_with_timestamps(), "", cfg, 3), prompts.SYSTEM_CLIPS,
                 prompts.CLIPS_SCHEMA, timeout=180)
    items = list_from_json(extract_json(raw), ("cortes",))
    print(f"  chat cru em {time.time() - t0:.1f}s: {len(items)} itens JSON; amostra: {json.dumps(items[:1], ensure_ascii=False)[:300]}")
    check(isinstance(extract_json(raw), dict), "resposta nao e JSON")
    t0 = time.time()
    plans = b.pick_clips(video, part, cfg, max_clips=3)
    print(f"  pick_clips em {time.time() - t0:.1f}s ({len(plans)} cortes; se o modelo errar, cai no heurístico):")
    show_plans(plans)
    check(plans, "sem cortes (nem fallback)")
    check_plans(plans, part, cfg)
    trends = [Trend("Bolsa Família", "google_trends", 70), Trend("resultado mega-sena", "google_trends", 95),
              Trend("GTA 6", "youtube", 60)]
    t0 = time.time()
    ranked = b.rank_trends(trends, cfg, limit=3)
    print(f"  rank_trends em {time.time() - t0:.1f}s:", [(t.topic, t.category, t.score, t.queries) for t in ranked])
    check(ranked, "rank_trends vazio")
    return f"JSON ok ({len(items)} itens crus), {len(plans)} cortes"


@step("7. faster-whisper small: trecho de 60 s")
def t_whisper():
    from fabrica import transcribe

    if "--sem-whisper" in ARGS:
        raise SkipTest("--sem-whisper")
    if OFFLINE:
        raise SkipTest("--sem-rede")
    import yt_dlp

    vid = (CTX.get("video").id.split(":", 1)[1]) if CTX.get("video") else VIDEO_ID
    TEST_DIR.mkdir(parents=True, exist_ok=True)
    opts = {**ytdlp_base(), "format": "bestaudio[ext=m4a]/bestaudio", "outtmpl": str(TEST_DIR / "%(id)s.audio.%(ext)s")}
    with yt_dlp.YoutubeDL(opts) as y:
        y.download([f"https://www.youtube.com/watch?v={vid}"])
    audio = next(TEST_DIR.glob(f"{vid}.audio.*"))
    print(f"  áudio: {audio.name} {audio.stat().st_size / 1e6:.1f} MB")
    cfg = load_config()
    cfg.set("transcricao.modelo_whisper", "small")
    t0 = time.time()
    transcribe.get_model("small", int(cfg.get("transcricao.threads", 0) or 0))
    load_s = time.time() - t0
    start, end = 120.0, 180.0
    t0 = time.time()
    tr = transcribe.transcribe(audio, cfg, start=start, end=end)
    el = time.time() - t0
    words = tr.words()
    print(f"  modelo carregado em {load_s:.1f}s; 60 s transcritos em {el:.1f}s (RTF {el / 60:.2f}); {len(words)} palavras")
    for w in words[:15]:
        print(f"    {w.start:6.2f}-{w.end:6.2f} {w.text}")
    print("  texto:", tr.text[:200])
    check(len(words) > 60, "poucas palavras")
    check(words[0].start < 5 and words[-1].end <= 60.5, "tempos devem ser relativos ao inicio do trecho")
    check(all(b.start >= a.start for a, b in zip(words, words[1:])), "palavras fora de ordem")
    # loudness / sinais com audio
    c = CTX.get("video")
    if c is not None and CTX.get("transcript"):
        c.extra["audio_path"] = str(audio)
        sig = signals.compute_signals(c, CTX["transcript"])
        print("  sinais com áudio:", signals.describe(sig), "| picos:", signals.loudness_peaks(audio, top=3))
        check("volume" in sig.available, "sinal de volume")
    CTX["rtf"] = el / 60
    return f"RTF small = {el / 60:.2f} ({len(words)} palavras)"


def cleanup():
    from fabrica.brain import OllamaBrain, clear_cache

    if CTX.get("ollama_started"):
        OllamaBrain.stop_started_server()
        print("  servidor Ollama iniciado pelo teste foi encerrado")
    clear_cache()
    if "--manter" not in ARGS:
        shutil.rmtree(TEST_DIR, ignore_errors=True)
        print(f"  {TEST_DIR} apagado")


def main() -> int:
    paths.ensure_dirs()
    for fn in (t_parse_samples, t_finalize, t_json_and_claude_mock, t_claude_real, t_real_heuristic, t_ollama, t_whisper):
        fn()
    print("\n=== limpeza ===")
    cleanup()
    print("\n=== RESUMO ===")
    ok = True
    for name, passed, info in RESULTS:
        print(f"{'OK    ' if passed else 'FALHOU'} {name}: {info}")
        ok = ok and passed
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
