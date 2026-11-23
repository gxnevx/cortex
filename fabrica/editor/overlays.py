"""Elementos sobrepostos ao video (PNG com Pillow, emojis coloridos como no titulo):

- etiqueta de nome (lower third de TV, ~2,6 s depois do teaser): "DIA FREITAS" / "no Podpah",
  sequencia de PNGs com entrada escalonada e saida suave (padrao, edicao.etiqueta_nome).
- cartao de contexto antigo (desligado por padrao, edicao.cartao_contexto).
- CTA de serie (ultimos 2,0 s, so quando ha proxima parte): pilula "PARTE 2 NO PERFIL".
- marca: logo (edicao.logo_marca_dagua) + @ de cada rede (uma versao do video por rede).
Onde cada um fica e decidido pelo safezone (nunca sobre o rosto, o titulo ou a legenda).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import fonts as _fonts
from . import style as _style
from . import titlecard as _tc

W, H = 1080, 1920


@dataclass
class Overlay:
    path: Path
    w: int
    h: int
    x: int = 0
    y: int = 0
    pad_top: int = 0      # sombra acima do conteudo visivel (para alinhar pelo conteudo)
    pad_bottom: int = 0


# ------------------------------------------------------------------ textos
_URL = re.compile(r"https?://\S+|www\.\S+")


def _clean(text: str, emojis: bool) -> str:
    t = unicodedata.normalize("NFC", text or "")
    t = _URL.sub("", t)
    t = re.sub(r"#\w+", "", t)
    t = _style.sanitize_text(t)
    if not emojis:
        t = _style.strip_emojis(t)
    return re.sub(r"\s+", " ", t).strip(" -|:;,")


def _shorten(text: str, max_chars: int) -> str:
    """Corta numa fronteira boa (virgula, dois-pontos, palavra) sem passar de max_chars."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars + 1]
    for sep in (". ", "! ", "? ", ": ", ", ", " - ", " ("):
        i = cut.rfind(sep)
        if i >= max_chars * 0.55:
            return text[:i].rstrip(" ,;:-(")
    i = cut.rfind(" ")
    return (text[:i] if i > 0 else text[:max_chars]).rstrip(" ,;:-") + "..."


def _same(a: str, b: str) -> bool:
    def n(s):
        s = unicodedata.normalize("NFKD", _style.strip_emojis(s or "")).encode("ascii", "ignore").decode().lower()
        return re.sub(r"[^a-z0-9]", "", s)
    na, nb = n(a), n(b)
    return bool(na) and (na == nb or (len(na) > 12 and (na in nb or nb in na)))


def context_text(plan, cfg, shown_title: str = "", max_chars: int = 60) -> str:
    """Linha de contexto: plan.context (se o cerebro preencher) > 1a frase da descricao.

    Nunca repete o titulo que ja esta no video. Sem prefixo (a etiqueta CONTEXTO e desenhada a parte).
    """
    if plan is None:
        return ""
    emojis = _style.emojis_enabled(cfg)
    override = cfg.get("edicao.contexto_texto", "") if cfg is not None else ""
    cands = [str(override or ""), str(getattr(plan, "context", "") or "")]
    desc = _clean(getattr(plan, "description", "") or "", emojis)
    if desc:
        first = re.split(r"(?<=[.!?…])\s+", desc, maxsplit=1)[0]
        cands.append(first)
    for c in cands:
        c = _clean(c, emojis)
        c = re.sub(r"^(contexto|context)\s*[:\-|]\s*", "", c, flags=re.I)
        c = c.rstrip(".").strip()
        if len(c) < 8 or _same(c, shown_title):
            continue
        return _shorten(c, max_chars)
    return ""


# rodizio das CTAs de serie (docs/ideias/criativo_genz.json, cta_finais.serie_no_video). Nada de
# "segue pra parte 2" (o TikTok trata como manipulacao de engajamento).
CTA_SERIE = [
    ("PARTE {n} NO PERFIL", "\U0001F440"),
    ("A RESPOSTA TÁ NA PARTE {n}", ""),
    ("CONTINUA NA PARTE {n}", "\U0001F51C"),
    ("PARTE {n} JÁ TÁ NO PERFIL", ""),
]


