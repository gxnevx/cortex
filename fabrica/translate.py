"""Traducao para PT-BR: legenda de cortes de videos estrangeiros (ingles, espanhol...) e frases soltas.

Contratos:
    detect_language(transcript_or_media, cfg=None, start=None, end=None) -> str     # "pt", "en", "es"...
    to_portuguese(transcript, cfg, context="") -> Transcript | None
        # traduz segmento a segmento (mesmo start/end) e cria o tempo de cada palavra traduzida
        # distribuindo pelo tempo de fala do segmento original (karaoke continua funcionando).
        # None = nenhuma IA disponivel ou traducao falhou (o pipeline pula o video estrangeiro)
    translate_text(text, cfg, target="pt") -> str      # titulos/citacoes; "" se nao der

Motor (traducao.motor): "ollama" (padrao, local e gratis: cerebro.ollama_modelo, 6 threads) | "claude" |
"auto" (Ollama, depois Claude). Com "ollama", o Claude so entra se o Ollama estiver indisponivel E
traducao.permitir_claude = true (padrao false: o Claude gasta a cota da assinatura do dono).
Uma requisicao por vez (trava global): este PC nao aguenta carga pesada em paralelo.
Chaves (opcionais): traducao.motor, traducao.permitir_claude, traducao.ollama_modelo, traducao.lote_caracteres
(1100), traducao.temperatura (0.2), traducao.timeout_s (Claude, 300), cerebro.ollama_timeout_s (600).
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from . import log
from .models import Segment, Transcript, Word
from .util import clean_text

logger = log.get(__name__)

_LLM_LOCK = threading.Lock()
MAX_THREADS = 6

SYSTEM_PT = (
    "Voce traduz legendas de videos curtos (TikTok, YouTube Shorts) para o portugues do Brasil falado, "
    "como um brasileiro jovem falaria na vida real.\n"
    "Regras:\n"
    "- Natural e informal (pra, ta, mano, cara, tipo). Prefira a expressao brasileira a traducao literal: "
    "side job = bico; dude/bro = mano; you know = tipo, sabe; I was like = eu falei; that's crazy = que doideira.\n"
    "- Mantenha TODO palavrao do original (nao corte nenhum), com o mesmo peso e no lugar natural do portugues: 'fucking' de enfase vira 'porra', 'caralho' "
    "ou 'a porra do/da' (nunca 'foda-se' no meio da frase); shut the fuck up = cala a porra da boca; "
    "shit = merda; what the fuck = que porra e essa. Nao censure nem suavize.\n"
    "- Nomes de pessoas, apelidos, marcas, jogos, times e lugares ficam como estao.\n"
    "- Cada trecho vira um trecho com o mesmo id, sem pular nenhum. Se a frase continua no trecho seguinte, "
    "traduza para cada pedaco ler bem sozinho (pode passar uma palavra para o trecho vizinho).\n"
    "- Frases curtas. Nao explique e nao acrescente nada. Responda somente com JSON."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "traducoes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "pt": {"type": "string"}},
                "required": ["id", "pt"],
            },
        }
    },
    "required": ["traducoes"],
}

TEXT_SCHEMA = {"type": "object", "properties": {"traducao": {"type": "string"}}, "required": ["traducao"]}

_LANG_NAMES = {"en": "ingles", "es": "espanhol", "fr": "frances", "it": "italiano", "de": "alemao",
               "ja": "japones", "ko": "coreano", "ru": "russo", "zh": "chines", "ar": "arabe", "pt": "portugues"}

# palavras muito frequentes (para adivinhar o idioma de um texto)
_STOP = {
    "pt": set("que nao não de da do eu voce você pra para com uma um os as ele ela isso essa esse mas tá ta ai aí "
              "né ne muito tem foi vai sao são mais meu minha gente cara".split()),
    "en": set("the and you that is it to of what this i'm i was for have with but not my they just like know "
              "don't it's yeah so we he she be are do".split()),
    "es": set("que el la de y no es en lo un una por con para pero mi yo tu tú esto eso muy está como "
              "qué porque bueno sí vamos".split()),
}


# ----------------------------------------------------------------------------------------
# Idioma
# ----------------------------------------------------------------------------------------
def guess_text_language(text: str) -> str:
    """Palpite barato pelo vocabulario (pt/en/es). "" se nao der para saber."""
    words = re.findall(r"[a-zà-ÿ']+", (text or "").lower())
    if len(words) < 6:
        return ""
    scores = {lang: sum(1 for w in words if w in st) for lang, st in _STOP.items()}
    best = max(scores, key=scores.get)
    ordered = sorted(scores.values(), reverse=True)
    if ordered[0] < 3 or ordered[0] < 1.4 * ordered[1]:
        return ""
    return best


def detect_language(transcript_or_media, cfg=None, start: float | None = None, end: float | None = None) -> str:
    """Idioma de um Transcript (Transcript.language, conferido pelo texto) ou de um arquivo de midia
    (deteccao do faster-whisper em ate 90 s de fala a partir de `start`)."""
    if isinstance(transcript_or_media, Transcript):
        tr = transcript_or_media
        lang = (tr.language or "").split("-")[0].lower()
        guess = guess_text_language(tr.text[:4000])
        if guess and lang and guess != lang and not str(tr.source or "").startswith("whisper"):
            return guess              # legenda de plataforma com idioma errado no nome do arquivo
        return lang or guess or "pt"
    from . import transcribe

    lang, prob = transcribe.detect_language_media(Path(transcript_or_media), cfg, start=start, end=end)
    logger.debug("idioma detectado: %s (%.2f)", lang, prob)
    return lang or "pt"


# ----------------------------------------------------------------------------------------
# Motores (Claude CLI ou Ollama)
# ----------------------------------------------------------------------------------------
def _cfg(cfg, key: str, default):
    try:
        v = cfg.get(key, default) if cfg is not None else default
    except Exception:
        v = default
    return default if v is None else v


class _Engine:
    def __init__(self, name: str, call, batch_chars: int):
        self.name = name
        self.call = call                  # call(prompt, system, schema) -> str
        self.batch_chars = batch_chars


_ENGINE_CACHE: dict[str, tuple[float, _Engine | None]] = {}


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "sim", "yes", "on")


def get_engine(cfg=None) -> _Engine | None:
    """IA para traduzir. Padrao: Ollama local (gratis). Claude so se traducao.motor = claude/auto, ou se o
    Ollama estiver indisponivel E traducao.permitir_claude = true (Claude gasta a cota da assinatura do dono).
    None = nenhuma IA disponivel."""
    motor = str(_cfg(cfg, "traducao.motor", "ollama") or "ollama").strip().lower()
    allow_claude = _truthy(_cfg(cfg, "traducao.permitir_claude", False))
    key = f"{motor}|{allow_claude}"
    hit = _ENGINE_CACHE.get(key)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    if motor == "claude":
        order = ["claude"]
    elif motor == "auto":
        order = ["ollama", "claude"]
    else:
        order = ["ollama"] + (["claude"] if allow_claude else [])
    eng: _Engine | None = None
    for m in order:
        try:
            if m == "claude":
                from .brain.claude_cli import ClaudeBrain

                timeout = float(_cfg(cfg, "traducao.timeout_s", 300) or 300)
                b = ClaudeBrain(cfg)
                if b.available():
                    eng = _Engine("claude", lambda p, s, schema, b=b, t=timeout: b._run(p, s, timeout=t),
                                  int(_cfg(cfg, "traducao.lote_caracteres_claude", 9000)))
                    break
            else:
                from .brain.ollama import OllamaBrain

                # lote pequeno (~1100 caracteres, ~300 tokens de resposta) termina bem dentro do limite
                timeout = float(_cfg(cfg, "cerebro.ollama_timeout_s", 600) or 600)
                b = OllamaBrain(cfg)
                model = str(_cfg(cfg, "traducao.ollama_modelo", "") or "").strip()
                if model:
                    b.model = model
                b.num_thread = min(MAX_THREADS, int(b.num_thread or MAX_THREADS))
                b.temperature = float(_cfg(cfg, "traducao.temperatura", 0.2))
                if b.available():
                    eng = _Engine("ollama", lambda p, s, schema, b=b, t=timeout: b.chat(p, s, schema, timeout=t,
                                                                                        num_predict=1536),
                                  int(_cfg(cfg, "traducao.lote_caracteres", 1100)))
                    break
        except Exception as e:  # checagem nunca derruba o pipeline
            logger.debug("motor de traducao %s indisponivel: %s", m, e)
    _ENGINE_CACHE[key] = (time.time(), eng)
    if eng is None:
        logger.info("Traducao indisponivel: Ollama sem o modelo/servidor%s.",
                    " e Claude nao logado" if "claude" in order else " (Claude desligado: traducao.permitir_claude)")
    return eng


def _ask(eng: _Engine, prompt: str, system: str, schema: dict) -> object:
    from .brain.base import extract_json

    with _LLM_LOCK:                       # uma requisicao por vez
        t0 = time.time()
        raw = eng.call(prompt, system, schema)
        logger.debug("traducao (%s): %.1fs", eng.name, time.time() - t0)
    return extract_json(raw)


# ----------------------------------------------------------------------------------------
# Traducao de segmentos
# ----------------------------------------------------------------------------------------
def _clean_pt(s: str) -> str:
    s = clean_text(str(s or ""), emojis=False)
    s = s.replace("\n", " ").strip()
    s = re.sub(r"\s+-+\s+", ", ", s)                  # travessao virou " - ": vira virgula na legenda
    s = re.sub(r"^-+\s*", "", s)
    s = re.sub(r"^[\"'“”]+|[\"'“”]+$", "", s).strip()
    s = re.sub(r"\s+([,.!?;:])", r"\1", s)
    return re.sub(r"\s{2,}", " ", s)


def _plausible(src: str, pt: str, lang: str) -> bool:
    if not pt:
        return False
    ls, lp = len(src), len(pt)
    if lp > 4 * ls + 25 or (ls > 25 and lp < 0.25 * ls):
        return False
    # copiou o original sem traduzir (frase com 4+ palavras igual a de entrada)
    if lang != "pt" and len(src.split()) >= 4 and re.sub(r"\W", "", src.lower()) == re.sub(r"\W", "", pt.lower()):
        return False
    return True


def _batches(items: list[tuple[int, str]], max_chars: int) -> list[list[tuple[int, str]]]:
    out: list[list[tuple[int, str]]] = []
    cur: list[tuple[int, str]] = []
    size = 0
    for it in items:
        if cur and (size + len(it[1]) > max_chars or len(cur) >= 25):
            out.append(cur)
            cur, size = [], 0
        cur.append(it)
        size += len(it[1]) + 12
    if cur:
        out.append(cur)
    return out


def _translate_batch(eng: _Engine, batch: list[tuple[int, str]], lang: str, context: str,
                     prev: str = "") -> dict[int, str]:
    from .brain.base import list_from_json

    lang_name = _LANG_NAMES.get(lang, lang or "idioma estrangeiro")
    items = [{"id": i, "texto": t} for i, t in batch]
    prompt = (
        (f"Contexto do video: {context.strip()[:300]}\n" if context.strip() else "")
        + (f"Fala anterior (so contexto, nao traduza): {prev[-200:]}\n" if prev else "")
        + f"Idioma original: {lang_name}.\n"
        + "Traduza cada trecho para portugues do Brasil falado:\n"
        + json.dumps(items, ensure_ascii=False)
        + '\n\nResponda exatamente neste formato, com todos os ids: {"traducoes": [{"id": 1, "pt": "..."}]}'
    )
    obj = _ask(eng, prompt, SYSTEM_PT, SCHEMA)
    rows = list_from_json(obj, ("traducoes", "translations", "itens", "items"))
    src = dict(batch)
    out: dict[int, str] = {}
    for r in rows:
        try:
            i = int(r.get("id"))
        except (TypeError, ValueError, AttributeError):
            continue
        pt = _clean_pt(r.get("pt") or r.get("texto") or r.get("traducao") or "")
        if i in src and _plausible(src[i], pt, lang):
            out[i] = pt
    return out


def _speech_intervals(seg: Segment, merge_gap: float = 0.2) -> list[tuple[float, float]]:
    """Trechos com fala dentro do segmento (pelas palavras originais); sem palavras = segmento inteiro."""
    ivs: list[list[float]] = []
    for w in sorted(seg.words, key=lambda w: w.start):
        s, e = max(seg.start, w.start), min(seg.end, w.end)
        if e <= s:
            continue
        if ivs and s - ivs[-1][1] <= merge_gap:
            ivs[-1][1] = max(ivs[-1][1], e)
        else:
            ivs.append([s, e])
    if not ivs or sum(e - s for s, e in ivs) < 0.25 * (seg.end - seg.start):
        return [(seg.start, max(seg.end, seg.start + 0.1))]
    return [(s, e) for s, e in ivs]


def distribute_words(text: str, seg: Segment) -> list[Word]:
    """Palavras traduzidas espalhadas pelo tempo de fala do segmento, proporcional ao tamanho da palavra."""
    words = text.split()
    if not words:
        return []
    ivs = _speech_intervals(seg)
    lens = [e - s for s, e in ivs]
    total = sum(lens)
    weights = [len(re.sub(r"\W", "", w)) + 2 for w in words]
    wsum = float(sum(weights))

    def locate(pos: float, prefer_next: bool) -> tuple[int, float]:
        acc = 0.0
        for k, ln in enumerate(lens):
            if pos < acc + ln - 1e-6 or (not prefer_next and pos <= acc + ln + 1e-6):
                return k, ivs[k][0] + max(0.0, pos - acc)
            acc += ln
        return len(ivs) - 1, ivs[-1][1]

    out: list[Word] = []
    cum = 0.0
    for w, wt in zip(words, weights):
        a, b = cum, cum + total * wt / wsum
        cum = b
        ka, ts = locate(a, True)
        kb, te = locate(b, False)
        if kb != ka:          # palavra caiu em cima de uma pausa: fica do lado onde tem mais tempo
            if ivs[ka][1] - ts >= te - ivs[kb][0]:
                te = ivs[ka][1]
            else:
                ts = ivs[kb][0]
        out.append(Word(round(ts, 3), round(max(te, ts + 0.04), 3), w))
    return out


def to_portuguese(transcript: Transcript, cfg=None, context: str = "") -> Transcript | None:
    """Legenda em PT-BR com os mesmos tempos de segmento. None se nao houver IA ou se a traducao falhar."""
    if transcript is None or not transcript.segments:
        return None
    lang = detect_language(transcript, cfg)
    if lang.startswith("pt"):
        return transcript
    eng = get_engine(cfg)
    if eng is None:
        return None
    segs = transcript.segments
    items = [(i + 1, re.sub(r"\s+", " ", s.text).strip()) for i, s in enumerate(segs)]
    items = [(i, t) for i, t in items if t]
    done: dict[int, str] = {}
    t0 = time.time()
    from .brain.base import BrainUnavailable

    bad = 0
    try:
        prev = ""
        for batch in _batches(items, eng.batch_chars):
            got = {}
            for attempt in range(2):
                todo = [(i, t) for i, t in batch if i not in got]
                if not todo:
                    break
                try:
                    got.update(_translate_batch(eng, todo, lang, context, prev))
                except BrainUnavailable:
                    raise
                except Exception as e:
                    bad += 1
                    logger.debug("lote de traducao falhou (tentativa %d): %s", attempt + 1, e)
                    if bad >= 3 or time.time() - t0 > 900:
                        raise RuntimeError("a IA de traducao nao esta respondendo") from e
            # o que sobrou: um por um (modelos pequenos as vezes pulam ids em lote)
            for i, t in batch:
                if i not in got:
                    try:
                        got.update(_translate_batch(eng, [(i, t)], lang, context, prev))
                    except BrainUnavailable:
                        raise
                    except Exception as e:
                        bad += 1
                        logger.debug("trecho %d nao traduziu: %s", i, e)
                        if bad >= 3 or time.time() - t0 > 900:
                            raise RuntimeError("a IA de traducao nao esta respondendo") from e
            done.update(got)
            prev = " ".join(t for _, t in batch)
    except Exception as e:
        logger.warning("Traducao falhou (%s): %s", eng.name, e)
        return None
    missing = [i for i, _ in items if i not in done]
    if missing:
        logger.warning("Traducao incompleta (%d de %d trechos sem traducao); legenda descartada",
                       len(missing), len(items))
        return None
    out: list[Segment] = []
    for i, s in enumerate(segs, 1):
        pt = done.get(i)
        if not pt:
            continue
        out.append(Segment(s.start, s.end, pt, distribute_words(pt, s)))
    logger.info("Legenda traduzida (%s -> pt, %s): %d trechos em %.1fs", lang, eng.name, len(out), time.time() - t0)
    src = str(transcript.source or "whisper")
    return Transcript(out, language="pt", source=f"{src}+traducao_{lang}")


def translate_text(text: str, cfg=None, target: str = "pt") -> str:
    """Traduz uma frase curta (titulo, citacao). Devolve "" se nao houver IA ou se falhar."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return ""
    tgt = (target or "pt").split("-")[0].lower()
    if guess_text_language(text) == tgt:
        return text
    eng = get_engine(cfg)
    if eng is None:
        return ""
    tname = "portugues do Brasil falado (natural, informal, mantendo girias e palavroes)" if tgt == "pt" \
        else _LANG_NAMES.get(tgt, tgt)
    prompt = (f"Traduza para {tname}. Mantenha nomes proprios. So a traducao, sem aspas e sem explicar.\n"
              f"Texto: {text}\n\nResponda: {{\"traducao\": \"...\"}}")
    system = SYSTEM_PT if tgt == "pt" else "Voce e um tradutor. Responda somente com JSON."
    try:
        obj = _ask(eng, prompt, system, TEXT_SCHEMA)
    except Exception as e:
        logger.debug("translate_text falhou: %s", e)
        return ""
    val = ""
    if isinstance(obj, dict):
        val = obj.get("traducao") or obj.get("pt") or obj.get("translation") or ""
    elif isinstance(obj, str):
        val = obj
    val = _clean_pt(val)
    return val if _plausible(text, val, "xx") else ""
