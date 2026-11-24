"""Legendas animadas em ASS (libass): 2 palavras por tela (padrao), palavra atual destacada na cor
do nicho (karaoke), entrada com "pop", contorno grosso. Tambem desenha a barra de progresso e a
marca d'agua.

Tempos do Transcript sao relativos ao inicio do corte (0 = inicio).
"""
from __future__ import annotations

import functools
import re
import struct
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from ..models import Transcript
from . import fonts as _fonts
from . import style as _style

W, H = 1080, 1920

# Y (centro da legenda) por layout. Zona inferior de UI do TikTok/Shorts: ~y>1540.
CAPTION_Y = {
    ("split", "centro"): 1290,    # sobre o fundo (a emenda fica com o titulo)
    ("split", "baixo"): 1420,
    ("blur", "centro"): 1410,
    ("blur", "baixo"): 1420,
    ("full", "centro"): 1300,     # abaixo do queixo no recorte 9:16 de podcast
    ("full", "baixo"): 1420,
}
WATERMARK_MAX_Y = 1560
# edicao.legenda.tamanho e uma escala "amigavel" (padrao 90). Fontsize real do ASS =
# tamanho * SIZE_SCALE * fator do layout (full maior, blur menor).
SIZE_SCALE = 1.25
LAYOUT_SIZE = {"full": 1.067, "split": 1.0, "blur": 0.933}
# largura maxima centrada: 140 px livres de cada lado (a coluna de botoes da direita comeca em x=940)
MAX_TEXT_W = {"split": 800, "blur": 800, "full": 800}
MIN_BLOCK_S = 0.30

_PUNCT_ONLY = re.compile(r"^[\W_]+$", re.U)
_BRACKETED = re.compile(r"^[\[\(].*[\]\)]$")


@dataclass
class _W:
    start: float
    end: float
    text: str
    raw: str = ""


# ------------------------------------------------------------------ util
def ass_color(hex_color: str, alpha: int = 0) -> str:
    """'#RRGGBB' -> '&HAABBGGRR' (alpha 0 = opaco)."""
    h = (hex_color or "#FFFFFF").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ass_inline_color(hex_color: str) -> str:
    return ass_color(hex_color)[4:]  # BBGGRR


def ass_time(cs: int) -> str:
    """centesimos -> H:MM:SS.cc"""
    cs = max(0, int(cs))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def escape_ass(text: str) -> str:
    """Remove o que o ASS interpretaria como comando."""
    text = (text or "").replace("\\", "").replace("{", "(").replace("}", ")")
    return re.sub(r"[\r\n\t]+", " ", text)


def strip_emoji(text: str) -> str:
    return _style.strip_emojis(text)


def clean_word(text: str, upper: bool, censor: bool = True) -> str:
    t = _style.sanitize_text(strip_emoji(unicodedata.normalize("NFC", text or ""))).strip()
    if _BRACKETED.match(t):   # [Musica], (risos)
        return ""
    t = escape_ass(t).strip()
    t = t.strip("\"'“”‘’«»()[]-/*_|")
    t = re.sub(r"[,;:]+$", "", t)
    t = t.rstrip(".") if t.endswith(".") else t
    if censor:
        t = _style.mask_profanity(t)
    return t.upper() if upper else t


# ------------------------------------------------------------------ medicao (mesmas regras do libass)
@functools.lru_cache(maxsize=8)
def _ass_em_ratio(font_path: str) -> float:
    """libass usa tamanho = (winAscent+winDescent); converte para tamanho em em do FreeType."""
    try:
        data = Path(font_path).read_bytes()
        n = struct.unpack(">H", data[4:6])[0]
        tables = {}
        for i in range(n):
            tag, _cs, off, _ln = struct.unpack(">4sIII", data[12 + 16 * i: 28 + 16 * i])
            tables[tag] = off
        upm = struct.unpack(">H", data[tables[b"head"] + 18: tables[b"head"] + 20])[0]
        os2 = tables.get(b"OS/2")
        if os2 is not None:
            asc, desc = struct.unpack(">HH", data[os2 + 74: os2 + 78])
            if asc + desc > 0:
                return upm / (asc + desc)
        hh = tables[b"hhea"]
        asc, desc = struct.unpack(">hh", data[hh + 4: hh + 8])
        return upm / (asc - desc)
    except Exception:  # noqa: BLE001
        return 0.82


