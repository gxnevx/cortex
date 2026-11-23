"""Menu do CORTEX: poucas opcoes, linguagem simples. Os comandos avancados continuam em `cortex --help`."""
from __future__ import annotations

import os
import time
import traceback

from . import log, paths, ui
from .painel import plan_line
from .config import Config, load_config, save_value

NOMES = {"youtube": "YouTube", "tiktok": "TikTok"}


# ------------------------------------------------------------------ situacao
def _networks(cfg: Config) -> list[str]:
    return list(cfg.get("publicacao.plataformas", ["youtube", "tiktok"]))


def _logged(cfg: Config) -> dict[str, bool]:
    from . import publish

    out = {}
    for p in _networks(cfg):
        try:
            out[p] = bool(publish.check_login(p, cfg))
        except Exception:
            out[p] = False
    return out


def _pause(platform: str) -> str | None:
    from .publish import guard

    pz = guard.paused_until(platform)
    return f"parado até {time.strftime('%d/%m %H:%M', time.localtime(pz[0]))}, precisa de você" if pz else None


def _pending() -> int:
    try:
        from .review import pending

        return len(pending())
    except Exception:
        return 0


# --------------------------------------------------------------- automatico
RISK = (
    "[b]RISCO DE BANIMENTO[/b]\n\n"
    "No automático o CORTEX posta sozinho, pelo navegador, sem ninguém conferir.\n"
    "YouTube e TikTok podem reduzir o alcance, suspender ou banir a conta por isso,\n"
    "e donos de vídeos podem pedir a remoção. Use uma conta que você aceita perder.\n\n"
    "Se aparecer CAPTCHA, eu abro o navegador na sua tela, você resolve e eu continuo."
)


def stop_autopilot() -> None:
    from . import autopilot, fundo, scheduler

    fundo.set_wanted(False)
    scheduler.remove_autostart()
    if not autopilot.running():
        ui.ok("O automático já estava desligado.")
        return
    autopilot.request_stop()
    with ui.console.status(" Desligando (se um post está no meio, ele termina antes)...", spinner="line"):
        end = time.time() + 900
        while autopilot.running() and time.time() < end:
            time.sleep(1)
    ui.ok("Automático desligado." if not autopilot.running() else "Ainda terminando um post; ele desliga em seguida.")


def auto_flow(cfg: Config) -> None:
    from . import autopilot, cli, fundo, painel, scheduler

    if autopilot.running():
        c = ui.ask_select("O automático já está ligado.", [("ver", "Acompanhar ao vivo"), ("parar", "Desligar o automático"),
                                                          ("voltar", "Voltar")])
        if c == "ver":
            painel.watch()
        elif c == "parar":
            stop_autopilot()
        return

    ui.panel(RISK, title="Atenção", color=ui.C_RED)
    if ui.ask_select("Ligar o automático?", [("ok", "OK, entendi o risco. Pode ligar"), ("voltar", "Voltar")]) != "ok":
        return

    logged = _logged(cfg)
    for p in _networks(cfg):
        if not logged[p] or _pause(p):
            why = "sem login" if not logged[p] else "esperando você resolver uma verificação"
            if ui.ask_confirm(f"{NOMES.get(p, p)} {why}. Abrir agora?", default=True):
                cli.do_login(cfg, p)
    logged = _logged(cfg)
    if not any(logged.values()):
        ui.warn("Nenhuma conta conectada. Faça o login e tente de novo.")
        return

    save_value("modo_publicacao", "auto")
    boot = True
    try:
        scheduler.install_autostart()
    except Exception as e:
        boot = False
        log.get("menu").warning("vigia: %s", e)
    with ui.console.status(" Ligando em segundo plano...", spinner="line"):
        on = fundo.start_autopilot()
    if not on:
        ui.err("O automático não deu sinal de vida. Veja logs\\segundo_plano_autopiloto.log ou rode o Diagnóstico em Ajustes.")
        return
    cfg = load_config()
    lines = ["[b]TUDO OK. O automático roda todo dia, sozinho.[/b]\n"]
    for p in _networks(cfg):
        lines.append(f"{NOMES.get(p, p):<9} {plan_line(p, cfg) if logged[p] else 'sem login, não vai postar'}")
    lines += ["", "Roda em segundo plano: pode fechar esta janela.",
              "Se o PC reiniciar ou ele cair, religa sozinho." if boot else
              "Não consegui criar o vigia do Windows: se reiniciar o PC, abra o CORTEX e ligue de novo.",
              "Para ver o que está acontecendo, é só abrir o CORTEX."]
    ui.panel("\n".join(lines), title="Automático", color=ui.C_OK)
    if ui.ask_confirm("Ver o painel ao vivo agora?", default=True):
        painel.watch()


