"""Titulo no topo do video (PNG com Pillow): caixa branca arredondada estilo TikTok,
texto preto pesado, emojis COLORIDOS e selo "PARTE 2/4".

Emojis: Segoe UI Emoji (COLR) com embedded_color; se nao sair colorido (ou para sequencias
com ZWJ/tom de pele/bandeiras, que o Pillow sem raqm nao compoe) usa PNGs do Twemoji
(jdecked/twemoji via jsdelivr, licenca CC-BY 4.0) baixados sob demanda para assets/emoji/.
"""
from __future__ import annotations

import functools
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .. import paths
from ..log import get as get_log
from . import fonts as _fonts
from . import style as _style

_log = get_log(__name__)

W, H = 1080, 1920
EMOJI_DIR = paths.ASSETS / "emoji"
TWEMOJI_URLS = [
    "https://cdn.jsdelivr.net/gh/jdecked/twemoji@15.1.0/assets/72x72/{name}.png",
    "https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/assets/72x72/{name}.png",
]

# zonas seguras (px em 1080x1920)
SAFE_TOP = 150
SAFE_BOTTOM = 380
SAFE_RIGHT = 140


@dataclass
class TitleCard:
    path: Path
    x: int
    y: int
    w: int
    h: int
    box: tuple[int, int, int, int] | None = None   # (x, y, w, h) do bloco de texto no quadro
    variant: str = "nativo"
    pill: tuple[int, int, int, int] | None = None  # (x, y, w, h) visivel da pilula PARTE X/Y no quadro
    size: str = "normal"                           # normal | compacto | mini
    lines: int = 0

    def shift(self, dy: int) -> None:
        """Move o titulo inteiro (PNG, bloco de texto e pilula) dy px na vertical."""
        dy = int(round(dy))
        self.y += dy
        if self.box:
            self.box = (self.box[0], self.box[1] + dy, self.box[2], self.box[3])
        if self.pill:
            self.pill = (self.pill[0], self.pill[1] + dy, self.pill[2], self.pill[3])

    def rects(self) -> list[tuple[str, tuple[float, float, float, float]]]:
        """Retangulos visiveis (x0, y0, x1, y1): pilula e bloco de texto (sem sombra)."""
        out = []
        if self.pill:
            x, y, w, h = self.pill
            out.append(("parte", (x, y, x + w, y + h)))
        if self.box:
            x, y, w, h = self.box
            out.append(("titulo", (x, y, x + w, y + h)))
        elif not self.pill:
            out.append(("titulo", (self.x, self.y, self.x + self.w, self.y + self.h)))
        return out

    def top(self) -> float:
        return min(r[1] for _n, r in self.rects())

    def bottom(self) -> float:
        return max(r[3] for _n, r in self.rects())


# ------------------------------------------------------------------ emoji: segmentacao
def _is_emoji_base(cp: int) -> bool:
    return (0x1F000 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF or 0x2300 <= cp <= 0x23FF
            or 0x2B00 <= cp <= 0x2BFF or cp in (0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139,
                                                  0x3030, 0x303D, 0x3297, 0x3299, 0x24C2)
            or 0x2194 <= cp <= 0x21AA or 0x25AA <= cp <= 0x25FE or 0x2934 <= cp <= 0x2935)


def _is_modifier(cp: int) -> bool:
    return cp in (0xFE0F, 0xFE0E, 0x20E3) or 0x1F3FB <= cp <= 0x1F3FF or 0xE0020 <= cp <= 0xE007F


