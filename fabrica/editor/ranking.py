"""Montagem do ranking: titulo fixo em cima, lista de 1 a 5 que vai sendo preenchida, video exatamente no meio da tela.

A lista fica acima do video (nunca por cima de rosto), o momento atual fica marcado em amarelo, nao ha tela preta entre um e
outro. Sai uma versao por rede (o @ muda), igual aos outros cortes.
"""
from __future__ import annotations

import math
import shutil
import struct
import wave
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .. import log, paths
from ..models import RenderedClip, Segment, Transcript, Word
from ..util import short_hash
from . import captions as captions_mod
from . import ffmpeg as ff
from . import fonts, overlays, style

_log = log.get("editor.ranking")
W, H, FPS = 1080, 1920, 30
BANDA = 608                     # altura do video 16:9 na largura da tela
BANDA_Y = (H - BANDA) // 2      # centro exato
LISTA_Y, LINHA = 350, 56
LEGENDA_Y = 1346
MARCA_Y = 1464
CORES = {1: "#FFD400", 2: "#D5DAE3", 3: "#E39A4B", 4: "#FFFFFF", 5: "#FFFFFF"}


def _f(peso: str, px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(paths.FONTS / f"Montserrat-{peso}.ttf"), px)


def _cabe(txt: str, peso: str, px: int, larg: int, minimo: int = 24) -> ImageFont.FreeTypeFont:
    while px > minimo and _f(peso, px).getlength(txt) > larg:
        px -= 2
    return _f(peso, px)


def _txt(d: ImageDraw.ImageDraw, xy: tuple, t: str, f: Any, cor: str, anchor: str = "lm", s: int = 3) -> None:
    d.text((xy[0], xy[1] + s), t, font=f, fill=(0, 0, 0, 170), anchor=anchor, stroke_width=3, stroke_fill=(0, 0, 0, 150))
    d.text(xy, t, font=f, fill=cor, anchor=anchor, stroke_width=3, stroke_fill="#000000")


def views_txt(v: int) -> str:
    """3317 -> 3,3 mil (nunca arredonda para cima)."""
    if v < 1000:
        return str(v)
    if v < 1_000_000:
        x = math.floor(v / 100) / 10
        return f"{x:.1f}".replace(".", ",").replace(",0", "") + " mil" if x < 100 else f"{int(x)} mil"
    return f"{math.floor(v / 100_000) / 10:.1f}".replace(".", ",").replace(",0", "") + " mi"


def linhas_titulo(tema: str) -> tuple[str, str]:
    return ("RANQUEANDO CLIPES", "DE LIVE DA SEMANA" if tema == "LIVE" else f"DE {tema.upper()} DA SEMANA")


