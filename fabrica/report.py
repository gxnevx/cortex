"""Relatorio de cada rodada: HTML bonito (abre no navegador) + JSON + resumo no terminal."""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

from . import paths, ui
from .util import fmt_duration, fmt_views


def _uri(p: str | None) -> str:
    if not p:
        return ""
    try:
        return Path(p).resolve().as_uri()
    except Exception:
        return ""


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""))


_CSS = """
:root{--bg:#0d0f14;--card:#161a22;--line:#262c38;--txt:#e9edf3;--dim:#8b95a7;--red:#FE2C55;--cyan:#25F4EE;--yel:#FFE600;--ok:#3DDC84}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font:15px/1.5 "Segoe UI",system-ui,sans-serif}
header{padding:28px 32px;background:linear-gradient(120deg,#2a0b14,#0b2a2a);border-bottom:1px solid var(--line)}
h1{margin:0;font-size:28px;letter-spacing:.5px}h1 span{background:linear-gradient(90deg,var(--red),var(--cyan));-webkit-background-clip:text;background-clip:text;color:transparent}
.meta{color:var(--dim);margin-top:6px}main{padding:24px 32px;max-width:1300px;margin:auto}
h2{font-size:18px;margin:28px 0 12px;color:var(--cyan)}
.kpis{display:flex;gap:12px;flex-wrap:wrap}.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 18px;min-width:150px}
.kpi b{display:block;font-size:26px}.kpi small{color:var(--dim)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.card img{width:100%;aspect-ratio:9/16;object-fit:cover;display:block;background:#000}
.card .b{padding:12px}.card .t{font-weight:700;margin-bottom:6px}.dim{color:var(--dim);font-size:13px}
.score{display:inline-block;padding:2px 8px;border-radius:99px;font-weight:700;font-size:13px}
.s-hi{background:#173d2a;color:var(--ok)}.s-mid{background:#3d3a17;color:var(--yel)}.s-lo{background:#3d1720;color:var(--red)}
.tag{display:inline-block;margin:6px 6px 0 0;padding:2px 8px;border-radius:6px;font-size:12px;background:#222838}
.ok{color:var(--ok)}.bad{color:var(--red)}a{color:var(--cyan)}
table{width:100%;border-collapse:collapse;background:var(--card);border-radius:12px;overflow:hidden}
td,th{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{color:var(--yel);font-weight:600}
.err{background:#2a1218;border:1px solid #5a1f2c;border-radius:10px;padding:10px 14px;margin:6px 0}
"""


def _score_cls(s: float) -> str:
    return "s-hi" if s >= 75 else ("s-mid" if s >= 55 else "s-lo")


