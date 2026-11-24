"""Publicador: YouTube Shorts, TikTok e Reels pelo navegador (Chrome real com perfil proprio da Fabrica).

API (docs/CONTRATOS.md):
    login(platform, cfg) -> bool
    check_login(platform, cfg) -> bool
    publish_batch(clips, cfg, platforms=None, dry_run=False, on_event=None) -> list[PostResult]
    export_cookies_txt(cfg) -> Path | None
    build_post_text(plan, platform, cfg, video_title=None, channel=None) -> (titulo, descricao)
    selftest(platform, cfg) -> {"ok": bool, "erro": str | None, "checks": {nome: bool}}

Erros que pedem acao humana comecam com "ACAO_NECESSARIA:" (login, captcha, verificacao) e
"LIMITE_DIARIO:" (a rede pediu para parar por hoje). Captcha/verificacao/limite pausam a rede por
publicacao.pausa_apos_bloqueio_h (padrao 24 h) ou ate o dono refazer o login (guard.py).
Resultado ok=True com erro "INCERTO: ..." = cliquei em Publicar mas nao vi a confirmacao: o corte
NUNCA e reenviado para aquela rede.
Camada de acoes: human.py. Pesquisa e regras: docs/PUBLICACAO_SEGURA.md. Seletores: docs/PUBLICACAO.md.
"""
from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Any, Callable

from .. import db
from ..log import get as get_log
from ..models import PostResult, RenderedClip
from . import browser, guard, human, instagram, tiktok, youtube, youtube_api
from .browser import (PROFILE_IN_USE_MSG, BrowserLaunchError, BrowserSession, ProfileInUseError,
                      export_cookies_txt, login, screenshot)
from .captions import build_post_text, source_info, strip_emojis

__all__ = ["login", "check_login", "publish_batch", "export_cookies_txt", "build_post_text", "selftest",
           "UPLOADERS", "BrowserSession", "ProfileInUseError", "PROFILE_IN_USE_MSG"]

log = get_log(__name__)

UPLOADERS = {"youtube": youtube, "tiktok": tiktok, "instagram": instagram}
NOMES = {"youtube": "YouTube", "tiktok": "TikTok", "instagram": "Instagram"}
BLOCKING_PREFIXES = ("ACAO_NECESSARIA", "LIMITE_DIARIO")


def check_login(platform: str, cfg: Any = None, deep: bool = False) -> bool:
    """Conta pronta para publicar? YouTube pela API oficial vale como login."""
    if (platform or "").lower() == "youtube" and cfg is not None and youtube_api.enabled(cfg) and youtube_api.connected():
        return True
    return browser.check_login(platform, cfg, deep)


def _emitter(on_event: Callable[[str], None] | None) -> Callable[[str], None]:
    def emit(msg: str) -> None:
        msg = strip_emojis(msg)  # nunca emoji no terminal/log
        log.info(msg)
        if on_event:
            try:
                on_event(msg)
            except Exception:
                pass
    return emit


def _interval(cfg: Any, dry_run: bool) -> tuple[float, float]:
    key = "publicacao.intervalo_teste_s" if dry_run else "publicacao.intervalo_entre_posts_s"
    default = [5, 15] if dry_run else [90, 240]
    v = cfg.get(key, default) or default
    try:
        if isinstance(v, (int, float)):
            return float(v), float(v)
        a, b = float(v[0]), float(v[-1])
        return (min(a, b), max(a, b))
    except Exception:
        return float(default[0]), float(default[1])


def _daily_limit(cfg: Any, platform: str) -> int:
    lim = cfg.get("publicacao.max_posts_por_dia", {}) or {}
    n = int(lim.get(platform, 10) or 0) if isinstance(lim, dict) else int(lim or 0)
    if not n:
        return n
    try:        # o auditor pode ter decidido mais, sempre dentro de estrategia.teto
        from .. import policy

        return max(n, int(policy.daily_limit(platform, cfg)))
    except Exception:
        return n


def _policy_ok(platform: str, cfg: Any) -> tuple[bool, str]:
    """Segunda trava: as mesmas regras do orquestrador (aquecimento, limite do dia, intervalo minimo)."""
    try:
        from .. import policy

        return policy.can_post(platform, cfg)
    except Exception as e:  # sem conferir a regra nao arriscamos
        log.warning("policy.can_post(%s): %s", platform, e)
        return False, f"não consegui conferir as regras da conta ({e})"


