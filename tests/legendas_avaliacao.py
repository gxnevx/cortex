"""Avaliacao da legenda do Whisper (WER e velocidade) contra legendas MANUAIS do YouTube.

Uso (sempre com o Python do projeto, cwd = raiz do projeto):
    python tests/legendas_avaliacao.py preparar          # baixa legenda manual + trecho de audio (45-60 s)
    python tests/legendas_avaliacao.py rodar small base,hotwords
    python tests/legendas_avaliacao.py tabela
    python tests/legendas_avaliacao.py limpar            # apaga as midias de teste

Verdade de referencia: legenda manual pt (writesubtitles, nunca a automatica). Videos com legenda "manual" que
e so copia do ASR do YouTube (mascara "[ __ ]", &nbsp;, texto igual ao automatico) foram descartados.
WER normalizado: minusculas, sem pontuacao, numeros por extenso, pra/para, ta/esta etc. (ver normalize()).
Regra da maquina: antes de cada job pesado espera nao haver outro ffmpeg.exe rodando; 1 job por vez; 6 threads.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import statistics
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fabrica import paths, tools, transcribe  # noqa: E402
from fabrica.config import load_config  # noqa: E402

DIR = paths.TMP / "leval"
RESULTS = DIR / "resultados.jsonl"

# (id do video, fracao do video onde comeca o trecho, tipo)
VIDEOS = [
    ("V7R4idWK518", 0.40, "podcast (Eu Nao Mordo, JuvTV)"),
    ("CxCD0XZJyPM", 0.45, "podcast (Emicida e Sergio Vaz)"),
    ("tH-Nuqm8zms", 0.45, "entrevista/debate TV 1994 (Roda Viva)"),
    ("YTlQ_2SaQmM", 0.30, "esquete, dialogo rapido (Porta dos Fundos)"),
]
MIN_S, MAX_S = 45.0, 60.0

OLD_VAD = {"min_silence_duration_ms": 500, "speech_pad_ms": 300}          # VAD do pipeline antigo
FINE_VAD = {"threshold": 0.35, "min_silence_duration_ms": 300, "speech_pad_ms": 400}

VARIANTS: dict[str, dict] = {
    # nome: {"prompt": passa prompt= ao transcribe (padrao atual), "opts": sobrescreve kwargs do Whisper}
    # "@P" = prompt de build_prompt(titulo, canal, descricao)
    "base": {"prompt": False, "opts": {"vad_parameters": OLD_VAD}},                       # pipeline antigo
    "prompt_ini": {"prompt": False, "opts": {"vad_parameters": OLD_VAD, "initial_prompt": "@P"}},
    "hotwords": {"prompt": False, "opts": {"vad_parameters": OLD_VAD, "hotwords": "@P"}},
    "ini+hot": {"prompt": False, "opts": {"vad_parameters": OLD_VAD, "initial_prompt": "@P", "hotwords": "@P"}},
    "cond_prev": {"prompt": False, "opts": {"vad_parameters": OLD_VAD, "initial_prompt": "@P",
                                            "condition_on_previous_text": True}},
    "beam1": {"prompt": False, "opts": {"vad_parameters": OLD_VAD, "initial_prompt": "@P", "beam_size": 1}},
    "temp0": {"prompt": False, "opts": {"vad_parameters": OLD_VAD, "initial_prompt": "@P", "temperature": 0.0}},
    "sem_vad": {"prompt": False, "opts": {"initial_prompt": "@P", "vad_filter": False}},
    "vad_fino": {"prompt": False, "opts": {"initial_prompt": "@P", "vad_parameters": FINE_VAD}},
    "best": {"prompt": True, "opts": {}},          # padrao atual do transcribe(): prompt + VAD fino
    "best_tempo_cru": {"prompt": True, "opts": {}, "raw_timing": True},   # sem o ajuste de tempo do karaoke
}


# ---------------------------------------------------------------- utilidades
def wait_no_ffmpeg(max_wait_s: float = 1800) -> None:
    """Regra da maquina: nao roda job pesado se outro ffmpeg.exe estiver rodando."""
    t0 = time.time()
    while time.time() - t0 < max_wait_s:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ffmpeg.exe", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, errors="replace").stdout
        if "ffmpeg.exe" not in out.lower():
            return
        print("  outro ffmpeg rodando; esperando 30 s...", flush=True)
        time.sleep(30)


class _Cfg:
    def __init__(self, base, **over):
        self.base, self.over = base, over

    def get(self, k, d=None):
        return self.over[k] if k in self.over else self.base.get(k, d)


_UNI = ["zero", "um", "dois", "três", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez", "onze", "doze",
        "treze", "catorze", "quinze", "dezesseis", "dezessete", "dezoito", "dezenove"]
_DEZ = ["", "", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"]
_CEM = ["", "cento", "duzentos", "trezentos", "quatrocentos", "quinhentos", "seiscentos", "setecentos",
        "oitocentos", "novecentos"]


def num_pt(n: int) -> str:
    if n < 20:
        return _UNI[n]
    if n < 100:
        return _DEZ[n // 10] + ("" if n % 10 == 0 else " e " + _UNI[n % 10])
    if n == 100:
        return "cem"
    if n < 1000:
        return _CEM[n // 100] + ("" if n % 100 == 0 else " e " + num_pt(n % 100))
    if n < 1_000_000:
        k, r = divmod(n, 1000)
        head = "mil" if k == 1 else num_pt(k) + " mil"
        if r == 0:
            return head
        return head + (" e " if r < 100 or r % 100 == 0 else " ") + num_pt(r)
    m, r = divmod(n, 1_000_000)
    head = "um milhão" if m == 1 else num_pt(m) + " milhões"
    return head if r == 0 else head + " " + num_pt(r)


_FILLERS = {"ah", "eh", "éh", "hã", "hum", "hmm", "hm", "uh", "uhum", "ahn", "ãh", "aham", "ã", "uhm", "mm"}
_MAP = {"pra": "para", "pro": "para o", "pros": "para os", "pras": "para as", "tá": "está",
        "tô": "estou", "tava": "estava", "tavam": "estavam", "tamo": "estamos", "cê": "você",
        "ocê": "você", "okay": "ok", "quatorze": "catorze", "uma": "um", "duas": "dois", "né": "né"}


def normalize(text: str) -> list[str]:
    """Texto -> palavras para WER (mesma regra para referencia e Whisper)."""
    s = unicodedata.normalize("NFC", text or "")
    s = re.sub(r"\b[A-Z]\w+(?: [A-Z]\w+){0,2}: ", " ", s)                    # "Fernando Mitre: " (falante)
    s = s.lower()
    s = re.sub(r"\[[^\]]*\]|\([^)]*\)|<[^>]*>|♪", " ", s)            # [risos] (musica) tags
    s = re.sub(r"^\s*[\w ]{1,20}:\s", " ", s)                                  # "fulano: "
    s = re.sub(r"(?:r\$|us\$)\s*([\d.,]+)", lambda m: m.group(1) + (" reais" if m.group(0).startswith("r") else " dólares"), s)
    s = s.replace("%", " por cento ")
    s = re.sub(r"(\d)\.(\d{3})", r"\1\2", s)
    s = re.sub(r"(\d)\.(\d{3})", r"\1\2", s)
    s = re.sub(r"(\d+),(\d+)", lambda m: f"{m.group(1)} vírgula {m.group(2)}", s)
    s = re.sub(r"\d+", lambda m: " " + num_pt(int(m.group(0))) + " " if len(m.group(0)) < 10 else m.group(0), s)
    s = re.sub(r"[^\w\s" + BAD + "]|_", " ", s)
    out: list[str] = []
    for w in s.split():
        if w in _FILLERS:
            continue
        out.extend(_MAP.get(w, w).split())
    return out


BAD = chr(0xFFFD)      # legenda antiga com acento quebrado: o caractere vale como coringa


def _eq(r: str, h: str) -> bool:
    if r == h:
        return True
    return BAD in r and re.fullmatch(re.escape(r).replace(re.escape(BAD), "."), h) is not None


def wer(ref: list[str], hyp: list[str]) -> tuple[float, int, int, int, int]:
    """(wer, substituicoes, delecoes, insercoes, n_ref)."""
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            c = 0 if _eq(ref[i - 1], hyp[j - 1]) else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + c)
    i, j, S, D, I = n, m, 0, 0, 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (0 if _eq(ref[i - 1], hyp[j - 1]) else 1):
            S += not _eq(ref[i - 1], hyp[j - 1])
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            D += 1
            i -= 1
        else:
            I += 1
            j -= 1
    return (d[n][m] / max(1, n), S, D, I, n)


def align_stats(hyp_words: list, ref_words: list) -> dict:
    """Compara o inicio de cada palavra do Whisper com o ASR do YouTube (tempo por palavra, ~0,1 s de erro)."""
    def key(w):
        t = normalize(w["text"] if isinstance(w, dict) else w.text)
        return t[0] if t else ""
    hk = [key(w) for w in hyp_words]
    rk = [key(w) for w in ref_words]
    sm = difflib.SequenceMatcher(None, hk, rk, autojunk=False)
    diffs: list[tuple[float, float]] = []
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            hw, rw = hyp_words[a + k], ref_words[b + k]
            hs = hw["start"] if isinstance(hw, dict) else hw.start
            diffs.append((rw["start"], hs - rw["start"]))
    if len(diffs) < 10:
        return {}
    ab = sorted(abs(x) for _, x in diffs)
    third = max(1, len(diffs) // 3)
    first = statistics.median(x for _, x in diffs[:third])
    last = statistics.median(x for _, x in diffs[-third:])
    bias = statistics.median(x for _, x in diffs)
    jit = sorted(abs(x - bias) for _, x in diffs)      # erro sem o atraso constante (que pode ser da referencia)
    return {"n": len(diffs), "med_abs": round(statistics.median(ab), 3), "p90_abs": round(ab[int(0.9 * (len(ab) - 1))], 3),
            "gt300ms": round(sum(1 for x in ab if x > 0.3) / len(ab), 3), "vies": round(bias, 3),
            "jit_med": round(statistics.median(jit), 3), "jit_p90": round(jit[int(0.9 * (len(jit) - 1))], 3),
            "jit_gt250": round(sum(1 for x in jit if x > 0.25) / len(jit), 3), "deriva": round(last - first, 3)}


# ---------------------------------------------------------------- preparar
def _vtt_cues(path: Path) -> list[tuple[float, float, str]]:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")      # legendas antigas em latin-1
    cues = transcribe._parse_cues(text)
    out = []
    for s, e, body in cues:
        txt = " ".join(transcribe._clean_line(b) for b in body).strip()
        if txt:
            out.append((s, e, txt))
    return out


def prepare() -> None:
    import yt_dlp

    from fabrica import download

    cfg = load_config()
    DIR.mkdir(parents=True, exist_ok=True)
    for vid, frac, kind in VIDEOS:
        meta_p = DIR / f"{vid}.json"
        if meta_p.exists():
            print("ja preparado:", vid)
            continue
        url = f"https://www.youtube.com/watch?v={vid}"
        info = download.fetch_info(url, cfg)
        manual = [k for k in (info.get("subtitles") or {}) if k.split("-")[0] == "pt"]
        if not manual:
            print("sem legenda manual pt:", vid)
            continue
        o = download.ytdlp_opts(cfg, skip_download=True, writesubtitles=True, subtitleslangs=manual[:1],
                                subtitlesformat="vtt", outtmpl=str(DIR / f"{vid}.man.%(ext)s"))
        with yt_dlp.YoutubeDL(o) as y:
            y.download([url])
        auto = [k for k in (info.get("automatic_captions") or {}) if k == "pt-orig"]
        if auto:
            o = download.ytdlp_opts(cfg, skip_download=True, writeautomaticsub=True, subtitleslangs=auto,
                                    subtitlesformat="json3", outtmpl=str(DIR / f"{vid}.auto.%(ext)s"))
            with yt_dlp.YoutubeDL(o) as y:
                y.download([url])
        man = next(DIR.glob(f"{vid}.man.*.vtt"))
        cues = _vtt_cues(man)
        dur = float(info.get("duration") or cues[-1][1])
        t_target = dur * frac
        i0 = next(i for i, c in enumerate(cues) if c[0] >= t_target)
        chosen = []
        for c in cues[i0:]:
            if c[1] - cues[i0][0] > MAX_S:
                break
            chosen.append(c)
        if chosen[-1][1] - chosen[0][0] < MIN_S:
            print("trecho curto demais:", vid)
        ws, we = max(0.0, chosen[0][0] - 0.25), chosen[-1][1] + 0.25
        ref = " ".join(c[2] for c in chosen)
        auto_words = []
        af = list(DIR.glob(f"{vid}.auto.*.json3"))
        if af:
            tr = transcribe.parse_subtitles(af[0])
            auto_words = [{"start": round(w.start - ws, 3), "end": round(w.end - ws, 3), "text": w.text}
                          for w in tr.words() if ws <= w.start <= we]
        # audio: melhor faixa de audio (como no corte final), so o trecho
        wait_no_ffmpeg()
        fmts = [f for f in info["formats"] if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")
                and f.get("ext") == "m4a"]
        f = max(fmts, key=lambda f: f.get("abr") or 0)
        audio = DIR / f"{vid}.m4a"
        args = [tools.ffmpeg(), "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-ss", f"{ws:.3f}",
                "-i", f["url"], "-t", f"{we - ws:.3f}", "-vn", "-c:a", "aac", "-b:a", "128k", str(audio)]
        r = subprocess.run([str(a) for a in args], capture_output=True, text=True, errors="replace", timeout=600)
        if r.returncode != 0:
            print("falha no audio:", vid, r.stderr[-300:])
            continue
        meta = {"id": vid, "tipo": kind, "title": info.get("title"), "channel": info.get("channel"),
                "description": (info.get("description") or "")[:3000], "ws": ws, "we": we, "dur": we - ws,
                "ref": ref, "auto_words": auto_words}
        meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"ok {vid}: {we - ws:.1f}s, {len(normalize(ref))} palavras ref, {len(auto_words)} palavras ASR")


# ---------------------------------------------------------------- rodar
def run(model: str, variants: list[str]) -> None:
    base_cfg = load_config()
    cfg = _Cfg(base_cfg, **{"transcricao.threads": 6})
    metas = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(DIR.glob("*.json"))]
    wait_no_ffmpeg()
    t0 = time.time()
    transcribe.get_model(model, 6)
    load_s = time.time() - t0
    print(f"modelo {model} carregado em {load_s:.1f}s")
    for vname in variants:
        v = VARIANTS[vname]
        for m in metas:
            P = transcribe.build_prompt(m["title"], m["channel"], m["description"])
            opts = {k: (P if val == "@P" else val) for k, val in v["opts"].items()}
            wait_no_ffmpeg()
            fix = transcribe._fix_word_timing
            if v.get("raw_timing"):
                transcribe._fix_word_timing = lambda toks, **k: toks
            t1 = time.time()
            try:
                tr = transcribe.transcribe(DIR / f"{m['id']}.m4a", cfg, model_name=model, language="pt",
                                           prompt=P if v["prompt"] else None, options=opts)
            finally:
                transcribe._fix_word_timing = fix
            el = time.time() - t1
            hyp = tr.text
            w, S, D, I, n = wer(normalize(m["ref"]), normalize(hyp))
            al = align_stats([{"start": x.start, "text": x.text} for x in tr.words()], m["auto_words"]) if m["auto_words"] else {}
            row = {"modelo": model, "variante": vname, "video": m["id"], "wer": round(w, 4), "S": S, "D": D, "I": I,
                   "n_ref": n, "seg": round(el, 2), "rtf": round(el / m["dur"], 3), "dur": round(m["dur"], 1),
                   "alinhamento": al, "hyp": hyp, "ts": time.time(),
                   "words": [[round(x.start, 3), round(x.end, 3), x.text] for x in tr.words()]}
            with open(RESULTS, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"{model:15s} {vname:10s} {m['id']}  WER {w:6.1%}  RTF {el / m['dur']:.2f}  {al}", flush=True)
    transcribe.unload_models()


def table(markdown: bool = False) -> None:
    rows = [json.loads(x) for x in RESULTS.read_text(encoding="utf-8").splitlines() if x.strip()]
    last: dict[tuple, dict] = {}
    for r in rows:
        last[(r["modelo"], r["variante"], r["video"])] = r
    agg: dict[tuple, list] = {}
    for (mo, va, _), r in last.items():
        agg.setdefault((mo, va), []).append(r)
    vids = sorted({k[2] for k in last})
    head = ["modelo", "variante", "WER", "RTF"] + [v[:6] for v in vids] + ["jit_med", "jit>250ms", "deriva"]
    if markdown:
        print("| " + " | ".join(head) + " |")
        print("|" + "---|" * len(head))
    else:
        print(f"{head[0]:16s} {head[1]:10s} {'WER':>6s} {'RTF':>5s} " + " ".join(f"{v:>7s}" for v in head[4:-3])
              + "  jit_med  >250ms  deriva")
    for (mo, va), rs in sorted(agg.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        if len(rs) < len(vids):
            continue
        errs = sum(r["S"] + r["D"] + r["I"] for r in rs)
        n = sum(r["n_ref"] for r in rs)
        rtf = sum(r["seg"] for r in rs) / sum(r["dur"] for r in rs)
        per = {r["video"]: r["wer"] for r in rs}
        als = [r["alinhamento"] for r in rs if r.get("alinhamento") and "jit_med" in r["alinhamento"]]
        med = statistics.mean(a["jit_med"] for a in als) if als else float("nan")
        gt = statistics.mean(a["jit_gt250"] for a in als) if als else float("nan")
        dr = statistics.mean(abs(a["deriva"]) for a in als) if als else float("nan")
        cells = [mo, va, f"{errs / max(1, n):.1%}", f"{rtf:.2f}"] + [f"{per.get(v, float('nan')):.1%}" for v in vids]             + [f"{med:.3f}", f"{gt:.1%}", f"{dr:.3f}"]
        if markdown:
            print("| " + " | ".join(cells) + " |")
        else:
            print(f"{cells[0]:16s} {cells[1]:10s} {cells[2]:>6s} {cells[3]:>5s} " + " ".join(f"{c:>7s}" for c in cells[4:-3])
                  + f"  {cells[-3]:>7s}  {cells[-2]:>6s}  {cells[-1]:>6s}")


def clean() -> None:
    import shutil

    shutil.rmtree(DIR, ignore_errors=True)
    print("apagado:", DIR)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "tabela"
    if cmd == "preparar":
        prepare()
    elif cmd == "rodar":
        run(sys.argv[2], sys.argv[3].split(",") if len(sys.argv) > 3 else ["base"])
    elif cmd == "tabela":
        table(markdown="--md" in sys.argv)
    elif cmd == "recalcular":      # refaz o WER das linhas salvas (depois de mudar a normalizacao)
        metas = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in DIR.glob("*.json")}
        rows = [json.loads(x) for x in RESULTS.read_text(encoding="utf-8").splitlines() if x.strip()]
        for r in rows:
            w, S, D, I, n = wer(normalize(metas[r["video"]]["ref"]), normalize(r["hyp"]))
            r.update(wer=round(w, 4), S=S, D=D, I=I, n_ref=n)
        RESULTS.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        table()
    elif cmd == "limpar":
        clean()
    else:
        print(__doc__)
