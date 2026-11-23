# Estilo visual dos cortes (modulo `fabrica/editor/`)

Pesquisa rapida (nov/2026) sobre o que os canais de cortes brasileiros e os Shorts/TikToks que
mais retem audiencia estao usando, mais as regras do dono e do guia `docs/ideias/criativo_genz.md`,
e as escolhas padrao que o editor implementa.

## O que funciona hoje (resumo da pesquisa)

- **Formato**: 1080x1920 (9:16), 30 fps, H.264 + AAC. Teto de 58 s (Short acima de 60 s com
  reivindicacao de direitos e bloqueado no YouTube).
- **Layouts comuns em cortes de podcast/live**
  - *Split*: podcast em cima, gameplay "hipnotico" ou video satisfatorio embaixo. Ainda segura o
    olho em podcast parado, mas saturou e virou cara de conta de corte em massa: usar como
    ferramenta (nunca em politica/noticia), nao como padrao.
  - *Fundo desfocado* (blur): video 16:9 inteiro no meio com copia ampliada e desfocada atras.
  - *Tela cheia* (crop 9:16): fonte vertical ou um rosto centralizado (close de podcast).
- **Legendas**: 2 palavras por tela (no maximo 3), CAIXA ALTA, fonte geometrica pesada
  (Montserrat Black), contorno preto grosso, palavra falada destacada numa cor que depende do
  nicho (o amarelo em tudo virou assinatura de corte generico), entrada com "pop" curto.
- **Titulo no topo**: caixa arredondada com texto pesado (estilo do texto nativo do TikTok) e
  emojis coloridos; em series, pilula "PARTE 2/4".
- **Zonas seguras** (fontes divergem; valores conservadores para TikTok + Shorts):
  topo ~150 px (abas, busca; a grade 3:4 do perfil corta ~240 px), base ~380-480 px (perfil,
  legenda do post, musica), direita ~120-160 px (coluna de botoes de y~1000 a ~1600).

Fontes: guias de safe zone (revid.ai, adaptlypost, quso.ai, merginit, Google Ads vertical specs),
guias de legenda para Shorts (opus.pro, blitzcutai, submagic, kapwing, captions.ai) e o guia
interno `docs/ideias/criativo_genz.md`.

## Padroes implementados

| Elemento | Padrao |
|---|---|
| Layout `auto` | fonte vertical -> `full`. Fonte horizontal: escolha estavel por corte (hash do `plan.id`) com pesos por nicho: politica/noticias -> full 60% / blur 40% (nunca split); games -> blur 60% / full 40%; resto -> split 40% / full 40% / blur 20%. Sem fundos -> sem split. `edicao.layout` fixo na config vence; senao vale `plan.layout`. |
| Split | video em cima (1080x960, preenche e corta o centro), fundo embaixo (1080x960) mudo, saturacao 0,92, brilho -0,04, offset aleatorio, loop se curto. Titulo na emenda (nao cobre o rosto), legenda sobre o fundo (y~1290) |
| Blur | video na largura 1080 centrado em y~860, fundo = reduz 270x480 -> boxblur -> amplia, escurecido e saturado; legenda logo abaixo do video |
| Full | crop central 9:16; legenda em y=1300 (abaixo do queixo num close de podcast) |
| Legenda | Montserrat Black, CAIXA ALTA, 2 palavras/tela, branco + palavra atual na cor do nicho, contorno preto (~7,5% do tamanho), sombra 50%, pop 75% -> 106% -> 100% em 130 ms, ate 2 linhas equilibradas, largura max 840-900 px; quebra em pausa > 0,6 s ou fim de frase; bloco minimo 0,30 s; sem emoji na legenda; "[Musica]"/"(risos)" removidos; palavroes com vogal mascarada ("P*RRA") |
| Tamanho | `edicao.legenda.tamanho` (padrao 90) x 1,25 = Fontsize ASS, x1,067 no full e x0,933 no blur |
| Cor de destaque | `cor_destaque: auto` -> politica `#00E5FF`, polemica/treta `#FF3B30`, humor `#FFE600`, games `#39FF88`, esportes/futebol `#C6FF00`, podcast `#FFD166`, celebridades `#FF4FD8`, noticias `#FF453A`, outros `#FFE600` |
| Titulo | `plan.hook` (ou `plan.title`) sem hashtags, ate 3 linhas equilibradas, topo em y=260. Tres variantes (escolha estavel por corte: nativo 50%, invertido 30%, contorno 20%; nichos de paleta escura trocam nativo por invertido): **nativo** = caixa branca por linha, texto preto Montserrat Black; **invertido** = caixa grafite 92%, texto branco, palavra-chave na cor do nicho; **contorno** = sem caixa, Anton branco com contorno preto e sombra, palavra-chave na cor do nicho |
| Emojis | ligados por padrao (`conteudo.emojis: true`): coloridos no titulo via Segoe UI Emoji (COLR) no Pillow; sequencias ZWJ/tom de pele/bandeiras via Twemoji (CC-BY 4.0) baixado sob demanda em `assets/emoji/`. Com `conteudo.emojis: false` o titulo sai so texto. Nunca em mensagens de terminal/log |
| Parte | pilula acima do titulo, 40 px, cor do nicho; "PARTE 2/3"; na ultima, "PARTE 3/3 \| FINAL" |
| Texto | travessoes e pontos medios/bolinhas sao trocados por "-" e "\|" em tudo que e desenhado |
| Barra de progresso | 8 px, logo abaixo do titulo e na largura dele, trilho branco 35%, preenchimento na cor do nicho; desligada em cortes de ate 35 s |
| Marca d'agua | `edicao.marca_dagua`, Montserrat ExtraBold 40, branco ~50%, logo abaixo da legenda |
| Audio | loudnorm -14 LUFS / -1,5 dBTP em 2 passadas (linear), AAC 192k 48 kHz estereo, fade de 40/80 ms nas pontas |
| Video | `encoder: auto` -> h264_amf (GPU AMD, vbr_peak 5/7 Mbit/s, preset balanced) se o teste passar; senao libx264 (`alta` = faster CRF 21, `media` = veryfast CRF 22, `rapida` = superfast CRF 23, teto 7/6/5 Mbit/s). GOP 2 s, yuv420p, +faststart, metadados removidos. libx264 com no maximo `edicao.threads` (padrao 8) threads |

