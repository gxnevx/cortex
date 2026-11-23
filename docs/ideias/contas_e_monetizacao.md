# CORTEX: quantas contas, quantos posts e como monetizar (TikTok + YouTube Shorts, Brasil)

> Data da pesquisa: **23/11/2026**. Escopo: um dono (uma pessoa, um CPF), contas **novas**, cortes em PT-BR (podcasts, lives, debates, games como GTA 6, memes e conteúdo traduzido do inglês), publicação por navegador logado.
> Complementa `algoritmo_e_riscos.md` (aquecimento, horários, direitos autorais), `benchmark_canais.md` (o que os grandes fazem) e `estrategia_conteudo.md` (o que cortar). Onde este documento corrige ou refina os anteriores, isso está dito na seção 0.2.
> Arquivo para máquina: `docs/ideias/contas_e_monetizacao.json`.
> **Nada aqui é aconselhamento jurídico, contábil ou tributário.** As partes de impostos são um mapa para conversar com um contador.

**Legenda de evidência:**
- **[OFICIAL]**: página de ajuda, política, termos ou blog oficial da plataforma, ou órgão público.
- **[IMPRENSA]**: veículo jornalístico ou de tecnologia.
- **[MERCADO]**: blog de ferramenta, agência ou plataforma de clipping (interesse comercial; tratar como indício).
- **[INFERÊNCIA]**: recomendação minha a partir das fontes.
- **[NÃO CONFIRMADO]**: procurei e não achei fonte oficial; conferir no app antes de decidir.

---

## 0. Respostas diretas

### 0.1 Resumo em uma tabela

| Pergunta | Resposta curta |
|---|---|
| Limite rígido de posts por dia | **YouTube**: existe limite diário por canal (web + celular + API), **número não publicado**; sobe com verificação [OFICIAL]. **TikTok**: sem número público para app e web; pela API oficial o teto é **"cerca de 15 posts por dia por conta"** [OFICIAL]. |
| Teto prático por conta (distribuição sem cara de spam) | **TikTok: 4 por dia** (até 6 só com métricas boas). **YouTube Shorts: 2 por dia** (máximo 3). Acima disso o ganho por post some e o risco sobe [ESTUDO + INFERÊNCIA]. |
| Rampa por idade da conta | TikTok: 0 nos dias 0 a 2, **1/dia** na semana 1, **2 a 3/dia** nas semanas 2 a 4, **3 a 4/dia** do mês 2 em diante. YouTube: **1/dia** na semana 1, **1 a 2/dia** nas semanas 2 a 4, **2/dia** do mês 2 em diante. |
| Espaçamento mínimo | **150 min** entre posts da mesma conta no TikTok, **240 a 300 min** no YouTube; entre contas diferentes da mesma plataforma, nunca ao mesmo tempo (mínimo 30 min de defasagem). |
| Pode ter 2 ou 4 contas? | **Sim, as regras permitem** várias contas por pessoa nas duas plataformas, **desde que não seja para enganar, burlar punição ou postar o mesmo conteúdo** [OFICIAL]. Recomendo **2 TikTok + 2 YouTube** (um par por nicho) e **no máximo 3 + 3** para um operador solo num PC. 4 + 4 é permitido, mas não compensa. |
| Mesmo clipe em duas contas próprias? | **Não** na mesma plataforma (é "conteúdo duplicado" e "rede coordenada"). Sim entre plataformas (o par TikTok A + YouTube A do mesmo nicho). |
| Um CPF monetiza vários canais no YouTube? | **Sim.** Uma única conta AdSense para YouTube por titular, e **vários canais podem ser vinculados a ela** [OFICIAL]. Cada canal precisa bater os requisitos sozinho. |
| Requisito do YPP com "20 milhões" | **Confirmado, com nuance.** A partir de **01/02/2027**, quem entra no YPP precisa de **20 M de views qualificadas de Shorts em 90 dias** (ou 8.000 h em 365 dias). E **todo** canal, novo ou antigo, precisa manter **10 M em 90 dias** para receber a receita de Shorts naquele mês [OFICIAL]. O nível de entrada (500 inscritos, 3 M em 90 dias) **não muda**. |
| Receita realista no curto prazo | Ordem: **campanhas de cortes pagas** (desde o dia 1, sem mínimo de seguidores) → **TikTok Creator Rewards** (10 mil seguidores + 100 mil views em 30 dias, vídeos de 1 min ou mais) → **YouTube nível de entrada + Shopping** (500 inscritos + 3 M em 90 dias). Receita de anúncios de Shorts no Brasil é quase simbólica (US$ 0,01 a 0,08 por mil views) [MERCADO]. |

### 0.2 Correções e ajustes em relação aos documentos anteriores

| Documento | O que dizia | O que a pesquisa de hoje mostra |
|---|---|---|
| `algoritmo_e_riscos.md` §0 e §3.3 | "A partir de 01/02/2027 novos entrantes precisam de 20 M de views de Shorts em 90 dias" | **Confirmado** no blog oficial do YouTube (10/08/2026) e na página de políticas de monetização de Shorts. **Faltava**: a exigência contínua de 10 M em 90 dias para receber a receita de Shorts vale para todos os parceiros, inclusive os novos. O blog não repete o número de inscritos; a página de ajuda atual e a imprensa mantêm 1.000. |
| `algoritmo_e_riscos.md` §1.2 e §5.5 | "Uma conta por plataforma; nada de rede de contas" | **Refinado.** A diretriz do TikTok diz literalmente que você pode ter várias contas, só não para enganar ou quebrar regras; o YouTube permite até 100 canais por Conta Google. O que é proibido é rede **coordenada**, conteúdo **duplicado** e **evasão de punição**. Recomendo 2 pares de contas com nichos distintos, sem disfarce (sem VPN, proxy ou navegador antidetecção). |
| `algoritmo_e_riscos.md` §5.2 | API do YouTube: cota de 10.000 unidades, upload custa ~1.600, dá ~6 uploads/dia | A tabela oficial de custos agora mostra `videos.insert` com **balde próprio de 100 chamadas por dia por projeto**, custo 1 cada [OFICIAL]. A cota da API deixou de ser o gargalo; o limite do canal continua valendo. |
| `algoritmo_e_riscos.md` §1.2 (YouTube até 4/dia) x `benchmark_canais.md` §9 (YouTube 2/dia) | divergência | Fico com **2 por dia (máximo 3)** no YouTube: os Shorts nativos que mais crescem postam ~1/dia e a Metricool mede o melhor desempenho por post com 2 a 4 Shorts por **semana**. Volume no YouTube não é o diferencial. |

---

## 1. Limites de postagem por conta

### 1.1 Limites rígidos (o que a plataforma bloqueia)

