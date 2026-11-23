# CORTEX: benchmark dos maiores canais de cortes do Brasil (23/11/2026)

> O que realmente funciona hoje para os grandes canais de cortes (YouTube Shorts e TikTok), medido com dados públicos, sem login e sem chave de API.
> Complementa `estrategia_conteudo.md` (o que cortar), `criativo_genz.md` (como deixar jovem) e `algoritmo_e_riscos.md` (horários, riscos). Onde os números daqui contradizem esses guias, isso está dito explicitamente.
> Arquivo para máquina: `docs/ideias/benchmark_canais.json`.

---

## 0. Resumo: os achados que mais mudam o resultado

1. **Os canais oficiais gigantes quase não vivem de Shorts.** Dos 18 canais com aba Shorts, só 10 postaram Short nos últimos 30 dias. Cortes do Inteligência (4,1 M de inscritos) não posta Short há 4 anos; Venus, RedCast, Gaules, Coringa e Casimito pararam há 2 a 20 meses. O carro-chefe deles é o corte horizontal de 8 a 20 min (Casimito: mediana de 786 mil views por vídeo longo contra 34 mil por Short).
2. **Quem ganha em Shorts hoje são canais "Shorts nativos" não oficiais.** @CyberCurioso.Cortes (169 mil inscritos), @SoUmClipeofc (61 mil) e @CortesPodCutsOficial (13 mil) fazem **2,2× a 4,1× o número de inscritos em views por Short (mediana)**, contra 0,1% a 3% na maioria dos oficiais. O padrão dos três: **1 post por dia**, **28 a 35 s**, acervo atemporal (talk show antigo, dublagem, curiosidades, TV dos anos 90/2000), título curto (28 a 36 caracteres) e quase sem emoji.
3. **Duração no YouTube tem forma de "U".** Nos canais ativos, Shorts de 21 a 40 s rendem 1,12× a 1,21× a mediana do próprio canal; **41 a 59 s caem para 0,77× a 0,88×** e só 12% dos de 51 a 59 s passam de 2× a mediana. A faixa 60 a 75 s rende 1,53×, mas é território dos donos do conteúdo (terceiro com reivindicação acima de 60 s é bloqueado no mundo todo).
4. **Horário: 21h a 24h é o horário mais forte e menos disputado no YouTube.** Shorts postados das 21h às 24h (BRT) rendem 1,36× a 2,34× a mediana de segunda a sexta. **18h a 21h é o pior horário útil (0,65× a 1,00× em dias úteis) e o mais lotado** (27% de todos os posts da amostra).
5. **Domingo e segunda são os melhores dias no YouTube** (1,48× e 1,22×); quarta, quinta e sexta ficam abaixo da mediana (0,91× a 0,95×). Os grandes postam menos no fim de semana (50 posts no sábado contra 88 na quinta), então há menos concorrência.
6. **No título, o que separa os 10% melhores é conflito com nome próprio, não enfeite.** Títulos com verbo de conflito ou acusação (humilhou, passou dos limites, destruiu, farsa, mentiu, armou) estão em **12% dos vencedores contra 3% do resto** (mediana de 1,72× o canal). Nome de pessoa aparece em 66% dos vencedores contra 53%.
7. **Aspas, exclamação e emoji não ajudam no YouTube.** Título entre aspas: 2% dos vencedores contra 7% do resto. "!": 12% contra 19%. Zero emoji em 90% dos vencedores; com 2 emojis a mediana cai para 0,87×. Palavrão (mesmo mascarado) é neutro (1,01×): não vale o risco.
8. **"Parte 1/2/3" praticamente não existe nos Shorts dos grandes:** 6 de 1.049 títulos (0,6%), sem ganho (1,03×). No TikTok aparece em 6% (séries longas de humor antigo).
9. **TikTok funciona em dois tamanhos:** "soco" de 7 a 20 s (Podpah, CazéTV e Coringa; os maiores virais da amostra têm 13 a 19 s e 1,3 M a 5,8 M de views) e "longo" de 60 a 180 s (debate, batalha de rima, storytime). O meio-termo de 46 a 59 s rende 0,89×. As maiores contas de TikTok postam **5 a 20 vezes por dia** (Jovem Pan 20, Charla 7,9, CazéTV 7,5, Podpah 5,3).
10. **Cold open (teaser no começo) não é o que faz os vencedores no Brasil hoje.** Em 24 vencedores transcritos, **0 abrem com teaser repetido**; 92% têm **fala em até 0,3 s**, e 25% abrem com pergunta direta (0% nos controles). Ver seção 7.

---

## 1. Método e amostra

**Data da coleta:** 23/11/2026, entre 09h40 e 10h20 (BRT). Tudo com dados públicos, sem login, sem cookies e sem chave de API.

**YouTube** (yt-dlp do projeto, `fabrica.download.ytdlp_opts`, com Node como runtime JS):
- 20 canais consultados; 18 têm aba Shorts (@CortesPodcast e @cazetv-cortes não têm).
- Para cada canal: lista dos **60 Shorts mais recentes** (título em pt e views), **30 vídeos longos mais recentes** (views e duração) e **metadados completos de uma amostra** (1 a cada 2 Shorts, ou 1 a cada 3 nos 4 canais extras): duração, data e hora exatas de publicação, views, likes, comentários, tags e descrição.
- Total: **1.049 Shorts** com título e views; **485 com metadados completos**. A hora dos Shorts sem metadados foi interpolada entre os vizinhos da lista (a lista é cronológica) só para calcular a idade; análises de horário usam apenas as 475 horas exatas.

