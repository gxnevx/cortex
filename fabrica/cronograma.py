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
        return [max(t, time.time()) for t, _ in policy.slots_today(rede, cfg)]
    n, gap = policy._limit_on(rede, cfg, dia), policy.min_interval_s(rede, cfg)
    out: list[float] = []
    for t, _ in policy._slot_times(rede, cfg, dia):
        if len(out) < n and all(abs(t - c) >= gap for c in out):
            out.append(t)
    return sorted(out)


def montar(cfg: Any, dias: int = 4, fila: list | None = None) -> list[dict]:
    """[{ts, rede, titulo, parte, clip_id, feito, url}] em ordem de horario."""
    from . import autopilot
    from .publish import guard

    out: list[dict] = []
    hoje0 = datetime.combine(date.today(), datetime.min.time()).timestamp()
    for r in db.conn().execute("SELECT p.platform, p.url, p.ts, p.clip_id, c.title FROM posts p LEFT JOIN clips c ON c.id = p.clip_id "
                               "WHERE p.ok=1 AND p.dry_run=0 AND p.ts>=? ORDER BY p.ts", (hoje0,)).fetchall():
        out.append({"ts": r["ts"], "rede": r["platform"], "titulo": r["title"] or "", "parte": "", "clip_id": r["clip_id"], "feito": True, "url": r["url"]})

    fila = autopilot.queue(cfg) if fila is None else fila
    ja = {c.plan.id: set(exclusivas.postados(c.plan.id)) for c in fila}
    plats = list(cfg.get("publicacao.plataformas", ["youtube", "tiktok"]) or [])
    excl = exclusivas.redes(cfg)
    fontes = {p: exclusivas._fontes_recentes(p) for p in excl}
    guardar = exclusivas.reserva(cfg) if excl else 0
    ev: list[tuple[float, str]] = []
    for k in range(max(1, dias)):
        dia = date.today() + timedelta(days=k)
        for p in plats:
            pausa = guard.paused_until(p)
            ev += [(t, p) for t in horarios(p, cfg, dia) if not (pausa and t < pausa[0])]
    for t, p in sorted(ev):
        c = None
        if p in excl:
            c = exclusivas.escolher(p, cfg, fila, ja=ja, fontes=fontes[p], guardar=guardar)
            if c is not None:
                fontes[p] = [c.plan.source_id, *fontes[p]][:2]
        else:
            c = next((x for x in fila if p not in ja[x.plan.id] and not any(e in ja[x.plan.id] for e in excl)), None)
        if c is not None:
            ja[c.plan.id].add(p)
        out.append({"ts": t, "rede": p, "titulo": c.plan.title if c else "", "clip_id": c.plan.id if c else None, "feito": False, "url": None,
                    "parte": f"{c.plan.part}/{c.plan.parts_total}" if c and c.plan.part else ""})
    return sorted(out, key=lambda x: x["ts"])
