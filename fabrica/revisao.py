"""Ultima conferencia: NADA sai sem passar aqui. Cada corte e revisto uma vez, com a fala, os textos e as imagens do video pronto.

1. Regras: arquivo, duracao, frase entre aspas que existe na fala, final inventado no titulo.
2. O Claude olha 8 quadros do video pronto e le a fala: da para entender sozinho? comeca e termina direito? o titulo e verdade?
Sem o Claude (teto do dia) o corte espera: nunca sai sem revisao.
"""
from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from . import andamento, db, honesto, log, paths, tools

_log = log.get("revisao")
STATE = paths.STATE / "revisoes.json"
SYSTEM = ("Você é o revisor final de um canal brasileiro de cortes. O dono odeia vídeo aleatório, sem sentido, e título que não bate. "
          "Use a escala inteira e seja justo: conversa de podcast é solta por natureza, e isso não é defeito. Responda SOMENTE com JSON válido.")
# nota minima de cada item (0 a 10) e da chance geral (0 a 100)
MINIMOS = {"entende_sozinho": 6, "comeca_bem": 5, "termina_bem": 5, "titulo_verdadeiro": 6, "imagem_ok": 4, "nota": 55}
_espera = [0.0]


def _sig(clip: Any) -> str:
    """Mudou o titulo, o texto na tela ou o arquivo: revisa de novo."""
    f = Path(clip.path)
    m = f"{f.stat().st_mtime:.0f}" if f.exists() else ""
    return hashlib.sha1(f"{clip.plan.title}|{clip.plan.hook}|{m}".encode()).hexdigest()[:12]


def estado(clip: Any) -> dict | None:
    d = (andamento.read_json(STATE) or {}).get(clip.plan.id)
    return d if isinstance(d, dict) and d.get("sig") == _sig(clip) else None


def gravar(clip: Any, ok: bool, motivo: str, por: str) -> dict:
    d = andamento.read_json(STATE) or {}
    d[clip.plan.id] = {"ok": bool(ok), "motivo": motivo[:200], "por": por, "ts": time.time(), "sig": _sig(clip)}
    for k in sorted(d, key=lambda k: d[k].get("ts", 0))[:-400]:
        d.pop(k)
    andamento.write_json(STATE, d, durable=True)
    return d[clip.plan.id]


def regras(clip: Any, fala: str) -> str | None:
    p = clip.plan
    if not Path(clip.path).exists():
        return "o arquivo do vídeo sumiu"
    if not (20 if p.part else 25) <= float(clip.duration or 0) <= 95:
        return f"duração fora do normal ({clip.duration:.0f} s)"
    if len(fala.split()) < 8:
        return "quase não tem fala"
    for nome, t in (("título", p.title), ("texto na tela", p.hook)):
        f = honesto.falsas(t, fala)
        if f:
            return f'{nome} cita uma frase que não está na fala: "{f[0][:60]}"'
    if honesto.limpa_titulo(p.title) != p.title:
        return f"título com reação inventada: {p.title[:70]}"
    return None


