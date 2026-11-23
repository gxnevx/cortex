"""Editor-chefe do automatico: decide sozinho o que posta e o que descarta.

1. Regras fixas (duracao, titulo generico, arquivo, fala).
2. O Claude le a fala de cada corte, da nota comparando um com o outro, barra o que nao pode ir ao ar e melhora o
   titulo se precisar. Passa quem fica acima da nota minima.
   Sem Claude: so passa quem tem nota alta dos sinais do publico.
Partes de uma mesma serie entram ou saem juntas. Tudo fica registrado e aparece em "Todos os cortes".
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from . import db, log
from .models import RenderedClip

_log = log.get("curadoria")

SYSTEM = ("Você é o editor-chefe de um canal brasileiro de cortes. Seu trabalho é só deixar sair o que um desconhecido "
          "entenderia e assistiria até o fim. Responda SOMENTE com JSON válido.")


def _plain(s: str) -> str:
    t = unicodedata.normalize("NFD", (s or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in t if not unicodedata.combining(c))).strip()


def pending(cfg: Any) -> list[RenderedClip]:
    """Cortes prontos que ninguem julgou ainda (os que o dono pediu para ver antes ficam com ele)."""
    rows = db.conn().execute(
        """SELECT c.id FROM clips c LEFT JOIN runs r ON r.id = c.run_id
           WHERE c.status='renderizado' AND COALESCE(c.curador, '') = ''
             AND COALESCE(r.publish_mode, '') NOT IN ('revisar', 'nao_publicar')""").fetchall()
    ids = {r["id"] for r in rows}
    return [c for c in db.clips_by_status("renderizado") if c.plan.id in ids]


def speech(clip: RenderedClip, cfg: Any) -> str:
    """O que e dito no corte."""
    if clip.plan.fala:
        return clip.plan.fala
    try:
        from . import transcribe

        t = transcribe.transcribe(clip.path_for("youtube"), cfg, language="pt", model_name="small", purpose="selecao")
        return re.sub(r"\s+", " ", t.text).strip()[:1500]
    except Exception as e:
        _log.warning("nao consegui ouvir %s: %s", clip.plan.id, e)
        return ""


def _rules(c: RenderedClip, fala: str, cfg: Any) -> str | None:
    """Motivo para descartar na hora, ou None."""
    from .brain.prompts import is_generic

    p = c.plan
    if not Path(c.path).exists():
        return "arquivo do vídeo não existe mais"
    if c.duration < float(cfg.get("curadoria.duracao_min_s", 25)) and not p.part:
        return f"curto demais ({c.duration:.0f} s), sem contexto"
    if is_generic(p.title):
        return "título genérico"
    if len(fala.split()) < 25:
        return "quase não tem fala"
    return None


def _prompt(items: list[tuple[RenderedClip, str]]) -> str:
    blocks = []
    for i, (c, fala) in enumerate(items, 1):
        p = c.plan
        part = f" | Parte {p.part} de {p.parts_total} da série '{p.series}'" if p.part else ""
        blocks.append(f"{i}. [{c.duration:.0f} s, {p.tipo or 'fala'}, nota {p.score:.0f}{part}]\n"
                      f"Título: {p.title}\nTexto na tela: {p.hook}\nFala: \"{fala[:1300]}\"")
    body = "\n\n".join(blocks)
    return f"""Dê nota para estes cortes de vídeo (TikTok e YouTube Shorts). O canal posta os melhores e descarta o resto.

Como o espectador vê: título grande na tela o tempo todo, etiqueta com o nome do programa, legenda da fala e crédito. Muitos abrem com um GANCHO (1 a 3 s da frase mais forte, repetida depois), então a primeira frase da fala pode parecer solta: isso é proposital. A fala vem de transcrição automática, com erros e sem identificar quem fala; julgue o conteúdo, não a transcrição. Conversa de podcast é naturalmente solta: não exija começo de redação.

Para cada corte devolva:
- "nota": 0 a 100, chance de segurar quem está rolando o feed, COMPARANDO os cortes entre si e usando a escala toda. Pesa a favor: frase forte, treta, piada, revelação, história, curiosidade completa, reação, assunto em que todo mundo tem opinião. Pesa contra: enrolação, assunto difícil de entender mesmo com o título, sem nenhum momento marcante.
- "fatal": true só se não pode ir ao ar: propaganda; menor de idade exposto; ódio contra grupo; vítima real de crime violento tratada com deboche, sensualização ou exposição da vida íntima; o título mente sobre o que é dito; acusa pessoa real e identificável de crime sem ser caso público (caso julgado, noticiado ou contado por jornalista é público); ou impossível de entender. Senão false.
- "motivo": até 12 palavras.
- "titulo": só se o título atual estiver fraco ou errado. Português do Brasil, 35 a 75 caracteres, 1 emoji no fim. Se usar aspas, copie a frase exatamente como está na fala. Curiosidade usa o nome real da coisa; tutorial usa título direto. Senão "".
Se dois cortes são quase iguais, dê nota menor ao pior.

CORTES
{body}

