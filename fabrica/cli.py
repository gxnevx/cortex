"""Linha de comando + menu interativo do CORTEX."""
from __future__ import annotations

import argparse
import os
import sys
import traceback

from rich.text import Text

from . import __version__, db, log, paths, ui
from .config import Config, load_config, save_value
from .util import fmt_duration, fmt_views

PLATFORMS = ("youtube", "tiktok")


# =========================================================== acoes
def do_run(cfg: Config, *, mode=None, keywords=None, urls=None, videos=None, publish=None,
           dry_run=False, scheduled=False, brain=None, origem_fundo=False) -> int:
    from .pipeline import RunOptions, run
    from .report import print_summary

    opts = RunOptions(
        trigger="agendado" if scheduled else "manual",
        search_mode=mode, keywords=keywords or [], urls=urls or [], n_videos=videos,
        publish_mode=publish, interactive=not (scheduled or origem_fundo), dry_run=dry_run, brain=brain,
    )
    ui.rule("RODADA " + ("AGENDADA" if scheduled else "MANUAL"), ui.C_RED)
    try:
        summary = run(cfg, opts, ui.Reporter())
    except RuntimeError as e:  # ex.: ja existe rodada em andamento
        ui.err(str(e))
        return 2
    ui.console.print()
    print_summary(summary)
    return 0 if summary.get("status") in ("ok", "parcial") else 1


def show_trends(cfg: Config, rank: bool = True) -> list:
    from . import discovery
    from .brain import get_brain

    with ui.console.status(" Varrendo as fontes de tendencias...", spinner="line"):
        trends = discovery.collect_trends(cfg)
    if rank and trends:
        brain = get_brain(cfg)
        with ui.console.status(f" {brain.name}: analisando o que rende corte...", spinner="line"):
            try:
                trends = brain.rank_trends(trends, cfg, limit=25)
            except Exception as e:
                ui.warn(f"Ranking falhou ({e}); mostrando lista bruta.")
    from .pipeline import adjust_trends

    trends = adjust_trends(trends, cfg)
    abbr = {"google_trends": "Google", "google_news": "Noticias", "x_trends": "X", "reddit": "Reddit",
            "youtube": "YouTube", "twitch": "Twitch", "kick": "Kick", "keyword": "voce"}
    rows = [[str(i), ui.score_text(t.score), Text(t.topic[:48], style="bold"), t.category or "-",
             "+".join(abbr.get(s, s) for s in (t.source or "").split("+"))]
            for i, t in enumerate(trends[:25], 1)]
    ui.table(["#", "Forca", "Assunto", "Categoria", "Fontes"], rows, title="O que esta em alta agora", compact=True)
    return trends


def show_search(cfg: Config, keywords: list[str], limit: int = 15) -> list:
    from . import discovery

    with ui.console.status(f" Buscando videos sobre: {', '.join(keywords)}...", spinner="line"):
        cands = discovery.find_candidates(cfg, keywords=keywords, limit=limit)
    rows = [[str(i), ui.score_text(c.score), Text(c.title[:55]), c.channel[:20], c.platform,
             fmt_views(c.views), fmt_duration(c.duration)] for i, c in enumerate(cands, 1)]
    ui.table(["#", "Potencial", "Video", "Canal", "Onde", "Views", "Dur."], rows,
             title=f"Videos encontrados ({len(cands)})", compact=True)
    return cands


def do_login(cfg: Config, platform: str) -> int:
    from . import publish

    platform = platform.lower()
    if platform not in PLATFORMS:
        ui.err(f"Plataforma desconhecida: {platform}. Use: {', '.join(PLATFORMS)}")
        return 2
    ui.panel(
        f"Vou abrir o navegador do CORTEX (perfil separado do seu Chrome normal).\n\n"
        f"1. Entre na sua conta do [b]{platform}[/b] normalmente.\n"
        f"2. Quando terminar, FECHE a janela do navegador.\n\n"
        f"Sua senha fica so no navegador - o CORTEX nunca ve nem guarda senha.",
        title=f"Login no {platform}", color=ui.C_CYAN)
    try:
        okk = publish.login(platform, cfg)
    except Exception as e:
        ui.err(f"Login falhou: {e}")
        return 1
    if okk:
        ui.ok(f"Login no {platform} detectado e salvo!")
        from . import policy

        policy.register_login(platform)
        if cfg.get("publicacao.aquecimento.ativo", True):
            ui.dim("Conta registrada. Aquecimento: nos primeiros dias o CORTEX posta pouco de proposito "
                   "(protege a conta nova). Ajuste em config.yaml > publicacao > aquecimento.")
        return 0
    ui.warn(f"Nao detectei o login no {platform}. Tente de novo.")
    return 1


