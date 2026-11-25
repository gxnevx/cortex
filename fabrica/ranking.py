"""Ranking: um video com 5 momentos do mesmo assunto, em ordem de views (formato aprovado pelo dono em 25/11/2026).

Os momentos sao os clipes que o PUBLICO criou na Twitch e na Kick na semana, com as views reais de cada um. Muito clipe visto tem
nudez, propaganda ou nao faz sentido fora da live: o Claude olha os quadros e le a fala de cada um antes de entrar.
No maximo 1 por dia e so quando ha 5 clipes bons: do mesmo jogo ou, se nenhum jogo tem 5, das lives da semana. Os aprovados ficam
guardados ate fechar 5. Canal bloqueado ou que proibe corte nunca entra.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import andamento, db, log, paths
from .models import Candidate, ClipPlan

_log = log.get("ranking")
STATE = paths.STATE / "ranking.json"
N = 5
MISTURA = "LIVE"                # assunto quando os 5 sao de jogos diferentes
LOTE = 10                       # clipes olhados por chamada do Claude
TRIAGEM = 40                    # capas olhadas de uma vez, antes de baixar
MIN_S, MAX_S = 4.5, 11.0        # tamanho de cada momento
SYSTEM = ("Você escolhe momentos de lives para um canal brasileiro de cortes. O dono odeia vídeo aleatório e título falso. "
          "Seja rigoroso com o que não pode ir ao ar. Responda SOMENTE com JSON válido.")

# jogo na Twitch/Kick -> como aparece na tela
NOMES = {"grand theft auto vi": "GTA 6", "grand theft auto vi (gta)": "GTA 6", "grand theft auto v": "GTA RP", "grand theft auto v (gta)": "GTA RP",
         "league of legends": "LOL", "counter-strike": "CS", "counter-strike 2": "CS", "ea sports fc 27": "EA FC", "roblox": "ROBLOX",
         "just chatting": "LIVE", "irl": "LIVE", "free fire": "FREE FIRE", "dead by daylight": "DBD"}
FORA_JOGO = re.compile(r"slot|cassino|casino|poker|bet|gambl|hot tub|pools|asmr|music|sport|watch part|radio|politic|crypto|always on|retro|dj", re.I)
# titulo do clipe que nem vale gastar o Claude
FORA_TITULO = re.compile(r"\b(sex\w*|secs?u\w*|nudes?|pelad\w*|pau|piru\w*|piroc\w*|pint[aã]o|bund\w+|rab[aã]o|peit\w+|bucet\w*|buce|trans(a|ar|ou|ando)|18|onlyfans|"
                         r"privacy|goz\w+|leitinho|punhet\w*|estupr\w*|sorteio|drops?|pix|apost\w*|bets?|tigrinho|cassino|slots?|suic\w+|tits?|boobs?|ass|porn\w*|"
                         r"gostosa|novinh\w+|highlight|created by)\b", re.I)
# o que e dito no clipe ja mostra que nao pode
FORA_FALA = re.compile(r"\b(piroc\w*|piru\w*|bucet\w*|xerec\w*|pelad[oa]s?|p[eê]nis|transand\w*|transar|gozar|gozou|tes[aã]o|punhet\w*|boquet\w*|peitinh\w*|peitos|"
                       r"sexo|estupr\w*|maconha|coca[ií]na|pix|sorteio|cassino|tigrinho)\b", re.I)
# o canal avisa que nao autoriza corte
PROIBE = re.compile(r"(n[aã]o\s+autoriz\w+|proibid\w+)[^.]{0,60}(corte|clipe|v[ií]deo|uso|repost|re-?upload|conte[uú]do)|"
                    r"(corte|clipe|repost|re-?upload)\w*[^.]{0,30}(proibid|n[aã]o\s+autoriz)", re.I)
TITULOS = ["Ranqueando 5 clipes {de} da semana: concorda com o 1º lugar? 🏆",
           "5 clipes {de} que rodaram essa semana: qual é o melhor? 🏆",
           "Ranqueando clipes {de} da semana: quem merecia o topo? 🔥"]
# o Claude leve confunde: cena de jogo com filme, QR code de canto com propaganda, personagem de vestido com nudez
LIVRE = ("NÃO é proibido: cena, personagem ou vídeo do PRÓPRIO JOGO (GTA 6 parece filme, mas é jogo); arma, tiro, atropelamento e morte de jogo; palavrão solto; QR code, "
         "doação, chat, logo ou aviso pequeno no canto da tela; personagem vestida, de vestido, de costas ou homem sem camisa; susto e terror.")
PERGUNTAS = ["Concorda com o 1º lugar?", "Qual desses você colocaria em 1º?", "Qual ficou na posição errada?", "Comenta a sua ordem."]


# ------------------------------------------------------------------ memoria
def _mem() -> dict:
    d = andamento.read_json(STATE)
    return d if isinstance(d, dict) else {}


def _grava(d: dict) -> None:
    velho = time.time() - 30 * 86400
    for k in ("usados", "recusados", "triagem"):
        d[k] = {s: v for s, v in (d.get(k) or {}).items() if (v if isinstance(v, (int, float)) else v[0]) > velho}
    d["bons"] = [c for c in d.get("bons") or [] if c["ts"] > time.time() - 7 * 86400 and c["id"] not in d["usados"]]
    d["feitos"] = (d.get("feitos") or [])[-60:]
    d["tentativas"] = [t for t in d.get("tentativas") or [] if t > time.time() - 3 * 86400]
    andamento.write_json(STATE, d, durable=True)


# ------------------------------------------------------------------ quando fazer
def ritmo(cfg: Any) -> int:
    """De quantos em quantos dias: 1, ou 3 se os numeros mostrarem que o ranking rende bem menos que o corte normal."""
    p = placar()
    r = [x["razao"] for x in p.values() if x["n"] >= 6 and x["n_normal"] >= 6]
    return 3 if r and max(r) < 0.6 else 1


def na_hora(cfg: Any, agora: datetime | None = None) -> bool:
    """Da para tentar o ranking de hoje agora?"""
    if not cfg.get("ranking.ativo", True):
        return False
    agora = agora or datetime.now()
    if agora.hour < int(cfg.get("ranking.hora", 8)):
        return False
    d = _mem()
    feitos = [x for x in d.get("feitos") or [] if x.get("id")]
    if feitos and (agora.date() - date.fromisoformat(feitos[-1]["dia"])).days < ritmo(cfg):
        return False
    hoje = [t for t in d.get("tentativas") or [] if datetime.fromtimestamp(t).date() == agora.date()]
    if len(hoje) >= int(cfg.get("ranking.tentativas_dia", 2)) or (hoje and agora.timestamp() - hoje[-1] < 4 * 3600):
        return False
    from . import uso_ia

    return uso_ia.pode_claude(cfg, "ranking")


# ------------------------------------------------------------------ busca
def nome_jogo(jogo: str) -> str:
    j = (jogo or "").strip()
    return NOMES.get(j.lower(), j.upper()[:16])


def _bloqueado(login: str, nome: str, cfg: Any) -> bool:
    from .discovery import filtros
    from .pipeline import is_blocked

    url = f"https://www.twitch.tv/{login}"
    if filtros.hard_block("", login, url) or filtros.hard_block("", nome, url):
        return True
    return is_blocked(Candidate(id="x", platform="twitch", url=url, title="", channel=nome or login, channel_url=url), cfg)


def _serve(c: dict, cfg: Any, d: dict) -> bool:
    """Regras que nao precisam do Claude."""
    if c["id"] in (d.get("usados") or {}) or c["id"] in (d.get("recusados") or {}) or any(b["id"] == c["id"] for b in d.get("bons") or []):
        return False
    if c["views"] < int(cfg.get("ranking.views_min", 800)) or not MIN_S <= c["dur"] <= 65:
        return False
    if not c["ts"] or c["ts"] < time.time() - 7.2 * 86400 or FORA_TITULO.search(c["titulo"]) or PROIBE.search(c["bio"]):
        return False
    return not _bloqueado(c["login"], c["nome"], cfg)


def _unicos(clipes: list[dict]) -> list[dict]:
    """O mesmo momento clipado por varias pessoas: fica o mais visto."""
    out: list[dict] = []
    for c in sorted(clipes, key=lambda c: -c["views"]):
        if not any(c["id"] == o["id"] or (c["login"] == o["login"] and abs(c["ts"] - o["ts"]) < 120) for o in out):
            out.append(c)
    return out


def _twitch(jogos: list[str]) -> list[dict]:
    from .discovery import twitch_gql as g

    out = []
    campos = ("{ edges { node { slug title viewCount createdAt durationSeconds thumbnailURL broadcaster { login displayName description } } } }")
    for i in range(0, len(jogos), 3):
        lote = jogos[i:i + 3]
        q = "query { " + " ".join(
            f"g{k}: game(name: {json.dumps(j)}) {{ name "
            f"s: clips(first: 100, criteria: {{period: LAST_WEEK, languages: [PT], sort: VIEWS_DESC}}) {campos} "
            f"d: clips(first: 20, criteria: {{period: LAST_DAY, languages: [PT], sort: VIEWS_DESC}}) {campos} }}" for k, j in enumerate(lote)) + " }"
        data, _ = g.gql(q, timeout=25, what="ranking")
        for v in (data or {}).values():
            for e in [*(((v or {}).get("s") or {}).get("edges") or []), *(((v or {}).get("d") or {}).get("edges") or [])]:
                n = e.get("node") or {}
                b = n.get("broadcaster") or {}
                if not b.get("login") or not n.get("slug"):
                    continue
                out.append({"id": n["slug"], "url": f"https://www.twitch.tv/{b['login']}/clip/{n['slug']}", "titulo": n.get("title") or "", "onde": "Twitch",
                            "views": int(n.get("viewCount") or 0), "dur": float(n.get("durationSeconds") or 0), "ts": g.iso_ts(n.get("createdAt")) or 0,
                            "login": b["login"].lower(), "nome": b.get("displayName") or b["login"], "bio": b.get("description") or "", "jogo": v.get("name") or "",
                            "capa": n.get("thumbnailURL") or ""})
    return out


def _jogos_em_alta(n: int = 24) -> list[str]:
    from .discovery import twitch_gql as g

    data, _ = g.gql("query { games(first: %d) { edges { node { name } } } }" % n, what="jogos")
    js = [(e.get("node") or {}).get("name") or "" for e in (((data or {}).get("games") or {}).get("edges") or [])]
    return [j for j in js if j and not FORA_JOGO.search(j)]


def _kick(cfg: Any) -> list[dict]:
    from .discovery import canais, platforms

    logins = list(dict.fromkeys([*(cfg.get("busca.canais_monitorados.kick", []) or []), *(s for s, _ in canais.KICK)]))
    out = []
    for s in logins:
        for c in platforms._flat(f"https://kick.com/{s}/clips", 15):
            jogo = next(iter(c.get("categories") or []), "")
            if FORA_JOGO.search(jogo or ""):
                continue
            out.append({"id": str(c.get("id")), "url": platforms._strip_smuggle(c.get("url") or ""), "titulo": c.get("title") or "", "onde": "Kick",
                        "views": int(c.get("view_count") or 0), "dur": float(c.get("duration") or 0), "ts": float(c.get("timestamp") or 0),
                        "login": s.lower(), "nome": c.get("channel") or s, "bio": "", "jogo": jogo or "",
                        "capa": c.get("thumbnail") or ""})
    return out


def listar(cfg: Any) -> list[dict]:
    """Os clipes mais vistos da semana em portugues (Twitch por jogo, Kick pelos canais acompanhados)."""
    jogos = list(dict.fromkeys([*(cfg.get("ranking.jogos", []) or []), *_jogos_em_alta()]))[:27]
    clipes = _twitch(jogos)
    if cfg.get("busca.fontes.kick", True):
        clipes += _kick(cfg)
    return clipes


def candidatos(cfg: Any, clipes: list[dict]) -> list[dict]:
    """Os que ainda vale olhar, do mais visto para o menos. Canal com 2 clipes proibidos nesta semana fica de fora."""
    d = _mem()
    ruins: dict[str, int] = {}
    for v in (d.get("recusados") or {}).values():
        if len(v) > 2 and str(v[1]).startswith("proibido") and v[0] > time.time() - 7 * 86400:
            ruins[v[2]] = ruins.get(v[2], 0) + 1
    perto = d.get("bons") or []
    out = _unicos([c for c in clipes if _serve(c, cfg, d) and ruins.get(c["login"], 0) < 2])
    out = [c for c in out if not any(c["login"] == b["login"] and abs(c["ts"] - b["ts"]) < 120 for b in perto)]
    tri = {k: v[1] for k, v in (d.get("triagem") or {}).items()}
    out = [c for c in out if tri.get(c["id"], 50) >= 40]           # a capa ja mostrou que nao serve
    return sorted(out, key=lambda c: -(tri.get(c["id"], 45) // 10))     # dentro da mesma faixa, o mais visto


def temas(cfg: Any, clipes: list[dict] | None = None) -> list[dict]:
    """Para o dono ver: assuntos e clipes de hoje, do melhor para o pior: [{"tema", "clipes": [...]}]."""
    bons = candidatos(cfg, listar(cfg) if clipes is None else clipes)
    grupos: dict[str, list[dict]] = {}
    for c in bons:
        grupos.setdefault(nome_jogo(c["jogo"]), []).append(c)
    out = [{"tema": tema, "clipes": cs, "peso": sum(c["views"] for c in cs[:N])} for tema, cs in grupos.items() if tema]
    return sorted(out, key=lambda x: -x["peso"])


def _recusa(d: dict, c: dict, motivo: str) -> None:
    _log.info("clipe fora: %s | %s | %s", c["nome"], c["titulo"][:40], motivo)
    d.setdefault("recusados", {})[c["id"]] = [time.time(), motivo, c["login"]]


# ------------------------------------------------------------------ olhar um por um
def _baixa(c: dict, pasta: Path, cfg: Any) -> Path | None:
    import yt_dlp

    from .download import ytdlp_opts

    dest = pasta / f"{re.sub(r'[^A-Za-z0-9_-]', '', c['id'])[-40:]}.mp4"
    if dest.exists():
        return dest
    try:
        with yt_dlp.YoutubeDL(ytdlp_opts(cfg, format="best[height<=1080][vcodec^=avc]/best[height<=1080]/best", outtmpl=str(dest))) as y:
            y.extract_info(c["url"], download=True)
    except Exception as e:  # noqa: BLE001
        _log.info("clipe %s nao baixou: %s", c["id"][:30], str(e)[:120])
        return None
    return dest if dest.exists() else None


def _quadros(f: Path, dur: float, pasta: Path, i: int) -> Path | None:
    """8 quadros do clipe com o segundo escrito em cada um."""
    import subprocess

    from PIL import Image, ImageDraw, ImageFont

    from . import tools

    n, w, h = 8, 320, 180
    folha = Image.new("RGB", (w * 4, h * 2))
    ok = 0
    fonte = ImageFont.truetype(str(paths.FONTS / "Montserrat-ExtraBold.ttf"), 22)
    for k in range(n):
        t = dur * (k + 0.5) / n
        q = pasta / f"q{i}_{k}.jpg"
        subprocess.run([tools.ffmpeg(), "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(f), "-frames:v", "1", "-vf",
                        f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2", "-q:v", "4", str(q)],
                       capture_output=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if not q.exists():
            continue
        im = Image.open(q).convert("RGB")
        ImageDraw.Draw(im).text((6, 4), f"{t:.0f}s", font=fonte, fill="#FFE600", stroke_width=2, stroke_fill="#000000")
        folha.paste(im, ((k % 4) * w, (k // 4) * h))
        q.unlink(missing_ok=True)
        ok += 1
    if ok < n // 2:
        return None
    out = pasta / f"folha{i}.jpg"
    folha.save(out, quality=80)
    return out


def _picos(f: Path) -> list[int]:
    """Segundos em que o volume da um salto (costuma ser a reacao)."""
    from .pipeline import _rms_per_second

    try:
        v = _rms_per_second(f)
    except Exception:  # noqa: BLE001
        return []
    if len(v) < 5:
        return []
    meio = sorted(v)[len(v) // 2]
    out: list[int] = []
    for i in sorted(range(len(v)), key=lambda i: -v[i]):
        if v[i] >= meio + 4 and all(abs(i - o) >= 4 for o in out):
            out.append(i)
        if len(out) == 3:
            break
    return sorted(out)


def preparar(c: dict, pasta: Path, cfg: Any, i: int) -> dict | None:
    """Baixa, confere o formato, transcreve e tira os quadros. None = nao serve agora; {"fora": motivo} = nao serve nunca."""
    from .editor.ffmpeg import probe
    from . import transcribe

    f = _baixa(c, pasta, cfg)
    if f is None:
        return None
    try:
        info = probe(f)
        if not info["has_video"] or not info["has_audio"] or info["width"] < info["height"] * 1.2 or not MIN_S <= info["duration"] <= 70:
            return None
        tr = transcribe.transcribe(f, cfg, 0.0, float(info["duration"]), language="pt", prompt=f"{c['nome']}, {nome_jogo(c['jogo'])}", purpose="legenda")
        m = FORA_FALA.search(tr.text)
        if m:
            return {"fora": f"proibido: fala {m.group(0).lower()[:3]}..."}
        img = _quadros(f, float(info["duration"]), pasta, i)
    except Exception as e:  # noqa: BLE001
        from . import memoria

        if isinstance(e, memoria.LowMemory):
            raise
        _log.info("clipe %s fora: %s", c["id"][:30], str(e)[:120])
        return None
    if img is None:
        return None
    return {**c, "arquivo": str(f), "dur": float(info["duration"]), "folha": str(img), "picos": _picos(f),
            "segs": [(round(s.start, 1), round(s.end, 1), s.text.strip()) for s in tr.segments],
            "words": [(w.start, w.end, w.text.strip()) for w in tr.words()]}


def _prompt(tema: str, itens: list[dict]) -> str:
    tema = "lives" if tema == "LIVES" else tema
    blocos = []
    for i, c in enumerate(itens, 1):
        fala = " ".join(f"[{a:.0f}-{b:.0f}s] {t}" for a, b, t in c["segs"])[:700] or "(sem fala entendida)"
        picos = ", ".join(f"{x}s" for x in c.get("picos") or [])
        blocos.append(f"{i}. canal {c['nome']} | {nome_jogo(c['jogo'])} | {c['dur']:.0f} s | nome que o público deu: \"{c['titulo'][:60]}\"{' | volume sobe em ' + picos if picos else ''}\nFala: {fala}")
    corpo = "\n\n".join(blocos)
    return f"""Vou montar um vídeo "RANQUEANDO CLIPES DA SEMANA" com {N} momentos curtos de {tema} brasileiras. Cada imagem é um clipe (na mesma ordem da lista): 8 quadros em ordem, com o segundo escrito no canto.

