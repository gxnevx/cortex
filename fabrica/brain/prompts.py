"""Prompts (pt-BR) e esquemas JSON usados pelos cerebros com IA.

Regras do dono refletidas aqui:
- conteudo.emojis (padrao true): 1-2 emojis no titulo, no maximo 1 no gancho; false = nenhum emoji.
- Nunca usar travessao, meia-risca nem marcadores tipo bolinha em texto gerado (o pos-processamento
  tambem remove). Este arquivo nao contem esses caracteres de proposito.
- Duracao respeita corte.duracao_min_s / duracao_max_s (Shorts > 60 s com Content ID sao bloqueados).
"""
from __future__ import annotations

import re

from .. import tom as tom_cfg
from . import modelos_tom as mt
from ..models import Candidate, Trend
from ..util import fmt_duration, fmt_views

SYSTEM_CLIPS = (
    "Você é editor-chefe de um canal brasileiro de cortes virais (YouTube Shorts, TikTok, Reels). "
    "Sua especialidade é achar, em vídeos longos (lives, podcasts, debates, entrevistas, gameplays, programas), "
    "os trechos com maior chance de viralizar e escrever títulos que prendem sem mentir. "
    "Responda SOMENTE com JSON válido: sem markdown, sem comentários, sem texto antes ou depois."
)

SYSTEM_TRENDS = (
    "Você é estrategista de conteúdo viral no Brasil. Você sabe quais assuntos do momento rendem bons "
    "cortes de vídeo (trechos falados de lives, podcasts, debates, entrevistas, reacts, gameplays). "
    "Responda SOMENTE com JSON válido: sem markdown, sem comentários, sem texto antes ou depois."
)

CATEGORIAS_TXT = "politica, polemica, games, humor, entretenimento, esportes, podcast, noticias, celebridades, outros"

PONTUACAO_TXT = (
    "Não use travessão nem meia-risca (traço longo) e nem marcadores tipo bolinha em nenhum texto: "
    "use só hífen simples (-), vírgula, dois-pontos ou barra vertical (|)."
)

_CLIP_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "inicio": {"type": "string"},
        "fim": {"type": "string"},
        "titulo": {"type": "string"},
        "gancho": {"type": "string"},
        "descricao": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "pontuacao": {"type": "integer"},
        "motivo": {"type": "string"},
        "categoria": {"type": "string"},
        "serie": {"type": "string"},          # "" = nao e serie (sem tipos uniao: mais compativel com o Ollama)
        "parte": {"type": "integer"},         # 0 = nao e serie
        "layout": {"type": "string"},
        "teaser_inicio": {"type": "string"},  # momento mais explosivo (1,5 a 3 s) que abre o video
        "teaser_fim": {"type": "string"},
        "teaser_texto": {"type": "string"},
    },
    "required": ["inicio", "fim", "titulo", "gancho", "pontuacao", "motivo"],
}
CLIPS_SCHEMA = {
    "type": "object",
    "properties": {"cortes": {"type": "array", "items": _CLIP_ITEM_SCHEMA}},
    "required": ["cortes"],
}
TRENDS_SCHEMA = {
    "type": "object",
    "properties": {"temas": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "indice": {"type": "integer"},
            "categoria": {"type": "string"},
            "pontuacao": {"type": "integer"},
            "tipo": {"type": "string"}, "motivo": {"type": "string"},
            "buscas": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["indice", "categoria", "pontuacao", "buscas"],
    }}},
    "required": ["temas"],
}
RANK_SCHEMA = {
    "type": "object",
    "properties": {"cortes": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "indice": {"type": "integer"},
            "titulo": {"type": "string"},
            "gancho": {"type": "string"},
            "descricao": {"type": "string"},
            "hashtags": {"type": "array", "items": {"type": "string"}},
            "pontuacao": {"type": "integer"},
            "motivo": {"type": "string"},
            "categoria": {"type": "string"},
            "teaser_texto": {"type": "string"},
        },
        "required": ["indice", "titulo", "pontuacao"],
    }}},
    "required": ["cortes"],
}


def _emojis(cfg) -> bool:
    from .base import emojis_enabled

    return emojis_enabled(cfg)