def do_claude_login() -> int:
    """Abre a autorizacao do Claude no navegador do dono. Ele so clica em Autorizar."""
    import subprocess
    import time

    from . import tools
    from .brain.claude_cli import clean_env
    from .util import run_cmd

    exe = tools.claude()
    if not exe:
        ui.err("Não achei o Claude Code neste PC. Instale o app Claude ou o Claude Code.")
        return 1

    def logged() -> bool:
        import json

        try:
            return bool(json.loads(run_cmd([exe, "auth", "status"], timeout=30, env=clean_env()).stdout).get("loggedIn"))
        except Exception:
            return False

    if logged():
        ui.ok("O Claude já está conectado.")
        return 0
    ui.panel("Vou abrir uma janela e o seu navegador na página do Claude.\n\n"
             "1. Entre na sua conta do Claude (se pedir) e clique em [b]Autorizar[/b].\n"
             "2. Se aparecer um código, cole na janela que abriu e aperte Enter.\n\n"
             "O CORTEX não vê a sua senha. Uso limitado a poucas chamadas por dia (Ajustes > Avançado).",
             title="Conectar o Claude", color=ui.C_CYAN)
    subprocess.Popen(["cmd", "/c", "start", "Conectar o Claude", "/D", str(paths.STATE), exe, "auth", "login"],
                     cwd=str(paths.STATE), env=clean_env())
    try:
        with ui.console.status(" Esperando você autorizar (até 5 min)...", spinner="line"):
            end = time.time() + 300
            while time.time() < end:
                time.sleep(4)
                if logged():
                    (paths.STATE / "cerebro_disponibilidade.json").unlink(missing_ok=True)
                    ui.ok("Claude conectado! Ele passa a escolher os cortes e escrever os títulos.")
                    return 0
    except KeyboardInterrupt:
        pass
    ui.warn("Ainda não conectou. Se autorizar depois, rode de novo para conferir.")
    return 1


def do_youtube_api(cfg: Config) -> int:
    """Conecta o YouTube pela API oficial (o dono cria o cliente no Google e autoriza no navegador dele)."""
    import shutil

    from . import policy
    from .publish import youtube_api as api

    if not api.CLIENT_FILE.exists():
        found = api.find_client_download()
        if found and ui.ask_confirm(f"Achei {found.name} na pasta Downloads. Usar este?", default=True):
            api.CLIENT_FILE.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(found), str(api.CLIENT_FILE))
    if not api.CLIENT_FILE.exists():
        ui.panel(
            "Faça uma vez só, com a conta Google do canal:\n\n"
            "1. Abra console.cloud.google.com e crie um projeto chamado CORTEX.\n"
            "2. APIs e serviços > Biblioteca: procure 'YouTube Data API v3' e clique em Ativar.\n"
            "3. Tela de consentimento OAuth: tipo Externo, preencha nome e e-mail e clique em Publicar app\n"
            "   (se ficar em teste, a conexão cai a cada 7 dias).\n"
            "4. Credenciais > Criar credenciais > ID do cliente OAuth > App para computador.\n"
            "5. Clique em Baixar JSON (deixe na pasta Downloads) e volte aqui.",
            title="API oficial do YouTube", color=ui.C_CYAN)
        return 1
    ui.info("Vou abrir o navegador. Entre com a conta do canal e clique em Permitir.")
    ui.dim("O Google avisa que o app não foi verificado: ele é seu, clique em Avançado e continue.")
    try:
        nome = api.connect()
    except Exception as e:
        ui.err(f"Não conectou: {e}")
        return 1
    policy.register_login("youtube")
    ui.ok(f"Conectado ao canal {nome}. O YouTube agora vai pela API oficial, sem abrir navegador.")
    return 0