**TikTok:**
- O perfil público do TikTok não lista vídeos para visitante sem login, e o yt-dlp é barrado pelo firewall (WAF) do TikTok. **Não tentamos contornar nenhum bloqueio.**
- Usamos o **widget oficial de incorporação** (`tiktok.com/embed/@perfil`), que mostra os 10 a 13 posts incorporáveis mais recentes, com legenda, views e data (a data sai do próprio ID do vídeo). Em 18 contas: **196 posts**.
- Para 90 desses posts, abrimos a página pública do vídeo num navegador comum, sem login, para ler duração, likes, comentários, compartilhamentos e salvamentos. Um bloqueio temporário (HTTP 403) apareceu depois de ~60 páginas; paramos, esperamos e seguimos com 1 página a cada ~5 s.
- Atenção: em 8 das 18 contas o widget mostrou posts antigos (de 1 mês a 3 anos). Ou a conta parou de postar no TikTok, ou os posts novos não são incorporáveis. Essas contas entram nas análises de título e duração, mas não nas de frequência atual.

**Volume de chamadas:** 485 metadados do YouTube + 92 páginas de vídeo do TikTok + 35 downloads de áudio (seção 7) = **612 chamadas pesadas**, com pausas de 0,6 a 5 s.

**Normalização (para comparar canal grande com pequeno):** cada vídeo recebe `razão = views / mediana de views dos Shorts do mesmo canal com 48 h ou mais` (TikTok: 24 h ou mais, sem os fixados). Razão 2,0 = o dobro do normal daquele canal. "Vencedores" ou "top 10%" = os 10% de maior razão: **YouTube razão ≥ 5,56 (105 de 1.034 Shorts maduros)**; **TikTok razão ≥ 10,0 (15 de 147)**. Tabelas mostram a **mediana da razão** e o número de vídeos (n).

**Horário:** convertido para BRT (UTC-3; o Brasil não tem horário de verão desde 2019).

### 1.1 Canais do YouTube

| Canal | Tipo | Inscritos | Shorts/dia | Último Short | Mediana de views por Short | Views/inscrito | Duração mediana (s) |
|---|---|---|---|---|---|---|---|
| @cortesdoflow | podcast, oficial | 3,27 M | 1,16 | 0,8 dia | 34,0 mil | 1,0% | 53 |
| @CortesPodpahOFICIAL | podcast, oficial | 3,04 M | 0,95 | 1,9 dia | 2,2 mil | 0,1% | 54 |
| @cortesdointeligencia | podcast, oficial | 4,12 M | parado | 4 anos | 16,8 mil | 0,4% | 48,5 |
| @CortesdoVenusOficial | podcast, oficial | 974 mil | parado | 20 meses | 9,2 mil | 0,9% | 49,5 |
| @CortesRedCast | podcast, oficial | 511 mil | parado | 7 meses | 8,2 mil | 1,6% | 56 |
| @CortesdoCasimitoOFICIAL | streamer, oficial | 4,03 M | 0,11 | 75 dias | 33,6 mil | 0,8% | 46,5 |
| @cortesloudcoringaoficial | streamer, oficial | 742 mil | 0,19 | 84 dias | 9,8 mil | 1,3% | 61,5 |
| @CortesdoGaulesOFICIAL | games, oficial | 112 mil | parado | 11 meses | 12,1 mil | 10,8% | 43,5 |
| @CortesdoDavyJones | games, oficial | 646 mil | 1,39 | 0,5 dia | 9,9 mil | 1,5% | 74,5 |
| @TicaracaticastCortes | humor, oficial | 1,38 M | 1,97 | 3,4 dias | 4,8 mil | 0,3% | 85,5 |
| @CortesdoLutzOFICIAL | humor, oficial | 704 mil | 1,15 | 0,5 dia | 1,5 mil | 0,2% | 72 |
| @cortespodcastpapagaiofalante | humor, oficial | 702 mil | 0,11 | 52 dias | 9,8 mil | 1,4% | 87,5 |
| @cortes247 | política | 757 mil | 0,02 | 12 meses | 318 mil (29 Shorts) | 42% | 59 |
| @CortesdoMBL | política | 522 mil | 0,30 | 2,9 dias | 14,4 mil | 2,8% | 71 |
| @CharlaPodcast | futebol (o próprio podcast) | 1,28 M | 0,94 | 3,9 dias | 2,7 mil | 0,2% | 81,5 |
| @CyberCurioso.Cortes | Shorts nativo, não oficial | 169 mil | 1,04 | 1,0 dia | **599 mil** | **354%** | 32 |
| @SoUmClipeofc | Shorts nativo, não oficial | 61,1 mil | 1,02 | 0,6 dia | **135 mil** | **221%** | 34,5 |
| @CortesPodCutsOficial | Shorts nativo, não oficial | 13,3 mil | 1,02 | 0,9 dia | **54 mil** | **406%** | 28,5 |

Viés de seleção: os 3 canais "Shorts nativos" foram achados numa busca do YouTube por Shorts da semana com muitas views. Eles representam **o que está dando certo agora**, não a média dos canais pequenos.

### 1.2 Contas do TikTok