## Edicao dinamica (editor v2)

Tudo na mesma passada do ffmpeg; cada recurso tem chave propria e vem ligado por padrao.
E a "transformacao" visivel que o YouTube (conteudo reutilizado/inautentico) e o TikTok (nao
original) cobram de canais de cortes (`docs/ideias/algoritmo_e_riscos.md`, secao 3.5).

| Recurso | Como funciona |
|---|---|
| Cold open (`cold_open`) | Se o cerebro preencher `plan.teaser_start/teaser_end`, os 1,5 a 3 s mais polemicos do proprio corte tocam primeiro (audio proprio, legenda com destaque vermelho vivo ou amarelo se o nicho ja e vermelho, 8% maior, punch-in 1,10x com leve avanco), depois flash branco de 0,17 s + whoosh procedural (~12 dB abaixo da voz) e o corte normal desde o inicio. Janela ajustada as palavras; se a frase for curta, puxa as palavras anteriores ate 1,5 s. Duracao total = teaser + corte, nunca acima de `corte.duracao_max_s` |
| Jump cuts (`cortar_silencios`) | Pausa maior que 0,40 s vira 0,12 s (0,07 s depois da fala + 0,05 s antes da proxima); o audio comeca na primeira palavra (pre-roll de no maximo 0,15 s); silencio depois da ultima fala/reacao sai (fica 0,25 s). A pausa e achada nos tempos do Whisper e confirmada pela energia do audio (limiar adaptativo entre ruido e voz), entao nunca corta dentro de palavra. Cortes na grade de quadros (1/30 s): audio e video com a mesma duracao em cada pedaco, sem deriva. Legenda retimada. Medido: mediana de 6 ms entre a legenda e a fala da saida |
| Zoom (`zooms`) | Entrada em 1,10x assentando em 1,00x (0,35 s). Troca seca entre 1,00 / 1,08 / 1,15 a cada 3 a 5 s, de preferencia num jump cut (esconde a emenda), num corte de camera ou fim de frase; nunca a menos de 0,9 s de um corte de camera. Enfase: +0,15 por ~0,6 s em 1 a 3 palavras fortes (CAIXA ALTA, "mentira", "absurdo", numeros, nomes, risada), 6 s entre elas. Ancorado nos olhos (o rosto nao sai do lugar). So no video principal (nunca no fundo do split) |
| Seguir rosto (`seguir_rosto`) | YuNet (OpenCV, `assets/modelos_visao/`, 230 KB) a 5 quadros/s em 320 px + deteccao de corte de camera a 10 quadros/s. Por plano: rosto mais presente e maior, desempate pelo movimento da boca. Enquadramento parado dentro do plano (so acompanha deriva grande, com transicao de 0,45 s), troca seca no corte de camera; sem rosto = centro. Vale para o full e a metade de cima do split; no blur so ancora o zoom. No full o titulo sobe ate a zona segura (y=150) se cobriria os olhos |
| Cartao de contexto (`cartao_contexto`) | ~2,2 s (depois do teaser, se houver): vidro escuro 87%, borda branca 15%, etiqueta "CONTEXTO" na cor do nicho + ate 2 linhas em Montserrat ExtraBold 30 a 42 px, emoji colorido se `conteudo.emojis`. Texto: `edicao.contexto_texto` > `plan.context` (se existir) > 1a frase da descricao, ate 60 caracteres, nunca igual ao titulo. Lugar escolhido para nao cobrir titulo, legenda nem o rosto (abaixo do titulo, acima da legenda ou acima do titulo) |
| CTA de serie (`cta_serie`) | So quando `part < parts_total`, nos 2,0 s finais: pilula 44 px na cor da pilula PARTE, rodizio estavel por corte entre "PARTE 2 NO PERFIL", "A RESPOSTA TA NA PARTE 2", "CONTINUA NA PARTE 2", "PARTE 2 JA TA NO PERFIL" (emoji so se ligado). Nunca "segue pra parte 2". Logo acima da legenda; sem espaco, logo abaixo |