| Plataforma | Limite | Detalhe | Fonte |
|---|---|---|---|
| YouTube (canal) | Limite diário de uploads **por canal**, somando computador, celular e API. Número **não publicado**. | Varia por país e histórico do canal. Ao atingir, aparece "limite diário de envio" e é preciso esperar 24 h. Strikes de diretrizes e de direitos autorais reduzem o limite. | [OFICIAL] Erros comuns de upload |
| YouTube (níveis) | Sem verificação: "limite diário limitado"; com recursos avançados: "limite diário maior" para "enviar vídeos e Shorts". | Recursos intermediários pedem verificação por telefone; avançados vêm do histórico do canal ou de verificação por documento ou vídeo. | [OFICIAL] Acesso a recursos |
| YouTube (Shorts) | Não há cota separada para Shorts. Short pode ter até 3 min, mas **acima de 1 min com qualquer reivindicação é bloqueado no mundo todo**. | O limite de upload é o mesmo dos vídeos longos. | [OFICIAL] |
| YouTube (API oficial) | `videos.insert`: **100 por dia por projeto** do Google Cloud, custo 1 cada. | Por projeto, não por canal. | [OFICIAL] Custos de cota da API |
| YouTube (Studio, lote) | Até 15 arquivos por lote de envio na interface. | É limite de interface, não cota diária. | [MERCADO] |
| TikTok (app e web) | **Sem número público.** | Contas que postam rápido demais podem receber restrição temporária de 24 a 72 h. | [MERCADO] |
| TikTok (API Direct Post) | **"Tipicamente cerca de 15 posts por dia por conta de criador"**, compartilhado entre todos os apps que usam a API. | Erros `spam_risk_too_many_posts` (teto do dia) e `spam_risk_user_banned_from_posting` (conta proibida de postar). | [OFICIAL] TikTok for Developers |
| TikTok (agendador nativo) | Agendamento até 10 dias à frente no TikTok Studio (computador). | Útil para o modo semiautomático. | [OFICIAL, citado em `algoritmo_e_riscos.md`] |

**Leitura [INFERÊNCIA]:** os limites rígidos estão muito acima do que faz sentido para uma conta de cortes. O que limita de verdade é a **distribuição**: a partir de certo volume, cada post novo rende menos e a conta começa a parecer fábrica.

### 1.2 Teto prático: onde a plataforma ainda distribui

O que existe de evidência:

1. **Nenhuma das duas plataformas publica um número de posts ideal.** O YouTube só pede uma frequência "sustentável no longo prazo" [OFICIAL]. A recomendação de "1 a 4 posts por dia" atribuída ao TikTok aparece só em fontes secundárias [NÃO CONFIRMADO].
2. **A política de spam do YouTube** diz que postar "algumas variações de um vídeo" é aceitável, mas proíbe "usar ferramentas automatizadas ou IA para gerar grande volume de conteúdo semelhante com mudanças mínimas" e "inundar a plataforma com conteúdo repetitivo" [OFICIAL].
3. **Dados de volume** [ESTUDO]: no TikTok o ganho de views por post cresce pouco com mais posts e achata (Buffer, 11 M de posts). No YouTube, o melhor desempenho **por Short** aparece com 2 a 4 Shorts por semana, sem teto para o total mensal (Metricool, 799 mil vídeos). O crescimento do canal acompanha a frequência, mas é correlação (vidIQ, 10,2 M de canais).
4. **O que os vencedores fazem** [MEDIDO em `benchmark_canais.md`]: os Shorts nativos que mais crescem no Brasil postam **~1 por dia**; no TikTok, contas grandes de notícia e esporte postam 5 a 20 por dia, mas são donas do conteúdo.
5. **Mudança de 01/10/2026 no YouTube** [OFICIAL via Creator Insider, IMPRENSA]: a recomendação de Shorts passou a reduzir o alcance de **canais** que repostam clipes de outros sem acréscimo relevante. Não contam como acréscimo: "descrições em voz do que acontece na tela, pequenas edições técnicas ou mudanças em massa baseadas em template". Para um canal de cortes, mais volume de baixa transformação piora o canal inteiro.

**Conclusão [INFERÊNCIA]:** teto prático por conta de cortes = **4/dia no TikTok** (6 só se as métricas aguentarem) e **2/dia no YouTube** (3 no máximo). O que passar disso deve ir para **outra conta de outro nicho**, não para a mesma conta.

### 1.3 Recomendação por idade da conta (cada conta, não o total)

| Idade da conta | TikTok (posts/dia) | YouTube Shorts (posts/dia) | Espaçamento mínimo na mesma conta | Condição para avançar |
|---|---|---|---|---|
| Dias 0 a 2 | **0** (só uso manual: assistir ao nicho, seguir 10 a 20 contas, completar o perfil) | **0** | n/a | perfil completo, nenhum aviso |
| Dias 3 a 7 (semana 1) | **1** | **1** | n/a (1 post na melhor janela) | 3 dos últimos 5 posts com 50+ views em 24 h |
| Semana 2 | **2** | **1** | TikTok 240 min | mediana de 24 h de 200+ (TT) ou 150+ (YT) |
| Semanas 3 e 4 | **3** | **2** | TikTok 150 min; YouTube 300 min | estado NORMAL por 7 dias e nenhum claim em 14 dias |
| Mês 2 | **3 a 4** | **2** | TikTok 150 min; YouTube 300 min | mediana de 7 dias igual ou acima da de 30 dias |
| Mês 3 em diante | **4** (até 6 se as 2 condições ao lado valerem por 14 dias) | **2** (até 3 se as condições valerem) | TikTok 150 min; YouTube 240 min | views por post não caem ao subir o volume; shares por mil na média ou acima |

Regras que valem sempre:
- **Avançar por métrica, não por calendário.** A máquina de estados NORMAL, CAUTELA, PAUSA e PARAR de `algoritmo_e_riscos.md` §1.5 continua valendo por conta.
- **Entre contas da mesma plataforma:** nunca duas sessões de upload ao mesmo tempo; defasagem mínima de **30 min** entre o post da conta A e o da conta B [INFERÊNCIA].
- **Mesmo corte em TikTok e YouTube do mesmo par:** 20 a 60 min de diferença (TikTok primeiro).
- **Sem posts entre 01:00 e 06:30** e sem intervalos exatos e repetidos.
- **O 4º post do dia no TikTok e o 3º no YouTube** só saem se o corte estiver no top 30% de nota do dia.

### 1.4 O que dispara penalidade de spam, inautenticidade ou conteúdo repetitivo

