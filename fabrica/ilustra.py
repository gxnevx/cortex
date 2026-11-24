"""Estilo com imagens: quando a pessoa cita alguem ou alguma coisa, a imagem aparece na tela por 1,5 s, com musica baixa de fundo.

Imagens: a principal do artigo da Wikipedia sobre aquilo, so com licenca livre (CC0, dominio publico, CC BY, CC BY-SA), com credito no texto
do post. Musica: gerada aqui mesmo (sem arquivo de ninguem), bem baixa e abaixando quando alguem fala.
So entra quando ha pelo menos 2 imagens certas; senao o corte fica simples.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import wave
from pathlib import Path
from typing import Any

from . import honesto, log, paths, tools

_log = log.get("ilustra")
CACHE = paths.DATA / "imagens"
UA = {"User-Agent": "cortes-local/1.0 (uso local)"}
LIVRES = re.compile(r"^(cc0|public domain|pd\b|cc by(-sa)?( \d|$)|cc-by)", re.I)
DUR = 1.5            # segundos de cada imagem
FPS = 30
MIN_IMG, MAX_IMG = 2, 5
CORES = {"humor": "#FFE600", "games": "#39FF88", "polemica": "#FF2D2D", "podcast": "#FFE600", "entretenimento": "#B46BFF", "curiosidade": "#35D6FF"}


# ------------------------------------------------------------------ busca
def _json(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def _api(site: str, **kw: Any) -> dict:
    return _json(f"https://{site}/w/api.php?" + urllib.parse.urlencode({"format": "json", "formatversion": 2, "action": "query", **kw}))


def _parecido(termo: str, titulo: str) -> bool:
    """O artigo achado e mesmo sobre o termo? (todas as palavras do termo no titulo, ou o contrario)"""
    a, b = set(honesto.plano(termo).split()), set(honesto.plano(re.sub(r"\(.*?\)", "", titulo)).split())
    return bool(a and b) and (a <= b or b <= a) and len(a & b) >= max(1, min(len(a), len(b)))


def _arquivo(termo: str) -> tuple[str, str] | None:
    """(titulo do artigo, nome do arquivo da imagem livre)."""
    for site in ("pt.wikipedia.org", "en.wikipedia.org"):
        d = _api(site, prop="pageimages", piprop="name", pilicense="free", titles=termo, redirects=1)
        for p in d.get("query", {}).get("pages", []):
            if p.get("pageimage"):
                return p["title"], p["pageimage"]
        s = _api(site, list="search", srsearch=termo, srlimit=2)
        for r in s.get("query", {}).get("search", []):
            if not _parecido(termo, r["title"]):
                continue
            d = _api(site, prop="pageimages", piprop="name", pilicense="free", titles=r["title"])
            for p in d.get("query", {}).get("pages", []):
                if p.get("pageimage"):
                    return p["title"], p["pageimage"]
    return None


def _limpo(v: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", v or ""))).strip()


def buscar(termo: str) -> dict | None:
    """{"arquivo", "artigo", "autor", "licenca"} ou None. Guarda em cache (tambem o "nao achei", por 7 dias)."""
    termo = re.sub(r"\s+", " ", str(termo or "")).strip()
    if not 2 <= len(termo) <= 60:
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    chave = hashlib.sha1(honesto.plano(termo).encode()).hexdigest()[:16]
    meta, img = CACHE / f"{chave}.json", CACHE / f"{chave}.jpg"
    try:
        m = json.loads(meta.read_text(encoding="utf-8"))
        if m.get("ok") and img.exists():
            return {**m, "arquivo": str(img)}
        if not m.get("ok") and time.time() - float(m.get("ts", 0)) < 7 * 86400:
            return None
    except Exception:
        pass
    res: dict = {"ok": False, "ts": time.time(), "termo": termo}
    try:
        got = _arquivo(termo)
        if got:
            d = _api("commons.wikimedia.org", titles=f"File:{got[1]}", prop="imageinfo", iiprop="url|extmetadata|size|mime", iiurlwidth=1100)
            ii = next((p["imageinfo"][0] for p in d.get("query", {}).get("pages", []) if p.get("imageinfo")), None)
            if ii and ii.get("mime") in ("image/jpeg", "image/png") and min(ii.get("width", 0), ii.get("height", 0)) >= 380:
                em = ii.get("extmetadata") or {}
                lic = _limpo((em.get("LicenseShortName") or {}).get("value", ""))
                if LIVRES.match(lic) and _baixa(ii.get("thumburl") or ii["url"], img):
                    res.update(ok=True, artigo=got[0], autor=_limpo((em.get("Artist") or {}).get("value", ""))[:60] or "autor desconhecido", licenca=lic)
    except Exception as e:
        _log.info("imagem de '%s': %s", termo, str(e)[:120])
        return None         # sem internet: tenta de novo na proxima
    meta.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    return {**res, "arquivo": str(img)} if res["ok"] else None


def _baixa(url: str, dest: Path) -> bool:
    if urllib.parse.urlparse(url).hostname not in ("upload.wikimedia.org", "thumb.wikimedia.org"):
        return False
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        raw = r.read(6_000_000)
    from io import BytesIO

    from PIL import Image

    im = Image.open(BytesIO(raw))
    im.load()
    im.convert("RGB").save(dest, quality=90)
    return True


# ------------------------------------------------------------------ momentos
def momentos(imagens: list[dict], palavras: list, total: float, inicio_livre: float = 2.6) -> list[dict]:
    """Em que segundo do video pronto cada imagem entra: na primeira vez que a palavra e dita, com folga entre elas."""
    ws = [(honesto.plano(w.text), float(w.start)) for w in palavras]
    out: list[dict] = []
    for im in imagens or []:
        alvo = honesto.plano(im.get("palavra")).split()
        if not alvo:
            continue
        for i in range(len(ws) - len(alvo) + 1):
            if [w for w, _ in ws[i:i + len(alvo)]] != alvo:
                continue
            t = ws[i][1]
            if inicio_livre <= t <= total - DUR - 1.5 and all(abs(t - o["t"]) >= DUR + 1.5 for o in out):
                out.append({**im, "t": round(t, 2)})
                break
    return sorted(out, key=lambda o: o["t"])[:MAX_IMG]


def preparar(imagens: list[dict], palavras: list, total: float) -> list[dict]:
    """Momentos com a imagem ja baixada. Menos de 2: lista vazia (o corte fica simples)."""
    prontos = []
    for m in momentos(imagens, palavras, total):
        b = buscar(m.get("busca") or m.get("palavra"))
        if b:
            prontos.append({**m, **{k: b[k] for k in ("arquivo", "artigo", "autor", "licenca")}})
    return prontos if len(prontos) >= MIN_IMG else []


def credito(ms: list[dict]) -> str:
    """Linha de credito do post (a licenca exige)."""
    vistos, partes = set(), []
    for m in ms or []:
        k = (m.get("autor"), m.get("licenca"))
        if m.get("autor") and k not in vistos:
            vistos.add(k)
            partes.append(f"{m['autor']} ({m['licenca']})")
    return ("Imagens: " + ", ".join(partes) + ", via Wikimedia Commons") if partes else ""


# ------------------------------------------------------------------ cartao
def _cartao(arquivo: str, cor: str) -> Any:
    from PIL import Image, ImageDraw, ImageFilter

    im = Image.open(arquivo).convert("RGB")
    cx, cy = (760, 520) if im.width >= im.height else (470, 600)
    k = min(cx / im.width, cy / im.height)
    im = im.resize((max(2, round(im.width * k)), max(2, round(im.height * k))), Image.LANCZOS)
    b, g = 8, 46
    w, h = im.width + 2 * (b + g), im.height + 2 * (b + g)
    rgb = tuple(int(cor[i:i + 2], 16) for i in (1, 3, 5))
    brilho = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(brilho).rectangle((g, g, w - g - 1, h - g - 1), fill=(*rgb, 255))
    brilho = brilho.filter(ImageFilter.GaussianBlur(20))
    ImageDraw.Draw(brilho).rectangle((g, g, w - g - 1, h - g - 1), fill=(*rgb, 255))
    brilho.paste(im, (g + b, g + b))
    return brilho


def _quadros(arquivo: str, cor: str, pasta: Path, i: int) -> tuple[str, int, int]:
    """Entra crescendo (0,17 s), fica parado e some (0,1 s). PNGs com transparencia, tela fixa."""
    from PIL import Image

    base = _cartao(arquivo, cor)
    W, H = round(base.width * 1.08) // 2 * 2, round(base.height * 1.08) // 2 * 2
    n = round(DUR * FPS)
    esc = [0.62, 0.86, 1.02, 1.06, 1.02]
    cache: dict = {}
    for f in range(n):
        s = esc[f] if f < len(esc) else 1.0
        a = 1.0 if f < n - 3 else (n - f) / 4
        if (s, a) not in cache:
            c = base if s == 1.0 else base.resize((max(2, round(base.width * s)), max(2, round(base.height * s))), Image.LANCZOS)
            t = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            t.alpha_composite(c, ((W - c.width) // 2, (H - c.height) // 2))
            if a < 1:
                t.putalpha(t.getchannel("A").point(lambda v: int(v * a)))
            cache[(s, a)] = t
        cache[(s, a)].save(pasta / f"c{i}_{f:03d}.png", compress_level=1)
    return str(pasta / f"c{i}_%03d.png"), W, H


# ------------------------------------------------------------------ musica
ACORDES = {"leve": [(57, 60, 64, 67), (53, 57, 60, 64), (48, 52, 55, 59), (55, 59, 62, 65)],
           "tensa": [(45, 48, 52, 55), (41, 45, 48, 52), (45, 48, 52, 57), (40, 44, 47, 50)]}


def trilha(dest: Path, dur: float, clima: str = "leve", semente: int = 0, sr: int = 44100) -> Path:
    """Base calma gerada na hora: acordes macios, baixo e uma batida discreta. Nada de ninguem, zero direito autoral."""
    import numpy as np

    rng = np.random.default_rng(semente)
    bpm = 78.0 if clima == "tensa" else 86.0
    passo = 60.0 / bpm
    n = int(sr * (dur + 0.5))
    t = np.arange(n) / sr
    x = np.zeros(n)
    tom = int(rng.integers(-2, 3))
    compasso = 4 * passo
    for k in range(int(dur / compasso) + 1):
        ini = k * compasso
        a, b = int(ini * sr), min(n, int((ini + compasso) * sr))
        if a >= n:
            break
        tt = t[a:b] - ini
        env = np.minimum(1, tt / 0.35) * np.minimum(1, np.maximum(0, compasso - tt) / 0.5)
        ac = ACORDES[clima][k % 4]
        for j, nota in enumerate(ac):
            f = 440 * 2 ** ((nota + tom - 69) / 12)
            x[a:b] += 0.10 * env * (np.sin(2 * np.pi * f * tt) + 0.25 * np.sin(2 * np.pi * 2 * f * tt + 0.3) * np.exp(-tt * 1.5)) * (1 + 0.15 * np.sin(2 * np.pi * 0.8 * tt + j))
        fb = 440 * 2 ** ((ac[0] + tom - 12 - 69) / 12)
        x[a:b] += 0.14 * env * np.sin(2 * np.pi * fb * tt)
        for q in range(4):          # batida discreta
            for off, tipo in ((0.0, "bumbo" if q in (0, 2) else "caixa"), (0.5, "prato")):
                s0 = int((ini + (q + off) * passo) * sr)
                m = int(0.16 * sr)
                if s0 + m >= n:
                    continue
                e = np.arange(m) / sr
                if tipo == "bumbo":
                    x[s0:s0 + m] += 0.22 * np.sin(2 * np.pi * (48 * e + 22 * (1 - np.exp(-e * 30)) / 3)) * np.exp(-e * 22)
                else:
                    r = rng.standard_normal(m)
                    r = r - np.concatenate(([0], r[:-1])) * (0.2 if tipo == "caixa" else 0.9)
                    x[s0:s0 + m] += (0.030 if tipo == "caixa" else 0.010) * r * np.exp(-e * (26 if tipo == "caixa" else 60))
    k = 24          # tira o brilho: fica atras da voz
    x = np.convolve(x, np.ones(k) / k, mode="same")
    fi = int(0.8 * sr)
    x[:fi] *= np.linspace(0, 1, fi)
    x[-int(1.5 * sr):] *= np.linspace(1, 0, int(1.5 * sr))
    x *= 0.5 / (np.abs(x).max() or 1.0)
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return dest


# ------------------------------------------------------------------ aplicar
def aplicar(arquivo: Path, ms: list[dict], dur: float, categoria: str | None, cfg: Any, centro_y: int = 960) -> None:
    """Poe as imagens e a musica num video pronto (troca o arquivo so se der tudo certo)."""
    arquivo = Path(arquivo)
    cor = CORES.get(str(categoria or ""), "#FFE600")
    clima = "tensa" if categoria in ("polemica", "politica", "noticias") else "leve"
    vol = float(cfg.get("edicao.musica_volume_db", -23))
    pasta = Path(tempfile.mkdtemp(prefix="ilustra_"))
    try:
        mus = trilha(pasta / "m.wav", dur, clima, semente=int(hashlib.sha1(arquivo.stem.encode()).hexdigest()[:6], 16))
        args = [tools.ffmpeg(), "-v", "error", "-y", "-i", str(arquivo), "-i", str(mus)]
        fc, ult = [], "0:v"
        for i, m in enumerate(ms):
            seq, w, h = _quadros(m["arquivo"], cor, pasta, i)
            args += ["-framerate", str(FPS), "-i", seq]
            fc.append(f"[{i + 2}:v]format=rgba,setpts=PTS+{m['t']:.3f}/TB[k{i}]")
            fc.append(f"[{ult}][k{i}]overlay=x={(1080 - w) // 2}:y={centro_y - h // 2}:eof_action=pass:enable='between(t,{m['t']:.3f},{m['t'] + DUR:.3f})'[v{i}]")
            ult = f"v{i}"
        # a musica abaixa quando ha voz (sidechain) e nunca passa da voz
        fc.append(f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={vol}dB[m];[0:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[a0][sc];"
                  f"[m][sc]sidechaincompress=threshold=0.03:ratio=4:attack=40:release=500[mm];[a0][mm]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]")
        tmp = arquivo.with_name(arquivo.stem + "_il.mp4")
        args += ["-filter_complex", ";".join(fc), "-map", f"[{ult}]" if ms else "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "fast", "-crf", "19",
                 "-pix_fmt", "yuv420p", "-r", str(FPS), "-threads", str(max(1, min(6, int(cfg.get("edicao.threads", 6) or 6)))), "-c:a", "aac", "-b:a", "192k",
                 "-movflags", "+faststart", str(tmp)]
        r = subprocess.run(args, capture_output=True, timeout=900, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode != 0 or not tmp.exists() or tmp.stat().st_size < 200_000:
            tmp.unlink(missing_ok=True)
            raise RuntimeError((r.stderr or b"").decode("utf-8", "replace")[-300:])
        tmp.replace(arquivo)
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def no_corte(rc: Any, p: Any, caps: Any, cfg: Any, tem_longa: bool) -> bool:
    """Depois de editar: se o corte foi sorteado para o estilo e ha imagens certas, aplica. Sem imagens, sai do teste."""
    if tem_longa or rc.layout in ("react", "split") or not getattr(p, "imagens", None) or caps is None:
        p.exp.pop("imagens", None)
        p.imagens = []
        return False
    ms = preparar(p.imagens, caps.words(), rc.duration)
    if not ms:
        p.exp.pop("imagens", None)
        p.imagens = []
        return False
    if p.exp.get("imagens") != "B":
        p.imagens = []          # podia, mas foi sorteado para ficar simples (lado A do teste)
        return False
    try:
        for f in {rc.path, *rc.variants.values()}:
            aplicar(Path(f), ms, rc.duration, p.category, cfg)
        p.imagens = ms
        _log.info("%d imagem(ns) e musica em '%s': %s", len(ms), p.title[:50], ", ".join(m["artigo"] for m in ms))
        return True
    except Exception as e:
        _log.warning("estilo com imagens falhou (%s); o corte fica simples", str(e)[:200])
        p.exp.pop("imagens", None)
        p.imagens = []
        return False
