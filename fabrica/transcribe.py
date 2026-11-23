"""Transcricao: legendas da plataforma (.json3/.vtt/.srt) e faster-whisper (CPU int8).

Contratos:
    parse_subtitles(path) -> Transcript
    transcribe(media, cfg, start=None, end=None, word_timestamps=True, language="pt", prompt=None,
               purpose="auto") -> Transcript
        # tempos RELATIVOS a `start` (0 = start); language=None detecta o idioma (Transcript.language)
    build_prompt(title, channel="", description="") -> str     # contexto (nomes/termos) para o Whisper
    detect_language_media(media, cfg, start=None, end=None) -> (idioma, probabilidade)

Modelos (avaliacao em docs/LEGENDAS.md):
    transcricao.modelo_legenda  -> legenda final do corte (trecho curto com start/end)
    transcricao.modelo_whisper  -> audio longo, so para achar momentos
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

# Antes de importar huggingface_hub/faster_whisper (Windows sem symlink, sem telemetria)
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")      # evita conflito de OpenMP no Windows
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")

from . import log, paths, tools  # noqa: E402
from .models import Segment, Transcript, Word  # noqa: E402
from .util import CREATE_NO_WINDOW, run_cmd, short_hash  # noqa: E402

logger = log.get(__name__)

# Limites da segmentacao em "frases"
MAX_SEG_S = 12.0
MAX_SEG_WORDS = 45
MAX_WORD_S = 1.5                 # palavra de legenda automatica nunca dura mais que isso
_SENT_END = re.compile(r"[.!?…]+[\"')\]]*$")
_NOTE_RE = re.compile(r"\[[^\]]{1,40}\]|>>")              # [Música], [Risos], [Aplausos], >> (troca de falante)
_DASHES = {"-", "\u2013", "\u2014"}                       # "- fala" em legendas de dialogo
_TS_TAG = re.compile(r"<(\d{1,2}:)?\d{2}:\d{2}[.,]\d{3}>")
_ANY_TAG = re.compile(r"</?[^>]{0,40}>")
_CUE_RE = re.compile(
    r"^\s*((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})"
)
_ASS_OVERRIDE = re.compile(r"\{\\[^}]*\}")


# ----------------------------------------------------------------------------------------
# Estrutura interna
# ----------------------------------------------------------------------------------------
@dataclass
class _Tok:
    start: float
    end: float
    text: str
    note: bool = False           # anotacao tipo [Risos] (vai no texto, nao vira palavra)


def _ts_to_s(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    sec = 0.0
    for p in parts:
        sec = sec * 60 + float(p)
    return sec


def _split_tokens(text: str) -> list[tuple[str, bool]]:
    """Separa texto em tokens; anotacoes entre colchetes viram um token so."""
    out: list[tuple[str, bool]] = []
    pos = 0
    for m in _NOTE_RE.finditer(text):
        out.extend((w, w in _DASHES) for w in text[pos:m.start()].split())
        out.append((m.group(0), True))
        pos = m.end()
    out.extend((w, w in _DASHES) for w in text[pos:].split())
    return out


def _distribute(text: str, t0: float, t1: float) -> list[_Tok]:
    """Distribui as palavras de um trecho de legenda ao longo de [t0, t1] proporcional ao tamanho."""
    toks = _split_tokens(text)
    if not toks:
        return []
    t1 = max(t1, t0 + 0.05 * len(toks))
    weights = [len(t) + 2 for t, _ in toks]
    total = float(sum(weights))
    out, cur = [], t0
    for (tok, note), w in zip(toks, weights):
        d = (t1 - t0) * w / total
        out.append(_Tok(cur, cur + d, tok, note))
        cur += d
    return out


def _fix_ends(toks: list[_Tok], cap: float | None = MAX_WORD_S) -> list[_Tok]:
    """Ordena, remove duplicadas e garante que cada palavra termina antes da proxima comecar."""
    toks = sorted(toks, key=lambda t: t.start)
    dedup: list[_Tok] = []
    for t in toks:
        if dedup and abs(dedup[-1].start - t.start) < 0.011 and dedup[-1].text == t.text:
            continue
        if dedup and t.note and t.text == ">>" and dedup[-1].text == ">>":
            continue
        dedup.append(t)
    for i, t in enumerate(dedup):
        if i + 1 < len(dedup) and dedup[i + 1].start > t.start:
            t.end = min(t.end, dedup[i + 1].start)
        if cap:
            t.end = min(t.end, t.start + cap)
        if t.end <= t.start:
            t.end = t.start + 0.05
    return dedup


def _build_segments(toks: list[_Tok], max_s: float = MAX_SEG_S) -> list[Segment]:
    """Agrupa palavras em segmentos "frase" (pontuacao, pausas, ate ~12 s)."""
    segs: list[Segment] = []
    cur: list[_Tok] = []

    def flush():
        if not cur:
            return
        text = re.sub(r"\s+", " ", " ".join(t.text for t in cur)).strip()
        words = [Word(round(t.start, 3), round(t.end, 3), t.text) for t in cur if not t.note]
        if text:
            segs.append(Segment(round(cur[0].start, 3), round(cur[-1].end, 3), text, words))
        cur.clear()

    for tok in toks:
        if cur:
            dur = cur[-1].end - cur[0].start
            gap = tok.start - cur[-1].end
            last = cur[-1].text
            if dur < 5:
                soft_gap = 0.7
            elif dur < 8:
                soft_gap = 0.4
            else:
                soft_gap = 0.22
            brk = (
                gap >= 1.2
                or (tok.end - cur[0].start) > max_s
                or (bool(_SENT_END.search(last)) and dur >= 1.0)
                or (last.endswith((",", ";", ":")) and dur >= 7.0)
                or (gap >= soft_gap and dur >= 2.5)
                or len(cur) >= MAX_SEG_WORDS
                or (tok.note != cur[-1].note and dur >= 2.0)
                or (tok.note and tok.text == ">>")
            )
            if brk:
                flush()
        cur.append(tok)
    flush()
    return segs


# ----------------------------------------------------------------------------------------
# Legendas da plataforma
# ----------------------------------------------------------------------------------------
def _parse_json3(data: dict) -> list[_Tok]:
    toks: list[_Tok] = []
    has_word_timing = False
    events = []
    for ev in data.get("events") or []:
        segs = ev.get("segs")
        if not segs or ev.get("aAppend"):
            continue
        t0 = float(ev.get("tStartMs", 0)) / 1000.0
        dur = float(ev.get("dDurationMs", 0) or 0) / 1000.0
        pieces = []
        for s in segs:
            txt = html.unescape(s.get("utf8", "") or "")
            if not txt.strip():
                continue
            if "tOffsetMs" in s:
                has_word_timing = True
            pieces.append((t0 + float(s.get("tOffsetMs", 0) or 0) / 1000.0, txt.replace("\n", " ")))
        if pieces:
            events.append((t0, t0 + (dur if dur > 0 else 2.0), pieces))
    events.sort(key=lambda e: e[0])
    for k, (t0, t_end, pieces) in enumerate(events):
        # no ASR do YouTube a duracao do evento e o tempo na tela (sobrepoe o proximo): limita no proximo evento
        if k + 1 < len(events) and events[k + 1][0] > t0:
            t_end = min(t_end, events[k + 1][0])
        for i, (ps, txt) in enumerate(pieces):
            pe = pieces[i + 1][0] if i + 1 < len(pieces) else t_end
            toks.extend(_distribute(txt, ps, max(pe, ps + 0.05)))
    return _fix_ends(toks, MAX_WORD_S if has_word_timing else None)


def _parse_cues(text: str) -> list[tuple[float, float, list[str]]]:
    """Le blocos VTT/SRT -> (inicio, fim, linhas cruas)."""
    cues = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i, n = 0, len(lines)
    while i < n:
        m = _CUE_RE.match(lines[i])
        if not m:
            i += 1
            continue
        start, end = _ts_to_s(m.group(1)), _ts_to_s(m.group(2))
        i += 1
        body = []
        # linhas so com espaco (" ") fazem parte do bloco no VTT do YouTube; bloco termina na linha vazia
        while i < n and lines[i] != "" and not _CUE_RE.match(lines[i]):
            body.append(lines[i])
            i += 1
        # SRT: a linha seguinte pode ser o numero do proximo bloco
        if body and body[-1].strip().isdigit() and i < n and _CUE_RE.match(lines[i] if i < n else ""):
            body.pop()
        cues.append((start, end, body))
    return cues


def _clean_line(s: str) -> str:
    s = _ASS_OVERRIDE.sub("", s)
    s = _ANY_TAG.sub("", s)
    s = html.unescape(s).replace("​", "")
    return re.sub(r"\s+", " ", s).strip()


def _parse_timed_line(line: str, cue_start: float, cue_end: float) -> list[_Tok]:
    """Linha VTT do YouTube com <00:00:01.234><c> palavra</c> -> palavras com tempo real."""
    parts = re.split(r"(<(?:\d{1,2}:)?\d{2}:\d{2}[.,]\d{3}>)", line)
    chunks: list[tuple[float, str]] = []
    t = cue_start
    for p in parts:
        if _TS_TAG.fullmatch(p or ""):
            t = _ts_to_s(p.strip("<>"))
            continue
        txt = _clean_line(p)
        if txt:
            chunks.append((t, txt))
    out: list[_Tok] = []
    for i, (ts, txt) in enumerate(chunks):
        te = chunks[i + 1][0] if i + 1 < len(chunks) else cue_end
        out.extend(_distribute(txt, ts, max(te, ts + 0.05)))
    return out


def _parse_vtt_srt(text: str) -> list[_Tok]:
    cues = _parse_cues(text)
    tagged = any(_TS_TAG.search(line) for _, _, body in cues for line in body)
    toks: list[_Tok] = []
    prev_lines: list[str] = []
    for start, end, body in cues:
        cleaned = [(b, _clean_line(b)) for b in body]
        plain_new = []
        for raw, ln in cleaned:
            if not ln:
                continue
            if _TS_TAG.search(raw):
                # YouTube: linha com marcacao por palavra = texto novo com tempo real
                toks.extend(_parse_timed_line(raw, start, end))
            elif ln not in prev_lines:
                # linha "rolante" repetida do bloco anterior e ignorada; so texto novo entra
                plain_new.append(ln)
        if plain_new:
            toks.extend(_distribute(" ".join(plain_new), start, end))
        prev_lines = [ln for _, ln in cleaned if ln]
    return _fix_ends(toks, MAX_WORD_S if tagged else None)


def parse_subtitles(path: str | Path) -> Transcript:
    """Le .json3 / .vtt / .srt e devolve Transcript em segmentos tipo frase, com tempo por palavra."""
    p = Path(path)
    raw = p.read_text(encoding="utf-8-sig", errors="replace")
    ext = p.suffix.lower()
    stripped = raw.lstrip()
    if ext == ".json3" or (ext not in (".vtt", ".srt") and stripped.startswith("{")):
        try:
            toks = _parse_json3(json.loads(raw))
        except json.JSONDecodeError:
            toks = _parse_vtt_srt(raw)
    else:
        toks = _parse_vtt_srt(raw)
    segs = _build_segments(toks)
    lang = "pt"
    m = re.search(r"\.([a-zA-Z]{2,3}(?:-[A-Za-z0-9]+)?)\.[a-z0-9]+$", p.name)
    if m:
        lang = m.group(1).split("-")[0].lower()
    tr = Transcript(segs, language=lang, source="youtube_subs" if segs else "vazio")
    logger.debug("legenda %s: %d segmentos, %d palavras, %.0fs", p.name, len(segs), len(tr.words()), tr.duration)
    return tr


# ----------------------------------------------------------------------------------------
# Whisper: modelos
# ----------------------------------------------------------------------------------------
_MODEL_CACHE: dict[tuple[str, int], object] = {}
_MODEL_LOCK = threading.Lock()
MAX_THREADS = 6                  # evita saturar a CPU

# Padroes medidos em docs/LEGENDAS.md (CPU de notebook, CPU int8, 6 threads)
DEFAULT_SELECTION_MODEL = "small"            # audio longo, so para achar momentos
DEFAULT_CAPTION_MODEL = "large-v3-turbo"     # legenda final do corte (precisa ser exata)
CAPTION_MAX_S = 150.0                         # trecho com start/end ate isso = legenda de corte


def _auto_threads() -> int:
    n = os.cpu_count() or 8
    return max(1, min(MAX_THREADS, n // 2 if n >= 8 else n))     # nucleos fisicos (SMT nao ajuda o CTranslate2)


def model_on_disk(name: str) -> bool:
    """True se o modelo ja esta em paths.MODELS (nao precisa de rede)."""
    from faster_whisper.utils import _MODELS

    repo = _MODELS.get(name, name)
    if "/" not in repo:
        return False
    d = paths.MODELS / ("models--" + repo.replace("/", "--")) / "snapshots"
    return d.is_dir() and any(p.joinpath("model.bin").is_file() for p in d.iterdir())


def get_model(name: str = "small", threads: int = 0):
    """Carrega (e guarda em cache) o WhisperModel. Baixa para paths.MODELS na primeira vez."""
    from faster_whisper import WhisperModel

    threads = min(MAX_THREADS, int(threads or 0) or _auto_threads())
    key = (name, threads)
    with _MODEL_LOCK:
        if key in _MODEL_CACHE:
            return _MODEL_CACHE[key]
        paths.MODELS.mkdir(parents=True, exist_ok=True)
        kw = dict(device="cpu", compute_type="int8", cpu_threads=threads, num_workers=1,
                  download_root=str(paths.MODELS))
        t0 = time.time()
        try:
            model = WhisperModel(name, local_files_only=True, **kw)      # sem rede se ja baixado
        except Exception:
            logger.info("Baixando modelo Whisper '%s' para %s (so na primeira vez)...", name, paths.MODELS)
            model = WhisperModel(name, local_files_only=False, **kw)
        logger.debug("whisper %s carregado em %.1fs (%d threads)", name, time.time() - t0, threads)
        _MODEL_CACHE[key] = model
        return model


def unload_models() -> None:
    """Libera os modelos Whisper da memoria (o autopilot chama entre ciclos; turbo ocupa ~1 GB de RAM)."""
    import gc

    with _MODEL_LOCK:
        n = len(_MODEL_CACHE)
        _MODEL_CACHE.clear()
    gc.collect()
    if n:
        logger.debug("whisper: %d modelo(s) liberado(s) da memoria", n)


def pick_model(cfg=None, span_s: float | None = None, purpose: str = "auto") -> str:
    """Escolhe o modelo: legenda de corte (curto) usa transcricao.modelo_legenda; o resto, modelo_whisper."""
    get = cfg.get if cfg is not None else (lambda k, d=None: d)
    sel = str(get("transcricao.modelo_whisper", DEFAULT_SELECTION_MODEL) or DEFAULT_SELECTION_MODEL)
    cap = str(get("transcricao.modelo_legenda", DEFAULT_CAPTION_MODEL) or "").strip() or sel
    lim = float(get("transcricao.legenda_max_s", CAPTION_MAX_S) or CAPTION_MAX_S)
    if purpose == "legenda" or (purpose == "auto" and span_s is not None and 0 < span_s <= lim):
        return cap
    return sel


# ----------------------------------------------------------------------------------------
# Audio
# ----------------------------------------------------------------------------------------
def extract_audio(media: str | Path, start: float | None, end: float | None, dest: Path | None = None) -> Path:
    """Extrai [start, end] como WAV 16 kHz mono (seek rapido antes do -i)."""
    ff = tools.ffmpeg()
    if not ff:
        raise RuntimeError("ffmpeg nao encontrado no PATH.")
    paths.TMP.mkdir(parents=True, exist_ok=True)
    dest = dest or paths.TMP / f"asr_{short_hash(f'{media}|{start}|{end}|{time.time()}')}.wav"
    args: list = [ff, "-nostdin", "-hide_banner", "-v", "error", "-y"]
    if start:
        args += ["-ss", f"{max(0.0, float(start)):.3f}"]
    args += ["-i", str(media)]
    if end is not None:
        args += ["-t", f"{max(0.05, float(end) - float(start or 0)):.3f}"]
    args += ["-vn", "-sn", "-dn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dest)]
    proc = run_cmd(args, timeout=600)
    if proc.returncode != 0 or not dest.exists() or dest.stat().st_size < 1000:
        raise RuntimeError(f"ffmpeg nao conseguiu extrair o audio de {media}: {(proc.stderr or '')[-500:]}")
    return dest


SAMPLE_RATE = 16000
CHUNK_S = 900.0          # midia longa e transcrita em blocos de 15 min (memoria + progresso)


def media_duration(media: str | Path) -> float | None:
    fp = tools.ffprobe()
    if not fp:
        return None
    proc = run_cmd([fp, "-v", "error", "-show_entries", "format=duration", "-of",
                    "default=noprint_wrappers=1:nokey=1", str(media)], timeout=60)
    try:
        return float((proc.stdout or "").strip().splitlines()[0])
    except (ValueError, IndexError):
        return None


def decode_audio(media: str | Path, start: float | None = None, end: float | None = None):
    """Decodifica [start, end] para float32 16 kHz mono via ffmpeg (nao depende do PyAV)."""
    import numpy as np

    ff = tools.ffmpeg()
    if not ff:
        raise RuntimeError("ffmpeg nao encontrado no PATH.")
    args: list = [ff, "-nostdin", "-hide_banner", "-v", "error"]
    if start:
        args += ["-ss", f"{max(0.0, float(start)):.3f}"]
    args += ["-i", str(media)]
    if end is not None:
        args += ["-t", f"{max(0.05, float(end) - float(start or 0)):.3f}"]
    args += ["-vn", "-sn", "-dn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"]
    proc = subprocess.run([str(a) for a in args], capture_output=True, creationflags=CREATE_NO_WINDOW,
                          timeout=1800)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace")[-500:]
        raise RuntimeError(f"ffmpeg nao conseguiu ler o audio de {media}: {err}")
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0


# ----------------------------------------------------------------------------------------
# Prompt (contexto para o Whisper acertar nomes e termos)
# ----------------------------------------------------------------------------------------
_URL_RE = re.compile(r"https?://\S+|www\.\S+|\S+@\S+|@\w+")
_HASH_RE = re.compile(r"#\w+")
_EMOJI_RE = re.compile("[\U0001F000-\U0001FFFF\u2600-\u27BF\uFE0F\u200D]+")
_SEP_RE = re.compile(r"\s*[|\u2022\u00B7\u2013\u2014/\\\[\]{}<>()]+\s*|\s+-\s+")
_NAME_RE = re.compile(r"\b([A-Z\u00C0-\u00DD][a-z\u00DF-\u00FF]+(?:\s+(?:d[aeo]s?\s+)?[A-Z\u00C0-\u00DD][a-z\u00DF-\u00FF]+){0,2})")
_NAME_STOP = {
    "O", "A", "Os", "As", "E", "Em", "No", "Na", "Nos", "Nas", "Do", "Da", "Dos", "Das", "De", "Um", "Uma", "Para",
    "Pra", "Por", "Com", "Sem", "Se", "Que", "Quem", "Como", "Quando", "Onde", "Mais", "Menos", "Muito", "Hoje",
    "Siga", "Sigam", "Inscreva", "Inscrevase", "Ative", "Assista", "Acesse", "Compre", "Use", "Link", "Cupom",
    "Instagram", "Youtube", "YouTube", "Twitter", "Tiktok", "TikTok", "Facebook", "Spotify", "Twitch", "Kick",
    "Apple", "Podcast", "Podcasts", "Canal", "Episodio", "Episódio", "Parte", "Live", "Clique", "Seja", "Membro",
    "Contato", "Email", "Comercial", "Patrocinio", "Patrocínio", "Apoie", "Loja", "Site", "Ep", "The", "And",
    "Of", "In", "On", "To", "For", "With", "Is", "It", "This", "That", "We", "You", "I", "My", "Our", "Your",
    "Follow", "Subscribe", "Watch", "Join", "Get", "Check", "Sponsored", "Thanks", "Thank", "All", "New", "Full",
}


def _decaps(s: str) -> str:
    """Titulo TODO EM MAIUSCULAS -> frase normal (prompt em caixa alta deixa o Whisper gritando)."""
    letters = [c for c in s if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.6:
        s = s.lower()
        s = s[:1].upper() + s[1:]
    return s


def _clean_prompt_piece(s: str) -> str:
    """Tira URL, hashtag, emoji e separadores ("|", "/"...) sem perder a pontuacao: o Whisper imita o estilo
    do prompt (prompt sem virgula/ponto = legenda sem virgula/ponto)."""
    s = _URL_RE.sub(" ", s or "")
    s = _HASH_RE.sub(" ", s)
    s = _EMOJI_RE.sub(" ", s)
    s = _SEP_RE.sub(" | ", s)
    s = re.sub(r"[\"'`*_~^=+]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    pieces = []
    for part in s.split("|"):
        part = part.strip(" ,;:-")
        if part:
            pieces.append(",".join(_decaps(x) if x.strip() else x for x in part.split(",")))
    out = ", ".join(pieces)
    out = re.sub(r"\s+([,.!?])", r"\1", out)
    out = re.sub(r"([,.!?])(?:\s*,)+", r"\1", out)
    return re.sub(r"\s+", " ", out).strip(" ,;:-")


def description_names(description: str, limit: int = 8) -> list[str]:
    """Nomes proprios/termos da descricao (pessoas, marcas, lugares), mais citados primeiro."""
    text = _URL_RE.sub(" ", description or "")
    text = _HASH_RE.sub(" ", text)
    counts: dict[str, int] = {}
    order: list[str] = []
    for line in text.splitlines():
        low = line.lower()
        if any(k in low for k in ("cupom", "desconto", "patroc", "parceiro", "link", "http", "inscreva", "siga ")):
            continue
        for m in _NAME_RE.finditer(line):
            name = m.group(1).strip()
            first = name.split()[0]
            if first in _NAME_STOP or len(name) < 3:
                continue
            before = line[:m.start()].rstrip()
            if " " not in name and (not before or before[-1] in ".!?:"):
                continue            # palavra comum no inicio da frase ("Neste episodio...")
            if name not in counts:
                order.append(name)
            counts[name] = counts.get(name, 0) + 1
    pos = {n: i for i, n in enumerate(order)}
    order.sort(key=lambda n: (-counts[n], pos[n]))
    return order[:limit]


def build_prompt(title: str = "", channel: str = "", description: str = "", extra: Iterable[str] = (),
                 max_chars: int = 220) -> str:
    """Prompt curto para o Whisper: titulo + canal + nomes da descricao (ajuda a escrever nomes certos).

    Ex.: build_prompt(c.title, c.channel, c.description) -> "Como a comedia mudou a cabeca de Thiago Ventura,
    Achismos podcast. AchismosTV. Thiago Ventura, Afonso Padilha."
    """
    parts: list[str] = []
    found = description_names(description)
    t = _clean_prompt_piece(title)
    for n in found + [_clean_prompt_piece(channel)]:     # titulo em caixa alta perdeu as maiusculas dos nomes
        if n:
            t = re.sub(r"(?i)(?<!\w)" + re.escape(n) + r"(?!\w)", n, t)
    if t:
        parts.append(t.rstrip(".!?") + ".")
    ch = _clean_prompt_piece(channel)
    if ch and ch.lower() not in t.lower():
        parts.append(ch + ".")
    names = [n for n in list(extra or []) + found if n and n not in " ".join(parts)]
    if names:
        seen: list[str] = []
        for n in names:
            if n.lower() not in (x.lower() for x in seen):
                seen.append(n)
        parts.append(", ".join(seen) + ".")
    out = " ".join(parts)
    if len(out) > max_chars:
        out = out[:max_chars].rsplit(" ", 1)[0].rstrip(" ,") + "."
    return out


def clean_prompt(prompt: str | None, max_chars: int = 220) -> str:
    """Normaliza um prompt livre (ex.: 'TITULO EM CAIXA ALTA | #tag, canal') para o Whisper."""
    if not prompt:
        return ""
    s = _clean_prompt_piece(prompt)
    if len(s) > max_chars:
        s = s[:max_chars].rsplit(" ", 1)[0]
    s = s.strip(" ,")
    if s and s[-1].isalnum():
        s += "."
    return s


# ----------------------------------------------------------------------------------------
# Pos-processamento (legibilidade da legenda queimada)
# ----------------------------------------------------------------------------------------
# frases que o Whisper inventa em silencio/musica (vem das legendas usadas no treino)
_HALLU_HARD = ("amara.org", "legendas pela comunidade", "legendado por", "legendas por", "legenda por",
               "legendagem", "transcrição e legendas", "tradução e legendas",
               "subtitles by", "subtitled by", "subtítulos por", "subtítulos realizados",
               "sous-titres", "untertitel")
_HALLU_SOFT = ("obrigado por assistir", "obrigada por assistir", "obrigado por ver", "thanks for watching",
               "thank you for watching", "gracias por ver", "inscreva-se no canal", "se inscreva no canal",
               "ative o sininho", "deixe seu like", "até o próximo vídeo", "www.", ".com.br")
_BANNED_IN_CAPTION = {"\u2014": ",", "\u2013": ",", "\u2022": " ", "\u00B7": " ", "\u266A": " ", "\u266B": " "}
_PUNCT_ONLY = re.compile(r"^[^\w$]+$")
_KEEP_PUNCT = re.compile(r"[.,!?;:%\u2026\"')\]]")
_NUM_GROUPS_EN = re.compile(r"^(\d{1,3})((?:,\d{3}){2,})(\D*)$")      # 1,000,000 -> 1.000.000 (pt)


def _norm_tok(s: str) -> str:
    return re.sub(r"[^\w]+", "", s.lower())


def _is_hallucination(text: str, prompt: str = "", weak: bool = False) -> bool:
    """Frase inventada pelo Whisper. weak=True quando o segmento tem baixa confianca/fala curta."""
    t = text.lower().strip()
    if not t:
        return True
    if any(h in t for h in _HALLU_HARD):
        return True
    if weak and any(h in t for h in _HALLU_SOFT):
        return True
    if prompt:
        # eco do prompt (o Whisper repete o titulo quando ouve musica/silencio)
        nt = [_norm_tok(w) for w in t.split() if _norm_tok(w)]
        pw = [_norm_tok(w) for w in prompt.split() if _norm_tok(w)]
        if len(nt) >= 4 and " ".join(nt) in " ".join(pw) and (weak or len(nt) >= 0.75 * len(pw)):
            return True
    return False


def _clean_word_text(txt: str) -> str:
    for a, b in _BANNED_IN_CAPTION.items():
        txt = txt.replace(a, b)
    txt = txt.strip()
    txt = re.sub(r"^-+(?=\w)", "", txt)            # "-Fala" (marca de dialogo) -> "Fala"
    txt = re.sub(r"\s+", " ", txt)
    txt = re.sub(r"\s+([,.!?;:%])", r"\1", txt)
    txt = re.sub(r"([,!?;:])(?=[^\s\d\"')\].,!?;:])", r"\1 ", txt)
    return txt


def _collapse_repeats(toks: list[_Tok], max_n: int = 6) -> list[_Tok]:
    """Laco de alucinacao: 'que que que que que' -> 'que que que'; frase repetida 3+ vezes -> 2 vezes."""
    norm = [_norm_tok(t.text) for t in toks]
    out: list[_Tok] = []
    i, n_tok = 0, len(toks)
    while i < n_tok:
        done = False
        for n in range(1, max_n + 1):
            if i + 2 * n > n_tok:
                break
            pat = norm[i:i + n]
            if not all(pat):
                continue
            k = 1
            while norm[i + k * n:i + (k + 1) * n] == pat:
                k += 1
            keep, thresh = (3, 5) if n == 1 else (2, 3)
            if k >= thresh:
                out.extend(toks[i:i + keep * n])
                i += k * n
                done = True
                break
        if not done:
            out.append(toks[i])
            i += 1
    return out


def _fix_numbers(toks: list[_Tok], language: str = "pt") -> list[_Tok]:
    """Numeros legiveis em PT: '10 000' -> '10.000'; '1,000,000' -> '1.000.000'; '50 %' -> '50%'."""
    if not (language or "pt").startswith("pt"):
        return toks
    out: list[_Tok] = []
    for t in toks:
        txt = t.text
        m = _NUM_GROUPS_EN.match(txt)
        if m:
            txt = m.group(1) + m.group(2).replace(",", ".") + m.group(3)
        if (out and re.fullmatch(r"\d{3}[.,!?%]?", txt) and re.fullmatch(r"\d{1,3}(?:\.\d{3})*", out[-1].text)
                and t.start - out[-1].end < 0.6):
            out[-1].text = out[-1].text + "." + txt
            out[-1].end = t.end
            continue
        t.text = txt
        out.append(t)
    return out


def postprocess_tokens(toks: list[_Tok], language: str = "pt") -> list[_Tok]:
    """Limpa as palavras do Whisper para legenda: espacos, pontuacao solta, tracos, lacos e numeros."""
    out: list[_Tok] = []
    for t in toks:
        txt = _clean_word_text(t.text)
        if not txt:
            continue
        if _PUNCT_ONLY.match(txt):
            keep = "".join(_KEEP_PUNCT.findall(txt))
            if out and keep:
                out[-1].text += keep
                out[-1].end = max(out[-1].end, min(t.end, out[-1].end + 0.3))
            continue
        out.append(_Tok(t.start, t.end, txt, t.note))
    out = _collapse_repeats(out)
    out = _fix_numbers(out, language)
    return out


def _fix_word_timing(toks: list[_Tok], max_word_s: float = 1.6, lead_s: float = 0.35) -> list[_Tok]:
    """Tempo por palavra para o karaoke: sem sobreposicao, sem palavra 'esticada' sobre silencio.

    O DTW do Whisper costuma comecar cedo demais a primeira palavra depois de uma pausa (ela 'engole' o
    silencio). Palavra curta com duracao longa logo apos pausa tem o inicio puxado para perto do fim."""
    toks = sorted(toks, key=lambda t: t.start)
    prev_end = None
    for i, t in enumerate(toks):
        if prev_end is not None and t.start < prev_end:
            t.start = prev_end
        dur = t.end - t.start
        expect = 0.12 + 0.075 * len(re.sub(r"\W", "", t.text))      # ~ duracao natural da palavra
        after_pause = prev_end is None or t.start - prev_end > 0.05 or i == 0
        if after_pause and dur > max(1.2, expect * 3.0):
            t.start = max(t.start, t.end - max(expect * 1.6, lead_s))
        if t.end - t.start > max_word_s:
            t.end = t.start + max_word_s
        if t.end <= t.start:
            t.end = t.start + 0.05
        prev_end = t.end
    return toks


# ----------------------------------------------------------------------------------------
# Opcoes do Whisper
# ----------------------------------------------------------------------------------------
def whisper_options(cfg=None, language: str | None = "pt", prompt: str = "", captions: bool = True,
                    model: str = "") -> dict:
    """kwargs de WhisperModel.transcribe (os padroes vieram da avaliacao em docs/LEGENDAS.md)."""
    get = cfg.get if cfg is not None else (lambda k, d=None: d)
    beam = int(get("transcricao.beam_size", 5) or 5)
    small = str(model or "").startswith(("tiny", "base", "small"))
    # legenda com modelo grande: VAD mais sensivel (voz baixa/convidado longe do microfone nao some).
    # No small o VAD sensivel piorou (deixa entrar risada/ruido e ele inventa): fica o VAD padrao.
    fine_vad = captions and not small
    opts: dict = dict(
        language=language or None,
        beam_size=beam,
        vad_filter=True,
        vad_parameters=({"threshold": 0.35, "min_silence_duration_ms": 300, "speech_pad_ms": 400} if fine_vad
                        else {"min_silence_duration_ms": 500, "speech_pad_ms": 300}),
        condition_on_previous_text=False,      # evita lacos de alucinacao
        temperature=[0.0, 0.2, 0.4, 0.6],
    )
    if prompt and get("transcricao.usar_prompt", True):
        # initial_prompt (vale para a 1a janela de 30 s). NAO usar hotwords: na avaliacao ele fez o Whisper
        # pular frases inteiras (turbo: WER 7,8% -> 23,4% num video). Ver docs/LEGENDAS.md.
        opts["initial_prompt"] = prompt
    return opts


# ----------------------------------------------------------------------------------------
# Transcricao
# ----------------------------------------------------------------------------------------
def transcribe(
    media: str | Path,
    cfg=None,
    start: float | None = None,
    end: float | None = None,
    word_timestamps: bool = True,
    language: str | None = "pt",
    on_progress: Callable[[float], None] | None = None,
    model_name: str | None = None,
    prompt: str | None = None,
    purpose: str = "auto",
    options: dict | None = None,
) -> Transcript:
    """Transcreve com faster-whisper (CPU int8). Com start/end, so o trecho e os tempos sao relativos a start.

    language=None detecta o idioma (fica em Transcript.language). prompt = contexto curto (titulo, canal,
    nomes) que ajuda a acertar nomes/termos. purpose: "legenda" (legenda final do corte, modelo
    transcricao.modelo_legenda), "selecao" (achar momentos, transcricao.modelo_whisper) ou "auto" (trecho
    com start/end de ate transcricao.legenda_max_s = legenda). options sobrescreve kwargs do Whisper (testes).
    """
    media = Path(media)
    if not media.exists():
        raise FileNotFoundError(media)
    get = cfg.get if cfg is not None else (lambda k, d=None: d)
    threads = int(get("transcricao.threads", 0) or 0)

    base = float(start or 0.0)
    span = None
    if start is not None or end is not None:
        ranges: list[tuple[float | None, float | None]] = [(start, end)]
        total = (float(end) - base) if end is not None else (media_duration(media) or 0.0) - base
        span = total
    else:
        total = media_duration(media) or 0.0
        if purpose != "selecao" and 0 < total <= float(get("transcricao.legenda_max_s", CAPTION_MAX_S)):
            span = total
        if total > CHUNK_S * 1.2:
            ranges = []
            t = 0.0
            while t < total - 0.5:
                ranges.append((t, min(total, t + CHUNK_S)))
                t += CHUNK_S
        else:
            ranges = [(None, None)]

    name = model_name or pick_model(cfg, span, purpose)
    if not model_name and span is None and total > 600:
        # audio longo (achar momentos): pode usar um modelo mais rapido (ex.: base, RTF ~0,12)
        long_model = str(get("transcricao.modelo_whisper_longo", "") or "").strip()
        if long_model:
            name = long_model
    try:
        model = get_model(name, threads)
    except Exception as e:
        fb = str(get("transcricao.modelo_whisper", DEFAULT_SELECTION_MODEL) or DEFAULT_SELECTION_MODEL)
        if fb == name:
            raise
        logger.warning("Modelo Whisper '%s' indisponivel (%s); usando '%s'", name, e, fb)
        name = fb
        model = get_model(name, threads)

    is_caption = span is not None
    pr = clean_prompt(prompt) if prompt else ""
    t0 = time.time()
    toks: list[_Tok] = []
    plain: list[Segment] = []
    lang = language or None
    for (ra, rb) in ranges:
        audio = decode_audio(media, ra, rb)
        if audio.size < SAMPLE_RATE // 4:
            continue
        off = float(ra or 0.0) - base           # deslocamento do bloco em relacao a `start`
        opts = whisper_options(cfg, lang, pr, captions=is_caption, model=name)
        if options:
            opts.update(options)
        opts["word_timestamps"] = word_timestamps
        seg_iter, info = model.transcribe(audio, **opts)
        if not lang:
            lang = getattr(info, "language", None) or None   # blocos seguintes no mesmo idioma
            logger.debug("idioma detectado: %s (%.2f)", lang, float(getattr(info, "language_probability", 0) or 0))
        for s in seg_iter:
            weak = s.no_speech_prob > 0.35 or s.avg_logprob < -0.7 or s.compression_ratio > 2.4
            if _is_hallucination(s.text, pr, weak) or (s.no_speech_prob > 0.7 and s.avg_logprob < -1.0):
                logger.debug("descartado (alucinacao): %r", s.text[:80])
                continue
            if word_timestamps and s.words:
                for w in s.words:
                    txt = (w.word or "").strip()
                    if txt:
                        toks.append(_Tok(off + float(w.start), off + float(max(w.end, w.start + 0.02)), txt))
            elif s.text.strip():
                plain.append(Segment(round(off + s.start, 3), round(off + s.end, 3), s.text.strip(), []))
            if on_progress and total > 0:
                try:
                    on_progress(min(1.0, (off + s.end) / total))
                except Exception:
                    pass
    lang = lang or language or "pt"
    if word_timestamps:
        toks = postprocess_tokens(_fix_ends(toks, None), lang)
        toks = _fix_word_timing(toks)
        segs = _build_segments(toks)
    else:
        segs = plain
    if end is not None:
        lim = float(end) - base
        for sg in segs:
            sg.end = min(sg.end, lim)
            for w in sg.words:
                w.end = min(w.end, lim)
                w.start = min(w.start, max(0.0, w.end - 0.05))
    elapsed = time.time() - t0
    if total:
        logger.debug("whisper %s: %.0fs de audio em %.1fs (RTF %.2f)", name, total, elapsed, elapsed / total)
    return Transcript(segs, language=lang, source="whisper" if segs else "vazio")


def detect_language_media(media: str | Path, cfg=None, start: float | None = None, end: float | None = None,
                          model_name: str | None = None) -> tuple[str, float]:
    """Idioma falado em [start, end] (ate 60 s de fala). Usa o modelo de selecao (rapido)."""
    get = cfg.get if cfg is not None else (lambda k, d=None: d)
    name = model_name or str(get("transcricao.modelo_whisper", DEFAULT_SELECTION_MODEL) or DEFAULT_SELECTION_MODEL)
    model = get_model(name, int(get("transcricao.threads", 0) or 0))
    s = float(start or 0.0)
    e = float(end) if end is not None else s + 90.0
    audio = decode_audio(media, s, e)
    if audio.size < SAMPLE_RATE // 2:
        return "", 0.0
    lang, prob, _ = model.detect_language(audio, vad_filter=True, language_detection_segments=2)
    return str(lang or ""), float(prob or 0.0)


def transcript_from_words(words: Iterable[Word]) -> Transcript:
    """Utilitario: remonta um Transcript (segmentos tipo frase) a partir de palavras."""
    toks = [_Tok(w.start, w.end, w.text) for w in words]
    return Transcript(_build_segments(toks), source="whisper")