def is_risk_signal(error: str | None) -> bool:
    """Captcha, verificacao da conta ou limite da rede: sinais de risco que pausam a rede por horas."""
    e = (error or "").lower()
    return e.startswith("limite_diario") or "captcha" in e or "verifica" in e


def _uncertain_from_ledger(clip: RenderedClip, platform: str) -> PostResult | None:
    """Se ja clicamos em Publicar para este corte nesta rede (e o banco nao sabe), NUNCA reenviar."""
    entry = guard.publish_clicked(clip.plan.id, platform)
    if not entry:
        return None
    quando = time.strftime("%d/%m %H:%M", time.localtime(float(entry.get("ts", time.time()))))
    return PostResult(clip.plan.id, platform, True, url=entry.get("url"), ts=time.time(),
                      error=f"INCERTO: já cliquei em Publicar para este corte em {quando}; não reenvio "
                            f"(confira na rede se ele saiu).")


def publish_batch(clips: list[RenderedClip], cfg: Any, platforms: list[str] | None = None, dry_run: bool = False,
                  on_event: Callable[[str], None] | None = None) -> list[PostResult]:
    """Publica cortes (human.py) e varias travas de seguranca.

    - pula (clip, rede) ja publicado (db.already_posted), repetido na lista ou com clique em Publicar ja
      registrado (guard.py): o mesmo corte nunca vai duas vezes para a mesma rede;
    - respeita publicacao.max_posts_por_dia e, como SEGUNDA trava, policy.can_post (aquecimento, limite do
      dia, intervalo minimo) antes de abrir o navegador e de novo antes de CADA post (fora do modo teste);
    - rede pausada por captcha/verificacao/limite nao recebe nada (nem teste) ate a pausa acabar ou o dono
      refazer o login;
    - uma publicacao por vez no PC (trava entre processos);
    - uma sessao de navegador por "horario de post" (um corte, todas as redes dele), fechada no fim;
    - espera aleatoria de publicacao.intervalo_entre_posts_s entre posts NA MESMA rede (navegador fechado);
    - cada resultado e salvo com db.save_post. Os cortes que ficaram para tras nao geram resultado.
    """
    emit = _emitter(on_event)
    if not platforms:       # rede com cortes proprios so recebe quando pedida pelo nome (exclusivas.py)
        from .. import exclusivas

        platforms = exclusivas.conjunto(cfg)
    wanted = [str(p).lower() for p in platforms]
    plats = [p for p in wanted if p in UPLOADERS]
    for p in wanted:
        if p not in UPLOADERS:
            emit(f"Rede desconhecida ignorada: {p}")
    results: list[PostResult] = []
    if not clips or not plats:
        return results

    def record(r: PostResult) -> None:
        results.append(r)
        try:
            db.save_post(r)
        except Exception as e:
            log.warning("db.save_post: %s", e)

    try:
        guard.publish_clicked("_", "_")  # registro legivel? sem ele, publicar poderia repetir um post
    except guard.LedgerError as e:
        emit(f"Não vou publicar nada: {e}")
        return results

    # redes pausadas por bloqueio recente (captcha, verificacao, limite): nem abre o navegador
    blocked: dict[str, str] = {}
    for p in plats:
        pz = guard.paused_until(p)
        if pz:
            blocked[p] = pz[1]
            emit(f"[{p}] pausado até {time.strftime('%d/%m %H:%M', time.localtime(pz[0]))} por segurança "
                 f"({pz[1][:120]}). Para liberar antes: cortex login {p}.")

    # fila (clip x rede) na ordem recebida (o pipeline ja ordena series: Parte 1 antes da 2)
    queue: list[tuple[RenderedClip, str]] = []
    seen: set[tuple[str, str]] = set()
    for clip in clips:
        for p in plats:
            key = (clip.plan.id, p)
            if key in seen or p in blocked:
                continue
            seen.add(key)
            if not dry_run and db.already_posted(clip.plan.id, p):
                emit(f"[{p}] já publicado antes, pulando: {strip_emojis(clip.plan.title)[:50]}")
                continue
            if not dry_run:
                unc = _uncertain_from_ledger(clip, p)
                if unc is not None:
                    emit(f"[{p}] {unc.error}")
                    record(unc)
                    continue
            fpath = clip.path_for(p)
            if not Path(fpath).is_file():
                record(PostResult(clip.plan.id, p, False, error=f"arquivo do corte não encontrado: {fpath}",
                                  ts=time.time(), dry_run=dry_run))
                continue
            queue.append((clip, p))

    # limite diario da Fabrica (publicacao.max_posts_por_dia) antes de abrir o navegador
    posted = {p: db.posts_today(p) for p in plats}
    if not dry_run:
        room = {p: (_daily_limit(cfg, p) - posted[p]) if _daily_limit(cfg, p) else 10**6 for p in plats}
        kept, over = [], {p: 0 for p in plats}
        for clip, p in queue:
            if room[p] > 0:
                kept.append((clip, p))
                room[p] -= 1
            else:
                over[p] += 1
        for p, n in over.items():
            if n:
                emit(f"[{p}] limite diário da Fábrica ({_daily_limit(cfg, p)}/dia, já foram {posted[p]}): "
                     f"{n} corte(s) ficam para amanhã")
        queue = kept
        # segunda trava (mesmas regras do orquestrador): se a rede nao pode agora, nem abre o navegador
        for p in sorted({q for _, q in queue}):
            ok, why = _policy_ok(p, cfg)
            if not ok:
                emit(f"[{p}] regra de segurança da conta: {why}. Nada vai para o {NOMES[p]} agora.")
                queue = [(c, q) for c, q in queue if q != p]
    if not queue:
        emit("Nada novo para publicar.")
        return results

    lock = guard.PublishLock()
    if not lock.acquire():
        emit("Outra publicação do CORTEX está em andamento neste PC; não vou abrir um segundo navegador. "
             "Os cortes continuam na fila.")
        return results
    try:
        _run_queue(queue, cfg, dry_run, emit, record, blocked, posted)
    finally:
        lock.release()
    return results


