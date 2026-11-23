# CORTEX: algoritmo, crescimento e riscos (TikTok + YouTube Shorts, Brasil)

> Data da pesquisa: **23/11/2026**. Escopo: contas **novas**, nicho de **cortes** em PT-BR, publicação por navegador real (Chrome logado pelo dono).
> Este documento só traz pesquisa e recomendações. Não contém código, e nada aqui foi testado em conta real.
> Seções do `config.yaml` analisadas: `execucao`, `corte`, `edicao`, `publicacao`.

**Legenda de evidência** (aparece entre colchetes ao longo do texto):
- **[OFICIAL]**: página de política, termos, ajuda ou blog oficial da plataforma, ou lei brasileira.
- **[ESTUDO]**: estudo com amostra grande feito por ferramenta de mercado (Buffer, Metricool, vidIQ, Sprout, Virlo). Mostra correlação, não causa.
- **[MERCADO]**: heurística de clipadores e vendedores de ferramentas. Não há confirmação das plataformas; use como ponto de partida.
- **[INFERÊNCIA]**: conclusão minha a partir das fontes acima.

---

## 0. Resumo executivo

O problema central do CORTEX hoje é o **volume**, e não a falta dele. O `config.yaml` atual permite **10 Shorts + 8 TikToks por dia**, com **90 a 240 segundos** entre posts, e o modo `revisar` "envia tudo de uma vez". Em conta nova, isso é exatamente o padrão que as plataformas tratam como spam: rajadas, volume alto e conteúdo de terceiros pouco transformado.

As 10 mudanças de maior impacto, em ordem:

1. **Rampa por idade da conta**: 0 posts nos dias 0 a 3; 1 por dia até o dia 10; 2 por dia até o dia 21; 3 por dia até o dia 42; depois até 4 por dia. Teto absoluto de **5 por dia** por plataforma, contra 10 e 8 hoje.
2. **Espaçamento**: no mínimo **150 min (TikTok) / 120 min (YouTube)** entre posts, com no máximo 1 post por janela de horário. O modo `revisar` passa a colocar os cortes numa **fila agendada** em vez de enviar tudo de uma vez.
3. **Camada de transformação obrigatória**: cartão de contexto de 2 a 3 s, pelo menos 2 comentários na tela, pergunta no final, zoom dinâmico e pelo menos 3 templates em rodízio. O fundo de gameplay (`split`) deixa de ser o layout padrão.
4. **Filtro de fontes de risco antes de baixar**: pular esporte transmitido, TV, filme e série, música, react de terceiros, **bets** (proibidas pela MP 1.394/2026) e menores; descartar trechos com **mais de 10% de música**.
5. **Duração por plataforma**: Shorts com **20 a 58 s** como limite rígido, porque um Short acima de 1 min com qualquer claim é bloqueado no mundo todo. TikTok com 25 a 45 s para alcance e **62 a 95 s** para o Programa de Recompensas.
6. **Máquina de estados de saúde da conta** (NORMAL, CAUTELA, PAUSA, PARAR), com limiares numéricos (seção 1.5).
7. **Janelas de horário em BRT**: o horário nobre é 20:30 a 22:30 nos dias úteis, 20:00 a 23:00 no sábado e 19:00 a 22:00 no domingo, com almoço e fim da tarde como janelas secundárias. As rodadas de produção devem acontecer 2 a 3 h antes.
8. **Termos de uso**: as duas plataformas proíbem acesso e interação automatizados. O caminho defensável é a **API oficial do YouTube** e o **semiautomático no TikTok**, em que o dono clica em Publicar ou usa o agendador nativo. Nunca usar stealth nem resolver captcha.
9. **Texto**: legendas únicas, **3 a 5 hashtags** (no máximo 1 fixa), sem `#viral` e sem `#fyp`, e crédito da fonte **na tela** e na descrição.
10. **Loop de métricas**: ler os dados em T+2 h, T+24 h, T+72 h e T+7 d, 2 vezes por dia, e alimentar um *bandit* (tema, fonte, duração, horário, template) e a memória do cérebro.

**Expectativa realista de monetização** [INFERÊNCIA]: para um canal novo, o Programa de Parceria do YouTube (YPP) por Shorts está praticamente fora de alcance no curto prazo. A partir de **01/02/2027**, quem entrar precisa de **20 milhões de views qualificadas de Shorts em 90 dias**. O caminho mais curto de receita é o **Programa de Recompensas do TikTok** (10 mil seguidores, 100 mil views em 30 dias e vídeos com pelo menos 1 min) e/ou **campanhas de cortes autorizados**, em que o próprio criador paga pelos cortes. Essas campanhas também resolvem o problema de direito autoral.

---

## 1. Aquecimento de conta nova

### 1.1 O que é fato e o que é folclore

- **Fato [OFICIAL]**: nenhuma das duas plataformas publica um "protocolo de aquecimento". O que existe de oficial são as regras de spam e de conteúdo, e um limite diário de envio. O YouTube diz que há um limite diário de uploads por canal, sem número público. A API do TikTok indica um teto de **cerca de 15 posts por dia por criador** via Direct Post, além de erros específicos como `spam_risk_too_many_posts` e `spam_risk_user_banned_from_posting`.
- **Fato [OFICIAL]**: no TikTok, quem posta repetidamente conteúdo que fere os padrões do feed Para Você (FYF) pode ter **a conta inteira** declarada inelegível para recomendação, não só o vídeo. Essa regra veio da atualização das diretrizes de 2024.
- **Dado [ESTUDO]**: no TikTok, postar mais aumenta as views por post de forma modesta. Comparado a 1 post por semana, 2 a 5 posts rendem até +17%, 6 a 10 rendem até +29% e mais de 11 rendem até +34% (Buffer, 11,4 milhões de posts). A mediana fica quase estável, e o ganho aparece nos posts do topo (p90). Volume compra **mais tentativas** de acertar um viral, mas não faz cada vídeo render mais. O vidIQ mostra o mesmo para Shorts: a mediana do 1º ao 10º Short fica em cerca de 1,3 mil views, e o melhor dos 10 chega a cerca de 8,8 mil.
- **Heurística [MERCADO]**: no TikTok, consumir conteúdo do nicho por 3 a 5 dias antes de postar, depois 1 post por dia na 1ª semana e 2 a 3 por dia na 2ª. Também é comum ver de 0 a poucas centenas de views nos primeiros vídeos. Ficar com **0 a 5 views em 3 ou mais posts seguidos** é tratado como conta marcada.

### 1.2 Cronograma recomendado (posts por dia, por plataforma)

| Fase | Dias desde a criação | TikTok | YouTube Shorts | Intervalo mínimo | Para avançar de fase (tudo precisa ser verdade) |
|---|---|---|---|---|---|
| 0. Uso humano | 0 a 3 (TT) / 0 a 2 (YT) | **0** | **0** | n/a | O dono usou a conta **manualmente** por 20 a 30 min por dia (assistiu ao nicho, seguiu de 10 a 20 contas do nicho) e o perfil está completo (seção 6). Nada disso é automatizado. |
| 1. Teste | 4 a 10 (TT) / 3 a 10 (YT) | **1** | **1** | n/a (1 post por dia, na janela A+) | Pelo menos 5 posts publicados, nenhum aviso na conta e pelo menos 3 dos últimos 5 posts com **50 views ou mais em 24 h** |
| 2. Rampa | 11 a 21 | **2** | **2** | 240 min | Mediana de 24 h ≥ **200 views (TT) / 150 (YT)** e participação do Para Você ≥ 50% (TT) |
| 3. Cruzeiro | 22 a 42 | **3** | **3** | 150 min (TT) / 120 min (YT) | Estado NORMAL por 7 dias seguidos e nenhum claim nos últimos 14 dias |
| 4. Escala | 43 em diante | **4** (teto de 5) | **4** (teto de 5) | 150 / 120 min | Mediana dos últimos 7 dias igual ou acima da dos 30 dias, e shares por mil views na média do canal ou acima |

Regras complementares:
- **Teto semanal**: 7 posts na fase 1, 14 na fase 2, 21 na fase 3 e 28 na fase 4, por plataforma.
- **Escala só com qualidade**: acima de 3 posts por dia, o 4º e o 5º post só saem se o corte tiver nota ≥ 75 (o `pontuacao_minima` atual é 55).
- **Nunca pular de fase por calendário.** A fase só avança quando os critérios da coluna da direita forem atendidos. Se a conta regredir para PAUSA, ela volta para a **fase 1**.
- **Uma conta por plataforma.** Nada de rede de contas no mesmo IP ou na mesma máquina. A diretriz do TikTok permite múltiplas contas, mas não para enganar nem para contornar restrições. Várias contas de cortes idênticas caem nas duas situações. [OFICIAL]

### 1.3 Espaçamento

- **Mínimo de 150 min no TikTok e 120 min no YouTube** entre dois posts da mesma plataforma, com no máximo **1 post por janela** (seção 2).
- **Uma plataforma de cada vez.** Nunca abrir duas sessões de upload em paralelo. Quando o mesmo corte vai para as duas, publicar com 20 a 60 min de diferença: primeiro no TikTok, onde o horário pesa mais, e depois no YouTube.
- **Sem publicação entre 01:00 e 06:30 BRT.** É a pior faixa de audiência, e post de madrugada é um padrão de comportamento atípico.
- **O modo `revisar` não pode virar rajada.** Aprovar 10 cortes significa colocar 10 cortes na fila, que sai ao longo de 3 a 4 dias.

### 1.4 Quando é seguro escalar

