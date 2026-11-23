"""Sinais baratos para achar momentos "quentes" de um video (sem IA).

- volume por segundo (ffmpeg -> PCM -> RMS em dBFS) + picos acima da base local
- velocidade da fala por janela
- palavras-chave de risada / polemica / surpresa / emocao / palavrao / gancho (pt-BR)
- "mais repetidos" do YouTube (Candidate.extra["heatmap"])
- clipes da Twitch/Kick (Candidate.extra["twitch_clips"])
- horarios citados nos comentarios top (Candidate.extra["comment_marks"], de download.enrich_candidate)
- picos do chat gravado (Candidate.extra["chat_spikes"], Twitch VOD / live do YouTube)

Tudo e opcional: se um sinal nao existe, os outros continuam funcionando.
signal_anchors(video) devolve [(tempo, peso)] dos sinais externos (para escolher janelas a transcrever).
"""
from __future__ import annotations

import math
import re
import subprocess
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import log, tools
from .models import Candidate, Transcript
from .util import CREATE_NO_WINDOW

logger = log.get(__name__)

# ----------------------------------------------------------------------------------------
# Lexico (texto normalizado: minusculo, sem acento)
# ----------------------------------------------------------------------------------------
KEYWORDS: dict[str, list[tuple[str, float]]] = {
    "risada": [
        (r"\bk{3,}\b", 1.2), (r"\b(?:ha){2,}h?\b", 1.0), (r"\b(?:he){3,}\b", 0.6), (r"\b(?:rs){2,}\b", 0.8),
        (r"\[(?:risos?|risadas?|gargalhadas?)[^\]]*\]", 1.2), (r"\bmorri\b", 0.7), (r"\bto morrendo\b", 0.8),
        (r"\bchorando de rir\b", 1.0), (r"\bque vergonha alheia\b", 0.8), (r"\bpalhacada\b", 0.6),
    ],
    "polemica": [
        (r"\bmentira\b", 1.0), (r"\bmentiros[oa]s?\b", 1.2), (r"\babsurd[oa]s?\b", 1.0), (r"\bpolemic[oa]s?\b", 1.0),
        (r"\bvergonh(?:a|oso|osa)\b", 0.9), (r"\bcala (?:a )?boca\b", 1.4), (r"\bridicul[oa]s?\b", 1.0),
        (r"\bhipocri(?:ta|tas|sia)\b", 1.1), (r"\bsafad[oa]s?\b", 0.9), (r"\bcanalhas?\b", 1.0), (r"\bladr(?:ao|oes|a)\b", 1.0),
        (r"\bcorrupt[oa]s?\b", 0.8), (r"\bfake news\b", 0.8), (r"\btreta\b", 1.0), (r"\bbriga\b", 0.7),
        (r"\bdesrespeito\b", 0.9), (r"\bfalta de respeito\b", 1.1), (r"\b(?:voce|vc) (?:ta|esta) errad[oa]\b", 1.0),
        (r"\bnao e verdade\b", 0.9), (r"\b(?:me )?deixa eu falar\b", 1.0), (r"\bescuta aqui\b", 1.0),
        (r"\bcom todo (?:o )?respeito\b", 0.8), (r"\bvagabund[oa]s?\b", 1.0), (r"\bpalhac[oa]s?\b", 0.9),
        (r"\bescandalo\b", 0.9), (r"\bgolpe\b", 0.6), (r"\bracis(?:ta|tas|mo)\b", 0.8), (r"\bmachis(?:ta|mo)\b", 0.7),
        (r"\bcancelad[oa]s?\b", 0.8), (r"\bprocess(?:ar|ei|ou)\b", 0.5), (r"\bdiscord[oa]\b", 0.6),
        (r"\bvoce nao sabe\b", 0.8), (r"\bpara de\b", 0.5), (r"\bnao me interrompe\b", 1.2), (r"\bdesonest[oa]\b", 1.0),
    ],
    "surpresa": [
        (r"\bnao acredito\b", 1.0), (r"\bmeu deus\b", 0.9), (r"\bcaramba\b", 0.6), (r"\bcaraca\b", 0.6),
        (r"\bnossa senhora\b", 0.7), (r"\bsocorro\b", 0.8), (r"\bchocad[oa]s?\b", 0.9), (r"\binacreditavel\b", 0.9),
        (r"\bque isso\b", 0.6), (r"\bolha isso\b", 1.0), (r"\bmisericordia\b", 0.8), (r"\bgente do ceu\b", 0.9),
        (r"\bnao e possivel\b", 0.9), (r"\bcomo assim\b", 0.6), (r"\bsurreal\b", 0.8), (r"\binsano\b", 0.7),
        (r"\bbizarr[oa]\b", 0.7), (r"\bserio\?", 0.5), (r"\bjura\?", 0.5), (r"\bfala serio\b", 0.7),
    ],
    "emocao": [
        (r"\bchorei\b", 0.8), (r"\bchorando\b", 0.7), (r"\bemocionad[oa]\b", 0.8), (r"\bemocionante\b", 0.7),
        (r"\blagrimas?\b", 0.7), (r"\bsaudade\b", 0.5), (r"\borgulho\b", 0.5), (r"\bde coracao\b", 0.5),
        (r"\b(?:muito|mt) triste\b", 0.6), (r"\bdepressao\b", 0.6), (r"\bperdi (?:meu|minha)\b", 0.7),
    ],
    "palavrao": [
        (r"\bporra\b", 0.8), (r"\bcaralho\b", 0.8), (r"\bmerda\b", 0.7), (r"\bputa que pariu\b", 1.0), (r"\bpqp\b", 0.8),
        (r"\bfod(?:a|eu|ase|ido)\b", 0.7), (r"\bcacete\b", 0.6), (r"\bbosta\b", 0.6), (r"\bdesgraca\b", 0.7),
        (r"\bvsf\b", 0.8), (r"\bvtnc\b", 0.8), (r"\botari[oa]s?\b", 0.8), (r"\bidiotas?\b", 0.8), (r"\bimbecil\b", 0.9),
        (r"\bburr[oa]\b", 0.5), (r"\bbabaca\b", 0.8),
    ],
    "gancho": [
        (r"\bsabe o que aconteceu\b", 0.9), (r"\bvou (?:te|te) contar\b", 0.7), (r"\bpresta atencao\b", 0.7),
        (r"\bolha so\b", 0.25),(r"\ba verdade e\b", 0.7), (r"\bninguem (?:fala|sabe|te conta)\b", 0.8),
        (r"\bo segredo\b", 0.6), (r"\bvoce sabia\b", 0.6), (r"\bdeixa eu te (?:falar|contar)\b", 0.6),
        (r"\bo (?:mais )?louco e\b", 0.7), (r"\bpior de tudo\b", 0.7), (r"\bnunca contei\b", 0.9),
        (r"\bpela primeira vez\b", 0.5), (r"\bvou ser sincer[oa]\b", 0.7), (r"\bsinceramente\b", 0.4),
        (r"\bisso ninguem\b", 0.6), (r"\bimagina\b", 0.3), (r"\bresumindo\b", 0.3),
    ],
    "impacto": [
        (r"\bmilh(?:ao|oes)\b", 0.4), (r"\bbilh(?:ao|oes)\b", 0.5), (r"\bmil reais\b", 0.4), (r"\bpres[oa]\b", 0.5),
        (r"\bmorreu\b", 0.4), (r"\bgol(?:aco|ac[oa])?\b", 0.5), (r"\bclutch\b", 0.7), (r"\bvirada\b", 0.4),
        (r"\bcampe(?:ao|oes|a)\b", 0.4), (r"\bdemitid[oa]\b", 0.6), (r"\bterminamos\b", 0.6), (r"\btraicao\b", 0.8),
    ],
}
# fontes estrangeiras (ingles): mesmo formato, texto normalizado
KEYWORDS_EN: dict[str, list[tuple[str, float]]] = {
    "risada": [(r"\blmf?ao+\b", 1.0), (r"\blol\b", 0.6), (r"\bi'?m dead\b", 0.8), (r"\bi'?m dying\b", 0.8),
               (r"\bhilarious\b", 0.7)],
    "polemica": [(r"\bliars?\b", 1.2), (r"\bbullshit\b", 1.2), (r"\byou'?re wrong\b", 1.0), (r"\bshut up\b", 1.2),
                 (r"\bhow dare you\b", 1.0), (r"\bdisrespect\w*\b", 0.9), (r"\bscam\w*\b", 0.8), (r"\bfraud\b", 0.9),
                 (r"\bcancell?ed\b", 0.8), (r"\bbeef\b", 0.8), (r"\bexposed\b", 0.9), (r"\bthat'?s not true\b", 0.9),
                 (r"\blet me finish\b", 1.0), (r"\bstop lying\b", 1.3), (r"\bclown\b", 0.9), (r"\bpathetic\b", 0.9)],
    "surpresa": [(r"\bno way\b", 0.9), (r"\boh my god\b", 0.9), (r"\bomg\b", 0.7), (r"\bwtf\b", 0.9),
                 (r"\bwhat the (?:hell|fuck|heck)\b", 1.0), (r"\binsane\b", 0.7), (r"\bcrazy\b", 0.5),
                 (r"\bare you serious\b", 0.8), (r"\bholy (?:shit|crap)\b", 1.0), (r"\bbro what\b", 0.7)],
    "emocao": [(r"\bi'?m crying\b", 0.8), (r"\btears\b", 0.6), (r"\bpassed away\b", 0.7), (r"\bheartbroken\b", 0.8)],
    "palavrao": [(r"\bfuck\w*\b", 0.8), (r"\bshit\w*\b", 0.7), (r"\bbitch\w*\b", 0.8), (r"\bmotherfuck\w*\b", 1.0),
                 (r"\bassholes?\b", 0.9), (r"\bdumbass\b", 0.8)],
    "gancho": [(r"\blet me tell you\b", 0.7), (r"\bnobody talks about\b", 0.8), (r"\bthe truth is\b", 0.7),
               (r"\bhere'?s the thing\b", 0.6), (r"\byou won'?t believe\b", 0.8)],
    "impacto": [(r"\bmillions?\b", 0.4), (r"\bbillions?\b", 0.5), (r"\barrested\b", 0.6), (r"\bbanned\b", 0.6),
                (r"\bfired\b", 0.5)],
}
for _k, _v in KEYWORDS_EN.items():
    KEYWORDS.setdefault(_k, []).extend(_v)