| Comportamento | Onde é proibido ou penalizado | Efeito típico |
|---|---|---|
| Repostar trecho de outro criador "sem adicionar nada seu" | YouTube spam ("conteúdo copiado") e conteúdo reutilizado; TikTok: material "não original ou reutilizado sem nada novo" fica fora do Para Você [OFICIAL] | YouTube: views não contam para a receita de Shorts e a monetização pode sair **do canal inteiro**; alcance menor desde 10/2026. TikTok: fora do Para Você. |
| "Conteúdo enviado muitas vezes por outros criadores" (o momento viral que 30 canais já cortaram) | YouTube, conteúdo reutilizado [OFICIAL] | Não monetizável |
| Clipes "editados juntos com pouca ou nenhuma narrativa"; compilações sem conteúdo original | YouTube [OFICIAL] | Não monetizável; views inelegíveis |
| Reação quase sem fala ("reações majoritariamente não verbais" sem comentário em voz) | YouTube [OFICIAL] | Não monetizável |
| Conteúdo em massa, repetitivo, "que parece feito com template" | YouTube, conteúdo inautêntico (nome desde 15/07/2025) [OFICIAL] | Saída do YPP |
| Narrar o que aparece na tela, pequenas edições técnicas, mudanças em lote por template | YouTube, Creator Insider 01/10/2026 [OFICIAL via IMPRENSA] | Não conta como transformação |
| Espelhar, acelerar, mudar o tom para fugir da detecção | YouTube spam ("episódio espelhado para evitar detecção") [OFICIAL] | Remoção, aviso, strike |
| **Mesmo vídeo em várias contas próprias** | YouTube: "redes coordenadas de canais"; TikTok: contas que "tentam manipular a plataforma" [OFICIAL] | Remoção, alcance zero, risco para todas as contas |
| Ferramentas de automação ou scripts "feitos para burlar nossos sistemas" | TikTok, diretrizes de 25/08/2026 (em vigor desde 24/09/2026) [OFICIAL] | Até banimento |
| Criar ou usar outra conta para contornar restrição ou banimento | TikTok e YouTube [OFICIAL] | Banimento das contas adicionais (TikTok); encerramento de **todos** os canais (YouTube) |
| Engajamento falso (comprar views, seguidores, grupos de engajamento) | TikTok e YouTube [OFICIAL] | Remoção dos sinais inflados, fora do Para Você, desqualificação de monetização |
| Postar repetidamente conteúdo inelegível para o Para Você | TikTok [OFICIAL, citado em `algoritmo_e_riscos.md`] | A **conta inteira** pode ficar inelegível para recomendação |
| Rajadas, intervalos exatos, legendas e hashtags iguais, apagar e repostar | [MERCADO + INFERÊNCIA] | Restrição temporária ou queda de alcance |
| Marca d'água de outra plataforma (TikTok, Kick, Twitch) | TikTok, padrões do Para Você [OFICIAL, citado em `estrategia_conteudo.md`] | Fora do Para Você |

### 1.5 O que torna um corte elegível (as duas plataformas)

O YouTube diz o que **é permitido**: clipes usados em **análise crítica**, **react com comentário** sobre o original, e conteúdo alheio que você "muda significativamente para torná-lo seu" [OFICIAL]. Na prática, para cada corte do CORTEX:

1. **Comentário próprio que muda a leitura do trecho**: cartão de contexto (quem, onde, por que importa) e pelo menos 2 intervenções editoriais na tela (ver `algoritmo_e_riscos.md` §3.5). Narração que só descreve a tela **não conta**.
2. **Edição com intenção**: reenquadramento, cortes de respiração, zoom na ênfase, legenda; não só um template trocado em lote.
3. **Momento não saturado** (menos de 5 canais com o mesmo trecho em 7 dias).
4. **Sem música de terceiros** e sem imagem de TV, esporte ou filme.
5. **Variedade real** entre posts (3 ou mais identidades visuais, ganchos diferentes).
6. Para conteúdo **traduzido do inglês**: legenda traduzida **mais** contexto para o público brasileiro. Tradução sozinha é argumento fraco de transformação [INFERÊNCIA].
7. **Memes**: repost de meme é o caso mais claro de "não original". Só com comentário ou montagem narrativa própria; senão, fora.

---

## 2. Múltiplas contas

### 2.1 O que as regras dizem

| Tema | TikTok | YouTube |
|---|---|---|
| Uma pessoa com várias contas | **Permitido**: "Você pode ter várias contas, mas não para enganar outras pessoas ou quebrar as regras" [OFICIAL, diretrizes de 25/08/2026] | **Permitido**: até **100 canais** por Conta Google, via Contas de Marca [OFICIAL] |
| Pré-requisito | Cada conta pessoal precisa de **e-mail ou telefone próprios**: um telefone fica ligado a uma única conta pessoal ou comercial [OFICIAL, ajuda de anúncios do TikTok] | "Adicionar canais à sua conta" é um **recurso avançado** (histórico do canal ou verificação por documento ou vídeo) [OFICIAL] |
| Verificação por telefone | um número por conta | **Um número verifica no máximo 2 canais por ano** [OFICIAL] |
| Contas por aparelho | O seletor do app aceita cerca de 3 contas (número não oficial) [MERCADO] | Troca de canal dentro da mesma Conta Google, sem sair |
| Rede coordenada | Proíbe contas que "enganam ou tentam manipular a plataforma" e operações de influência encobertas [OFICIAL] | A política de spam cobre "redes coordenadas de canais" [OFICIAL] |
| Evasão de punição | Proibido criar ou usar outra conta para contornar restrição; o TikTok pode banir as contas adicionais [OFICIAL] | Após encerramento, proibido usar, possuir ou criar outros canais; vale para **todos** os seus canais existentes e para canais onde você aparece com frequência [OFICIAL] |
| Punição de monetização | n/a | A aplicação pode valer "para todos os seus canais existentes, canais novos e canais em que você aparece com frequência" [OFICIAL] |

### 2.2 Riscos de rodar tudo no mesmo PC, IP e navegador

- **Não é proibido** ter 2 ou 3 contas legítimas na mesma máquina e na mesma internet. O que pesa é o **comportamento**: conteúdo duplicado, postagem simultânea, engajamento cruzado entre as próprias contas e evasão [OFICIAL + INFERÊNCIA].
- **As plataformas vão ligar as contas de qualquer jeito** (mesma Conta Google, mesmo AdSense, mesmo CPF no pagamento, mesmo aparelho e IP). Consequência prática: **destino compartilhado**. Um banimento por evasão ou um encerramento no YouTube derruba todas. Por isso cada conta precisa ser limpa sozinha.
- **Não disfarçar.** VPN, proxy, rotação de IP, navegador antidetecção ou impressão digital falsa são justamente o padrão de quem burla sistemas, e o TikTok proíbe ferramentas "feitas para burlar nossos sistemas" [OFICIAL]. Separar contas é organização; esconder a ligação entre elas é evasão.
- **Separação técnica correta:** um **perfil de Chrome por conta do TikTok** (cookies separados, não disfarce); no YouTube, os canais podem ficar como Contas de Marca na Conta Google do dono, com um perfil de Chrome. Uma sessão de upload por vez.
- **Mesmo clipe em duas contas próprias da mesma plataforma: nunca.** É o padrão de rede coordenada e o segundo upload vira "duplicado" [OFICIAL + MERCADO].
- **Não interagir entre as próprias contas** (curtir, comentar, duetar uma à outra) [INFERÊNCIA].