def cta_text(plan, cfg) -> str:
    if plan is None or not plan.part or not plan.parts_total or plan.part >= plan.parts_total:
        return ""
    custom = cfg.get("edicao.cta_serie_textos", None) if cfg is not None else None
    n = plan.part + 1
    if isinstance(custom, list) and custom:
        tpl = _style.stable_pick(f"cta:{plan.id}", [(str(c), 1.0) for c in custom])
        txt = tpl.replace("{n}", str(n))
    else:
        i = _style.stable_pick(f"cta:{plan.id}", [(str(k), 1.0) for k in range(len(CTA_SERIE))])
        tpl, emo = CTA_SERIE[int(i)]
        txt = tpl.format(n=n) + (f" {emo}" if emo else "")
    return _clean(txt, _style.emojis_enabled(cfg))


# ------------------------------------------------------------------ desenho
def _font(px: int, weight: str = "extrabold") -> ImageFont.FreeTypeFont:
    av = _fonts.ensure_fonts()
    key = {"black": "montserrat_black", "extrabold": "montserrat_extrabold"}.get(weight, "montserrat_extrabold")
    p = av.get(key) or av.get("montserrat_black") or av.get("montserrat_extrabold")
    if p is None:
        path, _var = _fonts.title_font_path(heavy=weight == "black")
        return ImageFont.truetype(str(path), px) if path else ImageFont.load_default(px)
    return ImageFont.truetype(str(p), px)


def _luma(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except (ValueError, IndexError):
        return 1.0
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def _tracked(draw: ImageDraw.ImageDraw, xy, text: str, font, fill, tracking: float) -> float:
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill, anchor="ls")
        x += font.getlength(ch) + tracking
    return x


def _tracked_len(text: str, font, tracking: float) -> float:
    return sum(font.getlength(c) for c in text) + tracking * max(0, len(text) - 1)


