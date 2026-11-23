"""Envio para o YouTube pela API oficial (YouTube Data API v3, videos.insert).

Caminho autorizado pelo Google: nao abre navegador. Conferido na documentacao em 23/11/2026:
100 envios por dia por projeto e projeto nao auditado pode publicar video publico (mudanca de 02/11/2026).

O dono cria o cliente OAuth (tipo "App para computador") no Google Cloud, salva o arquivo baixado em
data/google_oauth.json e roda `cortex login youtube-api` uma vez. O token fica em data/youtube_token.bin,
criptografado pelo Windows (DPAPI): so o usuario do Windows que conectou consegue abrir.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import http.server
import json
import secrets
import threading
import time
import urllib.parse
import webbrowser
from ctypes import wintypes
from pathlib import Path
from typing import Any, Callable

import requests

from .. import paths
from ..log import get as get_log
from ..models import PostResult, RenderedClip
from . import guard

log = get_log(__name__)

CLIENT_FILE = paths.DATA / "google_oauth.json"
TOKEN_FILE = paths.DATA / "youtube_token.bin"
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
RECONNECT = "ACAO_NECESSARIA: conecte de novo a API do YouTube (cortex login youtube-api)"


# ------------------------------------------------------------ token (DPAPI)
class _Blob(ctypes.Structure):
    _fields_ = [("n", wintypes.DWORD), ("p", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool) -> bytes:
    buf = ctypes.create_string_buffer(data, len(data))
    src, dst = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), _Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(dst)):
        raise OSError("o Windows nao conseguiu abrir/guardar o token")
    try:
        return ctypes.string_at(dst.p, dst.n)
    finally:
        ctypes.windll.kernel32.LocalFree(dst.p)


def _save_token(tok: dict) -> None:
    TOKEN_FILE.write_bytes(_dpapi(json.dumps(tok).encode("utf-8"), True))


def _load_token() -> dict | None:
    try:
        return json.loads(_dpapi(TOKEN_FILE.read_bytes(), False).decode("utf-8"))
    except Exception:
        return None


def _client() -> dict | None:
    try:
        d = json.loads(CLIENT_FILE.read_text(encoding="utf-8"))
        return d.get("installed") or None
    except Exception:
        return None


def enabled(cfg: Any) -> bool:
    """Usar a API? publicacao.youtube_via: auto (API se conectada) | api | navegador."""
    via = str(cfg.get("publicacao.youtube_via", "auto")).lower() if cfg is not None else "auto"
    if via == "navegador":
        return False
    return via == "api" or bool(_client() and TOKEN_FILE.exists())


def connected() -> bool:
    return bool(_client() and _load_token())


def ready(cfg: Any) -> bool:
    """A API deve ser usada AGORA? No modo auto, token vencido devolve False e o navegador assume."""
    if not enabled(cfg):
        return False
    if str(cfg.get("publicacao.youtube_via", "auto")).lower() == "api":
        return True
    try:
        return bool(_access())
    except Exception as e:
        log.warning("API do YouTube indisponivel agora (%s); uso o navegador", e)
        return False


def find_client_download() -> Path | None:
    """Cliente OAuth recem baixado na pasta Downloads (client_secret*.json do tipo 'App para computador')."""
    files = sorted((Path.home() / "Downloads").glob("client_secret*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files:
        try:
            if "installed" in json.loads(p.read_text(encoding="utf-8")):
                return p
        except Exception:
            continue
    return None


# ------------------------------------------------------------------ OAuth
def connect(timeout_s: float = 300) -> str:
    """Abre o navegador para o dono autorizar. Devolve o nome do canal conectado."""
    cl = _client()
    if not cl:
        raise RuntimeError(f"Falta o arquivo {CLIENT_FILE} (cliente OAuth do tipo 'App para computador').")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    got: dict = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            if q.get("state") == state and not got:
                got.update(q)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>CORTEX: pode fechar esta aba.</h2>".encode("utf-8"))

        def log_message(self, *a):
            return

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    redirect = f"http://127.0.0.1:{srv.server_port}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        webbrowser.open(AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": cl["client_id"], "redirect_uri": redirect, "response_type": "code", "scope": SCOPES,
            "access_type": "offline", "prompt": "consent", "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256"}))
        end = time.time() + timeout_s
        while not got and time.time() < end:
            time.sleep(0.3)
    finally:
        srv.shutdown()
        srv.server_close()
    if "code" not in got:
        raise RuntimeError(f"autorizacao nao concluida ({got.get('error', 'tempo esgotado')})")
    r = requests.post(TOKEN_URL, timeout=30, data={
        "client_id": cl["client_id"], "client_secret": cl.get("client_secret", ""), "code": got["code"],
        "code_verifier": verifier, "grant_type": "authorization_code", "redirect_uri": redirect})
    if not r.ok:
        raise RuntimeError(f"o Google recusou a conexao ({r.status_code})")
    tok = r.json()
    if not tok.get("refresh_token"):
        raise RuntimeError("o Google nao devolveu o token de renovacao; tente conectar de novo")
    tok["expira"] = time.time() + float(tok.get("expires_in", 3600)) - 120
    _save_token(tok)
    return channel_name()


def _access() -> str:
    tok, cl = _load_token(), _client()
    if not tok or not cl:
        raise PermissionError(RECONNECT)
    if time.time() < float(tok.get("expira", 0)):
        return tok["access_token"]
    r = requests.post(TOKEN_URL, timeout=30, data={
        "client_id": cl["client_id"], "client_secret": cl.get("client_secret", ""),
        "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"})
    if r.status_code in (400, 401):
        raise PermissionError(RECONNECT)
    r.raise_for_status()
    new = r.json()
    tok.update(access_token=new["access_token"], expira=time.time() + float(new.get("expires_in", 3600)) - 120)
    _save_token(tok)
    return tok["access_token"]


def channel_name() -> str:
    r = requests.get(f"{API}/channels", params={"part": "snippet", "mine": "true"}, timeout=30,
                     headers={"Authorization": f"Bearer {_access()}"})
    r.raise_for_status()
    items = r.json().get("items") or []
    if not items:
        raise RuntimeError("esta conta Google nao tem canal no YouTube")
    s = items[0]["snippet"]
    return f"{s.get('title', '')} {s.get('customUrl', '')}".strip()


# ------------------------------------------------------------------ envio
def _reason(r: requests.Response) -> str:
    try:
        return r.json()["error"]["errors"][0]["reason"]
    except Exception:
        return f"HTTP {r.status_code}"


def _fail(clip_id: str, msg: str, dry: bool) -> PostResult:
    return PostResult(clip_id, "youtube", False, error=msg, ts=time.time(), dry_run=dry)


def upload(clip: RenderedClip, cfg: Any, text: tuple[str, str], dry_run: bool = False,
           on_event: Callable[[str], None] | None = None) -> PostResult:
    cid, path = clip.plan.id, Path(clip.path_for("youtube"))
    emit = on_event or (lambda m: None)
    try:
        token = _access()
    except PermissionError as e:
        return _fail(cid, str(e), dry_run)
    except requests.RequestException as e:
        return _fail(cid, f"sem conexao com o Google ({e.__class__.__name__})", dry_run)
    if dry_run:
        try:
            emit(f"[youtube] (teste) API conectada ao canal {channel_name()}; nada foi enviado.")
            return PostResult(cid, "youtube", True, ts=time.time(), dry_run=True)
        except Exception as e:
            return _fail(cid, f"API conectada, mas nao li o canal ({e.__class__.__name__})", True)
    size = path.stat().st_size
    title, desc = (str(t or "").replace("<", "").replace(">", "") for t in text)
    body = {"snippet": {"title": title[:100], "description": desc[:4900], "categoryId": "24",
                        "defaultLanguage": "pt-BR", "defaultAudioLanguage": clip.plan.idioma_origem or "pt-BR"},
            "status": {"privacyStatus": str(cfg.get("publicacao.youtube_visibilidade", "public")),
                       "selfDeclaredMadeForKids": False, "containsSyntheticMedia": False}}
    try:
        r = requests.post(UPLOAD, params={"uploadType": "resumable", "part": "snippet,status"}, json=body, timeout=60,
                          headers={"Authorization": f"Bearer {token}", "X-Upload-Content-Type": "video/mp4",
                                   "X-Upload-Content-Length": str(size)})
    except requests.RequestException as e:
        return _fail(cid, f"sem conexao com o YouTube ({e.__class__.__name__})", False)
    if not r.ok:
        why = _reason(r)
        if why in ("quotaExceeded", "uploadLimitExceeded", "rateLimitExceeded", "dailyLimitExceeded"):
            return _fail(cid, f"LIMITE_DIARIO: o YouTube pediu para parar por hoje ({why})", False)
        if r.status_code == 401:
            return _fail(cid, RECONNECT, False)
        return _fail(cid, f"o YouTube recusou o envio ({why})", False)
    session = r.headers["Location"]
    guard.mark_publish_click(cid, "youtube", {"via": "api"})
    emit(f"[youtube] enviando pela API oficial ({size / 1e6:.0f} MB)...")
    res = None
    try:
        with path.open("rb") as fh:
            res = requests.put(session, data=fh, headers={"Content-Type": "video/mp4", "Content-Length": str(size)},
                               timeout=(30, float(cfg.get("publicacao.timeout_upload_s", 900))))
    except requests.RequestException as e:
        log.warning("envio interrompido: %s", e)
    if res is None or res.status_code >= 500:  # pergunta ao YouTube se o video chegou inteiro
        time.sleep(10)
        try:
            res = requests.put(session, headers={"Content-Range": f"bytes */{size}"}, timeout=60)
        except requests.RequestException:
            res = None
        if res is None or res.status_code >= 500:
            guard.mark_publish_result(cid, "youtube", "incerto")
            return PostResult(cid, "youtube", True, ts=time.time(),
                              error="INCERTO: o envio caiu e nao consegui confirmar se o video foi recebido")
        if res.status_code == 308:
            guard.clear_click(cid, "youtube")
            return _fail(cid, "o envio caiu no meio e o YouTube nao recebeu o video inteiro", False)
    if res.status_code not in (200, 201):
        guard.clear_click(cid, "youtube")
        return _fail(cid, f"o YouTube recusou o video ({_reason(res)})", False)
    data = res.json()
    url = f"https://youtube.com/shorts/{data.get('id')}"
    guard.mark_publish_result(cid, "youtube", "confirmado", url)
    got, want = (data.get("status") or {}).get("privacyStatus"), body["status"]["privacyStatus"]
    if got and got != want:
        emit(f"[youtube] atenção: o YouTube deixou o vídeo como '{got}' (pedi '{want}').")
    return PostResult(cid, "youtube", True, url=url, ts=time.time())
