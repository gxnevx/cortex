"""Situacao do CORTEX: o que esta rodando, quando sai o proximo post, logins, avisos.

Qualquer janela pode olhar a qualquer momento: nada aqui trabalha, so le o que os processos de fundo gravam.
"""
from __future__ import annotations

import json
import re
import time
from collections import deque
from datetime import datetime
from typing import Any

from rich.console import Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import andamento, db, paths, ui
from .config import Config, load_config
from .util import fmt_duration

NOMES = {"youtube": "YouTube", "tiktok": "TikTok"}
SPIN = "|/-\\"
_LOG_LINE = re.compile(r"^(\d\d:\d\d:\d\d) (INFO|WARNING|ERROR)\s+(\S+): (.*)$")
_login_cache: dict[str, Any] = {"ts": 0.0, "v": {}}


# ------------------------------------------------------------------ tempo
def when(ts: float) -> str:
    """'hoje 20:41 (daqui 5 h)' / '26/11 12:10 (daqui 2 dias)'."""
    now = time.time()
    if not ts or ts <= now:
        return "agora"
    d, dt = ts - now, datetime.fromtimestamp(ts)
    if d < 3600:
        left = f"{max(1, int(d // 60))} min"
    elif d < 48 * 3600:
        left = f"{int(round(d / 3600))} h"
    else:
        left = f"{int(d // 86400)} dias"
    day = "hoje" if dt.date() == datetime.now().date() else f"{dt:%d/%m}"
    return f"{day} {dt:%H:%M} (daqui {left})"


def logins(cfg: Config, max_age: float = 120) -> dict[str, bool]:
    if time.time() - _login_cache["ts"] > max_age:
        from . import publish

        v = {}
        for p in cfg.get("publicacao.plataformas", ["youtube", "tiktok"]):
            try:
                v[p] = bool(publish.check_login(p, cfg))
            except Exception:
                v[p] = False
        _login_cache.update(ts=time.time(), v=v)
    return dict(_login_cache["v"])


def plan_line(platform: str, cfg: Config) -> str:
    """Ex.: 'hoje nenhum (conta nova), 1 por dia a partir de 26/11'."""
    from . import policy

    steps = policy.plan_steps(platform, cfg)
    if len(steps) == 1:
        return f"até {steps[0][1]} por dia"
    out = [f"hoje {steps[0][1]}" if steps[0][1] else "hoje nenhum (conta nova)"]
    out += [f"{n} por dia a partir de {d:%d/%m}" for d, n in steps[1:]]
    return ", ".join(out)


# ------------------------------------------------------------------ retrato
def snapshot(cfg: Config | None = None) -> dict:
    from . import autopilot, fundo, memoria, policy, storage
    from .publish import guard

    cfg = cfg or load_config()
    hb = andamento.read_json(autopilot.HEARTBEAT) or {}
    on = autopilot.running()
    plats = list(cfg.get("publicacao.plataformas", ["youtube", "tiktok"]))
    lg = logins(cfg)
    redes, precisa = {}, []
    for p in plats:
        pz = guard.paused_until(p)
        redes[p] = {"login": lg.get(p, False), "hoje": db.posts_today(p), "limite": policy.effective_limit(p, cfg),
                    "plano": plan_line(p, cfg), "pausa": pz}
        if pz:
            precisa.append(f"{NOMES.get(p, p)} parado até {datetime.fromtimestamp(pz[0]):%d/%m %H:%M}: entre em Contas e resolva")
        elif not lg.get(p):
            precisa.append(f"{NOMES.get(p, p)} sem login: entre em Contas")
    precisa += list(guard.waiting().values())
    mem, free = memoria.status(), storage.free_gb()
    if free < float(cfg.get("armazenamento.espaco_minimo_livre_gb", 2)) + 1:
        precisa.append(f"disco quase cheio: {free:.1f} GB livres")
    try:
        q = autopilot.queue(cfg)
    except Exception:
        q = []
    prox = {p: policy.next_slot(p, cfg) for p in plats if redes[p]["login"] and not redes[p]["pausa"]}
    for p, t in prox.items():
        redes[p]["proximo"] = t
    proximo = min([t for t in prox.values() if t], default=0.0)
    last = db.conn().execute("SELECT platform, url, ts FROM posts WHERE ok=1 AND dry_run=0 ORDER BY ts DESC LIMIT 1").fetchone()
    return {"automatico": on, "querido": fundo.wanted(), "batida": hb, "rodada": andamento.read(), "pedidos": fundo.requests(),
            "redes": redes, "precisa": precisa, "fila": q, "proximo_post": proximo, "memoria": mem, "disco": free,
            "ultimo_post": dict(last) if last else None}


def now_text(s: dict) -> str:
    """O que esta acontecendo agora, em uma linha."""
    r, hb = s["rodada"], s["batida"] if s["automatico"] else {}
    parts = []
    if r:
        parts.append(f"{andamento.describe(r)} | há {fmt_duration(time.time() - r['inicio'])}")
    pub = str(hb.get("publicador") or "")
    if pub.startswith("publicando"):
        parts.append(pub)
    if not parts and s["automatico"]:
        parts.append(ui.term(str(hb.get("produtor") or "aguardando")))
    return "  +  ".join(parts) or "nada rodando"


