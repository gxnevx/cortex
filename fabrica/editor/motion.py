"""Zoom dinamico (punch-in) e expressoes por tempo para o ffmpeg.

- Zoom de impacto no inicio: entra em 1,10x e assenta em 1,00x (ease-out de 0,35 s).
- Punch-in a cada 3 a 5 s alternando 1,00 / 1,08 / 1,15, em corte seco, de preferencia num
  jump cut (o zoom esconde a emenda), senao num fim de frase ou na maior pausa da janela.
- Zoom de enfase: +0,15 por ~0,6 s em 1 a 3 palavras fortes (CAIXA ALTA, "mentira",
  "absurdo", numeros, nomes, risada), no minimo 6 s entre elas.

As curvas viram uma SOMA de degraus/rampas (sem ifs aninhados): expressao curta e rapida.
Tempos na linha do tempo da SAIDA (depois dos jump cuts).
"""
from __future__ import annotations

import random
import re
import unicodedata
from dataclasses import dataclass

from ..models import Transcript

# palavras que pedem enfase (comparadas sem acento, minusculas)
STRONG = {
    "mentira", "mentiroso", "absurdo", "absurda", "nunca", "jamais", "verdade", "milhao", "milhoes", "bilhao",
    "bilhoes", "mil", "dinheiro", "grana", "rico", "rica", "pobre", "morreu", "morri", "morte", "matar", "socorro",
    "serio", "inacreditavel", "impossivel", "chocado", "chocada", "policia", "preso", "presa", "cadeia", "traicao",
    "traiu", "demitido", "demitida", "odio", "odeio", "chorei", "chorar", "chorando", "medo",
    "proibido", "golpe", "roubo", "roubou", "fraude", "crime",
    "escandalo", "polemica", "treta", "briga", "vergonha", "loucura", "louco", "louca", "doido", "doida", "surreal",
    "bizarro", "gigante", "enorme", "acabou", "falido", "falencia", "faliu", "doutor",
    "caralho", "porra", "merda", "foda", "puta", "cacete",
}
# fortes so de leve (muito comuns na fala): valem metade
MEDIUM = {"todo", "tudo", "nada", "ninguem", "primeira", "ultima", "vish", "eita", "nossa", "pior", "melhor", "maior"}
_LAUGH = re.compile(r"^(k{3,}|(ha){2,}h?|(he){2,}|(hu){2,}|(rs){2,}|risos?|risadas?)$")
_NUMWORDS = {"dois", "tres", "quatro", "cinco", "seis", "sete", "oito", "nove", "dez", "cem", "cento", "duzentos",
             "trezentos", "vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa"}
_STOP_CAPS = {"eu", "ele", "ela", "a", "o", "e", "mas", "que", "entao", "porque", "nao", "sim", "voce", "isso", "ai",
              "tipo", "cara", "mano", "olha", "gente", "quem", "como", "se", "so", "um", "uma", "os", "as", "na", "no"}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


@dataclass
class Emph:
    t0: float
    t1: float
    word: str
    score: float


def strong_words(captions: Transcript | None, dur: float, max_n: int | None = None,
                 min_gap: float = 6.0, start_after: float = 1.2) -> list[Emph]:
    """Escolhe 1 a 3 palavras fortes (pontuacao heuristica), espacadas de pelo menos min_gap."""
    if captions is None:
        return []
    words = [w for w in captions.words() if (w.text or "").strip()]
    cands: list[Emph] = []
    prev_raw = ""
    for i, w in enumerate(words):
        raw = (w.text or "").strip()
        core = raw.strip(".,!?;:\"'()[]…-")
        n = _norm(core)
        sc = 0.0
        if not n:
            prev_raw = raw
            continue
        letters = [c for c in core if c.isalpha()]
        if len(letters) >= 3 and all(c.isupper() for c in letters):
            sc += 3.0                                   # CAIXA ALTA na legenda
        if n in STRONG:
            sc += 3.0
        elif n in MEDIUM:
            sc += 1.5
        if re.search(r"[.!?…]$", raw):
            sc += 0.8                                   # fim de frase = ponto alto (punchline)
        if any(c.isdigit() for c in core) or n in _NUMWORDS or n.startswith(("milh", "bilh")):
            sc += 2.5
        if _LAUGH.match(n):
            sc += 3.0
        sentence_start = (i == 0) or bool(re.search(r"[.!?…]$", prev_raw))
        if core[:1].isupper() and not sentence_start and n not in _STOP_CAPS and len(n) >= 3:
            sc += 2.0                                   # provavel nome proprio
        if raw.endswith("!"):
            sc += 1.0
        if len(n) >= 7:
            sc += 0.4
        if sc >= 2.0 and start_after <= w.start <= dur - 0.9:
            cands.append(Emph(w.start, w.end, core, sc))
        prev_raw = raw
    if max_n is None:
        max_n = max(1, min(3, int(round(dur / 12.0))))
    chosen: list[Emph] = []
    for c in sorted(cands, key=lambda c: (-c.score, c.t0)):
        if len(chosen) >= max_n:
            break
        if all(abs(c.t0 - o.t0) >= min_gap for o in chosen):
            chosen.append(c)
    return sorted(chosen, key=lambda c: c.t0)


