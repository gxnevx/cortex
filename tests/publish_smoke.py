"""Teste de fumaca do publicador SEM login (nao publica nada, nao digita senha).

Roda:  .venv\\Scripts\\python.exe tests\\publish_smoke.py   [--rapido = so testes sem navegador]

Confere:
- build_post_text (limites, emojis, < >, #Shorts, Fonte, rodape, Parte X/Y);
- deteccao de perfil travado (Chrome aberto "na mao" com o perfil da Fabrica);
- login() percebe a janela fechada e devolve False sem sessao;
- sessao CDP: Chrome real abre, paginas de upload caem no login, check_login -> False,
  upload() do YouTube/TikTok -> "ACAO_NECESSARIA: faca login...", arquivo > 50 MB pelo CDP;
- export_cookies_txt com o perfil deslogado (com e sem sessao aberta);
- publish_batch (modo teste) -> um resultado ACAO_NECESSARIA por rede, rede pausada, salvo no banco;
- pulos sem abrir navegador: ja publicado e limite diario;
- selftest -> ok=False com erro de login.
Usa um banco e um cookies.txt temporarios (nao suja data/).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fabrica import paths  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="fab_pub_"))
paths.DB_PATH = TMP / "teste.db"          # banco isolado (antes de qualquer db.conn())
paths.COOKIES_TXT = TMP / "cookies.txt"   # nao sobrescreve o cookies.txt real
from fabrica import hashtags as _hashtags  # noqa: E402  memoria de hashtags/CTA tambem isolada

_hashtags.MEMORY_FILE = TMP / "hashtags_recentes.json"
_hashtags.CTA_MEMORY_FILE = TMP / "cta_recentes.json"
_hashtags.TRENDING_FILE = TMP / "hashtags_trending.json"

from fabrica import db  # noqa: E402
from fabrica.config import load_config  # noqa: E402
from fabrica.models import ClipPlan, PostResult, RenderedClip  # noqa: E402
from fabrica.publish import browser as B  # noqa: E402
from fabrica.publish import build_post_text, check_login, export_cookies_txt, publish_batch, selftest  # noqa: E402
from fabrica.publish import human, tiktok, youtube  # noqa: E402
from fabrica.publish.captions import split_caption  # noqa: E402

human.SPEED = 0.2
CFG = load_config()
CFG.set("publicacao.intervalo_teste_s", [1, 2])
EVENTS: list[str] = []


def ev(msg: str) -> None:
    EVENTS.append(msg)
    print("   >", msg)


def plan(**kw) -> ClipPlan:
    d = dict(id="teste-c1", source_id="youtube:abc", start=10, end=70,
             title="Ele N\u00c3O esperava essa resposta \U0001f631\U0001f525 <script>", hook="O clima esquentou",
             description="Trecho do podcast de ontem.", hashtags=["podcast", "#Humor", "humor", "gta 6"])
    d.update(kw)
    return ClipPlan(**d)


# ------------------------------------------------------------- sem navegador
BANNED = ("\u2022", "\u00b7", "\u2014", "\u2013")


def _no_emoji(s: str) -> bool:
    from fabrica.publish.captions import _EMOJI_RE
    return not _EMOJI_RE.search(s)


def test_captions():
    CFG.set("publicacao.hashtags_fixas", ["#cortes"])
    CFG.set("publicacao.max_hashtags", 5)
    from fabrica.config import Config
    from fabrica.publish.captions import emojis_allowed
    assert emojis_allowed(Config({})) is True  # sem a chave: emojis ligados nos posts
    CFG.set("conteudo.emojis", True)
    p = plan()
    # conteudo.emojis: true -> emojis mantidos nos posts
    t, d = build_post_text(p, "youtube", CFG, video_title="Podcast #123 <ao vivo>", channel="Canal X")
    assert len(t) <= 100 and "\U0001F631\U0001F525" in t and "<" not in t and ">" not in t, t
    assert "<" not in d and ">" not in d, d
    assert d.rstrip().endswith("#Shorts"), d
    assert "Fonte: Canal X" in d and "O clima esquentou" in d, d
    assert d.lower().count("#humor") == 1 and "#gta6" in d and "#cortes" in d, d
    # conteudo.emojis: false -> tira todos
    CFG.set("conteudo.emojis", False)
    tn, dn = build_post_text(plan(description="Bora \U0001F468\u200d\U0001F469\u200d\U0001F467 \U0001F1E7\U0001F1F7 1\ufe0f\u20e3"),
                             "youtube", CFG, channel="Canal X")
    assert tn == "Ele NÃO esperava essa resposta script", tn
    assert _no_emoji(tn) and _no_emoji(dn) and "Bora" in dn, (tn, dn)
    CFG.set("conteudo.emojis", True)
    # pontuacao proibida (travessao, meia-risca, marcador, ponto medio)
    pp = plan(title="Treta \u2014 parte boa \u00b7 ao vivo \u2022 agora \u2013 ja",
              description="\u2022 item um\n\u2022 item dois", hook="Gancho \u2014 forte")
    for plat in ("youtube", "tiktok"):
        tp, dp = build_post_text(pp, plat, CFG, video_title="Video \u2014 original", channel="Canal \u00b7 X")
        assert not any(b in tp + dp for b in BANNED), (tp, dp)
    tp, dp = build_post_text(pp, "youtube", CFG)
    assert tp == "Treta - parte boa, ao vivo, agora - ja", tp
    assert "- item um\n- item dois" in dp, dp
    # limite de hashtags (padrao 5 + #Shorts no YouTube)
    many = plan(hashtags=[f"tag{i}" for i in range(12)])
    _, dm = build_post_text(many, "youtube", CFG)
    assert dm.split("\n")[-1].count("#") == 6, dm.split("\n")[-1]
    _, cm = build_post_text(many, "tiktok", CFG)
    assert split_caption(cm)[1] == ["#tag0", "#tag1", "#tag2", "#tag3", "#tag4"], cm
    # modo do TikTok
    assert tiktok.tiktok_mode(CFG) in ("auto", "semi")
    CFG.set("publicacao.tiktok_modo", "SEMI")
    assert tiktok.tiktok_mode(CFG) == "semi"
    CFG.set("publicacao.tiktok_modo", "auto")
    assert tiktok.tiktok_mode(CFG) == "auto"
    # titulo longo: corta em 100 mantendo o sufixo da serie
    longp = plan(title="Muito texto " * 20 + "\U0001f525", part=2, parts_total=3, series="Treta")
    t2, d2 = build_post_text(longp, "youtube", CFG)
    assert len(t2) <= 100 and t2.endswith("(Parte 2/3)"), t2
    t3, _ = build_post_text(plan(title="Treta Parte 1", part=1, parts_total=2), "youtube", CFG)
    assert t3.count("Parte") == 1 and t3.endswith("(Parte 1/2)"), t3
    # creditar_fonte desligado + rodape
    CFG.set("publicacao.creditar_fonte", False)
    CFG.set("publicacao.descricao_rodape", "Siga para mais cortes!")
    _, d4 = build_post_text(p, "youtube", CFG, channel="Canal X")
    assert "Fonte:" not in d4 and "Siga para mais cortes!" in d4, d4
    CFG.set("publicacao.creditar_fonte", True)
    CFG.set("publicacao.descricao_rodape", "")
    # TikTok
    t5, cap = build_post_text(plan(description="x" * 5000), "tiktok", CFG, channel="Canal X")
    assert len(cap) <= 2200 and "#Shorts" not in cap and "Fonte: Canal X" in cap, cap
    text, tags = split_caption(cap)
    assert tags and all(x.startswith("#") for x in tags) and "#podcast" in tags, (text, tags)
    assert text.startswith(t5), (text, t5)
    huge = plan(title="\U0001F525" * 3000, hashtags=[f"tag{i}" for i in range(40)])
    _, cap2 = build_post_text(huge, "tiktok", CFG)
    assert len(cap2) <= 2200, len(cap2)
    CFG.set("conteudo.emojis", False)
    th, cap3 = build_post_text(huge, "tiktok", CFG)
    assert len(cap3) <= 2200 and th == "O clima esquentou", (th, len(cap3))  # so emoji -> usa o gancho
    CFG.set("conteudo.emojis", True)
    # mensagens de terminal/log nunca levam emoji
    from fabrica.publish import _emitter
    got: list[str] = []
    _emitter(got.append)("[youtube] enviando: Titulo \U0001F525\U0001F631 ok")
    assert got == ["[youtube] enviando: Titulo ok"], got
    print("ok build_post_text (emojis on/off, pontuacao proibida, Parte X/Y, limites, hashtags, log sem emoji)")


def test_netscape_writer():
    f = TMP / "ck.txt"
    n = B.write_netscape([
        {"name": "A", "value": "1", "domain": ".youtube.com", "path": "/", "expires": 2e9, "secure": True,
         "httpOnly": True},
        {"name": "B", "value": "2", "domain": "www.tiktok.com", "path": "/", "expires": -1, "secure": False},
    ], f)
    assert n == 2, n
    body = f.read_text(encoding="utf-8")
    assert body.startswith("# Netscape HTTP Cookie File"), body
    assert "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t2000000000\tA\t1" in body, body
    assert "www.tiktok.com\tFALSE\t/\tFALSE\t0\tB\t2" in body, body
    # o leitor de cookies do yt-dlp aceita o arquivo
    from yt_dlp.cookies import YoutubeDLCookieJar
    jar = YoutubeDLCookieJar(str(f))
    jar.load(ignore_discard=True, ignore_expires=True)
    assert {c.name for c in jar} == {"A", "B"}, list(jar)
    print("ok cookies.txt (Netscape) + leitura pelo yt-dlp")


def test_login_detection_logic():
    now = time.time()
    yt = [{"domain": ".youtube.com", "name": "SAPISID", "expires": now + 1e6},
          {"domain": ".youtube.com", "name": "__Secure-3PSID", "expires": now + 1e6}]
    assert B._has_login(yt, "youtube")
    assert not B._has_login(yt[:1], "youtube")
    assert not B._has_login([dict(c, expires=now - 10) for c in yt], "youtube")
    assert not B._has_login([dict(c, domain=".google.com") for c in yt], "youtube")
    assert B._has_login([{"domain": ".tiktok.com", "name": "sessionid", "expires": now + 1e6, "value": "x"}], "tiktok")
    assert not B._has_login([{"domain": ".tiktok.com", "name": "sessionid", "expires": now + 1e6, "value": ""}], "tiktok")
    print("ok regras de cookie de login")


def make_clip(cid: str = "teste-c1") -> RenderedClip:
    out = TMP / f"{cid}.mp4"
    if not out.exists():
        from fabrica import tools
        subprocess.run([tools.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=2:r=30",
                        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-shortest", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(out)], check=True)
    return RenderedClip(plan=plan(id=cid), path=str(out), duration=2.0, layout="full")


def test_skips_without_browser():
    clip = make_clip("teste-pulo")
    db.save_post(PostResult("teste-pulo", "youtube", True, url="https://youtube.com/shorts/x", ts=time.time()))
    assert db.already_posted("teste-pulo", "youtube")
    t0 = time.time()
    r = publish_batch([clip], CFG, platforms=["youtube"], dry_run=False, on_event=ev)
    assert r == [] and time.time() - t0 < 5, r
    # limite diario: 1 post hoje e limite 1 -> nada abre
    CFG.set("publicacao.max_posts_por_dia", {"youtube": 1, "tiktok": 0})
    r = publish_batch([make_clip("teste-limite")], CFG, platforms=["youtube"], dry_run=False, on_event=ev)
    assert r == [] and any("limite diário" in e for e in EVENTS), EVENTS[-3:]
    CFG.set("publicacao.max_posts_por_dia", {"youtube": 10, "tiktok": 8})
    # arquivo inexistente vira resultado de erro (sem navegador)
    bad = RenderedClip(plan=plan(id="teste-sem-arquivo"), path=str(TMP / "nao_existe.mp4"), duration=1, layout="full")
    r = publish_batch([bad], CFG, platforms=["tiktok"], dry_run=True, on_event=ev)
    assert len(r) == 1 and not r[0].ok and "não encontrado" in r[0].error, r
    print("ok pulos sem navegador (ja publicado, limite diario, arquivo ausente)")


# ---------------------------------------------------------- com navegador
def _profile_browser_pids() -> list[int]:
    """PIDs do processo principal do Chrome/Edge que usa O PERFIL DA FABRICA (nunca o Chrome do usuario)."""
    prof = str(paths.BROWSER_PROFILE).replace("'", "''")
    ps = ("Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'chrome.exe' -or $_.Name -eq 'msedge.exe') "
          f"-and $_.CommandLine -like '*{prof}*' -and $_.CommandLine -notlike '*--type=*' }} | "
          "ForEach-Object { $_.ProcessId }")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=60)
    return [int(x) for x in out.stdout.split() if x.strip().isdigit()]


def _close_profile_browser(timeout: float = 20) -> None:
    for pid in _profile_browser_pids():
        subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True)  # fechamento normal (WM_CLOSE)
    if B.wait_profile_free(timeout):
        return
    for pid in _profile_browser_pids():
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    assert B.wait_profile_free(10), "perfil continuou travado"


def test_profile_lock():
    assert not B.profile_in_use(), "perfil ja estava em uso antes do teste"
    exe, _ = B.browser_exe(CFG)
    proc = subprocess.Popen([exe] + B._base_args(CFG) + ["--new-window", "about:blank"])
    try:
        end = time.time() + 20
        while not B.profile_in_use() and time.time() < end:
            time.sleep(0.5)
        assert B.profile_in_use(), "lock nao detectado"
        assert B.devtools_port() is None
        try:
            B.BrowserSession(CFG).start()
            raise AssertionError("deveria recusar perfil em uso")
        except B.ProfileInUseError as e:
            assert "Feche a janela do navegador da Fábrica" in str(e), e
        r = publish_batch([make_clip()], CFG, platforms=["youtube", "tiktok"], dry_run=True, on_event=ev)
        assert len(r) == 2 and all((not x.ok) and x.error.startswith("ACAO_NECESSARIA") and "Feche a janela" in x.error
                                   for x in r), r
        assert export_cookies_txt(CFG) is None
        assert check_login("youtube", CFG) is False  # banco travado -> False sem quebrar
        s = selftest("tiktok", CFG)
        assert s["ok"] is False and "Feche a janela" in s["erro"], s
        try:
            B.login("youtube", CFG, timeout_s=5, on_event=ev)
            raise AssertionError("login deveria recusar perfil em uso")
        except B.ProfileInUseError:
            pass
    finally:
        _close_profile_browser()
        try:
            proc.wait(10)
        except Exception:
            pass
    assert not B.profile_in_use()
    print("ok deteccao de perfil travado (sessao, publish_batch, export, selftest, login)")


def test_login_window_close():
    """login() abre o Chrome normal; simulamos o usuario fechando a janela sem logar."""
    out: dict = {}
    th = threading.Thread(target=lambda: out.setdefault("r", B.login("tiktok", CFG, timeout_s=90, on_event=ev)))
    t0 = time.time()
    th.start()
    end = time.time() + 30
    while not B.profile_in_use() and time.time() < end:
        time.sleep(0.5)
    assert B.profile_in_use(), "janela de login nao abriu"
    assert B.devtools_port() is None, "janela de login NAO deve ter porta de automacao"
    time.sleep(6)  # deixa a pagina de login carregar
    _close_profile_browser()
    th.join(40)
    assert not th.is_alive(), "login() nao percebeu a janela fechada"
    assert out.get("r") is False, out
    print(f"ok login(): detectou a janela fechada em {time.time() - t0:.0f}s e devolveu False (sem sessao)")


def test_cdp_session_logged_out():
    with B.BrowserSession(CFG) as s:
        assert s.launched and s.port, "sessao CDP nao abriu"
        assert B.profile_in_use()
        page = s.new_page()
        # arquivo > 50 MB pelo CDP (is_local=True)
        page.set_content('<input type=file id=f>')
        big = TMP / "grande.bin"
        with open(big, "wb") as fh:
            fh.seek(55 * 1024 * 1024 - 1)
            fh.write(b"\0")
        page.set_input_files("#f", str(big))
        assert page.evaluate("document.getElementById('f').files[0].size") == 55 * 1024 * 1024
        big.unlink()
        # paginas de upload deslogadas
        page.goto(youtube.UPLOAD_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        assert youtube.is_login_wall(page), page.url
        page.goto(tiktok.UPLOAD_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        assert tiktok.is_login_wall(page), page.url
        print(f"   studio/tiktok deslogados -> {page.url[:90]}")
        # check_login com o navegador aberto (via CDP)
        assert check_login("youtube", CFG) is False and check_login("tiktok", CFG) is False
        clip = make_clip()
        for mod in (youtube, tiktok):
            pg = s.new_page()
            r = mod.upload(pg, clip, CFG, dry_run=True, on_event=ev)
            pg.close()
            assert not r.ok and r.error.startswith("ACAO_NECESSARIA:") and "login" in r.error, r
            assert r.screenshot and Path(r.screenshot).exists(), r
            Path(r.screenshot).unlink()
            print(f"   {mod.PLATFORM}.upload -> {r.error[:80]}")
        p = export_cookies_txt(CFG, session=s, dest=TMP / "ck_sessao.txt")
        print(f"   export com sessao aberta -> {p}")
        if p:
            assert p.read_text(encoding="utf-8").startswith("# Netscape")
    assert B.wait_profile_free(10), "perfil continuou travado depois de fechar a sessao"
    assert B.devtools_port() is None
    print("ok sessao CDP deslogada (upload -> ACAO_NECESSARIA, check_login False, arquivo grande)")


def test_attach_existing_window():
    """Se o navegador da Fabrica ja estiver aberto COM porta de automacao, a sessao reaproveita e nao fecha."""
    proc, port = B._launch_debug_browser(CFG, headless=True)
    try:
        with B.BrowserSession(CFG) as s:
            assert not s.launched and s.port == port, (s.launched, s.port, port)
            pg = s.new_page()
            pg.goto("about:blank")
        assert B.devtools_port() == port, "a sessao reaproveitada nao deveria fechar o navegador"
        # login() fecha com calma um navegador de automacao esquecido antes de abrir a janela de login
        out: dict = {}
        th = threading.Thread(target=lambda: out.setdefault("r", B.login("youtube", CFG, timeout_s=60, on_event=ev)))
        th.start()
        end = time.time() + 30
        while B.devtools_port() is not None and time.time() < end:
            time.sleep(0.5)
        assert B.devtools_port() is None, "login() nao fechou o navegador de automacao"
        end = time.time() + 30
        while not B.profile_in_use() and time.time() < end:
            time.sleep(0.5)
        time.sleep(4)
        _close_profile_browser()
        th.join(40)
        assert out.get("r") is False, out
    finally:
        if proc.poll() is None:
            B._close_debug_browser(port) if B.devtools_port() else B._kill(proc)
        if B.profile_in_use():
            _close_profile_browser()
    print("ok reaproveita janela ja aberta (sem fechar) e login() fecha a de automacao antes")


def test_closed_profile_checks():
    meta = B.read_cookie_meta()
    assert meta is not None, "banco de cookies deveria estar legivel com o navegador fechado"
    assert check_login("youtube", CFG) is False and check_login("tiktok", CFG) is False
    t0 = time.time()
    p = export_cookies_txt(CFG)  # abre o Chrome sem janela so para ler os cookies e fecha
    assert not B.profile_in_use()
    print(f"   export sem sessao ({time.time() - t0:.1f}s) -> {p}")
    if p:
        body = p.read_text(encoding="utf-8")
        assert body.startswith("# Netscape") and ("youtube.com" in body or "google.com" in body or "tiktok.com" in body)
        assert p == paths.COOKIES_TXT
    print(f"ok perfil fechado: {len(meta)} cookies lidos do SQLite, check_login False, export_cookies_txt ok")


def test_publish_batch_logged_out():
    clips = [make_clip("teste-c1"), make_clip("teste-c2")]
    EVENTS.clear()
    t0 = time.time()
    r = publish_batch(clips, CFG, platforms=["youtube", "tiktok"], dry_run=True, on_event=ev)
    # 1 resultado por rede: a 1a falha de login pausa a rede e o 2o corte fica para depois
    assert len(r) == 2, r
    assert {x.platform for x in r} == {"youtube", "tiktok"}
    assert all(not x.ok and x.dry_run and x.error.startswith("ACAO_NECESSARIA:") for x in r), r
    assert any("ficaram para depois" in e for e in EVENTS), EVENTS
    for x in r:
        if x.screenshot:
            Path(x.screenshot).unlink(missing_ok=True)
    rows = db.conn().execute("SELECT COUNT(*) FROM posts WHERE dry_run=1 AND ok=0").fetchone()[0]
    assert rows >= 2, rows
    assert not B.profile_in_use()
    print(f"ok publish_batch deslogado em {time.time() - t0:.0f}s -> 2x ACAO_NECESSARIA, salvo no banco")


def test_selftest_logged_out():
    for p in ("youtube", "tiktok"):
        s = selftest(p, CFG)
        assert s["ok"] is False and "ACAO_NECESSARIA" in (s["erro"] or "") and "login" in s["erro"], s
        assert s["checks"].get("Cookies de login no perfil") is False
        if s.get("screenshot"):
            Path(s["screenshot"]).unlink(missing_ok=True)
        print(f"   selftest {p}: {s['erro'][:70]}")
    print("ok selftest deslogado")


def main() -> int:
    rapido = "--rapido" in sys.argv
    tests = [test_captions, test_netscape_writer, test_login_detection_logic, test_skips_without_browser]
    if not rapido and (check_login("youtube", CFG) or check_login("tiktok", CFG)):
        # os testes com navegador abaixo assumem o perfil DESLOGADO; logado, eles fariam envios de teste reais
        print("Perfil da Fabrica esta LOGADO: pulando os testes com navegador (eles exigem perfil deslogado).\n"
              "Para testar logado sem publicar: tests\\publish_dryrun.py")
        rapido = True
    if not rapido:
        if B.profile_in_use():
            print("O perfil da Fabrica esta aberto em outra janela: feche e rode de novo.")
            return 2
        tests += [test_profile_lock, test_login_window_close, test_cdp_session_logged_out, test_attach_existing_window,
                  test_closed_profile_checks, test_publish_batch_logged_out, test_selftest_logged_out]
    failed = 0
    for t in tests:
        print(f"-- {t.__name__}")
        try:
            t()
        except Exception as e:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FALHOU {t.__name__}: {e}")
            if B.profile_in_use():
                try:
                    _close_profile_browser()
                except Exception:
                    pass
    try:
        db.conn().close()
    except Exception:
        pass
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)
    print("\nRESULTADO:", "TUDO OK" if not failed else f"{failed} FALHA(S)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
