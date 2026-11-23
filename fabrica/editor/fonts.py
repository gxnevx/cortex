"""Fontes usadas nas legendas (libass) e no titulo (Pillow).

Baixa fontes livres (OFL) para assets/fonts na primeira vez:
  - Montserrat Black / ExtraBold (estaticas, do repositorio oficial da Montserrat;
    o google/fonts so tem a versao variavel, que o libass nao sabe usar no peso Black)
  - Montserrat variavel (google/fonts) - usada pelo Pillow se as estaticas faltarem
  - Anton, Bebas Neue (google/fonts)
Sem internet: cai para Impact / Arial Black do Windows.
"""
from __future__ import annotations

import functools
import struct
import threading
from pathlib import Path

from .. import paths
from ..log import get as get_log

_log = get_log(__name__)

_GF = "https://raw.githubusercontent.com/google/fonts/main/ofl"
_MONT = "https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf"

# chave -> (arquivo local, [urls], familia esperada pelo libass)
FONT_SPECS: dict[str, tuple[str, list[str], str]] = {
    "montserrat_black": ("Montserrat-Black.ttf",
                         [f"{_MONT}/Montserrat-Black.ttf"], "Montserrat Black"),
    "montserrat_extrabold": ("Montserrat-ExtraBold.ttf",
                             [f"{_MONT}/Montserrat-ExtraBold.ttf"], "Montserrat ExtraBold"),
    "montserrat_semibold": ("Montserrat-SemiBold.ttf",
                            [f"{_MONT}/Montserrat-SemiBold.ttf"], "Montserrat SemiBold"),
    "montserrat_var": ("Montserrat-VF.ttf",
                       [f"{_GF}/montserrat/Montserrat%5Bwght%5D.ttf"], "Montserrat"),
    "anton": ("Anton-Regular.ttf", [f"{_GF}/anton/Anton-Regular.ttf"], "Anton"),
    "bebas": ("BebasNeue-Regular.ttf", [f"{_GF}/bebasneue/BebasNeue-Regular.ttf"], "Bebas Neue"),
}
_LICENSES = {
    "OFL-Montserrat.txt": f"{_GF}/montserrat/OFL.txt",
    "OFL-Anton.txt": f"{_GF}/anton/OFL.txt",
    "OFL-BebasNeue.txt": f"{_GF}/bebasneue/OFL.txt",
}

WIN_FONTS = Path(r"C:\Windows\Fonts")
WINDOWS_FALLBACK: dict[str, tuple[str, str]] = {
    "impact": ("impact.ttf", "Impact"),
    "arial_black": ("ariblk.ttf", "Arial Black"),
    "segoe_bold": ("segoeuib.ttf", "Segoe UI"),
    "emoji": ("seguiemj.ttf", "Segoe UI Emoji"),
}

# apelidos aceitos em edicao.legenda.fonte
ALIASES = {
    "montserrat": "montserrat_black", "montserrat black": "montserrat_black",
    "montserrat extrabold": "montserrat_extrabold", "anton": "anton",
    "bebas": "bebas", "bebas neue": "bebas", "impact": "impact",
    "arial black": "arial_black",
}

_lock = threading.Lock()


def _download(url: str, dest: Path, min_size: int = 1000) -> bool:
    import requests

    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        r = requests.get(url, timeout=60, headers={"User-Agent": "fabrica-de-cortes/1.0"})
        r.raise_for_status()
        data = r.content
        if len(data) < min_size:
            raise ValueError(f"arquivo pequeno demais ({len(data)} bytes)")
        if dest.suffix.lower() == ".ttf" and data[:4] not in (b"\x00\x01\x00\x00", b"true", b"OTTO"):
            raise ValueError("nao parece uma fonte TTF")
        tmp.write_bytes(data)
        tmp.replace(dest)
        return True
    except Exception as e:  # noqa: BLE001
        _log.warning("Nao consegui baixar %s: %s", url, e)
        tmp.unlink(missing_ok=True)
        return False