Para cada clipe devolva:
- "proibido": "" se pode ir ao ar em Shorts, TikTok e Instagram. Senão, o motivo em poucas palavras: nudez ou sexo (mesmo de personagem de jogo, seminu, roupa íntima em destaque, conversa sobre sexo ou sobre partes íntimas), drogas, propaganda, sorteio, aposta, QR code ou pedido de dinheiro no centro da cena, ódio ou ataque a grupo, humilhação de pessoa comum, criança, violência real, dado pessoal, filme, série, TV ou música de terceiros ocupando a cena. {LIVRE}
- "nota": 0 a 100, o quanto ESSE momento diverte, assusta ou surpreende quem nunca viu o canal, sem explicação nenhuma. 85 = tem uma coisa clara acontecendo e um desfecho (queda, batida, susto, azar, resposta engraçada). 65 = dá para entender e tem graça, mesmo sendo só uma piada falada com desfecho. 30 = conversa sem desfecho, piada interna, cena parada, não dá para saber o que houve.
- "inicio" e "fim": os segundos do melhor pedaço, de 6 a 10 s, com a preparação curta e o desfecho inteiros. O pedaço tem que MOSTRAR o que o nome diz: confira nos quadros em que segundo a coisa acontece (o volume costuma subir na reação). Comece no começo de uma frase e termine depois da reação. Se o palavrão forte puder ficar de fora, deixe de fora.
- "nome": 2 a 4 palavras em português, até 20 letras, que dizem o que acontece e dão curiosidade, sem inventar nada. Exemplos: "Acabou a vibe", "A porta do ritual", "Foto do outdoor". Nunca "Momento engraçado", "Reação", "Kkkk".
- "legendado": true se já aparece na imagem uma legenda grande com a fala da pessoa; false se só há texto do jogo, chat ou nada.