@functools.lru_cache(maxsize=16)
def _pil_font(font_path: str, px: int):
    from PIL import ImageFont

    return ImageFont.truetype(font_path, px)


class TextMeasure:
    def __init__(self, font_path: Path | None, ass_size: float, outline: float):
        self.font_path = str(font_path) if font_path else None
        self.ass_size = ass_size
        self.outline = outline

    def width(self, text: str) -> float:
        if not self.font_path:
            return len(text) * self.ass_size * 0.62 + 2 * self.outline
        px = max(4, round(self.ass_size * _ass_em_ratio(self.font_path)))
        return _pil_font(self.font_path, px).getlength(text) + 2 * self.outline


# ------------------------------------------------------------------ palavras
def _transcript_words(tr: Transcript | None, duration: float) -> list[_W]:
    if tr is None:
        return []
    out: list[_W] = []
    for seg in tr.segments:
        if seg.words:
            for w in seg.words:
                out.append(_W(float(w.start), float(w.end), w.text))
        else:
            # so tempo do segmento: espalha as palavras proporcionalmente ao tamanho
            toks = (seg.text or "").split()
            if not toks:
                continue
            total = sum(len(t) + 1 for t in toks)
            t0, span = float(seg.start), max(0.2, float(seg.end) - float(seg.start))
            acc = 0
            for t in toks:
                ws = t0 + span * acc / total
                acc += len(t) + 1
                out.append(_W(ws, t0 + span * acc / total, t))
    out.sort(key=lambda w: w.start)
    # junta pontuacao solta na palavra anterior; corrige tempos
    fixed: list[_W] = []
    for w in out:
        txt = (w.text or "").strip()
        if not txt:
            continue
        if _PUNCT_ONLY.match(txt) and fixed:
            fixed[-1].text += txt
            fixed[-1].end = max(fixed[-1].end, w.end)
            continue
        s = max(0.0, w.start)
        e = max(s + 0.06, w.end)
        if fixed and s < fixed[-1].start:
            s = fixed[-1].start
        fixed.append(_W(s, e, txt))
    return [w for w in fixed if w.start < duration - 0.05]


def _group(words: list[_W], n: int, upper: bool, measure: TextMeasure, max_w: float,
           censor: bool = True, breaks: list[float] | None = None, max_lines: int = 2) -> list[list[_W]]:
    breaks = sorted(breaks or [])
    fit = 1.85 if max_lines >= 2 else 1.0   # 1 linha: par largo demais vira 2 telas de 1 palavra
    groups: list[list[_W]] = []
    cur: list[_W] = []
    for w in words:
        disp = clean_word(w.text, upper, censor)
        if not disp:
            continue
        ww = _W(w.start, w.end, disp, (w.text or "").strip())
        if cur:
            gap = ww.start - cur[-1].end
            text = " ".join(x.text for x in cur + [ww])
            too_wide = measure.width(text) > max_w * fit   # cabe em ate max_lines linhas
            sentence_end = re.search(r"[.!?…]$", cur[-1].raw or "") is not None
            crosses = any(cur[0].start < b <= ww.start + 0.005 for b in breaks)   # emenda teaser -> corte
            if len(cur) >= n or gap > 0.6 or too_wide or sentence_end or crosses:
                groups.append(cur)
                cur = []
        cur.append(ww)
    if cur:
        groups.append(cur)
    # bloco que ficaria menos de 0,30 s na tela junta com o proximo (se couber)
    merged: list[list[_W]] = []
    for i, grp in enumerate(groups):
        nxt = groups[i + 1] if i + 1 < len(groups) else None
        if nxt and nxt[0].start - grp[0].start < MIN_BLOCK_S and len(grp) + len(nxt) <= n + 1 \
                and not any(grp[0].start < b <= nxt[0].start + 0.005 for b in breaks) \
                and measure.width(" ".join(x.text for x in grp + nxt)) <= max_w * fit:
            groups[i + 1] = grp + nxt
        else:
            merged.append(grp)
    return merged