Velocidade medida (trecho de 38 s, 1080p60, libx264 `media`, 8 threads, outros processos
rodando): full ~1,6x tempo real, split ~1,4 a 2,1x, blur ~1,2x; analise de rosto 2,5 a 4 s por
corte, jump cuts 0,2 s.

## Chaves novas de config (opcionais, lidas com `cfg.get(..., padrao)`)

```yaml
conteudo:
  emojis: true               # false = titulo so com texto
edicao:
  preferir_gpu: true         # false = libx264 mesmo com encoder=auto
  audio_kbps: 192
  titulo_estilo: auto        # auto | nativo | invertido | contorno
  titulo_maiusculas: false
  titulo_topo: 260           # y do topo do bloco de texto do titulo
  titulo_largura_max: 900
  titulo_na_emenda: true     # no split, titulo centralizado na emenda
  titulo_cor_caixa: ""       # so variante nativo ("" = branco)
  titulo_cor_texto: ""
  parte_tamanho: 40
  cor_parte: ""              # "" = cor do nicho
  cor_parte_texto: ""
  barra_altura: 8
  barra_min_s: 35            # cortes ate 35 s ficam sem barra
  barra_posicao: topo        # so quando nao ha titulo: topo | base
  split_proporcao: 0.5       # fracao da altura do video de cima no split (0.4 a 0.65)
  layout_pesos: {split: 0.4, full: 0.4, blur: 0.2}   # auto (exceto politica/noticias/games)
  fundo_pesos: {gameplay: 0.6, satisfying: 0.2, asmr: 0.1, procedural: 0.1}
  manter_temporarios: false  # true = nao apaga work/tmp/ed_* (depuracao)
  threads: 8                 # teto de threads do libx264/filtros/decodificacao
  # editor v2
  cold_open: true            # teaser com o momento polemico (precisa de plan.teaser_start)
  cold_open_max_s: 3.0
  cold_open_cor: ""          # "" = vermelho vivo (amarelo se o nicho ja e vermelho)
  cold_open_flash: true
  cold_open_whoosh: true
  cortar_silencios: true
  silencio_max_s: 0.40       # pausas maiores viram silencio_vira_s
  silencio_vira_s: 0.12
  pre_roll_max_s: 0.15
  final_apos_fala_s: 0.45
  zooms: true
  zoom_niveis: [1.0, 1.08, 1.15]
  zoom_intervalo_s: [3, 5]
  zoom_enfase: 1.15
  zoom_enfase_ligado: true
  zoom_impacto_inicio: true
  seguir_rosto: true
  cartao_contexto: true
  cartao_contexto_s: 2.2
  contexto_texto: ""         # forca o texto do cartao
  contexto_etiqueta: CONTEXTO
  cta_serie: true
  cta_serie_s: 2.0
  cta_tamanho: 44
  cta_serie_textos: []       # lista propria com {n} = proxima parte
  cta_cor: ""                # "" = cor da pilula PARTE do nicho
  cta_cor_texto: ""
  legenda:
    y: 0                     # forca o Y da legenda (0 = automatico por layout)
    censurar_palavroes: true
```

`edicao.legenda.estilo`: `karaoke` (padrao), `palavra` (uma palavra por vez, 15% maior) ou
`bloco` (grupo sem destaque).

## Biblioteca de fundos

`assets/fundos/<categoria>/` (gameplay, satisfying, asmr, procedural), ja no formato da metade de
baixo (720x640, 9:8, 30 fps, sem audio, tarjas pretas removidas). Creditos (titulo, url, canal,
licenca) em `assets/fundos/creditos.json`. Para incluir videos proprios basta copiar `.mp4` para a
pasta da categoria (qualquer tamanho; o editor escala e corta). Para baixar mais:
`backgrounds.download_pack(cfg, max_total_mb=...)` (so aceita videos cujo campo de licenca do
YouTube diga Creative Commons). O sorteio evita repetir os ultimos 8 arquivos usados.