def _shadowed(card: Image.Image, radius: float, blur: int = 14, offset: int = 8, alpha: int = 120,
              margin: int = 28) -> tuple[Image.Image, int]:
    """Coloca o cartao numa tela maior com sombra difusa. Devolve (imagem, margem)."""
    w, h = card.size
    out = Image.new("RGBA", (w + 2 * margin, h + 2 * margin), (0, 0, 0, 0))
    sh = Image.new("RGBA", out.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((margin, margin + offset, margin + w, margin + h + offset),
                                         radius=radius, fill=(0, 0, 0, alpha))
    out.alpha_composite(sh.filter(ImageFilter.GaussianBlur(blur)))
    out.alpha_composite(card, (margin, margin))
    return out, margin


def render_context_card(text: str, out_path: Path, cfg=None, category: str | None = None,
                        max_w: int = 900) -> Overlay | None:
    """Cartao de vidro escuro: [CONTEXTO] + texto em ate 2 linhas (emojis coloridos se ligados)."""
    text = (text or "").strip()
    if not text:
        return None
    hi = _style.highlight_color(cfg, category)
    label = str(cfg.get("edicao.contexto_etiqueta", "CONTEXTO") if cfg is not None else "CONTEXTO") or "CONTEXTO"
    label = _style.sanitize_text(_style.strip_emojis(label)).upper()[:16]
    pad_x, pad_y = 30, 22
    words = [_tc._Word(_tc.split_runs(w)) for w in text.split()]
    chip_font = _font(24, "black")
    track = 2.2
    chip_text_w = _tracked_len(label, chip_font, track)
    chip_cap = chip_font.getbbox("H", anchor="ls")
    chip_h = round((chip_cap[3] - chip_cap[1]) + 2 * 11)
    chip_w = round(chip_text_w + 2 * 15)
    lines = None
    font = None
    epx = 0
    for px in range(42, 29, -1):
        font = _font(px, "extrabold")
        epx = round(px * 1.05)
        avail = max_w - 2 * pad_x
        lines = _tc._wrap(words, font, epx, avail, 2)
        if lines is not None:
            break
    if lines is None:   # nao coube: corta no fim
        kept: list = []
        for w in words:
            if _tc._wrap(kept + [w], font, epx, max_w - 2 * pad_x, 2) is None:
                break
            kept.append(w)
        if kept:
            kept[-1] = _tc._Word(kept[-1].runs + [("t", "...")])
        lines = _tc._wrap(kept, font, epx, max_w - 2 * pad_x, 2) or []
    if not lines:
        return None
    px = font.size
    sp = font.getlength(" ")
    cap = font.getbbox("H", anchor="ls")
    cap_h = cap[3] - cap[1]
    line_h = round(px * 1.30)
    widths = [sum(w.width(font, epx) for w in ln) + sp * (len(ln) - 1) for ln in lines]
    gap_chip = 14
    inner_w = max(widths + [chip_w])
    card_w = round(inner_w + 2 * pad_x)
    card_h = round(pad_y + chip_h + gap_chip + line_h * len(lines) - (line_h - cap_h) * 0.35 + pad_y)
    radius = 26
    card = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((0, 0, card_w - 1, card_h - 1), radius=radius, fill=(14, 14, 20, 222),
                        outline=(255, 255, 255, 38), width=2)
    # etiqueta
    chip_fg = "#0B0B0F" if _luma(hi) > 0.55 else "#FFFFFF"
    d.rounded_rectangle((pad_x, pad_y, pad_x + chip_w, pad_y + chip_h), radius=chip_h / 2, fill=hi)
    _tracked(d, (pad_x + 15, pad_y + 11 + (chip_cap[3] - chip_cap[1])), label, chip_font, chip_fg, track)
    # texto
    y0 = pad_y + chip_h + gap_chip
    for i, ln in enumerate(lines):
        baseline = y0 + i * line_h + cap_h
        _tc._draw_line(card, pad_x, baseline, ln, font, epx, (255, 255, 255, 255), cap_h)
    img, m = _shadowed(card, radius)
    out_path = Path(out_path)
    img.save(out_path)
    return Overlay(out_path, img.width, img.height, pad_top=m, pad_bottom=m)


def render_cta_pill(text: str, out_path: Path, cfg=None, category: str | None = None, px: int = 44) -> Overlay | None:
    """Pilula na cor do nicho com texto branco (emoji colorido no fim, se houver)."""
    text = (text or "").strip()
    if not text:
        return None
    pal = _style.palette(category)
    bg = str(cfg.get("edicao.cta_cor", "") if cfg is not None else "") or pal["pill"][0]
    fg = str(cfg.get("edicao.cta_cor_texto", "") if cfg is not None else "") or pal["pill"][1]
    font = _font(px, "black")
    epx = round(px * 1.08)
    words = [_tc._Word(_tc.split_runs(w)) for w in text.split()]
    sp = font.getlength(" ")
    tw = sum(w.width(font, epx) for w in words) + sp * (len(words) - 1)
    cap = font.getbbox("H", anchor="ls")
    cap_h = cap[3] - cap[1]
    pad_x, pad_y = round(px * 0.70), round(px * 0.46)
    w, h = round(tw + 2 * pad_x), round(cap_h + 2 * pad_y)
    card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=h / 2, fill=bg)
    _tc._draw_line(card, pad_x, pad_y + cap_h, words, font, epx, fg, cap_h)
    img, m = _shadowed(card, h / 2, blur=12, offset=6, alpha=130, margin=24)
    out_path = Path(out_path)
    img.save(out_path)
    return Overlay(out_path, img.width, img.height, pad_top=m, pad_bottom=m)


# ================================================================== etiqueta de nome (lower third)
# Quem fala + onde: "DIA FREITAS" / "no Podpah". Estilo de TV/canal de cortes premium: Montserrat
# Black no nome, SemiBold no complemento, barra de destaque na cor da marca, entrada escalonada
# (barra -> nome -> complemento) em 300 ms e saida com fade + leve recuo em 220 ms.
NAME_STYLES = ("tarja", "classica", "pilula")