CLIPES
{corpo}

RESPONDA SÓ COM ESTE JSON:
{{"clipes":[{{"i":1,"proibido":"","nota":70,"inicio":3.0,"fim":11.0,"nome":"...","legendado":false}}]}}"""


def triar(cands: list[dict], pasta: Path, cfg: Any) -> dict[str, float] | None:
    """Uma olhada nas capas e nos nomes, antes de baixar: nota de 0 a 100 por clipe. None = sem resposta."""
    import io

    import requests
    from PIL import Image, ImageDraw, ImageFont

    from .brain import get_brain
    from .brain.base import extract_json

    w, h, col = 240, 135, 8
    folha = Image.new("RGB", (w * col, h * ((len(cands) + col - 1) // col)))
    fonte = ImageFont.truetype(str(paths.FONTS / "Montserrat-ExtraBold.ttf"), 24)
    for k, c in enumerate(cands):
        try:
            im = Image.open(io.BytesIO(requests.get(c["capa"], timeout=10).content)).convert("RGB").resize((w, h))
        except Exception:  # noqa: BLE001
            im = Image.new("RGB", (w, h), "#333333")
        ImageDraw.Draw(im).text((5, 2), str(k + 1), font=fonte, fill="#FFE600", stroke_width=3, stroke_fill="#000000")
        folha.paste(im, ((k % col) * w, (k // col) * h))
    f = pasta / "capas.jpg"
    folha.save(f, quality=82)
    b = get_brain(cfg, tarefa="ranking")
    if b.name != "claude":
        return None
    lista = "\n".join(f"{k}. {c['nome']} | {nome_jogo(c['jogo'])} | {c['dur']:.0f} s | {c['views']} views | \"{c['titulo'][:60]}\"" for k, c in enumerate(cands, 1))
    p = f"""A imagem tem a capa de {len(cands)} clipes de lives, numeradas. Quero achar os que têm mais chance de ser um momento engraçado, de susto ou de surpresa que qualquer um entende e que pode ir ao ar em Shorts e TikTok.

