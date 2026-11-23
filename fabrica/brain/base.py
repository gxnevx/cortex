"""Interface do cerebro + pos-processamento comum a todos os motores.

Todo plano (venha do Claude, do Ollama ou da heuristica) passa por `finalize_plans`, que:
- limita os tempos a duracao da transcricao;
- encaixa inicio/fim em limites de frase/palavra (respiro de ~0,3 s, nunca corta palavra no meio);
- garante duracao minima/maxima e divide assuntos longos em series contiguas (Parte 1, 2...);
- remove sobreposicoes (menos entre partes da mesma serie, que sao contiguas);
- descarta pontuacao baixa (mantendo pelo menos o melhor), aplica o limite de cortes;
- gera ids, normaliza hashtags/categoria/layout;
- escolhe o teaser (cold open) de cada corte: teaser_start/teaser_end/teaser_text (1,5 a 3 s, palavras inteiras,
  pelo menos ~4 s depois do inicio, texto exato da transcricao);
- mascara palavrao no titulo/gancho/descricao (conteudo.palavroes: mascarar | mostrar | remover).

Funcoes reutilizaveis (o pipeline usa no refinamento pos-render):
    polemic_spans(words, cfg, min_s=1.5, max_s=3.0) -> [{"start","end","text","score","tipos"}]
    mask_profanity(text, mode) -> str
    pick_teaser(words, start, end, hint_text="", ...) -> {"start","end","text",...} | None
"""
from __future__ import annotations

import ast
import bisect
import json
import math
import re
import time
import unicodedata
from dataclasses import dataclass, field, replace
from typing import Any, Iterable

from .. import log, paths
from ..models import Candidate, ClipPlan, Transcript, Trend, Word
from ..util import short_hash, slugify

logger = log.get(__name__)

CATEGORIES = ["politica", "polemica", "games", "humor", "entretenimento", "esportes", "podcast",
              "noticias", "celebridades", "outros"]
LAYOUTS = {"split", "blur", "full"}
LEAD_IN = 0.3        # respiro antes da primeira palavra
TAIL = 0.35          # respiro depois da ultima palavra

_CAT_ALIASES = {
    "politica": "politica", "politico": "politica", "eleicao": "politica", "eleicoes": "politica",
    "polemica": "polemica", "polemicas": "polemica", "treta": "polemica", "debate": "polemica",
    "games": "games", "game": "games", "jogos": "games", "gamer": "games", "gameplay": "games", "esports": "games",
    "humor": "humor", "comedia": "humor", "engracado": "humor", "meme": "humor", "memes": "humor",
    "entretenimento": "entretenimento", "reality": "entretenimento", "tv": "entretenimento",
    "esportes": "esportes", "esporte": "esportes", "futebol": "esportes",
    "podcast": "podcast", "podcasts": "podcast", "entrevista": "podcast", "entrevistas": "podcast",
    "noticias": "noticias", "noticia": "noticias", "jornalismo": "noticias",
    "celebridades": "celebridades", "celebridade": "celebridades", "famosos": "celebridades",
    "fofoca": "celebridades", "musica": "entretenimento",
}


class BrainUnavailable(RuntimeError):
    """O motor nao pode ser usado agora (nao logado, servidor desligado, limite de uso...)."""


# ----------------------------------------------------------------------------------------
# Cache de disponibilidade (paths.STATE) - evita checar Claude/Ollama a cada execucao
# ----------------------------------------------------------------------------------------
CACHE_FILE = paths.STATE / "cerebro_disponibilidade.json"
CACHE_TTL_OK = 3600          # 1 h
CACHE_TTL_FAIL = 600         # 10 min (se o usuario logar/abrir o Ollama, nao espera 1 h)


def _cache_load() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def cache_get(key: str) -> dict | None:
    e = _cache_load().get(key)
    if isinstance(e, dict) and time.time() - float(e.get("ts", 0)) < float(e.get("ttl", CACHE_TTL_OK)):
        return e
    return None


def cache_set(key: str, ok: bool, msg: str, ttl: float | None = None) -> None:
    try:
        d = _cache_load()
        d[key] = {"ok": bool(ok), "msg": msg, "ts": time.time(),
                  "ttl": ttl if ttl is not None else (CACHE_TTL_OK if ok else CACHE_TTL_FAIL)}
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:  # cache e opcional
        logger.debug("cache do cerebro: %s", e)


def clear_cache() -> None:
    try:
        CACHE_FILE.unlink()
    except OSError:
        pass


# ----------------------------------------------------------------------------------------
# Interface
# ----------------------------------------------------------------------------------------
class Brain:
    name = "base"

    def __init__(self, cfg=None):
        self.cfg = cfg
        self._status = ""
        self.notes: list[str] = []        # avisos de fallback (ex.: "Claude nao logado")

    def available(self, refresh: bool = False) -> bool:
        return True

    def status(self) -> str:
        msg = self._status or f"Cérebro: {self.name}"
        if self.notes:
            msg += " (" + " ".join(self.notes) + ")"
        return msg

    def rank_trends(self, trends: list[Trend], cfg, limit: int = 15) -> list[Trend]:
        raise NotImplementedError

    def pick_clips(self, video: Candidate, transcript: Transcript, cfg, max_clips: int | None = None) -> list[ClipPlan]:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<Brain {self.name}>"


class LLMBrain(Brain):
    """Base dos motores com IA: qualquer erro cai no heuristico (o pipeline nunca para)."""

    def _pick_raw(self, video: Candidate, transcript: Transcript, cfg, limit: int, sig, sig_summary: str) -> list[dict]:
        raise NotImplementedError

    def _rank_raw(self, trends: list[Trend], cfg, limit: int) -> list[dict]:
        raise NotImplementedError

    def _heuristic(self):
        from .heuristic import HeuristicBrain

        return HeuristicBrain(self.cfg)

    def pick_clips(self, video, transcript, cfg, max_clips=None):
        from .. import signals as sigmod

        limit = resolve_limit(cfg, video, transcript, max_clips)
        sig = None
        summary = ""
        try:
            audio = (video.extra or {}).get("audio_path") or (video.extra or {}).get("media_path")
            sig = sigmod.compute_signals(video, transcript, audio_path=audio)
            summary = sigmod.summarize_for_prompt(sig)
        except Exception as e:  # sinais sao opcionais
            logger.debug("sinais falharam: %s", e)
        from . import games

        try:
            raw = games.chapter_windows(video, transcript, cfg, limit) or self._pick_raw(video, transcript, cfg, limit, sig, summary)
            plans = finalize_plans(raw, video, transcript, cfg, max_clips=max_clips,
                                   teaser_bonus=sigmod.teaser_bonus(sig))
            if plans:
                return plans
            logger.warning("%s nao devolveu cortes validos para '%s'; usando heuristico", self.name, safe_text(video.title, 50))
        except BrainUnavailable as e:
            logger.warning("%s indisponivel: %s - usando heuristico", self.name, safe_text(e))
        except Exception as e:
            logger.warning("%s falhou ao escolher cortes (%s) - usando heuristico", self.name, safe_text(e))
        return self._heuristic().pick_clips(video, transcript, cfg, max_clips=max_clips)

    def rank_trends(self, trends, cfg, limit=15):
        if not trends:
            return []
        try:
            raw = self._rank_raw(trends, cfg, limit)
            out = finalize_trends(raw, trends, limit)
            if out:
                return out
            logger.warning("%s nao devolveu temas validos; usando heuristico", self.name)
        except BrainUnavailable as e:
            logger.warning("%s indisponivel: %s - usando heuristico", self.name, safe_text(e))
        except Exception as e:
            logger.warning("%s falhou ao ranquear temas (%s) - usando heuristico", self.name, safe_text(e))
        return self._heuristic().rank_trends(trends, cfg, limit)


