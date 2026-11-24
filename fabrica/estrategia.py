"""Saude das contas (nota 0 a 100 com criterio), estimativa de tempo ate viralizar e as decisoes do estrategista.

NOTA (por rede):
  alcance 35     mediana de views dos posts com 20 h ou mais (200 = fraco, 1 mil = ok, 10 mil = otimo)
  retencao 30    YouTube: % que continuou assistindo (50 ruim, 70 bom, 80 otimo). TikTok: % do video assistido
  tendencia 15   ultimos 5 posts contra os 5 anteriores
  engajamento 10 curtidas por view (1% fraco, 4% bom, 8% otimo)
  conta 10       sem pausa, CAPTCHA, remocao ou restricao
Com menos de 3 posts maduros a nota e PROVISORIA (usa o que ha e diz isso).

DECISOES (uma vez por dia, passo de no maximo 1, sempre dentro dos tetos do config):
  quantidade por rede, mistura de assuntos, formatos (testes A/B) e buscas sugeridas pelo analista.
"""
from __future__ import annotations

import json
import math
import random
import time
from datetime import date
from typing import Any

from . import andamento, db, log, numeros, paths

_log = log.get("estrategia")
STATE = paths.STATE / "estrategia.json"
NOMES = {"youtube": "YouTube", "tiktok": "TikTok", "instagram": "Instagram"}
VIRAL_VIEWS = 10_000


def state() -> dict:
    return andamento.read_json(STATE) or {}


def _lerp(x: float, pts: list[tuple[float, float]]) -> float:
    """Interpolacao por pontos (x, nota 0..1)."""
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def _med(v: list[float]) -> float | None:
    s = sorted(x for x in v if x is not None)
    return None if not s else (s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2)


def duracao(rede: str, rd: dict, plan: dict) -> float:
    """Duracao do video que foi para esta rede (o TikTok pode ter recebido a versao longa)."""
    if rede in ("tiktok", "instagram") and plan.get("ext_start") is not None and plan.get("ext_end"):
        return float(plan["ext_end"]) - float(plan["ext_start"])
    return float(rd.get("duration") or 0)


def posts(rede: str, days: float = 45) -> list[dict]:
    out = []
    for r in numeros.latest(days):
        if r["platform"] != rede or r["views"] is None:
            continue
        try:
            rd = json.loads(r["rendered"] or "{}") or {}
            plan = json.loads(r["plan"] or "{}") or {}
        except Exception:
            rd, plan = {}, {}
        dur = duracao(rede, rd, plan)
        age = (time.time() - r["post_ts"]) / 3600
        ret = r["ficou_pct"] if rede == "youtube" else (
            100 * r["tempo_medio_s"] / dur if r["tempo_medio_s"] and dur else r["completo_pct"])
        out.append({"id": r["post_id"], "titulo": r["title"] or "", "views": int(r["views"]), "likes": r["likes"] or 0,
                    "ret": ret, "tempo": r["tempo_medio_s"], "dur": dur, "idade_h": age, "categoria": plan.get("category"),
                    "tipo": plan.get("tipo"), "url": r["url"], "fonte": plan.get("source_id"), "extra": json.loads(r["extra"] or "{}")})
    return out