# ------------------------------------------------------------------ curvas aditivas
@dataclass
class Key:
    t: float           # inicio da transicao
    dv: float          # variacao (soma ao valor anterior)
    d: float = 0.0     # duracao da transicao (0 = degrau seco)
    curve: str = "smooth"   # smooth | out


def expr(base: float, keys: list[Key], var: str) -> str:
    """Expressao do ffmpeg: base + soma das transicoes (degraus ou rampas suaves)."""
    parts = [f"{base:.4f}"]
    for k in keys:
        if abs(k.dv) < 1e-4:
            continue
        dv = f"{k.dv:+.4f}"
        if k.d <= 0.001:
            parts.append(f"{dv}*gte({var},{k.t:.4f})")
            continue
        p = f"clip(({var}-{k.t:.4f})/{k.d:.4f},0,1)"
        if k.curve == "out":
            parts.append(f"{dv}*(1-pow(1-{p},3))")
        else:
            parts.append(f"{dv}*{p}*{p}*(3-2*{p})")
    return "".join(parts)


def value_at(base: float, keys: list[Key], t: float) -> float:
    """Mesmo calculo da expressao, em Python (testes e posicionamento)."""
    v = base
    for k in keys:
        if k.d <= 0.001:
            v += k.dv if t >= k.t else 0.0
        else:
            p = min(1.0, max(0.0, (t - k.t) / k.d))
            v += k.dv * ((1 - (1 - p) ** 3) if k.curve == "out" else p * p * (3 - 2 * p))
    return v


def steps_to_keys(points: list[tuple[float, float, float]], start_value: float) -> list[Key]:
    """[(t, valor_absoluto, duracao)] -> chaves aditivas."""
    keys, cur = [], start_value
    for t, v, d in points:
        if abs(v - cur) > 1e-6:
            keys.append(Key(t, v - cur, d))
            cur = v
    return keys


# ------------------------------------------------------------------ zoom
@dataclass
class ZoomPlan:
    base: float
    keys: list[Key]
    emphasis: list[Emph]
    changes: int

    def expr(self, var: str = "it") -> str:
        return expr(self.base, self.keys, var)

    def at(self, t: float) -> float:
        return value_at(self.base, self.keys, t)