# ----------------------------------------------------------------------------------------
# JSON robusto (respostas de LLM)
# ----------------------------------------------------------------------------------------
def _balanced_candidates(text: str) -> list[str]:
    """Trechos {...} / [...] balanceados (respeitando strings)."""
    out = []
    for i, ch in enumerate(text):
        if ch not in "{[":
            continue
        stack = []
        in_str = False
        esc = False
        for j in range(i, len(text)):
            c = text[j]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c in "{[":
                stack.append(c)
            elif c in "}]":
                if not stack or (stack[-1] == "{") != (c == "}"):
                    break
                stack.pop()
                if not stack:
                    out.append(text[i: j + 1])
                    break
        if len(out) >= 6:
            break
    return out


def _try_load(s: str) -> Any:
    try:
        return json.loads(s)
    except Exception:
        pass
    fixed = re.sub(r",\s*([}\]])", r"\1", s)                     # virgula sobrando
    fixed = fixed.replace("“", '"').replace("”", '"')
    try:
        return json.loads(fixed)
    except Exception:
        pass
    try:  # estilo Python (aspas simples, True/None)
        py = re.sub(r"\btrue\b", "True", re.sub(r"\bfalse\b", "False", re.sub(r"\bnull\b", "None", fixed)))
        val = ast.literal_eval(py)
        if isinstance(val, (dict, list)):
            return val
    except Exception:
        pass
    raise ValueError("json invalido")


def extract_json(text: str) -> Any:
    """Extrai o JSON de uma resposta de LLM (aceita ```json```, texto antes/depois, virgula sobrando)."""
    if text is None:
        raise ValueError("resposta vazia")
    t = text.strip().lstrip("﻿")
    if not t:
        raise ValueError("resposta vazia")
    try:
        return _try_load(t)
    except ValueError:
        pass
    for m in re.finditer(r"```(?:json|JSON)?\s*(.*?)```", t, re.S):
        try:
            return _try_load(m.group(1).strip())
        except ValueError:
            continue
    cands = _balanced_candidates(t)
    starts = [i for i in (t.find("{"), t.find("[")) if i >= 0]
    first = min(starts) if starts else -1
    top_ok = any(t.startswith(c, first) for c in cands) if first >= 0 else False
    if first >= 0 and not top_ok:
        # resposta cortada no meio: fecha a lista ate o ultimo objeto completo
        body = t[first:]
        k = body.rfind("}")
        while k > 0:
            for closer in ("]}", "}", "]", "}]}", "]}]}"):
                try:
                    return _try_load(body[: k + 1] + closer)
                except ValueError:
                    pass
            k = body.rfind("}", 0, k)
    for c in sorted(cands, key=len, reverse=True):
        try:
            return _try_load(c)
        except ValueError:
            continue
    raise ValueError(f"nao achei JSON na resposta: {t[:200]!r}")


def list_from_json(obj: Any, keys: Iterable[str]) -> list[dict]:
    """Pega a lista principal de um JSON ({"cortes": [...]}, {"clips": [...]} ou [...])."""
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        for k in keys:
            v = obj.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        for v in obj.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return [x for x in v if isinstance(x, dict)]
        if any(k in obj for k in ("inicio", "start", "início")):
            return [obj]
    return []


# ----------------------------------------------------------------------------------------
# Normalizacao de campos
# ----------------------------------------------------------------------------------------
def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()


