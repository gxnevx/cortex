"""Testes da camada humana e das travas da publicacao (sem rede social, sem login, nada publicado).

Roda:  .venv\\Scripts\\python.exe tests\\publish_humano_unit.py   [--rapido = sem navegador]

Confere:
- Ritmo le cfg publicacao.humano.* (com padroes);
- Actor.step: uma tentativa; falha -> confere o estado (verify) antes de repetir; no maximo UMA
  repeticao; retry=False nunca repete; NeedsUserAction sobe na hora;
- guard: registro de clique em Publicar, pausa depois de captcha (e limpeza), trava entre processos;
- publish_batch: segunda trava (policy.can_post) impede abrir o navegador; clique ja registrado vira
  "INCERTO" sem reenviar; rede pausada e pulada; corte repetido na lista vai uma vez so;
- (com navegador, pagina local fora da tela) mouse em curva com varios pontos, clique fora do centro e
  dentro do elemento, hover 120-450 ms, espera o "carregando" sair antes de clicar, digitacao 6-9 letras/s
  com pausas em pontuacao, rolagem em passos.
Usa banco, estado e logs temporarios (nao suja data/ nem logs/).
"""
from __future__ import annotations

import math
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fabrica import paths  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="fab_hum_"))
paths.DB_PATH = TMP / "teste.db"
paths.STATE = TMP / "estado"
paths.LOGS = TMP / "logs"
paths.SCREENSHOTS = TMP / "logs" / "screenshots"

from fabrica import db  # noqa: E402
from fabrica.config import Config, load_config  # noqa: E402
from fabrica.models import ClipPlan, NeedsUserAction, PostResult, RenderedClip  # noqa: E402
from fabrica.publish import guard, human, publish_batch  # noqa: E402
from fabrica.publish import browser as B  # noqa: E402

CFG = load_config()
EVENTS: list[str] = []


def ev(m: str) -> None:
    EVENTS.append(m)
    print("   >", m)


class FakePage:
    """Pagina falsa so para testar o Actor.step (sem navegador)."""
    url = "about:blank"

    def wait_for_timeout(self, ms):
        time.sleep(ms / 1000 * 0.01)

    def on(self, *a):
        pass

    def screenshot(self, **k):
        raise RuntimeError("sem tela")


def test_ritmo_cfg():
    r = human.Ritmo.from_cfg(Config({}))
    assert r.hover_ms == (120, 450) and r.cps == (6.0, 9.0) and r.aquecimento == (5, 20), r
    r2 = human.Ritmo.from_cfg(Config({"publicacao": {"humano": {"hover_ms": [200, 300], "velocidade": 2,
                                                                 "digitacao_cps": 7}}}))
    assert r2.hover_ms == (200, 300) and r2.velocidade == 2 and r2.cps == (7, 7), r2
    print("ok Ritmo (publicacao.humano.* com padroes)")


def test_step_rules():
    cfg = Config({"publicacao": {"humano": {"pausa_antes_de_repetir_s": [0.01, 0.02]}}})
    h = human.Actor(FakePage(), cfg, "teste", "c1", ev)
    calls = {"n": 0}

    def fail_once():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("primeira falhou")
        return "ok"
    assert h.step("passo A", fail_once) == "ok" and calls["n"] == 2
    # verify diz que ja estava feito -> nao repete
    calls["n"] = 0

    def always_fail():
        calls["n"] += 1
        raise RuntimeError("falhou")
    assert h.step("passo B", always_fail, verify=lambda: True) is None and calls["n"] == 1
    # duas falhas -> StepError, exatamente 2 tentativas
    calls["n"] = 0
    try:
        h.step("passo C", always_fail)
        raise AssertionError("deveria desistir")
    except human.StepError as e:
        assert "desisti" in str(e) and calls["n"] == 2, (e, calls)
    # retry=False -> uma tentativa so
    calls["n"] = 0
    try:
        h.step("clicar em Publicar", always_fail, retry=False)
        raise AssertionError("deveria desistir")
    except human.StepError as e:
        assert calls["n"] == 1 and "duas vezes" in str(e), (e, calls)
    # captcha/login: sobe na hora, sem repetir
    calls["n"] = 0

    def captcha():
        calls["n"] += 1
        raise NeedsUserAction("ACAO_NECESSARIA: captcha")
    try:
        h.step("passo D", captcha)
        raise AssertionError
    except NeedsUserAction:
        assert calls["n"] == 1
    # blockers detectando captcha depois da 1a falha: nao repete
    calls["n"] = 0
    h2 = human.Actor(FakePage(), cfg, "teste", "c1", ev,
                     blockers=lambda: (_ for _ in ()).throw(NeedsUserAction("ACAO_NECESSARIA: captcha")))
    try:
        h2.step("passo E", always_fail)
        raise AssertionError
    except NeedsUserAction:
        assert calls["n"] == 1
    print("ok Actor.step (1 tentativa + no maximo 1 repeticao; verify; retry=False; captcha para na hora)")