Os portões para avançar estão na tabela 1.2. Na prática, para uma conta saudável, a fase 3 (3 por dia) chega por volta da 4ª semana e a fase 4 por volta da 7ª. **Escalar acima de 4 por dia quase não traz ganho** em views por post, segundo os estudos do Buffer e da Metricool, e aumenta o risco [INFERÊNCIA]. O ganho real depois disso vem de **qualidade e seleção** (seção 7), não de mais volume.

### 1.5 Sinais de limitação ("shadow-limit") e detecção automática

É preciso separar **dois diagnósticos**, porque o remédio é diferente:

| Diagnóstico | Sinais | Remédio |
|---|---|---|
| **Distribuição restrita** (a plataforma não está mostrando o vídeo) | Views perto de 0; pouca participação do **Para Você** (TT) ou do **feed de Shorts** (YT); aviso de "não elegível para recomendação" no post; aviso na página de status da conta | Reduzir o volume ou pausar (backoff) e investigar se houve violação |
| **Conteúdo fraco** (a plataforma mostra, mas o público rola) | Participação do Para Você alta, porém retenção baixa; "visualizado vs. deslizado" (YT) baixo | **Não pausar.** Trocar fonte, tema, gancho ou duração (seção 7) |

**Máquina de estados** (avaliada após cada leitura de métricas, por plataforma):

- **NORMAL → CAUTELA** quando qualquer uma destas condições valer:
  - a partir do dia 15, **5 posts seguidos** com views em 24 h abaixo de **200 (TT) / 150 (YT)**;
  - a mediana dos últimos 5 posts, em 24 h, ficar abaixo de **25%** da mediana dos 30 dias anteriores;
  - no TikTok, participação do Para Você abaixo de **40%** nos últimos 5 posts com mais de 100 views;
  - **2 claims de direitos autorais em 7 dias**.
- **Efeito da CAUTELA (72 h)**: posts por dia caem pela metade (mínimo 1), o intervalo é multiplicado por 1,5, só saem cortes com nota ≥ 75 e as fontes com claim vão para a lista negra.
- **→ PAUSA** quando qualquer uma destas condições valer:
  - em qualquer fase, **3 posts seguidos com menos de 10 views em 24 h** (com o vídeo público e sem aviso);
  - CAUTELA por 2 ciclos seguidos (6 dias);
  - 2 posts marcados como "inelegível para o Para Você" ou "restrito" em 7 dias.
- **Efeito da PAUSA**: **0 posts por 72 h**, notificação ao dono para conferir a página de status da conta à mão, e retorno na **fase 1** (1 por dia) por 5 dias.
- **→ PARAR** (exige o dono; volta só com um comando manual como `fabrica retomar tiktok`) quando ocorrer qualquer um destes:
  - strike de direitos autorais ou de diretrizes;
  - aviso de violação ou de inelegibilidade **da conta**;
  - captcha ou verificação de identidade;
  - erro de "limite diário de envio" ou "muitas publicações";
  - sessão expirada.

**Notas de implementação:**
- Use **views em 24 h** como métrica principal de alarme e **72 h** para aprendizado. No YouTube, o Short tem cauda longa (o efeito "slow burn" da Metricool 2026), então não convém concluir nada antes de 72 h.
- No YouTube, desde 31/03/2025, "views" conta cada vez que o Short começa a tocar ou repete. Para comparar desempenho, use **visualizações engajadas** (*engaged views*), a métrica que vale para o YPP. [OFICIAL, via cobertura]
- **Não** apagar e repostar um vídeo que foi mal. Isso gera conteúdo duplicado e é um sinal clássico de spam. [MERCADO + INFERÊNCIA]

### 1.6 Backoff em erros de publicação

| Evento no navegador | Ação |
|---|---|
| Captcha, "confirme que é você", verificação por telefone ou documento | **PARAR** a plataforma, marcar "AÇÃO NECESSÁRIA" e não tentar de novo sozinho |
| "Limite diário de envio" (YT) ou "você está postando rápido demais" (TT) | PARAR por 24 h e **reduzir o teto diário em 1** de forma permanente |
| Upload travado ou erro genérico | No máximo **1** nova tentativa, depois de 30 min. Se falhar de novo, o corte volta para a fila do dia seguinte |
| Sessão deslogada | PARAR e pedir login manual (o CORTEX nunca digita senha) |

---

## 2. Melhores horários no Brasil (BRT, UTC−3)

### 2.1 O que as fontes dizem

- **Brasil [ESTUDO, Opinion Box via Stone]**: **24%** dos acessos ao TikTok acontecem entre 18 h e 20 h e **29%** entre 20 h e meia-noite. Ou seja, mais da metade do uso fica na faixa das 18 h às 24 h.
- **Buffer 2026 [ESTUDO]** (7,1 milhões de posts, horários locais): melhor horário geral **domingo 9 h**, depois segunda 13 h e domingo 13 h. As views costumam atingir o pico **à noite (18 h a 23 h)**, e o melhor horário de sexta é 18 h. Por dia, o melhor é o **sábado** e os piores são quarta e quinta.
- **Metricool 2026 [ESTUDO]**: a atividade se concentra **a partir das 16 h, com pico às 20 h**. Os melhores horários por dia: seg 19 h, ter 16 h, qua 17 h, qui 17 h, sex 16 h, sáb 17 h, dom 20 h.
- **Sprout Social (nov/2025 a fev/2026) [ESTUDO]**: dias úteis à tarde (13 h a 18 h). Fim de semana e madrugada são os piores.
- **YouTube Shorts**: não existe estudo brasileiro sólido. Guias de mercado apontam **almoço (12 h a 15 h) e noite (19 h a 22 h)**. A Metricool 2026 mostra vida útil maior dos vídeos no YouTube, o que faz o horário pesar menos lá do que no TikTok. [ESTUDO + INFERÊNCIA]

**Síntese [INFERÊNCIA]**: as fontes divergem nos detalhes, mas todas convergem para a **noite** como horário nobre no Brasil, com **almoço** e **fim de tarde** como janelas secundárias e **manhã de domingo** como exceção forte. O Brasil não tem horário de verão desde 2019. Use `America/Sao_Paulo`; a maior parte da população está em UTC−3.

### 2.2 Janelas recomendadas (BRT)

Prioridade: **A+** recebe o melhor corte do dia; **A** o segundo; **B** o terceiro; **C** só a partir do 4º post por dia.

| Dia | A+ | A | B | C |
|---|---|---|---|---|
| Seg a Qui | 20:30 a 22:30 | 18:00 a 19:30 | 12:00 a 13:30 | 07:00 a 08:30 |
| Sexta | 18:00 a 20:00 | 21:00 a 23:00 | 12:00 a 13:30 | 07:00 a 08:30 |
| Sábado | 20:00 a 23:00 | 16:00 a 18:00 | 10:00 a 12:00 | 13:30 a 15:00 |
| Domingo | 19:00 a 22:00 | 09:00 a 11:00 | 13:00 a 14:30 | 16:00 a 17:30 |

### 2.3 Como o CORTEX deve usar isso

- **Publique nos primeiros 30 min da janela.** No TikTok, o lote inicial de distribuição acontece nas primeiras horas, então o post precisa estar no ar quando o público chega. [MERCADO + INFERÊNCIA]
- **O TikTok fica com as janelas A+ e A.** O YouTube pode usar A e B, porque o Short ganha alcance por mais tempo.
- **Produção antes da janela.** Hoje as rodadas rodam às `09:00, 13:00, 18:00, 22:00`, e a das 22 h produz cortes que só sairiam no dia seguinte, já menos frescos. Recomendo **3 rodadas: 09:30, 15:30 e 18:30**. Elas alimentam as janelas de 12 h, 18 h e 20:30 a 22:30. O corte de assunto do momento vale por **24 a 36 h**; depois disso, descartar.
- **Testar horários com explore/exploit.** Cerca de 85% dos posts vão para as janelas acima e cerca de 15% para janelas "de teste". Depois de 3 semanas, reponderar pelas métricas da própria conta. A aba de Seguidores do TikTok Studio e a aba Público do YouTube Studio mostram quando os seus seguidores estão ativos, e esse dado vence qualquer estudo genérico.

---

## 3. Duração ideal e monetização

### 3.1 Duração por plataforma

| | YouTube Shorts | TikTok |
|---|---|---|
| Limite técnico | até 3 min (desde out/2024) [OFICIAL] | uploads longos são permitidos |
| **Mínimo** | 20 s | 20 s |
| **Alvo de alcance** | **30 a 50 s** | **25 a 45 s** |
| **Alvo de monetização** | não se aplica | **62 a 95 s** (o Programa de Recompensas exige pelo menos 1 min) |
| **Máximo** | **58 s (rígido)** | 120 s como padrão; até 150 s só se a história sustentar |
| Séries ("Parte X") | partes de 45 a 58 s | partes de 62 a 90 s |

**Por que 58 s no YouTube [OFICIAL]:** pela política de monetização de Shorts, *"Shorts com mais de 1 minuto que tenham conteúdo reivindicado ficam bloqueados e não são elegíveis para monetização"*. O bloqueio vale **no mundo todo**, qualquer que seja a política do claim, inclusive claims manuais. Para um canal de cortes, praticamente todo material é de terceiros, então passar de 60 s no YouTube é apostar em bloqueio.

