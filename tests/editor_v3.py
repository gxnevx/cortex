"""Teste do editor v3: nada cobre o rosto, nada encosta em nada, etiqueta de nome, marca + @ por rede.

Usa o mesmo trecho do editor_v2 (Podpah #1104, <= 40 s, baixado em work/tmp/v2_fonte). Para cada
layout (full, split, blur), um ffmpeg por vez, libx264, threads <= 6:
  1. render final (qualidade media, cold open + tudo ligado) -> work/amostras/v3/v3_<layout>_<rede>.mp4
     e faixa de quadros (0,5 s / 2,5 s / 4 s / meio / fim) em v3_<layout>_quadros.jpg
  2. checagens do plano (LAST_STATS): rosto x elementos = 0 px a cada 1/15 s; elementos com >= 16 px
     entre si; pilula PARTE fora da caixa do titulo; tudo dentro das margens/zonas seguras; <= 25 MB
  3. checagem INDEPENDENTE: render limpo (mesmo plano, sem desenhar nada), YuNet nos quadros da
     saida a cada 0,5 s; nenhum retangulo de elemento pode tocar um rosto detectado
  4. render com a grade de depuracao (edicao.depurar_grade) -> depois_alinhamento.jpg
Tambem: --estilos (comparativo das 3 etiquetas sobre o quadro real) e --limpar.

Uso:
    .venv\\Scripts\\python.exe tests\\editor_v3.py [--layouts full,split,blur] [--sem-limpo] [--sem-grade]
        [--estilos] [--limpar]
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fabrica import paths  # noqa: E402
from fabrica.config import load_config  # noqa: E402
from fabrica.models import ClipPlan  # noqa: E402

OUT = paths.WORK / "amostras" / "v3"
VIDEO = {"title": "DÉIA FREITAS (NÃO INVIABILIZE) - Podpah #1104", "channel": "Podpah TV",
         "description": "A voz por trás de algumas das histórias mais inacreditáveis da internet chegou ao Podpah!"}
FORBIDDEN = tuple(chr(c) for c in (0x2022, 0x00B7, 0x2014, 0x2013))
MAX_MB = 25.0


def base_cfg(quality: str = "media"):
    cfg = load_config()
    cfg.set("edicao.encoder", "libx264")
    cfg.set("edicao.qualidade", quality)
    cfg.set("edicao.threads", 6)
    cfg.set("edicao.etiqueta_nome", True)
    cfg.set("edicao.cartao_contexto", False)
    cfg.set("edicao.marca_dagua_arroba", True)
    return cfg


def make_plan(src, tr, dur):
    import editor_v2

    plan = ClipPlan(id="v3-amostra-c1", source_id="youtube:Xy5gwR172tI", start=0, end=dur,
                    title="Ela nao aguentou e contou TUDO 😳", hook="ELA CONTOU TUDO 😳",
                    description="Déia Freitas fala da vida de criadora no Podpah. Trecho do episodio #1104.",
                    category="podcast", part=1, parts_total=2)
    ts, te, txt = editor_v2.loudest_phrase(src, tr, dur)
    plan.teaser_start, plan.teaser_end, plan.teaser_text = ts, te, txt
    return plan


def grab(video: Path, t: float):
    from PIL import Image

    from fabrica.editor import ffmpeg as ff

    p = subprocess.run([ff.ffmpeg_bin(), "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(video),
                        "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1"], capture_output=True)
    return Image.open(io.BytesIO(p.stdout)).convert("RGB")


def strip(video: Path, times: list[float], dest: Path, w: int = 432) -> None:
    from PIL import Image, ImageDraw

    ims = []
    for t in times:
        im = grab(video, t).resize((w, round(w * 1920 / 1080)))
        ImageDraw.Draw(im).text((8, 8), f"{t:.1f}s", fill=(255, 255, 0))
        ims.append(im)
    out = Image.new("RGB", (w * len(ims), ims[0].height))
    for i, im in enumerate(ims):
        out.paste(im, (i * w, 0))
    out.save(dest, quality=88)


def check_plan(st: dict, lay: str) -> list[str]:
    """Erros do plano (lista vazia = ok)."""
    from fabrica.editor import safezone, style

    errs = []
    if st["rosto_sobreposicao_px"] > 0:
        errs.append(f"rosto coberto: {st['rosto_pior']}")
    items = [safezone.Item(n, r, t0, 1e9 if t1 is None else t1) for n, r, t0, t1 in st["sobreposicoes"]]
    touch = safezone.items_overlap(items, gap=16)
    if touch:
        errs.append(f"elementos encostando: {touch}")
    rects = {it.name: it.rect for it in items}
    if "parte" in rects and "titulo" in rects:
        p, b = rects["parte"], rects["titulo"]
        if p[3] + 12 > b[1]:
            errs.append(f"pilula PARTE sobre/colada no titulo: {p} x {b}")
        if abs((p[0] + p[2]) / 2 - (b[0] + b[2]) / 2) > 2:
            errs.append("pilula PARTE fora do eixo do titulo")
    for it in items:
        x0, y0, x1, y1 = it.rect
        if x0 < style.MARGIN - 1 and it.name not in ("legenda",):
            errs.append(f"{it.name} fora da margem esquerda ({x0})")
        if x1 > 1080 - style.MARGIN + 1:
            errs.append(f"{it.name} fora da margem direita ({x1})")
        if y0 < style.SAFE_TOP - 1 or y1 > style.SAFE_BOTTOM_Y + 1:
            errs.append(f"{it.name} fora da zona segura vertical ({y0:.0f}-{y1:.0f})")
        if safezone._inter(it.rect, style.RAIL) > 0:
            errs.append(f"{it.name} na coluna de botoes")
        centered = it.name in ("titulo", "parte", "barra", "legenda", "cta")
        if centered and abs((x0 + x1) / 2 - 540) > 2:
            errs.append(f"{it.name} fora do eixo central ({(x0 + x1) / 2:.0f})")
    return errs


def independent_faces(clean_mp4: Path, st: dict, total: float, step: float = 0.25, dump: Path | None = None,
                      region: tuple | None = None) -> dict:
    """YuNet nos quadros da saida LIMPA (sem nada desenhado): rosto detectado x elementos ativos.

    region: (x0, y0, x1, y1) onde procurar (no blur, so a area nitida: o fundo e uma copia ampliada e
    desfocada em que o detector enxerga um rosto-fantasma). Uma deteccao so conta se aparecer em duas
    amostras seguidas; as isoladas (falso positivo de um quadro) saem listadas a parte, nunca escondidas."""
    import cv2
    import numpy as np

    from fabrica.editor import faces, safezone

    rx0, ry0, rx1, ry1 = (int(v) for v in (region or (0, 0, 1080, 1920)))
    w = 360
    h = max(2, int(round(w * (ry1 - ry0) / (rx1 - rx0) / 2)) * 2)
    det = cv2.FaceDetectorYN.create(str(faces.YUNET), "", (w, h), 0.7, 0.3, 20)
    items = [safezone.Item(n, r, t0, 1e9 if t1 is None else t1) for n, r, t0, t1 in st["sobreposicoes"]]
    sx = (rx1 - rx0) / w
    prev: list = []
    isolated: list = []
    pend: list = []
    worst, n_faces, frames = 0.0, 0, 0
    dumped = []
    hits = []
    t = 0.25
    while t < total - 0.1:
        full_im = grab(clean_mp4, t)
        im = np.array(full_im.crop((rx0, ry0, rx1, ry1)).resize((w, h)))[:, :, ::-1].copy()
        cur: list = []
        frames += 1
        _ok, fs = det.detect(im)
        for f in (fs if fs is not None else []):
            x, y, fw, fh = (float(v) * sx for v in f[:4])
            x, y = x + rx0, y + ry0
            if fh < 0.05 * 1920:
                continue
            n_faces += 1
            cur.append((x, y, x + fw, y + fh))
            seen = any(safezone._inter((x, y, x + fw, y + fh), q) > 0.3 * fw * fh for q in prev)
            r = faces.expand_box(x, y, fw, fh)
            raw = (x, y, x + fw, y + fh)
            this = []
            for it in items:
                if it.t0 <= t <= it.t1:
                    a = safezone._inter(r, it.rect)
                    if a > 0:
                        rec = (round(t, 2), it.name, round(a))
                        if seen:
                            hits.append(rec)
                            this.append(it)
                            worst = max(worst, a)
                        else:   # 1a aparicao: confirma (ou descarta) na amostra seguinte
                            pend.append((t, it, a, raw, rec))
            if this and dump is not None and len(dumped) < 6:
                from PIL import ImageDraw

                d = full_im.copy()
                dr = ImageDraw.Draw(d)
                dr.rectangle(raw, outline=(0, 255, 0), width=4)
                dr.rectangle(r, outline=(255, 0, 0), width=4)
                for it in this:
                    dr.rectangle(it.rect, outline=(255, 230, 0), width=5)
                dr.text((20, 20), f"{t:.2f}s score={float(f[14]):.2f}", fill=(255, 255, 0))
                fp = dump / f"colisao_{clean_mp4.stem}_{t:05.2f}.jpg"
                d.resize((540, 960)).save(fp, quality=85)
                dumped.append(fp.name)
        for (pt, pit, pa, praw, prec) in [q for q in pend if q[0] < t]:
            if any(safezone._inter(praw, q) > 0.3 * (praw[2] - praw[0]) * (praw[3] - praw[1]) for q in cur):
                hits.append(prec)          # persistiu: conta
                worst = max(worst, pa)
            else:
                isolated.append(prec)      # um quadro so: listado a parte
            pend.remove((pt, pit, pa, praw, prec))
        prev = cur
        t += step
    isolated += [q[4] for q in pend]
    return {"isoladas": isolated[:12], "quadros": frames, "rostos": n_faces, "pior_px": round(worst), "colisoes": hits[:12], "quadros_salvos": dumped}


def styles_compare(clean_mp4: Path, st: dict, dest: Path) -> None:
    """As 3 etiquetas sobre o mesmo quadro real (posicao escolhida pelo plano)."""
    from PIL import Image

    from fabrica.editor import overlays

    tag = next((x for x in st["sobreposicoes"] if x[0] == "etiqueta"), None)
    if tag is None:
        return
    _n, r, t0, _t1 = tag
    frame = grab(clean_mp4, t0 + 1.2).convert("RGBA")
    tiles = []
    tmp = paths.TMP / "v3_estilos"
    for sty in overlays.NAME_STYLES:
        shutil.rmtree(tmp, ignore_errors=True)
        nt = overlays.render_name_tag("DÉIA FREITAS", "no Podpah", tmp, None, sty)
        im = frame.copy()
        im.alpha_composite(Image.open(tmp / "n_040.png"), (int(r[0] - nt.vis[0]), int(r[1] - nt.vis[1])))
        tiles.append(im.convert("RGB").resize((540, 960)))
    shutil.rmtree(tmp, ignore_errors=True)
    out = Image.new("RGB", (540 * len(tiles), 960))
    for i, im in enumerate(tiles):
        out.paste(im, (540 * i, 0))
    out.save(dest, quality=88)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--layouts", default="full,split,blur")
    ap.add_argument("--sem-limpo", action="store_true")
    ap.add_argument("--sem-grade", action="store_true")
    ap.add_argument("--sem-final", action="store_true")
    ap.add_argument("--estilos", action="store_true")
    ap.add_argument("--fundo", default="minecraft-building")
    ap.add_argument("--limpar", action="store_true", help="apaga o trecho baixado e sai")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    import editor_v2

    if a.limpar:
        shutil.rmtree(editor_v2.SRC_DIR, ignore_errors=True)
        print("trecho de teste apagado")
        return 0
    paths.ensure_dirs()
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = base_cfg()
    src, tr = editor_v2.prepare(cfg, editor_v2.DEFAULT_URL, 1500, 38)
    from fabrica import editor
    from fabrica.editor import backgrounds

    info = editor.probe(src)
    dur = min(38, info["duration"] - 0.2)
    plan = make_plan(src, tr, dur)
    print(f"teaser {plan.teaser_start:.2f}-{plan.teaser_end:.2f}s")
    hit = [f for fs in backgrounds.library().values() for f in fs if a.fundo in f.name]
    forced = (hit[0], 30.0) if hit else None
    results, failures = {}, []
    after = []
    for lay in a.layouts.split(","):
        res = {}
        # 1. final
        if not a.sem_final:
            t0 = time.time()
            rc = editor.render_clip(src, 0.0, dur, plan, tr, cfg, OUT / f"v3_{lay}.mp4", layout=lay,
                                    background=forced if lay == "split" else None, video=VIDEO)
            st = dict(editor.LAST_STATS)
            st.pop("_segs", None)
            st.pop("_framing", None)
            st["parede_s"] = round(time.time() - t0, 1)
            sizes = {k: round(Path(v).stat().st_size / 1e6, 1) for k, v in rc.variants.items()}
            st["mb"] = sizes
            res["final"] = st
            print(f"[{lay}] {st['segundos_ffmpeg']}s ffmpeg ({st['saidas']} saidas) {sizes} cena={st['cena']}")
            print(f"[{lay}] etiqueta={st['etiqueta']} rosto x elementos={st['rosto_sobreposicao_px']} px")
            errs = check_plan(st, lay)
            for k, mb in sizes.items():
                if mb > MAX_MB:
                    errs.append(f"{k}: {mb} MB > {MAX_MB}")
            if set(rc.variants) != {"youtube", "tiktok"} or rc.path != rc.variants.get("youtube"):
                errs.append(f"variantes erradas: {rc.variants} / {rc.path}")
            total = rc.duration
            strip(Path(rc.path), [0.5, 2.5, 4.0, total / 2, total - 0.4], OUT / f"v3_{lay}_quadros.jpg")
            if errs:
                failures += [f"{lay}: {e}" for e in errs]
            thumb = Path(rc.thumbnail) if rc.thumbnail else None
            if thumb and thumb.exists():
                thumb.unlink()
        # 2. limpo (mesmo plano, nada desenhado) + YuNet independente
        if not a.sem_limpo:
            c2 = base_cfg("rapida")
            c2.set("edicao.depurar_sem_sobreposicoes", True)
            # MESMA config do final (inclusive o @): outro plano seria conferir um plano nos quadros de outro
            clean = paths.TMP / f"v3_limpo_{lay}.mp4"
            rc2 = editor.render_clip(src, 0.0, dur, plan, tr, c2, clean, layout=lay,
                                     background=forced if lay == "split" else None, video=VIDEO)
            st2 = dict(editor.LAST_STATS)
            if "final" in res:
                same = [x[:2] for x in st2["sobreposicoes"]] == [tuple(x[:2]) if isinstance(x, list) else x[:2]
                                                                   for x in res["final"]["sobreposicoes"]]
                res["mesmo_plano"] = same
                fin = [(n_, r_, a_) for n_, r_, a_, _b in res["final"]["sobreposicoes"]]
                cl = [(n_, r_, a_) for n_, r_, a_, _b in st2["sobreposicoes"]]
                if fin != cl:
                    failures.append(f"{lay}: o render limpo usou OUTRO plano (conferencia invalida)")
            g_ = editor.LAST_STATS["_framing"].geo
            ind = independent_faces(Path(rc2.path), st2, rc2.duration, dump=paths.TMP,
                                    region=(g_.ox, g_.oy, g_.ox + g_.ow, g_.oy + g_.oh))
            res["yunet_saida"] = ind
            print(f"[{lay}] YuNet na saida limpa: {ind}")
            if ind["pior_px"] > 0:
                failures.append(f"{lay}: YuNet achou elemento sobre rosto {ind['colisoes']}")
            if ind["rostos"] < ind["quadros"] * 0.5:
                failures.append(f"{lay}: poucos rostos detectados na saida ({ind})")
            if a.estilos and lay == "full":
                styles_compare(Path(rc2.path), st2, OUT / "etiqueta_estilos.jpg")
            for f_ in rc2.all_files():
                Path(f_).unlink(missing_ok=True)
            if rc2.thumbnail:
                Path(rc2.thumbnail).unlink(missing_ok=True)
        # 3. grade de depuracao
        if not a.sem_grade:
            c3 = base_cfg("rapida")
            c3.set("edicao.depurar_grade", True)
            c3.set("edicao.marca_dagua_arroba", True)
            dbg = paths.TMP / f"v3_grade_{lay}.mp4"
            rc3 = editor.render_clip(src, 0.0, dur, plan, tr, c3, dbg, layout=lay,
                                     background=forced if lay == "split" else None, video=VIDEO)
            total = rc3.duration
            after.append((Path(rc3.path), [0.5, 3.0, total - 0.4]))
            for v in list(rc3.variants.values()) + [rc3.path]:
                pass
        results[lay] = res
    if after:
        from PIL import Image

        tiles = []
        for mp4, times in after:
            for t in times:
                tiles.append(grab(mp4, t).resize((432, 768)))
        out = Image.new("RGB", (432 * len(tiles), 768))
        for i, im in enumerate(tiles):
            out.paste(im, (432 * i, 0))
        out.save(OUT / "depois_alinhamento.jpg", quality=88)
        for mp4, _t in after:
            for f in mp4.parent.glob(mp4.stem.rsplit("_", 1)[0] + "*"):
                if f.name.startswith("v3_grade_"):
                    f.unlink(missing_ok=True)
    (OUT / "resultado.json").write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    txt = json.dumps(results, ensure_ascii=False, default=str)
    if any(c in txt for c in FORBIDDEN):
        failures.append("caractere proibido no resultado")
    if failures:
        print("FALHAS:")
        for f in failures:
            print(" -", f)
        return 1
    print("tudo ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
