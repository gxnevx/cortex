"""Cerebro sem IA: funciona 100% offline.

Escolhe cortes pelos sinais (mais repetidos do YouTube, clipes da Twitch, picos de volume,
palavras-chave de risada/polemica, velocidade da fala), encaixa em frases inteiras, detecta
series e gera titulos estilo geracao Z a partir de modelos + frase-chave do trecho.
"""
from __future__ import annotations

import json
import math
import re

from .. import log, paths
from .. import signals as sg
from ..models import Candidate, ClipPlan, Transcript, Trend
from ..util import short_hash, slugify
from .. import tom as tom_cfg
from . import modelos_tom as mt
from .base import polemic_spans as base_polemic_spans
from .base import (Brain, clean_punct, emojis_enabled, finalize_plans, normalize_hashtags, resolve_limit,
                   strip_emojis, _cfg_get)

logger = log.get(__name__)

# ----------------------------------------------------------------------------------------
# Categorias (texto normalizado, sem acento)
# ----------------------------------------------------------------------------------------
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "politica": ["lula", "bolsonaro", "stf", "moraes", "eleicao", "eleicoes", "senado", "senador", "camara",
                 "deputad", "ministro", "governo", "presidente", "prefeito", "governador", "tarcisio", "haddad",
                 "congresso", "cpi", "pec", "pt ", "pl ", "psol", "direita", "esquerda", "trump", "anistia",
                 "impeachment", "bolsa familia", "imposto", "reforma", "politic", "michelle", "boulos",
                 "marcal", "nikolas", "ciro", "alckmin", "janja", "dino", "gilmar", "barroso", "itamaraty"],
    "games": ["gta", "minecraft", "fortnite", "free fire", "freefire", "cs2", "counter strike", "valorant",
              "league of legends", "lol ", "roblox", "gaules", "loud", "furia", "twitch", "ps5", "playstation",
              "xbox", "nintendo", "switch 2", "game", "gamer", "gameplay", "speedrun", "pokemon", "fifa",
              "ea fc", "warzone", "dota", "elden ring", "zelda", "esports", "e-sports", "major", "streamer"],
    "humor": ["meme", "piada", "stand up", "standup", "comedia", "comediante", "humorista", "zueira",
              "engracad", "resenha", "trollagem", "pegadinha", "kkk", "risada", "hilari",
              "funny", "prank", "comedy", "fails", "roast"],
    "esportes": ["futebol", "flamengo", "corinthians", "palmeiras", "sao paulo", "vasco", "gremio",
                 "internacional", "santos", "botafogo", "fluminense", "cruzeiro", "atletico", "bahia",
                 "fortaleza", "neymar", "vini jr", "vinicius", "selecao", "brasileirao", "libertadores",
                 "copa do brasil", "copa do mundo", "champions", "ufc", "mma", "boxe", "formula 1", "f1 ",
                 "volei", "nba", "basquete", "gol", "tecnico", "ancelotti", "jogador", "campeonato",
                 "classico", "real madrid", "barcelona", "messi", "cristiano", "tenis", "joao fonseca"],
    "celebridades": ["bbb", "big brother", "a fazenda", "reality", "cantor", "cantora", "atriz", "ator ",
                     "famos", "anitta", "virginia", "ze felipe", "luisa sonza", "gkay", "influencer",
                     "influenciador", "casamento", "separacao", "namoro", "show", "novela", "globo",
                     "carlinhos maia", "whindersson", "felca", "gusttavo lima", "wesley safadao"],
    "podcast": ["podcast", "flow", "podpah", "inteligencia ltda", "venus", "papagaio falante", "ticaracaticast",
                "cortes do", "entrevista", "bate papo", "conversa", "mesacast", "pod ", "talk"],
    "polemica": ["polemica", "treta", "briga", "discussao", "acusacao", "escandalo", "cancelad", "denuncia",
                 "preso", "prisao", "processo", "ataque", "detona", "rebate", "critica", "xinga", "bate boca",
                 "climao", "exposed", "expoe", "desabafa", "barraco", "revolta"],
    "entretenimento": ["filme", "serie", "netflix", "trailer", "estreia", "festival", "musica", "clipe",
                       "lancamento", "programa", "tv", "react", "live"],
    "noticias": ["noticia", "jornal", "plantao", "urgente", "ao vivo", "operacao", "policia", "investigacao"],
}
CAT_ORDER = ["polemica", "politica", "podcast", "humor", "games", "esportes", "celebridades",
             "entretenimento", "noticias"]
# quanto cada categoria costuma render em cortes
CAT_CLIP_BONUS = {"polemica": 16, "politica": 12, "podcast": 12, "humor": 12, "games": 9, "esportes": 9,
                  "celebridades": 9, "entretenimento": 6, "noticias": 2}
# assuntos que nao rendem corte (sem video falado / utilidade publica)
BAD_TOPIC = ["loteria", "mega sena", "mega-sena", "megasena", "quina", "lotofacil", "lotomania", "dupla sena",
             "timemania", "resultado do", "previsao do tempo", "tempo amanha", "temperatura", "frente fria",
             "dolar hoje", "cotacao", "ibovespa", "horoscopo", "signo", "gabarito", "inss", "concurso",
             "feriado", "horario de", "fgts", "pis pasep", "saque", "imposto de renda", "receita federal",
             "calendario", "cep ", "boleto", "nota fiscal", "tabela", "classificacao do", "escalacao"]
SENSITIVE = ["morre", "morreu", "morte", "falece", "faleceu", "velorio", "enterro", "acidente", "tragedia",
             "assassin", "homicidio", "estupro", "chacina", "atentado", "desaparecid", "luto"]