**Evidências sobre o TikTok:**
- Virlo, com vídeos de out/nov de 2026 comparados contra vídeos parecidos: menos de 15 s = **1,40×**; 15 a 30 s = 1,03×; 30 a 60 s = **0,82×**; 1 a 3 min = **0,88×**. Como 30 a 60 s e 1 a 3 min ficam praticamente empatados, **passar de 60 s não custa alcance** e libera o Programa de Recompensas. [ESTUDO + INFERÊNCIA]
- Socialinsider: vídeos mais longos acumulam mais views brutas, e vídeos de cerca de 30 s têm o maior engajamento. [ESTUDO]
- Shorts: a duração média vista caiu para cerca de **16 s por Short** (Metricool 2026). O gancho no primeiro segundo é o que decide. [ESTUDO]

**Estratégia [INFERÊNCIA]:**
- **Antes de 5 mil seguidores no TikTok**: 60% dos posts curtos (25 a 45 s) e 40% longos (62 a 95 s).
- **Depois de 5 mil seguidores**: inverter para 40% curtos e 60% longos.
- **No YouTube**: sempre 58 s ou menos.

Como implementar: o cérebro deve devolver, dentro de cada `ClipPlan`, um **"núcleo"** (`core_start` e `core_end`, com até 55 s). O editor renderiza duas versões: a **longa** para o TikTok e o **núcleo** para o YouTube.

**Proibido:** encher linguiça ou fazer loop para chegar a 1 min. O TikTok exclui conteúdo em loop e de baixa qualidade. [MERCADO, citando o FAQ do Creator Academy]

### 3.2 Programa de Recompensas do TikTok (Creator Rewards)

**Requisitos [OFICIAL, termos do programa]:**
- 18 anos ou mais;
- pelo menos **10.000 seguidores autênticos**;
- pelo menos **100.000 views autênticas nos últimos 30 dias**;
- conta **pessoal** em situação regular (contas **Business** e de organização **não** são elegíveis, nem contas de políticos ou partidos);
- vídeos com **pelo menos 1 min**, publicados como públicos.

**Mais detalhes:**
- O TikTok pode "silenciar, remover ou desqualificar" vídeos com uso não autorizado de música. [OFICIAL]
- No Brasil, o programa existe desde o *beta* do "Programa Criativo" em 2023, que já exigia vídeos com mais de 1 min. [Imprensa BR]
- A página de suporte em PT-BR exige "conteúdo original de alta qualidade" e vídeos de "um minuto ou mais". [OFICIAL]
- Só contam views **qualificadas**, em geral as do Para Você e não as vindas do perfil ou de anúncios. Valores reportados: cerca de **US$ 0,40 a 1,00 por mil views qualificadas**. [MERCADO]
- **Originalidade [MERCADO, citando o FAQ do Creator Academy]**: é "não original" o conteúdo *copiado de outros ou com edição e contribuição original mínimas*. **Filtros, texto, adesivos e mudança de velocidade não contam como transformação.** Tela dividida, reações sem sentido, slideshows, conteúdo em loop e compilações de clipes de terceiros são excluídos com frequência.
- **Recomendação**: manter a conta como **pessoal**, nunca Business.

### 3.3 YouTube Partner Program (Shorts)

**Hoje (até 31/01/2027) [OFICIAL]:**
- **Receita de anúncios**: 1.000 inscritos e **10 milhões de views qualificadas de Shorts em 90 dias**, ou 4.000 horas de vídeo longo em 12 meses.
- **Nível de entrada** (fan funding e Shopping; *não* inclui anúncios): 500 inscritos, 3 uploads públicos em 90 dias e **3 milhões de views de Shorts em 90 dias**.
- Exigências adicionais: verificação em duas etapas, acesso a recursos avançados, nenhum strike ativo e AdSense vinculado.
- O Brasil está na lista de países do YPP.

**A partir de 01/02/2027 [OFICIAL, blog do YouTube, 10/08/2026]:**
- Novos entrantes precisam de **1.000 inscritos** e **20 milhões de views qualificadas de Shorts em 90 dias**, ou **8.000 horas** em 365 dias.
- Quem já está no YPP precisa manter **10 milhões em 90 dias** para continuar recebendo da receita de Shorts.
- O nível de fan funding não muda.

**Implicação [INFERÊNCIA]:** um canal criado hoje não chega a 10 milhões antes de fevereiro, então na prática enfrentará a barra de **20 milhões em 90 dias**. O YouTube deve ser tratado como **canal de alcance e de marca**. A meta de receita de curto prazo fica no TikTok e nas campanhas (seção 3.7).

### 3.4 Conteúdo reutilizado e não original: o que exatamente precisa ser adicionado

**YouTube, política de "conteúdo reutilizado" [OFICIAL]:**

Vale para o **canal inteiro**. Os revisores olham o tema principal, os vídeos mais vistos e os mais recentes. Se houver vídeos em violação, a monetização pode ser retirada **do canal todo**.

- **Permitido** quando o espectador percebe uma *diferença significativa* em relação ao original. Exemplos: clipes usados em **análise crítica**; **react com comentário** sobre o original; vídeos de outros criadores **editados com narrativa e comentário adicionados**; edição com efeitos de áudio ou vídeo **substanciais**.
- **Não permitido**:
  - clipes "editados juntos com pouca ou nenhuma narrativa";
  - "vídeos curtos compilados de outras redes sociais";
  - "conteúdo enviado muitas vezes por outros criadores";
  - "promoção do conteúdo de outras pessoas, mesmo com permissão";
  - conteúdo copiado sem modificação substantiva.
- **"Conteúdo inautêntico"** (nome novo, desde 15/07/2025, do que antes se chamava "conteúdo repetitivo"): conteúdo que "parece feito com um template" ou é produzido em massa. A mesma vinheta de abertura e de encerramento é aceitável **se o conteúdo principal variar**.
- A empresa esclareceu que "não há mudanças nas políticas de conteúdo reutilizado sobre clipes, compilações e reacts". Esses formatos seguem monetizáveis com "comentário original significativo, modificações ou valor educativo ou de entretenimento". [OFICIAL, via Search Engine Journal]

**Política de spam do YouTube [OFICIAL]:**
- Proíbe "usar ferramentas automatizadas ou IA para gerar muito conteúdo semelhante com mudanças mínimas".
- Cita como exemplo proibido em Shorts o reenvio de trechos de vídeos famosos "sem edição transformadora, reação ou explicação".
- Cita **espelhar o vídeo para evitar a detecção**.

**TikTok [OFICIAL]:** conteúdo é inelegível para o Para Você "se incluir material não original ou reutilizado, sem nenhuma novidade". O orientador é "publique somente conteúdo que você criou ou que tem o direito de compartilhar".

**Ponto crítico para cortes brasileiros [INFERÊNCIA]:** os momentos virais de podcasts grandes são cortados por dezenas de canais. Isso cai literalmente em "conteúdo enviado muitas vezes por outros criadores". O CORTEX precisa **medir a saturação** de cada momento antes de cortá-lo (seção 4.5).

### 3.5 Camada de transformação automatizável (receita para o pipeline)

Teste prático: **"se eu tirar o vídeo-fonte, sobra alguma coisa do canal?"** Se a resposta for não, é repost. [MERCADO]

O CORTEX deve garantir **no mínimo 4 dos 7 itens abaixo em todo corte**, com os itens 1 e 2 sempre presentes:

1. **Cartão de contexto no início (1,5 a 3 s)**: o cérebro escreve em uma frase quem é a pessoa, o que está em jogo e por que importa, por exemplo "Ex-BBB rebate acusação de X ao vivo". Não é um título genérico; é contexto que o vídeo-fonte não tem.
2. **Pelo menos 2 comentários na tela** durante o corte, em balões ou faixas com voz editorial própria: "Contexto: ...", "Isso é falso porque...", "Repara na reação dele". O cérebro gera a partir da transcrição e das notícias da busca de tendências.
3. **Narração própria** na abertura e/ou no fechamento: TTS com uma voz **genérica e fixa do canal**, que funciona como marca. **Nunca** clonar a voz de quem aparece no corte (seção 3.6).
4. **Pergunta ou opinião no final (2 a 4 s)**: "Ele estava certo? Comenta", ou "Parte 2 no perfil". Isso gera comentários, que são um sinal forte de engajamento.
5. **Edição ativa**: zoom ou *punch-in* nas palavras de ênfase, reenquadramento que segue quem está falando (layout `full`), cortes de respiração e silêncio, e legenda karaokê.
6. **Estrutura editorial**: séries com resumo de 3 s no começo de cada parte ("No episódio anterior..."), ou compilação temática *com narrativa* que costura 2 ou 3 momentos ("3 vezes em que X mudou de opinião").
7. **Rodízio de templates**: pelo menos **3 identidades visuais** (cores, fonte, posição do título, estilo do cartão) em rotação, e variação no texto do gancho. Isso combate o enquadramento como "conteúdo inautêntico".

**Mudar o layout padrão.** O `layout: auto` atual com `split` (vídeo em cima e gameplay embaixo) é o formato "brainrot" mais associado a cortes de baixo esforço. A tela dividida aparece entre os formatos excluídos do Programa de Recompensas [MERCADO]. Recomendo `full` (rosto reenquadrado) ou `blur` como padrão, e `split` em no máximo 10% dos cortes, só quando o trecho for apenas áudio, sem imagem útil.

**Nunca fazer (é evasão, e a política de spam cita isso nominalmente):** espelhar, acelerar ou desacelerar, mudar o tom do áudio, colocar bordas ou molduras para fugir do Content ID, ou manter a marca d'água de outra plataforma.

### 3.6 IA e rótulos

