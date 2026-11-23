"""Auditor: aplica sozinho o que os numeros mandam, confere depois se melhorou e DESFAZ o que piorou.

O que ele pode mexer (sempre dentro de limites fixos, um passo por vez):
  formato     vencedor de teste A/B vai para 80% dos cortes; os outros 20% seguem testando e o proprio teste desfaz
  quantidade  posts por dia em cada rede (estrategia.py)
  assuntos    mistura de nichos e buscas (estrategia.py / analista.py)
  horarios    ordem das janelas de post de cada rede
  fontes      peso de cada canal-fonte na escolha dos videos (0,75 a 1,25)
  regua       nota minima do editor-chefe (64 a 76)
O que ele NUNCA mexe: regras de conteudo (o que nao pode ir ao ar), tetos, login, seguranca e o programa em si.

Cada mudanca fica registrada com o "antes". Depois de 8 posts maduros com a mudanca, compara com os anteriores na
mesma rede: caiu 30% ou mais com boa certeza = volta ao que era e fica 21 dias sem tentar de novo.
"""
from __future__ import annotations

import math
import time
from datetime import datetime
from typing import Any

from . import andamento, db, estrategia, experimentos, log, paths

_log = log.get("auditor")
STATE = paths.STATE / "auditor.json"
MIN_POSTS, QUEDA, CERTEZA, CASTIGO_D = 8, 0.30, 0.90, 21


def state() -> dict:
    return andamento.read_json(STATE) or {}


def _save(st: dict) -> None:
    st["registro"] = (st.get("registro") or [])[-200:]
    andamento.write_json(STATE, st)


def get(chave: str, default: Any = None) -> Any:
    """Valor ajustado pelo auditor (janelas.youtube, canais, regua...)."""
    return (state().get("valores") or {}).get(chave, default)


def _bloqueado(st: dict, chave: str) -> bool:
    return time.time() < float((st.get("castigo") or {}).get(chave, 0))


def registrar(st: dict, chave: str, antes: Any, depois: Any, porque: str, redes: list[str]) -> str:
    """Anota uma mudanca para conferir depois."""
    st.setdefault("registro", []).append({"ts": time.time(), "chave": chave, "antes": antes, "depois": depois, "porque": porque,
                                          "redes": redes, "estado": "conferindo"})
    _log.info("mudou %s: %s", chave, porque)
    return porque


# ------------------------------------------------------------------ dados
def maduros(rede: str, days: float = 60) -> list[dict]:
    return [p for p in estrategia.posts(rede, days) if p["idade_h"] >= 20]


def _post_ts(p: dict) -> float:
    return time.time() - p["idade_h"] * 3600


