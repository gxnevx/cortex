"""Cronograma: o que ja saiu hoje e o que deve sair nos proximos dias em cada rede (horario e corte).

E uma previsao: o horario vem das mesmas regras do automatico (policy) e os cortes sao os da fila de agora. Corte novo melhor
passa na frente, e quem nao tem corte ainda aparece como "a definir".
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Any

from . import db, exclusivas, policy


def horarios(rede: str, cfg: Any, dia: date) -> list[float]:
    """Horarios de post desta rede num dia (hoje: so os que ainda faltam)."""
    if dia == date.today():
        hoje = [max(t, time.time()) for t, _ in policy.slots_today(rede, cfg)]
        return hoje or (policy.slots_on(rede, cfg, dia) if policy.pausa_saude(rede, cfg) else [])
    return policy.slots_on(rede, cfg, dia)


def montar(cfg: Any, dias: int = 4, fila: list | None = None) -> list[dict]:
    """[{ts, rede, titulo, parte, clip_id, feito, url}] em ordem de horario."""
    from . import autopilot, revisao
    from .publish import guard

    out: list[dict] = []
    hoje0 = datetime.combine(date.today(), datetime.min.time()).timestamp()
    for r in db.conn().execute("SELECT p.platform, p.url, p.ts, p.clip_id, c.title FROM posts p LEFT JOIN clips c ON c.id = p.clip_id "
                               "WHERE p.ok=1 AND p.dry_run=0 AND p.ts>=? ORDER BY p.ts", (hoje0,)).fetchall():
        out.append({"ts": r["ts"], "rede": r["platform"], "titulo": r["title"] or "", "parte": "", "clip_id": r["clip_id"], "feito": True, "url": r["url"]})

    fila = autopilot.queue(cfg) if fila is None else fila
    com_guardados = [*fila, *exclusivas.guardados(cfg)]
    ja = {c.plan.id: set(exclusivas.postados(c.plan.id)) for c in com_guardados}
    plats = list(cfg.get("publicacao.plataformas", ["youtube", "tiktok"]) or [])
    excl = exclusivas.redes(cfg)
    fontes = {p: exclusivas._fontes_recentes(p) for p in excl}
    outras = exclusivas.conjunto(cfg)
    dia_de = lambda x: datetime.fromtimestamp(x).date()  # noqa: E731
    feitos = {(p, date.today()): db.posts_today(p) for p in excl}
    ev: list[tuple[float, str]] = []
    for k in range(max(1, dias)):
        dia = date.today() + timedelta(days=k)
        for p in plats:
            pausa = guard.paused_until(p)
            ev += [(t, p) for t in horarios(p, cfg, dia) if not (pausa and t < pausa[0])]
    for t, p in sorted(ev):
        c = None
        if p in excl:
            d = dia_de(t)
            restam = max([sum(1 for x, q in ev if q == o and x > t and dia_de(x) == d) for o in outras] or [0])
            c = exclusivas.escolher(p, cfg, com_guardados, ja=ja, fontes=fontes[p], restam=restam, feitos=feitos.get((p, d), 0))
            if c is not None:
                feitos[(p, d)] = feitos.get((p, d), 0) + 1
                fontes[p] = [c.plan.source_id, *fontes[p]][:2]
        else:
            c = next((x for x in fila if p not in ja[x.plan.id] and not exclusivas.e_de_exclusiva(x.plan.id, cfg, ja[x.plan.id])), None)
        repete = bool(c is not None and p in excl and ja[c.plan.id])
        if c is not None:
            ja[c.plan.id].add(p)
        out.append({"ts": t, "rede": p, "titulo": c.plan.title if c else "", "clip_id": c.plan.id if c else None, "feito": False, "url": None, "repete": repete,
                    "parte": f"{c.plan.part}/{c.plan.parts_total}" if c and c.plan.part else "",
                    "revisado": bool(c and (revisao.estado(c) or {}).get("ok"))})
    return sorted(out, key=lambda x: x["ts"])
