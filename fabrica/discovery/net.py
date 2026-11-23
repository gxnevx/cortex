"""HTTP simples para a descoberta: sessao por thread, timeouts curtos e NUNCA levanta excecao."""
from __future__ import annotations

import threading
import time

import requests

from .. import log

_log = log.get(__name__)

UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0.0.0 Safari/537.36")
UA_BOT = "fabrica-de-cortes/1.0 (leitor pessoal de tendencias)"

_local = threading.local()


def session() -> requests.Session:
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": UA_BROWSER, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.6"})
        # evita a tela de consentimento do Google/YouTube
        s.cookies.set("SOCS", "CAI", domain=".youtube.com")
        s.cookies.set("CONSENT", "YES+", domain=".youtube.com")
        s.cookies.set("SOCS", "CAI", domain=".google.com")
        _local.s = s
    return s


def get(url: str, *, params: dict | None = None, headers: dict | None = None, timeout: float = 15,
        retries: int = 1, what: str = "") -> requests.Response | None:
    """GET que devolve a resposta (status 200) ou None. Loga o motivo da falha."""
    last = ""
    for attempt in range(retries + 1):
        try:
            r = session().get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
            if r.status_code in (403, 404, 410):
                break  # nao adianta tentar de novo
            if r.status_code == 429:
                ra = r.headers.get("retry-after")
                wait = min(float(ra), 8.0) if ra and ra.replace(".", "").isdigit() else 2.0 * (attempt + 1)
                if attempt < retries:
                    time.sleep(wait)
                continue
        except requests.RequestException as e:
            last = type(e).__name__ + ": " + str(e)[:150]
        if attempt < retries:
            time.sleep(1.0 + attempt)
    _log.info("falha ao baixar %s %s: %s", what or "", url[:120], last)
    return None


def post(url: str, *, data=None, json=None, headers: dict | None = None, timeout: float = 15,
         what: str = "") -> requests.Response | None:
    try:
        r = session().post(url, data=data, json=json, headers=headers, timeout=timeout)
        if r.status_code == 200:
            return r
        _log.info("POST %s %s: HTTP %s", what, url[:100], r.status_code)
    except requests.RequestException as e:
        _log.info("POST %s %s: %s", what, url[:100], e)
    return None
