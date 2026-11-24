"""Antes de baixar qualquer coisa, o Claude le a lista de videos achados e escolhe os que rendem corte de verdade.

A busca mede o que esta bombando, mas numero alto nao quer dizer que o video tem um momento que um desconhecido entende
(votacao na Camara, bolsa de valores e pos-jogo bombam e quase nunca rendem). Uma chamada por rodada, que evita gastar tres
chamadas em cada video fraco. Os resultados do proprio canal entram na conversa: canal que so deu corte reprovado cai.
"""
from __future__ import annotations

import time
from typing import Any

from . import db, log

_log = log.get("escolha")
LISTA, DA_CASA, POR_CANAL, POR_ASSUNTO, MINIMA = 75, 42, 2, 5, 52
TETO_NICHO = {"politica": 6, "noticias": 4, "futebol": 4}
SYSTEM = ("Você escolhe os vídeos-fonte de um canal brasileiro de cortes virais. Conhece os podcasts, streamers e famosos do Brasil e sabe quais vídeos têm "
          "momentos que prendem quem nunca viu o canal. Responda SOMENTE com JSON válido.")


def historico_canais() -> dict[str, tuple[int, int]]:
    """{canal: (aprovados, reprovados)} pelos cortes que ja foram julgados."""
    out: dict[str, tuple[int, int]] = {}
    try:
        rs = db.conn().execute(
            "SELECT v.channel, SUM(c.status IN ('aprovado','publicado')), SUM(c.status='rejeitado') FROM clips c "
            "JOIN videos v ON v.id=c.video_id GROUP BY v.channel").fetchall()
        for r in rs:
            if r[0]:
                out[str(r[0])] = (int(r[1] or 0), int(r[2] or 0))
    except Exception as e:
        _log.debug("historico dos canais: %s", e)
    return out


def _nicho(c: Any, r: Any) -> str:
    from .discovery import nichos

    return nichos.niche_for(c, getattr(r, "category", None))


def _estrangeiro(c: Any) -> bool:
    """Canal gringo conhecido: so a busca normal, com nota bem alta, traz."""
    from .discovery import canais
    from .discovery.text import norm

    ex = c.extra or {}
    return bool(ex.get("estrangeiro")) or norm(c.channel or "").replace(" ", "") in {norm(x.lstrip("@")).replace(" ", "") for x in canais.FOREIGN_NAMES}


def _da_casa(c: Any, r: Any) -> bool:
    """Veio de um canal que o CORTEX acompanha (podcast, humor, streamer), e nao e noticia nem futebol."""
    return bool(getattr(r, "big_channel", False) or getattr(r, "monitored", False)) and _nicho(c, r) not in ("politica", "noticias", "futebol")


def lista(pre: list[tuple[Any, Any]]) -> list[tuple[Any, Any]]:
    """Os mais fortes pelos numeros, com variedade: metade dos canais acompanhados, e sem um assunto ou nicho tomar a lista."""
    canal: dict[str, int] = {}
    nicho: dict[str, int] = {}
    assunto: dict[str, int] = {}
    out: list[tuple[Any, Any]] = []

    def entra(c: Any, r: Any) -> bool:
        if _estrangeiro(c):
            return False
        k, n = (c.channel or c.id).lower(), _nicho(c, r)
        a = c.topic or ("gta 6" if "gta" in (c.title or "").lower() else "")
        if canal.get(k, 0) >= POR_CANAL or nicho.get(n, 0) >= TETO_NICHO.get(n, 999) or (a and assunto.get(a, 0) >= POR_ASSUNTO):
            return False
        canal[k], nicho[n] = canal.get(k, 0) + 1, nicho.get(n, 0) + 1
        if a:
            assunto[a] = assunto.get(a, 0) + 1
        out.append((c, r))
        return True

    casa = 0
    for c, r in pre:
        if casa >= DA_CASA:
            break
        if _da_casa(c, r):
            casa += entra(c, r)
    for c, r in pre:
        if len(out) >= LISTA:
            break
        if not _da_casa(c, r):
            entra(c, r)
    return out


def _linha(i: int, c: Any, r: Any, agora: float) -> str:
    idade = f"{max(0, agora - c.upload_ts) / 3600:.0f} h" if c.upload_ts else "?"
    vph = f", {c.views / max(1.0, (agora - c.upload_ts) / 3600):.0f}/h" if c.views and c.upload_ts else ""
    dur = f"{(c.duration or 0) / 60:.0f} min" if c.duration else "? min"
    alta = f" | em alta: {c.topic}" if c.topic and (getattr(r, "topics", None) or {}) else ""
    return f"{i}. {(c.title or '')[:110]} | {c.channel} | {dur} | {c.views or 0} views{vph} | há {idade} | {_nicho(c, r)}{alta}"


