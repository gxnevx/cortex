"""Paletas por nicho, grade de alinhamento, variantes do titulo e regras de conteudo do editor."""
from __future__ import annotations

import hashlib
import re
import unicodedata

# ------------------------------------------------------------------ grade (1080x1920)
# Tudo que e desenhado segue esta grade: elementos centralizados no eixo x=540 ou alinhados a
# margem lateral de 64 px; espacamentos da escala de 8/16 px; nenhum elemento encosta em outro.
W, H = 1080, 1920
MARGIN = 64              # margem lateral segura
SPACE = 16               # unidade da escala de espacamento
GAP = 24                 # espaco minimo entre dois elementos (1,5 unidade)
SAFE_TOP = 150           # abas/busca do TikTok e do Shorts
SAFE_BOTTOM_Y = 1540     # abaixo disso: @, legenda do post e musica
RAIL = (940, 1000, 1080, 1600)   # coluna de botoes a direita (curtir, comentar...)
RADIUS_BOX = 20          # raio de todas as caixas retangulares (titulo, etiqueta de nome)
# cores da marca
BRAND_RED = "#FE2C55"
BRAND_YELLOW = "#FFE600"
BRAND_WHITE = "#FFFFFF"
BRAND_INK = "#111114"


def snap(v: float, unit: int = 8) -> int:
    """Arredonda para a grade de 8 px."""
    return int(round(v / unit) * unit)

# nicho -> destaque da legenda, caixa do titulo (fundo, texto), pilula PARTE (fundo, texto)
PALETTES: dict[str, dict] = {
    "politica":     {"hi": "#00E5FF", "card": ("#FFFFFF", "#000000"), "pill": ("#1F2937", "#FFFFFF")},
    "polemica":     {"hi": "#FF3B30", "card": ("#111111", "#FFFFFF"), "pill": ("#FF3B30", "#FFFFFF")},
    "humor":        {"hi": "#FFE600", "card": ("#FFFFFF", "#000000"), "pill": ("#FF2D55", "#FFFFFF")},
    "games":        {"hi": "#39FF88", "card": ("#0B0B0F", "#FFFFFF"), "pill": ("#7C3AED", "#FFFFFF")},
    "esportes":     {"hi": "#C6FF00", "card": ("#FFFFFF", "#000000"), "pill": ("#111111", "#C6FF00")},
    "podcast":      {"hi": "#FFD166", "card": ("#FFFFFF", "#000000"), "pill": ("#FF2D55", "#FFFFFF")},
    "celebridades": {"hi": "#FF4FD8", "card": ("#FFFFFF", "#000000"), "pill": ("#FF4FD8", "#FFFFFF")},
    "noticias":     {"hi": "#FF453A", "card": ("#FFFFFF", "#000000"), "pill": ("#1F2937", "#FFFFFF")},
    "padrao":       {"hi": "#FFE600", "card": ("#FFFFFF", "#000000"), "pill": ("#FF2D55", "#FFFFFF")},
}
SYNONYMS = {
    "treta": "polemica", "fofoca": "celebridades", "reality": "celebridades", "famosos": "celebridades",
    "futebol": "esportes", "esporte": "esportes", "game": "games", "jogos": "games", "gameplay": "games",
    "esports": "games", "noticia": "noticias", "jornalismo": "noticias", "entrevista": "podcast",
    "storytime": "podcast", "comedia": "humor", "entretenimento": "humor", "react": "humor",
}

_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002300-\U000023FF\U00002B00-\U00002BFF"
    "\U0001F1E6-\U0001F1FF\U0000FE00-\U0000FE0F\U0000200D\U000020E3\U000E0020-\U000E007F"
    "\U00003030\U0000303D\U00003297\U00003299\U000024C2\U00002194-\U000021AA\U000025AA-\U000025FE"
    "\U00002934\U00002935\U0000203C\U00002049\U00002122\U00002139]+"
)


def niche_key(category: str | None) -> str:
    if not category:
        return "padrao"
    k = unicodedata.normalize("NFKD", str(category)).encode("ascii", "ignore").decode().lower().strip()
    k = SYNONYMS.get(k, k)
    return k if k in PALETTES else "padrao"


def palette(category: str | None) -> dict:
    return PALETTES[niche_key(category)]


def highlight_color(cfg, category: str | None) -> str:
    v = cfg.get("edicao.legenda.cor_destaque", "auto") if cfg is not None else "auto"
    if not v or str(v).strip().lower() == "auto":
        return palette(category)["hi"]
    return str(v)


def emojis_enabled(cfg) -> bool:
    """Emojis coloridos no video (titulo). Padrao: ligado. Nunca vao para log/terminal."""
    return bool(cfg.get("conteudo.emojis", True)) if cfg is not None else True


def strip_emojis(text: str) -> str:
    t = _EMOJI_RE.sub(" ", text or "")
    return re.sub(r"\s{2,}", " ", t).strip()


def stable_pick(seed: str, options: list[tuple[str, float]]) -> str:
    """Escolha ponderada deterministica (mesmo corte -> mesma escolha)."""
    total = sum(w for _, w in options)
    h = int(hashlib.sha1((seed or "x").encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF * total
    acc = 0.0
    for name, w in options:
        acc += w
        if h <= acc:
            return name
    return options[-1][0]


# palavroes: mascara a vogal do meio na legenda ("P*RRA"); o audio fica
_PROFANITY = ["caralho", "porra", "merda", "foda", "fodase", "foda-se", "foder", "fodido", "fodida", "puta",
              "cu", "puto", "putaria", "buceta", "cacete", "arrombado", "arrombada", "bosta", "viado", "piroca"]


def mask_profanity(word: str) -> str:
    base = unicodedata.normalize("NFKD", word).encode("ascii", "ignore").decode().lower()
    core = re.sub(r"[^a-z\-]", "", base)
    if core not in _PROFANITY:
        return word
    chars = list(word)
    vowels = [i for i, c in enumerate(chars) if i > 0 and c.lower() in "aeiouáéíóúâêôãõ"]
    if vowels:
        chars[vowels[0]] = "*"
    return "".join(chars)


# caracteres proibidos pelo dono em qualquer texto renderizado (travessoes e pontos medios)
_FORBIDDEN = {chr(c): "-" for c in (0x2012, 0x2013, 0x2014, 0x2015)}
_FORBIDDEN.update({chr(c): "|" for c in (0x2022, 0x00B7, 0x2027, 0x2219, 0x22C5)})
_FORBIDDEN_RE = re.compile("[" + "".join(_FORBIDDEN) + "]")


def sanitize_text(text: str) -> str:
    """Troca travessoes por '-' e pontos medios/bolinhas por '|'."""
    return _FORBIDDEN_RE.sub(lambda m: _FORBIDDEN[m.group(0)], text or "")
