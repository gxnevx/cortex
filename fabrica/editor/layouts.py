"""Layouts verticais 1080x1920 (filtergraphs do ffmpeg).

  split -> video principal em cima (preenche e corta) + fundo da biblioteca embaixo
           (gameplay/satisfying/procedural, sem audio, offset aleatorio, em loop se curto)
  blur  -> video inteiro na largura 1080 sobre copia desfocada/escurecida que preenche a tela
           (blur barato: reduz -> boxblur -> amplia)
  full  -> recorte central 9:16 (bom para fonte vertical ou rosto unico)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from . import style as _style

W, H = 1080, 1920
HALF = H // 2
VALID = ("split", "blur", "full")

# no blur o video fica um pouco acima do centro; a legenda vai embaixo dele (y~1310)
BLUR_CENTER_Y = 860
BLUR_MAX_H = 1000          # altura maxima do video no blur (deixa espaco p/ titulo e legenda)

# Distribuicao do layout "auto" para fonte horizontal (escolha deterministica por corte).
# Split ("brainrot") e ferramenta, nao padrao; nunca em politica/noticia; fonte que ja e jogo vai sem split.
AUTO_WEIGHTS = {
    "politica": [("full", 0.6), ("blur", 0.4)],
    "noticias": [("full", 0.6), ("blur", 0.4)],
    "games": [("blur", 0.6), ("full", 0.4)],
    "padrao": [("split", 0.4), ("full", 0.4), ("blur", 0.2)],
}


def is_vertical(info: dict) -> bool:
    w, h = info.get("width") or 0, info.get("height") or 0
    return bool(w and h and h / w >= 1.2)


def choose_layout(info: dict, plan=None, cfg=None, override: str | None = None,
                  has_backgrounds: bool = True) -> str:
    """Decide o layout. Prioridade: argumento > config (se != auto) > plan.layout > automatico."""
    def ok(x):
        return isinstance(x, str) and x.lower() in VALID

    chosen = None
    if ok(override):
        chosen = override.lower()
    else:
        conf = str(cfg.get("edicao.layout", "auto") if cfg is not None else "auto").lower()
        if ok(conf):
            chosen = conf
        elif plan is not None and ok(getattr(plan, "layout", None)):
            chosen = plan.layout.lower()
    if chosen is None:
        if is_vertical(info):
            chosen = "full"
        else:
            cat = _style.niche_key(getattr(plan, "category", None) if plan is not None else None)
            weights = AUTO_WEIGHTS.get(cat, AUTO_WEIGHTS["padrao"])
            if cfg is not None and isinstance(cfg.get("edicao.layout_pesos"), dict) and cat not in (
                    "politica", "noticias", "games"):
                weights = [(k, float(v)) for k, v in cfg.get("edicao.layout_pesos").items() if k in VALID] or weights
            if not has_backgrounds:
                weights = [(k, w) for k, w in weights if k != "split"] or [("blur", 1.0)]
            seed = getattr(plan, "id", None) or getattr(plan, "title", "") or ""
            chosen = _style.stable_pick(f"layout:{seed}", weights)
    if chosen == "split" and not has_backgrounds:
        chosen = "blur"
    if chosen == "split" and is_vertical(info):
        chosen = "full"   # video vertical cortado pela metade perde o rosto
    return chosen


def split_seam(cfg=None) -> int:
    """Y da emenda do split (edicao.split_proporcao = fracao da altura do video de cima)."""
    p = float(cfg.get("edicao.split_proporcao", 0.5) if cfg is not None else 0.5)
    p = min(0.65, max(0.4, p))
    return int(round(H * p / 2) * 2)


def _fps(fps: int) -> str:
    return f"fps={fps}"


def _even(v: float) -> int:
    return max(2, int(round(v / 2)) * 2)


@dataclass
class Motion:
    """Movimento do video principal (tudo opcional; vazio = layout estatico como antes).

    pre    -> filtros logo apos o fps= (ex.: select/setpts dos jump cuts)
    track  -> faces.FaceTrack (enquadramento no rosto em full/split, ancora do zoom)
    time_map -> tempo da fonte -> tempo da saida (jump cuts)
    pieces -> montagem [(ini_fonte, fim_fonte, mapa)] quando ha teaser (cold open); vence time_map
    zoom   -> motion.ZoomPlan (punch-ins); None = sem zoom
    framing -> Framing ja montado (com o reenquadramento por plano decidido pelo safezone)
    """
    pre: str = ""
    track: object | None = None
    time_map: Callable[[float], float] | None = None
    zoom: object | None = None
    follow_face: bool = True
    info: dict = field(default_factory=dict)
    pieces: list | None = None
    framing: "Framing | None" = None


def _crop_box(sw: int, sh: int, tw: int, th: int) -> tuple[int, int, int]:
    """Maior recorte com o aspecto tw:th dentro de sw x sh -> (largura, altura, y)."""
    if sw / sh > tw / th:
        ch = sh - (sh % 2)
        cw = min(sw - (sw % 2), _even(ch * tw / th))
        return cw, ch, 0
    cw = sw - (sw % 2)
    ch = min(sh - (sh % 2), _even(cw * th / tw))
    return cw, ch, (sh - ch) // 2 // 2 * 2


# zoom total maximo (reenquadramento x punch-in): acima disso o 1080p amolece demais
ZOOM_TOTAL_MAX = 1.40


@dataclass
class Steps:
    """Curva aditiva (base + degraus/rampas) - a mesma no ffmpeg e no Python."""
    base: float
    keys: list = field(default_factory=list)

    @classmethod
    def from_points(cls, pts: list, start: float | None = None) -> "Steps":
        from . import motion as _motion

        if not pts:
            return cls(start if start is not None else 0.0, [])
        base = pts[0][1] if start is None else start
        rest = pts[1:] if start is None else pts
        return cls(base, _motion.steps_to_keys(rest, base))

    def expr(self, var: str) -> str:
        from . import motion as _motion

        return _motion.expr(self.base, self.keys, var)

    def at(self, t: float) -> float:
        from . import motion as _motion

        return _motion.value_at(self.base, self.keys, t)

    @property
    def constant(self) -> bool:
        return not any(abs(k.dv) > 1e-6 for k in self.keys)


@dataclass
class Geo:
    """Onde o video principal cai no quadro: recorte da fonte -> saida do zoompan -> quadro."""
    layout: str
    sw: int
    sh: int
    cw: int          # recorte (full/split); no blur e o quadro inteiro
    ch: int
    cy0: int
    ow: int          # tamanho da saida do zoompan
    oh: int
    ox: int          # posicao dela no quadro 1080x1920
    oy: int


def geometry(layout: str, info: dict, cfg=None) -> Geo:
    sw, sh = int(info.get("width") or 1920), int(info.get("height") or 1080)
    if layout == "blur":
        bx, by, fw, fh = blur_video_box(info)
        return Geo(layout, sw, sh, blur_crop_w(sw, sh), sh, 0, fw, fh, bx, by)
    th = split_seam(cfg) if layout == "split" else H
    cw, ch, y0 = _crop_box(sw, sh, W, th)
    return Geo(layout, sw, sh, cw, ch, y0, W, th, 0, 0)


@dataclass
class Framing:
    """Modelo do movimento do video principal: recorte horizontal (segue o rosto), zoom dinamico
    (punch-ins) x zoom base por plano, ancora nos olhos e deslocamento vertical por plano.

    O ffmpeg (zoompan) e o Python usam as MESMAS curvas: o safezone preve onde o rosto cai na
    saida e garante que nada o cubra.
        janela do zoompan (fracao do recorte): X = (1-1/z)*ax ; Y = clip(ay - (ay+dy)/z, 0, 1-1/z)
        ponto p do recorte -> saida: (p - Y) * z * oh   (o ponto ay vai para ay+dy da saida)
    """
    geo: Geo
    pan: Steps                      # x do recorte em px (full/split)
    zoom: object | None = None      # motion.ZoomPlan
    zb: Steps = field(default_factory=lambda: Steps(1.0))    # zoom base por plano (degraus)
    dy: Steps = field(default_factory=lambda: Steps(0.0))    # deslocamento vertical (fracao da saida)
    dx: Steps = field(default_factory=lambda: Steps(0.0))    # deslocamento do recorte (fracao da largura dele)
    k: Steps = field(default_factory=lambda: Steps(1.0))     # intensidade dos punch-ins no plano (1 = cheio)
    ax: Steps = field(default_factory=lambda: Steps(0.5))
    ay: Steps = field(default_factory=lambda: Steps(0.42))
    dynamic: bool = False           # usa zoompan (senao escala simples)

    def zd_at(self, t: float) -> float:
        return float(self.zoom.at(t)) if self.zoom is not None else 1.0

    def z_at(self, t: float, zb: float | None = None, zd: float | None = None, k: float | None = None) -> float:
        zd = self.zd_at(t) if zd is None else zd
        kk = self.k.at(t) if k is None else k
        z = (self.zb.at(t) if zb is None else zb) * (1.0 + kk * (zd - 1.0))
        return max(1.0, min(ZOOM_TOTAL_MAX, z))

    def crop_x(self, t: float, dx: float | None = None) -> float:
        g = self.geo
        d = self.dx.at(t) if dx is None else dx
        return min(max(self.pan.at(t) + d * g.cw, 0.0), float(g.sw - g.cw))

    def anchor_x(self, t: float, dx: float | None = None) -> float:
        """Ancora horizontal do zoom: o rosto continua no centro do punch-in mesmo com o recorte deslocado."""
        shift = (self.crop_x(t, dx) - self.pan.at(t)) / self.geo.cw
        return min(0.85, max(0.15, self.ax.at(t) - shift))

    def project(self, box, t: float, *, zb: float | None = None, dy: float | None = None,
                zd: float | None = None, dx: float | None = None) -> tuple:
        """Caixa (fracoes da FONTE) -> retangulo no quadro 1080x1920 no instante t (sem recortar)."""
        g = self.geo
        z = self.z_at(t, zb, zd)
        ax, ay = self.anchor_x(t, dx), self.ay.at(t)
        d = self.dy.at(t) if dy is None else dy
        px = self.crop_x(t, dx)
        X = (1 - 1 / z) * ax
        Y = min(max(ay - (ay + d) / z, 0.0), 1 - 1 / z)
        a0, a1 = (box[0] * g.sw - px) / g.cw, (box[2] * g.sw - px) / g.cw
        b0, b1 = (box[1] * g.sh - g.cy0) / g.ch, (box[3] * g.sh - g.cy0) / g.ch
        return (g.ox + (a0 - X) * z * g.ow, g.oy + (b0 - Y) * z * g.oh,
                g.ox + (a1 - X) * z * g.ow, g.oy + (b1 - Y) * z * g.oh)

    def visible(self, r) -> tuple | None:
        """Parte do retangulo dentro da area do video principal (None se nada aparece)."""
        g = self.geo
        x0, y0 = max(r[0], g.ox), max(r[1], g.oy)
        x1, y1 = min(r[2], g.ox + g.ow), min(r[3], g.oy + g.oh)
        return (x0, y0, x1, y1) if x1 - x0 > 4 and y1 - y0 > 4 else None

    # -------------------------------------------------------------- expressoes do ffmpeg
    def zoom_expr(self) -> str:
        zd = self.zoom.expr("it") if self.zoom is not None else "1"
        if self.zoom is not None and not (self.k.constant and abs(self.k.base - 1.0) < 1e-6):
            zd = f"(1+({self.k.expr('it')})*(({zd})-1))"
        if self.zb.constant and abs(self.zb.base - 1.0) < 1e-6:
            return f"max(1,min({ZOOM_TOTAL_MAX},{zd}))" if self.zoom is not None else "1"
        return f"max(1,min({ZOOM_TOTAL_MAX},({self.zb.expr('it')})*({zd})))"

    def y_expr(self) -> str:
        ay, dy = self.ay.expr("it"), self.dy.expr("it")
        return f"clip(ih*({ay})-ih*({ay}+{dy})/zoom,0,ih-ih/zoom)"

    def x_expr(self) -> str:
        if self.geo.layout == "blur" or (self.dx.constant and abs(self.dx.base) < 1e-9):
            return f"(iw-iw/zoom)*({self.ax.expr('it')})"
        g = self.geo
        # mesmo deslocamento do recorte (limitado a borda da fonte), em fracao da largura do recorte
        shift = f"(clip({self.pan.expr('it')}+({self.dx.expr('it')})*{g.cw},0,{g.sw - g.cw})-({self.pan.expr('it')}))/{g.cw}"
        return f"(iw-iw/zoom)*clip(({self.ax.expr('it')})-{shift},0.15,0.85)"

    def pan_expr(self) -> str:
        """x do recorte (crop) no tempo t da saida, com o deslocamento por plano."""
        g = self.geo
        if self.dx.constant and abs(self.dx.base) < 1e-9:
            return self.pan.expr("t")
        return f"clip({self.pan.expr('t')}+({self.dx.expr('t')})*{g.cw},0,{g.sw - g.cw})"

    def needs_zoompan(self) -> bool:
        return (self.zoom is not None or not self.zb.constant or abs(self.zb.base - 1.0) > 1e-6
                or not self.dy.constant or abs(self.dy.base) > 1e-6)


def stack_framing() -> Framing:
    """Video em pe ja montado (react.py): quadro inteiro, sem movimento."""
    geo = Geo("blur", W, H, W, H, 0, W, H, 0, 0)
    return Framing(geo, Steps(0.0), None, dynamic=False)


def build_framing(layout: str, info: dict, cfg=None, motion: Motion | None = None) -> Framing:
    """Monta o modelo do movimento (sem reenquadramento: zb=1, dy=0)."""
    from . import faces as _faces

    geo = geometry(layout, info, cfg)
    sw, sh, cw, ch, y0 = geo.sw, geo.sh, geo.cw, geo.ch, geo.cy0
    center = (sw - cw) / 2
    m = motion
    pan = Steps(float(int(center) // 2 * 2))
    if m is not None and m.follow_face and m.track is not None and sw - cw >= 4:
        keys = _faces.crop_keys(m.track, cw, sw, m.time_map, pieces=m.pieces)
        pan = Steps.from_points([(t, x, d) for t, x, d in keys[1:]], keys[0][1])
    ax_pts, ay_pts = [], []
    tr = m.track if m is not None else None
    if tr is not None and getattr(tr, "found", False):
        eyes = {(s_.cx, s_.cy): s_.eye for s_ in tr.shots if s_.cx is not None and s_.eye is not None}
        for t, cx, cy, fh, _d in _faces.timeline(tr, m.time_map, m.pieces):
            if cx is None:
                ax, ay = 0.5, 0.42
            else:
                eye = eyes.get((cx, cy))
                if eye is None:
                    eye = _faces.eye_frac(cy, fh or 0.0)
                ax = min(0.75, max(0.25, (cx * sw - pan.at(t)) / cw))
                if layout == "blur":
                    ay = min(0.62, max(0.22, eye or 0.42))
                else:
                    ay = min(0.97, max(0.03, ((eye or 0.42) * sh - y0) / ch))
            ax_pts.append((t, ax, 0.0))
            ay_pts.append((t, ay, 0.0))
    ax = Steps.from_points(ax_pts) if ax_pts else Steps(0.5)
    ay = Steps.from_points(ay_pts) if ay_pts else Steps(0.42)
    zoom = m.zoom if m is not None else None
    dynamic = m is not None and (m.zoom is not None or m.track is not None) and sw > 0 and sh > 0
    return Framing(geo, pan, zoom, ax=ax, ay=ay, dynamic=dynamic)


def _zoom_or_scale(fr: Framing, fps: int) -> str:
    g = fr.geo
    if not fr.needs_zoompan():
        return f"scale={g.ow}:{g.oh}:flags=bicubic"
    return (f"zoompan=z='{fr.zoom_expr()}':x='{fr.x_expr()}':y='{fr.y_expr()}'"
            f":d=1:s={g.ow}x{g.oh}:fps={fps}")


def video_graph(layout: str, info: dict, fps: int = 30, main: str = "0:v", bg: str | None = "1:v",
                out: str = "base", cfg=None, motion: Motion | None = None) -> str:
    """Filtergraph que produz [out] 1080x1920 (yuv420p, sar 1, fps fixo)."""
    pre = f",{motion.pre}" if (motion is not None and motion.pre) else ""
    sw, sh = int(info.get("width") or 0), int(info.get("height") or 0)
    fr = None
    if motion is not None and sw > 0 and sh > 0:
        fr = motion.framing or build_framing(layout, info, cfg, motion)
    dynamic = fr is not None and (fr.dynamic or fr.needs_zoompan())
    if layout == "split":
        if not bg:
            raise ValueError("layout split precisa de video de fundo")
        top_h = split_seam(cfg)
        bot_h = H - top_h
        if dynamic:
            g = fr.geo
            top = (f"[{main}]{_fps(fps)}{pre},crop={g.cw}:{g.ch}:x='{fr.pan_expr()}':y={g.cy0},"
                   f"{_zoom_or_scale(fr, fps)},setsar=1[top];")
        else:
            top = (f"[{main}]{_fps(fps)}{pre},scale={W}:{top_h}:force_original_aspect_ratio=increase:flags=bicubic,"
                   f"crop={W}:{top_h},setsar=1[top];")
        return (
            top +
            f"[{bg}]{_fps(fps)},scale={W}:{bot_h}:force_original_aspect_ratio=increase:flags=bicubic,"
            f"crop={W}:{bot_h},setsar=1,eq=saturation=0.92:brightness=-0.04[bot];"
            f"[top][bot]vstack=inputs=2,format=yuv420p[{out}]"
        )
    if layout == "blur":
        bx, y, fw, fh = blur_video_box(info)
        if fr is not None:
            bx, y, fw, fh = fr.geo.ox, fr.geo.oy, fr.geo.ow, fr.geo.oh
        if fr is not None and fr.geo.cw < fr.geo.sw:
            g = fr.geo
            x = fr.pan_expr() if dynamic else str(int((g.sw - g.cw) / 2) // 2 * 2)
            fg = f"[m]crop={g.cw}:{g.ch}:x='{x}':y=0,{_zoom_or_scale(fr, fps)},setsar=1[fg];"
        elif dynamic and fr.needs_zoompan():
            fg = f"[m]{_zoom_or_scale(fr, fps)},setsar=1[fg];"
        else:
            fg = f"[m]scale={fw}:{fh}:force_original_aspect_ratio=increase:flags=bicubic,crop={fw}:{fh},setsar=1[fg];"
        return (
            f"[{main}]{_fps(fps)}{pre},setsar=1,split=2[m][b];"
            f"[b]scale=270:480:force_original_aspect_ratio=increase:flags=fast_bilinear,crop=270:480,"
            f"boxblur=luma_radius=10:luma_power=2:chroma_radius=10:chroma_power=2,"
            f"scale={W}:{H}:flags=bilinear,eq=brightness=-0.13:saturation=1.25,setsar=1[bgb];"
            + fg +
            f"[bgb][fg]overlay=x={bx}:y={y}:format=auto,format=yuv420p[{out}]"
        )
    # full
    if dynamic:
        g = fr.geo
        return (f"[{main}]{_fps(fps)}{pre},crop={g.cw}:{g.ch}:x='{fr.pan_expr()}':y={g.cy0},"
                f"{_zoom_or_scale(fr, fps)},setsar=1,format=yuv420p[{out}]")
    return (
        f"[{main}]{_fps(fps)}{pre},scale={W}:{H}:force_original_aspect_ratio=increase:flags=bicubic,"
        f"crop={W}:{H},setsar=1,format=yuv420p[{out}]"
    )


BLUR_AR = 1.40     # proporcao do video no blur: 16:9 perde um pouco das laterais e ocupa 40% da tela (era 32%)


def blur_crop_w(sw: int, sh: int) -> int:
    """Largura da fonte usada no blur."""
    return min(sw, int(round(sh * BLUR_AR / 2)) * 2) if sw / max(1, sh) > BLUR_AR else sw


def blur_video_box(info: dict, center_y: int | None = None) -> tuple[int, int, int, int]:
    """(x, y, w, h) do video principal no layout blur (para posicionar legenda/titulo).
    center_y: centro vertical do video (o safezone desce um pouco para caber marca + titulo)."""
    sw, sh = int(info.get("width") or 1920), int(info.get("height") or 1080)
    sw = blur_crop_w(sw, sh)
    fw, fh = W, round(W * sh / sw / 2) * 2
    if fh > BLUR_MAX_H:
        fh = BLUR_MAX_H
        fw = min(W, round(BLUR_MAX_H * sw / sh / 2) * 2)
    y = max(0, int(center_y or BLUR_CENTER_Y) - fh // 2) // 2 * 2
    return (W - fw) // 2, y, fw, fh