### 2.3 Como separar as contas

| Dimensão | Regra |
|---|---|
| Nicho | Um nicho principal por **par** (TikTok X + YouTube X). Nenhum canal-fonte aparece em dois pares. |
| Conteúdo | Cada corte vai para **um único par**. Momentos diferentes do mesmo episódio ficam no mesmo par. |
| Horários | Grades defasadas: se o par A posta às 12:00, 18:30 e 21:00, o par B posta 45 a 90 min depois ou em outras janelas. |
| Identidade | Nome, @, logo, cores, bio e templates próprios em cada par. Nunca "Cortes X 2". |
| Texto | Legendas e títulos únicos; similaridade máxima de 0,6 contra as últimas 50 legendas **de todas as contas**. Hashtags de nicho diferentes. |
| Acesso | Perfil de Chrome separado por conta TikTok; e-mails próprios; nada de engajamento cruzado. |

### 2.4 Máximo realista para um operador solo em um PC

| Plataforma | Começar | Escalar para | Máximo realista | Por quê |
|---|---|---|---|---|
| TikTok | 1 conta (dia 0) e a 2ª no dia 14 | **2** | **3** | Cada conta exige uso manual nos primeiros dias, resposta a comentários, clique de publicar no modo semiautomático e revisão da página de status. Um 4º nicho bem distinto e com fonte própria é difícil de sustentar. |
| YouTube | 1 canal (dia 0) e o 2º no dia 14 | **2** | **3** | Telefone verifica só 2 canais por ano; canal adicional exige recursos avançados; cada canal é avaliado sozinho no YPP e herda o risco dos outros. |

**4 contas por plataforma** são permitidas pelas regras, mas para um operador solo o custo (tempo, risco compartilhado, nichos fracos) passa do benefício [INFERÊNCIA]. Com o teto prático por conta, **2 pares já consomem 12 posts por dia** e **3 pares, até 18**: bem mais do que o número de cortes realmente bons que um dia produz.

### 2.5 Como o CORTEX deve distribuir os cortes entre as contas

1. **Cada canal-fonte e cada tema pertence a um par** (tabela `contas` no config). Exemplo de divisão:
   - **Par A "Resenha"**: podcasts, entrevistas, celebridades, storytime e debates não políticos. É o par mais forte para o Creator Rewards (storytime de 61 a 90 s).
   - **Par B "Gameplay"**: GTA 6, streamers da Kick e da Twitch, games e reações. Atenção à rádio do GTA (música com Content ID).
   - **Par C (opcional, mês 3 em diante)**: escolher **um**: "Gringos legendados" (cortes traduzidos do inglês com contexto) **ou** "Plenário" (Câmara dos Deputados, CC BY 4.0). Memes só como tempero dentro de B ou C, com comentário.
2. **Orçamento diário por conta** = posts permitidos pela fase da conta (tabela 1.3). Somar os orçamentos de todas as contas = número de cortes a publicar no dia.
3. **Fila por nota**: os cortes de cada par entram numa fila ordenada pela nota; publica-se o topo da fila nas janelas do par. Corte que não sair em 24 a 36 h (assunto quente) é descartado; corte de acervo pode esperar.
4. **Um corte, um par**: o mesmo render nunca vai para duas contas da mesma plataforma. Guardar um hash do trecho-fonte (fonte + início + fim) e bloquear duplicata em qualquer conta.
5. **Versões por plataforma dentro do par**: TikTok recebe a versão longa (61 a 90 s, se a conta mira o Creator Rewards) ou o soco curto; YouTube recebe o núcleo (22 a 45 s; nunca acima de 58 s).
6. **Campanhas pagas**: o corte de campanha vai para o par do nicho correspondente e conta no orçamento daquela conta; cada post vale para **uma** campanha.
7. **Produção sob medida**: com 2 pares (cerca de 12 posts por dia), produzir **18 a 20 cortes por dia** basta (1,5 vez o necessário). Produzir 40 para publicar 12 desperdiça CPU e disco, que nesta máquina é pouco (cerca de 6 GB livres).

---

## 3. Monetização

### 3.1 YouTube

**Requisitos do YPP (Brasil está na lista dos dois níveis) [OFICIAL]:**

| Nível | Até 31/01/2027 | A partir de 01/02/2027 | O que libera |
|---|---|---|---|
| **Entrada** (fan funding e Shopping) | 500 inscritos + 3 uploads públicos em 90 dias + **3 M de views qualificadas de Shorts em 90 dias** (ou 3.000 h em 12 meses) | **Sem mudança** ("os limites de entrada de fan funding e shopping permanecem") | Clube de membros, Super Thanks e similares, e **Programa de Afiliados do YouTube Shopping** (exige estar no YPP e ter 500 inscritos; no Brasil com Mercado Livre e Shopee). **Não inclui anúncios.** |
| **Receita de anúncios** (entrada) | 1.000 inscritos + **10 M** de views qualificadas de Shorts em 90 dias (ou 4.000 h em 12 meses) | **20 M** de views qualificadas de Shorts em 90 dias **ou 8.000 h** em 365 dias (1.000 inscritos segundo a página de ajuda atual e a imprensa) | Anúncios em vídeos longos e acesso à receita de Shorts |
| **Receita de Shorts** (manutenção) | não havia | **10 M de views qualificadas de Shorts nos últimos 90 dias**, para todos os parceiros. Abaixo disso, o canal fica no YPP mas não recebe a receita de Shorts naquele mês; volta ao passar de 10 M de novo | Parte da receita de anúncios e do Premium no feed de Shorts |

Outras exigências: seguir as políticas de monetização, verificação em duas etapas na Conta Google, acesso a recursos avançados, nenhum strike de diretrizes ativo, uma conta AdSense para YouTube vinculada. Quem já é parceiro precisa aceitar os novos termos no Studio até 31/01/2027. Para canais abaixo de 10 M, o YouTube prometeu incentivos (bônus de Shopping, de publicidade e de tendências) **sem detalhes publicados** até hoje [OFICIAL].

**Implicação [INFERÊNCIA]:** um canal criado agora não chega a 10 M em 90 dias antes de 01/02/2027 (faltam 70 dias). A barra real é **20 M em 90 dias = ~222 mil views por dia**, e depois **~111 mil por dia** só para continuar recebendo dos Shorts. A meta de YouTube no primeiro ano é o **nível de entrada: 3 M em 90 dias = ~33 mil views por dia**, que libera o Shopping.

**Como a receita de Shorts é dividida [OFICIAL]:**
1. A receita dos anúncios exibidos entre Shorts no feed vira um bolo mensal.
2. Cada Short "contribui" segundo as **views engajadas**. Sem música, 100% vai para o fundo de criadores; com 1 faixa de música, metade; com 2, um terço.
3. O fundo é dividido entre os canais monetizados **por país**, na proporção das views engajadas de cada um.
4. O criador fica com **45%** da parte alocada.
5. **Não contam**: Shorts não originais ou reutilizados (clipes sem edição de filmes e TV, reenvio de conteúdo de outros criadores, compilações sem conteúdo original), views inválidas e conteúdo fora das diretrizes para anunciantes.

