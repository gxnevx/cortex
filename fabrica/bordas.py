"""Acerta onde cada corte comeca e termina ANTES de baixar e editar, lendo a fala em volta.

O escolhedor acha o momento forte, mas as vezes pega a introducao, comeca no meio da historia ou corta antes do desfecho.
Aqui o Claude le o que vem antes e depois e devolve o corte inteiro (ou 2 a 3 partes, quando a historia nao cabe em um), ou
descarta o que nao faz sentido sozinho. Uma chamada por video.
"""
from __future__ import annotations

import copy
import re
from typing import Any

from . import honesto, log
from .models import ClipPlan, Transcript

_log = log.get("bordas")
ANTES, DEPOIS = 100.0, 75.0
SYSTEM = ("Você é editor de cortes virais. O corte tem que fazer sentido para quem nunca viu o vídeo: começa dizendo do que se trata e termina com a ideia "
          "completa. Responda SOMENTE com JSON válido.")


def _linhas(t: Transcript, a: float, b: float) -> str:
    return "\n".join(f"[{s.start:.0f}] {re.sub(chr(10), ' ', s.text).strip()}" for s in t.segments if s.end > a and s.start < b and s.text.strip())


def prompt(video_title: str, channel: str, itens: list[tuple[int, ClipPlan]], t: Transcript, dmin: float, dmax: float) -> str:
    blocos = []
    for i, p in itens:
        blocos.append(f"### CORTE {i}: hoje vai de {p.start:.0f} a {p.end:.0f} ({p.end - p.start:.0f} s)\nTítulo: {p.title}\nTexto na tela: {p.hook}\n"
                      f"Fala em volta (o número é o segundo em que a frase começa):\n{_linhas(t, p.start - ANTES, p.end + DEPOIS)}")
    corpo = "\n\n".join(blocos)
    return f"""Vídeo: {video_title} | Canal: {channel}

Para cada corte abaixo, confira o começo e o fim lendo a fala em volta e corrija.

REGRAS
- Começo: a primeira frase já diz de quem ou do que se fala, ou é a pergunta que abre o assunto. Se a história começou antes, recue. Nunca comece no meio de uma história, numa sobra de outro assunto, em vinheta, cumprimento ou introdução do vídeo.
- Fim: logo depois do desfecho, da resposta ou da piada. Nunca no meio da frase.
- Duração de cada corte: de {dmin:.0f} a {dmax:.0f} s.
- Se a história completa precisa de mais que {dmax:.0f} s e prende do começo ao fim, devolva "partes": 2 ou 3 pedaços contínuos (cada um de 30 a {dmax:.0f} s), cada um terminando num gancho.
- "serve": false se não dá para virar um corte que um desconhecido entenda (introdução, combinado do vídeo, trecho aleatório, conversa sem assunto, depende de imagem que não aparece, propaganda). Seja exigente: melhor descartar que postar algo sem sentido.
- "titulo": 35 a 75 caracteres, conta o que realmente acontece no trecho, com o nome da pessoa ou do assunto; aspas só com frase dita igual; 1 emoji no fim. Nunca invente reação ("a mesa travou", "humilhou", "perdeu a linha").
- "tela": até 38 caracteres, a frase mais forte ENTRE ASPAS exatamente como foi dita, ou um resumo verdadeiro sem aspas.
- "imagens": até 5 coisas ou pessoas PÚBLICAS citadas pelo nome no trecho, que ficam boas como imagem na tela: famoso, filme, série, jogo, lugar, marca, animal, objeto. Cada uma com "palavra" (exatamente como aparece na fala) e "busca" (nome do artigo na Wikipédia). Nada de conceito abstrato. NUNCA imagem de vítima, menor, pessoa comum ou alguém ligado a crime ou acusação no trecho. Sem nada bom: lista vazia.
- A transcrição é automática e erra nomes: escreva o nome certo no título.

{corpo}

Use só os números que aparecem entre colchetes. "fim" é o número da primeira frase que NÃO entra.
RESPONDA SÓ COM ESTE JSON:
{{"cortes":[{{"i":1,"serve":true,"inicio":120,"fim":168,"partes":[],"titulo":"...","tela":"...","imagens":[{{"palavra":"...","busca":"..."}}],"motivo":"até 12 palavras"}}]}}"""


