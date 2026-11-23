"""Navegador da Fabrica: Chrome (ou Edge) REAL com perfil proprio em paths.BROWSER_PROFILE.

Estrategia (detalhes em docs/PUBLICACAO.md):
- login(): abre o Chrome normal via subprocess, SEM nenhuma flag de automacao e sem porta de
  depuracao. O humano faz o login como em qualquer navegador; detectamos o fim quando a janela
  fecha e conferimos os cookies no banco do perfil.
- automacao (publicar/testar/exportar cookies): abre o MESMO Chrome com o MESMO perfil e
  `--remote-debugging-port=0`, e o Playwright conecta via `connect_over_cdp`. O navegador e
  identico ao do login (nada de --enable-automation, aviso de "controlado por software" ou
  perfil temporario), entao a sessao criada pelo humano continua valida e os cookies que o
  Google/TikTok renovam ficam salvos no perfil. Se ja houver uma janela da Fabrica aberta com
  porta de depuracao, reaproveitamos em vez de falhar por perfil travado.
- Alternativa (publicacao.modo_navegador: playwright): launch_persistent_context.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable

from .. import paths, tools
from ..log import get as get_log
from ..util import slugify

log = get_log(__name__)

PROFILE_IN_USE_MSG = "Feche a janela do navegador da Fábrica e tente de novo."

# Onde o humano faz login (redireciona para a tela de login se estiver deslogado)
LOGIN_URLS = {
    "youtube": "https://studio.youtube.com/",
    "tiktok": "https://www.tiktok.com/login?redirect_url=https%3A%2F%2Fwww.tiktok.com%2Ftiktokstudio%2Fupload",
}

# Cookies que indicam sessao ativa. Cada grupo precisa de pelo menos 1 cookie presente e nao expirado.
LOGIN_COOKIES: dict[str, dict[str, Any]] = {
    "youtube": {
        "domains": ("youtube.com",),
        "groups": [("SAPISID", "__Secure-3PAPISID", "__Secure-1PAPISID"),
                   ("__Secure-3PSID", "__Secure-1PSID", "SID")],
    },
    "tiktok": {
        "domains": ("tiktok.com",),
        "groups": [("sessionid", "sessionid_ss", "sid_tt")],
    },
}

COOKIE_EXPORT_DOMAINS = ("youtube.com", "google.com", "twitch.tv", "tiktok.com")
CHROME_EPOCH_OFFSET = 11644473600  # segundos entre 1601-01-01 e 1970-01-01


class ProfileInUseError(RuntimeError):
    """O perfil da Fabrica esta aberto em outra janela (sem porta de depuracao)."""

    def __init__(self, msg: str = PROFILE_IN_USE_MSG):
        super().__init__(msg)


class BrowserLaunchError(RuntimeError):
    pass


def _emit(on_event: Callable[[str], None] | None, msg: str) -> None:
    from .captions import strip_emojis

    msg = strip_emojis(msg)  # nunca emoji no terminal/log
    log.info(msg)
    if on_event:
        try:
            on_event(msg)
        except Exception:
            pass
    else:
        try:
            print(msg, flush=True)
        except UnicodeEncodeError:  # console sem UTF-8
            print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


# ---------------------------------------------------------------- perfil / processo
def profile_dir() -> Path:
    p = Path(paths.BROWSER_PROFILE)
    p.mkdir(parents=True, exist_ok=True)
    return p


def profile_in_use(profile: Path | None = None) -> bool:
    """True se algum Chrome/Edge esta usando o perfil.

    No Windows o navegador mantem `<perfil>/lockfile` aberto sem compartilhamento; tentamos
    abri-lo com acesso exclusivo (sem apagar nada). Violacao de compartilhamento = em uso.
    """
    lock = (profile or profile_dir()) / "lockfile"
    if not lock.exists():
        return False
    if os.name == "nt":
        k32 = ctypes.windll.kernel32
        k32.CreateFileW.restype = ctypes.c_void_p
        h = k32.CreateFileW(str(lock), 0x80000000 | 0x40000000, 0, None, 3, 0x80, None)  # RW, sem share, OPEN_EXISTING
        invalid = ctypes.c_void_p(-1).value
        if h in (None, invalid):
            err = k32.GetLastError()
            return err in (32, 33, 5)  # sharing/lock violation, acesso negado
        k32.CloseHandle(ctypes.c_void_p(h))
        return False
    # (fora do Windows: lockfile e um symlink host-pid)
    try:
        target = os.readlink(lock)
        pid = int(target.rsplit("-", 1)[-1])
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def wait_profile_free(timeout: float = 15.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if not profile_in_use():
            return True
        time.sleep(0.5)
    return not profile_in_use()


def browser_exe(cfg: Any) -> tuple[str, str]:
    """(caminho do executavel, canal playwright). Respeita publicacao.navegador."""
    want = str(cfg.get("publicacao.navegador", "chrome") or "chrome").lower()
    chrome, edge = tools.chrome(), tools.edge()
    if want in ("msedge", "edge"):
        order = [(edge, "msedge"), (chrome, "chrome")]
    else:  # chrome | chromium (o Chromium do Playwright nao esta instalado: usa o Chrome)
        order = [(chrome, "chrome"), (edge, "msedge")]
    for exe, channel in order:
        if exe:
            if channel != ("msedge" if want in ("msedge", "edge") else "chrome"):
                log.warning("Navegador '%s' nao encontrado; usando %s", want, exe)
            return exe, channel
    raise BrowserLaunchError("Nao achei o Google Chrome nem o Microsoft Edge neste PC. Instale o Chrome.")


def _base_args(cfg: Any) -> list[str]:
    args = [
        f"--user-data-dir={profile_dir()}",
        "--no-first-run",
        "--no-default-browser-check",
        f"--disk-cache-size={int(cfg.get('publicacao.cache_navegador_mb', 100)) * 1024 * 1024}",
    ]
    args += [str(a) for a in (cfg.get("publicacao.args_navegador", []) or [])]
    return args


def trim_profile(max_age_days: float = 1.0) -> int:
    """Apaga so arquivos de metricas antigos do Chrome (BrowserMetrics/*.pma) para poupar disco.

    Nunca mexe em cookies, logins ou configuracoes. So roda com o navegador fechado.
    """
    if profile_in_use():
        return 0
    n = 0
    cutoff = time.time() - max_age_days * 86400
    for f in (profile_dir() / "BrowserMetrics").glob("*.pma"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                n += 1
        except OSError:
            pass
    return n


def _popen(args: list[str]) -> subprocess.Popen:
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, close_fds=True)


# ------------------------------------------------------------- CDP (porta de depuracao)
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _http_json(url: str, timeout: float = 2.0) -> Any:
    with _NO_PROXY.open(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def devtools_port() -> int | None:
    """Porta de depuracao do navegador da Fabrica se ele estiver aberto e respondendo."""
    f = profile_dir() / "DevToolsActivePort"
    try:
        port = int(f.read_text(encoding="utf-8", errors="ignore").splitlines()[0].strip())
    except Exception:
        return None
    try:
        info = _http_json(f"http://127.0.0.1:{port}/json/version", 1.5)
        return port if info.get("webSocketDebuggerUrl") else None
    except Exception:
        return None


def cdp_browser_call(port: int, method: str, params: dict | None = None, timeout: float = 15.0) -> dict:
    """Chama um metodo CDP no nivel do NAVEGADOR (nao anexa em nenhuma aba)."""
    from websockets.sync.client import connect

    ws_url = _http_json(f"http://127.0.0.1:{port}/json/version", 3.0)["webSocketDebuggerUrl"]
    with connect(ws_url, max_size=None, open_timeout=timeout, close_timeout=2) as ws:
        ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
        end = time.time() + timeout
        while time.time() < end:
            try:
                msg = json.loads(ws.recv(timeout=max(0.1, end - time.time())))
            except TimeoutError:
                break
            if msg.get("id") == 1:
                if "error" in msg:
                    raise RuntimeError(f"CDP {method}: {msg['error']}")
                return msg.get("result", {})
    raise TimeoutError(f"CDP {method}: sem resposta")


def _close_debug_browser(port: int, wait: float = 15.0) -> bool:
    try:
        cdp_browser_call(port, "Browser.close", timeout=5)
    except Exception:
        pass  # a conexao cai quando o navegador fecha
    return wait_profile_free(wait)


def _hidden_window(cfg: Any) -> bool:
    """Janela fora da tela? Sim por padrao; nao no modo semi do TikTok (o dono precisa clicar em Publicar)."""
    if not cfg.get("publicacao.janela_oculta", True):
        return False
    return str(cfg.get("publicacao.tiktok_modo", "auto")) != "semi"


def _launch_debug_browser(cfg: Any, headless: bool, url: str = "about:blank",
                          timeout: float = 40.0) -> tuple[subprocess.Popen, int]:
    """Abre o navegador real com porta de depuracao aleatoria e devolve (processo, porta)."""
    if profile_in_use():
        raise ProfileInUseError()
    trim_profile()
    exe, _ = browser_exe(cfg)
    port_file = profile_dir() / "DevToolsActivePort"
    try:
        port_file.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        raise ProfileInUseError()
    args = [exe] + _base_args(cfg) + ["--remote-debugging-port=0"]
    if headless:
        args += ["--headless=new", "--window-size=1366,900"]
    else:
        args += ["--window-size=1366,900", "--new-window"]
        if _hidden_window(cfg):
            # Chrome normal (nao headless), so que fora da area visivel do monitor: nao atrapalha o dono.
            # Sem estas flags o Chrome "congela" janelas escondidas e o upload trava.
            args += ["--window-position=-4000,-4000", "--disable-backgrounding-occluded-windows",
                     "--disable-renderer-backgrounding", "--disable-background-timer-throttling"]
    args.append(url)
    proc = _popen(args)
    end = time.time() + timeout
    while time.time() < end:
        port = devtools_port()
        if port:
            return proc, port
        rc = proc.poll()
        if rc is not None:
            # o Chrome repassou a janela para outra instancia que ja usava o perfil
            time.sleep(1.0)
            port = devtools_port()
            if port:
                return proc, port
            if profile_in_use():
                raise ProfileInUseError()
            raise BrowserLaunchError(f"O navegador fechou sozinho ao abrir (codigo {rc}).")
        time.sleep(0.3)
    _kill(proc)
    raise BrowserLaunchError("O navegador abriu mas nao liberou a porta de automacao (politica da empresa?). "
                             "Tente publicacao.modo_navegador: playwright no config.yaml.")


def _kill(proc: subprocess.Popen | None) -> None:
    if not proc or proc.poll() is not None:
        return
    try:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=15)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


# ---------------------------------------------------------------------- sessao
class BrowserSession:
    """Uma sessao de navegador para varias publicacoes.

    with BrowserSession(cfg) as s:
        page = s.new_page()
    """

    def __init__(self, cfg: Any, headless: bool | None = None, on_event: Callable[[str], None] | None = None):
        self.cfg = cfg
        self.headless = bool(cfg.get("publicacao.headless", False)) if headless is None else headless
        self.on_event = on_event
        self.mode = str(cfg.get("publicacao.modo_navegador", "cdp") or "cdp").lower()
        self._pw = None
        self.browser = None
        self.context = None
        self.proc: subprocess.Popen | None = None
        self.launched = False
        self.port: int | None = None
        self._pages: list[Any] = []

    # -- ciclo de vida
    def __enter__(self) -> "BrowserSession":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def start(self) -> "BrowserSession":
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        try:
            if self.mode == "playwright":
                self._start_persistent()
            else:
                self._start_cdp()
        except Exception:
            self._stop_pw()
            raise
        return self

    def _start_cdp(self) -> None:
        port = devtools_port()
        if port:
            log.info("Reaproveitando o navegador da Fabrica ja aberto (porta %s)", port)
            self.launched = False
        else:
            self.proc, port = _launch_debug_browser(self.cfg, self.headless)
            self.launched = True
        self.port = port
        # is_local: Playwright e navegador na mesma maquina (permite enviar arquivos > 50 MB pelo caminho).
        # no_defaults: nao aplica emulacoes do Playwright (foco, midia, fontes) no contexto real do navegador.
        try:
            self.browser = self._pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=30_000,
                                                              is_local=True, no_defaults=True)
        except TypeError:  # Playwright antigo
            self.browser = self._pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}", timeout=30_000)
        self.context = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()

    def _start_persistent(self) -> None:
        if profile_in_use():
            raise ProfileInUseError()
        _, channel = browser_exe(self.cfg)
        self.context = self._pw.chromium.launch_persistent_context(
            str(profile_dir()), channel=channel, headless=self.headless, no_viewport=True,
            args=_base_args(self.cfg)[1:],  # user-data-dir ja e o 1o argumento do Playwright
        )
        self.launched = True

    def new_page(self) -> Any:
        page = self.context.new_page()
        page.set_default_timeout(30_000)
        page.set_default_navigation_timeout(60_000)

        def _on_dialog(d):  # "Sair do site? Alteracoes nao salvas" etc.
            try:
                d.accept()
            except Exception:
                pass

        page.on("dialog", _on_dialog)
        self._pages.append(page)
        return page

    def cookies(self, domains: Iterable[str] | None = None) -> list[dict]:
        cks = self.context.cookies()
        return _filter_domains(cks, domains) if domains else cks

    def close(self) -> None:
        for p in self._pages:
            try:
                if not p.is_closed():
                    p.close(run_before_unload=False)
            except Exception:
                pass
        self._pages.clear()
        try:
            if self.mode == "playwright":
                if self.context:
                    self.context.close()
            elif self.launched and self.port:
                try:
                    cdp = self.browser.new_browser_cdp_session()
                    cdp.send("Browser.close")
                except Exception:
                    pass
                if self.proc:
                    try:
                        self.proc.wait(timeout=15)
                    except Exception:
                        _kill(self.proc)
                wait_profile_free(10)
            elif self.browser:
                self.browser.close()  # so desconecta (janela aberta pelo usuario continua)
        except Exception as e:
            log.debug("fechando navegador: %s", e)
        finally:
            self._stop_pw()

    def _stop_pw(self) -> None:
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._pw = None


# ------------------------------------------------------------------- cookies
def _domain_match(domain: str, bases: Iterable[str]) -> bool:
    d = (domain or "").lstrip(".").lower()
    return any(d == b or d.endswith("." + b) for b in bases)


def _filter_domains(cookies: list[dict], domains: Iterable[str]) -> list[dict]:
    domains = tuple(domains)
    return [c for c in cookies if _domain_match(c.get("domain", ""), domains)]


def _cookie_db_path() -> Path | None:
    for rel in ("Default/Network/Cookies", "Default/Cookies"):
        p = profile_dir() / rel
        if p.is_file():
            return p
    return None


def read_cookie_meta() -> list[dict] | None:
    """Le nomes/dominios/validade dos cookies direto do SQLite do perfil (sem descriptografar).

    Devolve None se o arquivo estiver travado (navegador aberto) e [] se nao houver banco ainda.
    """
    src = _cookie_db_path()
    if not src:
        return []
    tmp = Path(tempfile.mkdtemp(prefix="fab_ck_"))
    try:
        try:
            for suffix in ("", "-wal", "-journal"):
                f = Path(str(src) + suffix)
                if f.exists():
                    shutil.copy2(f, tmp / ("Cookies" + suffix))
        except (PermissionError, OSError):
            return None
        con = sqlite3.connect(str(tmp / "Cookies"))
        try:
            cols = {r[1] for r in con.execute("PRAGMA table_info(cookies)")}
            sel = ["host_key", "name", "expires_utc"]
            sel.append("is_persistent" if "is_persistent" in cols else ("has_expires" if "has_expires" in cols else "1"))
            rows = con.execute(f"SELECT {', '.join(sel)} FROM cookies").fetchall()
        finally:
            con.close()
        out = []
        for host, name, exp, persistent in rows:
            expires = (exp / 1_000_000 - CHROME_EPOCH_OFFSET) if exp else -1
            out.append({"domain": host, "name": name, "expires": expires, "persistent": bool(persistent)})
        return out
    except sqlite3.Error as e:
        log.debug("cookie db: %s", e)
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _has_login(cookies: list[dict], platform: str) -> bool:
    spec = LOGIN_COOKIES.get(platform)
    if not spec:
        return False
    now = time.time()
    valid = set()
    for c in cookies:
        if not _domain_match(c.get("domain", ""), spec["domains"]):
            continue
        exp = c.get("expires", -1)
        if exp is not None and exp > 0 and exp < now:
            continue
        if "value" in c and not c.get("value"):
            continue
        valid.add(c.get("name"))
    return all(any(n in valid for n in group) for group in spec["groups"])


def _cookies_via_cdp(port: int) -> list[dict]:
    return cdp_browser_call(port, "Storage.getCookies").get("cookies", [])


def check_login(platform: str, cfg: Any = None, deep: bool = False) -> bool:
    """Confere pelos cookies do perfil se ha sessao ativa na rede. Nao abre janela (exceto deep=True).

    deep=True tambem abre a pagina de upload e confere que nao caiu na tela de login.
    """
    platform = (platform or "").lower()
    if platform not in LOGIN_COOKIES:
        return False
    cookies: list[dict] | None = None
    port = devtools_port()
    if port:
        try:
            cookies = _cookies_via_cdp(port)
        except Exception as e:
            log.debug("check_login via CDP: %s", e)
    if cookies is None:
        cookies = read_cookie_meta()
    if cookies is None:
        log.warning("check_login(%s): perfil em uso por outra janela; nao consegui ler os cookies", platform)
        return False
    ok = _has_login(cookies, platform)
    if ok and deep and cfg is not None:
        try:
            ok = _deep_login_check(platform, cfg)
        except ProfileInUseError:
            log.warning("check_login deep: perfil em uso")
        except Exception as e:
            log.warning("check_login deep (%s): %s", platform, e)
    return ok


def _deep_login_check(platform: str, cfg: Any) -> bool:
    from . import tiktok, youtube

    mod = youtube if platform == "youtube" else tiktok
    with BrowserSession(cfg, headless=True) as s:
        page = s.new_page()
        page.goto(mod.UPLOAD_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        return not mod.is_login_wall(page)


def write_netscape(cookies: list[dict], dest: Path) -> int:
    lines = ["# Netscape HTTP Cookie File",
             "# Gerado pela Fabrica de Cortes (perfil do navegador da Fabrica). NAO COMPARTILHE este arquivo.",
             ""]
    n = 0
    for c in sorted(cookies, key=lambda c: (c.get("domain", ""), c.get("name", ""))):
        domain = c.get("domain", "")
        name, value = c.get("name", ""), c.get("value", "")
        if not domain or not name or "\n" in value or "\t" in value:
            continue
        exp = c.get("expires", -1)
        exp = int(exp) if exp and exp > 0 else 0
        prefix = "#HttpOnly_" if c.get("httpOnly") else ""
        flag = "TRUE" if domain.startswith(".") else "FALSE"
        secure = "TRUE" if c.get("secure") else "FALSE"
        lines.append("\t".join([prefix + domain, flag, c.get("path", "/") or "/", secure, str(exp), name, value]))
        n += 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, dest)
    return n


def export_cookies_txt(cfg: Any, session: BrowserSession | None = None,
                       dest: Path | None = None) -> Path | None:
    """Exporta cookies (youtube/google/twitch/tiktok) do perfil da Fabrica para cookies.txt (Netscape).

    Usado pelo yt-dlp contra o bloqueio "confirme que nao e um robo". Devolve None se nao houver
    cookies ou se o perfil estiver aberto em outra janela sem porta de automacao.
    """
    dest = Path(dest or paths.COOKIES_TXT)
    domains = tuple(cfg.get("publicacao.cookies_dominios", COOKIE_EXPORT_DOMAINS) if cfg else COOKIE_EXPORT_DOMAINS)
    cookies: list[dict] | None = None
    try:
        if session is not None and session.context is not None:
            cookies = session.cookies()
        else:
            port = devtools_port()
            if port:
                cookies = _cookies_via_cdp(port)
            elif profile_in_use():
                log.warning("export_cookies_txt: %s", PROFILE_IN_USE_MSG)
                return None
            else:
                proc, port = _launch_debug_browser(cfg, headless=True)
                try:
                    cookies = _cookies_via_cdp(port)
                finally:
                    try:
                        cdp_browser_call(port, "Browser.close", timeout=5)
                    except Exception:
                        pass
                    try:
                        proc.wait(timeout=15)
                    except Exception:
                        _kill(proc)
                    wait_profile_free(10)
    except ProfileInUseError:
        log.warning("export_cookies_txt: %s", PROFILE_IN_USE_MSG)
        return None
    except Exception as e:
        log.warning("export_cookies_txt falhou: %s", e)
        return None
    cookies = _filter_domains(cookies or [], domains)
    if not cookies:
        return None
    n = write_netscape(cookies, dest)
    log.info("cookies.txt: %d cookies em %s", n, dest)
    return dest if n else None


# ---------------------------------------------------------------------- login
def login(platform: str, cfg: Any, timeout_s: float | None = None,
          on_event: Callable[[str], None] | None = None) -> bool:
    """Abre o navegador da Fabrica na pagina de login e espera o HUMANO entrar e fechar a janela.

    Nunca digita nada: so abre o Chrome normal (sem automacao) e confere os cookies no final.
    """
    platform = (platform or "").lower()
    if platform not in LOGIN_URLS:
        raise ValueError(f"Plataforma desconhecida: {platform}")
    timeout_s = float(timeout_s or cfg.get("publicacao.login_timeout_s", 600))

    from . import guard as _guard

    lock = _guard.PublishLock()
    if not lock.acquire():
        raise RuntimeError("tem um post sendo enviado agora; espere ele terminar e tente de novo")
    try:
        return _login_locked(platform, cfg, timeout_s, on_event)
    finally:
        lock.release()


def _login_locked(platform: str, cfg: Any, timeout_s: float, on_event: Callable[[str], None] | None) -> bool:
    port = devtools_port()
    if port:  # navegador de automacao esquecido aberto: fecha com calma antes
        _emit(on_event, "Fechando o navegador da Fábrica que tinha ficado aberto...")
        _close_debug_browser(port)
    if profile_in_use():
        raise ProfileInUseError()

    exe, _ = browser_exe(cfg)
    proc = _popen([exe] + _base_args(cfg) + ["--new-window", LOGIN_URLS[platform]])
    nome = "YouTube (conta Google)" if platform == "youtube" else "TikTok"
    _emit(on_event, f"Abri o navegador da Fábrica. Entre na sua conta do {nome} normalmente "
                    f"(senha, código, captcha: tudo por você). Quando terminar, FECHE a janela. "
                    f"Espero até {int(timeout_s // 60)} min.")
    t0 = time.time()
    next_tip = t0 + 120
    while True:
        rc = proc.poll()
        if rc is not None:
            if time.time() - t0 < 10 and profile_in_use():
                # o Chrome repassou a janela para outra instancia do mesmo perfil: espera ela fechar
                while profile_in_use() and time.time() - t0 < timeout_s:
                    time.sleep(1.0)
            break
        if time.time() - t0 > timeout_s:
            _emit(on_event, "Tempo esgotado. Feche a janela do navegador da Fábrica e rode o login de novo "
                            "(o que você já fez fica salvo no perfil).")
            return False
        if time.time() > next_tip:
            _emit(on_event, "Ainda esperando... depois de entrar na conta, feche a janela do navegador.")
            next_tip = time.time() + 120
        time.sleep(1.0)
    wait_profile_free(15)
    ok = check_login(platform, cfg)
    if ok:
        try:  # o dono resolveu o que a rede pediu: libera a pausa de seguranca (captcha/verificacao)
            from . import guard

            if guard.clear_pause(platform):
                _emit(on_event, f"Pausa de segurança do {nome} liberada (login refeito por você).")
        except Exception as e:
            log.debug("limpar pausa: %s", e)
    if not ok:
        _emit(on_event, f"Não encontrei a sessão do {nome} nos cookies. Se você entrou mesmo assim, "
                        f"abra o login de novo e confira se a página carregou logada antes de fechar.")
    return ok


# ------------------------------------------------------------ helpers de pagina
def screenshot(page: Any, platform: str, clip_id: str, tag: str = "erro") -> str | None:
    try:
        paths.SCREENSHOTS.mkdir(parents=True, exist_ok=True)
        f = paths.SCREENSHOTS / f"{platform}_{tag}_{slugify(clip_id, 40)}_{time.strftime('%Y%m%d-%H%M%S')}.png"
        page.screenshot(path=str(f), timeout=15_000)
        return str(f)
    except Exception as e:
        log.debug("screenshot falhou: %s", e)
        return None


def locator_for(root: Any, cand: Any) -> Any:
    """Converte um candidato de seletor em Locator.

    str            -> CSS/seletor Playwright
    ("role", r, rx)-> get_by_role(r, name=regex)
    ("text", rx)   -> get_by_text(regex)
    ("label", rx)  -> get_by_label(regex)
    """
    if isinstance(cand, str):
        return root.locator(cand)
    kind = cand[0]
    if kind == "role":
        return root.get_by_role(cand[1], name=re.compile(cand[2], re.I))
    if kind == "text":
        return root.get_by_text(re.compile(cand[1], re.I))
    if kind == "label":
        return root.get_by_label(re.compile(cand[1], re.I))
    raise ValueError(cand)


def find(root: Any, cands: list, timeout: float = 10.0, state: str = "visible") -> Any | None:
    """Primeiro elemento que casar com algum candidato (na ordem). state: visible | attached."""
    end = time.time() + timeout
    while True:
        for cand in cands:
            try:
                loc = locator_for(root, cand)
                n = loc.count()
                if not n:
                    continue
                if state == "attached":
                    return loc.first
                for i in range(min(n, 6)):
                    el = loc.nth(i)
                    if el.is_visible():
                        return el
            except Exception:
                continue
        if time.time() >= end:
            return None
        time.sleep(0.4)


def exists(root: Any, cands: list, state: str = "visible") -> bool:
    return find(root, cands, timeout=0, state=state) is not None


def page_text(root: Any, selector: str = "body", limit: int = 20000) -> str:
    try:
        return (root.locator(selector).first.inner_text(timeout=3000) or "")[:limit]
    except Exception:
        return ""