QUERY_SUFFIX = {
    "politica": [" debate", " entrevista"],
    "polemica": [" podcast", " polêmica"],
    "games": [" ao vivo", " live"],
    "humor": [" podcast", " react"],
    "esportes": [" react", " resenha"],
    "celebridades": [" entrevista", " podcast"],
    "entretenimento": [" react", " ao vivo"],
    "podcast": [" podcast", " entrevista"],
    "noticias": [" ao vivo", " debate"],
    None: [" ao vivo", " podcast"],
}
CAT_TAGS = {
    "politica": ["#politica", "#debate"], "polemica": ["#polemica", "#treta"], "games": ["#games", "#gamer"],
    "humor": ["#humor", "#comedia"], "esportes": ["#esportes", "#futebol"], "celebridades": ["#famosos", "#fofoca"],
    "entretenimento": ["#entretenimento"], "podcast": ["#podcast", "#cortespodcast"], "noticias": ["#noticias"],
}


def categorize(text: str) -> tuple[str | None, int]:
    t = " " + sg.norm(text) + " "
    best, best_n = None, 0
    for cat in CAT_ORDER:
        n = sum(1 for kw in CATEGORY_KEYWORDS[cat] if kw in t)
        if cat == "esportes" and n == 1 and " gol" in t and "futebol" not in t:
            n = 0                                    # "gol" sozinho e ambiguo
        if n > best_n:
            best, best_n = cat, n
    return best, best_n


# ----------------------------------------------------------------------------------------
# Titulos
# ----------------------------------------------------------------------------------------
# Modelos proprios (sem emoji; no maximo 1 palavra em CAIXA ALTA, como pede docs/ideias/criativo_genz.json).
# {tema} = assunto em alta que trouxe o video; modelos com campo vazio sao ignorados.
TITLES: dict[str, list[str]] = {
    "risada": ["Ninguém tankou essa resenha KKKKKK", "O estúdio inteiro caiu na risada", "Não consigo ver isso sem rir",
               "Essa resenha saiu do CONTROLE", "Até ele riu disso KKKKKK"],
    "polemica": ["O clima pesou nesse papo", "Ele falou mesmo, sem filtro", "Esse papo dividiu o estúdio",
                 "Ninguém esperava essa resposta", "A discussão esquentou AO VIVO", "Ele tá certo ou passou do ponto?"],
    "surpresa": ["Ninguém tava pronto pra essa resposta", "Ele não esperava essa pergunta", "Espera ele terminar a frase...",
                 "A reação no final diz TUDO"],
    "emocao": ["Esse momento pegou todo mundo", "Ele segurou o choro falando disso", "O desabafo que ninguém esperava"],
    "palavrao": ["Ele perdeu a paciência AO VIVO", "Saiu do sério nessa hora", "Ele não segurou e soltou o verbo"],
    "gancho": ["Presta atenção no final", "Ninguém te conta isso", "A história por trás disso"],
    "impacto": ["Os números assustam", "Isso é SURREAL", "Olha o tamanho disso"],
    "heatmap": ["O momento mais repetido do vídeo", "Todo mundo voltou pra ver essa parte",
                "A parte que todo mundo comentou"],
    "twitch": ["O clipe mais visto da live", "O chat não acreditou nisso", "Isso aconteceu AO VIVO"],
    "comentarios": ["A parte que todo mundo comentou", "Todo mundo voltou pra ver essa parte",
                    "O momento que a galera não para de citar"],
    "chat": ["O chat não acreditou nisso", "O chat explodiu nessa hora", "Isso aconteceu AO VIVO"],
    "games": ["O chat coringou com essa jogada", "Ninguém acreditou nessa jogada", "Isso aconteceu AO VIVO"],
    "debate": ["O debate esquentou nessa hora", "Esse argumento pesou", "Ele não deixou barato",
               "Opinião forte sobre {tema}", "Por que todo mundo tá falando de {tema}?"],
    "humor": ["Essa resenha é OURO", "Ninguém tankou essa história"],
    "geral": ["Você precisa ver isso", "Olha o que ele falou", "Presta atenção nessa parte"],
}
# gancho na tela: curto (ate 7 palavras / 40 caracteres), em CAIXA ALTA
HOOKS: dict[str, list[str]] = {
    "risada": ["NINGUÉM TANKOU ESSA", "O ESTÚDIO CAIU NA RISADA"], "polemica": ["O CLIMA PESOU", "FALOU SEM FILTRO",
                                                                               "ESSE PAPO DIVIDIU O ESTÚDIO"],
    "surpresa": ["ELE NÃO ESPERAVA ESSA", "ESPERA O FINAL"], "emocao": ["ESSE MOMENTO PEGOU"],
    "palavrao": ["PERDEU A PACIÊNCIA", "SAIU DO SÉRIO"], "gancho": ["PRESTA ATENÇÃO NO FINAL"],
    "impacto": ["OLHA O TAMANHO DISSO"], "heatmap": ["A PARTE MAIS REPETIDA", "TODO MUNDO VOLTOU AQUI"],
    "twitch": ["O CHAT NÃO ACREDITOU"], "comentarios": ["TODO MUNDO COMENTOU ISSO", "A PARTE MAIS CITADA"],
    "chat": ["O CHAT EXPLODIU", "O CHAT NÃO ACREDITOU"], "games": ["O CHAT CORINGOU"], "debate": ["O DEBATE ESQUENTOU",
                                                                                   "ESSE ARGUMENTO PESOU"],
    "humor": ["ESSA RESENHA É OURO"], "geral": ["OLHA O QUE ELE FALOU", "PRESTA ATENÇÃO NISSO"],
}
# emojis so quando conteudo.emojis = true (1 por titulo, sem repetir)
EMOJIS: dict[str, list[str]] = {
    "risada": ["\U0001F62D", "\U0001F480"], "polemica": ["\U0001F62C", "\U0001F5E3\ufe0f"],
    "surpresa": ["\U0001F633", "\U0001F92F", "\U0001F440"], "emocao": ["\U0001F972", "\U0001F494"],
    "palavrao": ["\U0001F624"], "gancho": ["\U0001F440", "\U0001F92B"], "impacto": ["\U0001F633", "\U0001F4B8"],
    "heatmap": ["\U0001F525", "\U0001F440"], "twitch": ["\U0001F3AE", "\U0001F525"], "games": ["\U0001F3AE"],
    "comentarios": ["\U0001F440", "\U0001F525"], "chat": ["\U0001F525", "\U0001F633"],
    "debate": ["\U0001F62C", "\U0001F914"], "humor": ["\U0001F62D", "\U0001F480"], "geral": ["\U0001F440"],
}
# tipo do momento -> categoria/emocao do guia criativo
NICHE = {"politica": "politica", "polemica": "polemica", "humor": "humor", "games": "games", "esportes": "futebol",
         "podcast": "podcast_storytime", "celebridades": "celebridades", "entretenimento": "celebridades",
         "noticias": "noticias"}
