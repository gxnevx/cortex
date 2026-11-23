"""Heuristicas simples (palavras/canais) para pular categorias arriscadas ou fora do perfil.

Config: busca.pular_categorias (padrao: todas abaixo)
  esporte_transmissao  jogo transmitido / melhores momentos (direito de transmissao)
  tv_aberta            conteudo de emissora de TV (Globo, SBT, Record, Band, RedeTV, reality shows, novelas)
  filmes_series        filme/serie/episodio completo, trailers
  musica               clipe oficial, lyric video, show, canal de gravadora/VEVO, categoria Music
  apostas              bets, cassino, tigrinho, palpites
  menores              conteudo infantil / com criancas
"""
from __future__ import annotations

import re

from .text import norm

ALL_CATEGORIES = ["esporte_transmissao", "tv_aberta", "filmes_series", "musica", "apostas", "menores"]

# "time x time", "time 1 x 0 time", "time 1x0 time"
_VS = re.compile(r"\b[a-z0-9]{2,}(?: \d{1,2})? (?:x|vs) (?:\d{1,2} )?[a-z0-9]{2,}|\b[a-z]{2,} \d{1,2}x\d{1,2} [a-z]{2,}")
_LIVE_DOT = "\U0001F534"   # bolinha vermelha que canais usam no titulo de transmissao


def _rx(words: str) -> re.Pattern:
    alts = [re.escape(norm(w)) for w in words.split("|") if norm(w)]
    return re.compile(r"\b(?:" + "|".join(alts) + r")\b")


_SPORT_STRONG = _rx("ao vivo e com imagens|ao vivo com imagens|jogo completo|partida completa|melhores momentos|"
                    "gols e melhores momentos|todos os gols|compacto|highlights|full match|extended highlights|"
                    "transmissao ao vivo|narracao ao vivo|assista ao vivo|onde assistir")
_SPORT_LIVE = _rx("ao vivo|assista|assistir|transmissao|narracao|imagens|live|en vivo")
_SPORT_COMMENT = _rx("pos jogo|pos-jogo|debate|analise|resenha|react|reage|reagindo|reacao|reacoes|opiniao|"
                     "comentarios|entrevista|coletiva|bastidores|podcast|programa|polemica|arbitragem|juiz")
_COMPETITION = _rx("campeonato brasileiro|brasileirao|rodada|libertadores|sul americana|sulamericana|copa do brasil|"
                   "serie a|serie b|paulistao|carioca|champions|premier league|la liga|copa do mundo|eliminatorias|"
                   "amistoso|final|semifinal|nba|nfl|ufc")
_SPORT_CTX = _rx("jogo|partida|futebol|gol|gols|placar|narracao|narrador|escalacao|estadio|jornada|jornada esportiva|"
                 "sem delay|tempo real|brasileiro|flamengo|palmeiras|corinthians|sao paulo|santos|vasco|fluminense|"
                 "botafogo|gremio|internacional|atletico|atletico mg|cruzeiro|bahia|fortaleza|ceara|sport|bragantino|"
                 "mirassol|juventude|vitoria|criciuma|athletico|coritiba|goias|remo|paysandu|chapecoense|cuiaba|"
                 "america mg|vila nova|novorizontino|ponte preta|guarani|barcelona|real madrid|liverpool|"
                 "manchester|chelsea|arsenal|psg|boca juniors|river plate|selecao")
_SCORE = re.compile(r"\b\d{1,2} ?x ?\d{1,2}\b")


def is_match_footage(title: str) -> bool:
    """Transmissao/narracao/melhores momentos de partida (comentario e pos-jogo passam)."""
    t = " " + norm(title) + " "
    if _SPORT_COMMENT.search(t):
        return False
    if _SPORT_STRONG.search(t):
        return True
    if not _VS.search(t):
        return False
    # "a x b" so conta como partida com contexto esportivo (placar, campeonato, jogo...) (evita "Lula x Bolsonaro")
    sports = bool(_SCORE.search(t) or _COMPETITION.search(t) or _SPORT_CTX.search(t))
    live = bool(_SPORT_LIVE.search(t) or _LIVE_DOT in (title or ""))
    return sports and (live or bool(_COMPETITION.search(t)))

_TV_CHANNELS = {norm(x) for x in (
    "globo|tv globo|gshow|globoplay|globonews|ge|sportv|sbt|sbt news|sbt online|record|record tv|recordtv|"
    "record news|band|band jornalismo|band tv|bandsports|redetv|rede tv|tv cultura|multishow|"
    "programa do ratinho|a fazenda|the noite com danilo gentili|jogo aberto|espn brasil|tnt sports brasil|"
    "domingao com huck|mais voce|encontro").split("|")}
