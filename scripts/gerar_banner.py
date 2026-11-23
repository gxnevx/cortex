"""Gera docs/cortex_banner.png: o banner ASCII do terminal, com degrade, para o README."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fabrica import ui  # noqa: E402

FONT_CANDIDATES = ["CascadiaMono.ttf", "CascadiaCode.ttf", "consola.ttf", "cour.ttf"]


def font(px: int) -> ImageFont.FreeTypeFont:
    for f in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(f, px)
        except OSError:
            continue
    raise SystemExit("nenhuma fonte monoespacada encontrada")


def main() -> None:
    px = 34
    f = font(px)
    cw = f.getlength("M")                      # largura fixa de cada caractere
    lh = int(px * 1.12)
    banner, side = ui._BANNER, ui._SIDE
    cols = max(len(b) for b in banner) + 3 + max(len(s) for s in side)
    W, H = int(cw * (cols + 6)), lh * (len(banner) + 6)
    img = Image.new("RGB", (W, H), (11, 11, 15))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([10, 10, W - 10, H - 10], 28, outline=(38, 42, 56), width=3)
    x0, y0 = cw * 3, lh * 2

    def draw_line(text, x, y, color_fn):
        for i, ch in enumerate(text):
            if ch == "█":  # retangulo exato: sem emendas entre as celulas
                d.rectangle([x + i * cw, y, x + (i + 1) * cw, y + lh], fill=color_fn(i, len(text)))
            elif ch != " ":
                d.text((x + i * cw, y), ch, font=f, fill=color_fn(i, len(text)))

    for r, line in enumerate(banner):
        shift = r / (len(banner) - 1) * 0.35
        draw_line(line, x0, y0 + r * lh,
                  lambda i, n, s=shift: ui._lerp_hex(ui.C_RED, ui.C_CYAN, min(1.0, i / max(1, n - 1) * 0.65 + s)))
    side_x = x0 + cw * (max(len(b) for b in banner) + 3)
    for r, line in enumerate(side):
        draw_line(line, side_x, y0 + r * lh,
                  lambda i, n: ui.C_YEL if line[i] in "✂>8<" else ("#FE2C55" if line[i] == "▓" else "#7A7F8C"))
    y = y0 + lh * len(banner) + int(lh * 0.6)
    tag = "Central Operacional de Recortes, Tendências e EXposição"
    d.text((x0, y), tag, font=f, fill="#8B95A7")
    d.text((x0, y + int(lh * 1.3)), "descobre / corta / edita / publica", font=f, fill="#FFE600")
    out = ROOT / "docs" / "cortex_banner.png"
    img.save(out)
    print("ok", out, img.size)


if __name__ == "__main__":
    main()