| Conta | Tipo | Seguidores | Posts no widget | Com detalhe | Posts/dia (recente) | Mediana de views | Duração mediana (s) |
|---|---|---|---|---|---|---|---|
| @podpah | podcast | 6,8 M | 10 | 10 | 5,3 | 13,3 mil | 14 |
| @cazetv | futebol | 15,7 M | 13 | 10 | 7,5 | 22,4 mil | 15,5 |
| @charlapodcast | futebol | 566 mil | 10 | 10 | 7,9 | 1,8 mil | 61,5 |
| @jovempannews | notícias | 6,4 M | 10 | 5 | 20,1 | 3,4 mil | 59 |
| @cnnbrasil | notícias | 4,4 M | 10 | 0 | 5,3 | 33,9 mil | - |
| @mblivre | política | 433 mil | 10 | 10 | 1,2 | 26,9 mil | 97,5 |
| @ticaracaticast | humor | 428 mil | 10 | 10 | 1,8 | 395 | 81 |
| @podcast3irmaos | podcast | 401 mil | 13 | 10 | 1,0 | 1,4 mil | 158 |
| @loud_coringa | streamer | 11,2 M | 12 | 8 | parado (37 dias) | 3,1 M | 15 |
| @jonvlogs | streamer | 3,6 M | 10 | 0 | pausa (23 dias) | 943 mil | - |
| @denilsonshow | futebol | 1,7 M | 13 | 7 | pausa (13 dias) | 5,3 mil | 89 |
| @cortesdocasimiro | streamer, cortes oficial | 2,0 M | 10 | 10 | parado (19 meses) | 104 mil | 52,5 |
| @venuspodcast | podcast | 673 mil | 10 | 0 | parado (15 meses) | 14,7 mil | - |
| @gaules | games | 329 mil | 10 | 0 | parado (4 meses) | 14,3 mil | - |
| @inteligencialtda | podcast | 163 mil | 10 | 0 | parado (8 meses) | 3,2 mil | - |
| @cortesdoticaracaticast | humor, cortes | 331 mil | 13 | 0 | parado (12 meses) | 20,1 mil | - |
| @cortesdopanico | humor, cortes | 65 mil | 12 | 0 | parado (3 anos) | 57,1 mil | - |
| @choquei | fofoca | 2,4 M | 10 | 0 | widget antigo | 93,6 mil | - |

Achado lateral: no TikTok, quase todos os canais de cortes "oficiais" do YouTube (Cortes do Flow, Cortes Podpah, Cortes do Inteligência) **não existem ou são perfis de terceiros com 0 a 67 seguidores** (exceção: @cortesdocasimiro, 2 M, parado há 19 meses). Os podcasts postam os cortes no **perfil principal**.

---

## 2. Duração x desempenho

### 2.1 YouTube Shorts (mediana da razão; % = parte dos vídeos com 2× ou mais a mediana do canal)

| Duração | Canais ativos (n = 250) | Todos os canais (n = 475) |
|---|---|---|
| até 20 s | 2,05× (n = 3, 67%) | 1,69× (n = 12, 42%) |
| 21 a 30 s | **1,12× (n = 32, 34%)** | **1,35× (n = 60, 30%)** |
| 31 a 40 s | **1,21× (n = 42, 29%)** | 0,99× (n = 68, 22%) |
| 41 a 50 s | 0,88× (n = 20, 25%) | 0,69× (n = 54, 17%) |
| 51 a 59 s | 0,77× (n = 24, 12%) | 0,99× (n = 79, 23%) |
| 60 a 75 s | 1,53× (n = 45, 33%) | 1,24× (n = 78, 33%) |
| 76 a 90 s | 0,71× (n = 40, 17%) | 0,76× (n = 55, 25%) |
| 91 s ou mais | 0,92× (n = 44, 16%) | 1,04× (n = 69, 22%) |

- Durações publicadas (todos os canais): 10% até 26 s, mediana 56 s, 90% até 105 s. Os canais oficiais ativos publicam **53 a 86 s**; os Shorts nativos que mais crescem, **28 a 35 s**.
- Os 60 a 75 s que rendem bem são quase todos de canais **oficiais** (donos do conteúdo, sem risco de reivindicação). Para o CORTEX (terceiro), acima de 60 s qualquer reivindicação bloqueia o Short no mundo todo.
- **Conclusão para o CORTEX no YouTube: alvo de 22 a 40 s; teto de 45 s para o corte comum; 46 a 58 s só para storytime com desfecho forte.**

### 2.2 TikTok (n = 65 com duração; amostra pequena, tratar como direção)

| Duração | Mediana da razão | n | Observação |
|---|---|---|---|
| até 15 s | 1,06× | 16 | Podpah, CazéTV e Coringa; os 8 posts do Coringa (13 a 19 s) têm de 1,3 M a 5,8 M de views |
| 31 a 45 s | 2,78× | 5 | poucos casos |
| 46 a 59 s | 0,89× | 9 | o meio-termo é o pior |
| 60 a 75 s | 0,72× | 11 | variância enorme: batalha de rima do Podpah com 60 a 73 s fez 224 mil a 752 mil |
| 76 a 90 s | 1,11× | 9 | |
| 91 a 120 s | 0,89× | 6 | |
| 121 a 180 s | 2,53× | 7 | debate e política (MBL, 3 Irmãos) |

Durações publicadas no TikTok: 10% até 14 s, 25% até 21 s, mediana 62 s, 75% até 88 s. **É bimodal: ou soco curto, ou vídeo longo.**

---

## 3. Horário, dia da semana e frequência (BRT)

### 3.1 YouTube: mediana da razão por janela de 3 h (n / mediana)

