"""Quando a rede pede CAPTCHA: traz a janela do navegador para a frente e espera o DONO resolver.

O CORTEX nao le, nao clica e nao resolve o CAPTCHA. Ele so mostra a janela, avisa (som + aviso do Windows)
e fica olhando ate o CAPTCHA sumir. Depois continua o mesmo post de onde parou.
Sem resposta no prazo, ou se a rede pedir CAPTCHA vezes demais no mesmo dia, para e a rede fica em pausa.
"""
from __future__ import annotations

import time
from typing import Any, Callable

from .. import notify
from ..log import get as get_log
from ..models import CaptchaAppeared, NeedsUserAction
from . import guard

log = get_log(__name__)

NOMES = {"youtube": "YouTube", "tiktok": "TikTok"}


def _move(page: Any, visible: bool) -> bool:
    """Poe a janela na tela (visible) ou devolve para fora dela."""
    try:
        cdp = page.context.new_cdp_session(page)
        win = cdp.send("Browser.getWindowForTarget")["windowId"]
        cdp.send("Browser.setWindowBounds", {"windowId": win, "bounds": {"windowState": "normal"}})
        pos = {"left": 60, "top": 40} if visible else {"left": -4000, "top": -4000}
        cdp.send("Browser.setWindowBounds", {"windowId": win, "bounds": {**pos, "width": 1366, "height": 820}})
        cdp.detach()
        if visible:
            page.bring_to_front()
        return True
    except Exception as e:
        log.warning("nao consegui mover a janela: %s", e)
        return False


def _beep() -> None:
    try:
        import winsound

        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        pass


def wait_owner(page: Any, platform: str, check: Callable[[], None], emit: Callable[[str], None], cfg: Any,
               clear_s: float = 4.0, poll_ms: int = 1500) -> bool:
    """Espera o dono resolver o CAPTCHA na janela. True = sumiu, pode continuar."""
    if cfg is None or cfg.get("publicacao.headless", False):
        return False  # sem janela nao ha o que mostrar
    nome = NOMES.get(platform, platform)
    minutes = float(cfg.get("publicacao.espera_captcha_min", 30))
    if minutes <= 0 or guard.captchas_today(platform) >= int(cfg.get("publicacao.captcha_por_dia", 2)):
        return False
    guard.note_captcha(platform)
    from . import browser

    hidden = browser._hidden_window(cfg)
    if not _move(page, True):
        return False
    msg = f"O {nome} pediu CAPTCHA. A janela está aberta: resolva nela e deixe aberta, eu continuo sozinho."
    emit(f"[{platform}] {msg}")
    guard.set_waiting(platform, msg)
    notify.toast("CORTEX precisa de você", msg, cfg)
    try:
        end, next_beep, clear_since = time.time() + minutes * 60, 0.0, None
        while time.time() < end:
            if time.time() >= next_beep:
                _beep()
                next_beep = time.time() + 120
            try:
                check()
                clear_since = clear_since or time.time()
                if time.time() - clear_since >= clear_s:  # sumiu de verdade
                    emit(f"[{platform}] CAPTCHA resolvido, continuando o post.")
                    return True
            except CaptchaAppeared:
                clear_since = None
            except NeedsUserAction:
                return False  # virou outra coisa (login, limite): segue o caminho normal
            page.wait_for_timeout(poll_ms)
        emit(f"[{platform}] ninguém resolveu o CAPTCHA em {int(minutes)} min.")
        return False
    except Exception as e:  # janela fechada pelo dono
        log.info("espera do captcha interrompida: %s", e)
        return False
    finally:
        guard.set_waiting(platform, None)
        if hidden:
            _move(page, False)
