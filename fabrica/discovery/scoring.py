"""Nota 0-100 de potencial de um video-fonte + motivos curtos em pt-BR.

Componentes (peso maximo):
  velocidade (views/hora desde a publicacao) 30 | views absolutas 15 | engajamento (likes+comentarios) 10
  frescor 10 | bate com o assunto/palavra-chave 15 | live/VOD de canal grande ou monitorado 8
  duracao boa para cortes 5 | clipes populares da Twitch 10 | heatmap "mais repetidos" 3 | legenda 2
Titulo que nao parece portugues leva multa (x0.6).
Velocidade: relativa a mediana do proprio canal quando ha historico (discovery/historico.py):
  V = clamp(0.5 + log2(vph / mediana_canal) / 4, 0, 1), misturada 75/25 com a absoluta; sem historico, so absoluta.
Assunto saturado (extra["saturacao"]["pular_melhor_momento"]): nota x0.7.
"""
from __future__ import annotations

import math
import time

from ..models import Candidate
from ..util import fmt_duration
from .text import pt_score

# referencia de "excelente" por plataforma: (views/hora, views totais)
_REF = {"youtube": (150_000, 3_000_000), "twitch": (4_000, 150_000), "kick": (3_000, 100_000),
        "rumble": (20_000, 500_000)}


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def fmt_num(n: float | None) -> str:
    if n is None:
        return "?"
    if n >= 1e6:
        return f"{n / 1e6:.1f}".rstrip("0").rstrip(".").replace(".", ",") + " mi"
    if n >= 1e3:
        return f"{n / 1e3:.1f}".rstrip("0").rstrip(".").replace(".", ",") + " mil"
    return str(int(n))


def _log_ratio(x: float, ref: float) -> float:
    return _clamp(math.log10(x + 1) / math.log10(ref + 1)) if x and x > 0 else 0.0


