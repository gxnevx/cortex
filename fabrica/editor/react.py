"""Video com webcam + tela (react, gameplay): separa os dois.

Acha a janelinha da webcam (rosto pequeno que nao sai do lugar, com moldura), recorta e monta um video em pe:
tela no meio, webcam GRANDE embaixo, fundo desfocado. O resto da edicao (legenda, titulo, cortes de silencio,
abertura) roda em cima desse video pronto, entao tudo continua sincronizado.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .. import paths
from ..log import get as get_log
from ..util import short_hash
from . import faces
from . import ffmpeg as ff

_log = get_log(__name__)

W, H = 1080, 1920
SEAM = 820                     # emenda tela/webcam (o titulo fica em cima dela)
SCREEN_TOP = 84               # acima disso fica a marca
SCREEN_MAX_H = 560             # sobra uma faixa para o titulo entre a tela e a webcam
TITLE_Y = 612                  # centro do titulo
CAM_H = 800                    # webcam de SEAM ate SEAM+CAM_H (abaixo disso fica a interface da rede)
CAPTION_Y = 1464               # legenda no peito da pessoa, abaixo do rosto
N_FRAMES = 28


@dataclass
class Layout:
    cam: tuple[float, float, float, float]       # fracoes da fonte (x0, y0, x1, y1)
    screen: tuple[float, float, float, float]
    conf: float
    face_x: float = 0.5                          # centro do rosto dentro da webcam (0..1)
    face_top: float = 0.2                        # topo da cabeca dentro da webcam (0..1)


# ------------------------------------------------------------------ deteccao
def _static_face(track) -> tuple[float, float, float, float, float] | None:
    """(x0, y0, x1, y1, altura) da caixa do rosto parado que mais aparece, ou None."""
    import numpy as np

    dets = [d for s in track.shots for d in (list(s.dets) + [x for od in s.others_dets for x in od])]
    if len(dets) < 12:
        return None
    pts = np.array([[d.cx, d.cy] for d in dets])
    best, best_n = None, 0
    for i in range(0, len(dets), max(1, len(dets) // 60)):
        near = np.hypot(pts[:, 0] - pts[i, 0], (pts[:, 1] - pts[i, 1]) * 0.6) < 0.07
        times = {round(dets[k].t, 1) for k in np.flatnonzero(near)}
        if len(times) > best_n:
            best_n, best = len(times), near
    total_t = {round(d.t, 1) for d in dets}
    if best is None or best_n < 0.5 * len(total_t):
        return None
    sel = [d for d, ok in zip(dets, best) if ok]
    cx, fh = np.median([d.cx for d in sel]), float(np.median([d.fh for d in sel]))
    if not 0.035 <= fh <= 0.30 or np.std([d.cx for d in sel]) > 0.035:
        return None     # rosto grande = e o proprio video; rosto andando = nao e webcam
    if 0.36 < cx < 0.64 and fh > 0.18:
        return None     # pessoa no centro do quadro: conversa normal
    boxes = np.array([d.box for d in sel if d.box and d.box[2] > d.box[0]])
    if len(boxes) < 8:
        return None
    x0, y0, x1, y1 = np.percentile(boxes[:, 0], 10), np.percentile(boxes[:, 1], 10), \
        np.percentile(boxes[:, 2], 90), np.percentile(boxes[:, 3], 90)
    return float(x0), float(y0), float(x1), float(y1), fh


def _border(edge, lo: int, hi: int, a: int, b: int, axis: int, outward: int) -> tuple[int, float] | None:
    """Linha reta persistente mais forte entre lo e hi. axis 0 = coluna (x), 1 = linha (y). Devolve (pos, forca 0..1)."""
    import numpy as np

    lo, hi = max(0, lo), max(0, hi)
    if hi - lo < 4 or b - a < 8:
        return None
    reg = edge[a:b, lo:hi] if axis == 0 else edge[lo:hi, a:b].T
    thr = max(10.0, float(np.percentile(edge, 88)))
    frac = (reg > thr).mean(axis=0)
    k = int(np.argmax(frac))
    return (lo + k, float(frac[k])) if frac[k] >= 0.5 else None


def detect(source: Path, start: float, dur: float, info: dict, cfg=None, track=None) -> Layout | None:
    """Acha webcam e tela. None = nao e um video com webcam separada."""
    try:
        import cv2
        import numpy as np
    except Exception:
        return None
    sw, sh = int(info.get("width") or 0), int(info.get("height") or 0)
    if sw < 640 or sw / max(1, sh) < 1.5:
        return None
    track = track or faces.analyze(source, start, dur, info, cfg)
    if track is None or not track.found:
        return None
    face = _static_face(track)
    if face is None:
        return None
    w = 640
    h = max(2, int(round(w * sh / sw / 2)) * 2)
    step, frames = max(1, int(dur * faces.SAMPLE_FPS / N_FRAMES)), []
    for i, (_t, fr) in enumerate(faces._decode(source, start, dur, w, h)):
        if i % step == 0:
            frames.append(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY).astype(np.float32))
    if len(frames) < 8:
        return None
    st = np.stack(frames)
    gx = np.median(np.abs(np.stack([cv2.Sobel(f, cv2.CV_32F, 1, 0, ksize=3) for f in frames])), axis=0)
    gy = np.median(np.abs(np.stack([cv2.Sobel(f, cv2.CV_32F, 0, 1, ksize=3) for f in frames])), axis=0)
    fx0, fy0, fx1, fy1 = int(face[0] * w), int(face[1] * h), int(face[2] * w), int(face[3] * h)
    fw, fh = max(6, fx1 - fx0), max(6, fy1 - fy0)
    # faixa vertical/horizontal em volta do rosto onde as bordas da janela tem que aparecer
    ya, yb = max(0, fy0 - int(0.2 * fh)), min(h, fy1 + int(0.8 * fh))
    xa, xb = max(0, fx0 - int(0.4 * fw)), min(w, fx1 + int(0.4 * fw))
    reach_x, reach_y = int(4.0 * fw), int(3.0 * fh)
    found, conf = {}, []
    for name, res in (("l", _border(gx, fx0 - reach_x, fx0 - int(0.25 * fw), ya, yb, 0, -1)),
                      ("r", _border(gx, fx1 + int(0.25 * fw), min(w, fx1 + reach_x), ya, yb, 0, 1)),
                      ("t", _border(gy, fy0 - reach_y, fy0 - int(0.15 * fh), xa, xb, 1, -1)),
                      ("b", _border(gy, fy1 + int(0.3 * fh), min(h, fy1 + reach_y), xa, xb, 1, 1))):
        if res is not None:
            found[name] = res[0]
            conf.append(res[1])
    # lado sem linha: vale a beirada do quadro se estiver perto
    if "l" not in found and fx0 - 2.2 * fw < 0:
        found["l"] = 0
    if "r" not in found and fx1 + 2.2 * fw > w:
        found["r"] = w
    if "t" not in found and fy0 - 1.6 * fh < 0:
        found["t"] = 0
    if "b" not in found and fy1 + 2.0 * fh > h:
        found["b"] = h
    if len(conf) < 2 or len(found) < 4 or sum(conf) / len(conf) < 0.85:
        _log.debug("webcam sem moldura clara (%s)", found)
        return None
    x0, x1, y0, y1 = found["l"], found["r"], found["t"], found["b"]
    cw, ch = x1 - x0, y1 - y0
    area = cw * ch / (w * h)
    if not (0.02 <= area <= 0.32 and 0.7 <= cw / max(1, ch) <= 2.4 and cw > 1.15 * fw and ch > 1.15 * fh):
        _log.debug("janela de webcam improvavel: %s area %.2f", (x0, y0, x1, y1), area)
        return None
    inset = 3   # tira a moldura
    cam = ((x0 + inset) / w, (y0 + inset) / h, (x1 - inset) / w, (y1 - inset) / h)

    # ---- tela: onde ha movimento fora da webcam
    act = st.std(axis=0)
    act[y0:y1, x0:x1] = 0
    outside = np.ones_like(act, bool)
    outside[y0:y1, x0:x1] = False
    framed = len(conf) == 4 and sum(conf) / 4 >= 0.97
    if not framed and float(np.median(act[outside])) < 6 and float((act[outside] > 14).mean()) < 0.25:
        _log.debug("fora da janela quase nada se mexe: nao e webcam com tela")   # podcast: cenario parado
        return None
    mask = act > max(8.0, 0.30 * float(np.percentile(act[outside], 95)))
    cols, rows = mask.mean(axis=0) > 0.15, mask.mean(axis=1) > 0.22
    if cols.sum() < 0.3 * w or rows.sum() < 0.25 * h:
        bx0, bx1, by0, by1 = 0, w, 0, h
    else:
        cx, cy = np.flatnonzero(cols), np.flatnonzero(rows)
        bx0, bx1, by0, by1 = int(cx[0]), int(cx[-1]) + 1, int(cy[0]), int(cy[-1]) + 1
    # candidatos: a tela inteira sem a faixa da webcam (4 jeitos), com proporcao que fica boa em pe
    cands = []
    for rx0, ry0, rx1, ry1 in ((bx0, by0, min(bx1, x0), by1), (max(bx0, x1), by0, bx1, by1),
                               (bx0, by0, bx1, min(by1, y0)), (bx0, max(by0, y1), bx1, by1)):
        rw, rh = rx1 - rx0, ry1 - ry0
        if rw < 0.3 * w or rh < 0.3 * h:
            continue
        ar = rw / rh
        if ar < 1.05:                                  # alto demais: corta em cima e embaixo
            nh = int(rw / 1.05)
            ry0 += (rh - nh) // 2
            rh = nh
            ry1 = ry0 + nh
        elif ar > 1.95:                                # largo demais: tira as pontas
            nw = int(rh * 1.95)
            rx0 += (rw - nw) // 2
            rw = nw
            rx1 = rx0 + nw
        cands.append((rw * rh * (0.6 + 0.4 * float(mask[ry0:ry1, rx0:rx1].mean())), (rx0, ry0, rx1, ry1)))
    if not cands:
        return None
    r = max(cands)[1]
    kx, ky = max(1e-3, cam[2] - cam[0]), max(1e-3, cam[3] - cam[1])
    fx_ = min(1.0, max(0.0, ((face[0] + face[2]) / 2 - cam[0]) / kx))
    ft_ = min(1.0, max(0.0, (face[1] - 0.35 * (face[3] - face[1]) - cam[1]) / ky))
    return Layout(cam, (r[0] / w, r[1] / h, r[2] / w, r[3] / h), float(sum(conf) / len(conf)), fx_, ft_)


# ------------------------------------------------------------------ montagem
def _px(box, sw: int, sh: int) -> tuple[int, int, int, int]:
    x0, y0 = int(box[0] * sw) // 2 * 2, int(box[1] * sh) // 2 * 2
    cw, ch = int((box[2] - box[0]) * sw) // 2 * 2, int((box[3] - box[1]) * sh) // 2 * 2
    return x0, y0, max(16, min(cw, sw - x0)), max(16, min(ch, sh - y0))


_KNOWN: dict[str, Layout] = {}     # video -> posicao ja achada (a webcam nao muda de lugar entre as partes)


def compose(source: Path, start: float, dur: float, info: dict, cfg=None, track=None, key: str = "") -> Path | None:
    """Monta o video em pe (tela no meio, webcam grande embaixo). Devolve o arquivo temporario ou None."""
    t0 = time.time()
    lay = detect(source, start, dur, info, cfg, track)
    old = _KNOWN.get(key) if key else None
    if lay is not None and old is not None and abs(lay.cam[0] - old.cam[0]) < 0.04 and abs(lay.cam[1] - old.cam[1]) < 0.04:
        lay.screen = old.screen        # mesma janela: mantem o recorte da tela da primeira parte
    if lay is None:
        return None
    if key and old is None:
        _KNOWN[key] = lay
    sw, sh = int(info["width"]), int(info["height"])
    cx, cy, cw, ch = _px(lay.cam, sw, sh)
    sx, sy, scw, sch = _px(lay.screen, sw, sh)
    # em cima: a tela inteira sobre fundo desfocado; embaixo: a webcam preenche tudo, centrada no rosto
    hs = min(int(W * sch / scw), SCREEN_MAX_H) // 2 * 2
    y1 = SCREEN_TOP + max(0, SCREEN_MAX_H - hs) // 2
    hc = CAM_H
    scale = max(W / cw, hc / ch)
    fw_, fh_ = int(cw * scale) // 2 * 2 + 2, int(ch * scale) // 2 * 2 + 2
    fx = lay.face_x * fw_                                   # centro do rosto na webcam ampliada
    ox = int(min(max(0, fx - W / 2), fw_ - W)) // 2 * 2
    oy = int(min(max(0, fh_ - hc), max(0.0, lay.face_top * fh_ - 90))) // 2 * 2   # folga acima da cabeca p/ o titulo
    out = paths.TMP / f"react_{short_hash(f'{source}{start}{time.time()}')}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    threads = str(max(1, min(6, int((cfg.get("edicao.threads", 6) if cfg is not None else 6) or 6))))

    graph = (f"[0:v]fps=30,split=3[a][b][c];"
             f"[a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=10:2,"
             f"scale={W}:{H}:flags=bilinear,eq=brightness=-0.16:saturation=1.2,setsar=1[bg];"
             f"[b]crop={scw}:{sch}:{sx}:{sy},scale={W}:{hs}:force_original_aspect_ratio=increase:flags=bicubic,"
             f"crop={W}:{hs},setsar=1[ct];"
             f"[c]crop={cw}:{ch}:{cx}:{cy},scale={fw_}:{fh_}:flags=bicubic,crop={W}:{hc}:{ox}:{oy},unsharp=5:5:0.5,setsar=1[cam];"
             f"[bg][ct]overlay=0:{y1}[t];[t][cam]overlay=0:{SEAM},format=yuv420p[v]")
    args = ["-threads", threads, "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(source), "-filter_complex", graph, "-map", "[v]",
            "-map", "0:a?", "-c:v", "libx264", "-preset", "superfast", "-crf", "17", "-c:a", "aac", "-b:a", "192k", str(out)]
    try:
        ff.run(args)
    except Exception as e:
        _log.warning("separar a webcam falhou, sigo no layout normal: %s", str(e)[:200])
        out.unlink(missing_ok=True)
        return None
    _log.info("webcam separada: tela %dx%d em cima, webcam %dx%d embaixo (confianca %.2f, %.1fs)", W, hs, W, hc, lay.conf,
              time.time() - t0)
    return out


def only_bottom_faces(track) -> None:
    """No video montado, so o rosto da webcam (embaixo da emenda) e protegido; os da tela podem ficar sob o titulo."""
    lim = SEAM / H
    for sh in track.shots:
        groups = [[d for d in g if d.cy > lim] for g in [sh.dets, *sh.others_dets]]
        groups = [g for g in groups if g]
        sh.others_dets, sh.others = [], []
        if not groups:
            sh.dets, sh.box, sh.cx, sh.cy, sh.eye = [], None, None, None, None
            continue
        main = max(groups, key=len)
        sh.dets, sh.box = main, faces.face_envelope(main)
        n = len(main)
        sh.cx, sh.cy = sum(d.cx for d in main) / n, sum(d.cy for d in main) / n
        sh.fh, sh.eye = sum(d.fh for d in main) / n, sum(d.eye for d in main) / n