def parse_time(v: Any) -> float | None:
    """'mm:ss', 'h:mm:ss', '75', '75.5', '1m15s', 75 -> segundos."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    s = str(v).strip().strip("[]()").replace(",", ".")
    if not s:
        return None
    m = re.fullmatch(r"(?:(\d+)h)?\s*(?:(\d+)m(?:in)?)?\s*(?:(\d+(?:\.\d+)?)s)?", s)
    if m and any(m.groups()):
        h, mi, se = m.groups()
        return int(h or 0) * 3600 + int(mi or 0) * 60 + float(se or 0)
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        return float(s)
    parts = s.split(":")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    sec = 0.0
    for p in nums:
        sec = sec * 60 + p
    return sec


def _first(d: dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def normalize_category(c: Any) -> str | None:
    if not c:
        return None
    k = re.sub(r"[^a-z]", "", _ascii(str(c)).lower())
    if k in _CAT_ALIASES:
        return _CAT_ALIASES[k]
    for alias, cat in _CAT_ALIASES.items():
        if alias in k:
            return cat
    return "outros"


def normalize_layout(v: Any) -> str | None:
    s = _ascii(str(v or "")).lower().strip()
    return s if s in LAYOUTS else None


def normalize_hashtags(tags: Any, max_n: int = 8) -> list[str]:
    if not tags:
        return []
    if isinstance(tags, str):
        tags = re.split(r"[\s,;]+", tags)
    out: list[str] = []
    for t in tags:
        s = _ascii(str(t)).lower()
        s = re.sub(r"[^a-z0-9_]", "", s)
        if len(s) < 2 or len(s) > 30 or s.isdigit():
            continue
        tag = "#" + s
        if tag not in out:
            out.append(tag)
        if len(out) >= max_n:
            break
    return out


_EMOJI_TAIL = re.compile(r"[\s\U0001F000-\U0001FFFF☀-➿️‍!?.…]+$")
_PART_RX = re.compile(r"\s*[\(\[\-|\u2013\u2014]*\s*parte\s*\d+\s*(?:/\s*\d+|de\s*\d+)?\s*(?:,\s*final)?\s*[\)\]]?", re.I)


def clean_title(title: str, max_len: int = 90) -> str:
    t = re.sub(r"\s+", " ", str(title or "")).strip()
    if t.startswith('"') and t.endswith('"') and t.count('"') == 2:
        t = t[1:-1].strip()
    if t.count('"') % 2 == 1:
        t = t.replace('"', "")
    if len(t) > max_len:
        cut = t[:max_len]
        sp = cut.rfind(" ")
        t = (cut[:sp] if sp > max_len * 0.6 else cut).rstrip(" ,.;:-") + "…"
    return t


_CAT_EMOJI = {"humor": "💀", "games": "🎮", "politica": "🔥", "polemica": "😳",
              "esportes": "⚽", "futebol": "⚽", "tecnologia": "🤯"}


def polish_title(title: str, category: str | None, n_emo: int, video_title: str = "") -> str:
    """IA local: titulo todo em CAIXA ALTA vira frase normal (nomes do video mantem a maiuscula) e, sem emoji, ganha um."""
    t = title or ""
    letters = [c for c in t if c.isalpha()]
    if len(letters) > 12 and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        names = {w.lower(): w for w in re.findall(r"[^\W\d_]{3,}", video_title or "") if w[:1].isupper() and not w.isupper()}
        low = re.sub(r"[^\W\d_]+", lambda m: names.get(m.group(0).lower(), m.group(0).lower()), t)
        low = re.sub(r"(^\W*|[.!?]\s+\W*)([^\W\d_])", lambda m: m.group(1) + m.group(2).upper(), low)
        t = low
    if n_emo > 0 and t and not _ONE_EMOJI.search(t):
        t = f"{t} {_CAT_EMOJI.get(category or '', chr(0x1F440))}"
    return t


# emojis/pictogramas (inclui bandeiras, tons de pele, ZWJ, seletor de variacao)
_EMOJI_RX = re.compile("[\U0001F000-\U0001FAFF☀-➿⌀-⏿⬀-⯿←-⇿"
                       "〰〽㊗㊙︎️‍⃣\U000E0020-\U000E007F]+")


def safe_text(x, max_len: int = 200) -> str:
    """Texto para log/status: sem emoji e sem travessao/bolinha."""
    return clean_punct(strip_emojis(str(x)))[:max_len]


def emojis_enabled(cfg) -> bool:
    """conteudo.emojis (padrao True: emojis no titulo/gancho; False = nenhum emoji)."""
    v = _cfg_get(cfg, "conteudo.emojis", True)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "sim", "yes", "on")
    return bool(v)


_EMO_BASE = "🀀-🫿☀-➿⌀-⏿⬀-⯿←-⇿〰〽㊗㊙"
_EMO_MOD = "︎️🏻-🏿⃣"
_ONE_EMOJI = re.compile(f"[🇦-🇿]{{2}}|[{_EMO_BASE}][{_EMO_MOD}]*(?:‍[{_EMO_BASE}][{_EMO_MOD}]*)*")


def limit_emojis(text: str, n: int) -> str:
    """Mantem no maximo n emojis diferentes (sem repetir, ex.: nada de fogo-fogo-fogo)."""
    seen: list[str] = []

    def repl(m):
        e = m.group(0)
        if e in seen or len(seen) >= n:
            return ""
        seen.append(e)
        return e

    t = _ONE_EMOJI.sub(repl, text or "")
    return re.sub(r"[ 	]{2,}", " ", t).strip()


def strip_emojis(text: str) -> str:
    t = _EMOJI_RX.sub("", text or "")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" +([,.;:!?\u2026)\]])", r"\1", t)
    t = re.sub(r"\(\s*\)|\[\s*\]", "", t)
    t = re.sub(r"(?:\s*[|\-\u2013\u2014:]\s*)+$", "", t.strip())
    t = re.sub(r"^(?:\s*[|\-\u2013\u2014:]\s*)+", "", t)
    return "\n".join(line.strip() for line in t.split("\n")).strip()


_BULLET_LINE = re.compile(r"^[ \t]*[\u2022\u00b7][ \t]*", re.M)
_BULLET = re.compile(r"[ \t]*[\u2022\u00b7][ \t]*")
_DASH_SPACED = re.compile(r"[ \t]+[\u2013\u2014][ \t]+")


def clean_punct(text: str) -> str:
    """Regra do dono: nada de travessao/meia-risca/bolinha. Vira '-', '|' ou ','."""
    if not text:
        return text or ""
    t = _BULLET_LINE.sub("- ", str(text))
    t = _BULLET.sub(" | ", t)
    t = _DASH_SPACED.sub(" - ", t)
    t = t.replace("\u2014", "-").replace("\u2013", "-")
    return re.sub(r"[ \t]{2,}", " ", t).strip()


def series_title(base: str, part: int, total: int | None = None) -> str:
    """'O clima pesou 😬' -> 'O clima pesou (parte 2) 😬'; ultima parte: '(parte 3, final)'."""
    base = _PART_RX.sub("", base).strip()
    m = _EMOJI_TAIL.search(base)
    tail = ""
    if m and _EMOJI_RX.search(m.group(0)):
        tail = m.group(0).strip()
        base = base[: m.start()].rstrip()
    suffix = f"(parte {part}, final)" if total and part == total and total > 1 else f"(parte {part})"
    out = f"{base} {suffix}"
    if tail:
        out += " " + tail
    return out


def short_hook(text: str, max_chars: int = 45) -> str:
    """Gancho da tela: ate ~45 caracteres, cortando em palavra inteira. Citacao inteira entre aspas
    ("VOCE E UM MENTIROSO") mantem as aspas."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    m = re.match(r'^["“]([^"“”]+)["”]\s*(.*)$', t)
    if m:
        inner, tail = m.group(1).strip(), m.group(2).strip()
        full = f"\"{inner}\"" + (f" {tail}" if tail else "")
        if len(full) <= max_chars:
            return full
        if len(inner) + 2 <= max_chars:
            return f"\"{inner}\""
        t = inner
    t = t.strip('"“”')
    if len(t) <= max_chars:
        return t
    cut = t[:max_chars]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > max_chars * 0.5 else cut).rstrip(" ,.;:-|")


# ----------------------------------------------------------------------------------------
# Palavroes (conteudo.palavroes: mascarar | mostrar | remover) e trechos polemicos (teaser / citacao)
# ----------------------------------------------------------------------------------------
_PROFANITY_RX = re.compile(
    r"(?i)\b(?:foda[- ]?se|fod(?:a|as|e|er|eu|ido|ida|idos|idas|endo)|porra|caralh[oa]s?|put(?:a|as|o|os|aria)|"
    r"merdas?|bostas?|cacetes?|b[uo]cetas?|cu|cuz[aã]o|desgra[cç](?:a|ado|ada|ados|adas)|arrombad[oa]s?|"
    r"viad[oa]s?|pqp|vsf|vtnc|fdp|krl|crl|piroca|punheta|cacete|"
    r"fuck\w*|motherfuck\w*|shit\w*|bitch\w*|assholes?|dumbass)\b")


def mask_profanity(text: str, mode: str = "mascarar") -> str:
    """Palavrao no titulo/gancho/descricao. mascarar: segunda letra vira * (p*rra, c*ralho, f*da-se);
    mostrar: sem mudanca; remover: tira a palavra."""
    if not text:
        return text or ""
    mode = str(mode or "mascarar").strip().lower()
    if mode in ("mostrar", "show", "nao", "não", "false", "off"):
        return text
    if mode in ("remover", "remove", "tirar"):
        out = _PROFANITY_RX.sub("", text)
        out = re.sub(r"\s+([,.!?:;])", r"\1", re.sub(r"[ \t]{2,}", " ", out))
        out = re.sub(r'"\s+', '"', re.sub(r'\s+"(?=\s|$)', '"', out))
        return out.strip()

    def _mask(m: re.Match) -> str:
        w = m.group(0)
        return w[0] + "*" + w[2:] if len(w) >= 3 else w[0] + "*"

    return _PROFANITY_RX.sub(_mask, text)