def _title_rules(cfg) -> str:
    if _emojis(cfg):
        emo_t = ("1 a 2 emojis (no fim ou logo depois da citação; nunca repita o mesmo emoji; "
                 "prefira \U0001F62D \U0001F480 \U0001F633 \U0001F440 \U0001F62C \U0001F525 e evite \U0001F602 \U0001F923 \U0001F631)")
        emo_h = "no máximo 1 emoji"
        ex_t = ('"\\"Você é um mentiroso\\" \U0001F633 o clima pesou ao vivo", '
                '"Casimiro não tava preparado pra essa pergunta \U0001F633", "\\"Eu fui traído\\" \U0001F62D ninguém esperava"')
        ex_h = '"\\"VOCÊ É UM MENTIROSO\\""'
    else:
        emo_t = "SEM EMOJIS (proibido usar emoji); chame atenção só pelas palavras"
        emo_h = "sem emojis"
        ex_t = ('"\\"Você é um mentiroso\\": o clima pesou ao vivo", "Casimiro não tava preparado pra essa pergunta", '
                '"\\"Eu fui traído\\": ninguém esperava essa"')
        ex_h = '"\\"VOCÊ É UM MENTIROSO\\""'
    return (
        f'- "titulo": estilo geração Z brasileira, 35 a 75 caracteres, {emo_t}. PROVOCATIVO e com lacuna de curiosidade. '
        "Quando a pessoa disse uma frase explosiva (xingamento, acusação, grito, choro, punchline, revelação), comece "
        "com ESSA frase ENTRE ASPAS, palavra por palavra como está na transcrição (pode ter palavrão: o sistema "
        "mascara sozinho), e complete com poucas palavras de contexto. Nunca invente citação nem fato: a frase entre "
        "aspas tem que existir na transcrição. No máximo 1 palavra em CAIXA ALTA fora da citação; no máximo 1 gíria; "
        f"\"KKKKKK\" quando for risada. Não escreva \"Parte 1\" (o sistema numera as séries). Ex.: {ex_t}.\n"
        f'- "gancho": texto curtíssimo para a tela (até 7 palavras e 40 caracteres, CAIXA ALTA, {emo_h}). '
        "De preferência a frase mais pesada do trecho ENTRE ASPAS, exatamente como foi dita; senão uma frase "
        f"provocativa curta. Ex.: {ex_h}.\n"
        '- "teaser_inicio", "teaser_fim", "teaser_texto": o momento MAIS polêmico/explosivo DENTRO do corte '
        "(palavrão, insulto, acusação, grito, choro ou punchline), com 1,5 a 3 segundos, começando pelo menos 4 s "
        "depois do início do corte. Ele toca primeiro como abertura do vídeo. \"teaser_texto\" = as palavras exatas "
        "(3 a 8 palavras) copiadas da transcrição; os tempos no formato mm:ss (o sistema acerta pelas palavras).\n"
        + "- " + tom_cfg.prompt_block(cfg).replace("\n", "\n- ") + "\n"
        + mt.prompt_examples(int(tom_cfg.settings(cfg).get("intensidade", 2)))
    )


def _example_json(cfg) -> str:
    t = ("\\\"Você tá mentindo\\\" \U0001F633 o clima pesou" if _emojis(cfg)
         else "\\\"Você tá mentindo\\\": o clima pesou")
    h = "\\\"VOCÊ TÁ MENTINDO\\\""
    return ('{"cortes":[{"inicio":"mm:ss","fim":"mm:ss","titulo":"' + t + '","gancho":"' + h + '",'
            '"descricao":"...","hashtags":["#podcast","#polemica"],"pontuacao":82,"motivo":"...",'
            '"categoria":"polemica","serie":null,"parte":null,"layout":"full",'
            '"teaser_inicio":"mm:ss","teaser_fim":"mm:ss","teaser_texto":"você tá mentindo"}]}')


def _video_block(video: Candidate) -> str:
    lines = [f"Título: {video.title}"]
    if video.channel:
        lines.append(f"Canal: {video.channel}")
    info = [f"Plataforma: {video.platform}"]
    if video.duration:
        info.append(f"Duração: {fmt_duration(video.duration)}")
    if video.views:
        info.append(f"Views: {fmt_views(video.views)}")
    if video.is_live or video.was_live:
        info.append("era uma LIVE")
    lines.append(" | ".join(info))
    if video.topic:
        lines.append(f"Assunto em alta que trouxe este vídeo: {video.topic}")
    if video.description:
        d = " ".join(video.description.split())[:400]
        lines.append(f"Descrição: {d}")
    return "\n".join(lines)


