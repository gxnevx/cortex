"""Teste do editor v2 (jump cuts, zooms, cartao de contexto, rosto, CTA de serie).

Baixa um trecho curto (<= 40 s) de podcast brasileiro, transcreve com o Whisper small,
renderiza os 3 layouts com tudo ligado (libx264, um ffmpeg por vez) e salva MP4 + quadros
em work/amostras/v2/. Tambem confere sincronia (legenda x fala) e o formato da saida.

Uso:
    .venv\\Scripts\\python.exe tests\\editor_v2.py [--url URL] [--inicio 1500] [--dur 38]
        [--layouts full,split,blur] [--so-preparar] [--limpar]
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

from fabrica import paths  # noqa: E402
from fabrica.config import load_config  # noqa: E402
from fabrica.models import Candidate, ClipPlan, Transcript  # noqa: E402

OUT = paths.WORK / "amostras" / "v2"
SRC_DIR = paths.TMP / "v2_fonte"
DEFAULT_URL = "https://www.youtube.com/watch?v=Xy5gwR172tI"   # Podpah #1104


def prepare(cfg, url: str, start: float, dur: float) -> tuple[Path, Transcript]:
    """Baixa o trecho (cache) e transcreve com o Whisper small (cache)."""
    from fabrica import download, transcribe

    SRC_DIR.mkdir(parents=True, exist_ok=True)
    src = SRC_DIR / "fonte.mp4"
    if not src.exists():
        vid = url.rsplit("v=", 1)[-1][:11]
        c = Candidate(id=f"youtube:{vid}", platform="youtube", url=url, title="teste")
        t0 = time.time()
        files = download.download_sections(c, [(start, start + dur)], cfg, SRC_DIR)
        Path(files[0]).replace(src)
        print(f"trecho baixado em {time.time() - t0:.1f}s ({src.stat().st_size / 1e6:.1f} MB)")
    cache = SRC_DIR / "transcricao.json"
    if cache.exists():
        tr = Transcript.from_dict(json.loads(cache.read_text(encoding="utf-8")))
    else:
        t0 = time.time()
        tr = transcribe.transcribe(src, cfg)
        cache.write_text(json.dumps(tr.to_dict(), ensure_ascii=False), encoding="utf-8")
        print(f"whisper: {len(tr.words())} palavras em {time.time() - t0:.1f}s")
    return src, tr


def loudest_phrase(src: Path, tr: Transcript, dur: float, win: float = 2.6) -> tuple[float, float, str]:
    """Simula o cerebro: janela de ~2,6 s (alinhada a palavras) com mais energia de voz."""
    import numpy as np

    from fabrica.editor import jumpcut

    db = jumpcut.audio_energy(src, 0, dur)
    words = [w for w in tr.words() if w.start > 3.0 and w.end < dur - 3.0]
    best = (-1e9, 0.0, 0.0, "")
    ends = (".", "!", "?", "…")
    for i, w in enumerate(words):
        if i > 0 and not words[i - 1].text.strip().endswith(ends):
            continue                                  # comeca no inicio de uma frase
        ws = [x for x in words[i:] if x.end - w.start <= win]
        while ws and not ws[-1].text.strip().endswith(ends):
            ws.pop()                                  # termina no fim de uma frase
        if len(ws) < 3 or ws[-1].end - w.start < 1.6:
            continue
        a, b = w.start, ws[-1].end
        seg = db[int(a * 100):int(b * 100)]
        score = float(np.mean(np.sort(seg)[-max(1, len(seg) // 3):]))
        if score > best[0]:
            best = (score, a, b, " ".join(x.text for x in ws))
    return best[1], best[2], best[3]


def frames(video: Path, name: str, times: list[float]) -> list[Path]:
    from fabrica.editor import ffmpeg as ff

    outs = []
    for t in times:
        p = OUT / f"{name}_{t:05.2f}s.jpg"
        ff.extract_frame(video, t, p, width=540)
        outs.append(p)
    return outs


def check_output(path: Path, expected: float) -> dict:
    import subprocess

    from fabrica import tools

    p = subprocess.run([tools.ffprobe(), "-v", "error", "-print_format", "json", "-show_streams", "-show_format",
                        str(path)], capture_output=True, text=True)
    d = json.loads(p.stdout)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    a = next(s for s in d["streams"] if s["codec_type"] == "audio")
    res = {
        "video": f"{v['codec_name']} {v['width']}x{v['height']} {v['avg_frame_rate']}",
        "audio": f"{a['codec_name']} {a['sample_rate']} {a['channels']}ch",
        "dur_video": round(float(v.get("duration", 0)), 3),
        "dur_audio": round(float(a.get("duration", 0)), 3),
        "dur_esperada": round(expected, 3),
        "mb": round(int(d["format"]["size"]) / 1e6, 1),
    }
    ok = (v["codec_name"] == "h264" and v["width"] == 1080 and v["height"] == 1920 and v["avg_frame_rate"] == "30/1"
          and a["codec_name"] == "aac" and abs(res["dur_video"] - expected) < 0.1
          and abs(res["dur_audio"] - res["dur_video"]) < 0.1)
    res["ok"] = ok
    return res


def sync_check(out_mp4: Path, retimed: Transcript, cfg) -> dict:
    """Transcreve a SAIDA e compara o inicio das palavras com a legenda retimada (deve bater)."""
    from fabrica import transcribe

    tr2 = transcribe.transcribe(out_mp4, cfg)
    a = [w for w in retimed.words()]
    b = [w for w in tr2.words()]

    def norm(s):
        return "".join(ch for ch in s.lower() if ch.isalnum())

    j = 0
    deltas = []
    for w in a:
        k = j
        while k < len(b) and k < j + 6:
            if norm(b[k].text) == norm(w.text) and len(norm(w.text)) >= 3:
                deltas.append(b[k].start - w.start)
                j = k + 1
                break
            k += 1
    deltas.sort()
    med = deltas[len(deltas) // 2] if deltas else None
    return {"pares": len(deltas), "mediana_s": round(med, 3) if med is not None else None,
            "p90_abs_s": round(sorted(abs(x) for x in deltas)[int(len(deltas) * 0.9)] if deltas else 0, 3)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--inicio", type=float, default=1500)
    ap.add_argument("--dur", type=float, default=38)
    ap.add_argument("--layouts", default="full,split,blur")
    ap.add_argument("--so-preparar", action="store_true")
    ap.add_argument("--sincronia", action="store_true", help="transcreve a saida e mede a sincronia")
    ap.add_argument("--quadros", default="0.3,1.2,2.4,6,11,17,24")
    ap.add_argument("--limpar", action="store_true", help="apaga o trecho baixado e sai")
    ap.add_argument("--sem-teaser", action="store_true", help="renderiza sem cold open")
    ap.add_argument("--fundo", default="minecraft-building", help="parte do nome do fundo do split")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    if a.limpar:
        shutil.rmtree(SRC_DIR, ignore_errors=True)
        print("trecho de teste apagado")
        return 0

    paths.ensure_dirs()
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    cfg.set("edicao.encoder", "libx264")
    cfg.set("edicao.qualidade", "media")
    src, tr = prepare(cfg, a.url, a.inicio, a.dur)
    if a.so_preparar:
        for w in tr.words()[:400]:
            print(f"{w.start:6.2f} {w.end:6.2f} {w.text}")
        return 0

    from fabrica import editor

    info = editor.probe(src)
    dur = min(a.dur, info["duration"] - 0.2)
    plan = ClipPlan(id="v2-amostra-c1", source_id="youtube:teste", start=0, end=dur,
                    title="Ela nao aguentou e contou TUDO 😳", hook="ELA CONTOU TUDO 😳",
                    description="Dia Freitas fala da vida de criadora no Podpah. Trecho do episodio #1104.",
                    category="podcast", part=1, parts_total=2)
    if not a.sem_teaser:
        ts, te, txt = loudest_phrase(src, tr, dur)
        plan.teaser_start, plan.teaser_end, plan.teaser_text = ts, te, txt
        print(f"teaser (frase mais intensa): {ts:.2f}-{te:.2f}s  {txt}")
    results = {}
    for lay in a.layouts.split(","):
        out = OUT / f"v2_{lay}.mp4"
        t0 = time.time()
        forced = None
        if lay == "split" and a.fundo:
            from fabrica.editor import backgrounds

            hit = [f for fs in backgrounds.library().values() for f in fs if a.fundo in f.name]
            forced = (hit[0], 30.0) if hit else None
        rc = editor.render_clip(src, 0.0, dur, plan, tr, cfg, out, layout=lay, background=forced)
        st = dict(editor.LAST_STATS)
        st["parede_s"] = round(time.time() - t0, 1)
        st["saida"] = check_output(out, rc.duration)
        results[lay] = st
        print(f"{lay}: {json.dumps(st, ensure_ascii=False)}")
        times = [float(x) for x in a.quadros.split(",")] + [max(0.0, rc.duration - 1.0)]
        frames(out, f"q_{lay}", [t for t in times if t < rc.duration])
        if a.sincronia and editor.LAST_CAPTIONS is not None:
            results[lay]["sincronia"] = sync_check(out, editor.LAST_CAPTIONS, cfg)
            print("sincronia:", results[lay]["sincronia"])
    res_path = OUT / "resultado.json"
    try:
        old = json.loads(res_path.read_text(encoding="utf-8")) if res_path.exists() else {}
    except ValueError:
        old = {}
    old.update(results)
    res_path.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
