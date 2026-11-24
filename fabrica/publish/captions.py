"""Monta titulo e descricao/legenda de cada post (YouTube Shorts e TikTok).

    build_post_text(plan, platform, cfg, video_title=None, channel=None) -> (titulo, descricao)

YouTube: titulo <= 100 (citacao e 1 a 2 emojis do plano, "(LEGENDADO)" e "(Parte X/Y)" no fim);
descricao = gancho + contexto + CTA + "Fonte: canal" + rodape + hashtags (com #Shorts).
TikTok: legenda = titulo + contexto curto + CTA + "Fonte: canal" + hashtags (ultima linha, ate 5).
Hashtags e CTA: fabrica/hashtags.py. Regras e fontes: docs/HASHTAGS.md.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from .. import hashtags as htags
from ..log import get as get_log
from ..models import ClipPlan

log = get_log(__name__)

YT_TITLE_MAX = 100
YT_DESC_MAX = 5000
TT_CAPTION_MAX = 2200          # limite da API/agendadores; o app aceita 4000, ficamos no menor
TT_TITLE_MAX = 150             # primeira linha da legenda do TikTok
YT_CONTEXT_MAX = 700
TT_CONTEXT_MAX = 150
TITLE_EMOJIS_MAX = 2
# O YouTube ignorava todas as hashtags acima de 15 (a ajuda atual fala em 60); ficamos bem abaixo
YT_MAX_HASHTAGS = 15

# Emojis: pictogramas, simbolos/dingbats, bandeiras, tons de pele, keycaps, ZWJ e seletores de variacao.
_EMOJI_RE = re.compile(
    r"(?:[0-9#*]️?⃣)"                       # keycaps (1 + FE0F + 20E3)
    r"|[\U0001F000-\U0001FAFF]"                       # pictogramas, emoticons, transporte, bandeiras, tons de pele
    r"|[\U000E0020-\U000E007F]"                       # tags (bandeiras de subdivisao)
    r"|[☀-➿]"                               # simbolos diversos + dingbats
    r"|[⌚⌛⌨⏏⏩-⏳⏸-⏺]"
    r"|[⬅-⬇⬛⬜⭐⭕]"
    r"|[↔-↙↩↪▪▫▶◀◻-◾]"
    r"|[〰〽㊗㊙‼⁉ℹⓂ]"
    r"|[©®™]️"                    # (c) (r) TM so quando vierem como emoji
    r"|[‍︎️⃣]"                    # ZWJ, seletores de variacao, keycap solto
)
# Um emoji "visivel" inteiro (com tom de pele, seletor e sequencias ZWJ), para contar/limitar
_EMO_BASE = (r"[\U0001F000-\U0001FAFF☀-➿⌚⌛⌨⏏⏩-⏳⏸-⏺"
             r"⬅-⬇⬛⬜⭐⭕〰〽㊗㊙‼⁉]")
_EMO_MOD = r"[︎️\U0001F3FB-\U0001F3FF⃣]*"
_ONE_EMOJI_RE = re.compile(r"[\U0001F1E6-\U0001F1FF]{2}|[0-9#*]️?⃣|"
                           + _EMO_BASE + _EMO_MOD + r"(?:‍" + _EMO_BASE + _EMO_MOD + r")*")


def strip_emojis(text: str | None) -> str:
    """Remove emojis (inclui sequencias com ZWJ, tons de pele, bandeiras e keycaps) e arruma os espacos."""
    if not text:
        return ""
    out = _EMOJI_RE.sub("", text)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = "\n".join(line.strip() for line in out.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def limit_emojis(text: str | None, n: int) -> str:
    """Mantem no maximo n emojis diferentes (o mesmo emoji repetido conta uma vez e some na repeticao)."""
    seen: list[str] = []

    def repl(m: re.Match) -> str:
        e = m.group(0)
        if e in seen or len(seen) >= n:
            return ""
        seen.append(e)
        return e

    out = _ONE_EMOJI_RE.sub(repl, text or "")
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def emojis_allowed(cfg: Any) -> bool:
    """Emojis nos posts: ligado por padrao (conteudo.emojis: true). Nunca em mensagens de terminal/log."""
    if cfg is None:
        return True
    v = cfg.get("conteudo.emojis", True)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "sim", "yes", "on")
    return bool(v)


# "Parte 2", "(parte 3, final)", "parte 2 de 3", "Pt. 2/3", "part 1"
_PART_RE = re.compile(r"[\(\[]?\s*\b(?:parte|part|pt\.?)\s*\d+\s*(?:/\s*\d+|de\s*\d+)?\s*(?:,\s*final)?\s*[\)\]]?",
                      re.I)
_LEG_RE = re.compile(r"[\(\[]?\s*\blegendado\b\s*[\)\]]?", re.I)
_TAG_CLEAN_RE = re.compile(r"[^\w]", re.UNICODE)


# Regra do dono: nada de travessao, meia-risca, marcador ou ponto medio nos posts.
_DASHES_RE = re.compile(r"[ \t]*[\u2014\u2013\u2012\u2015][ \t]*")
_BULLET_LINE_RE = re.compile(r"^[ \t]*[\u2022\u00b7\u2027\u2219][ \t]*", re.M)
_DOTS_RE = re.compile(r"[ \t]*[\u2022\u00b7\u2027\u2219][ \t]*")


def fix_punct(text: str | None) -> str:
    """Travessao/meia-risca -> " - "; marcador no inicio da linha -> "- "; ponto medio/marcador no meio -> ", "."""
    if not text:
        return ""
    text = _DASHES_RE.sub(" - ", text)
    text = _BULLET_LINE_RE.sub("- ", text)
    text = _DOTS_RE.sub(", ", text)
    return text.replace("…", "...")


def _clean(text: str | None) -> str:
    """Remove < > (o YouTube recusa), caracteres de controle, pontuacao proibida e espacos repetidos."""
    text = fix_punct((text or "").replace("<", "").replace(">", ""))
    text = "".join(ch for ch in text if ch in "\n" or unicodedata.category(ch)[0] != "C"
                   or ch in "‍️")  # mantem ZWJ / seletor de variacao dos emojis
    text = re.sub(r"[ \t]+", " ", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def _one_line(text: str | None) -> str:
    return re.sub(r"\s+", " ", _clean(text)).strip()


def _cut(text: str, limit: int) -> str:
    """Corta sem quebrar emoji/palavra quando possivel e adiciona reticencias."""
    if len(text) <= limit:
        return text
    cut = text[: max(0, limit - 3)]  # espaco para "..."
    # nao deixa um ZWJ/seletor solto no fim
    while cut and unicodedata.category(cut[-1]) in ("Mn", "Cf"):
        cut = cut[:-1]
    sp = cut.rfind(" ")
    if sp >= limit * 0.6:
        cut = cut[:sp]
    return cut.rstrip(" -,.;:") + "..."


def style(cfg: Any, plan: ClipPlan | None = None) -> dict:
    """Tom efetivo do post (fabrica/tom.py, com teto por nicho: politica/noticias no maximo "polemico").
    {nivel, intensidade 0-4, palavroes mascarar|mostrar|remover, max_emojis}."""
    lv = htags.tone(cfg, plan)
    s = htags.tone_settings(cfg)
    if lv == s.get("nivel"):
        out = {"nivel": lv, "intensidade": int(s.get("intensidade", 2)), "palavroes": s.get("palavroes"),
               "max_emojis": int(s.get("max_emojis", TITLE_EMOJIS_MAX) or TITLE_EMOJIS_MAX)}
    else:  # nivel rebaixado pelo nicho
        conf = str(cfg.get("conteudo.palavroes", "mascarar") if cfg is not None else "mascarar")
        out = {"nivel": lv, "intensidade": htags.TONES.index(lv),
               "palavroes": "remover" if lv == "neutro" else ("mascarar" if conf == "mostrar" else conf),
               "max_emojis": 1 if lv == "neutro" else TITLE_EMOJIS_MAX}
    out["palavroes"] = str(out.get("palavroes") or "mascarar").strip().lower()
    if plan is not None and out["palavroes"] == "mostrar" and htags.tone_capped(plan):
        out["palavroes"] = "mascarar"  # politica/noticias: nunca palavrao sem mascara
    out["max_emojis"] = max(1, min(3, out["max_emojis"]))
    return out


def mask_profanity(text: str | None, cfg: Any, mode: str | None = None) -> str:
    """Palavrao: mascarar (p*rra) | mostrar | remover. O modo vem do tom (modo_besta = mostrar, neutro =
    remover) ou de conteudo.palavroes. Usa o mesmo lexico do cerebro."""
    if not text:
        return text or ""
    if mode is None:
        mode = style(cfg).get("palavroes") if cfg is not None else "mascarar"
    try:
        from ..brain.base import mask_profanity as _mask
    except Exception:  # pragma: no cover - cerebro indisponivel nao pode travar o post
        return text
    out = _mask(text, mode or "mascarar")
    return re.sub(r"[ 	]{2,}", " ", out)


def mask_unspoken(text: str, source: str, mode: str) -> str:
    """Palavrao que NAO esta no texto do corte (ex.: veio da IA) sai mascarado mesmo no modo mostrar."""
    if not text:
        return text
    try:
        from ..brain.base import _PROFANITY_RX
    except Exception:  # pragma: no cover
        return mask_profanity(text, None, "mascarar")
    src = " " + _words(source) + " "

    def repl(m: re.Match) -> str:
        w = m.group(0)
        if mode == "mostrar" and f" {_words(w)} " in src:
            return w
        if mode == "remover":
            return ""
        return w[0] + "*" + w[2:] if len(w) >= 3 else w[0] + "*"

    return re.sub(r"[ 	]{2,}", " ", _PROFANITY_RX.sub(repl, text)).strip()


def normalize_hashtag(tag: str) -> str | None:
    """'gta 6' -> '#gta6'; '#Neymar!' -> '#neymar'. Devolve None se ficar vazio."""
    return htags.normalize(tag)


def collect_hashtags(plan: ClipPlan, cfg: Any, platform: str, video_title: str | None = None,
                     channel: str | None = None) -> list[str]:
    """Hashtags finais do post (compatibilidade): ver hashtags.choose."""
    return htags.choose(plan, (platform or "").lower(), cfg, video_title=video_title, channel=channel)


def part_suffix(plan: ClipPlan) -> str:
    if plan.part and plan.parts_total and plan.parts_total > 1:
        return f"(Parte {plan.part}/{plan.parts_total})"
    if plan.part and plan.part > 1:
        return f"(Parte {plan.part})"
    return ""


def _tidy(t: str) -> str:
    t = re.sub(r"\(\s*\)|\[\s*\]", "", t)
    t = re.sub(r"[ \t]{2,}", " ", t).strip()
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    return t.strip(" -|:,")


def post_title(plan: ClipPlan, cfg: Any, limit: int = YT_TITLE_MAX, emojis: bool | None = None,
               lang: str | None = None) -> str:
    """Titulo do post: mantem citacao e ate 2 emojis do plano (3 no modo_besta), trata palavrao conforme o
    tom, tira "Parte N" duplicado
    e poe "(LEGENDADO)" e "(Parte X/Y)" no fim (nunca cortados)."""
    emojis = emojis_allowed(cfg) if emojis is None else emojis
    st = style(cfg, plan) if cfg is not None else {"palavroes": "mascarar", "max_emojis": TITLE_EMOJIS_MAX}

    def prep(t: str | None) -> str:
        t = mask_profanity(_one_line(t), cfg, st["palavroes"])
        t = limit_emojis(t, st["max_emojis"]) if emojis else _one_line(strip_emojis(t))
        return _tidy(t) if t else ""

    title = prep(plan.title) or prep(plan.hook) or "Corte"
    suffixes: list[str] = []
    mark = cfg.get("conteudo.marcar_legendado", True) if cfg is not None else True
    if (lang or "LEGENDADO" in title.upper()) and mark:
        title = _tidy(_LEG_RE.sub(" ", title)) or title
        suffixes.append("(LEGENDADO)")
    suffix_part = part_suffix(plan)
    if suffix_part:
        title = _tidy(_PART_RE.sub(" ", title)) or title  # tira "Parte 1" que o cerebro ja tenha posto
        suffixes.append(suffix_part)
    if suffixes:
        tail = " ".join(suffixes)
        return _cut(title, limit - len(tail) - 1) + " " + tail
    return _cut(title, limit)


def _title_with_part(plan: ClipPlan, limit: int, emojis: bool = True) -> str:
    """Compatibilidade com o nome antigo."""
    return post_title(plan, None, limit, emojis)


def _source_line(cfg: Any, channel: str | None, video_title: str | None) -> str:
    if not cfg.get("publicacao.creditar_fonte", True):
        return ""
    ch = _one_line(channel)
    if not ch:
        return ""
    vt = mask_profanity(_one_line(video_title), cfg, "remover" if style(cfg).get("palavroes") == "remover"
                        else "mascarar")
    line = f"Fonte: {ch}"
    if vt:
        line += f' - "{_cut(vt, 80)}"'
    return line


def _words(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore")
                  .decode("ascii")).strip()


def _hook_line(plan: ClipPlan, title: str, cfg: Any, emojis: bool, st: dict | None = None) -> str:
    """Gancho da descricao: so se nao repetir o titulo; gancho todo em CAPS vira frase normal
    (no super_polemico e no modo_besta o CAPS fica)."""
    st = st or style(cfg, plan)
    hook = mask_profanity(_one_line(plan.hook), cfg, st["palavroes"])
    hook = limit_emojis(hook, 1) if emojis else _one_line(strip_emojis(hook))
    if not hook:
        return ""
    wh, wt = _words(hook), _words(title)
    if not wh or wh in wt:
        return ""
    letters = [c for c in hook if c.isalpha()]
    if st["intensidade"] < 3 and len(letters) > 10 and sum(c.isupper() for c in letters) / len(letters) > 0.8:
        i = next((k for k, c in enumerate(hook) if c.isalpha()), 0)
        hook = hook[:i] + hook[i].upper() + hook[i + 1:].lower()
    return hook


def _context(plan: ClipPlan, title: str, cfg: Any, emojis: bool, lang: str | None, limit: int,
             one_line: bool, st: dict | None = None) -> str:
    """Contexto curto (descricao do cerebro) + nota de traducao para cortes legendados."""
    st = st or style(cfg, plan)
    desc = mask_profanity(_one_line(plan.description) if one_line else _clean(plan.description), cfg,
                          st["palavroes"])
    if not emojis:
        desc = strip_emojis(desc)
    if desc and _words(desc) and _words(desc) in _words(title):
        desc = ""
    note = ""
    if lang:
        name = htags.LANG_NAMES.get(lang)
        note = f"Original em {name}, com legenda em português." if name else "Com legenda em português."
    if desc and note:
        desc = _cut(desc, max(20, limit - len(note) - 1))
        sep = " " if desc.endswith((".", "!", "?")) else ". "
        return desc + sep + note
    return _cut(desc, limit) if desc else note


# ---------------------------------------------------------------------------------------- IA (opcional)
_AI_CACHE: dict[str, dict] = {}
_AI_FORBIDDEN = re.compile(r"(?i)\b(curt[aei]\w*|like|likes|segue|sigam|seguir|inscrev\w*|sininho|link na bio)\b|#|@|https?:")
AI_SYSTEM = ("Você escreve o texto de posts de cortes (YouTube Shorts e TikTok) para o público jovem brasileiro. "
             "Português do Brasil, natural, sem exagero de gíria. Responda só com JSON.")
AI_SCHEMA = {"type": "object", "properties": {"linha": {"type": "string"}, "pergunta": {"type": "string"}},
             "required": ["linha", "pergunta"]}


_AI_LIMITS = ("Limites absolutos: nada que não esteja no título/contexto; nunca insinue crime, traição, caso amoroso, "
              "ato sexual ou droga sobre pessoa real; nada sexual envolvendo menor; nada de ódio, xingamento ou "
              "ataque a grupo; nada enganoso.")
# termos que so podem aparecer no texto da IA se ja estiverem no proprio corte (anti-insinuacao inventada)
_SENSITIVE = ("trai", "traicao", "traiu", "chifre", "amante", "caso com", "ficou com", "pegou", "transa", "sexo",
              "sexual", "nude", "nudes", "pelad", "motel", "gravid", "preso", "presa", "prisao", "cadeia", "crime",
              "roubou", "roubo", "ladra", "corrup", "propina", "lavagem", "droga", "cocaina", "maconha", "drogad",
              "bebad", "assedi", "abuso", "estupr", "pedof", "menor de idade", "novinha", "novinho", "golpe")
_ALWAYS_BLOCK = ("pedof", "estupr", "novinha", "novinho", "menor de idade")


def _tone_block(cfg: Any, plan: ClipPlan) -> str:
    """Guia do tom para a IA (fabrica/tom.py); com o teto por nicho aplicado."""
    lv = htags.tone(cfg, plan)
    try:
        from .. import tom as tom_mod
        if lv == tom_mod.level(cfg):
            return tom_mod.prompt_block(cfg)
        return f"TOM ({lv}): {tom_mod.GUIDE[lv]}\n{tom_mod.FLOOR}"
    except Exception:
        return f"TOM ({lv})."


def _ai_prompt(plan: ClipPlan, title: str, hook: str, context: str, tone_block: str = "") -> str:
    return (
        f"Título do corte: {strip_emojis(title)}\n"
        f"Gancho na tela: {strip_emojis(plan.hook or '')}\n"
        f"Contexto: {strip_emojis(context or plan.description or '')[:400]}\n"
        f"Categoria: {plan.category or 'geral'}\n\n"
        'Devolva {"linha": "...", "pergunta": "..."}.\n'
        "linha: 1 frase de até 120 caracteres que puxa a curiosidade sobre o momento; comece pelo nome da pessoa, "
        "programa ou jogo se houver; no máximo 1 emoji, sem hashtag, sem travessão.\n"
        "pergunta: até 80 caracteres, CTA dirigida a quem assiste, que dá para responder com uma palavra ou emoji; "
        "nunca peça like, follow, inscrição ou compartilhamento.\n"
        f"{tone_block}\n{_AI_LIMITS}"
    )


def _grounded(text: str, source: str) -> bool:
    """Texto da IA so pode tocar em tema sensivel (traicao, crime, sexo, droga...) se o corte ja falar disso."""
    t, s = f" {_words(text)} ", f" {_words(source)} "
    for term in _SENSITIVE:
        if f" {term}" in t and (term in _ALWAYS_BLOCK or f" {term}" not in s):
            return False
    return True


def _ask_ai(plan: ClipPlan, cfg: Any, title: str, hook: str, context: str) -> dict:
    """Pede a linha e a pergunta ao cerebro disponivel (Claude CLI ou Ollama). {} se nao der."""
    from ..brain import extract_json, get_brain

    brain = get_brain(cfg)
    prompt = _ai_prompt(plan, title, hook, context, _tone_block(cfg, plan))
    timeout = float(cfg.get("conteudo.legenda_post_ia_timeout_s", 90) or 90)
    if brain.name == "claude":
        txt = brain._run(prompt, AI_SYSTEM, timeout=timeout)
    elif brain.name == "ollama":
        txt = brain.chat(prompt, AI_SYSTEM, schema=AI_SCHEMA, timeout=timeout, num_predict=200)
    else:
        return {}
    data = extract_json(txt)
    return data if isinstance(data, dict) else {}


def _valid_ai(s: Any, max_len: int, cfg: Any, emojis: bool, source: str = "", st: dict | None = None) -> str:
    """Texto da IA: limites, sem pedido de like/follow, sem insinuacao sem base no corte, palavrao so
    sem mascara se foi dito no corte (modo_besta), CAPS total so no super_polemico/modo_besta."""
    if not isinstance(s, str):
        return ""
    st = st or {"palavroes": "mascarar", "intensidade": 2}
    t = mask_unspoken(_one_line(s), source, st["palavroes"]).strip(' "')
    t = limit_emojis(t, 1) if emojis else _one_line(strip_emojis(t))
    if not t or len(t) > max_len or _AI_FORBIDDEN.search(t) or not _grounded(t, source):
        return ""
    letters = [c for c in t if c.isalpha()]
    caps_max = 0.85 if st["intensidade"] >= 3 else 0.6
    if letters and sum(c.isupper() for c in letters) / len(letters) > caps_max:
        return ""
    return t


def ai_polish(plan: ClipPlan, platform: str, cfg: Any, title: str, hook: str, context: str,
              cta_text: str) -> tuple[str, str]:
    """conteudo.legenda_post_ia (padrao false): reescreve gancho/contexto e a pergunta-CTA com IA.
    Sempre com o texto deterministico como reserva. Uma chamada por corte (as duas redes reaproveitam)."""
    if cfg is None or not cfg.get("conteudo.legenda_post_ia", False):
        return hook, cta_text
    key = str(plan.id or "")
    res = _AI_CACHE.get(key)
    if res is None:
        try:
            res = _ask_ai(plan, cfg, title, hook, context) or {}
        except Exception as e:
            log.info("Legenda com IA indisponivel, usando o texto padrao (%s)", strip_emojis(str(e))[:120])
            res = {}
        _AI_CACHE[key] = res
    emojis = emojis_allowed(cfg)
    st = style(cfg, plan)
    source = " ".join(str(x or "") for x in (plan.title, plan.hook, plan.description, plan.teaser_text, title))
    line = _valid_ai(res.get("linha"), 140, cfg, emojis, source, st)
    question = _valid_ai(res.get("pergunta"), 90, cfg, emojis, source, st)
    new_cta = cta_text
    if question and cta_text and not part_suffix(plan):  # serie e "sem CTA" continuam deterministicos
        new_cta = question
    return (line or hook), new_cta


# ---------------------------------------------------------------------------------------- montagem
def build_post_text(plan: ClipPlan, platform: str, cfg: Any, video_title: str | None = None,
                    channel: str | None = None) -> tuple[str, str]:
    """Devolve (titulo, descricao). No TikTok a "descricao" e a legenda completa do post.

    YouTube: titulo <= 100 caracteres (citacao e ate 2 emojis do plano, sem < >, "(LEGENDADO)" e
    "(Parte X/Y)" no fim); descricao = gancho + contexto + CTA + "Fonte: canal" + rodape + hashtags
    (+ #Shorts), <= 5000. TikTok: legenda <= 2200 = titulo + contexto curto + CTA + fonte + hashtags
    (sempre na ultima linha, ate 5).
    """
    platform = (platform or "").lower()
    emojis = emojis_allowed(cfg)
    noemo = (lambda t: t) if emojis else strip_emojis  # conteudo.emojis: false -> tira os emojis
    lang = htags.translated_lang(plan)
    st = style(cfg, plan)
    footer = noemo(_clean(cfg.get("publicacao.descricao_rodape", "") or ""))
    source = noemo(_source_line(cfg, channel, video_title))
    tags = htags.choose(plan, platform, cfg, video_title=video_title, channel=channel)
    tag_line = " ".join(tags)
    call = htags.cta(plan, platform, cfg)
    if (getattr(plan, "exp", None) or {}).get("cta") == "B":     # sorteado para sair sem pedido de comentario
        call = ""

    if platform == "youtube":
        title = post_title(plan, cfg, YT_TITLE_MAX, emojis, lang)
        hook = _hook_line(plan, title, cfg, emojis, st)
        context = _context(plan, title, cfg, emojis, lang, YT_CONTEXT_MAX, one_line=False, st=st)
        hook, call = ai_polish(plan, platform, cfg, title, hook, context, call)
        parts = [hook, context, call, source, footer]
        body = "\n\n".join(p for p in parts if p)
        room = YT_DESC_MAX - len(tag_line) - 2
        body = _cut(body, room) if len(body) > room else body
        description = (body + "\n\n" + tag_line).strip() if tag_line else body
        return title, description

    # TikTok (e qualquer outra rede curta)
    title = post_title(plan, cfg, TT_TITLE_MAX, emojis, lang)
    context = ""
    if cfg.get("publicacao.tiktok_contexto", True):
        context = _context(plan, title, cfg, emojis, lang, TT_CONTEXT_MAX, one_line=True, st=st)
    context, call = ai_polish(plan, platform, cfg, title, context, context, call)
    lines = [title, context, call, source]
    if footer and cfg.get("publicacao.tiktok_rodape", False):
        lines.append(footer)
    head = "\n".join(p for p in lines if p)
    room = TT_CAPTION_MAX - len(tag_line) - 1
    if len(head) > room:
        head = _cut(head, room)
    if platform == "instagram":     # o @ do canal no YouTube pode ser de outra pessoa no Instagram
        head = re.sub(r"(?<!\w)@(?=\w)", "", head)
    caption = (head + "\n" + tag_line).strip() if tag_line else head
    return title, caption[:TT_CAPTION_MAX]


def split_caption(caption: str) -> tuple[str, list[str]]:
    """Separa a legenda do TikTok em (texto, hashtags finais) para digitar as tags uma a uma."""
    lines = caption.rstrip().split("\n")
    last = lines[-1].strip() if lines else ""
    if last and all(tok.startswith("#") for tok in last.split()):
        return "\n".join(lines[:-1]).rstrip(), last.split()
    return caption, []


def source_info(plan: ClipPlan) -> tuple[str | None, str | None]:
    """(titulo do video-fonte, canal) a partir do banco; melhor esforco."""
    try:
        from .. import db

        r = db.conn().execute("SELECT title, channel FROM videos WHERE id=?", (plan.source_id,)).fetchone()
        if r:
            return r["title"], r["channel"]
    except Exception:
        pass
    return None, None
