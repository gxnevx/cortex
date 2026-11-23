# Ideias dos agentes: o que ja esta no CORTEX e o que vem depois

Pesquisas completas nesta pasta: `estrategia_conteudo.md` (o que cortar), `criativo_genz.md` + `.json` (como deixar jovem), `algoritmo_e_riscos.md` (crescimento, horarios, riscos).

## Ja aplicado

| Ideia | Origem | Onde |
|---|---|---|
| Cortes de no maximo 58 s (Short acima de 60 s com reivindicacao e bloqueado no mundo todo) | Gen Z + Algoritmo | `corte.duracao_max_s` |
| Series de no maximo 3 partes, Parte 1 sempre antes da 2 | Gen Z + Estrategia | `corte.max_partes`, ordem de publicacao |
| Aquecimento de conta nova (0, 1, 2, 3, 4 posts/dia por fase) | Algoritmo | `publicacao.aquecimento` |
| Intervalo minimo entre posts (2 h YouTube, 2 h 30 TikTok) e variacao aleatoria de 7 a 25 min | Algoritmo + Gen Z | `publicacao.intervalo_minimo_min`, `autopiloto.variacao_min` |
| Horario nobre por dia da semana (BRT) | Algoritmo | `autopiloto.horarios_nobres_semana` |
| Sem #viral e #fyp, 3 a 5 hashtags | Gen Z + Algoritmo | `publicacao.hashtags_fixas`, `max_hashtags` |
| No maximo 3 cortes do mesmo canal por dia | Gen Z | `corte.max_cortes_mesma_fonte_dia` |
| So publica sozinho nota 62 ou mais; abaixo disso espera aprovacao | Estrategia | `autopiloto.nota_minima_publicar` |
| Legenda de 2 palavras, tamanho 90, cor de destaque por nicho | Gen Z | `edicao.legenda` |
| Titulo com 1 ou 2 emojis, sem bolinhas nem travessoes | Gen Z + dono | cerebro e publicador |
| Canais que proibem cortes bloqueados (alanzoka, PodPeople, TV Senado, A Fazenda, CazeTV) | Estrategia | `busca.canais_bloqueados` |
| Pular apostas, jogos de futebol, filmes, clipes de musica | Estrategia + Algoritmo | `busca.pular_categorias` |
| Jogo em alta vira busca por resenha/podcast (nunca a partida) | Estrategia | `pipeline.adjust_trends` |
| Kick ligado (grandes streamers BR migraram), Reddit desligado (403) | Estrategia | `busca.fontes` |
| Camara dos Deputados como fonte (licenca CC BY 4.0) | Estrategia | `busca.canais_monitorados` |
| Modo semi no TikTok (voce clica em Publicar) | Algoritmo | `publicacao.tiktok_modo` |
| Captcha/verificacao pausa a rede e avisa (nunca burla) | Algoritmo | publicador + piloto |

## Proximos passos (roadmap)

| Ideia | Origem | Por que ainda nao |
|---|---|---|
| Via rapida: clipe da Twitch/Kick explodindo vira corte em menos de 60 min | Estrategia | precisa de um vigia a cada 5-10 min; o piloto hoje roda por ciclos |
| Timestamps citados nos comentarios e picos de chat como sinal (o heatmap quase nunca existe em video novo) | Estrategia | leitura de comentarios/chat ainda nao implementada |
| Velocidade relativa ao canal (views/hora vs mediana do proprio canal) | Estrategia | precisa de historico por canal |
| Checagem de saturacao (8+ canais ja cortaram = escolher o 2o/3o melhor momento) | Estrategia | busca extra por corte |
| Dois renders por momento: TikTok 62-95 s (monetiza) e Shorts ate 58 s | Estrategia + Algoritmo | dobra o tempo de edicao |
| Cartao de contexto de 2-3 s e comentario na tela (transformacao contra "conteudo reutilizado") | Algoritmo | recurso novo no editor |
| Ler metricas (24 h, 72 h, 7 d) do YouTube Studio/TikTok Studio e aprender o que funciona | Algoritmo | precisa das contas logadas |
| Saude da conta: 3 posts seguidos com menos de 10 views pausam 72 h | Algoritmo | depende das metricas |
| Lista de campanhas de cortes pagas (fontes autorizadas ganham +10 pontos) | Estrategia | voce preenche quando entrar em campanhas |