def score_candidate(c: Candidate, *, now: float | None = None, window_h: float = 48, match: float = 0.0,
                    match_topic: str | None = None, trend_score: float | None = None, big_channel: bool = False,
                    monitored: bool = False, category: str | None = None) -> Candidate:
    """Calcula c.score e c.reasons (sobrescreve). Devolve o proprio candidato."""
    now = now or time.time()
    reasons: list[str] = []
    vph_ref, views_ref = _REF.get(c.platform, _REF["youtube"])
    extra = c.extra or {}
    is_clip = extra.get("tipo") == "clipe"

    age_h = (now - c.upload_ts) / 3600 if c.upload_ts else None
    if age_h is not None:
        age_h = max(age_h, 0.25)

    # velocidade: relativa a mediana do proprio canal (historico), senao absoluta
    if c.views and age_h:
        vph = c.views / age_h
        s_abs = _log_ratio(vph, vph_ref)
        rel = None
        if not is_clip:
            try:
                from . import historico

                rel = historico.relative_velocity(historico.keys_for(c), vph, age_h,
                                                  exclude_id=c.id.split(":", 1)[-1])
            except Exception:  # noqa: BLE001  (historico e opcional)
                rel = None
        if rel:
            s_vel = 0.75 * rel["V"] + 0.25 * s_abs
            c.extra = dict(c.extra or {})
            c.extra["velocidade_rel"] = rel
            if rel["r"] >= 1.5:
                reasons.append(f"{str(rel['r']).replace('.', ',')}x a velocidade normal do canal")
            elif rel["r"] <= 0.5:
                reasons.append("abaixo da velocidade normal do canal")
        else:
            s_vel = s_abs
        if vph >= 300:
            reasons.append(f"{fmt_num(vph)} views/hora")
    else:
        s_vel = 0.3
    # views absolutas
    s_views = _log_ratio(c.views or 0, views_ref) if c.views else 0.25
    if c.views and c.views >= 10_000:
        reasons.append(f"{fmt_num(c.views)} visualizacoes")
    # engajamento
    if c.views and c.views >= 1000 and (c.likes or c.comments):
        ratio = ((c.likes or 0) + 3 * (c.comments or 0)) / c.views
        s_eng = _clamp(ratio / 0.06)
        if ratio >= 0.04:
            reasons.append(f"engajamento alto ({ratio * 100:.1f}%)")
    else:
        s_eng = 0.4
    # frescor
    if age_h is None:
        s_fresh = 0.5
    else:
        s_fresh = _clamp(1 - max(0.0, age_h - 6) / max(1.0, window_h - 6))
        if age_h < 1:
            reasons.append("publicado ha menos de 1 h")
        elif age_h < 48:
            reasons.append(f"publicado ha {int(age_h)} h")
        else:
            reasons.append(f"publicado ha {int(age_h // 24)} dias")
    # assunto
    m = _clamp(match)
    if trend_score is not None:
        m *= 0.6 + 0.4 * _clamp(trend_score / 100)
    if match >= 0.5 and match_topic:
        reasons.append(f"bate com '{match_topic[:50]}'")
    # canal
    s_ch = 0.0
    if monitored:
        s_ch = 0.7
        reasons.append("canal monitorado")
    elif big_channel:
        s_ch = 0.5
        reasons.append(f"canal grande{f' ({category})' if category else ''}")
    if (c.is_live or c.was_live) and (monitored or big_channel):
        s_ch += 0.4
        reasons.append("live/VOD de canal grande")
    s_ch = _clamp(s_ch)
    # duracao
    d = c.duration
    if d is None:
        s_dur = 0.5
    elif is_clip:
        s_dur = 0.5 if 20 <= d <= 90 else 0.2
    elif d < 90:
        s_dur = 0.1
    elif d < 480:
        s_dur = 0.6
    elif d <= 3 * 3600:
        s_dur = 1.0
        if d >= 1800:
            reasons.append(f"{fmt_duration(d)} de material")
    elif d <= 6 * 3600:
        s_dur = 0.8
        reasons.append(f"{fmt_duration(d)} de material")
    else:
        s_dur = 0.5
    # clipes da Twitch
    tclips = extra.get("twitch_clips") or []
    plat_name = {"twitch": "Twitch", "kick": "Kick"}.get(c.platform, c.platform)
    s_tw = 0.0
    if tclips:
        tot = sum(int(x.get("views") or 0) for x in tclips)
        s_tw = _log_ratio(tot, 20_000)
        reasons.append(f"{len(tclips)} clipe(s) popular(es) na {plat_name} ({fmt_num(tot)} views)")
    elif is_clip and c.views:
        s_tw = _log_ratio(c.views, 20_000)
        reasons.append(f"clipe da {plat_name} com {fmt_num(c.views)} views")
    # sinais do enriquecimento
    s_heat = 1.0 if extra.get("heatmap") else 0.0
    if s_heat:
        reasons.append("tem 'mais repetidos' do YouTube")
    s_subs = 1.0 if c.has_subtitles else 0.0
    if c.has_subtitles:
        reasons.append("legenda da plataforma disponivel")

    score = (30 * s_vel + 15 * s_views + 10 * s_eng + 10 * s_fresh + 15 * m + 8 * s_ch + 5 * s_dur
             + 10 * s_tw + 3 * s_heat + 2 * s_subs)
    # idioma
    lang = (extra.get("language") or "").split("-")[0]
    pts = pt_score(f"{c.title} {c.description[:200] if c.description else ''}")
    if (c.extra or {}).get("estrangeiro"):
        # fonte estrangeira aceita (busca.idiomas): sem multa, mas a descoberta exige nota_minima alta
        reasons.append(f"video em '{(c.extra or {}).get('idioma') or lang or '?'}' (fonte estrangeira)")
    elif lang and lang != "pt":
        score *= 0.6
        reasons.append(f"audio em '{lang}' (nao portugues)")
    elif not lang and pts < -0.3 and not (big_channel or monitored):
        score *= 0.6
        reasons.append("titulo parece nao ser em portugues")
    if c.is_live:
        reasons.append("AO VIVO agora")
    # saturacao (discovery/saturacao.py): muitos canais ja cortaram o assunto hoje
    sat = (c.extra or {}).get("saturacao")
    if isinstance(sat, dict) and sat.get("pular_melhor_momento"):
        score *= float(sat.get("multa", 0.7))
        reasons.insert(0, f"assunto saturado ({sat.get('canais')} canais ja cortaram hoje): vai no 2o/3o melhor momento")
    try:
        from .. import auditor

        w = float((auditor.get("canais") or {}).get(c.channel, 1.0))
        if abs(w - 1.0) >= 0.05:
            score *= w
            reasons.append(f"canal {'rende bem' if w > 1 else 'rende pouco'} aqui (x{w:.2f})")
    except Exception:
        pass
    c.score = round(_clamp(score, 0, 100), 1)
    # motivos mais importantes primeiro, sem repeticao
    seen, out = set(), []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            out.append(r)
    c.reasons = out[:8]
    return c