_LANG_NAMES = {"en": "INGLÊS", "es": "ESPANHOL", "fr": "FRANCÊS", "it": "ITALIANO", "de": "ALEMÃO", "ja": "JAPONÊS"}


def video_lang(video: Candidate) -> str:
    """'pt', 'en', 'es'... (Candidate.extra["idioma"] ou o idioma do audio informado pela plataforma)."""
    ex = video.extra or {}
    lang = ex.get("idioma") or ex.get("language") or "pt"
    return str(lang).split("-")[0].lower() or "pt"


def foreign_block(video: Candidate) -> str:
    lang = video_lang(video)
    if lang == "pt":
        return ""
    nome = _LANG_NAMES.get(lang, lang.upper())
    return (f"\nIDIOMA: o vídeo está em {nome}. Escolha os cortes pelo conteúdo, mas escreva TUDO que vai ao público "
            "(titulo, gancho, descricao, hashtags, motivo) em português do Brasil, para brasileiros. Citação entre aspas "
            "no título/gancho = tradução FIEL da fala para o português (nunca invente). \"teaser_texto\" continua com as "
            "palavras ORIGINAIS da transcrição (o sistema traduz a legenda depois). Prefira momentos que um brasileiro "
            "entende sem contexto local (reação, treta, susto, risada, lance de jogo).\n")


def clips_prompt(video: Candidate, transcript_text: str, signals_text: str, cfg, limit: int,
                 chunk_note: str = "", auto: bool = True) -> str:
    dmin = int(cfg.get("corte.duracao_min_s", 20))
    dmax = int(cfg.get("corte.duracao_max_s", 58))
    dpart = int(cfg.get("corte.duracao_parte_s", 50))
    max_parts = int(cfg.get("corte.max_partes", 3))
    min_score = int(cfg.get("corte.pontuacao_minima", 55))
    series_ok = bool(cfg.get("corte.permitir_series", True))
    ideal_lo = max(dmin, min(30, dmax - 15))
    ideal_hi = min(dmax, 55)
    if auto:
        qty = (f"Você decide quantos cortes valem a pena (no máximo {limit}). Qualidade acima de quantidade: "
               "se só 1 trecho é bom, devolva 1.")
    else:
        qty = f"Devolva até {limit} cortes (os melhores), se houver material bom."
    series = (
        f"- SÉRIE: procure pelo menos UMA história ou discussão contínua de 70 a 160 s que prenda do começo ao fim "
        f"(história pessoal, treta com réplica, caso contado com desfecho, explicação completa). Se existir, devolva como "
        f"partes contínuas (a parte 2 começa exatamente onde a 1 termina), cada uma com {max(35, dpart - 10)} a {dpart} s, no "
        f"máximo {max_parts} partes, todas com o mesmo \"serie\" (nome curto do assunto) e \"parte\" 1, 2, 3. Termine cada parte "
        "num gancho (pergunta, revelação prestes a sair). Cada parte conta como um corte. Se não houver nenhuma, não force."
        if series_ok else "- Não faça séries: cada corte é independente (\"serie\": null)."
    )
    return f"""TAREFA: escolha os melhores cortes verticais (9:16) do vídeo abaixo para postar no YouTube Shorts e no TikTok.

O QUE É UM BOM CORTE
- Duração entre {dmin} e {dmax} segundos, NUNCA mais que {dmax} s (Shorts acima de 60 s com direitos autorais são bloqueados). O ideal costuma ser de {ideal_lo} a {ideal_hi} s.
- Gancho forte nos 2 primeiros segundos: começa numa frase de impacto, pergunta, acusação, risada ou revelação. Nunca comece em "então...", cumprimentos ou contexto morno.
- Autocontido: quem nunca viu o vídeo entende o que está acontecendo.
- Termina no clímax, na punchline ou na resposta: não corte antes do desfecho e não deixe "rabo" depois.
- Prefira: treta, polêmica, opinião forte, momento engraçado, reação exagerada, história surpreendente, revelação, frase de efeito, lance absurdo de jogo.
- Evite: propaganda/patrocínio, pedido de inscrição, silêncio, música, trechos sem contexto, fala arrastada.
- Os cortes NÃO podem se sobrepor.
{series}

QUANTIDADE: {qty}
PONTUAÇÃO ("pontuacao", de 0 a 100) = chance real de viralizar. Seja exigente: 85 ou mais só para momentos excepcionais; abaixo de {min_score} o corte será descartado.

TIPO DO CORTE (campo "tipo")
{TIPO_RULES}

TEXTOS (português do Brasil){foreign_block(video)}
{_title_rules(cfg)}
- "descricao": 1 a 2 frases com o contexto do trecho.
- "hashtags": 3 a 5, sem espaços, minúsculas e sem acento: 1 ampla, 1 a 2 do nicho e 1 da pessoa/programa/jogo (ex.: "#podcast", "#politica").
- "motivo": por que esse trecho vai viralizar (curto).
- "categoria": uma de {CATEGORIAS_TXT}.
- "layout": "full" (1 ou 2 rostos, podcast), "blur" (muita coisa na tela: gameplay com facecam, telejornal, slides), "split" (fala longa com pouco movimento, mostra gameplay embaixo) ou null.
- {PONTUACAO_TXT}

TEMPOS
- Use os carimbos [mm:ss] da transcrição.
- "inicio": carimbo da primeira frase do corte.
- "fim": carimbo da primeira frase que NÃO entra no corte (o corte acaba logo antes dela).
- Formato "mm:ss" ou "h:mm:ss".

VÍDEO
{_video_block(video)}

SINAIS AUTOMÁTICOS (pistas, não regras: "mais repetidos" do YouTube, clipes, horários citados nos comentários, picos do chat, volume, palavras-chave; os sinais do PÚBLICO valem mais que palavras-chave)
{signals_text or "nenhum"}

TRANSCRIÇÃO{(" " + chunk_note) if chunk_note else ""}
{transcript_text}

RESPONDA SÓ COM ESTE JSON (lista "cortes", do melhor para o pior):
{_example_json(cfg)}"""