def curto(t: str, n: int = 38) -> str:
    """Encurta sem cortar palavra no meio e sem aspas soltas."""
    t = re.sub(r"\s+", " ", re.sub(r"[\"“”]|\(parte[^)]*\)", "", t or "")).strip()
    if len(t) <= n:
        return t
    corte = t[:n + 1].rsplit(" ", 1)[0].rstrip(" ,.;:-")
    while corte and corte.split()[-1].lower() in ("de", "do", "da", "dos", "das", "e", "a", "o", "que", "um", "uma", "em", "no", "na", "para", "pra", "com", "vai", "se"):
        corte = corte.rsplit(" ", 1)[0] if " " in corte else ""
    return corte or t[:n]


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _textos(p: ClipPlan, d: dict, fala: str) -> None:
    from .curadoria import _good_title
    from .util import clean_text

    p.imagens = [{"palavra": str(x.get("palavra"))[:60], "busca": str(x.get("busca") or x.get("palavra"))[:60]} for x in (d.get("imagens") or [])
                 if isinstance(x, dict) and x.get("palavra")][:5]

    t = clean_text(str(d.get("titulo") or ""), True).strip()
    if _good_title(t, fala):
        p.title, p.titulo_alt = t, ""
    tela = clean_text(str(d.get("tela") or ""), True).strip()
    if 4 <= len(tela) <= 46 and not honesto.falsas(tela, fala):
        p.hook = tela.upper() if '"' in tela else tela


def aplicar(plans: list[ClipPlan], decisoes: dict[int, dict], itens: list[tuple[int, ClipPlan]], t: Transcript, dmin: float, dmax: float,
            dur: float | None = None) -> list[ClipPlan]:
    """Aplica as decisoes. Sem decisao para um corte: fica como esta (a revisao final ainda barra)."""
    fora: set[int] = set()
    novos: dict[int, list[ClipPlan]] = {}
    fim_video = float(dur or t.duration or 1e9)
    for i, p in itens:
        d = decisoes.get(i)
        if not d:
            continue
        if d.get("serve") in (False, "false", "False", 0):
            fora.add(id(p))
            _log.info("descartado antes de editar: '%s' (%s)", p.title[:60], str(d.get("motivo") or "")[:100])
            continue
        partes = []
        for x in d.get("partes") or []:
            a, b = (_num(x[0]), _num(x[1])) if isinstance(x, (list, tuple)) and len(x) == 2 else \
                   (_num(x.get("inicio")), _num(x.get("fim"))) if isinstance(x, dict) else (None, None)
            if a is not None and b is not None:
                partes.append((a, b))
        if len(partes) in (2, 3) and all(25 <= b - a <= dmax + 2 for a, b in partes) and all(abs(n[0] - m[1]) <= 3 for m, n in zip(partes, partes[1:])) \
                and partes[0][0] >= p.start - ANTES - 5 and partes[-1][1] <= min(fim_video, p.end + DEPOIS + 5):
            novos[id(p)] = _serie(p, partes, d, t)
            continue
        a, b = _num(d.get("inicio")), _num(d.get("fim"))
        if a is None or b is None or not (p.start - ANTES - 5 <= a < b <= min(fim_video, p.end + DEPOIS + 5)):
            continue
        if not dmin - 4 <= b - a <= dmax + 2:
            continue
        if abs(a - p.start) > 1.5 or abs(b - p.end) > 1.5:
            _log.info("bordas: %.0f-%.0f virou %.0f-%.0f '%s'", p.start, p.end, a, b, p.title[:50])
        p.start, p.end = a, min(b, a + dmax)
        if p.teaser_start is not None and not (p.start <= p.teaser_start and (p.teaser_end or 0) <= p.end):
            p.teaser_start = p.teaser_end = None
            p.teaser_text = ""
        _textos(p, d, t.slice(p.start, p.end).text)
    out: list[ClipPlan] = []
    for p in plans:
        if id(p) in fora:
            continue
        out += novos.get(id(p), [p])
    return _sem_sobrepor(out)