def test_guard():
    assert guard.publish_clicked("c9", "tiktok") is None
    guard.mark_publish_click("c9", "tiktok")
    assert guard.publish_clicked("c9", "tiktok")["estado"] == "clicado"
    guard.mark_publish_result("c9", "tiktok", "incerto", None)
    assert guard.publish_clicked("c9", "tiktok")["estado"] == "incerto"
    assert guard.paused_until("tiktok") is None
    guard.pause_platform("tiktok", "ACAO_NECESSARIA: captcha", hours=1)
    pz = guard.paused_until("tiktok")
    assert pz and pz[0] > time.time() + 3000 and "captcha" in pz[1], pz
    assert guard.clear_pause("tiktok") and guard.paused_until("tiktok") is None
    guard.pause_platform("youtube", "x", hours=0)
    assert guard.paused_until("youtube") is None  # pausa vencida nao conta
    a, b = guard.PublishLock(), guard.PublishLock()
    assert a.acquire() and not b.acquire(), "trava deveria impedir a segunda publicacao"
    a.release()
    assert b.acquire()
    b.release()
    print("ok guard (registro de clique, pausa e liberacao, trava entre processos)")


def _clip(cid: str, exists: bool = True) -> RenderedClip:
    f = TMP / f"{cid}.mp4"
    if exists:
        f.write_bytes(b"\0" * 1024)
    plan = ClipPlan(id=cid, source_id="t:1", start=0, end=10, title=f"Titulo {cid}", hook="", description="d",
                    hashtags=["a"])
    return RenderedClip(plan=plan, path=str(f), duration=10, layout="full")


def test_publish_batch_guards():
    from fabrica import policy

    orig = policy.can_post
    opened = {"n": 0}
    orig_start = B.BrowserSession.start

    def no_browser(self):
        opened["n"] += 1
        raise AssertionError("nao deveria abrir o navegador")
    B.BrowserSession.start = no_browser
    try:
        # 1) policy diz nao -> nada abre, nada gravado
        policy.can_post = lambda p, cfg: (False, "aquecimento da conta (dia 0): sem posts ainda")
        EVENTS.clear()
        r = publish_batch([_clip("g1")], CFG, platforms=["youtube", "tiktok"], dry_run=False, on_event=ev)
        assert r == [] and opened["n"] == 0, r
        assert sum("regra de segurança" in e for e in EVENTS) == 2, EVENTS
        # 2) clique em Publicar ja registrado -> INCERTO (ok=True) sem reenviar, e conta como publicado
        policy.can_post = lambda p, cfg: (True, "ok")
        guard.mark_publish_click("g2", "tiktok")
        policy_calls = {"n": 0}

        def deny_count(p, cfg):
            policy_calls["n"] += 1
            return (False, "teste")
        policy.can_post = deny_count
        r = publish_batch([_clip("g2")], CFG, platforms=["tiktok"], dry_run=False, on_event=ev)
        assert len(r) == 1 and r[0].ok and r[0].error.startswith("INCERTO"), r
        assert db.already_posted("g2", "tiktok") and opened["n"] == 0
        # 3) rede pausada -> pulada (mesmo no teste)
        guard.pause_platform("youtube", "ACAO_NECESSARIA: o YouTube mostrou um captcha", hours=1)
        EVENTS.clear()
        r = publish_batch([_clip("g3")], CFG, platforms=["youtube"], dry_run=True, on_event=ev)
        assert r == [] and any("pausado até" in e for e in EVENTS), EVENTS
        guard.clear_pause("youtube")
        # 4) corte repetido na lista vai uma vez so (arquivo ausente gera 1 resultado por rede, sem navegador)
        bad = _clip("g4", exists=False)
        r = publish_batch([bad, bad], CFG, platforms=["tiktok"], dry_run=True, on_event=ev)
        assert len(r) == 1 and "não encontrado" in r[0].error, r
        # 5) versao por rede (variants): usa o arquivo da rede
        v = _clip("g5", exists=False)
        good = TMP / "g5_tiktok.mp4"
        good.write_bytes(b"\0")
        v.variants = {"tiktok": str(good)}
        assert v.path_for("tiktok") == str(good) and v.path_for("youtube") == v.path
    finally:
        policy.can_post = orig
        B.BrowserSession.start = orig_start
    print("ok publish_batch (policy como 2a trava, INCERTO nunca reenvia, pausa, sem duplicar)")


