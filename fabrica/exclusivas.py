"""Redes com cortes so delas (publicacao.redes_exclusivas): o corte que sai nelas nao sai nas outras, e vice-versa.

YouTube e TikTok formam o conjunto (o mesmo corte vai para os dois). O Instagram pega OUTROS cortes da fila: avulsos
(sem Parte 1/2/3), mais curtos, de preferencia humor, games e reacao; politica e noticia por ultimo. So ficam guardados
para o conjunto os cortes que ainda saem nele HOJE, e a rede exclusiva que esta zerada no dia passa na frente de um deles.
"""
from __future__ import annotations

import json
import re
from typing import Any

from . import db

CATEGORIAS = {"humor": 5, "games": 5, "entretenimento": 4, "curiosidade": 3, "podcast": 1, "polemica": 0, "noticias": -6, "politica": -8}
# a categoria vem da IA e as vezes erra: titulo e nome da fonte tambem contam
SERIO_RE = re.compile(r"\b(stf|stm|tse|senado|senador\w*|c[aâ]mara|deputad\w+|vereador\w*|presidente|ministr\w+|governo|prefeit\w+|lula|bolsonaro|"
                      r"trump|cleitinho|elei[cç][aã]o|jornal|news|not[ií]cias?|cpi)\b", re.I)
TIPOS = {"reacao": 3, "humor": 3, "curiosidade": 2, "noticia": -4}


def redes(cfg: Any) -> list[str]:
    plats = cfg.get("publicacao.plataformas", ["youtube", "tiktok"]) or []
    return [p for p in (cfg.get("publicacao.redes_exclusivas", []) or []) if p in plats]


def conjunto(cfg: Any) -> list[str]:
    ex = redes(cfg)
    return [p for p in (cfg.get("publicacao.plataformas", ["youtube", "tiktok"]) or []) if p not in ex]


def postados(clip_id: str) -> set[str]:
    """Redes em que este corte ja saiu (ou pode ter saido: o clique em Publicar conta)."""
    out = {r["platform"] for r in db.conn().execute("SELECT platform FROM posts WHERE clip_id=? AND ok=1 AND dry_run=0", (clip_id,)).fetchall()}
    try:
        from .publish import guard

        out |= {p for p in ("youtube", "tiktok", "instagram") if guard.publish_clicked(clip_id, p)}
    except Exception:
        pass
    return out


def e_de_exclusiva(clip_id: str, cfg: Any, ja: set[str] | None = None) -> bool:
    ja = postados(clip_id) if ja is None else ja
    return any(p in ja for p in redes(cfg))


def nota(clip: Any, fontes_recentes: list[str] | None = None) -> float:
    """Quanto este corte combina com uma rede exclusiva (a nota do editor mais o gosto da rede)."""
    p = clip.plan
    dur = float(clip.duration or 0)
    v = float(p.score or 0) + CATEGORIAS.get(str(p.category or ""), 0) + TIPOS.get(str(p.tipo or ""), 0)
    v += 3 if dur and dur <= 45 else 0
    if SERIO_RE.search(f"{p.title or ''} {str(p.id).replace('-', ' ')}"):
        v += min(0, -10 - min(0, CATEGORIAS.get(str(p.category or ""), 0)))
    if getattr(p, "ext_start", None) is not None:
        v -= 2          # a versao com o @ certo e a longa
    if fontes_recentes and p.source_id in fontes_recentes:
        v -= 4          # varia a fonte
    return v


def _fontes_recentes(rede: str, n: int = 2) -> list[str]:
    rows = db.conn().execute("SELECT c.plan FROM posts p JOIN clips c ON c.id = p.clip_id WHERE p.platform=? AND p.ok=1 AND p.dry_run=0 "
                             "ORDER BY p.ts DESC LIMIT ?", (rede, n)).fetchall()
    out = []
    for r in rows:
        try:
            out.append((json.loads(r["plan"] or "{}") or {}).get("source_id"))
        except ValueError:
            continue
    return [x for x in out if x]


def reserva(rede: str, cfg: Any, restam: int | None = None, feitos: int | None = None) -> int:
    """Quantos cortes ainda sem post ficam guardados para YouTube e TikTok: os horarios que faltam nelas hoje. Com a rede exclusiva
    zerada no dia, um a menos (ela tambem precisa postar). restam/feitos: simulacao do cronograma."""
    from . import policy

    restam = max([len(policy.slots_today(p, cfg)) for p in conjunto(cfg)] or [0]) if restam is None else restam
    feitos = db.posts_today(rede) if feitos is None else feitos
    return max(0, restam - (0 if feitos else 1))


def candidatos(rede: str, cfg: Any, fila: list, ja: dict[str, set[str]] | None = None, fontes: list[str] | None = None,
             guardar: int | None = None) -> list:
    """Cortes da fila que servem para esta rede, do melhor para o pior (vazio = nada sobrando). ja/fontes: simulacao do cronograma."""
    real = ja is None
    ja = {c.plan.id: postados(c.plan.id) for c in fila} if ja is None else ja
    livres = [c for c in fila if not ja.get(c.plan.id)]
    guardar = reserva(rede, cfg) if guardar is None else guardar
    if len(livres) <= guardar:
        return []
    ok = [c for c in livres if not c.plan.part and (not real or db.failed_attempts(c.plan.id, rede) < 3)]
    rec = _fontes_recentes(rede) if fontes is None else fontes
    return sorted(ok, key=lambda c: (nota(c, rec), c.plan.id), reverse=True)


def escolher(rede: str, cfg: Any, fila: list, ja: dict[str, set[str]] | None = None, fontes: list[str] | None = None,
             guardar: int | None = None) -> Any | None:
    """O melhor, ou None."""
    return next(iter(candidatos(rede, cfg, fila, ja, fontes, guardar)), None)
