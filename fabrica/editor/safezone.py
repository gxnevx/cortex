"""Planejador da cena: onde cada elemento fica e como o video e reenquadrado para que NADA cubra
o rosto de quem fala (testa ao queixo + margem), em nenhum quadro.

Elementos: titulo (pilula PARTE X/Y + caixa + barra de progresso), legenda, marca (logo + @),
etiqueta de nome (lower third), CTA de serie. Todos seguem a grade (style.MARGIN, style.GAP):
centralizados no eixo x=540 ou alinhados a margem de 64 px, com no minimo 16 px entre si.

Estrategia (na ordem que o dono pediu, por custo):
  a) reenquadrar o video por plano: zoom base 1,00 a 1,20 + deslocamento vertical (troca seca
     no corte de camera, o mesmo instante em que o recorte horizontal ja troca);
  b) titulo menor / menos linhas (compacto, mini);
  c) titulo em outra zona segura (logo acima da legenda; no split abaixo da emenda).
O rosto vem do faces.FaceTrack (envelope de cada plano, inclusive outros rostos relevantes) e a
projecao na saida usa o MESMO modelo (layouts.Framing) que gera as expressoes do ffmpeg, com o
zoom dinamico (punch-ins) amostrado a 10 Hz. Restricao dura: sobreposicao zero; se for
impossivel, escolhe a menor sobreposicao e registra em LAST_STATS.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from ..log import get as get_log
from . import layouts as _layouts
from . import style as _style

_log = get_log(__name__)

W, H = _style.W, _style.H
INF = 1e9
EDGE_GAP = 16            # nenhum elemento encosta em outro (espaco minimo entre retangulos)
FACE_GAP = 4             # folga extra entre um elemento e o retangulo do rosto (que ja tem margem propria)
ZB_OPTS = (1.0, 1.05, 1.10, 1.15, 1.20)
DY_OPTS = tuple(round(x, 3) for x in np.arange(-0.40, 0.4001, 0.04))
DX_OPTS = (0.0, -0.09, 0.09, -0.18, 0.18, -0.24, 0.24)   # rosto fora do centro (fracao da largura do recorte)
PLAN_BUDGET_S = 8.0               # tempo maximo de busca (o melhor achado ate ali vale)
K_OPTS = (1.0, 0.5, 0.0)          # punch-ins inteiros, pela metade ou desligados no plano
W_ZOOM, W_SHIFT, W_EYE, W_DX, W_K = 12.0, 5.0, 3.0, 12.0, 2.0


Rect = tuple[float, float, float, float]


@dataclass
class Item:
    name: str
    rect: Rect
    t0: float = 0.0
    t1: float = INF


def _inter(a: Rect, b: Rect) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if (w > 0 and h > 0) else 0.0


def _grow(r: Rect, m: float) -> Rect:
    return (r[0] - m, r[1] - m, r[2] + m, r[3] + m)


def _union(rs: list[Rect]) -> Rect:
    return (min(r[0] for r in rs), min(r[1] for r in rs), max(r[2] for r in rs), max(r[3] for r in rs))


@dataclass
class CapGeo:
    size: float          # Fontsize do ASS
    half: float          # meia altura do bloco (linhas medidas, com contorno)
    max_w: int
    default_y: int
    forced: bool = False
    lines: int = 2       # maior numero de linhas medido neste corte
    modes: dict = field(default_factory=dict)   # {max_linhas: (meia altura, largura)} alternativos

    def rect(self, cy: float, lines: int | None = None) -> Rect:
        half, w = self.modes.get(lines, (self.half, self.max_w)) if lines else (self.half, self.max_w)
        return (W / 2 - w / 2, cy - half, W / 2 + w / 2, cy + half)


@dataclass
class Placed:
    """Posicao final de um elemento (PNG no quadro + janela de tempo)."""
    slot: str
    x: int
    y: int
    t0: float = 0.0
    t1: float = INF
    extra: dict = field(default_factory=dict)


@dataclass
class Scene:
    framing: _layouts.Framing
    title: object | None = None            # TitleCard ja posicionado
    title_slot: str = ""
    bar_rect: tuple | None = None          # (x, y, w, h) para o ASS
    cap_y: int = 0
    cap_lines: int = 2                     # maximo de linhas da legenda (1 = par largo vira 2 telas)
    blur_center: int | None = None
    brand: Placed | None = None            # extra: {"arranjo", "logo_xy", "arroba_xy": {rede: (x, y)}}
    tag: Placed | None = None
    cta: Placed | None = None
    hide_title: list = field(default_factory=list)   # janelas em que o titulo some (CTA/etiqueta no lugar)
    items: list[Item] = field(default_factory=list)
    overlap: float = 0.0
    cost: float = 0.0
    zooms: list = field(default_factory=list)        # (t0, zb, dy) por trecho
    notes: list = field(default_factory=list)


@dataclass
class _Seg:
    t0: float
    t1: float
    boxes: np.ndarray        # (amostras, rostos, 4) fracoes da fonte; NaN = rosto ausente
    ts: np.ndarray
    pan: np.ndarray
    ax: np.ndarray
    ay: np.ndarray
    zd: np.ndarray
    grid: tuple | None = None   # retangulos do rosto de todos os candidatos (calculado uma vez)


class Planner:
    def __init__(self, *, lay: str, total: float, teaser: float, framing: _layouts.Framing, segs: list,
                 cfg=None, make_title: Callable[[str], object] | None = None, bar_h: int = 0,
                 cap: CapGeo, tag=None, tag_dur: float = 2.6, cta=None, cta_s: float = 2.0, brand=None,
                 info: dict | None = None, seam: int = 960):
        self.lay, self.total, self.T = lay, float(total), float(teaser)
        self.base_framing = framing
        self.cfg = cfg
        self.g = (lambda k, d: cfg.get(k, d)) if cfg is not None else (lambda k, d: d)
        self.make_title = make_title
        self.bar_h = int(bar_h or 0)
        self.cap = cap
        self.tag, self.tag_dur = tag, float(tag_dur)
        self.cta, self.cta_s = cta, float(cta_s)
        # marca: uma ou mais versoes (normal e compacta); a compacta custa mais
        self.brands = [b for b in (brand if isinstance(brand, (list, tuple)) else [brand])
                       if b is not None and getattr(b, "size", "") != "mini"]
        self.mini = next((b for b in (brand if isinstance(brand, (list, tuple)) else [brand])
                          if b is not None and getattr(b, "size", "") == "mini"), None)
        self.brand = self.brands[0] if self.brands else None
        self.info = info or {}
        self.seam = seam
        self.raw_segs = [fs for fs in segs if getattr(fs.shot, "box", None) is not None]
        zmax = float(self.g("edicao.rosto_zoom_max", 1.20) or 1.20)
        self.zb_opts = tuple(z for z in ZB_OPTS if z <= zmax + 1e-6) or (1.0,)
        self._cache: dict = {}
        self._title_cache: dict = {}
        self._fr = framing
        self._segs: list[_Seg] = []
        self._hard: list[float] = []

    # ------------------------------------------------------------------ amostragem dos planos
    def _prepare(self, fr: _layouts.Framing) -> None:
        self._fr = fr
        self._cache = {}
        self._segs = []
        self._hard = []
        for fs in self.raw_segs:
            a, b = fs.t0, fs.t1
            n = int(min(64, max(3, (b - a) * 8)))   # denso: planos longos nao podem perder um pico de movimento
            spacing = (b - a) / max(1, n - 1)
            ts = list(np.linspace(a + 0.02, max(a + 0.03, b - 0.02), n))
            # inclui os picos do zoom dinamico (punch-in) do trecho
            fine = np.linspace(a + 0.02, max(a + 0.03, b - 0.02), int(max(3, (b - a) * 15)))
            zf = np.array([fr.zd_at(float(t)) for t in fine])
            ts += [float(fine[int(np.argmax(zf))]), float(fine[int(np.argmin(zf))])]
            ts = np.array(sorted(set(round(t, 4) for t in ts)))
            n = len(ts)
            win = max(0.4, spacing / 2 + 0.15)   # cada amostra cobre o intervalo inteiro ate a vizinha
            bl = [fs.boxes_at(float(t), win) for t in ts]
            nb = max([len(x) for x in bl] + [1])
            boxes = np.full((n, nb, 4), np.nan)
            for i, x in enumerate(bl):
                for j, bx in enumerate(x):
                    boxes[i, j] = bx
            self._segs.append(_Seg(a, b, boxes, ts,
                                   np.array([fr.pan.at(t) for t in ts]), np.array([fr.ax.at(t) for t in ts]),
                                   np.array([fr.ay.at(t) for t in ts]), np.array([fr.zd_at(t) for t in ts])))
            self._hard.append(0.0)

    def _grid(self, sg: "_Seg"):
        """Retangulos do rosto para TODOS os candidatos (zb, dy, dx, k) do trecho (calculado uma vez)."""
        if sg.grid is not None:
            return sg.grid
        g = self._fr.geo
        dxo = DX_OPTS if g.layout != "blur" else (0.0,)
        ko = K_OPTS if bool(np.any(np.abs(sg.zd - 1.0) > 1e-4)) else (1.0,)
        ZB, DY, DX, KK = np.meshgrid(np.array(self.zb_opts), np.array(DY_OPTS), np.array(dxo), np.array(ko),
                                     indexing="ij")
        ZB, DY, DX, KK = ZB.ravel(), DY.ravel(), DX.ravel(), KK.ravel()
        nat = int(np.argmin(np.abs(ZB - 1) + np.abs(DY) + np.abs(DX) + np.abs(KK - 1)))
        z = np.clip(ZB[:, None] * (1.0 + KK[:, None] * (sg.zd[None, :] - 1.0)), 1.0, _layouts.ZOOM_TOTAL_MAX)
        if g.layout != "blur":
            px = np.clip(sg.pan[None, :] + DX[:, None] * g.cw, 0.0, float(g.sw - g.cw))
            axs = np.clip(sg.ax[None, :] - (px - sg.pan[None, :]) / g.cw, 0.15, 0.85)
        else:
            px = np.zeros((1, len(sg.ts)))
            axs = sg.ax[None, :]
        X = (1 - 1 / z) * axs
        Y = np.clip(sg.ay[None, :] - (sg.ay[None, :] + DY[:, None]) / z, 0.0, 1 - 1 / z)
        rects = []   # float32: ate ~40 planos por clipe longo
        env = [INF, INF, -INF, -INF]
        as32 = np.float32
        for bi in range(sg.boxes.shape[1]):
            b = sg.boxes[:, bi, :]
            present = ~np.isnan(b[:, 0])
            if not present.any():
                continue
            b = np.nan_to_num(b)
            a0 = (b[None, :, 0] * g.sw - px) / g.cw
            a1 = (b[None, :, 2] * g.sw - px) / g.cw
            b0 = (b[:, 1] * g.sh - g.cy0) / g.ch
            b1 = (b[:, 3] * g.sh - g.cy0) / g.ch
            x0 = np.maximum(g.ox + (a0 - X) * z * g.ow, g.ox)
            x1 = np.minimum(g.ox + (a1 - X) * z * g.ow, g.ox + g.ow)
            y0 = np.maximum(g.oy + (b0[None, :] - Y) * z * g.oh, g.oy)
            y1 = np.minimum(g.oy + (b1[None, :] - Y) * z * g.oh, g.oy + g.oh)
            valid = ((x1 - x0) > 4) & ((y1 - y0) > 4) & present[None, :]
            rects.append((x0.astype(as32), y0.astype(as32), x1.astype(as32), y1.astype(as32), valid))
            if valid.any():
                env = [min(env[0], float(x0[valid].min())), min(env[1], float(y0[valid].min())),
                       max(env[2], float(x1[valid].max())), max(env[3], float(y1[valid].max()))]
        eye = g.oy + (sg.ay[None, :] - Y) * z * g.oh
        eye_pen = np.clip((_style.SAFE_TOP + 50) - eye, 0, None).mean(axis=1) / 100.0 if g.layout != "blur" \
            else np.zeros(len(ZB))
        cost = (W_ZOOM * (ZB - 1.0) + W_SHIFT * np.abs(DY) + W_EYE * eye_pen + W_DX * np.abs(DX)
                + W_K * (1.0 - KK))
        sg.grid = (ZB, DY, DX, KK, nat, rects, tuple(env), cost)
        return sg.grid

    def _opt_seg(self, k: int, items: list[Item]) -> tuple:
        """Melhor (zb, dy, dx, k) do trecho k contra os itens ativos.
        Devolve (zb, dy, custo, sobreposicao, dx, k)."""
        sg = self._segs[k]
        ZB, DY, DX, KK, nat, rects, env, cost = self._grid(sg)
        act = []
        for it in items:
            if it.t1 <= sg.t0 or it.t0 >= sg.t1:
                continue
            r = _grow(it.rect, FACE_GAP)
            if _inter(r, env) <= 0:   # nenhum enquadramento possivel chega nesse elemento
                continue
            act.append((r, (sg.ts >= it.t0) & (sg.ts <= it.t1)))
        key = (k, tuple((tuple(round(v) for v in r), int(m.sum()), int(np.argmax(m)) if m.any() else -1)
                        for r, m in act))
        if key in self._cache:
            return self._cache[key]

        def over(sel):
            o = np.zeros(len(ZB) if sel is None else 1)
            for x0, y0, x1, y1, valid in rects:
                if sel is not None:
                    x0, y0, x1, y1, valid = x0[sel:sel + 1], y0[sel:sel + 1], x1[sel:sel + 1], y1[sel:sel + 1], \
                        valid[sel:sel + 1]
                for r, m in act:
                    if not m.any():
                        continue
                    iw = np.clip(np.minimum(x1, r[2]) - np.maximum(x0, r[0]), 0, None)
                    ih = np.clip(np.minimum(y1, r[3]) - np.maximum(y0, r[1]), 0, None)
                    o += (iw * ih * valid * m[None, :]).mean(axis=1)
            return o

        if not act or over(nat)[0] <= 0:   # o enquadramento natural ja livra o rosto
            res = (1.0, 0.0, float(cost[nat]), 0.0, 0.0, 1.0)
        else:
            overlap = over(None)
            i = int(np.argmin(overlap * 1e3 + cost))
            res = (float(ZB[i]), float(DY[i]), float(cost[i]), float(overlap[i]), float(DX[i]), float(KK[i]))
        self._cache[key] = res
        return res

    def _framing_cost(self, items: list[Item], early_exit: bool = False) -> tuple[float, float, list]:
        """Custo do reenquadramento (media ponderada pela duracao) e sobreposicao com rosto.
        early_exit: para no primeiro trecho impossivel (os mais dificeis sao testados primeiro)."""
        tot_c, tot_o = 0.0, 0.0
        res: dict = {}
        order = sorted(range(len(self._segs)), key=lambda k: -self._hard[k]) if early_exit else range(len(self._segs))
        for k in order:
            sg = self._segs[k]
            r = self._opt_seg(k, items)
            res[k] = r
            w = (sg.t1 - sg.t0) / max(1e-6, self.total)
            tot_c += r[2] * w
            tot_o += r[3] * (sg.t1 - sg.t0)
            if r[3] > 0:
                self._hard[k] += 1.0
                if early_exit:
                    return tot_c, max(tot_o, 1e-3), []
        choice = [(self._segs[k].t0, res[k][0], res[k][1], res[k][4], res[k][5]) for k in range(len(self._segs))]
        return tot_c, tot_o, choice

    # ------------------------------------------------------------------ geometria dos elementos
    def _title(self, size: str):
        if size not in self._title_cache:
            self._title_cache[size] = self.make_title(size) if self.make_title else None
        return self._title_cache[size]

    def _title_items(self, card) -> tuple[list[Item], tuple | None]:
        items = [Item(n, r) for n, r in card.rects()]
        bar = None
        if self.bar_h and card.box:
            bx, by, bw, bh = card.box
            bar = (bx, by + bh + _style.SPACE, bw, self.bar_h)
            items.append(Item("barra", (bar[0], bar[1], bar[0] + bar[2], bar[1] + bar[3])))
        return items, bar

    @staticmethod
    def _group(items: list[Item]) -> Rect:
        return _union([it.rect for it in items])

    def _place_title(self, card0, slot: str, top_line: float, cap_rect: Rect, video_box: Rect | None):
        """Copia do titulo movida para o lugar pedido. None se nao couber."""
        card = copy.copy(card0)
        items, _bar = self._title_items(card)
        grp = self._group(items)
        h = grp[3] - grp[1]
        if slot == "topo":
            # bloco de texto em edicao.titulo_topo (padrao 260), sem subir acima da linha livre
            want = float(self.g("edicao.titulo_topo", 260) or 260)
            box_top = card.box[1] if card.box else grp[1]
            y_top = max(top_line, grp[1] + (want - box_top))
        elif slot == "topo_alto":
            y_top = top_line
        elif slot == "acima_legenda":
            y_top = cap_rect[1] - _style.GAP - h
        elif slot == "emenda":
            box = card.box or (grp[0], grp[1], grp[2] - grp[0], h)
            y_top = grp[1] + (self.seam - (box[1] + box[3] / 2))
        elif slot == "abaixo_emenda":
            y_top = self.seam + _style.GAP
        elif slot == "acima_video" and video_box is not None:
            y_top = video_box[1] - _style.GAP - h
        else:
            return None
        card.shift(round(y_top - grp[1]))
        items, bar = self._title_items(card)
        grp = self._group(items)
        if grp[1] < top_line - 0.5 or grp[3] > _style.SAFE_BOTTOM_Y - _style.SPACE:
            return None
        if _inter(_grow(grp, EDGE_GAP), cap_rect) > 0:
            return None
        return card, items, bar

    def _brand_rects(self, slot: str, arr: str, cap_rect: Rect, b=None) -> tuple[list, dict] | None:
        """([(nome, retangulo)], posicoes dos PNGs) da marca: logo e linha do @ (alinhados ao canto)."""
        b = b or self.brand
        m = 10
        lw, lh = b.logo_wh
        hws = {p_: (w - 2 * m, h - 2 * m) for p_, (_pt, w, h, _c) in b.handles.items()}
        hw = max([v[0] for v in hws.values()] + [0])
        hh = max([v[1] for v in hws.values()] + [0])
        if not hws:
            bw, bh = lw, lh
        elif arr == "linha":
            bw, bh = lw + 2 * b.gap + hw, max(lh, hh)
        else:
            bw, bh = max(lw, hw), lh + b.gap + hh
        M, top = _style.MARGIN, _style.SAFE_TOP + _style.SPACE
        if slot == "topo_dir":
            x0, y0 = W - M - bw, top
        elif slot == "topo_esq":
            x0, y0 = M, top
        elif slot == "base_esq":
            x0, y0 = M, _style.SAFE_BOTTOM_Y - _style.SPACE - bh
        elif slot == "abaixo_legenda":
            x0, y0 = round(W / 2 - bw / 2), cap_rect[3] + _style.SPACE
        else:
            return None
        x0, y0 = int(round(x0)), int(round(y0))
        if y0 + bh > _style.SAFE_BOTTOM_Y - 8:
            return None
        if _inter((x0, y0, x0 + bw, y0 + bh), _style.RAIL) > 0:
            return None
        right, center = slot == "topo_dir", slot == "abaixo_legenda"
        pos = {"arroba": {}}
        if arr == "linha" and hws:
            ly = y0 + round((bh - lh) / 2)
            hy = y0 + round((bh - hh) / 2)
            if right:   # [@][LOGO]: logo no canto
                logo = (x0 + bw - lw, ly, x0 + bw, ly + lh)
                hrect = (x0, hy, x0 + hw, hy + hh)
            else:       # [LOGO][@]
                logo = (x0, ly, x0 + lw, ly + lh)
                hrect = (x0 + lw + 2 * b.gap, hy, x0 + lw + 2 * b.gap + hw, hy + hh)
        else:
            if right:
                logo = (x0 + bw - lw, y0, x0 + bw, y0 + lh)
                hrect = (x0 + bw - hw, y0 + lh + b.gap, x0 + bw, y0 + lh + b.gap + hh)
            elif center:
                logo = (round(W / 2 - lw / 2), y0, round(W / 2 - lw / 2) + lw, y0 + lh)
                hrect = (round(W / 2 - hw / 2), y0 + lh + b.gap, round(W / 2 - hw / 2) + hw, y0 + lh + b.gap + hh)
            else:
                logo = (x0, y0, x0 + lw, y0 + lh)
                hrect = (x0, y0 + lh + b.gap, x0 + hw, y0 + lh + b.gap + hh)
        pos["logo"] = (int(logo[0]), int(logo[1]))
        rects = [("marca", logo)]
        if hws:
            rects.append(("arroba", hrect))
            for plat, (vw, vh) in hws.items():
                # cada @ encosta na mesma borda (direita no canto direito; centro; esquerda)
                if arr == "linha" and right:
                    hx = hrect[2] - vw
                elif right:
                    hx = hrect[2] - vw
                elif center:
                    hx = round(W / 2 - vw / 2)
                else:
                    hx = hrect[0]
                pos["arroba"][plat] = (int(hx - m), int(hrect[1] + round((hh - vh) / 2) - m))
        return rects, pos

    def _pill_row_brand(self, card, t_items: list, cap_rect: Rect):
        """Marca mini alinhada a margem direita, na altura da pilula PARTE (com a do texto ao lado)."""
        b = self.mini
        if b is None or card is None or not card.pill or not b.handles:
            return None
        m = 10
        px0, py0, pw, ph = card.pill
        lw, lh = b.logo_wh
        hw = max(w - 2 * m for _p, w, _h, _c in b.handles.values())
        hh = max(h - 2 * m for _p, _w, h, _c in b.handles.values())
        gap = 8
        right = W - _style.MARGIN
        # [LOGO][@] encostado na margem direita, centrado na altura da pilula
        x_logo = right - hw - gap - lw
        if x_logo < px0 + pw + _style.GAP:
            return None
        cyc = py0 + ph / 2
        logo = (x_logo, round(cyc - lh / 2), x_logo + lw, round(cyc - lh / 2) + lh)
        hrect = (right - hw, round(cyc - hh / 2), right, round(cyc - hh / 2) + hh)
        items = [Item("marca", logo), Item("arroba", hrect)]
        if any(_inter(_grow(i.rect, EDGE_GAP), o.rect) > 0 for i in items for o in t_items + [Item("legenda", cap_rect)]):
            return None
        pos = {"logo": (int(logo[0]), int(logo[1])), "arroba": {}}
        for plat, (_p, w, h, _c) in b.handles.items():
            vw, vh = w - 2 * m, h - 2 * m
            pos["arroba"][plat] = (int(hrect[2] - vw - m), int(hrect[1] + round((hh - vh) / 2) - m))
        return items, pos

    def _video_box(self, fr: _layouts.Framing) -> Rect:
        g = fr.geo
        return (g.ox, g.oy, g.ox + g.ow, g.oy + g.oh)

    # ------------------------------------------------------------------ busca
    def plan(self) -> Scene:
        import time as _time

        lay = self.lay
        blur_opts = [(None, 0.0)]
        if lay == "blur":
            blur_opts = [(860, 0.0), (900, 0.4), (940, 0.8), (980, 1.2)]
        sizes = [("normal", 0.0), ("compacto", 4.0), ("mini", 7.0)] if self.make_title else [(None, 0.0)]
        if lay == "full":
            tslots = [("topo", 0.0), ("topo_alto", 1.0), ("acima_legenda", 5.0)]
        elif lay == "split":
            tslots = [("emenda", 0.0), ("abaixo_emenda", 5.0), ("topo", 6.0)]
        else:
            tslots = [("topo", 0.0), ("topo_alto", 0.5), ("acima_video", 1.0)]
        brand_opts = [(None, None, 0.0, None)]
        if self.brands:
            slots = [("topo_dir", "pilha", 0.0), ("topo_dir", "linha", 0.3), ("topo_esq", "pilha", 1.0),
                     ("topo_esq", "linha", 1.3), ("base_esq", "linha", 2.5), ("abaixo_legenda", "linha", 3.0)]
            brand_opts = []
            for bi, br in enumerate(self.brands):
                brand_opts += [(sl, ar, c + 4.0 * bi, br) for sl, ar, c in slots]
            brand_opts.append((None, None, 25.0, None))
        line_opts = [(self.cap.lines, 0.0)] + [(n, 1.5) for n in sorted(self.cap.modes) if n != self.cap.lines]
        # 1) combinacoes geometricamente validas (sem rosto), ordenadas pelo custo de estilo
        combos = []
        for bc, c_blur in blur_opts:
            fr = self._framing_for(bc)
            vbox = self._video_box(fr)
            for n_lines, c_lines in line_opts:
                for cy, c_cap in self._cap_opts(vbox, n_lines):
                    cap_rect = self.cap.rect(cy, n_lines)
                    for b_slot, b_arr, c_brand, b_obj in brand_opts:
                        b_items, b_pos = [], None
                        if b_slot is not None:
                            r = self._brand_rects(b_slot, b_arr, cap_rect, b_obj)
                            if r is None:
                                continue
                            b_items, b_pos = [Item(n_, rr) for n_, rr in r[0]], r[1]
                            if any(_inter(_grow(it.rect, EDGE_GAP), cap_rect) > 0 for it in b_items):
                                continue
                        b_union = _union([it.rect for it in b_items]) if b_items else None
                        for size, c_size in sizes:
                            card0 = self._title(size) if size else None
                            for tslot, c_slot in (tslots if card0 is not None else [("", 0.0)]):
                                card, t_items, bar = None, [], None
                                if card0 is not None:
                                    top_line = _style.SAFE_TOP + _style.SPACE
                                    pr = self._place_title(card0, tslot, top_line, cap_rect, vbox)
                                    if pr is not None and b_union is not None and b_slot in ("topo_dir", "topo_esq") \
                                            and _inter(_grow(self._group(pr[1]), EDGE_GAP), b_union) > 0:
                                        pr = self._place_title(card0, tslot, b_union[3] + _style.GAP, cap_rect, vbox)
                                    if pr is None:
                                        continue
                                    card, t_items, bar = pr
                                    if any(_inter(_grow(self._group(t_items), EDGE_GAP), it.rect) > 0 for it in b_items):
                                        continue
                                base = c_blur + c_lines + c_cap + c_brand + c_size + c_slot
                                if b_slot is None and card is not None and self.mini is not None:
                                    # sem canto livre: marca mini na linha da pilula, antes de abrir mao da marca
                                    pb = self._pill_row_brand(card, t_items, cap_rect)
                                    if pb is not None:
                                        combos.append((base - c_brand + 6.0, bc, fr, vbox, cy, n_lines, cap_rect,
                                                       "linha_parte", "mini", pb[0],
                                                       {**pb[1], "obj": self.mini}, card, tslot, t_items, bar))
                                combos.append((base, bc, fr, vbox, cy, n_lines, cap_rect, b_slot, b_arr, b_items,
                                               {**b_pos, "obj": b_obj} if b_pos else None, card, tslot, t_items, bar))
        combos.sort(key=lambda c: c[0])
        # 2) avalia o rosto (reenquadramento por plano) na ordem; para no primeiro custo impossivel de bater
        best: Scene | None = None
        fallback, fallback_ctx = None, None
        t_start = _time.time()
        prepared = object()   # sentinela (bc pode ser None)
        evaluated = 0
        for (base, bc, fr, vbox, cy, n_lines, cap_rect, b_slot, b_arr, b_items, b_pos, card, tslot, t_items,
             bar) in combos:
            if best is not None and base >= best.cost:
                break
            if _time.time() - t_start > PLAN_BUDGET_S and (best is not None or fallback is not None):
                break
            if prepared is not bc:
                self._prepare(fr)
                prepared = bc
            evaluated += 1
            static = list(t_items) + [Item("legenda", cap_rect)] + list(b_items)
            f_cost, f_over, _ch = self._framing_cost(static, early_exit=fallback is not None)
            sc = Scene(fr, card, tslot, bar, int(round(cy)), n_lines, bc, None, None, None, [], static, f_over,
                       base + f_cost)
            if b_slot is not None:
                sc.brand = Placed(b_slot, int(b_pos["logo"][0]), int(b_pos["logo"][1]),
                                  extra={"arranjo": b_arr, **b_pos})
            if f_over > 0:
                if fallback is None or (f_over, sc.cost) < (fallback.overlap, fallback.cost):
                    fallback, fallback_ctx = sc, (vbox, cap_rect, bc)
                continue
            if best is not None and sc.cost >= best.cost:
                continue
            self._add_timed(sc, vbox, cap_rect)
            if best is None or sc.cost < best.cost:
                best = sc
        sc = best
        if sc is None and fallback is not None:
            # sem plano 100% livre: o de menor sobreposicao; etiqueta/CTA so entram onde for seguro
            sc = fallback
            self._prepare(sc.framing)
            self._add_timed(sc, fallback_ctx[0], fallback_ctx[1])
            sc.notes.append("sem plano 100% livre: menor sobreposicao")
        if sc is None:   # nada coube: tudo no padrao, sem reenquadrar
            fr = self._framing_for(None if lay != "blur" else 860)
            card = self._title("normal") if self.make_title else None
            sc = Scene(fr, card, "topo", None, self.cap.default_y, self.cap.lines, 860 if lay == "blur" else None)
            sc.notes.append("sem plano valido")
        sc.notes.append(f"{evaluated}/{len(combos)} combinacoes em {_time.time() - t_start:.1f}s")
        self._finish(sc)
        return sc

    def _framing_for(self, blur_center: int | None) -> _layouts.Framing:
        fr = self.base_framing
        if blur_center is None or self.lay != "blur":
            return fr
        bx, by, fw, fh = _layouts.blur_video_box(self.info, blur_center)
        geo = copy.copy(fr.geo)
        geo.ox, geo.oy, geo.ow, geo.oh = bx, by, fw, fh
        fr2 = copy.copy(fr)
        fr2.geo = geo
        return fr2

    def _cap_opts(self, vbox: Rect, lines: int | None = None) -> list[tuple[float, float]]:
        c = self.cap
        half = c.modes.get(lines, (c.half, c.max_w))[0] if lines else c.half
        if c.forced:
            return [(c.default_y, 0.0)]
        if self.lay == "blur":
            y0 = vbox[3] + _style.GAP + half
            opts = [(y0, 0.0), (y0 + 40, 1.0), (y0 + 80, 2.0)]
        else:
            y0 = c.default_y
            opts = [(y0, 0.0), (y0 + 40, 1.0), (y0 + 80, 2.0), (y0 + 120, 3.0), (y0 - 40, 1.5)]
        return [(y, cst) for y, cst in opts if y + half <= _style.SAFE_BOTTOM_Y - 8]

    # ------------------------------------------------------------------ etiqueta e CTA
    def _timed_slots(self, sc: Scene, w: int, h: int, vbox: Rect, cap_rect: Rect, centered: bool) -> list:
        """[(slot, x0, y0, custo)] do retangulo VISIVEL (w x h) de um elemento temporario."""
        t_items = [it for it in sc.items if it.name in ("titulo", "parte", "barra")]
        grp = self._group(t_items) if t_items else None
        x0 = round(W / 2 - w / 2) if centered else _style.MARGIN
        g = _style.GAP
        out = [("acima_legenda", x0, cap_rect[1] - g - h, 0.0)]
        if grp is not None:
            out.append(("abaixo_titulo", x0, grp[3] + g, 0.5))
            out.append(("acima_titulo", x0, grp[1] - g - h, 0.6))
        if self.lay == "blur":
            out.append(("base_video", x0, vbox[3] - g - h, 0.0 if not centered else 0.8))
            out.append(("acima_video", x0, vbox[1] - g - h, 1.0))
        elif self.lay == "split":
            out.append(("base_video", x0, min(self.seam, grp[1] if grp else self.seam) - g - h, 0.0 if not centered else 0.8))
        out.append(("topo", x0, _style.SAFE_TOP + _style.SPACE, 2.0))
        if sc.title is not None and sc.title.box:
            bx, by, bw, bh = sc.title.box
            out.append(("no_titulo", x0, round(by + bh / 2 - h / 2), 8.0 if not centered else 2.5))
        return out

    def _try_timed(self, sc: Scene, name: str, w: int, h: int, t0: float, t1: float, slots: list,
                   extra_cost: float = 0.0):
        """Melhor lugar (sem encostar em nada e sem cobrir rosto). Devolve (custo, item, slot, oculta)."""
        best = None
        for slot, x0, y0, c in slots:
            rect = (x0, y0, x0 + w, y0 + h)
            if rect[1] < _style.SAFE_TOP + _style.SPACE - 0.5 or rect[3] > _style.SAFE_BOTTOM_Y - 8:
                continue
            if _inter(rect, _style.RAIL) > 0:
                continue
            hides = slot == "no_titulo"
            clash = False
            for it in sc.items:
                if it.t1 <= t0 or it.t0 >= t1:
                    continue
                if hides and it.name in ("titulo", "parte"):
                    continue
                if _inter(_grow(rect, EDGE_GAP), it.rect) > 0:
                    clash = True
                    break
            if clash:
                continue
            items = [it for it in sc.items if not (hides and it.name in ("titulo", "parte"))
                     or it.t1 <= t0 or it.t0 >= t1] + [Item(name, rect, t0, t1)]
            f_cost, f_over, _ch = self._framing_cost(items)
            if f_over > 0:
                continue
            total = c + extra_cost + f_cost
            if best is None or total < best[0]:
                best = (total, Item(name, rect, t0, t1), slot, hides, f_cost)
        return best

    def _add_timed(self, sc: Scene, vbox: Rect, cap_rect: Rect) -> None:
        f_base, _o, _c = self._framing_cost(sc.items)
        # etiqueta de nome: ~2,6 s logo depois do teaser (ou um pouco mais tarde se nao couber)
        if self.tag is not None:
            vw, vh = self.tag.vis[2] - self.tag.vis[0], self.tag.vis[3] - self.tag.vis[1]
            slots = self._timed_slots(sc, vw, vh, vbox, cap_rect, centered=False)
            choice = None
            start0 = (self.T + 0.25) if self.T > 0 else 0.6
            for off, c_off in ((0.0, 0.0), (1.5, 1.5), (3.0, 3.0)):
                t0 = start0 + off
                t1 = t0 + self.tag_dur
                if t1 > self.total - 1.0:
                    break
                r = self._try_timed(sc, "etiqueta", vw, vh, t0, t1, slots, c_off)
                if r is not None and (choice is None or r[0] < choice[0]):
                    choice = r
            if choice is None:
                sc.cost += 30.0
                sc.notes.append("etiqueta sem lugar seguro: pulada")
            else:
                total, item, slot, hides, f_cost = choice
                sc.cost += total - f_cost + (f_cost - f_base)
                sc.items.append(item)
                if hides:
                    self._hide_title(sc, item.t0, item.t1)
                sc.tag = Placed(slot, int(item.rect[0]), int(item.rect[1]), item.t0, item.t1)
        if self.cta is not None:
            vw, vh = self.cta.w - 2 * self.cta.pad_top, self.cta.h - self.cta.pad_top - self.cta.pad_bottom
            t0, t1 = max(0.0, self.total - self.cta_s), self.total + 1.0
            slots = self._timed_slots(sc, vw, vh, vbox, cap_rect, centered=True)
            f_now, _o, _c = self._framing_cost(sc.items)
            r = self._try_timed(sc, "cta", vw, vh, t0, t1, slots)
            if r is None:
                sc.cost += 30.0
                sc.notes.append("CTA sem lugar seguro: pulada")
            else:
                total, item, slot, hides, f_cost = r
                sc.cost += total - f_cost + (f_cost - f_now)
                sc.items.append(item)
                if hides:
                    self._hide_title(sc, t0, t1)
                sc.cta = Placed(slot, int(item.rect[0]), int(item.rect[1]), t0, t1)

    @staticmethod
    def _hide_title(sc: Scene, t0: float, t1: float) -> None:
        sc.hide_title.append((t0, t1))
        new = []
        for it in sc.items:
            if it.name in ("titulo", "parte"):
                if it.t0 < t0:
                    new.append(Item(it.name, it.rect, it.t0, t0))
                if it.t1 > t1:
                    new.append(Item(it.name, it.rect, t1, it.t1))
            else:
                new.append(it)
        sc.items[:] = new

    # ------------------------------------------------------------------ resultado
    def _finish(self, sc: Scene) -> None:
        """Grava o reenquadramento escolhido no Framing e mede a sobreposicao final quadro a quadro."""
        self._prepare(sc.framing)
        _c, over, choice = self._framing_cost(sc.items)
        fr = copy.copy(sc.framing)
        # o trecho seguinte comeca onde o anterior termina; sem rosto (sem trecho) volta ao natural
        pts = {"zb": [], "dy": [], "dx": [], "k": []}
        natural = {"zb": 1.0, "dy": 0.0, "dx": 0.0, "k": 1.0}
        starts = {round(sg.t0, 4) for sg in self._segs}
        for (t, zb, dy, dx, kk), sg in zip(choice, self._segs):
            for name, v in (("zb", zb), ("dy", dy), ("dx", dx), ("k", kk)):
                pts[name].append((t, v, 0.0))
                if round(sg.t1, 4) not in starts:
                    pts[name].append((sg.t1, natural[name], 0.0))
        for name in pts:
            st = _layouts.Steps.from_points(pts[name], natural[name]) if pts[name] else _layouts.Steps(natural[name])
            setattr(fr, name, st)
        sc.framing = fr
        sc.zooms = [(round(t, 2), zb, dy, dx, kk) for t, zb, dy, dx, kk in choice
                    if abs(zb - 1) > 1e-6 or abs(dy) > 1e-6 or abs(dx) > 1e-6 or abs(kk - 1) > 1e-6]
        sc.overlap = float(face_overlap(fr, self.raw_segs, sc.items, self.total)["max_px"])


def face_rects_at(fr: _layouts.Framing, segs: list, t: float) -> list[Rect]:
    """Retangulos dos rostos (testa ao queixo + margem) visiveis no instante t da saida."""
    out = []
    for fs in segs:
        if fs.t0 <= t < fs.t1 and getattr(fs.shot, "box", None) is not None:
            for box in fs.boxes_at(t):
                r = fr.visible(fr.project(box, t))
                if r is not None:
                    out.append(r)
    return out


def face_overlap(fr: _layouts.Framing, segs: list, items: list[Item], total: float, step: float = 1 / 15) -> dict:
    """Confere a cada 1/15 s: maior area (px) de elemento sobre rosto e em que instante."""
    worst, worst_t, worst_name = 0.0, None, ""
    t = 0.0
    while t < total:
        for r in face_rects_at(fr, segs, t):
            for it in items:
                if it.t0 <= t <= it.t1:
                    a = _inter(r, it.rect)
                    if a > worst:
                        worst, worst_t, worst_name = a, t, it.name
        t += step
    return {"max_px": round(worst, 1), "t": None if worst_t is None else round(worst_t, 2), "item": worst_name}


GROUPS = ({"marca", "arroba"},)   # partes de um mesmo bloco (podem ficar a menos de 16 px)


def items_overlap(items: list[Item], gap: float = 0.0) -> list[tuple[str, str]]:
    """Pares de elementos que se tocam (com folga gap) ao mesmo tempo."""
    bad = []
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if a.t1 <= b.t0 or b.t1 <= a.t0:
                continue
            if a.name == b.name or any({a.name, b.name} <= grp for grp in GROUPS):
                continue
            if _inter(_grow(a.rect, gap / 2), _grow(b.rect, gap / 2)) > 0:
                bad.append((a.name, b.name))
    return bad
