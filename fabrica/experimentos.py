"""Testes A/B de verdade: cada corte e SORTEADO em cada teste antes de ser feito; depois os numeros reais decidem.

- O sorteio e fixo por corte e independente entre testes (um corte participa de todos ao mesmo tempo).
- Compara dentro da mesma rede, com a leitura perto de 24 h (ou 72 h). Metrica principal: views (em log, para um
  estouro nao decidir sozinho). Metrica de apoio: quanto do video as pessoas assistem.
- So julga em marcos fixos (12, 24, 40, 60, 90 posts de cada lado) e com exigencia alta em cada um, para nao cair na
  armadilha de olhar todo dia e parar quando parece que ganhou. Ate o primeiro marco diz quanto falta.
- Vencedor vai para 80% dos cortes novos; 20% continuam no outro lado para conferir se segue valendo.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import time
from typing import Any

from . import andamento, db, log, paths

_log = log.get("experimentos")
STATE = paths.STATE / "experimentos.json"
# Olhar o placar todo dia e parar quando "ganhou" inventa vencedor: medido em simulacao, 31% de falso vencedor com
# regra de 95%. Por isso o placar so e julgado em marcos fixos (posts de cada lado), com exigencia alta em cada um.
MARCOS = {12: 0.996, 24: 0.992, 40: 0.988, 60: 0.985, 90: 0.985}
MIN_N = min(MARCOS)
KEEP = 0.80                 # fatia do vencedor

# id -> (pergunta, variante A, variante B). A = o que o programa fazia antes.
TESTES: dict[str, dict] = {
    "gancho": {"pergunta": "Abrir com a frase mais forte ou começar direto?", "A": "abre com a frase", "B": "começa direto"},
    "titulo": {"pergunta": "Título com frase entre aspas ou título direto?", "A": "com aspas", "B": "direto"},
    "longo": {"pergunta": "TikTok: versão longa (61 s ou mais) ou curta?", "A": "curta", "B": "longa", "redes": ["tiktok"]},
    "layout": {"pergunta": "Fundo desfocado ou tela cheia?", "A": "fundo desfocado", "B": "tela cheia"},
    "emoji": {"pergunta": "Título com emoji ou sem emoji?", "A": "com emoji", "B": "sem emoji"},
}


def _u(clip_id: str, teste: str) -> float:
    return int(hashlib.sha1(f"ab|{teste}|{clip_id}".encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF


def state() -> dict:
    return andamento.read_json(STATE) or {}


def fatia_a(teste: str) -> float:
    """Que parte dos cortes novos vai para a variante A."""
    v = (state().get("vencedores") or {}).get(teste)
    return 0.5 if not v else (KEEP if v["lado"] == "A" else 1 - KEEP)


def lado(clip_id: str, teste: str) -> str:
    """Sorteio do corte neste teste: 'A' ou 'B'."""
    return "A" if _u(clip_id, teste) < fatia_a(teste) else "B"


# ------------------------------------------------------------------ dados
def _rows(days: float = 60) -> list[dict]:
    from . import numeros

    out = []
    for r in numeros.latest(days):
        try:
            plan = json.loads(r["plan"] or "{}")
        except Exception:
            continue
        lados = plan.get("exp") or {}
        if not lados:
            continue
        m = numeros.at_age(r["post_id"], 24) or numeros.at_age(r["post_id"], 72)
        if not m or m["views"] is None:
            continue
        from . import estrategia

        dur = estrategia.duracao(r["platform"], json.loads(r["rendered"] or "{}") or {}, plan)
        ret = m["ficou_pct"] if m["ficou_pct"] is not None else (
            100 * m["tempo_medio_s"] / dur if m["tempo_medio_s"] and dur else None)
        out.append({"rede": r["platform"], "lados": lados, "y": math.log1p(m["views"]), "views": m["views"], "ret": ret,
                    "fonte": plan.get("source_id"), "post_id": r["post_id"]})
    return out


def _prob_b_melhor(a: list[float], b: list[float], n: int = 4000, seed: int = 7) -> float:
    """P(media de B > media de A) por bootstrap bayesiano (nao supoe formato da distribuicao)."""
    import numpy as np

    rng = np.random.default_rng(seed)

    def draw(x: list[float]):
        w = rng.standard_exponential((n, len(x)))
        return (w @ np.asarray(x, float)) / w.sum(axis=1)

    return float((draw(b) > draw(a)).mean())


def _compare(xa: list[float], xb: list[float]) -> dict:
    p = _prob_b_melhor(xa, xb) if len(xa) >= 3 and len(xb) >= 3 else 0.5
    ma, mb = (sum(xa) / len(xa) if xa else 0.0), (sum(xb) / len(xb) if xb else 0.0)
    return {"p_b": p, "ma": ma, "mb": mb}


def avaliar(rows: list[dict] | None = None) -> list[dict]:
    """Placar de cada teste em cada rede."""
    rows = _rows() if rows is None else rows
    out = []
    for tid, t in TESTES.items():
        for rede in t.get("redes") or ["youtube", "tiktok"]:
            g = {"A": [], "B": []}
            for r in rows:
                if r["rede"] == rede and r["lados"].get(tid) in g:
                    g[r["lados"][tid]].append(r)
            # partes da mesma fonte nao sao independentes: no maximo 3 por fonte em cada lado
            for k in g:
                seen: dict[str, int] = {}
                keep = []
                for r in g[k]:
                    seen[r["fonte"]] = seen.get(r["fonte"], 0) + 1
                    if seen[r["fonte"]] <= 3:
                        keep.append(r)
                g[k] = keep
            na, nb = len(g["A"]), len(g["B"])
            marco = max([m for m in MARCOS if m <= min(na, nb)], default=0)
            if marco:       # so os primeiros `marco` posts de cada lado, na ordem em que sairam
                g = {k: sorted(v, key=lambda r: r["post_id"])[:marco] for k, v in g.items()}
            c = _compare([r["y"] for r in g["A"]], [r["y"] for r in g["B"]])
            ra = [r["ret"] for r in g["A"] if r["ret"] is not None]
            rb = [r["ret"] for r in g["B"] if r["ret"] is not None]
            rc = _compare(ra, rb)
            efeito = math.exp(c["mb"] - c["ma"]) - 1 if na and nb else 0.0
            falta = max(0, MIN_N - na) + max(0, MIN_N - nb)
            ganhador, p = ("B", c["p_b"]) if c["p_b"] >= 0.5 else ("A", 1 - c["p_b"])
            contra = len(ra) >= 5 and len(rb) >= 5 and (rc["p_b"] if ganhador == "A" else 1 - rc["p_b"]) >= 0.9
            if falta:
                ver = "cedo"
            elif p >= MARCOS[marco] and not contra:
                ver = "provado"
            elif contra and p >= MARCOS[marco]:
                ver = "conflito"        # mais views mas menos retencao: nao adota
            elif marco >= 60 and p < 0.90:
                ver = "empate"
            else:
                ver = "indicio" if p >= 0.93 else "aberto"
            out.append({"teste": tid, "rede": rede, "pergunta": t["pergunta"], "A": t["A"], "B": t["B"], "na": na, "nb": nb,
                        "mediana_a": _med([r["views"] for r in g["A"]]), "mediana_b": _med([r["views"] for r in g["B"]]),
                        "ret_a": _med(ra), "ret_b": _med(rb), "p": round(p, 3), "ganhador": ganhador, "efeito": round(efeito, 3),
                        "falta": falta, "marco": marco, "veredito": ver})
    return out


def _med(x: list[float]) -> float | None:
    s = sorted(v for v in x if v is not None)
    return None if not s else (s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2)


# ------------------------------------------------------------------ decisao
def adotar(placar: list[dict] | None = None) -> list[str]:
    """Adota vencedores provados (80/20) e volta para 50/50 se a prova sumir. Devolve o que mudou, em frases."""
    placar = avaliar() if placar is None else placar
    st = state()
    venc = dict(st.get("vencedores") or {})
    mudou = []
    for tid, t in TESTES.items():
        res = [r for r in placar if r["teste"] == tid]
        prov = [r for r in res if r["veredito"] == "provado"]
        lados = {r["ganhador"] for r in prov}
        if len(lados) == 1:
            lado_ = lados.pop()
            # a outra rede nao pode estar dizendo o contrario com forca
            if any(r["ganhador"] != lado_ and r["p"] >= 0.8 and not r["falta"] for r in res):
                continue
            if (venc.get(tid) or {}).get("lado") != lado_:
                venc[tid] = {"lado": lado_, "ts": time.time(), "redes": [r["rede"] for r in prov]}
                mudou.append(f"{t['pergunta']} Ganhou: {t[lado_]}. Vai para 80% dos próximos cortes.")
        elif tid in venc and res and all(r["veredito"] in ("aberto", "empate", "conflito") for r in res if not r["falta"]) \
                and any(not r["falta"] for r in res):
            venc.pop(tid)
            mudou.append(f"{t['pergunta']} A vantagem sumiu com mais dados: voltou para metade e metade.")
    if mudou:
        st["vencedores"] = venc
        st.setdefault("historico", []).extend({"ts": time.time(), "msg": m} for m in mudou)
        andamento.write_json(STATE, st)
        for m in mudou:
            _log.info("A/B: %s", m)
    return mudou


def frase(r: dict) -> str:
    """Resultado em uma linha simples."""
    nome = {"youtube": "YouTube", "tiktok": "TikTok"}.get(r["rede"], r["rede"])
    if r["veredito"] == "cedo":
        return f"{nome}: cedo demais ({r['na']} x {r['nb']} posts, faltam {r['falta']})"
    quem = r[r["ganhador"]]
    ef = r["efeito"] if r["ganhador"] == "B" else (1 / (1 + r["efeito"]) - 1 if r["efeito"] > -1 else 0)
    base = f"{nome}: {quem} rende {ef * 100:+.0f}% views (certeza {r['p'] * 100:.0f}%, {r['na']} x {r['nb']} posts)"
    return {"provado": f"{base}. PROVADO", "indicio": f"{base}. Indício, ainda não é prova",
            "empate": f"{nome}: tanto faz ({r['na']} x {r['nb']} posts)", "aberto": f"{nome}: sem diferença clara ainda "
            f"({r['na']} x {r['nb']} posts)", "conflito": f"{base}, mas as pessoas assistem menos. Não adoto"}[r["veredito"]]


def aprendizados(placar: list[dict] | None = None, max_n: int = 4) -> list[str]:
    """Frases que podem orientar a IA: so o que esta provado ou com indicio forte."""
    placar = avaliar() if placar is None else placar
    ok = sorted((r for r in placar if r["veredito"] in ("provado", "indicio")), key=lambda r: -r["p"])
    return [f"{frase(r)}" for r in ok[:max_n]]