def split_runs(text: str) -> list[tuple[str, str]]:
    """'OI 😳🔥' -> [('t','OI '), ('e','😳'), ('e','🔥')]"""
    runs: list[tuple[str, str]] = []
    i, n = 0, len(text)
    buf = ""
    while i < n:
        cp = ord(text[i])
        is_keycap = text[i] in "0123456789#*" and i + 1 < n and ord(text[i + 1]) in (0xFE0F, 0x20E3) and (
            ord(text[i + 1]) == 0x20E3 or (i + 2 < n and ord(text[i + 2]) == 0x20E3))
        if _is_emoji_base(cp) or is_keycap:
            if buf:
                runs.append(("t", buf))
                buf = ""
            j = i + 1
            if 0x1F1E6 <= cp <= 0x1F1FF and j < n and 0x1F1E6 <= ord(text[j]) <= 0x1F1FF:
                j += 1  # bandeira
            while j < n:
                c = ord(text[j])
                if _is_modifier(c):
                    j += 1
                elif c == 0x200D and j + 1 < n:
                    j += 2  # ZWJ + proximo
                else:
                    break
            runs.append(("e", text[i:j]))
            i = j
            continue
        if cp in (0xFE0F, 0xFE0E, 0x200D):
            i += 1
            continue
        buf += text[i]
        i += 1
    if buf:
        runs.append(("t", buf))
    return runs


def twemoji_name(cluster: str) -> str:
    cps = [ord(c) for c in cluster]
    if 0x200D not in cps:
        cps = [c for c in cps if c != 0xFE0F]
    return "-".join(f"{c:x}" for c in cps)


# ------------------------------------------------------------------ emoji: desenho
@functools.lru_cache(maxsize=1)
def segoe_color_ok() -> bool:
    """Confere se o Segoe UI Emoji sai colorido no Pillow desta maquina."""
    p = _fonts.emoji_font_path()
    if not p:
        return False
    try:
        f = ImageFont.truetype(str(p), 64)
        im = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((8, 8), "\U0001F525", font=f, embedded_color=True)
        px = [q for q in im.get_flattened_data() if q[3] > 200] if hasattr(im, "get_flattened_data") \
            else [q for q in im.getdata() if q[3] > 200]
        colored = sum(1 for r, g, b, _a in px if max(r, g, b) - min(r, g, b) > 60)
        return len(px) > 200 and colored > len(px) * 0.4
    except Exception as e:  # noqa: BLE001
        _log.info("Segoe UI Emoji sem cor: %s", e)
        return False


def _twemoji(cluster: str) -> Image.Image | None:
    name = twemoji_name(cluster)
    dest = EMOJI_DIR / f"{name}.png"
    if not dest.exists():
        import requests

        EMOJI_DIR.mkdir(parents=True, exist_ok=True)
        for tpl in TWEMOJI_URLS:
            try:
                r = requests.get(tpl.format(name=name), timeout=20)
                if r.status_code == 200 and r.content[:4] == b"\x89PNG":
                    dest.write_bytes(r.content)
                    break
            except Exception:  # noqa: BLE001
                continue
    if dest.exists():
        try:
            return Image.open(dest).convert("RGBA")
        except Exception:  # noqa: BLE001
            return None
    return None


def _segoe(cluster: str) -> Image.Image | None:
    p = _fonts.emoji_font_path()
    if not p:
        return None
    base = "".join(c for c in cluster if ord(c) not in (0xFE0F, 0xFE0E))[:1]
    f = ImageFont.truetype(str(p), 128)
    im = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((20, 20), base, font=f, embedded_color=True)
    bb = im.getbbox()
    return im.crop(bb) if bb else None