RESPONDA SÓ COM ESTE JSON:
{{"decisoes":[{{"i":1,"nota":80,"fatal":false,"motivo":"...","titulo":""}}]}}"""


def _ask_claude(items: list[tuple[RenderedClip, str]], cfg: Any) -> dict[int, dict] | None:
    from .brain import get_brain
    from .brain.base import extract_json, list_from_json

    b = get_brain(cfg, tarefa="clips")
    if b.name != "claude":
        return None
    try:
        res = b._run(_prompt(items), SYSTEM)
        out = {}
        for d in list_from_json(extract_json(res), ("decisoes", "decisões", "cortes")):
            try:
                out[int(d.get("i"))] = d
            except (TypeError, ValueError):
                continue
        return out or None
    except Exception as e:
        _log.warning("o Claude nao julgou os cortes (%s); uso as regras", e)
        return None


def _good_title(t: str, fala: str) -> bool:
    """Titulo novo so vale se a citacao existir na fala de verdade."""
    from .brain.prompts import is_generic

    t = (t or "").strip()
    if not 15 <= len(t) <= 95 or is_generic(t):
        return False
    quotes = re.findall(r"[\"“”]([^\"“”]{4,})[\"“”]", t)
    f = _plain(fala)
    return all(_plain(q) in f for q in quotes)


def curate(cfg: Any, clips: list[RenderedClip] | None = None) -> dict:
    """Julga os cortes pendentes. Devolve {"aprovados": [...], "descartados": [(titulo, motivo)]}."""
    clips = pending(cfg) if clips is None else clips
    out: dict = {"aprovados": [], "descartados": []}
    if not clips:
        return out
    judged: list[tuple[RenderedClip, str]] = []
    verdict: dict[str, tuple[bool, str, float, str]] = {}   # id -> (postar, motivo, nota, titulo)
    for c in clips:
        fala = speech(c, cfg)
        if fala and not c.plan.fala:
            c.plan.fala = fala
        why = _rules(c, fala, cfg)
        if why:
            verdict[c.plan.id] = (False, why, c.plan.score, "")
        else:
            judged.append((c, fala))
    minimum = float(cfg.get("curadoria.nota_minima", 68))
    for k in range(0, len(judged), 8):
        lote = judged[k:k + 8]
        dec = _ask_claude(lote, cfg)
        for i, (c, fala) in enumerate(lote, 1):
            d = (dec or {}).get(i)
            if d is None:
                ok = c.plan.score >= minimum + (4 if dec is None else 0)
                verdict[c.plan.id] = (ok, "nota dos sinais do público", c.plan.score, "")
                continue
            try:
                nota = float(d.get("nota", c.plan.score))
            except (TypeError, ValueError):
                nota = c.plan.score
            t = str(d.get("titulo") or "").strip()
            fatal = d.get("fatal") in (True, "true", "True", 1)
            final = 0.65 * nota + 0.35 * c.plan.score   # editor-chefe pesa mais que o sinal do publico
            # so troca o titulo se o atual e generico ou cita o que nao foi dito
            troca = t if _good_title(t, fala) and not _good_title(c.plan.title, fala) else ""
            verdict[c.plan.id] = (not fatal and final >= minimum - 6, str(d.get("motivo") or "")[:120], nota, troca)
    # serie: todas as partes ou nenhuma (vale a media das notas, a nao ser que alguma parte nao possa ir ao ar)
    series: dict[str, list[RenderedClip]] = {}
    for c in clips:
        if c.plan.part:
            series.setdefault(f"{c.plan.source_id}|{c.plan.series}", []).append(c)
    for parts in series.values():
        media = sum(0.65 * verdict[c.plan.id][2] + 0.35 * c.plan.score for c in parts) / len(parts)
        if media >= minimum - 6 and any(verdict[c.plan.id][0] for c in parts):
            for c in parts:
                v = verdict[c.plan.id]
                verdict[c.plan.id] = (True, v[1], v[2], "")
        elif any(not verdict[c.plan.id][0] for c in parts):
            why = next(verdict[c.plan.id][1] for c in parts if not verdict[c.plan.id][0])
            for c in parts:
                v = verdict[c.plan.id]
                verdict[c.plan.id] = (False, f"série incompleta: {why}" if v[0] else v[1], v[2], "")
    for c in clips:
        ok, why, nota, title = verdict[c.plan.id]
        if title and not c.plan.part:
            c.plan.title = title
        if ok:
            c.plan.score = round(0.5 * c.plan.score + 0.5 * nota, 1)
        db.update_clip_plan(c.plan)
        db.conn().execute("UPDATE clips SET curador=?, score=? WHERE id=?",
                          (f"{'aprovado' if ok else 'descartado'}: {why}", c.plan.score, c.plan.id))
        db.set_clip_status(c.plan.id, "aprovado" if ok else "rejeitado")
        (out["aprovados"].append(c.plan.title) if ok else out["descartados"].append((c.plan.title, why)))
        _log.info("%s '%s' (%s)", "vai postar" if ok else "descartei", c.plan.title[:60], why)
    return out
