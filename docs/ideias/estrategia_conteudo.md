# CORTEX: como achar O MELHOR conteúdo para cortar no Brasil (nov/2026)

> Documento de estratégia de conteúdo (fontes, nichos, sinais de viralidade, seleção de momentos, velocidade, campanhas pagas e riscos).
> Complementa `algoritmo_e_riscos.md` (aquecimento, horários, monetização, direitos autorais) e `criativo_genz.md` (ganchos, títulos, visual, séries). Onde os três se sobrepõem, os números foram alinhados.
>
> **Legenda de confiança:** **[OFICIAL]** = página da plataforma, lei ou órgão público · **[MEDIDO]** = medido por nós em 23/11/2026 com yt-dlp/APIs públicas, sem login · **[IMPRENSA]** = veículo jornalístico · **[MERCADO]** = blog de fornecedor (interesse comercial, tratar como indício) · **[INFERÊNCIA]** = recomendação nossa a partir dos dados.

---

## 0. Resumo executivo (o que mais muda o resultado)

1. **O gargalo não é editar, é escolher.** Em 2026, os grandes podcasts e streamers já têm canais de cortes **oficiais** gigantes (Cortes do Inteligência 4,1 M de inscritos, Cortes do Casimito 4,0 M, Cortes do Flow 3,3 M, Cortes Podpah 3,0 M) [MEDIDO]. Ganhar deles no "momento óbvio" é difícil. O CORTEX ganha em **velocidade**, **ângulo** e **fontes médias sem canal oficial de cortes**.
2. **O "mais repetidos" do YouTube não existe em vídeo novo.** Em ~90 vídeos amostrados, **nenhum com menos de ~50 dias tinha heatmap**, nem vídeos com 5 M de views [MEDIDO]. Para conteúdo fresco, os sinais que funcionam são: **clipes da Twitch/Kick**, **timestamps citados nos comentários**, **picos no chat** e **velocidade de views via RSS**.
3. **Kick virou fonte principal de streamers BR de entretenimento.** Coringa (1,37 M seguidores na Kick), Paulinho o Loko, Gaules, TcK10 e Jon Vlogs transmitem/multitransmitem na Kick; vários estavam sem clipes na Twitch nos últimos 7 dias [MEDIDO]. A API pública da Kick responde sem chave.
4. **Política: a fonte mais segura e menos explorada é a Câmara dos Deputados.** As transmissões de atividades legislativas estão sob **Creative Commons BY 4.0** (uso comercial permitido, com crédito e marca d'água mantida) [OFICIAL]. A TV Senado, ao contrário, **proíbe uso comercial e edição** [OFICIAL].
5. **Futebol: nunca a imagem do jogo.** A Lei Geral do Esporte só libera flagrantes para **noticiário**, até **3% do tempo e no máximo 30 s**, sem patrocínio [OFICIAL]. Corte o podcast, a coletiva ou a reação do streamer, não a transmissão.
6. **Reality (A Fazenda 18 no ar agora; BBB 27 em janeiro): só via terceiros comentando.** Globo derruba vídeos e perfis; o feed da Record/PlayPlus é dela [IMPRENSA].
7. **Plataformas apertaram o cerco ao conteúdo reaproveitado em 2026:** YouTube (16/07/2026, conteúdo "templated"/em massa não monetiza; out/2026, Shorts reaproveitados perdem alcance) e TikTok (conteúdo sem edição criativa fora do Para Você) [OFICIAL/IMPRENSA]. Cada corte precisa de **camada de contexto** (ver `algoritmo_e_riscos.md` §3.5).
8. **Velocidade:** para momento de live, a janela útil é **30 a 90 min** até o feed saturar; para episódio de podcast, as primeiras **4 a 6 h** [MERCADO]. A agenda atual (4 rodadas/dia) é lenta demais: precisa de um **"vigia" contínuo**.
9. **Campanhas pagas existem, mas pagam pouco no BR** (campanhas "Brazil Clips" no Content Rewards a **US$ 0,25 a 0,30 por mil views**) [MERCADO/página da plataforma]. Vale integrar como **lista de fontes autorizadas + bônus de pontuação**, não como modelo de negócio principal.
10. **Ler a descrição do canal-fonte automaticamente.** Ex.: alanzoka escreve na descrição "Não autorizo o uso desses vídeos [...] em outro canal" [MEDIDO]. Um regex simples evita strikes.

---

## 1. O que mudou entre 2025 e nov/2026 (e o impacto no CORTEX)

| Data | Mudança | Impacto no CORTEX |
|---|---|---|
| 21/07/2025 | YouTube removeu a página **Em alta (Trending)** e trocou por paradas por categoria [IMPRENSA] | Não existe mais "trending geral" para raspar. Usar Google Trends RSS, trends24, Google Notícias, RSS de canais e busca do YouTube. |
| 26/06/2025 | STF declarou o art. 19 do Marco Civil parcialmente inconstitucional: plataformas respondem após **notificação extrajudicial** em vários casos [IMPRENSA/STF] | Plataformas removem mais rápido quando notificadas. Cortes difamatórios ou fora de contexto caem e podem gerar ação. |
| 17/03/2026 | **ECA Digital** (Lei 15.211/2025) em vigor; multas de até R$ 50 M por infração para plataformas [IMPRENSA] | Conteúdo com menores tende a ser derrubado/limitado. Evitar. |
| 16/07/2026 | YouTube detalhou o que é "conteúdo inautêntico": **repetitivo/templated**, produzido em massa, e conteúdo feito para chocar [IMPRENSA, TechCrunch] | Variar template, adicionar contexto, nunca postar 20 cortes idênticos no formato. |
| 24/08/2026 | YouTube passou a contar view pública a partir do 1º frame; o "engaged view" antigo segue valendo para YPP [OFICIAL] | Velocidade de views de Shorts ficou inflada. Para medir concorrentes, comparar sempre com a mesma métrica. |
| set/2026 | Twitch: clipes no programa de DJ sem a música licenciada [MERCADO] | Sinal de que plataformas querem cortes, mas sem música. |
| ~02/10/2026 | YouTube: recomendação de Shorts passa a favorecer original; canais "repost-heavy" perdem alcance [IMPRENSA, Digital Trends] | Reforça a camada de transformação. |
| 13/11/2026 | TwitchCon: clipes da Twitch vão de 60 s para **5 min** (sem data) e o "hosting" volta [IMPRENSA] | Quando sair, um clipe da Twitch já vira um corte TikTok >1 min. |
| nov/2026 | **GTA VI lançado (~19/11/2026)**; domina as lives (Kick/Twitch/YouTube) [MEDIDO: títulos "GTA 6 dia 5" em 23/11] | Pico de demanda em games agora, mas **rádio do GTA tem música licenciada** (Content ID). |
| sempre | Shorts > 1 min com **qualquer** claim de Content ID ficam **bloqueados no mundo todo** [OFICIAL] | YouTube: manter ≤ 58 s (alinhado com `algoritmo_e_riscos.md`). |

**Achados técnicos nossos (23/11/2026) [MEDIDO]:**
- **Heatmap ("mais repetidos")**: nenhum dos ~80 vídeos com idade entre 5 h e ~53 dias tinha heatmap (incluindo Podpah com 2,2 M e 3,2 M views e alanzoka com 5,1 M). Os que tinham (100 pontos) eram de ~55+ dias **e** com dezenas de milhares de views; vídeos antigos com poucas views continuavam sem. Ou o YouTube passou a gerar o gráfico muito tarde, ou a extração mudou. **Para o fluxo diário, tratar o heatmap como ausente.** Usar só no "garimpo de acervo" (vídeos antigos) e registrar no log quantos candidatos vêm com heatmap, para perceber se isso mudar.
- **Legendas automáticas em pt**: presentes num vídeo de ~14 h e nos mais antigos; ausentes num upload de ~3 h (92 min). Para lives recém-terminadas, contar com o Whisper nos trechos quentes.
- **Comentários com timestamp**: entre os 300 comentários "top", 3% a 8% citam um horário do vídeo. Buscar 300 comentários leva de 3 a 9 s com yt-dlp. Os clusters apontam momentos (ex.: minuto 113 e 114 no GTA do alanzoka).
- **RSS do canal do YouTube** (`/feeds/videos.xml?channel_id=...`) funciona sem chave e traz `media:statistics views` de cada vídeo → dá para medir **velocidade real** (Δviews/Δtempo) com 1 requisição a cada 10 min por canal.
- **API pública da Kick** (`kick.com/api/v2/channels/{slug}` e `/clips?sort=view&time=week`) responde sem chave, com seguidores, status ao vivo e clipes da semana (Kick aceita clipes de até ~180 s).
- **Reddit**: `reddit.com/r/brasil/hot.json` deu **403** e o `.rss` deu 404 desta máquina. A fonte "reddit" provavelmente falha em silêncio. Rebaixar ou desligar até ter outra via.
- **Google Trends RSS (BR)**: só **10 itens**, com tráfego aproximado grosseiro ("100+", "1000+"). Às 04h UTC estava cheio de NBA/NFL. Precisa de filtro "dá corte?" (pessoa/programa com vídeo em pt).

---

## 2. Nichos: o que performa, o que está saturado e o que está mal servido

Escala: Demanda (procura do público) · Saturação (concorrência de canais de cortes) · Risco (direitos autorais/marca/política).

| Nicho | Demanda | Saturação | Risco | Veredito para o CORTEX |
|---|---|---|---|---|
| **Podcasts grandes** (Podpah, Flow, Inteligência Ltda, Venus, Ticaracaticast, 3 Irmãos, PodPeople) | Altíssima | **Altíssima**: todos têm canal **[OFICIAL]** de cortes; na busca "cortes podpah", 19 de 20 resultados são do oficial [MEDIDO] | Médio a alto: donos monetizam os cortes; Podpah aplicou strikes em canais críticos (mar/2025) [Wikipédia/IMPRENSA]; PodPeople **revogou** a permissão de cortes em 01/01/2026 [OFICIAL, aviso no site] | Usar como **sinal** (o que o oficial postou e quanto viralizou) e cortar só **ângulos diferentes** ou episódios ignorados pelo oficial. Não basear o canal nisso. |
| **Streamers de entretenimento/IRL** (Kick: Coringa, Paulinho o Loko, Jon Vlogs + Bonde do Jon, TcK10, Gaules) | Muito alta | Média: muitos canais de fã pequenos e fragmentados [MEDIDO: busca "cortes paulinho o loko" teve 12 canais diferentes] | Médio: música ambiente, **apostas/cassino**, menores em IRL | **Melhor nicho de crescimento** (cultura de "exército de clipadores" na Kick). Prioridade em clipes da Kick com muitas views + VOD. |
| **Games** (GTA VI agora; LoL, VALORANT e Tibia são os mais vistos no BR na Twitch [MERCADO, citando relatório da Twitch]) | Alta (pico agora) | Alta durante lançamentos | Médio: trilha/rádio do jogo, cutscenes longas | Cortar a **reação** (rosto + fala), não cutscene nem rádio. Clutch e rage funcionam até em 25 s. |
| **Política** | Alta (pós-eleição 2026, CPIs, votações) | Alta e polarizada (Cortes 247, Cortes do MBL, grandes portais) [MEDIDO] | Alto em marca/difamação; **baixo em copyright se a fonte for a Câmara** | **Nicho mal servido = Câmara (CC BY 4.0)**: brigas de plenário/CPI com tom neutro e contexto ("o que aconteceu hoje na Câmara"). Evitar canais de TV (CNN, Jovem Pan, GloboNews). |
| **Futebol** | Altíssima | Alta | **Altíssimo** com imagem de jogo | Só **resenha**: podcasts (Charla, Denílson Show), Cortes da CazéTV (programas de debate), coletivas, reações de streamer **sem** a transmissão. |
| **Reality** (A Fazenda 18 agora; BBB 27 em jan/2027) | Altíssima | Baixa no YouTube (o oficial @afazenda domina a busca) | **Altíssimo** (Globo/Record) | Só **conteúdo de terceiros comentando** (podcasts de fofoca, ex-participantes em podcasts, streamers reagindo com a câmera deles). Nunca o feed. |
| **Humor/stand-up** | Alta | Alta | Alto para *specials* (Netflix/Prime/HBO) | Cortar humoristas **em podcasts** (Flow, Ticaracaticast), não os *specials*. |
| **True crime** | Alta (Beto Ribeiro 2,4 M inscritos; casos no top de podcasts no YouTube BR) | Média | Alto em marca: vítimas, menores, violência → desmonetização | Fazer só com narradores/jornalistas falando (sem imagens de vítimas, sem menores). Bom para TikTok > 1 min (storytime). |
| **Celebridades/fofoca** | Muito alta | Alta | Médio: difamação | Fonte = entrevistas em podcasts. Sempre com data e contexto. |
| **Notícias "quentes"** | Alta | Alta (portais) | Médio | Usar como **gatilho** (trend) para achar o vídeo de podcast/streamer que comenta o assunto. |
| **Religioso** (Frei Gilson foi o nº 1 em horas assistidas de live no BR em 2025; Bispo Bruno Leonardo foi o nº 3) [IMPRENSA, Streams Charts] | Altíssima | Média (muitos canais de "pregação cortes") | Baixo em copyright (pregadores querem difusão), sensível no tom | **Oportunidade subestimada.** Público fiel e brand-safe. Exige respeito no título (nada de deboche). |
| **Finanças/negócios/ciência/história** (PrimoCast, "Sala de Guerra" do Inteligência) | Média | **Baixa** | Baixo | **Evergreen**: bom para o garimpo de acervo e para RPM maior. |

**Regra prática de saturação [INFERÊNCIA]:** se a busca `"cortes <criador>"` no YouTube retorna ≥ 70% dos resultados de **um** canal "[OFICIAL]", o criador está saturado para nós. Se retorna ≥ 6 canais diferentes e pequenos, é sinal de **tolerância a cortes** e espaço para entrar.

---

## 3. Criadores e canais para monitorar (com status de permissão)

**Como ler:** `sim` = há autorização pública verificável · `nao` = proibição pública verificável ou fonte de risco legal alto · `incerto` = sem política pública (a maioria). "Tem canal [OFICIAL] de cortes" significa que o dono monetiza cortes: terceiros competem com ele e podem levar claim.

### 3.1 Evidências de permissão encontradas

- **Câmara dos Deputados (@CamaradosDeputadosOficial): `sim`.** "Vídeos das transmissões das atividades legislativas seguem a licença Creative Commons BY 4.0", reprodução gratuita sem autorização prévia, **sem suprimir a marca d'água**. Demais conteúdos da TV Câmara: CC BY-NC-ND (não comercial e sem edição → `nao` para nós) [OFICIAL].
- **TV Senado (@tvsenado): `nao`.** A política proíbe uso comercial e cortes/montagem ("sem cortes [...] e sem qualquer montagem") [OFICIAL].
- **PodPeople – Ana Beatriz Barbosa (@podpeopleanabeatriz): `nao`.** Aviso oficial revoga, a partir de 01/01/2026, a permissão de "produção, divulgação e manutenção de cortes"; novos cortes só com autorização prévia e expressa [OFICIAL, site da produção].
- **alanzoka (@alanzoka / twitch `alanzoka`): `nao`.** A descrição do canal diz que ele não autoriza uso dos vídeos/lives em outro canal [MEDIDO].
- **Podpah: `incerto` (cautela).** Em mar/2025 aplicou strikes em canais que republicavam trechos com críticas [Wikipédia pt, IMPRENSA]. Tem canal oficial de cortes com 3 M de inscritos.
- **Casimiro / CazéTV: `incerto` (cautela).** Canal oficial de cortes (@CortesdoCasimitoOFICIAL, 4 M). A CazéTV transmite futebol (imagem de jogo = `nao`) e tem @cazetv-cortes oficial. Casimiro foi condenado em R$ 15 mil por react de um episódio de *Supernanny* (TJSP, fev/2025) e há ação de R$ 120 mil contra a CazéTV por comentário numa transmissão do canal de cortes [IMPRENSA]. **Reacts de conteúdo de TV/filme carregam o risco da obra original.**
- **Flow Podcast: `incerto`.** Canal oficial de cortes (3,3 M); o grupo diz "investir mais nos cortes" [IMPRENSA, Exame]. Não achamos política pública para terceiros.

### 3.2 Regra automática de permissão (implementável)

Ao enriquecer um candidato, ler `channel.description` (yt-dlp: `description` da aba do canal; Kick: `bio`) e aplicar regex em texto normalizado:
- **Bloquear** (`permite_cortes = nao`): `nao autorizo|proibid[oa] (o )?(uso|cortes|reupload)|nao (e )?permitid|sem autorizacao|todos os direitos reservados.*cort|strike`
- **Liberar** (`sim`): `cortes? liberad|pode(m)? cortar|libero (os )?cortes|cortem a vontade|uso livre|creative commons|cc by`
- Caso contrário → `incerto`. Guardar o trecho que casou no banco, para auditoria.

### 3.3 Lista curada
A lista completa e legível por máquina está na **seção 9(a)**. Destaques por nicho:
- **Kick (entretenimento/IRL):** `coringa`, `paulinholokobr`, `gaules`, `tck10`, `jonvlogs`, `fontinnelerj` (Bonde do Jon, IRL RJ, ~20 mil espectadores ao vivo em 23/11) [MEDIDO].
- **Twitch:** `cellbit` (clipes de ~8 mil views/semana), `felps`, `baiano`, `casimiro` (sem clipes em 7 dias: conferir se migrou para o YouTube) [MEDIDO].
- **YouTube (podcasts):** @FlowPodcast, @Podpah, @inteligencialtda, @TICARACATICAST, @venuspdc, @podcast3irmaos, @PrimoCast, @CharlaPodcast, @denilsonshow.
- **YouTube (sinal/concorrência, não cortar):** canais oficiais de cortes: @cortesdoflow, @CortesPodpahOFICIAL, @cortesdointeligencia, @CortesdoCasimitoOFICIAL, @CortesdoVenusOficial, @TicaracaticastCortes, @cortespodcast3irmaosoficial, @CortesdoGaulesOFICIAL, @cortesloudcoringaoficial, @CortesdoDavyJones.

---

## 4. Indicadores de viralidade sem chave de API e fórmula de pontuação

### 4.1 Linhas de base medidas (23/11/2026) [MEDIDO]

| Fonte | Views por hora (vph) | Taxa de like (likes/views) | Taxa de comentário |
|---|---|---|---|
| Podpah (episódios, 3 a 7 dias) | 2 mil a 12,8 mil | 2,8% a 6,6% | 0,04% a 0,06% |
| alanzoka (GTA VI, 7 a 14 h) | **18,9 mil a 21,4 mil** | 3,9% a 5,0% | 0,15% a 0,19% |
| Flow (14 h) | 4,1 mil | 2,7% | 0,14% |
| Cortes Podpah OFICIAL (Duelo de MCs, 5 h) | até **34,7 mil** | 4,5% | 0,35% |
| Cortes do Inteligência (1 a 2 dias) | 500 a 9,6 mil | 1,6% a 2,0% | 0,04% a 0,07% |
| Câmara (vídeos editados) | 18 a 77 | 0,7% a 1,8% | 0% a 0,08% |
| Clipes Kick da semana | Coringa: 5 mil · Paulinho: 8,5 mil | - | - |
| Clipes Twitch da semana | alanzoka: 60 mil · cellbit: 8,5 mil | - | - |

Conclusão: **valores absolutos variam 1000×** entre fontes. A velocidade precisa ser **relativa à mediana do próprio canal**.

### 4.2 Sinais e como calcular (todos sem chave)

| Sinal | Como obter | Quando existe | Observação |
|---|---|---|---|
| **Velocidade (V)** | RSS do canal a cada 10 min → `vph = Δviews/Δh`; mediana dos últimos 10 uploads do canal na mesma faixa de idade | Minutos após o upload | Melhor sinal de "esse episódio estourou" |
| **Engajamento (E)** | yt-dlp: `like_count`, `comment_count` / `view_count` | Imediato | Comentário alto = polêmica |
| **Clipes da Twitch** | yt-dlp `twitch.tv/<login>/clips?filter=clips&range=24hr` (ou GQL pública) | Durante a live | O próprio chat escolhe o momento; o clipe traz o offset no VOD |
| **Clipes da Kick** | `kick.com/api/v2/channels/<slug>/clips?sort=view&time=day` | Durante a live | Até ~180 s; títulos tipo "kkkk" indicam humor |
| **Pico de chat** | Twitch VOD: legenda `rechat` (yt-dlp); YouTube live: `live_chat`; Kick: histórico de mensagens | Logo após a live | z-score da taxa de mensagens por 10 s; emotes de riso e "CLIPA" |
| **Timestamps nos comentários** | yt-dlp `getcomments`, `max_comments=300`, `comment_sort=top`; regex `(\d{1,2}:)?\d{1,2}:\d{2}` | 1 a 3 h após o upload | Peso = 1 + √likes/5 por menção; cluster ≥ 3 em 60 s = momento quente |
| **Heatmap** | yt-dlp `heatmap` | Só em vídeos antigos (~55+ dias) | Usar no garimpo de acervo |
| **Pico de áudio** | `signals.loudness_curve` | Após baixar o áudio do trecho | ≥ +6 dB sobre a mediana móvel de 30 s |
| **Tendência (T)** | Google Trends RSS, trends24 (última 1 a 3 h), Google Notícias RSS `q=<entidade> when:1d` | Contínuo | Casar entidades com título, descrição e transcrição |
| **Saturação (C)** | Busca do YouTube filtrada por "Hoje" (`&sp=EgIIAg%3D%3D`; "última hora" = `EgIIAQ%3D%3D`, conferir) com `"<criador> <termo>"`; contar canais distintos ≠ fonte | Contínuo | Também checar se o canal [OFICIAL] já postou o mesmo momento |
| **Afinidade (A)** | Nosso histórico: views dos nossos cortes daquela fonte vs. mediana da conta | Após 72 h | Aprendizado (ver `algoritmo_e_riscos.md` §7) |

### 4.3 Fórmula proposta [INFERÊNCIA]

**Nível 1: pontuação do vídeo-fonte (0 a 100)**

```
S_fonte = 100 × P × (0,25·V + 0,20·H + 0,15·T + 0,15·F + 0,10·E + 0,10·A + 0,05·Q) × (1 − 0,5·C)
```

- **P (permissão/risco):** `sim` = 1,0 · `incerto` = 0,8 · `nao` = 0 (bloqueia). Bandeira de risco forte (jogo de futebol, feed de TV, propaganda de bet) = ×0. Risco moderado (música detectada, menor em cena) = ×0,6. Fonte com **campanha paga ativa** = 1,0 e +10 pontos no final (máximo 100).
- **V (velocidade):** `r = vph_atual / mediana_vph_canal` → `V = clamp(0,5 + log2(r)/4, 0, 1)` (r = 1 → 0,5; r = 4 → 1,0; r = 0,25 → 0). Sem histórico: `V = clamp((log10(vph) − 2) / 2,3, 0, 1)` (100 vph → 0; 1 mil → 0,43; 5 mil → 0,74; 20 mil → 1,0).
- **H (evidência de momento quente):** o maior valor entre: clipes Twitch/Kick (`views_top_clip / max(500, 0,05 × média_de_espectadores)`, até 1), cluster de timestamps nos comentários (≥ 3 menções em 60 s = 1), z-score do chat ≥ 3 = 1, pico do heatmap ≥ 0,8 = 1. **Nenhum disponível = 0,3** (neutro, não zero).
- **T (tendência):** `0,35·[Google Trends] + 0,35·[trends24 nas últimas 3 h] + 0,15·[≥ 3 notícias em 24 h] + 0,15·[sugestão/charts do YouTube]`, até 1.
- **F (frescor):** lives/VODs: `exp(−idade_h / 6)` · uploads de podcast: `exp(−idade_h / 18)` · garimpo de acervo: F = 0,5 fixo.
- **E (engajamento):** `0,6·clamp(like_rate / 0,04) + 0,4·clamp(comment_rate / 0,0025)`.
- **A (afinidade):** média bayesiana `(soma_views_nossos + 5·mediana_conta) / (n + 5) / mediana_conta`, mapeada `clamp(0,5·x, 0, 1)`. Começa em 0,5.
- **Q (qualidade da fonte):** 1080p + rosto visível + áudio limpo = 1 · 720p = 0,6 · < 480p = 0.
- **C (saturação):** `C = clamp(n_canais_terceiros_24h / 8, 0, 1)`, +0,3 se o canal [OFICIAL] já postou o mesmo momento (similaridade de título ≥ 0,6). Máximo 1.

**Nível 2: pontuação do momento (0 a 100)**

```
S_momento = 100 × (0,30·Externo + 0,20·Áudio + 0,25·Texto + 0,15·Autossuficiência + 0,10·Trend_no_trecho)
```

- **Externo:** sobreposição do trecho com clipe Twitch/Kick, cluster de timestamps, pico de chat ou heatmap (máximo entre eles).
- **Áudio:** pico ≥ +6 dB = 0,6 e ≥ +9 dB = 1,0; +0,2 se houver risada (tag `[risos]` ou riso no chat); +0,2 se a velocidade da fala for ≥ 1,4× a mediana do vídeo. Máximo 1.
- **Texto:** soma ponderada do léxico (seção 9(c)), normalizada pelo percentil 95 do próprio vídeo, mais 0,2 se houver frase de efeito e mais 0,2 se houver gancho nos 3 s iniciais.
- **Autossuficiência:** começa no início de uma frase (1), sem pronome solto nos 5 s iniciais (−0,3 para "ele/ela/isso/aquilo" sem antecedente), com desfecho dentro do trecho (1), terminando até 1,5 s após o desfecho.
- **Trend_no_trecho:** a entidade em alta aparece na fala do trecho.

**Decisão final**

```
S_final = 0,35·S_fonte + 0,65·S_momento
publicar automaticamente se S_final ≥ 62
mandar para revisão se 50 ≤ S_final < 62
descartar se < 50
```

**Gatilhos da "via rápida"** (processar já, fora da rodada):
- clipe da Twitch com ≥ 1.500 views em ≤ 3 h, ou ≥ 3× a mediana de views dos clipes do canal em 7 dias;
- clipe da Kick com ≥ 1.000 views em ≤ 24 h;
- upload do YouTube com `r ≥ 3` nas primeiras 6 h, ou vph absoluto ≥ 5 mil;
- trend (trends24 ou Google) casando com um canal monitorado que está **ao vivo** agora.

**Pular (concorrência):** se `n_canais_terceiros_24h ≥ 8` e o melhor concorrente passa de 100 mil views, pular o momento principal e cortar o **2º ou 3º melhor momento** do mesmo vídeo. O 2º melhor momento sem concorrência costuma valer mais que o 1º com 15 cópias [INFERÊNCIA].

---

## 5. O que torna um MOMENTO cortável e como detectar

### 5.1 Tipos de momento, sinais e plataforma

| Tipo | Sinais no texto (transcrição) | Sinais de áudio/chat | Melhor formato |
|---|---|---|---|
| **Conflito/treta** | "deixa eu falar", "você tá errado", "mentira", "cala a boca", "não me interrompe" | Volume +6 dB, falas curtas alternadas (< 1,5 s por segmento), velocidade alta | Shorts 30–55 s; TikTok 62–90 s com o contexto antes |
| **Revelação/confissão** | "nunca contei", "pela primeira vez", "ninguém sabe", "vou ser sincero", "confesso" | Pausa ≥ 0,8 s antes, queda de volume (fala baixa) e depois reação | TikTok > 1 min (setup + revelação) |
| **Risada/humor** | "kkkk" no chat, `[risos]`/`[risadas]` na legenda, "morri", "chorando de rir" | Rajada de volume com picos curtos; chat com KEKW/💀/😂 | Shorts 20–40 s; o punchline nos 3 s finais |
| **Frase de efeito (quotable)** | Frase de 6 a 16 palavras com "nunca/sempre/ninguém/todo mundo/a diferença entre/se você"; segunda pessoa e generalização | Pausa logo depois; risada ou "nossa" de quem ouve | Shorts 15–30 s; vira título |
| **Pico emocional** | "chorei", "minha mãe", "faleceu", "superei", "arrepiei" | Fala mais lenta e baixa, voz embargada (queda de energia), silêncio | TikTok 62–90 s |
| **Storytime** | "uma vez", "teve um dia", "eu tava", "aí ele", "do nada", "você não vai acreditar" | Um falante dominante por 45 a 150 s; termina em risada | **TikTok 62–95 s** (o melhor formato para o Programa de Recompensas) |
| **Opinião forte (hot take)** | "vou falar uma coisa", "pode me cancelar", "ninguém tem coragem de falar", "é superestimado", "na minha opinião" | Taxa de comentário alta no vídeo-fonte | Shorts 25–45 s (gera comentário) |
| **Números/dinheiro** | "R$ X mil/milhões", "faturei", "quanto ganha", "quebrei" | - | Título com o número; 30–60 s |
| **Clutch/rage (games)** | "não acredito", "1x5", "ace", "virada", palavrão | Pico de volume ≥ +9 dB, chat com "CLIPA"/POG | Shorts 15–35 s |

### 5.2 Detecção a partir de transcrição + áudio (recomendações concretas)

1. **Janela deslizante de 20 s com passo de 5 s.** Para cada janela, calcular `texto = Σ(peso × ocorrências) / percentil_95_do_vídeo`. Isso estende o `signals.KEYWORDS` atual com as categorias novas da seção 9(c).
2. **Tags das legendas automáticas do YouTube:** `[Risos]`/`[Risadas]`/`[Aplausos]` = sinal positivo. `[Música]` = **risco**: se cobrir ≥ 20% do trecho, descartar ou exigir revisão.
3. **Conflito sem diarização:** contar trocas de falante pela legenda (segmentos < 1,5 s alternados) e interjeições de interrupção ("não, não, não", "peraí", "calma"). Três ou mais trocas em 10 s + volume alto = treta.
4. **Timing de humor:** pausa ≥ 0,6 s seguida de pico de volume em até 2 s = provável punchline + risada. Ancorar o **fim** do corte de 0,8 a 1,5 s depois desse pico.
5. **Frase de efeito:** frases de 6 a 16 palavras, com generalização ("todo mundo", "ninguém", "sempre", "nunca") ou estrutura "a diferença entre X e Y", e sem pronome solto no começo. Pontuar e oferecer a frase como texto do card.
6. **Storytime:** marcador de abertura ("uma vez", "teve um dia"...) + 45 a 150 s com o mesmo falante + verbos no passado ("tava", "fui", "falou") + fecho (risada ou "e foi isso"). Começar o corte **no marcador**, não antes.
7. **Início do corte:** recuar até o início da frase (pontuação da legenda ou pausa ≥ 0,4 s). **Abrir na resposta, não na pergunta** (ex.: "O maior erro que eu cometi foi..."). Se o desfecho vier mais de 20 s depois do setup, cortar o setup ou mover o desfecho para o gancho (ver `criativo_genz.md` §2).
8. **Prompt do cérebro (Claude/Ollama):** enviar o top 8 de janelas candidatas (já pontuadas), não a transcrição inteira, com o tipo provável de cada uma. Pedir: tipo, nota 0–100, início e fim ajustados à frase, "núcleo" ≤ 55 s e título. Isso economiza tokens e melhora a precisão.

### 5.3 Duração por plataforma em 2026 (alinhada com `algoritmo_e_riscos.md` §3.1)

| Plataforma | Faixa recomendada | Por quê |
|---|---|---|
| **TikTok (monetização)** | **62–95 s** (alvo 65–75 s) | O Programa de Recompensas só paga vídeos ≥ 1 min [OFICIAL]. Use 62 s como piso, para não ficar em 59,9 s após o encode. |
| **TikTok (alcance)** | 20–45 s | Teasers e humor rápido |
| **YouTube Shorts** | **25–58 s** (rígido ≤ 58 s) | Shorts > 1 min com qualquer claim de Content ID são bloqueados globalmente [OFICIAL] |
| **Reels (se entrar no futuro)** | 30–60 s | - |

**Renderizar duas versões por momento:** a **longa** (setup + momento + reação, 62–95 s) para o TikTok e o **núcleo** (≤ 55 s) para os Shorts. Quem decide quais momentos aguentam a versão longa é o tipo: storytime, revelação e emoção aguentam. Humor rápido e clutch não aguentam e vão só em versão curta.

### 5.4 Quando fazer "Parte 1/2/3" (seleção; a apresentação está em `criativo_genz.md` §7)

Criar série **somente se todas** as condições valerem [INFERÊNCIA]:
- unidade narrativa (mesma história ou discussão) com ≥ 140 s;
- a curva de interesse do trecho fica ≥ 0,6 (normalizada) em ≥ 70% da duração;
- existe um ponto de suspense natural a cada 62–90 s: uma pergunta, "só que...", "aí ele falou..." ou uma pausa antes da resposta;
- tipo = storytime, revelação, debate longo ou CPI/plenário.

Parâmetros: **máximo de 3 partes** (`corte.max_partes: 3`), cada uma com 62–90 s no TikTok. No Shorts, publicar só o "melhor núcleo" ≤ 55 s com link de vídeo relacionado. **Parte 2 só se a Parte 1 atingir, em 2 h, ≥ 1,5× a mediana de views da conta**. Se não atingir, cancelar as partes seguintes e devolver a cota de posts.

---

## 6. Velocidade: quanto tempo depois e como ganhar dos outros canais

### 6.1 Prazos-alvo (SLA)

| Tipo de fonte | Do momento/upload até o post | Fonte do dado |
|---|---|---|
| Momento de live (Twitch/Kick/YouTube live) | **≤ 60 min** (ideal ≤ 30) | Janela de 30 a 90 min até saturar [MERCADO, AutoClip] |
| Episódio de podcast no YouTube | **1º corte ≤ 3 h**; 2 a 3 cortes nas primeiras 24–48 h; o restante ao longo da semana | Janela de 4 a 6 h [MERCADO]; o canal oficial do Podpah publicou 14 cortes num intervalo de ~2,5 h (Duelo de MCs, 22/11) [MEDIDO] |
| Política (sessão ao vivo, CPI) | ≤ 2 h | [INFERÊNCIA] |
| Assunto em alta (trends24/Google) | ≤ 3 h depois que o termo aparece | [INFERÊNCIA] |
| Acervo (evergreen) | Sem pressa; postar nos horários de pico | ver `algoritmo_e_riscos.md` §2 |

### 6.2 Como implementar a velocidade

1. **Novo modo "vigia" (processo contínuo)**, além das 4 rodadas fixas:
   - RSS do YouTube dos canais monitorados a cada **10 min** (1 requisição por canal; guarda `views` para a velocidade);
   - Kick `api/v2/channels/<slug>` a cada **5 min** (está ao vivo? `viewer_count`) e `clips?sort=view&time=day` a cada **10 min** quando ao vivo;
   - Twitch: clipes das últimas 24 h dos logins monitorados a cada **10 min**;
   - trends24 + Google Trends RSS a cada **30 min**.
2. **Via "clipe primeiro" para lives:** quando um clipe Twitch/Kick dispara o gatilho (§4.3), baixar **o próprio clipe** (60 s na Twitch, até ~180 s na Kick) mais ±30 s do VOD se existir, transcrever só isso com Whisper e publicar. Não esperar a live acabar.
3. **Podcasts:** usar a legenda automática quando ela existir. Se não existir em 30 min, baixar só o áudio dos 3 trechos com mais timestamps nos comentários e passar o Whisper.
4. **Fila de prioridade:** `prioridade = S_fonte × urgência`, com urgência = 3 para live, 2 para upload < 6 h e 1 para o resto.
5. **Revisão híbrida:** o modo `revisar` mata a velocidade. Proposta: `auto` para fontes `permite_cortes: sim` (ou com campanha ativa) e `S_final ≥ 70`; o resto vai para revisão.
6. **Twitch VOD expira** (de 7 a 60 dias): baixar logo os trechos quentes de lives importantes.

### 6.3 Como ganhar dos outros canais de cortes

- **Ser o primeiro** nos criadores médios (100 mil a 1 M) que **não têm canal [OFICIAL] de cortes**. Essa lacuna é detectada automaticamente (§2, regra de saturação).
- **Ângulo diferente** quando o momento já saturou: o 2º/3º melhor momento, a reação de outra pessoa ou o contexto ("POR QUE TODO MUNDO TÁ FALANDO DISSO").
- **Contexto que o concorrente não tem:** card de 2 s com quem, onde e quando, mais legenda palavra por palavra. Isso também conta como transformação para as plataformas.
- **Abrir no desfecho/reação** (frame 0 forte) e terminar até 1,5 s após o desfecho. Passar ~4 s do fim é o erro mais comum [MERCADO].
- **Cruzar trend × fonte:** quando um termo sobe no trends24, procurar entre os canais monitorados quem **falou daquilo nas últimas 72 h** (busca na transcrição em cache). Esse corte "explicador" chega antes da notícia saturar.
- **Postar TikTok e Shorts em até 30 min** para momentos de live. Para acervo, espaçar de 2 a 4 h entre plataformas [INFERÊNCIA].

---

## 7. Campanhas pagas de cortes ("clipping") em 2025–2026 e como plugar

### 7.1 Panorama

| Programa | Como paga | Observações para o Brasil |
|---|---|---|
| **Content Rewards (ex-"Whop Content Rewards")** | Por mil views (mediana ~US$ 1/mil; teto mediano ~US$ 200 por clipe; ganha a partir de US$ 2) [MERCADO]. Views contadas por 30 dias | Organização **"Brazil Clips"**: 3 campanhas visíveis, a **US$ 0,25–0,30/mil** (orçamentos de US$ 1 mil a 2 mil) [página da plataforma]. Contas conectadas e verificadas (TikTok, Instagram Business, YouTube, X). Proíbe views falsas; cada post vale para uma só campanha; algumas campanhas proíbem IA [OFICIAL, termos] |
| **Vyro** (MrBeast, lançado em out/2025) | Valor por mil views verificadas, definido pela marca (ex.: US$ 3/mil) | Pagamento em USD via Stripe/PayPal; saldo pendente até a checagem final [MERCADO] |
| **Programas de streamers (Discord)** | Ex.: N3on (Kick) pagou US$ 1,4 M a 303 clipadores em 5 semanas, a **US$ 40 por 100 mil views** [MERCADO, citando Business Insider] | Regras no Discord do criador; exigem tag, @ ou marca d'água para rastrear |
| **Kick** | Não há programa aberto confirmado; relatos conflitantes [MERCADO] | Verificar o Discord oficial da Kick antes de contar com isso |
| **Plataformas BR de campeonato de cortes** | Cut.Pro (PIX; exemplo de R$ 5/mil; o criador precisa de ≥ R$ 5 mil de prêmio); também citadas Clipou, Clipay, KlipCorte, Keoto e Real Oficial (não verificadas) | Pagam em reais via PIX. As regras variam: hashtag única por campeonato, @ obrigatório [MERCADO] |
| **X Original Content Rewards** | Programa de monetização do X | Exige Premium; não paga conteúdo copiado [MERCADO] |

**Escala realista:** no BR, US$ 0,25/mil significa que **1 M de views ≈ US$ 250**. Compensa como **bônus** sobre fontes autorizadas, não como receita principal.

### 7.2 Como o CORTEX pode se plugar (sem nunca logar em nada)

1. **Registro manual de campanhas** (`campanhas.yaml`, preenchido pelo usuário depois de entrar nas campanhas por conta própria):
   `{id, plataforma_campanha, fontes: [handles/URLs], cpm_usd, teto_por_video_usd, plataformas_aceitas, duracao_min_s, duracao_max_s, hashtags_obrigatorias, mencoes_obrigatorias, marca_dagua, proibe_ia: bool, proibe_musica: bool, prazo_envio_min, data_fim}`.
2. **Descoberta:** fontes de campanhas ativas entram como `permite_cortes: sim` + bônus de +10 no `S_final`, e ganham **prioridade de via rápida**.
3. **Conformidade automática antes de publicar:** duração dentro da faixa, hashtags/@ exigidos na legenda, marca d'água se pedida, nenhuma reutilização do mesmo corte em duas campanhas, nenhum repost.
4. **Envio:** como o CORTEX não faz login nesses sites, gerar no relatório uma **lista "enviar na campanha"** com o link do post, a campanha e o prazo. O usuário envia manualmente. Se a campanha tiver prazo curto de envio (há relatos de 30 min), avisar com toast do Windows.
5. **Acompanhamento:** ler as views públicas dos posts (RSS do próprio canal do YouTube e página pública do TikTok) por 30 dias e estimar a receita da campanha no relatório.
6. **Proibido:** views compradas, bots, "pods" de engajamento e contas compradas. Isso leva a banimento e confisco de saldo [OFICIAL, termos do Content Rewards].

---

## 8. Conteúdo a EVITAR (jurídico, direitos autorais, marca e política das plataformas)

**Bloqueio duro (P = 0):**
- **Imagem de transmissão esportiva** (jogos, gols, VAR, melhores momentos oficiais): o direito de arena é do mandante (Lei 14.597/2023, art. 160) e o uso para noticiário é restrito a veículos, com 3% do tempo e **máximo de 30 s**, sem patrocínio e com notificação prévia (art. 163) [OFICIAL]. Canal de cortes monetizado não se enquadra.
- **Feeds de TV e streaming:** BBB/Globo e Globoplay, A Fazenda/Record e PlayPlus, novelas, telejornais (GloboNews, CNN Brasil, Jovem Pan, Band), sportv/Premiere. A Globo derruba vídeos e perfis [IMPRENSA].
- **Música:** shows, sets de DJ, música tocando na live, **rádio do GTA VI**, abertura de podcast com música licenciada. Se `[Música]` cobrir ≥ 20% do trecho ou o áudio tiver pico tonal contínuo, descartar ou silenciar e exigir revisão.
- ***Specials* de stand-up e filmes/séries** (Netflix, Prime, HBO, Disney), inclusive **reacts** em que a obra aparece. O react não "limpa" a obra (caso Casimiro × *Supernanny*, TJSP 2025) [IMPRENSA].
- **Criadores que proíbem cortes:** alanzoka, PodPeople (desde 01/01/2026), TV Senado e canais cuja descrição case com o regex de bloqueio (§3.2).
- **Apostas/cassino** ("tigrinho", slots, código promocional, link de bet): as regras de publicidade de bets endureceram em 2026 e passaram a alcançar quem **divulga ou veicula** a peça (Portaria Interministerial 73/2026, Portaria SPA/MF 1.964/2026) [IMPRENSA/escritórios]. Comum em streams da Kick.
- **Menores de idade** em destaque (ECA Digital, em vigor desde 17/03/2026).
- **Discurso de ódio, apologia (ex.: nazismo), incitação à violência, desinformação eleitoral ou de saúde.** O YouTube removeu canais do Monark repetidamente [IMPRENSA].

**Revisão obrigatória (P = 0,6 e nunca automático):**
- **Acusações contra pessoas identificáveis** (crimes contra a honra). Corte fora de contexto pode gerar ação (há processo de R$ 120 mil contra a CazéTV por comentário numa transmissão do canal de cortes) [IMPRENSA]. Exigir que o corte contenha a fala completa e a data no título.
- **True crime** com nome ou imagem de vítimas, violência gráfica ou casos com menores.
- **Política:** sempre com data e contexto (fala antiga postada como nova = desinformação). Tom neutro no título quando a fonte for a Câmara.
- **Câmara no TikTok:** a licença exige **manter a marca d'água**, mas o TikTok tira do Para Você clipes "com marca d'água ou logo de outra pessoa" [OFICIAL]. Priorizar o YouTube para cortes da Câmara e, no TikTok, aceitar o risco de alcance menor.

**Política das plataformas (padrões que derrubam alcance/monetização):**
- Repost sem transformação, template idêntico em massa, logo/marca d'água de outra plataforma (TikTok/Kick/Twitch) no vídeo, loop para atingir 1 min, compilação sem narrativa [OFICIAL/IMPRENSA]. Ver a "camada de transformação" em `algoritmo_e_riscos.md` §3.5.

---

## 9. Seção para máquina

### (a) Canais sugeridos para monitorar

> Handles do YouTube **verificados em 23/11/2026** via yt-dlp (o `uploader_id` retornado). Logins da Twitch e slugs da Kick verificados por listagem de clipes/API pública. Status `incerto` = sem política pública encontrada; tratar com P = 0,8.

```yaml
canais_sugeridos:
  # ---------------- Política (fonte segura) ----------------
  - {plataforma: youtube, handle: "@CamaradosDeputadosOficial", nicho: politica, permite_cortes: sim, nota: "Transmissoes legislativas em CC BY 4.0; manter marca d'agua e creditar Camara. Demais programas da TV Camara: CC BY-NC-ND (nao usar)."}
  - {plataforma: youtube, handle: "@tvsenado", nicho: politica, permite_cortes: nao, nota: "Politica de uso proibe uso comercial e cortes/montagem."}
  - {plataforma: youtube, handle: "@STF_oficial", nicho: politica, permite_cortes: incerto, nota: "Sessoes do STF; licenca nao verificada. Revisao manual."}
  - {plataforma: youtube, handle: "@rodaviva", nicho: politica, permite_cortes: incerto, nota: "TV Cultura (emissora); risco de claim. Usar so como sinal/trend."}
  # ---------------- Podcasts (alto volume, saturados) ----------------
  - {plataforma: youtube, handle: "@FlowPodcast", nicho: podcast, permite_cortes: incerto, nota: "6,8M inscritos; tem @cortesdoflow oficial (3,3M). Cortar angulos que o oficial nao cortou."}
  - {plataforma: youtube, handle: "@Podpah", nicho: podcast, permite_cortes: incerto, nota: "10,3M; tem @CortesPodpahOFICIAL (3M). Aplicou strikes em canais criticos (mar/2025). Cautela."}
  - {plataforma: youtube, handle: "@inteligencialtda", nicho: podcast, permite_cortes: incerto, nota: "5,8M; @cortesdointeligencia oficial (4,1M). Bom em historia/ciencia/true crime (evergreen)."}
  - {plataforma: youtube, handle: "@TICARACATICAST", nicho: humor, permite_cortes: incerto, nota: "3,1M; @TicaracaticastCortes oficial (1,4M). Humoristas convidados."}
  - {plataforma: youtube, handle: "@venuspdc", nicho: podcast, permite_cortes: incerto, nota: "1,3M; @CortesdoVenusOficial (974k). Relacionamentos/fofoca."}
  - {plataforma: youtube, handle: "@podcast3irmaos", nicho: podcast, permite_cortes: incerto, nota: "770k; @cortespodcast3irmaosoficial (421k)."}
  - {plataforma: youtube, handle: "@podpeopleanabeatriz", nicho: podcast, permite_cortes: nao, nota: "Permissao de cortes REVOGADA desde 01/01/2026 (aviso oficial)."}
  - {plataforma: youtube, handle: "@PrimoCast", nicho: financas, permite_cortes: incerto, nota: "1,7M; financas/negocios; nicho pouco saturado, bom RPM."}
  # ---------------- Futebol (so resenha, nunca jogo) ----------------
  - {plataforma: youtube, handle: "@CharlaPodcast", nicho: futebol, permite_cortes: incerto, nota: "1,3M; resenha pos-jogo, posta rapido (3-5h). Sem imagem de partida."}
  - {plataforma: youtube, handle: "@denilsonshow", nicho: futebol, permite_cortes: incerto, nota: "973k; entrevistas com ex-jogadores."}
  - {plataforma: youtube, handle: "@CazeTV", nicho: futebol, permite_cortes: nao, nota: "Transmissoes de jogos (direito de arena). Nunca cortar partidas."}
  - {plataforma: youtube, handle: "@cazetv-cortes", nicho: futebol, permite_cortes: incerto, nota: "Programas de debate (Roda de Bobo). So falas, sem lances."}
  # ---------------- Streamers: Kick ----------------
  - {plataforma: kick, handle: "coringa", nicho: streamer, permite_cortes: incerto, nota: "1,37M seguidores Kick; clipes ~5k views/semana; @cortesloudcoringaoficial existe."}
  - {plataforma: kick, handle: "paulinholokobr", nicho: streamer, permite_cortes: incerto, nota: "372k Kick; YouTube @PaulinhoLOKOoficial (7,9M); muitos canais de fa (tolerancia aparente)."}
  - {plataforma: kick, handle: "gaules", nicho: games, permite_cortes: incerto, nota: "Multistream Kick/YouTube/Twitch; CS e GTA VI; @CortesdoGaulesOFICIAL."}
  - {plataforma: kick, handle: "tck10", nicho: games, permite_cortes: incerto, nota: "Valorant; 181k Kick."}
  - {plataforma: kick, handle: "jonvlogs", nicho: irl, permite_cortes: incerto, nota: "IRL/viagens; Bonde do Jon. Cuidado com apostas e menores em IRL."}
  - {plataforma: kick, handle: "fontinnelerj", nicho: irl, permite_cortes: incerto, nota: "IRL RJ (Bonde do Jon), ~20k ao vivo em 23/11/2026. Risco: rua, terceiros, PIX/doacoes."}
  # ---------------- Streamers: Twitch ----------------
  - {plataforma: twitch, handle: "alanzoka", nicho: games, permite_cortes: nao, nota: "Descricao do YouTube proibe uso das lives em outro canal. Usar so como sinal de trend."}
  - {plataforma: twitch, handle: "cellbit", nicho: games, permite_cortes: incerto, nota: "Clipes ~8k views/semana."}
  - {plataforma: twitch, handle: "felps", nicho: games, permite_cortes: incerto, nota: "Clipes ~1,4k views/semana; GTA."}
  - {plataforma: twitch, handle: "baiano", nicho: streamer, permite_cortes: incerto, nota: "Atividade baixa na Twitch em 7 dias; conferir Kick/YouTube."}
  - {plataforma: twitch, handle: "casimiro", nicho: streamer, permite_cortes: incerto, nota: "Sem clipes em 7 dias na Twitch; YouTube @CasimiroMiguel e @CortesdoCasimitoOFICIAL (4M). Reacts de TV/filme = risco da obra."}
  # ---------------- Games (YouTube) ----------------
  - {plataforma: youtube, handle: "@Gameplayrj", nicho: games, permite_cortes: incerto, nota: "Davy Jones; GTA VI; @CortesdoDavyJones oficial (646k)."}
  - {plataforma: youtube, handle: "@TcK10", nicho: games, permite_cortes: incerto, nota: "Valorant."}
  # ---------------- True crime / humor / religioso ----------------
  - {plataforma: youtube, handle: "@BetoRibeiroCrime", nicho: true_crime, permite_cortes: incerto, nota: "2,4M; narrativa longa = TikTok >1min. Sem imagens de vitimas."}
  - {plataforma: youtube, handle: "@RafinhaBastos", nicho: humor, permite_cortes: incerto, nota: "Evitar trechos de specials (direitos de streaming)."}
  - {plataforma: youtube, handle: "@pastorclaudioduarte", nicho: religioso, permite_cortes: incerto, nota: "Pregacao com humor; nicho de alta demanda, tom respeitoso."}
  # ---------------- Reality / TV (NAO cortar; usar como sinal) ----------------
  - {plataforma: youtube, handle: "@afazenda", nicho: reality, permite_cortes: nao, nota: "Record. Usar so para detectar o assunto; cortar podcasts/streamers comentando."}

# Canais oficiais de cortes: monitorar como SINAL e CONCORRENCIA (nunca re-cortar)
canais_concorrencia_oficial:
  ["@cortesdoflow", "@CortesPodpahOFICIAL", "@cortesdointeligencia", "@CortesdoCasimitoOFICIAL",
   "@CortesdoVenusOficial", "@TicaracaticastCortes", "@cortespodcast3irmaosoficial",
   "@CortesdoGaulesOFICIAL", "@cortesloudcoringaoficial", "@CortesdoDavyJones", "@cazetv-cortes"]
```

### (b) Pesos e limites da pontuação

```yaml
score:
  fonte:                     # S_fonte = 100*P*(soma ponderada)*(1-0.5*C)
    pesos: {velocidade: 0.25, momento_quente: 0.20, tendencia: 0.15, frescor: 0.15,
            engajamento: 0.10, afinidade: 0.10, qualidade: 0.05}
    penalidade_saturacao: 0.5
    permissao: {sim: 1.0, incerto: 0.8, nao: 0.0}
    risco_forte: 0.0         # jogo de futebol, feed de TV, bet, musica dominante
    risco_moderado: 0.6      # musica parcial, menor em cena, acusacao a terceiros
    bonus_campanha_pontos: 10
    velocidade:
      formula_relativa: "clamp(0.5 + log2(vph/mediana_canal)/4, 0, 1)"
      formula_absoluta: "clamp((log10(vph) - 2) / 2.3, 0, 1)"
      historico_videos: 10
    frescor_meia_vida_h: {live: 6, podcast: 18, acervo: null}   # acervo => F = 0.5
    engajamento_ref: {like_rate: 0.04, comment_rate: 0.0025}
    momento_quente_sem_sinal: 0.3
    saturacao: {canais_ref: 8, bonus_se_oficial_ja_postou: 0.3}
  momento:                   # S_momento = 100*(soma ponderada)
    pesos: {externo: 0.30, audio: 0.20, texto: 0.25, autossuficiencia: 0.15, trend_no_trecho: 0.10}
    audio_pico_db: {medio: 6, forte: 9}
    fala_rapida_x_mediana: 1.4
    janela_s: 20
    passo_s: 5
    musica_max_fracao: 0.20
  final:
    formula: "0.35*S_fonte + 0.65*S_momento"
    publicar_auto_min: 62
    revisar_min: 50
    auto_so_se: {permite_cortes: sim, S_final_min: 70}
  gatilhos_via_rapida:
    twitch_clip_views_min: 1500
    twitch_clip_idade_max_h: 3
    twitch_clip_x_mediana_7d: 3
    kick_clip_views_min: 1000
    kick_clip_idade_max_h: 24
    youtube_r_min: 3
    youtube_r_janela_h: 6
    youtube_vph_abs_min: 5000
    comentarios_ts_cluster_min: 3      # mencoes em 60 s, entre os 300 comentarios top
  pular_momento_se:
    concorrentes_24h_min: 8
    melhor_concorrente_views_min: 100000
  vigia_intervalos_min: {youtube_rss: 10, kick_status: 5, kick_clips: 10, twitch_clips: 10, trends: 30}
  duracao_s:
    tiktok_longo: [62, 95]
    tiktok_curto: [20, 45]
    youtube_shorts: [25, 58]
    nucleo_max: 55
  serie:
    max_partes: 3
    unidade_min_s: 140
    interesse_min: 0.6
    cobertura_min: 0.70
    parte2_se_views_2h_x_mediana: 1.5
```

### (c) Léxicos pt-BR para momentos quentes

> Texto **normalizado** (minúsculo, sem acento), igual a `signals.norm()`. Peso sugerido entre parênteses quando diferente de 1,0. Os itens são regex simples; `\b` implícito nas pontas. Estende o `signals.KEYWORDS` atual sem substituir.

```yaml
lexico:
  risada: ["k{4,}", "(ha){3,}", "(rs){2,}", "\\[(risos|risadas|gargalhadas)\\]", "chorando de rir", "morri", "to morrendo",
           "nao aguento", "me mijei", "ri muito", "que isso mano", "mano do ceu", "palhacada"]
  conflito: ["deixa eu falar (1.2)", "me deixa terminar (1.2)", "nao me interrompe (1.3)", "escuta aqui", "cala a boca (1.4)",
             "voce ta errad[oa]", "nao e bem assim", "mentira", "mentiros[oa] (1.2)", "hipocrit[ao]", "desonest[oa]",
             "falta de respeito (1.1)", "abaixa o tom", "nao grita", "tu ta maluc[oa]", "ta de brincadeira", "baixaria",
             "pera ai", "calma (0.5)", "sai daqui", "vou embora", "to saindo", "acabou (0.4)", "absurdo", "ridicul[oa]",
             "nao, nao, nao (1.1)", "discordo (0.7)"]
  revelacao: ["nunca contei (1.3)", "nunca falei (isso|disso) (1.2)", "pela primeira vez", "ninguem sabe", "vou revelar",
              "vou te contar uma coisa", "segredo", "a verdade e", "vou ser sincer[oa]", "confesso", "admito", "assumo",
              "em primeira mao", "bastidores", "fui traid[oa]", "terminamos", "to gravida", "fui demitid[oa]",
              "fui pres[oa]", "quebrei", "falir|fali", "processei|me processou"]
  storytime: ["uma vez (0.6)", "teve um dia", "eu tava", "ai eu", "ai ele", "ai ela", "do nada (0.7)", "quando eu era",
              "sabe o que aconteceu (1.1)", "voce nao vai acreditar (1.1)", "deixa eu te contar", "eu lembro que",
              "na epoca", "a gente tava", "e foi assim que", "resumindo (0.4)", "no fim das contas"]
  hot_take: ["vou falar uma coisa", "pode me cancelar (1.3)", "vou ser cancelad[oa] (1.2)", "ninguem tem coragem (1.2)",
             "ninguem fala isso", "superestimad[oa]", "e uma farsa", "e golpe", "opiniao impopular (1.2)", "o brasileiro (0.5)",
             "todo mundo sabe", "o problema e", "a culpa e", "na minha opiniao (0.5)", "pra mim (0.3)", "simples assim"]
  frase_efeito_marcadores: ["nunca", "sempre", "ninguem", "todo mundo", "a diferenca entre", "se voce", "nao existe",
                            "o segredo", "quem (nao )?", "o pobre", "o rico", "a vida", "o sucesso"]   # so vale em frase de 6 a 16 palavras
  emocao: ["chorei", "to chorando", "emocionad[oa]", "arrepiei", "me arrepia", "saudade", "minha mae", "meu pai",
           "faleceu|morreu", "perdi (meu|minha)", "depressao", "ansiedade", "superei", "orgulho", "obrigad[oa] por tudo", "lagrimas"]
  choque: ["nao acredito", "meu deus", "gente do ceu", "misericordia", "socorro", "como assim", "nao e possivel", "surreal",
           "bizarr[oa]", "insano", "olha isso (1.1)", "caraca", "mds", "chocad[oa]"]
  dinheiro_numeros: ["\\d+[.,]?\\d*\\s*(mil|milhao|milhoes|bilhao|bilhoes|reais|k)", "salario", "quanto (ele |ela )?ganha",
                     "faturei", "faturamento", "divida", "fiquei ric[oa]", "investi", "perdi tudo (1.2)"]
  games: ["clutch (1.2)", "ace", "1x5|1v5", "virada", "rage", "bugou", "glitch", "headshot", "jogou demais", "carregou",
          "tiltad[oa]", "nao acredito", "quase", "perdemo", "ganhamo", "gg"]
  futebol_resenha: ["golaco", "frango", "penalti", "var", "roubad[oa]|roubaram", "juiz", "rebaixad[oa]|rebaixamento",
                    "titulo", "campea[oa]", "vice", "contratacao", "demitid[oa]", "tecnico", "classico", "torcida"]
  politica: ["vossa excelencia (1.1)", "pela ordem", "questao de ordem", "quebra de decoro (1.3)", "cassacao", "cpi|cpmi",
             "convocad[oa]", "depoimento", "voce mentiu (1.3)", "corrupcao", "propina", "impeachment", "anistia",
             "emenda pix", "orcamento secreto", "stf", "ministr[oa]"]
  reality: ["paredao", "roca", "prova de fogo", "prova do fazendeiro", "eliminad[oa]", "berlinda", "votou em mim",
            "traidor|traicao", "falsa|falso", "estrategia", "lider", "dinamica", "expuls[oa]", "desistiu", "apertou o botao",
            "barraco", "climao"]
  true_crime: ["assassinato", "homicidio", "investigacao", "delegad[oa]", "suspeito", "desaparecid[oa]", "condenad[oa]",
               "inocente", "provas", "pericia", "julgamento", "juri", "serial killer"]
  celebridade: ["namor(o|ad[oa])", "casamento", "separacao", "divorcio", "traiu", "ficou com", "beijou", "indireta",
                "processou", "cancelad[oa]", "ex (namorad[oa]|mulher|marido)"]
  gancho_inicio: ["o problema e", "a verdade e", "ninguem te conta", "o maior erro", "eu nunca", "voce sabia", "olha so",
                  "presta atencao", "o dia que", "isso aqui"]          # vale +0.2 se aparecer nos 3 s iniciais

sinais_chat:   # contar por janela de 10 s; z-score >= 3 = pico
  riso: ["k{4,}", "kekw", "lul", "omegalul", "lmao", "💀", "😂", "🤣"]
  hype: ["clipa", "clipa isso", "clip it", "pog", "pogchamp", "vamo+", "a{4,}", "no{3,}", "w", "gg"]
  choque: ["\\?{3,}", "monkas", "que isso", "mds", "😳", "😱"]
  treta: ["l", "ratio", "f", "vergonha", "cringe"]

tags_legenda:
  positivas: ["[risos]", "[risadas]", "[aplausos]", "[gritos]"]
  risco: ["[musica]"]              # >= 20% do trecho => descartar ou revisar

bloqueio_risco:   # P = 0 (bloqueio) ou revisao obrigatoria; aplicar em titulo, descricao, transcricao e texto na tela (OCR opcional)
  bets_cassino: ["bet(s)?", "aposta(s|r)?", "cassino|casino", "slot(s)?", "tigrinho", "fortune (tiger|ox|rabbit)", "aviator",
                 "blaze", "roleta", "codigo promocional", "cupom", "deposit(a|o)", "banca", "odd(s)?"]
  transmissao_tv_esporte: ["premiere", "sportv", "globoplay", "playplus", "recordplus", "ao vivo na globo", "transmissao oficial",
                           "melhores momentos oficiais"]
  autolesao: ["suicidio", "me matar", "se matar", "automutilacao"]
  menores: ["menor de idade", "\\b(1[0-7]|[1-9]) anos de idade", "meu filho de \\d", "minha filha de \\d"]
  sexual: ["nudes", "onlyfans", "privacy", "pack (do|da)"]
  odio_extremismo: ["nazis(mo|ta)", "supremacia", "hitler"]   # contexto: revisao manual, nunca auto
  # lista de insultos discriminatorios: manter localmente em data/estado/bloqueio_ofensas.txt (nao versionar)
```

---

## 10. Fontes

**Oficiais (leis, órgãos, plataformas)**
- Lei 14.597/2023 (Lei Geral do Esporte), arts. 160 e 163: https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2023/lei/l14597.htm
- Câmara dos Deputados, vídeos (CC BY 4.0 para transmissões legislativas): https://www2.camara.leg.br/a-camara/documentos-e-pesquisa/arquivo/acervo-por-tipo/videos
- Senado, política de uso: https://www12.senado.leg.br/assessoria-de-imprensa/politica-de-uso
- YouTube, Shorts de 3 min e bloqueio com Content ID: https://support.google.com/youtube/answer/15424877
- YouTube, contagem de views a partir do 1º frame (ago/2026): https://blog.youtube/inside-youtube/engaged-views-youtube-explained/
- TikTok, diretrizes (inelegibilidade de conteúdo não original no Para Você): https://www.tiktok.com/community-guidelines/en/integrity-authenticity/
- Aviso PodPeople/Dra. Ana Beatriz sobre revogação de cortes (01/01/2026): https://draanabeatriz.com.br/cortes
- Content Rewards, termos para criadores: https://www.contentrewards.com/terms-of-service/clippers · página "Brazil Clips": https://contentrewards.com/brazil-clips
- STF, parâmetros de responsabilização de plataformas: https://noticias.stf.jus.br/postsnoticias/stf-define-parametros-para-responsabilizacao-de-plataformas-por-conteudos-de-terceiros
- Agência Senado, ECA Digital em vigor: https://www12.senado.leg.br/noticias/materias/2026/03/17/eca-digital-para-protecao-on-line-de-criancas-e-adolescentes-entra-em-vigor

**Imprensa**
- TechCrunch (16–20/07/2026), YouTube e "AI slop"/conteúdo templated: https://techcrunch.com/2026/07/20/youtube-clarifies-policies-around-ai-slop-and-upsetting-videos/
- Digital Trends (out/2026), Shorts reaproveitados perdem alcance: https://digitaltrends.com/phones/youtube-cracks-down-on-reposted-shorts-with-a-new-recommendation-update/
- Search Engine Journal (jul/2025), "inauthentic content" não mira canais de react/cortes: https://www.searchenginejournal.com/youtube-clarifies-monetization-update-targeting-spam-not-reaction-channels/550123/
- TechCrunch (jul/2025), fim da página Em alta: https://techcrunch.com/2025/07/10/youtube-is-getting-rid-of-its-trending-page-and-trending-now-list
- Inven Global (nov/2026), clipes de 5 min na Twitch: https://www.invenglobal.com/articles/28680/twitch-plans-five-minute-clips-and-hosting-return-at-twitchcon-san-diego-2026
- Streams Charts, top streamers BR 2025: https://streamscharts.com/news/top-brazilian-streamers-2025
- Olhar Digital (jul/2026), Twitch × Kick: https://olhardigital.com.br/2026/07/30/games-e-consoles/twitch-vs-kick-por-que-a-disputa-do-streaming-ja-nao-e-apenas-por-audiencia/
- Wikipédia pt, Podpah (strikes de mar/2025): https://pt.wikipedia.org/wiki/Podpah
- Correio (BBB 26, regras da Globo para perfis): https://www.correio24horas.com.br/asteriscao/isso-a-globo-nao-deixa-descubra-o-que-os-perfis-dos-participantes-do-bbb-nao-podem-fazer-0225
- TecMundo, Globo e vídeos piratas do BBB: https://www.tecmundo.com.br/seguranca/259672-globo-pede-funcionarios-denunciem-videos-piratas-bbb-23.htm
- O Povo (fev/2025), Casimiro condenado por react: https://www.opovo.com.br/vidaearte/2025/02/14/amp/casimiro-e-condenado-em-rs-15-mil-apos-reagir-um-episodio-de-supernanny.html
- DGABC, ação contra a CazéTV por comentário no canal de cortes: https://www.dgabc.com.br/Noticia/4339129/ator-processa-a-caze-tv-e-pede-rs-120-mil-por-danos-morais-grande-prejuizo-
- Uai/Jornal Opção (jul/2026), CazéTV fora da Copa do Brasil: https://www.jornalopcao.com.br/ultimas-noticias/saiba-por-que-a-cazetv-foi-excluida-da-disputa-pelos-direitos-da-copa-do-brasil-ate-2030-841975/
- Gazeta do Povo, desmonetização do Flow/Cortes do Flow: https://www.gazetadopovo.com.br/vida-e-cidadania/flow-podcast-youtube-rigidas-penalizacoes/
- Exame, estratégia de cortes do Flow: https://exame.com/pop/agora-na-tv-de-verdade-flow-aposta-na-diversificacao-de-formatos-para-manter-protagonismo/
- Migalhas/Cescon Barrieu (2026), novas regras de publicidade de bets: https://www.migalhas.com.br/quentes/460340/governo-amplia-restricoes-a-publicidade-de-bets-e-exige-alertas · https://cesconbarrieu.com.br/novas-portarias-bets/
- Dexerto, Kick e promoção de clipes: https://www.dexerto.com/kick/clavicular-says-kick-spent-nearly-700000-promoting-his-clips-in-a-single-month-3393030/

**Mercado (fornecedores; usar como indício)**
- Cut.Pro: reposts não pagam mais (2026): https://cut.pro/pt-BR/blog/reposts-dont-pay-x-meta-youtube-2026 · Twitch quer cortes: https://cut.pro/pt-BR/blog/twitch-quer-seus-cortes-2026 · Copa 2026 sem strike: https://cut.pro/pt-BR/blog/copa-do-mundo-2026-clipar-sem-restreamar · Como ganhar com cortes: https://cut.pro/pt-BR/blog/how-to-make-money-clipping-2026 · Comparativo de plataformas: https://cut.pro/pt-BR/blog/plataformas-campeonato-de-cortes-comparativo-2026 · Campeonato de cortes: https://cut.pro/pt-BR/blog/campeonato-de-cortes-para-streamer-2026 · Exército de clipadores: https://cut.pro/pt-BR/blog/join-streamer-clipper-army-2026 · Kick paga clipadores: https://cut.pro/en/blog/kick-pays-clippers-directly-2026
- AutoClip: janelas de tempo após eventos de streamer: https://autoclip.dev/blog/how-fast-clips-go-viral-after-streamer-events · estratégia de cortes de podcast: https://autoclip.dev/blog/podcast-clipping-strategy-2026
- Opus Pro, Whop Content Rewards: https://www.opus.pro/blog/whop-content-rewards
- Stream Rise, Kick no Brasil 2026: https://stream-rise.com/pt-br/blog/top-kick-streamers-brazil-2026

**Medições próprias (23/11/2026, sem login, só metadados públicos)**
- yt-dlp 2026.10.26 (venv do projeto): metadados de ~40 canais, ~90 vídeos (views, likes, comentários, heatmap, legendas), 300 comentários "top" de 3 vídeos, busca do YouTube para 18 consultas de cortes.
- API pública da Kick (`/api/v2/channels/<slug>` e `/clips`), listagem de clipes da Twitch via yt-dlp, RSS de canal do YouTube, Google Trends RSS (geo=BR), trends24.in/brazil, Reddit (bloqueado: 403).