def prompt(itens: list[tuple[Any, Any]], quantos: int) -> str:
    agora = time.time()
    hist = historico_canais()
    nomes = {c.channel for c, _ in itens}
    bons = [f"{k} ({a} de {a + b})" for k, (a, b) in hist.items() if a and k in nomes]
    ruins = [f"{k} (0 de {b})" for k, (a, b) in hist.items() if not a and b >= 3 and k in nomes]
    h = ("\nO que já aconteceu aqui (cortes aprovados por canal): " + "; ".join(bons) if bons else "") + \
        ("\nCanais que até agora só deram corte reprovado: " + "; ".join(ruins) + ". Só escolha de novo com motivo forte." if ruins else "")
    linhas = "\n".join(_linha(i, c, r, agora) for i, (c, r) in enumerate(itens, 1))
    return f"""Escolha os vídeos que vamos cortar agora. Cada corte tem de 30 a 58 segundos, é quase só fala, e precisa fazer sentido para quem nunca viu o vídeo.

Público: brasileiros de 16 a 35 anos no YouTube Shorts, TikTok e Instagram. Assuntos do canal: podcast, humor, famosos, streamers, games, curiosidades e polêmica.{h}

RENDE BEM: entrevista ou podcast com gente conhecida contando história com desfecho, confissão, briga, opinião que divide; humorista; streamer perdendo a cabeça ou reagindo a algo que todo mundo conhece; curiosidade ou revelação completa; assunto em alta explicado por alguém com opinião forte.
RENDE MAL (nota abaixo de 50): jornal, votação, sessão, economia e bolsa, análise técnica, pós-jogo ou debate sobre um time só, gameplay sem reação, campeonato, música ou batalha de rima, muita gente falando junto, vídeo que depende da imagem, propaganda, aula, culto, coletânea, crime com vítima.
Política: no máximo 1, e só com frase de impacto ou briga.
Só vídeo falado em português: canal gringo (Joe Rogan, MrBeast e parecidos) fica de fora, mesmo com título traduzido.
Prefira nome conhecido e assunto que muita gente entende. Vídeo que está bombando agora ganha pontos, mas não salva assunto fraco.

VÍDEOS
{linhas}

Cada linha: título | canal | duração | visualizações e velocidade | idade | assunto. Vídeo com mais de 20 minutos de conversa rende mais cortes que vídeo curto já editado ou esquete roteirizada.

Devolva de 8 a {quantos} vídeos, do melhor para o pior, no máximo 2 do mesmo canal, de assuntos variados. "nota" de 0 a 100 é a chance de sair pelo menos um corte forte: 85 = quase certo, 70 = boa, 55 = talvez. Seja honesto: só passa de 80 o que você publicaria.
RESPONDA SÓ COM ESTE JSON:
{{"videos":[{{"n":1,"nota":80,"motivo":"até 10 palavras"}}]}}"""


def aplicar(itens: list[tuple[Any, Any]], resp: list[dict], quantos: int) -> list[tuple[Any, Any]]:
    """Os escolhidos, em ordem, com a nota guardada em extra['ia_nota']."""
    vistos: set[int] = set()
    out = []
    for d in resp:
        try:
            n, nota = int(d.get("n")), float(d.get("nota"))
        except (TypeError, ValueError):
            continue
        if not 1 <= n <= len(itens) or n in vistos or nota < MINIMA:
            continue
        vistos.add(n)
        c, r = itens[n - 1]
        c.extra = dict(c.extra or {})
        c.extra["ia_nota"], c.extra["ia_motivo"] = min(100.0, nota), str(d.get("motivo") or "")[:100]
        out.append((c, r))
    out.sort(key=lambda x: -x[0].extra["ia_nota"])
    return out[:quantos]


def escolher(pre: list[tuple[Any, Any]], cfg: Any, quantos: int = 14) -> list[tuple[Any, Any]] | None:
    """Lista curta escolhida pelo Claude, ou None (sem Claude, sem resposta ou lista pequena demais)."""
    if cfg is None or not cfg.get("busca.escolha_ia", True) or len(pre) < 8:
        return None
    from .brain import get_brain
    from .brain.base import extract_json, list_from_json

    b = get_brain(cfg, tarefa="escolha")
    if b.name != "claude":
        return None
    itens = lista(pre)
    try:
        resp = list_from_json(extract_json(b._run(prompt(itens, quantos), SYSTEM)), ("videos", "escolhidos"))
    except Exception as e:
        _log.warning("a escolha dos videos nao respondeu: %s", str(e)[:150])
        return None
    out = aplicar(itens, [d for d in resp if isinstance(d, dict)], quantos)
    for c, _ in out:
        _log.info("escolhido %.0f '%s' (%s): %s", c.extra["ia_nota"], (c.title or "")[:70], c.channel, c.extra["ia_motivo"])
    return out if len(out) >= 2 else None


def rapida(cands: list[Any], cfg: Any, minima: float = 70) -> list[Any]:
    """Via rapida: do que esta explodindo, o que vale um corte agora. Jornal e politica explodem o dia inteiro e ficam para a rodada normal."""
    from .brain import get_brain
    from .brain.base import extract_json, list_from_json

    itens = [(c, None) for c in cands if _nicho(c, None) not in ("politica", "noticias")][:15]
    if not itens or not cfg.get("busca.escolha_ia", True):
        return [c for c, _ in itens]
    b = get_brain(cfg, tarefa="escolha")
    if b.name != "claude":
        return []
    try:
        resp = list_from_json(extract_json(b._run(prompt(itens, 3), SYSTEM)), ("videos", "escolhidos"))
    except Exception as e:
        _log.warning("a escolha da via rapida nao respondeu: %s", str(e)[:150])
        return []
    out = [c for c, _ in aplicar(itens, [d for d in resp if isinstance(d, dict)], 3) if c.extra["ia_nota"] >= minima]
    _log.info("via rapida: %d de %d passaram%s", len(out), len(itens), "".join(f" | {c.extra['ia_nota']:.0f} {(c.title or '')[:50]}" for c in out))
    return out


def nota_final(c: Any) -> float:
    """Junta a nota dos numeros com a da escolha (a escolha pesa mais)."""
    ia = (c.extra or {}).get("ia_nota")
    return c.score if ia is None else round(0.35 * (c.score or 0) + 0.65 * float(ia), 1)