**RPM de Shorts no Brasil [MERCADO]:** **US$ 0,01 a 0,08 por mil views** (as faixas publicadas giram em torno de US$ 0,03 a 0,08 no geral, e o Brasil fica abaixo da média mundial). Conta de bolso: 10 M de views em 90 dias × US$ 0,03 = **~US$ 300 por trimestre**. Anúncio de Shorts não é modelo de negócio para o CORTEX.

**Content ID e receita [OFICIAL]:**
- Short **acima de 1 min com qualquer reivindicação**: bloqueado no mundo todo e sem monetização.
- Até 1 min: a página só reduz a contribuição ao fundo por **música** e diz que nenhum outro tipo de conteúdo de terceiros é creditado como contribuição, "mesmo quando há uma política de monetização do Content ID". A página **não deixa claro** se um claim de não música tira a receita do criador naquele Short [NÃO CONFIRMADO]. Na prática: claim acumula histórico negativo, e o mesmo trecho costuma cair também em "reutilizado". Tratar todo claim como perda.

**Conteúdo reutilizado em canal de cortes [OFICIAL]:** os revisores olham o tema principal, os vídeos mais vistos, os mais novos, os de maior tempo assistido, os metadados e a seção "Sobre". Se a violação for de reutilização, a monetização pode sair **do canal todo**, e a aplicação pode valer para **todos os canais** do dono. Por isso o canal tem que ser transformador **desde o primeiro vídeo** (seção 1.5), e não só quando for pedir o YPP.

**Um CPF, vários canais [OFICIAL]:**
- "Você também pode monetizar mais de um canal do YouTube usando a mesma conta AdSense para YouTube."
- Só pode existir **uma** conta AdSense ou AdSense para YouTube por titular (nome do beneficiário). Conta duplicada é reprovada e a monetização do canal ligado a ela é desligada.
- A conta AdSense vinculada só pode ser trocada **uma vez a cada 32 dias**; usar a conta de outra pessoa, mesmo com permissão, viola os termos.
- Cada canal faz a **própria** inscrição no YPP e precisa bater os números sozinho; views de um canal não somam para outro.

**Pagamento e impostos (pessoa física no Brasil). Não é aconselhamento tributário.**

| Etapa | O que acontece | Fonte |
|---|---|---|
| Moeda e meio | O AdSense paga brasileiros **em dólar**, por transferência internacional para a conta bancária do titular; a conversão para real é feita pelo banco ou plataforma de câmbio. | [MERCADO, consistente entre várias fontes] |
| Limites | Escolher a forma de pagamento a partir de **US$ 10**; pagamento a partir de **US$ 100** acumulados. | [OFICIAL] |
| Custos | IOF de câmbio de 0,38% na entrada, spread e tarifa do banco. | [MERCADO] |
| Informações fiscais dos EUA | Enviar no AdSense (pessoa física fora dos EUA: formulário W-8, normalmente o **W-8BEN**, com CPF como TIN estrangeiro). Prazo: **10 de dezembro de cada ano**. | [OFICIAL] |
| Retenção nos EUA | Retenção de **0 a 30%** só sobre o que vem de **espectadores dos EUA**, conforme tratado. Brasil e EUA **não têm tratado**, então a expectativa é **30%** dessa parte. Sem o formulário, pode haver retenção de **até 24% sobre os ganhos do mundo todo**. | [OFICIAL] + [IMPRENSA] |
| Brasil: carnê-leão | Rendimento recebido do exterior por residente é recolhido **mensalmente pelo carnê-leão**, até o **último dia útil do mês seguinte** ao recebimento, e depois entra na Declaração de Ajuste Anual. | [OFICIAL, Receita Federal] |
| Conversão | Pela regra da Receita, valores em moeda estrangeira são convertidos em dólar e depois em real pela cotação de **compra do Banco Central do último dia útil da 1ª quinzena do mês anterior** ao recebimento. | [OFICIAL via Portal Tributário, "Perguntas e Respostas IRPF"] |
| Imposto pago nos EUA | Pode ser compensado no carnê-leão e na declaração se houver tratado **ou reciprocidade**, até a diferença do imposto com e sem esse rendimento. Fontes contábeis indicam reciprocidade com os EUA; confirmar com o contador. | [OFICIAL via Portal Tributário] + [NÃO CONFIRMADO] |
| 2026 | A Lei 15.270/2025 zerou na prática o IR de quem tem renda mensal tributável de até R$ 5 mil a partir de 01/01/2026, com redução parcial até R$ 7.350. Contabilistas indicam que a redução também vale no carnê-leão. | [IMPRENSA] + [NÃO CONFIRMADO para carnê-leão] |
| Depois | Se a renda crescer, avaliar com contador abrir empresa (Simples Nacional) em vez de pessoa física. | [INFERÊNCIA] |

### 3.2 TikTok

**Programa de Recompensas do Criador (Creator Rewards Program)**

| Item | O que se sabe | Evidência |
|---|---|---|
| Disponível no Brasil? | **Sim, segundo várias fontes e a própria central de ajuda em pt-BR** (seção "Programa de Recompensas do Criador"). O Brasil aparece na lista de mercados ao lado de EUA, Reino Unido, Alemanha, França, Japão, Coreia do Sul e, em 2026, México. A lista oficial de países não pôde ser lida (as páginas do TikTok carregam por JavaScript). | [OFICIAL parcial] + [MERCADO]; conferir em TikTok Studio, Monetização |
| Sucessor em 2026? | **Não achei sucessor.** Os termos do programa foram atualizados em **20/07/2026** (versão EUA). | [OFICIAL] |
| Idade | 18 anos ou mais | [OFICIAL] |
| Seguidores | **10.000 seguidores autênticos** | [OFICIAL] |
| Views | **100.000 views autênticas nos últimos 30 dias** | [OFICIAL] |
| Tipo de conta | **Pessoal** e em situação regular. Conta Business ou de Organização não entra. | [OFICIAL] |
| Vídeo | **1 min ou mais**, publicado como público. Pela central de ajuda pt-BR: "conteúdo original de alta qualidade". | [OFICIAL] |
| Como paga | Por **views qualificadas** (em geral as do Para Você; não as vindas do perfil ou de anúncios). Fórmula considera **originalidade, duração assistida, valor de busca, engajamento** e valor publicitário. | [OFICIAL, newsroom 18/03/2024] + [MERCADO] para a definição de view qualificada |
| Quanto paga | **US$ 0,40 a 1,00 por mil views qualificadas** é a faixa mais citada; análise de jun/2026 vai de US$ 362 a 1.035 por milhão. **O Brasil fica na parte de baixo da faixa.** O TikTok não publica tabela. | [MERCADO] |
| Recebimento | Termos dos EUA: mínimo de **US$ 50**, pago todo dia 15, conta de pagamento **no nome do próprio criador**. No Brasil, relatos de PayPal e Pix. | [OFICIAL para os EUA] + [NÃO CONFIRMADO para o Brasil] |
| Conteúdo de cortes | Recompensa originalidade; tela dividida, compilações, loops e conteúdo com edição mínima tendem a ser excluídos. | [MERCADO, citando o Creator Academy] |
| Várias contas, um CPF | **Não achei regra oficial** que limite a uma conta por pessoa. Cada conta precisa bater os requisitos sozinha e passar pela verificação de identidade. Conteúdo duplicado entre as contas é causa citada de desqualificação. | [NÃO CONFIRMADO] + [MERCADO] |