def profanity_mode(cfg) -> str:
    """mascarar | mostrar | remover: o nivel do tom (fabrica.tom) manda; senao conteudo.palavroes."""
    try:
        from .. import tom

        return str(tom.settings(cfg).get("palavroes") or "mascarar")
    except Exception:  # noqa: BLE001
        return str(_cfg_get(cfg, "conteudo.palavroes", "mascarar") or "mascarar")


def max_title_emojis(cfg) -> int:
    try:
        from .. import tom

        return int(tom.settings(cfg).get("max_emojis", 2))
    except Exception:  # noqa: BLE001
        return 2


_INSULT_RX = re.compile(r"\b(?:mentiros[oa]s?|ladr(?:ao|ona|oes|onas)|idiotas?|imbecil|otari[oa]s?|palhac[oa]s?|"
                        r"vagabund[oa]s?|safad[oa]s?|canalhas?|covardes?|hipocritas?|burr[oa]s?|babacas?|lixo|"
                        r"fracassad[oa]s?|sem vergonha|corrupt[oa]s?|bandid[oa]s?|nojent[oa]s?|ridicul[oa]s?|"
                        r"vergonha|mau carater|cretin[oa]s?|escroto|escrota|bosta|lixo humano|"
                        r"liars?|idiots?|stupid|clowns?|losers?|frauds?|morons?|pathetic|disgusting|dumbass)\b")
_ACCUSE_RX = re.compile(r"\b(?:voce|vc|tu|ce|ele|ela|voces)\s+(?:(?:e|eh|ta|esta|foi|era)\s+)?(?:um|uma)?\s*"
                        r"(?:mentiros|ladr|idiot|imbecil|otari|palhac|vagabund|safad|canalh|covard|hipocrit|burr|"
                        r"corrupt|bandid|ridicul|cretin)\w*|\b(?:voce|vc|tu|ce)\s+(?:mentiu|roubou|traiu|esta mentindo|"
                        r"ta mentindo|ta roubando|nao sabe nada|nao tem moral|nao tem vergonha)\b|"
                        r"\b(?:cala a boca|cala boca|vai se f\w*|vai tomar no \w+|sai daqui|me respeita|abaixa o tom|"
                        r"nao grita|mentira|e mentira|isso e mentira)\b|"
                        r"\byou(?:'re| are) (?:a |an |so |such a )?(?:liar|idiot|stupid|clown|loser|fraud|moron|pathetic|joke)\b|"
                        r"\b(?:you lied|stop lying|shut (?:the fuck )?up|get out|how dare you)\b")
_KIND_MULT = {"palavrao": 1.6, "polemica": 1.4, "emocao": 1.0, "surpresa": 0.8, "risada": 0.7, "impacto": 0.6,
              "gancho": 0.4}
_FILLER_EDGE = {"e", "mas", "ai", "entao", "tipo", "ne", "cara", "mano", "assim", "que", "de", "do", "da", "o", "a",
                "pra", "com", "no", "na", "um", "uma", "se", "eh", "ah", "hum", "tipo,", "ne,"}


def _word_hits(nwords: list[str]) -> list[tuple[int, int, float, str]]:
    """Acertos do lexico sobre as palavras normalizadas: (palavra_ini, palavra_fim, peso, tipo)."""
    from .. import signals as sg

    offs, pos = [], 0
    for w in nwords:
        offs.append((pos, pos + len(w)))
        pos += len(w) + 1
    text = " ".join(nwords)

    def widx(ch: int) -> int:
        return max(0, bisect.bisect_right([o[0] for o in offs], ch) - 1)

    hits: list[tuple[int, int, float, str]] = []
    for kind, pats in sg._COMPILED.items():
        mult = _KIND_MULT.get(kind, 0.5)
        for rx, w in pats:
            for m in rx.finditer(text):
                hits.append((widx(m.start()), widx(max(m.start(), m.end() - 1)), w * mult, kind))
    for rx, w, kind in ((_PROFANITY_RX, 1.3, "palavrao"), (_INSULT_RX, 1.3, "insulto"), (_ACCUSE_RX, 1.6, "acusacao")):
        for m in rx.finditer(text):
            hits.append((widx(m.start()), widx(max(m.start(), m.end() - 1)), w, kind))
    return hits


def polemic_spans(words: list, cfg=None, min_s: float = 1.5, max_s: float = 3.0, top: int = 8,
                  bonus=None) -> list[dict]:
    """Trechos de min_s a max_s segundos (alinhados a palavras) mais polemicos/explosivos: palavrao, insulto,
    acusacao, grito (CAIXA ALTA, "!"), choro, risada, punchline. Devolve [{"start","end","text","score","tipos"}]
    do melhor para o pior, sem sobreposicao, nos MESMOS tempos de `words` (lista de Word).
    bonus(a, b) -> float opcional soma sinais externos (pico de volume, comentarios, chat)."""
    from .. import signals as sg

    ws = [w for w in (words or []) if str(getattr(w, "text", "")).strip()]
    n = len(ws)
    if n == 0:
        return []
    nw = [sg.norm(w.text).strip() or "_" for w in ws]
    hits = _word_hits(nw)
    caps = [1 if (len(re.sub(r"\W", "", w.text)) >= 3 and re.sub(r"\W", "", w.text).isupper()) else 0 for w in ws]
    excl = [1 if "!" in w.text else 0 for w in ws]
    ends = [bool(re.search(r"[.!?…]$", w.text.strip())) for w in ws]
    cands: list[dict] = []
    for i in range(n):
        j = i
        while j < n and ws[j].end - ws[i].start <= max_s + 0.05:
            dur = ws[j].end - ws[i].start
            if dur >= min_s - 0.05 and j - i + 1 >= 2:
                sc = 0.0
                kinds: set[str] = set()
                for a, b, w, k in hits:
                    if a >= i and b <= j:
                        sc += w
                        kinds.add(k)
                if "insulto" in kinds and any(k in kinds for k in ("acusacao", "polemica")):
                    sc += 0.8                                    # "voce e um mentiroso"
                sc += min(0.9, 0.3 * sum(caps[i: j + 1])) + min(0.8, 0.4 * sum(excl[i: j + 1]))
                if i == 0 or ends[i - 1] or ws[i].start - ws[i - 1].end > 0.35:
                    sc += 0.3                                    # comeca no inicio da frase
                if j == n - 1 or ends[j] or (j + 1 < n and ws[j + 1].start - ws[j].end > 0.35):
                    sc += 0.3                                    # termina no fim da frase
                if nw[i].strip(",.!?") in _FILLER_EDGE:
                    sc -= 0.25
                if nw[j].strip(",.!?") in _FILLER_EDGE:
                    sc -= 0.25
                if j - i + 1 < 3:
                    sc -= 0.3
                sc -= 0.15 * abs(dur - 2.3)
                if bonus is not None:
                    try:
                        sc += float(bonus(ws[i].start, ws[j].end) or 0.0)
                    except Exception:  # noqa: BLE001
                        pass
                text = re.sub(r"\s+", " ", " ".join(w.text.strip() for w in ws[i: j + 1])).strip()
                cands.append({"start": round(ws[i].start, 3), "end": round(ws[j].end, 3), "text": text,
                              "score": round(sc, 2), "tipos": sorted(kinds)})
            j += 1
    cands.sort(key=lambda c: -c["score"])
    out: list[dict] = []
    for c in cands:
        if all(c["end"] <= o["start"] or c["start"] >= o["end"] for o in out):
            out.append(c)
        if len(out) >= top:
            break
    return out


