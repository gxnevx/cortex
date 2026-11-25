"""Editor: transforma um trecho de video em corte vertical 1080x1920 pronto para Shorts/TikTok.

    render_clip(source, start, end, plan, captions, cfg, out_path, layout=None, video=None) -> RenderedClip

Uma unica passada do ffmpeg: seek preciso, jump cuts (pausas longas viram ~0,12 s, legenda
retimada), enquadramento no rosto de quem fala, zoom dinamico (punch-ins), layout
(split/blur/full), titulo PNG com emojis coloridos, etiqueta de nome (lower third) depois do
teaser, CTA de serie nos 2 s finais, legendas ASS animadas (libass), barra de progresso, logo da
marca + @ da rede e loudnorm (-14 LUFS, duas passadas: a medicao e so de audio e leva ~1 s).

O safezone decide onde cada elemento fica e reenquadra o video por plano para que NADA cubra o
rosto (testa ao queixo). Com edicao.marca_dagua_arroba, sai uma versao por rede (o @ muda) na
MESMA passada do ffmpeg: o quadro composto e dividido e cada copia ganha o seu @.

Chaves (todas opcionais): edicao.cortar_silencios, zooms, seguir_rosto, etiqueta_nome,
etiqueta_estilo, cartao_contexto (antigo, desligado), cta_serie, logo_marca_dagua,
marca_dagua_arroba, depurar_grade, depurar_sem_sobreposicoes.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Callable

from .. import paths
from ..log import get as get_log
from ..models import ClipPlan, RenderedClip, Transcript
from ..util import short_hash
from . import backgrounds, coldopen, faces, fonts, jumpcut, layouts, motion, overlays, safezone, titlecard
from . import captions as captions_mod
from . import ffmpeg as ff
from .ffmpeg import FFmpegError, pick_encoder, probe

__all__ = ["render_clip", "probe", "pick_encoder", "backgrounds", "fonts", "layouts", "titlecard",
           "FFmpegError", "LAST_STATS", "LAST_CAPTIONS"]

_log = get_log(__name__)
W, H = 1080, 1920

# estatisticas do ultimo render (encoder, tempo, velocidade, cortes...) - util para relatorios/benchmarks
LAST_STATS: dict = {}
# legenda do ultimo render ja na linha do tempo da saida (depois dos jump cuts)
LAST_CAPTIONS: Transcript | None = None
# grafo maior que isso vai por arquivo (-/filter_complex, ffmpeg 7+): a linha de comando do Windows tem limite
GRAPH_FILE_MIN = 6000


def _rel_or_copy(target: Path, work: Path) -> str:
    """Caminho relativo (com /) de work ate target - evita escapar 'C:' dentro do filtro."""
    try:
        rel = os.path.relpath(target, work).replace("\\", "/")
        if ":" not in rel and "'" not in rel:
            return rel
    except ValueError:
        pass
    dest = work / target.name
    shutil.copytree(target, dest, dirs_exist_ok=True) if target.is_dir() else shutil.copy2(target, dest)
    return dest.name


def _title_text(plan: ClipPlan | None) -> str:
    if plan is None:
        return ""
    return (plan.hook or "").strip() or (plan.title or "").strip()


def _caption_geo(cfg, lay: str, caps=None, total: float = 0.0, teaser: float = 0.0) -> safezone.CapGeo:
    """Faixa ocupada pela legenda deste corte (linhas e largura medidas nos grupos reais)."""
    g = (lambda k, d: cfg.get(k, d)) if cfg is not None else (lambda k, d: d)
    lay_k = lay if lay in ("split", "blur", "full") else "full"
    size = float(g("edicao.legenda.tamanho", 90) or 90) * captions_mod.SIZE_SCALE * captions_mod.LAYOUT_SIZE[lay_k]
    if str(g("edicao.legenda.estilo", "karaoke")).lower() == "palavra":
        size *= 1.15
    pos = str(g("edicao.legenda.posicao", "centro")).lower()
    pos = pos if pos in ("centro", "baixo") else "centro"
    forced = int(g("edicao.legenda.y", 0) or 0)
    cy = forced or captions_mod.CAPTION_Y[(lay_k, pos)]
    if lay_k == "split" and not forced and pos == "centro":
        cy = min(1420, layouts.split_seam(cfg) + 330)
    outline = max(3.0, round(size * 0.075, 1))
    max_lines = 1 if int(g("edicao.legenda.max_linhas", 2) or 2) <= 1 else 2

    def half_for(n: int) -> float:   # linhas x corpo, com o "pop" de 106% e o contorno
        return n * size / 2 * 1.06 + outline + 4

    lines, width = max_lines, float(captions_mod.MAX_TEXT_W[lay_k])
    modes: dict = {}
    if caps is not None:
        try:
            ext = captions_mod.caption_extent(caps, total, cfg, lay_k, teaser, max_lines=max_lines)
            lines, width = max(1, ext["lines"]), max(200.0, ext["width"])
            if lines > 1:   # alternativa: so 1 linha (par largo vira 2 telas de 1 palavra)
                e1 = captions_mod.caption_extent(caps, total, cfg, lay_k, teaser, max_lines=1)
                modes[1] = (half_for(1), int(round(max(200.0, e1["width"]) / 2)) * 2)
        except Exception as e:  # noqa: BLE001
            _log.debug("medida da legenda falhou: %s", e)
    return safezone.CapGeo(size, half_for(lines), int(round(width / 2)) * 2, int(cy), forced=bool(forced),
                           lines=lines, modes=modes)


def _variant_platforms(cfg) -> list[str]:
    """Redes que ganham versao propria (com o @ delas)."""
    if cfg is None or not cfg.get("edicao.marca_dagua_arroba", True):
        return []
    plats = cfg.get("publicacao.plataformas", ["youtube", "tiktok"]) or []
    out = [str(p) for p in plats if str(p) in ("youtube", "tiktok")]
    ig, tt = (str(cfg.get(f"publicacao.contas.{r}.handle", "") or "").strip().lstrip("@").lower() for r in ("instagram", "tiktok"))
    if "instagram" in plats and ig and ig != tt:     # com o mesmo @ usa a versao do TikTok
        out.append("instagram")
    return out


def _video_info(plan) -> dict | None:
    """Titulo/canal/descricao do video de origem (tabela videos, so leitura) para a etiqueta de nome."""
    sid = getattr(plan, "source_id", None) if plan is not None else None
    if not sid:
        return None
    try:
        from .. import db

        r = db.conn().execute("SELECT title, channel, data FROM videos WHERE id=?", (sid,)).fetchone()
        if r is None:
            return None
        d = json.loads(r["data"] or "{}") if r["data"] else {}
        return {"title": r["title"] or "", "channel": r["channel"] or "", "description": d.get("description", "")}
    except Exception:  # noqa: BLE001
        return None


def render_clip(source: Path, start: float, end: float, plan: ClipPlan | None, captions: Transcript | None,
                cfg, out_path: Path, layout: str | None = None,
                on_progress: Callable[[float], None] | None = None,
                background: tuple[Path, float] | None = None, video=None,
                platforms: list[str] | None = None) -> RenderedClip:
    """Renderiza o corte. start/end na linha do tempo de `source`; captions relativas a `start`.

    Extras opcionais: on_progress(fracao 0..1); background=(arquivo, offset) para forcar o fundo;
    video = Candidate (ou dict title/channel/description) para a etiqueta de nome (sem ele, le a
    tabela videos pelo plan.source_id). Com jump cuts a duracao final e menor que end-start.
    Com @ por rede: RenderedClip.variants = {"youtube": ..., "tiktok": ...} e path = versao do YouTube.
    platforms: None = todas as redes da config; ["tiktok"] (por exemplo) = so a versao dessa rede, e
    path = ela. Sem o YouTube na lista, o teto de corte.duracao_max_s nao corta o trecho pedido
    (versao longa do TikTok, ate ~93 s com o teaser).
    """
    global LAST_CAPTIONS
    t_begin = time.time()
    source, out_path = Path(source), Path(out_path)
    if not source.exists():
        raise FileNotFoundError(f"video de origem nao existe: {source}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    info = probe(source)
    if not info["has_video"]:
        raise FFmpegError(f"sem faixa de video: {source}")
    start = max(0.0, float(start))
    if info["duration"]:
        end = min(float(end), info["duration"])
    dur = round(float(end) - start, 3)
    if dur < 1.0:
        raise ValueError(f"trecho curto demais ({dur:.2f}s)")

    g = (lambda k, d: cfg.get(k, d)) if cfg is not None else (lambda k, d: d)
    serio = str(getattr(plan, "category", "") or "") in ("politica", "noticias")
    if serio:
        info["blur_ar"] = 1.78      # quadro inteiro: a tarja do programa nao pode aparecer cortada
    if layout is None and g("edicao.separar_webcam", True) and not serio:
        from . import react

        comp = None
        try:
            comp = react.compose(source, start, dur, info, cfg, key=str(getattr(plan, "source_id", "") or ""))
        except Exception as e:  # noqa: BLE001
            _log.warning("separar webcam ignorado: %s", e)
        if comp is not None:
            try:
                rc = render_clip(comp, 0.0, dur, plan, captions, cfg, out_path, layout="stack", on_progress=on_progress,
                                 video=video, platforms=platforms)
                rc.layout = "react"
                return rc
            finally:
                comp.unlink(missing_ok=True)
    fps = int(g("edicao.fps", 30) or 30)
    threads = max(1, min(6, int(g("edicao.threads", 6) or 6)))   # teto de 6 para nao saturar a CPU
    timings: dict[str, float] = {}

    # ---------- layout e fundo
    lib = backgrounds.library()
    if not any(lib.values()):
        lib = backgrounds.ensure_library(cfg)
    # auto: decide pela categoria do plano (sem deteccao de rosto), escolha estavel por corte
    stack = layout == "stack"       # video ja montado pelo react.py: tela em cima, webcam embaixo
    lay = "full" if stack else layouts.choose_layout(info, plan, cfg, override=layout, has_backgrounds=any(lib.values()))
    bg = None
    if lay == "split":
        bg = background or backgrounds.pick(cfg, dur)
        if bg is None:
            lay = "blur"

    # ---------- jump cuts (pausas longas e silencio do comeco)
    cut = None
    # reacao/react: o silencio faz parte (a cena passa na tela, a pessoa reage)
    calado = stack or getattr(plan, "tipo", "") == "reacao"
    if g("edicao.cortar_silencios", True) and captions is not None and not calado:
        t0 = time.time()
        try:
            energy = jumpcut.audio_energy(source, start, dur) if info["has_audio"] else None
            cut = jumpcut.plan_cuts(captions, dur, fps, cfg, energy)
            if cut is not None and cut.out_duration < max(1.0, dur * 0.4):
                _log.info("jump cuts descartados: sobraria pouco (%.1fs de %.1fs)", cut.out_duration, dur)
                cut = None
        except Exception as e:  # noqa: BLE001
            _log.warning("jump cuts falharam, seguindo sem: %s", e)
            cut = None
        timings["jump_cuts_s"] = round(time.time() - t0, 2)
    # ---------- cold open (teaser com o momento mais polemico do proprio corte)
    teaser = None
    try:
        teaser = coldopen.plan_teaser(plan, dur, captions, cfg, fps)
    except Exception as e:  # noqa: BLE001
        _log.warning("cold open ignorado: %s", e)
    T = 0.0
    if teaser is not None:
        if cut is None:   # corte inteiro como um pedaco so (duracoes exatas na emenda)
            cut = jumpcut.CutPlan([(0, int(round(dur * fps)))], fps, dur)
        max_total = float(g("corte.duracao_max_s", 58) or 58)
        if platforms is not None and "youtube" not in platforms:
            # so TikTok: quem pediu manda no tamanho (o teto de 58 s existe por causa do Shorts)
            max_total = max(max_total, float(g("corte.duracao_max_tiktok_s", 0) or 0),
                            dur + float(g("edicao.cold_open_max_s", 3.0) or 3.0) + 0.5)
        if teaser.dur + cut.out_duration > max_total:
            teaser.frames = max(min(teaser.frames, int(1.5 * fps)), int((max_total - cut.out_duration) * fps))
            if teaser.dur + cut.out_duration > max_total:
                cut.truncate(int((max_total - teaser.dur) * fps))
        T = teaser.dur
    out_dur = round(cut.out_duration, 3) if cut is not None else dur     # parte normal (sem o teaser)
    caps = jumpcut.retime(captions, cut) if cut is not None else captions
    time_map = cut.map_time if cut is not None else None
    total = round(T + out_dur, 3)

    # ---------- rosto (full / metade de cima do split; no blur so ancora o zoom)
    zoom_on = bool(g("edicao.zooms", False))
    follow = bool(g("edicao.seguir_rosto", True))
    track = None
    # o rosto tambem protege os elementos sobrepostos (nada pode cobri-lo), entao a analise roda
    # sempre que houver detector, mesmo sem seguir rosto
    if (follow or g("edicao.rosto_seguro", True)) and faces.available():
        t0 = time.time()
        try:
            track = faces.analyze(source, start, dur, info, cfg)
        except Exception as e:  # noqa: BLE001
            _log.warning("analise de rosto falhou, recorte central: %s", e)
            track = None
        if stack and track is not None:
            from . import react as _react

            _react.only_bottom_faces(track)
        timings["rosto_s"] = round(time.time() - t0, 2)
    # duas pessoas longe uma da outra: o recorte de tela cheia corta quem fala. Vai para a faixa no meio, com todo mundo
    if track is not None and not stack and layout is None and not layouts.is_vertical(info):
        ar = (info.get("width") or 1920) / max(1, info.get("height") or 1080)
        if lay == "full" and faces.gente_fora(track, (layouts.W / layouts.H) / ar) >= float(g("edicao.gente_fora_max", 0.25)):
            _log.info("enquadramento: mais de uma pessoa em cena, tela cheia virou faixa no meio")
            lay = "blur"
        if lay == "blur" and not info.get("blur_ar") and faces.gente_fora(track, min(1.0, layouts.BLUR_AR / ar)) >= 0.12:
            info["blur_ar"] = 1.78
    cam_cuts = [time_map(s.t0) if time_map else s.t0 for s in (track.shots[1:] if track else [])]
    pieces = None
    if teaser is not None:
        ta, mp_main = teaser.t0, time_map or (lambda t: t)
        pieces = [(ta, ta + T, lambda t, _a=ta: t - _a), (0.0, dur, lambda t, _m=mp_main: _m(t) + T)]

    # ---------- zoom dinamico
    zplan = None
    if zoom_on:
        try:
            zplan = motion.plan_zoom(caps, out_dur, cfg, seed=getattr(plan, "id", "") or str(source),
                                     cut_times=cut.cut_times_out() if cut is not None else [], camera_cuts=cam_cuts)
        except Exception as e:  # noqa: BLE001
            _log.warning("zoom dinamico falhou, seguindo sem: %s", e)
            zplan = None
    if teaser is not None:
        zplan = motion.with_teaser(zplan, T) if zoom_on else None
        caps = coldopen.merge_captions(coldopen.teaser_captions(captions, teaser), caps, T)

    work = paths.TMP / f"ed_{short_hash(f'{out_path}{time.time()}')}"
    work.mkdir(parents=True, exist_ok=True)
    try:
        fonts.ensure_fonts()
        category = getattr(plan, "category", None) if plan is not None else None
        clean = bool(g("edicao.depurar_sem_sobreposicoes", False))   # teste: planeja tudo, nao desenha nada
        debug = bool(g("edicao.depurar_grade", False))

        # ---------- movimento (o mesmo modelo gera o ffmpeg e a previsao do rosto no safezone)
        main_pre = cut.video_filter() if (cut is not None and teaser is None) else ""
        mot = layouts.Motion(pre=main_pre, track=track, time_map=time_map, zoom=zplan, follow_face=follow,
                             info=info, pieces=pieces)
        framing = layouts.stack_framing() if stack else layouts.build_framing(lay, info, cfg, mot)
        splits = [T + x for x in cut.cut_times_out()] if cut is not None else []
        segs = faces.segments(track, total, time_map, pieces, splits=splits) if track is not None else []

        # ---------- titulo: o safezone escolhe tamanho (normal/compacto/mini) e lugar
        title_shown = ""
        make_title = None
        if g("edicao.titulo_no_video", True) and plan is not None:
            title_shown = _title_text(plan)
            if title_shown or plan.part:
                def make_title(size: str):
                    return titlecard.render_title_card(title_shown, work / f"titulo_{size}.png", cfg, plan.part,
                                                       plan.parts_total, category=category, seed=plan.id, size=size)
        tdur_title = float(g("edicao.duracao_titulo_s", 0) or 0)
        title_always = not (0 < tdur_title < total)
        bar_on = (bool(g("edicao.barra_progresso", True)) and title_always
                  and total > float(g("edicao.barra_min_s", 35) or 0))
        bar_h = int(g("edicao.barra_altura", 8) or 8) if bar_on else 0
        cap_geo = _caption_geo(cfg, "split" if stack else lay, caps, total, T)
        if stack:
            from . import react as _react

            cap_geo.default_y, cap_geo.forced = _react.CAPTION_Y, True

        # ---------- etiqueta de nome (lower third: quem fala + onde), ~2,6 s depois do teaser
        tag = None
        tag_dur = float(g("edicao.etiqueta_nome_s", 2.6) or 2.6)
        tag_txt = None
        if g("edicao.etiqueta_nome", True) and plan is not None and total >= tag_dur + 3.0:
            try:
                tag_txt = overlays.name_tag_text(plan, cfg, video if video is not None else _video_info(plan))
                if tag_txt:
                    tag = overlays.render_name_tag(tag_txt[0], tag_txt[1], work / "etiqueta", cfg,
                                                   style=str(g("edicao.etiqueta_estilo", "tarja") or "tarja"),
                                                   fps=fps, dur=tag_dur)
            except Exception as e:  # noqa: BLE001
                _log.warning("etiqueta de nome ignorada: %s", e)
                tag = None
        if tag is None and g("edicao.cartao_contexto", False) and plan is not None and total >= tag_dur + 3.0:
            # cartao antigo (desligado por padrao): mesmo lugar seguro da etiqueta, PNG parado com fade
            ctx_text = overlays.context_text(plan, cfg, title_shown)
            ov = overlays.render_context_card(ctx_text, work / "contexto.png", cfg, category) if ctx_text else None
            if ov is not None:
                tag = overlays.NameTag(ov.path.name, 1, ov.w, ov.h, (ov.pad_top, ov.pad_top, ov.w - ov.pad_top,
                                                                    ov.h - ov.pad_bottom), "contexto")

        # ---------- CTA de serie (ultimos 2 s)
        cta = None
        cta_s = min(float(g("edicao.cta_serie_s", 2.0) or 2.0), max(0.0, total - 6.0))
        if g("edicao.cta_serie", True) and plan is not None and cta_s >= 1.0:
            cta_txt = overlays.cta_text(plan, cfg)
            if cta_txt:
                cta = overlays.render_cta_pill(cta_txt, work / "cta.png", cfg, category,
                                               px=int(g("edicao.cta_tamanho", 44) or 44))

        # ---------- marca (logo + @ de cada rede: uma versao do video por rede)
        plats = _variant_platforms(cfg) if platforms is None else [
            p_ for p_ in dict.fromkeys(str(x).lower() for x in platforms) if p_ in ("youtube", "tiktok", "instagram")]
        if platforms is not None and not plats:
            raise ValueError(f"nenhuma rede valida em platforms={platforms}")
        brands = []
        if g("edicao.marca", True):
            try:
                for sc_, mini_ in ((1.0, False), (0.8, False), (1.0, True)):   # normal, compacta e mini
                    b_ = overlays.render_brand(cfg, work, plats, scale=sc_, mini=mini_)
                    if b_ is not None:
                        brands.append(b_)
            except Exception as e:  # noqa: BLE001
                _log.warning("marca d'agua ignorada: %s", e)

        # ---------- plano da cena: nada cobre o rosto, nada encosta em nada
        t_plan = time.time()
        planner = safezone.Planner(lay="split" if stack else lay, total=total, teaser=T, framing=framing, segs=segs, cfg=cfg,
                                   make_title=make_title, bar_h=bar_h, cap=cap_geo, tag=tag, tag_dur=tag_dur,
                                   cta=cta, cta_s=cta_s, brand=brands, info=info, seam=_react.TITLE_Y if stack else layouts.split_seam(cfg))
        if stack:
            planner.zb_opts = (1.0,)      # o quadro montado nao se mexe
            planner.brand_only = ("base_esq", "cam_esq")      # marca embaixo ou no canto da webcam, fora do filme e do rosto
            planner.title_only = ("emenda",)        # titulo so na faixa dele
        scene = planner.plan()
        timings["plano_s"] = round(time.time() - t_plan, 2)
        lost = ((make_title is not None and scene.title is None) or (bool(brands) and scene.brand is None)
                or scene.overlap > 0)
        if lost and lay != "blur" and layout is None and str(g("edicao.layout", "auto") or "auto") == "auto":
            # o rosto ocupa a tela toda: no fundo desfocado sobra lugar para titulo e marca
            _log.info("layout %s sem espaco para titulo/marca (rosto grande): refazendo em blur", lay)
            return render_clip(source, start, end, plan, captions, cfg, out_path, layout="blur", on_progress=on_progress,
                               video=video, platforms=platforms)
        mot.framing = scene.framing
        card = scene.title
        brand = scene.brand.extra.get("obj") if scene.brand is not None else None
        bar_rect = scene.bar_rect
        if scene.overlap > 0:
            _log.warning("nao deu para livrar o rosto 100%% (%.0f px2): %s", scene.overlap, scene.notes)

        # sem titulo a barra vai para a borda da tela: so desenha se nao encostar em nenhum rosto
        bar_flag = None
        if bar_rect is None and bool(g("edicao.barra_progresso", True)):
            bh_ = int(g("edicao.barra_altura", 8) or 8)
            by_ = H - bh_ if str(g("edicao.barra_posicao", "topo")).lower() == "base" else 0
            edge = safezone.Item("barra", (0, by_, W, by_ + bh_))
            if card is None and not safezone.face_hits(scene.framing, segs, [edge], total) \
                    and total > float(g("edicao.barra_min_s", 35) or 0):
                scene.items.append(edge)
            else:
                bar_flag = False
        ass_path = captions_mod.build_ass(caps, total, cfg, "split" if stack else lay, work / "leg.ass", watermark="",
                                          progress_bar=bar_flag,
                                          caption_y=scene.cap_y, category=category, bar_rect=bar_rect,
                                          teaser_until=T,
                                          teaser_color=coldopen.teaser_color(cfg, category) if T > 0 else None,
                                          max_lines=scene.cap_lines)
        dbg_path = None
        if debug:
            faces_t = []
            tt = 0.0
            while tt < total:
                for r in safezone.face_rects_at(scene.framing, segs, tt):
                    faces_t.append((tt, tt + 0.2, r))
                tt += 0.2
            dbg_path = captions_mod.build_debug_ass(work / "grade.ass", total,
                                                    [(it.name, it.rect, it.t0, it.t1) for it in scene.items], faces_t)

        # ---------- audio
        measured = None
        if info["has_audio"] and g("edicao.normalizar_audio", True):
            measured = ff.measure_loudness(source, start, dur)
        whoosh = None
        if T > 0 and info["has_audio"] and g("edicao.cold_open_whoosh", True):
            whoosh = coldopen.whoosh_wav(work / "whoosh.wav")

        # ---------- comando
        args: list[str] = ["-threads", str(threads), "-ss", f"{start:.3f}", "-t", f"{dur + 0.5:.3f}",
                           "-i", str(source)]
        idx = 1
        bg_idx = title_idx = audio_idx = tag_idx = cta_idx = tz_idx = wh_idx = logo_idx = None
        handle_idx: dict[str, int] = {}
        if teaser is not None:   # o mesmo arquivo de novo, a partir do momento polemico
            args += ["-threads", str(threads), "-ss", f"{start + teaser.t0:.3f}", "-t", f"{T + 0.4:.3f}",
                     "-i", str(source)]
            tz_idx, idx = idx, idx + 1
        if bg is not None:
            bg_path, bg_off = bg
            args += ["-stream_loop", "-1", "-ss", f"{bg_off:.2f}", "-i", str(bg_path)]
            bg_idx, idx = idx, idx + 1
        draw = not clean
        if card is not None and draw:
            args += ["-i", card.path.name]
            title_idx, idx = idx, idx + 1
        if tag is not None and scene.tag is not None and draw:
            if tag.frames > 1:
                args += ["-framerate", str(fps), "-start_number", "0", "-i", tag.pattern]
            else:
                args += ["-loop", "1", "-framerate", str(fps), "-t", f"{tag_dur:.3f}", "-i", tag.pattern]
            tag_idx, idx = idx, idx + 1
        if cta is not None and scene.cta is not None and draw:
            args += ["-loop", "1", "-framerate", str(fps), "-t", f"{cta_s + 0.2:.3f}", "-i", cta.path.name]
            cta_idx, idx = idx, idx + 1
        if brand is not None and scene.brand is not None and draw:
            if brand.logo is not None and "logo" in scene.brand.extra:
                args += ["-i", brand.logo.name]
                logo_idx, idx = idx, idx + 1
            for plat, (pth, _w, _h, _c) in brand.handles.items():
                if plat in scene.brand.extra.get("arroba", {}):
                    args += ["-i", pth.name]
                    handle_idx[plat], idx = idx, idx + 1
        if whoosh is not None:
            args += ["-i", whoosh.name]
            wh_idx, idx = idx, idx + 1
        if not info["has_audio"]:
            args += ["-f", "lavfi", "-t", f"{total + 0.5:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            audio_idx, idx = idx, idx + 1

        graph = []
        main_v = "0:v"
        if teaser is not None:
            graph.append(f"[0:v]fps={fps},{cut.video_filter()}[mv]")
            graph.append(f"[{tz_idx}:v]fps={fps},trim=end_frame={teaser.frames},setpts=PTS-STARTPTS[tv]")
            graph.append("[tv][mv]concat=n=2:v=1:a=0[cm]")
            main_v = "cm"
        graph.append(layouts.video_graph(lay, info, fps, main=main_v, bg=f"{bg_idx}:v" if bg_idx else None,
                                         out="base", cfg=cfg, motion=mot))
        cur = "base"
        if teaser is not None and g("edicao.cold_open_flash", True):
            # flash branco rapido na emenda teaser -> corte (so no video, por baixo de titulo/legenda)
            graph.append(f"[{cur}]eq=brightness='0.62*(1-clip((t-{T:.3f})/0.17,0,1))':eval=frame"
                         f":enable='between(t,{T - 0.001:.3f},{T + 0.18:.3f})'[vf]")
            cur = "vf"
        if title_idx is not None:
            conds = []
            if 0 < tdur_title < total:
                conds.append(f"lt(t,{tdur_title:.2f})")
            for a, b, _who in scene.hide_title:
                conds.append(f"not(between(t,{a:.2f},{b:.2f}))")
            enable = f":enable='{'*'.join(conds)}'" if conds else ""
            graph.append(f"[{cur}][{title_idx}:v]overlay=x={card.x}:y={card.y}:format=auto{enable}[vt]")
            cur = "vt"
        if tag_idx is not None:
            p = scene.tag
            tx, ty = int(p.x - tag.vis[0]), int(p.y - tag.vis[1])
            fades = ""
            if tag.frames <= 1:
                fo = p.t0 + max(0.0, tag_dur - 0.25)
                fades = f",fade=t=in:st={p.t0:.3f}:d=0.2:alpha=1,fade=t=out:st={fo:.3f}:d=0.25:alpha=1"
            graph.append(f"[{tag_idx}:v]format=rgba,setpts=PTS+{p.t0:.3f}/TB{fades}[tgv]")
            graph.append(f"[{cur}][tgv]overlay=x={tx}:y={ty}:format=auto:eof_action=pass"
                         f":enable='between(t,{p.t0:.3f},{p.t0 + tag_dur:.3f})'[vg]")
            cur = "vg"
        if cta_idx is not None:
            p = scene.cta
            t_cta = p.t0
            cx_, cy_ = int(p.x - cta.pad_top), int(p.y - cta.pad_top)
            graph.append(f"[{cta_idx}:v]format=rgba,setpts=PTS+{t_cta:.3f}/TB,"
                         f"fade=t=in:st={t_cta:.3f}:d=0.16:alpha=1[ctav]")
            graph.append(f"[{cur}][ctav]overlay=x={cx_}:y='{cy_}+16*pow(1-clip((t-{t_cta:.3f})/0.2,0,1),3)'"
                         f":format=auto:eof_action=pass:enable='gte(t,{t_cta:.3f})'[vx]")
            cur = "vx"
        fontsdir = _rel_or_copy(paths.FONTS, work)
        if draw:
            graph.append(f"[{cur}]ass={ass_path.name}:fontsdir={fontsdir}[vs]")
            cur = "vs"
        if logo_idx is not None:
            lx, ly = scene.brand.extra["logo"]
            graph.append(f"[{cur}][{logo_idx}:v]overlay=x={lx}:y={ly}:format=auto[vl]")
            cur = "vl"
        if dbg_path is not None:
            graph.append(f"[{cur}]ass={dbg_path.name}[vd]")
            cur = "vd"
        # uma saida por rede (o @ muda): o quadro composto e dividido e cada copia ganha o seu @
        outs: list[tuple[str, str, Path]] = []   # (rede, rotulo do video, arquivo)
        copies: list[tuple[str, Path]] = []      # redes com quadro identico (sem @ desenhado): copia

        def plat_path(plat: str) -> Path:
            return out_path.with_name(f"{out_path.stem}_{plat}.mp4")

        drawn = [p_ for p_ in plats if p_ in handle_idx]
        enc_plats = plats if drawn else plats[:1]
        if plats:
            copies = [(p_, plat_path(p_)) for p_ in plats if p_ not in enc_plats]
            n = len(enc_plats)
            if n > 1:
                graph.append(f"[{cur}]split={n}" + "".join(f"[vp{i}]" for i in range(n)))
            for i, plat in enumerate(enc_plats):
                src_lbl = f"vp{i}" if n > 1 else cur
                if plat in handle_idx:
                    hx, hy = scene.brand.extra["arroba"][plat]
                    graph.append(f"[{src_lbl}][{handle_idx[plat]}:v]overlay=x={hx}:y={hy}:format=auto,"
                                 f"format=yuv420p[vo{i}]")
                else:
                    graph.append(f"[{src_lbl}]format=yuv420p[vo{i}]")
                outs.append((plat, f"vo{i}", plat_path(plat)))
        else:
            graph.append(f"[{cur}]format=yuv420p[vo0]")
            outs.append(("", "vo0", out_path))

        fade = f"afade=t=in:d=0.04,afade=t=out:st={max(0.0, total - 0.08):.3f}:d=0.08"
        a_last = "apre" if wh_idx is not None else "aout"
        if audio_idx is not None:
            graph.append(f"[{audio_idx}:a]aresample=48000,{fade}[aout]")
            a_last = "aout"
        else:
            a_in = "0:a"
            if cut is not None:
                graph.append(cut.audio_filter("0:a", "acut"))
                a_in = "acut"
            if teaser is not None:
                spf = 48000 // fps if 48000 % fps == 0 else 0
                trim = (f"atrim=end_sample={teaser.frames * spf}" if spf else f"atrim=end={T:.6f}")
                graph.append(f"[{tz_idx}:a]aresample=48000,{trim},asetpts=PTS-STARTPTS,"
                             f"afade=t=out:st={max(0.0, T - 0.008):.4f}:d=0.008[ta]")
                graph.append(f"[ta][{a_in}]concat=n=2:v=0:a=1[acomb]")
                a_in = "acomb"
            norm = (ff.loudnorm_filter(measured) + ",") if g("edicao.normalizar_audio", True) else ""
            graph.append(f"[{a_in}]aresample=48000,{norm}aresample=48000,"
                         f"aformat=sample_fmts=fltp:channel_layouts=stereo,{fade}[{a_last}]")
        if wh_idx is not None and a_last == "apre":
            # whoosh com o pico na emenda (~12 dB abaixo da voz)
            dl = int(max(0.0, T - 0.18) * 1000)
            graph.append(f"[{wh_idx}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                         f"adelay={dl}|{dl}[wh]")
            graph.append("[apre][wh]amix=inputs=2:duration=first:normalize=0[aout]")
        a_labels = ["aout"]
        if len(outs) > 1:
            graph.append(f"[aout]asplit={len(outs)}" + "".join(f"[ao{i}]" for i in range(len(outs))))
            a_labels = [f"ao{i}" for i in range(len(outs))]

        encoder = pick_encoder(cfg)
        tmp_outs = [o[2].with_name(o[2].stem + ".part.mp4") for o in outs]
        graph_txt = ";\n".join(graph)
        fc: list[str]
        if len(graph_txt) > GRAPH_FILE_MIN:   # grafo grande (muitas chaves de zoom/corte): vai por arquivo
            (work / "grafo.txt").write_text(graph_txt, encoding="utf-8")
            fc = ["-/filter_complex", "grafo.txt"]
        else:
            fc = ["-filter_complex", graph_txt.replace("\n", "")]

        def build(enc: str) -> list[str]:
            # cada encoder recebe a sua parte do teto de threads (2 saidas = metade cada)
            per = max(1, threads // len(outs))
            cmd = [*args, *fc, "-filter_complex_threads", str(threads)]
            for (plat, vlab, _final), alab, tmp in zip(outs, a_labels if len(a_labels) == len(outs)
                                                       else a_labels * len(outs), tmp_outs):
                cmd += ["-map", f"[{vlab}]", "-map", f"[{alab}]", "-t", f"{total:.3f}", "-r", str(fps),
                        *ff.video_encoder_args(enc, cfg, fps, threads=per), *ff.audio_args(cfg),
                        "-map_metadata", "-1", "-map_chapters", "-1", "-movflags", "+faststart", str(tmp)]
            return cmd

        t_enc = time.time()
        try:
            ff.run(build(encoder), duration=total, on_progress=on_progress, cwd=work, timeout=max(900, dur * 15 * len(outs)))
        except FFmpegError as e:
            if encoder != "h264_amf":
                raise
            _log.warning("h264_amf falhou, refazendo com libx264: %s", str(e)[-300:])
            ff.mark_amf_broken(str(e))
            encoder = "libx264"
            t_enc = time.time()
            ff.run(build(encoder), duration=total, on_progress=on_progress, cwd=work, timeout=max(900, dur * 15 * len(outs)))
        enc_secs = time.time() - t_enc

        # ---------- validacao
        finals: dict[str, str] = {}
        oi = None
        for (plat, _vlab, final), tmp in zip(outs, tmp_outs):
            oi = probe(tmp)
            problems = []
            if (oi["width"], oi["height"]) != (W, H):
                problems.append(f"resolucao {oi['width']}x{oi['height']}")
            if abs(oi["duration"] - total) > 0.3:
                problems.append(f"duracao {oi['duration']:.2f}s (esperado {total:.2f}s)")
            if not oi["has_audio"]:
                problems.append("sem audio")
            if problems:
                for t_ in tmp_outs:
                    t_.unlink(missing_ok=True)
                raise FFmpegError("render invalido: " + ", ".join(problems))
            tmp.replace(final)
            finals[plat] = str(final)
        for plat, final in copies:   # mesma imagem (sem @ para desenhar): so copia o arquivo
            shutil.copy2(next(iter(finals.values())), final)
            finals[plat] = str(final)
        variants = {k: v for k, v in finals.items() if k}
        main_path = Path(variants.get("youtube") or next(iter(finals.values())))

        thumb = out_path.with_suffix(".jpg")
        try:
            ff.extract_frame(main_path, min(1.0, total / 2), thumb)
        except FFmpegError:
            thumb = None

        LAST_CAPTIONS = caps
        LAST_STATS.clear()
        fo_check = safezone.face_overlap(scene.framing, segs, scene.items, total)
        LAST_STATS.update({
            "encoder": encoder, "layout": lay, "duracao": round(oi["duration"], 2),
            "duracao_trecho": round(dur, 2),
            "segundos_total": round(time.time() - t_begin, 2), "segundos_ffmpeg": round(enc_secs, 2),
            "velocidade": round(oi["duration"] / max(0.01, enc_secs), 2),
            "tamanho_mb": round(main_path.stat().st_size / 1024 / 1024, 1),
            "loudnorm": "2 passadas" if measured else ("1 passada" if info["has_audio"] else "silencio"),
            "jump_cuts": cut.n_cuts if cut is not None else 0,
            "silencio_removido_s": round(cut.removed_s, 2) if cut is not None else 0.0,
            "zooms": zplan.changes if zplan is not None else 0,
            "enfases": [e.word for e in zplan.emphasis] if zplan is not None else [],
            "rosto": (f"{sum(1 for s in track.shots if s.cx is not None)}/{len(track.shots)} planos"
                      if track is not None else "desligado"),
            "etiqueta": (f"{tag_txt[0]} / {tag_txt[1]}" if (tag_txt and scene.tag) else bool(scene.tag)),
            "cta_serie": bool(scene.cta), "cold_open_s": round(T, 2),
            "cena": {"titulo": f"{card.size}/{scene.title_slot}" if card is not None else None,
                     "legenda_y": scene.cap_y, "legenda_linhas": scene.cap_lines,
                     "blur_centro": scene.blur_center,
                     "marca": (f"{scene.brand.slot}/{scene.brand.extra.get('arranjo')}/{brand.size}"
                               if (scene.brand and brand is not None) else None),
                     "etiqueta": (f"{scene.tag.slot}@{scene.tag.t0:.2f}s" if scene.tag else None),
                     "cta": scene.cta.slot if scene.cta else None,
                     "reenquadramento": scene.zooms, "custo": round(scene.cost, 2), "notas": scene.notes},
            "rosto_sobreposicao_px": fo_check["max_px"], "rosto_pior": fo_check,
            "sobreposicoes": [(it.name, tuple(round(v) for v in it.rect), round(it.t0, 2),
                               None if it.t1 >= 1e8 else round(it.t1, 2)) for it in scene.items],
            "variantes": variants, "saidas": len(outs), "redes": list(plats),
            **timings,
        })
        # rostos por trecho (para o teste independente e a camada de depuracao)
        LAST_STATS["_segs"] = segs
        LAST_STATS["_framing"] = scene.framing
        _log.info("Render ok %s [%s, %s] %.1fs em %.1fs (%d saida(s), cortes %d, zooms %d)", main_path.name, lay,
                  encoder, oi["duration"], enc_secs, len(outs), LAST_STATS["jump_cuts"], LAST_STATS["zooms"])
        return RenderedClip(
            plan=plan, path=str(main_path), duration=round(oi["duration"], 2), layout=lay,
            thumbnail=str(thumb) if thumb else None,
            background=str(bg[0]) if bg is not None else None,
            variants=variants,
        )
    finally:
        if not g("edicao.manter_temporarios", False):
            shutil.rmtree(work, ignore_errors=True)