def do_selftest(cfg: Config, platform: str | None) -> int:
    from . import publish

    rc = 0
    for p in ([platform] if platform else list(cfg.get("publicacao.plataformas", PLATFORMS))):
        with ui.console.status(f" Testando a pagina de upload do {p} (nao publica nada)...", spinner="line"):
            try:
                res = publish.selftest(p, cfg)
            except Exception as e:
                res = {"ok": False, "erro": str(e)}
        if isinstance(res, dict):
            if res.get("ok"):
                ui.ok(f"{p}: tudo certo para publicar")
            else:
                rc = 1
                ui.err(f"{p}: {res.get('erro') or res.get('error') or res}")
            for k, v in (res.get("checks") or {}).items():
                ui.dim(f"{'OK' if v else 'X'} {k}")
        else:
            ui.info(f"{p}: {res}")
    return rc


def do_schedule(cfg: Config, horarios: list[str] | None) -> int:
    from . import scheduler

    horarios = horarios or list(cfg.get("execucao.horarios", []))
    try:
        created = scheduler.install(horarios)
    except Exception as e:
        ui.err(str(e))
        return 1
    ui.ok(f"Agendado para rodar todo dia as: {', '.join(created)}")
    ui.dim("Roda com voce logado no Windows; se o PC estiver desligado no horario, roda quando ligar.")
    return 0


def show_schedule() -> None:
    from . import scheduler

    st = scheduler.status()
    if not st:
        ui.info("Agendamento automatico: DESLIGADO")
        return
    ui.table(["Tarefa", "Estado", "Proxima", "Ultima", "Resultado"],
             [[t.get("nome"), t.get("estado"), t.get("proxima"), t.get("ultima"), str(t.get("resultado"))] for t in st],
             title="Agendamento automatico")


def show_status(cfg: Config) -> None:
    from . import painel, storage, tools

    ui.console.print(painel.summary(painel.snapshot(cfg)))
    ui.rule("DIAGNOSTICO")
    rows = []
    for name, p in tools.summary().items():
        rows.append([name, Text("OK", style=ui.C_OK) if p else Text("X", style=ui.C_RED), (p or "nao encontrado")[-70:]])
    try:
        import yt_dlp

        rows.append(["yt-dlp", Text("OK", style=ui.C_OK), yt_dlp.version.__version__])
    except Exception as e:
        rows.append(["yt-dlp", Text("X", style=ui.C_RED), str(e)])
    ui.table(["Programa", "", "Onde / versao"], rows, title="Programas")

    # cerebro
    try:
        from .brain import get_brain

        with ui.console.status(" verificando cerebro...", spinner="line"):
            b = get_brain(cfg)
        ui.info(f"Cerebro: {b.status()}")
    except Exception as e:
        ui.err(f"Cerebro: {e}")

    # whisper
    model = cfg.get("transcricao.modelo_whisper", "small")
    has = any(model in p.name for p in paths.MODELS.glob("*")) if paths.MODELS.exists() else False
    ui.info(f"Whisper '{model}': {'baixado' if has else 'sera baixado no primeiro uso'}")

    # logins
    try:
        from . import publish

        for p in cfg.get("publicacao.plataformas", PLATFORMS):
            try:
                okk = publish.check_login(p, cfg)
            except Exception:
                okk = False
            (ui.ok if okk else ui.warn)(f"Login {p}: {'OK' if okk else 'NAO LOGADO (menu > Contas, ou: cortex login {p})'}")
    except Exception as e:
        ui.warn(f"Publicador indisponivel: {e}")

    # fundos
    try:
        from .editor import backgrounds

        lib = backgrounds.ensure_library(cfg) if hasattr(backgrounds, "ensure_library") else {}
        ui.info("Fundos: " + ", ".join(f"{k}={len(v)}" for k, v in lib.items()))
    except Exception as e:
        ui.warn(f"Biblioteca de fundos: {e}")

    u = storage.usage()
    (ui.info if u["livre_gb"] >= cfg.get("armazenamento.espaco_minimo_livre_gb", 2) else ui.warn)(
        f"Disco livre: {u['livre_gb']} GB | trabalho {u['work']} | cortes {u['renders']} | fundos {u['fundos']} | "
        f"modelos {u['modelos']}")
    od = storage.onedrive_root(cfg)
    if od:
        ui.info(f"OneDrive: cortes publicados vao para {od} "
                f"({'sincronizando' if storage.onedrive_running() else 'ATENCAO: OneDrive fechado'})")
    s = db.stats()
    ui.info(f"Historico: {s['execucoes']} rodadas | {s['videos']} videos | {s['cortes']} cortes | "
            f"{s['publicados']} publicados | {s['aguardando_revisao']} aguardando revisao")
    from . import autopilot, policy

    for line in policy.describe(cfg):
        ui.dim("conta " + line)
    ui.info(autopilot.status_text())
    show_schedule()


