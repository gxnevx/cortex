"""Enquadramento que segue o rosto (layout full e metade de cima do split).

Decodifica o trecho em baixa resolucao (320 px, 10 quadros/s), detecta cortes de camera
(diferenca entre quadros) e rostos (YuNet do OpenCV, modelo de 230 KB em
assets/modelos_visao/). Para cada plano (trecho entre cortes de camera) escolhe quem fala:
o rosto mais presente e maior, com desempate pelo movimento da boca. O enquadramento fica
parado dentro do plano (visual de editor, sem tremedeira) e so acompanha se a pessoa se
mexer bastante; troca seca no corte de camera. Sem rosto: recorte central.

Tempos relativos ao inicio do corte (linha do tempo da fonte, antes dos jump cuts).
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .. import paths
from ..log import get as get_log
from ..util import CREATE_NO_WINDOW
from . import ffmpeg as ff

_log = get_log(__name__)

MODEL_DIR = paths.ASSETS / "modelos_visao"
YUNET = MODEL_DIR / "face_detection_yunet_2023mar.onnx"
SAMPLE_FPS = 10          # quadros por segundo analisados (cortes de camera com precisao de 0,1 s)
DETECT_EVERY = 2         # roda o detector a cada N amostras (5/s) + logo apos cada corte de camera
SAMPLE_W = 320
MIN_FACE_H = 0.07        # rosto menor que 7% da altura e plateia/quadro na parede
MIN_SCORE = 0.62
MIN_SHOT_S = 0.35
MAX_THREADS = 6          # nao satura a CPU
# caixa do YuNet vai da sobrancelha/testa baixa ao queixo: estende ate a linha do cabelo e da margem
FACE_TOP = 0.22          # fracao da altura da caixa acrescentada acima (testa)
FACE_BOTTOM = 0.07       # abaixo (queixo)
FACE_SIDE = 0.08         # de cada lado
OTHER_MIN_PRESENCE = 0.3
# folga so do PLANO (alem da margem acima): a caixa do detector varia uns 3 a 5% com a escala da
# imagem (320 px na analise x 1080 px na saida); sem isto a conferencia independente raspava na margem
PLAN_EXTRA_TOP, PLAN_EXTRA_BOTTOM, PLAN_EXTRA_SIDE = 0.03, 0.05, 0.03


@dataclass
class Det:
    t: float
    cx: float            # centro normalizado (0..1) no quadro da fonte
    cy: float
    fh: float            # altura do rosto normalizada
    score: float
    mouth: float = 0.0   # movimento na regiao da boca (0..~1)
    box: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)   # caixa do YuNet (x0, y0, x1, y1) normalizada
    eye: float = 0.0     # linha dos olhos (media dos 2 pontos dos olhos), normalizada


@dataclass
class Shot:
    t0: float
    t1: float
    cx: float | None = None          # centro do rosto escolhido (None = sem rosto)
    cy: float | None = None
    fh: float = 0.0
    drift: list[tuple[float, float]] = field(default_factory=list)   # (t, cx) dentro do plano
    # geometria para nada cobrir o rosto: envelope (testa ao queixo + margem) do rosto escolhido
    # durante o plano, linha dos olhos e os outros rostos relevantes (fracoes da fonte)
    box: tuple[float, float, float, float] | None = None
    eye: float | None = None
    others: list[tuple[float, float, float, float]] = field(default_factory=list)
    dets: list = field(default_factory=list)           # deteccoes do rosto escolhido (Det), em ordem
    others_dets: list = field(default_factory=list)    # [[Det, ...], ...] dos outros rostos relevantes

    def boxes_at(self, t: float, win: float = 0.4) -> list[tuple[float, float, float, float]]:
        """Retangulos protegidos (fracoes da fonte) no instante t da FONTE: envelope das deteccoes
        em t +- win (o rosto se mexe); sem deteccao por perto, o envelope do plano."""
        out = []
        main = _local_box(self.dets, t, win)
        if main is None and self.box is not None:
            main = self.box
        if main is not None:
            out.append(main)
        for i, od in enumerate(self.others_dets):
            b = _local_box(od, t, win)
            if b is None and not od and i < len(self.others):
                b = self.others[i]
            if b is not None:
                out.append(b)
        return out


@dataclass
class FaceTrack:
    shots: list[Shot]
    width: int
    height: int
    samples: int = 0
    detections: int = 0
    secs: float = 0.0

    @property
    def found(self) -> bool:
        return any(s.cx is not None for s in self.shots)

    def face_at(self, t: float) -> tuple[float, float, float] | None:
        for s in self.shots:
            if s.t0 <= t < s.t1 and s.cx is not None:
                return s.cx, s.cy or 0.4, s.fh
        return None


def available() -> bool:
    if not YUNET.exists():
        return False
    try:
        import cv2  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _decode(source: Path, start: float, dur: float, w: int, h: int):
    """Gera (t, quadro BGR) a SAMPLE_FPS em w x h."""
    import numpy as np

    cmd = [ff.ffmpeg_bin(), "-hide_banner", "-nostdin", "-v", "error", "-threads", str(MAX_THREADS),
           "-skip_frame:v", "noref", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(source),
           "-an", "-sn", "-vf", f"fps={SAMPLE_FPS},scale={w}:{h}:flags=bilinear",
           "-pix_fmt", "bgr24", "-f", "rawvideo", "pipe:1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
    size = w * h * 3
    i = 0
    try:
        assert proc.stdout is not None
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield i / SAMPLE_FPS, np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            i += 1
    finally:
        try:
            proc.stdout.close()  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            proc.kill()


def analyze(source: Path, start: float, dur: float, info: dict, cfg=None) -> FaceTrack | None:
    """Analisa o trecho [start, start+dur] da fonte. None se o OpenCV/modelo faltar ou der erro."""
    if not available():
        _log.info("Seguir rosto desligado: OpenCV ou modelo YuNet ausente (%s)", YUNET.name)
        return None
    import cv2
    import numpy as np

    t_begin = time.time()
    sw, sh = int(info.get("width") or 1920), int(info.get("height") or 1080)
    w = SAMPLE_W
    h = max(2, int(round(w * sh / sw / 2)) * 2)
    try:
        cv2.setNumThreads(min(4, MAX_THREADS))
        det = cv2.FaceDetectorYN.create(str(YUNET), "", (w, h), MIN_SCORE, 0.3, 20)
    except Exception as e:  # noqa: BLE001
        _log.info("YuNet indisponivel: %s", e)
        return None

    dets: list[Det] = []
    diffs: list[tuple[float, float]] = []
    prev_small = None
    prev_gray = None
    n = 0
    force_detect = True
    try:
        for t, frame in _decode(source, start, dur, w, h):
            n += 1
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            small = cv2.resize(gray, (64, max(2, 64 * h // w)), interpolation=cv2.INTER_AREA).astype(np.int16)
            d = float(np.abs(small - prev_small).mean()) if prev_small is not None else 0.0
            diffs.append((t, d))
            if d > 22:
                force_detect = True
            if force_detect or (n - 1) % DETECT_EVERY == 0:
                force_detect = False
                _ok, faces = det.detect(frame)
                if faces is not None:
                    for f in faces:
                        x, y, fw, fhh = (float(v) for v in f[:4])
                        score = float(f[14])
                        if fhh / h < MIN_FACE_H or score < MIN_SCORE:
                            continue
                        mouth = 0.0
                        if prev_gray is not None:
                            # regiao da boca: entre os cantos (landmarks 4 e 5), um pouco abaixo
                            mx0, my0, mx1, my1 = f[10], f[11], f[12], f[13]
                            pad = 0.18 * fw
                            x0 = int(max(0, min(mx0, mx1) - pad))
                            x1 = int(min(w, max(mx0, mx1) + pad))
                            y0 = int(max(0, min(my0, my1) - 0.12 * fhh))
                            y1 = int(min(h, max(my0, my1) + 0.22 * fhh))
                            if x1 - x0 >= 3 and y1 - y0 >= 3:
                                a = gray[y0:y1, x0:x1].astype(np.int16)
                                b = prev_gray[y0:y1, x0:x1].astype(np.int16)
                                mouth = float(np.abs(a - b).mean()) / 40.0
                        eye_y = (float(f[5]) + float(f[7])) / 2 / h
                        dets.append(Det(t, (x + fw / 2) / w, (y + fhh / 2) / h, fhh / h, score, mouth,
                                        box=(x / w, y / h, (x + fw) / w, (y + fhh) / h), eye=eye_y))
            prev_small = small
            prev_gray = gray
    except Exception as e:  # noqa: BLE001
        _log.info("Analise de rosto falhou: %s", e)
        return None
    if n == 0:
        return None

    shots = _shots(diffs, n / SAMPLE_FPS)
    for s in shots:
        _frame_shot(s, [d for d in dets if s.t0 <= d.t < s.t1])
    _fill_gaps(shots)
    tr = FaceTrack(shots, sw, sh, samples=n, detections=len(dets), secs=round(time.time() - t_begin, 2))
    _log.debug("rosto: %d amostras, %d deteccoes, %d planos, %.1fs", n, len(dets), len(shots), tr.secs)
    return tr


def _shots(diffs: list[tuple[float, float]], total: float) -> list[Shot]:
    """Divide em planos pelos cortes de camera (salto grande na diferenca entre quadros)."""
    import statistics

    vals = [d for _t, d in diffs[1:]] or [0.0]
    base = statistics.median(vals)
    thr = max(18.0, base * 4.0)
    cuts = [0.0]
    for i, (t, d) in enumerate(diffs):
        if i == 0 or d < thr:
            continue
        # pico local (evita marcar 2 cortes numa transicao de 2 quadros)
        nxt = diffs[i + 1][1] if i + 1 < len(diffs) else 0.0
        if d >= nxt and t - cuts[-1] >= MIN_SHOT_S:
            cuts.append(t - 0.5 / SAMPLE_FPS)   # o corte aconteceu entre a amostra anterior e esta
    bounds = cuts + [total]
    return [Shot(a, b) for a, b in zip(bounds[:-1], bounds[1:]) if b - a > 0.01]


def _frame_shot(shot: Shot, dets: list[Det]) -> None:
    """Escolhe o rosto principal do plano e define o centro (com deriva se a pessoa andar)."""
    if not dets:
        return
    sample_ts = sorted({d.t for d in dets})
    n_frames = max(1, len(sample_ts))
    # agrupa por posicao horizontal
    clusters: list[list[Det]] = []
    for d in sorted(dets, key=lambda d: d.cx):
        if clusters and abs(d.cx - clusters[-1][-1].cx) <= 0.08:
            clusters[-1].append(d)
        else:
            clusters.append([d])

    def med(xs):
        xs = sorted(xs)
        return xs[len(xs) // 2]

    scored = []
    for c in clusters:
        presence = min(1.0, len({d.t for d in c}) / n_frames)
        size = med([d.fh for d in c])
        mouth = sum(d.mouth for d in c) / len(c)
        scored.append([presence * size, presence, size, mouth, c])
    scored.sort(key=lambda s: -s[0])
    best = scored[0]
    if len(scored) > 1:
        other = scored[1]
        # dois rostos parecidos no plano: quem mexe mais a boca provavelmente esta falando
        if other[1] >= 0.5 and best[2] / max(1e-6, other[2]) < 1.35 and other[3] > best[3] * 1.3 + 0.02:
            best = other
    c = sorted(best[4], key=lambda d: d.t)
    shot.cx = med([d.cx for d in c])
    shot.cy = med([d.cy for d in c])
    shot.fh = best[2]
    shot.box = face_envelope(c)
    eyes = [d.eye for d in c if d.eye > 0]
    shot.eye = med(eyes) if eyes else shot.cy - 0.15 * shot.fh
    others = [o for o in scored if o is not best and o[1] >= OTHER_MIN_PRESENCE][:3]
    shot.others = [face_envelope(o[4]) for o in others]
    shot.dets = c
    shot.others_dets = [sorted(o[4], key=lambda d: d.t) for o in others]
    # deriva: plano longo com a pessoa se movendo -> segue com zona morta
    if shot.t1 - shot.t0 >= 4.0 and len(c) >= 6:
        xs = [d.cx for d in c]
        spread = sorted(xs)[int(len(xs) * 0.9)] - sorted(xs)[int(len(xs) * 0.1)]
        if spread > 0.06:
            win = 5
            smooth = [(c[i].t, med([d.cx for d in c[max(0, i - win // 2): i + win // 2 + 1]])) for i in range(len(c))]
            cur = smooth[0][1]
            keys = [(shot.t0, cur)]
            for t, x in smooth[1:]:
                if abs(x - cur) > 0.05 and t - keys[-1][0] >= 1.0:
                    cur = x
                    keys.append((t, x))
            if len(keys) > 1:
                shot.drift = keys
                shot.cx = keys[0][1]


def _fill_gaps(shots: list[Shot]) -> None:
    """Plano curto sem rosto (deteccao falhou) entre dois planos com o mesmo enquadramento herda ele."""
    for i, s in enumerate(shots):
        if s.cx is not None:
            continue
        prev = shots[i - 1] if i > 0 else None
        nxt = shots[i + 1] if i + 1 < len(shots) else None
        if s.t1 - s.t0 <= 1.2:
            ref = prev if (prev and prev.cx is not None) else (nxt if (nxt and nxt.cx is not None) else None)
            if ref is not None:
                s.cx, s.cy, s.fh = ref.cx, ref.cy, ref.fh
                s.box, s.eye, s.others = ref.box, ref.eye, list(ref.others)
                # plano curto sem deteccao: herda so o envelope (as deteccoes sao de outro trecho)


def face_envelope(dets: list[Det]) -> tuple[float, float, float, float]:
    """Envelope robusto (p10/p90) das caixas do rosto no plano, da linha do cabelo ao queixo + margem."""
    def pct(xs, q):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))]

    x0 = pct([d.box[0] for d in dets], 0.1)
    y0 = pct([d.box[1] for d in dets], 0.1)
    x1 = pct([d.box[2] for d in dets], 0.9)
    y1 = pct([d.box[3] for d in dets], 0.9)
    return plan_box(x0, y0, max(1e-4, x1 - x0), max(1e-4, y1 - y0))


def plan_box(x: float, y: float, w: float, h: float) -> tuple[float, float, float, float]:
    """Retangulo que o PLANO protege: expand_box + folga para a variacao do detector."""
    a, b, c, d = expand_box(x, y, w, h)
    return (a - PLAN_EXTRA_SIDE * w, b - PLAN_EXTRA_TOP * h, c + PLAN_EXTRA_SIDE * w, d + PLAN_EXTRA_BOTTOM * h)


def _local_box(dets: list, t: float, win: float) -> tuple[float, float, float, float] | None:
    near = [d for d in dets if abs(d.t - t) <= win]
    if not near:
        cand = [d for d in dets if abs(d.t - t) <= 2.5 * win]
        if not cand:
            return None
        near = [min(cand, key=lambda d: abs(d.t - t))]
    x0 = min(d.box[0] for d in near)
    y0 = min(d.box[1] for d in near)
    x1 = max(d.box[2] for d in near)
    y1 = max(d.box[3] for d in near)
    return plan_box(x0, y0, x1 - x0, y1 - y0)


def expand_box(x: float, y: float, w: float, h: float) -> tuple[float, float, float, float]:
    """Caixa do YuNet (qualquer escala) -> retangulo protegido (testa ao queixo + margem), mesma escala."""
    return (x - FACE_SIDE * w, y - FACE_TOP * h, x + w + FACE_SIDE * w, y + h + FACE_BOTTOM * h)


@dataclass
class FaceSeg:
    """Um plano dentro de um pedaco da montagem, na linha do tempo da SAIDA."""
    t0: float
    t1: float
    shot: Shot
    src: list            # amostras de tempo da fonte (10/s) ...
    out: list            # ... e o tempo correspondente na saida (cresce; jump cut = degrau parado)

    def src_at(self, t_out: float) -> float:
        import bisect

        i = bisect.bisect_right(self.out, t_out) - 1
        i = max(0, min(len(self.src) - 1, i))
        if i + 1 < len(self.src) and self.out[i + 1] > self.out[i]:
            f = (t_out - self.out[i]) / (self.out[i + 1] - self.out[i])
            return self.src[i] + max(0.0, min(1.0, f)) * (self.src[i + 1] - self.src[i])
        return self.src[i]

    def boxes_at(self, t_out: float, win: float = 0.4) -> list:
        return self.shot.boxes_at(self.src_at(t_out), win)

    # compatibilidade: (t0, t1, shot) = seg
    def __iter__(self):
        return iter((self.t0, self.t1, self.shot))


def segments(track: FaceTrack | None, total: float, time_map=None, pieces=None, splits=None,
             min_len: float = 2.5) -> list[FaceSeg]:
    """Planos com rosto na ordem da saida: um por plano em cada pedaco da montagem (teaser +
    corte com jump cuts). A deriva dentro do plano nao abre um novo trecho.

    splits: instantes da saida (jump cuts) em que um plano longo (> 2 x min_len) pode trocar de
    enquadramento escondido pelo corte (monologos longos)."""
    if track is None:
        return []
    out: list[FaceSeg] = []
    for a, b, fn in _pieces(time_map, pieces):
        for s in track.shots:
            if s.t1 <= a or s.t0 >= b:
                continue
            sa, sb = max(s.t0, a), min(s.t1, b)
            t0, t1 = fn(sa), min(fn(sb), total)
            if t1 - t0 <= 1e-3:
                continue
            n = max(2, int((sb - sa) * 10) + 1)
            src = [sa + (sb - sa) * i / (n - 1) for i in range(n)]
            outs = [min(total, fn(x)) for x in src]
            cuts = [t0]
            for sp in sorted(splits or []):
                if t1 - t0 > 2 * min_len and cuts[-1] + min_len <= sp <= t1 - min_len:
                    cuts.append(sp)
            cuts.append(t1)
            for a_, b_ in zip(cuts[:-1], cuts[1:]):
                out.append(FaceSeg(a_, b_, s, src, outs))
    out.sort(key=lambda k: k.t0)
    return out


# ------------------------------------------------------------------ enquadramento por layout
Piece = tuple[float, float, "object"]   # (inicio na fonte, fim na fonte, funcao fonte -> saida)


def _pieces(time_map=None, pieces=None) -> list:
    if pieces:
        return list(pieces)
    return [(0.0, float("inf"), time_map or (lambda t: t))]


def timeline(track: FaceTrack | None, time_map=None, pieces=None) -> list[tuple]:
    """Chaves (t_saida, cx, cy, fh, duracao_da_transicao) do rosto escolhido, plano a plano.

    `pieces` descreve a montagem: [(ini_fonte, fim_fonte, mapa)] em ordem de saida (ex.: teaser +
    corte inteiro com jump cuts). Inicio de pedaco e corte de camera -> troca seca; deriva -> suave.
    """
    if track is None:
        return []
    out: list[tuple] = []
    for a, b, fn in _pieces(time_map, pieces):
        for s in track.shots:
            if s.t1 <= a or s.t0 >= b:
                continue
            t_src = max(s.t0, a)
            cx = s.cx
            for t, x in s.drift:
                if t <= t_src + 1e-6:
                    cx = x
            out.append((fn(t_src), cx, s.cy, s.fh, 0.0))
            for t, x in s.drift[1:]:
                if t_src < t < b:
                    out.append((fn(t), x, s.cy, s.fh, 0.45))
    out.sort(key=lambda k: k[0])
    return out


def crop_keys(track: FaceTrack | None, crop_w: int, src_w: int, time_map=None, dur_out: float | None = None,
              ease_s: float = 0.45, pieces=None) -> list[tuple[float, float, float]]:
    """Chaves (t_saida, x_em_px, duracao_da_transicao) do recorte horizontal de largura crop_w.

    Corte de camera -> troca seca (0 s); deriva dentro do plano -> transicao suave.
    """
    center = (src_w - crop_w) / 2

    def x_for(cx: float | None) -> float:
        if cx is None:
            return center
        x = cx * src_w - crop_w / 2
        return float(max(0, min(src_w - crop_w, x)))

    if track is None or not track.found:
        return [(0.0, center, 0.0)]
    keys = [(t, x_for(cx), (ease_s if d > 0 else 0.0)) for t, cx, _cy, _fh, d in timeline(track, time_map, pieces)
            if dur_out is None or t < dur_out]
    # remove chaves redundantes (mesmo x) e duplicadas no mesmo instante
    out: list[tuple[float, float, float]] = []
    for k in keys:
        if out and k[0] - out[-1][0] < 0.05:
            out[-1] = (out[-1][0], k[1], out[-1][2])
            continue
        if out and abs(k[1] - out[-1][1]) < 2:
            continue
        out.append(k)
    if out and out[0][0] > 0:
        out.insert(0, (0.0, out[0][1], 0.0))
    return out or [(0.0, center, 0.0)]


def eye_frac(cy: float | None, fh: float) -> float | None:
    """Linha dos olhos (fracao da altura da fonte): ~15% da altura do rosto acima do centro."""
    return None if cy is None else cy - 0.15 * fh


def face_spans(track: FaceTrack | None, total: float, time_map=None, pieces=None) -> list[tuple]:
    """[(t0_saida, t1_saida, cy, fh)] dos trechos com rosto, na linha do tempo da saida."""
    keys = timeline(track, time_map, pieces)
    out = []
    for i, (t, cx, cy, fh, _d) in enumerate(keys):
        t1 = keys[i + 1][0] if i + 1 < len(keys) else total
        if cx is not None and cy is not None and t1 > t:
            out.append((t, min(t1, total), cy, fh))
    return out


def eye_line(track: FaceTrack | None, total: float, time_map=None, pieces=None, q: float = 0.25) -> float | None:
    """Linha dos olhos mais alta "tipica" (quantil q ponderado pela duracao), fracao da fonte."""
    spans = face_spans(track, total, time_map, pieces)
    if not spans:
        return None
    vals = sorted((eye_frac(cy, fh), t1 - t0) for t0, t1, cy, fh in spans)
    tot = sum(w for _v, w in vals)
    acc = 0.0
    for v, w in vals:
        acc += w
        if acc >= q * tot:
            return v
    return vals[-1][0]


def face_band(track: FaceTrack | None, t0: float, t1: float, total: float, time_map=None,
              pieces=None) -> tuple[float, float] | None:
    """Faixa vertical (fracao da fonte) de sobrancelha a boca dos rostos visiveis em [t0, t1]."""
    spans = [s for s in face_spans(track, total, time_map, pieces) if s[1] > t0 and s[0] < t1]
    if not spans:
        return None
    top = min(cy - 0.30 * fh for _a, _b, cy, fh in spans)
    bottom = max(cy + 0.36 * fh for _a, _b, cy, fh in spans)
    return top, bottom
