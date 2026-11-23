# Arquitetura

```
fabrica.bat ──► python -m fabrica ──► cli.py (menu ASCII / subcomandos)
                                         │
                                         ▼
                                   pipeline.run()
   ┌───────────────┬───────────────┬──────────────┬───────────────┬──────────────┐
   ▼               ▼               ▼              ▼               ▼              ▼
discovery/     download.py     transcribe.py   brain/          editor/       publish/
tendencias     yt-dlp: info,   legendas da     claude_cli      ffmpeg 9:16   Chrome com perfil
+ busca de     legendas,       plataforma ou   ollama          layouts       proprio (Playwright)
videos-fonte   audio, trechos  faster-whisper  heuristico      legendas ASS  YouTube Studio
                                               + signals.py    titulo/emoji  TikTok Studio
                                                                fundos
   └───────────────┴───────────────┴──────┬───────┴───────────────┴──────────────┘
                                          ▼
                     db.py (SQLite)  |  report.py (HTML)  |  notify.py (toast)
                     storage.py (limpeza de disco)  |  scheduler.py (Agendador do Windows)
```

## Etapas de uma rodada

1. **Preparo** - limpeza de disco, checagem de espaco, escolha do cerebro (Claude > Ollama > heuristico).
2. **Descoberta** - `collect_trends` (Google Trends, Google Noticias, X via trends24, Reddit, YouTube, Twitch) → o cerebro filtra o que rende corte e cria buscas → `find_candidates` busca videos recentes e pontua (velocidade de views, engajamento, frescor, canal grande, clipes da Twitch).
3. **Corte e edicao** (por video, em sequencia):
   - legenda da plataforma (rapido) ou Whisper; em lives longas sem legenda, transcreve so os "momentos quentes" (heatmap, clipes, picos de volume);
   - cerebro escolhe os trechos (nota 0-100, motivo, titulo com emojis, series "Parte X");
   - baixa **so os trechos** (com 1,5 s de folga);
   - Whisper no trecho para legenda palavra-a-palavra;
   - `render_clip` gera o MP4 1080x1920.
4. **Publicacao** - `auto`: publica em ordem (series em sequencia) respeitando limites diarios; `revisar`: fila de revisao (`fabrica revisar`); `nao_publicar`: so salva.
5. **Relatorio** - HTML em `relatorios/`, notificacao do Windows, historico no SQLite.

## Estados no banco
- videos: `encontrado → processando → processado | falhou | ignorado`
- clips: `planejado → renderizado → aprovado → publicado | falhou | rejeitado | expirado`

## Tolerancia a falhas
- Cada fonte de tendencia falha sozinha sem derrubar a rodada.
- Se o cerebro (Claude/Ollama) falhar num video, o heuristico assume.
- Um video com erro e pulado; a rodada segue para o proximo candidato.
- Captcha/verificacao/login → para a publicacao daquela rede e vira "ACAO NECESSARIA" no relatorio.
- Trava de rodada (`data/estado/rodada.lock`) impede duas rodadas ao mesmo tempo.