- **YouTube [OFICIAL]**: é obrigatório divulgar conteúdo sintético **realista**, como a voz sintética de uma pessoa real ou a troca de rosto. Narração com TTS genérico **não exige rótulo**, desde que não imite uma pessoa real.
- **TikTok [OFICIAL]**: é obrigatório rotular conteúdo gerado por IA com imagem, áudio ou vídeo **realistas**, por exemplo uma pessoa real cuja voz ou fala foi alterada.
- **Regra para o CORTEX**: voz de narrador genérica e sem rótulo. **Proibido** gerar voz, rosto ou fala sintética de pessoas reais, especialmente de políticos. Se algum dia usar imagem realista gerada por IA, ligar o rótulo de IA nas duas plataformas.

### 3.7 Caminho de receita mais realista

- **Campanhas de cortes pagas ("clipping")**: streamers, plataformas como a Kick e marcas pagam clipadores por alcance. Valores reportados vão de **US$ 0,50 a US$ 25 por mil views**, com média em torno de US$ 1. [MERCADO]
- **Vantagem dupla [INFERÊNCIA]**: além da receita, a campanha vem com **autorização do dono do conteúdo**, o que elimina a maior parte do risco de direito autoral.
- **Como implementar**: um "modo campanha" com fontes em lista branca e regras de briefing (crédito obrigatório, hashtags da campanha).
- **Atenção**:
  - Permissões mudam. O PodPeople, por exemplo, **revogou em 01/01/2026** a autorização genérica de cortes e passou a exigir autorização expressa.
  - Desde a **MP 1.394/2026** (25/09/2026), qualquer conteúdo que promova apostas de quota fixa para o público brasileiro é proibido. Campanhas pagas por bets estão fora.

---

## 4. Direitos autorais

### 4.1 Como funciona [OFICIAL]

- **YouTube Content ID**: os detentores (emissoras, ligas, gravadoras e alguns podcasts grandes) enviam arquivos de referência, e a comparação com cada upload é automática, inclusive em Shorts.
  - O claim pode **monetizar a favor do detentor**, **rastrear** ou **bloquear**.
  - Em Shorts com **mais de 1 min**, *qualquer* claim significa **bloqueio global**.
  - Um claim **não é strike**.
- **Strike de direitos autorais**: vem de um pedido de remoção válido. Expira em 90 dias, desde que o curso de direitos autorais seja concluído. **3 strikes em 90 dias encerram o canal e os canais associados.** Não há aviso prévio.
- **TikTok**: remove conteúdo que infringe direitos e **bane quem infringe repetidamente**. Em casos graves, o banimento é imediato, e o TikTok pode impedir a criação de uma conta nova. Os termos do Programa de Recompensas permitem silenciar ou desqualificar vídeos com música não autorizada.

### 4.2 O que tipicamente gera claim, remoção ou strike em cortes

Em ordem de risco [MERCADO + INFERÊNCIA]:

1. **Música**: trilha de fundo, música tocando na live, abertura de podcast com música licenciada, show ou DVD. É a causa número 1 de claim automático.
2. **Esporte transmitido**: jogos, gols e "melhores momentos". O Brasileirão 2026 tem direitos repartidos entre **Globo, Record, CazéTV/YouTube e Prime Video**, todos detentores ativos.
3. **TV aberta e paga**: telejornais, novelas, realities (BBB, A Fazenda) e programas de auditório.
4. **Filmes, séries, anime e trailers.**
5. **React de terceiros**: streamer assistindo jogo, filme ou vídeo de outro canal. Aqui o risco é duplo, porque o conteúdo de baixo é de terceiros.
6. **Podcasts que usam Content ID** para proteger os próprios canais de cortes, ou que revogaram a autorização de cortes.
7. **Trechos longos ou muitos trechos da mesma fonte.** O "pequeno trecho" vira "parte substancial da obra".

### 4.3 Lei brasileira, em resumo [OFICIAL]

- **Lei 9.610/98, art. 46**:
  - o **inciso III** permite **citação** "para fins de estudo, crítica ou polêmica, na medida justificada", com nome do autor e origem;
  - o **inciso VIII** permite reproduzir **pequenos trechos** "sempre que a reprodução em si não seja o objetivo principal da obra nova".
  - **[INFERÊNCIA]**: num canal de cortes **sem** transformação, o trecho *é* o objetivo principal, e a exceção fica fraca. Com comentário e crítica de verdade (seção 3.5), a tese do inciso III melhora. As plataformas, porém, decidem pelo sistema delas, e a lei brasileira não impede um claim automático.
- **Lei Geral do Esporte (14.597/2023), art. 163**: imagens de evento esportivo só podem ser usadas para **fins exclusivamente jornalísticos**, com limite de **3% do tempo do evento e no máximo 30 s**, sem associação a patrocínio ou publicidade e com notificação prévia ao detentor. **Canal de cortes monetizado não se enquadra.** Por isso: **pular esporte transmitido.**
- **MP 1.394/2026 (bets)**:
  - o art. 16 veda publicidade, marketing e patrocínio de apostas de quota fixa "em qualquer meio físico ou digital", e alcança qualquer conteúdo que "ofereça, promova, divulgue ou facilite o acesso" a apostas;
  - os arts. 19 e 20 obrigam as plataformas a remover esse conteúdo depois de notificadas.
  - **Consequência para o CORTEX**: cortar trechos com merchandising de bet, como o logo no cenário, um cupom ou um "patrocinado por", passou a ser risco legal e risco de remoção. *(A MP tem força de lei, mas depende de conversão pelo Congresso. Confirme o status antes de qualquer decisão.)*
- **Menores**: a própria página do YPP no Brasil cita a exigência de autorização judicial para monetizar conteúdo que mostra regularmente a imagem ou a rotina de menores (art. 34 do Decreto 12.880). **Pular** trechos em que um menor é o protagonista.

### 4.4 Práticas seguras

- **Lista branca de fontes com permissão comprovada.** Guardar a URL da política ou do post de autorização, a data de verificação e a data de revalidação (a cada 90 dias).
- **Crédito duplo.** Na **tela**, nos 3 primeiros segundos ou fixo no canto ("Fonte: @canal"), e na **descrição**, com nome e link. O `creditar_fonte: true` atual cobre só a descrição.
- **E-mail para detentores na bio e na descrição do canal** ("Detentor de direitos? Remoção em 24 h: email"). Atender rápido diminui a chance de strike, porque o detentor tende a pedir em vez de derrubar. [INFERÊNCIA]
- **Sem música.** Descartar trechos com música; nunca adicionar música de fundo fora da biblioteca de áudio nativa de cada plataforma. Como o CORTEX não usa o editor nativo, **o mais seguro é não ter música nenhuma.**
- **Contestação de claim**: só quando houver autorização documentada. Caso contrário, aceitar e colocar a fonte na lista negra.

### 4.5 Detecção automática de fontes de risco (antes de baixar)

| Sinal | Onde obter | Regra |
|---|---|---|
| Categoria do vídeo | `yt-dlp` → `categories` | `Music`, `Sports` ou `Film & Animation` → **pular** |
| Música identificada | `yt-dlp` → `track`, `artist`, `album` presentes | → **pular** o vídeo, ou ao menos o trecho da música |
| Licença | `yt-dlp` → `license` | "Creative Commons" → **bônus de prioridade** |
| Canal | lista de bloqueio sugerida na seção 9 | emissoras, ligas, gravadoras → **pular** |
| Título e tags | regex (seção 9) | jogo ("Time x Time"), "gols", "melhores momentos", "BBB", "novela", "trailer", "clipe oficial", "react" → **pular** |
| Categoria Twitch/Kick | metadado da live ou do clipe | `Music`, `Sports`, watch party → **pular** |
| Proporção de música no trecho | segmentador fala/música no áudio do trecho (por exemplo um classificador do tipo inaSpeechSegmenter ou YAMNet) | música acima de **10%** do trecho → descartar. No YouTube, **qualquer** música em corte com mais de 50 s → descartar |
| Bets e publicidade | transcrição do trecho | "bet", "aposta", "odd", "cupom", "código promocional", "patrocinado", nomes de casas de apostas → **pular o trecho** |
| Menores | (opcional) detector de idade aparente ou palavras-chave ("meu filho", "criança") | menor como protagonista → **pular** |
| **Saturação do momento** | busca `ytsearch20:` pela frase de 8 a 12 palavras mais marcante do trecho | **5 ou mais Shorts de canais diferentes nos últimos 7 dias** → pular, ou exigir o nível máximo de transformação |
| Histórico de claim | banco SQLite (seção 7) | 1º claim → fonte bloqueada por 30 dias; 2º claim → bloqueio **permanente** |

---

## 5. Riscos da automação

### 5.1 O que os termos dizem (risco estrutural) [OFICIAL]

- **YouTube (Termos de Serviço, "Permissões e restrições")**: é proibido acessar o serviço "por meios automatizados (como robôs, botnets ou scrapers)". As exceções são mecanismos de pesquisa públicos que respeitam o robots.txt, ou "mediante permissão prévia por escrito do YouTube".
- **TikTok (Termos, seção 5)**: é proibido "usar scripts automatizados para colher informações dos Serviços ou de outra forma interagir com os Serviços". As **Diretrizes** acrescentam que "é expressamente proibido o uso de ferramentas de automação, scripts" para contornar os sistemas, com punições que vão até o banimento.
- **Leitura honesta [INFERÊNCIA]**: postar e ler métricas por Playwright num navegador logado é, *pela letra dos termos*, uma forma de interação automatizada, **mesmo na conta do próprio dono e em volume baixo**. Volume baixo e ritmo humano **reduzem** a chance de enforcement, mas **não tornam a prática permitida**. O risco máximo é a perda da conta. A equipe precisa assumir isso de forma consciente.