KIND_EMOTION = {"risada": "risada", "polemica": "treta", "surpresa": "choque", "emocao": "emocao",
                "palavrao": "indignacao", "gancho": "revelacao", "impacto": "choque", "heatmap": "hype",
                "twitch": "hype", "comentarios": "hype", "chat": "hype", "debate": "treta", "humor": "risada", "games": "choque", "geral": "curiosidade"}
CAT_EMOTION = {"politica": "treta", "polemica": "treta", "humor": "risada", "games": "choque",
               "celebridades": "treta", "esportes": "hype", "podcast": "choque", "noticias": "curiosidade"}
GUIDE_PATH = paths.ROOT / "docs" / "ideias" / "criativo_genz.json"
_GUIDE: dict | None = None


def creative_guide() -> dict:
    """docs/ideias/criativo_genz.json (opcional). {} se nao existir/invalido."""
    global _GUIDE
    if _GUIDE is None:
        try:
            _GUIDE = json.loads(GUIDE_PATH.read_text(encoding="utf-8"))
        except Exception:
            _GUIDE = {}
    return _GUIDE


_PH = re.compile(r"\{(\w+)\}")


def _fill(template: str, values: dict[str, str]) -> str | None:
    """Preenche {campos}; None se algum campo nao tem valor."""
    names = _PH.findall(template)
    if any(not values.get(n) for n in names):
        return None
    return _PH.sub(lambda m: values[m.group(1)], template)


def _guide_templates(section: str, key: str) -> list[str]:
    g = creative_guide().get(section) or {}
    out = []
    for x in g.get(key) or []:
        t = x.get("t") if isinstance(x, dict) else x
        if isinstance(t, str):
            out.append(t)
    return out


KIND_TO_CAT = {"risada": "humor", "polemica": "polemica", "palavrao": "polemica"}
_FILLERS = {"e", "mas", "ai", "aí", "entao", "então", "ne", "né", "tipo", "cara", "mano", "assim", "porque",
            "pois", "bom", "bem", "enfim", "sabe", "o", "ó", "ô", "uai", "ah", "eh", "é,", "hã", "hum", "ta",
            "tá", "ok", ">>", "-", "que", "daí", "dai", "agora", "isso,", "gente,", "olha,", "não,", "sim,"}
_FILLERS_END = {"e", "mas", "que", "de", "do", "da", "o", "a", "os", "as", "um", "uma", "pra", "para", "com",
                "no", "na", "em", "se", "porque", "né", "ne", "tipo", "assim", "aí", "ai", "então", "por", "ao"}


def _rng_pick(items: list[str], seed: str, k: int = 0) -> str:
    if not items:
        return ""
    return items[(int(short_hash(seed, 8), 16) + k) % len(items)]


def _clean_phrase(words: list[str], max_words: int = 9) -> str:
    ws = [w for w in words if w not in (">>", "-", "\u2013", "\u2014")]
    while ws and sg.norm(ws[0]).strip(",.!?") in {sg.norm(f).strip(",") for f in _FILLERS}:
        ws = ws[1:]
    ws = ws[:max_words]
    while ws and sg.norm(ws[-1]).strip(",.;:") in _FILLERS_END:
        ws = ws[:-1]
    txt = " ".join(ws).strip(" ,;:-")
    txt = re.sub(r"[.,;:]+$", "", txt)
    return txt


def key_phrase(tr: Transcript, a: float, b: float, peak: float, hits: list[sg.KeywordHit]) -> tuple[str, str]:
    """(frase curta de impacto, frase de contexto) dentro de [a, b]."""
    segs = [s for s in tr.segments if s.end > a and s.start < b]
    if not segs:
        return "", ""
    best, best_sc = None, -1e9
    for s in segs:
        n = len(s.text.split())
        hs = [h for h in hits if s.start - 0.5 <= h.t <= s.end + 0.5 and h.text != "!"]
        sc = sum(h.weight for h in hs) * 2.0
        sc += 1.0 if ("?" in s.text or "!" in s.text) else 0.0
        sc -= abs((s.start + s.end) / 2 - peak) / 25.0
        sc += 0.6 if 3 <= n <= 16 else (-0.5 if n < 3 else 0.0)
        if sc > best_sc:
            best, best_sc = s, sc
    assert best is not None
    clauses = [c.strip() for c in re.split(r"(?<=[.!?;])\s+|,\s+", best.text) if c.strip()]
    kwset = [h.text for h in hits if best.start - 0.5 <= h.t <= best.end + 0.5 and h.text != "!"]

    def clause_score(c: str) -> float:
        nc = sg.norm(c)
        n = len(c.split())
        return (2.0 * sum(1 for k in kwset if k in nc)) + (1.0 if c.endswith(("?", "!")) else 0) \
            + (1.0 if 3 <= n <= 9 else (-1.0 if n < 3 else -0.3))

    clause = max(clauses, key=clause_score) if clauses else best.text
    phrase = _clean_phrase(clause.split())
    if len(phrase.split()) < 3:
        phrase = _clean_phrase(best.text.split())
    context = re.sub(r"\s+", " ", best.text.replace(">>", "")).strip()
    return phrase, context[:220]


