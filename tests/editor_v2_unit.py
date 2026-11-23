"""Testes rapidos do editor v2 (jump cuts, zoom, cold open, cartoes). Sem rede.

Uso:
    .venv\\Scripts\\python.exe tests\\editor_v2_unit.py            # so logica (sem ffmpeg)
    .venv\\Scripts\\python.exe tests\\editor_v2_unit.py --render   # + render sintetico de 8 s nos 3 layouts
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from fabrica.editor import coldopen, jumpcut, motion, overlays  # noqa: E402
from fabrica.models import ClipPlan, Segment, Transcript, Word  # noqa: E402

FORBIDDEN = tuple(chr(c) for c in (0x2022, 0x00B7, 0x2014, 0x2013))   # proibidos pelo dono


def tr_from(words):
    ws = [Word(a, b, t) for a, b, t in words]
    return Transcript([Segment(ws[0].start, ws[-1].end, " ".join(w.text for w in ws), ws)])


def fake_energy(dur, speech):
    """dB a cada 10 ms: -15 na fala, -50 no silencio."""
    db = np.full(int(dur * 100), -50.0)
    for a, b in speech:
        db[int(a * 100):int(b * 100)] = -15.0
    return db


def test_jumpcut():
    # silencio no comeco (0-0.8), pausa longa (2.0-3.2) e pausa curta (4.0-4.3)
    words = [(0.8, 1.2, "eu"), (1.2, 2.0, "falei"), (3.2, 3.6, "que"), (3.6, 4.0, "nao"), (4.3, 5.0, "vou.")]
    tr = tr_from(words)
    en = fake_energy(6.0, [(0.8, 2.0), (3.2, 4.0), (4.3, 5.0)])
    cp = jumpcut.plan_cuts(tr, 6.0, 30, None, en)
    assert cp is not None
    # o primeiro trecho comeca no maximo 0,15 s antes da primeira palavra
    assert 0.8 - cp.segments[0][0] / 30 <= 0.15 + 1e-6, cp.segments
    # a pausa de 1,2 s vira ~0,12 s; a de 0,3 s fica
    m = cp.map_time
    assert abs((m(3.2) - m(2.0)) - 0.12) < 0.05, (m(2.0), m(3.2))
    assert abs((m(4.3) - m(4.0)) - 0.3) < 0.02
    # palavras nunca encurtam (corte nunca cai dentro de palavra)
    for a, b, _t in words:
        assert abs((m(b) - m(a)) - (b - a)) < 0.04, (a, b)
    # duracoes inteiras em quadros: audio e video identicos
    assert all(isinstance(a, int) and isinstance(b, int) for a, b in cp.segments)
    vf, af = cp.video_filter(), cp.audio_filter("0:a", "ac")
    assert vf.startswith("select='between(n,") and "setpts=N/(30*TB)" in vf
    assert af.count("atrim=start_sample=") == len(cp.segments) and "concat=n=" in af
    rt = jumpcut.retime(tr, cp)
    assert abs(rt.words()[2].start - m(3.2)) < 1e-3
    # sem energia (fallback so pelas palavras) tambem corta a pausa longa
    cp2 = jumpcut.plan_cuts(tr, 6.0, 30, None, None)
    assert cp2 is not None and cp2.removed_s > 0.9
    # truncate respeita o teto
    cp.truncate(60)
    assert cp.out_frames == 60
    print("ok jumpcut")


def test_zoom():
    words = []
    t = 0.2
    txt = "eu nunca vi uma MENTIRA tao grande na minha vida. e ele falou 20 milhoes. absurdo total.".split()
    while t < 30:
        for w in txt:
            words.append((t, t + 0.3, w))
            t += 0.36
            if t > 30:
                break
        t += 0.5
    tr = tr_from(words)
    zp = motion.plan_zoom(tr, 30.0, None, seed="x", cut_times=[6.0, 13.0], camera_cuts=[20.0])
    assert 1 <= len(zp.emphasis) <= 3
    emph_t = sorted(e.t0 for e in zp.emphasis)
    assert all(b - a >= 6.0 for a, b in zip(emph_t, emph_t[1:]))
    steps = sorted(k.t for k in zp.keys if k.d == 0)
    assert all(b - a >= 2.0 for a, b in zip(steps, steps[1:])), steps    # nunca 2 trocas em menos de 2 s
    assert abs(zp.at(0.0) - 1.10) < 1e-6 and abs(zp.at(0.5) - 1.0) < 1e-6      # zoom de impacto
    for tt in np.arange(0, 30, 0.05):
        assert 0.99 <= zp.at(float(tt)) <= 1.36
    e = zp.emphasis[0]
    assert zp.at(e.t0 + 0.2) - zp.at(e.t0 - 0.3) >= 0.06                    # punch-in de enfase
    ex = zp.expr("it")
    assert "if(" not in ex and ex.count("gte(") >= 1
    zt = motion.with_teaser(zp, 2.0)
    assert abs(zt.at(0.0) - 1.10) < 1e-6 and abs(zt.at(2.0) - zp.at(0.0)) < 1e-6
    print("ok zoom")


def test_coldopen():
    words = [(0.2 + i * 0.4, 0.5 + i * 0.4, w) for i, w in enumerate(
        "entao ele chegou e falou voce e um mentiroso sim e todo mundo ficou quieto ali.".split())]
    tr = tr_from(words)
    p = ClipPlan(id="c", source_id="s", start=100.0, end=130.0, title="t",
                 teaser_start=100.0 + 2.9, teaser_end=100.0 + 4.0, teaser_text="voce e um mentiroso")
    t = coldopen.plan_teaser(p, 30.0, tr, None, 30)
    assert t is not None and 1.5 - 1e-6 <= t.dur <= 3.0, t
    starts = [w[0] for w in words]
    assert any(abs(t.t0 - (s - 0.06)) < 1e-3 for s in starts), t.t0          # comeca no inicio de uma palavra
    p.teaser_start, p.teaser_end = 100.0 + 1.0, 100.0 + 9.0                     # longo demais: corta em 3 s
    t2 = coldopen.plan_teaser(p, 30.0, tr, None, 30)
    assert t2 is not None and t2.dur <= 3.0 + 1e-6
    p.teaser_start = None
    assert coldopen.plan_teaser(p, 30.0, tr, None, 30) is None
    caps = coldopen.merge_captions(coldopen.teaser_captions(tr, t), tr, t.dur)
    assert caps.words()[0].start < t.dur and min(w.start for w in caps.words()[3:]) >= 0
    assert coldopen.teaser_color(None, "polemica") == "#FFE600"
    assert coldopen.teaser_color(None, "podcast") == "#FF2D2D"
    print("ok coldopen")


def test_texts():
    p = ClipPlan(id="c9", source_id="s", start=0, end=30, title="Ela contou tudo",
                 hook="ELA CONTOU TUDO", description=f"Debate sobre a reforma {chr(0x2014)} no podcast X {chr(0x2022)} ao vivo. Outra frase.",
                 part=1, parts_total=3)
    ctx = overlays.context_text(p, None, "ELA CONTOU TUDO")
    assert ctx and len(ctx) <= 63 and not any(c in ctx for c in FORBIDDEN), ctx
    cta = overlays.cta_text(p, None)
    assert "2" in cta and not any(c in cta for c in FORBIDDEN), cta
    assert "segue" not in cta.lower() and "curte" not in cta.lower()
    p.part = 3
    assert overlays.cta_text(p, None) == ""
    print("ok textos")


def test_render(tmp: Path):
    """Render sintetico (testsrc2 + tom), sem rosto: confere que o grafo monta nos 3 layouts."""
    from fabrica import editor
    from fabrica.editor import ffmpeg as ff

    src = tmp / "sint.mp4"
    ff.run(["-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=9", "-f", "lavfi", "-i",
            "sine=f=440:d=9:sample_rate=48000", "-af", "volume=enable='between(t,3,4.4)':volume=0",
            "-c:v", "libx264", "-preset", "ultrafast", "-threads", "4", "-c:a", "aac", "-shortest", str(src)])
    words = [(0.1 + i * 0.35, 0.4 + i * 0.35, w) for i, w in enumerate("isso e um teste".split())]
    words += [(4.5 + i * 0.35, 4.8 + i * 0.35, w) for i, w in enumerate("de verdade MENTIRA total sim".split())]
    tr = tr_from(words)
    plan = ClipPlan(id="sint-c1", source_id="x", start=0, end=8.5, title="Teste", hook="TESTE DO EDITOR",
                    description="Contexto de teste do editor novo.", category="humor", part=1, parts_total=2,
                    teaser_start=4.5, teaser_end=6.2)
    from fabrica.config import load_config

    cfg = load_config()
    cfg.set("edicao.encoder", "libx264")
    cfg.set("edicao.qualidade", "rapida")
    for lay in ("full", "split", "blur"):
        out = tmp / f"sint_{lay}.mp4"
        rc = editor.render_clip(src, 0.0, 8.5, plan, tr, cfg, out, layout=lay)
        st = editor.LAST_STATS
        info = ff.probe(out)
        assert (info["width"], info["height"]) == (1080, 1920) and info["has_audio"]
        assert st["jump_cuts"] >= 1 and st["cold_open_s"] > 1.0, st
        assert abs(rc.duration - (8.5 - st["silencio_removido_s"] + st["cold_open_s"])) < 0.15, (rc.duration, st)
        print(f"ok render {lay}: {rc.duration:.2f}s, {st['segundos_ffmpeg']}s")
    # sem nenhum recurso novo: mesmo comportamento de antes (duracao = trecho)
    for k in ("cortar_silencios", "zooms", "cartao_contexto", "seguir_rosto", "cta_serie", "cold_open"):
        cfg.set(f"edicao.{k}", False)
    rc = editor.render_clip(src, 0.0, 8.5, plan, tr, cfg, tmp / "sint_off.mp4", layout="full")
    assert abs(rc.duration - 8.5) < 0.1, rc.duration
    print("ok render sem recursos novos")


if __name__ == "__main__":
    test_jumpcut()
    test_zoom()
    test_coldopen()
    test_texts()
    if "--render" in sys.argv:
        import shutil
        import tempfile

        from fabrica import paths

        paths.TMP.mkdir(parents=True, exist_ok=True)
        d = Path(tempfile.mkdtemp(prefix="edv2_", dir=paths.TMP))
        try:
            test_render(d)
        finally:
            shutil.rmtree(d, ignore_errors=True)
    print("tudo ok")