### 5.2 Caminhos oficiais que eliminam o risco de termos

- **YouTube Data API v3 (`videos.insert`)** [OFICIAL]:
  - é o caminho permitido para enviar vídeos ao **próprio canal**, com OAuth;
  - a cota padrão é de 10.000 unidades por dia, e um upload custa cerca de 1.600 unidades, o que dá **cerca de 6 uploads por dia**, mais do que suficiente para a rampa da seção 1;
  - projetos não verificados criados depois de 28/07/2020 publicam como **privado** até passarem pela **auditoria de conformidade da API**.
  - **Recomendação**: migrar a publicação do YouTube para a API, com auditoria, e ler métricas pela **YouTube Analytics API**, também oficial.
- **TikTok Content Posting API (Direct Post)** [OFICIAL]:
  - cliente não auditado só posta como `SELF_ONLY` (privado), para até 5 usuários em 24 h;
  - cliente auditado tem teto de **cerca de 15 posts por dia por criador**;
  - as diretrizes exigem **prévia do vídeo, legenda editável e consentimento explícito do usuário a cada post**;
  - o objetivo é que "criadores autênticos publiquem conteúdo original", e "copiar conteúdo arbitrário de outras plataformas não é aceitável". Um app de cortes de terceiros **dificilmente passa na auditoria**.
- **Modo semiautomático para o TikTok** (recomendado) [INFERÊNCIA]: o CORTEX abre o TikTok Studio, anexa o arquivo, preenche a legenda e **para**. O dono revisa e clica em **Publicar** ou **Agendar**. Uma variação é **1 sessão supervisionada por dia** em que o dono agenda os posts do dia pelo **agendador nativo** do TikTok Studio no desktop (até 10 dias de antecedência, para contas pessoais ou de criador).

  Com isso, a automação faz só a parte pesada (escolher, editar, preencher), e o ato de publicar fica com um humano. Isso também resolve o horário certo, porque é a plataforma que solta o post.

### 5.3 Gatilhos típicos (o que as plataformas tratam como spam) [OFICIAL + MERCADO]

- **Rajadas**: vários posts em minutos. O intervalo atual de 90 a 240 s é exatamente isso.
- **Volume alto em conta nova** (15 a 20 posts por dia é citado como alerta vermelho), e muitos vídeos parecidos com mudanças mínimas (política de spam do YouTube).
- **Texto repetido**: legendas idênticas, a mesma lista de hashtags em todo post, hashtags sem relação com o vídeo. O YouTube ignora **todas** as hashtags quando passam de 60, e hashtag enganosa pode levar à remoção do vídeo.
- **Publicação em intervalos exatos e regulares** ou 24 h por dia.
- **Muitas contas** no mesmo IP ou dispositivo; troca de IP, VPN ou datacenter; navegador headless.
- **Ações de engajamento automatizadas** (curtir, seguir, comentar em massa) e apagar e repostar em série.
- **Metadados enganosos**: título que promete algo que o vídeo não entrega, como "jogo completo" num trecho. Isso está no exemplo da política de spam do YouTube.

### 5.4 Práticas seguras (fazer)

- **Volume de criador dedicado, não de robô**: a rampa da seção 1 e o teto de 5 por dia.
- **Horários definidos pela audiência** (janelas da seção 2), que naturalmente variam de dia para dia. Uma escala rígida a cada X minutos não é o objetivo.
- **Uma conta por plataforma**, do dono, sempre no **mesmo perfil de Chrome** (`paths.BROWSER_PROFILE`), na **mesma máquina e na conexão residencial do dono**. Sem VPN, sem proxy, sem revezar máquinas.
- **`headless: false`** (como está) e **nenhuma** extensão ou plugin de "stealth".
- **Nada de engajamento automatizado.** O CORTEX **não** curte, não segue, não comenta e não manda DM. Responder comentários é tarefa do dono (seção 6).
- **Texto único em cada post**: título e legenda gerados por corte, com similaridade máxima de 0,6 em relação às últimas 20 legendas.
- **Leitura de métricas com parcimônia**: no máximo 2 a 3 sessões por dia, lendo a **lista** de conteúdos em vez de abrir post por post.
- **Parar diante de qualquer verificação** (já previsto no `ARQUITETURA.md`) e nunca tentar de novo sozinho.

### 5.5 Não fazer (fora de escopo, por política)

- Burlar ou resolver captcha; usar falsificação de impressão digital do navegador, *user-agents* falsos ou rotação de IP; simular movimento de mouse para "parecer humano".
- Criar contas em série, comprar contas "aquecidas" ou operar várias contas de cortes.
- Comprar views ou seguidores, ou participar de grupos de engajamento. Isso viola as regras de engajamento falso e desqualifica do Programa de Recompensas.
- Espelhar, acelerar ou mudar o tom para escapar do Content ID.

---

## 6. Checklist de setup de um canal novo de cortes (Brasil)

**Conta e segurança**
- [ ] Titular **maior de 18 anos**, residente no Brasil, com documento e dados bancários no próprio nome. É exigência do Programa de Recompensas e do AdSense.
- [ ] Google: **verificação em duas etapas** (exigência do YPP); verificar o telefone no YouTube (recursos intermediários); solicitar **recursos avançados** (exigência do YPP).
- [ ] TikTok: conta **pessoal**, não Business. Na Business não há Programa de Recompensas.
- [ ] Uma conta por plataforma, criada e logada **pelo dono, à mão**, no perfil de Chrome do CORTEX.

**Identidade**
- [ ] **Nome**: marca própria + nicho, por exemplo "Resenha Cortada" ou "Papo em 60s". **Nunca** usar o nome do criador-fonte como se fosse o canal oficial ("FlowCortes Oficial"), porque isso é risco de falsidade ideológica e de marca registrada. O mesmo @ nas duas plataformas.
- [ ] **Foto**: logo próprio, legível em 48 px, igual nas duas plataformas. No YouTube, banner com a promessa e a frequência ("Os melhores momentos de podcasts, todo dia às 21h").
- [ ] **Bio** (até 80 caracteres no TikTok), com o que o canal entrega, a frequência e a transparência. Exemplo: "Cortes comentados de podcasts • canal independente, não oficial • créditos em cada vídeo". No YouTube, acrescentar o e-mail para detentores de direitos.
- [ ] **Sem link na bio** nas primeiras 2 semanas. [MERCADO]
- [ ] Padrões de upload no YouTube: idioma pt-BR, local Brasil, categoria "Entretenimento", **"Não, não é conteúdo para crianças"**, "conteúdo alterado/sintético: não" (enquanto não houver IA realista), e um modelo de descrição com espaço para crédito.

**Nicho**
- [ ] **Escolher 1 tema principal + 1 adjacente nos primeiros 30 dias**, por exemplo "podcasts de entrevista e humor" + "celebridades". Os 9 `temas` atuais são largos demais. O algoritmo precisa de um sinal de público coerente, e o revisor do YPP olha o tema principal do canal. [INFERÊNCIA]
- [ ] Abrir novos temas só depois da fase 3, e um de cada vez, medindo pelo loop da seção 7.

**Os 10 primeiros vídeos** (para o pior caso, em que a conta passa a fase 1 inteira postando 1 por dia)
1. Todos do **mesmo nicho**, com nota ≥ **75**, e fontes da lista branca ou de baixo risco.
2. **1 por dia, na janela A+** (20:30 a 22:30 em dia útil).
3. **Variar o gancho** em ordem: pergunta, frase polêmica, número ou lista, reação, "ninguém percebeu".
4. **Testar duração**:
   - YouTube: 5 cortes de 25 a 40 s e 5 de 40 a 58 s.
   - TikTok: 6 de 25 a 45 s e 4 de 62 a 90 s.
5. Incluir **1 série de 2 a 3 partes** entre os vídeos 4 e 8, para gerar visitas ao perfil e seguidores.
6. **Nada polêmico demais no começo**: sem política partidária, tragédia ou acusação criminal. São temas que costumam ficar fora do Para Você ou ser pouco amigáveis a anunciantes, e uma conta nova não tem histórico que a proteja.
7. **Fixar os 3 melhores** no perfil do TikTok a partir do 6º vídeo. No YouTube, criar playlists por série ou tema.
8. **O dono responde aos primeiros comentários à mão** em cada vídeo, nos primeiros 60 min.
9. **Não apagar** os vídeos fracos. Eles servem de dado para o loop.
10. Depois do 10º vídeo, conferir o estado (seção 1.5) e avançar de fase só se os critérios forem atendidos.

---

## 7. Loop de métricas (o que ler e como aprender)

### 7.1 O que ler

**Preferência**: APIs oficiais (YouTube Analytics API; Display API do TikTok para contagens básicas). **Alternativa**: leitura pelo navegador logado, com no máximo 3 sessões por dia (seção 5.4).