def _layout_lines(words: list[str], measure: TextMeasure, max_w: float) -> tuple[list[list[int]], float]:
    """Quebra em 1 ou 2 linhas equilibradas. Devolve (linhas como indices, escala %)."""
    full = measure.width(" ".join(words))
    if full <= max_w or len(words) == 1:
        return [list(range(len(words)))], min(100.0, 100.0 * max_w / full) if full > max_w else 100.0
    best, best_w = 1, 1e9
    for k in range(1, len(words)):
        w1 = measure.width(" ".join(words[:k]))
        w2 = measure.width(" ".join(words[k:]))
        if max(w1, w2) < best_w:
            best, best_w = k, max(w1, w2)
    lines = [list(range(best)), list(range(best, len(words)))]
    scale = 100.0 if best_w <= max_w else 100.0 * max_w / best_w
    return lines, scale


def _rounded_rect(w: int, h: int, r: int) -> str:
    """Retangulo de cantos arredondados em desenho ASS (\\p1)."""
    r = max(0, min(r, h // 2, w // 2))
    if r == 0:
        return f"m 0 0 l {w} 0 {w} {h} 0 {h}"
    return (f"m {r} 0 l {w - r} 0 b {w} 0 {w} 0 {w} {r} l {w} {h - r} b {w} {h} {w} {h} {w - r} {h} "
            f"l {r} {h} b 0 {h} 0 {h} 0 {h - r} l 0 {r} b 0 0 0 0 {r} 0")


# ------------------------------------------------------------------ ASS
def build_ass(captions: Transcript | None, duration: float, cfg, layout: str, out_path: Path,
              watermark: str | None = None, progress_bar: bool | None = None,
              caption_y: int | None = None, category: str | None = None,
              bar_rect: tuple[int, int, int, int] | None = None,
              teaser_until: float = 0.0, teaser_color: str | None = None, max_lines: int | None = None) -> Path:
    """Gera o .ass com legendas + barra de progresso + marca d'agua.

    bar_rect = (x, y, largura, altura) da barra (ex.: logo abaixo do titulo); None = topo da tela.
    teaser_until > 0: as legendas antes desse instante (cold open) usam teaser_color no destaque,
    ficam 8% maiores e nunca se juntam com as do corte normal.
    """
    g = (lambda k, d: cfg.get(k, d)) if cfg is not None else (lambda k, d: d)
    family, font_path = _fonts.caption_font(cfg)
    lay = layout if layout in ("split", "blur", "full") else "full"
    style = str(g("edicao.legenda.estilo", "karaoke")).lower()
    size = float(g("edicao.legenda.tamanho", 90) or 90) * SIZE_SCALE * LAYOUT_SIZE[lay]
    color = str(g("edicao.legenda.cor", "#FFFFFF"))
    hi = _style.highlight_color(cfg, category)
    outline_c = str(g("edicao.legenda.contorno", "#000000"))
    n_words = max(1, int(g("edicao.legenda.palavras_por_tela", 2) or 2))
    upper = bool(g("edicao.legenda.maiusculas", True))
    censor = bool(g("edicao.legenda.censurar_palavroes", True))
    pos = str(g("edicao.legenda.posicao", "centro")).lower()
    pos = pos if pos in ("centro", "baixo") else "centro"
    if style == "palavra":
        n_words, size = 1, size * 1.15
    outline = max(3.0, round(size * 0.075, 1))
    shadow = max(2.0, round(size * 0.035, 1))
    # caption_y vem do safezone (ja respeita edicao.legenda.posicao e o lugar livre do rosto)
    cy = int(g("edicao.legenda.y", 0) or 0) or (caption_y if caption_y else 0) or CAPTION_Y[(lay, pos)]
    max_w = MAX_TEXT_W[lay]
    measure = TextMeasure(font_path, size, outline)

    wm_raw = watermark if watermark is not None else str(g("edicao.marca_dagua", "") or "")
    wm_text = escape_ass(_style.sanitize_text(_style.strip_emojis(wm_raw))).strip()
    bar = bool(g("edicao.barra_progresso", True)) if progress_bar is None else progress_bar
    if duration <= float(g("edicao.barra_min_s", 35) or 0):
        bar = False   # corte curto: a barra nativa da plataforma basta
    wm_family = (_fonts.FONT_SPECS["montserrat_extrabold"][2]
                 if "montserrat_extrabold" in _fonts.ensure_fonts() else family)
    wm_y = min(WATERMARK_MAX_Y, cy + round(size * 1.35))

    dur_cs = int(round(duration * 100))
    lines = [
        "[Script Info]",
        "; Fabrica de Cortes - legendas",
        "ScriptType: v4.00+",
        f"PlayResX: {W}",
        f"PlayResY: {H}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{family},{size:.0f},{ass_color(color)},{ass_color(hi)},{ass_color(outline_c)},"
        f"&H80000000,0,0,0,0,100,100,1,0,1,{outline},{shadow},5,40,40,40,1",
        f"Style: Wm,{wm_family},40,{ass_color('#FFFFFF', 0x80)},&H00FFFFFF,{ass_color('#000000', 0xA0)},"
        f"&HFF000000,0,0,0,0,100,100,1,0,1,2,0,5,40,40,40,1",
        "Style: Bar,Arial,20,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    # ---- barra de progresso (desenho ASS com \clip animado: barato e suave)
    if bar and dur_cs > 0:
        if bar_rect:
            bx, by, bw, bh = (int(v) for v in bar_rect)
        else:
            bh = int(g("edicao.barra_altura", 8) or 8)
            bx, bw = 0, W
            by = H - bh if str(g("edicao.barra_posicao", "topo")).lower() == "base" else 0
        shape = _rounded_rect(bw, bh, bh // 2 if bar_rect else 0)
        lines.append(f"Dialogue: 5,{ass_time(0)},{ass_time(dur_cs)},Bar,,0,0,0,,"
                     f"{{\\an7\\pos({bx},{by})\\p1\\bord0\\shad0\\c&HFFFFFF&\\alpha&HA6&}}{shape}")
        lines.append(f"Dialogue: 6,{ass_time(0)},{ass_time(dur_cs)},Bar,,0,0,0,,"
                     f"{{\\an7\\pos({bx},{by})\\p1\\bord0\\shad0\\c&H{ass_inline_color(hi)}&"
                     f"\\clip({bx},{by},{bx},{by + bh})\\t(0,{dur_cs * 10},\\clip({bx},{by},{bx + bw},{by + bh}))}}"
                     f"{shape}")

    # ---- marca d'agua
    if wm_text and dur_cs > 0:
        lines.append(f"Dialogue: 4,{ass_time(0)},{ass_time(dur_cs)},Wm,,0,0,0,,"
                     f"{{\\an5\\pos({W // 2},{wm_y})}}{wm_text}")

    # ---- legendas
    words = _transcript_words(captions, duration)
    if max_lines is None:
        max_lines = int(g("edicao.legenda.max_linhas", 2) or 2)
    groups = _group(words, n_words, upper, measure, max_w, censor,
                    breaks=[teaser_until] if teaser_until > 0 else None, max_lines=max_lines)
    hi_tag = f"\\c&H{ass_inline_color(hi)}&"
    tz_tag = f"\\c&H{ass_inline_color(teaser_color or hi)}&"
    base_tag = f"\\c&H{ass_inline_color(color)}&"
    for gi, grp in enumerate(groups):
        nxt = groups[gi + 1][0].start if gi + 1 < len(groups) else duration
        g_start = grp[0].start
        in_teaser = teaser_until > 0 and g_start < teaser_until
        g_end = min(nxt, max(grp[-1].end + 0.35, g_start + MIN_BLOCK_S), duration)
        if in_teaser:
            g_end = min(g_end, teaser_until - 0.006)   # some antes do 1o quadro do corte normal
        texts = [w.text for w in grp]
        line_idx, scale = _layout_lines(texts, measure, max_w)
        if in_teaser:   # 8% maior, sem estourar a largura maxima
            widest = max(measure.width(" ".join(texts[i] for i in idxs)) for idxs in line_idx)
            scale = min(scale * 1.08, 100.0 * max_w / max(1.0, widest))
        act_tag = tz_tag if in_teaser else hi_tag
        sc = f"{scale:.0f}"
        pop = (f"\\fscx{scale * 0.75:.0f}\\fscy{scale * 0.75:.0f}"
               f"\\t(0,65,\\fscx{scale * 1.06:.0f}\\fscy{scale * 1.06:.0f})\\t(65,130,\\fscx{sc}\\fscy{sc})")
        head = f"\\an5\\pos({W // 2},{cy})\\blur0.6"

        def render(active: int | None) -> str:
            parts = []
            for idxs in line_idx:
                seg = []
                for i in idxs:
                    if active is not None and i == active:
                        seg.append(f"{{{act_tag}}}{texts[i]}{{{base_tag}}}")
                    else:
                        seg.append(texts[i])
                parts.append(" ".join(seg))
            return "\\N".join(parts)

        if style == "bloco":
            events = [(g_start, g_end, None)]
        else:
            events = []
            for i, w in enumerate(grp):
                s = g_start if i == 0 else w.start
                e = grp[i + 1].start if i + 1 < len(grp) else g_end
                if e - s < 0.01:
                    continue
                events.append((s, e, i))
        cs_prev_end = None
        for k, (s, e, act) in enumerate(events):
            s_cs = int(round(s * 100)) if cs_prev_end is None else cs_prev_end
            e_cs = max(s_cs + 1, int(round(e * 100)))
            cs_prev_end = e_cs
            tag = head + (pop if k == 0 else f"\\fscx{sc}\\fscy{sc}")
            lines.append(f"Dialogue: 1,{ass_time(s_cs)},{ass_time(e_cs)},Cap,,0,0,0,,{{{tag}}}{render(act)}")

    out_path = Path(out_path)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return out_path


# ------------------------------------------------------------------ camada de depuracao (edicao.depurar_grade)
def build_debug_ass(out_path: Path, duration: float, items: list, faces_t: list) -> Path:
    """Grade de alinhamento e zonas seguras + contorno de cada elemento e dos rostos ao longo do tempo.

    items: [(nome, (x0, y0, x1, y1), t0, t1)]; faces_t: [(t0, t1, (x0, y0, x1, y1))].
    Ciano = margens de 64 px; magenta = eixo central; vermelho translucido = zonas de UI;
    laranja = coluna de botoes; amarelo = elementos; vermelho = rostos (nada pode encostar)."""
    from . import style as _st

    dur_cs = max(1, int(round(duration * 100)))

    def rect_shape(x0, y0, x1, y1):
        x0, y0, x1, y1 = (int(round(v)) for v in (x0, y0, x1, y1))
        return f"m {x0} {y0} l {x1} {y0} {x1} {y1} {x0} {y1}"

    def fill(x0, y0, x1, y1, color, alpha, layer=0, t0=0.0, t1=None):
        a, b = int(round(t0 * 100)), dur_cs if t1 is None else min(dur_cs, int(round(t1 * 100)))
        return (f"Dialogue: {layer},{ass_time(a)},{ass_time(max(a + 1, b))},Dbg,,0,0,0,,"
                f"{{\\an7\\pos(0,0)\\p1\\bord0\\shad0\\c&H{ass_inline_color(color)}&\\alpha&H{alpha:02X}&}}"
                f"{rect_shape(x0, y0, x1, y1)}")

    def outline(x0, y0, x1, y1, color, layer=2, t0=0.0, t1=None, wd=3):
        return [fill(x0, y0, x1, y0 + wd, color, 0x10, layer, t0, t1), fill(x0, y1 - wd, x1, y1, color, 0x10, layer, t0, t1),
                fill(x0, y0, x0 + wd, y1, color, 0x10, layer, t0, t1), fill(x1 - wd, y0, x1, y1, color, 0x10, layer, t0, t1)]

    ev = []
    ev.append(fill(0, 0, W, _st.SAFE_TOP, "#FF0000", 0xC0))
    ev.append(fill(0, _st.SAFE_BOTTOM_Y, W, H, "#FF0000", 0xC0))
    ev.append(fill(*_st.RAIL, "#FF8800", 0xC0))
    for x in (_st.MARGIN, W - _st.MARGIN):
        ev.append(fill(x - 1, 0, x + 1, H, "#00FFFF", 0x30))
    ev.append(fill(W // 2 - 1, 0, W // 2 + 1, H, "#FF00FF", 0x50))
    for y in range(0, H, 64):   # regua de 64 px (marcas menores a cada 16 px)
        ev.append(fill(0, y, 28, y + 2, "#FFFFFF", 0x40))
        for k in (16, 32, 48):
            ev.append(fill(0, y + k, 12, y + k + 1, "#FFFFFF", 0x70))
    for name, r, t0, t1 in items:
        ev += outline(*r, "#FFE600", 3, t0, None if t1 >= 1e8 else t1, 2)
    for t0, t1, r in faces_t:
        ev += outline(*r, "#FF2020", 4, t0, t1, 4)
    head = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Dbg,Arial,20,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    out_path = Path(out_path)
    out_path.write_text("\n".join(head + ev) + "\n", encoding="utf-8-sig")
    return out_path


def caption_extent(captions: Transcript | None, duration: float, cfg, layout: str,
                   teaser_until: float = 0.0, max_lines: int = 2) -> dict:
    """Quanto a legenda ocupa de verdade neste corte (mesmas regras do build_ass): maior numero de
    linhas, maior largura e o corpo. O safezone reserva so isso (e nao o pior caso de 2 linhas)."""
    g = (lambda k, d: cfg.get(k, d)) if cfg is not None else (lambda k, d: d)
    _family, font_path = _fonts.caption_font(cfg)
    lay = layout if layout in ("split", "blur", "full") else "full"
    style = str(g("edicao.legenda.estilo", "karaoke")).lower()
    size = float(g("edicao.legenda.tamanho", 90) or 90) * SIZE_SCALE * LAYOUT_SIZE[lay]
    n_words = max(1, int(g("edicao.legenda.palavras_por_tela", 2) or 2))
    upper = bool(g("edicao.legenda.maiusculas", True))
    censor = bool(g("edicao.legenda.censurar_palavroes", True))
    if style == "palavra":
        n_words, size = 1, size * 1.15
    outline = max(3.0, round(size * 0.075, 1))
    max_w = MAX_TEXT_W[lay]
    measure = TextMeasure(font_path, size, outline)
    words = _transcript_words(captions, duration)
    groups = _group(words, n_words, upper, measure, max_w, censor,
                    breaks=[teaser_until] if teaser_until > 0 else None, max_lines=max_lines)
    lines_max, width_max = 0, 0.0
    for grp in groups:
        texts = [w.text for w in grp]
        line_idx, scale = _layout_lines(texts, measure, max_w)
        k = scale / 100.0
        if teaser_until > 0 and grp[0].start < teaser_until:
            k = min(k * 1.08, max_w / max(1.0, max(measure.width(" ".join(texts[i] for i in ix)) for ix in line_idx)))
        lines_max = max(lines_max, len(line_idx))
        for ix in line_idx:
            width_max = max(width_max, measure.width(" ".join(texts[i] for i in ix)) * k)
    return {"lines": lines_max, "width": min(float(max_w), width_max), "size": size, "outline": outline,
            "max_w": max_w}