| Dia | 09h a 12h | 12h a 15h | 15h a 18h | 18h a 21h | 21h a 24h |
|---|---|---|---|---|---|
| seg | 3 / 9,80 | 13 / 1,24 | 17 / 0,79 | 23 / 0,91 | 16 / **1,36** |
| ter | 8 / 0,77 | 13 / 1,06 | 19 / 0,63 | 14 / 1,00 | 16 / **1,72** |
| qua | 7 / 1,39 | 11 / **1,67** | 22 / 0,90 | 21 / 0,67 | 7 / **1,75** |
| qui | 9 / 1,19 | 26 / 0,89 | 15 / 1,11 | 26 / 0,65 | 6 / **1,64** |
| sex | 8 / 0,98 | 17 / 0,88 | 17 / 1,02 | 21 / 0,81 | 9 / **2,34** |
| sáb | 6 / 0,66 | 17 / 1,11 | 8 / **1,59** | 12 / 0,88 | 3 / 0,56 |
| dom | 6 / 1,38 | 15 / 1,08 | 4 / 0,51 | 10 / **2,00** | 4 / 1,67 |

Por faixa de 2 h (todos os dias): 22h a 24h = **1,73×** (n = 39); 10h a 12h = 1,36× (n = 40); 00h a 02h = 1,32× (n = 12); 20h a 22h = 1,28× (n = 77); 12h a 14h = 1,11× (n = 87); 18h a 20h = **0,78×** (n = 72); 08h a 10h = 0,69× (n = 13).
Parte dos vídeos que entram no top 10%: **16% dos postados às 21h a 24h** e 13% dos postados às 09h a 12h, contra 8% a 10% nas outras janelas.
Por dia: dom 1,48×; seg 1,22×; sáb 1,13×; ter 1,12×; sex 0,95×; qui 0,92×; qua 0,91×.

**Onde os grandes postam** (485 horas exatas): 12h a 14h (18%), 20h a 22h (16%), 18h a 20h (15%), 14h a 16h (14%). Quase nada antes das 10h. Fim de semana tem ~40% menos posts que quinta.

### 3.2 TikTok (n = 147, direção)

Por faixa: **20h a 22h = 2,25×** (n = 20); 10h a 12h = 1,34×; 14h a 16h = 1,20×; 18h a 20h = 0,91× (a faixa mais lotada, 34 posts); 06h a 08h = 0,72×.
Por dia: seg 1,62×; ter 1,30×; sex 1,13×; sáb 1,02× (mas sábado à noite tem os maiores picos: 18h a 24h com 2,95× e 5,63×); dom 0,97×; qui 0,93×; **qua 0,53×**.

### 3.3 Frequência

- **YouTube:** os canais ativos postam **0,9 a 2 Shorts por dia**. Os 3 Shorts nativos que mais crescem postam **exatamente ~1 por dia** (1,02 a 1,04).
- **TikTok:** as contas grandes de notícia e esporte postam **5 a 20 por dia**; podcasts e humor, 1 a 2.

---

## 4. Padrões de título

### 4.1 YouTube: vencedores (top 10%) x resto

| Métrica | Top 10% (n = 105) | Resto (n = 929) | Leitura |
|---|---|---|---|
| Tamanho (mediana) | 38 caracteres, 7 palavras | 37 caracteres, 7 palavras | igual |
| Título todo em CAPS | 67% | 70% | CAPS é o padrão do nicho, não diferencia |
| CAPS seletivo (2 a 4 palavras em CAPS no meio de minúsculas) | 13% | 7% | leve vantagem |
| Sem emoji | 90% | 87% | emoji não ajuda |
| 2 ou mais emojis | 4% | 5% | mediana 0,87× |
| Pergunta (?) | 19% | 20% | neutro |
| Exclamação (!) | 12% | 19% | pior |
| Aspas | 2% | 7% | pior |
| Reticências | 6% | 7% | mediana 0,75× |
| Hashtag no título | 32% | 34% | 3 hashtags no título: 0,80× |
| "Parte X" | 0% | 0,6% | quase ninguém usa |
| Número | 17% | 14% | leve vantagem |
| Nome de pessoa | 66% | 53% | vantagem |
| Verbo de conflito/acusação | 12% | 3% | **1,72×** |
| Taxa de comentário (mediana) | 0,03% | 0,06% | vencedor atinge público amplo, não só fã |
| Taxa de like | 4,0% | 3,8% | 2% a 8% é a faixa saudável; 8%+ = 0,71× (público de nicho) |

Nos Shorts **recentes** (até 180 dias), a diferença de emoji aumenta: 88% dos vencedores sem emoji contra 78% do resto; exclamação 5% contra 15%; aspas 3% contra 10%.

**Tamanho x desempenho (YouTube):** 61 a 80 caracteres = 1,44× (n = 80); até 30 = 0,99×; 31 a 45 = 1,00×; 46 a 60 = 0,89×.

**Primeira palavra (YouTube, mediana da razão):** nome próprio (Davy 4,9×, Wendel 1,57×, Briggs 1,30×, Coringa 1,28×), "dublador" 2,02×, **"quando" 1,62×**, **"quem" 1,45×**, "ele" 1,23×; neutras: "o" 1,00× (a mais comum, 11%), "a" 0,93×, "como" 0,92×; **piores: "não" 0,72× e "por" 0,56×**.

**Estilo por canal (o que cada um faz):** Flow, Davy, Inteligência, Ticaracaticast, Coringa, Gaules, RedCast, Charla, CortesPodCuts e CyberCurioso usam CAPS em 63% a 100% dos títulos; Podpah mistura (48%) e escreve curto (29 caracteres); SoUmClipe e Casimito usam frase normal com 1 a 3 hashtags de entidade; Venus e MBL usam CAPS seletivo; Lutz usa título longo (85 caracteres) em frase normal e é o de pior mediana do grupo (1,5 mil views com 704 mil inscritos).