def _tokens(s: str) -> list[str]:
    from .. import signals as sg

    return re.findall(r"[a-z0-9]+", sg.norm(s or ""))


def pick_teaser(words: list, start: float, end: float, hint_text: str = "", hint_start: float | None = None,
                cfg=None, bonus=None, min_s: float = 1.5, max_s: float = 3.0, lead: float = 4.0) -> dict | None:
    """Teaser (cold open) de um corte [start, end] no tempo de `words`: 1,5 a 3 s alinhados a palavras, comecando
    pelo menos `lead` s depois do inicio. Usa a citacao sugerida (hint_text, procurada nas palavras de verdade)
    ou o trecho mais polemico. {"start","end","text","score"} ou None. O texto e sempre o que foi dito."""
    ws = [w for w in (words or []) if w.start >= start + lead - 0.05 and w.end <= end + 0.05
          and str(w.text).strip()]
    if len(ws) < 2 or ws[-1].end - ws[0].start < min_s:
        return None
    ht = _tokens(hint_text)
    if len(ht) >= 2:
        wt = [(_tokens(w.text) or [""])[0] for w in ws]
        best = None
        L = len(ht)
        for i in range(len(ws)):
            seg = wt[i: i + L]
            if len(seg) < min(L, 2):
                break
            match = sum(1 for a, b in zip(ht, seg) if a == b)
            ratio = match / L
            if match >= 2 and ratio >= 0.6:
                dist = abs(ws[i].start - hint_start) if hint_start is not None else 0.0
                key = (ratio, -dist)
                if best is None or key > best[0]:
                    best = (key, i, min(len(ws) - 1, i + L - 1))
        if best is not None:
            _, i, j = best
            while j > i and ws[j].end - ws[i].start > max_s:
                j -= 1
            while ws[j].end - ws[i].start < min_s:
                if j + 1 < len(ws) and ws[j + 1].end - ws[i].start <= max_s:
                    j += 1
                elif i > 0 and ws[j].end - ws[i - 1].start <= max_s:
                    i -= 1
                else:
                    break
            if min_s - 0.05 <= ws[j].end - ws[i].start <= max_s + 0.05:
                return {"start": round(ws[i].start, 3), "end": round(ws[j].end, 3),
                        "text": " ".join(w.text.strip() for w in ws[i: j + 1]), "score": None, "fonte": "sugerido"}
    spans = polemic_spans(ws, cfg, min_s, max_s, top=1, bonus=bonus)
    if not spans:
        return None
    sp = dict(spans[0])
    sp["fonte"] = "polemico"
    return sp


def valid_teaser(plan: ClipPlan, lead: float = 3.5, min_s: float = 1.2, max_s: float = 3.5) -> bool:
    ts, te = plan.teaser_start, plan.teaser_end
    if ts is None or te is None:
        return False
    return plan.start + lead - 0.05 <= ts < te <= plan.end + 0.05 and min_s <= te - ts <= max_s


def coerce_raw(d: dict) -> dict | None:
    """Dicionario de cortes (chaves em pt ou en) -> formato interno."""
    if isinstance(d, ClipPlan):
        d = d.to_dict()
    start = parse_time(_first(d, "inicio", "início", "start", "inicio_s", "start_s", "ini"))
    end = parse_time(_first(d, "fim", "end", "fim_s", "end_s", "final"))
    if start is None or end is None:
        dur = parse_time(_first(d, "duracao", "duration"))
        if start is not None and dur:
            end = start + dur
        else:
            return None
    try:
        score = float(_first(d, "pontuacao", "pontuação", "score", "nota", default=60))
    except (TypeError, ValueError):
        score = 60.0
    if 0 < score < 1.0:          # veio como fracao (0.82)
        score *= 100
    part = _first(d, "parte", "part")
    try:
        part = int(part) if part not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        part = None
    series = _first(d, "serie", "série", "series")
    return {
        "start": float(start), "end": float(end),
        "title": str(_first(d, "titulo", "título", "title", default="") or ""),
        "hook": str(_first(d, "gancho", "hook", default="") or ""),
        "description": str(_first(d, "descricao", "descrição", "description", default="") or ""),
        "hashtags": _first(d, "hashtags", "tags", default=[]) or [],
        "score": max(0.0, min(100.0, score)),
        "reason": str(_first(d, "motivo", "reason", "porque", "justificativa", default="") or ""),
        "category": _first(d, "categoria", "category"),
        "tipo": str(_first(d, "tipo", default="") or "").strip().lower(),
        "series": str(series).strip() if series and str(series).strip().lower() not in ("null", "none", "nao", "não", "false") else None,
        "part": part,
        "layout": _first(d, "layout"),
        "series_name": d.get("series_name"),      # nome sugerido caso o corte vire serie ao ser dividido
        # teaser (cold open): trecho mais explosivo; o texto e procurado nas palavras de verdade
        "teaser_start": parse_time(_first(d, "teaser_inicio", "teaser_início", "teaser_start")),
        "teaser_end": parse_time(_first(d, "teaser_fim", "teaser_end")),
        "teaser_text": str(_first(d, "teaser_texto", "teaser_text", "teaser", default="") or "").strip().strip('"“”'),
    }


