"""Jump cuts: tira as pausas longas da fala (e o silencio do comeco) e retima a legenda.

Regra (docs/ideias/criativo_genz.json, audio): pausa maior que 0,40 s vira ~0,12 s; o audio
comeca numa palavra (pre-roll de no maximo 0,15 s). As pausas sao achadas pelos tempos das
palavras do Whisper E confirmadas pela energia do audio (o Whisper estica o fim das palavras),
entao o corte nunca cai dentro de uma fala. Os pontos de corte ficam na grade de quadros
(1/fps), assim audio e video tem exatamente a mesma duracao em cada pedaco: sem deriva de
sincronia, por mais cortes que existam.

Tempos relativos ao inicio do corte (0 = start do render_clip).
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..log import get as get_log
from ..models import Segment, Transcript, Word
from ..util import CREATE_NO_WINDOW
from . import ffmpeg as ff

_log = get_log(__name__)

HOP = 0.01               # resolucao da energia (s)
AUDIO_SR = 48000


@dataclass
class CutPlan:
    segments: list[tuple[int, int]]      # (quadro inicial, quadro final exclusivo) mantidos
    fps: int
    src_dur: float
    removed: list[tuple[float, float]] = field(default_factory=list)   # trechos tirados (s, fonte)

    @property
    def out_frames(self) -> int:
        return sum(b - a for a, b in self.segments)

    @property
    def out_duration(self) -> float:
        return self.out_frames / self.fps

    @property
    def removed_s(self) -> float:
        return max(0.0, self.src_dur - self.out_duration)

    @property
    def n_cuts(self) -> int:
        return max(0, len(self.segments) - 1)

    def map_time(self, t: float) -> float:
        """Tempo da fonte -> tempo da saida (trecho removido gruda na borda)."""
        acc = 0.0
        for a, b in self.segments:
            ta, tb = a / self.fps, b / self.fps
            if t < ta:
                return acc
            if t <= tb:
                return acc + (t - ta)
            acc += tb - ta
        return acc

    def truncate(self, max_frames: int) -> None:
        """Encurta o fim para caber em max_frames quadros de saida (teto de duracao)."""
        out: list[tuple[int, int]] = []
        left = max(1, int(max_frames))
        for a, b in self.segments:
            if left <= 0:
                break
            take = min(b - a, left)
            out.append((a, a + take))
            left -= take
        self.segments = out

    def cut_times_out(self) -> list[float]:
        """Instantes da saida onde ha emenda (jump cut)."""
        out, acc = [], 0
        for a, b in self.segments[:-1]:
            acc += b - a
            out.append(acc / self.fps)
        return out

    # -------------------------------------------------------------- filtros do ffmpeg
    def video_filter(self) -> str:
        """select por indice de quadro (depois do fps=) + timestamps contiguos."""
        terms = "+".join(f"between(n,{a},{b - 1})" for a, b in self.segments)
        return f"select='{terms}',setpts=N/({self.fps}*TB)"

    def audio_filter(self, src: str, out: str) -> str:
        """atrim por amostra (48 kHz, alinhado aos quadros) + concat, com micro-fade nas emendas."""
        spf = AUDIO_SR // self.fps if AUDIO_SR % self.fps == 0 else None

        def trim(a: int, b: int) -> str:
            if spf:
                return f"atrim=start_sample={a * spf}:end_sample={b * spf}"
            return f"atrim=start={a / self.fps:.6f}:end={b / self.fps:.6f}"

        pre = f"[{src}]aresample={AUDIO_SR}"
        if len(self.segments) == 1:
            a, b = self.segments[0]
            return f"{pre},{trim(a, b)},asetpts=PTS-STARTPTS[{out}]"
        n = len(self.segments)
        parts = [f"{pre},asplit={n}" + "".join(f"[jc{i}]" for i in range(n))]
        for i, (a, b) in enumerate(self.segments):
            d = (b - a) / self.fps
            fade = ""
            if i > 0:
                fade += ",afade=t=in:d=0.006"
            if i < n - 1:
                fade += f",afade=t=out:st={max(0.0, d - 0.006):.4f}:d=0.006"
            parts.append(f"[jc{i}]{trim(a, b)},asetpts=PTS-STARTPTS{fade}[jd{i}]")
        parts.append("".join(f"[jd{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[{out}]")
        return ";".join(parts)


# ------------------------------------------------------------------ energia do audio
def audio_energy(source: Path, start: float, dur: float):
    """dB por janela de 20 ms (passo de 10 ms) do trecho. None se nao houver audio/der erro."""
    try:
        import numpy as np

        p = subprocess.run(
            [ff.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
             "-i", str(source), "-vn", "-sn", "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"],
            capture_output=True, timeout=120, creationflags=CREATE_NO_WINDOW)
        x = np.frombuffer(p.stdout, np.float32)
        hop, win = 160, 320
        if p.returncode != 0 or len(x) < win * 10:
            return None
        n = (len(x) - win) // hop + 1
        fr = np.lib.stride_tricks.sliding_window_view(x, win)[::hop][:n]
        rms = np.sqrt((fr.astype(np.float64) ** 2).mean(axis=1) + 1e-12)
        return 20 * np.log10(rms)
    except Exception as e:  # noqa: BLE001
        _log.info("energia do audio indisponivel: %s", e)
        return None


def _silent_mask(db):
    """True onde e silencio (limiar adaptativo entre o ruido de fundo e a voz)."""
    import numpy as np

    k = 7
    pad = np.pad(db, (k // 2, k // 2), mode="edge")
    med = np.median(np.lib.stride_tricks.sliding_window_view(pad, k), axis=1)
    noise, speech = np.percentile(db, 8), np.percentile(db, 90)
    if speech - noise < 12:           # sem contraste (musica de fundo, ruido alto): nao confia
        return None
    thr = min(noise + 0.32 * (speech - noise), speech - 16)
    return med < thr


def _runs(mask, lo: float, hi: float) -> list[tuple[float, float]]:
    """Trechos silenciosos (s) dentro de [lo, hi]."""
    i0, i1 = max(0, int(lo / HOP)), min(len(mask), int(hi / HOP) + 1)
    out, cur = [], None
    for i in range(i0, i1):
        if mask[i]:
            if cur is None:
                cur = i
        elif cur is not None:
            out.append((cur * HOP + HOP, i * HOP))   # centro da janela de 20 ms
            cur = None
    if cur is not None:
        out.append((cur * HOP + HOP, i1 * HOP))
    return out


# ------------------------------------------------------------------ plano de cortes
def _words(captions: Transcript | None) -> list[Word]:
    if captions is None:
        return []
    ws = [w for w in captions.words() if (w.text or "").strip() and w.end > w.start - 1e-6]
    return sorted(ws, key=lambda w: w.start)


def plan_cuts(captions: Transcript | None, dur: float, fps: int, cfg=None, energy=None) -> CutPlan | None:
    """Calcula os trechos mantidos. None = nada a cortar (ou sem palavras para se guiar)."""
    g = (lambda k, d: cfg.get(k, d)) if cfg is not None else (lambda k, d: d)
    max_pause = float(g("edicao.silencio_max_s", 0.40) or 0.40)
    keep_pause = float(g("edicao.silencio_vira_s", 0.12) or 0.12)
    pre_roll = min(0.15, float(g("edicao.pre_roll_max_s", 0.15) or 0.15))
    tail = float(g("edicao.final_apos_fala_s", 0.45) or 0.45)
    words = [w for w in _words(captions) if w.start < dur]
    if len(words) < 2 or dur < 2:
        return None
    mask = _silent_mask(energy) if energy is not None and len(energy) > 50 else None
    starts = [w.start for w in words]

    removed: list[tuple[float, float]] = []

    # 1) silencio antes da primeira palavra (o Whisper as vezes marca o inicio tarde: recua ate o ataque)
    s0 = words[0].start
    onset = s0
    if mask is not None:
        i = int(s0 / HOP)
        lim = int(max(0.0, s0 - 0.5) / HOP)
        while i - 1 >= lim and i - 1 < len(mask) and not mask[i - 1]:
            i -= 1
        onset = min(s0, i * HOP)
    lead_end = max(0.0, onset - min(pre_roll, 0.08))
    if lead_end >= 0.12:
        removed.append((0.0, lead_end))

    # 2) pausas entre palavras
    after, before = keep_pause * 0.58, keep_pause * 0.42    # um pouco mais de "respiro" depois da fala
    for p, nx in zip(words, words[1:]):
        if nx.start - p.end < max_pause * 0.6 and mask is None:
            continue
        if mask is not None:
            lo, hi = p.start + 0.12, nx.start + 0.06
            if hi - lo < max_pause:
                continue
            runs = [r for r in _runs(mask, lo, hi) if r[1] - r[0] > max_pause]
        else:
            runs = [(p.end, nx.start)] if nx.start - p.end > max_pause else []
        for r0, r1 in runs:
            c0, c1 = r0 + after, r1 - before
            # nunca dentro de palavra: se o Whisper ouviu uma palavra comecar ali, encurta o corte
            inside = [s for s in starts if c0 + 0.05 < s < c1]
            if inside:
                c1 = min(inside) - 0.05
            if c1 - c0 >= 0.10:
                removed.append((c0, c1))

    # 3) silencio depois da ultima fala (mantem a reacao: anda ate o fim do som + respiro)
    last = max(w.end for w in words)
    end_keep = min(dur, last + tail)
    if mask is not None:
        i = int(min(dur, words[-1].start + 0.1) / HOP)
        while i < len(mask) and i * HOP < dur and not mask[i]:
            i += 1
        end_keep = min(dur, max(i * HOP + 0.25, words[-1].end + 0.2))
        end_keep = max(end_keep, min(dur, last + 0.15))
    if dur - end_keep >= 0.30:
        removed.append((end_keep, dur))

    if not removed:
        return None
    # mantidos = complemento dos removidos, na grade de quadros
    removed.sort()
    keep: list[tuple[int, int]] = []
    cur = 0.0
    for r0, r1 in removed:
        if r0 > cur:
            keep.append((int(round(cur * fps)), int(round(r0 * fps))))
        cur = max(cur, r1)
    total_f = int(round(dur * fps))
    if cur < dur:
        keep.append((int(round(cur * fps)), total_f))
    keep = [(a, min(b, total_f)) for a, b in keep if b - a >= 1]
    # pedacos muito curtos (< 0,2 s) voltam a colar no vizinho (desfaz o corte entre eles)
    merged: list[list[int]] = []
    for a, b in keep:
        if merged and (b - a < round(0.2 * fps) or merged[-1][1] - merged[-1][0] < round(0.2 * fps)) \
                and a - merged[-1][1] <= round(1.5 * fps):
            merged[-1][1] = b
        else:
            merged.append([a, b])
    segs = [(a, b) for a, b in merged if b > a]
    if not segs:
        return None
    if len(segs) == 1 and segs[0][0] == 0 and segs[0][1] >= total_f - 1:
        return None
    rem = []
    prev = 0
    for a, b in segs:
        if a > prev:
            rem.append((prev / fps, a / fps))
        prev = b
    if prev < total_f:
        rem.append((prev / fps, dur))
    return CutPlan(segs, fps, dur, rem)


def retime(captions: Transcript | None, plan: CutPlan | None) -> Transcript | None:
    """Legenda na linha do tempo da saida (depois dos cortes)."""
    if captions is None or plan is None:
        return captions
    mp = plan.map_time
    segs: list[Segment] = []
    for s in captions.segments:
        words = []
        for w in s.words:
            a, b = mp(w.start), mp(w.end)
            if b - a < 0.02 and a >= plan.out_duration - 0.02:
                continue
            words.append(Word(round(a, 3), round(max(b, a + 0.02), 3), w.text))
        a, b = mp(s.start), mp(s.end)
        if b <= a and not words:
            continue
        segs.append(Segment(round(a, 3), round(max(a, b), 3), s.text, words))
    return Transcript(segs, captions.language, captions.source)