def write(summary: dict) -> Path:
    paths.REPORTS.mkdir(parents=True, exist_ok=True)
    rid = summary.get("run_id", datetime.now().strftime("%Y%m%d-%H%M%S"))
    json_path = paths.REPORTS / f"rodada_{rid}.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    clips = summary.get("clips", [])
    posts = summary.get("posts", [])
    posts_by_clip: dict[str, list] = {}
    for p in posts:
        posts_by_clip.setdefault(p["clip_id"], []).append(p)

    ok_posts = sum(1 for p in posts if p.get("ok") and not p.get("dry_run"))
    fail_posts = sum(1 for p in posts if not p.get("ok"))
    status = summary.get("status", "?")
    status_txt = {"ok": "Tudo certo", "parcial": "! Concluida com avisos", "erro": "Falhou"}.get(status, status)

    h = [f"<!doctype html><html lang='pt-br'><head><meta charset='utf-8'>"
         f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
         f"<title>Rodada {rid} | CORTEX</title><style>{_CSS}</style></head><body>"]
    h.append(f"<header><h1>8< <span>CORTEX</span> | relatorio</h1>"
             f"<div class='meta'>Rodada {_e(rid)} | {_e(summary.get('started_txt',''))} | "
             f"duracao {_e(fmt_duration(summary.get('duration_s')))} | {_e(status_txt)}</div>"
             f"<div class='meta'>Busca: {_e(summary.get('search_mode'))} {_e(', '.join(summary.get('keywords') or []))} | "
             f"Publicacao: {_e(summary.get('publish_mode'))} | Cerebro: {_e(summary.get('brain'))} | "
             f"Disparo: {_e(summary.get('trigger'))}</div></header><main>")

    h.append("<div class='kpis'>")
    for label, val in [
        ("assuntos em alta", len(summary.get("trends", []))),
        ("videos analisados", len(summary.get("candidates", []))),
        ("cortes prontos", len(clips)),
        ("publicados", ok_posts),
        ("falhas", fail_posts + len(summary.get("errors", []))),
    ]:
        h.append(f"<div class='kpi'><b>{val}</b><small>{label}</small></div>")
    h.append("</div>")

    if summary.get("errors") or summary.get("warnings") or summary.get("actions"):
        h.append("<h2>Atencao</h2>")
        for a in summary.get("actions", []):
            h.append(f"<div class='err'><b>Acao necessaria:</b> {_e(a)}</div>")
        for e in summary.get("errors", []):
            h.append(f"<div class='err'>{_e(e)}</div>")
        for w in summary.get("warnings", []):
            h.append(f"<div class='err' style='background:#2a2612;border-color:#5a4f1f'>! {_e(w)}</div>")

    if clips:
        h.append("<h2>Cortes</h2><div class='grid'>")
        for c in sorted(clips, key=lambda c: -(c.get("score") or 0)):
            s = c.get("score") or 0
            part = f" | Parte {c['part']}/{c.get('parts_total') or '?'}" if c.get("part") else ""
            h.append("<div class='card'>")
            if c.get("thumbnail"):
                h.append(f"<a href='{_uri(c.get('path'))}'><img src='{_uri(c['thumbnail'])}' alt=''></a>")
            h.append(f"<div class='b'><div class='t'>{_e(c.get('title'))}</div>"
                     f"<span class='score {_score_cls(s)}'>{int(s)}/100</span> "
                     f"<span class='dim'>{_e(fmt_duration(c.get('duration')))} | {_e(c.get('layout'))}{_e(part)}</span>"
                     f"<div class='dim' style='margin-top:6px'>{_e(c.get('reason'))}</div>"
                     f"<div class='dim' style='margin-top:6px'>Fonte: <a href='{_e(c.get('source_url'))}'>{_e(c.get('source_title'))}</a></div>")
            for p in posts_by_clip.get(c["id"], []):
                if p.get("ok"):
                    link = f"<a href='{_e(p.get('url'))}'>{_e(p.get('url') or 'publicado')}</a>" if p.get("url") else "publicado"
                    dry = " (teste)" if p.get("dry_run") else ""
                    h.append(f"<div class='tag ok'>+ {_e(p['platform'])}{dry}: {link}</div>")
                else:
                    h.append(f"<div class='tag bad'>x {_e(p['platform'])}: {_e(p.get('error'))}</div>")
            h.append(f"<div class='tag'>{_e(c.get('status'))}</div></div></div>")
        h.append("</div>")

    cands = summary.get("candidates", [])
    if cands:
        h.append("<h2>Videos-fonte</h2><table><tr><th>#</th><th>Video</th><th>Canal</th><th>Views</th>"
                 "<th>Duracao</th><th>Nota</th><th>Por que</th><th>Status</th></tr>")
        for i, c in enumerate(cands, 1):
            h.append(f"<tr><td>{i}</td><td><a href='{_e(c.get('url'))}'>{_e(c.get('title'))}</a>"
                     f"<div class='dim'>{_e(c.get('platform'))} | {_e(c.get('topic') or '')}</div></td>"
                     f"<td>{_e(c.get('channel'))}</td><td>{_e(fmt_views(c.get('views')))}</td>"
                     f"<td>{_e(fmt_duration(c.get('duration')))}</td><td>{int(c.get('score') or 0)}</td>"
                     f"<td class='dim'>{_e('; '.join(c.get('reasons') or []))}</td>"
                     f"<td>{_e(c.get('status'))} <span class='bad'>{_e(c.get('error') or '')}</span></td></tr>")
        h.append("</table>")

    trends = summary.get("trends", [])
    if trends:
        h.append("<h2>Assuntos em alta</h2><table><tr><th>Assunto</th><th>Fonte</th><th>Categoria</th><th>Nota</th><th>Motivo</th></tr>")
        for t in trends[:40]:
            h.append(f"<tr><td>{_e(t.get('topic'))}</td><td>{_e(t.get('source'))}</td><td>{_e(t.get('category') or '')}</td>"
                     f"<td>{int(t.get('score') or 0)}</td><td class='dim'>{_e(t.get('reason') or '')}</td></tr>")
        h.append("</table>")

    h.append(f"<p class='dim' style='margin-top:30px'>Log completo: {_e(paths.LOGS)}</p></main></body></html>")
    out = paths.REPORTS / f"rodada_{rid}.html"
    out.write_text("".join(h), encoding="utf-8")
    (paths.REPORTS / "ultimo.html").write_text("".join(h), encoding="utf-8")
    return out


def latest() -> Path | None:
    p = paths.REPORTS / "ultimo.html"
    return p if p.exists() else None


def print_summary(summary: dict) -> None:
    clips = summary.get("clips", [])
    posts = summary.get("posts", [])
    ui.rule("RESUMO DA RODADA")
    if clips:
        rows = []
        for i, c in enumerate(sorted(clips, key=lambda c: -(c.get("score") or 0)), 1):
            st = []
            for p in posts:
                if p["clip_id"] == c["id"]:
                    st.append(("+ " if p.get("ok") else "x ") + p["platform"])
            rows.append([str(i), ui.score_text(c.get("score") or 0), c.get("title", "")[:60],
                         fmt_duration(c.get("duration")), ", ".join(st) or c.get("status", "")])
        ui.table(["#", "Viral", "Titulo", "Dur.", "Publicacao"], rows)
    else:
        ui.warn("Nenhum corte foi gerado nesta rodada.")
    for a in summary.get("actions", []):
        ui.warn("ACAO NECESSARIA: " + a)
    for e in summary.get("errors", [])[:8]:
        ui.err(e)
    ok_posts = sum(1 for p in posts if p.get("ok") and not p.get("dry_run"))
    ui.info(f"{len(clips)} cortes | {ok_posts} publicacoes | duracao {fmt_duration(summary.get('duration_s'))}")
    if summary.get("report_path"):
        ui.dim(f"Relatorio: {summary['report_path']}")