def rank_clips_prompt(video: Candidate, candidates: list[dict], limit: int, cfg) -> str:
    """Passo final (Ollama, videos longos): escolhe e dá titulo aos melhores candidatos ja achados."""
    min_score = int(cfg.get("corte.pontuacao_minima", 55))
    rows = []
    for i, c in enumerate(candidates, 1):
        rows.append(f"{i}. [{fmt_duration(c['start'])} a {fmt_duration(c['end'])}] nota prévia {int(c.get('score', 0))} | "
                    f"{c.get('title', '')} | motivo: {c.get('reason', '')[:120]} | trecho: \"{c.get('excerpt', '')[:280]}\"")
    lista = "\n".join(rows)
    return f"""TAREFA: abaixo estão trechos candidatos a corte viral (Shorts/TikTok) do mesmo vídeo. Escolha os melhores (no máximo {limit}) e escreva o texto final de cada um.

Regras: nota de 0 a 100 = chance real de viralizar (abaixo de {min_score} é descartado). Categoria: uma de {CATEGORIAS_TXT}. Hashtags: 3 a 5. Textos em português do Brasil.{foreign_block(video)}
{_title_rules(cfg)}
{PONTUACAO_TXT}

VÍDEO
{_video_block(video)}

CANDIDATOS
{lista}

RESPONDA SÓ COM ESTE JSON:
{{"cortes":[{{"indice":1,"titulo":"...","gancho":"...","descricao":"...","hashtags":["#..."],"pontuacao":80,"motivo":"...","categoria":"..."}}]}}"""


GENERIC_TITLES = ("Ninguém comentou", "Leu nas entrelinhas", "Entendedores entenderão", "Você não vai acreditar",
                  "Ele não negou", "Ela não negou", "o que ele quis dizer", "o que ela quis dizer", "disse tudo",
                  "Não sei se eu entendi certo", "todo mundo percebeu")


def is_generic(title: str) -> bool:
    """Titulo que serviria para qualquer video (modelo pequeno adora copiar os exemplos do prompt)."""
    import unicodedata

    def plain(s: str) -> str:
        return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if not unicodedata.combining(c))

    t = plain(title or "")
    return not t.strip() or any(plain(g) in t for g in GENERIC_TITLES)


def short_tone(cfg) -> str:
    """Tom sem exemplos: a IA local copia qualquer exemplo que aparecer."""
    return re.sub(r"\s*\([^)]*'[^)]*\)", "", tom_cfg.prompt_block(cfg))


