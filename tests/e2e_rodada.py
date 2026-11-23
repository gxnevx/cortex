"""Teste ponta a ponta SEM publicar: pega um video curto em PT-BR, corta, legenda e edita.

Uso:
    python tests/e2e_rodada.py                 # procura um video curto sozinho
    python tests/e2e_rodada.py <url>           # usa o link dado
    python tests/e2e_rodada.py --trends        # rodada completa por tendencias (1 video)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fabrica import log, paths, ui  # noqa: E402
from fabrica.config import load_config  # noqa: E402
from fabrica.pipeline import RunOptions, run  # noqa: E402
from fabrica.report import print_summary  # noqa: E402


def find_short_video(cfg) -> str:
    import yt_dlp

    from fabrica import download

    opts = download.ytdlp_opts(cfg, extract_flat=True)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info("ytsearch15:podcast entrevista polêmica corte completo", download=False)
    for e in info.get("entries") or []:
        d = e.get("duration") or 0
        if 240 <= d <= 900:
            return e.get("url") or f"https://www.youtube.com/watch?v={e['id']}"
    raise SystemExit("nao achei video curto")


def main():
    log.setup(verbose=False)
    paths.ensure_dirs()
    cfg = load_config()
    cfg.set("execucao.max_cortes_por_execucao", 2)
    cfg.set("execucao.cortes_por_video", 2)
    brain = None
    for a in sys.argv[1:]:
        if a.startswith("--cerebro="):
            brain = a.split("=", 1)[1]
    args = [a for a in sys.argv[1:] if not a.startswith("--cerebro=")]
    if "--trends" in args:
        opts = RunOptions(trigger="manual", search_mode="trends", n_videos=1, publish_mode="nao_publicar",
                          interactive=False, brain=brain)
    else:
        url = args[0] if args else find_short_video(cfg)
        ui.info(f"Video de teste: {url}")
        opts = RunOptions(trigger="manual", urls=[url], n_videos=1, publish_mode="nao_publicar",
                          interactive=False, brain=brain or "heuristico")
    summary = run(cfg, opts, ui.Reporter())
    print_summary(summary)
    ok = bool(summary["clips"]) and all(Path(c["path"]).exists() for c in summary["clips"])
    print("E2E OK" if ok else "E2E FALHOU")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