**Outras fontes de receita no TikTok Brasil:**

| Caminho | Requisitos | Serve para o CORTEX? |
|---|---|---|
| **TikTok Shop, afiliados** (lançado no Brasil em **08/05/2025**) | 18+; **5 mil seguidores** no lançamento segundo a imprensa; blogs relatam **1 mil** desde jul/2026 [NÃO CONFIRMADO]; comissão por venda | Sim, no par B (games, periféricos) e talvez no A. Exige vídeo que mostre o produto; não colar link em corte de terceiro com a imagem do criador-fonte. |
| **LIVE e presentes** | 18+ para receber presentes; cerca de 1.000 seguidores para abrir LIVE [MERCADO] | Não: exige o dono ao vivo. |
| **Assinaturas** | Ligadas a quem faz LIVE [NÃO CONFIRMADO para 2026] | Não. |
| **Series** (conteúdo pago) | 18+, conta com 30+ dias, 10 mil seguidores (dados de 2023) [IMPRENSA] | Não: cobrar por trecho de terceiro é pedir problema de direito autoral. |

### 3.3 Campanhas pagas de cortes ("clipping")

| Plataforma | Como paga | Requisitos e regras | Valores observados |
|---|---|---|---|
| **Content Rewards (Whop)** | Valor por mil views definido pela campanha, pago **só após aprovação** do vídeo pela marca | Mínimo por vídeo antes de entrar na fila (ex.: US$ 6 a US$ 3/mil = 2.000 views); máximo por vídeo; plataformas aceitas por campanha (TikTok, Shorts, Reels, X); contas conectadas; views falsas, bots e grupos de engajamento banem e confiscam saldo; cada post vale para **uma** campanha | Média declarada ~US$ 1/mil; campanhas "Brazil Clips" a **US$ 0,25 a 0,30/mil** (medido em `estrategia_conteudo.md`) [OFICIAL docs + MERCADO] |
| **Cut.Pro** (brasileira, "campeonatos de cortes") | Por mil views ou por pódio; prêmio em créditos ou **Pix** | Grátis, **sem mínimo de seguidores** e sem aprovação para entrar; posts nas **próprias contas**; hashtags e @ obrigatórios; vídeo tem de ficar público até o fim da revisão; piso por vídeo (ex.: só paga a partir de 3 mil ou 5 mil views); teto por vídeo (R$ 150 a R$ 270); Pix validado em ~2 dias úteis; taxa de 20% paga pelo organizador; bot ou compra de views elimina | **R$ 1 a R$ 4 por mil views** nos exemplos de nov/2026 [MERCADO, página da plataforma] |
| **Programas de streamers (Discord)** | Por views, regras de cada criador | Tag, @ ou marca d'água para rastrear | Varia [MERCADO] |

Pontos práticos:
- **Campanha é a única receita disponível desde o dia 1** e ainda traz a **autorização do dono do conteúdo**, o que resolve boa parte do risco de direito autoral.
- Pagamento de plataforma estrangeira (Whop) é rendimento do exterior (carnê-leão); pagamento de empresa brasileira via Pix segue outra regra. Guardar comprovantes e perguntar ao contador.
- **Publicidade**: corte pago por campanha é conteúdo comercial. Marcar "promoção paga" no YouTube e "conteúdo comercial" no TikTok. Segundo a Cut.Pro, o guia do CONAR revisado em mai/2026 diz que pagar por resultado não tira o caráter publicitário [IMPRENSA via MERCADO, NÃO CONFIRMADO no CONAR].
- **Nunca** campanhas de apostas (MP 1.394/2026, ver `algoritmo_e_riscos.md` §4.3).

### 3.4 Outras plataformas em 2026 (para depois)

| Plataforma | Status no Brasil | Vale para cortes de terceiros? |
|---|---|---|
| **Kwai** | Programa de Receita de Anúncios por convite gradual: nível de criador acima de 6 ou 500+ fãs, conteúdo original, 12+ vídeos em 30 dias, média de 1.000+ views ou 10 mil no total, maioridade. Saque por Pix ou banco. A central de ajuda exclui de monetização filmes, séries e vídeos de outros criadores reenviados [MERCADO, citando a central do Kwai, nov/2026]. | **Não para monetizar.** Só como destino de campeonatos de cortes que aceitam Kwai. |
| **Instagram Reels** | Sem programa aberto de pagamento por view no Brasil; bônus de Reels foram por convite e encerrados em 2023 [MERCADO]. | Não. Alcance sim, receita não. |
| **Facebook Reels** | **Creator Fast Track chegou ao Brasil em 04/11/2026**: 20 mil seguidores em Instagram, TikTok ou YouTube, 30 mil views em 30 dias, 20 Reels **originais** por 30 dias em dias diferentes, por 3 meses; US$ 25 por mês (até US$ 75) para quem tem até 100 mil seguidores. Monetização de conteúdo segue por convite. Desde 07/2025 a Meta desmonetiza e reduz o alcance de quem reposta conteúdo alheio [IMPRENSA]. | Só depois que um par tiver 20 mil seguidores, e só com cortes com transformação forte. Baixa prioridade. |

---

## 4. Plano para o dono

### 4.1 Configuração recomendada

| Fase | Quando | Contas | Posts por dia (por conta) | Total por dia |
|---|---|---|---|---|
| 1. Largada | dia 0 | TikTok A + YouTube A (nicho "Resenha") | rampa da tabela 1.3 | 0 a 2 |
| 2. Segundo par | dia 14, só se o par A estiver em NORMAL, sem captcha nem aviso | + TikTok B + YouTube B (nicho "Gameplay") | A em 3 (TikTok) e 2 (YouTube), pois está nas semanas 3 e 4; B começa a rampa | 5 a 7 |
| 3. Cruzeiro | mês 2 | 2 TikTok + 2 YouTube | TikTok 3 a 4; YouTube 2 | 10 a 12 |
| 4. Escala (opcional) | mês 3 ou 4, só se A e B estiverem saudáveis e um deles já tiver passado de 10 mil seguidores no TikTok | + par C (um nicho distinto) | C faz a rampa do zero | até 18 |
| Teto | sempre | **3 TikTok + 3 YouTube** | TikTok 4 (6 com métricas); YouTube 2 (3 com métricas) | 18 a 27 |