_NAME_STOP = {
    "a", "o", "as", "os", "um", "uma", "ele", "ela", "eles", "elas", "eu", "voce", "nos", "quando", "como",
    "porque", "por", "que", "se", "mas", "e", "nesse", "neste", "nessa", "esta", "este", "essa", "esse", "isso",
    "trecho", "episodio", "ep", "corte", "cortes", "parte", "video", "live", "podcast", "entrevista", "convidado",
    "convidada", "hoje", "aqui", "sobre", "fala", "conta", "contou", "revela", "ao", "vivo", "programa", "canal",
    "the", "and", "with", "feat", "ft", "part", "react", "reagindo", "assista", "veja", "novo", "nova", "melhores",
    "momentos", "historia", "historias", "polemica", "treta", "debate", "contexto", "brasil", "brasileiro",
}
_SHOWS = ["Podpah", "Flow Podcast", "Inteligência Ltda", "Ticaracaticast", "PodDelas", "Venus Podcast",
          "Mano a Mano", "Papagaio Falante", "Podcast 3 Irmãos", "Achismos", "Café com Ferri", "Prosa Guiada",
          "Sem Groselha", "Desinibidos", "Positivamente Podcast", "Pod Pai Pod Filho", "Mais que 8 Minutos"]


def _norm_ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def _is_cap_word(w: str) -> bool:
    w = w.strip(".,!?;:\"'()[]")
    return len(w) >= 2 and w[0].isupper() and all(c.isalpha() or c in "'-" for c in w)


def _clean_program(ch: str) -> str:
    ch = _clean(ch or "", False)
    ch = re.sub(r"\b(oficial|official|tv|channel|canal)\b", "", ch, flags=re.I)
    m = re.match(r"^\s*cortes?\s+(?:do|da|de|dos|das)\s+(.+)$", ch, flags=re.I)
    if m:
        ch = m.group(1)
    ch = re.sub(r"\s+cortes?\s*$", "", ch, flags=re.I)
    ch = re.sub(r"\s+", " ", ch).strip(" -|:")
    return ch if 2 <= len(ch) <= 28 else ""


def _program_from_text(texts: list[str]) -> str:
    for t in texts:
        for sh in _SHOWS:
            if _norm_ascii(sh) in _norm_ascii(t):
                return sh
    for t in texts:
        m = re.search(r"\b(?:no|na|do|da)\s+((?:[A-Z][\w'À-ÿ]+)(?:\s+(?:[A-Z][\w'À-ÿ]+|Podcast|Ltda\.?|Cast))*)", t or "")
        if m and _norm_ascii(m.group(1)) not in _NAME_STOP:
            return m.group(1).rstrip(".")
    return ""


def _person_from_title(title: str, program: str) -> str:
    """'DIA FREITAS - Podpah #1104' -> 'Dia Freitas'. So aceita pedaco curto com cara de nome."""
    t = _clean(title or "", False)
    parts = re.split(r"\s+[-|:]\s+|\s*\|\s*|#\d+|\s+(?:no|na)\s+(?=[A-Z])", t)
    best = ""
    for p in parts:
        p = re.sub(r"\(.*?\)|\[.*?\]", "", p).strip(" -|:,.!?")
        if not p or (program and _norm_ascii(program) in _norm_ascii(p)):
            continue
        words = p.split()
        if not 2 <= len(words) <= 4 or len(p) > 28:
            continue
        if any(_norm_ascii(w) in _NAME_STOP for w in words if len(w) > 2):
            continue
        if not all(_is_cap_word(w) or w.lower() in ("da", "de", "do", "dos", "das") for w in words):
            continue
        if any(ch.isdigit() for ch in p):
            continue
        best = p
        break
    return best