def _allowed_now(clip: RenderedClip, p: str, cfg: Any, emit: Callable[[str], None], held: dict[str, int]) -> bool:
    """Rechecagem logo antes do post: outro processo pode ter publicado; as regras mudam com o tempo."""
    if db.already_posted(clip.plan.id, p) or guard.publish_clicked(clip.plan.id, p):
        emit(f"[{p}] este corte já foi enviado para o {NOMES[p]}; pulando.")
        return False
    ok, why = _policy_ok(p, cfg)
    if not ok:
        emit(f"[{p}] regra de segurança da conta: {why}. Fica para depois.")
        held[p] = held.get(p, 0) + 1
    return ok


def _after(r: PostResult, p: str, cfg: Any, dry_run: bool, emit: Callable[[str], None],
           record: Callable[[PostResult], None], blocked: dict[str, str], posted: dict[str, int],
           last_end: dict[str, float]) -> None:
    record(r)
    last_end[p] = time.time()
    if r.ok:
        if not dry_run:
            posted[p] = posted.get(p, 0) + 1
        emit(f"[{p}] {'(teste) ok' if dry_run else 'publicado'}: {r.url or '(sem link)'}")
        return
    emit(f"[{p}] falhou: {r.error}")
    if (r.error or "").startswith(BLOCKING_PREFIXES):
        blocked[p] = r.error or ""
        if is_risk_signal(r.error):
            until = guard.pause_platform(p, r.error or "", cfg)
            emit(f"[{p}] {NOMES[p]} pausado até {time.strftime('%d/%m %H:%M', time.localtime(until))} "
                 f"(não vou insistir; 'cortex login {p}' libera antes).")
        else:
            emit(f"[{p}] pausando o {NOMES[p]} neste lote (não vou insistir).")


