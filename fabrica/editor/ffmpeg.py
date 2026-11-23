"""Execucao do ffmpeg/ffprobe: progresso, probe, escolha do encoder, loudnorm, frames."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Sequence

from .. import paths, tools
from ..log import get as get_log
from ..util import CREATE_NO_WINDOW

_log = get_log(__name__)

ProgressCb = Callable[[float], None]   # recebe fracao 0..1

W, H = 1080, 1920


class FFmpegError(RuntimeError):
    pass


def ffmpeg_bin() -> str:
    exe = tools.ffmpeg()
    if not exe:
        raise FFmpegError("ffmpeg nao encontrado (coloque ffmpeg.exe no PATH ou na pasta tools\\)")
    return exe


def ffprobe_bin() -> str:
    exe = tools.ffprobe()
    if not exe:
        raise FFmpegError("ffprobe nao encontrado (coloque ffprobe.exe no PATH ou na pasta tools\\)")
    return exe


# ------------------------------------------------------------------ runner
def run(args: Sequence[str | Path], *, duration: float | None = None, on_progress: ProgressCb | None = None,
        cwd: str | Path | None = None, timeout: float | None = None, check: bool = True) -> tuple[int, str]:
    """Roda o ffmpeg (sem o executavel em args). Devolve (returncode, stderr).

    Com `duration` e `on_progress`, chama on_progress(fracao) conforme o ffmpeg avanca.
    """
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-y"]
    if on_progress and duration:
        cmd += ["-progress", "pipe:1", "-nostats"]
    cmd += [str(a) for a in args]
    _log.debug("ffmpeg %s", " ".join(cmd[1:])[:2000])
    err_file = tempfile.TemporaryFile()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE if on_progress else subprocess.DEVNULL,
                            stderr=err_file, cwd=str(cwd) if cwd else None, creationflags=CREATE_NO_WINDOW)
    killer = None
    if timeout:
        killer = threading.Timer(timeout, proc.kill)
        killer.start()
    try:
        if on_progress and duration and proc.stdout is not None:
            for raw in proc.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                    try:
                        us = int(line.split("=", 1)[1])
                        on_progress(max(0.0, min(1.0, us / 1e6 / duration)))
                    except ValueError:
                        pass
                elif line == "progress=end":
                    on_progress(1.0)
        rc = proc.wait()
    finally:
        if killer:
            killer.cancel()
    err_file.seek(0)
    err = err_file.read().decode("utf-8", "replace")
    err_file.close()
    if check and rc != 0:
        tail = "\n".join(l for l in err.splitlines() if l.strip())[-2500:]
        raise FFmpegError(f"ffmpeg falhou (codigo {rc}):\n{tail}")
    return rc, err


# ------------------------------------------------------------------ probe
def _ratio(s: str | None) -> float:
    if not s or s in ("0/0", "N/A"):
        return 0.0
    if "/" in s:
        a, b = s.split("/", 1)
        try:
            return float(a) / float(b) if float(b) else 0.0
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def probe(path: str | Path) -> dict:
    """Informacoes basicas: duration, width, height (ja girados), fps, has_audio, vcodec, acodec..."""
    p = subprocess.run(
        [ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=60,
    )
    if p.returncode != 0:
        raise FFmpegError(f"ffprobe falhou em {path}: {p.stderr.decode('utf-8', 'replace')[-500:]}")
    data = json.loads(p.stdout.decode("utf-8", "replace") or "{}")
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})
    dur = _ratio(fmt.get("duration")) or (_ratio(v.get("duration")) if v else 0.0) or (
        _ratio(a.get("duration")) if a else 0.0)
    w = int(v.get("width", 0)) if v else 0
    h = int(v.get("height", 0)) if v else 0
    rot = 0
    if v:
        try:
            rot = int(float((v.get("tags") or {}).get("rotate", 0)))
        except ValueError:
            rot = 0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                try:
                    rot = int(float(sd["rotation"]))
                except (TypeError, ValueError):
                    pass
    if abs(rot) % 180 == 90:
        w, h = h, w
    return {
        "duration": dur,
        "width": w,
        "height": h,
        "fps": (_ratio(v.get("avg_frame_rate")) or _ratio(v.get("r_frame_rate"))) if v else 0.0,
        "has_video": v is not None,
        "has_audio": a is not None,
        "vcodec": v.get("codec_name") if v else None,
        "acodec": a.get("codec_name") if a else None,
        "sample_rate": int(a.get("sample_rate", 0) or 0) if a else 0,
        "channels": int(a.get("channels", 0) or 0) if a else 0,
        "pix_fmt": v.get("pix_fmt") if v else None,
        "bit_rate": int(fmt.get("bit_rate", 0) or 0),
        "size": int(fmt.get("size", 0) or 0),
        "rotation": rot,
    }


# ------------------------------------------------------------------ encoder
_ENC_CACHE = paths.STATE / "encoder.json"
_enc_lock = threading.Lock()

# rapida | media | alta  -> (preset, crf, teto de bitrate em Mbit/s)
# O teto evita arquivos enormes quando o fundo e gameplay com muito movimento
# (YouTube recomenda ~8 Mbit/s para 1080p30; TikTok recomprime tudo).
X264_PRESETS = {"rapida": ("superfast", 23, 5), "media": ("veryfast", 22, 6), "alta": ("faster", 21, 7)}
# AMF (GPU AMD): vbr_peak. Medido nesta maquina: o modo qvbr e 3-4x mais lento e o
# preset "quality" nao melhora o SSIM em relacao ao "balanced" (0,9932 x 0,9932).
# -> (preset AMF, bitrate alvo, teto) em Mbit/s
AMF_PRESETS = {"rapida": ("speed", 4, 5), "media": ("balanced", 4.5, 6), "alta": ("balanced", 4.5, 7)}


def _ffmpeg_version() -> str:
    try:
        p = subprocess.run([ffmpeg_bin(), "-hide_banner", "-version"], capture_output=True,
                           creationflags=CREATE_NO_WINDOW, timeout=20)
        return p.stdout.decode("utf-8", "replace").splitlines()[0][:120]
    except Exception:  # noqa: BLE001
        return "?"


def video_encoder_args(encoder: str, cfg=None, fps: int = 30, threads: int | None = None) -> list[str]:
    q = str(cfg.get("edicao.qualidade", "alta") if cfg is not None else "alta").lower()
    gop = str(int(fps) * 2)
    if encoder == "h264_amf":
        quality, target, cap = AMF_PRESETS.get(q, AMF_PRESETS["alta"])
        return ["-c:v", "h264_amf", "-usage", "transcoding", "-quality", quality,
                "-rc", "vbr_peak", "-b:v", f"{target}M", "-maxrate", f"{cap}M", "-bufsize", f"{cap * 2}M",
                "-profile:v", "high", "-g", gop, "-bf", "2", "-pix_fmt", "nv12"]
    preset, crf, cap = X264_PRESETS.get(q, X264_PRESETS["alta"])
    # teto de threads (edicao.threads, padrao 6): nao satura a CPU
    cap_t = max(1, min(6, int(cfg.get("edicao.threads", 6) or 6))) if cfg is not None else 6
    threads = max(1, min(cap_t, int(threads))) if threads else cap_t
    return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-profile:v", "high",
            "-maxrate", f"{cap}M", "-bufsize", f"{cap * 2}M", "-g", gop, "-pix_fmt", "yuv420p",
            "-threads", str(threads)]


def test_encoder(encoder: str, cfg=None) -> tuple[bool, float]:
    """Codifica 2 s de teste 1080x1920. Devolve (funcionou, segundos gastos)."""
    out = paths.TMP / f"enc_test_{encoder}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    try:
        run(["-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r=30:d=2", *video_encoder_args(encoder, cfg),
             "-an", str(out)], timeout=90)
        info = probe(out)
        ok = info["width"] == W and info["height"] == H and info["duration"] > 1.5
    except Exception as e:  # noqa: BLE001
        _log.info("Encoder %s indisponivel: %s", encoder, str(e)[-300:])
        ok = False
    finally:
        out.unlink(missing_ok=True)
    return ok, time.time() - t0


def _load_cache() -> dict:
    try:
        return json.loads(_ENC_CACHE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_cache(d: dict) -> None:
    try:
        _ENC_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _ENC_CACHE.write_text(json.dumps(d, indent=2), encoding="utf-8")
    except OSError:
        pass


def amf_available(cfg=None, force_test: bool = False) -> bool:
    with _enc_lock:
        cache = _load_cache()
        ver = _ffmpeg_version()
        if not force_test and cache.get("ffmpeg") == ver and "amf_ok" in cache:
            return bool(cache["amf_ok"])
        ok, secs = test_encoder("h264_amf", cfg)
        cache.update({"ffmpeg": ver, "amf_ok": ok, "amf_test_s": round(secs, 2), "tested_at": time.time()})
        _save_cache(cache)
        return ok


def mark_amf_broken(reason: str) -> None:
    cache = _load_cache()
    cache.update({"amf_ok": False, "amf_error": reason[-300:], "ffmpeg": _ffmpeg_version()})
    _save_cache(cache)


def pick_encoder(cfg=None) -> str:
    """edicao.encoder: auto | h264_amf | libx264.

    auto -> h264_amf (GPU AMD) quando o teste de 2 s passa nesta maquina (cache em
    data/estado/encoder.json); senao libx264. Medido: com a CPU ocupada (Whisper, outros
    processos) o AMF em vbr_peak codifica 1080x1920 ~1,7x mais rapido que o libx264 veryfast,
    com SSIM igual (~0,993) e arquivo ~40% maior. edicao.preferir_gpu: false forca o libx264.
    Se o AMF falhar no meio de um render, render_clip refaz com libx264 e marca o AMF como quebrado.
    """
    want = str(cfg.get("edicao.encoder", "auto") if cfg is not None else "auto").lower()
    if want in ("h264_amf", "amf", "gpu"):
        return "h264_amf" if amf_available(cfg) else "libx264"
    if want in ("libx264", "x264", "cpu"):
        return "libx264"
    prefer_gpu = bool(cfg.get("edicao.preferir_gpu", True)) if cfg is not None else True
    if prefer_gpu and amf_available(cfg):
        return "h264_amf"
    return "libx264"


def audio_args(cfg=None) -> list[str]:
    br = str(cfg.get("edicao.audio_kbps", 192) if cfg is not None else 192)
    return ["-c:a", "aac", "-b:a", f"{br}k", "-ar", "48000", "-ac", "2"]


# ------------------------------------------------------------------ loudnorm (2 passadas)
LOUD_I, LOUD_TP, LOUD_LRA = -14.0, -1.5, 11.0


def measure_loudness(source: str | Path, start: float, dur: float, target_i: float = LOUD_I) -> dict | None:
    """Primeira passada do loudnorm (so audio, rapido). None se falhar/silencio."""
    try:
        _rc, err = run(["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(source), "-vn", "-sn", "-dn",
                        "-af", f"loudnorm=I={target_i}:TP={LOUD_TP}:LRA={LOUD_LRA}:print_format=json",
                        "-f", "null", "-"], timeout=300)
    except FFmpegError as e:
        _log.info("loudnorm (medicao) falhou: %s", str(e)[-200:])
        return None
    m = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", err, re.S)
    if not m:
        return None
    try:
        d = json.loads(m[-1])
        if not all(k in d for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")):
            return None
        if "inf" in str(d["input_i"]).lower() or float(d["input_i"]) < -70:
            return None
        return d
    except (ValueError, json.JSONDecodeError):
        return None


def loudnorm_filter(measured: dict | None, target_i: float = LOUD_I) -> str:
    base = f"loudnorm=I={target_i}:TP={LOUD_TP}:LRA={LOUD_LRA}"
    if measured:
        base += (f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
                 f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
                 f":offset={measured['target_offset']}:linear=true")
    return base


# ------------------------------------------------------------------ frames
def extract_frame(video: str | Path, t: float, out: str | Path, width: int | None = None) -> Path:
    out = Path(out)
    vf = ["-vf", f"scale={width}:-2"] if width else []
    q = ["-q:v", "3"] if out.suffix.lower() in (".jpg", ".jpeg") else []
    run(["-ss", f"{max(0.0, t):.3f}", "-i", str(video), "-frames:v", "1", *vf, *q, str(out)], timeout=60)
    return out