def _serie(p: ClipPlan, partes: list[tuple[float, float]], d: dict, t: Transcript) -> list[ClipPlan]:
    from .brain.base import series_title

    base = copy.deepcopy(p)
    _textos(base, d, t.slice(partes[0][0], partes[-1][1]).text)
    nome = re.sub(r"\W+", " ", honesto.plano(base.title)).strip()[:40] or "historia"
    out = []
    for k, (a, b) in enumerate(partes, 1):
        q = copy.deepcopy(base)
        q.id, q.start, q.end = f"{p.id}-serie-p{k}", a, b
        q.part, q.parts_total, q.series = k, len(partes), nome
        q.title = series_title(base.title, k, len(partes))
        q.teaser_start = q.teaser_end = None
        q.teaser_text, q.titulo_alt = "", ""
        if honesto.falsas(q.hook, t.slice(a, b).text):      # a frase da tela e de outra parte
            q.hook = curto(base.title)
        out.append(q)
    _log.info("virou serie de %d partes: '%s'", len(out), base.title[:60])
    return out


def _sem_sobrepor(plans: list[ClipPlan]) -> list[ClipPlan]:
    """Dois cortes que ficaram um em cima do outro: fica o de nota maior (serie vale como um)."""
    out: list[ClipPlan] = []
    for p in sorted(plans, key=lambda x: (-(x.score or 0), x.id)):
        if all((p.series and p.series == q.series) or p.end <= q.start + 2 or p.start >= q.end - 2 for q in out):
            out.append(p)
    series_ok = {}
    for p in out:
        if p.part:
            series_ok.setdefault(p.series, set()).add(p.part)
    out = [p for p in out if not p.part or len(series_ok[p.series]) == (p.parts_total or 0)]      # serie so inteira
    return sorted(out, key=lambda x: x.start)


def ajustar(plans: list[ClipPlan], t: Transcript, video: Any, cfg: Any) -> list[ClipPlan]:
    """Cortes com comeco e fim conferidos. Sem o Claude: devolve como veio (a revisao final barra o que nao presta)."""
    from .brain import get_brain
    from .brain.base import extract_json, list_from_json

    itens = [(i, p) for i, p in enumerate([p for p in plans if not p.part], 1)]
    if not itens or not cfg.get("corte.conferir_bordas", True) or not t.segments:
        return plans
    b = get_brain(cfg, tarefa="bordas")
    if b.name != "claude":
        return plans
    dmin, dmax = float(cfg.get("corte.duracao_min_s", 28)), float(cfg.get("corte.duracao_max_s", 58))
    try:
        res = b._run(prompt(video.title, getattr(video, "channel", "") or "", itens, t, dmin, dmax), SYSTEM)
        dec: dict[int, dict] = {}
        for d in list_from_json(extract_json(res), ("cortes", "clips")):
            n = _num(d.get("i"))
            if n is not None:
                dec[int(n)] = d
    except Exception as e:
        _log.warning("nao conferi as bordas: %s", str(e)[:150])
        return plans
    return aplicar(plans, dec, itens, t, dmin, dmax, getattr(video, "duration", None))


# ------------------------------------------------------------------ ajuste fino: depois da transcricao boa, por frase inteira
SYSTEM_FINO = ("Você é o editor-chefe de um canal brasileiro de cortes virais. Escolhe exatamente em que frase o corte começa e termina, e dá nota. "
               "Só passa o que um desconhecido entende e assiste até o fim. Responda SOMENTE com JSON válido.")