def plan_zoom(captions: Transcript | None, dur: float, cfg=None, seed: str = "", cut_times: list[float] | None = None,
              camera_cuts: list[float] | None = None) -> ZoomPlan:
    g = (lambda k, d: cfg.get(k, d)) if cfg is not None else (lambda k, d: d)
    levels = [float(x) for x in (g("edicao.zoom_niveis", [1.0, 1.08, 1.15]) or [1.0, 1.08, 1.15])]
    levels = sorted({max(1.0, min(1.4, x)) for x in levels}) or [1.0, 1.08, 1.15]
    lo_iv, hi_iv = (g("edicao.zoom_intervalo_s", [3, 5]) or [3, 5])[:2]
    lo_iv, hi_iv = float(lo_iv), max(float(lo_iv) + 0.5, float(hi_iv))
    emph_z = float(g("edicao.zoom_enfase", 1.15) or 1.15)
    impact = bool(g("edicao.zoom_impacto_inicio", True))
    rng = random.Random(f"zoom:{seed}")
    cut_times = sorted(cut_times or [])
    camera_cuts = sorted(camera_cuts or [])

    words = [w for w in captions.words() if (w.text or "").strip()] if captions is not None else []
    emph = strong_words(captions, dur) if bool(g("edicao.zoom_enfase_ligado", True)) else []

    def blocked(t: float) -> bool:
        if t < 0.6 or t > dur - 0.8:
            return True
        if any(e.t0 - 0.5 <= t <= e.t0 + 1.1 for e in emph):
            return True
        # nao "piscar" logo antes/depois de um corte de camera (a nao ser no proprio corte)
        if any(0.05 < abs(t - c) < 0.9 for c in camera_cuts):
            return True
        return False

    # candidatos a troca: jump cuts (peso 3), cortes de camera (2), fim de frase (2), pausas (1 + tamanho)
    cands: list[tuple[float, float]] = [(t, 3.0) for t in cut_times]
    cands += [(t, 2.0) for t in camera_cuts]
    for p, nx in zip(words, words[1:]):
        gap = nx.start - p.end
        t = max(p.end, nx.start - 0.04)
        if re.search(r"[.!?…]$", (p.text or "").strip()):
            cands.append((t, 2.0 + min(gap, 1.0)))
        elif gap > 0.08:
            cands.append((t, 1.0 + min(gap, 1.0)))
    cands = sorted(c for c in cands if not blocked(c[0]))

    points: list[tuple[float, float, float]] = []
    cur = levels[0]
    last = 0.0
    while True:
        lo, hi = last + lo_iv, last + hi_iv
        if lo > dur - 1.5:
            break
        win = [c for c in cands if lo <= c[0] <= hi]
        if win:
            t = max(win, key=lambda c: (c[1], -abs(c[0] - (lo + hi) / 2)))[0]
        else:
            t = (lo + hi) / 2
            if blocked(t):
                # anda ate achar um instante livre
                tt = lo
                while tt <= hi and blocked(tt):
                    tt += 0.1
                if tt > hi:
                    last = hi
                    continue
                t = tt
        # proximo nivel: diferente do atual; volta ao aberto com mais frequencia
        opts = [lv for lv in levels if abs(lv - cur) > 1e-6]
        if cur > levels[0] and rng.random() < 0.55:
            nxt = levels[0]
        else:
            nxt = rng.choice(opts)
        # palavra de enfase no proximo trecho: deixa o enquadramento aberto para o punch-in aparecer
        seg_end = t + hi_iv
        if any(t <= e.t0 <= seg_end for e in emph):
            nxt = levels[0] if abs(cur - levels[0]) > 1e-6 else (levels[1] if len(levels) > 1 else cur)
            if nxt > levels[0] and any(t <= e.t0 <= t + lo_iv for e in emph):
                nxt = cur
        if abs(nxt - cur) > 1e-6:
            points.append((t, nxt, 0.0))
            cur = nxt
        last = t

    start_val = levels[0]
    keys: list[Key] = []
    base = start_val
    if impact:
        base = start_val + 0.10
        keys.append(Key(0.0, -0.10, 0.35, "out"))
    keys += steps_to_keys(points, start_val)
    # enfase: rampa rapida de entrada (80 ms), segura ~0,6 s, volta em 150 ms
    for e in emph:
        t_in = max(0.0, e.t0 - 0.04)
        hold = min(0.9, max(0.6, e.t1 - e.t0 + 0.15))
        lvl = value_at(base, keys, e.t0)
        dz = max(0.06, emph_z - lvl) if lvl < emph_z else 0.08
        keys.append(Key(t_in, dz, 0.08))
        keys.append(Key(t_in + hold, -dz, 0.15))
    keys.sort(key=lambda k: k.t)
    return ZoomPlan(base, keys, emph, len(points))


def with_teaser(main: ZoomPlan | None, teaser_s: float, level: float = 1.10, push: float = 0.04) -> ZoomPlan:
    """Cold open: teaser em ~1,10x com leve avanco (push-in) e, na emenda, o corte normal comeca
    no proprio plano de zoom dele (o zoom de impacto 1,10 -> 1,00 vira a "saida rapida")."""
    keys = [Key(0.0, push, max(0.2, teaser_s), "smooth")]
    end_val = level + push
    if main is None:
        keys.append(Key(teaser_s, 1.0 - end_val, 0.0))
        return ZoomPlan(level, keys, [], 0)
    keys.append(Key(teaser_s, main.base - end_val, 0.0))
    keys += [Key(k.t + teaser_s, k.dv, k.d, k.curve) for k in main.keys]
    emph = [Emph(e.t0 + teaser_s, e.t1 + teaser_s, e.word, e.score) for e in main.emphasis]
    return ZoomPlan(level, keys, emph, main.changes)