def _post_api(clip: RenderedClip, cfg: Any, dry_run: bool, emit: Callable[[str], None],
              record: Callable[[PostResult], None], blocked: dict[str, str], posted: dict[str, int],
              held: dict[str, int], last_end: dict[str, float]) -> None:
    if not dry_run and not _allowed_now(clip, "youtube", cfg, emit, held):
        return
    vt, ch = source_info(clip.plan)
    text = build_post_text(clip.plan, "youtube", cfg, video_title=vt, channel=ch)
    emit(f"[youtube] {'(teste) ' if dry_run else ''}enviando pela API oficial: {strip_emojis(text[0])[:70]}")
    try:
        r = youtube_api.upload(clip, cfg, text, dry_run=dry_run, on_event=emit)
    except Exception as e:
        log.exception("API do YouTube")
        clicked = guard.publish_clicked(clip.plan.id, "youtube")
        r = PostResult(clip.plan.id, "youtube", bool(clicked), ts=time.time(), dry_run=dry_run,
                       error=f"INCERTO: {e}" if clicked else f"Falha na API do YouTube: {e}")
    _after(r, "youtube", cfg, dry_run, emit, record, blocked, posted, last_end)


def _run_queue(queue: list[tuple[RenderedClip, str]], cfg: Any, dry_run: bool, emit: Callable[[str], None],
               record: Callable[[PostResult], None], blocked: dict[str, str], posted: dict[str, int]) -> None:
    held: dict[str, int] = {}
    last_end: dict[str, float] = {}
    lo, hi = _interval(cfg, dry_run)

    # agrupa por corte: cada corte = um "horario de post" = UMA sessao de navegador (todas as redes dele)
    slots: list[tuple[RenderedClip, list[str]]] = []
    for clip, p in queue:
        if slots and slots[-1][0] is clip:
            slots[-1][1].append(p)
        else:
            slots.append((clip, [p]))

    for clip, slot_plats in slots:
        todo = [p for p in slot_plats if p not in blocked]
        for p in slot_plats:
            if p in blocked:
                held[p] = held.get(p, 0) + 1
        if not dry_run:
            sem_vaga = [p for p in todo if not _policy_ok(p, cfg)[0]]
            for p in sem_vaga:
                held[p] = held.get(p, 0) + 1
            todo = [p for p in todo if p not in sem_vaga]
        if not todo:
            continue
        # intervalo entre posts na mesma rede (com o navegador FECHADO)
        now = time.time()
        waits = [random.uniform(lo, hi) - (now - last_end[p]) for p in todo if p in last_end]
        wait = max(waits) if waits else 0
        if wait > 1:
            emit(f"Aguardando {int(wait)} s antes do próximo post (navegador fechado)...")
            time.sleep(wait)

        # YouTube pela API oficial quando conectada: nao precisa de navegador
        if "youtube" in todo and youtube_api.ready(cfg):
            _post_api(clip, cfg, dry_run, emit, record, blocked, posted, held, last_end)
            todo = [p for p in todo if p != "youtube"]
            if not todo:
                continue

        # modo semi do TikTok: o humano clica em Publicar, entao a janela precisa estar visivel
        semi = (not dry_run and "tiktok" in todo and tiktok.tiktok_mode(cfg) == "semi")
        session = BrowserSession(cfg, headless=False if semi else None, on_event=emit)
        try:
            session.start()
        except Exception as e:
            if isinstance(e, ProfileInUseError):
                msg = f"ACAO_NECESSARIA: {PROFILE_IN_USE_MSG}"
            elif isinstance(e, BrowserLaunchError):
                msg = f"ACAO_NECESSARIA: {e}"
            else:
                msg = f"Falha ao abrir o navegador da Fábrica: {e}"
            emit(msg)
            for p in todo:  # um resultado por rede explicando; o resto fica para a proxima
                record(PostResult(clip.plan.id, p, False, error=msg, ts=time.time(), dry_run=dry_run))
            return

        where = "fora da tela" if (browser._hidden_window(cfg) and not semi and not session.headless) else "visível"
        emit(f"Navegador da Fábrica aberto ({'novo' if session.launched else 'reaproveitado'}, {where}): "
             f"{', '.join(todo)}" + (" [MODO TESTE: nada será publicado]" if dry_run else ""))
        try:
            for i, p in enumerate(todo):
                if p in blocked:
                    held[p] = held.get(p, 0) + 1
                    continue
                if not dry_run and not _allowed_now(clip, p, cfg, emit, held):
                    continue
                if i:
                    human.sleep(3, 8)  # troca de rede: pausa curta
                vt, ch = source_info(clip.plan)
                text = build_post_text(clip.plan, p, cfg, video_title=vt, channel=ch)
                emit(f"[{p}] {'(teste) ' if dry_run else ''}enviando: {strip_emojis(text[0])[:70]}")
                page = None
                try:
                    page = session.new_page()
                    r = UPLOADERS[p].upload(page, clip, cfg, dry_run=dry_run, text=text, on_event=emit)
                except Exception as e:  # upload() ja trata tudo; isso e so rede de seguranca
                    r = PostResult(clip.plan.id, p, False, error=f"Falha no {NOMES[p]}: {e}", ts=time.time(),
                                   dry_run=dry_run, screenshot=screenshot(page, p, clip.plan.id) if page else None)
                finally:
                    if page is not None:
                        try:
                            page.close(run_before_unload=False)
                        except Exception:
                            pass
                _after(r, p, cfg, dry_run, emit, record, blocked, posted, last_end)
            if "youtube" in todo and "youtube" not in blocked and cfg.get("publicacao.exportar_cookies", False):
                try:  # cookies frescos para o yt-dlp
                    export_cookies_txt(cfg, session=session)
                except Exception as e:
                    log.debug("export cookies: %s", e)
        finally:
            session.close()
    for p, n in held.items():
        if n:
            emit(f"[{p}] {n} corte(s) ficaram para depois: {blocked.get(p) or 'regras de segurança da conta'}")


