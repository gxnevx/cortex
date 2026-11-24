"""Teste AO VIVO da publicacao com o perfil LOGADO, sem publicar nada.

Roda:  .venv\\Scripts\\python.exe tests\\publish_dryrun.py [--so-selftest] [--redes youtube,tiktok]
                                                         [--video work\\amostras\\v2\\v2_full.mp4]

1. selftest de cada rede: abre o Studio como uma pessoa (inicio, 5-20 s olhando, Criar/Carregar) e confere
   a pagina de upload. Nao envia nada.
2. modo teste (dry run) com um video de amostra: escolhe o arquivo, escreve titulo/descricao/legenda,
   marca as opcoes, espera o envio terminar e NAO clica em Publicar. YouTube: visibilidade Privado e o
   rascunho e apagado no fim (se nao der, o link aparece no relatorio). TikTok: "Somente voce" e Descartar.
Confere tambem que a janela do Chrome ficou FORA da tela e mostra os tempos "humanos" registrados
(logs/publicacao_ritmo.log). Usa um banco temporario (o teste nao entra no historico de posts).
"""
from __future__ import annotations

import argparse
import json
import subprocess
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

TMP = Path(tempfile.mkdtemp(prefix="fab_dry_"))
REAL_DB = paths.DB_PATH
paths.DB_PATH = TMP / "teste.db"

from fabrica import hashtags as _hashtags  # noqa: E402  memoria de hashtags/CTA isolada (o teste nao conta como post)

_hashtags.MEMORY_FILE = TMP / "hashtags_recentes.json"
_hashtags.CTA_MEMORY_FILE = TMP / "cta_recentes.json"

from fabrica import db, tools  # noqa: E402
from fabrica.config import load_config  # noqa: E402
from fabrica.models import ClipPlan, RenderedClip  # noqa: E402
from fabrica.publish import browser as B  # noqa: E402
from fabrica.publish import check_login, publish_batch, selftest  # noqa: E402

T0 = time.time()
WINDOW: list[tuple[str, list]] = []


def say(m: str) -> None:
    print(f"[{time.time() - T0:6.1f}s] {m}", flush=True)


def _watch_window() -> None:
    """Registra a posicao da janela de cada aba aberta pela publicacao (tem que estar fora da tela)."""
    orig = B.BrowserSession.new_page

    def new_page(self):
        page = orig(self)
        try:
            page.goto("about:blank")
            WINDOW.append(("aba", page.evaluate("[screenX, screenY, outerWidth, outerHeight]")))
        except Exception as e:
            WINDOW.append(("aba", [f"erro {e}"]))
        return page
    B.BrowserSession.new_page = new_page


