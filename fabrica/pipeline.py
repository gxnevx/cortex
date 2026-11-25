"""Esteira principal da fabrica.

descobrir assuntos -> achar videos -> transcrever -> IA escolhe os cortes -> baixa so os trechos
-> legenda palavra a palavra -> edita (9:16) -> publica (ou fila de revisao) -> relatorio
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import db, log, notify, paths, report, storage
from .config import Config
from .models import Candidate, ClipPlan, RenderedClip, Segment, Transcript, Trend
from .ui import Reporter
from .util import fmt_duration, run_cmd, run_id_now, slugify

_log = log.get("pipeline")


@dataclass
class RunOptions:
    trigger: str = "manual"                 # manual | agendado
    search_mode: str | None = None          # trends | palavra_chave | misto | link (None = config)
    keywords: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    n_videos: int | None = None
    publish_mode: str | None = None         # auto | revisar | nao_publicar (None = config)
    interactive: bool = True
    dry_run: bool = False                   # publica em modo teste (preenche tudo, nao clica em publicar)
    brain: str | None = None                # forca o motor (claude | ollama | heuristico)
    notify: bool = True                     # notificacao do Windows ao terminar
    max_clips: int | None = None            # teto de cortes desta rodada (None = config)
    candidates: list = field(default_factory=list)  # candidatos prontos (via rapida do vigia); pula a descoberta


# =================================================================== trava
LOCK = paths.STATE / "rodada.lock"


def _pid_alive(pid: int) -> bool:
    """Checa se um processo existe (sem usar os.kill, que no Windows MATA o processo)."""
    try:
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    except Exception:
        return False


class RunLock:
    def __enter__(self):
        paths.STATE.mkdir(parents=True, exist_ok=True)
        if LOCK.exists():
            try:
                data = json.loads(LOCK.read_text(encoding="utf-8"))
                age_h = (time.time() - data.get("ts", 0)) / 3600
                from . import andamento

                if andamento.alive(data) and age_h < 6:
                    raise RuntimeError(
                        f"Ja existe uma rodada em andamento (iniciada {datetime.fromtimestamp(data['ts']):%H:%M}). "
                        "Espere ela terminar."
                    )
            except (ValueError, KeyError):
                pass
        from . import andamento

        LOCK.write_text(json.dumps({**andamento.me(), "ts": time.time()}), encoding="utf-8")
        return self

    def __exit__(self, *exc):
        from . import andamento

        andamento.end()
        try:
            LOCK.unlink()
        except OSError:
            pass


# ============================================================ util interno
def _platform_of(info: dict) -> str:
    key = (info.get("extractor_key") or info.get("extractor") or "").lower()
    for p in ("youtube", "twitch", "kick", "rumble", "tiktok", "instagram", "twitter"):
        if p in key:
            return p
    return "outro"


def candidate_from_url(url: str, cfg: Config) -> Candidate:
    """Cria um Candidate a partir de um link colado pelo usuario."""
    from . import download

    info = download.fetch_info(url, cfg)
    platform = _platform_of(info)
    subs = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    has_subs = any(k.startswith("pt") for k in list(subs) + list(auto))
    return Candidate(
        id=f"{platform}:{info.get('id')}",
        platform=platform,
        url=info.get("webpage_url") or url,
        title=info.get("title") or url,
        channel=info.get("uploader") or info.get("channel") or "",
        channel_url=info.get("channel_url") or info.get("uploader_url"),
        duration=info.get("duration"),
        views=info.get("view_count"),
        likes=info.get("like_count"),
        comments=info.get("comment_count"),
        upload_ts=info.get("timestamp") or info.get("release_timestamp"),
        is_live=bool(info.get("is_live")),
        was_live=bool(info.get("was_live")),
        thumbnail=info.get("thumbnail"),
        description=(info.get("description") or "")[:3000],
        topic=None,
        score=100.0,
        reasons=["link escolhido por voce"],
        has_subtitles=has_subs,
        extra={"heatmap": info.get("heatmap") or [], "chapters": info.get("chapters") or []},
    )


def _rms_per_second(media: Path) -> list[float]:
    """Volume (RMS em dB) por segundo - usado para achar momentos quentes em lives longas."""
    from . import tools

    ff = tools.ffmpeg()
    if not ff:
        return []
    r = run_cmd([ff, "-hide_banner", "-nostats", "-i", str(media), "-vn", "-ac", "1", "-af",
                 "aresample=8000,asetnsamples=n=8000:p=0,astats=metadata=1:reset=1,"
                 "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-", "-f", "null", "-"],
                timeout=1800)
    vals = []
    for line in (r.stdout or "").splitlines():
        if "RMS_level=" in line:
            try:
                v = float(line.split("=", 1)[1])
                vals.append(v if v > -200 else -90.0)
            except ValueError:
                vals.append(-90.0)
    return vals


def _hot_windows(c: Candidate, audio: Path, cfg: Config, n: int, win: float) -> list[tuple[float, float]]:
    """Escolhe janelas para transcrever em videos longos sem legenda (heatmap, clipes, picos de volume)."""
    dur = float(c.duration or 0)
    anchors: list[tuple[float, float]] = []  # (tempo, peso)
    # sinais externos: heatmap do YouTube, clipes da Twitch/Kick, minutos citados nos comentarios, picos de chat
    try:
        from . import signals

        anchors.extend((float(t), float(w)) for t, w in signals.signal_anchors(c))
    except Exception as e:
        _log.debug("signal_anchors: %s", e)
    # tenta usar o modulo de sinais (picos de audio) se existir
    try:
        from . import signals  # noqa: F401

        fn = getattr(signals, "loudness_peaks", None)
        if fn:
            for t, w in fn(audio, top=n * 3):
                anchors.append((float(t), float(w)))
    except Exception:
        pass
    if len(anchors) < n:
        rms = _rms_per_second(audio)
        if rms:
            # janela movel de 20 s; pega os maiores picos separados
            k = 20
            sums = []
            acc = sum(rms[:k])
            for i in range(len(rms) - k):
                sums.append((acc / k, i + k / 2))
                acc += rms[i + k] - rms[i]
            sums.sort(reverse=True)
            for val, t in sums[: n * 5]:
                anchors.append((t, 1.0 + (val + 60) / 60))
    if not anchors and dur:
        step = dur / (n + 1)
        anchors = [(step * (i + 1), 1.0) for i in range(n)]
    anchors.sort(key=lambda a: -a[1])
    chosen: list[tuple[float, float]] = []
    for t, _w in anchors:
        s = max(0.0, t - win / 2)
        e = min(dur or t + win / 2, s + win)
        if all(e <= cs or s >= ce for cs, ce in chosen):
            chosen.append((s, e))
        if len(chosen) >= n:
            break
    return sorted(chosen)


def get_transcript(c: Candidate, cfg: Config, workdir: Path, rep: Reporter) -> tuple[Transcript, Path | None]:
    """Legenda da plataforma (rapido) ou Whisper. Devolve (transcricao, audio baixado ou None).

    Se o candidato vier com extra["janela"] = [inicio, fim] (via rapida: momento que esta explodindo),
    so aquela janela e transcrita; os tempos continuam na linha do tempo do video original.
    """
    from . import download, transcribe

    janela = (c.extra or {}).get("janela")
    if janela and len(janela) == 2 and janela[1] > janela[0]:
        ws, we = float(janela[0]), float(janela[1])
    else:
        ws = we = None

    if cfg.get("transcricao.usar_legendas_da_plataforma", True) and c.has_subtitles:
        try:
            with rep.working("Baixando legendas da plataforma..."):
                sub = download.download_platform_subtitles(c, cfg, workdir)
            if sub:
                t = transcribe.parse_subtitles(sub)
                if ws is not None:
                    t = t.slice(ws, we, rebase=False)
                if t.segments:
                    rep.dim(f"legenda da plataforma: {len(t.segments)} trechos")
                    return t, None
        except Exception as e:
            rep.dim(f"legenda indisponivel ({e}); usando Whisper")

    if ws is not None:
        with rep.working(f"Baixando so o momento quente ({fmt_duration(ws)} a {fmt_duration(we)})..."):
            audio = download.download_audio(c, cfg, workdir, start=ws, end=we)
        with rep.working("Transcrevendo o momento quente..."):
            part = transcribe.transcribe(audio, cfg, language=_lang_param(c))
        for sg in part.segments:  # volta para a linha do tempo do video original
            sg.start += ws
            sg.end += ws
            for w in sg.words:
                w.start += ws
                w.end += ws
        return Transcript(part.segments, part.language, "whisper_janela"), None

    with rep.working("Baixando audio para transcrever..."):
        audio = download.download_audio(c, cfg, workdir)
    dur = float(c.duration or 0)
    full_limit = float(cfg.get("transcricao.max_minutos_completo", 25)) * 60
    if dur and dur > full_limit:
        n = int(cfg.get("transcricao.janelas_video_longo", 8))
        win = float(cfg.get("transcricao.tamanho_janela_s", 240))
        windows = _hot_windows(c, audio, cfg, n, win)
        rep.dim(f"video longo ({fmt_duration(dur)}): transcrevendo {len(windows)} momentos quentes")
        segs: list[Segment] = []
        langs: list[str] = []
        for i, (s, e) in enumerate(windows, 1):
            with rep.working(f"Transcrevendo momento {i}/{len(windows)} ({fmt_duration(s)})..."):
                part = transcribe.transcribe(audio, cfg, start=s, end=e, language=_lang_param(c))
                langs.append(part.language or "pt")
            for sg in part.segments:
                sg.start += s
                sg.end += s
                for w in sg.words:
                    w.start += s
                    w.end += s
                segs.append(sg)
        lang = max(set(langs), key=langs.count) if langs else "pt"
        return Transcript(segs, lang, "whisper_parcial"), audio
    with rep.working(f"Transcrevendo {fmt_duration(dur)} de audio com Whisper..."):
        t = transcribe.transcribe(audio, cfg, language=_lang_param(c))
    return t, audio


def _group_plans(plans: list[ClipPlan], pad: float, dur: float | None) -> list[tuple[float, float, list[ClipPlan]]]:
    """Junta cortes proximos/contiguos (ex.: Parte 1, 2, 3) num mesmo trecho de download."""
    groups: list[tuple[float, float, list[ClipPlan]]] = []
    def eff(p: ClipPlan) -> tuple[float, float]:
        return (p.ext_start if p.ext_start is not None else p.start,
                p.ext_end if p.ext_end is not None else p.end)

    for p in sorted(plans, key=lambda p: eff(p)[0]):
        s = max(0.0, eff(p)[0] - pad)
        e = eff(p)[1] + pad
        if dur:
            e = min(e, float(dur))
        if groups and s <= groups[-1][1] + 5:
            gs, ge, gp = groups[-1]
            groups[-1] = (gs, max(ge, e), gp + [p])
        else:
            groups.append((s, e, [p]))
    return groups


# ============================================= gancho de abertura e frase polemica
# Pesos de "polemica" por palavra (minusculas, sem acento). Palavrao e acusacao valem mais.
_POLEMIC = {
    "porra": 5, "caralho": 5, "merda": 4, "foda": 4, "fodase": 5, "fdp": 5, "puta": 4, "cacete": 3, "bosta": 3,
    "desgraca": 4, "desgracado": 5, "vagabundo": 5, "vagabunda": 5, "otario": 4, "idiota": 4, "burro": 3,
    "babaca": 4, "safado": 4, "ladrao": 5, "mentiroso": 5, "mentirosa": 5, "mentira": 4, "canalha": 5,
    "vergonha": 3, "absurdo": 3, "ridiculo": 3, "nojo": 3, "lixo": 3, "covarde": 4, "palhaco": 4,
    "cala": 3, "boca": 1, "nunca": 1.5, "jamais": 2, "odeio": 3, "chorar": 3, "chorando": 3, "chorei": 3,
    "morri": 2, "socorro": 2, "kkkk": 2, "kkkkk": 2, "kkkkkk": 2, "verdade": 1, "prova": 1.5, "roubou": 4,
    "roubo": 4, "traiu": 4, "traicao": 4, "processo": 2, "cadeia": 3, "preso": 3, "matar": 3, "briga": 2,
    "absurda": 3, "sacanagem": 4, "palhacada": 4, "vergonhoso": 4, "hipocrita": 4, "hipocrisia": 4,
    # ingles (videos estrangeiros)
    "fuck": 5, "fucking": 5, "fucked": 5, "shit": 4, "bitch": 5, "asshole": 5, "bullshit": 5, "damn": 2,
    "liar": 5, "lying": 4, "lie": 3, "stupid": 3, "idiot": 4, "insane": 3, "crazy": 2, "wtf": 4, "hell": 2,
    "shut": 3, "never": 1.5, "hate": 3, "crying": 3, "cried": 3, "scam": 4, "fraud": 4, "fired": 3, "kill": 3,
}
_PROFANITY = {"porra", "caralho", "merda", "foda", "fodase", "fdp", "puta", "cacete", "bosta", "desgraca",
              "desgracado", "buceta", "cu", "viado", "arrombado", "piranha",
              "fuck", "fucking", "fucked", "shit", "bitch", "asshole", "bullshit"}


def _norm_word(w: str) -> str:
    import unicodedata

    w = unicodedata.normalize("NFKD", w.lower()).encode("ascii", "ignore").decode()
    return _re.sub(r"[^a-z0-9]", "", w)


def mask_profanity(text: str, mode: str = "mascarar") -> str:
    """'mascarar': p*rra, c*ralho | 'mostrar': sem mudar | 'remover': tira o palavrao."""
    try:
        from .brain import base as _b

        if hasattr(_b, "mask_profanity"):
            return _b.mask_profanity(text, mode)
    except Exception:
        pass
    if mode == "mostrar":
        return text

    def repl(m):
        w = m.group(0)
        if _norm_word(w) not in _PROFANITY:
            return w
        if mode == "remover":
            return ""
        for i, ch in enumerate(w[1:], 1):  # troca a primeira vogal depois da 1a letra por *
            if ch.lower() in "aeiouáéíóúâêôãõ":
                return w[:i] + "*" + w[i + 1:]
        return w[0] + "*" * (len(w) - 1)

    out = _re.sub(r"[\wÀ-ÿ]+", repl, text)
    return _re.sub(r" {2,}", " ", out).strip()


def polemic_spans(words, cfg: Config, min_s: float = 1.5, max_s: float = 3.0) -> list[dict]:
    """Trechos curtos (frase inteira) mais polemicos. Usa a versao do cerebro se existir."""
    try:
        from .brain import base as _b

        if hasattr(_b, "polemic_spans"):
            return _b.polemic_spans(words, cfg, min_s=min_s, max_s=max_s)
    except Exception:
        pass
    out = []
    n = len(words)
    weak_start = {"e", "que", "um", "uma", "o", "a", "os", "as", "de", "do", "da", "isso", "mas", "pra", "com", "sou"}
    for i in range(n):
        # comeco natural: depois de pausa ou pontuacao; evita comecar em palavra de ligacao
        prev = words[i - 1] if i > 0 else None
        natural = prev is None or (words[i].start - prev.end) >= 0.3 or _re.search(r"[.!?,]$", prev.text.strip())
        score = (2.0 if natural else -1.0) - (0.8 if _norm_word(words[i].text) in weak_start else 0.0)
        for j in range(i, n):
            dur = words[j].end - words[i].start
            if dur > max_s:
                break
            tok = words[j].text
            score += _POLEMIC.get(_norm_word(tok), 0.0)
            if "!" in tok or "?" in tok:
                score += 0.7
            letters = _re.sub(r"[^A-Za-zÀ-ÿ]", "", tok)
            if len(letters) >= 3 and letters.isupper():
                score += 0.5
            if dur >= min_s and score > 1.0:
                # prefere terminar em fim de frase
                end_bonus = 1.5 if _re.search(r"[.!?]$", tok) else 0.0
                text = " ".join(w.text.strip() for w in words[i:j + 1])
                out.append({"start": words[i].start, "end": words[j].end, "text": text, "score": score + end_bonus})
    out.sort(key=lambda s: -s["score"])
    return out


def _ab_bucket(key: str, test: str) -> float:
    """Numero fixo entre 0 e 1 por corte e por teste (o mesmo corte cai sempre no mesmo grupo)."""
    import hashlib

    h = hashlib.sha1(f"{test}|{key}".encode("utf-8", "ignore")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def _render(src: Path, ls: float, le: float, p: ClipPlan, captions: Transcript, cfg: Config, out: Path,
            platforms: list[str] | None = None) -> RenderedClip:
    """render_clip com as versoes por rede (logo + @), se o editor suportar."""
    from . import editor
    import inspect

    kw = {}
    if platforms and "platforms" in inspect.signature(editor.render_clip).parameters:
        kw["platforms"] = platforms
    from . import memoria

    memoria.prepare("render", cfg)
    return editor.render_clip(src, ls, le, p, captions, cfg, out, **kw)


def _add_long_version(rc: RenderedClip, src: Path, s_abs: float, e_abs: float, gs: float, p: ClipPlan,
                      full: Transcript, captions: Transcript, cfg: Config, out: Path, rep: Reporter) -> RenderedClip:
    """Renderiza a versao estendida do TikTok e junta nas versoes do corte."""
    import copy

    p_long = copy.copy(p)
    p_long.start, p_long.end = s_abs, e_abs
    out_tt = out.with_name(out.stem + "_longo.mp4")
    if "youtube" not in (rc.variants or {}):
        rc.variants = {**(rc.variants or {}), "youtube": rc.path}
    try:
        with rep.working(f"Editando a versao longa do TikTok ({fmt_duration(e_abs - s_abs)})..."):
            rc_tt = _render(src, s_abs - gs, e_abs - gs, p_long, full, cfg, out_tt, platforms=["tiktok"])
        rc.variants["tiktok"] = (rc_tt.variants or {}).get("tiktok") or rc_tt.path
    except Exception as e:
        _log.warning("versao longa falhou (%s); TikTok recebe a curta", e)
        try:  # curta com o @ do TikTok
            rc_s = _render(src, p.start - gs, p.end - gs, p, captions, cfg, out.with_name(out.stem + "_tt.mp4"),
                           platforms=["tiktok"])
            rc.variants["tiktok"] = (rc_s.variants or {}).get("tiktok") or rc_s.path
        except Exception as e2:
            _log.warning("versao curta do TikTok falhou: %s", e2)
    return rc


def plan_extension(p: ClipPlan, transcript: Transcript, video_dur: float | None, cfg: Config) -> tuple | None:
    """Versao estendida do TikTok (61-90 s) em volta do corte: mais contexto antes e o desfecho depois.

    So quando o momento sustenta: bordas em inicio/fim de frase e fala continua no trecho extra.
    """
    if not cfg.get("publicacao.tiktok_longo.ativo", True):
        return None
    if "tiktok" not in (cfg.get("publicacao.plataformas", []) or []) or p.part:
        return None  # series (Parte X) ficam curtas: as partes sao contiguas
    min_s = float(cfg.get("publicacao.tiktok_longo.min_s", 61))
    max_s = float(cfg.get("publicacao.tiktok_longo.max_s", 90))
    dur = p.end - p.start
    if dur >= min_s:
        return (p.start, p.end) if dur <= max_s else None
    segs = [s for s in transcript.segments if s.text.strip()]
    if not segs:
        return None
    target = min_s + 1 + (min(max_s, 75.0) - min_s - 1) * _ab_bucket(p.id, "longo_dur")
    extra = target - dur
    want_s = max(0.0, p.start - extra * 0.4)       # 40% de contexto antes
    want_e = p.end + extra * 0.6                   # 60% de desfecho depois
    vmax = float(video_dur) if video_dur else max(sg.end for sg in segs)
    want_e = min(want_e, vmax)
    starts = sorted({sg.start for sg in segs if sg.start <= p.start + 0.01})
    ends = sorted({sg.end for sg in segs if sg.end >= p.end - 0.01})
    if not starts or not ends:
        return None
    s2 = min(starts, key=lambda x: abs(x - want_s))
    e2 = min(ends, key=lambda x: abs(x - want_e))
    # ajusta para caber em [min_s, max_s] andando de frase em frase
    while e2 - s2 < min_s:
        nxt_e = [x for x in ends if x > e2]
        prv_s = [x for x in starts if x < s2]
        if nxt_e and (not prv_s or (nxt_e[0] - e2) <= (s2 - prv_s[-1])):
            e2 = nxt_e[0]
        elif prv_s:
            s2 = prv_s[-1]
        else:
            return None
    while e2 - s2 > max_s:
        prev_e = [x for x in ends if x < e2]
        if not prev_e or prev_e[-1] - s2 < min_s:
            return None
        e2 = prev_e[-1]
    # fala continua no trecho extra (sem buraco de mais de 4 s e com ritmo de conversa)
    span = sorted([sg for sg in segs if sg.end > s2 and sg.start < e2], key=lambda sg: sg.start)
    last = s2
    for sg in span:
        if sg.start - last > 4.0:
            return None
        last = max(last, sg.end)
    if e2 - last > 4.0:
        return None
    extra_words = sum(len(sg.text.split()) for sg in span if sg.end <= p.start or sg.start >= p.end)
    extra_secs = max(1.0, (p.start - s2) + (e2 - p.end))
    if extra_words / extra_secs < 1.0:
        return None
    return round(s2, 2), round(e2, 2)


def _lang_param(c: Candidate) -> str | None:
    """Idioma para o Whisper: o que a descoberta informou, ou None (o Whisper detecta sozinho)."""
    lang = str((c.extra or {}).get("idioma") or "").lower()[:2]
    return lang or None


def _lang_of(c: Candidate) -> str:
    """Idioma do video-fonte ('pt' quando nao se sabe)."""
    lang = str((c.extra or {}).get("idioma") or "pt").lower()
    return lang[:2] or "pt"


_TRANSCRIBE_PARAMS: set | None = None


def _transcribe_clip(media: Path, cfg: Config, ls: float, le: float, c: Candidate, p: ClipPlan) -> Transcript:
    """Legenda do corte com o melhor modelo e um 'prompt' com nomes/termos do video (ajuda o Whisper)."""
    global _TRANSCRIBE_PARAMS
    import inspect

    from . import transcribe

    if _TRANSCRIBE_PARAMS is None:
        _TRANSCRIBE_PARAMS = set(inspect.signature(transcribe.transcribe).parameters)
    kw: dict = {"start": ls, "end": le, "language": (p.idioma_origem or _lang_of(c))}
    if "purpose" in _TRANSCRIBE_PARAMS:
        kw["purpose"] = "legenda"  # modelo turbo + prompt + VAD sensivel (erro 16% -> 11%)
    if "prompt" in _TRANSCRIBE_PARAMS:
        build = getattr(transcribe, "build_prompt", None)
        kw["prompt"] = (build(c.title, c.channel, c.description) if build
                        else ", ".join(x for x in [c.title, c.channel] if x)[:220])
    model = cfg.get("transcricao.modelo_legenda")
    if model and "model_name" in _TRANSCRIBE_PARAMS:
        kw["model_name"] = model
    return transcribe.transcribe(media, cfg, **kw)


def _translate_text(text: str, cfg: Config) -> str:
    """Traduz uma frase curta para PT-BR (modulo de traducao). Vazio se nao der."""
    try:
        from . import translate

        return (translate.translate_text(text, cfg, target="pt") or "").strip()
    except Exception as e:
        _log.debug("traducao da frase falhou: %s", e)
        return ""


def to_portuguese_captions(p: ClipPlan, captions: Transcript, cfg: Config, context: str = "") -> Transcript:
    """Legenda em PT-BR para corte estrangeiro. Levanta erro se nao conseguir (o corte e pulado)."""
    try:
        from . import translate
    except ImportError as e:
        raise RuntimeError("traducao indisponivel nesta versao") from e
    pt = translate.to_portuguese(captions, cfg, context=context)
    if not pt or not pt.segments:
        raise RuntimeError("nao consegui traduzir a legenda (precisa do Claude ou do Ollama)")
    return pt


_SENT_END = (".", "?", "!", "…")


def snap_sentences(p: ClipPlan, wide: Transcript, wa: float, s_abs: float, e_abs: float, tem_longa: bool,
                   cfg: Config) -> tuple[float, float]:
    """Encosta o corte no comeco e no fim de frases (pontuacao do Whisper). Ajusta p.start/p.end (e a versao longa)
    e devolve a faixa nova. `wide` = legenda com folga, tempos relativos a `wa`. Partes do meio de uma serie nao mexem."""
    words = wide.words()
    if len(words) < 8:
        return s_abs, e_abs
    starts = [words[0].start] + [b.start for a, b in zip(words, words[1:]) if a.text.strip().endswith(_SENT_END)]
    ends = [w.end for w in words if w.text.strip().endswith(_SENT_END)]
    maxd = float(cfg.get("corte.duracao_max_s", 58))

    def near(opts: list[float], t: float, back: float, fwd: float) -> float | None:
        ok = [x for x in opts if t - back <= x <= t + fwd]
        return min(ok, key=lambda x: abs(x - t)) if ok else None

    def fit(a: float, b: float, limit: float) -> tuple[float, float]:
        ra, rb = a - wa, b - wa
        na = near(starts, ra, 5.0, 2.5) if not p.part or p.part == 1 else None
        nb = near(ends, rb, 2.5, 5.0) if not p.part or p.part == (p.parts_total or 0) else None
        na = max(0.0, na - 0.12) if na is not None else ra
        nb = nb + 0.25 if nb is not None else rb
        if nb - na > limit:         # passou do teto: fica com o fim de frase anterior (sem perder o desfecho)
            prev = [x for x in ends if na + 0.8 * (rb - ra) < x <= na + limit - 0.25]
            nb = prev[-1] + 0.25 if prev else min(rb, na + limit)
        return (na + wa, nb + wa) if nb - na >= 0.8 * (b - a) else (a, b)

    if tem_longa:
        p.start, p.end = (round(x, 3) for x in fit(p.start, p.end, maxd))
        a, b = fit(s_abs, e_abs, float(cfg.get("publicacao.tiktok_longo.max_s", 90)))
        a, b = min(a, p.start), max(b, p.end)
        p.ext_start, p.ext_end = round(a, 3), round(b, 3)
        return p.ext_start, p.ext_end
    p.start, p.end = (round(x, 3) for x in fit(p.start, p.end, maxd))
    return p.start, p.end


def whole_sentence(words: list, a: float, b: float, max_chars: int = 62) -> str:
    """A frase COMPLETA mais forte que encosta em [a, b] (3 a 11 palavras). Vazio = nao ha frase boa para citar."""
    sents, cur = [], []
    for w in words:
        cur.append(w)
        if w.text.strip().endswith(_SENT_END):
            sents.append(cur)
            cur = []
    best, best_v = "", -1.0
    for st in sents:
        if st[-1].end < a - 0.2 or st[0].start > b + 0.2:
            continue
        txt = _re.sub(r"\s+", " ", " ".join(w.text.strip() for w in st)).strip(" ,.;:-\"")
        n = len(txt.split())
        if not 3 <= n <= 11 or len(txt) > max_chars:
            continue
        v = sum(_POLEMIC.get(_plain(x), 0) for x in txt.split()) + 0.1 * n
        if v > best_v:
            best, best_v = txt, v
    return best


# palavra que, sozinha na abertura, aponta para algo que quem chegou agora nao viu (ou emenda numa frase anterior)
_SOLTA = {"e", "mas", "que", "porque", "pois", "entao", "ai", "dai", "ele", "ela", "eles", "elas", "dele", "dela", "isso", "isto", "aquilo", "esse", "essa",
          "esses", "essas", "aquele", "aquela", "ou", "nem", "tambem", "de", "do", "da", "dos", "das", "ne", "la", "ali"}


def gancho_inteiro(captions: Transcript, a: float, b: float, max_s: float = 3.0) -> dict | None:
    """A abertura que toca [a, b] como frase INTEIRA que se entende sozinha, ou None (melhor abrir direto do que com pedaco de frase)."""
    ws: list = []
    fecha: list[bool] = []
    for s in captions.segments:
        novas = [w for w in s.words if w.text.strip()]
        if ws and novas and novas[0].text.strip()[:1].isupper():      # legenda sem ponto: trecho novo com maiuscula e frase nova
            fecha[-1] = True
        ws += novas
        fecha += [w.text.strip().endswith(_SENT_END) for w in novas]
    for i in range(len(ws) - 1):
        fecha[i] = fecha[i] or ws[i + 1].start - ws[i].end > 0.6
    sents, cur = [], []
    for w, f in zip(ws, fecha):
        cur.append(w)
        if f:
            sents.append(cur)
            cur = []
    if cur:
        sents.append(cur)

    def toca(st: list) -> float:
        return min(st[-1].end, b) - max(st[0].start, a)

    idx = [i for i, st in enumerate(sents) if toca(st) > 0.15]
    if not idx:
        return None
    grupos = [sents[idx[0]:idx[-1] + 1]] + [[sents[i]] for i in sorted(idx, key=lambda i: -toca(sents[i]))]
    for g in grupos:
        pal = [w for st in g for w in st]
        dur = pal[-1].end - pal[0].start
        if not 1.0 <= dur <= max_s + 0.2 or len(pal) < 3 or _plain(pal[0].text) in _SOLTA or pal[-1].text.strip().endswith(("...", "…")):
            continue
        if sum(max(0.0, toca(st)) for st in g) < 0.5 * (b - a):
            continue        # outra frase: nao e a que a IA quis
        return {"start": round(pal[0].start, 3), "end": round(pal[-1].end, 3), "text": _re.sub(r"\s+", " ", " ".join(w.text.strip() for w in pal)).strip()}
    return None


def _plain(w: str) -> str:
    import unicodedata

    t = unicodedata.normalize("NFD", w.lower())
    return "".join(ch for ch in t if ch.isalnum())


def _sortear(plans: list[ClipPlan], cfg: Config) -> None:
    """Sorteia o lado de cada corte nos testes A/B (antes de qualquer decisao que dependa do resultado)."""
    from . import experimentos
    from .brain.prompts import is_generic
    from .util import _EMOJI_RE

    if not cfg.get("experimentos.ativo", True):
        return
    for p in plans:
        e = {t: experimentos.lado(p.id, t) for t in experimentos.TESTES}
        # titulo: so entra se existem os dois estilos, os dois bons
        alt, tem = p.titulo_alt, '"' in p.title
        if alt and 15 <= len(alt) <= 95 and not is_generic(alt) and (('"' in alt) != tem) and not p.part:
            if (e["titulo"] == "A") != tem:
                p.title, p.titulo_alt = alt, p.title
        else:
            e.pop("titulo")
        # layout: conversa na horizontal, sem indicacao forte de jogo
        if p.category in ("politica", "noticias"):
            e.pop("layout")     # bancada e telejornal: quadro inteiro, senao corta a tarja e enquadra quem so ouve
            p.layout = "blur"
        elif p.category == "games" or p.layout == "split" or p.tipo == "reacao":
            e.pop("layout")
        else:
            if p.part:          # todas as partes da serie com o mesmo visual
                e["layout"] = experimentos.lado(f"{p.source_id}|{p.series}", "layout")
            p.layout = "blur" if e["layout"] == "A" else "full"
        if p.part:
            e.pop("cta")        # serie sempre chama para a proxima parte
        if len(p.imagens or []) < 2 or p.tipo in ("reacao", "tutorial"):
            e.pop("imagens")    # nada para ilustrar
        if e["emoji"] == "B":
            t = _EMOJI_RE.sub("", p.title).strip()
            if len(t) >= 12:
                p.title = _re.sub(r"\s{2,}", " ", t)
        p.exp = e


def refine_with_captions(p: ClipPlan, captions: Transcript, cfg: Config, rep: Reporter | None = None) -> Transcript:
    """Com a legenda limpa (Whisper) do corte: escolhe o gancho de abertura e coloca a frase mais pesada
    entre aspas no texto do video e no titulo. Ajusta o fim do corte para caber no limite de duracao.
    `captions` tem tempos relativos ao inicio do corte. Devolve a legenda (talvez encurtada)."""
    words = captions.words()
    if not words or not cfg.get("edicao.cold_open", True):
        return captions
    if p.tipo in ("tutorial", "curiosidade"):   # comeca pelo contexto, sem adiantar a resposta
        p.exp.pop("gancho", None)
        p.teaser_start = p.teaser_end = None
        p.teaser_text = ""
        return captions
    # Teste A/B (a pesquisa de concorrentes indica que os campeoes nao usam gancho; o dono quer gancho):
    # uma fracao dos cortes sai sem gancho e o aprendizado mede qual rende mais nesta conta.
    from . import tom

    ts = tom.settings(cfg)  # o nivel de tom (neutro ... modo besta) manda nas proporcoes e no palavrao
    min_s, max_s = 1.5, float(cfg.get("edicao.cold_open_max_s", 3.0))
    min_gap = float(cfg.get("edicao.cold_open_min_inicio_s", 4.0))
    min_score = float(cfg.get("edicao.cold_open_nota_minima", 3.5))
    brain_has = (p.teaser_start is not None and p.teaser_end is not None
                 and p.start <= p.teaser_start < p.teaser_end <= p.end)
    best, achou = None, False
    # 1) a frase que a IA sugeriu, procurada nas palavras da legenda limpa (texto sempre o que foi dito)
    if brain_has and p.teaser_text:
        try:
            from .brain import base as _b

            if hasattr(_b, "pick_teaser"):
                sp = _b.pick_teaser(words, 0.0, words[-1].end, hint_text=p.teaser_text,
                                    hint_start=p.teaser_start - p.start, cfg=cfg, min_s=min_s, max_s=max_s,
                                    lead=min_gap)
                if sp and sp.get("fonte") == "sugerido":
                    achou = True
                    inteiro = gancho_inteiro(captions, sp["start"], sp["end"], max_s)
                    best = {**sp, **inteiro} if inteiro and inteiro["start"] >= min_gap - 0.5 else None
        except Exception as e:
            _log.debug("pick_teaser: %s", e)
    # 2) senao, o trecho mais polemico da legenda limpa (so se for polemico de verdade)
    if best is None:
        spans = [s for s in polemic_spans(words, cfg, min_s, max_s)
                 if s["start"] >= min_gap and s["score"] >= min_score and (s.get("tipos") is None or s.get("tipos"))]
        for s in spans:
            inteiro = gancho_inteiro(captions, s["start"], s["end"], max_s)
            if inteiro and inteiro["start"] >= min_gap - 0.5:
                best = {**s, **inteiro}
                break
    if best is None and brain_has and not achou and p.tipo == "reacao" and 1.0 <= p.teaser_end - p.teaser_start <= 5.0:
        return captions     # a frase famosa e da cena (a transcricao nao pega): abre pelo tempo que a IA marcou
    if best is None:
        p.exp.pop("gancho", None)             # sem frase forte nao ha o que testar
        p.teaser_start = p.teaser_end = None  # sem frase forte: melhor sem gancho do que gancho fraco
        p.teaser_text = ""
        return captions
    if p.exp.get("gancho") == "B":            # sorteado para comecar direto (a frase forte existe, mas nao abre o video)
        p.teaser_start = p.teaser_end = None
        p.teaser_text = ""
        return captions
    p.teaser_start = round(p.start + best["start"], 3)
    p.teaser_end = round(p.start + best["end"], 3)
    p.teaser_text = best["text"]

    # texto do video e titulo: a frase entre aspas (traduzida, se o corte for estrangeiro)
    mode = str(ts["palavroes"])
    raw_quote = whole_sentence(words, best["start"], best["end"])
    if (p.idioma_origem or "pt")[:2] != "pt":
        raw_quote = _translate_text(raw_quote, cfg)
    quote = mask_profanity(raw_quote, mode) if raw_quote else ""
    use_quote = (cfg.get("conteudo.titulo_com_citacao", True) and p.tipo in ("", "fala", "reacao")
                 and _ab_bucket(p.id, "citacao") < float(ts["citacao_proporcao"]))
    from .brain.prompts import is_generic

    # a IA ja escreveu um titulo com citacao ou um titulo proprio: ele vale mais que a citacao automatica
    if '"' in (p.title or "") or not is_generic(p.title or ""):
        use_quote = False
    if quote and use_quote:
        q_hook = quote.upper() if ts["caps_gancho"] else quote
        if len(q_hook) <= 46:   # frase inteira ou nada: pedaco de frase nao faz sentido
            p.hook = f"\"{q_hook}\""
        from .util import _EMOJI_RE

        emo = "".join(_EMOJI_RE.findall(p.title or ""))[:4] if cfg.get("conteudo.emojis", True) else ""
        base = _EMOJI_RE.sub("", p.title or "").strip()
        q_title = quote[0].upper() + quote[1:]
        title = f"\"{q_title}\""
        if base and "\"" not in base and len(title) + len(base) + 3 <= 90:
            title = f"{title} {emo} {base}".replace("  ", " ").strip() if emo else f"{title} | {base}"
        elif emo:
            title = f"{title} {emo}"
        p.title = title[:100]

    # o gancho soma tempo: encurta o fim para caber no limite (Shorts ate 58 s)
    teaser_len = (p.teaser_end - p.teaser_start) + 0.2
    max_total = float(cfg.get("corte.duracao_max_s", 58))
    if p.duration + teaser_len > max_total:
        limit_rel = max_total - teaser_len - 0.15
        cut = max((w.end for w in words if w.end <= limit_rel), default=limit_rel)
        if cut > float(cfg.get("corte.duracao_min_s", 20)) and p.start + cut > (p.teaser_end or 0):
            p.end = round(p.start + cut + 0.15, 3)
            captions = captions.slice(0.0, cut + 0.15, rebase=False)
    if rep:
        rep.dim(f"gancho: {fmt_duration(p.teaser_start - p.start)} \"{quote[:50]}\"")
    return captions


def _fallback_brain(cfg: Config, current: str | None = None):
    """Proximo motor na ordem Claude > Ollama > heuristico (sem repetir o que acabou de falhar)."""
    from .brain import get_brain

    if current == "claude":
        return get_brain(cfg, force="ollama")  # devolve o heuristico se o Ollama nao estiver disponivel
    return get_brain(cfg, force="heuristico")


def pedir_candidatos(minutos: float, budget: int, motor: str) -> int:
    """Quantos candidatos pedir ao cerebro. Video longo com o Claude: mais do que cabe editar (o ajuste fino corta os fracos depois)."""
    from .brain import prompts

    alvo = prompts.candidatos(minutos, 10) if motor == "claude" else None
    return max(budget, alvo[1]) if alvo else budget


def os_melhores(plans: list[ClipPlan], n: int) -> list[ClipPlan]:
    """Os n melhores pela nota do editor (ou da escolha). Serie entra inteira ou nao entra."""
    if len(plans) <= n:
        return list(plans)
    grupos: dict[str, list[ClipPlan]] = {}
    for p in plans:
        grupos.setdefault(f"{p.source_id}|{p.series}" if p.part else p.id, []).append(p)

    def nota(g: list[ClipPlan]) -> float:
        return max(float((p.editor or {}).get("nota") or p.score or 0) for p in g)

    ordem = sorted(grupos.values(), key=nota, reverse=True)
    out: list[ClipPlan] = []
    for g in ordem:
        if len(out) + len(g) <= n:
            out += g
    return out or sorted(ordem[0], key=lambda p: p.part or 0)[:n]


def process_candidate(c: Candidate, cfg: Config, brain, run_id: str, rep: Reporter,
                      budget: int) -> tuple[list[RenderedClip], list[str]]:
    """Processa um video-fonte inteiro. Devolve (cortes renderizados, avisos)."""
    from . import download, editor, memoria, transcribe

    warnings: list[str] = []
    workdir = paths.run_dir(run_id) / slugify(c.id, 40)
    workdir.mkdir(parents=True, exist_ok=True)
    rendered: list[RenderedClip] = []
    try:
        # regra anti-repost: no maximo N cortes do mesmo canal por dia
        same_max = int(cfg.get("corte.max_cortes_mesma_fonte_dia", 3))
        used = db.clips_today_from_channel(c.channel)
        if used >= same_max:
            raise RuntimeError(f"ja foram {used} cortes do canal '{c.channel}' hoje (limite {same_max})")
        budget = min(budget, same_max - used)

        with rep.working("Lendo detalhes do video..."):
            c = download.enrich_candidate(c, cfg)
        db.upsert_video(c, "processando", run_id)

        transcript, audio = get_transcript(c, cfg, workdir, rep)
        if not transcript.segments:
            raise RuntimeError("nao encontrei fala neste video (sem legenda e Whisper nao ouviu nada)")
        if audio:
            c.extra["audio_path"] = str(audio)  # sinal de picos de volume para o cerebro

        plans: list[ClipPlan] = []
        pedir = pedir_candidatos(float(c.duration or 0) / 60, budget, brain.name)
        try:
            with rep.working(f"{brain.name}: escolhendo os melhores momentos..."):
                plans = brain.pick_clips(c, transcript, cfg, max_clips=pedir)
        except Exception as e:
            nxt = _fallback_brain(cfg, brain.name)
            warnings.append(f"{brain.name} falhou em '{c.title[:40]}': {str(e)[:120]} - usei {nxt.name}")
            rep.warn(warnings[-1])
        if not plans and brain.name != "heuristico":
            fb = _fallback_brain(cfg, brain.name)
            plans = fb.pick_clips(c, transcript, cfg, max_clips=budget)
            if not plans and fb.name != "heuristico":
                plans = _fallback_brain(cfg, fb.name).pick_clips(c, transcript, cfg, max_clips=budget)
        if len(plans) > pedir:  # o cerebro ja respeita o limite; isto e so uma garantia
            plans = sorted(plans, key=lambda p: -p.score)[:pedir]
        plans.sort(key=lambda p: p.start)
        if not plans:
            raise RuntimeError("nenhum trecho com potencial viral encontrado")
        from .util import clean_text

        emj = bool(cfg.get("conteudo.emojis", True))
        lang = _lang_of(c) if _lang_of(c) != "pt" else str(transcript.language or "pt")[:2]
        for p in plans:  # regra do dono: sem emojis, bolinhas ou travessoes em titulo, gancho, descricao, hashtags
            if lang != "pt":
                p.idioma_origem = lang  # corte estrangeiro: legenda sera traduzida para PT-BR
            p.title = clean_text(p.title, emj) or p.title
            p.hook = clean_text(p.hook, emj)
            p.description = clean_text(p.description, emj)
            p.hashtags = [h for h in (clean_text(t, emj) for t in p.hashtags) if h.strip("#")]
            if (c.extra or {}).get("via_rapida"):
                # momento explodindo agora: quem posta primeiro leva; sobe na fila de publicacao
                p.score = min(100.0, (p.score or 0) + float(cfg.get("busca.via_rapida.bonus_nota", 10)))
                p.reason = (p.reason + " | " if p.reason else "") + "via rapida: " + str(
                    c.extra.get("motivo_via_rapida", "momento explodindo agora"))
        # aprendizado: categorias que rendem mais na SUA conta ganham um pouco de nota (0,7x a 1,3x)
        try:
            from . import learning

            for p in plans:
                w = float(learning.weight_for(cfg, "categoria", p.category or ""))
                if abs(w - 1.0) > 0.01:
                    p.score = max(0.0, min(100.0, (p.score or 0) * w))
        except Exception as e:
            _log.debug("aprendizado indisponivel: %s", e)
        if lang == "pt":        # comeco e fim conferidos lendo a fala em volta, antes de baixar e editar
            from . import bordas

            with rep.working("Conferindo começo e fim de cada corte..."):
                plans = bordas.ajustar(plans, transcript, c, cfg)
            if not plans:
                raise RuntimeError("nenhum trecho faz sentido sozinho neste video")
        for p in plans:
            db.save_plan(p, run_id)
            rep.dim(f"nota {int(p.score):3d}  |  {fmt_duration(p.start)}-{fmt_duration(p.end)}  |  {p.title}")

        _sortear(plans, cfg)
        # versao estendida do TikTok (>= 61 s): decide ANTES do download para baixar o trecho maior
        for p in plans:
            try:
                ext = plan_extension(p, transcript, c.duration, cfg)
                if ext is None:
                    p.exp.pop("longo", None)        # nao da para alongar este: fica fora do teste
                elif p.exp.get("longo") == "A":
                    ext = None                      # sorteado para a versao curta
            except Exception as e:
                _log.debug("versao longa: %s", e)
                ext = None
            p.ext_start, p.ext_end = ext if ext else (None, None)
            if ext:
                rep.dim(f"versao longa do TikTok: {fmt_duration(ext[0])}-{fmt_duration(ext[1])} "
                        f"({fmt_duration(ext[1] - ext[0])}) para '{p.title[:40]}'")
        pad = float(cfg.get("corte.margem_frase_s", 6))
        groups = _group_plans(plans, pad=pad, dur=c.duration)
        storage.check_free_space(cfg, need_gb=0.3)
        with rep.working(f"Baixando {len(groups)} trecho(s) do video..."):
            files = download.download_sections(c, [(s, e) for s, e, _ in groups], cfg, workdir)

        # 1) legenda boa de todos os cortes, com folga dos dois lados
        largas: dict[str, tuple[Transcript, float]] = {}
        for (gs, _ge, gplans), f in zip(groups, files):
            for p in sorted(gplans, key=lambda p: p.start):
                s_abs, e_abs = (p.ext_start, p.ext_end) if p.ext_start is not None else (p.start, p.end)
                try:
                    with rep.working(f"Legendando '{p.title[:40]}'..."):
                        wa, wb = max(gs, s_abs - pad + 0.5), min(_ge, e_abs + pad - 0.5)
                        wide = _transcribe_clip(Path(f), cfg, wa - gs, wb - gs, c, p)
                        if wide and wide.segments:
                            largas[p.id] = (wide, wa)
                except memoria.LowMemory:
                    raise
                except Exception as e:
                    _log.warning("Whisper no corte falhou (%s); usando transcricao original", e)
        # 2) comeco e fim por frase inteira e nota, antes de gastar edicao
        ajustados: set[str] = set()
        if lang == "pt" and largas:
            from . import bordas

            ordem = [p for p in plans if p.id in largas]
            itens = [(n, p, bordas.frases(*largas[p.id])) for n, p in enumerate(ordem, 1)]
            with rep.working("Escolhendo a frase de começo e de fim..."):
                fora = bordas.fino(itens, c, cfg)
            for pid, motivo in fora.items():
                db.conn().execute("UPDATE clips SET curador=? WHERE id=?", (f"descartado antes de editar: {motivo}", pid))
                db.set_clip_status(pid, "rejeitado")
            ajustados = {p.id for p in ordem if p.editor and p.id not in fora}
            groups = [(a, b, [p for p in g if p.id not in fora]) for a, b, g in groups]
            if not any(g for _, _, g in groups):
                raise RuntimeError("nenhum corte bom o bastante para editar neste video")

        # candidatos a mais (video longo): so os melhores sao editados; o limite por canal continua valendo
        vivos = [p for _, _, g in groups for p in g]
        ficam = {p.id for p in os_melhores(vivos, budget)}
        for p in vivos:
            if p.id not in ficam:
                db.conn().execute("UPDATE clips SET curador=? WHERE id=?", ("descartado antes de editar: passou, mas havia melhores deste vídeo", p.id))
                db.set_clip_status(p.id, "rejeitado")
        groups = [(a, b, [p for p in g if p.id in ficam]) for a, b, g in groups]

        for (gs, _ge, gplans), f in zip(groups, files):
            for p in sorted(gplans, key=lambda p: p.start):
                tem_longa = p.ext_start is not None
                s_abs, e_abs = (p.ext_start, p.ext_end) if tem_longa else (p.start, p.end)
                full: Transcript | None = None
                if p.id in largas:
                    wide, wa = largas[p.id]
                    if p.id not in ajustados:
                        s_abs, e_abs = snap_sentences(p, wide, wa, s_abs, e_abs, tem_longa, cfg)
                    full = wide.slice(s_abs - wa, e_abs - wa)
                if not full or not full.segments:
                    full = transcript.slice(s_abs, e_abs)
                off = p.start - s_abs
                captions = full.slice(off, off + p.duration) if tem_longa else full
                p.fala = _re.sub(r"\s+", " ", full.text).strip()[:1500]
                # gancho de abertura + frase polemica entre aspas, a partir da legenda limpa do corte
                try:
                    captions = refine_with_captions(p, captions, cfg, rep)
                    db.save_plan(p, run_id)
                except Exception as e:
                    _log.warning("refinamento do gancho falhou: %s", e)
                if (p.idioma_origem or "pt")[:2] == "pt":
                    from . import honesto

                    for m in honesto.arruma_plano(p, p.fala):
                        _log.info("texto corrigido: %s", m)
                    db.save_plan(p, run_id)
                # corte estrangeiro: legenda queimada em portugues (sem traducao, nao publica)
                if (p.idioma_origem or "pt")[:2] != "pt":
                    try:
                        with rep.working("Traduzindo a legenda para portugues..."):
                            full = to_portuguese_captions(p, full, cfg, context=c.title)
                        captions = full.slice(off, off + p.duration) if tem_longa else full
                        if cfg.get("conteudo.marcar_legendado", True) and "LEGENDADO" not in p.title.upper():
                            p.title = p.title[:86].rstrip() + " (LEGENDADO)"
                        db.save_plan(p, run_id)
                    except Exception as e:
                        db.set_clip_status(p.id, "falhou")
                        warnings.append(f"pulei '{p.title[:40]}': {e}")
                        rep.warn(warnings[-1])
                        continue
                ls, le = p.start - gs, p.end - gs
                out = paths.RENDERS / f"{p.id}.mp4"
                try:
                    with rep.working(f"Editando '{p.title[:40]}' ({fmt_duration(p.duration)})..."):
                        rc = _render(Path(f), ls, le, p, captions, cfg, out,
                                     platforms=["youtube"] if tem_longa else None)
                    if p.imagens:       # estilo com imagens e musica (so no lado B do teste)
                        from . import editor, ilustra

                        with rep.working("Vendo se dá para ilustrar..."):
                            ilustra.no_corte(rc, p, editor.LAST_CAPTIONS, cfg, tem_longa)
                    else:
                        p.exp.pop("imagens", None)
                    if tem_longa:
                        rc = _add_long_version(rc, Path(f), s_abs, e_abs, gs, p, full, captions, cfg, out, rep)
                    if rc.layout in ("react", "split") or rc.layout != p.layout:     # nao saiu como o teste pediu
                        p.exp.pop("layout", None)
                    db.save_rendered(rc)
                    rendered.append(rc)
                    rep.ok(f"Corte pronto: {p.title}  [{rc.layout}, {fmt_duration(rc.duration)}"
                           + (" + versao longa TikTok" if tem_longa else "") + "]")
                except memoria.LowMemory:
                    db.set_clip_status(p.id, "falhou")
                    raise
                except Exception as e:
                    db.set_clip_status(p.id, "falhou")
                    warnings.append(f"falha ao editar '{p.title[:40]}': {e}")
                    rep.warn(warnings[-1])
                    _log.debug(traceback.format_exc())
        db.upsert_video(c, "processado", run_id)
    except storage.DiskFullError:
        raise
    except Exception as e:
        passageiro = isinstance(e, memoria.LowMemory)
        desistir = not passageiro and db.bump_attempt(c.id) >= db.MAX_VIDEO_ATTEMPTS
        db.upsert_video(c, "ignorado" if desistir else "falhou", run_id, error=str(e)[:500])
        raise
    finally:
        if cfg.get("armazenamento.apagar_brutos_apos_render", True):
            shutil.rmtree(workdir, ignore_errors=True)
    return rendered, warnings


# ============================================================ descoberta
_RISKY = ("bet", "bets", "aposta", "apostas", "cassino", "casino", "tigrinho", "jogo do bicho", "blaze", "fortune tiger",
          "bet365", "betano", "sportingbet", "superbet", "betnacional", "esportes da sorte", "estrelabet",
          "estrela bet", "pixbet", "kto", "f12bet", "aviator",
          "melhores momentos", "gols da partida", "ao vivo e de graca", "filme completo", "episodio completo",
          "clipe oficial", "official music video", "lyric video")


def is_blocked(c: Candidate, cfg: Config) -> bool:
    """Canal bloqueado ou conteudo de risco (apostas, jogo de futebol, filme, clipe de musica)."""
    hay = " ".join([c.channel or "", c.channel_url or "", c.url or ""]).lower()
    for b in cfg.get("busca.canais_bloqueados", []) or []:
        b = str(b).lower().strip()
        if b and (b in hay or b.lstrip("@") in hay.replace(" ", "")):
            return True
    title = (c.title or "").lower()
    if any(w in title for w in cfg.get("busca.palavras_bloqueadas", []) or []):
        return True
    if cfg.get("busca.pular_categorias"):
        import re

        if any(re.search(rf"\b{re.escape(r)}\b", title) for r in _RISKY):
            return True
    return False


import re as _re

_MATCH_RE = _re.compile(r"^\s*[\wÀ-ÿ.'\- ]{2,32}\s+(x|vs\.?|versus)\s+[\wÀ-ÿ.'\- ]{2,32}\s*$", _re.I)


def adjust_trends(trends: list[Trend], cfg: Config) -> list[Trend]:
    """Jogo esportivo ('time x time'): imagem da partida da strike. Rebaixa e busca so resenha/podcast."""
    for t in trends:
        if _MATCH_RE.match(t.topic or ""):
            t.score = round((t.score or 0) * 0.55, 1)
            t.queries = [f"{t.topic} resenha", f"{t.topic} podcast pos jogo", f"{t.topic} entrevista coletiva"]
            note = "jogo: so resenha/podcast (imagem da partida da strike)"
            t.reason = f"{t.reason}; {note}" if t.reason else note
    return sorted(trends, key=lambda t: -(t.score or 0))


def discover(cfg: Config, opts: RunOptions, brain, rep: Reporter, summary: dict, run_id: str,
             n_videos: int) -> list[Candidate]:
    from . import discovery

    mode = summary["search_mode"]
    if mode == "via_rapida":
        for c in opts.candidates:
            rep.info(f"Via rapida: {c.title[:60]} ({(c.extra or {}).get('motivo_via_rapida', 'momento explodindo')})")
        return [c for c in opts.candidates if not is_blocked(c, cfg)]
    if mode == "link":
        out = []
        for u in opts.urls:
            try:
                with rep.working(f"Lendo {u[:60]}..."):
                    out.append(candidate_from_url(u, cfg))
            except Exception as e:
                summary["errors"].append(f"link invalido ou indisponivel: {u} ({e})")
                rep.error(summary["errors"][-1])
        return out

    trends: list[Trend] = []
    if mode in ("trends", "misto"):
        with rep.working("Varrendo Google Trends, noticias, X, Reddit, YouTube e Twitch..."):
            trends = discovery.collect_trends(cfg)
        rep.info(f"{len(trends)} assuntos em alta encontrados")
        try:
            with rep.working(f"{brain.name}: separando o que rende corte..."):
                trends = brain.rank_trends(trends, cfg, limit=int(cfg.get("busca.max_assuntos", 15)))
        except Exception as e:
            rep.warn(f"{brain.name} nao conseguiu ranquear os assuntos ({e}); usando heuristica")
            trends = _fallback_brain(cfg, "ollama").rank_trends(trends, cfg, limit=int(cfg.get("busca.max_assuntos", 15)))
        trends = adjust_trends(trends, cfg)
        db.save_trends(run_id, trends)
        summary["trends"] = [t.to_dict() for t in trends]
        for t in trends[:10]:
            rep.dim(f"{int(t.score):3d}  {t.topic}  [{t.category or t.source}]")

    keywords = summary["keywords"]
    seen = {r["id"] for r in db.conn().execute(
        "SELECT id FROM videos WHERE status IN ('processado','ignorado')").fetchall()}
    with rep.working("Procurando videos-fonte (YouTube, Twitch...)..."):
        cands = discovery.find_candidates(
            cfg, trends=trends or None, keywords=keywords or None, limit=max(n_videos * 3, 10), exclude_ids=seen,
        )
    cands = [c for c in cands if c.id not in seen and not c.is_live and not is_blocked(c, cfg)]
    rep.info(f"{len(cands)} videos candidatos; processando os {min(n_videos, len(cands))} melhores")
    return cands


def _cota(cfg: Config) -> bool:
    """Da para comecar mais um video e ainda julgar e revisar o que sair dele?"""
    from . import uso_ia

    return not cfg.get("cerebro.produzir_so_com_claude", True) or uso_ia.pode_claude(cfg, "clips")


# =============================================================== rodada
def run(cfg: Config, opts: RunOptions, rep: Reporter | None = None) -> dict:
    from . import andamento

    rep = andamento.Tap(rep or Reporter(quiet=not opts.interactive))
    paths.ensure_dirs()
    run_id = run_id_now()
    search_mode = ("via_rapida" if opts.candidates else
                   "link" if opts.urls else (opts.search_mode or cfg.get("busca.modo", "trends")))
    keywords = list(opts.keywords or [])
    if not keywords and search_mode in ("palavra_chave", "misto"):
        keywords = list(cfg.get("busca.palavras_chave", []) or [])
    if search_mode == "palavra_chave" and not keywords:
        search_mode = "trends"
    publish_mode = opts.publish_mode or cfg.get("modo_publicacao", "revisar")
    n_videos = int(opts.n_videos or cfg.get("execucao.videos_por_execucao", 5))
    max_clips = int(opts.max_clips or cfg.get("execucao.max_cortes_por_execucao", 15))

    t0 = time.time()
    summary: dict = {
        "run_id": run_id, "started": t0, "started_txt": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "trigger": opts.trigger, "search_mode": search_mode, "keywords": keywords,
        "publish_mode": publish_mode + (" (teste)" if opts.dry_run else ""), "brain": "?",
        "trends": [], "candidates": [], "clips": [], "posts": [],
        "errors": [], "warnings": [], "actions": [], "status": "ok",
    }
    TOTAL = 4
    with RunLock():
        andamento.begin({"manual": "pedido seu", "autopiloto": "automático", "agendado": "agendada"}.get(opts.trigger, opts.trigger),
                        ", ".join(opts.urls or keywords)[:120])
        db.release_stuck()
        db.start_run(run_id, opts.trigger, search_mode, keywords, publish_mode)
        try:
            # 1 ─ preparo
            rep.stage(1, TOTAL, "Preparando a fabrica")
            cl = storage.cleanup(cfg)
            rep.dim(f"disco livre: {cl['livre_gb']} GB | pasta de trabalho: {cl['work_txt']}")
            storage.check_free_space(cfg, need_gb=0.5)
            from .brain import get_brain

            brain = get_brain(cfg, force=opts.brain, tarefa="clips")          # escolher cortes: Claude leve > Ollama
            brain_trends = get_brain(cfg, force=opts.brain, tarefa="trends")  # ranquear assuntos: IA local
            summary["brain"] = brain.name
            rep.info(f"Cerebro: {brain.status()}")

            # 2 ─ descoberta
            rep.stage(2, TOTAL, "Descobrindo o que esta em alta" if search_mode != "link" else "Lendo os links")
            cands = discover(cfg, opts, brain_trends, rep, summary, run_id, n_videos)
            from .brain import games as _games

            soltos = [] if opts.urls else [c for c in cands if _games.plain_gameplay(c)]
            if soltos:
                cands = [c for c in cands if c not in soltos]
                rep.info(f"{len(soltos)} gameplay(s) comum(ns) de fora (sem reacao nem curiosidade)")
            if not opts.urls and brain.name != "claude" and cfg.get("busca.estrangeiro.exige_claude", True):
                fora = [c for c in cands if (c.extra or {}).get("estrangeiro")]
                if fora:
                    cands = [c for c in cands if c not in fora]
                    rep.info(f"{len(fora)} video(s) em outra lingua ficaram de fora (so entram com o Claude escolhendo)")

            # 3 ─ processamento
            rep.stage(3, TOTAL, "Cortando e editando")
            all_rendered: list[RenderedClip] = []
            processed = fails = 0
            max_h = float(cfg.get("execucao.max_horas_rodada", 3))
            for c in cands:
                if processed >= n_videos or len(all_rendered) >= max_clips:
                    break
                if fails >= int(cfg.get("execucao.max_falhas_rodada", 4)) or time.time() - t0 > max_h * 3600:
                    rep.warn("Rodada encerrada: muitas falhas seguidas ou tempo demais. Tento de novo na proxima.")
                    break
                if opts.trigger != "manual" and brain.name == "claude" and not _cota(cfg):
                    rep.info("Cota do Claude desta parte do dia acabou: guardo o resto para mais tarde.")
                    break
                cinfo = {"id": c.id, "title": c.title, "channel": c.channel, "platform": c.platform, "url": c.url,
                         "views": c.views, "duration": c.duration, "score": c.score, "reasons": c.reasons,
                         "topic": c.topic, "status": "processando", "error": None}
                summary["candidates"].append(cinfo)
                rep.info(f"[{processed + 1}/{min(n_videos, len(cands))}] {c.title[:70]}  |  {c.channel}")
                try:
                    budget = max_clips - len(all_rendered)
                    try:
                        rendered, warns = process_candidate(c, cfg, brain, run_id, rep, budget)
                    except storage.DiskFullError:
                        raise
                    except Exception as first_err:
                        # via rapida: se a live (VOD) nao baixou, usa o proprio clipe que estava explodindo
                        reserva = (c.extra or {}).get("clip_reserva") or {}
                        if not reserva.get("url"):
                            raise
                        rep.warn(f"Live indisponivel ({str(first_err)[:80]}); usando o clipe que viralizou")
                        alt = candidate_from_url(reserva["url"], cfg)
                        for k in ("via_rapida", "motivo_via_rapida", "idioma", "categoria", "prioridade"):
                            if k in (c.extra or {}):
                                alt.extra[k] = c.extra[k]
                        alt.topic, alt.score, alt.reasons = c.topic, c.score, c.reasons
                        rendered, warns = process_candidate(alt, cfg, brain, run_id, rep, budget)
                    all_rendered.extend(rendered)
                    summary["warnings"].extend(warns)
                    cinfo["status"] = f"{len(rendered)} cortes"
                    processed += 1
                    # rodada automatica: respiro para a CPU esfriar entre um video e outro
                    if opts.trigger != "manual":
                        pausa = float(cfg.get("autopiloto.pausa_entre_videos_s", 20))
                        if pausa > 0:
                            time.sleep(pausa)
                except storage.DiskFullError as e:
                    summary["errors"].append(str(e))
                    summary["actions"].append("Libere espaco no disco C: (ou rode 'fabrica limpar').")
                    rep.error(str(e))
                    cinfo["status"] = "parado"
                    break
                except Exception as e:
                    fails += 1
                    msg = str(e).strip().splitlines()[0][:300] if str(e).strip() else type(e).__name__
                    cinfo["status"], cinfo["error"] = "falhou", msg
                    from . import memoria

                    if isinstance(e, memoria.LowMemory):   # 3) sem memoria: nao adianta tentar os outros videos agora
                        summary["errors"].append(msg)
                        summary["actions"].append(msg)
                        rep.error(msg)
                        break
                    summary["warnings"].append(f"'{c.title[:50]}': {msg}")
                    rep.warn(f"Pulei este video: {msg}")
                    _log.debug(traceback.format_exc())
                    from .models import NeedsUserAction

                    if (isinstance(e, NeedsUserAction) or "cortex login" in msg) and msg not in summary["actions"]:
                        summary["actions"].append(msg)
                    # falha nao conta como processado: segue para o proximo candidato

            for rc in all_rendered:
                summary["clips"].append(_clip_info(rc, cands))

            # 4 ─ publicacao
            rep.stage(4, TOTAL, "Publicacao")
            if not all_rendered:
                rep.warn("Nada para publicar nesta rodada.")
            elif publish_mode == "auto":
                _publish(cfg, all_rendered, opts, rep, summary)
            elif publish_mode == "fila":
                rep.info(f"{len(all_rendered)} corte(s) entraram na fila do piloto automatico")
            elif publish_mode == "revisar":
                if opts.interactive:
                    from . import review

                    results = review.review(cfg, only_ids={rc.plan.id for rc in all_rendered},
                                            dry_run=opts.dry_run, rep=rep)
                    _merge_posts(summary, results)
                else:
                    summary["actions"].append(
                        f"{len(all_rendered)} cortes aguardando sua revisao: abra o CORTEX > Ver cortes prontos.")
                    rep.info(summary["actions"][-1])
            else:
                rep.info(f"Modo 'nao_publicar': cortes salvos em {paths.RENDERS}")

            if summary["errors"]:
                summary["status"] = "erro" if not all_rendered else "parcial"
            elif summary["warnings"] or summary["actions"]:
                summary["status"] = "parcial"
        except Exception as e:
            summary["status"] = "erro"
            summary["errors"].append(str(e))
            rep.error(str(e))
            _log.error(traceback.format_exc())
        finally:
            summary["finished"] = time.time()
            summary["duration_s"] = summary["finished"] - t0
            try:
                path = report.write(summary)
                summary["report_path"] = str(path)
            except Exception as e:  # pragma: no cover
                _log.error("relatorio falhou: %s", e)
            db.finish_run(run_id, summary["status"], {k: summary[k] for k in ("status", "errors", "actions")} |
                          {"cortes": len(summary["clips"]), "posts": len(summary["posts"])})
            try:
                storage.cleanup(cfg)
            except Exception:
                pass
            ok_posts = sum(1 for p in summary["posts"] if p.get("ok") and not p.get("dry_run"))
            if opts.notify or summary["actions"]:
                notify.toast("CORTEX",
                             f"{len(summary['clips'])} cortes prontos, {ok_posts} publicados. "
                             + ("Precisa de voce: " + summary["actions"][0] if summary["actions"] else
                                ("Tudo certo!" if summary["status"] == "ok" else "Veja o relatorio.")), cfg)
    return summary


def _clip_info(rc: RenderedClip, cands: list[Candidate]) -> dict:
    src = next((c for c in cands if c.id == rc.plan.source_id), None)
    return {"id": rc.plan.id, "title": rc.plan.title, "score": rc.plan.score, "reason": rc.plan.reason,
            "duration": rc.duration, "layout": rc.layout, "path": rc.path, "thumbnail": rc.thumbnail,
            "part": rc.plan.part, "parts_total": rc.plan.parts_total, "status": "renderizado",
            "source_title": src.title if src else rc.plan.source_id, "source_url": src.url if src else ""}


def _merge_posts(summary: dict, results) -> None:
    for r in results or []:
        summary["posts"].append(r.to_dict())
        if r.error and r.error.startswith("ACAO_NECESSARIA"):
            msg = r.error.split(":", 1)[1].strip()
            if msg not in summary["actions"]:
                summary["actions"].append(msg)
    status_by_clip: dict[str, str] = {}
    for r in results or []:
        if r.ok and not r.dry_run:
            status_by_clip[r.clip_id] = "publicado"
        else:
            status_by_clip.setdefault(r.clip_id, "falhou" if not r.ok else "renderizado")
    for c in summary["clips"]:
        if c["id"] in status_by_clip:
            c["status"] = status_by_clip[c["id"]]


MAX_TENTATIVAS = 3


def publish_clips(cfg: Config, clips: list[RenderedClip], dry_run: bool, rep: Reporter,
                  only: list[str] | None = None, revisado_pelo_dono: bool = False) -> tuple[list, list[str]]:
    """Revisa (revisao.py), checa login de cada rede e publica. Devolve (resultados, acoes necessarias)."""
    from . import exclusivas, publish, revisao

    actions: list[str] = []
    if not dry_run and not revisado_pelo_dono:      # nada sai sem revisao, venha de onde vier o pedido
        n = len(clips)
        clips, espera = revisao.filtrar(clips, cfg)
        if len(clips) < n:
            rep.warn(f"{n - len(clips)} corte(s) nao passaram na revisao" + (" ou esperam o Claude" if espera else ""))
        if not clips:
            return [], actions
    platforms = []
    if only is None:        # rede com cortes proprios so recebe quando pedida pelo nome
        only = exclusivas.conjunto(cfg)
    for p in cfg.get("publicacao.plataformas", ["youtube", "tiktok"]):
        if p not in only:
            continue
        try:
            logged = publish.check_login(p, cfg)
        except Exception as e:
            logged = False
            _log.warning("check_login %s: %s", p, e)
        if logged:
            from . import policy

            policy.register_login(p)
            can, why = policy.can_post(p, cfg)
            if can or dry_run:
                platforms.append(p)
            else:
                rep.warn(f"{p}: {why} (regra de seguranca da conta; ajuste em config.yaml > publicacao)")
        else:
            actions.append(f"Faca login no {p}: abra o CORTEX > Contas (ou: cortex login {p})")
            rep.warn(actions[-1])
    if not platforms:
        return [], actions
    clips = publish_order(clips)
    rep.info(f"Publicando {len(clips)} corte(s) em: {', '.join(platforms)}" + (" [MODO TESTE]" if dry_run else ""))
    results = publish.publish_batch(clips, cfg, platforms=platforms, dry_run=dry_run, on_event=rep.info)
    all_targets = exclusivas.conjunto(cfg)
    for clip in clips:
        rs = [r for r in results if r.clip_id == clip.plan.id]
        if dry_run:
            continue
        so_dela = exclusivas.e_de_exclusiva(clip.plan.id, cfg)
        dele = [p for p in exclusivas.redes(cfg) if p in exclusivas.postados(clip.plan.id)] if so_dela else []
        if dele:        # corte so dessa rede: acabou aqui (nao vai para as outras)
            db.set_clip_status(clip.plan.id, "publicado")
            if db.has_uncertain_post(clip.plan.id) or not all(db.already_posted(clip.plan.id, p) for p in dele):
                actions.append(f"Confira no app se '{clip.plan.title[:50]}' foi publicado (nao vi a confirmacao). O video foi mantido no PC.")
            else:
                try:
                    storage.release_published(clip.plan.id, clip.path, cfg)
                except Exception as e:
                    _log.warning("liberar video publicado: %s", e)
            continue
        if any(p in exclusivas.redes(cfg) for p in platforms):
            # nao saiu na rede dele: volta para a fila. Repetiu um que ja tinha terminado nas outras: agora libera o arquivo
            if all_targets and all(db.already_posted(clip.plan.id, p) for p in all_targets) and not db.has_uncertain_post(clip.plan.id) \
                    and any(r.ok for r in rs) and not exclusivas.segurar(clip, cfg):
                try:
                    storage.release_published(clip.plan.id, clip.path, cfg)
                except Exception as e:
                    _log.warning("liberar video publicado: %s", e)
            continue
        # so e "publicado" quando saiu em TODAS as redes; senao continua na fila para a que faltou
        # INCERTO = cliquei em Publicar e nao vi a confirmacao: guarda o video ate o dono conferir
        if any((r.error or "").startswith("INCERTO") for r in rs) or db.has_uncertain_post(clip.plan.id, all_targets):
            actions.append(f"Confira no app se '{clip.plan.title[:50]}' foi publicado (nao vi a confirmacao). "
                           "O video foi mantido no PC.")
            continue
        if all_targets and all(db.already_posted(clip.plan.id, p) for p in all_targets):
            db.set_clip_status(clip.plan.id, "publicado")
            if exclusivas.segurar(clip, cfg):      # uma rede exclusiva ainda pode repetir: o arquivo espera no PC
                continue
            try:
                destino = storage.release_published(clip.plan.id, clip.path, cfg)
                if destino in ("onedrive", "apagado"):
                    rep.dim(f"video liberado do PC ({destino})")
            except Exception as e:
                _log.warning("liberar video publicado: %s", e)
        else:
            desistiu = [p for p in all_targets if not db.already_posted(clip.plan.id, p)
                        and db.failed_attempts(clip.plan.id, p) >= MAX_TENTATIVAS]
            if desistiu and all(db.already_posted(clip.plan.id, p) or p in desistiu for p in all_targets):
                saiu = any(db.already_posted(clip.plan.id, p) for p in all_targets)
                db.set_clip_status(clip.plan.id, "publicado" if saiu else "falhou")
                actions.append(f"'{clip.plan.title[:45]}' nao foi para {', '.join(desistiu)} depois de {MAX_TENTATIVAS} "
                               "tentativas (veja os prints em logs/screenshots).")
    for r in results:
        if r.ok:
            rep.ok(f"{r.platform}: {r.url or 'publicado'}" + (" (teste)" if r.dry_run else ""))
        else:
            rep.error(f"{r.platform}: {r.error}")
    return results, actions


def publish_order(clips: list[RenderedClip]) -> list[RenderedClip]:
    """Ranking do dia na frente, depois os melhores; series sempre em ordem (Parte 1 antes da Parte 2)."""
    def group_key(c: RenderedClip) -> str:
        p = c.plan
        return f"{p.source_id}|{p.series}" if p.part else p.id

    best: dict[str, float] = {}
    for c in clips:
        k = group_key(c)
        best[k] = max(best.get(k, 0.0), c.plan.score or 0.0)
    return sorted(clips, key=lambda c: (c.plan.tipo != "ranking", -best[group_key(c)], group_key(c), c.plan.part or 0))


def _publish(cfg: Config, clips: list[RenderedClip], opts: RunOptions, rep: Reporter, summary: dict) -> None:
    try:
        results, actions = publish_clips(cfg, clips, opts.dry_run, rep)
        summary["actions"].extend(a for a in actions if a not in summary["actions"])
        _merge_posts(summary, results)
    except Exception as e:
        summary["errors"].append(f"publicacao falhou: {e}")
        rep.error(summary["errors"][-1])
        _log.error(traceback.format_exc())