def show_history(n: int = 15) -> None:
    rows = []
    for r in db.last_runs(n):
        import json
        from datetime import datetime

        sm = json.loads(r["summary"] or "{}")
        rows.append([datetime.fromtimestamp(r["started"]).strftime("%d/%m %H:%M"), r["trigger"], r["search_mode"],
                     r["publish_mode"], r["status"], str(sm.get("cortes", "")), str(sm.get("posts", ""))])
    ui.table(["Quando", "Disparo", "Busca", "Publicacao", "Status", "Cortes", "Posts"], rows, title="Ultimas rodadas")


def show_metrics(cfg: Config) -> None:
    """Views de cada post, saude das contas e o que o CORTEX aprendeu."""
    try:
        from . import learning, metrics
    except ImportError:
        ui.warn("Modulo de metricas indisponivel nesta versao.")
        return
    with ui.console.status(" Lendo as views dos posts (link publico, sem login)...", spinner="line"):
        res = metrics.collect(cfg) or {}
    rows = []
    for r in metrics.summary_rows(cfg) or []:
        rows.append([Text(str(r.get("titulo", ""))[:50]), r.get("rede", ""), r.get("idade", ""),
                     str(r.get("views", "")), str(r.get("likes", "")), r.get("situacao", "")])
    if rows:
        ui.table(["Post", "Rede", "Idade", "Views", "Likes", "Situacao"], rows, title="Desempenho dos posts (7 dias)",
                 compact=True)
    else:
        ui.info("Ainda nao ha posts publicados para medir.")
    for p in cfg.get("publicacao.plataformas", PLATFORMS):
        h = metrics.account_health(p, cfg) or {}
        (ui.ok if h.get("nivel", "normal") == "normal" else ui.warn)(
            f"Conta {p}: {h.get('nivel', 'normal')} | {h.get('motivo') or 'tudo certo'}")
    for m in res.get("mensagens") or []:
        ui.dim(m)
    for line in learning.insights(cfg) or []:
        ui.info(line)