def _duration(path: Path) -> float:
    try:
        out = subprocess.run([tools.ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of",
                              "default=nw=1:nk=1", str(path)], capture_output=True, text=True, timeout=60)
        return float(out.stdout.strip())
    except Exception:
        return 30.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--so-selftest", action="store_true")
    ap.add_argument("--redes", default="youtube,tiktok")
    ap.add_argument("--clip", help="id de um corte pronto: ensaia com o video e o texto dele")
    ap.add_argument("--video", default=str(paths.ROOT / "work" / "amostras" / "v2" / "v2_full.mp4"))
    a = ap.parse_args()
    redes = [r.strip() for r in a.redes.split(",") if r.strip()]
    cfg = load_config()
    if not cfg.get("publicacao.janela_oculta", True):
        print("publicacao.janela_oculta esta desligado no config; este teste exige a janela fora da tela.")
        return 2
    if B.profile_in_use():
        print("O perfil da Fabrica esta aberto em outra janela: feche e rode de novo.")
        return 2
    for r in redes:
        if not check_login(r, cfg):
            print(f"{r}: sem login no perfil da Fabrica (rode: cortex login {r}).")
            return 2
    _watch_window()
    report: dict = {"selftest": {}, "dry_run": [], "janela": WINDOW}
    failed = 0

    for r in redes:
        say(f"selftest {r}...")
        s = selftest(r, cfg)
        report["selftest"][r] = {k: s.get(k) for k in ("ok", "erro", "checks", "info", "ritmo", "screenshot")}
        for k, v in (s.get("checks") or {}).items():
            say(f"   [{'ok' if v else 'FALHOU'}] {k}")
        say(f"   info: {s.get('info')}  erro: {s.get('erro')}")
        failed += 0 if s.get("ok") else 1
        if s.get("erro") and ("captcha" in s["erro"].lower() or "verifica" in s["erro"].lower()):
            say("   captcha/verificacao: parando o teste (nada de repetir).")
            print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
            return 1

    if not a.so_selftest:
        video = Path(a.video)
        if not video.is_file():
            print(f"video de amostra nao encontrado: {video}")
            return 2
        plan = ClipPlan(id=f"teste-humano-{time.strftime('%H%M%S')}", source_id="amostra:v2", start=0,
                        end=_duration(video), title="Teste do CORTEX (rascunho, não publicar)",
                        hook="", description="Teste automático de envio. Este rascunho é apagado em seguida.",
                        hashtags=["cortes", "podcast"])
        clip = RenderedClip(plan=plan, path=str(video), duration=plan.end, layout="full")
        if a.clip:
            import sqlite3

            real = sqlite3.connect(f"file:{REAL_DB.as_posix()}?mode=ro", uri=True)
            row = real.execute("SELECT rendered FROM clips WHERE id=?", (a.clip,)).fetchone()
            clip = RenderedClip.from_dict(json.loads(row[0]))
            video = Path(clip.path_for(redes[0]))
        say(f"dry run com {video.name} ({plan.end:.1f}s) em {redes}...")
        eventos: list[str] = []

        def on_ev(m: str) -> None:
            eventos.append(m)
            say("   " + m)
        res = publish_batch([clip], cfg, platforms=redes, dry_run=True, on_event=on_ev)
        # sobra de teste nao e "tudo ok": descarte nao confirmado (TikTok) ou rascunho que ficou (YouTube)
        sobras = [m for m in eventos if "confirmei o descarte" in m or "ficou um rascunho" in m]
        report["sobras"] = sobras
        if sobras:
            failed += 1
            say(f"   SOBRA DE TESTE (confira na conta): {sobras}")
        for x in res:
            report["dry_run"].append(x.to_dict())
            say(f"   resultado {x.platform}: ok={x.ok} url={x.url} erro={x.error}")
            failed += 0 if x.ok else 1
        if len(res) < len(redes):
            failed += 1
            say("   faltou resultado de alguma rede (pausada ou bloqueada?)")

    off = [w for _, w in WINDOW if isinstance(w, list) and len(w) >= 2 and isinstance(w[0], (int, float))]
    hidden = bool(off) and all(w[0] <= -1000 or w[1] <= -1000 for w in off)
    say(f"janela do Chrome nas abas abertas: {[w for _, w in WINDOW]} -> {'FORA da tela' if hidden else 'VISIVEL?'}")
    failed += 0 if hidden else 1
    try:
        lines = (paths.LOGS / "publicacao_ritmo.log").read_text(encoding="utf-8").splitlines()
        start = time.strftime("%Y-%m-%d %H:%M", time.localtime(T0))
        mine = [ln for ln in lines if ln >= start[:13]] if lines else []
        idx = next((i for i, ln in enumerate(lines) if ln[:16] >= start), len(lines))
        say("tempos humanos registrados (logs/publicacao_ritmo.log):")
        for ln in lines[idx:]:
            print("   " + ln)
        del mine
    except Exception as e:
        say(f"sem log de ritmo: {e}")
    out = paths.LOGS / f"publicacao_teste_{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    say(f"relatorio: {out}")
    try:
        db.conn().close()
    except Exception:
        pass
    print("\nRESULTADO:", "TUDO OK" if not failed else f"{failed} FALHA(S)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