def _dominant_kind(hits: list[sg.KeywordHit], heat: float, twitch: float, category: str | None = None,
                   cm: float = 0.0, chat: float = 0.0) -> str:
    """Tipo do momento (define o modelo de titulo). So usa palavra-chave se o sinal for claro."""
    score: dict[str, float] = {}
    for h in hits:
        if h.text == "!":
            continue
        score[h.kind] = score.get(h.kind, 0) + h.weight
    if score:
        k, v = max(score.items(), key=lambda kv: kv[1])
        if v >= 0.9 and k != "impacto":
            return k
    if twitch > 0:
        return "twitch"
    if cm > 0:
        return "comentarios"
    if chat > 0:
        return "chat"
    if heat > 0.4:
        return "heatmap"
    if category in ("politica", "polemica"):
        return "debate"
    if category == "humor":
        return "humor"
    if category == "games":
        return "games"
    return "geral"


def _strip_emoji(t: str) -> str:
    return strip_emojis(t).split("|")[0].strip()


def _topic_short(video: Candidate) -> str:
    t = (video.topic or "").strip()
    if t and len(t) <= 28:
        return t
    return ""


def _clean_name(name: str) -> str:
    """Nome curto de canal/programa: tira '[OFICIAL]', 'Cortes do', 'Podcast'..."""
    n = re.sub(r"\[[^\]]*\]|\([^)]*\)", "", name or "")
    n = re.sub(r"(?i)\b(cortes?\s+d[oa]s?|oficial|official|canal|tv)\b", "", n)
    n = re.sub(r"\s+", " ", n).strip(" -|:")
    return n if 2 <= len(n) <= 22 else ""


POLEMIC_SUFFIX: dict[str, list[str]] = {
    "polemica": ["o clima pesou ao vivo", "ninguém esperava essa resposta", "e o estúdio travou",
                 "ele falou sem filtro"],
    "palavrao": ["ele perdeu a paciência", "saiu do sério ao vivo", "ele não segurou"],
    "risada": ["ninguém tankou KKKKKK", "o estúdio caiu na risada"],
    "emocao": ["ninguém segurou o choro", "esse momento pegou todo mundo"],
    "surpresa": ["a reação diz tudo", "ninguém tava pronto pra isso"],
    "debate": ["o debate esquentou", "ele não deixou barato"],
    "geral": ["presta atenção no final", "olha o que ele falou"],
}
_TIPO_TO_KIND = {"palavrao": "palavrao", "insulto": "polemica", "acusacao": "polemica", "polemica": "polemica",
                 "emocao": "emocao", "risada": "risada", "surpresa": "surpresa"}


def _quote_text(text: str, max_words: int = 10) -> str:
    """Citacao limpa (sem muleta nas pontas, sem pontuacao final fraca), mantendo as palavras ditas."""
    ws = [w for w in str(text or "").replace('"', "").split() if w not in (">>", "-")]
    while ws and sg.norm(ws[0]).strip(",.!?") in {sg.norm(f).strip(",") for f in _FILLERS}:
        ws = ws[1:]
    while ws and sg.norm(ws[-1]).strip(",.;:") in _FILLERS_END:
        ws = ws[:-1]
    if len(ws) < 2 or len(ws) > max_words:
        return ""
    q = " ".join(ws).strip(" ,;:-")
    return re.sub(r"[.,;:]+$", "", q)


_HOT_RX = re.compile(r"\b(?:mentiros|ladr|idiot|imbecil|otari|palhac|vagabund|safad|canalh|covard|hipocrit|burr|"
                     r"mentira|mentindo|cala a boca|porra|caralh|foda|merda|puta|cu|pqp|vsf|desgrac|absurd|vergonha|"
                     r"chor|traid|traiu|nunca|ninguem)\w*")


def _hook_clause(q: str, max_chars: int = 36) -> str:
    """Parte mais pesada da citacao que cabe no gancho (sempre palavras ditas, na ordem)."""
    parts = [p.strip(" ,;:") for p in re.split(r"(?<=[.!?,;])\s+", q) if p.strip(" ,;:")]
    ok = [p for p in parts if len(p) <= max_chars and len(p.split()) >= 2]
    if not ok:
        return ""
    hot = [p for p in ok if _HOT_RX.search(sg.norm(p))]
    return max(hot or ok, key=len).rstrip(",;:")


def polemic_kind(tipos: list[str]) -> str | None:
    for t in ("palavrao", "acusacao", "insulto", "polemica", "emocao", "risada", "surpresa"):
        if t in (tipos or []):
            return _TIPO_TO_KIND[t]
    return None


