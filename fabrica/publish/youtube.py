"""Upload de Shorts pelo YouTube Studio (navegador, sem API), com ritmo humano (human.Actor).

Fluxo: Studio (painel, 5-20 s olhando) -> Criar > Carregar videos -> Selecionar ficheiros (seletor de
arquivo interceptado) -> titulo/descricao -> "nao e para criancas" -> Seguinte x N -> visibilidade ->
espera o envio chegar a 100% -> Publicar -> confirmacao.
dry_run: escolhe PRIVADO, NUNCA clica em Publicar/Guardar, fecha o dialogo e apaga o rascunho de teste.
Seletores com varias alternativas (ids do Polymer + texto en/pt-BR/pt-PT); lista em docs/PUBLICACAO.md.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable

from ..log import get as get_log
from ..models import CaptchaAppeared, NeedsUserAction, PostResult, RenderedClip
from . import guard, human
from .browser import exists, find, page_text, screenshot
from .captions import build_post_text, source_info, strip_emojis

log = get_log(__name__)

PLATFORM = "youtube"
UPLOAD_URL = "https://www.youtube.com/upload"
STUDIO_URL = "https://studio.youtube.com/"
HOME_URL = STUDIO_URL

D = "ytcp-uploads-dialog"
SEL: dict[str, list] = {
    # o host Polymer pode ter tamanho zero; o tp-yt-paper-dialog interno e o que fica visivel
    "upload_dialog": [f"{D} tp-yt-paper-dialog", D],
    "create_btn": ["ytcp-button#create-icon", "#create-icon", 'button[aria-label="Criar"]',
                   'button[aria-label="Create"]', ("role", "button", r"^\s*(criar|create)\s*$")],
    "create_upload_item": ['tp-yt-paper-item[test-id="upload"]', "#text-item-0",
                           ("role", "menuitem", r"(upload videos|enviar v[ií]deos|carregar v[ií]deos|fazer upload)")],
    "file_input": [f'{D} ytcp-uploads-file-picker input[type="file"]', 'ytcp-uploads-file-picker input[type="file"]',
                   'input[type="file"][name="Filedata"]', 'input[type="file"]'],
    "select_files": ["#select-files-button",
                     ("role", "button", r"^\s*(select files|selecionar arquivos|selecionar ficheiros)\s*$")],
    "title": [f"{D} #title-textarea #textbox", "#title-textarea #textbox",
              "ytcp-social-suggestions-textbox#title-textarea #textbox", "ytcp-video-title #textbox",
              "div#textbox[contenteditable='true'][aria-label*='title' i]",
              "div#textbox[contenteditable='true'][aria-label*='título' i]"],
    "description": [f"{D} #description-textarea #textbox", "#description-textarea #textbox",
                    "ytcp-video-description #textbox",
                    "div#textbox[contenteditable='true'][aria-label*='viewers' i]",
                    "div#textbox[contenteditable='true'][aria-label*='espectadores' i]"],
    "not_for_kids": ['tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]',
                     '[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]', '[name="NOT_MADE_FOR_KIDS"]',
                     ("role", "radio", r"(not made for kids|n[aã]o [eé] (conte[uú]do )?(feito )?para crian[cç]as)")],
    "show_more": [f"{D} #toggle-button", ("role", "button", r"^\s*(show more|mostrar mais)\s*$")],
    "altered_no": ['tp-yt-paper-radio-button[name="VIDEO_HAS_ALTERED_CONTENT_NO"]',
                   '[name="VIDEO_HAS_ALTERED_CONTENT_NO"]'],
    "next": [f"{D} #next-button", "#next-button",
             ("role", "button", r"^\s*(next|pr[oó]xim[oa]|avan[cç]ar|seguinte)\s*$")],
    "visibility": [f"{D} #privacy-radios", "#privacy-radios", "ytcp-video-visibility-select"],
    "vis_PUBLIC": [f'{D} tp-yt-paper-radio-button[name="PUBLIC"]', '#privacy-radios [name="PUBLIC"]',
                   ("role", "radio", r"^\s*(public|p[uú]blico)\b")],
    "vis_UNLISTED": [f'{D} tp-yt-paper-radio-button[name="UNLISTED"]', '#privacy-radios [name="UNLISTED"]',
                     ("role", "radio", r"^\s*(unlisted|n[aã]o listado)\b")],
    "vis_PRIVATE": [f'{D} tp-yt-paper-radio-button[name="PRIVATE"]', '#privacy-radios [name="PRIVATE"]',
                    ("role", "radio", r"^\s*(private|privado)\b")],
    "done": [f"{D} #done-button", "#done-button",
             ("role", "button", r"^\s*(publish|save|publicar|salvar|guardar)\s*$")],
    "close_dialog": ["#ytcp-uploads-dialog-close-button", f"{D} #close-button", f'{D} [aria-label="Save and close"]', f'{D} [aria-label="Salvar e fechar"]',
                     f'{D} [aria-label="Guardar e fechar"]', f'{D} ytcp-icon-button[aria-label*="close" i]',
                     f'{D} ytcp-icon-button[aria-label*="fechar" i]'],
    "video_link": [f"{D} ytcp-video-info a", "ytcp-video-info a", "a.ytcp-video-info", ".video-url-fadeable a",
                   'a[href^="https://youtu.be/"]', 'a[href*="youtube.com/shorts/"]'],
    "progress": [f"{D} ytcp-video-upload-progress", "ytcp-video-upload-progress"],
    "progress_label": [f"{D} ytcp-video-upload-progress span.progress-label", "span.progress-label"],
    "error_area": [f"{D} .error-short", f"{D} .error-area", f"{D} #error-message"],
    "share_dialog": ["ytcp-video-share-dialog tp-yt-paper-dialog", "ytcp-video-share-dialog",
                     "ytcp-uploads-still-processing-dialog tp-yt-paper-dialog", "ytcp-uploads-still-processing-dialog"],
    # botoes procurados DENTRO do dialogo de "publicado"/"ainda processando"
    "share_close": ["#close-button", "#close-icon-button", ("role", "button", r"^\s*(close|fechar)\s*$")],
    "prechecks": ["ytcp-prechecks-warning-dialog"],
    "create_channel": ["#create-channel-button", "ytd-channel-creation-dialog-renderer", "ytcp-create-channel-dialog",
                       ("role", "button", r"^\s*(create channel|criar canal)\s*$")],
    "hashtag_dropdown": ["tp-yt-iron-dropdown:visible"],
    "ad_none": [("role", "checkbox", r"(none of the above|nenhuma das op[cç][oõ]es)")],
    "ad_submit": [("role", "button", r"(submit rating|enviar classifica[cç][aã]o)")],
    "row_menu": ['ytcp-icon-button[aria-label="Opções"]', 'ytcp-icon-button[aria-label="Options"]', "#overflow-menu-button", "ytcp-icon-button#menu-button",
                 ("role", "button", r"^\s*(options|op[cç][oõ]es|mais a[cç][oõ]es|more actions)\s*$")],
    "delete_item": ['ytcp-text-menu tp-yt-paper-item[test-id="delete"]', ("role", "menuitem", r"(delete forever|(excluir|eliminar) (permanentemente|definitivamente))"),
                    ("role", "option", r"(delete forever|(excluir|eliminar) (permanentemente|definitivamente))"),
                    ("text", r"^\s*(delete forever|(excluir|eliminar) (permanentemente|definitivamente))\s*$")],
}

DAILY_LIMIT_RE = re.compile(r"(daily upload limit|limite di[aá]rio)", re.I)
VERIFY_RE = re.compile(r"(verify it.?s you|confirm it.?s you|confirme que [eé] voc[eê]|verifique que [eé] voc[eê]|"
                       r"confirme sua identidade|confirme a sua identidade)", re.I)
UPLOAD_FAIL_RE = re.compile(r"(upload failed|falha no (upload|envio|carregamento)|processing abandoned|"
                            r"processamento abandonado|invalid file|arquivo inv[aá]lido|ficheiro inv[aá]lido|"
                            r"n[aã]o foi poss[ií]vel (enviar|processar|carregar))", re.I)
UPLOADING_RE = re.compile(r"(upload(ing)?|enviando|a carregar|fazendo (o )?upload|carregando|carregamento)"
                          r"\D{0,25}\d{1,3}\s?%", re.I)
UPLOAD_DONE_RE = re.compile(r"(upload complete|upload conclu[ií]do|envio conclu[ií]do|carregamento conclu[ií]do|"
                            r"processing|processando|a processar|checks complete|verifica[cç][oõ]es conclu[ií]das|"
                            r"checking|verificando|a verificar)", re.I)
VIDEO_ID_RE = re.compile(r"(?:youtu\.be/|/shorts/|[?&]v=|/video/)([\w-]{11})")
CHANNEL_RE = re.compile(r"/channel/(UC[\w-]{20,})")

LOGIN_MSG = ("ACAO_NECESSARIA: faça login no YouTube no navegador da Fábrica "
             "(menu > Contas, ou: cortex login youtube).")

# "assinatura" do passo atual do assistente de upload (para saber se o Seguinte avancou)
_STEP_SIG_JS = """() => {
  const d = document.querySelector('ytcp-uploads-dialog');
  if (!d) return '';
  const vis = (s) => { const e = d.querySelector(s); return e && (e.offsetWidth || e.offsetHeight) ? '1' : '0'; };
  const badges = Array.from(d.querySelectorAll('[id^="step-badge-"], ytcp-stepper [role="tab"]')).map(b =>
     (b.getAttribute('state') || '') + (b.getAttribute('aria-selected') || '') + (b.className.includes('active') ? 'A' : '') +
     (b.hasAttribute('completed') ? 'C' : ''));
  return badges.join('|') + '#' + vis('#title-textarea') + vis('ytcp-video-elements, ytcp-uploads-video-elements') +
         vis('ytcp-uploads-checks, ytcp-uploads-review, ytcp-checks') + vis('#privacy-radios');
}"""


class UncertainPost(Exception):
    """Cliquei em Publicar, mas nao vi a confirmacao: NAO reenviar (pode ter saido)."""

    def __init__(self, msg: str, url: str | None = None):
        super().__init__(msg)
        self.url = url


# ---------------------------------------------------------------- verificacoes
def is_login_wall(page: Any) -> bool:
    url = page.url or ""
    if "accounts.google.com" in url or "/ServiceLogin" in url or "youtube.com/signin" in url:
        return True
    return False


def _check_blockers(page: Any, stage: str = "", own: str = "") -> None:
    """Levanta NeedsUserAction se aparecer login, verificacao, captcha, falta de canal ou limite diario."""
    url = page.url or ""
    if "accounts.google.com" in url:
        if re.search(r"/(challenge|speedbump|signin/v\d/challenge|v3/signin/challenge)", url):
            raise NeedsUserAction("ACAO_NECESSARIA: o Google pediu verificação da conta (\"Confirme que é você\"). "
                                  "Abra o login do YouTube na Fábrica, conclua a verificação e rode de novo.")
        raise NeedsUserAction(LOGIN_MSG)
    # desafio do reCAPTCHA (o selo invisivel "size=invisible" nao conta)
    if "google.com/sorry" in url or exists(page, ['iframe[src*="recaptcha"][src*="bframe"]',
                                                  'iframe[src*="recaptcha"][src*="anchor"]:not([src*="size=invisible"])']):
        raise CaptchaAppeared("ACAO_NECESSARIA: o YouTube mostrou um captcha. A Fábrica não resolve captcha: abra o "
                              "login do YouTube na Fábrica, resolva você mesmo e rode de novo mais tarde.")
    if exists(page, SEL["create_channel"]):
        raise NeedsUserAction("ACAO_NECESSARIA: sua conta Google ainda não tem canal no YouTube. Abra studio.youtube.com "
                              "no login da Fábrica, crie o canal e rode de novo.")
    # inner_text so devolve texto visivel (avisos escondidos no template nao contam)
    dialog_text = " ".join(page_text(page, s, 4000) for s in ("ytcp-uploads-dialog", "ytcp-confirmation-dialog")
                           if page.locator(s).count())
    confirm_text = page_text(page, "ytcp-confirmation-dialog", 2000) if page.locator("ytcp-confirmation-dialog").count() else ""
    if DAILY_LIMIT_RE.search(dialog_text) and not DAILY_LIMIT_RE.search(own):
        raise NeedsUserAction("LIMITE_DIARIO: o YouTube avisou que o limite diário de envios foi atingido. "
                              "Tente de novo em 24 h (e diminua publicacao.max_posts_por_dia.youtube).")
    if VERIFY_RE.search(confirm_text):
        raise NeedsUserAction("ACAO_NECESSARIA: o YouTube pediu para verificar a conta. Abra studio.youtube.com no "
                              "login da Fábrica (cortex login youtube), faça a verificação e rode de novo.")


def _channel_id(page: Any) -> str | None:
    m = CHANNEL_RE.search(page.url or "")
    return m.group(1) if m else None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _dialog_open(page: Any) -> bool:
    return exists(page, SEL["upload_dialog"]) or exists(page, SEL["select_files"])


# ---------------------------------------------------------- abrir e anexar
def _open_upload(h: human.Actor) -> None:
    """Abre a janela de upload pelo caminho de quem usa o Studio (Criar > Carregar videos).
    Se o menu nao aparecer, abre youtube.com/upload (mesmo dialogo). Nao clica duas vezes."""
    page = h.page
    h.blockers()
    if "studio.youtube.com" in (page.url or "") and not _dialog_open(page):
        btn = find(page, SEL["create_btn"], timeout=10)
        if btn is not None:
            h.click(btn, what="botão Criar")
            item = find(page, SEL["create_upload_item"], timeout=8)
            if item is not None:
                h.click(item, what="'Carregar vídeos'")
            else:
                page.keyboard.press("Escape")
    end = time.time() + 15
    while time.time() < end and not _dialog_open(page):
        h._wait(0.5)
    if not _dialog_open(page):
        log.info("youtube: menu Criar nao abriu o dialogo; indo direto para %s", UPLOAD_URL)
        h.goto(UPLOAD_URL)
    h.blockers()
    btn = find(page, SEL["select_files"], timeout=h.r.timeout)
    if btn is None and find(page, SEL["file_input"], timeout=5, state="attached") is None:
        h.blockers()
        raise RuntimeError("a janela de upload do YouTube Studio não abriu (campo de arquivo não encontrado)")
    if btn is not None:
        h.wait_ready(btn, what="botão 'Selecionar ficheiros'")


def attach_file(h: human.Actor, select_cands: list, input_cands: list, path: Path, root: Any = None) -> str:
    """Clica em "Selecionar" como uma pessoa; o seletor de arquivos do sistema e interceptado (nao abre
    janela) e recebe o arquivo. Se o clique nao abrir o seletor, usa o campo de arquivo (sem clicar de novo).
    Devolve "seletor" ou "campo"."""
    page = h.page
    root = root if root is not None else page
    btn = find(root, select_cands, timeout=10)
    if btn is not None:
        clicked = False
        try:
            with page.expect_file_chooser(timeout=15_000) as fc:
                h.click(btn, what="botão de selecionar vídeo")
                clicked = True
            fc.value.set_files(str(path))
            return "seletor"
        except Exception as e:
            log.info("seletor de arquivo nao abriu (%s); usando o campo de arquivo", e)
            if clicked:
                h.sleep(1.0, 2.0)
    inp = find(root, input_cands, timeout=10, state="attached")
    if inp is None:
        raise RuntimeError("campo de arquivo não encontrado")
    inp.set_input_files(str(path))
    return "campo"


def _wait_details(h: human.Actor, timeout: float = 120) -> Any:
    end = time.time() + timeout
    while time.time() < end:
        if h.blockers():  # o dono resolveu um CAPTCHA: recomeca a contagem
            end = time.time() + timeout
        box = find(h.page, SEL["title"], timeout=2)
        if box is not None:
            return box
    raise RuntimeError("o formulário de detalhes não apareceu depois de escolher o arquivo")


# -------------------------------------------------------------- formulario
def _box_has(page: Any, cands: list, text: str) -> bool:
    box = find(page, cands, timeout=2)
    return box is not None and _norm(box.inner_text()) == _norm(text)


def _set_textbox(h: human.Actor, cands: list, text: str, what: str) -> None:
    """Limpa o campo contenteditable e escreve (digita textos curtos, cola longos ou com #)."""
    page = h.page
    box = find(page, cands, timeout=15)
    if box is None:
        raise RuntimeError(f"campo de {what} não encontrado")
    # o titulo vem pre-preenchido com o nome do arquivo de forma assincrona: espera estabilizar
    last, stable = None, 0
    for _ in range(24):
        cur = box.inner_text()
        stable = stable + 1 if cur == last else 0
        last = cur
        if stable >= 2:
            break
        h._wait(0.25)
    h.click(box, enabled=False, what=f"campo de {what}")
    h.select_all_and_delete()
    h.write(text)
    _close_hashtag_dropdown(h)
    got, want = _norm(box.inner_text()), _norm(text)
    if got != want:
        raise RuntimeError(f"o campo de {what} não ficou certo (ficou: {got[:60]!r})")


def _close_hashtag_dropdown(h: human.Actor) -> None:
    # o autocompletar de #hashtag cobre os botoes "Seguinte/Publicar"
    for _ in range(2):
        if exists(h.page, SEL["hashtag_dropdown"]):
            h.page.keyboard.press("Escape")
            h.sleep(0.2, 0.4)


def _checked(el: Any) -> bool:
    try:
        return (el.get_attribute("aria-checked") or "").lower() == "true" or el.get_attribute("checked") is not None
    except Exception:
        return False


def _radio_checked(page: Any, cands: list) -> bool:
    el = find(page, cands, timeout=2)
    return el is not None and _checked(el)


def _click_radio(h: human.Actor, cands: list, what: str, timeout: float = 15) -> None:
    el = find(h.page, cands, timeout=timeout)
    if el is None:
        raise RuntimeError(f"opção '{what}' não encontrada")
    if _checked(el):
        return
    h.click(el, what=f"opção '{what}'")
    end = time.time() + 5
    while time.time() < end:
        if _checked(el):
            return
        h._wait(0.3)
    raise RuntimeError(f"não consegui marcar '{what}'")


def _is_disabled(el: Any) -> bool:
    try:
        return ((el.get_attribute("aria-disabled") or "").lower() == "true"
                or el.get_attribute("disabled") is not None)
    except Exception:
        return True


def _at_visibility(page: Any) -> bool:
    return exists(page, SEL["vis_PUBLIC"]) or exists(page, SEL["visibility"])


def _step_sig(page: Any) -> str:
    try:
        return str(page.evaluate(_STEP_SIG_JS))
    except Exception:
        return ""


def _go_to_visibility(h: human.Actor) -> None:
    """Clica Seguinte ate a etapa Visibilidade (3 vezes normalmente; 4+ em canal monetizado).
    Cada clique precisa mudar de etapa; se nao mudar, para (nao fica clicando no mesmo botao)."""
    page = h.page
    for _ in range(7):
        if _at_visibility(page):
            return
        h.blockers()
        none_box = find(page, SEL["ad_none"], timeout=0)
        if none_box is not None:  # etapa de adequacao para anuncios (canal monetizado)
            h.click(none_box, what="'Nenhuma das opções'")
            sub = find(page, SEL["ad_submit"], timeout=3)
            if sub is not None:
                h.click(sub, what="'Enviar classificação'")
        nxt = find(page, SEL["next"], timeout=10)
        if nxt is None:
            raise RuntimeError("botão Seguinte não encontrado")
        before = _step_sig(page)
        h.click(nxt, timeout=90, what="botão Seguinte")
        end = time.time() + 12
        while time.time() < end and _step_sig(page) == before and not _at_visibility(page):
            h._wait(0.3)
        if _step_sig(page) == before and not _at_visibility(page):
            raise RuntimeError("o botão Seguinte não avançou de etapa (veja o print)")
        h.pause()
    if not _at_visibility(page):
        raise RuntimeError("não cheguei na etapa de Visibilidade")


# ------------------------------------------------------------- envio
def _progress_label(page: Any) -> str:
    el = find(page, SEL["progress_label"], timeout=0, state="attached")
    try:
        return (el.inner_text() if el is not None else "").strip()
    except Exception:
        return ""


def _wait_upload(h: human.Actor, timeout: float, emit: Callable[[str], None]) -> str:
    """Espera o envio do arquivo terminar (processamento/verificacoes podem continuar depois). So le a pagina."""
    page = h.page
    end = time.time() + timeout
    last_report = 0.0
    label = ""
    while time.time() < end:
        if h.blockers():  # o dono resolveu um CAPTCHA: recomeca a contagem
            end = time.time() + timeout
        err = " ".join(page_text(page, s, 1000) for s in SEL["error_area"] if exists(page, [s]))
        if UPLOAD_FAIL_RE.search(err):
            raise RuntimeError(f"o YouTube recusou o arquivo: {err.strip()[:200]}")
        label = _progress_label(page)
        prog = find(page, SEL["progress"], timeout=0, state="attached")
        uploading_attr = False
        if prog is not None:
            try:
                uploading_attr = bool(prog.evaluate("e => e.hasAttribute('uploading')"))
            except Exception:
                pass
        if label and not UPLOADING_RE.search(label) and (UPLOAD_DONE_RE.search(label) or not uploading_attr):
            return label
        if time.time() - last_report > 20 and label:
            emit(f"[youtube] {label}")
            last_report = time.time()
        h._wait(1.5)
    raise RuntimeError(f"o envio não terminou em {int(timeout)} s (último status: {label or '?'})")


def _video_id(page: Any, timeout: float = 30) -> str | None:
    end = time.time() + timeout
    while time.time() < end:
        for cand in SEL["video_link"]:
            try:
                loc = page.locator(cand)
                for i in range(min(loc.count(), 4)):
                    href = loc.nth(i).get_attribute("href") or loc.nth(i).inner_text()
                    m = VIDEO_ID_RE.search(href or "")
                    if m:
                        return m.group(1)
            except Exception:
                continue
        time.sleep(1.0)
    return None


def _wait_published(h: human.Actor, timeout: float = 150) -> None:
    """Depois do clique em Publicar: exige evidencia positiva (dialogo "publicado"/"ainda processando" ou o
    botao Publicar sumir por varias leituras) antes de fechar a aba. "Publicar mesmo assim" e clicado no
    maximo UMA vez (faz parte do mesmo Publicar)."""
    page = h.page
    end = time.time() + timeout
    h._wait(3)
    gone = 0
    anyway_clicked = False
    while time.time() < end:
        if h.blockers():  # o dono resolveu um CAPTCHA: recomeca a contagem
            end = time.time() + timeout
        pre = find(page, SEL["prechecks"], timeout=0)
        if pre is not None and not anyway_clicked:
            btn = find(pre, [("role", "button", r"(publish anyway|publicar mesmo assim|publicar assim mesmo|"
                                                r"publish|publicar)"), "#secondary-action-button"], timeout=3)
            if btn is not None:
                anyway_clicked = True
                h.think()
                h.click(btn, what="'Publicar mesmo assim'")
        if exists(page, SEL["share_dialog"]):
            return
        gone = gone + 1 if not exists(page, [f"{D} #done-button", f"{D} #next-button"]) else 0
        if gone >= 4:
            return
        err = " ".join(page_text(page, s, 600) for s in SEL["error_area"] if exists(page, [s])).strip()
        if err and UPLOAD_FAIL_RE.search(err):
            raise RuntimeError(f"o YouTube não publicou: {err[:200]}")
        h._wait(1.5)
    raise RuntimeError("cliquei em Publicar mas a confirmação não apareceu")


def _close_share_dialog(h: human.Actor) -> None:
    dlg = find(h.page, SEL["share_dialog"], timeout=8)
    if dlg is None:
        return
    h.sleep(1.5, 4.0)  # "le" a confirmacao
    btn = find(dlg, SEL["share_close"], timeout=5)
    if btn is not None:
        try:
            h.click(btn, what="Fechar")
        except Exception:
            pass


# ----------------------------------------------------------- rascunho de teste
def _close_upload_dialog(h: human.Actor) -> bool:
    """Fecha o dialogo de upload pelo X (o video fica como rascunho/privado; nunca clica em Guardar/Publicar)."""
    page = h.page
    if not exists(page, [f"{D} tp-yt-paper-dialog"]):
        return True
    btn = find(page, SEL["close_dialog"], timeout=5)
    if btn is None:
        page.keyboard.press("Escape")
        h.sleep(1.0, 2.0)
    else:
        h.click(btn, enabled=False, what="fechar o diálogo")
    end = time.time() + 12
    while time.time() < end:
        if not exists(page, [f"{D} tp-yt-paper-dialog"]):
            return True
        # pergunta ao fechar? (so dentro do dialogo de confirmacao, nunca no de upload)
        conf = find(page, ["ytcp-confirmation-dialog"], timeout=0)
        if conf is not None:
            ok = find(conf, [("role", "button", r"^\s*(fechar|close|sair|leave|guardar rascunho|save draft)\s*$")], timeout=1)
            if ok is not None:
                h.click(ok, what="confirmar fechar")
        h._wait(0.7)
    return not exists(page, [f"{D} tp-yt-paper-dialog"])


def delete_draft(h: human.Actor, video_id: str, channel_id: str, emit: Callable[[str], None]) -> bool:
    """Apaga o rascunho de teste (a linha e reconhecida pela miniatura, que traz o id do video)."""
    page = h.page
    row_sel = f'ytcp-video-row:has(img[src*="{video_id}"]), ytcp-video-row:has(a[href*="{video_id}"])'
    for tab in ("short", "upload"):
        try:
            h.goto(f"https://studio.youtube.com/channel/{channel_id}/videos/{tab}")
            row = find(page, [row_sel], timeout=25)
            if row is None:
                continue
            h.think()
            box = h._bbox(row)
            if box:  # passa o mouse na linha (os botoes so aparecem no hover)
                h.move_to(box["x"] + box["width"] * 0.5,
                          box["y"] + box["height"] * 0.5, box["height"])
                h.sleep(0.6, 1.2)
            menu = find(row, SEL["row_menu"], timeout=5)
            if menu is None:
                emit("[youtube] (teste) menu 'Opções' da linha não encontrado")
                continue
            h.click(menu, enabled=False, what="menu Opções do vídeo")
            item = find(page, SEL["delete_item"], timeout=6)
            if item is None:
                page.keyboard.press("Escape")
                continue
            h.click(item, what="'Eliminar definitivamente'")
            dlg = find(page, ["ytcp-confirmation-dialog", "ytcp-dialog"], timeout=8) or page
            cbox = find(dlg, ["#confirm-checkbox", "ytcp-checkbox-lit", "tp-yt-paper-checkbox",
                              ("role", "checkbox", r".")], timeout=5)
            if cbox is not None and not _checked(cbox):
                h.click(cbox, enabled=False, what="caixa de confirmação")
            ok_btn = find(dlg, ["#confirm-button",
                                ("role", "button", r"(delete forever|(excluir|eliminar) (permanentemente|definitivamente))")],
                          timeout=5)
            if ok_btn is None:
                page.keyboard.press("Escape")
                continue
            h.click(ok_btn, timeout=20, what="confirmar exclusão do rascunho de teste")
            gone_end = time.time() + 25
            while time.time() < gone_end:
                if not exists(page, [row_sel]):
                    emit(f"[youtube] (teste) rascunho de teste {video_id} apagado do Studio")
                    return True
                h._wait(1.0)
            emit(f"[youtube] (teste) cliquei em excluir, mas a linha do rascunho {video_id} não sumiu")
            return False
        except NeedsUserAction:
            raise
        except Exception as e:
            log.info("apagar rascunho (%s): %s", tab, e)
            emit(f"[youtube] (teste) não consegui apagar o rascunho na aba {tab}: {human._short(e)}")
    return False


def _discard_draft(h: human.Actor, video_id: str | None, channel_id: str | None,
                   emit: Callable[[str], None], delete: bool) -> bool:
    """Modo teste: fecha o dialogo (o video fica PRIVADO/rascunho, nunca publicado) e apaga o rascunho pelo id."""
    try:
        closed = _close_upload_dialog(h)
    except NeedsUserAction:
        raise
    except Exception as e:
        closed = False
        log.info("fechar dialogo: %s", e)
    if not closed:
        emit("[youtube] (teste) não consegui fechar o diálogo pelo X; o rascunho fica PRIVADO")
    if not delete or not video_id or not channel_id:
        return False
    return delete_draft(h, video_id, channel_id, emit)


# ------------------------------------------------------------------- upload
def upload(page: Any, clip: RenderedClip, cfg: Any, dry_run: bool = False, *,
           text: tuple[str, str] | None = None, on_event: Callable[[str], None] | None = None) -> PostResult:
    """Envia um corte como Short. Nunca levanta excecao: devolve PostResult (ok=False + erro em pt-BR).

    Se o clique em Publicar aconteceu mas a confirmacao nao veio, devolve ok=True com erro "INCERTO: ..."
    para o corte NUNCA ser reenviado (um post duplicado e pior que um a menos)."""
    emit_raw = on_event or (lambda m: log.info(m))

    def emit(m: str) -> None:  # nunca emoji no terminal/log
        emit_raw(strip_emojis(m))
    clip_id = clip.plan.id
    res = PostResult(clip_id=clip_id, platform=PLATFORM, ok=False, ts=time.time(), dry_run=dry_run)
    own = " ".join(text or ())
    h = human.Actor(page, cfg, PLATFORM, clip_id, emit, blockers=lambda: _check_blockers(page, own=own))
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
        emit(f"[youtube] {res.error}")
    except NeedsUserAction as e:
        res.error = str(e)
        res.screenshot = screenshot(page, PLATFORM, clip_id, "acao")
    except Exception as e:
        log.exception("upload youtube falhou")
        msg = human._short(e)
        res.error = strip_emojis(f"Falha no YouTube: {msg[:300]}")
        res.screenshot = screenshot(page, PLATFORM, clip_id)
    finally:
        h.finish("teste" if dry_run else ("ok" if res.ok else "erro"))
    res.ts = time.time()
    return res


def _upload(h: human.Actor, clip: RenderedClip, cfg: Any, dry_run: bool, text: tuple[str, str] | None,
            emit: Callable[[str], None]) -> str | None:
    page = h.page
    path = Path(clip.path_for(PLATFORM))
    if not path.is_file():
        raise RuntimeError(f"arquivo do corte não encontrado: {path}")
    if clip.duration and clip.duration > 180:
        emit(f"[youtube] aviso: {clip.duration:.0f}s passa de 3 min e não vira Short")
    if text is None:
        vt, ch = source_info(clip.plan)
        text = build_post_text(clip.plan, PLATFORM, cfg, video_title=vt, channel=ch)
    title, description = text
    timeout_up = float(cfg.get("publicacao.timeout_upload_s", 900))

    secs = h.warm_up(HOME_URL)
    emit(f"[youtube] Studio aberto; olhei o painel por {secs:.0f} s")
    channel_id = _channel_id(page)
    h.step("abrir a janela de envio", lambda: _open_upload(h))
    channel_id = channel_id or _channel_id(page)
    h.think()
    how = h.step("escolher o arquivo do vídeo",
                 lambda: attach_file(h, SEL["select_files"], SEL["file_input"], path), retry=False)
    emit(f"[youtube] arquivo escolhido ({how}): {path.name}")

    h.step("esperar o formulário de detalhes", lambda: _wait_details(h))
    h.think()
    h.step("escrever o título", lambda: _set_textbox(h, SEL["title"], title, "título"),
           verify=lambda: _box_has(page, SEL["title"], title))
    h.pause()
    h.step("escrever a descrição", lambda: _set_textbox(h, SEL["description"], description, "descrição"),
           verify=lambda: _box_has(page, SEL["description"], description))
    h.pause()
    h.step("marcar 'não é conteúdo para crianças'",
           lambda: _click_radio(h, SEL["not_for_kids"], "Não é conteúdo para crianças"),
           verify=lambda: _radio_checked(page, SEL["not_for_kids"]))

    if not cfg.get("publicacao.youtube_conteudo_alterado", False):
        try:  # "Conteudo alterado: Nao" fica em "Mostrar mais"; opcional (cortes reais nao precisam do selo)
            if not exists(page, SEL["altered_no"]):
                more = find(page, SEL["show_more"], timeout=2)
                if more is not None:
                    h.click(more, what="'Mostrar mais'")
            if exists(page, SEL["altered_no"]) and not _radio_checked(page, SEL["altered_no"]):
                _click_radio(h, SEL["altered_no"], "Conteúdo alterado: Não", timeout=3)
        except NeedsUserAction:
            raise
        except Exception as e:
            log.info("conteudo alterado: %s", e)

    h.think()
    h.step("avançar até Visibilidade", lambda: _go_to_visibility(h), verify=lambda: _at_visibility(page))
    vis = str(cfg.get("publicacao.youtube_visibilidade", "public") or "public").upper()
    vis = {"PUBLICO": "PUBLIC", "NAO_LISTADO": "UNLISTED", "PRIVADO": "PRIVATE"}.get(vis, vis)
    if vis not in ("PUBLIC", "UNLISTED", "PRIVATE"):
        vis = "PUBLIC"
    if dry_run:
        vis = "PRIVATE"  # teste: nunca marca Publico
    h.step(f"escolher a visibilidade ({vis.lower()})", lambda: _click_radio(h, SEL[f"vis_{vis}"], f"visibilidade {vis}"),
           verify=lambda: _radio_checked(page, SEL[f"vis_{vis}"]))
    emit(f"[youtube] visibilidade: {vis.lower()}")

    status = _wait_upload(h, timeout_up, emit)
    emit(f"[youtube] envio concluído ({status[:80]})")
    vid = _video_id(page)

    if dry_run:
        done = find(page, SEL["done"], timeout=5)
        emit(f"[youtube] (teste) tudo pronto; botão Publicar/Guardar {'encontrado' if done is not None else 'NÃO encontrado'}. "
             "Não vou clicar.")
        if done is None:
            raise RuntimeError("botão Publicar/Guardar não encontrado (o seletor mudou?)")
        h.think()
        deleted = _discard_draft(h, vid, channel_id, emit, bool(cfg.get("publicacao.teste_apagar_rascunho", True)))
        if not deleted and vid:
            emit(f"[youtube] (teste) ficou um rascunho PRIVADO no Studio (nunca publicado); apague se quiser: "
                 f"https://studio.youtube.com/video/{vid}/edit")
            return f"https://studio.youtube.com/video/{vid}/edit"
        return None

    # ------------------------------------------------ publicar de verdade (uma vez so)
    done = find(page, SEL["done"], timeout=15)
    if done is None:
        raise RuntimeError("botão Publicar não encontrado")
    h.wait_ready(done, timeout=120, enabled=True, what="botão Publicar")
    h.think()
    h.blockers()
    url = f"https://youtube.com/shorts/{vid}" if vid else None
    clicked = {"v": False}

    def press() -> None:
        assert not dry_run
        guard.mark_publish_click(clip.plan.id, PLATFORM, {"video": vid})
        clicked["v"] = True

    try:
        h.step("clicar em Publicar", lambda: h.click(done, what="botão Publicar", on_press=press), retry=False)
        h.step("esperar a confirmação do YouTube", lambda: _wait_published(h), retry=False)
    except NeedsUserAction as e:
        if clicked["v"]:
            guard.pause_platform(PLATFORM, str(e), cfg)
            raise UncertainPost("cliquei em Publicar e depois o YouTube pediu ação; NÃO vou reenviar. Confira no "
                                "Studio se o vídeo saiu.", url)
        raise
    except Exception as e:
        if clicked["v"]:
            raise UncertainPost(f"cliquei em Publicar mas não vi a confirmação ({human._short(e)}). NÃO vou "
                                f"reenviar este corte; confira no Studio.", url)
        raise
    vid = vid or _video_id(page, timeout=10)
    _close_share_dialog(h)
    if not vid:
        emit("[youtube] publicado, mas não consegui ler o link do vídeo")
        return None
    return f"https://youtube.com/shorts/{vid}"


# ------------------------------------------------------------------ selftest
def selftest_page(page: Any, cfg: Any) -> dict:
    """Abre o Studio como uma pessoa (painel -> Criar > Carregar videos) e confere os seletores que existem
    ANTES de escolher um arquivo. Nao envia nada."""
    checks: dict[str, bool] = {}
    erro = None
    info: dict[str, str] = {}
    h = human.Actor(page, cfg, PLATFORM, "selftest", blockers=lambda: _check_blockers(page))
    try:
        try:
            secs = h.warm_up(HOME_URL)
            info["aquecimento"] = f"{secs:.1f} s no painel do Studio"
        except NeedsUserAction as e:
            checks["Logado (sem tela de login do Google)"] = not is_login_wall(page)
            return {"ok": False, "erro": str(e), "checks": checks}
        checks["Logado (sem tela de login do Google)"] = not is_login_wall(page)
        checks["Canal do YouTube existe (URL /channel/UC...)"] = _channel_id(page) is not None
        checks["Botão 'Criar' no Studio"] = exists(page, SEL["create_btn"])
        try:
            _open_upload(h)
        except NeedsUserAction as e:
            return {"ok": False, "erro": str(e), "checks": checks}
        info["caminho"] = "menu Criar" if "studio.youtube.com" in (page.url or "") else "youtube.com/upload"
        checks["Janela de upload aberta"] = _dialog_open(page)
        checks["Campo de arquivo (input file)"] = find(page, SEL["file_input"], timeout=10, state="attached") is not None
        checks["Botão 'Selecionar ficheiros'"] = exists(page, SEL["select_files"])
        checks["Sem aviso de limite diário"] = not DAILY_LIMIT_RE.search(page_text(page, D, 3000))
        # fecha o dialogo vazio com calma (nada foi enviado)
        btn = find(page, SEL["close_dialog"], timeout=3)
        if btn is not None:
            try:
                h.click(btn, what="fechar o diálogo")
            except Exception:
                pass
    except Exception as e:
        erro = f"Falha ao abrir o YouTube Studio: {human._short(e)}"
    finally:
        h.finish("selftest")
    ok = erro is None and all(checks.values())
    if not ok and erro is None:
        erro = "alguns elementos não foram encontrados (veja a lista e o print em logs/screenshots)"
    return {"ok": ok, "erro": erro, "checks": checks, "info": info, "ritmo": h.t.resumo()}