def folha_imagens(clip: Any) -> Path | None:
    """O quadro em que cada imagem ilustrativa aparece."""
    ms = [m for m in (clip.plan.imagens or []) if m.get("t") is not None and m.get("arquivo")]
    if not ms:
        return None
    out = paths.STATE / f"revisao_img_{clip.plan.id[:60]}.jpg"
    sel = "+".join(f"between(t,{m['t'] + 0.6:.2f},{m['t'] + 0.62 + 1 / 30:.2f})" for m in ms)
    try:
        subprocess.run([tools.ffmpeg(), "-v", "error", "-y", "-i", clip.path, "-vf", f"select='{sel}',scale=250:-2,tile={len(ms)}x1:padding=6", "-frames:v", "1",
                        "-fps_mode", "vfr", "-q:v", "4", str(out)], capture_output=True, timeout=180, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return out if out.exists() else None
    except Exception as e:
        _log.warning("imagens da revisao: %s", e)
        return None


def folha(clip: Any, n: int = 8) -> Path | None:
    """8 quadros do video pronto, em ordem, numa imagem so."""
    out = paths.STATE / f"revisao_{clip.plan.id[:60]}.jpg"
    d = max(1.0, float(clip.duration or 30))
    try:
        subprocess.run([tools.ffmpeg(), "-v", "error", "-y", "-i", clip.path, "-vf",
                        f"fps={n}/{d:.2f},scale=250:-2,tile=4x{(n + 3) // 4}:padding=6", "-frames:v", "1", "-q:v", "4", str(out)],
                       capture_output=True, timeout=180, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return out if out.exists() else None
    except Exception as e:
        _log.warning("quadros da revisao: %s", e)
        return None


def _prompt(clip: Any, fala: str) -> str:
    p = clip.plan
    parte = f"\nEste é a Parte {p.part} de {p.parts_total} de uma série: quem vê já viu a anterior; pode terminar em suspense se não for a última." if p.part else ""
    gancho = f'\nO vídeo abre repetindo a frase mais forte ("{p.teaser_text}"), isso é proposital.' if p.teaser_text else ""
    il = [m for m in (p.imagens or []) if m.get("t") is not None and m.get("artigo")]
    ilus = ("\nA segunda imagem mostra as ilustrações que aparecem por 1,5 s quando a pessoa cita o nome: " + ", ".join(f"'{m['palavra']}' ({m['artigo']})" for m in il)
            + ". Se alguma não tem relação com o que é dito, imagem_ok é no máximo 3. Cobrir o rosto por 1,5 s com a ilustração NÃO é defeito.") if il else ""
    return f"""Última conferência antes de publicar este corte. A imagem tem 8 quadros do vídeo pronto, em ordem (esquerda para a direita, de cima para baixo).{ilus}

Título do post: {p.title}
Texto fixo na tela: {p.hook}
Duração: {clip.duration:.0f} s | tipo: {p.tipo or 'fala'} | assunto: {p.category or '?'}{parte}{gancho}
Fala completa (transcrição automática, pode ter erro de palavra e não diz quem fala):
"{fala[:1500]}"

Dê nota de 0 a 10 em cada item, pensando em alguém que nunca viu esse canal nem o vídeo original:
- entende_sozinho: dá para saber do que se trata e por que assistir? 9 = claro desde o começo. 6 = um pouco solto, mas dá para seguir o assunto. 2 = introdução do vídeo, vinheta, combinado, trecho aleatório, assunto pela metade ou que depende de algo que não aparece.
- comeca_bem: 9 = a primeira frase já prende ou abre o assunto. 5 = começa meio solto, mas o assunto fica claro em poucos segundos. 2 = começa no meio de uma história sem dizer de quem ou do que se fala, ou com sobra de outro assunto.
- termina_bem: 9 = fecha com desfecho, resposta ou frase forte. 5 = fecha a ideia sem impacto. 2 = corta no meio da frase ou antes do desfecho.
- titulo_verdadeiro: 9 = título e texto na tela contam o que acontece. 5 = exagera um pouco. 2 = promete o que não acontece ou afirma reação, treta ou acusação que não está no trecho.
- imagem_ok: 9 = pessoa principal bem enquadrada. 5 = dá para ver bem, com algum detalhe ruim. 2 = pessoa principal cortada, texto em cima do rosto, tela quebrada, ou mais da metade dos quadros sem mostrar o assunto.
- nota: 0 a 100, chance de um desconhecido assistir até o fim.
- motivo: até 15 palavras, dizendo o principal problema ou qualidade.

Como é o visual do canal, e NÃO é defeito: vídeo numa faixa no meio da tela com fundo desfocado (claro ou escuro) em cima e embaixo, título grande fixo, marca do canal, legenda de 1 a 3 palavras por vez, cortes rápidos entre câmeras, clarão na abertura e etiqueta com o nome do programa no começo.

RESPONDA SÓ COM ESTE JSON:
{{"entende_sozinho":0,"comeca_bem":0,"termina_bem":0,"titulo_verdadeiro":0,"imagem_ok":0,"nota":0,"motivo":"..."}}"""


def perguntar(clip: Any, fala: str, cfg: Any) -> dict | None:
    """Resposta do Claude com as imagens, ou None (sem cota ou sem resposta)."""
    from .brain import get_brain
    from .brain.base import extract_json

    b = get_brain(cfg, tarefa="revisao")
    if b.name != "claude":
        return None
    img = folha(clip)
    if img is None:
        return None
    img2 = folha_imagens(clip)
    try:
        res = extract_json(b._run(_prompt(clip, fala), SYSTEM, images=[img] + ([img2] if img2 else [])))
        if isinstance(res, list):
            res = next((x for x in res if isinstance(x, dict)), None)
        return res if isinstance(res, dict) and "nota" in res else None
    except Exception as e:
        _log.warning("a revisao nao respondeu: %s", str(e)[:150])
        return None
    finally:
        img.unlink(missing_ok=True)
        if img2:
            img2.unlink(missing_ok=True)


def faltas(d: dict) -> list[str]:
    """Itens abaixo do minimo (item sem nota conta como falta)."""
    out = []
    for k, minimo in MINIMOS.items():
        try:
            v = float(d.get(k))
        except (TypeError, ValueError):
            v = -1.0
        if v < minimo:
            out.append(f"{k} {v:.0f}")
    return out


def garantir(clip: Any, cfg: Any) -> dict:
    """{"ok", "motivo", "espera"}: espera=True quer dizer que nao deu para revisar agora (nao e reprovacao)."""
    from . import curadoria

    st = estado(clip)
    if st:
        return {"ok": st["ok"], "motivo": st["motivo"], "espera": False}
    fala = clip.plan.fala or curadoria.speech(clip, cfg)
    why = regras(clip, fala)
    if why:
        gravar(clip, False, why, "regras")
        return {"ok": False, "motivo": why, "espera": False}
    if time.time() < _espera[0]:
        return {"ok": False, "motivo": "esperando o Claude para revisar", "espera": True}
    d = perguntar(clip, fala, cfg)
    if d is None:
        _espera[0] = time.time() + 1800
        return {"ok": False, "motivo": "esperando o Claude para revisar", "espera": True}
    ruins = faltas(d)
    ok = not ruins
    motivo = str(d.get("motivo") or "")[:150] + (f" ({', '.join(ruins)})" if ruins else "")
    gravar(clip, ok, motivo, "claude")
    _log.info("revisao %s '%s': %s", "aprovou" if ok else "REPROVOU", clip.plan.title[:60], motivo)
    return {"ok": ok, "motivo": motivo, "espera": False}


def reprovar(clip: Any, motivo: str) -> None:
    """Sai da fila e fica guardado (da para recuperar em Ver cortes prontos)."""
    db.conn().execute("UPDATE clips SET curador=? WHERE id=?", (f"descartado na revisão: {motivo}", clip.plan.id))
    db.set_clip_status(clip.plan.id, "rejeitado")


def filtrar(clips: list, cfg: Any) -> tuple[list, bool]:
    """(revistos e aprovados, algum ficou esperando?). Reprovado sai da fila; parte reprovada leva junto as seguintes."""
    bons, espera = [], False
    for c in clips:
        r = garantir(c, cfg)
        if r["ok"]:
            bons.append(c)
        elif r["espera"]:
            espera = True
        else:
            reprovar(c, r["motivo"])
            if c.plan.part:
                _reprova_serie(c, r["motivo"])
    return bons, espera


def _reprova_serie(c: Any, motivo: str) -> None:
    for x in db.clips_by_status("aprovado"):
        if x.plan.source_id == c.plan.source_id and x.plan.series == c.plan.series and (x.plan.part or 0) > (c.plan.part or 0):
            reprovar(x, f"a parte {c.plan.part} foi reprovada: {motivo}")


def adiantar(cfg: Any, limite: int = 2) -> dict:
    """Revisa a fila com antecedencia, poucos por vez, para o cronograma ja mostrar so o que passou."""
    from . import autopilot

    out = {"ok": 0, "fora": 0}
    for c in [x for x in autopilot.queue(cfg) if estado(x) is None][:limite]:
        bons, espera = filtrar([c], cfg)
        if espera:
            break
        out["ok" if bons else "fora"] += 1
    return out


def imagem_b64(path: Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode()


def json_mensagem(texto: str, images: list[Path]) -> str:
    """Uma mensagem com imagens no formato stream-json do Claude Code."""
    content: list[dict] = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": imagem_b64(i)}} for i in images]
    content.append({"type": "text", "text": texto})
    return json.dumps({"type": "user", "message": {"role": "user", "content": content}}, ensure_ascii=False) + "\n"