def _person_from_sentence(text: str, program: str) -> str:
    """'Dia Freitas fala da vida...' -> 'Dia Freitas'; '... com Mano Brown' -> 'Mano Brown'."""
    t = _clean(text or "", False)
    pats = [r"^((?:[A-ZÀ-Ý][\w'À-ÿ]+)(?:\s+(?:d[aeo]s?\s+)?[A-ZÀ-Ý][\w'À-ÿ]+){1,2})\b",
            r"\b(?:com|convidad[oa]|entrevista)\s+((?:[A-ZÀ-Ý][\w'À-ÿ]+)(?:\s+(?:d[aeo]s?\s+)?[A-ZÀ-Ý][\w'À-ÿ]+){1,2})\b"]
    for pat in pats:
        m = re.search(pat, t)
        if not m:
            continue
        cand = m.group(1).strip()
        words = cand.split()
        if any(_norm_ascii(w) in _NAME_STOP for w in words):
            continue
        if program and _norm_ascii(cand) == _norm_ascii(program):
            continue
        if program and _norm_ascii(program) in _norm_ascii(cand):
            continue
        return cand
    return ""


def name_tag_text(plan, cfg=None, video=None) -> tuple[str, str] | None:
    """(nome, complemento) da etiqueta: quem fala + onde. None = nao da para saber.

    Fontes, nesta ordem: edicao.etiqueta_nome_texto ("NOME | onde"), plan.context, titulo/canal do
    video (Candidate ou dict com title/channel/description), plan.description. Sem pessoa
    identificavel: so o programa/canal no nome. Nada identificavel: None (sem etiqueta).
    """
    override = str(cfg.get("edicao.etiqueta_nome_texto", "") if cfg is not None else "") or ""
    if override.strip():
        a, _sep, b = override.partition("|")
        a, b = _clean(a, False), _clean(b, False)
        return (a.upper()[:24], b[:30]) if a else None
    if plan is None and video is None:
        return None

    def vget(k):
        if video is None:
            return ""
        return str((video.get(k) if isinstance(video, dict) else getattr(video, k, "")) or "")

    context = str(getattr(plan, "context", "") or "")
    desc = str(getattr(plan, "description", "") or "")
    vtitle, vchan, vdesc = vget("title"), vget("channel"), vget("description")[:400]
    program = _clean_program(vchan) or _program_from_text([context, vtitle, desc, vdesc])
    person = (_person_from_sentence(context, program) or _person_from_title(vtitle, program)
              or _person_from_sentence(desc, program))
    if person and len(person) <= 24:
        sub = f"no {program}" if program else ""
        return person.upper(), sub
    if program:
        return program.upper(), ""
    return None


@dataclass
class NameTag:
    pattern: str            # padrao do ffmpeg (ex.: "etiqueta/n_%03d.png") relativo a pasta de trabalho
    frames: int
    w: int                  # tamanho do PNG
    h: int
    vis: tuple[int, int, int, int]   # (x0, y0, x1, y1) visivel dentro do PNG (sem sombra)
    style: str = "tarja"
    x: int = 0              # posicao do PNG no quadro
    y: int = 0

    def rect(self) -> tuple[float, float, float, float]:
        return (self.x + self.vis[0], self.y + self.vis[1], self.x + self.vis[2], self.y + self.vis[3])


def _ease_out(p: float) -> float:
    p = min(1.0, max(0.0, p))
    return 1 - (1 - p) ** 3


def _font_w(weight: str, px: int) -> ImageFont.FreeTypeFont:
    av = _fonts.ensure_fonts()
    key = {"black": "montserrat_black", "extrabold": "montserrat_extrabold",
           "semibold": "montserrat_semibold"}.get(weight, "montserrat_extrabold")
    p = av.get(key) or av.get("montserrat_extrabold") or av.get("montserrat_black")
    if p is None:
        path, _var = _fonts.title_font_path(heavy=True)
        return ImageFont.truetype(str(path), px) if path else ImageFont.load_default(px)
    return ImageFont.truetype(str(p), px)


def _cap_h(font) -> int:
    b = font.getbbox("H", anchor="ls")
    return b[3] - b[1]


def _plate(w: int, h: int, fill, radius: float, corners=(True, True, True, True)) -> Image.Image:
    im = Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=fill, corners=corners)
    return im


