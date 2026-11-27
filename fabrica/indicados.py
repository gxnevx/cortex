"""Canais que o dono indicou (busca.indicados): entram sempre na busca e a IA que escolhe os cortes e a revisao sabem
qual e a graca daquele canal.

Com prioridade (o padrao) o canal ganha pontos na escolha dos videos, a IA corta esses momentos primeiro e o corte sai
antes no YouTube e no TikTok. Com prioridade: false ele so concorre igual aos outros e os numeros decidem.

busca:
  indicados:
    - {canal: "@handle", nome: "NOME DO CANAL", gosto: "que momentos cortar", prioridade: true}
"""
from __future__ import annotations

from typing import Any

BONUS = 10      # pontos na escolha dos videos (nao salva video fraco: a revisao continua igual)


def lista(cfg: Any) -> list[dict]:
    v = cfg.get("busca.indicados", []) if cfg is not None else []
    return [x for x in v or [] if isinstance(x, dict) and (x.get("canal") or x.get("nome"))]


def prioriza(x: dict | None) -> bool:
    """O dono quer este canal na frente (prioridade: true, o padrao) ou so quer que ele concorra igual aos outros."""
    return bool(x) and x.get("prioridade", True) is not False


def canais(cfg: Any) -> list[str]:
    """Handles do YouTube para a busca acompanhar."""
    return [str(x["canal"]) for x in lista(cfg) if x.get("canal")]


def do_video(video: Any, cfg: Any) -> dict | None:
    """A indicacao que vale para este video, ou None."""
    from .discovery.text import norm

    ch = norm(getattr(video, "channel", "") or "").replace(" ", "")
    url = (getattr(video, "channel_url", "") or "").lower().rstrip("/")
    for x in lista(cfg):
        nome = norm(str(x.get("nome") or "")).replace(" ", "")
        canal = str(x.get("canal") or "").lower()
        if (nome and nome == ch) or (canal and url.endswith("/" + canal)):
            return x
    return None


def do_clip(clip: Any, cfg: Any) -> dict | None:
    """A indicacao que vale para o video de onde este corte saiu, ou None."""
    if not lista(cfg):
        return None
    from types import SimpleNamespace

    from . import db

    r = db.conn().execute("SELECT channel, data FROM videos WHERE id=?", (clip.plan.source_id,)).fetchone()
    if r is None:
        return None
    import json

    try:
        url = (json.loads(r["data"] or "{}") or {}).get("channel_url")
    except ValueError:
        url = None
    return do_video(SimpleNamespace(channel=r["channel"], channel_url=url), cfg)


def para_revisao(clip: Any, cfg: Any) -> str:
    """O revisor precisa saber qual e a graca do canal indicado (as notas minimas continuam as mesmas)."""
    x = do_clip(clip, cfg)
    if not x or not x.get("gosto"):
        return ""
    return (f"\nContexto: {x.get('nome') or x.get('canal')} é um canal que está em alta e que o dono pediu. A graça dele: {str(x['gosto']).strip()} "
            "Quem vê este corte costuma conhecer essa piada; julgue o humor sabendo disso. Começar direto na fala dele, com o título explicando a situação, não é defeito.")


def bloco(video: Any, cfg: Any) -> str:
    """Trecho do pedido de cortes para a IA."""
    x = do_video(video, cfg)
    if not x or not x.get("gosto"):
        return ""
    if not prioriza(x):
        return (f"\nCANAL QUE O DONO ACOMPANHA ({x.get('nome') or x.get('canal')}). A graça dele: {str(x['gosto']).strip()} "
                "Use isso só para entender o humor: este canal concorre igual aos outros, então corte apenas se o momento for forte pelas regras gerais.\n")
    return (f"\nCANAL INDICADO PELO DONO ({x.get('nome') or x.get('canal')}). O que ele quer ver deste canal: {str(x['gosto']).strip()} "
            "Escolha esses momentos primeiro, mesmo que as regras gerais peçam outra coisa, e continue exigindo começo claro, desfecho e título verdadeiro.\n")


def para_escolha(itens: list, cfg: Any) -> str:
    """Linha do pedido de escolha de videos."""
    achei = {}
    for c, _r in itens:
        x = do_video(c, cfg)
        if prioriza(x):
            achei[str(x.get("nome") or x.get("canal"))] = str(x.get("gosto") or "")[:220]
    if not achei:
        return ""
    return "\nIndicação do dono (inclua pelo menos 1 vídeo de cada, o mais promissor): " + "; ".join(f"{n}" + (f" ({g})" if g else "") for n, g in achei.items()) + "."