_TV_HANDLES = {"@globonews", "@bandjornalismo", "@sbtnews", "@recordnews", "@programadoratinho", "@afazenda",
               "@thenoite", "@jogoaberto", "@espnbrasil", "@gshow", "@tvglobo", "@sbt", "@recordtv", "@redetv",
               "@band", "@sportv", "@ge", "@tntsportsbr"}
_TV_WORDS = _rx("bbb|big brother brasil|a fazenda|domingao|fantastico|jornal nacional|novela|capitulo de hoje|"
                "mais voce|encontro com patricia|altas horas|caldeirao|programa silvio santos|casos de familia|"
                "the voice brasil|danca dos famosos|estrela da casa|power couple|ilha record")
_FILM = _rx("filme completo|filme dublado|filmes completos|serie completa|episodio completo|temporada completa|"
            "trailer oficial|official trailer|trailer dublado|trailer legendado|filme de acao|filme de terror|"
            "assistir filme|dublado completo|legendado completo")
_MUSIC = _rx("clipe oficial|videoclipe|video oficial|official video|official music video|music video|lyric video|"
             "lyrics|com letra|audio oficial|official audio|visualizer|dvd ao vivo|show completo|album completo|"
             "ep completo|acustico|karaoke|remix|cover oficial")
_MUSIC_CHANNEL = re.compile(r"(vevo|records|music|musica|oficial \w+ music|topic)$")
_BET = _rx("aposta|apostas|bet|bets|betano|bet365|blaze|cassino|casino|tigrinho|fortune tiger|aviator|roleta|"
           "slot|slots|palpite|palpites|odds|jogo do bicho|mines|crash game|esportes da sorte|estrelabet|pixbet")
_KIDS = _rx("infantil|infantis|kids|crianca|criancas|para criancas|bebe|bebes|brinquedo|brinquedos|toys|"
            "escolinha|desenho animado|desenhos animados|musica infantil|turma da monica|galinha pintadinha|"
            "luccas neto|enaldinho|maria clara e jp|familia brancoala")
_KIDS_CHANNELS = {norm(x) for x in "luccas neto|enaldinho|maria clara e jp|galinha pintadinha|mundo bita|"
                  "turma da monica|gato galactico|felipe neto kids".split("|")}


def hard_block(title: str, channel: str = "", channel_url: str | None = None) -> str | None:
    """Bloqueios fixos do dono: canais da lista canais.HARD_BLOCK e imagens de partida de futebol."""
    from .canais import HARD_BLOCK

    ch = norm(channel)
    url = (channel_url or "").lower().rstrip("/")
    for b in HARD_BLOCK:
        if b.startswith("@"):
            if url.endswith("/" + b.lower()) or f"/{b.lower()}/" in url + "/":
                return "canal bloqueado"
        elif norm(b) and (ch == norm(b) or url.endswith("/" + norm(b).replace(" ", ""))):
            return "canal bloqueado"
    if is_match_footage(title):
        return "esporte_transmissao"
    return None


def is_tv_handle(handle: str) -> bool:
    return handle.strip().lower() in _TV_HANDLES


def categories(cfg) -> list[str]:
    cats = cfg.get("busca.pular_categorias", ALL_CATEGORIES) if cfg is not None else ALL_CATEGORIES
    return [str(c) for c in (cats or [])]


def skip_reason(title: str, channel: str = "", channel_url: str | None = None, description: str = "",
                yt_categories: list[str] | None = None, tags: list[str] | None = None,
                active: list[str] | None = None) -> str | None:
    """Devolve a categoria que manda pular o video (ou None)."""
    active = ALL_CATEGORIES if active is None else active
    if not active:
        return None
    t = " " + norm(title) + " "
    d = " " + norm((description or "")[:400]) + " "
    ch = norm(channel)
    url = (channel_url or "").lower()
    handle = ("@" + url.split("/@", 1)[1].split("/")[0]) if "/@" in url else ""
    tg = " " + norm(" ".join(tags or [])[:400]) + " "
    ycat = {str(x).lower() for x in (yt_categories or [])}

    if "apostas" in active and (_BET.search(t) or _BET.search(tg)):
        return "apostas"
    if "menores" in active and (_KIDS.search(t) or ch in _KIDS_CHANNELS or _KIDS.search(tg)):
        return "menores"
    if "musica" in active:
        if "music" in ycat or _MUSIC_CHANNEL.search(ch):
            return "musica"
        if _MUSIC.search(t) and not _SPORT_COMMENT.search(t):
            return "musica"
    if "filmes_series" in active and (_FILM.search(t) or "film & animation" in ycat and _FILM.search(d)):
        return "filmes_series"
    if "esporte_transmissao" in active and is_match_footage(title):
        return "esporte_transmissao"
    if "tv_aberta" in active:
        if ch in _TV_CHANNELS or handle.lower() in _TV_HANDLES or _TV_WORDS.search(t):
            return "tv_aberta"
    return None