TIPOS = ("fala", "reacao", "curiosidade", "tutorial", "noticia")
TIPO_RULES = """Primeiro decida o "tipo" do trecho, porque o título muda com ele:
  fala = opinião, treta, história ou piada: frase forte ENTRE ASPAS, igual à transcrição, e quem disse.
  reacao = rage quit, surto, susto ou briga (muito comum em jogo): QUEM e o que aconteceu, com emoção.
  curiosidade = easter egg, segredo, teoria: o NOME REAL da coisa e de onde é (jogo, filme), sem mistério falso.
  tutorial = como fazer algo: título direto e honesto ("Como ..."), dizendo o resultado. Nada de frase polêmica.
  noticia = fato: o fato em si, direto, com o nome da pessoa ou do lugar.
Use frase polêmica só quando ela combina com o trecho; título real vale mais que título exagerado."""


def infer_tipo(video: Candidate, category: str | None = None) -> str:
    t = (video.title or "").lower()
    if re.search(r"\bcomo (fazer|ter|criar|ganhar|usar|conseguir|montar|instalar|jogar)|passo a passo|tutorial|aprenda|\bdicas?\b|how to", t):
        return "tutorial"
    from . import games

    if games.is_curiosity(video):
        return "curiosidade"
    if category == "games" or games.is_game(video):
        return "reacao"
    return "noticia" if category == "noticias" else "fala"


def retitle_prompt(video: Candidate, text: str, cfg) -> str:
    return f"""Escreva 1 título em português do Brasil para este trecho de vídeo (TikTok/Shorts), de 35 a 75 caracteres. Diga QUEM ou O QUÊ e o que acontece de surpreendente, usando palavras do próprio trecho, conforme o tipo. Nada genérico, nada inventado.
{TIPO_RULES}
{foreign_block(video)}
VÍDEO: {video.title} (canal {video.channel})
TRECHO: {text[:900]}
RESPONDA SÓ COM ESTE JSON: {{"titulo":"...","gancho":"até 7 palavras"}}"""


RETITLE_SCHEMA = {"type": "object", "required": ["titulo", "gancho"],
                  "properties": {"titulo": {"type": "string"}, "gancho": {"type": "string"}}}


def quick_clips_prompt(video: Candidate, blocks: list[str], limit: int, cfg) -> str:
    """Modo rapido da IA local: os trechos ja vem separados (sinais do publico); ela escolhe, ajusta e intitula."""
    dmin = int(cfg.get("corte.duracao_min_s", 15))
    dmax = int(cfg.get("corte.duracao_max_s", 45))
    emo = "1 ou 2 emojis no fim" if _emojis(cfg) else "sem emojis"
    lista = "\n\n".join(blocks)
    return f"""Abaixo estão trechos do mesmo vídeo que podem virar corte no TikTok e no Shorts. Escolha os {limit} melhores (menos, se os outros forem fracos).

Prefira: treta, opinião forte, frase chocante, piada, revelação, lance absurdo. Evite: propaganda, enrolação, trecho sem sentido sozinho.
- "inicio" e "fim": carimbos mm:ss do próprio trecho. Quem nunca viu o vídeo tem que entender: comece onde o assunto começa (a pergunta ou a frase que abre) e termine depois do desfecho, com a frase completa. Corte normal: {dmin} a {dmax} segundos.
- "historia": true só quando o trecho é UMA história ou discussão contínua que precisa de mais de {dmax} segundos. Aí "fim" pode ir até 3 minutos depois do "inicio" e o sistema divide em Parte 1, 2 e 3. Senão false.
- {TIPO_RULES}
- "titulo": português do Brasil, 35 a 75 caracteres, {emo}, seguindo o tipo. Nunca invente frase nem fato. Proibido título que serviria para qualquer vídeo.
- "gancho": até 7 palavras em CAIXA ALTA, sobre este trecho.
- "teaser_texto": as 3 a 8 palavras exatas do momento mais forte do trecho.
- "pontuacao": 0 a 100, chance real de viralizar.
- "hashtags": 3, específicas do assunto.
- "categoria": uma de {CATEGORIAS_TXT}.{foreign_block(video)}
- {short_tone(cfg)}

VÍDEO
{_video_block(video)[:500]}

TRECHOS
{lista}

RESPONDA SÓ COM ESTE JSON, do melhor para o pior:
{{"cortes":[{{"indice":1,"tipo":"fala","inicio":"mm:ss","fim":"mm:ss","historia":false,"titulo":"...","gancho":"...","teaser_texto":"...","descricao":"1 frase de contexto","hashtags":["#..."],"pontuacao":80,"categoria":"..."}}]}}"""


