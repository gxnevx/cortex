"""Teste de fumaca do editor: baixa um trecho curto de podcast brasileiro, transcreve (Whisper tiny),
renderiza os 3 layouts e salva amostras (MP4 + quadros PNG) em work/amostras/.

Uso:
    .venv\\Scripts\\python.exe tests\\editor_smoke.py [--url URL] [--inicio 600] [--dur 60]
        [--layouts split,blur,full] [--encoder auto|libx264|h264_amf] [--bench] [--manter-fonte]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fabrica import paths, tools  # noqa: E402
from fabrica.config import load_config  # noqa: E402
from fabrica.models import ClipPlan, Segment, Transcript, Word  # noqa: E402

OUT = paths.WORK / "amostras"
SRC_DIR = paths.TMP / "smoke"
QUERIES = ["podpah podcast episodio completo", "flow podcast episodio completo", "podcast brasileiro entrevista"]


def _ydl_opts(**extra):
    o = {"quiet": True, "no_warnings": True, "noplaylist": True, "socket_timeout": 30}
    if tools.node():
        o["js_runtimes"] = {"node": {"path": tools.node()}}
    o.update(extra)
    return o


def find_source() -> tuple[str, str]:
    import yt_dlp

    for q in QUERIES:
        with yt_dlp.YoutubeDL(_ydl_opts(extract_flat="in_playlist")) as y:
            info = y.extract_info(f"ytsearch10:{q}", download=False)
        for e in info.get("entries") or []:
            if e and (e.get("duration") or 0) > 1200 and not e.get("live_status") == "is_live":
                return f"https://www.youtube.com/watch?v={e['id']}", e.get("title") or ""
    raise RuntimeError("nao achei video de podcast para teste")


def download_section(url: str, start: float, dur: float) -> Path:
    import yt_dlp
    from yt_dlp.utils import download_range_func

    SRC_DIR.mkdir(parents=True, exist_ok=True)
    dest = SRC_DIR / "fonte.mp4"
    if dest.exists():
        return dest
    opts = _ydl_opts(format="bv*[height<=1080][vcodec!*=av01]+ba/b[height<=1080]", merge_output_format="mp4",
                     outtmpl=str(SRC_DIR / "fonte.%(ext)s"),
                     download_ranges=download_range_func(None, [(start, start + dur)]),
                     force_keyframes_at_cuts=False)
    with yt_dlp.YoutubeDL(opts) as y:
        y.download([url])
    if not dest.exists():
        cand = [p for p in SRC_DIR.glob("fonte.*") if p.suffix not in (".part", ".ytdl")]
        if not cand:
            raise RuntimeError("download falhou")
        cand[0].rename(dest)
    mb = dest.stat().st_size / 1024 / 1024
    print(f"fonte: {dest} ({mb:.1f} MB)")
    if mb > 50:
        print("AVISO: fonte maior que 50 MB")
    return dest


def get_words(src: Path, dur: float) -> Transcript:
    cache = SRC_DIR / "transcricao.json"
    if cache.exists():
        return Transcript.from_dict(json.loads(cache.read_text(encoding="utf-8")))
    try:
        from faster_whisper import WhisperModel

        t0 = time.time()
        model = WhisperModel("tiny", device="cpu", compute_type="int8", download_root=str(paths.MODELS))
        # decodifica o audio com o ffmpeg (o decodificador PyAV do faster-whisper quebra com av>=15)
        import subprocess

        import numpy as np

        pcm = subprocess.run([tools.ffmpeg(), "-v", "error", "-i", str(src), "-t", f"{dur:.2f}", "-ac", "1",
                              "-ar", "16000", "-f", "f32le", "-"], capture_output=True, check=True).stdout
        audio = np.frombuffer(pcm, dtype=np.float32).copy()
        segs, _ = model.transcribe(audio, language="pt", word_timestamps=True, vad_filter=True)
        out = []
        for s in segs:
            if s.start >= dur:
                break
            out.append(Segment(s.start, s.end, s.text.strip(),
                               [Word(w.start, w.end, w.word.strip()) for w in (s.words or [])]))
        tr = Transcript(out, "pt", "whisper")
        print(f"whisper tiny: {len(tr.words())} palavras em {time.time() - t0:.1f}s")
    except Exception as e:  # noqa: BLE001
        print(f"whisper falhou ({e}); usando tempos falsos")
        text = ("entao mano eu cheguei la e o cara olhou pra mim e falou assim voce nao vai entrar "
                "e eu fiquei tipo como assim irmao serio mesmo") .split()
        words, t = [], 0.3
        while t < dur - 1:
            for w in text:
                if t >= dur - 1:
                    break
                words.append(Word(t, t + 0.28, w))
                t += 0.34
        tr = Transcript([Segment(0, dur, " ".join(w.text for w in words), words)], "pt", "fake")
    cache.write_text(json.dumps(tr.to_dict(), ensure_ascii=False), encoding="utf-8")
    return tr


def frames(video: Path, name: str, times: list[float]) -> list[Path]:
    from fabrica.editor import ffmpeg as ff

    outs = []
    for t in times:
        p = OUT / f"{name}_t{int(t):02d}.png"
        ff.extract_frame(video, t, p)
        outs.append(p)
    return outs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--inicio", type=float, default=900)
    ap.add_argument("--dur", type=float, default=58)
    ap.add_argument("--layouts", default="split,blur,full")
    ap.add_argument("--encoder", default=None)
    ap.add_argument("--bench", action="store_true", help="renderiza cada layout com libx264 e h264_amf")
    ap.add_argument("--manter-fonte", action="store_true")
    ap.add_argument("--marca", default="@fabricadecortes")
    ap.add_argument("--fundo", default=None, help="parte do nome do arquivo de fundo para o split")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    paths.ensure_dirs()
    OUT.mkdir(parents=True, exist_ok=True)
    from fabrica import editor
    from fabrica.editor import backgrounds

    cfg = load_config()
    cfg.set("edicao.marca_dagua", a.marca)
    if a.encoder:
        cfg.set("edicao.encoder", a.encoder)

    backgrounds.ensure_library(cfg)
    url = a.url
    title = ""
    if not (SRC_DIR / "fonte.mp4").exists():
        if not url:
            url, title = find_source()
        from fabrica.editor.style import strip_emojis

        print(f"video: {url}  {strip_emojis(title)}")
    src = download_section(url or "", a.inicio, a.dur + 2)
    info = editor.probe(src)
    print("probe:", info)
    dur = min(a.dur, info["duration"] - 0.5)
    tr = get_words(src, dur)

    plan = ClipPlan(id="amostra-c1", source_id="youtube:teste", start=0, end=dur,
                    title="O CLIMA ESQUENTOU 😳🔥", hook="", part=1, parts_total=3, category="podcast")
    results = {}
    encs = ["libx264", "h264_amf"] if a.bench else [None]
    for lay in a.layouts.split(","):
        for enc in encs:
            if enc:
                cfg.set("edicao.encoder", enc)
            suffix = f"_{enc}" if a.bench else ""
            out = OUT / f"amostra_{lay}{suffix}.mp4"
            cfg.set("edicao.titulo_estilo", {"split": "nativo", "blur": "invertido", "full": "contorno"}.get(lay, "auto"))
            t0 = time.time()
            forced = None
            if a.fundo and lay == "split":
                hit = [f for fs in backgrounds.library().values() for f in fs if a.fundo in f.name]
                forced = (hit[0], 20.0) if hit else None
            rc = editor.render_clip(src, 0.0, dur, plan, tr, cfg, out, layout=lay, background=forced)
            st = dict(editor.LAST_STATS)
            st["parede_s"] = round(time.time() - t0, 1)
            st["fundo"] = Path(rc.background).name if rc.background else None
            results[f"{lay}{suffix}"] = st
            print(f"{lay}{suffix}: {json.dumps(st, ensure_ascii=False)}")
            if not a.bench or enc == "libx264":
                frames(out, f"quadro_{lay}", [0.5, 12, 33])
    # comparativo lado a lado
    from fabrica.editor import ffmpeg as ff

    lays = [l for l in ("split", "blur", "full") if (OUT / f"quadro_{l}_t12.png").exists()]
    if lays:
        ins = []
        for l in lays:
            ins += ["-i", str(OUT / f"quadro_{l}_t12.png")]
        n = len(lays)
        fc = "".join(f"[{i}]scale=540:960[s{i}];" for i in range(n)) + "".join(f"[s{i}]" for i in range(n)) + \
            f"hstack=inputs={n}" if n > 1 else "[0]scale=540:960"
        ff.run([*ins, "-filter_complex", fc, str(OUT / "comparativo.png")])
    res_path = OUT / "resultado.json"
    try:
        old = json.loads(res_path.read_text(encoding="utf-8")) if res_path.exists() else {}
    except ValueError:
        old = {}
    old.update(results)
    res_path.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
    if not a.manter_fonte:
        shutil.rmtree(SRC_DIR, ignore_errors=True)
    print("ok ->", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