# ------------------------------------------------------------------ nota
def saude(rede: str, cfg: Any = None, ps: list[dict] | None = None) -> dict:
    """{"nota", "nivel", "provisoria", "partes": {...}, "n", "resumo", "motivos": [...]}"""
    ps = posts(rede) if ps is None else ps
    maduros = [p for p in ps if p["idade_h"] >= 20]
    base = maduros or ps
    if not base:
        return {"nota": None, "nivel": "sem dados", "provisoria": True, "partes": {}, "n": 0, "resumo": "ainda sem números",
                "motivos": []}
    med = _med([p["views"] for p in base]) or 0.0
    rets = [p["ret"] for p in base if p["ret"] is not None]
    eng = [p["likes"] / p["views"] for p in base if p["views"] >= 20]
    partes = {"alcance": 35 * _lerp(math.log10(max(1.0, med)), [(0.5, 0), (2.3, 0.3), (3, 0.6), (4, 1.0)])}
    if rets:
        pts = [(35, 0), (50, 0.25), (60, 0.5), (70, 0.8), (80, 1)] if rede == "youtube" else [(8, 0), (25, 0.3), (45, 0.65), (70, 1)]
        partes["retencao"] = 30 * _lerp(_med(rets) or 0, pts)
    if len(maduros) >= 6:
        novos, velhos = maduros[:5], maduros[5:10]
        r = (math.log1p(_med([p["views"] for p in novos]) or 0) - math.log1p(_med([p["views"] for p in velhos]) or 0))
        partes["tendencia"] = 15 * _lerp(r, [(-1.0, 0), (0, 0.5), (1.0, 1)])
    if eng:
        partes["engajamento"] = 10 * _lerp(100 * (_med(eng) or 0), [(0, 0), (1, 0.3), (4, 0.75), (8, 1)])
    problemas = _problemas(rede)
    partes["conta"] = 0.0 if problemas else 10.0
    pesos = {"alcance": 35, "retencao": 30, "tendencia": 15, "engajamento": 10, "conta": 10}
    total = sum(pesos[k] for k in partes)
    nota = round(100 * sum(partes.values()) / total) if total else None
    prov = len(maduros) < 3
    nivel = "ótima" if nota >= 75 else "boa" if nota >= 55 else "regular" if nota >= 38 else "fraca"
    motivos = list(problemas)
    if med < 20 and len(base) >= 2:
        motivos.append("a rede quase não está entregando os vídeos (menos de 20 views)")
    if rets and (_med(rets) or 0) < (50 if rede == "youtube" else 20):
        motivos.append("as pessoas saem nos primeiros segundos: o começo do corte precisa prender mais")
    if eng and (_med(eng) or 0) < 0.01:
        motivos.append("poucas curtidas por view")
    ret_txt = f"{_med(rets):.0f}% " + ("continuam vendo" if rede == "youtube" else "do vídeo assistido") if rets else "sem retenção ainda"
    return {"nota": nota, "nivel": nivel, "provisoria": prov, "partes": {k: round(v, 1) for k, v in partes.items()}, "n": len(base),
            "maduros": len(maduros), "mediana": round(med), "retencao": _med(rets), "resumo": f"mediana {_fmt(med)} views, {ret_txt}",
            "motivos": motivos}


def _fmt(v: float) -> str:
    return f"{v:.0f}" if v < 1000 else f"{v / 1000:.1f} mil".replace(".", ",")


def _problemas(rede: str) -> list[str]:
    out = []
    try:
        from .publish import guard

        pz = guard.paused_until(rede)
        if pz:
            out.append("rede parada por segurança, precisa de você")
        if guard.captchas_today(rede):
            out.append(f"{guard.captchas_today(rede)} CAPTCHA nas últimas 24 h")
        n = db.conn().execute("SELECT COUNT(*) FROM post_metrics WHERE platform=? AND status IN ('removido','restrito','direitos','violacao')"
                              " AND ts>=?", (rede, time.time() - 14 * 86400)).fetchone()[0]
        if n:
            out.append(f"{n} post(s) removido(s) ou com restrição nos últimos 14 dias")
    except Exception as e:
        _log.debug("problemas: %s", e)
    return out


