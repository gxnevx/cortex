# Fabrica de Cortes - contratos entre modulos

Projeto Python 3.12 local para Windows 11 (CMD). Raiz: `<pasta do projeto>`.
Python do projeto: `<pasta do projeto>\.venv\Scripts\python.exe` (sempre use este).

## Fluxo de uma execucao (orquestrado por `fabrica/pipeline.py`)

```
collect_trends ─► brain.rank_trends ─► find_candidates ─► (para cada video)
   download.enrich_candidate ─► legendas da plataforma (parse_subtitles) OU audio+whisper (transcribe)
   ─► brain.pick_clips ─► download.download_sections (trechos com folga)
   ─► transcribe(trecho, start, end) [legenda palavra-a-palavra] ─► editor.render_clip
─► ranking final ─► publish.publish_batch (auto) ou fila de revisao ─► relatorio
```

## Ambiente da maquina (importante)
- Windows 11, CPU de 8 nucleos, video AMD integrado (SEM NVIDIA/CUDA).
- **Disco: so ~6 GB livres no C:.** Economize. Apague arquivos de teste. Nunca baixe videos inteiros longos.
- ffmpeg 9 (gyan full) no PATH: tem libass, drawtext, h264_amf (AMD), libx264.
- Node 24 no PATH (runtime JS para o yt-dlp). Chrome e Edge instalados.
- Ollama instalado (servidor desligado), modelos: so `gemma3:270m` e `bge-m3`.
- Claude Code CLI existe (`fabrica.tools.claude()`), mas NAO esta logado em modo terminal.
- Caminhos longos quebram (sem long path support). Mantenha caminhos curtos.

## Modulos compartilhados (NAO altere; se precisar de mudanca, descreva no seu relatorio final)
- `fabrica/paths.py` - todas as pastas (`paths.DOWNLOADS`, `paths.RENDERS`, `paths.MODELS`, `paths.BROWSER_PROFILE`, `paths.COOKIES_TXT`, `paths.SCREENSHOTS`, `paths.FONTS`, `paths.BACKGROUNDS`, `paths.STATE`, `paths.TMP` ...). `paths.ensure_dirs()`.
- `fabrica/config.py` - `load_config()` -> `Config`; use `cfg.get("secao.chave", padrao)`. Chaves em `config.yaml`. Se precisar de chave nova, leia com `cfg.get(..., padrao)` e liste no relatorio.
- `fabrica/models.py` - `Trend`, `Candidate`, `Word`, `Segment`, `Transcript`, `ClipPlan`, `RenderedClip`, `PostResult`, `NeedsUserAction`.
- `fabrica/db.py` - SQLite (`posts_today`, `already_posted`, `save_post`, ...).
- `fabrica/util.py` - `run_cmd`, `slugify`, `fmt_ts`, `retry`, ...
- `fabrica/tools.py` - `tools.ffmpeg()`, `tools.ffprobe()`, `tools.node()`, `tools.chrome()`, `tools.claude()`, `tools.ollama()`.
- `fabrica/log.py` - `log.get(__name__)`.

Mensagens para o usuario em portugues do Brasil. Codigo com nomes em ingles, comentarios curtos em PT.

## Contratos por modulo

### Descoberta - `fabrica/discovery/` + `fabrica/download.py`
```python
collect_trends(cfg) -> list[Trend]
find_candidates(cfg, trends=None, keywords=None, limit=15, exclude_ids=None) -> list[Candidate]

download.ytdlp_opts(cfg, **extra) -> dict
download.fetch_info(url, cfg) -> dict
download.enrich_candidate(c, cfg) -> Candidate        # duracao, views, extra["heatmap"], extra["chapters"], has_subtitles
download.download_platform_subtitles(c, cfg, dest_dir) -> Path | None   # prefere .json3 (tempo por palavra)
download.download_audio(c, cfg, dest_dir) -> Path
download.download_sections(c, sections: list[tuple[float, float]], cfg, dest_dir, max_height=1080) -> list[Path]
download.download_video(c, cfg, dest_dir, max_height=1080) -> Path
```
`download_sections`: o arquivo i cobre exatamente `sections[i]` (inicio em 0 = `sections[i][0]` do original).

### Transcricao - `fabrica/transcribe.py`
```python
parse_subtitles(path) -> Transcript                    # .json3/.vtt/.srt (remove duplicacao das legendas "rolantes" do YouTube)
transcribe(media, cfg, start=None, end=None, word_timestamps=True, language="pt") -> Transcript
    # tempos RELATIVOS a `start` (0 = start). faster-whisper CPU int8, modelo em paths.MODELS
```

### Cerebro - `fabrica/brain/`
```python
get_brain(cfg, force=None) -> Brain     # auto: claude (logado) -> ollama (rodando + modelo) -> heuristico
Brain.name: str
Brain.rank_trends(trends, cfg, limit=15) -> list[Trend]        # filtra/ordena, preenche category, reason, queries
Brain.pick_clips(video: Candidate, transcript: Transcript, cfg, max_clips=None) -> list[ClipPlan]
Brain.status() -> str
```
`ClipPlan.start/end` na linha do tempo do video ORIGINAL. Titulos estilo geracao Z com emojis.

### Editor - `fabrica/editor/`
```python
render_clip(source: Path, start: float, end: float, plan: ClipPlan, captions: Transcript | None,
            cfg, out_path: Path, layout: str | None = None) -> RenderedClip
    # start/end na linha do tempo de `source`; captions com tempos relativos a `start`.
    # Saida: MP4 1080x1920 30fps H.264 + AAC, faststart, audio normalizado.
probe(path) -> dict
backgrounds.ensure_library(cfg) -> dict[str, list[Path]]
fonts.ensure_fonts() -> dict[str, Path]
```

### Publicador - `fabrica/publish/`
```python
login(platform, cfg) -> bool            # abre Chrome com perfil proprio (paths.BROWSER_PROFILE); o USUARIO faz o login
check_login(platform, cfg) -> bool
publish_batch(clips: list[RenderedClip], cfg, platforms=None, dry_run=False, on_event=None) -> list[PostResult]
export_cookies_txt(cfg) -> Path | None  # cookies.txt (Netscape) para o yt-dlp
build_post_text(plan, platform, cfg, video_title=None, channel=None) -> tuple[str, str]   # (titulo, descricao/legenda)
```
`on_event(msg: str)` e um callback opcional para mostrar progresso no terminal.

## Regras para quem desenvolve
- Edite so os arquivos do seu modulo (+ `tests/<seu_modulo>_*.py`).
- Nunca faca login em conta nenhuma, nunca digite senha, nunca publique nada, nunca resolva captcha.
- Nao altere configuracoes do sistema; nao instale nada globalmente. `pip install` so no `.venv` e avise.
- Teste de verdade nesta maquina, com arquivos pequenos, e apague o que baixou para teste.