def show_analysis(cfg: Config, rodar: bool = False) -> None:
    """Numeros de cada post, nota das contas, placar dos testes A/B e a leitura do analista."""
    from . import analista, estrategia, experimentos, numeros

    if rodar:
        with ui.console.status(" Lendo os números no YouTube Studio e no TikTok Studio...", spinner="line"):
            numeros.collect(cfg)
        with ui.console.status(" Analisando...", spinner="line"):
            experimentos.adotar()
            estrategia.decidir(cfg)
            analista.analisar(cfg, force=True)
    rows = []
    for rede in cfg.get("publicacao.plataformas", PLATFORMS):
        for p in estrategia.posts(rede)[:10]:
            ret = "-" if p["ret"] is None else f"{p['ret']:.0f}%"
            rows.append([Text(ui.term(p["titulo"])[:40]), estrategia.NOMES.get(rede, rede), f"{p['idade_h']:.0f} h", str(p["views"]),
                         str(p["likes"]), ret, "-" if not p["tempo"] else f"{p['tempo']:.0f} s"])
    if rows:
        ui.table(["Post", "Rede", "Idade", "Views", "Curtidas", "Assistem", "Tempo médio"], rows, title="Números reais (do seu canal)", compact=True)
    for rot, txt, nivel in estrategia.linhas(cfg):
        (ui.ok if nivel in ("ótima", "boa") else ui.warn)(f"{rot}: {txt}")
    for rede in cfg.get("publicacao.plataformas", PLATFORMS):
        s = estrategia.saude(rede, cfg)
        for m in s["motivos"]:
            ui.dim(f"{estrategia.NOMES.get(rede, rede)}: {m}")
        ui.info(f"Primeiro viral no {estrategia.NOMES.get(rede, rede)} (10 mil views): {estrategia.viral(rede, cfg)['texto']}")
    ab = [[Text(r["pergunta"]), Text(experimentos.frase(r))] for r in experimentos.avaliar()]
    ui.table(["Teste A/B", "Placar"], ab, title="O que está sendo testado", compact=True)
    a = analista.last()
    if a.get("resumo"):
        ui.rule("ANALISTA")
        ui.info(a["resumo"])
        for k, tit in (("deu_certo", "Deu certo"), ("nao_deu", "Não deu")):
            for x in a.get(k) or []:
                ui.dim(f"{tit}: {x['o_que']} [{x['forca']}: {x['prova']}]")
        for k, tit in (("padrao", "Padrão"), ("proximo_teste", "Próximo teste"), ("alerta", "Alerta")):
            if a.get(k):
                ui.info(f"{tit}: {a[k]}")
    from . import auditor

    reg = auditor.linhas()
    ui.rule("AUDITOR (decide, confere e desfaz sozinho)")
    for d in reg:
        ui.info(d)
    if not reg:
        ui.dim("Nenhuma mudança ainda: ele só mexe com números suficientes (a partir de 8 posts com 20 h em cada rede).")
    for x in (estrategia.state().get("historico") or [])[-1:]:
        for d in x.get("decisoes", []):
            ui.dim(f"Quantidade: {d}")


def show_clips(n: int = 20) -> None:
    """Todos os cortes recentes e a situacao de cada um (a mesma lista do relatorio)."""
    from datetime import datetime

    rows = []
    for r in db.clip_overview(n):
        rows.append([datetime.fromtimestamp(r["created"]).strftime("%d/%m %H:%M") if r["created"] else "",
                     Text(ui.term(r["title"])[:56]), str(int(r["score"])), r["situacao"]])
    if rows:
        ui.table(["Quando", "Corte", "Nota", "Situação"], rows, title="Todos os cortes", compact=True)
    else:
        ui.info("Nenhum corte ainda.")


def do_backgrounds(cfg: Config, action: str) -> int:
    from .editor import backgrounds

    if action == "baixar":
        with ui.console.status(" Baixando videos de fundo (licenca Creative Commons)...", spinner="line"):
            got = backgrounds.download_pack(cfg)
        ui.ok(f"{len(got)} video(s) de fundo baixados")
    elif action == "gerar":
        with ui.console.status(" Gerando fundos procedurais...", spinner="line"):
            lib = backgrounds.ensure_library(cfg)
        ui.ok("Fundos: " + ", ".join(f"{k}={len(v)}" for k, v in lib.items()))
    else:
        lib = backgrounds.ensure_library(cfg)
        for cat, files in lib.items():
            ui.info(f"{cat}: {len(files)}")
            for f in files[:8]:
                ui.dim(str(f.name))
        ui.dim(f"Pasta: {paths.BACKGROUNDS}  (pode colocar seus proprios .mp4 nas subpastas)")
    return 0


def open_report() -> int:
    from .report import refresh

    p = refresh()
    if not p:
        ui.warn("Nenhum relatorio ainda.")
        return 1
    os.startfile(str(p))
    ui.ok(f"Abrindo {p}")
    return 0


# =========================================================== piloto
def do_autopilot(dry_run: bool = False, no_publish: bool = False, headless: bool = False) -> int:
    from .autopilot import Autopilot

    try:
        return Autopilot(dry_run=dry_run, no_publish=no_publish).run(headless=headless)
    except RuntimeError as e:
        ui.err(str(e))
        return 2