{lista}

Dê nota de 0 a 100 para cada um pela capa e pelo nome. Nota menor que 40 para o que parece nudez, sexo, insinuação sexual, biquíni ou roupa íntima em destaque, aposta, slot, propaganda, sorteio, briga de chat, dança, pessoa parada conversando, placar ou tela de espera. 70 ou mais só quando parece haver uma cena ou reação clara.

RESPONDA SÓ COM ESTE JSON, uma nota para cada número: {{"notas":{{"1":50,"2":30}}}}"""
    try:
        res = extract_json(b._run(p, SYSTEM, images=[f]))
        notas = (res.get("notas") if isinstance(res, dict) else None) or {}
        return {cands[int(k) - 1]["id"]: float(v) for k, v in notas.items() if str(k).isdigit() and 1 <= int(k) <= len(cands)} or None
    except Exception as e:  # noqa: BLE001
        _log.warning("triagem das capas: %s", str(e)[:150])
        return None


def conferir(itens: list[dict], pasta: Path, cfg: Any) -> dict[int, dict] | None:
    """Os pedacos EXATOS que vao para o video: cada um mostra o que o nome diz e faz sentido? None = sem resposta."""
    import subprocess

    from PIL import Image, ImageDraw, ImageFont

    from . import tools
    from .brain import get_brain
    from .brain.base import extract_json, list_from_json

    b = get_brain(cfg, tarefa="ranking")
    if b.name != "claude":
        return None
    w, h, n = 320, 180, 5
    folha = Image.new("RGB", (w * n, h * len(itens)))
    fonte = ImageFont.truetype(str(paths.FONTS / "Montserrat-ExtraBold.ttf"), 24)
    for k, c in enumerate(itens):
        for q in range(n):
            arq = pasta / f"conf{k}_{q}.jpg"
            t = c["ini"] + (c["fim"] - c["ini"]) * (q + 0.5) / n
            subprocess.run([tools.ffmpeg(), "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", c["arquivo"], "-frames:v", "1", "-vf",
                            f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2", str(arq)],
                           capture_output=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if arq.exists():
                im = Image.open(arq).convert("RGB")
                if q == 0:
                    ImageDraw.Draw(im).text((6, 2), str(k + 1), font=fonte, fill="#FFE600", stroke_width=3, stroke_fill="#000000")
                folha.paste(im, (q * w, k * h))
    f = pasta / "conferencia.jpg"
    folha.save(f, quality=84)
    linhas = []
    for k, c in enumerate(itens, 1):
        fala = " ".join(t for a, b_, t in c.get("words") or [] if c["ini"] <= (a + b_) / 2 <= c["fim"])[:350]
        linhas.append(f"{k}. nome na tela: {c['nome_tela']} | canal {c['nome']} | {c['fim'] - c['ini']:.0f} s | fala: \"{fala or '(sem fala)'}\"")
    corpo = "\n".join(linhas)
    p = f"""Estes {len(itens)} pedaços curtos vão entrar num vídeo de ranking. Cada linha da imagem é um pedaço, com 5 quadros em ordem.