def summary(s: dict) -> Text:
    """Resumo curto (menu e `cortex status`)."""
    t = Text()

    def line(k: str, v: str, style: str = "white") -> None:
        t.append(f"  {k:<13} ", style=ui.C_DIM)
        t.append(ui.term(v) + "\n", style=style)

    if s["automatico"]:
        since = fmt_duration(time.time() - float(s["batida"].get("desde") or time.time()))
        test = " em TESTE" if s["batida"].get("teste") else ""
        line("Automático", f"LIGADO{test} há {since} (em segundo plano, pode fechar esta janela)", f"bold {ui.C_OK}")
    elif s["querido"]:
        line("Automático", "parou, religando sozinho em até 10 min", f"bold {ui.C_YEL}")
    else:
        line("Automático", "desligado")
    busy = bool(s["rodada"]) or s["automatico"]
    line("Agora", now_text(s), f"bold {ui.C_CYAN}" if busy else ui.C_DIM)
    if s["pedidos"]:
        line("Na espera", f"{len(s['pedidos'])} pedido(s) seu(s)")
    if s["automatico"]:
        line("Próximo post", when(s["proximo_post"]) + f" | {len(s['fila'])} corte(s) na fila", ui.C_YEL)
    for p, r in s["redes"].items():
        if r["pausa"]:
            line(NOMES.get(p, p), "parado, precisa de você", f"bold {ui.C_YEL}")
        elif not r["login"]:
            line(NOMES.get(p, p), "sem login", ui.C_RED)
        else:
            line(NOMES.get(p, p), f"login ok | {r['hoje']} de {r['limite']} hoje | próximo {when(r.get('proximo') or 0)}", ui.C_OK)
    if s["ultimo_post"]:
        u = s["ultimo_post"]
        line("Último post", f"{NOMES.get(u['platform'], u['platform'])} {datetime.fromtimestamp(u['ts']):%d/%m %H:%M} {u['url'] or ''}")
    if s["precisa"]:
        for msg in s["precisa"]:
            line("PRECISA DE VOCÊ", msg, f"bold white on {ui.C_RED}")
    else:
        line("Situação", "tudo certo", ui.C_OK)
    return t