def frases(t: Transcript, base: float) -> list[tuple[float, float, str]]:
    """[(comeco, fim, texto)] em tempo do video original. Quebra na pontuacao, na pausa ou a cada ~20 palavras."""
    out: list[tuple[float, float, str]] = []
    cur: list = []
    ws = t.words()
    for i, w in enumerate(ws):
        cur.append(w)
        prox = ws[i + 1] if i + 1 < len(ws) else None
        fim = w.text.strip().endswith((".", "?", "!", "…"))
        pausa = prox is not None and prox.start - w.end > 0.8
        if fim or pausa or prox is None or len(cur) >= 22:
            txt = re.sub(r"\s+", " ", " ".join(x.text.strip() for x in cur)).strip()
            if txt:
                out.append((base + cur[0].start, base + cur[-1].end, txt))
            cur = []
    return out


def prompt_fino(titulo: str, canal: str, itens: list[tuple[int, ClipPlan, list]], dmin: float, dmax: float) -> str:
    blocos = []
    for i, p, fr in itens:
        parte = f" | Parte {p.part} de {p.parts_total} da mesma história" if p.part else ""
        linhas = []
        for n, (a, b, txt) in enumerate(fr):
            dentro = "*" if a >= p.start - 0.6 and b <= p.end + 0.6 else " "
            linhas.append(f"{dentro}{n} [{a - fr[0][0]:.0f}s] {txt}")
        blocos.append(f"### CORTE {i}{parte}\nTítulo: {p.title}\nTexto na tela: {p.hook}\nFrases (número, segundo, texto; com * = dentro do corte hoje):\n" + "\n".join(linhas))
    corpo = "\n\n".join(blocos)
    return f"""Vídeo: {titulo} | Canal: {canal}

Para cada corte, escolha a PRIMEIRA e a ÚLTIMA frase (números) e dê a nota.

- Começo: uma frase que abre o assunto ou prende na hora, entendível por quem nunca viu o vídeo. Nunca sobra de outro assunto, cumprimento, vinheta, "então", "e aí" no meio de uma história, nem pronome sem dono ("ele", "ela", "isso") que não se resolve em poucos segundos.
- Fim: a frase que fecha a ideia, a resposta, a piada ou o desfecho. Se a frase continua na seguinte, inclua a seguinte ou pare antes. Nunca no meio da frase, nunca com chamada para o intervalo, agradecimento ou começo de outro assunto.
- Duração entre a primeira e a última: de {dmin:.0f} a {dmax:.0f} s (o segundo está entre colchetes). Parte de série: de 22 a {dmax:.0f} s; a parte 1 tem que abrir o assunto e a última tem que fechar.
- "serve": false se nenhuma combinação dá um corte que faz sentido sozinho.
- "nota": 0 a 100, chance de segurar um desconhecido até o fim. 80+ = frase forte, treta, piada boa, revelação, história com desfecho, curiosidade completa. 65 = interessante. 50 = morno, técnico ou de nicho. Comentário de jornal sobre votação, economia ou processo, ou conversa que só o torcedor de um time entende, sem frase de impacto: no máximo 50.
- "titulo": 35 a 75 caracteres, conta o que realmente acontece, com o nome da pessoa ou do assunto; aspas só com frase dita igual; 1 emoji no fim; sem reação inventada.
- "tela": até 38 caracteres, a frase mais forte ENTRE ASPAS igual à fala, de dentro do corte escolhido.
- "imagens": até 5 pessoas públicas, filmes, séries, jogos, lugares, marcas ou objetos citados pelo nome dentro do corte, boas como imagem na tela: "palavra" (igual à fala) e "busca" (artigo da Wikipédia). Nunca vítima, menor, pessoa comum ou alguém ligado a crime ou acusação no trecho. Sem nada: lista vazia.

{corpo}

RESPONDA SÓ COM ESTE JSON:
{{"cortes":[{{"i":1,"serve":true,"primeira":2,"ultima":9,"nota":70,"titulo":"...","tela":"...","imagens":[],"motivo":"até 12 palavras"}}]}}"""


