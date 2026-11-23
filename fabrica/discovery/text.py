"""Utilitarios de texto da descoberta: normalizacao, similaridade, idioma e numeros em pt-BR."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# Palavras vazias (pt + algumas en/es) ignoradas na comparacao de assuntos
STOP = set("""
a o as os um uma uns umas de do da dos das no na nos nas em ao aos à às e ou que se por para pra pro com sem
sobre entre ate até apos após como mais menos muito muita muitos muitas ja já nao não sim seu sua seus suas
ele ela eles elas eu voce você voces vocês isso isto esse essa este esta esses essas aquele aquela the of and
to in on for at is are was be by an vs x é foi ser ter tem diz dizem apos hoje ontem agora vai vao vão
el la los las del y con por para un una es
""".split())

# Marcadores para adivinhar idioma de um titulo
_PT_MARKERS = set("""
de do da dos das que não nao é com para pra uma um os as no na nos nas ao aos mais muito você voce
ele ela isso esse essa este esta vai tem foi são sao está esta ficou porque quando sobre ate até
""".split())
_ES_MARKERS = set("el los las del y es con por una muy pero cuando sobre qué que está esto esta este hasta".split())
_EN_MARKERS = set("the and of to is are was with for this that you what how why when in on my your".split())
_PT_CHARS = re.compile(r"[ãõçâêô]")
_ES_CHARS = re.compile(r"[ñ¿¡]")


def strip_accents(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(ch))


def split_hashtag(tag: str) -> str:
    """#ProvaDeFogo -> 'Prova De Fogo'; #bbb26 -> 'bbb26'."""
    t = tag.lstrip("#@")
    if t.isupper() or t.islower():
        return t.replace("_", " ")
    t = re.sub(r"(?<=[a-zà-ÿ])(?=[A-ZÀ-Þ])", " ", t)
    t = re.sub(r"(?<=[A-Za-zÀ-ÿ])(?=\d)", " ", t)
    return t.replace("_", " ")


def clean_topic(s: str) -> str:
    """Deixa um assunto legivel (expande hashtag, tira espacos repetidos)."""
    s = (s or "").strip()
    if s.startswith("#"):
        s = split_hashtag(s)
    return re.sub(r"\s+", " ", s).strip()


def norm(s: str) -> str:
    """minusculas, sem acento, sem pontuacao."""
    s = clean_topic(s)
    s = strip_accents(s).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(s: str, drop_stop: bool = True, min_len: int = 2) -> list[str]:
    out = []
    stop_n = _STOP_N
    for t in norm(s).split():
        if len(t) < min_len:
            continue
        if drop_stop and t in stop_n:
            continue
        out.append(t)
    return out


_STOP_N = {strip_accents(w) for w in STOP}


def similarity(a: str, b: str) -> float:
    """0-1: mistura de razao de sequencia e sobreposicao de palavras."""
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    seq = SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(tokens(a)), set(tokens(b))
    if not ta or not tb:
        return seq
    inter = len(ta & tb)
    jac = inter / len(ta | tb)
    contain = inter / min(len(ta), len(tb))
    # "contido" so vale quando o menor tem pelo menos 2 palavras relevantes
    if min(len(ta), len(tb)) < 2:
        contain = contain * 0.7
    return max(seq, jac, contain * 0.9)


def contains_topic(text: str, topic: str) -> bool:
    """True se todas as palavras relevantes do assunto aparecem no texto (ou a frase inteira)."""
    nt = norm(topic)
    if not nt:
        return False
    ntext = " " + norm(text) + " "
    if f" {nt} " in ntext:
        return True
    tt = tokens(topic)
    if len(tt) < 2 and (not tt or len(tt[0]) < 5):
        return False
    return all(f" {t} " in ntext for t in tt)


def match_score(text: str, topic: str) -> float:
    """0-1: quanto um titulo bate com um assunto/palavra-chave."""
    if not text or not topic:
        return 0.0
    if contains_topic(text, topic):
        return 1.0
    tt = set(tokens(topic))
    if not tt:
        return 0.0
    tx = set(tokens(text))
    hit = len(tt & tx)
    # casamento parcial por prefixo (ex.: "bolsonaro" x "bolsonarista")
    if hit < len(tt) and len(tt) >= 2:
        for t in tt - tx:
            if len(t) >= 7 and any(len(w) >= 7 and w.startswith(t[:6]) for w in tx):
                hit += 0.4
    return min(1.0, hit / len(tt))


def pt_score(text: str) -> float:
    """-1 (com certeza nao e portugues) .. +1 (com certeza portugues). 0 = nao sei."""
    if not text:
        return 0.0
    low = text.lower()
    words = re.findall(r"[a-zà-ÿ]+", low)
    if not words:
        return 0.0
    pt = sum(1 for w in words if w in _PT_MARKERS) + 1.5 * len(_PT_CHARS.findall(low))
    es = sum(1 for w in words if w in _ES_MARKERS) + 2.0 * len(_ES_CHARS.findall(low))
    en = sum(1 for w in words if w in _EN_MARKERS)
    # palavras ambiguas pt/es ("de", "que", "con") pesam nos dois
    total = pt + es + en
    if total < 1:
        return 0.0
    return max(-1.0, min(1.0, (pt - max(es, en)) / total))