| Métrica | TikTok Studio | YouTube Studio | Para que serve |
|---|---|---|---|
| Views | ✓ | ✓ (desde 03/2025 conta replays) | volume |
| **Views engajadas** | n/a | ✓ (Analytics, modo avançado) | comparar Shorts; é a métrica do YPP |
| **Visualizado vs. deslizado** | n/a | ✓ (Conteúdo → Shorts) | **força do gancho** (abaixo de 55% = gancho ruim) [MERCADO: ≥ 70% é típico, ≥ 80% é forte] |
| Tempo médio assistido / % médio assistido | ✓ | ✓ | retenção |
| % que assistiu o vídeo inteiro, curva de retenção, ponto de abandono | ✓ | ✓ (curva) | onde cortar o início e o fim |
| Curtidas, comentários, **compartilhamentos**, salvamentos | ✓ | ✓ (sem salvamentos) | ressonância (shares e saves valem mais) |
| **Novos seguidores ou inscritos por vídeo** | ✓ | ✓ | conversão |
| **Origem do tráfego** | Para Você / Seguindo / Perfil / Busca / Som | Feed de Shorts / Pesquisa / Páginas do canal / Externo | **distribuição restrita vs. conteúdo fraco** (seção 1.5) |
| Termos de busca que trouxeram views | ✓ | ✓ | títulos e temas com demanda |
| Público: país, cidade, idade, horários ativos | ✓ | ✓ | conferir que o público é brasileiro; recalibrar as janelas |
| **Avisos e restrições** | aviso de "não elegível para o Para Você" no post; página de **Status da conta / Verificação da conta** | coluna **Restrições** (direitos autorais, restrição de idade, adequação a anúncios); aba **Direitos autorais**; avisos do painel | gatilhos de CAUTELA, PAUSA e PARAR |
| Ideias de tema | **Creator Search Insights** (filtro "lacuna de conteúdo") | aba de Pesquisa/Inspiração do Studio, se estiver disponível na conta | entrada para `rank_trends` |
| Monetização (quando elegível) | views qualificadas e RPM do Programa de Recompensas | RPM e receita de Shorts | otimizar duração e temas pela receita |

### 7.2 Quando ler

- Snapshots por post em **T+2 h** (só TikTok, como alerta precoce), **T+24 h** (alarmes), **T+72 h** (aprendizado) e **T+7 d** (cauda longa, principalmente no YouTube).
- **2 sessões por dia** (sugestão: 11:00 e 23:45), cada uma lendo a lista de posts dos últimos 7 dias.
- **Status da conta, restrições e direitos autorais: 1 vez por dia**, além de logo após cada sessão de publicação.

### 7.3 Pontuação de desempenho (por post, em T+72 h)

Normalizar cada métrica pelo **z-score contra a média móvel dos últimos 30 dias da própria conta**, por plataforma:

```
score = 0,30·gancho + 0,25·retenção + 0,20·shares_por_mil + 0,15·seguidores_por_mil + 0,10·comentários_por_mil
gancho   = visualizado_vs_deslizado (YT) | % que passou dos 3 s ou % que assistiu tudo (TT)
retenção = % médio assistido
```

Sucesso = score acima da mediana dos últimos 30 dias. Esse rótulo binário alimenta o *bandit*.

### 7.4 Como realimentar a seleção

1. **Guardar as características de cada corte**: tema, canal-fonte, pessoa que fala, tipo de gancho, faixa de duração, layout, template, estilo de título, janela e dia, número da parte, proporção de música, nível de transformação (quantos dos 7 itens) e saturação do momento.
2. ***Bandit* (Thompson sampling, Beta(1,1))** por **tema**, **canal-fonte**, **faixa de duração**, **janela** e **template**:
   - 75% exploração do que funciona e 25% de teste;
   - meia-vida de **14 dias**, porque assuntos do momento envelhecem;
   - pelo menos **20 posts por braço** antes de cortar um braço.
3. **Memória do cérebro**: toda semana, gerar um resumo com os **5 melhores e os 5 piores** dos últimos 14 dias, com as características de cada um, e injetar no prompt de `pick_clips` e `rank_trends` ("ganchos de pergunta rendem 1,8× mais shares", "cortes acima de 50 s no YT têm deslize de 62%: evite").
4. **Ajuste de nota**: `pontuacao_minima` dinâmica, publicando só cortes cuja nota prevista esteja no **top 40%** do que foi produzido. Calibrar a nota do cérebro contra o score real com uma regressão simples, depois de 50 posts.
5. **Lista negra automática**: uma fonte com claim ou com "inelegível para o Para Você" fica bloqueada por 30 dias na 1ª vez e de forma permanente na 2ª. Um tema com 3 posts seguidos abaixo de p25 sai de rodízio por 7 dias.
6. **Reponderar as janelas** a cada 3 semanas, com os dados de público ativo e o score por janela.

**Tabelas sugeridas no SQLite** (descrição para a equipe):
- `post_metrics` (post, plataforma, T em horas, métricas acima, flags de restrição ou claim);
- `account_health` (plataforma, data, estado, motivo);
- `clip_features` (características do item 1);
- `source_permissions` (canal, status, URL da prova, data de verificação, data de expiração);
- `source_blocklist` (canal, motivo, data de expiração).

---

## 8. O que mudar no `config.yaml` atual

| Chave atual | Valor atual | Recomendado | Por quê |
|---|---|---|---|
| `modo_publicacao: revisar` + "envia tudo de uma vez" | rajada depois da aprovação | aprovação → **fila agendada** pelas janelas | evitar rajada (seção 1.3) |
| `publicacao.max_posts_por_dia` | YT 10 / TT 8 | rampa por idade da conta (0 → 1 → 2 → 3 → 4), teto de 5 | seção 1.2 |
| `publicacao.intervalo_entre_posts_s` | `[90, 240]` (1,5 a 4 min) | mínimo **150 min (TT) / 120 min (YT)**, 1 post por janela | seção 1.3 |
| `publicacao.hashtags_fixas` | `#cortes`, `#viral` | no máximo 1 fixa de nicho (ex.: `#cortesdepodcast`) + 2 a 4 do assunto; **sem** `#viral` e `#fyp` | seção 5.3 |
| `publicacao.creditar_fonte` | só na descrição | descrição **e tela** | seção 4.4 |
| `execucao.horarios` | 09:00, 13:00, 18:00, 22:00 | **09:30, 15:30, 18:30** | produzir 2 a 3 h antes das janelas |
| `execucao.max_cortes_por_execucao` | 15 | **posts permitidos no dia × 1,5**, dividido pelas rodadas (≈ 2 a 4) | não produzir 60 cortes por dia para postar 3 |
| `corte.duracao_min_s/max_s` | 25 / 90 (as duas plataformas) | YT 20 a 58 (rígido); TT 20 a 120 (alvos de 25 a 45 e 62 a 95) | seção 3.1 |
| `corte.duracao_parte_s / max_partes` | 65 / 5 | YT 55 / TT 75; **no máximo 3 partes** | queda de retenção nas partes finais [INFERÊNCIA] |
| `corte.pontuacao_minima` | 55 | 65 (fase 1 e 2: 75) e depois dinâmica (top 40%) | seção 7.4 |
| `edicao.layout` | `auto` (inclui `split` com gameplay) | `full`/`blur` como padrão; `split` em 10% ou menos | seção 3.5 |
| `busca.temas` | 9 temas | 1 principal + 1 adjacente nos primeiros 30 dias | seção 6 |
| `busca.canais_bloqueados` | `[]` | lista sugerida na seção 9 | seção 4 |
| `publicacao.headless` | false | **manter false**; sem stealth | seção 5.4 |

---

## 9. Valores recomendados (YAML para máquina)