def ensure_fonts(download: bool = True) -> dict[str, Path]:
    """Garante as fontes em assets/fonts. Devolve {chave: caminho} das disponiveis
    (inclui as do Windows usadas como reserva)."""
    with _lock:
        return _ensure_fonts(download)


@functools.lru_cache(maxsize=2)
def _ensure_fonts(download: bool) -> dict[str, Path]:
    paths.FONTS.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    for key, (fname, urls, _fam) in FONT_SPECS.items():
        dest = paths.FONTS / fname
        # a variavel so e necessaria se a Montserrat estatica nao veio
        if key == "montserrat_var" and "montserrat_black" in out:
            continue
        if not dest.exists() and download:
            for u in urls:
                if _download(u, dest):
                    _log.info("Fonte baixada: %s", fname)
                    break
        if dest.exists():
            out[key] = dest
    if download:
        lic_dir = paths.FONTS / "licencas"
        for fname, url in _LICENSES.items():
            if not (lic_dir / fname).exists():
                lic_dir.mkdir(exist_ok=True)
                _download(url, lic_dir / fname, min_size=200)
    for key, (fname, _fam) in WINDOWS_FALLBACK.items():
        p = WIN_FONTS / fname
        if p.exists():
            out[key] = p
    return out


def font_names(path: Path) -> dict[int, str]:
    """Le a tabela 'name' de um TTF (familia=1, subfamilia=2, nome completo=4, tipografica=16)."""
    data = Path(path).read_bytes()
    num_tables = struct.unpack(">H", data[4:6])[0]
    names: dict[int, str] = {}
    for i in range(num_tables):
        rec = data[12 + 16 * i: 28 + 16 * i]
        tag, _cs, off, _ln = struct.unpack(">4sIII", rec)
        if tag != b"name":
            continue
        _fmt, count, str_off = struct.unpack(">HHH", data[off:off + 6])
        for j in range(count):
            pid, eid, lid, nid, ln, so = struct.unpack(">HHHHHH", data[off + 6 + 12 * j: off + 18 + 12 * j])
            raw = data[off + str_off + so: off + str_off + so + ln]
            if pid == 3 and lid in (0x409, 0) and nid not in names:
                names[nid] = raw.decode("utf-16-be", "replace")
            elif pid == 1 and nid not in names:
                names[nid] = raw.decode("latin-1", "replace")
        break
    return names


def caption_font(cfg=None) -> tuple[str, Path | None]:
    """(familia para o ASS, arquivo) conforme edicao.legenda.fonte."""
    fonts = ensure_fonts()
    want = str(cfg.get("edicao.legenda.fonte", "auto") if cfg is not None else "auto").strip().lower()
    order = ["montserrat_black", "anton", "impact", "arial_black"]
    if want and want != "auto":
        key = ALIASES.get(want, want)
        if key in fonts:
            order.insert(0, key)
        else:
            # nome de familia qualquer instalado no Windows: o libass acha sozinho
            return cfg.get("edicao.legenda.fonte"), None
    for key in order:
        if key in fonts:
            fam = FONT_SPECS[key][2] if key in FONT_SPECS else WINDOWS_FALLBACK[key][1]
            return fam, fonts[key]
    return "Arial", None


def title_font_path(heavy: bool = True) -> tuple[Path | None, str | None]:
    """Fonte do titulo (Pillow). Devolve (arquivo, variacao) - variacao para a fonte variavel."""
    fonts = ensure_fonts()
    for key in (("montserrat_black", "montserrat_extrabold") if heavy else ("montserrat_extrabold", "montserrat_black")):
        if key in fonts:
            return fonts[key], None
    if "montserrat_var" in fonts:
        return fonts["montserrat_var"], "Black" if heavy else "ExtraBold"
    for key in ("arial_black", "impact", "segoe_bold"):
        if key in fonts:
            return fonts[key], None
    return None, None


def emoji_font_path() -> Path | None:
    return ensure_fonts().get("emoji")
