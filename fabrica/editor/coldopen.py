"""Cold open (teaser): os 1,5 a 3 s mais polemicos do proprio corte tocam primeiro, com
legenda no destaque mais forte e leve punch-in (1,10x); depois um flash branco rapido
(+ whoosh gerado aqui, sem efeito baixado) e o corte normal desde o comeco.

ClipPlan.teaser_start/teaser_end vem na linha do tempo do video ORIGINAL; render_clip recebe
start/end na linha do tempo do arquivo-fonte, entao o teaser relativo ao corte e
plan.teaser_start - plan.start (mesmo deslocamento).
"""
from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

from ..log import get as get_log
from ..models import Segment, Transcript, Word
from . import style as _style

_log = get_log(__name__)


@dataclass
class Teaser:
    t0: float          # inicio, relativo ao inicio do corte (s)
    frames: int        # duracao em quadros (grade do fps)
    fps: int
    text: str = ""

    @property
    def dur(self) -> float:
        return self.frames / self.fps


def plan_teaser(plan, dur: float, captions: Transcript | None, cfg=None, fps: int = 30) -> Teaser | None:
    """Janela do teaser (ajustada as palavras para nao comecar/terminar no meio de uma)."""
    g = (lambda k, d: cfg.get(k, d)) if cfg is not None else (lambda k, d: d)
    if plan is None or not g("edicao.cold_open", True):
        return None
    ts = getattr(plan, "teaser_start", None)
    if ts is None:
        return None
    te = getattr(plan, "teaser_end", None)
    max_s = min(5.0, max(1.0, float(g("edicao.cold_open_max_s", 3.0) or 3.0)))
    a = float(ts) - float(plan.start)
    b = (float(te) - float(plan.start)) if te is not None else a + 2.5
    a = max(0.0, min(a, dur - 1.0))
    b = max(a + 0.5, min(b, dur))
    words = [w for w in (captions.words() if captions is not None else []) if (w.text or "").strip()]
    inside = [w for w in words if w.end > a + 0.04 and w.start < b - 0.04]
    if inside:
        a = max(0.0, inside[0].start - 0.06)
        last = inside[-1]
        if last.end - b < 0.6:
            # termina na ultima palavra, sem pegar o comeco da proxima frase
            nxt = next((w for w in words if w.start >= last.end - 0.02 and w is not last), None)
            tail = last.end + 0.10 if nxt is None else max(last.end + 0.02, min(last.end + 0.10, nxt.start - 0.02))
            b = min(dur, max(b if nxt is None else min(b, tail), tail))
    if b - a > max_s:
        ends = [w.end for w in inside if w.end <= a + max_s - 0.1]
        b = (max(ends) + 0.10) if ends and max(ends) - a >= 1.0 else a + max_s
    min_s = min(max_s, 1.5)
    if b - a < min_s:
        # frase curta demais: puxa palavras anteriores (o contexto imediato da frase polemica)
        before = [w for w in words if w.end <= a + 0.06]
        while before and b - a < min_s and b - (before[-1].start - 0.06) <= max_s:
            a = max(0.0, before.pop().start - 0.06)
        if b - a < min_s:
            b = min(dur, a + min_s)
    if b - a < 0.8:
        _log.info("teaser curto demais (%.2fs), seguindo sem cold open", b - a)
        return None
    return Teaser(round(a, 3), int(round((b - a) * fps)), fps, str(getattr(plan, "teaser_text", "") or ""))


def teaser_captions(captions: Transcript | None, t: Teaser) -> list[Segment]:
    """Palavras dentro do teaser, com tempos a partir de 0."""
    if captions is None:
        return []
    a, d = t.t0, t.dur
    out: list[Segment] = []
    for s in captions.segments:
        ws = [Word(round(max(0.0, w.start - a), 3), round(min(d, w.end - a), 3), w.text)
              for w in s.words if w.end > a + 0.03 and w.start < a + d - 0.08]
        if ws:
            out.append(Segment(ws[0].start, ws[-1].end, " ".join(w.text for w in ws), ws))
    return out


def merge_captions(teaser_segs: list[Segment], main: Transcript | None, offset: float) -> Transcript:
    segs = list(teaser_segs)
    if main is not None:
        for s in main.segments:
            segs.append(Segment(round(s.start + offset, 3), round(s.end + offset, 3), s.text,
                                [Word(round(w.start + offset, 3), round(w.end + offset, 3), w.text) for w in s.words]))
    lang = main.language if main is not None else "pt"
    src = main.source if main is not None else "whisper"
    return Transcript(segs, lang, src)


def teaser_color(cfg, category: str | None) -> str:
    """Destaque mais forte que o do nicho: vermelho vivo (ou amarelo se o nicho ja e vermelho)."""
    v = cfg.get("edicao.cold_open_cor", "") if cfg is not None else ""
    if v:
        return str(v)
    hi = _style.highlight_color(cfg, category).lstrip("#").upper()
    try:
        r, gg, b = int(hi[0:2], 16), int(hi[2:4], 16), int(hi[4:6], 16)
    except ValueError:
        return "#FF2D2D"
    reddish = r > 200 and gg < 110 and b < 110
    return "#FFE600" if reddish else "#FF2D2D"


def whoosh_wav(path: Path, sr: int = 48000, dur: float = 0.42, peak_at: float = 0.18,
               peak_db: float = -17.0) -> Path | None:
    """Whoosh procedural: ruido com filtro passa-baixa varrendo 350 -> 5500 -> 900 Hz, envelope
    rapido e panoramico da esquerda para a direita. Sem arquivo externo (zero direito autoral)."""
    try:
        import numpy as np

        n = int(sr * dur)
        rng = np.random.default_rng(20261123)
        noise = rng.standard_normal((n, 2)).astype(np.float64)
        t = np.arange(n) / sr
        up = np.clip(t / peak_at, 0, 1)
        down = np.clip((t - peak_at) / (dur - peak_at), 0, 1)
        fc = np.where(t <= peak_at, 350 * (5500 / 350) ** up, 5500 * (900 / 5500) ** down)
        alpha = 1 - np.exp(-2 * np.pi * fc / sr)
        y = np.zeros_like(noise)
        acc = np.zeros(2)
        for i in range(n):                       # passa-baixa de 1 polo com corte variavel
            acc += alpha[i] * (noise[i] - acc)
            y[i] = acc
        hp = np.zeros_like(y)                    # tira o grave (passa-alta fixo ~180 Hz)
        a_hp = np.exp(-2 * np.pi * 180 / sr)
        prev_x = np.zeros(2)
        prev_y = np.zeros(2)
        for i in range(n):
            prev_y = a_hp * (prev_y + y[i] - prev_x)
            prev_x = y[i]
            hp[i] = prev_y
        env = np.where(t <= peak_at, up ** 2.2, np.exp(-down * 5.5) * (1 - down) ** 0.5)
        pan = np.clip(t / dur, 0, 1) * np.pi / 2
        out = hp * env[:, None]
        out[:, 0] *= np.cos(pan * 0.8 + 0.15)
        out[:, 1] *= np.sin(pan * 0.8 + 0.15) + 0.25
        peak = float(np.abs(out).max()) or 1.0
        out *= (10 ** (peak_db / 20)) / peak
        pcm = (np.clip(out, -1, 1) * 32767).astype("<i2")
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(pcm.tobytes())
        return Path(path)
    except Exception as e:  # noqa: BLE001
        _log.info("whoosh nao gerado: %s", e)
        return None