@functools.lru_cache(maxsize=256)
def emoji_image(cluster: str, px: int) -> Image.Image | None:
    """Emoji colorido com altura ~px (quadrado)."""
    simple = len([c for c in cluster if ord(c) not in (0xFE0F, 0xFE0E)]) == 1
    img = None
    if simple and segoe_color_ok():
        img = _segoe(cluster)
    if img is None:
        img = _twemoji(cluster)
    if img is None and not simple and segoe_color_ok():
        img = _segoe(cluster)
    if img is None:
        return None
    # encaixa num quadrado px x px mantendo proporcao
    scale = px / max(img.width, img.height)
    img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    sq = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    sq.alpha_composite(img, ((px - img.width) // 2, (px - img.height) // 2))
    return sq


# ------------------------------------------------------------------ texto
def _font(px: int, heavy: bool = True) -> ImageFont.FreeTypeFont:
    path, variation = _fonts.title_font_path(heavy)
    if path is None:
        return ImageFont.load_default(px)
    f = ImageFont.truetype(str(path), px)
    if variation:
        try:
            f.set_variation_by_name(variation)
        except Exception:  # noqa: BLE001
            pass
    return f


class _Word:
    def __init__(self, runs: list[tuple[str, str]]):
        self.runs = runs

    def width(self, font: ImageFont.FreeTypeFont, epx: int) -> float:
        w = 0.0
        for k, s in self.runs:
            w += font.getlength(s) if k == "t" else epx + epx * 0.08
        return w


def clean_title(text: str) -> str:
    t = unicodedata.normalize("NFC", text or "")
    t = re.sub(r"#\w+", "", t)
    t = re.sub(r"[\(\[]?\bparte\s*\d+\s*(/|de)?\s*\d*[\)\]]?", "", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" -|:")
    return t


def _wrap(words: list[_Word], font, epx: int, max_w: float, max_lines: int) -> list[list[_Word]] | None:
    sp = font.getlength(" ")
    widths = [w.width(font, epx) for w in words]
    if any(x > max_w for x in widths):
        return None
    # quantas linhas no minimo (guloso)
    lines_n, cur = 1, 0.0
    for x in widths:
        if cur and cur + sp + x > max_w:
            lines_n += 1
            cur = x
        else:
            cur = cur + sp + x if cur else x
    if lines_n > max_lines:
        return None
    # equilibra: minimiza a maior linha com o mesmo numero de linhas
    n = len(words)

    def lw(i, j):
        return sum(widths[i:j]) + sp * (j - i - 1)

    @functools.lru_cache(maxsize=None)
    def best(i: int, k: int) -> tuple[float, tuple[int, ...]]:
        if k == 1:
            w = lw(i, n)
            return (w if w <= max_w else 1e9), ()
        res = (1e9, ())
        for j in range(i + 1, n - k + 2):
            w = lw(i, j)
            if w > max_w:
                break
            sub, cuts = best(j, k - 1)
            cand = max(w, sub)
            if cand < res[0]:
                res = (cand, (j,) + cuts)
        return res

    k = min(lines_n, n)
    val, cuts = best(0, k)
    if val >= 1e9:
        return None
    out, prev = [], 0
    for c in list(cuts) + [n]:
        out.append(words[prev:c])
        prev = c
    return out


def _draw_line(img: Image.Image, x: float, baseline: float, words: list[_Word], font, epx: int,
               color, cap_h: float, stroke: int = 0, stroke_fill=None, hi_word: int | None = None,
               hi_color=None) -> None:
    d = ImageDraw.Draw(img)
    sp = font.getlength(" ")
    for wi, w in enumerate(words):
        if wi:
            x += sp
        fill = hi_color if (hi_word is not None and wi == hi_word and hi_color) else color
        for k, s in w.runs:
            if k == "t":
                d.text((x, baseline), s, font=font, fill=fill, anchor="ls",
                       stroke_width=stroke, stroke_fill=stroke_fill)
                x += font.getlength(s)
            else:
                em = emoji_image(s, epx)
                if em is not None:
                    ey = round(baseline - cap_h / 2 - epx / 2)
                    img.alpha_composite(em, (round(x + epx * 0.04), ey))
                x += epx + epx * 0.08


def _rounded_mask(size: tuple[int, int], boxes: list[tuple[float, float, float, float]], r: float) -> Image.Image:
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    for (x0, y0, x1, y1) in boxes:
        d.rounded_rectangle((x0, y0, x1, y1), radius=r, fill=255)
    return m


PILL_SHADOW = 14   # margem de sombra em volta da pilula no PNG


def _pill(text: str, px: int, bg: str, fg: str) -> Image.Image:
    f = _font(px, heavy=True)
    tw = f.getlength(text)
    cap = f.getbbox("H", anchor="ls")
    cap_h = cap[3] - cap[1]
    # texto centrado pela altura das maiusculas (centro optico), nao pela caixa da fonte
    padx, pady = round(px * 0.62), round(px * 0.42)
    w, h = round(tw + 2 * padx), round(cap_h + 2 * pady)
    sh = PILL_SHADOW
    img = Image.new("RGBA", (w + 2 * sh, h + 2 * sh), (0, 0, 0, 0))
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((sh, sh + 5, sh + w, sh + h + 5), radius=h / 2, fill=(0, 0, 0, 110))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(6)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((sh, sh, sh + w, sh + h), radius=h / 2, fill=bg)
    d.text((sh + padx, sh + pady + cap_h), text, font=f, fill=fg, anchor="ls")
    return img


_KW_STRIP = ".,!?:;\"'"


def _keyword_index(lines: list[list[_Word]]) -> tuple[int, int] | None:
    """Palavra-chave para colorir (variantes invertido/contorno): numero > palavra mais longa."""
    best, best_score = None, 0.0
    for li, ln in enumerate(lines):
        for wi, w in enumerate(ln):
            txt = "".join(s for k, s in w.runs if k == "t").strip(_KW_STRIP)
            if not txt:
                continue
            score = len(txt) + (20 if any(c.isdigit() for c in txt) else 0)
            if score > best_score and len(txt) >= 4:
                best, best_score = (li, wi), score
    return best


VARIANTS = ("nativo", "invertido", "contorno")


def choose_variant(cfg, category: str | None, seed: str | None) -> str:
    want = str(cfg.get("edicao.titulo_estilo", "auto") if cfg is not None else "auto").lower()
    alias = {"tiktok": "nativo", "a": "nativo", "cartao": "nativo", "b": "invertido", "escuro": "invertido",
             "c": "contorno", "sem_caixa": "contorno"}
    want = alias.get(want, want)
    if want in VARIANTS:
        return want
    v = _style.stable_pick(f"titulo:{seed}", [("nativo", 0.5), ("invertido", 0.3), ("contorno", 0.2)])
    # nichos de paleta escura (polemica, games) trocam o nativo branco pelo invertido
    if v == "nativo" and _style.palette(category)["card"][0].upper() != "#FFFFFF":
        v = "invertido"
    return v


SIZES = {   # tamanho -> (faixa de corpo nas variantes com caixa, faixa no contorno, max de linhas)
    "normal": (range(74, 40, -2), range(96, 52, -2), 3),
    "compacto": (range(60, 38, -2), range(76, 46, -2), 2),
    "mini": (range(50, 34, -2), range(62, 40, -2), 2),
}


def render_title_card(text: str, out_path: Path, cfg=None, part: int | None = None,
                      parts_total: int | None = None, top: int | None = None,
                      category: str | None = None, seed: str | None = None,
                      variant: str | None = None, size: str = "normal") -> TitleCard | None:
    """Gera o PNG do titulo e devolve onde ele deve ser sobreposto no quadro 1080x1920.

    Variantes: nativo (caixa branca por linha, texto preto - estilo do texto do TikTok),
    invertido (caixa grafite, texto branco, palavra-chave na cor do nicho) e
    contorno (sem caixa, Anton branco com contorno preto). A pilula PARTE X/Y fica acima.
    """
    g = (lambda k, d: cfg.get(k, d)) if cfg is not None else (lambda k, d: d)
    pal = _style.palette(category)
    text = clean_title(_style.sanitize_text(text))
    if not _style.emojis_enabled(cfg):
        text = _style.strip_emojis(text)
    variant = variant if variant in VARIANTS else choose_variant(cfg, category, seed or text)
    if g("edicao.titulo_maiusculas", False) or variant == "contorno":
        text = text.upper()
    has_part = bool(part)
    if not text and not has_part:
        return None
    # mesma coluna da legenda (140 a 940): a coluna de botoes da direita comeca em x=940
    max_box_w = int(g("edicao.titulo_largura_max", 800))
    top = int(top if top is not None else g("edicao.titulo_topo", 260))
    hi_color = _style.highlight_color(cfg, category)
    if variant == "nativo":
        box_color = str(g("edicao.titulo_cor_caixa", "") or "#FFFFFF")
        text_color = str(g("edicao.titulo_cor_texto", "") or "#000000")
        hi_color = None
    elif variant == "invertido":
        box_color, text_color = pal["card"] if pal["card"][0].upper() != "#FFFFFF" else ("#111111", "#FFFFFF")
    else:
        box_color, text_color = None, "#FFFFFF"

    heavy_path = None
    if variant == "contorno":
        fonts_av = _fonts.ensure_fonts()
        heavy_path = fonts_av.get("anton") or fonts_av.get("impact")

    def font_for(px: int):
        if heavy_path:
            return ImageFont.truetype(str(heavy_path), px)
        return _font(px)

    size = size if size in SIZES else "normal"
    box_range, outline_range, max_lines = SIZES[size]
    size_range = list(outline_range if variant == "contorno" else box_range)
    words = [_Word(split_runs(w)) for w in text.split()] if text else []
    lines = None
    font, epx = None, 0
    for px in size_range:
        font = font_for(px)
        epx = round(px * (0.92 if variant == "contorno" else 1.02))
        padx = px * 0.55 if box_color else px * 0.2
        lines = _wrap(words, font, epx, max_box_w - 2 * padx, max_lines) if words else []
        if lines is not None:
            break
    if lines is None:  # nao coube nem pequeno: corta e poe reticencias
        px = size_range[-1]
        font, epx = font_for(px), round(px * 1.02)
        padx = px * 0.55
        kept: list[_Word] = []
        for w in words:
            if _wrap(kept + [w], font, epx, max_box_w - 2 * padx, max_lines) is None:
                break
            kept.append(w)
        if kept:
            kept[-1] = _Word(kept[-1].runs + [("t", "...")])
            if _wrap(kept, font, epx, max_box_w - 2 * padx, max_lines) is None:
                kept = kept[:-1]
        lines = _wrap(kept, font, epx, max_box_w - 2 * padx, max_lines) or []

    px = font.size
    padx = px * 0.55 if box_color else px * 0.2
    cap = font.getbbox("H", anchor="ls")
    cap_h = cap[3] - cap[1]
    line_h = round(px * (1.36 if box_color else 1.14))
    radius = min(_style.RADIUS_BOX, line_h / 2)   # mesmo raio de todas as caixas
    margin = 24 if box_color else 48  # espaco para sombra
    stroke = max(4, round(px * 0.09)) if variant == "contorno" else 0
    widths = [sum(w.width(font, epx) for w in ln) + font.getlength(" ") * (len(ln) - 1) for ln in lines]
    box_ws = [w + 2 * padx for w in widths]
    text_h = line_h * len(lines) + (px * 0.12 if lines else 0)

    pill_img = None
    if has_part:
        last = bool(parts_total) and part == parts_total and parts_total > 1
        ptxt = f"PARTE {part}/{parts_total}" if parts_total else f"PARTE {part}"
        if last:
            ptxt += " | FINAL"
        pbg, pfg = pal["pill"]
        pill_img = _pill(_style.sanitize_text(ptxt), int(g("edicao.parte_tamanho", 40)),
                         str(g("edicao.cor_parte", "") or pbg), str(g("edicao.cor_parte_texto", "") or pfg))
    # o selo PARTE X/Y fica SEPARADO da caixa do titulo (o dono achou sobreposto demais):
    # espaco VISIVEL entre a pilula e a caixa = edicao.parte_espaco (a sombra do PNG nao conta)
    pill_gap = int(g("edicao.parte_espaco", 16)) if (pill_img is not None and lines) else 0
    pill_h = (pill_img.height - 2 * PILL_SHADOW + pill_gap) if pill_img is not None else 0
    # sem caixa (contorno): o que se ve e o texto, nao a linha; o espaco conta a partir das maiusculas
    ink_top = 0.0 if box_color else max(0.0, (line_h - cap_h) / 2 - max(stroke, (epx - cap_h) / 2))
    canvas_w = round(max(box_ws + [0.0, float(pill_img.width if pill_img else 0)]) + 2 * margin)
    canvas_h = max(2, round(text_h + 2 * margin + pill_h))
    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    cx = canvas_w / 2
    ty0 = margin + pill_h - ink_top  # topo do bloco de texto
    bw_max = max(box_ws + [0.0])
    if box_color:
        box = (cx - bw_max / 2, ty0, cx + bw_max / 2, ty0 + text_h)
    else:
        ink_bottom = ty0 + (len(lines) - 1) * line_h + line_h / 2 + cap_h / 2 + max(stroke, (epx - cap_h) / 2)
        box = (cx - bw_max / 2, ty0 + ink_top, cx + bw_max / 2, ink_bottom)
    kw = _keyword_index(lines) if (variant != "nativo" and hi_color) else None

    if lines:
        if box_color:
            boxes = []
            for i, bw in enumerate(box_ws):
                y0 = ty0 + i * line_h
                y1 = y0 + line_h + (px * 0.12 if i == len(lines) - 1 else radius)
                boxes.append((cx - bw / 2, y0, cx + bw / 2, y1))
            mask = _rounded_mask(img.size, boxes, radius)
            sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
            sh.putalpha(mask.point(lambda v: v * 0.45))
            sh = sh.filter(ImageFilter.GaussianBlur(9))
            img.alpha_composite(sh, (0, 6))
            fill = Image.new("RGBA", img.size, box_color)
            alpha = 235 if variant == "invertido" else 255
            fill.putalpha(mask.point(lambda v: v * alpha // 255))
            img.alpha_composite(fill)
        else:
            # sombra difusa larga atras do texto: segura a leitura mesmo sobre fundo claro/poluido
            shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
            for i, ln in enumerate(lines):
                baseline = ty0 + i * line_h + line_h / 2 + cap_h / 2
                _draw_line(shadow, cx - widths[i] / 2, baseline + 4, ln, font, epx, (0, 0, 0, 200), cap_h,
                           stroke=stroke + 14, stroke_fill=(0, 0, 0, 200))
            img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(16)))
            img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(6)))
        for i, ln in enumerate(lines):
            baseline = ty0 + i * line_h + line_h / 2 + cap_h / 2 + (
                px * 0.06 if (box_color and i == len(lines) - 1) else 0)
            _draw_line(img, cx - widths[i] / 2, baseline, ln, font, epx, text_color, cap_h,
                       stroke=stroke, stroke_fill="#000000",
                       hi_word=kw[1] if (kw and kw[0] == i) else None, hi_color=hi_color)

    pill_vis = None
    if pill_img is not None:
        # a pilula visivel comeca em y=margin (a sombra de cima sai do quadro do PNG)
        px0 = round((canvas_w - pill_img.width) / 2)
        img.alpha_composite(pill_img, (px0, margin - PILL_SHADOW))
        pill_vis = (px0 + PILL_SHADOW, margin, pill_img.width - 2 * PILL_SHADOW, pill_img.height - 2 * PILL_SHADOW)

    # recorte com centro horizontal preservado (o eixo do PNG continua sendo o eixo do quadro)
    bb = img.getbbox()
    ox = oy = 0
    if bb:
        cxc = canvas_w / 2
        half = max(cxc - bb[0], bb[2] - cxc)
        x0c, x1c = max(0, int(cxc - half)), min(canvas_w, int(round(cxc + half)))
        img = img.crop((x0c, bb[1], x1c, bb[3]))
        ox, oy = x0c, bb[1]
    out_path = Path(out_path)
    img.save(out_path)
    x = round(W / 2 - (canvas_w / 2 - ox))
    y = max(SAFE_TOP, top - round(box[1] - oy))   # topo do bloco de texto em y=top
    bx0, by0, bx1, by1 = box
    frame_box = (x + round(bx0 - ox), y + round(by0 - oy), round(bx1 - bx0), round(by1 - by0)) if lines else None
    frame_pill = None
    if pill_vis is not None:
        frame_pill = (x + pill_vis[0] - ox, y + pill_vis[1] - oy, pill_vis[2], pill_vis[3])
    return TitleCard(out_path, x, y, img.width, img.height, box=frame_box, variant=variant, pill=frame_pill,
                     size=size, lines=len(lines))