{corpo}

Para cada um, seja rigoroso:
- "ok": true só se, vendo SÓ este pedaço, dá para entender o que acontece, ele tem um desfecho ou reação e pode ir ao ar (sem nudez, sexo, aposta, propaganda em destaque ou criança). {LIVRE} Piada falada com desfecho vale. Corredor vazio sem reação, conversa solta ou cena cortada antes de acontecer = false.
- "nome": o nome certo para este pedaço, de 2 a 4 palavras e até 20 letras, do que REALMENTE aparece ou é dito nele. Repita o atual se já estiver certo.
- "motivo": até 10 palavras.

RESPONDA SÓ COM ESTE JSON: {{"itens":[{{"i":1,"ok":true,"nome":"...","motivo":"..."}}]}}"""
    try:
        out = {}
        for x in list_from_json(extract_json(b._run(p, SYSTEM, images=[f])), ("itens", "clipes")):
            try:
                out[int(x.get("i"))] = x
            except (TypeError, ValueError):
                continue
        return out or None
    except Exception as e:  # noqa: BLE001
        _log.warning("conferencia dos pedacos: %s", str(e)[:150])
        return None


def julgar(tema: str, itens: list[dict], cfg: Any) -> dict[int, dict] | None:
    """Resposta do Claude por clipe, ou None (sem cota ou sem resposta)."""
    from .brain import get_brain
    from .brain.base import extract_json, list_from_json

    b = get_brain(cfg, tarefa="ranking")
    if b.name != "claude":
        return None
    try:
        res = b._run(_prompt(tema, itens), SYSTEM, images=[Path(c["folha"]) for c in itens])
        out = {}
        for x in list_from_json(extract_json(res), ("clipes", "itens")):
            try:
                out[int(x.get("i"))] = x
            except (TypeError, ValueError):
                continue
        return out or None
    except Exception as e:  # noqa: BLE001
        _log.warning("o Claude nao olhou os clipes: %s", str(e)[:150])
        return None


def ajustar(ini: float, fim: float, words: list[tuple], dur: float) -> tuple[float, float] | None:
    """Encaixa o pedaco na fala: nao comeca nem termina no meio de palavra e fecha a frase se ela acaba logo depois."""
    ini, fim = max(0.0, float(ini)), min(dur, float(fim))
    for a, b, _t in words:
        if a < ini < b:
            ini = max(0.0, a - 0.06)        # comecava no meio da palavra
            break
    for k, (a, b, t) in enumerate(words):
        if a < fim < b or (b <= fim and b > fim - 0.35):
            j = k
            while not re.search(r"[.!?…]$", words[j][2]) and j + 1 < len(words) and words[j + 1][0] - words[j][1] < 0.45 and words[j + 1][1] <= fim + 1.8:
                j += 1
            fim = min(dur, words[j][1] + 0.3)
            if j + 1 < len(words):
                fim = min(fim, max(words[j][1] + 0.05, words[j + 1][0] - 0.04))
            break
    if fim - ini > MAX_S:       # passou: corta o comeco (o desfecho fica), no inicio de uma palavra
        lim = fim - MAX_S
        ini = next((max(lim, a - 0.06) for a, _b, _t in words if a >= lim), lim)
    if fim - ini < MIN_S:       # curto: abre um pouco antes
        ini = max(0.0, fim - MIN_S)
        for a, b, _t in words:
            if a < ini < b:
                ini = max(0.0, a - 0.06)
                break
    return (round(ini, 2), round(fim, 2)) if fim - ini >= MIN_S - 0.4 else None


def nome_ok(nome: str) -> str:
    """Nome na tela, limpo, ou "" se nao serve."""
    from .editor import style
    from .pipeline import mask_profanity

    n = re.sub(r"[\"“”'.]", "", style.strip_emojis(style.sanitize_text(str(nome or "")))).strip(" -|:,!?")
    if not 4 <= len(n) <= 24 or re.fullmatch(r"(?i)(k+|momento\b.*|rea[cç][aã]o\b.*|clipe\b.*|engra[cç]ado|sem t[ií]tulo)", n) or FORA_TITULO.search(n):
        return ""
    return mask_profanity(n, "mascarar").upper()


def avaliar(itens: list[dict], dec: dict[int, dict], cfg: Any, rep: Any = None) -> tuple[list[dict], list[tuple[dict, str]]]:
    """(aprovados, [(recusado, motivo)])."""
    minimo = float(cfg.get("ranking.nota_minima", 60))
    bons, fora = [], []
    for i, c in enumerate(itens, 1):
        d = dec.get(i)
        if not d:
            continue            # nao respondeu sobre este: pode ser visto outro dia
        pr = d.get("proibido")
        proibido = "sim" if pr is True else str(pr or "").strip()
        try:
            nota = float(d.get("nota"))
            tr = ajustar(float(d.get("inicio")), float(d.get("fim")), c["words"], c["dur"])
        except (TypeError, ValueError):
            nota, tr = 0.0, None
        nome = nome_ok(d.get("nome"))
        if proibido.lower() not in ("", "false", "não", "nao", "nenhum", "nada", "none", "null"):
            fora.append((c, "proibido: " + proibido[:60]))
        elif nota < minimo:
            fora.append((c, f"nota {nota:.0f}"))
        elif tr is None or not nome:
            fora.append((c, "sem trecho ou nome bom"))
        else:
            bons.append({**c, "nota": nota, "ini": tr[0], "fim": tr[1], "nome_tela": nome, "legendado": d.get("legendado") in (True, "true", "True", 1)})
    return bons, fora


def escolher(bons: list[dict]) -> list[dict] | None:
    """Os 5 (no maximo 2 por canal, nomes diferentes), ja com a posicao pelas views. None = nao da."""
    out: list[dict] = []
    for c in sorted(bons, key=lambda c: (-c["nota"], -c["views"])):
        if sum(o["login"] == c["login"] for o in out) < 2 and not any(o["nome_tela"] == c["nome_tela"] for o in out):
            out.append(c)
        if len(out) == N:
            break
    if len(out) < N:
        return None
    return [{**c, "pos": k} for k, c in enumerate(sorted(out, key=lambda c: -c["views"]), 1)]


def ordem(itens: list[dict]) -> list[dict]:
    """Ordem em que aparecem: abre com um forte do fim da lista, o 2º no meio e o 1º por ultimo."""
    baixo = sorted([c for c in itens if c["pos"] >= 3], key=lambda c: -c["nota"])
    por = {c["pos"]: c for c in itens}
    return [baixo[0], por[2], *baixo[1:], por[1]]


# ------------------------------------------------------------------ fazer
def de(tema: str) -> str:
    return "de live" if tema == "LIVE" else f"de {tema}" if tema.isupper() and len(tema) <= 9 else f"de {tema.title()}"


def _plano(tema: str, itens: list[dict], run_id: str) -> tuple[ClipPlan, Candidate]:
    hoje = date.today()
    seq = [c for c in sorted(itens, key=lambda c: c["pos"])]
    nomes = list(dict.fromkeys(c["nome"] for c in seq))
    quem = ", ".join(nomes[:-1]) + f" e {nomes[-1]}" if len(nomes) > 1 else nomes[0]
    onde = " e ".join(sorted({c["onde"] for c in itens}, reverse=True))
    slug = re.sub(r"[^a-z0-9]+", "-", tema.lower()).strip("-")
    sid = f"ranking:{slug}-{hoje:%Y%m%d}"
    titulo = TITULOS[hoje.toordinal() % len(TITULOS)].format(de=de(tema))
    lista = ", ".join(f"{c['nome_tela'].capitalize()}" for c in seq)
    p = ClipPlan(id=f"ranking-{slug}-{hoje:%Y%m%d}-{run_id[-4:]}", source_id=sid, start=0.0, end=0.0, title=titulo, hook=f"RANQUEANDO CLIPES {de(tema).upper()} DA SEMANA",
                 description=f"{lista}. Ordem pelas views de cada clipe na {onde.replace(' e ', ' e na ')}.", hashtags=[slug.replace("-", ""), "clipes", "streamers"],
                 score=round(sum(c["nota"] for c in itens) / len(itens), 1), reason="ranking de clipes do publico",
                 category="humor" if tema == "LIVE" else "games", tipo="ranking")
    v = Candidate(id=sid, platform="twitch", url=itens[0]["url"], title="", channel=f"{quem} ({onde})", duration=None,
                  views=sum(c["views"] for c in itens), topic=tema, score=p.score, extra={"clipes": [c["url"] for c in seq]})
    return p, v


def _proximo(cands: list[dict], vistos: set[str], lote: list[dict], bons: list[dict]) -> dict | None:
    """O proximo clipe a olhar: o mais visto, sem deixar um assunto ou um canal tomar conta do lote."""
    livres = [c for c in cands if c["id"] not in vistos and sum(o["login"] == c["login"] for o in [*lote, *bons]) < 3]
    varios = len({nome_jogo(c["jogo"]) for c in livres}) > 1
    for c in livres:
        if not varios or sum(nome_jogo(o["jogo"]) == nome_jogo(c["jogo"]) for o in lote) < LOTE * 0.7:
            return c
    return None


def fechar(bons: list[dict], mistura: bool) -> tuple[str, list[dict]] | None:
    """(assunto, os 5): um jogo com 5 bons; senao, se puder misturar, as lives da semana."""
    grupos: dict[str, list[dict]] = {}
    for c in bons:
        grupos.setdefault(nome_jogo(c["jogo"]), []).append(c)
    feitos = [(tema, escolher(cs)) for tema, cs in grupos.items()]
    feitos = [(tema, cs) for tema, cs in feitos if cs]
    if feitos:
        return max(feitos, key=lambda x: sum(c["views"] for c in x[1]))
    cs = escolher(bons) if mistura else None
    return (MISTURA, cs) if cs else None


def produzir(cfg: Any, rep: Any, trigger: str = "autopiloto") -> dict:
    """Uma tentativa completa. {"ok", "id", "tema", "motivo", "caminho"}. Os aprovados ficam guardados para a proxima."""
    import shutil

    from . import storage
    from .editor import ranking as montagem
    from .util import run_id_now

    d = _mem()
    if trigger != "manual":
        d.setdefault("tentativas", []).append(time.time())
        _grava(d)
    run_id = run_id_now()
    rep.stage(1, 4, "Ranking: procurando os clipes da semana")
    storage.check_free_space(cfg, need_gb=0.7)
    todos = listar(cfg)
    views = {c["id"]: c["views"] for c in todos}
    bons = [{**c, "views": max(c["views"], views.get(c["id"], 0))} for c in d.get("bons") or []]
    cands = candidatos(cfg, todos)
    rep.info(f"{len(cands)} clipe(s) para olhar, {len(bons)} já aprovado(s) antes")
    pasta = paths.TMP / f"ranking_{run_id}"
    pasta.mkdir(parents=True, exist_ok=True)
    consultas, vistos, i = int(cfg.get("ranking.consultas", 2)), set(), 0
    try:
        novos = [c for c in cands if c["id"] not in (d.get("triagem") or {})]
        if fechar(bons, True) is None and len(cands) > LOTE and len(novos) >= TRIAGEM // 2:
            with rep.working("claude: olhando as capas"):
                notas = triar(novos[:TRIAGEM], pasta, cfg)
            if notas:
                d.setdefault("triagem", {}).update({k: [time.time(), v] for k, v in notas.items()})
                _grava(d)
                cands = candidatos(cfg, todos)
                rep.info(f"triagem: {sum(v >= 40 for v in notas.values())} de {len(notas)} capas valem a pena")
        while fechar(bons, consultas <= 0) is None and consultas > 0:
            rep.stage(2, 4, "Ranking: olhando clipe por clipe")
            lote: list[dict] = []
            while len(lote) < LOTE:
                c = _proximo(cands, vistos, lote, bons)
                if c is None or i >= 45:
                    break
                i += 1
                vistos.add(c["id"])
                with rep.working(f"Baixando e ouvindo: {c['nome']} ({c['views']} views)"):
                    x = preparar(c, pasta, cfg, i)
                if x and x.get("fora"):
                    _recusa(d, c, x["fora"])
                elif x:
                    lote.append(x)
            if not lote:
                break
            with rep.working("claude: escolhendo os momentos"):
                dec = julgar("LIVES", lote, cfg)
            consultas -= 1
            if dec is None:
                _grava(d)
                return {"ok": False, "motivo": "o Claude não respondeu ou a cota acabou"}
            novos, fora = avaliar(lote, dec, cfg)
            for c, m in fora:
                _recusa(d, c, m)
            for c in novos:
                _log.info("clipe bom: %s | %s | nota %.0f | %s (%.1f a %.1f s)", c["nome"], nome_jogo(c["jogo"]), c["nota"], c["nome_tela"], c["ini"], c["fim"])
            bons += novos
            d["bons"] = [{k: v for k, v in c.items() if k not in ("arquivo", "folha", "segs", "bio", "capa")} for c in bons]
            _grava(d)
            rep.info(f"{len(bons)} clipe(s) bons até agora")
        # monta: baixa de novo os que vieram guardados; o que sumiu sai da lista
        while True:
            f = fechar(bons, True)
            if f is None:
                return {"ok": False, "motivo": f"só {len(bons)} clipe(s) bons até agora (ficam guardados)"}
            tema, itens = f
            sumiu = []
            for c in itens:
                if not c.get("arquivo") or not Path(c["arquivo"]).exists():
                    arq = _baixa(c, pasta, cfg)
                    c["arquivo"] = str(arq) if arq else ""
                    if not arq:
                        sumiu.append(c["id"])
            fora_ids = set(sumiu)
            falta = [c for c in itens if not c.get("conferido")]
            if not sumiu and falta:
                with rep.working("claude: conferindo os pedaços"):
                    conf = conferir(falta, pasta, cfg)
                if conf is None:
                    return {"ok": False, "motivo": "falta o Claude conferir os pedaços (os aprovados ficam guardados)"}
                for k, c in enumerate(falta, 1):
                    x = conf.get(k) or {}
                    if x.get("ok") not in (True, "true", "True", 1):
                        _recusa(d, c, f"conferência: {str(x.get('motivo') or 'sem resposta')[:60]}")
                        fora_ids.add(c["id"])
                        continue
                    c["conferido"], c["nome_tela"] = True, nome_ok(x.get("nome")) or c["nome_tela"]
                    for g in d.get("bons") or []:
                        if g["id"] == c["id"]:
                            g["conferido"], g["nome_tela"] = True, c["nome_tela"]
                    for g in bons:
                        if g["id"] == c["id"]:
                            g["conferido"], g["nome_tela"], g["arquivo"] = True, c["nome_tela"], c["arquivo"]
            if not fora_ids:
                break
            bons = [c for c in bons if c["id"] not in fora_ids]
            d["bons"] = [c for c in d.get("bons") or [] if c["id"] not in fora_ids]
            _grava(d)
        rep.stage(3, 4, f"Ranking {tema}: montando o vídeo")
        p, v = _plano(tema, itens, run_id)
        db.start_run(run_id, trigger, "ranking", [tema], "fila")
        db.upsert_video(v, status="processado", run_id=run_id)
        rc = montagem.render(ordem(itens), tema, p, cfg, paths.RENDERS / f"{p.id}.mp4")
        p.end = rc.duration
        db.save_plan(p, run_id)
        db.save_rendered(rc)
        db.conn().execute("UPDATE clips SET status='aprovado', curador=? WHERE id=?", ("ranking: os 5 clipes foram aprovados um a um", p.id))
        db.conn().commit()
        db.finish_run(run_id, "ok", {"status": "ok", "cortes": 1, "posts": 0})
        usados = {c["id"] for c in itens}
        d.setdefault("feitos", []).append({"dia": date.today().isoformat(), "tema": tema, "id": p.id})
        d["bons"] = [c for c in d.get("bons") or [] if c["id"] not in usados]
        d.setdefault("usados", {}).update({i_: time.time() for i_ in usados})
        _grava(d)
        rep.ok(f"Corte pronto: {p.title}  [ranking, {rc.duration:.0f} s]")
        return {"ok": True, "id": p.id, "tema": tema, "caminho": rc.path, "titulo": p.title, "itens": p.itens}
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def rodar(cfg: Any, rep: Any, trigger: str = "autopiloto") -> dict:
    """produzir() com a trava de rodada (nunca junto com outra) e sem derrubar quem chamou."""
    from .pipeline import RunLock

    rep = andamento.Tap(rep)
    try:
        with RunLock():
            andamento.begin({"manual": "pedido seu"}.get(trigger, "automático"), "ranking do dia")
            return produzir(cfg, rep, trigger)
    except Exception as e:  # noqa: BLE001
        import traceback

        _log.error("ranking: %s\n%s", e, traceback.format_exc())
        return {"ok": False, "motivo": str(e)[:150]}


# ------------------------------------------------------------------ depois
def vencer(horas: float = 72) -> int:
    """Ranking "da semana" que nao saiu em todas as redes em 3 dias sai da fila."""
    n = 0
    for r in db.conn().execute("SELECT id, plan FROM clips WHERE status='aprovado' AND id LIKE 'ranking-%' AND created<?", (time.time() - horas * 3600,)).fetchall():
        saiu = db.conn().execute("SELECT 1 FROM posts WHERE clip_id=? AND ok=1 AND dry_run=0", (r["id"],)).fetchone()
        db.set_clip_status(r["id"], "publicado" if saiu else "expirado")
        n += 1
    return n


def placar(dias: float = 45) -> dict[str, dict]:
    """Ranking x corte normal em cada rede, com as views em 24 h: {"youtube": {"n", "n_normal", "views", "normal", "razao"}}."""
    import statistics

    from . import numeros

    g: dict[str, dict[str, list[float]]] = {}
    for r in numeros.latest(dias):
        m = numeros.at_age(r["post_id"], 24) or numeros.at_age(r["post_id"], 72)
        if not m or m["views"] is None:
            continue
        lado = "ranking" if str(r["clip_id"] or "").startswith("ranking-") else "normal"
        g.setdefault(r["platform"], {"ranking": [], "normal": []})[lado].append(float(m["views"]))
    out = {}
    for rede, x in g.items():
        if x["ranking"]:
            a = statistics.median(x["ranking"])
            b = statistics.median(x["normal"]) if x["normal"] else 0.0
            out[rede] = {"n": len(x["ranking"]), "n_normal": len(x["normal"]), "views": a, "normal": b, "razao": (a + 1) / (b + 1)}
    return out