```yaml
# CORTEX: valores recomendados pela pesquisa algoritmo_e_riscos.md (23/11/2026)
# Unidades: minutos (_min), segundos (_s), horas (_h). Fuso: America/Sao_Paulo (BRT, UTC-3, sem horario de verao).
cortex_recomendado:
  fuso: America/Sao_Paulo

  publicacao:
    modo_envio: fila_agendada          # aprovacao nunca dispara rajada
    uma_plataforma_por_vez: true
    defasagem_entre_plataformas_min: [20, 60]   # mesmo corte: TikTok primeiro, YouTube depois
    silencio_publicacao: {inicio: "01:00", fim: "06:30"}
    max_posts_por_janela: 1
    publicar_nos_primeiros_min_da_janela: 30
    frac_posts_fora_das_janelas_teste: 0.15
    posts_por_dia_por_idade_conta:      # idade em dias desde a criacao da conta
      tiktok:
        - {dias_de: 0,  dias_ate: 3,    posts_dia: 0}
        - {dias_de: 4,  dias_ate: 10,   posts_dia: 1}
        - {dias_de: 11, dias_ate: 21,   posts_dia: 2}
        - {dias_de: 22, dias_ate: 42,   posts_dia: 3}
        - {dias_de: 43, dias_ate: null, posts_dia: 4}
      youtube:
        - {dias_de: 0,  dias_ate: 2,    posts_dia: 0}
        - {dias_de: 3,  dias_ate: 10,   posts_dia: 1}
        - {dias_de: 11, dias_ate: 21,   posts_dia: 2}
        - {dias_de: 22, dias_ate: 42,   posts_dia: 3}
        - {dias_de: 43, dias_ate: null, posts_dia: 4}
    teto_absoluto_posts_dia: {tiktok: 5, youtube: 5}
    teto_posts_semana_por_fase: {fase1: 7, fase2: 14, fase3: 21, fase4: 28}
    nota_minima_para_post_4_e_5: 75
    intervalo_min_entre_posts_min: {tiktok: 150, youtube: 120}
    intervalo_max_entre_posts_min: {tiktok: 480, youtube: 480}
    intervalo_min_fase2_min: 240
    criterios_avanco_fase:
      fase1_para_2: {posts_publicados_min: 5, views_24h_min: 50, posts_acima_de_views_min_de_5: 3, avisos: 0}
      fase2_para_3: {mediana_views_24h_min: {tiktok: 200, youtube: 150}, participacao_para_voce_min_tiktok: 0.5}
      fase3_para_4: {dias_estado_normal: 7, claims_14d: 0}
      fase4_continua: {mediana_7d_vs_30d_min: 1.0}

  janelas_prime_brt:                    # prioridade: A+ > A > B > C (C so para o 4o post ou mais)
    seg_qui:
      - {inicio: "20:30", fim: "22:30", prioridade: A+}
      - {inicio: "18:00", fim: "19:30", prioridade: A}
      - {inicio: "12:00", fim: "13:30", prioridade: B}
      - {inicio: "07:00", fim: "08:30", prioridade: C}
    sexta:
      - {inicio: "18:00", fim: "20:00", prioridade: A+}
      - {inicio: "21:00", fim: "23:00", prioridade: A}
      - {inicio: "12:00", fim: "13:30", prioridade: B}
      - {inicio: "07:00", fim: "08:30", prioridade: C}
    sabado:
      - {inicio: "20:00", fim: "23:00", prioridade: A+}
      - {inicio: "16:00", fim: "18:00", prioridade: A}
      - {inicio: "10:00", fim: "12:00", prioridade: B}
      - {inicio: "13:30", fim: "15:00", prioridade: C}
    domingo:
      - {inicio: "19:00", fim: "22:00", prioridade: A+}
      - {inicio: "09:00", fim: "11:00", prioridade: A}
      - {inicio: "13:00", fim: "14:30", prioridade: B}
      - {inicio: "16:00", fim: "17:30", prioridade: C}
    tiktok_prefere: [A+, A]
    youtube_prefere: [A, B]
    reponderar_a_cada_dias: 21

  producao:
    horarios_rodadas: ["09:30", "15:30", "18:30"]
    cortes_por_dia_fator: 1.5           # produzir = posts_permitidos_hoje * 1.5
    validade_corte_assunto_do_momento_h: 36

  corte:
    youtube_shorts: {min_s: 20, alvo_s: [30, 50], max_s: 58}   # >60s + qualquer claim = bloqueio global
    tiktok:
      curto: {min_s: 20, alvo_s: [25, 45], max_s: 59}
      longo_recompensas: {min_s: 62, alvo_s: [65, 95], max_s: 120, max_excepcional_s: 150}
      frac_longo_antes_5k_seguidores: 0.4
      frac_longo_apos_5k_seguidores: 0.6
    series: {parte_youtube_s: 55, parte_tiktok_s: 75, max_partes: 3, recap_inicio_s: 3}
    renderizar_nucleo_para_youtube: true   # ClipPlan.core_start/core_end <= 55s
    pontuacao_minima: {fase1_2: 75, fase3_4: 65, dinamica_top_frac: 0.4}
    proibir_loop_ou_enchimento: true

  transformacao:
    obrigatoria: true
    itens_minimos: 4                     # de 7; cartao_contexto e comentarios_tela sempre
    cartao_contexto_s: [1.5, 3.0]
    comentarios_tela_min: 2
    narracao_tts: {usar: true, voz: generica_fixa_do_canal, clonar_voz_real: false}
    pergunta_final_s: [2, 4]
    zoom_dinamico: true
    templates_rotativos_min: 3
    layout_padrao: [full, blur]
    layout_split_gameplay_max_frac: 0.1
    proibido: [espelhar, alterar_velocidade, alterar_tom, bordas_anti_content_id, marca_dagua_de_terceiros, musica_de_fundo]
    rotulo_ia: {youtube: "so se conteudo sintetico realista", tiktok: "so se conteudo sintetico realista"}

  texto:
    hashtags_total: [3, 5]
    hashtags_fixas_max: 1
    hashtags_proibidas: ["#viral", "#fyp", "#foryou", "#foryoupage", "#paravoce", "#xyzbca", "#viralvideo"]
    similaridade_max_com_ultimas_20_legendas: 0.6
    titulo_youtube_max_chars: 70
    creditar_fonte: {tela: true, tela_s: 3, descricao: true}
    email_detentores_na_bio: true

  saude_conta:
    leituras_metricas_por_dia: 2          # sugestao 11:00 e 23:45
    snapshots_h: [2, 24, 72, 168]
    checar_status_conta_por_dia: 1
    limiares:
      quase_zero_views_24h: 10
      posts_seguidos_quase_zero_para_pausa: 3
      views_24h_baixo: {tiktok: 200, youtube: 150}   # vale a partir do dia 15
      posts_seguidos_baixo_para_cautela: 5
      mediana5_vs_mediana30_min: 0.25
      participacao_para_voce_min_tiktok: 0.40
      participacao_feed_shorts_min_youtube: 0.40
      visualizado_vs_deslizado_ruim_youtube: 0.55
      claims_7d_para_cautela: 2
      inelegivel_fyf_7d_para_pausa: 2
    acoes:
      CAUTELA: {duracao_h: 72, fator_posts_dia: 0.5, posts_dia_min: 1, fator_intervalo: 1.5, nota_minima: 75}
      PAUSA: {duracao_h: 72, voltar_para_fase: 1, dias_na_fase1: 5, notificar_dono: true}
      PARAR:
        exige_comando_manual: true
        gatilhos: [strike_direitos_autorais, strike_diretrizes, aviso_status_conta, conta_inelegivel_para_voce, captcha, verificacao_identidade, limite_diario_envio, postando_rapido_demais, sessao_expirada]
      limite_diario_envio: {pausa_h: 24, reduzir_teto_permanente_em: 1}
      erro_upload: {tentativas_extras: 1, esperar_min: 30}
    nunca_apagar_e_repostar: true

  aprendizado:
    janela_avaliacao_h: 72
    pesos_score: {gancho: 0.30, retencao: 0.25, shares_por_mil: 0.20, seguidores_por_mil: 0.15, comentarios_por_mil: 0.10}
    bandit: {metodo: thompson_beta, prior: [1, 1], bracos: [tema, canal_fonte, faixa_duracao, janela, template], explorar_frac: 0.25, meia_vida_dias: 14, min_amostras_por_braco: 20}
    memoria_cerebro: {frequencia_dias: 7, top_n: 5, bottom_n: 5, janela_dias: 14}
    tema_fora_do_rodizio: {posts_seguidos_abaixo_p25: 3, dias: 7}

  nicho_inicial:
    temas_max_primeiros_30_dias: 2
    novo_tema_somente_na_fase: 3

  fontes:
    permissoes:
      exigir_prova_para_lista_branca: true
      revalidar_a_cada_dias: 90
    preferir:
      - autorizacao_explicita_ou_campanha_de_cortes
      - licenca_creative_commons          # yt-dlp: license contem "Creative Commons"
      - podcast_ou_entrevista_falada_sem_musica
    categorias_risco_pular:
      - id: esporte_transmissao
        motivo: "Content ID das detentoras; Lei 14.597/2023 art. 163 so cobre uso jornalistico (3% do tempo, no maximo 30s)"
        sinais: {ytdlp_categories: [Sports], titulo_regex: ["(?i)\\b\\w+\\s+x\\s+\\w+\\b", "(?i)gols?\\b", "(?i)melhores momentos", "(?i)highlights", "(?i)brasileir[aã]o|libertadores|copa do brasil|champions"]}
      - id: tv_aberta_paga
        motivo: "telejornal, novela, reality, auditorio: Content ID agressivo"
        sinais: {titulo_regex: ["(?i)\\bbbb\\b|a fazenda|novela|cap[ií]tulo|jornal nacional|fant[aá]stico|domingo legal"]}
      - id: filme_serie_anime_trailer
        sinais: {ytdlp_categories: ["Film & Animation"], titulo_regex: ["(?i)trailer|filme completo|epis[oó]dio|temporada"]}
      - id: musica
        motivo: "causa no 1 de claim automatico; desqualifica do Programa de Recompensas"
        sinais: {ytdlp_categories: [Music], ytdlp_campos_presentes: [track, artist, album], titulo_regex: ["(?i)clipe oficial|official (music )?video|lyric|ao vivo no|\\bdvd\\b|\\bshow\\b"]}
        proporcao_musica_max: 0.10
        youtube_musica_permitida_acima_de_s: 50   # acima disso, nenhuma musica
      - id: react_de_terceiros
        motivo: "conteudo de baixo e de terceiros: risco duplo"
        sinais: {titulo_regex: ["(?i)react|reagindo|assistindo|watch ?party"], categoria_twitch_kick: [Music, Sports, "Watch Party"]}
      - id: apostas_bets
        motivo: "MP 1.394/2026 art. 16: publicidade de apostas proibida em meio digital"
        sinais: {transcricao_regex: ["(?i)\\bbet\\b|aposta|\\bodds?\\b|cupom|c[oó]digo promocional|patrocinad"]}
      - id: publicidade_patrocinio
        motivo: "trecho publicitario de terceiros; conteudo patrocinado nao gera recompensa"
        sinais: {transcricao_regex: ["(?i)\\bpubli\\b|oferecimento|parceiro do (programa|podcast)|use o c[oó]digo"]}
      - id: menores_protagonistas
        motivo: "regras de protecao de menores; monetizacao exige autorizacao judicial (Decreto 12.880, art. 34, citado pelo YouTube)"
      - id: sensivel
        motivo: "tragedia, violencia, acidente, crime com vitima, saude sem contexto: fica fora do Para Voce ou e pouco amigavel a anunciantes"
      - id: desinformacao_politica
        motivo: "fala fora de contexto, voz ou rosto sintetico de politico"
      - id: cortes_revogados_ou_proibidos
        exemplo: "PodPeople revogou a autorizacao generica a partir de 2026-01-01"
      - id: momento_saturado
        motivo: "YouTube: conteudo enviado muitas vezes por outros criadores = conteudo reutilizado"
        regra: {busca: "ytsearch20 com a frase de 8 a 12 palavras", shorts_canais_distintos_7d_max: 4}
    canais_bloqueados_sugeridos:   # verificar e ajustar os @ reais antes de usar
      tv: [TV Globo, g1, ge, GloboNews, Globoplay, SporTV, Premiere, Record, R7, Record News, SBT, SBT News, Band, BandNews, Band Sports, RedeTV, CNN Brasil, Jovem Pan News, TV Cultura]
      esporte: [CazeTV, ESPN Brasil, TNT Sports Brasil, Prime Video Brasil, DAZN, CONMEBOL, CBF TV, FIFA, NBA Brasil, UFC Brasil]
      musica: [Vevo, Sony Music Brasil, Universal Music Brasil, Warner Music Brasil, Som Livre, GR6 Explode, KondZilla]
    claims:
      primeiro_claim_bloqueia_fonte_dias: 30
      segundo_claim_bloqueia_fonte: permanente
      contestar_somente_com_autorizacao: true

  automacao:
    navegador_headless: false
    plugins_stealth: false
    resolver_captcha: false
    contas_por_plataforma: 1
    vpn_ou_proxy: false
    engajamento_automatico: false        # nada de curtir, seguir, comentar ou DM
    tiktok_modo_recomendado: semiautomatico_dono_clica_publicar_ou_agendador_nativo
    youtube_modo_recomendado: data_api_v3_com_auditoria
    metricas_modo_recomendado: {youtube: youtube_analytics_api, tiktok: leitura_painel_max_2x_dia}
```