def make_title(kind: str, phrase: str, video: Candidate, seed: str, idx: int, category: str | None,
               emojis: bool = False, polemic: str = "", polemic_kind: str | None = None,
               intensity: int = 1, clip_text: str = "", quote_prop: float = 1.0) -> tuple[str, str]:
    """(titulo, gancho) estilo geracao Z, sem inventar fatos. Sem emoji, a menos que emojis=True.
    polemic = frase explosiva que existe na transcricao: vira citacao entre aspas no titulo e no gancho.
    intensity = fabrica.tom (0 neutro, 1 polemico, 2 malicioso, 3 super_polemico, 4 modo_besta); clip_text = fala
    do trecho normalizada (modelos especificos so entram quando a fala apoia a insinuacao); quote_prop = proporcao
    de cortes com a citacao no titulo (fabrica.tom.settings["citacao_proporcao"])."""
    topic = _topic_short(video)
    chan = _clean_name(video.channel or "")
    values = {"tema": topic, "canal_original": chan,
              "programa": chan if category in ("podcast", "humor", "polemica", "politica") else "",
              "streamer": chan if (video.platform in ("twitch", "kick") or category == "games") else "",
              "frase_curta": phrase if 2 <= len(phrase.split()) <= 6 else ""}
    emotion = KIND_EMOTION.get(kind, "curiosidade")
    if kind in ("heatmap", "twitch", "comentarios", "chat", "geral"):   # sinal neutro: emocao vem da categoria
        emotion = CAT_EMOTION.get(category or "", emotion)
    pool = list(TITLES.get(kind) or TITLES["geral"])
    # do guia so entram os modelos genericos por emocao (os por categoria afirmam fatos que a heuristica
    # nao consegue checar, ex.: "o conselho que mudou a vida dele")
    pool += _guide_templates("titulos_por_emocao", emotion)
    titles = [t for t in (_fill(x, values) for x in pool) if t]
    titles = [strip_emojis(t) for t in titles] if not emojis else titles
    tmpl = _rng_pick(titles or TITLES["geral"], seed)
    hooks_pool = list(HOOKS.get(kind) or HOOKS["geral"])
    hooks_pool += [h.upper() for h in _guide_templates("hooks_por_categoria", "universal")]
    hooks = [h for h in (_fill(x, values) for x in hooks_pool) if h and len(h) <= 40]
    hooks = [strip_emojis(h) for h in hooks] if not emojis else hooks
    hook_t = _rng_pick(hooks or HOOKS["geral"], seed, 3)
    emo = ""
    hook_emo = ""
    if emojis:
        pool_e = EMOJIS.get(kind) or EMOJIS["geral"]
        g = (creative_guide().get("emojis_por_emocao") or {}).get(emotion)
        if isinstance(g, list) and g:
            avoid = set((creative_guide().get("emojis_por_emocao") or {}).get("evitar") or {})
            pool_e = [e for e in g if isinstance(e, str) and e not in avoid] or pool_e
        e1 = _rng_pick(pool_e, seed, 1)
        e2 = _rng_pick([e for e in pool_e if e != e1], seed, 2) if len(pool_e) > 1 else ""
        two = int(short_hash(seed + "e", 4), 16) % 5 < 2              # ~40% com 2 emojis
        emo = " " + e1 + (e2 if two and e2 else "")
        hook_emo = " " + e1
        tmpl = strip_emojis(tmpl)
    if intensity >= 2 and emojis:
        pool_m = mt.emojis_for(intensity)
        e1 = _rng_pick(pool_m, seed, 1)
        e2 = _rng_pick([e for e in pool_m if e != e1], seed, 2)
        emo = " " + e1 + (e2 if int(short_hash(seed + "e", 4), 16) % 5 < (2 if intensity < 4 else 4) else "")
        hook_emo = " " + e1
    use_quote = (int(short_hash(seed + "q", 4), 16) % 100) < quote_prop * 100
    pq = _quote_text(polemic) if (polemic and intensity >= 1 and use_quote) else ""
    if pq:
        # a frase mais explosiva que a pessoa disse, ENTRE ASPAS (titulo em caixa normal, gancho em CAIXA ALTA)
        pk = polemic_kind or kind
        if intensity >= 2:
            suffix = _rng_pick(mt.suffixes_for(pk, intensity), seed, 5)
        else:
            suffix = _rng_pick(POLEMIC_SUFFIX.get(pk) or POLEMIC_SUFFIX.get(kind) or POLEMIC_SUFFIX["geral"], seed, 5)
        q = pq[0].upper() + pq[1:]
        if len(q) > 60:
            title = f"\"{q}\"" + emo
        elif emojis:
            title = f"\"{q}\"{emo} {suffix}"
        else:
            title = f"\"{q}\": {suffix}"
        hq = pq if len(pq) <= 36 else _hook_clause(pq)
        hook = (f"\"{hq.upper()}\"" + hook_emo) if hq else (strip_emojis(hook_t) + hook_emo)
        if not emojis:
            title, hook = strip_emojis(title), strip_emojis(hook)
        return clean_punct(title), clean_punct(hook)
    ph = phrase.strip()
    nwords = len(ph.split())
    quote_ok = 3 <= nwords <= 9 and len(ph) <= 55
    if intensity >= 2 and not (quote_ok and idx % 3 == 2 and intensity == 2):
        # insinuacao / duplo sentido (3+: verbos agressivos, caixa alta, ragebait); modelos especificos so com
        # apoio na fala, nenhum afirma fato novo
        title = _rng_pick(mt.titles_for(kind, clip_text, intensity), seed) + emo
        if intensity >= 4 and len(title) < 55:
            title += " | " + _rng_pick(mt.RAGEBAIT_SUFFIX, seed, 7)
        hk = _rng_pick(mt.hooks_for(clip_text, intensity), seed, 3)
        hook = ((ph.upper() if quote_ok and len(ph) <= 40 and nwords <= 7 and idx % 2 == 1 else hk) + hook_emo)
        if not emojis:
            title, hook = strip_emojis(title), strip_emojis(hook)
        return clean_punct(title), clean_punct(hook)
    if quote_ok and idx % 2 == 0:
        q = ph[0].upper() + ph[1:]
        title = f"\"{q}\"" + (" KKKKKK" if kind == "risada" else "") + emo
        hook = strip_emojis(hook_t) + hook_emo
    else:
        title = tmpl + emo
        if topic and "{tema}" not in " ".join(pool) and topic.lower() not in title.lower() and len(title) + len(topic) < 75:
            title += f" | {topic}"
        hook = (ph.upper() if (quote_ok and len(ph) <= 40 and nwords <= 7) else strip_emojis(hook_t)) + hook_emo
    if not emojis:
        title, hook = strip_emojis(title), strip_emojis(hook)
    return clean_punct(title), clean_punct(hook)


def make_hashtags(video: Candidate, category: str | None, kind: str) -> list[str]:
    tags: list[str] = []
    if video.topic:
        words = [w for w in re.split(r"\s+", sg.norm(video.topic)) if len(w) > 1]
        if words:
            tags.append("#" + "".join(words)[:28])
    if video.channel:
        ch = slugify(video.channel, 30).replace("-", "")
        if 3 <= len(ch) <= 25:
            tags.append("#" + ch)
    tags += CAT_TAGS.get(category or "", [])[:2]
    if kind in ("risada",) and "#humor" not in tags:
        tags.append("#humor")
    if kind in ("polemica", "palavrao") and "#polemica" not in tags:
        tags.append("#polemica")
    if video.platform == "twitch":
        tags.append("#twitch")
    return normalize_hashtags(tags, max_n=6)