def detect_lang(text: str) -> str | None:
    """'pt' | 'en' | 'es' pelo texto (titulo/descricao), ou None se nao der para saber."""
    if not text:
        return None
    low = text.lower()
    words = re.findall(r"[a-zà-ÿ]+", low)
    if not words:
        return None
    pt = sum(1 for w in words if w in _PT_MARKERS) + 1.5 * len(_PT_CHARS.findall(low))
    es = sum(1 for w in words if w in _ES_MARKERS) + 2.0 * len(_ES_CHARS.findall(low))
    en = sum(1 for w in words if w in _EN_MARKERS)
    scores = sorted((("pt", pt), ("es", es), ("en", en)), key=lambda x: -x[1])
    (best, b1), (_, b2) = scores[0], scores[1]
    if b1 < 1.5 or b1 < 1.4 * b2:
        return None
    return best


def lang_code(lang: str | None) -> str | None:
    """'pt-BR' -> 'pt', 'en-US' -> 'en'."""
    if not lang:
        return None
    return str(lang).split("-")[0].split("_")[0].lower()[:3] or None


# ------------------------------------------------------------------ numeros e tempos (pt/en)
_MULT = {
    "mil": 1e3, "k": 1e3, "mi": 1e6, "m": 1e6, "mi.": 1e6, "milhao": 1e6, "milhoes": 1e6,
    "bi": 1e9, "b": 1e9, "bilhao": 1e9, "bilhoes": 1e9,
}


def parse_count(text: str | None) -> int | None:
    """'1.778.168 visualizacoes' -> 1778168; '116 mil' -> 116000; '1,2 mi' -> 1200000; '25K' -> 25000."""
    if not text:
        return None
    t = strip_accents(str(text)).lower().replace("\xa0", " ").strip()
    if re.search(r"\b(nenhuma|no views|sem visualiza)", t):
        return 0
    m = re.search(r"(\d[\d.,\s]*)\s*(mil|mi\.?|milhoes|milhao|bi|bilhoes|bilhao|k|m|b)?\b", t)
    if not m:
        return None
    num, mult = m.group(1).strip(), m.group(2)
    num = num.replace(" ", "")
    if mult:
        # decimal com virgula (pt) ou ponto (en)
        num = num.replace(",", ".")
        if num.count(".") > 1:
            num = num.replace(".", "", num.count(".") - 1)
        try:
            return int(float(num) * _MULT.get(mult, 1))
        except ValueError:
            return None
    digits = re.sub(r"[.,]", "", num)
    return int(digits) if digits.isdigit() else None


_UNITS = {
    "segundo": 1, "second": 1, "seg": 1, "minuto": 60, "minute": 60, "min": 60, "hora": 3600, "hour": 3600,
    "dia": 86400, "day": 86400, "semana": 604800, "week": 604800, "mes": 2592000, "meses": 2592000,
    "month": 2592000, "ano": 31536000, "year": 31536000,
}


def parse_age(text: str | None) -> float | None:
    """'ha 3 horas' / 'Transmitido ha 2 dias' / '5 hours ago' -> segundos desde a publicacao."""
    if not text:
        return None
    t = strip_accents(str(text)).lower()
    m = re.search(r"(\d+)\s*(segundos?|minutos?|horas?|dias?|semanas?|mes(?:es)?|anos?|seconds?|minutes?|hours?"
                  r"|days?|weeks?|months?|years?)", t)
    if not m:
        # abreviado: "ha 17 h", "ha 30 min", "ha 2 d", "3 sem."
        m2 = re.search(r"(\d+)\s*(h|hr|hrs|min|mins|d|sem|s)\b", t)
        if not m2:
            return None
        n = int(m2.group(1))
        return float(n * {"h": 3600, "hr": 3600, "hrs": 3600, "min": 60, "mins": 60, "d": 86400,
                          "sem": 604800, "s": 1}[m2.group(2)])
    n = int(m.group(1))
    unit = m.group(2)
    for k, v in _UNITS.items():
        if unit.startswith(k):
            return float(n * v)
    return None


def parse_clock(text: str | None) -> float | None:
    """'1:23:16' -> 4996.0"""
    if not text:
        return None
    m = re.search(r"(\d+(?::\d{1,2}){1,2})", str(text))
    if not m:
        return None
    sec = 0
    for part in m.group(1).split(":"):
        sec = sec * 60 + int(part)
    return float(sec)


def short_query(headline: str, max_words: int = 7) -> str:
    """Manchete longa -> consulta curta para busca de video."""
    h = re.sub(r"\s+[-|\u2013\u2014]\s+[^-|\u2013\u2014]{2,40}$", "", headline or "").strip()  # tira " - Fonte"
    h = re.sub(r"[\"“”'‘’:;!?()\[\]]", " ", h)
    words = [w for w in h.split() if strip_accents(w.lower()) not in _STOP_N or w[:1].isupper()]
    words = [w for w in words if len(w) > 1]
    return " ".join(words[:max_words]).strip() or h[:60]
