"""Teste de fumaca da descoberta + download (rede de verdade).

Uso (na raiz do projeto):
    .venv\\Scripts\\python.exe tests\\discovery_smoke.py            # completo
    .venv\\Scripts\\python.exe tests\\discovery_smoke.py --rapido   # pula o modo trends do find_candidates

Faz: top 15 assuntos (com fontes e notas) -> find_candidates(keywords=["debate"], limit=5) ->
find_candidates modo trends (limit=5) -> enriquece o melhor candidato -> baixa a legenda da plataforma ->
baixa um trecho de 20 s e confere com ffprobe -> mostra os tempos. Apaga tudo que baixou no fim.
Sai com codigo 0 se tudo passou.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

from fabrica import discovery, download, log, paths  # noqa: E402
from fabrica.config import load_config  # noqa: E402
from fabrica.util import fmt_duration  # noqa: E402

TIMES: dict[str, float] = {}
FAILS: list[str] = []


def step(name: str):
    class _S:
        def __enter__(self):
            self.t = time.time()
            print(f"\n=== {name}")
            return self

        def __exit__(self, et, ev, tb):
            TIMES[name] = time.time() - self.t
            if et is not None:
                FAILS.append(f"{name}: {ev}")
                print(f"FALHOU: {ev}")
                traceback.print_exception(et, ev, tb, limit=3)
            print(f"--- {name}: {TIMES[name]:.1f}s")
            return True   # continua os proximos passos
    return _S()


def show_cands(cands):
    for c in cands:
        print(f"  {c.score:5.1f}  {c.id:42s} {fmt_duration(c.duration):>8s}  views={c.views}  canal={c.channel!r}")
        print(f"         {c.title[:90]}")
        print(f"         motivos: {'; '.join(c.reasons)}")


def main() -> int:
    log.setup(verbose=False, console=False)
    paths.ensure_dirs()
    cfg = load_config()
    quick = "--rapido" in sys.argv
    work = paths.TMP / "smoke_descoberta"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    trends, kw_cands, tr_cands = [], [], []

    with step("collect_trends"):
        trends = discovery.collect_trends(cfg)
        assert trends, "nenhum assunto em alta encontrado"
        for i, t in enumerate(trends[:15], 1):
            print(f"  {i:2d}. {t.score:5.1f}  {t.topic[:60]:60s} [{t.source}] {t.category or '-'} | {t.traffic or ''}")
            if t.reason:
                print(f"         {t.reason}")
        srcs = {s for t in trends for s in t.source.split("+")}
        print(f"  fontes que responderam: {sorted(srcs)}")
        assert all(0 <= t.score <= 100 for t in trends), "nota fora de 0-100"
        assert all(t.queries for t in trends), "Trend.queries vazio"

    with step("find_candidates palavra-chave 'debate'"):
        kw_cands = discovery.find_candidates(cfg, keywords=["debate"], limit=5)
        show_cands(kw_cands)
        assert kw_cands, "nenhum candidato para 'debate'"
        assert all(c.id.startswith(c.platform + ":") for c in kw_cands), "Candidate.id fora do padrao"

    if not quick:
        with step("find_candidates modo trends"):
            tr_cands = discovery.find_candidates(cfg, trends=trends[:15], limit=5)
            show_cands(tr_cands)
            assert tr_cands, "nenhum candidato no modo trends"

    # melhor candidato do YouTube com legenda (para testar legendas + trecho)
    pool = [c for c in kw_cands + tr_cands if c.platform == "youtube"]
    pool.sort(key=lambda c: (not c.has_subtitles, -c.score))
    top = pool[0] if pool else (kw_cands or tr_cands or [None])[0]
    if top is None:
        FAILS.append("sem candidato para testar download")
    else:
        with step(f"enrich_candidate {top.id}"):
            download.enrich_candidate(top, cfg)
            ex = top.extra
            print(f"  titulo: {top.title[:80]}")
            print(f"  duracao={fmt_duration(top.duration)} views={top.views} likes={top.likes} comentarios={top.comments}"
                  f" publicado={time.strftime('%d/%m %H:%M', time.localtime(top.upload_ts)) if top.upload_ts else '?'}")
            print(f"  heatmap={len(ex.get('heatmap') or [])} pontos | capitulos={len(ex.get('chapters') or [])} |"
                  f" legendas={top.has_subtitles} {ex.get('subtitle_langs')} | idioma={ex.get('language')}")
            assert top.duration and top.duration > 0, "duracao vazia"

        with step("download_platform_subtitles"):
            sub = download.download_platform_subtitles(top, cfg, work)
            print(f"  arquivo: {sub}")
            if top.has_subtitles:
                assert sub and sub.is_file(), "tinha legenda mas nao baixou"
                if sub.suffix == ".json3":
                    ev = json.loads(sub.read_text(encoding="utf-8")).get("events") or []
                    words = sum(len(e.get("segs") or []) for e in ev)
                    print(f"  json3: {len(ev)} eventos, {words} pedacos com tempo")

        with step("download_sections (20 s)"):
            dur = float(top.duration or 0)
            heat = top.extra.get("heatmap") or []
            if heat:
                peak = max(heat, key=lambda h: h["value"])
                s = max(0.0, min(peak["start_time"], dur - 25))
            else:
                s = max(0.0, min(dur * 0.3, dur - 25))
            s = round(s, 2)
            files = download.download_sections(top, [(s, s + 20)], cfg, work)
            f = files[0]
            pr = download._probe(f)
            fdur = float(pr["format"]["duration"])
            streams = [(x.get("codec_type"), x.get("codec_name"), x.get("width"), x.get("height")) for x in pr["streams"]]
            print(f"  trecho {s:.2f}-{s + 20:.2f}s -> {f.name} ({f.stat().st_size / 1e6:.1f} MB) dur={fdur:.2f}s {streams}")
            assert abs(fdur - 20) <= 0.5, f"duracao do trecho {fdur:.2f}s (esperado 20 +- 0.5)"
            assert {"video", "audio"} <= {x[0] for x in streams}, "trecho sem audio ou video"
            assert any(x[1] == "h264" for x in streams) and any(x[1] == "aac" for x in streams), "codec nao e h264/aac"

    shutil.rmtree(work, ignore_errors=True)
    print("\n=== tempos")
    for k, v in TIMES.items():
        print(f"  {v:6.1f}s  {k}")
    if FAILS:
        print("\nFALHAS:")
        for f in FAILS:
            print("  - " + f)
        return 1
    print("\nOK: descoberta e download funcionando")
    return 0


if __name__ == "__main__":
    sys.exit(main())
