"""IA analista: uma vez por dia le os numeros reais, o placar dos testes A/B e diz o que deu certo e o que nao deu.

Quem faz a conta e o programa (experimentos.py, estrategia.py); a IA interpreta, separa fato de palpite e propoe
buscas e cuidados para os proximos cortes. Nada que ela diga vira "provado" sem passar pelo teste A/B.
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime
from typing import Any

from . import andamento, estrategia, experimentos, log, paths

_log = log.get("analista")
STATE = paths.STATE / "analise.json"

SYSTEM = ("Você é analista de crescimento de um canal novo de cortes (TikTok e YouTube Shorts). Você é cético: só afirma o que os "
          "números mostram, separa prova de palpite e nunca inventa número. Responda SOMENTE com JSON válido, em português do Brasil.")


def last() -> dict:
    return andamento.read_json(STATE) or {}


def _tabela(cfg: Any) -> tuple[str, int]:
    rows = []
    for rede in ("youtube", "tiktok"):
        for p in estrategia.posts(rede)[:25]:
            rows.append(f"{rede} | {p['idade_h']:.0f} h | {p['views']} views | {p['likes']} curtidas | "
                        + (f"retenção {p['ret']:.0f}% | " if p["ret"] is not None else "retenção ? | ")
                        + f"{p['dur']:.0f} s | {p['categoria'] or '?'}/{p['tipo'] or '?'} | {p['titulo'][:80]}"
                        + (f" | param aos {p['extra'].get('para_em_s')} s" if p["extra"].get("para_em_s") is not None else ""))
    return "\n".join(rows), len(rows)


def prompt(cfg: Any) -> tuple[str, int]:
    tab, n = _tabela(cfg)
    ab = "\n".join(f"- {r['pergunta']} {experimentos.frase(r)}" for r in experimentos.avaliar()) or "nenhum teste com dados"
    sa = "\n".join(f"- {estrategia.NOMES[r]}: nota {s['nota']} ({s['resumo']}); pontos {s['partes']}; alertas: {', '.join(s['motivos']) or 'nenhum'}"
                   for r, s in ((r, estrategia.saude(r, cfg)) for r in ("youtube", "tiktok")) if s["nota"] is not None)
    return f"""POSTS (rede | idade | views | curtidas | retenção | duração | assunto/tipo | título). "retenção" no YouTube = % que continuou vendo; no TikTok = % do vídeo assistido:
{tab or 'nenhum'}

SAÚDE DAS CONTAS (0 a 100):
{sa or 'sem dados'}

TESTES A/B (sorteio de verdade; só "PROVADO" é prova):
{ab}

Analise e devolva:
- "resumo": 2 ou 3 frases simples para o dono, que não é técnico, com os números mais importantes.
- "deu_certo": até 3 itens {{"o_que":"...","prova":"número que mostra","forca":"prova|indício|palpite"}}
- "nao_deu": até 3 itens no mesmo formato.
- "padrao": 1 ou 2 frases: o que os melhores têm em comum e os piores não têm. Se há menos de 6 posts, diga que é cedo.
- "buscas": até 5 buscas curtas em português para achar vídeos-fonte parecidos com o que funcionou (assunto + formato). Nada de pessoa específica acusada de algo.
- "evitar": até 3 coisas para os próximos cortes evitarem (curtas e práticas).
- "proximo_teste": 1 frase: o que vale testar a seguir e por quê.
- "alerta": frase curta se algo parece errado na conta (ex.: rede não entregando), senão "".
Com poucos posts quase tudo é "palpite": diga isso.
RESPONDA SÓ COM O JSON.""", n


def analisar(cfg: Any, force: bool = False) -> dict | None:
    """Roda no maximo uma vez por dia e so se houver numeros. Devolve a analise (ou None)."""
    old = last()
    if not force and old.get("dia") == date.today().isoformat():
        return None
    p, n = prompt(cfg)
    if n == 0:
        return None
    d: dict = {}
    try:
        from .brain import get_brain
        from .brain.base import extract_json

        b = get_brain(cfg, tarefa="analise")
        if b.name == "claude":
            d = extract_json(b._run(p, SYSTEM)) or {}
        elif not force:
            return None     # sem o Claude hoje: tenta no proximo ciclo
    except Exception as e:
        _log.warning("analise: %s", str(e)[:200])
    d = d if isinstance(d, dict) else {}
    out = {"dia": date.today().isoformat() if d else old.get("dia"), "ts": time.time(), "n": n,
           "resumo": str(d.get("resumo") or "")[:600], "deu_certo": _itens(d.get("deu_certo")), "nao_deu": _itens(d.get("nao_deu")),
           "padrao": str(d.get("padrao") or "")[:400], "proximo_teste": str(d.get("proximo_teste") or "")[:250],
           "alerta": str(d.get("alerta") or "")[:250], "buscas": _curtas(d.get("buscas"), 5, 60), "evitar": _curtas(d.get("evitar"), 3, 120)}
    if not d:
        return None
    andamento.write_json(STATE, out)
    st = estrategia.state()     # vira orientacao para a busca e para os cortes
    st["buscas"], st["evitar"] = out["buscas"], out["evitar"]
    andamento.write_json(estrategia.STATE, st)
    try:
        log_dir = paths.REPORTS / "analises"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / f"analise_{datetime.now():%Y%m%d}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    _log.info("analise do dia: %s", out["resumo"])
    return out


def _itens(v: Any) -> list[dict]:
    out = []
    for x in v if isinstance(v, list) else []:
        if isinstance(x, dict) and x.get("o_que"):
            f = str(x.get("forca") or "palpite").lower()
            out.append({"o_que": str(x["o_que"])[:160], "prova": str(x.get("prova") or "")[:160],
                        "forca": f if f in ("prova", "indício", "indicio", "palpite") else "palpite"})
    return out[:3]


def _curtas(v: Any, n: int, size: int) -> list[str]:
    return [str(x).strip()[:size] for x in (v if isinstance(v, list) else []) if str(x).strip()][:n]


def ciclo(cfg: Any) -> list[str]:
    """Chamado pelo automatico: coleta, testa, adota, decide e analisa. Devolve novidades para o dono."""
    from . import numeros

    news: list[str] = []
    r = numeros.collect(cfg)
    if r["lidos"]:
        _log.info("numeros: %d lido(s), %d falha(s)", r["lidos"], r["falhas"])
    from . import auditor

    news += auditor.ciclo(cfg)
    a = analisar(cfg)
    if a and a.get("alerta"):
        news.append(a["alerta"])
    return news