# ---------------------------------------------------------------- cortar agora
def cut_flow(cfg: Config) -> None:
    from . import andamento, fundo, painel

    run = andamento.read()
    if run:
        ui.warn("Já tem algo rodando:")
        ui.console.print(painel.summary(painel.snapshot(cfg)))
        c = ui.ask_select("O que fazer?", [("fila", "Colocar meu pedido na fila (começa quando este terminar)"),
                                           ("ver", "Acompanhar o que está rodando"),
                                           ("cancelar", "Parar o que está rodando"), ("voltar", "Voltar")])
        if c == "ver":
            painel.watch()
        elif c == "cancelar":
            cancel_run(run)
        if c != "fila":
            return
    txt = ui.ask_text("Cole um link ou escreva um assunto (vazio = eu escolho o que está em alta):", "")
    if txt is None:
        return
    words = txt.split()
    urls = [w for w in words if w.lower().startswith(("http://", "https://", "www."))]
    topics = [] if urls else [k.strip() for k in txt.split(",") if k.strip()]
    after = ui.ask_select("Quando ficar pronto?", [("revisar", "Me mostrar antes de postar"),
                                                   ("auto", "Postar sozinho (risco de banimento)"),
                                                   ("nao_publicar", "Só salvar os vídeos"), ("voltar", "Voltar")])
    if after in (None, "voltar"):
        return
    from . import autopilot

    if after == "auto" and autopilot.running():
        after = "fila"      # o automatico julga e posta nos melhores horarios
    n = int(cfg.get("execucao.videos_por_execucao", 5))
    req = {"publish": after, "videos": len(urls) if urls else n}
    if urls:
        req["urls"] = urls
    elif topics:
        req.update(mode="palavra_chave", keywords=topics)
    else:
        req["mode"] = "trends"
    pos = fundo.add_request(req)
    if run or pos > 1:
        ui.ok(f"Pedido na fila (posição {pos}). Começa sozinho quando terminar o que está rodando.")
    else:
        ui.ok("Começou em segundo plano. Pode fechar esta janela; aviso quando ficar pronto.")
    if ui.ask_confirm("Ver o painel ao vivo agora?", default=True):
        painel.watch()


def cancel_run(run: dict) -> None:
    """Para a rodada em andamento (a do automatico para junto com ele)."""
    from . import andamento, autopilot, fundo
    from .util import run_cmd

    hb = andamento.read_json(autopilot.HEARTBEAT) or {}
    if autopilot.running() and hb.get("pid") == run.get("pid"):
        ui.info("Quem está cortando é o automático.")
        if ui.ask_confirm("Desligar o automático?", default=False):
            stop_autopilot()
        return
    if not ui.ask_confirm("Parar a rodada? Os cortes prontos ficam, o que está no meio se perde.", default=False):
        return
    from .publish import guard

    lock = guard.PublishLock()
    if not lock.acquire():
        ui.warn("Tem um post sendo enviado agora. Espere ele terminar e cancele depois.")
        return
    try:
        fundo.clear_requests()
        if andamento.alive(run):
            run_cmd(["taskkill", "/PID", str(run["pid"]), "/T", "/F"], timeout=20)
    finally:
        lock.release()
    andamento.end()
    ui.ok("Parado. Os cortes que já estavam prontos continuam salvos.")


# ------------------------------------------------------------------ resultados
def results_flow(cfg: Config) -> None:
    from . import cli

    cli.show_analysis(cfg)
    if ui.ask_confirm("Ler os números e analisar agora? (usa 1 chamada do Claude)", default=False):
        cli.show_analysis(cfg, rodar=True)
    cli.show_clips(12)
    cli.show_history(6)
    if ui.ask_confirm("Abrir o relatório no navegador?", default=False):
        cli.open_report()


# --------------------------------------------------------------------- contas
def accounts_flow(cfg: Config) -> None:
    from . import cli
    from .publish import youtube_api

    logged = _logged(cfg)
    opts = []
    for p in _networks(cfg):
        opts.append((p, f"{NOMES.get(p, p)}: {_pause(p) or ('conectado' if logged[p] else 'entrar')}"))
    api = youtube_api.connected()
    opts += [("api", f"YouTube pela API oficial: {'conectada' if api else 'não conectada (recomendado)'}"),
             ("claude", "Claude (IA que ajuda a escolher os cortes)"), ("voltar", "Voltar")]
    c = ui.ask_select("Qual conta?", opts)
    if c in NOMES:
        cli.do_login(cfg, c)
    elif c == "api":
        cli.do_youtube_api(cfg)
    elif c == "claude":
        cli.do_claude_login()


