"""Fila de revisao: voce ve os cortes prontos, escolhe, edita titulo e manda publicar tudo de uma vez."""
from __future__ import annotations

import os
from pathlib import Path

from rich.text import Text

from . import db, paths, ui
from .config import Config
from .models import PostResult, RenderedClip
from .util import fmt_duration


def pending(only_ids: set[str] | None = None) -> list[RenderedClip]:
    clips = [c for c in db.clips_by_status("renderizado", "aprovado") if Path(c.path).exists()]
    if only_ids:
        clips = [c for c in clips if c.plan.id in only_ids]
    return sorted(clips, key=lambda c: -c.plan.score)


def _show(clips: list[RenderedClip]) -> None:
    rows = []
    for i, c in enumerate(clips, 1):
        p = c.plan
        part = f"{p.part}/{p.parts_total}" if p.part else ""
        rows.append([str(i), ui.score_text(p.score), Text(p.title[:58]), fmt_duration(c.duration), c.layout, part])
    ui.table(["#", "Chance de viralizar", "Titulo", "Dur.", "Layout", "Parte"], rows,
             title=f"{len(clips)} corte(s) aguardando revisao")


def _pick_one(clips: list[RenderedClip], question: str) -> RenderedClip | None:
    choice = ui.ask_select(question, [(str(i), f"{i}. {c.plan.title[:70]}") for i, c in enumerate(clips)] +
                           [("x", "<- cancelar")])
    if choice in (None, "x"):
        return None
    return clips[int(choice)]


def recoverable() -> list[RenderedClip]:
    """Cortes descartados (ou vencidos) que ainda estao no PC: da para trazer de volta."""
    return [c for c in db.clips_by_status("rejeitado", "expirado", "falhou") if Path(c.path).exists()]


def recover() -> int:
    """Lista os descartados e devolve para a fila os que o dono escolher."""
    clips = recoverable()
    if not clips:
        ui.info("Nenhum corte descartado guardado no PC.")
        return 0
    ids = ui.ask_checkbox("Quais trazer de volta?", [(c.plan.id, f"{int(c.plan.score):3d}  {c.plan.title[:65]}", False)
                                                    for c in clips])
    for cid in ids:
        db.set_clip_status(cid, "renderizado")
    if ids:
        ui.ok(f"{len(ids)} corte(s) de volta em 'Ver cortes prontos'.")
    return len(ids)


def review(cfg: Config, only_ids: set[str] | None = None, dry_run: bool = False, rep=None) -> list[PostResult]:
    from .pipeline import publish_clips
    from .ui import Reporter

    rep = rep or Reporter()
    results: list[PostResult] = []
    while True:
        clips = pending(only_ids)
        if not clips:
            ui.info("Nenhum corte esperando você.")
            n = len(recoverable()) if not only_ids else 0
            if n and ui.ask_confirm(f"Tem {n} corte(s) descartado(s) guardado(s). Quer recuperar algum?", default=False) and recover():
                continue
            return results
        ui.console.print()
        _show(clips)
        action = ui.ask_select("O que voce quer fazer?", [
            ("todos", f"Publicar TODOS ({len(clips)}) de uma vez"),
            ("escolher", " Escolher quais publicar"),
            ("assistir", ">  Assistir um corte"),
            ("pasta", "Abrir a pasta dos videos"),
            ("editar", " Editar o titulo/legenda do post"),
            ("descartar", " Descartar cortes"),
            ("recuperar", " Recuperar um corte descartado"),
            ("teste", "Publicacao de TESTE (preenche tudo e nao publica)"),
            ("voltar", "<- Voltar (deixa na fila)"),
        ])
        if action in (None, "voltar"):
            return results
        if action == "assistir":
            c = _pick_one(clips, "Qual corte?")
            if c:
                os.startfile(c.path)  # abre no player padrao
        elif action == "pasta":
            os.startfile(str(paths.RENDERS))
        elif action == "editar":
            c = _pick_one(clips, "Editar qual corte?")
            if c:
                new_title = ui.ask_text("Novo titulo do post:", c.plan.title)
                if new_title:
                    c.plan.title = new_title
                new_desc = ui.ask_text("Descricao (Enter mantem):", c.plan.description)
                c.plan.description = new_desc
                tags = ui.ask_text("Hashtags separadas por espaco (Enter mantem):", " ".join(c.plan.hashtags))
                c.plan.hashtags = [t if t.startswith("#") else f"#{t}" for t in tags.split() if t.strip("#")]
                db.update_clip_plan(c.plan)
                ui.ok("Salvo. (O titulo desenhado dentro do video continua o original.)")
        elif action == "descartar":
            ids = ui.ask_checkbox("Quais descartar?", [(c.plan.id, c.plan.title[:70], False) for c in clips])
            if ids and not ui.ask_confirm(f"Descartar {len(ids)} corte(s)?", default=False):
                continue
            for cid in ids:
                db.set_clip_status(cid, "rejeitado")
            if ids:
                ui.ok(f"{len(ids)} corte(s) descartado(s). Dá para recuperar por alguns dias.")
        elif action == "recuperar":
            recover()
        elif action in ("todos", "escolher", "teste"):
            if action == "escolher":
                ids = set(ui.ask_checkbox("Quais publicar?", [(c.plan.id, f"{int(c.plan.score):3d}  {c.plan.title[:65]}", True)
                                                               for c in clips]))
                chosen = [c for c in clips if c.plan.id in ids]
            else:
                chosen = clips
            if not chosen:
                continue
            is_test = dry_run or action == "teste"
            if not is_test and not ui.ask_confirm(
                    f"Publicar {len(chosen)} corte(s) em {', '.join(cfg.get('publicacao.plataformas', []))} agora?"):
                continue
            if not is_test:
                for c in chosen:
                    db.set_clip_status(c.plan.id, "aprovado")
            res, actions = publish_clips(cfg, chosen, is_test, rep, revisado_pelo_dono=True)
            results.extend(res)
            for a in actions:
                ui.warn(a)
            ok = sum(1 for r in res if r.ok)
            ui.info(f"{ok}/{len(res)} envios com sucesso.")
            if actions and not res:
                return results