def aplicar_fino(itens: list[tuple[int, ClipPlan, list]], dec: dict[int, dict], dmin: float, dmax: float, corte_nota: float) -> dict[str, str]:
    """Aplica nos planos. Devolve {id: motivo} dos que nao devem ser editados."""
    fora: dict[str, str] = {}
    for i, p, fr in itens:
        d = dec.get(i)
        if not d:
            continue        # sem resposta: fica como esta; o editor-chefe e a revisao julgam depois
        motivo = str(d.get("motivo") or "")[:120]
        nota = _num(d.get("nota")) or 0.0
        if d.get("serve") in (False, "false", "False", 0):
            fora[p.id] = motivo or "não faz sentido sozinho"
            continue
        a, b = _num(d.get("primeira")), _num(d.get("ultima"))
        if a is None or b is None or not 0 <= a <= b < len(fr):
            continue
        t0, t1 = max(0.0, fr[int(a)][0] - 0.12), fr[int(b)][1] + 0.3
        minimo = 22.0 if p.part else dmin - 4
        if not minimo <= t1 - t0 <= dmax + 1.5:
            fora[p.id] = f"não coube em {dmin:.0f} a {dmax:.0f} s fazendo sentido ({t1 - t0:.0f} s)"
            continue
        if nota < corte_nota:
            fora[p.id] = f"nota {nota:.0f}: {motivo}"
            continue
        p.start, p.end = round(t0, 3), round(min(t1, t0 + dmax), 3)
        p.ext_start = p.ext_end = None
        if p.teaser_start is not None and not (p.start <= p.teaser_start and (p.teaser_end or 0) <= p.end):
            p.teaser_start = p.teaser_end = None
            p.teaser_text = ""
        fala = " ".join(x[2] for x in fr[int(a):int(b) + 1])
        base = p.title
        _textos(p, d, fala)
        if p.part:      # a parte continua com o titulo da serie
            from .brain.base import series_title

            p.title = series_title(re.sub(r"\s*\(parte[^)]*\)", "", base).strip(), p.part, p.parts_total)
            if honesto.falsas(p.title, fala):
                p.title = re.sub(r"[\"“”]", "", p.title)
        p.editor = {"nota": nota, "motivo": motivo}
    # serie: cai uma parte, caem todas
    ruins = {p.series for _, p, _ in itens if p.part and p.id in fora}
    for _, p, _ in itens:
        if p.part and p.series in ruins and p.id not in fora:
            fora[p.id] = "outra parte da série não serviu"
    return fora


def fino(itens: list[tuple[int, ClipPlan, list]], video: Any, cfg: Any) -> dict[str, str]:
    """Comeco e fim por frase, nota e textos, com a transcricao boa. {} se o Claude nao puder responder."""
    from .brain import get_brain
    from .brain.base import extract_json, list_from_json

    itens = [x for x in itens if x[2]]
    if not itens or not cfg.get("corte.conferir_bordas", True):
        return {}
    b = get_brain(cfg, tarefa="fino")
    if b.name != "claude":
        return {}
    dmin, dmax = float(cfg.get("corte.duracao_min_s", 28)), float(cfg.get("corte.duracao_max_s", 58))
    try:
        res = b._run(prompt_fino(video.title, getattr(video, "channel", "") or "", itens, dmin, dmax), SYSTEM_FINO)
        dec: dict[int, dict] = {}
        for d in list_from_json(extract_json(res), ("cortes", "clips")):
            n = _num(d.get("i"))
            if n is not None:
                dec[int(n)] = d
    except Exception as e:
        _log.warning("ajuste fino nao respondeu: %s", str(e)[:150])
        return {}
    fora = aplicar_fino(itens, dec, dmin, dmax, float(cfg.get("corte.nota_para_editar", 62)))
    for _, p, _ in itens:
        _log.info("fino: %s '%s' %s", f"FORA ({fora[p.id]})" if p.id in fora else f"nota {p.editor.get('nota', 0):.0f} {p.end - p.start:.0f} s", p.title[:60],
                  f"imagens: {len(p.imagens)}" if p.imagens else "")
    return fora