def selftest(platform: str, cfg: Any) -> dict:
    """Depois do login: abre o Studio da rede como uma pessoa e confere a pagina de upload SEM enviar nada.

    Os campos de titulo/legenda/privacidade so aparecem depois de escolher um arquivo; para testar
    esses use um lote em modo teste (dry_run), que preenche tudo e NAO clica em Publicar.
    """
    platform = (platform or "").lower()
    if platform not in UPLOADERS:
        return {"ok": False, "erro": f"rede desconhecida: {platform}", "checks": {}}
    if platform == "youtube" and youtube_api.ready(cfg):
        try:
            return {"ok": True, "erro": None, "checks": {f"API oficial: {youtube_api.channel_name()}": True}}
        except Exception as e:
            return {"ok": False, "erro": f"API oficial: {e}", "checks": {"API oficial": False}}
    checks: dict[str, bool] = {"Cookies de login no perfil": check_login(platform, cfg)}
    pz = guard.paused_until(platform)
    if pz:
        return {"ok": False, "checks": checks,
                "erro": f"{NOMES[platform]} pausado até {time.strftime('%d/%m %H:%M', time.localtime(pz[0]))} "
                        f"por segurança ({pz[1][:120]}). Rode 'cortex login {platform}' para liberar."}
    lock = guard.PublishLock()
    if not lock.acquire():
        return {"ok": False, "erro": "outra publicação do CORTEX está em andamento; tente depois", "checks": checks}
    session = BrowserSession(cfg)
    try:
        try:
            session.start()
        except ProfileInUseError:
            return {"ok": False, "erro": PROFILE_IN_USE_MSG, "checks": checks}
        except Exception as e:
            return {"ok": False, "erro": f"Falha ao abrir o navegador: {e}", "checks": checks}
        shot = None
        try:
            page = session.new_page()
            res = UPLOADERS[platform].selftest_page(page, cfg)
            shot = screenshot(page, platform, "selftest", "teste")
        except Exception as e:
            res = {"ok": False, "erro": f"Falha no teste: {e}", "checks": {}}
        finally:
            session.close()
    finally:
        lock.release()
    checks.update(res.get("checks") or {})
    ok = bool(res.get("ok")) and all(checks.values())
    erro = res.get("erro")
    if not ok and not erro:
        erro = f"faltou login (rode: cortex login {platform})"
    if erro and is_risk_signal(erro):  # captcha/verificacao ate no teste: pausa a rede tambem
        guard.pause_platform(platform, erro, cfg)
    return {"ok": ok, "erro": erro, "checks": checks, "screenshot": shot, "info": res.get("info", {}),
            "ritmo": res.get("ritmo", {}),
            "nota": "Título/legenda/privacidade só aparecem após escolher o vídeo: teste com o modo teste (dry run)."}