# ----------------------------------------------------------------------------------------
# Encaixe nos limites de palavra/frase
# ----------------------------------------------------------------------------------------
@dataclass
class _Timeline:
    seg_starts: list[float]
    seg_ends: list[float]
    w_starts: list[float]
    w_ends: list[float]
    end_punct: list[bool]          # palavra termina frase (. ? !)
    duration: float

    @classmethod
    def build(cls, tr: Transcript, duration: float) -> "_Timeline":
        words = sorted(tr.words(), key=lambda w: w.start)
        segs = sorted(tr.segments, key=lambda s: s.start)
        return cls([s.start for s in segs], [s.end for s in segs], [w.start for w in words],
                    [w.end for w in words], [bool(re.search(r"[.!?…]$", w.text.strip())) for w in words],
                    duration)

    def _prev_word_end(self, t: float) -> float | None:
        i = bisect.bisect_left(self.w_ends, t + 1e-6) - 1     # ultima palavra que termina antes de t
        return self.w_ends[i] if i >= 0 else None

    def _next_word_start(self, t: float) -> float | None:
        i = bisect.bisect_right(self.w_starts, t - 1e-6)
        return self.w_starts[i] if i < len(self.w_starts) else None

    def snap_start(self, t: float, window: float = 2.5) -> float:
        t = max(0.0, min(t, self.duration))
        cands = [s for s in self.seg_starts if t - window <= s <= t + window]
        if cands:
            # prefere o inicio de frase mais proximo (levemente a favor de comecar antes)
            base = min(cands, key=lambda s: abs(s - t) if s <= t else abs(s - t) * 1.3)
        elif self.w_starts:
            # palavra que contem t (volta pro inicio dela) ou a proxima
            i = bisect.bisect_right(self.w_starts, t) - 1
            if i >= 0 and self.w_ends[i] > t:
                base = self.w_starts[i]
            else:
                nxt = self._next_word_start(t)
                base = nxt if nxt is not None and nxt - t < 3 else t
        else:
            return t
        # respiro, sem invadir a palavra anterior
        lead = base - LEAD_IN
        prev = self._prev_word_end(base)
        if prev is not None and prev <= base:
            lead = max(lead, min(base, prev + 0.02))
        return round(max(0.0, lead), 3)

    def snap_end(self, t: float, window: float = 3.0) -> float:
        t = max(0.0, min(t, self.duration))
        cands = [e for e in self.seg_ends if t - window <= e <= t + window]
        if cands:
            base = min(cands, key=lambda e: abs(e - t) if e >= t - 0.5 else abs(e - t) * 1.3)
        elif self.w_starts:
            i = bisect.bisect_left(self.w_starts, t) - 1      # ultima palavra que comeca antes de t
            base = self.w_ends[i] if i >= 0 else t
        else:
            return t
        tail = base + TAIL
        nxt = self._next_word_start(base)
        if nxt is not None and nxt >= base:
            tail = min(tail, max(base, nxt - 0.02))
        return round(min(self.duration, tail), 3)

    def boundary_near(self, t: float, lo: float, hi: float) -> float:
        """Ponto de divisao entre duas palavras (meio da pausa) perto de t, preferindo fim de frase."""
        if not self.w_starts:
            cands = [e for e in self.seg_ends if lo <= e <= hi]
            return min(cands, key=lambda e: abs(e - t)) if cands else t
        best, best_score = None, -1e9
        i0 = max(0, bisect.bisect_left(self.w_ends, lo) - 1)
        for i in range(i0, len(self.w_ends) - 1):
            e = self.w_ends[i]
            if e > hi:
                break
            if e < lo:
                continue
            gap = max(0.0, self.w_starts[i + 1] - e)
            sc = (2.0 if self.end_punct[i] else 0.0) + min(gap, 1.5) * 2 - abs(e - t) / 6.0
            if e in self._seg_end_set():
                sc += 1.0
            if sc > best_score:
                best, best_score = (e + self.w_starts[i + 1]) / 2 if gap < 0.8 else e + 0.3, sc
        return round(best, 3) if best is not None else t

    def _seg_end_set(self):
        if not hasattr(self, "_se"):
            self._se = set(self.seg_ends)
        return self._se

    def end_at_or_before(self, limit: float, after: float) -> float | None:
        """Maior fim de frase <= limit (e > after)."""
        cands = [e for e in self.seg_ends if after < e <= limit]
        if cands:
            return max(cands)
        i = bisect.bisect_right(self.w_ends, limit) - 1
        if i >= 0 and self.w_ends[i] > after:
            return self.w_ends[i]
        return None

    def end_at_or_after(self, limit: float) -> float | None:
        cands = [e for e in self.seg_ends if e >= limit]
        return min(cands) if cands else None


# ----------------------------------------------------------------------------------------
# Limites e pos-processamento
# ----------------------------------------------------------------------------------------
@dataclass
class _Group:
    parts: list[tuple[float, float]]
    meta: dict
    score: float
    series: str | None = None
    titles: list[str] = field(default_factory=list)

    @property
    def start(self) -> float:
        return self.parts[0][0]

    @property
    def end(self) -> float:
        return self.parts[-1][1]


def _cfg_get(cfg, key, default):
    try:
        v = cfg.get(key, default) if cfg is not None else default
    except Exception:
        v = default
    return default if v is None else v


def auto_clip_count(duration: float) -> int:
    m = duration / 60.0
    for lim, n in ((3, 1), (6, 2), (12, 3), (20, 4), (40, 5), (60, 6), (120, 8)):
        if m < lim:
            return n
    return 10


def resolve_limit(cfg, video: Candidate | None, transcript: Transcript | None, max_clips: int | None = None) -> int:
    dur = max(float((video.duration if video else 0) or 0), transcript.duration if transcript else 0.0)
    per = _cfg_get(cfg, "execucao.cortes_por_video", "auto")
    if max_clips:
        lim = int(max_clips)
        if str(per).strip().isdigit():
            lim = min(lim, int(per))
        elif str(per).strip().lower() == "auto":
            lim = min(lim, auto_clip_count(dur))
    elif str(per).strip().isdigit():
        lim = int(per)
    else:
        lim = auto_clip_count(dur)
    return max(1, lim)


def _split_span(tl: _Timeline, a: float, b: float, dmin: float, dmax: float, dpart: float,
                max_parts: int) -> list[tuple[float, float]]:
    length = b - a
    n = max(1, round(length / dpart))
    while n < max_parts and length / n > dmax:
        n += 1
    while n > 1 and length / n < dmin:
        n -= 1
    if n > max_parts:
        n = max_parts
    if length / n > dmax - 3:                    # nao cabe: encurta o assunto (folga para ajustar as emendas)
        unit = min(dpart, dmax - 3)
        b = tl.end_at_or_before(a + n * unit, a + dmin) or (a + n * unit)
        length = b - a
    bounds = [a]
    # a emenda pode andar ate `win` s para cair entre palavras, sem nenhuma parte passar de dmax
    win = max(0.0, min(8.0, length / n / 4, (dmax - length / n) / 2))
    for k in range(1, n):
        t = a + k * length / n
        bounds.append(tl.boundary_near(t, t - win, t + win))
    bounds.append(b)
    return [(bounds[i], bounds[i + 1]) for i in range(n)]


def _fit_single(tl: _Timeline, s: float, e: float, dmin: float, dmax: float) -> tuple[float, float] | None:
    if e - s > dmax:
        ne = tl.end_at_or_before(s + dmax - TAIL, s + dmin)
        e = tl.snap_end(ne) if ne else s + dmax
        if e - s > dmax:
            e = s + dmax
    if e - s < dmin:
        ne = tl.end_at_or_after(s + dmin - TAIL)
        if ne is not None and tl.snap_end(ne) - s <= dmax:
            e = tl.snap_end(ne)
        if e - s < dmin:                         # fim do video: puxa o inicio para tras
            ns = max(0.0, e - max(dmin, min(dmax, (dmin + dmax) / 2)))
            s = tl.snap_start(ns)
            if e - s > dmax:
                s = e - dmax
        if e - s < dmin * 0.8:
            return None
    return round(s, 3), round(e, 3)