---

## 10. Fontes

**YouTube: políticas e ajuda (oficial)**
- Visão geral e qualificação do YPP (pt-BR): https://support.google.com/youtube/answer/72851?hl=pt-BR
- YPP expandido e países: https://support.google.com/youtube/answer/13429240
- Mudanças do YPP a partir de 01/02/2027 (blog do YouTube, 10/08/2026): https://blog.youtube/news-and-events/youtube-partner-program-updates-2027-new-opportunities-earn/
- Políticas de monetização de canais (conteúdo reutilizado e inautêntico): https://support.google.com/youtube/answer/1311392
- Esclarecimento de 07/2025 sobre clipes, compilações e reacts: https://www.searchenginejournal.com/youtube-clarifies-monetization-update-targeting-spam-not-reaction-channels/550123/
- Políticas de monetização de Shorts (Shorts acima de 1 min com claim): https://support.google.com/youtube/answer/12504220
- Shorts de 3 minutos: https://support.google.com/youtube/answer/15424877
- Reivindicações do Content ID: https://support.google.com/youtube/answer/6013276
- Avisos (strikes) de direitos autorais (pt-BR): https://support.google.com/youtube/answer/2814000?hl=pt-BR
- Política de spam, práticas enganosas e golpes (pt-BR): https://support.google.com/youtube/answer/2801973?hl=pt-BR
- Regras de hashtags (pt-BR): https://support.google.com/youtube/answer/6390658?hl=pt-BR
- Termos de Serviço (pt-BR): https://www.youtube.com/static?template=terms&hl=pt-BR&gl=BR
- Desempenho de conteúdo / visualizado vs. deslizado: https://support.google.com/youtube/answer/12220281
- Divulgação de conteúdo alterado ou sintético: https://support.google.com/youtube/answer/14328491 e https://blog.youtube/news-and-events/disclosing-ai-generated-content
- Erros de upload e limite diário: https://support.google.com/youtube/answer/10383400
- Data API `videos.insert` (projetos não verificados → privado): https://developers.google.com/youtube/v3/docs/videos/insert
- Mudança na contagem de views de Shorts (31/03/2025): https://techcrunch.com/2025/03/26/youtube-is-changing-how-youtube-shorts-views-are-counted

**TikTok (oficial)**
- Termos do Programa de Recompensas (EUA; requisitos de 10 mil, 100 mil e 1 min): https://www.tiktok.com/legal/page/global/creator-rewards-program-us/en
- Lançamento do Programa de Recompensas (03/2024): https://newsroom.tiktok.com/introducing-the-new-creator-rewards-program
- Programa de Recompensas no suporte (pt-BR): https://support.tiktok.com/pt_BR/business-and-creator/creator-rewards-program/creator-rewards-program
- Diretrizes: Integridade e autenticidade (pt-BR): https://www.tiktok.com/community-guidelines/pt-BR/integrity-authenticity
- Padrões de elegibilidade para o Para Você (pt-BR): https://www.tiktok.com/community-guidelines/pt-BR/fyf-standards
- Atualização das diretrizes e Verificação da conta (2024): https://newsroom.tiktok.com/cgupdate
- Termos de Serviço (pt-BR): https://www.tiktok.com/legal/page/row/terms-of-service/pt-BR
- Política de direitos autorais (pt-BR): https://www.tiktok.com/legal/page/global/copyright-policy/pt-BR
- Conteúdo gerado por IA: https://support.tiktok.com/en/using-tiktok/creating-videos/ai-generated-content
- Content Posting API (Direct Post): https://developers.tiktok.com/doc/content-posting-api-reference-direct-post
- Diretrizes de compartilhamento de conteúdo (≈15 posts por dia, consentimento a cada post): https://developers.tiktok.com/doc/content-sharing-guidelines
- Creator Search Insights: https://newsroom.tiktok.com/creator-search-insights?lang=en

**Imprensa e análises**
- Diretrizes do TikTok em 2025 (TechCrunch): https://techcrunch.com/2025/08/15/tiktoks-new-guidelines-add-subtle-changes-for-live-creators-ai-content-and-more/
- "Content check" do Para Você (Engadget): https://www.engadget.com/social-media/tiktok-content-check-tells-creators-if-their-videos-will-be-blocked-from-for-you-pages-110015168.html
- Programa Criativo no Brasil (2023): https://olhardigital.com.br/2023/09/23/dicas-e-tutoriais/o-que-e-o-programa-criativo-do-tiktok-e-como-ganhar-dinheiro-com-ele/
- Direitos do Brasileirão 2026 (Lance): https://www.lance.com.br/lance-negocios/onde-assistir-ao-brasileirao-2026-entenda-divisao-dos-direitos-de-transmissao.html

**Estudos de mercado**
- Buffer, melhores horários no TikTok 2026 (7,1 milhões de posts): https://buffer.com/pt/resources/melhor-horario-para-postar-no-tiktok
- Buffer, frequência no TikTok (11,4 milhões de posts): https://buffer.com/resources/how-often-should-you-post-on-tiktok/
- Metricool, horários TikTok 2026: https://metricool.com/pt/melhor-horario-postar-tiktok/
- Metricool, estudo YouTube 2026: https://metricool.com/youtube-trends/
- Sprout Social, melhores horários (pt-BR): https://sproutsocial.com/insights/best-times-to-post-on-social-media-pt_br/
- Opinion Box via Stone (uso do TikTok por horário no Brasil): https://conteudo.stone.com.br/melhores-horarios-para-postar-no-tiktok/
- vidIQ, primeiros 10 vídeos (07/2026): https://vidiq.com/research/youtube-first-10-videos-study/
- Virlo, duração no TikTok (out/nov 2026): https://virlo.ai/data/how-long-should-a-tiktok-be
- Socialinsider, duração no TikTok: https://www.socialinsider.io/blog/how-long-are-tiktok-videos/
- Adobe Express, duração de Shorts (pesquisa com criadores): https://www.adobe.com/express/learn/blog/youtube-shorts-length-study

**Heurísticas de clipadores (sem confirmação das plataformas)**
- cut.pro, aquecimento de conta 2026: https://cut.pro/en/blog/warm-up-tiktok-instagram-account-2026
- Ssemble, aquecimento de conta 2026: https://www.ssemble.com/blog/account-warmup-guide-2026
- cut.pro, mercado de clipping pago 2026: https://cut.pro/pt-BR/blog/streamers-pagam-clipadores-mercado-2026
- FindClout, cortes repostados e o Programa de Recompensas: https://findclout.com/blog/tiktok-creator-rewards-reposted-clips

**Legislação brasileira**
- Lei 9.610/98 (direitos autorais, art. 46): https://www.planalto.gov.br/ccivil_03/leis/l9610.htm
- Lei 14.597/2023 (Lei Geral do Esporte, art. 163): https://www.planalto.gov.br/ccivil_03/_Ato2023-2026/2023/Lei/L14597.htm
- MP 1.394/2026 (proibição das bets e da publicidade de apostas): https://planalto.gov.br/ccivil_03/_ato2023-2026/2026/mpv/mpv1394.htm
- Revogação de autorização de cortes (PodPeople): https://draanabeatriz.com.br/cortes

---

*Limitações desta pesquisa:*
- Os números de aquecimento e de "shadowban" são heurísticas de mercado, porque nenhuma plataforma os publica.
- Os estudos de horário e de duração são globais ou de amostras de clientes das ferramentas, e não exclusivamente brasileiros.
- A página oficial em PT-BR do Programa de Recompensas não pôde ser lida diretamente (redirecionamento); os requisitos vêm dos termos oficiais dos EUA e da imprensa brasileira.
- A MP 1.394/2026 ainda depende de conversão pelo Congresso.
- Revise este documento a cada 3 meses.
