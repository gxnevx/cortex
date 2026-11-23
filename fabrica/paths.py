"""Caminhos do projeto. Tudo e relativo a pasta raiz (onde fica fabrica.bat)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Dados persistentes (banco, perfil do navegador, cookies, modelos)
DATA = ROOT / "data"
DB_PATH = DATA / "fabrica.db"
BROWSER_PROFILE = DATA / "navegador"
COOKIES_TXT = DATA / "cookies.txt"
MODELS = DATA / "modelos"          # cache dos modelos do Whisper
STATE = DATA / "estado"            # arquivos de estado diversos (cache do cerebro etc.)

# Area de trabalho (pode ser apagada a qualquer momento)
WORK = ROOT / "work"
DOWNLOADS = WORK / "downloads"
TRANSCRIPTS = WORK / "transcricoes"
RENDERS = WORK / "renders"
TMP = WORK / "tmp"

# Recursos visuais
ASSETS = ROOT / "assets"
FONTS = ASSETS / "fonts"
BACKGROUNDS = ASSETS / "fundos"
MUSIC = ASSETS / "musicas"

# Saidas para o usuario
REPORTS = ROOT / "relatorios"
LOGS = ROOT / "logs"
SCREENSHOTS = LOGS / "screenshots"

CONFIG_PATH = ROOT / "config.yaml"
CONFIG_EXAMPLE_PATH = ROOT / "config.exemplo.yaml"

_ALL_DIRS = [
    DATA, BROWSER_PROFILE, MODELS, STATE,
    WORK, DOWNLOADS, TRANSCRIPTS, RENDERS, TMP,
    ASSETS, FONTS, BACKGROUNDS, MUSIC,
    REPORTS, LOGS, SCREENSHOTS,
]


def ensure_dirs() -> None:
    for d in _ALL_DIRS:
        d.mkdir(parents=True, exist_ok=True)
    for cat in ("gameplay", "satisfying", "asmr", "procedural"):
        (BACKGROUNDS / cat).mkdir(parents=True, exist_ok=True)


def run_dir(run_id: str) -> Path:
    """Pasta de trabalho de uma execucao."""
    p = WORK / "execucoes" / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p