# ------------------------------------------------------------------ ajustes
def ajustar_horarios(st: dict, cfg: Any) -> list[str]:
    """Reordena as janelas de cada rede pelo que rendeu de verdade (a pesquisa vale como 6 posts de cada janela)."""
    from . import policy

    out = []
    for rede in cfg.get("publicacao.plataformas", ["youtube", "tiktok"]):
        chave = f"janelas.{rede}"
        ps = maduros(rede)
        if len(ps) < 14 or _bloqueado(st, chave):
            continue
        base = policy.base_windows(rede, cfg)
        med = sorted(math.log1p(p["views"]) for p in ps)[len(ps) // 2]
        score = {}
        for i, w in enumerate(base):
            a, b = (int(x.split(":")[0]) + int(x.split(":")[1]) / 60 for x in w.split("-"))
            ys = [math.log1p(p["views"]) - med for p in ps
                  if a - 0.25 <= (lambda d: d.hour + d.minute / 60)(datetime.fromtimestamp(_post_ts(p))) <= b + 0.5]
            prior = 0.35 - 0.2 * i                       # a ordem da pesquisa
            score[w] = (6 * prior + sum(ys)) / (6 + len(ys))
        nova = sorted(base, key=lambda w: -score[w])
        atual = (st.get("valores") or {}).get(chave) or base
        if nova != atual and nova[0] != atual[0]:        # so quando muda a janela principal
            st.setdefault("valores", {})[chave] = nova
            out.append(registrar(st, chave, atual, nova, f"{estrategia.NOMES.get(rede, rede)}: melhor horário agora é {nova[0]} (era {atual[0]})", [rede]))
    return out


def ajustar_canais(st: dict, cfg: Any) -> list[str]:
    """Canais-fonte que rendem mais sobem na escolha; os que so dao post fraco descem (peso 0,75 a 1,25)."""
    if _bloqueado(st, "canais"):
        return []
    by: dict[str, list[float]] = {}
    n = 0
    for rede in cfg.get("publicacao.plataformas", ["youtube", "tiktok"]):
        ps = maduros(rede)
        if len(ps) < 12:
            continue
        med = sorted(math.log1p(p["views"]) for p in ps)[len(ps) // 2]
        for p in ps:
            row = db.conn().execute("SELECT channel FROM videos WHERE id=?", (p["fonte"],)).fetchone()
            if row and row["channel"]:
                by.setdefault(row["channel"], []).append(math.log1p(p["views"]) - med)
                n += 1
    if n < 20:
        return []
    novo = {c: round(min(1.25, max(0.75, math.exp(0.5 * sum(v) / (len(v) + 5)))), 2) for c, v in by.items() if len(v) >= 3}
    novo = {c: w for c, w in novo.items() if abs(w - 1) >= 0.05}
    atual = (st.get("valores") or {}).get("canais") or {}
    if all(abs(novo.get(c, 1) - atual.get(c, 1)) < 0.08 for c in set(novo) | set(atual)):
        return []
    st.setdefault("valores", {})["canais"] = novo
    top = sorted(novo.items(), key=lambda x: -x[1])
    txt = ", ".join(f"{c} {'sobe' if w > 1 else 'desce'}" for c, w in (top[:2] + [x for x in top[-2:] if x not in top[:2]]))
    return [registrar(st, "canais", atual, novo, f"fontes: {txt}", ["youtube", "tiktok"])]


def ajustar_regua(st: dict, cfg: Any) -> list[str]:
    """Nota minima do editor-chefe: fila sobrando sobe a regua; faltando corte para o dia, desce (64 a 76)."""
    if _bloqueado(st, "regua"):
        return []
    from . import autopilot

    base = float(cfg.get("curadoria.nota_minima", 68))
    atual = float((st.get("valores") or {}).get("regua") or base)
    if time.time() - float(st.get("regua_ts") or 0) < 2 * 86400:
        return []
    dia = time.time() - 48 * 3600
    ap = db.conn().execute("SELECT COUNT(*) FROM clips WHERE created>=? AND curador LIKE 'aprovado%'", (dia,)).fetchone()[0]
    rj = db.conn().execute("SELECT COUNT(*) FROM clips WHERE created>=? AND curador LIKE 'descartado%'", (dia,)).fetchone()[0]
    if ap + rj < 12:
        return []
    q, cap = len(autopilot.queue(cfg)), max(1, autopilot.capacity(cfg))
    novo = atual + 1 if q >= 3 * cap and ap / (ap + rj) > 0.4 else atual - 1 if q < cap and ap / (ap + rj) < 0.25 else atual
    novo = min(76.0, max(64.0, novo))
    if novo == atual:
        return []
    st.setdefault("valores", {})["regua"], st["regua_ts"] = novo, time.time()
    return [registrar(st, "regua", atual, novo, f"régua de qualidade: {atual:.0f} para {novo:.0f} ({'sobra' if novo > atual else 'falta'} corte bom na fila)",
                      ["youtube", "tiktok"])]


# ------------------------------------------------------------------ conferir e desfazer
def conferir(st: dict, cfg: Any) -> list[str]:
    """Cada mudanca e conferida com os posts que vieram depois. Piorou de verdade: desfaz."""
    out = []
    for r in st.get("registro") or []:
        if r.get("estado") != "conferindo":
            continue
        piorou = melhorou = pronto = False
        for rede in r["redes"]:
            ps = maduros(rede)
            antes = [p for p in ps if r["ts"] - 21 * 86400 <= _post_ts(p) < r["ts"]]
            depois = [p for p in ps if _post_ts(p) >= r["ts"]]
            if len(antes) < MIN_POSTS or len(depois) < MIN_POSTS:
                continue
            pronto = True
            ya, yb = [math.log1p(p["views"]) for p in antes[:20]], [math.log1p(p["views"]) for p in depois[:20]]
            p_melhor = experimentos._prob_b_melhor(ya, yb)
            efeito = math.exp(sum(yb) / len(yb) - sum(ya) / len(ya)) - 1
            r.setdefault("efeito", {})[rede] = round(efeito, 2)
            piorou |= efeito <= -QUEDA and p_melhor <= 1 - CERTEZA
            melhorou |= efeito >= 0.15 and p_melhor >= CERTEZA
        if not pronto:
            if time.time() - r["ts"] > 60 * 86400:
                r["estado"] = "sem dados"
            continue
        if piorou and not melhorou:
            _desfazer(st, r)
            out.append(f"desfiz: {r['porque']} (as views caíram depois)")
        else:
            r["estado"] = "aprovada" if melhorou else "neutra"
            if melhorou:
                out.append(f"deu certo: {r['porque']}")
    return out


def _desfazer(st: dict, r: dict) -> None:
    r["estado"] = "desfeita"
    k = r["chave"]
    if k.startswith("quantidade."):
        e = estrategia.state()
        e.setdefault("quantidade", {})[k.split(".", 1)[1]] = r["antes"]
        andamento.write_json(estrategia.STATE, e)
    elif k == "assuntos":
        e = estrategia.state()
        e["mix"] = r["antes"] or {}
        andamento.write_json(estrategia.STATE, e)
    else:
        st.setdefault("valores", {})[k] = r["antes"]
    st.setdefault("castigo", {})[k] = time.time() + CASTIGO_D * 86400
    _log.warning("desfiz %s: %s", k, r["porque"])


# ------------------------------------------------------------------ ciclo
def ciclo(cfg: Any) -> list[str]:
    """Uma vez por dia (o automatico chama a cada 30 min; so age quando vira o dia)."""
    st = state()
    hoje = datetime.now().strftime("%Y%m%d")
    if st.get("dia") == hoje or datetime.now().hour < 8:
        return []
    news: list[str] = []
    # 1) primeiro confere o que ja mudou; 2) depois muda (no maximo 2 mudancas por dia, para saber o que causou o que)
    news += conferir(st, cfg)
    _save(st)
    mudancas: list[str] = []
    qa, ma, va = dict(estrategia.state().get("quantidade") or {}), dict(estrategia.state().get("mix") or {}), dict(experimentos.state().get("vencedores") or {})
    mudancas += experimentos.adotar()
    vn = experimentos.state().get("vencedores") or {}
    for t in set(va) | set(vn):
        if t not in experimentos.TESTES:
            continue
        redes = list((vn.get(t) or va.get(t) or {}).get("redes") or ["youtube", "tiktok"])
        if t in vn and (va.get(t) or {}).get("lado") != vn[t]["lado"]:
            registrar(st, f"formato.{t}", va.get(t), vn[t], f"formato: {experimentos.TESTES[t][vn[t]['lado']]} vai para 80% dos cortes", redes)
            st["registro"][-1]["estado"] = "em teste"       # o A/B segue medindo nos outros 20%
        elif t in va and t not in vn:
            for r in st.get("registro") or []:
                if r["chave"] == f"formato.{t}" and r["estado"] == "em teste":
                    r["estado"] = "desfeita"
    estrategia.decidir(cfg)
    e = estrategia.state()
    for rede, q in (e.get("quantidade") or {}).items():
        from . import policy

        velho = qa.get(rede) or int((cfg.get("publicacao.max_posts_por_dia", {}) or {}).get(rede, 2))
        if qa.get(rede) != q and velho != q:
            if _bloqueado(st, f"quantidade.{rede}"):
                e["quantidade"][rede] = velho
                andamento.write_json(estrategia.STATE, e)
                continue
            mudancas.append(registrar(st, f"quantidade.{rede}", velho, q, f"{estrategia.NOMES.get(rede, rede)}: {velho} para {q} posts por dia", [rede]))
    if e.get("mix") and e["mix"] != ma and any(abs(e["mix"].get(k, 0) - ma.get(k, 0)) >= 0.05 for k in set(e["mix"]) | set(ma)):
        if _bloqueado(st, "assuntos"):
            e["mix"] = ma
            andamento.write_json(estrategia.STATE, e)
        else:
            mudancas.append(registrar(st, "assuntos", ma, e["mix"], "assuntos: " + ", ".join(f"{k} {v * 100:.0f}%" for k, v in sorted(e["mix"].items(), key=lambda x: -x[1])), ["youtube", "tiktok"]))
    for fn in (ajustar_horarios, ajustar_canais, ajustar_regua):
        if len(mudancas) >= 2:
            break
        try:
            mudancas += fn(st, cfg)
        except Exception as ex:
            _log.warning("%s: %s", fn.__name__, str(ex)[:150])
    st["dia"] = hoje
    _save(st)
    return news + mudancas


def linhas(n: int = 8) -> list[str]:
    """Ultimas decisoes, para o terminal."""
    out = []
    for r in reversed((state().get("registro") or [])[-n:]):
        ef = " ".join(f"{estrategia.NOMES.get(k, k)} {v * 100:+.0f}%" for k, v in (r.get("efeito") or {}).items())
        out.append(f"{datetime.fromtimestamp(r['ts']):%d/%m} {r['porque']} [{r['estado']}{', ' + ef if ef else ''}]")
    return out
