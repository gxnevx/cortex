"""Modelos de titulo/gancho por intensidade do tom (fabrica.tom: neutro 0, polemico 1, malicioso 2,
super_polemico 3, modo_besta 4). O nivel e as regras vem do modulo compartilhado `fabrica.tom`.

Os modelos sao genericos de proposito: o cerebro heuristico nao entende o video, entao nenhum modelo afirma
fato novo. Modelos com "req" so entram se a fala do trecho tiver aquelas palavras (texto normalizado, sem
acento), para a insinuacao/acusacao ficar apoiada no que foi dito. Piso fixo (fabrica.tom.FLOOR) em todos os
niveis: nada de crime, traicao, caso ou ato sexual inventado sobre pessoa real; nada sexual com menores; nada
de odio contra grupos; nada de informacao falsa. Sem bolinhas nem travessoes; emojis entram pelo cerebro.
"""
from __future__ import annotations

import re

_REVEAL = r"\b(nunca contei|ninguem sabe|vou contar|segredo|vou revelar|a verdade e|vou abrir o jogo|confesso)\b"

# (titulo, req) ; req = regex no texto normalizado do trecho (None = generico, sempre seguro)
MALICIOUS_TITLES: dict[str, list[tuple[str, str | None]]] = {
    "geral": [
        ("Ficou claro o que quis dizer", None), ("Quem entendeu, entendeu", None), ("Disse sem dizer", None),
        ("Leu nas entrelinhas?", None), ("Essa frase não saiu por acaso", None), ("Tem coisa aí, presta atenção", None),
        ("Repara no final", None), ("O recado foi dado", None), ("Entendedores entenderão", None),
        ("Ninguém comentou, mas todo mundo percebeu", None), ("Era só uma conversa até essa parte", None),
        ("Ninguém esperava ouvir isso ao vivo", None),
    ],
    "polemica": [
        ("Depois dessa, será que convidam de novo?", None), ("A indireta foi pra quem?", None),
        ("O clima mudou depois dessa frase", None), ("Falou o que todo mundo pensava e ninguém dizia", None),
        ("Ninguém teve coragem de rebater na hora", None), ("Foi indireta ou foi direta mesmo?", None),
        ("Essa resposta não foi à toa", None),
        ("Mandou o recado sem citar nome", r"\b(nao vou falar o nome|sem citar|nao vou citar|voces sabem quem|todo mundo sabe quem)\b"),
        ("Ninguém esperava que fosse admitir isso ao vivo", r"\b(admito|confesso|assumo|nao vou negar|nao nego|e verdade)\b"),
        ("Não negou", r"\b(nao nego|nao vou negar|nao vou mentir|e verdade|confirmo)\b"),
        ("O silêncio disse tudo", r"\b(sem comentarios|proxima pergunta|nao vou responder|prefiro nao falar|nao posso falar)\b"),
    ],
    "palavrao": [("A paciência acabou bem nessa hora", None), ("Era pra ser tranquilo, até que...", None),
                 ("Segurou até onde deu", None)],
    "risada": [("Era pra ser sério, até que...", None), ("A risada entregou tudo", None),
               ("Ninguém conseguiu segurar depois dessa", None), ("A pergunta era inocente. A resposta não", None),
               ("Duplo sentido ou foi só eu?", None)],
    "gancho": [("Entregou o que rolava nos bastidores", r"\bbastidor"),
               ("Contou o que ninguém tinha coragem de contar", _REVEAL),
               ("O que aconteceu depois da festa", r"\bfesta\b"),
               ("Achou que ninguém ia lembrar dessa história", r"\b(uma vez|teve um dia|lembro que|na epoca)\b"),
               ("A história começou normal...", None), ("Espera a parte que muda tudo", None)],
    "emocao": [("Não era pra ter falado isso, mas falou", None), ("Abriu o coração e ninguém esperava", None),
               ("Essa parte pesou mais do que parece", None)],
    "surpresa": [("A reação diz mais que mil palavras", None), ("Ninguém tava pronto pra essa resposta", None),
                 ("Foi só uma pergunta, mas...", None), ("Até agora tentando entender essa", None)],
    "games": [("O chat percebeu antes dele", None), ("Ninguém viu isso na primeira vez", None),
              ("Esse detalhe passou batido por quase todo mundo", r"\b(easter egg|detalhe|segredo|escondid)")],
}
# intensidade 3+ (super_polemico / modo_besta): verbos agressivos e caixa alta nas palavras-chave
AGGRESSIVE_TITLES: dict[str, list[tuple[str, str | None]]] = {
    "geral": [("Isso aqui vai DIVIDIR opiniões", None), ("Você concorda com ISSO?", None),
              ("Fala a verdade: tá CERTO ou passou do ponto?", None), ("Ninguém tá preparado pra ESSA", None)],
    "polemica": [("PERDEU A LINHA ao vivo", None), ("Não deixou BARATO", None), ("Foi pra CIMA sem medo", None),
                 ("A treta saiu do CONTROLE", None), ("DESTRUIU o argumento na cara", None),
                 ("HUMILHOU sem dó nessa resposta", None), ("Calou a mesa INTEIRA", None),
                 ("Foi ATAQUE direto ou só verdade?", None),
                 ("EXPÔS tudo ao vivo", _REVEAL)],
    "palavrao": [("PERDEU A LINHA e soltou o verbo", None), ("Ninguém SEGURA mais", None),
                 ("Chutou o balde AO VIVO", None)],
    "risada": [("Ninguém AGUENTOU essa", None), ("Acabou com a resenha INTEIRA", None)],
    "gancho": [("EXPÔS os bastidores sem dó", r"\bbastidor"), ("ABRIU O JOGO ao vivo", _REVEAL),
               ("Contou TUDO e não se arrependeu", _REVEAL)],
    "emocao": [("DESABOU ao vivo", r"\b(chorei|chorando|chorar|lagrima|emocionad)"),
               ("Falou o que ninguém tem CORAGEM de falar", None)],
    "surpresa": [("Ficou SEM REAÇÃO", None), ("TRAVOU ao vivo", None)],
    "games": [("O chat ENLOUQUECEU com isso", None), ("Isso aqui é INSANO", None)],
}
MALICIOUS_HOOKS: list[tuple[str, str | None]] = [
    ("QUEM ENTENDEU, ENTENDEU", None), ("DISSE SEM DIZER", None), ("REPARA NO FINAL", None),
    ("FICOU NO AR", None), ("TEM COISA AÍ", None), ("O RECADO FOI DADO", None), ("LEU NAS ENTRELINHAS?", None),
    ("FOI INDIRETA?", None), ("ESPERA ESSA PARTE", None),
    ("NÃO NEGOU", r"\b(nao nego|nao vou negar|e verdade|confirmo)\b"),
    ("O SILÊNCIO DISSE TUDO", r"\b(sem comentarios|proxima pergunta|nao vou responder|prefiro nao falar)\b"),
    ("ENTREGOU OS BASTIDORES", r"\bbastidor"),
]
AGGRESSIVE_HOOKS: list[tuple[str, str | None]] = [
    ("PERDEU A LINHA", None), ("SEM DÓ", None), ("VOCÊ CONCORDA?", None), ("ISSO DIVIDE OPINIÃO", None),
    ("TRAVOU AO VIVO", None), ("NÃO DEIXOU BARATO", None), ("ABRIU O JOGO", _REVEAL),
]
MALICIOUS_SUFFIX = ["quem entendeu, entendeu", "ficou claro o recado", "disse sem dizer", "e o clima mudou na hora",
                    "leu nas entrelinhas?", "foi indireta?", "repara na resposta"]