### 4.2 TikTok: vencedores x resto

| Métrica | Top 10% (n = 15) | Resto (n = 132) |
|---|---|---|
| Tamanho da legenda (mediana) | 79 caracteres | 44,5 caracteres |
| Legenda toda em CAPS | 0% | 6% |
| CAPS seletivo | 40% | 18% |
| Sem emoji | 47% | 53% |
| Hashtags (média) | 1,7 | 2,0 |
| Taxa de like | **15,4%** | 7,9% |
| Taxa de comentário | 0,15% | 0,06% |

- Legendas longas e descritivas (manchete + contexto) ou curtíssimas em minúsculas ("veio com apetite 🥶", Podpah, 752 mil views). O que não funciona é a legenda genérica: Ticaracaticast repete "Assista o EP completo no link da bio" em todos os posts e tem mediana de 395 views com 428 mil seguidores.
- Hashtags: 4 hashtags = 1,30×; 0 = 1,00×. Hashtags de tema/entidade (#futebolbrasileiro 1,58×, #noticias 1,26×, #mbl 1,27×) batem hashtags genéricas (#humor 0,93×, #engraçado 0,70×).

### 4.3 Emojis

| Plataforma | Emoji | Títulos com ele | Mediana da razão |
|---|---|---|---|
| YouTube | 🤣 | 12 | **2,73×** |
| YouTube | 😂 | 18 | **1,61×** |
| YouTube | 🔥 | 9 | 1,44× |
| YouTube | 🚨 | 10 | 1,03× |
| YouTube | 👀 | 10 | 0,85× |
| YouTube | 😳 | 7 | 0,74× |
| TikTok | 🎙️ | 5 | 1,18× |
| TikTok | 👉 | 9 | 1,00× |
| TikTok | 🤣 | 8 | 0,78× |
| TikTok | 🔥 | 6 | 0,60× |

**Contradição com `criativo_genz.md`:** lá, 😂 e 🤣 estão em "evitar" (leitura millennial). No nicho de cortes BR do YouTube, eles aparecem associados a vencedores de humor (n pequeno, 30 títulos). Recomendação: **permitir 😂/🤣 em humor no YouTube**, sem tornar regra; 👀 e 😳, os mais usados pelo CORTEX hoje, ficaram abaixo da mediana.

### 4.4 Hashtags

- **YouTube:** #shorts está em 18% dos Shorts e rende 0,91× (não ajuda). As hashtags com melhor mediana são **de entidade e de acervo**: #sbt 6,41×, #silviosantos 6,13×, #danilogentilli 5,85×, #historia 2,41×, #thenoite 2,11×, #igor3k 1,86×, #guilhermebriggs 1,65×, #humor 1,53×. #viral (1,31×, n = 26) e #fyp (1,12×, n = 9) não mostram dano nem ganho claro (estão em canais que já iam bem); seguem fora por coerência anti-spam.
- **TikTok:** #futebolbrasileiro 1,58×, #mbl/#renansantos 1,27×, #noticias 1,26×; genéricas abaixo de 1.

---

## 5. O que os 10% melhores têm em comum

1. **Personagem conhecido + ação de conflito ou revelação**, nos primeiros 40 caracteres (nome de pessoa em 66%; verbo de conflito em 12%).
2. **Acervo atemporal e nostalgia** rendem demais em Shorts: TV antiga (SBT, The Noite, Silvio Santos), dublagem (Briggs, Wendel Bezerra), curiosidades. Os Shorts nativos que fazem 2 a 4× os inscritos vivem disso.
3. **Confissão em primeira pessoa** ("contei", "descobri", "terminei e me arrependi", "deram 6 meses de vida"): 4 dos 60 maiores outliers.
4. **Humor de humilhação ou zoeira entre famosos com KKKK** (Coringa, Ticaracaticast): a maior razão da amostra é um "humilhou ... KKKK" com 400× a mediana do canal.
5. **Duração curta (21 a 40 s) ou cheia (60 a 75 s), nunca o meio**.
6. **Fala no frame 0** (seção 7).
7. **Público amplo**: taxa de comentário menor (0,03% contra 0,06%) e taxa de like entre 2% e 8%.
8. **Postado às 21h a 24h ou de domingo/segunda.**

---

## 6. Texto polêmico nos títulos

Medido nos títulos vencedores (top 10%) contra o resto. Detecção automática por regras (nome = dicionário de nomes próprios do próprio conjunto de títulos; acusação = verbos como humilhou, mentiu, armou, destruiu, farsa, passou dos limites, ataca, traição; palavrão = lista + formas mascaradas como P*RRA, PUT@, C4GU3I).

| Recurso | YouTube top 10% | YouTube resto | Mediana com / sem | TikTok top 10% | TikTok resto |
|---|---|---|---|---|---|
| Citação direta entre aspas | 2% | 7% | 1,02× / 1,00× | 0% | 4% |
| Palavrão (inteiro ou mascarado) | 3% | 2% | 1,01× / 1,00× | 7% | 2% |
| Acusação / conflito | **12%** | 3% | **1,72× / 0,99×** | 7% | 5% |
| Nome de pessoa | **66%** | 53% | 1,04× / 0,95× | 73% | 69% |
| Pergunta (? ou quem/como/qual/existe) | 22% | 22% | 0,98× / 1,00× | 20% | 22% |
| KKKK | 6% | 6% | 1,09× / 1,00× | 0% | 5% |
| CAPS seletivo | 13% | 7% | 1,09× / 1,00× | 40% | 18% |

Leituras:
- **Acusação funciona, desde que atribuída** (quem acusa é o convidado, não o canal). É o único recurso "polêmico" com efeito claro.
- **Palavrão não traz ganho.** Quando aparece, vem mascarado em palavra sensível para anúncio (M*RT0, C4GU3I): é "algospeak" para não desmonetizar, não tempero.
- **Aspas atrapalham no YouTube**: o canal CyberCurioso põe a fala entre aspas em parte dos títulos e esses estão entre os piores do próprio canal (0,05× a 0,07×).
- **Pergunta é neutra**: depende do conteúdo, não do "?".

### 6.1 25 modelos reais de títulos vencedores (abstraídos)

Cada modelo vem de um título real do top 10% (canal e razão sobre a mediana do canal entre parênteses). Use os placeholders do `criativo_genz.json`.

| # | Modelo | Origem | Recurso |
|---|---|---|---|
| 1 | `{PESSOA} HUMILHOU {PESSOA2} KKKK` | @cortesloudcoringaoficial, 400× | acusação + nome + risada |
| 2 | `CONTEI para o BRASIL INTEIRO que {REVELACAO}` | @CortesdoVenusOficial, 185× | confissão, CAPS seletivo |
| 3 | `{PESSOA} É UM {ROTULO_FORTE}!` | @cortesdointeligencia, 152× | rótulo sobre pessoa |
| 4 | `{PESSOA} SOLTA O VERBO` | @CortesdoDavyJones, 93× | nome + conflito |
| 5 | `O TERROR DO {GRUPO}` | @CortesPodpahOFICIAL, 75× | identidade de grupo |
| 6 | `{ACAO} E ME ARREPENDI EM {N} DIAS` | @cortespodcastpapagaiofalante, 69× | confissão + número |
| 7 | `Tente não se emocionar...` | @SoUmClipeofc, 47× | desafio (usar raramente) |
| 8 | `A {COISA} mais {ADJETIVO} que você verá` | @cortesdoflow, 44× | superlativo |
| 9 | `Os mais {ADJETIVO} do Brasil` | @cortesdoflow, 43× | superlativo nacional |
| 10 | `Ele {ACAO_CHOCANTE} no meio do programa` | @SoUmClipeofc, 33× | bastidor de TV |
| 11 | `{PESSOA} NO {JOGO} KKKKKKKK` | @CortesdoDavyJones, 28× | games + risada |
| 12 | `{PROFISSAO} É TUDO {ROTULO} 😂` | @CortesPodCutsOficial, 26× | generalização bem-humorada |
| 13 | `{FAMOSO} ERA {ROTULO}?` | @cortespodcastpapagaiofalante, 21× | pergunta sobre ídolo |
| 14 | `ISSO É SER DE {LADO} NO BRASIL...?` | @CortesdoMBL, 19× | identidade política |
| 15 | `É POSSÍVEL {COISA_ABSURDA}?!` | @CortesdoVenusOficial, 60× | curiosidade absurda |
| 16 | `{PESSOA} se ABRE sobre {TEMA} com {PESSOA2}` | @CortesdoVenusOficial, 46× | revelação de celebridade |
| 17 | `{COISA_DO_DIA_A_DIA} é uma FARSA!` | @CortesdoVenusOficial, 42× | desmascarar |
| 18 | `O {GRUPO} DE {N} ANOS É SÓ UM {ROTULO}` | @CortesRedCast, 37× | opinião forte |
| 19 | `{PESSOA} PASSOU DOS LIMITES` | @CortesRedCast, 12× | acusação |
| 20 | `{PESSOA} CHAMOU {PESSOA2} DE {APELIDO} KKKK` | @cortesloudcoringaoficial, 10× | zoeira entre famosos |
| 21 | `QUANDO DESCOBRI {FATO_PESSOAL}` | @cortespodcastpapagaiofalante, 11× | confissão |
| 22 | `O QUE DESTRUIU {PESSOA}` | @CortesRedCast, 8× | curiosidade + queda |
| 23 | `{POLITICO} E {POLITICO2} SÃO IGUALMENTE {ADJETIVO}` | @CortesdoMBL, 7,5× | opinião atribuída |
| 24 | `{PESSOA} REVELA OS BASTIDORES DE {EVENTO_FAMOSO}` | @CharlaPodcast, 5,6× | bastidor + nostalgia |
| 25 | `Quem é o {PAPEL} mais {ADJETIVO} do Brasil?` | @SoUmClipeofc, 5,9× | pergunta-ranking |

TikTok (legenda): `{frase curta em minúsculas} {1 emoji}` (Podpah, 57×) e `{PESSOA} é o novo {CARGO} do {TIME}, rapaziada! 👀 E aí, o que acharam?` (Denilson Show, 42×).

---

## 7. Cold open (teaser no começo do corte)

**Pergunta:** os vencedores abrem com um teaser, isto é, os primeiros 1,5 a 3 s repetem um momento mais forte que aparece de novo mais tarde no mesmo corte?

**Método:** 25 Shorts do top 10% recente (até ~13 meses, no máximo 4 por canal, 11 canais) e 10 Shorts de controle (razão próxima de 1,0, 1 por canal). Para cada um, baixamos **só o áudio dos primeiros 60 s** (mediana de 0,8 MB), transcrevemos com faster-whisper `tiny` na CPU (`fabrica.transcribe.transcribe(..., model_name="tiny")`, uma transcrição por vez) e apagamos o áudio logo depois. Teaser = uma sequência de 4 ou mais palavras (ou 1 s ou mais de fala) dos 3 primeiros segundos que reaparece pelo menos 5 s depois, por igualdade exata ou por janela com semelhança de Jaccard de 0,6 ou mais. TikTok ficou de fora: o download é barrado pelo firewall do TikTok.

| Medida | Top 10% (n = 24 com fala) | Controle (n = 10) |
|---|---|---|
| Abre com teaser que reaparece depois | **0 de 24** | 0 de 10 |
| Coincidências descartadas (3 palavras comuns, 0,3 a 0,5 s; ou gagueira repetida 1,7 s depois) | 3 | 1 |
| Primeira palavra em até 0,3 s | **22 (92%)** | 8 (80%) |
| Primeira palavra em até 1 s | **24 (100%)** | 9 (90%) |
| Palavras nos 3 primeiros segundos (mediana) | 11,5 (cerca de 3,8 por segundo) | 10 |
| Abre com pergunta direta ("posso falar uma coisa...?", "o que é isso?") | **6 (25%)** | 0 |
| Abre em primeira pessoa contando ("eu cheguei...", "eu fui o cara que...") | **6 (25%)** | 1 (10%) |
| Abertura repete palavras do título | 3 (13%) | 2 (20%) |
| Tipo do momento na abertura (classificador por palavras) | 23 frase de impacto, 1 revelação; nenhum palavrão, briga ou choro nos 3 s iniciais | 10 frase de impacto |

**Conclusões:**
1. **Nenhum vencedor brasileiro da amostra usa cold open falado.** O que eles fazem é começar **já dentro da frase-gancho**, com fala no frame 0 (92%) e ritmo alto (quase 4 palavras por segundo).
2. As aberturas que mais diferenciam vencedores de controles são **pergunta direta a alguém** e **início de relato em primeira pessoa** (25% cada, contra 0% e 10%).
3. Briga, palavrão e choro não aparecem nos 3 segundos iniciais: quando existem, estão no meio ou no fim do corte (o clímax), não na abertura.
4. Para o CORTEX: o "teaser invertido" do `criativo_genz.md` (até 25% dos cortes) não tem respaldo no que os grandes fazem; **reduzir para no máximo 10% e só como teste A/B**. A regra que importa: **cortar o começo até a primeira palavra da frase-gancho** (pré-silêncio máximo de 0,3 s) e preferir trechos que abrem com pergunta ou com "eu" contando algo.
5. Limites: só os primeiros 60 s (Shorts acima disso podem ter um retorno depois), transcrição `tiny` erra palavras (por isso a regra de 4 palavras ou Jaccard), e um teaser só visual (cara de reação sem fala) não é detectado.

---

## 8. Regras para o CORTEX

### 8.1 Duração por plataforma

| Plataforma | Alvo | Aceitável | Evitar |
|---|---|---|---|
| YouTube Shorts | **22 a 40 s** | 15 a 45 s; 46 a 58 s só storytime com desfecho forte | 41 a 59 s "de enchimento" (0,77× a 0,88×); acima de 58 s (bloqueio por reivindicação) |
| TikTok, alcance | **8 a 20 s** (soco: reação, frase, lance) | até 30 s | 46 a 59 s (0,89×) |
| TikTok, monetização | **61 a 90 s** (storytime, debate, batalha) | até 150 s em debate/política | cortar no meio da história |

### 8.2 Janelas de postagem (BRT)

| Dia | YouTube | TikTok (direção) |
|---|---|---|
| seg | 12:00 a 14:00 e **21:00 a 23:30** | 18:00 a 21:00 |
| ter | 12:00 a 14:00 e **21:00 a 23:30** | 21:00 a 23:30 |
| qua | **12:00 a 14:30** e 21:00 a 23:30 | 09:00 a 12:00 (dia fraco: 0,53×) |
| qui | 10:00 a 12:00 e **21:00 a 23:30** | 12:00 a 14:00 e 21:00 a 23:00 |
| sex | 15:00 a 17:30 e **21:00 a 23:59** | 18:00 a 21:00 |
| sáb | 12:00 a 14:00 e **15:00 a 17:30** | **19:00 a 23:00** |
| dom | 10:00 a 12:00 e **18:30 a 21:30** | 15:00 a 18:00 |

Evitar: **18:00 a 20:30 em dias úteis** no YouTube (0,65× a 1,00× e a faixa mais lotada) e **antes das 10h** (0,66× a 0,69×).

### 8.3 Título

- **YouTube:** 25 a 45 caracteres (alvo), até 80 se for frase completa de contexto; **nome próprio nas 3 primeiras palavras**; CAPS total é aceito (padrão do nicho) ou CAPS seletivo em 2 a 4 palavras-chave; **0 emoji por padrão** (no máximo 1 em ~30% dos títulos: 🤣/😂 em humor, 🔥 em hype, 🚨 só em notícia de menos de 24 h); sem aspas; sem "!"; no máximo 1 hashtag no título e só de entidade (#silviosantos, #igor3k); sem #shorts.
- **Começar com:** nome da pessoa, "QUANDO", "QUEM" ou "ELE/ELA". **Evitar começar com** "NÃO" (0,72×) e "POR QUE" (0,56×).
- **TikTok:** legenda em frase normal ou minúsculas (nunca tudo em CAPS); duas formas que funcionam: curtíssima (2 a 5 palavras + 1 emoji) ou manchete com contexto (60 a 120 caracteres) e pergunta no fim; 3 a 4 hashtags de tema/entidade; nunca a mesma legenda genérica em todo post.
- **Conflito atribuído:** verbo de conflito (humilhou, expôs, passou dos limites, armou, destruiu, mentiu) sempre com o nome de quem faz a acusação e só se o trecho mostra isso (checagem anti-clickbait do `criativo_genz.md` continua valendo).

### 8.4 Modelos por categoria

Ver `titulos_modelos_por_categoria` no JSON (podcast, humor, games/streamer, futebol, política, celebridades, curiosidades/acervo, notícias), todos derivados de títulos vencedores desta amostra.

### 8.5 Evitar

1. Corte de 41 a 59 s no YouTube sem desfecho forte.
2. Postar às 18h a 20h30 em dia útil no YouTube; quarta no TikTok.
3. Título entre aspas, com "!", com reticências, com 2 ou mais emojis, com 3 ou mais hashtags.
4. 👀 e 😳 como emoji padrão (abaixo da mediana).
5. "Parte 1/2/3" em Shorts (ninguém usa; sem ganho).
6. Legenda genérica repetida ("assista o EP completo no link da bio").
7. Post de autopromoção ou agenda ("1 milhão de views, obrigado", "vote em", agenda da semana em foto): estão entre os piores de cada canal.
8. Palavrão no título (sem ganho, risco de anúncio limitado).
9. Corte de evento ao vivo que os oficiais já postaram em dezenas de versões; preferir acervo atemporal e ângulos que o oficial ignorou.
10. Silêncio, respiração ou vinheta antes da primeira palavra (92% dos vencedores falam em até 0,3 s) e "teaser invertido" como padrão (0 de 24 vencedores usam).

### 8.6 Abertura do corte

- Primeira palavra em até **0,3 s**; começar **dentro** da frase-gancho, não antes dela.
- Preferir trechos que abrem com **pergunta direta** a alguém ou com **relato em primeira pessoa** ("eu cheguei...", "eu fui...").
- Deixar o clímax (briga, palavrão, choro) no meio ou no fim; a abertura é a frase que faz querer ver o clímax.
- Teaser invertido: no máximo 10% dos cortes, só como teste A/B.

---

## 9. Mudanças recomendadas no `config.yaml`

| Chave | Hoje | Recomendado | Por quê |
|---|---|---|---|
| `autopiloto.horarios_nobres_semana.seg` | 12:00-13:30, 20:30-22:30 | `["12:00-14:00", "21:00-23:30"]` | 21h a 24h = 1,36× |
| `...ter` | 12:00-13:30, 20:30-22:30 | `["12:00-14:00", "21:00-23:30"]` | 21h a 24h = 1,72× |
| `...qua` | 12:00-13:30, 20:30-22:30 | `["12:00-14:30", "21:00-23:30"]` | almoço 1,67×; noite 1,75× |
| `...qui` | 12:00-13:30, 20:30-22:30 | `["10:00-12:00", "21:00-23:30"]` | almoço de quinta 0,89×; noite 1,64× |
| `...sex` | 12:00-13:30, 18:00-20:00 | `["15:00-17:30", "21:00-23:59"]` | 18h a 21h de sexta = 0,81×; 21h+ = 2,34× |
| `...sab` | 11:00-13:00, 20:00-23:00 | `["12:00-14:00", "15:00-17:30"]` | sábado à noite fraco no YouTube (0,56× a 0,88×) |
| `...dom` | 11:00-13:00, 19:00-22:00 | `["10:00-12:00", "18:30-21:30"]` | domingo 18h a 21h = 2,00× |
| `autopiloto.janela_publicacao` | 08:00 a 00:30 | `["09:30", "00:30"]` | antes das 10h rende 0,66× a 0,69× |
| `publicacao.max_posts_por_dia.youtube` | 4 | **2** | quem mais cresce em Shorts posta ~1 por dia; volume não é o diferencial |
| `publicacao.max_posts_por_dia.tiktok` | 4 | 4 (subir para 6 só depois do dia 43, se as métricas ajudarem) | contas grandes postam 5 a 20 por dia |
| `publicacao.intervalo_minimo_min.youtube` | 120 | **300** | com 2 posts, um no almoço e um às 21h+ |
| `publicacao.max_hashtags` | 5 | **3** | 3+ hashtags no título do YouTube = 0,80×; TikTok rende bem com 3 a 4 |
| `corte.duracao_min_s` | 20 | **15** | até 20 s = 1,69× a 2,05× (n pequeno) |
| `corte.duracao_max_s` | 58 | **45** | 41 a 59 s = 0,77× a 0,88× nos canais ativos |
| `corte.permitir_series` | true | **false** | 0,6% dos Shorts dos grandes usam "Parte"; sem ganho |
| `corte.duracao_parte_s` | 50 | 40 (se séries forem mantidas) | mesma lógica da duração |

Quando o CORTEX tiver render separado por plataforma (roadmap): YouTube 22 a 40 s; TikTok 8 a 20 s (alcance) ou 61 a 90 s (monetização).

---

## 10. Limitações

- Views de Shorts antigos acumulam por meses; a razão compara cada vídeo com o próprio canal, mas canais parados há anos (Inteligência, Venus) pesam na análise de título e duração. Por isso as tabelas de duração trazem também o recorte "canais ativos".
- TikTok: amostra pequena (147 posts maduros, 65 com duração) e enviesada para o que o widget mostra. Use como direção, não como regra.
- Correlação não é causa: os Shorts nativos escolhem acervo forte e postam curto; não dá para separar o efeito da duração do efeito da escolha do momento.
- A partir de 24/08/2026 o YouTube conta view pública desde o 1º frame; Shorts recentes e antigos usam métricas um pouco diferentes.
- Nenhum login, nenhum desvio de bloqueio. O que não estava público ficou de fora.
