"""Menu simples, gravacao do config, espera do CAPTCHA e API do YouTube (tudo simulado: nada e publicado).

Rodar: .venv/Scripts/python tests/menu_unit.py
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TMP = Path(tempfile.mkdtemp(prefix="cortex_menu_"))

import yaml  # noqa: E402

from fabrica import autopilot, cli, config, menu, paths, policy, scheduler, ui  # noqa: E402
from fabrica.config import Config, load_config, save_value  # noqa: E402
from fabrica.models import CaptchaAppeared, ClipPlan, NeedsUserAction, RenderedClip  # noqa: E402
from fabrica.publish import ajuda, browser, guard, human, youtube_api  # noqa: E402
from fabrica import notify, publish  # noqa: E402

guard._state_dir = lambda: TMP  # nunca mexe no estado real
fails: list[str] = []


def check(name: str, cond: bool, extra: object = "") -> None:
    print(("ok    " if cond else "FALHA ") + name + (f"  [{extra}]" if extra and not cond else ""))
    if not cond:
        fails.append(name)


# ------------------------------------------------------------- 1. config
src = paths.CONFIG_PATH if paths.CONFIG_PATH.exists() else paths.ROOT / "config.exemplo.yaml"
cf = TMP / "config.yaml"
cf.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
before = cf.read_text(encoding="utf-8")
for key, val in [("publicacao.max_posts_por_dia.youtube", 3), ("publicacao.max_posts_por_dia.tiktok", 5),
                 ("publicacao.aquecimento.ativo", False), ("modo_publicacao", "auto"),
                 ("busca.palavras_chave", ["gta 6", "flow podcast"]), ("busca.modo", "misto"),
                 ("publicacao.chave_nova_de_teste", True)]:
    save_value(key, val, cf)
    d = yaml.safe_load(cf.read_text(encoding="utf-8"))
    for part in key.split("."):
        d = d[part]
    check(f"save_value {key}", d == val, d)
after = cf.read_text(encoding="utf-8")
check("save_value preserva os comentarios", after.count("#") == before.count("#"), (before.count("#"), after.count("#")))
check("save_value muda poucas linhas", sum(a not in before.splitlines() for a in after.splitlines()) <= 9)

# ------------------------------------------------------------- 2. menu
paths.CONFIG_PATH = cf
config.paths.CONFIG_PATH = cf
buf = io.StringIO()
from rich.console import Console  # noqa: E402

ui.console = Console(file=buf, width=100, force_terminal=False)
called: list[str] = []
answers: list = []
ui.ask_select = lambda q, ch, default=None: (called.append("menu:" + q + "|" + " / ".join(c[1] for c in ch)), answers.pop(0))[1]
ui.ask_text = lambda q, default="": answers.pop(0)
ui.ask_confirm = lambda q, default=True: answers.pop(0)
ui.pause = lambda *a: None
os.system = lambda *a: 0
time_sleep, time.sleep = time.sleep, lambda s: None
scheduler.autostart_enabled = lambda: False
scheduler.install_autostart = lambda: called.append("autostart")
scheduler.remove_autostart = lambda: True
autopilot.running = lambda: False
publish.check_login = lambda p, cfg=None, deep=False: True
from fabrica import andamento, fundo, painel  # noqa: E402

andamento.FILE = TMP / "andamento.json"
fundo.WANTED, fundo.REQUESTS, fundo.WORKER = TMP / "lig.json", TMP / "ped.json", TMP / "w.json"
fundo.start_autopilot = lambda wait_s=0: (called.append("piloto"), True)[1]
fundo.spawn = lambda args: called.append("spawn:" + " ".join(args)) or 1
painel.watch = lambda: called.append("painel")

answers[:] = ["auto", "ok", True, "sair"]
menu.interactive_menu()
out = buf.getvalue()
check("menu abre e liga o automatico", called.count("piloto") == 1 and "autostart" in called, called)
check("aviso de banimento aparece", "RISCO DE BANIMENTO" in out)
check("resumo do dia aparece", "TUDO OK" in out and "YouTube" in out and "TikTok" in out)
first = next(c for c in called if c.startswith("menu:O que vamos fazer?"))
check("menu principal com ate 7 opcoes", first.count(" / ") <= 6, first)
check("terminal sem bolinha, travessao ou emoji", not re.search("[—–•·●\U0001F300-\U0001FAFF]", out))

answers[:] = ["auto", "voltar", "sair"]
n = called.count("piloto")
menu.interactive_menu()
check("voltar no aviso nao liga nada", called.count("piloto") == n)

answers[:] = ["cortar", "https://youtu.be/abc", "revisar", False, "cortar", "gta 6, flow", "nao_publicar", False,
              "cortar", "", "auto", True, "sair"]
menu.interactive_menu()
runs = fundo.requests()
check("link vira corte de link", runs[0].get("urls") == ["https://youtu.be/abc"], runs)
check("assunto vira palavra-chave", runs[1].get("keywords") == ["gta 6", "flow"], runs)
check("vazio usa o que esta em alta", runs[2].get("mode") == "trends", runs)
check("pedido roda em segundo plano", "spawn:pedidos" in called, called)

# ja tem coisa rodando: mostra e nao comeca por cima
andamento.begin("pedido seu", "teste")
andamento.update(etapa=3, titulo="Cortando e editando", video=1, videos=2, video_titulo="Flow", msg="Legendando 'x'", prontos=1)
d = andamento.read()
check("andamento visivel para outra janela", d and d["etapa"] == 3 and "1 corte pronto" in andamento.describe(d), d)
buf.truncate(0)
answers[:] = ["cortar", "voltar", "sair"]
menu.interactive_menu()
out = buf.getvalue()
check("menu avisa que ja tem algo rodando", "Já tem algo rodando" in out and "Cortando e editando" in out, out[-600:])
check("menu oferece acompanhar", any(c.startswith("menu:O que vamos") and "Acompanhar" in c for c in called))
from fabrica.pipeline import RunLock  # noqa: E402
from fabrica import pipeline  # noqa: E402

pipeline.LOCK = TMP / "rodada.lock"
pipeline.LOCK.write_text(json.dumps({"pid": os.getpid(), "nasceu": 1.0, "ts": time.time()}), encoding="utf-8")
check("trava de processo morto com PID reaproveitado nao vale", not andamento.alive(json.loads(pipeline.LOCK.read_text())))
andamento.end()
check("acabou: some do andamento", andamento.read() is None)
snap = painel.snapshot(load_config())
txt = painel.summary(snap).plain
check("resumo diz tudo em poucas linhas", "Automático" in txt and "YouTube" in txt and len(txt.splitlines()) <= 12, txt)
check("quando() humano", "daqui 5 h" in painel.when(time.time() + 5 * 3600) and "daqui 2 dias" in painel.when(time.time() + 50 * 3600))
con = Console(file=io.StringIO(), width=120, height=45)
con.print(painel.render(snap))
check("painel desenha sem erro", "NADA RODANDO" in con.file.getvalue())

# fila de pedidos: um por vez, na ordem
fundo._save([{"publish": "revisar", "urls": ["a"]}, {"publish": "revisar", "urls": ["b"]}])
done: list = []
fundo.serve_requests(load_config, lambda c, r: (done.append(r["urls"][0]), 0)[1])
check("pedidos atendidos na ordem", done == ["a", "b"] and fundo.requests() == [], done)

answers[:] = ["ajustes", "dia", "2", "4", "slow", "voltar", "sair"]
menu.interactive_menu()
y = yaml.safe_load(cf.read_text(encoding="utf-8"))["publicacao"]
check("ajustes gravam videos por dia", y["max_posts_por_dia"] == {"youtube": 2, "tiktok": 4}, y["max_posts_por_dia"])
check("ajustes ligam o comeco devagar", y["aquecimento"]["ativo"] is True)
time.sleep = time_sleep

# ------------------------------------------------------------- 3. plano por dia
cfg = load_config()
st = policy.plan_steps("tiktok", cfg)
check("plano por dia cresce ate o teto", st[-1][1] == 4 and all(a[0] < b[0] for a, b in zip(st, st[1:])), st)

# ------------------------------------------------------------- 4. CAPTCHA: so o dono resolve
moves: list[bool] = []
ajuda._move = lambda page, visible: (moves.append(visible), True)[1]
ajuda._beep = lambda: None
notify.toast = lambda *a, **k: True
browser._hidden_window = lambda cfg: True


class Page:
    def __init__(self, solve_after: float):
        self.t = time.time() + solve_after

    def wait_for_timeout(self, ms):
        time.sleep(ms / 1000)

    def check(self):
        if time.time() < self.t:
            raise CaptchaAppeared("ACAO_NECESSARIA: captcha")


ccfg = Config({"publicacao": {"espera_captcha_min": 0.05, "captcha_por_dia": 2}}) if not isinstance(cfg, dict) else cfg
pg = Page(0.5)
ev: list[str] = []
ok = ajuda.wait_owner(pg, "tiktok", pg.check, ev.append, ccfg, clear_s=0.3, poll_ms=100)
check("dono resolveu: continua o post", ok and moves == [True, False], (ok, moves, ev))
check("aviso some do painel depois", guard.waiting() == {})
pg = Page(99)
check("ninguem resolveu: para", ajuda.wait_owner(pg, "tiktok", pg.check, ev.append, ccfg, 0.3, 100) is False)
check("terceiro CAPTCHA no dia: nem abre, pausa", ajuda.wait_owner(Page(0), "tiktok", pg.check, ev.append, ccfg) is False
      and moves == [True, False, True, False], moves)

a = human.Actor.__new__(human.Actor)
a.page, a.platform, a.emit, a.cfg = None, "youtube", ev.append, ccfg
a._check = lambda: (_ for _ in ()).throw(CaptchaAppeared("x"))
ajuda.wait_owner = lambda *x, **k: True
check("ator segue depois que o dono resolve", a.blockers() is True)
ajuda.wait_owner = lambda *x, **k: False
try:
    a.blockers()
    check("sem resolver, o ator para", False)
except NeedsUserAction:
    check("sem resolver, o ator para", True)

# ------------------------------------------------------------- 5. API oficial do YouTube
youtube_api.CLIENT_FILE, youtube_api.TOKEN_FILE = TMP / "cli.json", TMP / "tok.bin"
check("sem cliente a API fica desligada", not youtube_api.enabled(cfg) and not youtube_api.ready(cfg))
youtube_api.CLIENT_FILE.write_text(json.dumps({"installed": {"client_id": "x", "client_secret": "y"}}), encoding="utf-8")
youtube_api._save_token({"access_token": "segredo123", "refresh_token": "r", "expira": time.time() + 999})
check("token criptografado no disco", b"segredo123" not in youtube_api.TOKEN_FILE.read_bytes() and
      youtube_api._load_token()["access_token"] == "segredo123")
check("API conectada e pronta", youtube_api.connected() and youtube_api.ready(cfg))
vid = TMP / "v.mp4"
vid.write_bytes(b"0" * 2048)
sent: dict = {}


class R(SimpleNamespace):
    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self.body


def fake_post(url, **k):
    sent["meta"] = k.get("json")
    return R(status_code=sent.get("post", 200), headers={"Location": "https://up/1"},
             body={"error": {"errors": [{"reason": "quotaExceeded"}]}})


def fake_put(url, **k):
    sent["put"] = sent.get("put", 0) + 1
    st = sent["seq"].pop(0)
    if st == "erro":
        raise youtube_api.requests.ConnectionError("caiu")
    return R(status_code=st, headers={}, body={"id": "ABC", "status": {"privacyStatus": "public"}})


youtube_api.requests = SimpleNamespace(post=fake_post, put=fake_put, get=None, ConnectionError=ConnectionError,
                                       RequestException=Exception, Response=object)


def clip(i):
    pl = ClipPlan(id=i, source_id="youtube:x", start=0, end=20, title="Teste <b>", reason="", score=1) \
        if "reason" in ClipPlan.__dataclass_fields__ else ClipPlan(id=i, source_id="youtube:x", start=0, end=20, title="Teste")
    return RenderedClip(plan=pl, path=str(vid), duration=20, layout="full") if "layout" in RenderedClip.__dataclass_fields__ \
        else RenderedClip(plan=pl, path=str(vid), duration=20)


real_sleep, youtube_api.time.sleep = time.sleep, lambda s: None
sent["seq"] = [200]
r = youtube_api.upload(clip("c1"), cfg, ("Titulo <x>", "desc"))
check("envio normal", r.ok and r.url.endswith("ABC") and not r.error, r)
check("metadados: publico, nao infantil, sem < >", sent["meta"]["status"]["selfDeclaredMadeForKids"] is False
      and "<" not in sent["meta"]["snippet"]["title"], sent["meta"])
check("registro impede reenvio", guard.publish_clicked("c1", "youtube")["estado"] == "confirmado")
sent["seq"] = ["erro", 308]
r = youtube_api.upload(clip("c2"), cfg, ("t", "d"))
check("caiu no meio e nao chegou: falha limpa", not r.ok and guard.publish_clicked("c2", "youtube") is None, r)
sent["seq"] = ["erro", "erro"]
r = youtube_api.upload(clip("c3"), cfg, ("t", "d"))
check("sem confirmacao: INCERTO, nunca reenvia", r.ok and r.error.startswith("INCERTO")
      and guard.publish_clicked("c3", "youtube") is not None, r)
sent["seq"] = ["erro", 200]
r = youtube_api.upload(clip("c4"), cfg, ("t", "d"))
check("caiu na resposta mas chegou: ok", r.ok and r.url and not r.error, r)
sent["post"] = 403
r = youtube_api.upload(clip("c5"), cfg, ("t", "d"))
check("limite da rede: para", not r.ok and r.error.startswith("LIMITE_DIARIO"), r)
check("limite conta como sinal para pausar", publish.is_risk_signal(r.error))
time.sleep = real_sleep

print(f"\n{'TUDO OK' if not fails else 'FALHAS: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