### 4.2 Roteiro de monetização com marcos

| Marco | Meta | Prazo realista | O que libera | Ação |
|---|---|---|---|---|
| M0 | Contas criadas, 2FA, telefone verificado, perfis completos | semana 0 | rampa | checklist itens 1 a 9 |
| M1 | Inscrição em campeonatos de cortes de fontes autorizadas | semana 1 | receita por mil views (R$ 1 a 4/mil na Cut.Pro) | o dono se inscreve; o CORTEX prioriza fontes de campanha |
| M2 | TikTok A com 1.000 seguidores | dia 30 a 60 | LIVE; possivelmente afiliado do TikTok Shop (se o limite de 1 mil se confirmar) | conferir Monetização no TikTok Studio |
| M3 | TikTok A com **10 mil seguidores + 100 mil views em 30 dias** | dia 60 a 120 | **Creator Rewards** (~US$ 300 a 1.000 por milhão de views qualificadas, Brasil na parte de baixo) | 50 a 60% dos posts da conta com 61 a 90 s; inscrição manual; conta pessoal |
| M4 | YouTube A com **500 inscritos + 3 M de views de Shorts em 90 dias** (~33 mil por dia) | mês 4 a 8 | YPP nível de entrada + **Shopping afiliados** | criar o AdSense para YouTube na inscrição; enviar W-8BEN |
| M5 | TikTok B no Creator Rewards | mês 4 a 6 | segunda fonte TikTok | mesma regra do M3 |
| M6 | YouTube A com **1.000 inscritos + 20 M em 90 dias** (~222 mil por dia) | 12 meses ou mais, se acontecer | anúncios; receita de Shorts só enquanto mantiver 10 M em 90 dias | tratar como bônus, não como plano |

**Expectativa de receita por milhão de views (ordem de grandeza) [MERCADO + INFERÊNCIA]:**

| Fonte | Por 1 milhão de views | Observação |
|---|---|---|
| Campeonato Cut.Pro | R$ 1.000 a R$ 4.000 | limitado por teto por vídeo e orçamento da campanha |
| Content Rewards "Brazil Clips" | US$ 250 a 300 | idem |
| TikTok Creator Rewards (Brasil) | ~US$ 300 a 400 por milhão de views **qualificadas** | só vídeos de 1 min ou mais, só views do Para Você |
| YouTube Shorts (anúncios) | US$ 10 a 80 | e só com 10 M em 90 dias a partir de 01/02/2027 |

### 4.3 Checklist do que o dono faz pessoalmente

O CORTEX não cria conta, não digita senha, não resolve captcha e não se inscreve em programas. Tudo abaixo é manual.

**Contas e acesso**
1. Escolher os nichos dos pares A e B (e reservar a ideia do C).
2. Na Conta Google do dono: ativar **verificação em duas etapas**.
3. Criar o canal A como **Conta de Marca** (nome do nicho, não o nome do criador-fonte) e **verificar o telefone** (lembrar: 1 número verifica no máximo 2 canais por ano).
4. Pedir **recursos avançados** (histórico, documento ou vídeo). São necessários para criar o canal B na mesma conta e para o YPP.
5. Criar a conta **TikTok A pessoal** (não Business) com e-mail próprio, data de nascimento real, perfil completo; usar à mão por 3 dias (assistir ao nicho, seguir 10 a 20 contas).
6. Criar um **perfil de Chrome por conta do TikTok** e logar à mão. Sem VPN, proxy ou extensão de "stealth".
7. Repetir os itens 3, 5 e 6 para o par B no dia 14, se o par A estiver saudável.
8. Anotar a **data de criação** de cada conta no config (a rampa depende dela).
9. Configurar padrões de upload no YouTube: pt-BR, "não é conteúdo para crianças", conteúdo alterado ou sintético "não" (enquanto não houver IA realista), modelo de descrição com crédito e e-mail para detentores de direitos.

**Rotina**
10. Responder à mão os comentários da primeira hora nos primeiros 30 posts de cada conta.
11. Clicar em Publicar ou Agendar no TikTok (modo semiautomático) e conferir a página de status de cada conta 1 vez por dia.
12. Nunca interagir entre as próprias contas e nunca postar o mesmo corte em duas contas da mesma plataforma.

**Receita**
13. Inscrever-se à mão na **Cut.Pro** e no **Content Rewards**, registrar as campanhas no `campanhas.yaml` e enviar os links dos posts dentro do prazo.
14. Ao bater 10 mil seguidores + 100 mil views em 30 dias: TikTok Studio, Monetização, **Creator Rewards**; fazer a verificação de identidade e cadastrar o recebimento **no próprio nome**.
15. Ao bater 500 inscritos + 3 M em 90 dias: inscrever o canal no **YPP** pelo Studio; criar **uma** conta AdSense para YouTube no nome e CPF do dono (e depois vincular os outros canais à mesma conta); cadastrar conta bancária que receba transferência internacional em dólar.
16. No AdSense: enviar as **informações fiscais dos EUA** (W-8BEN, pessoa física, Brasil) e revisar até 10/12 de cada ano.
17. Ao entrar no YPP: pedir acesso ao **Shopping afiliados** se o nicho combinar.

**Impostos (com contador)**
18. Guardar todo comprovante de pagamento (Google, TikTok, Whop, Cut.Pro) e o contrato de câmbio de cada recebimento.
19. Recolher o **carnê-leão** (Carnê-Leão Web no e-CAC) até o último dia útil do mês seguinte a cada recebimento do exterior; informar na declaração anual.
20. Quando a renda mensal passar de ~R$ 5 mil, conversar sobre abrir empresa.

---

## 5. Fontes (todas acessadas em 23/11/2026)

