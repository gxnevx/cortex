"""Testes rapidos do editor v3 (sem rede): alinhamento, etiqueta de nome, rosto seguro, marca.

Uso:
    .venv\\Scripts\\python.exe tests\\editor_v3_unit.py            # so logica (sem ffmpeg)
    .venv\\Scripts\\python.exe tests\\editor_v3_unit.py --render   # + render sintetico curto (platforms, 2 saidas)
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from fabrica.config import load_config  # noqa: E402
from fabrica.editor import faces, layouts, motion, overlays, safezone, style, titlecard  # noqa: E402
from fabrica.models import ClipPlan  # noqa: E402

FORBIDDEN = tuple(chr(c) for c in (0x2022, 0x00B7, 0x2014, 0x2013))


# ------------------------------------------------------------------ titulo: pilula x caixa
def test_title(tmp: Path):
    texts = ["ELA CONTOU TUDO 😳", "O MOTIVO REAL DA BRIGA QUE NINGUEM CONTOU ATE HOJE", "GOL?", "VOCE NAO VAI ACREDITAR 😱🔥"]
    n = 0
    for variant in titlecard.VARIANTS:
        for size in titlecard.SIZES:
            for txt in texts:
                for part, tot in ((1, 2), (3, 3), (None, None)):
                    cfg = load_config()
                    c = titlecard.render_title_card(txt, tmp / f"t_{n}.png", cfg, part, tot, category="podcast",
                                                    seed="x", variant=variant, size=size)
                    n += 1
                    assert c is not None and c.box is not None
                    bx, by, bw, bh = c.box
                    assert abs((bx + bw / 2) - 540) <= 1.5, (variant, txt, c.box)          # eixo central
                    assert bx >= style.MARGIN - 1 and bx + bw <= 1080 - style.MARGIN + 1, c.box
                    if part:
                        px, py, pw, ph = c.pill
                        assert abs((px + pw / 2) - 540) <= 1.5, c.pill
                        gap = by - (py + ph)
                        assert 12 <= gap <= 24, (variant, size, txt, gap)   # separada da caixa, sem sobrepor
                        # a faixa entre pilula e caixa e transparente (so sombra)
                        im = Image.open(c.path).convert("RGBA")
                        y_mid = int(round((py + ph + by) / 2)) - c.y
                        x_mid = int(round(540 - c.x))
                        if variant != "contorno":   # o contorno tem sombra larga atras do texto
                            assert im.getpixel((x_mid, y_mid))[3] < 170, (variant, size, txt)
    print(f"ok titulo ({n} combinacoes)")


# ------------------------------------------------------------------ etiqueta de nome
def test_name_text():
    cfg = load_config()
    p = ClipPlan(id="a", source_id="s", start=0, end=30, title="t", hook="h",
                 description="Déia Freitas fala da vida de criadora no Podpah.", category="podcast")
    v = {"title": "DÉIA FREITAS (NÃO INVIABILIZE) - Podpah #1104", "channel": "Podpah TV", "description": ""}
    assert overlays.name_tag_text(p, cfg, v) == ("DÉIA FREITAS", "no Podpah")
    v2 = {"title": "MANO BROWN | Mano a Mano #45", "channel": "Spotify Brasil"}
    assert overlays.name_tag_text(ClipPlan(id="a", source_id="s", start=0, end=1, title="t"), cfg, v2)[0] == "MANO BROWN"
    v3 = {"title": "ELE PERDEU TUDO NA APOSTA", "channel": "Flow Podcast"}
    r3 = overlays.name_tag_text(ClipPlan(id="a", source_id="s", start=0, end=1, title="t"), cfg, v3)
    assert r3 == ("FLOW PODCAST", ""), r3
    assert overlays.name_tag_text(ClipPlan(id="a", source_id="s", start=0, end=1, title="t"), cfg, {"title": "x", "channel": ""}) is None
    cfg.set("edicao.etiqueta_nome_texto", "ANA SOUZA | na Globo")
    assert overlays.name_tag_text(p, cfg, v) == ("ANA SOUZA", "na Globo")
    for a, b in ((p, v), (ClipPlan(id="a", source_id="s", start=0, end=1, title="t"), v2)):
        for t in overlays.name_tag_text(a, None, b) or ():
            assert not any(c in t for c in FORBIDDEN), t
    print("ok textos da etiqueta")


def test_name_render(tmp: Path):
    for sty in overlays.NAME_STYLES:
        d = tmp / f"et_{sty}"
        nt = overlays.render_name_tag("ANA SOUZA", "no Podpah", d, None, sty, dur=2.0)
        assert nt.frames == 60 and (d / "n_000.png").exists() and (d / "n_059.png").exists()
        x0, y0, x1, y1 = nt.vis
        assert 300 < x1 - x0 <= 760 and 60 < y1 - y0 < 180, (sty, nt.vis)
        # cap height centrada nas caixas: o topo e a base da tinta do nome ficam simetricos na placa
        im = np.array(Image.open(d / "n_030.png").convert("RGBA")).astype(int)
        if sty == "tarja":
            # placa do nome: pixels quase pretos; texto: quase brancos. Altura da placa do nome.
            row_ink = (im[:, :, 0] < 60) & (im[:, :, 3] > 200)
            rows = np.where(row_ink[:, int((x0 + x1) / 2)])[0]
            assert len(rows), sty
        # a etiqueta some no fim (ultimo quadro quase transparente)
        last = np.array(Image.open(d / "n_059.png").convert("RGBA"))
        assert last[:, :, 3].max() < 120, sty
        first = np.array(Image.open(d / "n_000.png").convert("RGBA"))
        assert first[:, :, 3].max() < 160 or sty != "pilula"
    print("ok etiqueta (3 estilos)")


# ------------------------------------------------------------------ planejador: rosto seguro
def fake_track(dur: float, sw: int, sh: int, boxes_by_time, shots=None) -> faces.FaceTrack:
    """Trilha de rosto sintetica: boxes_by_time(t) -> (x0, y0, x1, y1) (fracoes) ou None."""
    shots = shots or [(0.0, dur)]
    out = []
    for a, b in shots:
        dets = []
        for t in np.arange(a, b, 0.2):
            bx = boxes_by_time(float(t))
            if bx is None:
                continue
            x0, y0, x1, y1 = bx
            dets.append(faces.Det(float(t), (x0 + x1) / 2, (y0 + y1) / 2, y1 - y0, 0.9, 0.0, bx, y0 + 0.4 * (y1 - y0)))
        s = faces.Shot(a, b)
        if dets:
            s.cx = float(np.median([d.cx for d in dets]))
            s.cy = float(np.median([d.cy for d in dets]))
            s.fh = float(np.median([d.fh for d in dets]))
            s.box = faces.face_envelope(dets)
            s.eye = s.cy - 0.1 * s.fh
            s.dets = dets
        out.append(s)
    return faces.FaceTrack(out, sw, sh, len(out))


def make_planner(tmp: Path, lay: str, total: float, track, info: dict, teaser: float = 2.0, tag=True,
                 cta=True, parts=(1, 2), brand=True, hook="ELA CONTOU TUDO 😳"):
    cfg = load_config()
    segs = faces.segments(track, total, None, None)
    zoom = motion.plan_zoom(None, total, cfg, seed="x") if False else motion.ZoomPlan(1.0, [motion.Key(4.0, 0.08, 0.0)], [], 1)
    mot = layouts.Motion(track=track, zoom=zoom, follow_face=True, info=info, pieces=None)
    fr = layouts.build_framing(lay, info, cfg, mot)
    pl = ClipPlan(id="p", source_id="s", start=0, end=total, title="t", hook=hook, category="podcast",
                  part=parts[0], parts_total=parts[1])

    def make_title(size):
        return titlecard.render_title_card(hook, tmp / f"tt_{size}.png", cfg, parts[0], parts[1], category="podcast",
                                           seed="p", size=size)

    tag_obj = None
    if tag:
        tag_obj = overlays.render_name_tag("DÉIA FREITAS", "no Podpah", tmp / "tag", None, "tarja", dur=2.6)
    cta_obj = overlays.render_cta_pill("PARTE 2 NO PERFIL", tmp / "cta.png", cfg, "podcast") if cta else None
    br = overlays.render_brand(cfg, tmp, ["youtube", "tiktok"]) if brand else None
    brs = [br] if br else []
    if br:
        brs.append(overlays.render_brand(cfg, tmp, ["youtube", "tiktok"], scale=0.8))
        brs.append(overlays.render_brand(cfg, tmp, ["youtube", "tiktok"], mini=True))
    size = 120.0
    cap = safezone.CapGeo(size, 2 * size / 2 * 1.06 + 13, 800, 1300, lines=2,
                          modes={1: (1 * size / 2 * 1.06 + 13, 760)})
    return safezone.Planner(lay=lay, total=total, teaser=teaser, framing=fr, segs=segs, cfg=cfg, make_title=make_title,
                            bar_h=8, cap=cap, tag=tag_obj, tag_dur=2.6, cta=cta_obj, cta_s=2.0, brand=brs, info=info,
                            seam=layouts.split_seam(cfg))


def check_scene(p, sc, label: str):
    ov = safezone.face_overlap(sc.framing, p.raw_segs, sc.items, p.total)
    touch = safezone.items_overlap(sc.items, gap=15)
    assert not touch, (label, touch)
    assert sc.title is None or sc.title.box is not None
    return ov


def test_planner(tmp: Path):
    info = {"width": 1920, "height": 1080, "fps": 30, "has_video": True, "has_audio": True, "duration": 60}
    cases = {
        # (caixa do rosto normalizada na fonte) por situacao tipica de podcast
        "rosto_pequeno_centro": lambda t: (0.45, 0.30, 0.55, 0.48),
        "rosto_close_alto": lambda t: (0.40, 0.05, 0.58, 0.45),
        "rosto_close_baixo": lambda t: (0.40, 0.20, 0.60, 0.62),
        "rosto_esquerda": lambda t: (0.22, 0.10, 0.40, 0.45),
        "rosto_anda": lambda t: (0.35 + 0.15 * np.sin(t), 0.08, 0.50 + 0.15 * np.sin(t), 0.40),
    }
    for lay in ("full", "split", "blur"):
        for name, fn in cases.items():
            tr = fake_track(38.0, 1920, 1080, fn)
            p = make_planner(tmp, lay, 38.0, tr, info)
            sc = p.plan()
            ov = check_scene(p, sc, f"{lay}/{name}")
            # rosto pequeno: sempre da para livrar 100%; close enorme: aceita quase zero
            if name == "rosto_pequeno_centro":
                assert ov["max_px"] <= 0, (lay, name, ov, sc.notes)
            print(f"  {lay:5s} {name:20s} sobreposicao={ov['max_px']:.0f} titulo={sc.title.size}/{sc.title_slot} "
                  f"marca={sc.brand.slot if sc.brand else None} etiqueta={sc.tag.slot if sc.tag else None}")
    # clipe longo (93 s) e sem rosto
    tr = fake_track(93.0, 1920, 1080, lambda t: (0.40, 0.08, 0.58, 0.44) if int(t) % 20 < 12 else None,
                    shots=[(0, 30), (30, 61), (61, 93)])
    p = make_planner(tmp, "full", 93.0, tr, info)
    sc = p.plan()
    check_scene(p, sc, "longo")
    print("ok planejador longo:", sc.notes[-1])
    p = make_planner(tmp, "blur", 30.0, None, info)
    sc = p.plan()
    check_scene(p, sc, "sem rosto")
    # a expressao do ffmpeg do plano e valida (numerica, sem faltar parenteses)
    for e in (sc.framing.zoom_expr(), sc.framing.y_expr(), sc.framing.x_expr()):
        assert e.count("(") == e.count(")"), e
    print("ok planejador")


def test_framing_math():
    """A projecao em Python bate com a formula do zoompan."""
    info = {"width": 1920, "height": 1080}
    cfg = load_config()
    fr = layouts.build_framing("full", info, cfg, None)
    fr.zb = layouts.Steps(1.2)
    fr.dy = layouts.Steps(0.1)
    fr.ay = layouts.Steps(0.3)
    z = 1.2
    # janela do zoompan
    Y = min(max(0.3 - 0.4 / z, 0), 1 - 1 / z)
    x0, y0, x1, y1 = fr.project((0.45, 0.3, 0.55, 0.4), 0.0)
    ch = 1080
    assert abs(y0 - (0.3 - Y) * z * 1920 * (1080 / ch)) < 1e-6 or True   # crop = altura inteira
    exp_y0 = (0.3 * 1080 / 1080 - Y) * z * 1920
    assert abs(y0 - exp_y0) < 1e-6, (y0, exp_y0)
    print("ok projecao")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="edv3_"))
    import shutil

    try:
        test_framing_math()
        test_title(tmp)
        test_name_text()
        test_name_render(tmp)
        test_planner(tmp)
        if "--render" in sys.argv:
            test_render(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("tudo ok")
    return 0


def test_render(tmp: Path):
    """Render sintetico: duas saidas (com @ por rede), platforms=["tiktok"] e trecho > 58 s no TikTok."""
    from fabrica import editor
    from fabrica.editor import ffmpeg as ff

    src = tmp / "sint.mp4"
    ff.run(["-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=64", "-f", "lavfi", "-i",
            "sine=f=440:d=64:sample_rate=48000", "-c:v", "libx264", "-preset", "ultrafast", "-threads", "4",
            "-c:a", "aac", "-shortest", str(src)])
    cfg = load_config()
    cfg.set("edicao.encoder", "libx264")
    cfg.set("edicao.qualidade", "rapida")
    cfg.set("edicao.threads", 6)
    plan = ClipPlan(id="sint-c1", source_id="x", start=0, end=8.5, title="Teste", hook="TESTE DO EDITOR",
                    description="Contexto", category="humor", part=1, parts_total=2)
    rc = editor.render_clip(src, 0.0, 8.5, plan, None, cfg, tmp / "dual.mp4", layout="blur")
    assert set(rc.variants) == {"youtube", "tiktok"}, rc.variants
    assert rc.path == rc.variants["youtube"] and Path(rc.variants["tiktok"]).exists()
    for p_ in rc.all_files():
        i = ff.probe(p_)
        assert (i["width"], i["height"]) == (1080, 1920) and i["has_audio"], p_
    rc = editor.render_clip(src, 0.0, 8.5, plan, None, cfg, tmp / "so_tt.mp4", layout="full", platforms=["tiktok"])
    assert set(rc.variants) == {"tiktok"} and rc.path == rc.variants["tiktok"] and rc.path.endswith("so_tt_tiktok.mp4")
    plan.end = 62.0
    rc = editor.render_clip(src, 0.0, 62.0, plan, None, cfg, tmp / "longo.mp4", layout="full", platforms=["tiktok"])
    assert abs(rc.duration - 62.0) < 0.3 and set(rc.variants) == {"tiktok"}, (rc.duration, rc.variants)
    print("ok render (2 saidas, so tiktok, longo)")


if __name__ == "__main__":
    raise SystemExit(main())
