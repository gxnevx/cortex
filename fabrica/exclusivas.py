"""Redes com cortes so delas (publicacao.redes_exclusivas): o corte que sai nelas nao sai nas outras, e vice-versa.

YouTube e TikTok formam o conjunto (o mesmo corte vai para os dois). O Instagram pega OUTROS cortes da fila: avulsos
(sem Parte 1/2/3), mais curtos, de preferencia humor, games e reacao; politica e noticia por ultimo. So ficam guardados
para o conjunto os cortes que ainda saem nele HOJE, e a rede exclusiva que esta zerada no dia passa na frente de um deles.

publicacao.repetir_sem_exclusivo: quando nao ha corte so dela, a rede repete um avulso que ja saiu no conjunto (autorizado pelo
dono em 25/11). O arquivo do corte fica no PC ate ela usar, por no maximo REPETE_DIAS dias.
"""
from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path
from typing import Any

from . import db

REPETE_DIAS = 4
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
    """Saiu so na rede exclusiva: as outras pulam. Se tambem ja saiu no conjunto, foi a rede exclusiva que repetiu."""
    ja = postados(clip_id) if ja is None else ja
    return any(p in ja for p in redes(cfg)) and not any(p in ja for p in conjunto(cfg))


def pode_repetir(clip: Any, rede: str, cfg: Any, ja: set[str] | None = None) -> bool:
    """Avulso que ja saiu no conjunto e ainda da para sair nesta rede? ja: simulacao do cronograma (nao olha o arquivo)."""
    if not cfg.get("publicacao.repetir_sem_exclusivo", False) or clip.plan.part:
        return False
    real, i = ja is None, clip.plan.id
    ja = postados(i) if ja is None else ja
    if rede in ja or not any(p in ja for p in conjunto(cfg)):
        return False
    c = db.conn()
    r = c.execute("SELECT MIN(ts) t, SUM(COALESCE(error, '') LIKE 'apagado%') a FROM posts WHERE clip_id=? AND ok=1 AND dry_run=0", (i,)).fetchone()
    if r["a"] or (r["t"] and r["t"] < time.time() - REPETE_DIAS * 86400):
        return False        # o dono apagou, ou ja ficou velho
    from .metrics import PROBLEM_STATUSES

    marcas = ",".join("?" * len(PROBLEM_STATUSES))
    if c.execute(f"SELECT 1 FROM post_metrics WHERE clip_id=? AND status IN ({marcas})", (i, *PROBLEM_STATUSES)).fetchone():
        return False        # removido, restrito ou com aviso de direitos em outra rede
    return not real or (Path(clip.path_for(rede)).exists() and Path(clip.path).exists() and db.failed_attempts(i, rede) < 3)


def guardados(cfg: Any) -> list:
    """Cortes ja publicados no conjunto cujo arquivo fica no PC porque uma rede exclusiva ainda pode repetir."""
    if not redes(cfg) or not cfg.get("publicacao.repetir_sem_exclusivo", False):
        return []
    from .models import RenderedClip

    out = []
    for r in db.conn().execute("SELECT rendered FROM clips WHERE status='publicado' AND rendered IS NOT NULL AND id IN "
                               "(SELECT clip_id FROM posts WHERE ok=1 AND dry_run=0 AND ts>=?)", (time.time() - REPETE_DIAS * 86400,)).fetchall():
        try:
            c = RenderedClip.from_dict(json.loads(r["rendered"]))
        except Exception:
            continue
        if any(pode_repetir(c, p, cfg) for p in redes(cfg)):
            out.append(c)
    return out


def segurar(clip: Any, cfg: Any) -> bool:
    """O arquivo deste corte ja publicado deve ficar no PC?"""
    return any(pode_repetir(clip, p, cfg) for p in redes(cfg))


def _views(clip_id: str) -> int:
    """O maximo de views que este corte ja fez em alguma rede."""
    r = db.conn().execute("SELECT MAX(views) v FROM post_metrics WHERE clip_id=?", (clip_id,)).fetchone()
    return int(r["v"] or 0)


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


def reserva(rede: str, cfg: Any, restam: int | None = None, feitos: int | None = None, repete: bool = False) -> int:
    """Quantos cortes ainda sem post ficam guardados para YouTube e TikTok: os horarios que faltam nelas hoje. Com a rede exclusiva
    zerada no dia e sem nada para repetir, um a menos (ela tambem precisa postar). restam/feitos: simulacao do cronograma."""
    from . import policy

    restam = max([len(policy.slots_today(p, cfg)) for p in conjunto(cfg)] or [0]) if restam is None else restam
    feitos = db.posts_today(rede) if feitos is None else feitos
    return max(0, restam - (0 if feitos or repete else 1))


def candidatos(rede: str, cfg: Any, fila: list, ja: dict[str, set[str]] | None = None, fontes: list[str] | None = None,
             guardar: int | None = None, restam: int | None = None, feitos: int | None = None) -> list:
    """Cortes que servem para esta rede, do melhor para o pior: primeiro os so dela, depois os que ela pode repetir.
    ja/fontes/restam/feitos: simulacao do cronograma."""
    real = ja is None
    ja = {c.plan.id: postados(c.plan.id) for c in fila} if ja is None else ja
    rec = _fontes_recentes(rede) if fontes is None else fontes
    rep = [c for c in [*fila, *(guardados(cfg) if real else [])] if pode_repetir(c, rede, cfg, None if real else ja.get(c.plan.id) or set())]
    rep.sort(key=lambda c: (nota(c, rec) + min(8.0, 2 * math.log10(1 + _views(c.plan.id))), c.plan.id), reverse=True)
    livres = [c for c in fila if not ja.get(c.plan.id)]
    guardar = reserva(rede, cfg, restam, feitos, bool(rep)) if guardar is None else guardar
    if len(livres) <= guardar:
        return rep
    # o ranking sai primeiro no conjunto (e onde ele e comparado com o corte normal); aqui entra repetido
    ok = [c for c in livres if not c.plan.part and c.plan.tipo != "ranking" and (not real or db.failed_attempts(c.plan.id, rede) < 3)]
    return sorted(ok, key=lambda c: (nota(c, rec), c.plan.id), reverse=True) + rep


def escolher(rede: str, cfg: Any, fila: list, ja: dict[str, set[str]] | None = None, fontes: list[str] | None = None,
             guardar: int | None = None, restam: int | None = None, feitos: int | None = None) -> Any | None:
    """O melhor, ou None."""
    return next(iter(candidatos(rede, cfg, fila, ja, fontes, guardar, restam, feitos)), None)