# ----------------------------------------------------------------------------------------
# Cerebro
# ----------------------------------------------------------------------------------------
class HeuristicBrain(Brain):
    name = "heuristico"

    def __init__(self, cfg=None):
        super().__init__(cfg)
        self._status = ("Cérebro: heurístico (sem IA), usa 'mais repetidos' do YouTube, clipes da Twitch/Kick, "
                        "horários citados nos comentários, picos do chat, picos de áudio e palavras-chave.")

    # ----- temas
    def rank_trends(self, trends: list[Trend], cfg, limit: int = 15) -> list[Trend]:
        if not trends:
            return []
        temas = [sg.norm(t) for t in (_cfg_get(cfg, "busca.temas", []) or [])]
        groups: dict[str, list[Trend]] = {}
        order: list[str] = []
        for t in trends:
            key = re.sub(r"[^a-z0-9 ]", "", sg.norm(t.topic).replace("#", "")).strip()
            if not key:
                continue
            match = next((k for k in order if k == key or (len(key) > 4 and len(k) > 4 and (key in k or k in key))), None)
            if match is None:
                groups[key] = [t]
                order.append(key)
            else:
                groups[match].append(t)
        out: list[Trend] = []
        for key in order:
            grp = groups[key]
            main = max(grp, key=lambda x: x.score)
            sources = sorted({x.source for x in grp})
            related = list(dict.fromkeys(r for x in grp for r in (x.related or [])))[:8]
            text = " ".join([main.topic] + related)
            ntext = " " + sg.norm(text) + " "
            cat, hits = categorize(text)
            cat = main.category or cat
            s = 0.45 * max(0.0, min(100.0, float(main.score or 0)))
            s += 9 * min(3, len(sources) - 1)
            s += CAT_CLIP_BONUS.get(cat or "", 4)
            if cat and sg.norm(cat) in temas:
                s += 10
            if main.traffic and re.search(r"(mil|k|m)\+?", str(main.traffic).lower()):
                s += 4
            bad = any(b in ntext for b in BAD_TOPIC)
            sensitive = any(b in ntext for b in SENSITIVE)
            if bad:
                s -= 45
            if sensitive:
                s -= 25
            s = round(max(0.0, min(100.0, s)), 1)
            topic = main.topic.strip()
            sufs = QUERY_SUFFIX.get(cat, QUERY_SUFFIX[None])
            queries = [clean_punct(strip_emojis(q)) for q in [topic] + [topic + sfx for sfx in sufs]]
            why = []
            if cat:
                why.append(f"categoria {cat}")
            if len(sources) > 1:
                why.append(f"em alta em {len(sources)} fontes ({', '.join(sources)})")
            else:
                why.append(f"em alta no {sources[0]}")
            if main.traffic:
                why.append(f"tráfego {main.traffic}")
            if bad:
                why.append("assunto de serviço (rende pouco corte)")
            if sensitive:
                why.append("tema sensível")
            out.append(Trend(topic=topic, source=main.source, score=s, traffic=main.traffic, related=related,
                             url=main.url, category=cat, queries=queries[:3], reason="; ".join(why)))
        out.sort(key=lambda t: -t.score)
        good = [t for t in out if t.score >= 20] or out[:3]
        return good[:limit]

    # ----- cortes
    def pick_clips(self, video: Candidate, transcript: Transcript, cfg, max_clips: int | None = None) -> list[ClipPlan]:
        self._sig = None
        raw = self.candidate_windows(video, transcript, cfg, max_clips)
        return finalize_plans(raw, video, transcript, cfg, max_clips=max_clips,
                              teaser_bonus=sg.teaser_bonus(getattr(self, "_sig", None)))

    def candidate_windows(self, video: Candidate, transcript: Transcript, cfg, max_clips: int | None = None) -> list[dict]:
        dmin = float(_cfg_get(cfg, "corte.duracao_min_s", 25))
        dmax = float(_cfg_get(cfg, "corte.duracao_max_s", 90))
        allow_series = bool(_cfg_get(cfg, "corte.permitir_series", True))
        limit = resolve_limit(cfg, video, transcript, max_clips)
        audio = (video.extra or {}).get("audio_path") or (video.extra or {}).get("media_path")
        sig = sg.compute_signals(video, transcript, audio_path=audio)
        dur = max(transcript.duration, 1.0) if transcript.segments else float(video.duration or 0)
        if dur <= 0:
            return []
        logger.debug("sinais %s: %s", video.id, sg.describe(sig))
        target = max(dmin, min(dmax, (dmin + dmax) / 2 + 2))
        moments = sg.hot_moments(sig, top=max(12, limit * 4), min_gap=max(15.0, dmin * 0.8))
        wins: list[tuple[float, float, float, sg.Moment | None]] = []
        # serie so com evidencia forte do publico (mais repetidos / clipes / comentarios / chat), nao so palavra-chave
        strong = any(k in sig.available for k in ("heatmap", "twitch", "comentarios", "chat"))
        for m in moments:
            rlen = m.end - m.start
            if allow_series and strong and rlen > dmax * 1.3 and m.score >= 0.6:
                a, b = m.start - 6, m.end + 4                      # assunto longo -> serie
            else:
                L = max(dmin, min(dmax, max(rlen + 16, target)))
                a = m.peak - 0.65 * L                               # contexto antes, climax perto do fim
                b = a + L
                if m.start < a and b - (m.start - 3) <= dmax:
                    a = m.start - 3
                if m.end > b and (m.end + 3) - a <= dmax:
                    b = m.end + 3
            a, b = max(0.0, a), min(dur, b)
            if b - a >= dmin * 0.6:
                wins.append((a, b, m.peak, m))
        # sinais do publico sao fontes de janela por si so (a curva suavizada pode juntar/apagar dois lances)
        wins += self._audience_windows(sig, target, dur, [(w[0], w[1]) for w in wins])
        if len(wins) < limit:
            wins += self._fallback_windows(transcript, sig, target, dur, exclude=[(w[0], w[1]) for w in wins])

        cat_video, _ = categorize(" ".join([video.title or "", video.topic or "", video.channel or "",
                                            (video.description or "")[:300]]))
        # pontua e remove janelas repetidas (mesmo momento visto por sinais diferentes)
        scored = sorted(((self._score_window(a, b, sig, transcript, video), a, b, peak, m)
                         for a, b, peak, m in wins), key=lambda x: -x[0][0])
        scored = self._apply_saturation(scored, sig)
        kept: list = []
        for item in scored:
            _, a, b, peak, m = item
            dup = False
            for _, ka, kb, kp, _ in kept:
                ov = min(b, kb) - max(a, ka)
                if ov > 0.25 * (b - a) or (ka <= peak <= kb):
                    dup = True
                    break
            if not dup:
                kept.append(item)
        emo_on = emojis_enabled(cfg)
        self._sig = sig
        quote_on = bool(_cfg_get(cfg, "conteudo.titulo_com_citacao", True))
        tset = tom_cfg.settings(cfg)
        intensity = int(tset.get("intensidade", 2))
        quote_prop = float(tset.get("citacao_proporcao", 0.7) or 0.0)
        # video estrangeiro: a fala nao e em portugues, entao titulo/gancho/descricao saem dos modelos em pt-BR
        # (sem citar a fala original); o teaser continua sendo o trecho mais explosivo (palavras originais)
        from .prompts import video_lang

        foreign = video_lang(video) != "pt"
        if foreign:
            quote_on = False
        whisper = str(transcript.source or "").startswith("whisper")
        all_words = transcript.words()
        bonus = sg.teaser_bonus(sig)
        from . import games

        only_reaction = games.is_game(video) and bool(_cfg_get(cfg, "conteudo.games_so_reacao", True))
        raw: list[dict] = []
        for i, ((sc, parts), a, b, peak, m) in enumerate(kept):
            hits = [h for h in sig.keywords if a <= h.t <= b]
            kind = _dominant_kind(hits, parts["heat"], parts["twitch"], cat_video, parts["cm"], parts["chat"])
            cat = cat_video
            if kind in KIND_TO_CAT and (cat is None or cat in ("podcast", "noticias", "entretenimento")):
                cat = KIND_TO_CAT[kind]
            phrase, context = key_phrase(transcript, a, b, peak, sig.keywords)
            # legenda automatica da plataforma vem sem pontuacao e as vezes truncada:
            # citar frase dela no titulo fica estranho. So cita quando veio do Whisper.
            if not str(transcript.source or "").startswith("whisper") or foreign:
                phrase = ""
            seed = f"{video.id}|{int(a)}"
            is_series = (b - a) > dmax * 1.15
            # frase mais explosiva do trecho (palavrao, insulto, acusacao, grito, choro, punchline): vira teaser e,
            # se for forte, citacao no titulo/gancho. Legenda da plataforma (sem pontuacao) so com acerto forte.
            pol = None
            ws_in = [w for w in all_words if a + 4.0 <= w.start and w.end <= min(b, a + dmax)]
            if ws_in:
                spans = base_polemic_spans(ws_in, cfg, top=1, bonus=bonus)
                if spans:
                    pol = spans[0]
            if only_reaction and not games.strong_reaction(pol):
                continue        # gameplay sem reacao nenhuma: corte aleatorio, nao presta
            strong_quote = bool(pol and quote_on and pol["score"] >= (1.4 if whisper else 2.2)
                                and any(t in pol["tipos"] for t in ("palavrao", "insulto", "acusacao", "polemica",
                                                                     "emocao", "risada", "surpresa")))
            pk = polemic_kind(pol["tipos"]) if pol else None
            # serie: titulo de modelo (a frase-chave so representaria a parte 1)
            ctext = sg.norm(" ".join(w.text for w in all_words if a <= w.start <= b)) if not foreign else ""
            title, hook = make_title(kind, "" if is_series else phrase, video, seed, i, cat, emojis=emo_on,
                                     polemic=pol["text"] if strong_quote else "", polemic_kind=pk,
                                     intensity=intensity, clip_text=ctext, quote_prop=quote_prop)
            if not tset.get("caps_gancho", True) and hook.isupper():
                hook = hook[:1] + hook[1:].lower()
            if is_series and phrase and len(phrase) <= 40 and not strong_quote:
                hook = phrase.upper()
            reasons = (m.reasons if m else []) or sg._reasons_at(sig, a, b)[0] or ["trecho com fala intensa"]
            if parts.get("saturado"):
                reasons = list(reasons) + ["2º melhor momento (o mais óbvio já foi muito cortado hoje)"]
            desc = context if not foreign else (
                f"Momento de {video.channel or 'um criador gringo'} que está bombando lá fora (legendado em português).")
            if desc and not desc.endswith((".", "!", "?")):
                desc += "…"
            if video.title:
                desc = (desc + f" Trecho de \"{video.title[:90]}\".").strip()
            layout = "blur" if cat in ("games", "esportes") else None
            raw.append({
                "start": a, "end": b, "title": title, "hook": hook, "description": desc,
                "hashtags": make_hashtags(video, cat, kind), "score": sc,
                "reason": "; ".join(reasons)[:300], "category": cat or "outros", "series": None,
                "series_name": (_topic_short(video) or _strip_emoji(title)) if is_series else None,
                "part": None, "layout": layout,
                "teaser_texto": pol["text"] if pol else "", "teaser_inicio": pol["start"] if pol else None,
            })
        return raw

    @staticmethod
    def _audience_windows(sig: sg.Signals, target: float, dur: float,
                          exclude: list[tuple[float, float]]) -> list[tuple[float, float, float, None]]:
        """Uma janela por horario citado nos comentarios / pico de chat que ainda nao tem janela.
        Comentario cita o inicio do lance (janela comeca ~6 s antes); o chat explode depois (termina ~4 s depois)."""
        anchors: list[tuple[float, float, float]] = []   # (inicio, fim, pico)
        for m in sig.comment_marks[:8]:
            a = m["t"] - 6
            anchors.append((a, a + target, m["t"] + 12))
        for s in sig.chat_spikes[:8]:
            b = s["t"] + 4
            anchors.append((b - target, b, s["t"] - 12))
        out: list[tuple[float, float, float, None]] = []
        taken = list(exclude)
        for a, b, pk in anchors:
            a, b = max(0.0, a), min(dur, b)
            if b - a < target * 0.6 or pk < 0 or pk > dur:
                continue
            if any(x <= pk <= y for x, y in taken):
                continue
            out.append((a, b, max(a, min(b, pk)), None))
            taken.append((a, b))
        return out

    @staticmethod
    def _apply_saturation(scored: list, sig: sg.Signals) -> list:
        """Assunto saturado (8+ canais ja cortaram hoje): o momento mais obvio cai para tras e o 2o/3o melhor
        sobe (o 2o melhor sem concorrencia costuma valer mais que o 1o com 15 copias)."""
        sat = sig.saturation or {}
        if not sat.get("pular_melhor_momento") or len(scored) < 2:
            return scored
        (s0, p0), a0, b0, pk0, m0 = scored[0]
        p0 = dict(p0, obvio=True)
        demoted = ((round(s0 * 0.8, 1), p0), a0, b0, pk0, m0)
        rest = list(scored[1:])
        (s1, p1), a1, b1, pk1, m1 = rest[0]
        rest[0] = ((round(max(s1, min(97.0, s0 * 0.95)), 1), dict(p1, saturado=True)), a1, b1, pk1, m1)
        return sorted(rest + [demoted], key=lambda x: -x[0][0])

    @staticmethod
    def _fallback_windows(tr: Transcript, sig: sg.Signals, target: float, dur: float,
                          exclude: list[tuple[float, float]]) -> list[tuple[float, float, float, None]]:
        """Sem sinais fortes: janelas com mais perguntas/exclamacoes/palavras-chave e fala densa."""
        segs = tr.segments
        if not segs:
            return []
        out = []
        step = max(10.0, target / 3)
        t = segs[0].start
        while t + target * 0.6 < dur:
            a, b = t, min(dur, t + target)
            inside = [s for s in segs if s.start >= a and s.end <= b]
            if inside:
                txt = " ".join(s.text for s in inside)
                kw = sum(h.weight for h in sig.keywords if a <= h.t <= b)
                inten = kw + 0.4 * (txt.count("?") + txt.count("!")) + 0.02 * len(txt.split())
                peak = max(inside, key=lambda s: s.text.count("?") + s.text.count("!")).start
                out.append((inten, a, b, peak))
            t += step
        out.sort(reverse=True)
        chosen: list[tuple[float, float, float, None]] = []
        for _, a, b, peak in out:
            if all(b <= x or a >= y for x, y in exclude + [(c[0], c[1]) for c in chosen]):
                chosen.append((a, b, peak, None))
            if len(chosen) >= 6:
                break
        return chosen

    @staticmethod
    def _score_window(a: float, b: float, sig: sg.Signals, tr: Transcript, video: Candidate) -> tuple[float, dict]:
        """Pontuacao absoluta 0-100 (chance de viralizar) a partir dos sinais."""
        heat = 0.0
        if sig.heatmap:
            vals = sorted(v for _, _, v in sig.heatmap)
            med, top = vals[len(vals) // 2], max(vals)
            skip = max(20.0, 0.04 * sig.duration)
            for ha, hb, v in sig.heatmap:
                if hb > a and ha < b and ha >= skip:
                    heat = max(heat, (v - med) / max(1e-6, top - med))
            heat = max(0.0, min(1.0, heat))
        twitch = 0.0
        if sig.twitch_clips:
            mx = math.log1p(max(c["views"] for c in sig.twitch_clips) or 1)
            for c in sig.twitch_clips:
                if c["offset"] < b and c["offset"] + c["duration"] > a:
                    twitch = max(twitch, 0.5 + 0.5 * (math.log1p(c["views"]) / mx if mx else 0))
        cm = 0.0
        if sig.comment_marks:
            mxp = max(m["peso"] for m in sig.comment_marks)
            for m in sig.comment_marks:
                if a - 8 <= m["t"] <= b - 8:
                    cm = max(cm, sg.comment_value(m, mxp))
        chat = 0.0
        for s in sig.chat_spikes:
            if a + 8 <= s["t"] <= b + 25:
                chat = max(chat, sg.chat_value(s))
        jan = 0.0
        if sig.janela:
            ov = min(b, sig.janela[1]) - max(a, sig.janela[0])
            jan = max(0.0, min(1.0, ov / max(1.0, min(b - a, sig.janela[1] - sig.janela[0]))))
        kw = sum(h.weight for h in sig.keywords if a <= h.t <= b)
        loud = max((p[2] for p in sig.loud_peaks if a <= p[0] <= b), default=0.0)
        fala = sig.components.get("fala") or []
        rate = max(fala[int(a): int(b) + 1], default=0.0) if fala else 0.0
        nwords = sum(1 for w in tr.words() if a <= w.start <= b) if tr.segments else 0
        if nwords == 0 and tr.segments:
            nwords = sum(len(s.text.split()) for s in tr.segments if s.start >= a and s.end <= b)
        wps = nwords / max(1.0, b - a)
        pop = 0.0
        if video.views:
            pop = max(0.0, min(4.0, math.log10(max(1, video.views)) - 4.0))
        # sinais do publico (heatmap, clipe, comentarios, chat): o mais forte vale cheio, os outros somam pouco
        aud = sorted([38 * heat, 25 * twitch, 30 * cm, 24 * chat], reverse=True)
        score = 40 + aud[0] + 0.35 * sum(aud[1:]) + 10 * jan + min(18.0, 5.0 * kw) + min(8.0, loud) + 4 * rate + pop
        if wps < 0.8:
            score -= 15
        if sig.heatmap and heat < 0.15:
            score -= 5
        if (sig.comment_marks or sig.chat_spikes) and max(cm, chat, heat, twitch) == 0:
            score -= 4          # o publico apontou outros momentos, nao este
        score = max(5.0, min(97.0, score))
        return round(score, 1), {"heat": heat, "twitch": twitch, "cm": cm, "chat": chat, "jan": jan, "kw": kw,
                                 "loud": loud, "wps": wps}