_COMPILED = {k: [(re.compile(p), w) for p, w in v] for k, v in KEYWORDS.items()}

KIND_PT = {
    "risada": "risadas", "polemica": "polêmica", "surpresa": "surpresa", "emocao": "emoção",
    "palavrao": "palavrão", "gancho": "gancho de história", "impacto": "fato forte",
}


def norm(text: str) -> str:
    """Minusculo e sem acento (para comparar palavras-chave)."""
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", t)


# ----------------------------------------------------------------------------------------
# Estruturas
# ----------------------------------------------------------------------------------------
@dataclass
class KeywordHit:
    t: float
    kind: str
    text: str
    weight: float


@dataclass
class Moment:
    start: float
    end: float
    peak: float
    score: float                     # 0-1 (relativo ao video)
    reasons: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)   # heatmap, volume, risada, polemica, twitch...


@dataclass
class Signals:
    duration: float
    loudness: list[float] = field(default_factory=list)          # dBFS por segundo
    loud_peaks: list[tuple[float, float, float]] = field(default_factory=list)   # (t, forca 0-1, dB acima da base)
    speech_rate: list[tuple[float, float]] = field(default_factory=list)          # (inicio janela, palavras/s)
    keywords: list[KeywordHit] = field(default_factory=list)
    heatmap: list[tuple[float, float, float]] = field(default_factory=list)       # (ini, fim, valor 0-1)
    heat_peaks: list[tuple[float, float, float]] = field(default_factory=list)    # (ini, fim, valor)
    twitch_clips: list[dict] = field(default_factory=list)
    comment_marks: list[dict] = field(default_factory=list)       # {"t","peso","n","exemplo"}
    chat_spikes: list[dict] = field(default_factory=list)         # {"t","z","msgs","riso"}
    chat_base: float | None = None                                # msgs/10 s normais do chat
    saturation: dict | None = None                                # Candidate.extra["saturacao"]
    janela: tuple[float, float] | None = None                     # Candidate.extra["janela"] (via rapida)
    chapters: list[dict] = field(default_factory=list)
    curve: list[float] = field(default_factory=list)              # pontuacao combinada por segundo (0-1)
    components: dict[str, list[float]] = field(default_factory=dict)
    available: list[str] = field(default_factory=list)

    @property
    def strength(self) -> float:
        """Quanto confiar nos sinais (0-1): sinais do publico valem mais que palavras-chave."""
        w = {"heatmap": 0.45, "twitch": 0.35, "comentarios": 0.35, "chat": 0.30, "volume": 0.15,
             "palavras": 0.15, "fala": 0.05}
        return min(1.0, sum(w.get(a, 0) for a in self.available))


