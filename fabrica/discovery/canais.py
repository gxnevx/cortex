"""Canais brasileiros grandes usados como fonte quando `busca.usar_canais_sugeridos` = true (padrao).

Handles do YouTube verificados em 23/11/2026 (pagina /@handle respondeu 200 com o nome certo).
Logins da Twitch verificados com o yt-dlp (VODs e/ou clipes recentes). Canais que deixarem de existir sao
ignorados automaticamente (e lembrados em data/estado/canais_invalidos.json).

Formato YouTube: (handle, categoria, abas)  - abas: "streams" (lives gravadas) e/ou "videos".
Formato Twitch:  (login, categoria)
"""
from __future__ import annotations

YOUTUBE: list[tuple[str, str, tuple[str, ...]]] = [
    # podcasts / entrevistas (lives longas = muito material)
    ("@flowpodcast", "podcast", ("streams", "videos")),
    ("@podpah", "podcast", ("streams", "videos")),
    ("@InteligenciaLtda", "podcast", ("streams", "videos")),
    ("@ticaracaticast", "podcast", ("streams", "videos")),
    ("@charlapodcast", "podcast", ("videos",)),
    ("@FalaGlauberPodcast", "podcast", ("videos", "streams")),
    ("@ProgramaPanico", "podcast", ("streams", "videos")),
    ("@primorico", "podcast", ("videos",)),
    # noticias / politica
    ("@CNNbrasil", "noticias", ("streams", "videos")),
    ("@jovempannews", "politica", ("streams", "videos")),
    ("@OsPingosNosIs", "politica", ("streams",)),
    ("@GloboNews", "noticias", ("videos", "streams")),
    ("@uol", "noticias", ("videos", "streams")),
    ("@BandJornalismo", "noticias", ("videos", "streams")),
    ("@SBTNews", "noticias", ("videos", "streams")),
    ("@recordnews", "noticias", ("streams", "videos")),
    ("@MetropolesTV", "noticias", ("videos", "streams")),
    ("@RevistaOeste", "politica", ("streams", "videos")),
    ("@brasil247", "politica", ("streams",)),
    ("@canalmynews", "politica", ("streams", "videos")),
    ("@iclnoticias", "politica", ("streams",)),
    ("@poder360", "politica", ("videos", "streams")),
    ("@CamaradosDeputadosOficial", "politica", ("streams", "videos")),   # licenca CC BY 4.0
    # esportes
    ("@CazeTV", "esportes", ("streams", "videos")),
    ("@JogoAberto", "esportes", ("streams", "videos")),
    ("@ESPNBrasil", "esportes", ("videos", "streams")),
    ("@desimpedidos", "esportes", ("videos",)),
    ("@flowsportclub", "esportes", ("streams", "videos")),
    # streamers / games
    ("@Gaules", "games", ("videos", "streams")),
    ("@CellbitLives", "games", ("streams", "videos")),
    ("@LOUDgg", "games", ("videos",)),
    ("@LOUDCoringa", "games", ("videos", "streams")),
    ("@T3ddy", "games", ("videos",)),
    ("@BRKsEDU", "games", ("videos",)),
    ("@JovemNerd", "games", ("videos",)),
    # humor / entretenimento
    ("@felipeneto", "entretenimento", ("videos",)),
    ("@portadosfundos", "humor", ("videos",)),
    ("@TheNoite", "humor", ("videos",)),
    ("@ProgramadoRatinho", "entretenimento", ("videos",)),
    ("@Rezendeevil", "entretenimento", ("videos",)),
]

TWITCH: list[tuple[str, str]] = [
    ("casimiro", "entretenimento"),
    ("gaules", "games"),
    ("cellbit", "games"),
    ("baiano", "games"),
    ("felps", "games"),
    ("tck10", "games"),
    ("liminhag0d", "games"),
    ("brino", "games"),
    ("paulinholokobr", "entretenimento"),
    ("xarola_", "games"),
    ("mount", "games"),
    ("ninext", "games"),
    ("jukes", "games"),
    ("zigueira", "games"),
    ("bagi", "games"),
]

KICK: list[tuple[str, str]] = [
    # grandes streamers BR migraram para a Kick (verificados com o yt-dlp em 23/11/2026)
    ("coringa", "games"),
    ("paulinholokobr", "entretenimento"),
    ("gaules", "games"),
    ("tck10", "games"),
    ("jonvlogs", "entretenimento"),
]

# ------------------------------------------------------------------ fontes estrangeiras
# Usadas quando busca.idiomas inclui "en" e busca.estrangeiro.ativo = true. So entram com nota alta
# (busca.estrangeiro.nota_minima). Verificadas em 23/11/2026 (canal existe e tem video/clipe recente).
# permite_cortes: "sim" = o criador libera react/corte publicamente; "incerto" = cortes circulam aos montes
# sem derrubada conhecida, mas sem permissao formal [INFERENCIA]. Ninguem aqui proibe cortes publicamente.
# Formato YouTube: (handle, categoria, abas, permite_cortes, nota)
YOUTUBE_EN: list[tuple[str, str, tuple[str, ...], str, str]] = [
    ("@IShowSpeed", "humor", ("streams", "videos"), "incerto", "lives IRL; cortes dele estao em todo lugar"),
    ("@KaiCenat", "humor", ("streams", "videos"), "incerto", "maior streamer dos EUA; cortes toleradissimos"),
    ("@xQcOW", "games", ("videos",), "sim", "xQc libera react/corte publicamente"),
    ("@penguinz0", "humor", ("videos",), "incerto", "MoistCr1TiKaL; comentario de internet/polemicas"),
    ("@Jynxzi", "games", ("videos",), "incerto", "games; cortes de reacao"),
    ("@ludwig", "games", ("videos",), "incerto", "games/entretenimento"),
    ("@TheoVon", "podcast", ("videos",), "incerto", "podcast; cortes circulam muito"),
    ("@joerogan", "podcast", ("videos",), "incerto", "JRE; tem canal oficial de cortes (concorrencia)"),
    ("@impaulsive", "podcast", ("videos",), "incerto", "Logan Paul; polemicas de celebridade"),
    ("@FULLSENDPODCAST", "podcast", ("videos",), "incerto", "NELK; humor/polemica"),
    ("@FlagrantPodcast", "podcast", ("videos",), "incerto", "Andrew Schulz; humor"),
    ("@HasanAbi", "politica", ("videos", "streams"), "incerto", "politica dos EUA; so quando o tema bomba aqui"),
]
TWITCH_EN: list[tuple[str, str]] = [
    ("kaicenat", "humor"), ("jynxzi", "games"), ("caseoh_", "games"), ("plaqueboymax", "humor"),
    ("agent00", "humor"), ("zackrawrr", "games"), ("hasanabi", "politica"),
]
KICK_EN: list[tuple[str, str]] = [("xqc", "games"), ("adinross", "humor")]
PERMISSAO_EN = {h.lower(): p for h, _c, _t, p, _n in YOUTUBE_EN} | {"xqc": "sim"}
FOREIGN_NAMES = ({h.lower() for h, *_ in YOUTUBE_EN} | {lg for lg, _ in TWITCH_EN} | {lg for lg, _ in KICK_EN})

# Bloqueio fixo pedido pelo dono (vale mesmo para busca e canais monitorados)
HARD_BLOCK = ["alanzoka", "PodPeople", "Pod People", "TV Senado", "@tvsenado", "@afazenda", "A Fazenda"]