# -------------------------------------------------------------------- ajustes
def settings_flow(cfg: Config) -> None:
    from . import cli, scheduler, tom

    while True:
        mx = cfg.get("publicacao.max_posts_por_dia", {}) or {}
        slow = bool(cfg.get("publicacao.aquecimento.ativo", True))
        own = cfg.get("busca.modo") != "trends"
        boot = scheduler.autostart_enabled()
        c = ui.ask_select("Ajustes", [
            ("dia", "Vídeos por dia: " + ", ".join(f"{NOMES.get(p, p)} {mx.get(p, '-')}" for p in _networks(cfg))),
            ("slow", f"Conta nova começa devagar: {'sim' if slow else 'não'}"),
            ("tom", f"Nível da polêmica: {tom.LABELS.get(tom.level(cfg), tom.level(cfg)).split('(')[0].strip()}"),
            ("temas", f"Assuntos: {', '.join(cfg.get('busca.palavras_chave') or []) if own else 'o que estiver em alta'}"),
            ("boot", f"Ligar o automático com o Windows: {'sim' if boot else 'não'}"),
            ("diag", "Diagnóstico"),
            ("arq", "Avançado (abrir o config.yaml)"),
            ("voltar", "Voltar"),
        ])
        if c in (None, "voltar"):
            return
        if c == "dia":
            for p in _networks(cfg):
                v = ui.ask_text(f"Máximo por dia no {NOMES.get(p, p)}:", str(mx.get(p, 2)))
                if v and v.isdigit():
                    save_value(f"publicacao.max_posts_por_dia.{p}", int(v))
        elif c == "slow":
            if slow and not ui.ask_confirm("Sem isso, conta nova posta no máximo já no primeiro dia (mais risco). "
                                           "Desligar?", default=False):
                continue
            save_value("publicacao.aquecimento.ativo", not slow)
        elif c == "tom":
            v = ui.ask_select("Nível da polêmica nos títulos:", [(lv, tom.LABELS[lv]) for lv in tom.LEVELS],
                              default=tom.level(cfg))
            if not v:
                continue
            save_value("conteudo.tom_titulo", v)
            if v == "modo_besta":
                ui.warn("Modo besta: palavrão sem máscara. As redes podem reduzir o alcance. O piso continua valendo: "
                        "nada inventado sobre pessoa real, nada com menores, nada de ódio.")
        elif c == "temas":
            v = ui.ask_text("Seus assuntos, separados por vírgula (vazio = o que estiver em alta):",
                            ", ".join(cfg.get("busca.palavras_chave") or []) if own else "")
            ks = [k.strip() for k in (v or "").split(",") if k.strip()]
            save_value("busca.palavras_chave", ks)
            save_value("busca.modo", "misto" if ks else "trends")
        elif c == "boot":
            try:
                scheduler.remove_autostart() if boot else scheduler.install_autostart()
            except Exception as e:
                ui.err(str(e))
                continue
        elif c == "diag":
            cli.show_status(cfg)
            ui.pause()
            continue
        elif c == "arq":
            os.startfile(str(paths.CONFIG_PATH))
            continue
        cfg = load_config()
        ui.ok("Salvo.")


# ----------------------------------------------------------------------- menu
def interactive_menu() -> int:
    from . import cli, painel

    while True:
        cfg = load_config()
        os.system("cls")
        ui.banner()
        snap = painel.snapshot(cfg)
        ui.console.print(painel.summary(snap))
        busy = bool(snap["rodada"]) or snap["automatico"]
        n = _pending()
        opts = [("ver", "Acompanhar o que está rodando")] if busy else []
        opts += [
            ("auto", "AUTOMÁTICO ligado (ver ou desligar)" if snap["automatico"] else "LIGAR O AUTOMÁTICO"),
            ("cortar", "Fazer cortes agora"),
            ("prontos", f"Ver cortes prontos ({n})"),
            ("resultados", "Resultados"),
            ("contas", "Contas"),
            ("ajustes", "Ajustes"),
            ("sair", "Sair (o que está rodando continua)" if busy else "Sair"),
        ]
        choice = ui.ask_select("O que vamos fazer?", opts)
        try:
            if choice in (None, "sair"):
                return 0
            if choice == "ver":
                painel.watch()
                continue
            if choice == "ajustes":
                settings_flow(cfg)
                continue
            if choice == "prontos":
                from .review import review

                review(cfg)
                cli.show_clips(12)
            else:
                {"auto": auto_flow, "cortar": cut_flow, "resultados": results_flow, "contas": accounts_flow}[choice](cfg)
        except KeyboardInterrupt:
            ui.warn("Interrompido.")
        except Exception as e:
            ui.err(f"Erro: {e}")
            log.get("cli").error(traceback.format_exc())
        ui.pause()