# =========================================================== argparse
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cortex", description="CORTEX - Central Operacional de Recortes, Tendencias e EXposicao.")
    p.add_argument("--versao", action="version", version=f"CORTEX {__version__}")
    p.add_argument("-v", "--verbose", action="store_true", help="mostra logs detalhados")
    sub = p.add_subparsers(dest="cmd")

    r = sub.add_parser("rodar", help="roda uma rodada completa")
    r.add_argument("--modo", choices=["trends", "palavra_chave", "misto"])
    r.add_argument("--temas", help="palavras-chave separadas por virgula (ativa modo palavra_chave)")
    r.add_argument("--videos", type=int, help="quantos videos-fonte processar")
    r.add_argument("--publicar", choices=["auto", "revisar", "nao_publicar"])
    r.add_argument("--teste", action="store_true", help="publicacao de teste (preenche tudo, nao publica)")
    r.add_argument("--agendado", action="store_true", help="modo nao interativo (usado pelo agendador)")
    r.add_argument("--cerebro", choices=["claude", "ollama", "heuristico"])

    c = sub.add_parser("cortar", help="corta um ou mais links especificos")
    c.add_argument("urls", nargs="+")
    c.add_argument("--publicar", choices=["auto", "revisar", "nao_publicar"])
    c.add_argument("--teste", action="store_true")
    c.add_argument("--cerebro", choices=["claude", "ollama", "heuristico"])

    sub.add_parser("tendencias", help="mostra o que esta em alta agora")
    b = sub.add_parser("buscar", help="busca videos por palavra-chave (sem processar)")
    b.add_argument("palavras", nargs="+")
    sub.add_parser("revisar", help="revisa e publica cortes prontos")
    lg = sub.add_parser("login", help="login no YouTube, TikTok ou Claude")
    lg.add_argument("plataforma", choices=PLATFORMS + ("youtube-api", "claude"))
    tp = sub.add_parser("testar-publicacao", help="confere a pagina de upload sem publicar")
    tp.add_argument("plataforma", nargs="?", choices=PLATFORMS)
    ag = sub.add_parser("agendar", help="liga o agendamento automatico diario")
    ag.add_argument("--horarios", help="ex.: 09:00,13:00,18:00,22:00")
    sub.add_parser("desagendar", help="desliga o agendamento automatico")
    sub.add_parser("agenda", help="mostra o agendamento")
    ap = sub.add_parser("autopiloto", help="PILOTO AUTOMATICO 24/7 com painel ao vivo")
    ap.add_argument("--teste", action="store_true", help="simula a publicacao (nao publica de verdade)")
    ap.add_argument("--so-produzir", action="store_true", help="produz cortes mas nao publica")
    ap.add_argument("--fundo", action="store_true", help="sem janela (o menu e 'cortex acompanhar' mostram o andamento)")
    sub.add_parser("acompanhar", help="painel ao vivo do que esta rodando (fechar nao para nada)")
    sub.add_parser("parar", help="desliga o automatico")
    vg = sub.add_parser("vigia", help=argparse.SUPPRESS)
    vg.add_argument("--espera", type=float, default=0)
    sub.add_parser("pedidos", help=argparse.SUPPRESS)
    ia = sub.add_parser("inicio-automatico", help="liga/desliga o piloto ao entrar no Windows")
    ia.add_argument("acao", choices=["ligar", "desligar"])
    sub.add_parser("status", help="diagnostico do sistema")
    sub.add_parser("historico", help="ultimas rodadas")
    sub.add_parser("metricas", help="views dos posts, saude das contas e aprendizado")
    an = sub.add_parser("analise", help="numeros, nota das contas, testes A/B e a leitura do analista")
    an.add_argument("--agora", action="store_true", help="le os numeros e analisa agora")
    rt = sub.add_parser("retomar", help="tira uma conta da pausa de seguranca")
    rt.add_argument("plataforma", choices=PLATFORMS)
    sub.add_parser("relatorio", help="abre o ultimo relatorio")
    f = sub.add_parser("fundos", help="biblioteca de videos de fundo")
    f.add_argument("acao", nargs="?", default="listar", choices=["listar", "baixar", "gerar"])
    lp = sub.add_parser("limpar", help="libera espaco em disco")
    lp.add_argument("--tudo", action="store_true", help="apaga tambem cortes nao publicados antigos")
    sub.add_parser("config", help="abre o config.yaml")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    log.setup(verbose=getattr(args, "verbose", False))
    paths.ensure_dirs()
    cfg = load_config()
    try:
        if not args.cmd:
            from .menu import interactive_menu

            return interactive_menu()
        if args.cmd in ("rodar", "cortar") and not getattr(args, "agendado", False):
            from . import andamento, painel

            if andamento.read():
                ui.warn("Já tem uma rodada em andamento:")
                ui.console.print(painel.summary(painel.snapshot(cfg)))
                ui.dim("Veja ao vivo com: cortex acompanhar")
                return 2
        if args.cmd == "rodar":
            ui.banner()
            kws = [k.strip() for k in (args.temas or "").split(",") if k.strip()]
            mode = args.modo or ("palavra_chave" if kws else None)
            return do_run(cfg, mode=mode, keywords=kws, videos=args.videos, publish=args.publicar,
                          dry_run=args.teste, scheduled=args.agendado, brain=args.cerebro)
        if args.cmd == "cortar":
            ui.banner()
            return do_run(cfg, urls=args.urls, videos=len(args.urls), publish=args.publicar,
                          dry_run=args.teste, brain=args.cerebro)
        if args.cmd == "tendencias":
            show_trends(cfg)
        elif args.cmd == "buscar":
            show_search(cfg, args.palavras)
        elif args.cmd == "revisar":
            from .review import review

            review(cfg)
        elif args.cmd == "login":
            if args.plataforma == "claude":
                return do_claude_login()
            if args.plataforma == "youtube-api":
                return do_youtube_api(cfg)
            return do_login(cfg, args.plataforma)
        elif args.cmd == "testar-publicacao":
            return do_selftest(cfg, args.plataforma)
        elif args.cmd == "agendar":
            hs = [h.strip() for h in args.horarios.split(",")] if args.horarios else None
            return do_schedule(cfg, hs)
        elif args.cmd == "desagendar":
            from . import scheduler

            ui.ok(f"{scheduler.remove_all()} tarefa(s) removida(s).")
        elif args.cmd == "agenda":
            show_schedule()
        elif args.cmd == "autopiloto":
            return do_autopilot(dry_run=args.teste, no_publish=args.so_produzir, headless=args.fundo)
        elif args.cmd == "acompanhar":
            from . import painel

            painel.watch()
        elif args.cmd == "parar":
            from . import menu

            menu.stop_autopilot()
        elif args.cmd == "vigia":
            import time

            from . import fundo

            time.sleep(min(60, max(0, args.espera)))
            fundo.ensure()
        elif args.cmd == "pedidos":
            from . import autopilot, fundo

            autopilot.set_low_priority()

            def atender(c: Config, req: dict) -> int:
                rc = do_run(c, mode=req.get("mode"), keywords=req.get("keywords"), urls=req.get("urls"),
                            videos=req.get("videos"), publish=req.get("publish"), origem_fundo=True)
                return rc

            return fundo.serve_requests(load_config, atender)
        elif args.cmd == "inicio-automatico":
            from . import scheduler

            if args.acao == "ligar":
                scheduler.install_autostart()
                ui.ok("O piloto automatico vai ligar sozinho quando voce entrar no Windows.")
            else:
                ui.ok("Desligado." if scheduler.remove_autostart() else "Nao estava ligado.")
        elif args.cmd == "status":
            show_status(cfg)
        elif args.cmd == "historico":
            show_history()
        elif args.cmd == "analise":
            show_analysis(cfg, rodar=args.agora)
        elif args.cmd == "metricas":
            show_metrics(cfg)
        elif args.cmd == "retomar":
            from . import metrics

            metrics.resume(args.plataforma)
            ui.ok(f"Conta {args.plataforma} retomada: o CORTEX volta a postar nela.")
        elif args.cmd == "relatorio":
            return open_report()
        elif args.cmd == "fundos":
            return do_backgrounds(cfg, args.acao)
        elif args.cmd == "limpar":
            from . import storage

            r = storage.cleanup(cfg, aggressive=args.tudo)
            ui.ok(f"Liberado: {r['liberado_txt']} | disco livre: {r['livre_gb']} GB")
        elif args.cmd == "config":
            os.startfile(str(paths.CONFIG_PATH))
        return 0
    except KeyboardInterrupt:
        ui.warn("Interrompido pelo usuario.")
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
