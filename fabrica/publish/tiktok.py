"""Upload pelo TikTok Studio (www.tiktok.com/tiktokstudio) no navegador, sem API, com ritmo humano.

Fluxo: TikTok Studio (inicio, 5-20 s olhando) -> botao Carregar da barra lateral -> Selecionar video
(seletor de arquivo interceptado) -> fecha avisos -> legenda (Draft.js; hashtags escolhidas no popover)
-> "Quem pode assistir" -> espera o botao Publicar habilitar -> Publicar -> "Publicar agora?" (no maximo
uma vez) -> confirmacao (tiktokstudio/content) -> link do video.
dry_run: escolhe "Somente voce", faz tudo menos o clique em Publicar e descarta o envio.
Seletores com alternativas (data-e2e/data-tt/classes + texto pt-BR/ingles): docs/PUBLICACAO.md.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable

from ..log import get as get_log
from ..models import CaptchaAppeared, NeedsUserAction, PostResult, RenderedClip
from . import guard, human
from .browser import exists, find, locator_for, page_text, screenshot
from .captions import build_post_text, source_info, split_caption, strip_emojis

log = get_log(__name__)

PLATFORM = "tiktok"
UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?from=webapp"
CONTENT_URL = "https://www.tiktok.com/tiktokstudio/content"
HOME_URL = "https://www.tiktok.com/tiktokstudio"

SEL: dict[str, list] = {
    "iframe": ['iframe[data-tt="Upload_index_iframe"]'],
    "upload_entry": ['button[data-tt="Sidebar_UploadEntrance_WideButton"]', 'button[data-tt="Sidebar_UploadEntrance_Button"]',
                     '[data-tt="Sidebar_UploadEntrance_Container"] button', 'a[href*="tiktokstudio/upload"]'],
    "file_input": ['input[type="file"][accept*="video"]', 'input[type="file"]'],
    "select_video": [("role", "button", r"(select (a )?video|select file|selecionar (o )?v[ií]deo|selecionar arquivo)"),
                     'button[aria-label="Select file"]', 'button[aria-label="Selecionar arquivo"]',
                     '[data-e2e="select_video_button"]', ".upload-text-container"],
    "caption": ['div.public-DraftEditor-content[contenteditable="true"]',
                '.DraftEditor-root [contenteditable="true"]',
                'div[role="combobox"][contenteditable="true"]',
                '[data-e2e="caption_container"] [contenteditable="true"]',
                'div[contenteditable="true"]'],
    "hashtag_popover": ['div[class*="mention-list-popover"]', 'div[class*="hashtag-suggestion"]',
                        'div[class*="HashtagSuggestion"]', '[data-e2e*="hashtag"][role="listbox"]'],
    "hashtag_item": ['span.hash-tag-topic', '[class*="hash-tag-topic"]', '[class*="hashtag-topic"]',
                     '[role="option"]'],
    "post": ['button[data-e2e="post_video_button"]',
             ("role", "button", r"^\s*(post|publicar)\s*$"),
             'div.button-group button:has-text("Post")', 'div.button-group button:has-text("Publicar")'],
    "discard": ['button[data-e2e="discard_video_button"]', ("role", "button", r"^\s*(discard|descartar)\s*$")],
    "discard_confirm": [".TUXModal button.TUXButton--primary", '.common-modal-footer button[data-type="primary"]',
                        ("role", "button", r"^\s*(discard|descartar)\s*$")],
    "post_now": ['.TUXModal.common-modal-confirm-modal button.TUXButton--primary',
                 ("role", "button", r"^\s*(post now|publicar agora)\s*$"),
                 'button:has-text("Post now")', 'button:has-text("Publicar agora")'],
    "visibility_combo": ['[data-e2e="video_visibility_container"] button[role="combobox"]',
                         '[data-e2e="video_visibility_container"] [role="combobox"]',
                         'div[class*="view-auth-container"] button',
                         'div[class*="view-auth-container"] [role="combobox"]',
                         ("role", "combobox", r"(who can watch|quem pode (assistir|ver))"),
                         "div.tiktok-select-selector"],
    "show_more": [("role", "button", r"^\s*(show more|mostrar mais|ver mais)\s*$"),
                  ("text", r"^\s*(show more|mostrar mais|ver mais)\s*$")],
    "uploaded": [("text", r"^\s*(uploaded|carregado|enviado)\b")],
    "content_status": ['div[class*="status-result"][data-show="true"]'],
    "captcha": ['.captcha-verify-container', '#captcha-verify-image', '.captcha_verify_container',
                '.secsdk-captcha-drag-icon', '.captcha_verify_slide--slidebar', '#captcha_refresh_button',
                '.verify-captcha-submit-button', '#tiktok-verify-ele', 'div[class*="captcha_verify"]',
                ("text", r"(drag the slider|arraste o controle|verify to continue|verifique para continuar|"
                         r"select \d+ objects|selecione \d+ objetos)")],
    "login_modal": ['[data-e2e="login-modal"]', '#login-modal', '#loginContainer',
                    ("role", "dialog", r"(log in|entrar|fa[cç]a login)")],
    "post_table_link": ['div[data-tt="components_PostTable_Container"] div[data-tt="components_PostInfoCell_Container"] a',
                        'div[data-tt="components_PostTable_Container"] a[href*="/video/"]',
                        'a[href*="/video/"]'],
}

# botoes de avisos/tutoriais que podemos fechar sem mudar nada da conta
POPUP_BUTTONS = [
    '//div[@data-floating-ui-portal]//button[normalize-space(.)="Got it"]',
    '//div[@data-floating-ui-portal]//button[normalize-space(.)="Entendi"]',
    ("role", "button", r"^\s*(got it|entendi|entendido|percebi|not now|agora n[aã]o|skip|pular|fechar tutorial)\s*$"),
    '.react-joyride__tooltip button[data-action="primary"]',  # tour "Entendido/Seguinte": so avanca o tutorial
    "//button[./div[text()='Not now']]",
    '.react-joyride__tooltip button[data-action="skip"]',
    '.react-joyride__tooltip button[data-action="close"]',
]
# "Ativar verificacoes automaticas de conteudo?" -> Cancelar (nao alteramos configuracoes da conta)
CONTENT_CHECK_MODAL_RE = re.compile(r"(automatic content check|verifica[cç](ões|oes|ão|ao) autom[aá]tica|"
                                    r"turn on automatic|ativar verifica)", re.I)
COOKIE_DECLINE = [("role", "button", r"(decline optional cookies|recusar cookies opcionais|recusar opcionais)")]

SUCCESS_RE = re.compile(r"(your video (has been|was) (uploaded|posted|published)|video published|"
                        r"v[ií]deo( foi)? (publicado|carregado|enviado)( com (êxito|sucesso))?|"
                        r"seu v[ií]deo foi (publicado|carregado|enviado)|leaving the page does not interrupt|"
                        r"sair da p[aá]gina n[aã]o interromp)", re.I)
ERROR_RE = re.compile(r"(something went wrong|algo deu errado|algo correu mal|upload failed|falha no (upload|carregamento|envio)|"
                      r"couldn.?t (upload|post)|n[aã]o foi poss[ií]vel (carregar|enviar|publicar))", re.I)
# so procurado em avisos (toast/alerta/modal): o status da verificacao de conteudo tambem fala em "amanha"
RATE_RE = re.compile(r"(too fast|muito r[aá]pido|demasiad[oa] (r[aá]pido|frequente)|too many|muitas (tentativas|solicita)|try again later|"
                     r"tente novamente mais tarde|limit reached|limite atingido|daily limit|limite di[aá]rio|"
                     r"posting limit|limite de publica)", re.I)
NOTICE_SELECTORS = ['[role="alert"]', '[class*="Toast"]', '[class*="toast"]', ".TUXModal", '[role="dialog"]']
VIDEO_ID_RE = re.compile(r"/video/(\d{8,})")

VISIBILITY = {
    "everyone": r"^\s*(everyone|todos|todo mundo|p[uú]blico)\s*$",
    "friends": r"^\s*(friends|amigos|seguidores que voc[eê] segue de volta)\s*$",
    "followers": r"^\s*(followers|seguidores)\s*$",
    "only_me": r"^\s*(only you|only me|somente voc[eê]|s[oó] voc[eê]|apenas voc[eê]|somente eu|s[oó] eu|"
               r"s[oó] tu|apenas tu|somente tu|privado)\s*$",
}
_VIS_ALIASES = {"public": "everyone", "todos": "everyone", "publico": "everyone", "amigos": "friends",
                "private": "only_me", "privado": "only_me", "somente_eu": "only_me", "so_eu": "only_me",
                "seguidores": "followers"}

LOGIN_MSG = ("ACAO_NECESSARIA: faça login no TikTok no navegador da Fábrica "
             "(menu > Contas, ou: cortex login tiktok).")
CAPTCHA_MSG = ("ACAO_NECESSARIA: o TikTok mostrou um captcha/verificação. A Fábrica não resolve captcha e não "
               "tenta de novo sozinha: o TikTok fica pausado (24 h ou até você refazer o login). Rode "
               "'cortex login tiktok', resolva você mesmo na janela e feche (se repetir, publique menos por dia).")


class UncertainPost(Exception):
    """Cliquei em Publicar, mas nao vi a confirmacao: NAO reenviar (pode ter saido)."""

    def __init__(self, msg: str, url: str | None = None):
        super().__init__(msg)
        self.url = url


# ---------------------------------------------------------------- verificacoes
def is_login_wall(page: Any) -> bool:
    url = page.url or ""
    if re.search(r"tiktok\.com/(login|signup)", url):
        return True
    return exists(page, SEL["login_modal"])


def _check_blockers(page: Any) -> None:
    if is_login_wall(page):
        raise NeedsUserAction(LOGIN_MSG)
    if exists(page, SEL["captcha"]):
        raise CaptchaAppeared(CAPTCHA_MSG)


def _root(page: Any) -> Any:
    """A pagina antiga colocava o formulario num iframe; a atual (2026) nao."""
    if page.locator(SEL["iframe"][0]).count():
        return page.frame_locator(SEL["iframe"][0])
    return page


def dismiss_popups(h: human.Actor, rounds: int = 2) -> int:
    """Fecha tutoriais/avisos (Entendi, Agora nao...) e recusa cookies opcionais. Devolve quantos fechou."""
    page = h.page
    n = 0
    for _ in range(rounds):
        clicked = False
        for cand in COOKIE_DECLINE + POPUP_BUTTONS:
            el = find(page, [cand], timeout=0)
            if el is not None:
                try:
                    h.sleep(0.6, 1.6)  # "le" o aviso antes de fechar
                    h.click(el, timeout=8, what="fechar aviso")
                    n += 1
                    clicked = True
                except NeedsUserAction:
                    raise
                except Exception:
                    pass
        # modal "ativar verificacoes automaticas?" -> Cancelar
        for modal_sel in (".TUXModal", '[role="dialog"]'):
            try:
                modals = page.locator(modal_sel)
                for i in range(min(modals.count(), 3)):
                    m = modals.nth(i)
                    if m.is_visible() and CONTENT_CHECK_MODAL_RE.search(m.inner_text(timeout=2000) or ""):
                        btn = find(m, ['.common-modal-footer button[data-type="neutral"]',
                                       ("role", "button", r"^\s*(cancel|cancelar|not now|agora n[aã]o)\s*$")], timeout=1)
                        if btn is not None:
                            h.sleep(0.8, 2.0)
                            h.click(btn, timeout=8, what="Cancelar")
                            n += 1
                            clicked = True
            except NeedsUserAction:
                raise
            except Exception:
                pass
        if not clicked:
            break
    return n


# ------------------------------------------------------------------ legenda
def _caption_ok(root: Any, caption: str) -> bool:
    box = find(root, SEL["caption"], timeout=2)
    if box is None:
        return False
    text, _ = split_caption(caption)
    got = re.sub(r"\s+", " ", box.inner_text() or "")
    first = re.sub(r"\s+", " ", (text or caption))[:20].strip()
    return bool(first) and first[:12] in got


def _type_caption(h: human.Actor, root: Any, caption: str, emit: Callable[[str], None]) -> None:
    page = h.page
    box = find(root, SEL["caption"], timeout=60)
    if box is None:
        raise RuntimeError("campo de legenda não encontrado")
    text, tags = split_caption(caption)
    h.click(box, enabled=False, what="campo de legenda")
    h.select_all_and_delete()
    if text:
        if len(text) <= h.r.digitar_ate:
            h.type_text(text)
        else:
            h.paste_text(text)
    if tags:
        page.keyboard.press("Enter")
        h.sleep(0.2, 0.5)
    picked = 0
    for tag in tags:
        h.type_text(tag)  # hashtag digitada: o TikTok abre as sugestoes
        if _pick_hashtag(h, root, tag):
            picked += 1
        else:
            page.keyboard.type(" ")
        h.sleep(0.3, 0.8)
    if not _caption_ok(root, caption):
        got = re.sub(r"\s+", " ", box.inner_text() or "")
        raise RuntimeError(f"a legenda não ficou certa no editor (ficou: {got[:60]!r})")
    if tags:
        emit(f"[tiktok] legenda escrita ({picked}/{len(tags)} hashtags escolhidas na sugestão)")


def _pick_hashtag(h: human.Actor, root: Any, tag: str, timeout: float = 4.0) -> bool:
    """Clica na sugestao IGUAL a hashtag digitada (Enter agora quebra linha em vez de escolher)."""
    pop = find(root, SEL["hashtag_popover"], timeout=timeout)
    if pop is None:
        return False
    want = tag.lower()
    end = time.time() + 2.5
    while time.time() < end:
        for cand in SEL["hashtag_item"]:
            try:
                items = locator_for(pop, cand)
                for i in range(min(items.count(), 10)):
                    it = items.nth(i)
                    t = (it.inner_text(timeout=1000) or "").strip().split("\n")[0].strip().lower()
                    if t == want:
                        h.sleep(0.3, 0.9)  # le a lista de sugestoes
                        h.click(it, timeout=8, enabled=False, what=f"sugestão {tag}")
                        return True
            except NeedsUserAction:
                raise
            except Exception:
                continue
        h._wait(0.3)
    return False


# --------------------------------------------------------------- opcoes
def _notices(page: Any) -> str:
    out = []
    for sel in NOTICE_SELECTORS:
        try:
            loc = page.locator(sel)
            for i in range(min(loc.count(), 5)):
                el = loc.nth(i)
                if el.is_visible():
                    out.append(el.inner_text(timeout=1500) or "")
        except Exception:
            continue
    return " | ".join(out)[:6000]


def _visibility_now(root: Any) -> str | None:
    combo = find(root, SEL["visibility_combo"], timeout=2)
    if combo is None:
        return None
    return (combo.inner_text() or "").strip().split("\n")[0]


def _set_visibility(h: human.Actor, root: Any, wanted: str, emit: Callable[[str], None]) -> None:
    page = h.page
    rx = re.compile(VISIBILITY[wanted], re.I)
    combo = find(root, SEL["visibility_combo"], timeout=10)
    if combo is None:
        if wanted == "everyone":
            emit("[tiktok] aviso: não achei 'Quem pode assistir'; mantendo o padrão do TikTok (Todos)")
            return
        raise RuntimeError("não achei o seletor 'Quem pode assistir' (não vou publicar com privacidade errada)")
    current = (combo.inner_text() or "").strip()
    if rx.search(current.split("\n")[0]):
        return
    h.click(combo, enabled=False, what="'Quem pode assistir'")
    find(page, ['[role="option"]', 'div[class*="select-option"]'], timeout=5)
    target = None
    for cand in [("role", "option", VISIBILITY[wanted]), 'div[role="option"]', 'div[class*="select-option"]',
                 'li[role="option"]']:
        try:
            loc = locator_for(page, cand)
            for i in range(min(loc.count(), 10)):
                el = loc.nth(i)
                if el.is_visible() and rx.search((el.inner_text() or "").strip().split("\n")[0]):
                    target = el
                    break
        except Exception:
            continue
        if target is not None:
            break
    if target is None:
        page.keyboard.press("Escape")
        raise RuntimeError(f"opção de privacidade '{wanted}' não encontrada")
    h.click(target, enabled=False, what=f"opção '{wanted}'")
    h.sleep(0.5, 1.0)
    now = (combo.inner_text() or "").strip().split("\n")[0]
    if not rx.search(now):
        raise RuntimeError(f"a privacidade não mudou para '{wanted}' (está: {now!r})")


def _toggle_inputs(root: Any, label_rx: str) -> list:
    out = []
    try:
        lab = locator_for(root, ("label", label_rx))
        if lab.count():
            out.append(lab.first)
    except Exception:
        pass
    try:  # <label>Comment</label><div>...<input type=checkbox></div>
        txt = locator_for(root, ("text", label_rx))
        for i in range(min(txt.count(), 4)):
            t = txt.nth(i)
            for rel in ("xpath=following-sibling::div//input", "xpath=following-sibling::*//input",
                        "xpath=..//input[@type='checkbox' or @role='switch']",
                        "xpath=../..//input[@type='checkbox' or @role='switch']"):
                inp = t.locator(rel)
                if inp.count():
                    out.append(inp.first)
                    break
    except Exception:
        pass
    return out


def _set_toggle(h: human.Actor, root: Any, label_rx: str, want: bool) -> bool | None:
    """Liga/desliga uma opcao (Comentarios, Reutilizacao de conteudo...). None = nao encontrada.
    Clica no interruptor visivel (o input costuma ser invisivel), uma vez so."""
    for el in _toggle_inputs(root, label_rx):
        try:
            if el.is_checked() != want:
                target = el if el.is_visible() else el.locator("xpath=..")
                h.click(target, enabled=False, what="interruptor")
                h.sleep(0.4, 0.9)
            return el.is_checked() == want
        except NeedsUserAction:
            raise
        except Exception:
            continue
    return None


def _apply_interaction_settings(h: human.Actor, root: Any, cfg: Any, emit: Callable[[str], None]) -> None:
    comments = cfg.get("publicacao.tiktok_permitir_comentarios", None)
    reuse = cfg.get("publicacao.tiktok_permitir_reuso", None)
    if comments is None and reuse is None:
        return  # mantem o padrao da conta
    more = find(root, SEL["show_more"], timeout=2)
    if more is not None:
        try:
            h.click(more, enabled=False, what="'Mostrar mais'")
        except NeedsUserAction:
            raise
        except Exception:
            pass
    if comments is not None:
        r = _set_toggle(h, root, r"^(comment|comments|coment[aá]rio|coment[aá]rios)$", bool(comments))
        if not r:
            emit("[tiktok] aviso: não consegui ajustar 'Comentários'")
    if reuse is not None:
        ok = False
        for rx in (r"^(reuse of content|reutiliza[cç][aã]o de conte[uú]do)$", r"^(duet|dueto)$", r"^(stitch|costura)$"):
            ok = bool(_set_toggle(h, root, rx, bool(reuse))) or ok
        if not ok:
            emit("[tiktok] aviso: não consegui ajustar 'Dueto/Costura'")


# ------------------------------------------------------------ envio/publicacao
def _post_button(root: Any, timeout: float = 5) -> Any | None:
    return find(root, SEL["post"], timeout=timeout)


def _enabled(btn: Any) -> bool:
    try:
        if (btn.get_attribute("data-disabled") or "").lower() == "true":
            return False
        if (btn.get_attribute("aria-disabled") or "").lower() == "true":
            return False
        if (btn.get_attribute("data-loading") or "").lower() == "true":
            return False
        return btn.is_enabled()
    except Exception:
        return False


def _wait_ready(h: human.Actor, root: Any, timeout: float, emit: Callable[[str], None]) -> Any:
    """Espera o upload terminar: botao Publicar habilitado. So le a pagina (e fecha avisos que surgirem)."""
    page = h.page
    end = time.time() + timeout
    last = 0.0
    while time.time() < end:
        if h.blockers():  # o dono resolveu um CAPTCHA: recomeca a contagem
            end = time.time() + timeout
        avisos = _notices(page)
        if ERROR_RE.search(avisos):
            raise RuntimeError(f"o TikTok recusou o vídeo: {ERROR_RE.search(avisos).group(0)}")
        btn = _post_button(root, timeout=1)
        if btn is not None and _enabled(btn):
            return btn
        if time.time() - last > 25:
            emit("[tiktok] enviando o vídeo...")
            last = time.time()
        dismiss_popups(h, rounds=1)
        h._wait(2)
    raise RuntimeError(f"o botão Publicar não habilitou em {int(timeout)} s (upload travado?)")


def _content_check_note(root: Any) -> str | None:
    el = find(root, SEL["content_status"], timeout=0)
    if el is None:
        return None
    try:
        cls = el.get_attribute("class") or ""
        txt = (el.inner_text() or "").strip().replace("\n", " ")
        if "status-warn" in cls or "status-error" in cls:
            return f"verificação de conteúdo: {txt[:120]}"
        if "status-limit" in cls:
            return f"verificação de conteúdo indisponível: {txt[:120]}"
    except Exception:
        pass
    return None


def _wait_posted(h: human.Actor, root: Any, timeout: float = 150, human_posts: bool = False,
                 emit: Callable[[str], None] | None = None) -> None:
    """Espera a confirmacao do post.

    human_posts=True (modo semi): quem clica em Publicar/"Publicar agora" e o HUMANO; a Fabrica so observa.
    Se aparecer captcha nesse modo, o humano esta na frente da tela: avisamos e seguimos esperando
    (sem tocar no captcha). No modo auto, "Publicar agora" e clicado no maximo UMA vez.
    """
    page = h.page
    end = time.time() + timeout
    warned_captcha = False
    post_now_clicked = False
    while time.time() < end:
        if "tiktokstudio/content" in (page.url or ""):
            return
        if human_posts:
            if is_login_wall(page):
                raise NeedsUserAction(LOGIN_MSG)
            if exists(page, SEL["captcha"]):
                if not warned_captcha and emit:
                    emit("[tiktok] apareceu um captcha/verificação: resolva você mesmo na janela; sigo esperando.")
                warned_captcha = True
                h._wait(2)
                continue
            if _post_button(root, timeout=0) is None and exists(root, SEL["select_video"]):
                raise RuntimeError("o envio foi descartado na janela (modo semi); nada foi publicado")
        else:
            if h.blockers():  # o dono resolveu um CAPTCHA: recomeca a contagem
                end = time.time() + timeout
            pn = find(page, SEL["post_now"], timeout=0)
            if pn is not None and not post_now_clicked:
                # "Continuar publicando?" -> Publicar agora (parte do mesmo Publicar; uma vez so)
                post_now_clicked = True
                h.think()
                h.click(pn, what="'Publicar agora'")
                continue
        notes = _notices(page)
        own = getattr(h, "own_text", "")     # o texto do nosso post nao vale como confirmacao
        if SUCCESS_RE.search(notes) or (not SUCCESS_RE.search(own) and SUCCESS_RE.search(page_text(page, "body", 8000))):
            return
        if RATE_RE.search(notes):
            raise NeedsUserAction("LIMITE_DIARIO: o TikTok pediu para ir mais devagar (\"" +
                                  RATE_RE.search(notes).group(0) + "\"). Pausei o TikTok; "
                                  "diminua publicacao.max_posts_por_dia.tiktok.")
        if ERROR_RE.search(notes):
            raise RuntimeError(f"o TikTok não publicou: {ERROR_RE.search(notes).group(0)}")
        h._wait(1.5)
    if human_posts:
        raise NeedsUserAction(f"ACAO_NECESSARIA: modo semi do TikTok: ninguém clicou em Publicar em "
                              f"{int(timeout // 60)} min, então o vídeo NÃO foi publicado. Pausei o TikTok neste lote; "
                              f"rode de novo quando estiver na frente do PC (ou use publicacao.tiktok_modo: auto).")
    raise RuntimeError("cliquei em Publicar mas não vi a confirmação do TikTok")


def _posted_url(h: human.Actor, caption_title: str) -> str | None:
    """Melhor esforco: le o link do post mais recente em tiktokstudio/content."""
    page = h.page
    try:
        if "tiktokstudio/content" not in (page.url or ""):
            h.goto(CONTENT_URL)
        find(page, ['div[data-tt="components_PostTable_Container"]'], timeout=30, state="attached")
        snippet = re.sub(r"[^\w ]", "", caption_title or "", flags=re.UNICODE).strip()[:15].lower()
        end = time.time() + 30
        strict_until = time.time() + 15  # depois disso aceita o link mais recente mesmo sem conferir o texto
        while time.time() < end:
            for cand in SEL["post_table_link"]:
                loc = page.locator(cand)
                for i in range(min(loc.count(), 5)):
                    href = loc.nth(i).get_attribute("href") or ""
                    m = VIDEO_ID_RE.search(href)
                    if not m:
                        continue
                    if snippet and time.time() < strict_until:  # confere se a linha e a do nosso post
                        try:
                            row_txt = loc.nth(i).locator("xpath=ancestor::*[contains(@data-tt,'Row') or "
                                                         "contains(@data-tt,'PostInfoCell')][1]").inner_text(timeout=2000)
                            if snippet not in re.sub(r"[^\w ]", "", row_txt, flags=re.UNICODE).lower():
                                continue
                        except Exception:
                            pass
                    return href if href.startswith("http") else "https://www.tiktok.com" + href
            h._wait(2)
    except Exception as e:
        log.debug("link do tiktok: %s", e)
    return None


def _discard(h: human.Actor, root: Any) -> bool:
    """Modo teste: descarta o envio (nada fica salvo como rascunho). Devolve True se o descarte foi confirmado."""
    page = h.page
    ok = False
    try:
        dismiss_popups(h, rounds=3)  # o tour/aviso pode cobrir o botao Descartar
        btn = find(root, SEL["discard"], timeout=5)
        if btn is not None:
            h.click(btn, enabled=False, what="Descartar")
            conf = find(page, SEL["discard_confirm"], timeout=6)
            if conf is not None:
                h.sleep(0.5, 1.2)
                h.click(conf, what="confirmar Descartar")
            end = time.time() + 15
            while time.time() < end:
                if exists(root, SEL["select_video"]) and _post_button(root, timeout=0) is None:
                    ok = True
                    break
                h._wait(0.5)
    except NeedsUserAction:
        raise
    except Exception as e:
        log.info("descartar: %s", e)
    try:
        page.goto("about:blank")  # o aviso "sair da pagina?" e aceito automaticamente
    except Exception:
        pass
    return ok


# ------------------------------------------------------------------- upload
def upload(page: Any, clip: RenderedClip, cfg: Any, dry_run: bool = False, *,
           text: tuple[str, str] | None = None, on_event: Callable[[str], None] | None = None) -> PostResult:
    """Envia um corte ao TikTok. Nunca levanta excecao: devolve PostResult (ok=False + erro em pt-BR).

    Se o clique em Publicar aconteceu mas a confirmacao nao veio, devolve ok=True com erro "INCERTO: ..."
    para o corte NUNCA ser reenviado."""
    emit_raw = on_event or (lambda m: log.info(m))

    def emit(m: str) -> None:  # nunca emoji no terminal/log
        emit_raw(strip_emojis(m))
    clip_id = clip.plan.id
    res = PostResult(clip_id=clip_id, platform=PLATFORM, ok=False, ts=time.time(), dry_run=dry_run)
    h = human.Actor(page, cfg, PLATFORM, clip_id, emit, blockers=lambda: _check_blockers(page))
    h.own_text = " ".join(text or ())
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
        emit(f"[tiktok] {res.error}")
    except NeedsUserAction as e:
        res.error = str(e)
        res.screenshot = screenshot(page, PLATFORM, clip_id, "acao")
    except Exception as e:
        log.exception("upload tiktok falhou")
        msg = human._short(e)
        res.error = strip_emojis(f"Falha no TikTok: {msg[:300]}")
        res.screenshot = screenshot(page, PLATFORM, clip_id)
        if dry_run:  # teste que falhou no meio: tenta descartar o envio e diz se conseguiu confirmar
            try:
                ok = _discard(h, _root(page))
            except Exception as e2:
                ok = False
                log.info("descartar depois da falha: %s", e2)
            emit("[tiktok] (teste) envio descartado depois da falha" if ok else
                 "[tiktok] (teste) NÃO confirmei o descarte do envio; confira em tiktok.com/tiktokstudio/content")
    finally:
        h.finish("teste" if dry_run else ("ok" if res.ok else "erro"))
    res.ts = time.time()
    return res


def tiktok_mode(cfg: Any) -> str:
    """auto = a Fabrica clica em Publicar | semi = preenche tudo e o HUMANO clica em Publicar."""
    m = str(cfg.get("publicacao.tiktok_modo", "auto") or "auto").lower().strip()
    return "semi" if m in ("semi", "semiautomatico", "semi-automatico", "manual") else "auto"


def _visibility(cfg: Any) -> str:
    v = str(cfg.get("publicacao.tiktok_visibilidade", "everyone") or "everyone").lower().strip()
    v = _VIS_ALIASES.get(v, v)
    return v if v in VISIBILITY else "everyone"


def _upload_page_ready(page: Any) -> bool:
    root = _root(page)
    return "tiktokstudio/upload" in (page.url or "") and find(root, SEL["file_input"], timeout=0,
                                                               state="attached") is not None


def _open_upload(h: human.Actor, cfg: Any) -> Any:
    """Abre a pagina de upload pelo botao Carregar da barra lateral (como uma pessoa); se nao achar, vai
    direto para a URL. Devolve o root (pagina ou iframe antigo)."""
    page = h.page
    h.blockers()
    if "tiktokstudio" in (page.url or "") and "tiktokstudio/upload" not in (page.url or ""):
        btn = find(page, SEL["upload_entry"], timeout=10)
        if btn is not None:
            h.click(btn, enabled=False, what="botão Carregar")
            end = time.time() + 20
            while time.time() < end and not _upload_page_ready(page):
                h._wait(0.5)
    if not _upload_page_ready(page):
        url = UPLOAD_URL + ("&lang=en" if cfg.get("publicacao.tiktok_forcar_ingles", False) else "")
        log.info("tiktok: botao Carregar nao levou ao upload; indo direto para %s", url)
        h.goto(url)
    end = time.time() + 60
    while time.time() < end:
        h.blockers()
        root = _root(page)
        if find(root, SEL["file_input"], timeout=2, state="attached") is not None:
            sel = find(root, SEL["select_video"], timeout=3)
            if sel is not None:
                h.wait_ready(sel, what="botão 'Selecionar vídeo'")
            return root
        dismiss_popups(h, rounds=1)
    h.blockers()
    raise RuntimeError("a página de upload do TikTok não carregou (campo de arquivo não encontrado)")


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
    title, caption = text
    timeout_up = float(cfg.get("publicacao.timeout_upload_s", 900))

    secs = h.warm_up(HOME_URL)
    emit(f"[tiktok] TikTok Studio aberto; olhei o início por {secs:.0f} s")
    dismiss_popups(h, rounds=1)
    root = h.step("abrir a página de envio", lambda: _open_upload(h, cfg))
    h.think()
    how = h.step("escolher o arquivo do vídeo",
                 lambda: attach_file(h, SEL["select_video"], SEL["file_input"], path, root=root), retry=False)
    emit(f"[tiktok] arquivo escolhido ({how}): {path.name}")
    h.sleep(2.0, 4.0)
    dismiss_popups(h, rounds=4)  # tour de novidades costuma abrir depois do upload
    h.blockers()

    h.step("escrever a legenda", lambda: _type_caption(h, root, caption, emit), verify=lambda: _caption_ok(root, caption))
    h.pause()
    dismiss_popups(h, rounds=1)
    vis = "only_me" if dry_run else _visibility(cfg)  # teste: nunca "Todos"
    h.step(f"escolher quem pode assistir ({vis})", lambda: _set_visibility(h, root, vis, emit),
           verify=lambda: bool(re.search(VISIBILITY[vis], _visibility_now(root) or "", re.I)))
    emit(f"[tiktok] quem pode assistir: {vis}")
    _apply_interaction_settings(h, root, cfg, emit)

    btn = _wait_ready(h, root, timeout_up, emit)
    note = _content_check_note(root)
    if note:
        emit(f"[tiktok] {note}")
    dismiss_popups(h, rounds=1)

    if dry_run:
        h.think()
        emit("[tiktok] (teste) tudo pronto e botão Publicar habilitado. Não vou clicar; descartando o envio.")
        if _discard(h, root):
            emit("[tiktok] (teste) envio descartado (nada salvo no TikTok)")
        else:
            emit("[tiktok] (teste) não confirmei o descarte; fechei a página (o TikTok não publica sem o clique)")
        return None

    if tiktok_mode(cfg) == "semi":
        wait_s = float(cfg.get("publicacao.tiktok_espera_humano_s", 600))
        try:
            page.bring_to_front()
        except Exception:
            pass
        emit(f"[tiktok] MODO SEMI: está tudo preenchido. Confira a janela do navegador e clique em PUBLICAR "
             f"você mesmo (espero até {int(wait_s // 60)} min). A Fábrica não clica.")
        _wait_posted(h, root, timeout=wait_s, human_posts=True, emit=emit)
    else:
        h.think()
        h.blockers()
        clicked = {"v": False}

        def press() -> None:
            assert not dry_run
            guard.mark_publish_click(clip.plan.id, PLATFORM)
            clicked["v"] = True

        try:
            h.step("clicar em Publicar", lambda: h.click(btn, what="botão Publicar", on_press=press), retry=False)
            h.step("esperar a confirmação do TikTok", lambda: _wait_posted(h, root), retry=False)
        except NeedsUserAction as e:
            if clicked["v"]:
                guard.pause_platform(PLATFORM, str(e), cfg)
                raise UncertainPost("cliquei em Publicar e depois o TikTok pediu ação; NÃO vou reenviar. Confira "
                                    "em tiktok.com/tiktokstudio/content se o vídeo saiu.")
            raise
        except Exception as e:
            if clicked["v"]:
                raise UncertainPost(f"cliquei em Publicar mas não vi a confirmação ({human._short(e)}). NÃO vou "
                                    f"reenviar este corte; confira em tiktok.com/tiktokstudio/content.")
            raise
    emit("[tiktok] publicado, buscando o link...")
    h.sleep(2.0, 5.0)
    url = _posted_url(h, title)
    if not url:
        emit("[tiktok] publicado, mas não consegui ler o link (veja em tiktok.com/tiktokstudio/content)")
    return url


# ------------------------------------------------------------------ selftest
def selftest_page(page: Any, cfg: Any) -> dict:
    """Abre o TikTok Studio como uma pessoa (inicio -> Carregar) e confere a pagina de upload. Nao envia nada."""
    checks: dict[str, bool] = {}
    erro = None
    info: dict[str, str] = {}
    h = human.Actor(page, cfg, PLATFORM, "selftest", blockers=lambda: _check_blockers(page))
    try:
        try:
            secs = h.warm_up(HOME_URL)
            info["aquecimento"] = f"{secs:.1f} s no início do TikTok Studio"
        except NeedsUserAction as e:
            checks["Logado (sem tela de login)"] = not is_login_wall(page)
            checks["Sem captcha/verificação"] = not exists(page, SEL["captcha"])
            return {"ok": False, "erro": str(e), "checks": checks}
        checks["Logado (sem tela de login)"] = True
        checks["Sem captcha/verificação"] = True
        checks["Botão 'Carregar' na barra lateral"] = exists(page, SEL["upload_entry"])
        dismiss_popups(h)
        try:
            root = _open_upload(h, cfg)
        except NeedsUserAction as e:
            return {"ok": False, "erro": str(e), "checks": checks}
        info["caminho"] = "botão Carregar" if checks["Botão 'Carregar' na barra lateral"] else "URL direta"
        checks["Campo de arquivo (input file)"] = find(root, SEL["file_input"], timeout=30, state="attached") is not None
        checks["Botão 'Selecionar vídeo'"] = exists(root, SEL["select_video"])
    except Exception as e:
        erro = f"Falha ao abrir o TikTok Studio: {human._short(e)}"
    finally:
        h.finish("selftest")
    ok = erro is None and all(checks.values())
    if not ok and erro is None:
        erro = "alguns elementos não foram encontrados (veja a lista e o print em logs/screenshots)"
    return {"ok": ok, "erro": erro, "checks": checks, "info": info, "ritmo": h.t.resumo()}