def finalize_plans(raw_plans: list[dict | ClipPlan], video: Candidate, transcript: Transcript, cfg,
                   max_clips: int | None = None, teaser_bonus=None) -> list[ClipPlan]:
    """...e escolhe o teaser de cada corte (teaser_start/teaser_end/teaser_text: 1,5 a 3 s, palavras inteiras,
    pelo menos ~4 s depois do inicio): a citacao sugerida pelo motor, se existir de verdade na transcricao,
    senao o trecho mais polemico (polemic_spans + teaser_bonus(a, b) opcional com sinais externos).
    Titulo, gancho e descricao passam por mask_profanity (conteudo.palavroes)."""
    dmin = float(_cfg_get(cfg, "corte.duracao_min_s", 25))
    dmax = float(_cfg_get(cfg, "corte.duracao_max_s", 90))
    dpart = float(_cfg_get(cfg, "corte.duracao_parte_s", 65))
    max_parts = int(_cfg_get(cfg, "corte.max_partes", 5))
    min_score = float(_cfg_get(cfg, "corte.pontuacao_minima", 55))
    allow_series = bool(_cfg_get(cfg, "corte.permitir_series", True))
    dpart = max(dmin, min(dpart, dmax))
    limit = resolve_limit(cfg, video, transcript, max_clips)

    if transcript and transcript.segments:
        dur = transcript.duration + 0.5
        if video and video.duration:
            dur = min(dur, float(video.duration))
    else:
        dur = float(video.duration or 0)
    if dur <= 0:
        return []
    tl = _Timeline.build(transcript or Transcript(), dur)
    all_words = transcript.words() if transcript else []
    if not all_words and transcript:     # legenda sem tempo por palavra: palavras espalhadas no segmento
        for sgm in transcript.segments:
            toks = sgm.text.split()
            step = (sgm.end - sgm.start) / max(1, len(toks))
            all_words += [Word(sgm.start + k * step, sgm.start + (k + 1) * step, tk) for k, tk in enumerate(toks)]

    items = [x for x in (coerce_raw(r) for r in raw_plans if isinstance(r, (dict, ClipPlan))) if x]
    # ---- agrupa series vindas do motor
    groups: list[_Group] = []
    series_map: dict[str, list[dict]] = {}
    singles: list[dict] = []
    for it in items:
        it["start"] = max(0.0, min(float(it["start"]), dur))
        it["end"] = max(0.0, min(float(it["end"]), dur))
        if it["end"] - it["start"] < 3:
            continue
        if it.get("series") and allow_series:
            series_map.setdefault(slugify(it["series"], 40), []).append(it)
        else:
            singles.append(it)
    for key, lst in series_map.items():
        lst.sort(key=lambda x: (x.get("part") or 0, x["start"]))
        if len(lst) == 1:
            singles.append(lst[0])
            continue
        a, b = lst[0]["start"], max(x["end"] for x in lst)
        s0 = tl.snap_start(a)
        e0 = tl.snap_end(b)
        # fronteiras do motor, unificadas num ponto entre palavras (partes contiguas)
        bounds = [s0]
        for prev, nxt in zip(lst, lst[1:]):
            t = (prev["end"] + nxt["start"]) / 2
            bounds.append(tl.boundary_near(t, t - 4, t + 4))
        bounds.append(e0)
        bounds = sorted(set(bounds))
        parts = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1) if bounds[i + 1] - bounds[i] > 1]
        # parte longa demais -> divide; parte curta demais -> junta com a vizinha
        fixed: list[tuple[float, float]] = []
        for ps, pe in parts:
            if pe - ps > dmax:
                fixed.extend(_split_span(tl, ps, pe, dmin, dmax, dpart, max_parts))
            elif fixed and pe - ps < dmin and pe - fixed[-1][0] <= dmax:
                fixed[-1] = (fixed[-1][0], pe)
            else:
                fixed.append((ps, pe))
        if len(fixed) > 1 and fixed[-1][1] - fixed[-1][0] < dmin and fixed[-1][1] - fixed[-2][0] <= dmax:
            fixed[-2:] = [(fixed[-2][0], fixed[-1][1])]
        fixed = fixed[:max_parts]
        best = max(lst, key=lambda x: x["score"])
        meta = dict(lst[0])
        meta["score"] = max(x["score"] for x in lst)
        for k in ("hashtags", "category", "layout", "reason", "description"):
            if not meta.get(k):
                meta[k] = best.get(k)
        groups.append(_Group(fixed, meta, meta["score"], series=lst[0]["series"],
                             titles=[x.get("title", "") for x in lst]))

    for it in singles:
        s = tl.snap_start(it["start"])
        e = tl.snap_end(it["end"])
        if e <= s:
            continue
        if e - s > dmax * 1.15 and allow_series and max_parts > 1:
            parts = _split_span(tl, s, e, dmin, dmax, dpart, max_parts)
            if len(parts) > 1:
                groups.append(_Group(parts, it, it["score"],
                                     series=it.get("series_name") or it.get("series") or it.get("title") or "serie"))
                continue
        fit = _fit_single(tl, s, e, dmin, dmax)
        if fit:
            groups.append(_Group([fit], it, it["score"]))

    if not groups:
        return []

    # ---- remove sobreposicoes (maior pontuacao primeiro)
    groups.sort(key=lambda g: -g.score)
    kept: list[_Group] = []
    for g in groups:
        ok = True
        for k in kept:
            ov = min(g.end, k.end) - max(g.start, k.start)
            if ov <= 0.05:
                continue
            if len(g.parts) == 1 and ov < 0.35 * (g.end - g.start):
                # sobreposicao pequena: apara o corte de menor pontuacao
                s, e = g.parts[0]
                if s < k.start:
                    e = tl.end_at_or_before(k.start - 0.05, s) or k.start - 0.05
                    e = min(tl.snap_end(e), k.start)
                else:
                    s = max(tl.snap_start(k.end + 0.1), k.end)
                if e - s >= dmin:
                    g.parts = [(round(s, 3), round(e, 3))]
                    continue
            ok = False
            break
        if ok:
            kept.append(g)

    # ---- pontuacao minima (mantem pelo menos o melhor)
    good = [g for g in kept if g.score >= min_score]
    if not good:
        good = kept[:1]

    # ---- limite de cortes (cada parte conta como um corte)
    chosen: list[_Group] = []
    count = 0
    for g in good:
        room = limit - count
        if room <= 0:
            break
        if len(g.parts) <= room:
            chosen.append(g)
            count += len(g.parts)
        elif len(g.parts) > 1 and room >= 2:
            g.parts = g.parts[:room]
            g.meta["_truncated"] = True          # assunto continua: ultima parte nao e "final"
            chosen.append(g)
            count += room
        elif not chosen:
            g.parts = g.parts[:1]
            g.series = None
            p = g.parts[0]
            fit = _fit_single(tl, p[0], p[1], dmin, dmax)
            if fit:
                g.parts = [fit]
            chosen.append(g)
            count += 1

    # ---- monta os ClipPlans
    base_id = f"{slugify(video.title or video.id)[:30].rstrip('-')}-{short_hash(video.id, 6)}"
    emo = emojis_enabled(cfg)
    fix = (lambda x: clean_punct(x)) if emo else (lambda x: clean_punct(strip_emojis(x)))
    n_emo = max_title_emojis(cfg)
    fix_title = (lambda x: limit_emojis(fix(x), n_emo)) if emo else fix  # 1-2 emojis no titulo (3 no modo besta)
    fix_hook = (lambda x: limit_emojis(fix(x), 1)) if emo else fix       # no maximo 1 no gancho
    out: list[ClipPlan] = []
    n = 0
    for g in chosen:
        m = g.meta
        total = len(g.parts)
        is_series = total > 1
        title0 = clean_title(fix_title(str(m.get("title") or "")) or fix(video.title or "") or "Corte")
        from . import prompts as _pr

        if _pr.is_generic(title0) and _tipo(m, video) in ("tutorial", "curiosidade", "noticia"):
            title0 = clean_title(fix_title(video.title or "") or title0)
        hook0 = short_hook(fix_hook(str(m.get("hook") or ""))) or short_hook(_EMOJI_TAIL.sub("", title0))
        series_name = (str(g.series).strip()[:60] if is_series and g.series else None)
        if is_series and series_name:
            series_name = fix(series_name)
            series_name = (_EMOJI_TAIL.sub("", _PART_RX.sub("", series_name)).strip().strip('"“”').strip()
                           or _EMOJI_TAIL.sub("", title0))
        for k, (s, e) in enumerate(g.parts, 1):
            n += 1
            if is_series:
                src_title = g.titles[k - 1] if k - 1 < len(g.titles) and g.titles[k - 1] else title0
                title = series_title(clean_title(fix_title(src_title) or title0, 80), k,
                                     None if m.get("_truncated") else total)
                hook = hook0 if k == 1 else short_hook(f"PARTE {k}: {hook0}", 60)
            else:
                title, hook = title0, hook0
            title = polish_title(title, normalize_category(m.get("category")), n_emo if emo else 0, video.title or "")
            out.append(ClipPlan(
                id=f"{base_id}-{int(s)}s{int(round(e - s))}",
                source_id=video.id,
                start=round(s, 3),
                end=round(e, 3),
                title=title,
                hook=hook,
                description=fix(str(m.get("description") or ""))[:600].strip(),
                hashtags=normalize_hashtags(m.get("hashtags")),
                score=round(float(g.score) - (0.01 * (k - 1) if is_series else 0.0), 2),
                reason=fix(str(m.get("reason") or ""))[:400].strip(),
                category=normalize_category(m.get("category")),
                series=series_name if is_series else None,
                part=k if is_series else None,
                parts_total=total if is_series else None,
                layout=normalize_layout(m.get("layout")),
                tipo=_tipo(m, video),
            ))
            p = out[-1]
            try:
                tz = pick_teaser(all_words, p.start, p.end, hint_text=str(m.get("teaser_text") or ""),
                                 hint_start=m.get("teaser_start"), cfg=cfg, bonus=teaser_bonus)
            except Exception as e:  # noqa: BLE001  (teaser e opcional)
                logger.debug("teaser falhou: %s", e)
                tz = None
            if tz:
                p.teaser_start, p.teaser_end, p.teaser_text = tz["start"], tz["end"], clean_punct(tz["text"])
                if not valid_teaser(p):
                    p.teaser_start, p.teaser_end, p.teaser_text = None, None, ""
    pmode = profanity_mode(cfg)
    for p in out:
        p.title = mask_profanity(p.title, pmode) or p.title
        hk = mask_profanity(p.hook, pmode)
        p.hook = hk if re.search(r"\w", hk or "") else short_hook(_EMOJI_TAIL.sub("", p.title))
        p.description = mask_profanity(p.description, pmode)
    return out