**YouTube e Google (oficiais)**
- Blog do YouTube, mudanças no YPP a partir de 01/02/2027 (10/08/2026): https://blog.youtube/news-and-events/youtube-partner-program-updates-2027-new-opportunities-earn/
- Visão geral e qualificação do YPP: https://support.google.com/youtube/answer/72851?hl=en
- YPP expandido (nível de entrada) e países, Brasil incluído: https://support.google.com/youtube/answer/13429240?hl=en
- Políticas de monetização de Shorts (divisão de receita, 45%, 10 M a partir de 01/02/2027, Content ID): https://support.google.com/youtube/answer/12504220?hl=en
- Políticas de monetização de canais (conteúdo reutilizado e inautêntico, efeito em todos os canais): https://support.google.com/youtube/answer/1311392?hl=en
- Política de spam, práticas enganosas e golpes: https://support.google.com/youtube/answer/2801973?hl=en
- Encerramento de canal ou conta (vale para todos os canais): https://support.google.com/youtube/answer/2802168?hl=en
- Acesso a recursos (limites diários, canais adicionais como recurso avançado): https://support.google.com/youtube/answer/9890437?hl=en
- Verificar a conta (1 telefone, no máximo 2 canais por ano): https://support.google.com/youtube/answer/171664?hl=en
- Alternar entre canais (até 100 canais por Conta Google): https://support.google.com/youtube/answer/3046356?hl=en
- Erros comuns de upload (limite diário): https://support.google.com/youtube/answer/10383400?hl=en
- Dicas de cronograma de upload: https://support.google.com/youtube/answer/13616979?hl=en-GB
- AdSense para YouTube, vários canais numa conta e uma conta por titular: https://support.google.com/youtube/answer/72866?hl=en
- Requisitos fiscais dos EUA para criadores: https://support.google.com/youtube/answer/10391362?hl=en
- Limites de pagamento do AdSense (US$ 10 e US$ 100): https://support.google.com/adsense/answer/1709871?hl=en
- Custos de cota da YouTube Data API (`videos.insert` 100 por dia): https://developers.google.com/youtube/v3/determine_quota_cost
- Programa de afiliados do YouTube Shopping no Brasil: https://blog.youtube/intl/pt-br/news-and-events/yt-shopping-afiliados-brasil/ e https://www.youtube.com/intl/pt-BR/creators/partner-program/shopping

**YouTube (imprensa sobre mudanças de 2026)**
- Search Engine Journal, Shorts originais x clipes repostados (01/10/2026): https://www.searchenginejournal.com/youtube-original-shorts-reposted-clips-reach/591774/
- Search Engine Journal, novos termos e regra de 10 M: https://www.searchenginejournal.com/youtube-updates-partner-program-terms-shorts-payout-rules/585331/
- NewscastStudio (10/08/2026): https://www.newscaststudio.com/2026/08/10/youtube-partner-program-monetization-changes-2027/
- Search Engine Journal, esclarecimento de 07/2025 sobre reacts e clipes: https://www.searchenginejournal.com/youtube-clarifies-monetization-update-targeting-spam-not-reaction-channels/550755/

**TikTok (oficiais)**
- Diretrizes da Comunidade, integridade e autenticidade (lançadas em 25/08/2026, em vigor em 24/09/2026): https://www.tiktok.com/community-guidelines/en/integrity-authenticity
- Termos do Creator Rewards Program (versão EUA, atualizada em 20/07/2026): https://www.tiktok.com/legal/page/global/creator-rewards-program-us/en
- Lançamento do Creator Rewards Program (18/03/2024): https://newsroom.tiktok.com/introducing-the-new-creator-rewards-program?lang=en
- Central de ajuda pt-BR, Programa de Recompensas do Criador: https://support.tiktok.com/pt_BR/business-and-creator/creator-rewards-program/creator-rewards-program
- Content Sharing Guidelines (cerca de 15 posts por dia): https://developers.tiktok.com/doc/content-sharing-guidelines
- Referência do Direct Post (erros de spam): https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post
- Ajuda de anúncios do TikTok, telefone ligado a uma conta pessoal: https://ads.tiktok.com/help/article/about-organization-accounts-login-with-member-phone-or-email
- TikTok Shop chega ao Brasil (08/05/2025): https://newsroom.tiktok.com/tiktok-shop-chega-ao-brasil?lang=pt-BR
- TikTok Shop, primeiro ano no Brasil (04/06/2026): https://newsroom.tiktok.com/tiktok-shop-cresce-102-vezes-em-seu-primeiro-ano-no-brasil?lang=pt-BR

**Campanhas e outras plataformas**
- Whop, documentação do Content Rewards: https://docs.whop.com/memberships-and-access/third-party-apps/content-rewards.md
- Cut.Pro, como funciona um campeonato de cortes (2026): https://cut.pro/pt-BR/blog/campeonato-de-cortes-como-funciona-2026
- Cut.Pro, RPM comparado (27/08/2026): https://cut.pro/pt-BR/blog/rpm-tiktok-shorts-reels-comparado-2026
- Cut.Pro, quanto o Kwai paga (17/11/2026): https://cut.pro/pt-BR/blog/quanto-kwai-paga-por-mil-views-2026
- Social Media Today, Creator Fast Track no Brasil (04/11/2026): https://socialmediatoday.com/news/facebook-expands-creator-fast-track-program-to-brazil/873821
- TechCrunch, Meta contra conteúdo não original no Facebook (14/07/2025): https://techcrunch.com/2025/07/14/following-youtube-meta-announces-crackdown-on-unoriginal-facebook-content

**Volume e frequência (estudos)**
- Buffer, frequência no TikTok (11 M de posts): https://buffer.com/resources/how-often-should-you-post-on-tiktok/
- Metricool, tendências do YouTube 2026: https://metricool.com/youtube-trends/
- vidIQ, frequência de upload (jul/2026): https://vidiq.com/research/youtube-upload-frequency-study/

**Impostos (Brasil)**
- Receita Federal, carnê-leão: https://www.gov.br/receitafederal/pt-br/assuntos/meu-imposto-de-renda/pagamento/carne-leao
- Portal Tributário, imposto pago no exterior e conversão (com base no "Perguntas e Respostas IRPF"): https://www.portaltributario.com.br/irpf/o-imposto-sobre-a-renda-cobrado-pelo-pais.htm
- Contadores.cnt.br, Lei 15.270/2025 e carnê-leão (05/03/2026): https://contadores.cnt.br/projetos/46/noticias/tecnicas/2026/03/05/carne-leao-e-clt-as-novas-regras-que-mudam-a-retencao-de-impostos-em-2026.html
- Tecnoblog, retenção dos EUA para canais brasileiros (2021): https://tecnoblog.net/noticias/2021/03/09/youtube-vai-cobrar-imposto-sobre-ganhos-de-canais-nos-eua/
- Wise, IOF e recebimento do AdSense: https://wise.com/br/blog/como-receber-adsense-pela-remessa-online

### 5.1 O que não foi possível confirmar
- **Lista oficial de países do Creator Rewards** e os métodos de saque no Brasil: as páginas do TikTok carregam por JavaScript e não puderam ser lidas; a disponibilidade no Brasil vem da central pt-BR (título da seção) e de várias fontes secundárias.
- **Uma pessoa com várias contas no Creator Rewards**: nenhum texto oficial permite ou proíbe.
- **Requisito atual de seguidores do afiliado TikTok Shop no Brasil** (5 mil no lançamento; 1 mil relatado desde jul/2026).
- **Número de contas no seletor do app do TikTok** (3 é o mais citado, sem fonte oficial).
- **Se a redução da Lei 15.270/2025 se aplica ao carnê-leão** e **se o imposto retido nos EUA é compensável por reciprocidade**: confirmar com contador.
- **Efeito exato de um claim de não música na receita de um Short de até 1 min.**
- **Número de inscritos exigido em 2027**: o blog não o repete; a página de ajuda atual diz 1.000.
