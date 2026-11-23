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
           dry_run=False, scheduled=False, brain=None) -> int:
    from .pipeline import RunOptions, run
    from .report import print_summary

    opts = RunOptions(
        trigger="agendado" if scheduled else "manual",
        search_mode=mode, keywords=keywords or [], urls=urls or [], n_videos=videos,
        publish_mode=publish, interactive=not scheduled, dry_run=dry_run, brain=brain,
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
        try:
            p = publish.export_cookies_txt(cfg)
            if p:
                ui.dim("cookies exportados para o downloader (evita bloqueio 'nao sou robo' do YouTube)")
        except Exception:
            pass
        return 0
    ui.warn(f"Nao detectei o login no {platform}. Tente de novo.")
    return 1


def do_claude_login() -> int:
    """Abre o Claude Code numa janela nova para o usuario fazer /login (uma vez so)."""
    import subprocess

    from . import tools

    exe = tools.claude()
    if not exe:
        ui.err("Nao achei o Claude Code neste PC. Instale o app Claude ou o Claude Code.")
        return 1
    ui.panel(
        "Vou abrir o Claude Code numa janela nova.\n\n"
        "1. Digite [b]/login[/b] e Enter, e siga o login no navegador.\n"
        "2. Quando aparecer que voce esta logado, digite [b]/exit[/b] e feche a janela.\n\n"
        "Depois disso o CORTEX passa a usar o Claude para escolher os cortes e escrever os titulos.",
        title="Login no Claude", color=ui.C_CYAN)
    subprocess.Popen(["cmd", "/c", "start", "Claude - login", "/D", str(paths.STATE), exe],
                     cwd=str(paths.STATE))
    try:
        from .brain import get_brain  # noqa: F401

        cache = paths.STATE / "cerebro_disponibilidade.json"
        if cache.exists():
            cache.unlink()  # forca nova checagem do login na proxima rodada
    except Exception:
        pass
    ui.ok("Janela aberta. Depois de logar, rode o Diagnostico para conferir.")
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
    from . import storage, tools

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
            (ui.ok if okk else ui.warn)(f"Login {p}: {'OK' if okk else 'NAO LOGADO (menu > Login, ou: cortex login {p})'}")
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
    from .report import latest

    p = latest()
    if not p:
        ui.warn("Nenhum relatorio ainda.")
        return 1
    os.startfile(str(p))
    ui.ok(f"Abrindo {p}")
    return 0


# =========================================================== menu
def _quick_status(cfg: Config) -> Text:
    from . import storage

    t = Text("  ")
    try:
        pend = db.stats()["aguardando_revisao"]
    except Exception:
        pend = 0
    t.append(f"modo: {cfg.get('modo_publicacao')}", style=ui.C_CYAN)
    t.append("  |  ", style=ui.C_DIM)
    t.append(f"{cfg.get('execucao.videos_por_execucao')} videos/rodada", style="white")
    t.append("  |  ", style=ui.C_DIM)
    t.append(f"cerebro: {cfg.get('cerebro.motor')}", style="white")
    t.append("  |  ", style=ui.C_DIM)
    livre = storage.free_gb()
    t.append(f"disco livre: {livre:.1f} GB", style=ui.C_OK if livre > 3 else ui.C_YEL)
    if pend:
        t.append("  |  ", style=ui.C_DIM)
        t.append(f"{pend} corte(s) esperando revisao", style=f"bold {ui.C_YEL}")
    return t


def _ask_int(q: str, default: int) -> int:
    ans = ui.ask_text(q, str(default))
    try:
        return max(1, int(ans))
    except ValueError:
        return default


def _ask_publish_mode(cfg: Config) -> str | None:
    return ui.ask_select("E depois de cortar?", [
        ("revisar", "Me mostrar antes (eu aprovo e envia tudo de uma vez)"),
        ("auto", "Publicar sozinho no TikTok + YouTube Shorts"),
        ("nao_publicar", "So gerar os videos"),
    ], default=cfg.get("modo_publicacao", "revisar"))


def menu_settings(cfg: Config) -> None:
    while True:
        ui.rule("CONFIGURACOES")
        choice = ui.ask_select("Mudar o que?", [
            ("modo", f"Modo de publicacao padrao: {cfg.get('modo_publicacao')}"),
            ("videos", f"Videos por rodada: {cfg.get('execucao.videos_por_execucao')}"),
            ("cortes", f"Cortes por video: {cfg.get('execucao.cortes_por_video')}"),
            ("busca", f"Modo de busca: {cfg.get('busca.modo')}  (palavras: {', '.join(cfg.get('busca.palavras_chave') or []) or '-'})"),
            ("cerebro", f"Cerebro (IA): {cfg.get('cerebro.motor')}"),
            ("layout", f"Layout dos videos: {cfg.get('edicao.layout')}"),
            ("tom", f"Volume da polemica: {cfg.get('conteudo.tom_titulo')}"),
            ("marca", f"Marca d'agua: {cfg.get('edicao.marca_dagua') or '(nenhuma)'}"),
            ("arquivo", "Abrir config.yaml completo no Bloco de Notas"),
            ("voltar", "<- Voltar"),
        ])
        if choice in (None, "voltar"):
            return
        if choice == "arquivo":
            os.startfile(str(paths.CONFIG_PATH))
            continue
        if choice == "modo":
            v = _ask_publish_mode(cfg)
            if v:
                save_value("modo_publicacao", v)
        elif choice == "videos":
            save_value("execucao.videos_por_execucao", _ask_int("Quantos videos-fonte por rodada?", cfg.get("execucao.videos_por_execucao", 5)))
        elif choice == "cortes":
            v = ui.ask_text("Cortes por video (numero ou 'auto'):", str(cfg.get("execucao.cortes_por_video")))
            save_value("execucao.cortes_por_video", int(v) if v.isdigit() else "auto")
        elif choice == "busca":
            v = ui.ask_select("Modo de busca padrao:", [("trends", "Tendencias automaticas"),
                                                         ("palavra_chave", "So minhas palavras-chave"),
                                                         ("misto", "Os dois")], default=cfg.get("busca.modo"))
            if v:
                save_value("busca.modo", v)
                if v in ("palavra_chave", "misto"):
                    kw = ui.ask_text("Palavras-chave (separadas por virgula):", ", ".join(cfg.get("busca.palavras_chave") or []))
                    save_value("busca.palavras_chave", [k.strip() for k in kw.split(",") if k.strip()])
        elif choice == "cerebro":
            v = ui.ask_select("Qual IA usar?", [("auto", "auto (Claude > Ollama > heuristico)"), ("claude", "Claude"),
                                                 ("ollama", "Ollama (local)"), ("heuristico", "Sem IA (heuristico)")],
                              default=cfg.get("cerebro.motor"))
            if v:
                save_value("cerebro.motor", v)
        elif choice == "layout":
            v = ui.ask_select("Layout:", [("auto", "auto"), ("split", "video em cima + gameplay embaixo"),
                                          ("blur", "fundo desfocado"), ("full", "tela cheia")], default=cfg.get("edicao.layout"))
            if v:
                save_value("edicao.layout", v)
        elif choice == "tom":
            from . import tom

            v = ui.ask_select("Volume da polemica nos titulos e textos:",
                              [(lv, tom.LABELS[lv]) for lv in tom.LEVELS], default=tom.level(cfg))
            if v:
                save_value("conteudo.tom_titulo", v)
                if v == "modo_besta":
                    ui.warn("Modo besta: palavrao sem mascara e provocacao no maximo. As redes podem reduzir o "
                            "alcance de texto com palavrao explicito. O piso (nada inventado sobre pessoa real, "
                            "nada com menores, nada de odio) continua valendo.")
        elif choice == "marca":
            save_value("edicao.marca_dagua", ui.ask_text("Texto da marca d'agua (ex.: @seucanal):", cfg.get("edicao.marca_dagua", "")))
        cfg = load_config()
        ui.ok("Salvo.")


def do_autopilot(dry_run: bool = False, no_publish: bool = False) -> int:
    from .autopilot import Autopilot

    try:
        return Autopilot(dry_run=dry_run, no_publish=no_publish).run()
    except RuntimeError as e:
        ui.err(str(e))
        return 2


def menu_autopilot(cfg: Config) -> None:
    from . import policy, scheduler

    ui.rule("PILOTO AUTOMATICO 24/7", ui.C_RED)
    ui.panel(
        "O CORTEX fica ligado sem parar:\n"
        "  - quando a fila de cortes baixa, ele descobre o que esta em alta, corta e edita;\n"
        "  - publica um corte por vez, espacado, priorizando o horario nobre;\n"
        "  - respeita o aquecimento de conta nova e o limite diario de cada rede;\n"
        "  - se algo der errado, registra, espera e tenta de novo.\n\n"
        "Painel ao vivo com log. Para parar: Ctrl+C.",
        title="Como funciona", color=ui.C_CYAN)
    for line in policy.describe(cfg):
        ui.dim(line)
    auto_on = scheduler.autostart_enabled()
    choice = ui.ask_select("Piloto automatico:", [
        ("ligar", "LIGAR AGORA (produz e publica sozinho)"),
        ("teste", "Ligar em modo TESTE (produz e simula a publicacao)"),
        ("produzir", "Ligar so produzindo (sem publicar)"),
        ("auto_on" if not auto_on else "auto_off",
         "Ligar sozinho quando o Windows iniciar" if not auto_on else " Nao ligar mais sozinho com o Windows"),
        ("voltar", "<- Voltar"),
    ])
    if choice == "ligar":
        do_autopilot()
    elif choice == "teste":
        do_autopilot(dry_run=True)
    elif choice == "produzir":
        do_autopilot(no_publish=True)
    elif choice == "auto_on":
        try:
            scheduler.install_autostart()
            ui.ok("Pronto: o piloto liga sozinho 2 minutos depois que voce entrar no Windows.")
        except Exception as e:
            ui.err(str(e))
    elif choice == "auto_off":
        ui.ok("Inicio automatico desligado." if scheduler.remove_autostart() else "Nao estava ligado.")


def menu_schedule(cfg: Config) -> None:
    from . import scheduler

    show_schedule()
    choice = ui.ask_select("Agendamento:", [
        ("ligar", f"Ligar/atualizar ({', '.join(cfg.get('execucao.horarios', []))})"),
        ("horarios", "Mudar horarios e ligar"),
        ("agora", ">  Disparar a rodada agendada agora (teste)"),
        ("desligar", " Desligar"),
        ("voltar", "<- Voltar"),
    ])
    if choice == "ligar":
        do_schedule(cfg, None)
    elif choice == "horarios":
        v = ui.ask_text("Horarios (HH:MM separados por virgula):", ", ".join(cfg.get("execucao.horarios", [])))
        hs = [h.strip() for h in v.split(",") if h.strip()]
        save_value("execucao.horarios", hs)
        do_schedule(load_config(), hs)
    elif choice == "agora":
        ui.ok("Disparado." if scheduler.run_now() else "Nenhuma tarefa agendada.")
    elif choice == "desligar":
        n = scheduler.remove_all()
        ui.ok(f"{n} tarefa(s) removida(s).")


def interactive_menu() -> int:
    while True:
        cfg = load_config()
        os.system("cls")
        ui.banner()
        ui.console.print(_quick_status(cfg))
        ui.console.print()
        choice = ui.ask_select("O que vamos fazer?", [
            ("piloto", "PILOTO AUTOMATICO 24/7 (tudo sozinho, com painel ao vivo)"),
            ("rodar", "Rodar uma vez agora (descobrir o que esta em alta e cortar)"),
            ("palavra", "Rodar com um tema / palavra-chave"),
            ("link", "Cortar um link especifico (YouTube, Twitch, Kick, Rumble...)"),
            ("trends", "Ver o que esta em alta agora"),
            ("revisar", "Revisar e publicar cortes prontos"),
            ("login", "Login (YouTube / TikTok / Claude)"),
            ("agenda", "Agendamento automatico (2 a 4x por dia)"),
            ("fundos", "Biblioteca de fundos (gameplay / ASMR)"),
            ("relatorio", "Abrir ultimo relatorio"),
            ("metricas", "Desempenho dos posts (views, saude da conta, aprendizado)"),
            ("historico", "Historico de rodadas"),
            ("status", "Diagnostico do sistema"),
            ("config", " Configuracoes"),
            ("sair", "Sair"),
        ])
        try:
            if choice in (None, "sair"):
                return 0
            if choice == "piloto":
                menu_autopilot(cfg)
            elif choice == "rodar":
                n = _ask_int("Quantos videos-fonte processar?", cfg.get("execucao.videos_por_execucao", 5))
                pm = _ask_publish_mode(cfg)
                do_run(cfg, mode="trends", videos=n, publish=pm)
            elif choice == "palavra":
                kw = ui.ask_text("Tema(s) / palavra(s)-chave (separe por virgula):")
                if kw:
                    n = _ask_int("Quantos videos-fonte processar?", cfg.get("execucao.videos_por_execucao", 5))
                    pm = _ask_publish_mode(cfg)
                    do_run(cfg, mode="palavra_chave", keywords=[k.strip() for k in kw.split(",") if k.strip()],
                           videos=n, publish=pm)
            elif choice == "link":
                url = ui.ask_text("Cole o(s) link(s) (separe por espaco):")
                if url:
                    pm = _ask_publish_mode(cfg)
                    urls = url.split()
                    do_run(cfg, urls=urls, videos=len(urls), publish=pm)
            elif choice == "trends":
                trends = show_trends(cfg)
                if trends and ui.ask_confirm("Quer cortar videos de algum desses assuntos agora?", default=False):
                    picked = ui.ask_checkbox("Quais assuntos?", [(t.topic, t.topic, False) for t in trends[:25]])
                    if picked:
                        n = _ask_int("Quantos videos-fonte?", cfg.get("execucao.videos_por_execucao", 5))
                        do_run(cfg, mode="palavra_chave", keywords=picked, videos=n, publish=_ask_publish_mode(cfg))
            elif choice == "revisar":
                from .review import review

                review(cfg)
            elif choice == "login":
                p = ui.ask_select("Qual conta?", [("youtube", "YouTube"), ("tiktok", "TikTok"),
                                                  ("claude", "Claude (a IA que escolhe os cortes)"), ("voltar", "<- Voltar")])
                if p == "claude":
                    do_claude_login()
                elif p in PLATFORMS:
                    do_login(cfg, p)
                    if ui.ask_confirm("Testar a pagina de upload agora (sem publicar nada)?", default=True):
                        do_selftest(cfg, p)
            elif choice == "agenda":
                menu_schedule(cfg)
            elif choice == "fundos":
                a = ui.ask_select("Fundos:", [("listar", "Ver biblioteca"), ("baixar", " Baixar mais (Creative Commons)"),
                                              ("gerar", "Gerar fundos procedurais"), ("voltar", "<- Voltar")])
                if a and a != "voltar":
                    do_backgrounds(cfg, a)
            elif choice == "relatorio":
                open_report()
            elif choice == "historico":
                show_history()
            elif choice == "metricas":
                show_metrics(cfg)
            elif choice == "status":
                show_status(cfg)
            elif choice == "config":
                menu_settings(cfg)
                continue
        except KeyboardInterrupt:
            ui.warn("Interrompido.")
        except Exception as e:
            ui.err(f"Erro: {e}")
            log.get("cli").error(traceback.format_exc())
        ui.pause()


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
    lg.add_argument("plataforma", choices=PLATFORMS + ("claude",))
    tp = sub.add_parser("testar-publicacao", help="confere a pagina de upload sem publicar")
    tp.add_argument("plataforma", nargs="?", choices=PLATFORMS)
    ag = sub.add_parser("agendar", help="liga o agendamento automatico diario")
    ag.add_argument("--horarios", help="ex.: 09:00,13:00,18:00,22:00")
    sub.add_parser("desagendar", help="desliga o agendamento automatico")
    sub.add_parser("agenda", help="mostra o agendamento")
    ap = sub.add_parser("autopiloto", help="PILOTO AUTOMATICO 24/7 com painel ao vivo")
    ap.add_argument("--teste", action="store_true", help="simula a publicacao (nao publica de verdade)")
    ap.add_argument("--so-produzir", action="store_true", help="produz cortes mas nao publica")
    ia = sub.add_parser("inicio-automatico", help="liga/desliga o piloto ao entrar no Windows")
    ia.add_argument("acao", choices=["ligar", "desligar"])
    sub.add_parser("status", help="diagnostico do sistema")
    sub.add_parser("historico", help="ultimas rodadas")
    sub.add_parser("metricas", help="views dos posts, saude das contas e aprendizado")
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
            return interactive_menu()
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
            return do_autopilot(dry_run=args.teste, no_publish=args.so_produzir)
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
