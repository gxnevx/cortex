"""Reels pelo site do Instagram, no navegador do CORTEX (a sessao e do dono; sem API).

Fluxo: inicio -> confere que a conta ativa e a do canal -> Nova publicacao -> escolhe o arquivo -> recorte 9:16 ->
Seguinte -> Seguinte -> legenda -> Partilhar -> confirmacao -> link pela lista de reels do perfil.
dry_run: faz tudo menos o clique em Partilhar e descarta.
Nada aqui esconde que e automatico nem resolve CAPTCHA: se o Instagram avisar ou pedir verificacao, para e fica em pausa.
Textos em pt-BR, pt-PT e ingles (o site muda conforme a conta).
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable

from ..log import get as get_log
from ..models import CaptchaAppeared, NeedsUserAction, PostResult, RenderedClip
from . import guard, human
from .browser import exists, find, screenshot
from .captions import build_post_text, source_info, strip_emojis

log = get_log(__name__)

PLATFORM = "instagram"
HOME_URL = "https://www.instagram.com/"
UPLOAD_URL = HOME_URL
DIALOG = 'div[role="dialog"]'

SEL: dict[str, list] = {
    "create": ['a:has(svg[aria-label="Nova publicação"])', 'a:has(svg[aria-label="Novo post"])', 'a:has(svg[aria-label="New post"])',
               '[role="button"]:has(svg[aria-label="Nova publicação"])', '[role="button"]:has(svg[aria-label="New post"])',
               ("role", "link", r"^\s*(criar|create|nova publica[cç][aã]o|new post)\b")],
    # algumas contas abrem um menu antes (Publicacao / Video em direto / Anuncio)
    "create_post": ['a:has(svg[aria-label="Publicação"])', 'a:has(svg[aria-label="Post"])',
                    ("role", "link", r"^\s*(publica[cç][aã]o|post|postar)\s*$"), ("role", "button", r"^\s*(publica[cç][aã]o|post|postar)\s*$")],
    "file_input": [f'{DIALOG} input[type="file"][accept*="video"]', 'input[type="file"][accept*="video"]'],
    "select": [("role", "button", r"(selecionar (no|do) computador|select from computer)")],
    "crop_menu": ['button:has(svg[aria-label="Selecionar recorte"])', 'button:has(svg[aria-label="Selecionar corte"])',
                  'button:has(svg[aria-label="Select crop"])', 'button:has(svg[aria-label="Select Crop"])'],
    "crop_916": [f'{DIALOG} [role="button"]:has-text("9:16")'],
    "next": [("role", "button", r"^\s*(seguinte|avan[cç]ar|next)\s*$")],
    "share": [("role", "button", r"^\s*(partilhar|compartilhar|share)\s*$")],
    "caption": [f'{DIALOG} [role="textbox"][contenteditable="true"]', f'{DIALOG} textarea'],
    "ok": [("role", "button", r"^\s*ok\s*$")],
    "close": ['svg[aria-label="Fechar"]', 'svg[aria-label="Close"]'],
    "discard": [("role", "button", r"^\s*(descartar|discard)\s*$")],
    "captcha": ['iframe[src*="recaptcha"]', 'iframe[src*="captcha"]', 'iframe[title*="captcha" i]', '#captcha'],
    "login": ['input[type="password"]'],
}
# avisos que so informam: fecha sem mudar nada da conta
POPUPS = [("role", "button", r"^\s*(agora n[aã]o|not now)\s*$")]
COOKIES = [("role", "button", r"(recusar cookies opcionais|decline optional cookies)")]

CHALLENGE_RE = re.compile(r"instagram\.com/(challenge|auth_platform|accounts/(confirm|two_factor))", re.I)
DEAD_RE = re.compile(r"instagram\.com/accounts/(suspended|disabled)", re.I)
SUCCESS_RE = re.compile(r"(reel|v[ií]deo|publica[cç][aã]o|post)\s+(foi\s+)?(com)?partilhad[oa]|your (reel|post) has been shared|"
                        r"(reel|post) shared", re.I)
ERROR_RE = re.compile(r"(n[aã]o foi poss[ií]vel (com)?partilhar|n[aã]o foi poss[ií]vel (publicar|carregar)|n[aã]o p[oô]de ser (com)?partilhad|"
                      r"algo deu errado|ocorreu um (erro|problema)|something went wrong|couldn.?t be (shared|posted|uploaded)|"
                      r"formato .{0,20}n[aã]o (é )?suportado|file (type )?(is )?not supported|n[aã]o [eé] compat[ií]vel)", re.I)
RATE_RE = re.compile(r"(restringimos|limitamos (certas|determinadas)|a[cç][aã]o bloqueada|action blocked|we (restrict|limit)|"
                     r"tent[ae] novamente mais tarde|try again later|proteger a (nossa )?comunidade|protect our community)", re.I)
AUTO_RE = re.compile(r"(comportamento|atividade|behaviou?r|activity).{0,40}automati[zs]|automat(ed|izad).{0,40}(behaviou?r|activity|comportamento|atividade)", re.I)

LOGIN_MSG = ("ACAO_NECESSARIA: faça login no Instagram no navegador da Fábrica (menu > Contas, ou: cortex login instagram).")
CHECK_MSG = ("ACAO_NECESSARIA: o Instagram pediu uma verificação/captcha. Não resolvo sozinho: o Instagram fica pausado até você rodar "
             "'cortex login instagram' e resolver na janela.")
AUTO_MSG = ("LIMITE_DIARIO: o Instagram avisou sobre atividade automática. Parei o Instagram por 7 dias. Entre no aplicativo, veja o aviso "
            "e decida se quer continuar.")
WARN_HOURS = 7 * 24


class UncertainPost(Exception):
    """Cliquei em Partilhar, mas nao vi a confirmacao: NAO reenviar (pode ter saido)."""

    def __init__(self, msg: str, url: str | None = None):
        super().__init__(msg)
        self.url = url


# ---------------------------------------------------------------- verificacoes
def handle(cfg: Any) -> str:
    """@ do canal no Instagram, sem o @ (vazio = nao configurado)."""
    return str((cfg.get("publicacao.contas.instagram.handle", "") if cfg is not None else "") or "").strip().lstrip("@").strip("/")


def is_login_wall(page: Any) -> bool:
    return "/accounts/login" in (page.url or "") or exists(page, SEL["login"])


def _notices(page: Any) -> str:
    """Texto dos avisos na tela (fora do formulario, que tem o nosso proprio texto)."""
    out = []
    for sel in (DIALOG, '[role="alert"]'):
        try:
            loc = page.locator(sel)
            for i in range(min(loc.count(), 5)):
                el = loc.nth(i)
                if el.is_visible() and not el.locator('[role="textbox"]').count():
                    out.append(el.inner_text(timeout=1500) or "")
        except Exception:
            continue
    return " | ".join(out)[:5000]


def _check_blockers(page: Any) -> None:
    url = page.url or ""
    if DEAD_RE.search(url):
        raise NeedsUserAction("ACAO_NECESSARIA: o Instagram suspendeu ou desativou a conta (verificação). Abra o aplicativo e veja o aviso.")
    if CHALLENGE_RE.search(url):
        try:
            body = page.inner_text("body", timeout=3000) or ""
        except Exception:
            body = ""
        if AUTO_RE.search(body):
            raise NeedsUserAction(AUTO_MSG)
        raise CaptchaAppeared(CHECK_MSG)
    if is_login_wall(page):
        raise NeedsUserAction(LOGIN_MSG)
    if exists(page, SEL["captcha"]):
        raise CaptchaAppeared(CHECK_MSG)
    n = _notices(page)
    if AUTO_RE.search(n):
        raise NeedsUserAction(AUTO_MSG)
    m = RATE_RE.search(n)
    if m:
        raise NeedsUserAction(f'LIMITE_DIARIO: o Instagram pediu para ir mais devagar ("{m.group(0)}"). Pausei o Instagram.')


def own_account(page: Any, want: str, timeout: float = 15) -> bool | None:
    """A conta aberta e a do canal? None = nao deu para saber (sem @ no config)."""
    if not want:
        return None
    return find(page, [f'a[href="/{want}/"]:has(img)', f'a[href="/{want}/"]'], timeout=timeout) is not None


def _require_account(h: human.Actor, cfg: Any) -> None:
    want = handle(cfg)
    if own_account(h.page, want) is False:
        raise NeedsUserAction(f"ACAO_NECESSARIA: o Instagram do navegador da Fábrica não está na conta @{want}. Rode 'cortex login instagram' "
                              "e entre na conta do canal.")


def dismiss_popups(h: human.Actor) -> int:
    n = 0
    for cand in COOKIES + POPUPS:
        el = find(h.page, [cand], timeout=0)
        if el is not None:
            try:
                h.click(el, timeout=8, what="fechar aviso")
                n += 1
            except NeedsUserAction:
                raise
            except Exception:
                pass
    return n


# ------------------------------------------------------------------ reels do perfil
GRID_JS = """() => [...document.querySelectorAll('a[href*="/reel/"]')].map(a => {
  const m = (a.getAttribute('href') || '').match(/\\/reel\\/([\\w-]+)/);
  return m ? {code: m[1], text: (a.innerText || '').trim()} : null;
}).filter(Boolean)"""


def reels_url(want: str) -> str:
    return f"{HOME_URL}{want}/reels/"


def list_reels(page: Any, want: str, wait_s: float = 12) -> list[dict]:
    """[{code, text}] da aba Reels do perfil, do mais novo para o mais velho (text traz as visualizacoes)."""
    page.goto(reels_url(want), wait_until="domcontentloaded")
    end = time.time() + wait_s
    rows: list[dict] = []
    while time.time() < end:
        page.wait_for_timeout(1500)
        rows = page.evaluate(GRID_JS) or []
        if rows:
            page.wait_for_timeout(800)
            rows = page.evaluate(GRID_JS) or rows
            break
    seen, out = set(), []
    for r in rows:
        if r["code"] not in seen:
            seen.add(r["code"])
            out.append(r)
    return out


def reel_link(want: str, code: str) -> str:
    return f"{HOME_URL}{want}/reel/{code}/" if want else f"{HOME_URL}reel/{code}/"


# ------------------------------------------------------------------ envio
def _dialog(page: Any) -> Any:
    """So as janelas abertas: o feed atras tambem tem botoes Partilhar e Seguinte."""
    return page.locator(DIALOG)


def _open_create(h: human.Actor) -> None:
    page = h.page
    for tentativa in range(2):
        btn = find(page, SEL["create"], timeout=20)
        if btn is None:
            h.blockers()
            raise RuntimeError("botão 'Nova publicação' não encontrado")
        h.click(btn, enabled=False, what="'Nova publicação'")
        if find(page, SEL["file_input"], timeout=4, state="attached") is not None:
            return
        item = find(page, SEL["create_post"], timeout=2)
        if item is not None:
            h.click(item, enabled=False, what="'Publicação'")
        if find(page, SEL["file_input"], timeout=10, state="attached") is not None:
            return
        h.blockers()
        dismiss_popups(h)
    raise RuntimeError("a janela de nova publicação não abriu")


def _wait_editor(h: human.Actor, timeout: float) -> None:
    """Espera a tela de recorte e fecha o aviso "videos agora sao reels"."""
    page = h.page
    end = time.time() + timeout
    while time.time() < end:
        notes = _notices(page)
        ok = find(_dialog(page), SEL["ok"], timeout=0)
        if ok is not None and not ERROR_RE.search(notes):
            h.click(ok, what="OK do aviso de reels")
            continue
        if ERROR_RE.search(notes):
            raise RuntimeError(f"o Instagram recusou o vídeo: {ERROR_RE.search(notes).group(0)}")
        if find(_dialog(page), SEL["next"], timeout=1) is not None and page.locator(f"{DIALOG} video").count():
            h._wait(1.5)    # o aviso de reels pode abrir logo depois
            if find(_dialog(page), SEL["ok"], timeout=0) is None:
                return
        h.blockers()
        h._wait(0.7)
    raise RuntimeError(f"a tela de recorte não abriu em {int(timeout)} s")


RATIO_JS = """() => { const v = [...document.querySelectorAll('div[role="dialog"] video')].map(e => e.getBoundingClientRect())
  .sort((a, b) => b.height - a.height)[0]; return v ? [v.width, v.height, innerHeight] : null; }"""


def _is_vertical(page: Any) -> bool:
    """O video aparece inteiro em pe (9:16) na previa? Num recorte quadrado ele passa da tela."""
    r = page.evaluate(RATIO_JS)
    return bool(r) and r[1] > 0 and abs(r[0] / r[1] - 0.5625) < 0.03 and r[1] <= r[2]


def _set_crop(h: human.Actor) -> None:
    page = h.page
    menu = find(page, SEL["crop_menu"], timeout=10)
    if menu is None:
        if _is_vertical(page):
            return
        raise RuntimeError("botão de recorte não encontrado")
    h.click(menu, enabled=False, what="recorte")
    opt = find(page, SEL["crop_916"], timeout=6)
    if opt is None:
        raise RuntimeError("opção 9:16 não encontrada")
    h.click(opt, enabled=False, what="9:16")
    h.sleep(1.0)
    if not _is_vertical(page):
        raise RuntimeError("o vídeo não ficou em pé (9:16) na prévia")


def _to_caption(h: human.Actor) -> Any:
    page = h.page
    for _ in range(4):
        box = find(page, SEL["caption"], timeout=1)
        if box is not None:
            return box
        nxt = find(_dialog(page), SEL["next"], timeout=20)
        if nxt is None:
            break
        h.click(nxt, what="'Seguinte'")
        h.sleep(1.5)
    box = find(page, SEL["caption"], timeout=20)
    if box is None:
        raise RuntimeError("campo da legenda não encontrado")
    return box


def _norm(t: str | None) -> str:
    return re.sub(r"[^\w#]", "", t or "", flags=re.UNICODE).lower()


def _caption_ok(page: Any, caption: str) -> bool:
    box = find(page, SEL["caption"], timeout=2)
    if box is None:
        return False
    got = _norm(box.inner_text() if box.get_attribute("contenteditable") else box.input_value())
    lines = [x for x in caption.split("\n") if x.strip()]
    return bool(lines) and _norm(lines[0])[:20] in got and _norm(lines[-1])[-12:] in got


def _type_caption(h: human.Actor, caption: str) -> None:
    page = h.page
    box = _to_caption(h)
    h.click(box, enabled=False, what="legenda")
    h.select_all_and_delete()
    for i, line in enumerate(caption.split("\n")):
        if i:
            page.keyboard.press("Enter")
            h._wait(0.05)
        if line:
            page.keyboard.insert_text(line)
    page.keyboard.insert_text(" ")      # fecha as sugestoes da ultima hashtag
    h.sleep(0.8)
    if not _caption_ok(page, caption):
        raise RuntimeError("a legenda não ficou certa no editor")


def _wait_posted(h: human.Actor, timeout: float) -> None:
    page = h.page
    end = time.time() + timeout
    while time.time() < end:
        if h.blockers():
            end = time.time() + timeout
        notes = _notices(page)
        if SUCCESS_RE.search(notes):
            return
        if ERROR_RE.search(notes):
            raise RuntimeError(f"o Instagram não publicou: {ERROR_RE.search(notes).group(0)}")
        h._wait(1.5)
    raise RuntimeError("cliquei em Partilhar mas não vi a confirmação do Instagram")


def _posted_url(h: human.Actor, want: str, before: set[str]) -> str | None:
    if not want:
        return None
    end = time.time() + 75
    while time.time() < end:
        try:
            for r in list_reels(h.page, want):
                if r["code"] not in before:
                    return reel_link(want, r["code"])
        except Exception as e:
            log.debug("link do instagram: %s", e)
        h._wait(8)
    return None


def _discard(h: human.Actor) -> bool:
    """Modo teste: fecha a janela e confirma Descartar."""
    page = h.page
    try:
        btn = find(page, SEL["close"], timeout=5)
        if btn is not None:
            h.click(btn, enabled=False, timeout=8, what="Fechar")
        else:
            page.keyboard.press("Escape")
        conf = find(_dialog(page), SEL["discard"], timeout=6)
        if conf is not None:
            h.click(conf, what="Descartar")
        end = time.time() + 10
        while time.time() < end:
            if find(_dialog(page), SEL["share"] + SEL["next"] + SEL["discard"], timeout=0) is None and not page.locator(f"{DIALOG} video").count():
                return True
            h._wait(0.5)
    except NeedsUserAction:
        raise
    except Exception as e:
        log.info("descartar: %s", e)
    return False


def upload(page: Any, clip: RenderedClip, cfg: Any, dry_run: bool = False, *,
           text: tuple[str, str] | None = None, on_event: Callable[[str], None] | None = None) -> PostResult:
    """Envia um corte como reel. Nunca levanta excecao: devolve PostResult (ok=False + erro em pt-BR)."""
    emit_raw = on_event or (lambda m: log.info(m))

    def emit(m: str) -> None:  # nunca emoji no terminal/log
        emit_raw(strip_emojis(m))
    clip_id = clip.plan.id
    res = PostResult(clip_id=clip_id, platform=PLATFORM, ok=False, ts=time.time(), dry_run=dry_run)
    h = human.Actor(page, cfg, PLATFORM, clip_id, emit, blockers=lambda: _check_blockers(page))
    try:
        res.url = _upload(h, clip, cfg, dry_run, text, emit)
        res.ok = True
        if not dry_run:
            guard.mark_publish_result(clip_id, PLATFORM, "confirmado", res.url)
    except UncertainPost as e:
        res.ok, res.url = True, e.url
        res.error = strip_emojis(f"INCERTO: {e}")
        res.screenshot = screenshot(page, PLATFORM, clip_id, "incerto")
        guard.mark_publish_result(clip_id, PLATFORM, "incerto", e.url)
        emit(f"[instagram] {res.error}")
    except NeedsUserAction as e:
        res.error = str(e)
        res.screenshot = screenshot(page, PLATFORM, clip_id, "acao")
        if res.error == AUTO_MSG:
            guard.pause_platform(PLATFORM, res.error, cfg, hours=WARN_HOURS)
    except Exception as e:
        log.exception("upload instagram falhou")
        res.error = strip_emojis(f"Falha no Instagram: {human._short(e)[:300]}")
        res.screenshot = screenshot(page, PLATFORM, clip_id)
        if dry_run:
            emit("[instagram] (teste) descartado depois da falha" if _discard(h) else
                 "[instagram] (teste) NÃO confirmei o descarte do envio")
    finally:
        h.finish("teste" if dry_run else ("ok" if res.ok else "erro"))
    res.ts = time.time()
    return res


def _upload(h: human.Actor, clip: RenderedClip, cfg: Any, dry_run: bool, text: tuple[str, str] | None,
            emit: Callable[[str], None]) -> str | None:
    from .youtube import attach_file

    page = h.page
    path = Path(clip.path_for(PLATFORM))
    if not path.is_file():
        raise RuntimeError(f"arquivo do corte não encontrado: {path}")
    if text is None:
        vt, ch = source_info(clip.plan)
        text = build_post_text(clip.plan, PLATFORM, cfg, video_title=vt, channel=ch)
    _, caption = text
    timeout_up = float(cfg.get("publicacao.timeout_upload_s", 900))
    want = handle(cfg)

    before: set[str] = set()
    if want and not dry_run:        # para achar o link do post novo depois
        before = {r["code"] for r in list_reels(page, want, wait_s=8)}
        h.blockers()
    h.warm_up(HOME_URL)
    _require_account(h, cfg)
    dismiss_popups(h)
    h.step("abrir a janela de nova publicação", lambda: _open_create(h))
    how = h.step("escolher o arquivo do vídeo", lambda: attach_file(h, SEL["select"], SEL["file_input"], path), retry=False)
    emit(f"[instagram] arquivo escolhido ({how}): {path.name}")
    h.step("esperar a tela de recorte", lambda: _wait_editor(h, min(timeout_up, 180)), retry=False)
    h.step("recorte 9:16", lambda: _set_crop(h), verify=lambda: _is_vertical(page))
    h.step("escrever a legenda", lambda: _type_caption(h, caption), verify=lambda: _caption_ok(page, caption))
    if not _is_vertical(page):
        raise RuntimeError("o vídeo não está em pé (9:16) na tela final")
    btn = find(_dialog(page), SEL["share"], timeout=15)
    if btn is None:
        raise RuntimeError("botão Partilhar não encontrado")

    if dry_run:
        h.screenshot("pronto")
        emit("[instagram] (teste) tudo pronto e botão Partilhar na tela. Não vou clicar; descartando.")
        emit("[instagram] (teste) envio descartado (nada salvo)" if _discard(h) else
             "[instagram] (teste) não confirmei o descarte; fechei a página (o Instagram não publica sem o clique)")
        return None

    h.blockers()
    clicked = {"v": False}

    def press() -> None:
        assert not dry_run
        guard.mark_publish_click(clip.plan.id, PLATFORM)
        clicked["v"] = True

    try:
        h.step("clicar em Partilhar", lambda: h.click(btn, what="botão Partilhar", on_press=press), retry=False)
        h.step("esperar a confirmação do Instagram", lambda: _wait_posted(h, min(timeout_up, 420)), retry=False)
    except NeedsUserAction as e:
        if clicked["v"]:
            guard.pause_platform(PLATFORM, str(e), cfg, hours=WARN_HOURS if str(e) == AUTO_MSG else None)
            raise UncertainPost("cliquei em Partilhar e depois o Instagram pediu ação; NÃO vou reenviar. Confira no perfil se o reel saiu.")
        raise
    except Exception as e:
        if clicked["v"]:
            url = _posted_url(h, want, before)      # sem a confirmacao, o perfil ainda pode provar que saiu
            if url:
                emit("[instagram] não vi a confirmação, mas o reel está no perfil")
                return url
            raise UncertainPost(f"cliquei em Partilhar mas não vi a confirmação ({human._short(e)}). NÃO vou reenviar este corte; "
                                f"confira no perfil do Instagram.")
        raise
    emit("[instagram] publicado, buscando o link...")
    url = _posted_url(h, want, before)
    if not url:
        emit("[instagram] publicado, mas não consegui ler o link (veja no perfil)")
    return url


# ------------------------------------------------------------------ selftest
def selftest_page(page: Any, cfg: Any) -> dict:
    """Abre o Instagram, confere login, conta certa e a janela de nova publicacao. Nao envia nada."""
    checks: dict[str, bool] = {}
    erro = None
    h = human.Actor(page, cfg, PLATFORM, "selftest", blockers=lambda: _check_blockers(page))
    try:
        try:
            h.warm_up(HOME_URL)
        except NeedsUserAction as e:
            checks["Logado (sem tela de login)"] = not is_login_wall(page)
            return {"ok": False, "erro": str(e), "checks": checks}
        checks["Logado (sem tela de login)"] = True
        checks["Conta certa"] = own_account(page, handle(cfg)) is not False
        dismiss_popups(h)
        _open_create(h)
        checks["Janela de nova publicação"] = True
        checks["Campo de arquivo"] = find(page, SEL["file_input"], timeout=10, state="attached") is not None
    except NeedsUserAction as e:
        erro = str(e)
    except Exception as e:
        erro = f"Falha ao abrir o Instagram: {human._short(e)}"
    finally:
        h.finish("selftest")
    ok = erro is None and all(checks.values())
    if not ok and erro is None:
        erro = "alguns elementos não foram encontrados (veja o print em logs/screenshots)"
    return {"ok": ok, "erro": erro, "checks": checks, "info": {}, "ritmo": h.t.resumo()}