def tela(itens: list[dict], vistos: set[int], atual: int, tema: str, nota: str) -> Image.Image:
    """Tudo que fica por cima do video num momento (sem a marca)."""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    a, b = linhas_titulo(tema)
    _txt(d, (W // 2, 198), a, _cabe(a, "Black", 66, W - 128), "#FFFFFF", "mm")
    _txt(d, (W // 2, 278), b, _cabe(b, "Black", 66, W - 128), style.BRAND_YELLOW, "mm")
    por = {c["pos"]: c for c in itens}
    for n in range(1, len(itens) + 1):
        y = LISTA_Y + (n - 1) * LINHA
        cy = y + LINHA // 2
        if n == atual:
            d.rounded_rectangle((style.MARGIN, y + 2, W - style.MARGIN, y + LINHA - 2), 14, fill=(255, 230, 0, 240))
        _txt(d, (92, cy), str(n), _f("Black", 42), CORES.get(n, "#FFFFFF") if n != atual else "#FFFFFF", "lm")
        if n not in vistos:
            continue
        c = por[n]
        dir_ = f"{c['nome']}  {views_txt(c['views'])}"
        if n == atual:
            f2 = _cabe(dir_, "ExtraBold", 28, 400, 20)
            d.text((W - 84, cy), dir_, font=f2, fill=style.BRAND_INK, anchor="rm")
            d.text((150, cy), c["nome_tela"], font=_cabe(c["nome_tela"], "Black", 36, int(W - 84 - f2.getlength(dir_) - 150 - 24)), fill=style.BRAND_INK, anchor="lm")
        else:
            f2 = _cabe(dir_, "SemiBold", 26, 400, 20)
            _txt(d, (W - 84, cy), dir_, f2, "#E8E8EC", "rm", 2)
            _txt(d, (150, cy), c["nome_tela"], _cabe(c["nome_tela"], "ExtraBold", 34, int(W - 84 - f2.getlength(dir_) - 150 - 24)), "#FFFFFF", "lm", 2)
    d.text((W // 2, 1436), nota, font=_f("SemiBold", 26), fill=(255, 255, 255, 215), anchor="mm", stroke_width=2, stroke_fill=(0, 0, 0, 160))
    return im


def _marca(marca: Any, rede: str, work: Path) -> Path | None:
    """Logo e @ da rede lado a lado numa imagem sem sobra nas bordas (centralizar a imagem centraliza o que se ve)."""
    if marca is None:
        return None
    pecas = [Image.open(p).convert("RGBA") for p in (marca.logo, (marca.handles.get(rede) or [None])[0]) if p is not None]
    pecas = [im.crop(im.getchannel("A").point(lambda v: 255 if v > 60 else 0).getbbox() or (0, 0, *im.size)) for im in pecas]
    if not pecas:
        return None
    h, vao = max(p.height for p in pecas), 16
    larg = sum(p.width for p in pecas) + vao * (len(pecas) - 1)
    im = Image.new("RGBA", (larg + larg % 2, h), (0, 0, 0, 0))
    x = 0
    for p in pecas:
        im.alpha_composite(p, (x, (h - p.height) // 2))
        x += p.width + vao
    out = work / f"marca_{rede or 'u'}.png"
    im.save(out)
    return out


def _estalo(dest: Path, sr: int = 48000) -> Path:
    """Som curto quando um momento novo entra na lista."""
    n = int(sr * 0.25)
    with wave.open(str(dest), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"".join(struct.pack("<h", int(32767 * 0.35 * math.sin(2 * math.pi * (520 + 1400 * i / sr) * i / sr) * math.exp(-22 * i / sr))) for i in range(n)))
    return dest


def legendas(itens: list[dict]) -> Transcript:
    """Fala dos momentos que nao vieram legendados, no tempo do video final (frase de um nao se junta com a do outro)."""
    segs = []
    for c in itens:
        if c.get("legendado"):
            continue
        ws = [Word(max(c["t0"], c["t0"] + a - c["ini"]), min(c["t1"], c["t0"] + b - c["ini"]), t)
              for a, b, t in c.get("words") or [] if c["ini"] - 0.02 <= (a + b) / 2 <= c["fim"]]
        if ws:
            segs.append(Segment(ws[0].start, ws[-1].end, " ".join(w.text for w in ws), ws))
    return Transcript(segs, "pt", "whisper")


def render(itens: list[dict], tema: str, plan: Any, cfg: Any, out_path: Path, platforms: list[str] | None = None) -> RenderedClip:
    """itens na ordem em que aparecem. Preenche plan.itens e plan.fala."""
    from . import _variant_platforms

    fonts.ensure_fonts()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work = paths.TMP / f"rk_{short_hash(str(out_path))}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    threads = max(1, min(6, int(cfg.get("edicao.threads", 6) or 6)))
    onde = sorted({c["onde"] for c in itens}, reverse=True)
    nota = "ordem por views do clipe na " + " e na ".join(onde)
    try:
        pop = _estalo(work / "pop.wav")
        t, vistos, partes = 0.0, set(), []
        for k, c in enumerate(itens):
            quadros = round((c["fim"] - c["ini"]) * FPS)
            dur = quadros / FPS
            c["t0"], c["t1"] = round(t, 3), round(t + dur, 3)
            t += dur
            vistos.add(c["pos"])
            tela(itens, vistos, c["pos"], tema, nota).save(work / f"t{k}.png")
            med = ff.measure_loudness(c["arquivo"], c["ini"], dur)
            mat = "out_color_matrix=bt709:out_range=tv"     # cada clipe vem com uma matriz de cor: sem isto o amarelo muda de um para o outro
            tag = "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv"
            g = (f"[0:v]fps={FPS},setsar=1,split[a][b];"
                 f"[a]scale=270:480:force_original_aspect_ratio=increase:{mat},format=yuv420p,{tag},crop=270:480,boxblur=7:2,scale={W}:{H},eq=brightness=-0.16:saturation=0.9[bg];"
                 f"[b]scale={W}:{BANDA}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos:{mat},format=yuv420p,{tag}[fg];"
                 f"[1:v]format=rgba,scale=iw:ih:{mat},format=yuva420p,{tag}[ov];"
                 f"[bg][fg]overlay=(W-w)/2:(H-h)/2[x];[x][ov]overlay=0:0,format=yuv420p,{tag}[v];"
                 f"[0:a]aresample=48000,{ff.loudnorm_filter(med)},aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                 f"apad,atrim=end_sample={quadros * 1600},asetpts=PTS-STARTPTS,afade=t=in:d=0.04,afade=t=out:st={max(0.0, dur - 0.06):.3f}:d=0.06[a0];"
                 f"[2:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[p];[a0][p]amix=inputs=2:duration=first:normalize=0,"
                 f"alimiter=limit=0.89:level=false[ao]")
            o = work / f"s{k}.mkv"
            ff.run(["-threads", str(threads), "-ss", f"{c['ini']:.3f}", "-t", f"{dur + 0.6:.3f}", "-i", c["arquivo"], "-i", f"t{k}.png", "-i", pop.name,
                    "-filter_complex", g, "-map", "[v]", "-map", "[ao]", "-frames:v", str(quadros), "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "14", "-threads", str(threads), "-c:a", "pcm_s16le", "-ar", "48000", str(o)], cwd=work, timeout=600)
            partes.append(o)
        total = round(t, 3)
        (work / "lista.txt").write_text("".join(f"file '{p.name}'\n" for p in partes), encoding="utf-8")

        plats = _variant_platforms(cfg) if platforms is None else list(platforms)
        marca = None
        try:
            marca = overlays.render_brand(cfg, work, plats, scale=0.8)
        except Exception as e:  # noqa: BLE001
            _log.warning("marca: %s", e)
        ass = captions_mod.build_ass(legendas(itens), total, cfg, "blur", work / "leg.ass", watermark="", progress_bar=False, caption_y=LEGENDA_Y,
                                     category=getattr(plan, "category", None), max_lines=1)
        from . import _rel_or_copy

        args = ["-threads", str(threads), "-f", "concat", "-safe", "0", "-i", "lista.txt"]
        idx, cur, graph = 1, "vs", [f"[0:v]ass={ass.name}:fontsdir={_rel_or_copy(paths.FONTS, work)}[vs]"]
        saidas = plats or [""]
        n = len(saidas)
        if n > 1:
            graph.append(f"[{cur}]split={n}" + "".join(f"[c{i}]" for i in range(n)))
        for i, rede in enumerate(saidas):
            src = f"c{i}" if n > 1 else cur
            m = _marca(marca, rede, work)
            if m is not None:
                args += ["-i", m.name]
                graph.append(f"[{idx}:v]format=rgba,scale=iw:ih:out_color_matrix=bt709:out_range=tv,format=yuva420p[m{i}];"
                             f"[{src}][m{i}]overlay=(W-w)/2:{MARCA_Y},format=yuv420p[o{i}]")
                idx += 1
            else:
                graph.append(f"[{src}]format=yuv420p[o{i}]")
        enc = ff.pick_encoder(cfg)
        finais = [out_path.with_name(f"{out_path.stem}_{r}.mp4") if r else out_path for r in saidas]
        tmps = [f.with_name(f.stem + ".part.mp4") for f in finais]
        cmd = [*args, "-filter_complex", ";".join(graph)]
        for i, tmp in enumerate(tmps):
            cmd += ["-map", f"[o{i}]", "-map", "0:a", "-t", f"{total:.3f}", "-r", str(FPS), *ff.video_encoder_args(enc, cfg, FPS, threads=max(1, threads // n)),
                    *ff.audio_args(cfg), "-map_metadata", "-1", "-movflags", "+faststart", str(tmp)]
        ff.run(cmd, cwd=work, timeout=1200)
        for f, tmp in zip(finais, tmps):
            i = ff.probe(tmp)
            if (i["width"], i["height"]) != (W, H) or abs(i["duration"] - total) > 0.3 or not i["has_audio"]:
                for x in tmps:
                    x.unlink(missing_ok=True)
                raise ff.FFmpegError(f"ranking invalido: {i['width']}x{i['height']} {i['duration']:.2f}s (esperado {total:.2f}s)")
            tmp.replace(f)
        variants = {r: str(f) for r, f in zip(saidas, finais) if r}
        principal = Path(variants.get("youtube") or finais[0])
        thumb = out_path.with_suffix(".jpg")
        try:
            ff.extract_frame(principal, 1.0, thumb)
        except ff.FFmpegError:
            thumb = None
        plan.itens = [{"pos": c["pos"], "nome": c["nome_tela"], "quem": c["nome"], "views": c["views"], "onde": c["onde"], "url": c["url"], "t0": c["t0"], "t1": c["t1"],
                       "fala": " ".join(w for a, b, w in c.get("words") or [] if c["ini"] <= (a + b) / 2 <= c["fim"])[:400]} for c in itens]
        plan.fala = " ".join(x["fala"] for x in plan.itens if x["fala"])[:1500]
        _log.info("ranking montado: %s (%.1f s, %d saida(s))", principal.name, total, n)
        return RenderedClip(plan=plan, path=str(principal), duration=total, layout="ranking", thumbnail=str(thumb) if thumb else None, variants=variants)
    finally:
        shutil.rmtree(work, ignore_errors=True)