QUICK_CLIPS_SCHEMA = {"type": "object", "required": ["cortes"], "properties": {"cortes": {"type": "array", "items": {
    "type": "object", "required": ["indice", "tipo", "inicio", "fim", "titulo", "gancho", "teaser_texto", "pontuacao", "categoria"],
    "properties": {
        "indice": {"type": "integer"}, "tipo": {"type": "string", "enum": list(TIPOS)}, "inicio": {"type": "string"}, "fim": {"type": "string"}, "titulo": {"type": "string"},
        "gancho": {"type": "string"}, "teaser_texto": {"type": "string"}, "descricao": {"type": "string"},
        "hashtags": {"type": "array", "items": {"type": "string"}}, "pontuacao": {"type": "integer"},
        "historia": {"type": "boolean"}, "categoria": {"type": "string"}}}}}}


def quick_trends_prompt(trends: list[Trend], cfg, limit: int) -> str:
    """Versao curta para a IA local (a longa leva minutos na CPU)."""
    temas = ", ".join(cfg.get("busca.temas", []) or []) or "qualquer"
    lista = "\n".join(f"{i}. {t.topic[:70]}" for i, t in enumerate(trends, 1))
    return f"""Assuntos em alta no Brasil agora. Escolha até {limit} que rendem cortes de vídeo falado (podcast, live, debate, react, gameplay, futebol, humor, celebridade, política). Descarte serviço (loteria, clima, cotação) e tragédia.
Temas preferidos: {temas}.
"categoria": uma de {CATEGORIAS_TXT}. "pontuacao": 0 a 100. "buscas": 2 buscas curtas em português para achar vídeos longos.

{lista}

RESPONDA SÓ COM ESTE JSON, do melhor para o pior:
{{"temas":[{{"indice":1,"categoria":"polemica","pontuacao":80,"buscas":["...","..."]}}]}}"""


def trends_prompt(trends: list[Trend], cfg, limit: int) -> str:
    temas = ", ".join(cfg.get("busca.temas", []) or []) or "qualquer"
    rows = []
    for i, t in enumerate(trends, 1):
        extra = []
        if t.source:
            extra.append(f"fonte: {t.source}")
        if t.traffic:
            extra.append(f"tráfego: {t.traffic}")
        if t.related:
            extra.append("relacionados: " + "; ".join(str(r)[:80] for r in t.related[:3]))
        rows.append(f"{i}. {t.topic}" + (" | " + " | ".join(extra) if extra else ""))
    lista = "\n".join(rows)
    return f"""Abaixo estão assuntos em alta no Brasil agora. Escolha até {limit} que rendem BONS CORTES DE VÍDEO hoje: trechos falados de lives, podcasts, debates, entrevistas, programas de TV, reacts, gameplays/streamers, resenhas de futebol, humor, polêmicas e celebridades.

Descarte: assuntos que não geram vídeo falado (resultado de loteria, previsão do tempo, cotação, horóscopo, gabarito, serviços), notícias trágicas ou sensíveis (mortes, acidentes, crimes violentos) e coisas sem vídeo recente.
Temas preferidos do usuário: {temas}.

Para cada assunto escolhido devolva:
- "indice": número do assunto na lista;
- "categoria": uma de {CATEGORIAS_TXT};
- "pontuacao": de 0 a 100 = potencial de gerar cortes virais HOJE;
- "motivo": curto, sem emojis;
- "buscas": 2 a 3 buscas em português para achar vídeos LONGOS no YouTube/Twitch sobre o assunto (ex.: "<assunto> podcast", "<assunto> ao vivo", "<assunto> debate", "<assunto> entrevista", nome do streamer/programa).
{PONTUACAO_TXT}

ASSUNTOS
{lista}

RESPONDA SÓ COM ESTE JSON (do melhor para o pior):
{{"temas":[{{"indice":1,"categoria":"polemica","pontuacao":80,"motivo":"...","buscas":["...","..."]}}]}}"""
