"""Teste real: video estrangeiro -> Whisper (detecta idioma) -> legenda traduzida para PT-BR com tempo por palavra.

    python tests/legendas_traducao.py <url> <inicio_s> <duracao_s> [modelo]

Baixa so o trecho de audio (pasta work/tmp/ltrad), imprime original x portugues com tempos e apaga a midia.
Regra da maquina: espera nao haver outro ffmpeg.exe antes de cada job pesado; 1 job por vez.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fabrica import paths, transcribe, translate  # noqa: E402
from fabrica.config import load_config  # noqa: E402

DIR = paths.TMP / "ltrad"


def wait_no_ffmpeg() -> None:
    while True:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ffmpeg.exe", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, errors="replace").stdout
        if "ffmpeg.exe" not in out.lower():
            return
        print("  outro ffmpeg rodando; esperando 30 s...", flush=True)
        time.sleep(30)


def fetch_audio(url: str, start: float, dur: float, cfg) -> tuple[Path, dict]:
    """So o trecho de audio, pelo mesmo caminho do pipeline (download.download_audio com start/end)."""
    from fabrica import download
    from fabrica.models import Candidate

    info = download.fetch_info(url, cfg)
    c = Candidate(id=f"youtube:{info['id']}", platform="youtube", url=url, title=info.get("title") or "",
                  channel=info.get("channel") or "", duration=info.get("duration"))
    DIR.mkdir(parents=True, exist_ok=True)
    wait_no_ffmpeg()
    out = download.download_audio(c, cfg, DIR, start=start, end=start + dur)
    return out, info


def main() -> None:
    url, start, dur = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    model = sys.argv[4] if len(sys.argv) > 4 else None
    cfg = load_config()
    try:
        audio, info = fetch_audio(url, start, dur, cfg)
        print(f"video: {info.get('title')} | {info.get('channel')}")
        wait_no_ffmpeg()
        t0 = time.time()
        lang = translate.detect_language(audio, cfg)
        print(f"idioma (deteccao no audio): {lang}  [{time.time() - t0:.1f}s]")
        wait_no_ffmpeg()
        t0 = time.time()
        tr = transcribe.transcribe(audio, cfg, start=0, end=dur, language=None, model_name=model,
                                   prompt=transcribe.build_prompt(info.get("title") or "", info.get("channel") or ""))
        t_asr = time.time() - t0
        print(f"whisper: idioma {tr.language}, {len(tr.segments)} segmentos em {t_asr:.1f}s (RTF {t_asr / dur:.2f})")
        t0 = time.time()
        eng = translate.get_engine(cfg)
        print("motor de traducao:", eng.name if eng else "nenhum")
        pt = translate.to_portuguese(tr, cfg, context=f"{info.get('title')} ({info.get('channel')})")
        t_tr = time.time() - t0
        if pt is None:
            print("TRADUCAO FALHOU (o pipeline pularia este video)")
            return
        print(f"traducao em {t_tr:.1f}s\n")
        for a, b in zip(tr.segments, pt.segments):
            print(f"[{a.start:6.2f} - {a.end:6.2f}] {a.text}")
            print(f"{'':17s} {b.text}")
            print(f"{'':17s} " + " ".join(f"{w.text}@{w.start:.2f}" for w in b.words))
            print()
        ws = pt.words()
        assert all(w.end > w.start for w in ws)
        assert all(ws[i].end <= ws[i + 1].start + 1e-6 for i in range(len(ws) - 1))
        print(f"ok: {len(ws)} palavras PT, sem sobreposicao; total {t_asr + t_tr:.1f}s para {dur:.0f}s de video")
        title = translate.translate_text(info.get("title") or "", cfg)
        print("titulo traduzido:", title)
    finally:
        shutil.rmtree(DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