# -------------------------------------------------------------------- painel
def log_tail(n: int = 14) -> list[tuple[str, str, str, str]]:
    files = sorted(paths.LOGS.glob("fabrica_*.log"))
    if not files:
        return []
    try:
        with files[-1].open("rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 60_000))
            txt = fh.read().decode("utf-8", "replace")
    except OSError:
        return []
    out: deque = deque(maxlen=n)
    for ln in txt.splitlines():
        m = _LOG_LINE.match(ln)
        if m and "yt-dlp aviso" not in ln:
            out.append((m.group(1), m.group(2), m.group(3).replace("fabrica.", ""), ui.term(m.group(4))))
    return list(out)


def _head() -> Group:
    rows = []
    for i, line in enumerate(ui._BANNER):
        n = max(1, len(line) - 1)
        t = Text(" ")
        for j, ch in enumerate(line):
            t.append(ch, style=f"bold {ui._lerp_hex(ui.C_RED, ui.C_CYAN, min(1.0, j / n * 0.7 + i * 0.06))}")
        rows.append(t)
    return Group(*rows)


def render(s: dict) -> Layout:
    tick = SPIN[int(time.time() * 4) % len(SPIN)]
    r, hb = s["rodada"], s["batida"] if s["automatico"] else {}
    work = Table.grid(padding=(0, 1))
    work.add_column(style=ui.C_CYAN, no_wrap=True)
    work.add_column()
    if r:
        bar = "".join("█" if i < int(r.get("etapa") or 0) else "░" for i in range(int(r.get("etapas") or 4)))
        work.add_row("Etapa", Text(f"{bar} {r.get('etapa')}/{r.get('etapas')} {ui.term(r.get('titulo') or '')}", style="bold white"))
        if r.get("videos"):
            work.add_row("Vídeo", Text(f"{r['video']} de {r['videos']}: {ui.term(r.get('video_titulo') or '')[:64]}"))
        work.add_row("Fazendo", Text(f"{tick} {ui.term(r.get('msg') or 'preparando')[:70]}", style="white"))
        work.add_row("", Text(f"há {fmt_duration(time.time() - float(r.get('msg_desde') or time.time()))} neste passo, "
                              f"{fmt_duration(time.time() - r['inicio'])} no total, {r.get('prontos', 0)} corte(s) pronto(s)", style=ui.C_DIM))
    else:
        work.add_row("Cortando", Text(ui.term(str(hb.get("produtor") or "nada rodando"))[:74]))
    work.add_row("Postando", Text(ui.term(str(hb.get("publicador") or "nada"))[:74]))
    if s["automatico"]:
        work.add_row("Próximo post", Text(when(s["proximo_post"]), style=ui.C_YEL))
        work.add_row("Próxima busca", Text(when(float(hb.get("proxima_busca") or 0)), style=ui.C_YEL))
    if s["pedidos"]:
        work.add_row("Na espera", Text(f"{len(s['pedidos'])} pedido(s) seu(s)"))

    day = Table.grid(padding=(0, 1))
    day.add_column(style=ui.C_CYAN, no_wrap=True)
    day.add_column()
    for p, x in s["redes"].items():
        st = Text(f"{x['hoje']}/{x['limite']} hoje", style="bold white")
        st.append(" login ok" if x["login"] else " SEM LOGIN", style=ui.C_OK if x["login"] else ui.C_RED)
        if x.get("proximo"):
            st.append(f" | {datetime.fromtimestamp(x['proximo']):%d/%m %H:%M}", style=ui.C_YEL)
        if x["pausa"]:
            st.append(" PARADO", style=f"bold {ui.C_YEL}")
        day.add_row(NOMES.get(p, p), st)
    mem = s["memoria"]
    day.add_row("Memória", Text(f"{mem['ram_livre']:.1f} GB livres", style=ui.C_OK if mem["reserva_livre"] > 3 else ui.C_YEL))
    day.add_row("Disco", Text(f"{s['disco']:.1f} GB livres", style=ui.C_OK if s["disco"] > 4 else ui.C_YEL))
    if hb:
        day.add_row("Rodadas", Text(f"{hb.get('rodadas_ok', 0)} ok de {hb.get('rodadas', 0)}"))
        day.add_row("PC", Text("em uso por você (eu espero)" if hb.get("pc_em_uso") else "livre"))

    qt = Table.grid(padding=(0, 1))
    for _ in range(3):
        qt.add_column(no_wrap=True, overflow="ellipsis")
    for i, c in enumerate(s["fila"][:5], 1):
        part = f" (P{c.plan.part}/{c.plan.parts_total})" if c.plan.part else ""
        qt.add_row(f"{i}.", ui.score_text(c.plan.score), Text(ui.term(c.plan.title)[:70] + part))
    if not s["fila"]:
        qt.add_row("", Text("vazia", style=ui.C_DIM), "")

    lg = Text()
    for msg in s["precisa"]:
        lg.append(f" PRECISA DE VOCÊ: {ui.term(msg)} \n", style=f"bold white on {ui.C_RED}")
    for a in (hb.get("alertas") or [])[-2:]:
        lg.append(f"! {a}\n", style=f"bold {ui.C_YEL}")
    for ts, lvl, name, msg in log_tail(14):
        lg.append(f"{ts} ", style=ui.C_DIM)
        lg.append(f"{name[:10]:<10} ", style=ui.C_CYAN)
        lg.append(msg[:150] + "\n", style=ui.C_RED if lvl == "ERROR" else ui.C_YEL if lvl == "WARNING" else "white")

    if s["automatico"]:
        state = Text(f" {tick} AUTOMÁTICO LIGADO", style=f"bold {ui.C_OK}")
    elif r:
        state = Text(f" {tick} RODADA EM ANDAMENTO ({r.get('origem', '')})", style=f"bold {ui.C_CYAN}")
    else:
        state = Text(" NADA RODANDO", style="bold white")
    state.append(f"   |   {datetime.now():%d/%m %H:%M:%S}", style=ui.C_DIM)

    lay = Layout()
    lay.split_column(
        Layout(Group(_head(), state), name="head", size=8),
        Layout(name="mid", size=10),
        Layout(Panel(qt, title=f"Cortes na fila ({len(s['fila'])})", border_style=ui.C_DIM), size=7),
        Layout(Panel(lg, title="Ao vivo", border_style=ui.C_DIM)),
        Layout(Text(" Ctrl+C sai do painel. O trabalho continua em segundo plano.", style=ui.C_DIM), size=1),
    )
    lay["mid"].split_row(Layout(Panel(work, title="Agora", border_style=ui.C_CYAN), ratio=3),
                         Layout(Panel(day, title="Contas e PC", border_style=ui.C_RED), ratio=2))
    return lay


def watch() -> None:
    """Painel ao vivo: so olha. Fechar nao para nada."""
    cfg, ts, snap = load_config(), 0.0, None
    try:
        snap = snapshot(cfg)
        with Live(render(snap), console=ui.console, refresh_per_second=4, screen=True) as live:
            while True:
                if time.time() - ts > 2:
                    try:
                        snap = snapshot(cfg)
                    except Exception as e:  # leitura no meio de uma gravacao: tenta no proximo ciclo
                        from . import log

                        log.get("painel").debug("retrato: %s", e)
                    ts = time.time()
                try:
                    live.update(render(snap))
                except Exception as e:
                    from . import log

                    log.get("painel").debug("desenho: %s", e)
                time.sleep(0.4)
    except KeyboardInterrupt:
        pass
    ui.console.print()


def as_json(s: dict) -> str:
    d = {k: v for k, v in s.items() if k not in ("fila",)}
    d["fila"] = [c.plan.title for c in s["fila"]]
    return json.dumps(d, ensure_ascii=False, default=str)