# frase direta (xingamento/acusacao) nao combina com "entrelinhas": sufixos proprios
MALICIOUS_SUFFIX_DIRECT = ["o recado foi dado", "e o clima mudou na hora", "falou sem filtro", "e ninguém esperava",
                           "depois dessa, será que convidam de novo?"]
AGGRESSIVE_SUFFIX = ["e PERDEU A LINHA", "sem dó nenhum", "e não deixou BARATO", "e a mesa TRAVOU",
                     "na cara de todo mundo"]
RAGEBAIT_SUFFIX = ["se discordar, comenta", "tá certo ou errado?", "quero ver defender isso", "time dele ou contra?"]
MALICIOUS_EMOJIS = ["\U0001F60F", "\U0001FAE2", "\U0001F440", "\U0001F633", "\U0001F910", "\U0001F525"]
AGGRESSIVE_EMOJIS = ["\U0001F525", "\U0001F624", "\U0001F480", "\U0001F633", "\U0001F62C", "\U0001F92F"]

KIND_GROUP = {"polemica": "polemica", "debate": "polemica", "palavrao": "palavrao", "risada": "risada",
              "humor": "risada", "gancho": "gancho", "impacto": "gancho", "emocao": "emocao", "surpresa": "surpresa",
              "games": "games", "twitch": "games", "chat": "surpresa", "comentarios": "geral", "heatmap": "geral",
              "geral": "geral"}