# ------------------------------------------------------------------ estimativa de viral
def viral(rede: str, cfg: Any = None, por_dia: float | None = None, ps: list[dict] | None = None) -> dict:
    """Quando deve sair o primeiro post com 10 mil views, se nada mudar.

    Modelo simples e honesto: views de posts seguem uma curva log-normal. Parte do que se sabe de conta nova
    (mediana 300, muita variacao) e vai se ajustando com os posts reais. Devolve faixa, nunca uma data."""
    ps = posts(rede) if ps is None else ps
    alvo = float(cfg.get("estrategia.viral_views", VIRAL_VIEWS)) if cfg is not None else VIRAL_VIEWS
    done = [p for p in ps if p["views"] >= alvo]
    if done:
        return {"ja": True, "n": len(done), "melhor": max(p["views"] for p in done), "texto": f"já aconteceu: {len(done)} post(s) acima de {_fmt(alvo)}"}
    if por_dia is None:
        try:
            from . import policy

            por_dia = float(policy.effective_limit(rede, cfg) or 1)
        except Exception:
            por_dia = 2.0
    ys = [math.log(max(1.0, p["views"])) for p in ps]
    n = len(ys)
    mu0, k0, s0, v0 = math.log(300), 3.0, 1.35, 6.0          # conta nova tipica; pesa como 3 posts
    m = sum(ys) / n if n else mu0
    k, mu = k0 + n, (k0 * mu0 + sum(ys)) / (k0 + n)
    ss = sum((y - m) ** 2 for y in ys)
    # com poucos posts a variacao nao da para medir: usa a tipica (senao um post ruim faria a estimativa melhorar)
    var = s0 ** 2 if n < 8 else (v0 * s0 ** 2 + ss) / (v0 + n)
    rng, dias = random.Random(11), []
    for _ in range(3000):
        sig = math.sqrt(var * (v0 + n) / max(1e-6, rng.gammavariate((v0 + n) / 2, 2)))
        mus = rng.gauss(mu, sig / math.sqrt(k))
        z = (math.log(alvo) - mus) / sig
        p = 0.5 * math.erfc(z / math.sqrt(2))
        dias.append(rng.expovariate(max(1e-7, p * por_dia)))
    dias.sort()
    lo, mid, hi = dias[int(0.25 * len(dias))], dias[len(dias) // 2], dias[int(0.75 * len(dias))]
    conf = "chute" if n < 5 else "baixa" if n < 15 else "média" if n < 40 else "boa"
    maduros = sum(p["idade_h"] >= 20 for p in ps)
    faixa = f"de {_dias(lo)} a {_dias(hi)}" if _dias(lo) != _dias(hi) else _dias(hi)
    if maduros < 5:
        return {"ja": False, "dias": round(mid), "lo": round(lo), "hi": round(hi), "confianca": "chute", "n": n,
                "texto": f"cedo para dizer ({maduros} de 5 posts com 24 h). Se seguir assim, chute {faixa}"}
    return {"ja": False, "dias": round(mid), "lo": round(lo), "hi": round(hi), "confianca": conf, "n": n,
            "texto": f"{faixa} (confiança: {conf}, {n} post{'s' if n != 1 else ''} medido{'s' if n != 1 else ''})"}


def _dias(d: float) -> str:
    if d < 1.5:
        return "1 dia"
    if d < 14:
        return f"{d:.0f} dias"
    if d < 60:
        return f"{d / 7:.0f} semanas"
    if d < 540:
        return f"{d / 30:.0f} meses"
    return "mais de 1 ano e meio"


# ------------------------------------------------------------------ decisoes
def quantidade(rede: str, base: int) -> int:
    """Quantidade por dia decidida pelo estrategista (base = o que o config manda)."""
    q = (state().get("quantidade") or {}).get(rede)
    return int(q) if q else base


def mix(base: dict) -> dict:
    return (state().get("mix") or {}) or base


def buscas() -> list[str]:
    return list(state().get("buscas") or [])[:5]


def evitar() -> list[str]:
    return list(state().get("evitar") or [])[:5]


def decidir(cfg: Any, force: bool = False) -> list[str]:
    """Roda uma vez por dia. Muda um passo por vez, so com dados suficientes. Devolve as decisoes em frases."""
    st = state()
    if not force and st.get("dia") == date.today().isoformat():
        return []
    frases: list[str] = []
    q = dict(st.get("quantidade") or {})
    teto = cfg.get("estrategia.teto", {"youtube": 3, "tiktok": 6, "instagram": 3}) or {}
    for rede in cfg.get("publicacao.plataformas", ["youtube", "tiktok"]):
        s = saude(rede, cfg)
        from . import policy

        base = int((cfg.get("publicacao.max_posts_por_dia", {}) or {}).get(rede, 2))
        cur = int(q.get(rede) or policy.daily_limit(rede, cfg))     # o que vale hoje de verdade
        if s["nota"] is None or s.get("maduros", 0) < 8:
            frases.append(f"{NOMES.get(rede, rede)}: mantém {cur} por dia (só {s.get('maduros', 0)} post(s) com 24 h; decido a partir de 8)")
            continue
        novo = cur
        if s["nota"] >= 65 and not _problemas(rede):
            novo = min(int(teto.get(rede, base)), cur + 1)
        elif s["nota"] < 35:
            novo = max(1, cur - 1)
        if novo != cur:
            q[rede] = novo
            frases.append(f"{NOMES.get(rede, rede)}: {cur} para {novo} por dia (saúde {s['nota']}/100, {s['resumo']})")
        else:
            frases.append(f"{NOMES.get(rede, rede)}: mantém {cur} por dia (saúde {s['nota']}/100)")
    st["quantidade"] = q
    m = _novo_mix(cfg)
    if m:
        st["mix"] = m
        frases.append("assuntos: " + ", ".join(f"{k} {v * 100:.0f}%" for k, v in sorted(m.items(), key=lambda x: -x[1])))
    st["dia"] = date.today().isoformat()
    st.setdefault("historico", []).append({"ts": time.time(), "decisoes": frases})
    st["historico"] = st["historico"][-60:]
    andamento.write_json(STATE, st)
    for f in frases:
        _log.info("decisao: %s", f)
    return frases


def _novo_mix(cfg: Any) -> dict:
    """Assuntos que rendem mais ganham espaco (de 10% a 60%), com peso para o que ja estava no config."""
    base = dict(cfg.get("busca.mix_nichos", {"politica": 0.3, "games": 0.35, "humor": 0.35}) or {})
    by: dict[str, list[float]] = {}
    for rede in ("youtube", "tiktok"):
        ps = [p for p in posts(rede) if p["idade_h"] >= 20]
        med = _med([p["views"] for p in ps])
        if not med or len(ps) < 6:
            continue
        for p in ps:
            from .discovery import nichos

            k = nichos.map_cat(p["categoria"]) or "outros"
            by.setdefault(k, []).append(math.log1p(p["views"]) - math.log1p(med))
    if sum(len(v) for v in by.values()) < 12:
        return {}
    score = {}
    for k in set(base) | {k for k, v in by.items() if len(v) >= 3 and k != "outros"}:
        v = by.get(k, [])
        score[k] = float(base.get(k, 0.15)) * math.exp((sum(v) / (len(v) + 4)) if v else 0.0)   # encolhe com poucos dados
    tot = sum(score.values())
    out = {k: min(0.6, max(0.1, v / tot)) for k, v in score.items()}
    tot = sum(out.values())
    return {k: round(v / tot, 2) for k, v in out.items()}


def linhas(cfg: Any) -> list[tuple[str, str, str]]:
    """Linhas curtas para o topo do terminal: [(rotulo, texto, nivel)]."""
    out = []
    for rede in cfg.get("publicacao.plataformas", ["youtube", "tiktok"]):
        s = saude(rede, cfg)
        if s["nota"] is None:
            out.append((f"Saúde {NOMES.get(rede, rede)}", "ainda sem números", "sem dados"))
            continue
        bar = "█" * round(s["nota"] / 10) + "░" * (10 - round(s["nota"] / 10))
        out.append((f"Saúde {NOMES.get(rede, rede)}", f"{bar} {s['nota']}/100 {s['nivel']}" + (" (provisória)" if s["provisoria"] else "")
                    + f" | {s['resumo']}", s["nivel"]))
    return out