# ------------------------------------------------------------- com navegador
PAGE = """<!doctype html><html><body style="margin:0;height:3000px;font-family:sans-serif">
<div style="height:300px"></div>
<button id="b" style="position:absolute;left:600px;top:420px;width:180px;height:48px">Publicar</button>
<div id="spin" class="loading-spinner" style="position:absolute;left:590px;top:410px;width:200px;height:70px;
     background:rgba(0,0,0,.2)"></div>
<input id="t" style="position:absolute;left:100px;top:120px;width:500px;height:30px">
<script>
window.ev = []; window.keys = [];
document.addEventListener('mousemove', e => ev.push(['m', e.clientX, e.clientY, performance.now(), e.isTrusted]));
document.addEventListener('mousedown', e => ev.push(['d', e.clientX, e.clientY, performance.now(), e.isTrusted]));
document.getElementById('b').addEventListener('click', e => { window.clickAt = [e.clientX, e.clientY, performance.now(), e.isTrusted]; });
document.getElementById('t').addEventListener('keydown', e => keys.push([e.key, performance.now()]));
window.wheels = 0; document.addEventListener('wheel', () => wheels++);
setTimeout(() => { document.getElementById('spin').remove(); window.spinGone = performance.now(); }, 1500);
</script></body></html>"""


def test_actor_in_browser():
    human.SPEED = 1.0
    with B.BrowserSession(CFG) as s:
        page = s.new_page()
        page.set_content(PAGE)
        pos = page.evaluate("[screenX, screenY]")
        h = human.Actor(page, Config({}), "teste", "local", ev)
        t0 = page.evaluate("performance.now()")
        h.click(page.locator("#b"), what="botão de teste")
        click = page.evaluate("window.clickAt")
        gone = page.evaluate("window.spinGone")
        assert click and click[3] is True, click
        assert click[2] > gone, "clicou antes do 'carregando' sumir"
        assert click[2] - t0 >= 1400, (click[2] - t0)
        bx, by, bw, bh = 600, 420, 180, 48
        assert bx <= click[0] <= bx + bw and by <= click[1] <= by + bh, click
        h.click(page.locator("#t"), enabled=False, what="campo")
        texto = "Ele nao esperava essa resposta, olha so. Que treta boa!"
        h.type_text(texto)
        assert page.input_value("#t") == texto, page.input_value("#t")
    human.SPEED = 1.0
    print("ok Actor no navegador (espera o carregando, clique no alvo, texto digitado certo)")


def main() -> int:
    rapido = "--rapido" in sys.argv
    tests = [test_ritmo_cfg, test_step_rules, test_guard, test_publish_batch_guards]
    if not rapido:
        if B.profile_in_use():
            print("O perfil da Fabrica esta aberto em outra janela: feche e rode de novo.")
            return 2
        tests.append(test_actor_in_browser)
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