def _tipo(m: dict, video) -> str:
    from . import prompts

    t = str(m.get("tipo") or "")
    return t if t in prompts.TIPOS else prompts.infer_tipo(video, normalize_category(m.get("category")))


def finalize_trends(raw: list[dict], trends: list[Trend], limit: int = 15) -> list[Trend]:
    """Aplica a resposta do motor ({indice, categoria, pontuacao, motivo, buscas}) nos Trends originais."""
    out: list[Trend] = []
    seen: set[int] = set()
    for r in raw:
        try:
            idx = int(_first(r, "indice", "índice", "index", "id", "n"))
        except (TypeError, ValueError):
            topic = str(_first(r, "assunto", "tema", "topic", default="")).strip().lower()
            idx = next((i + 1 for i, t in enumerate(trends) if t.topic.strip().lower() == topic), 0)
        if not (1 <= idx <= len(trends)) or idx in seen:
            continue
        seen.add(idx)
        t = trends[idx - 1]
        queries = _first(r, "buscas", "queries", "consultas", default=[]) or []
        if isinstance(queries, str):
            queries = [q for q in re.split(r"[;\n]", queries) if q.strip()]
        qs: list[str] = []
        for q in queries:
            q = clean_punct(strip_emojis(re.sub(r"\s+", " ", str(q)))).strip().strip('"')[:80]
            if q and q.lower() not in [x.lower() for x in qs]:
                qs.append(q)
        if not qs:
            qs = [t.topic, f"{t.topic} ao vivo"]
        try:
            score = float(_first(r, "pontuacao", "pontuação", "score", default=t.score))
        except (TypeError, ValueError):
            score = t.score
        if 0 < score <= 1:
            score *= 100
        out.append(replace(t, category=normalize_category(_first(r, "categoria", "category")) or t.category,
                           score=round(max(0.0, min(100.0, score)), 1),
                           reason=clean_punct(strip_emojis(str(_first(r, "motivo", "reason", default=t.reason) or "")))[:300],
                           queries=qs[:3]))
    out.sort(key=lambda t: -t.score)
    return out[:limit]


def time_chunks(tr: Transcript, max_chars: int, overlap_s: float = 30.0, max_s: float | None = None) -> list[Transcript]:
    """Divide a transcricao em blocos (tempos originais) com no maximo `max_chars` de texto carimbado."""
    chunks: list[Transcript] = []
    segs = tr.segments
    i = 0
    while i < len(segs):
        size = 0
        j = i
        while j < len(segs):
            add = len(segs[j].text) + 9
            if j > i and (size + add > max_chars or (max_s and segs[j].end - segs[i].start > max_s)):
                break
            size += add
            j += 1
        chunks.append(Transcript(segs[i:j], tr.language, tr.source))
        if j >= len(segs):
            break
        # volta um pouco para nao perder um corte que cruza a fronteira
        k = j
        while k > i + 1 and segs[j].start - segs[k - 1].start < overlap_s:
            k -= 1
        i = max(i + 1, k)
    return chunks