def _text_img(text: str, font, fill, tracking: float = 0.0, shadow: bool = False) -> tuple[Image.Image, int]:
    """Texto num PNG justo: largura = avanço; altura = cap height (centro optico). Devolve (img, cap)."""
    cap = _cap_h(font)
    tw = round(_tracked_len(text, font, tracking)) + 2
    desc = round(font.size * 0.3)
    im = Image.new("RGBA", (tw, cap + desc), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if tracking:
        _tracked(d, (0, cap), text, font, fill, tracking)
    else:
        d.text((0, cap), text, font=font, fill=fill, anchor="ls")
    return im, cap


def render_name_tag(name: str, sub: str, out_dir: Path, cfg=None, style: str = "tarja", fps: int = 30,
                    dur: float = 2.6, intro: float = 0.30, outro: float = 0.22) -> NameTag | None:
    """Gera a sequencia de PNGs da etiqueta (entrada + parada + saida). None se nao houver nome."""
    name = _style.sanitize_text(_style.strip_emojis(name or "")).strip()
    sub = _style.sanitize_text(_style.strip_emojis(sub or "")).strip()
    if not name:
        return None
    style = style if style in NAME_STYLES else "tarja"
    g = (lambda k, d: cfg.get(k, d)) if cfg is not None else (lambda k, d: d)
    red = str(g("edicao.etiqueta_cor", "") or _style.BRAND_RED)
    ink, white, yellow = _style.BRAND_INK, _style.BRAND_WHITE, _style.BRAND_YELLOW
    name_px = int(g("edicao.etiqueta_tamanho", 54) or 54)
    sub_px = max(24, round(name_px * 0.6))
    f_name = _font_w("black", name_px)
    f_sub = _font_w("semibold", sub_px)
    # nome encolhe se for comprido (largura maxima ~ 2/3 da tela, dentro da margem)
    max_w = int(g("edicao.etiqueta_largura_max", 760) or 760)
    track_n = round(name_px * 0.02, 1)
    while _tracked_len(name, f_name, track_n) > max_w - 64 and f_name.size > 34:
        f_name = _font_w("black", f_name.size - 2)
    n_img, n_cap = _text_img(name, f_name, white if style != "classica" else ink, track_n)
    s_img, s_cap = (_text_img(sub, f_sub, ink if style in ("tarja", "classica") else white)
                    if sub else (None, 0))
    R = _style.RADIUS_BOX
    bar_w = 10
    # caixas: texto centrado pela altura das maiusculas (padding vertical igual em cima e embaixo)
    pad_x = 28
    n_pad_y = round(name_px * 0.40)
    s_pad_y = round(sub_px * 0.42)
    n_w, n_h = n_img.width + 2 * pad_x, n_cap + 2 * n_pad_y
    s_w, s_h = ((s_img.width + 2 * pad_x, s_cap + 2 * s_pad_y) if s_img is not None else (0, 0))
    shadow_m = 28

    layers = []   # (img, x, y, t_ini, t_fim, modo) - modo: wipe | grow | fade
    if style in ("tarja", "classica"):
        n_fill = ink if style == "tarja" else white   # caixas opacas: a barra nao vaza por baixo
        s_fill = white if style == "tarja" else yellow
        total_h = n_h + s_h
        x0 = bar_w
        layers.append((_plate(bar_w + R, total_h, red, R, (True, False, False, True)), 0, 0, 0.0, 0.14, "grow"))
        plate_n = _plate(n_w, n_h, n_fill, R, (False, True, s_img is None, False))
        plate_n.alpha_composite(n_img, (pad_x, n_pad_y))
        layers.append((plate_n, x0, 0, 0.05, 0.27, "wipe"))
        if s_img is not None:
            plate_s = _plate(s_w, s_h, s_fill, R, (False, False, True, False))
            plate_s.alpha_composite(s_img, (pad_x, s_pad_y))   # mesma borda esquerda do nome
            layers.append((plate_s, x0, n_h, 0.11, 0.30, "wipe"))
        vis_w = max(x0 + n_w, x0 + s_w)
        vis_h = total_h
    else:   # pilula: capsula grafite com o nome + capsula vermelha com o complemento
        cap_pad = round(n_h / 2)
        name_cap = _plate(n_img.width + 2 * cap_pad, n_h, ink, n_h / 2)
        name_cap.alpha_composite(n_img, (cap_pad, n_pad_y))
        layers.append((name_cap, 0, 0, 0.0, 0.26, "wipe"))
        vis_w, vis_h = name_cap.width, n_h
        if s_img is not None:
            gap = 8
            pill = _plate(s_img.width + 2 * cap_pad, s_h, red, s_h / 2)
            pill.alpha_composite(s_img, (cap_pad, s_pad_y))   # texto alinhado ao do nome
            layers.append((pill, 0, n_h + gap, 0.08, 0.30, "wipe"))
            vis_w = max(vis_w, pill.width)
            vis_h = n_h + gap + s_h
    W_, H_ = vis_w + 2 * shadow_m + 24, vis_h + 2 * shadow_m
    ox, oy = shadow_m, shadow_m

    def compose(t: float, alpha: float = 1.0, dx: float = 0.0) -> Image.Image:
        base = Image.new("RGBA", (W_, H_), (0, 0, 0, 0))
        content = Image.new("RGBA", (W_, H_), (0, 0, 0, 0))
        for img, lx, ly, a, b, mode in layers:
            p = _ease_out((t - a) / max(1e-3, b - a))
            if p <= 0:
                continue
            if mode == "wipe":
                cw = max(1, round(img.width * p))
                content.alpha_composite(img.crop((0, 0, cw, img.height)), (round(ox + lx + dx), oy + ly))
            elif mode == "grow":
                ch = max(1, round(img.height * p))
                y_off = (img.height - ch) // 2
                content.alpha_composite(img.crop((0, y_off, img.width, y_off + ch)), (round(ox + lx + dx), oy + ly + y_off))
            else:
                im2 = img.copy()
                im2.putalpha(im2.getchannel("A").point(lambda v, _p=p: int(v * _p)))
                content.alpha_composite(im2, (round(ox + lx + dx - 16 * (1 - p)), oy + ly))
        # sombra suave do conjunto
        sh = Image.new("RGBA", (W_, H_), (0, 0, 0, 0))
        sh.putalpha(content.getchannel("A").point(lambda v: int(v * 0.42)))
        sh = sh.filter(ImageFilter.GaussianBlur(10))
        base.alpha_composite(sh, (0, 5))
        base.alpha_composite(content)
        if alpha < 0.999:
            base.putalpha(base.getchannel("A").point(lambda v, _a=alpha: int(v * _a)))
        return base

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    n = max(2, int(round(dur * fps)))
    n_in, n_out = int(round(intro * fps)), int(round(outro * fps))
    still = compose(10.0)
    for k in range(n):
        t = k / fps
        if k < n_in:
            im = compose(t)
        elif k >= n - n_out:
            q = _ease_out((k - (n - n_out) + 1) / max(1, n_out))
            im = compose(10.0, alpha=1 - q, dx=-24 * q)
        else:
            im = still
        im.save(out_dir / f"n_{k:03d}.png", compress_level=2)
    return NameTag(f"{out_dir.name}/n_%03d.png", n, W_, H_, (ox, oy, ox + vis_w, oy + vis_h), style)


# ================================================================== marca: logo + @ da rede
@dataclass
class Brand:
    logo: Path | None                  # PNG da logo ja reduzida e com opacidade
    logo_wh: tuple[int, int]
    handles: dict[str, tuple[Path, int, int, int]]   # rede -> (png, w, h, cap) do @
    text_wh: tuple[int, int] = (0, 0)  # reserva em texto (sem logo)
    gap: int = 8
    size: str = "normal"               # normal | compacto (80%, so quando o rosto nao deixa espaco)

    def block(self, arrangement: str) -> tuple[int, int]:
        """(largura, altura) do conjunto: pilha (logo em cima do @) ou linha (@ ao lado da logo)."""
        lw, lh = self.logo_wh
        hw = max([w for _p, w, _h, _c in self.handles.values()] + [0])
        hh = max([h for _p, _w, h, _c in self.handles.values()] + [0])
        if not self.handles:
            return lw, lh
        if arrangement == "linha":
            return lw + self.gap * 2 + hw, max(lh, hh)
        return max(lw, hw), lh + self.gap + hh


MINI_LOGO_H = 46      # marca pequena na linha da pilula PARTE (so quando o rosto nao deixa canto livre)


def render_brand(cfg, work: Path, platforms: list[str], scale: float = 1.0, mini: bool = False) -> Brand | None:
    """Logo (edicao.logo_marca_dagua, ~160 px, 85%) + rotulo do @ de cada rede (SemiBold 32, branco
    com sombra suave). Sem logo: texto edicao.marca_dagua. Sem nada: None."""
    from .. import paths as _paths

    g = (lambda k, d: cfg.get(k, d)) if cfg is not None else (lambda k, d: d)
    work = Path(work)
    logo_cfg = str(g("edicao.logo_marca_dagua", "") or "")
    logo_w = round(int(g("edicao.logo_largura", 160) or 160) * scale)
    sfx = "_m" if mini else ("" if abs(scale - 1.0) < 1e-6 else "_c")
    opacity = float(g("edicao.logo_opacidade", 0.85) or 0.85)
    logo_path, logo_wh = None, (0, 0)
    if logo_cfg:
        lp = Path(logo_cfg)
        if not lp.is_absolute():
            lp = _paths.ROOT / lp if hasattr(_paths, "ROOT") else Path.cwd() / lp
        if lp.exists():
            try:
                im = Image.open(lp).convert("RGBA")
                bb = im.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()
                if bb:
                    im = im.crop(bb)
                if mini:
                    logo_w = round(im.width * MINI_LOGO_H / im.height)
                h = round(im.height * logo_w / im.width)
                im = im.resize((logo_w, h), Image.LANCZOS)
                im.putalpha(im.getchannel("A").point(lambda v: int(v * opacity)))
                logo_path = work / f"logo{sfx}.png"
                im.save(logo_path)
                logo_wh = (logo_w, h)
            except Exception:  # noqa: BLE001
                logo_path = None
    handles: dict[str, tuple[Path, int, int, int]] = {}
    if g("edicao.marca_dagua_arroba", True):
        px = 26 if mini else round(int(g("edicao.arroba_tamanho", 32) or 32) * scale)
        f = _font_w("semibold", px)
        for plat in platforms:
            hd = str(g(f"publicacao.contas.{plat}.handle", "") or "").strip()
            if not hd:
                continue
            if not hd.startswith("@"):
                hd = "@" + hd
            hd = _style.sanitize_text(_style.strip_emojis(hd))
            txt, cap = _text_img(hd, f, (255, 255, 255, 240))
            m = 10
            im = Image.new("RGBA", (txt.width + 2 * m, txt.height + 2 * m), (0, 0, 0, 0))
            sha = Image.new("RGBA", im.size, (0, 0, 0, 0))
            sha.alpha_composite(txt, (m, m + 2))
            sha.putalpha(sha.getchannel("A").point(lambda v: int(v * 0.75)))
            black = Image.new("RGBA", im.size, (0, 0, 0, 0))
            black.putalpha(sha.getchannel("A"))
            im.alpha_composite(black.filter(ImageFilter.GaussianBlur(4)))
            im.alpha_composite(txt, (m, m))
            pth = work / f"arroba_{plat}{sfx}.png"
            im.save(pth)
            handles[plat] = (pth, im.width, im.height, cap)
    if logo_path is None:
        wm = _style.sanitize_text(_style.strip_emojis(str(g("edicao.marca_dagua", "") or ""))).strip()
        if not wm and not handles:
            return None
        if wm:
            f = _font_w("extrabold", 40)
            txt, _cap = _text_img(wm.upper(), f, (255, 255, 255, 200), 1.5)
            logo_path = work / f"marca_texto{sfx}.png"
            txt.save(logo_path)
            logo_wh = (txt.width, txt.height)
    return Brand(logo_path, logo_wh, handles, size={"": "normal", "_c": "compacto", "_m": "mini"}[sfx])