# ----------------------------------------------------------------------------------------
# Volume
# ----------------------------------------------------------------------------------------
def loudness_curve(media: str | Path, start: float | None = None, end: float | None = None,
                   rate: int = 8000) -> list[float]:
    """Volume (RMS em dBFS) por segundo. Retorna [] se nao der para ler o audio."""
    ff = tools.ffmpeg()
    if not ff or not Path(media).exists():
        return []
    try:
        import numpy as np
    except Exception:  # pragma: no cover
        return []
    args = [ff, "-nostdin", "-hide_banner", "-v", "error"]
    if start:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", str(media)]
    if end is not None:
        args += ["-t", f"{max(0.1, end - (start or 0)):.3f}"]
    args += ["-vn", "-sn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"]
    out: list[float] = []
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                creationflags=CREATE_NO_WINDOW)
        chunk = rate * 2
        buf = b""
        assert proc.stdout is not None
        while True:
            data = proc.stdout.read(chunk * 30)
            if not data:
                break
            buf += data
            n = len(buf) // chunk
            if n:
                arr = np.frombuffer(buf[: n * chunk], dtype=np.int16).astype(np.float32).reshape(n, rate)
                rms = np.sqrt(np.mean(arr * arr, axis=1)) / 32768.0
                out.extend((20 * np.log10(np.maximum(rms, 3e-4))).round(2).tolist())
                buf = buf[n * chunk:]
        if len(buf) >= rate // 2 * 2:
            arr = np.frombuffer(buf[: len(buf) // 2 * 2], dtype=np.int16).astype(np.float32)
            rms = float(np.sqrt(np.mean(arr * arr))) / 32768.0
            out.append(round(20 * math.log10(max(rms, 3e-4)), 2))
        proc.wait(timeout=30)
    except Exception as e:
        logger.debug("loudness falhou: %s", e)
        return []
    return out


def _moving_avg(x: list[float], k: int) -> list[float]:
    if not x or k <= 1:
        return list(x)
    h = k // 2
    pref = [0.0]
    for v in x:
        pref.append(pref[-1] + v)
    out = []
    n = len(x)
    for i in range(n):
        a, b = max(0, i - h), min(n, i + h + 1)
        out.append((pref[b] - pref[a]) / (b - a))
    return out


def _rolling_median(x: list[float], k: int, step: int = 5) -> list[float]:
    """Mediana movel (aproximada a cada `step` amostras, rapida para lives longas)."""
    import statistics

    n = len(x)
    if n == 0:
        return []
    h = k // 2
    anchors = {}
    for i in range(0, n, step):
        anchors[i] = statistics.median(x[max(0, i - h): min(n, i + h + 1)])
    out = []
    for i in range(n):
        a = (i // step) * step
        out.append(anchors[a])
    return out


def find_loud_peaks(loud: list[float], min_db: float = 4.0, min_gap: int = 15) -> list[tuple[float, float, float]]:
    """Picos de volume acima da base local (mediana de ~1 min). Retorna (t, forca 0-1, dB acima)."""
    if len(loud) < 10:
        return []
    sm = _moving_avg(loud, 3)
    base = _rolling_median(sm, 61)
    excess = [s - b for s, b in zip(sm, base)]
    cands = []
    for i in range(1, len(excess) - 1):
        e = excess[i]
        if e >= min_db and sm[i] > -45 and e >= excess[i - 1] and e >= excess[i + 1]:
            cands.append((e, i))
    cands.sort(reverse=True)
    chosen: list[tuple[float, float, float]] = []
    for e, i in cands:
        if all(abs(i - c[0]) >= min_gap for c in chosen):
            chosen.append((float(i), min(1.0, e / 12.0), round(e, 1)))
    chosen.sort()
    return chosen


def loudness_peaks(media: str | Path, top: int = 10, start: float | None = None,
                   end: float | None = None) -> list[tuple[float, float]]:
    """Atalho: os `top` maiores picos de volume do arquivo -> [(tempo_s, peso 0-1)] (tempo no arquivo)."""
    curve = loudness_curve(media, start, end)
    peaks = find_loud_peaks(curve, min_db=3.0)
    peaks.sort(key=lambda p: -p[1])
    off = float(start or 0.0)
    return [(t + off, w) for t, w, _ in peaks[:top]]


# ----------------------------------------------------------------------------------------
# Transcricao: palavras-chave e velocidade da fala
# ----------------------------------------------------------------------------------------
def keyword_hits(transcript: Transcript) -> list[KeywordHit]:
    hits: list[KeywordHit] = []
    for seg in transcript.segments:
        text = norm(seg.text)
        if not text:
            continue
        dur = max(0.1, seg.end - seg.start)
        for kind, pats in _COMPILED.items():
            for rx, w in pats:
                for m in rx.finditer(text):
                    t = seg.start + dur * (m.start() / max(1, len(text)))
                    hits.append(KeywordHit(round(t, 2), kind, m.group(0), w))
        # exclamacoes/interrogacoes repetidas indicam fala exaltada
        if "!" in seg.text or "?!" in seg.text:
            hits.append(KeywordHit(round(seg.start, 2), "surpresa", "!", 0.2))
    hits.sort(key=lambda h: h.t)
    return hits


def speech_rate(transcript: Transcript, window: float = 10.0, step: float = 5.0) -> list[tuple[float, float]]:
    """Palavras por segundo em janelas deslizantes."""
    times: list[float] = []
    for s in transcript.segments:
        if s.words:
            times.extend(w.start for w in s.words)
        else:
            n = len(s.text.split())
            times.extend(s.start + (s.end - s.start) * i / max(1, n) for i in range(n))
    if not times:
        return []
    times.sort()
    out = []
    dur = transcript.duration
    t = 0.0
    j0 = 0
    while t < dur:
        while j0 < len(times) and times[j0] < t:
            j0 += 1
        j = j0
        while j < len(times) and times[j] < t + window:
            j += 1
        out.append((t, (j - j0) / window))
        t += step
    return out


# ----------------------------------------------------------------------------------------
# Plataforma: heatmap do YouTube e clipes da Twitch
# ----------------------------------------------------------------------------------------
def _heatmap(video: Candidate | None) -> list[tuple[float, float, float]]:
    raw = (video.extra or {}).get("heatmap") if video else None
    out = []
    for h in raw or []:
        try:
            out.append((float(h["start_time"]), float(h["end_time"]), float(h.get("value", 0) or 0)))
        except (KeyError, TypeError, ValueError):
            continue
    out.sort()
    return out


def heatmap_peaks(heat: list[tuple[float, float, float]], duration: float, top: int = 8) -> list[tuple[float, float, float]]:
    """Picos do "mais repetidos" (ignora o comeco do video, que e sempre alto)."""
    if len(heat) < 5:
        return []
    vals = [v for _, _, v in heat]
    srt = sorted(vals)
    med = srt[len(srt) // 2]
    thr = max(0.3, med + 0.12)
    skip_until = max(20.0, 0.04 * duration)
    peaks = []
    for i, (a, b, v) in enumerate(heat):
        if a < skip_until or v < thr:
            continue
        nb = vals[max(0, i - 2): i] + vals[i + 1: i + 3]
        if all(v >= x for x in nb):
            # expande enquanto continua alto
            lo, hi = i, i
            while lo - 1 >= 0 and vals[lo - 1] >= 0.75 * v and heat[lo - 1][0] >= skip_until:
                lo -= 1
            while hi + 1 < len(vals) and vals[hi + 1] >= 0.75 * v:
                hi += 1
            peaks.append((heat[lo][0], heat[hi][1], v))
    peaks.sort(key=lambda p: -p[2])
    merged: list[tuple[float, float, float]] = []
    for p in peaks:
        if all(p[1] <= q[0] or p[0] >= q[1] for q in merged):
            merged.append(p)
    return merged[:top]


def _twitch_clips(video: Candidate | None) -> list[dict]:
    raw = (video.extra or {}).get("twitch_clips") if video else None
    out = []
    for c in raw or []:
        try:
            off = c.get("offset")
            if off is None:
                continue
            out.append({"offset": float(off), "duration": float(c.get("duration") or 30),
                        "views": int(c.get("views") or 0), "title": str(c.get("title") or "")})
        except (TypeError, ValueError, AttributeError):
            continue
    out.sort(key=lambda c: -c["views"])
    return out


def _comment_marks(video: Candidate | None) -> list[dict]:
    raw = (video.extra or {}).get("comment_marks") if video else None
    out = []
    for m in raw or []:
        try:
            out.append({"t": float(m["t"]), "peso": float(m.get("peso") or 1), "n": int(m.get("n") or 1),
                        "exemplo": str(m.get("exemplo") or ""), "forte": bool(m.get("forte", True))})
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    out.sort(key=lambda m: -m["peso"])
    return out


def _chat_spikes(video: Candidate | None) -> list[dict]:
    raw = (video.extra or {}).get("chat_spikes") if video else None
    out = []
    for s in raw or []:
        try:
            out.append({"t": float(s["t"]), "z": float(s.get("z") or 3), "msgs": float(s.get("msgs") or 0),
                        "riso": float(s.get("riso") or 0)})
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    out.sort(key=lambda s: -s["z"])
    return out


# o comentario cita o INICIO do momento; o chat explode DEPOIS do lance
COMMENT_SPAN = (-8.0, 38.0)
CHAT_SPAN = (-35.0, 6.0)


def comment_value(m: dict, max_peso: float) -> float:
    v = 0.55 + 0.45 * (math.log1p(m["peso"]) / math.log1p(max_peso) if max_peso > 0 else 0)
    return v if m.get("forte", True) else 0.7 * v     # citacao isolada (1 a 2 pessoas) vale menos


def chat_value(s: dict) -> float:
    return min(1.0, 0.55 + 0.45 * min(1.0, (s["z"] - 3.0) / 6.0) + 0.15 * min(1.0, s["riso"] / 0.4))


def _plateau(arr: list[float], a: float, b: float, val: float, ramp: float = 6.0) -> None:
    """Soma um "degrau" suave [a, b] (rampa de `ramp` s nas pontas), limitado a 1."""
    n = len(arr)
    for t in range(max(0, int(a - ramp)), min(n, int(b + ramp) + 1)):
        if t < a:
            k = max(0.0, 1 - (a - t) / ramp)
        elif t > b:
            k = max(0.0, 1 - (t - b) / ramp)
        else:
            k = 1.0
        arr[t] = min(1.0, max(arr[t], val * k))


def signal_anchors(video: Candidate | None) -> list[tuple[float, float]]:
    """[(tempo do momento, peso)] dos sinais externos (heatmap, clipes, comentarios, chat), maiores primeiro.
    Serve para escolher quais janelas transcrever num video longo sem legenda."""
    out: list[tuple[float, float]] = []
    if not video:
        return out
    for a, b, v in heatmap_peaks(_heatmap(video), float(video.duration or 0) or 1e9):
        out.append(((a + b) / 2, 1.5 + 2.0 * v))
    for c in _twitch_clips(video):
        out.append((c["offset"] + c["duration"] / 2, 2.0 + min(3.0, c["views"] / 5000)))
    marks = _comment_marks(video)
    mx = max((m["peso"] for m in marks), default=1.0)
    for m in marks:
        out.append((m["t"] + 15, 1.8 + 2.5 * comment_value(m, mx)))
    for s in _chat_spikes(video):
        out.append((s["t"] - 12, 1.6 + 2.5 * chat_value(s)))
    jan = (video.extra or {}).get("janela")
    if isinstance(jan, (list, tuple)) and len(jan) == 2:
        try:
            out.append(((float(jan[0]) + float(jan[1])) / 2, 6.0))
        except (TypeError, ValueError):
            pass
    out.sort(key=lambda x: -x[1])
    return out


# ----------------------------------------------------------------------------------------
# Combinacao
# ----------------------------------------------------------------------------------------
WEIGHTS = {"heatmap": 0.40, "twitch": 0.35, "comentarios": 0.38, "chat": 0.33, "palavras": 0.25, "volume": 0.20,
           "fala": 0.10}
LABELS = {"heatmap": "mais repetidos do YouTube", "twitch": "clipes da Twitch/Kick",
          "comentarios": "horários citados nos comentários", "chat": "picos do chat", "palavras": "palavras-chave",
          "volume": "volume do áudio", "fala": "velocidade da fala"}


def compute_signals(video: Candidate | None, transcript: Transcript | None,
                    audio_path: str | Path | None = None, duration: float | None = None) -> Signals:
    """Calcula todos os sinais disponiveis. `audio_path` (ou video.extra['audio_path']) liga o sinal de volume."""
    tr = transcript or Transcript()
    dur = float(duration or (video.duration if video and video.duration else 0) or tr.duration or 0)
    dur = max(dur, tr.duration)
    sig = Signals(duration=dur)
    n = int(math.ceil(dur)) + 1
    if n <= 1:
        return sig
    comps: dict[str, list[float]] = {}

    # heatmap
    sig.heatmap = _heatmap(video)
    if sig.heatmap:
        sig.heat_peaks = heatmap_peaks(sig.heatmap, dur)
        vals = sorted(v for _, _, v in sig.heatmap)
        med = vals[len(vals) // 2]
        top = max(vals) if vals else 1.0
        H = [0.0] * n
        skip_until = max(20.0, 0.04 * dur)
        for a, b, v in sig.heatmap:
            x = max(0.0, (v - med) / max(1e-6, top - med))
            if a < skip_until:
                x *= 0.3
            for t in range(int(a), min(n, int(math.ceil(b)) + 1)):
                H[t] = max(H[t], x)
        comps["heatmap"] = _moving_avg(H, 5)

    # twitch
    sig.twitch_clips = _twitch_clips(video)
    if sig.twitch_clips:
        mx = math.log1p(max(c["views"] for c in sig.twitch_clips) or 1)
        W = [0.0] * n
        for c in sig.twitch_clips:
            val = 0.5 + 0.5 * (math.log1p(c["views"]) / mx if mx else 0)
            for t in range(int(c["offset"]), min(n, int(c["offset"] + c["duration"]) + 1)):
                W[t] = min(1.0, W[t] + val)
        comps["twitch"] = W

    # horarios citados nos comentarios
    sig.comment_marks = [m for m in _comment_marks(video) if m["t"] < n]
    if sig.comment_marks:
        mx = max(m["peso"] for m in sig.comment_marks)
        C = [0.0] * n
        for m in sig.comment_marks:
            _plateau(C, m["t"] + COMMENT_SPAN[0], m["t"] + COMMENT_SPAN[1], comment_value(m, mx))
        comps["comentarios"] = C

    # picos do chat gravado
    sig.chat_spikes = [s for s in _chat_spikes(video) if s["t"] < n + 30]
    if video is not None:
        sig.chat_base = ((video.extra or {}).get("chat_info") or {}).get("base_msgs")
    if sig.chat_spikes:
        Z = [0.0] * n
        for s in sig.chat_spikes:
            _plateau(Z, s["t"] + CHAT_SPAN[0], s["t"] + CHAT_SPAN[1], chat_value(s))
        comps["chat"] = Z

    if video is not None:
        sat = (video.extra or {}).get("saturacao")
        sig.saturation = sat if isinstance(sat, dict) else None
        jan = (video.extra or {}).get("janela")
        if isinstance(jan, (list, tuple)) and len(jan) == 2:
            try:
                sig.janela = (float(jan[0]), float(jan[1]))
            except (TypeError, ValueError):
                sig.janela = None

    # palavras-chave
    if tr.segments:
        sig.keywords = keyword_hits(tr)
        if sig.keywords:
            K = [0.0] * n
            sigma = 6.0
            for h in sig.keywords:
                c = int(h.t)
                for t in range(max(0, c - 15), min(n, c + 16)):
                    K[t] += h.weight * math.exp(-((t - h.t) ** 2) / (2 * sigma * sigma))
            comps["palavras"] = [min(1.0, k / 2.5) for k in K]
        sig.speech_rate = speech_rate(tr)
        if len(sig.speech_rate) >= 6:
            rates = sorted(r for _, r in sig.speech_rate)
            med = rates[len(rates) // 2]
            mad = sorted(abs(r - med) for r in rates)[len(rates) // 2] or 0.3
            R = [0.0] * n
            for t0, r in sig.speech_rate:
                z = (r - med) / (1.4826 * mad)
                val = max(0.0, min(1.0, z / 3.0))
                for t in range(int(t0), min(n, int(t0 + 5))):
                    R[t] = max(R[t], val)
            comps["fala"] = R

    # volume
    ap = audio_path or ((video.extra or {}).get("audio_path") if video else None) \
        or ((video.extra or {}).get("media_path") if video else None)
    if ap and Path(ap).exists():
        sig.loudness = loudness_curve(ap)
        if sig.loudness:
            sig.loud_peaks = find_loud_peaks(sig.loudness)
            sm = _moving_avg(sig.loudness, 3)
            base = _rolling_median(sm, 61)
            L = [max(0.0, min(1.0, (s - b) / 9.0)) if s > -50 else 0.0 for s, b in zip(sm, base)]
            L = (L + [0.0] * n)[:n]
            comps["volume"] = L

    sig.chapters = list((video.extra or {}).get("chapters") or []) if video else []
    sig.components = comps
    sig.available = [k for k in WEIGHTS if k in comps]
    tot = sum(WEIGHTS[k] for k in comps) or 1.0
    curve = [0.0] * n
    for k, arr in comps.items():
        w = WEIGHTS[k] / tot
        for i in range(min(n, len(arr))):
            curve[i] += w * arr[i]
    sig.curve = _moving_avg(curve, 5)
    return sig


def _fmt(t: float) -> str:
    t = max(0, int(t))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _reasons_at(sig: Signals, a: float, b: float) -> tuple[list[str], list[str]]:
    reasons, kinds = [], []
    for (ha, hb, v) in sig.heat_peaks:
        if hb > a and ha < b:
            reasons.append(f"mais repetido pelo público ({int(v * 100)}%)")
            kinds.append("heatmap")
            break
    for c in sig.twitch_clips:
        if c["offset"] < b and c["offset"] + c["duration"] > a:
            reasons.append(f"clipe da Twitch ({c['views']} views): \"{c['title'][:50]}\"")
            kinds.append("twitch")
            break
    for m in sig.comment_marks:
        if a - 10 <= m["t"] <= b:
            ex = m["exemplo"][:60]
            reasons.append(f"citado nos comentários ({m['n']} menções" + (f", ex.: \"{ex}\")" if ex else ")"))
            kinds.append("comentarios")
            break
    for s in sig.chat_spikes:
        if a <= s["t"] <= b + 25:
            extra = f", {int(round(s['riso'] * 100))}% risadas" if s["riso"] >= 0.15 else ""
            reasons.append(f"pico no chat ({s['msgs']:.0f} msgs/10 s, z {s['z']:.1f}{extra})")
            kinds.append("chat")
            break
    lp = [p for p in sig.loud_peaks if a <= p[0] <= b]
    if lp:
        reasons.append(f"pico de volume (+{max(p[2] for p in lp):.0f} dB)")
        kinds.append("volume")
    kw = [h for h in sig.keywords if a <= h.t <= b and h.text != "!"]
    if kw:
        by_kind: dict[str, list[str]] = {}
        for h in kw:
            by_kind.setdefault(h.kind, []).append(h.text)
        parts = []
        for k, words in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
            uniq = list(dict.fromkeys(words))[:3]
            parts.append(f"{KIND_PT.get(k, k)} ({', '.join(uniq)})")
            kinds.append(k)
        reasons.append("; ".join(parts[:3]))
    fala = sig.components.get("fala")
    if fala:
        seg = fala[int(a): int(b) + 1]
        if seg and max(seg) > 0.6:
            reasons.append("fala acelerada/exaltada")
            kinds.append("fala")
    return reasons, kinds


def hot_moments(sig: Signals, top: int = 10, min_gap: float = 25.0, max_len: float = 120.0) -> list[Moment]:
    """Picos da curva combinada -> momentos (regiao em volta do pico ainda "quente")."""
    c = sig.curve
    if not c or max(c) <= 0:
        return []
    n = len(c)
    cands = [(c[i], i) for i in range(1, n - 1) if c[i] > 0.05 and c[i] >= c[i - 1] and c[i] >= c[i + 1]]
    cands.sort(reverse=True)
    out: list[Moment] = []
    for v, i in cands:
        if any(abs(i - m.peak) < min_gap or m.start <= i <= m.end for m in out):
            continue   # mesmo "planalto" (ex.: pico de chat/comentario) nao vira dois momentos
        lo = hi = i
        lim = 0.55 * v
        while lo > 0 and c[lo - 1] >= lim and (i - lo) < max_len * 0.7:
            lo -= 1
        while hi < n - 1 and c[hi + 1] >= lim and (hi - i) < max_len * 0.5:
            hi += 1
        reasons, kinds = _reasons_at(sig, lo - 3, hi + 3)
        out.append(Moment(float(lo), float(hi), float(i), round(float(v), 3), reasons, kinds))
        if len(out) >= top:
            break
    mx = max((m.score for m in out), default=1.0) or 1.0
    for m in out:
        m.score = round(m.score / mx, 3)       # relativo ao melhor momento do video
    return out


def summarize_for_prompt(sig: Signals, max_items: int = 10, moments: list[Moment] | None = None) -> str:
    """Resumo compacto dos momentos quentes para colocar no prompt da IA."""
    lines = []
    if sig.available:
        lines.append("Sinais disponíveis: " + ", ".join(LABELS.get(k, k) for k in sig.available) + ".")
    ms = moments if moments is not None else hot_moments(sig, top=max_items)
    for m in ms[:max_items]:
        why = "; ".join(r for r in m.reasons if r) or "intensidade acima da média"
        lines.append(f"- [{_fmt(m.start)} a {_fmt(m.end)}] pico {_fmt(m.peak)}, força {m.score:.2f}: {why}")
    # trecho do video (chunk): so os sinais externos que caem nele
    if moments is not None:
        if ms:
            lo, hi = min(m.start for m in ms) - 60, max(m.end for m in ms) + 60
        else:
            lo, hi = 1.0, 0.0
    else:
        lo, hi = -1e9, 1e9
    cms = [m for m in sig.comment_marks if lo <= m["t"] <= hi][:6]
    if cms:
        lines.append("Momentos que o público cita nos comentários (o horário marca o INÍCIO do lance; "
                     "sinal forte, quase sempre vale um corte):")
        for m in sorted(cms, key=lambda x: x["t"]):
            ex = f": \"{m['exemplo'][:90]}\"" if m["exemplo"] else ""
            fraco = "" if m.get("forte", True) else " (citação isolada)"
            lines.append(f"- [{_fmt(m['t'])}] {m['n']} menções, peso {m['peso']:.1f}{fraco}{ex}")
    sps = [s for s in sig.chat_spikes if lo <= s["t"] <= hi][:6]
    if sps:
        base = f" (normal: {sig.chat_base:.0f} msgs/10 s)" if sig.chat_base else ""
        lines.append(f"Picos do chat ao vivo{base}; o lance costuma estar 5 a 30 s ANTES do pico:")
        for s in sorted(sps, key=lambda x: x["t"]):
            riso = f", {int(round(s['riso'] * 100))}% risadas/emotes" if s["riso"] >= 0.1 else ""
            lines.append(f"- [{_fmt(s['t'])}] {s['msgs']:.0f} msgs/10 s, z {s['z']:.1f}{riso}")
    if sig.janela:
        a, b = sig.janela
        lines.append(f"VIA RÁPIDA: o momento que está explodindo agora fica entre {_fmt(a)} e {_fmt(b)}. "
                     "Priorize um corte dentro dessa janela.")
    sat = sig.saturation or {}
    if sat.get("pular_melhor_momento"):
        views = f"{int(sat.get('top_views') or 0):,}".replace(",", ".")
        lines.append(f"ATENÇÃO, ASSUNTO SATURADO: {sat.get('canais', '8+')} canais já postaram cortes disso hoje "
                     f"(o mais visto tem {views} views). Evite o momento mais óbvio "
                     "(o mais citado/mais forte acima): prefira o 2º ou 3º melhor momento ou um ângulo diferente.")
    if sig.chapters:
        ch = []
        for c in sig.chapters[:20]:
            try:
                ch.append(f"{_fmt(float(c.get('start_time', 0)))} {str(c.get('title', ''))[:40]}")
            except (TypeError, ValueError, AttributeError):
                continue
        if ch:
            lines.append("Capítulos: " + " | ".join(ch))
    if not lines:
        return "Sem sinais automáticos (sem 'mais repetidos', sem áudio). Decida só pela transcrição."
    return "\n".join(lines)


def teaser_bonus(sig: Signals | None):
    """bonus(a, b) para brain.base.polemic_spans: pico de volume no trecho, horario citado nos comentarios
    logo antes (o comentario marca o inicio do lance) ou pico de chat logo depois. None sem sinais."""
    if sig is None:
        return None
    loud, cms, sps = list(sig.loud_peaks), list(sig.comment_marks), list(sig.chat_spikes)
    if not (loud or cms or sps):
        return None

    def bonus(a: float, b: float) -> float:
        x = 0.0
        lp = [p for p in loud if a - 0.5 <= p[0] <= b + 0.5]
        if lp:
            x += min(1.2, max(p[2] for p in lp) / 8.0)        # grito/explosao no audio
        if any(m["t"] - 5 <= a <= m["t"] + 35 for m in cms):
            x += 0.4
        sp = [s for s in sps if s["t"] - 35 <= a <= s["t"] + 3]
        if sp:
            x += 0.4 + 0.4 * min(1.0, max(s["riso"] for s in sp) / 0.3)
        return x

    return bonus


def describe(sig: Signals) -> dict[str, Any]:
    """Resumo para log/debug."""
    return {
        "duracao": round(sig.duration, 1), "sinais": sig.available, "picos_heatmap": len(sig.heat_peaks),
        "picos_volume": len(sig.loud_peaks), "palavras_chave": len(sig.keywords),
        "clipes_twitch": len(sig.twitch_clips), "marcas_comentarios": len(sig.comment_marks),
        "picos_chat": len(sig.chat_spikes), "saturado": bool((sig.saturation or {}).get("pular_melhor_momento")),
    }
