"""Texto honesto: o que esta entre aspas no titulo, na tela e no gancho tem que existir na fala do corte.

Tambem tira do titulo os finais prontos que afirmam uma reacao que ninguem conferiu ("e a mesa TRAVOU", "sem dó nenhum").
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

_NUM = {"um": "1", "uma": "1", "dois": "2", "duas": "2", "tres": "3", "quatro": "4", "cinco": "5", "seis": "6", "sete": "7", "oito": "8",
        "nove": "9", "dez": "10", "pra": "para", "pro": "para", "ta": "esta", "to": "estou", "ce": "voce", "vc": "voce"}

# finais que afirmam coisa que o programa nao tem como saber
INVENTADOS = ["e a mesa travou", "a mesa travou", "a mesa rachou", "e a mesa rachou", "e o estudio travou", "o estudio caiu na risada", "calou a mesa inteira",
              "e perdeu a linha", "sem do nenhum", "e nao deixou barato", "ele nao deixou barato", "na cara de todo mundo", "e o clima mudou na hora",
              "o clima pesou ao vivo", "ninguem esperava essa resposta", "e ninguem esperava", "ninguem segurou o choro", "ninguem tankou kkkkkk",
              "ele perdeu a paciencia", "saiu do serio ao vivo", "ele nao segurou", "esse momento pegou todo mundo", "ninguem tava pronto pra isso",
              "o debate esquentou", "o chat enlouqueceu", "ficou claro o recado", "o recado foi dado", "disse sem dizer"]


def plano(s: str | None) -> str:
    t = unicodedata.normalize("NFD", str(s or "").lower())
    return re.sub(r"[^a-z0-9* ]+", " ", "".join(c for c in t if not unicodedata.combining(c))).strip()


def _palavras(s: str | None) -> list[str]:
    return [_NUM.get(w, w) for w in plano(s).split() if "*" not in w]


def citacoes(texto: str | None) -> list[str]:
    return [q.strip() for q in re.findall(r"[\"“”]([^\"“”]{4,})[\"“”]", texto or "")]


def existe(q: str, fala: str, minimo: float = 0.78) -> bool:
    """A frase foi dita? Aceita pequenas diferencas da transcricao (2 / dois, pra / para)."""
    a, b = _palavras(q), _palavras(fala)
    if not a:
        return True
    alvo = " ".join(a)
    if alvo in " ".join(b):
        return True
    if len(a) <= 2 or not b:
        return False
    melhor = 0.0
    for n in (len(a) - 1, len(a), len(a) + 1):
        for i in range(0, max(1, len(b) - n + 1)):
            melhor = max(melhor, SequenceMatcher(None, alvo, " ".join(b[i:i + n])).ratio())
            if melhor >= minimo:
                return True
    return False


def falsas(texto: str | None, fala: str) -> list[str]:
    """Citacoes do texto que nao estao na fala."""
    return [q for q in citacoes(texto) if not existe(q, fala)]


def limpa_titulo(t: str | None) -> str:
    """Tira o final inventado, mantendo citacao e emojis."""
    s = str(t or "")
    for f in sorted(INVENTADOS, key=len, reverse=True):
        palavras = f.split()
        # compara sem acento e sem caixa, palavra por palavra, so no fim do texto (pode ter emoji depois)
        m = re.search(r"[\s|:,]*\b" + r"\s+".join(_sem_acento_rx(w) for w in palavras) + r"\b(?=\W*$)", s, re.I)
        if m:
            s = (s[:m.start()] + s[m.end():]).rstrip(" |:,-")
    return re.sub(r"\s{2,}", " ", s).strip()


def _sem_acento_rx(w: str) -> str:
    m = {"a": "[aáâãà]", "e": "[eéê]", "i": "[ií]", "o": "[oóôõ]", "u": "[uú]", "c": "[cç]"}
    return "".join(m.get(c, re.escape(c)) for c in w)


def arruma_plano(p: Any, fala: str) -> list[str]:
    """Antes de editar: o texto que vai ser queimado no video tem que ser verdade. Devolve o que mudou."""
    out = []
    novo = limpa_titulo(p.title)
    if novo != (p.title or "") and len(re.sub(r"\W", "", novo)) >= 8:
        out.append(f"titulo: {p.title} -> {novo}")
        p.title = novo
    if falsas(p.title, fala):
        sem = re.sub(r"[\"“”]", "", p.title)
        out.append(f"titulo sem aspas (a frase nao esta na fala): {p.title}")
        p.title = sem
    if falsas(p.hook, fala):
        boas = [q for q in citacoes(p.title) if existe(q, fala) and len(q) <= 46]
        if not boas:        # frase de verdade do trecho, para nao inventar
            frases = [f.strip(" ,;:") for f in re.split(r"(?<=[.!?])\s+", fala) if 3 <= len(f.split()) <= 8]
            boas = [f for f in frases if len(f) <= 40][:1]
        out.append(f"texto na tela: {p.hook} -> {boas[0] if boas else '(titulo)'}")
        p.hook = f'"{boas[0].rstrip(".").upper()}"' if boas else re.sub(r"[\"“”]", "", p.title)[:40]
    return out