def _ok(req: str | None, text: str) -> bool:
    return req is None or bool(re.search(req, text))


def _pool(table: dict, kind: str, clip_text: str) -> tuple[list[str], list[str]]:
    g = KIND_GROUP.get(kind, "geral")
    items = table.get(g, []) + (table.get("geral", []) if g != "geral" else [])
    return ([t for t, r in items if r is not None and _ok(r, clip_text)], [t for t, r in items if r is None])


def titles_for(kind: str, clip_text: str, intensity: int = 2) -> list[str]:
    """Modelos aplicaveis ao tipo do momento (os apoiados na fala tem mais chance)."""
    spec, gen = _pool(MALICIOUS_TITLES, kind, clip_text)
    if intensity >= 3:
        s2, g2 = _pool(AGGRESSIVE_TITLES, kind, clip_text)
        w = 2 if intensity == 3 else 3
        spec, gen = spec + s2 * w, (gen if intensity == 3 else gen[: len(gen) // 2]) + g2 * w
    return spec * 3 + gen


def hooks_for(clip_text: str, intensity: int = 2) -> list[str]:
    spec = [h for h, r in MALICIOUS_HOOKS if r is not None and _ok(r, clip_text)]
    gen = [h for h, r in MALICIOUS_HOOKS if r is None]
    if intensity >= 3:
        spec += [h for h, r in AGGRESSIVE_HOOKS if r is not None and _ok(r, clip_text)] * 2
        gen = gen[: len(gen) // 2] + [h for h, r in AGGRESSIVE_HOOKS if r is None] * 2
    return spec * 3 + gen


def suffixes_for(kind: str | None, intensity: int = 2) -> list[str]:
    direct = kind in ("polemica", "palavrao")
    if intensity >= 4:
        return RAGEBAIT_SUFFIX + (AGGRESSIVE_SUFFIX if direct else MALICIOUS_SUFFIX)
    if intensity == 3:
        return AGGRESSIVE_SUFFIX if direct else MALICIOUS_SUFFIX + AGGRESSIVE_SUFFIX[:2]
    return MALICIOUS_SUFFIX_DIRECT if direct else MALICIOUS_SUFFIX


def emojis_for(intensity: int) -> list[str]:
    return AGGRESSIVE_EMOJIS if intensity >= 3 else MALICIOUS_EMOJIS


def count_templates() -> int:
    return sum(len(v) for v in MALICIOUS_TITLES.values()) + sum(len(v) for v in AGGRESSIVE_TITLES.values())


def prompt_examples(intensity: int) -> str:
    """Exemplos extras para o prompt da IA (o guia e o piso vem de fabrica.tom.prompt_block)."""
    if intensity <= 1:
        return ""
    ex = ('"Não negou \U0001FAE2", "Ficou claro o que ele quis dizer \U0001F60F", "Ele entregou o que rolava nos '
          'bastidores \U0001F440", "Ninguém esperava que ela fosse admitir isso ao vivo", "O silêncio dele disse tudo", '
          '"A pergunta era inocente. A resposta não"')
    if intensity >= 3:
        ex += ', "Ele PERDEU A LINHA ao vivo \U0001F525", "HUMILHOU sem dó nessa resposta", "Você concorda com ISSO?"'
    if intensity >= 4:
        ex += ', "\\"Vai tomar no c*\\" e a mesa travou \U0001F480 se discordar, comenta"'
    return ("- Exemplos de estilo (adapte ao trecho; cada ideia como festa, bastidores, silêncio, admitir precisa "
            f"estar na fala): {ex}.")
