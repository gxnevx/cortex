"""Notificacao do Windows (toast) ao fim de uma rodada. Sem dependencias extras."""
from __future__ import annotations

from . import log
from .util import run_cmd

_log = log.get("notify")

# AppUserModelID do PowerShell (ja registrado no Windows), necessario para o toast aparecer
_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"


def _ps_escape(s: str) -> str:
    return (s or "").replace("'", "''").replace("\r", " ").replace("\n", " ")[:250]


def toast(title: str, message: str, cfg=None) -> bool:
    if cfg is not None and not cfg.get("notificacoes.windows_toast", True):
        return False
    script = f"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$x = $t.GetElementsByTagName('text')
$x.Item(0).AppendChild($t.CreateTextNode('{_ps_escape(title)}')) > $null
$x.Item(1).AppendChild($t.CreateTextNode('{_ps_escape(message)}')) > $null
$n = [Windows.UI.Notifications.ToastNotification]::new($t)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{_APP_ID}').Show($n)
"""
    try:
        r = run_cmd(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=20)
        if r.returncode != 0:
            _log.debug("toast falhou: %s", r.stderr[-300:])
        return r.returncode == 0
    except Exception as e:  # pragma: no cover
        _log.debug("toast falhou: %s", e)
        return False
