# Texto dos posts: hashtags, CTA e legenda (YouTube Shorts e TikTok)

Arquivos: `fabrica/hashtags.py` (escolha de hashtags, CTA, em alta), `fabrica/publish/captions.py`
(`build_post_text`), dados curados em `fabrica/dados/hashtags_ptbr.json`.
Teste: `.venv\Scripts\python.exe tests\texto_post_unit.py` (8 cortes de exemplo nas duas redes, sem navegador).
Data de referência: 23/11/2026. Revise o JSON a cada 60 dias (`_meta.revisar_ate`).

---

## 1. O que a pesquisa diz (2025 e 2026)

### 1.1 Limites e regras por rede

| Item | YouTube Shorts | TikTok |
|---|---|---|
| Título | 100 caracteres (limite rígido). No feed aparecem cerca de 40 a 50; média dos Shorts em alta: 51 caracteres | Não há título: a primeira linha da legenda faz esse papel (cerca de 80 caracteres antes do "mais") |
| Descrição / legenda | 5.000 caracteres | 2.200 pela API e agendadores; 4.000 no app. Usamos 2.200 |
| Hashtags | Acima de **60** o YouTube ignora todas (ajuda oficial atual; a regra antiga de 15 ainda circula em blogs). Usamos no máximo 15 | Desde ago/2025 o TikTok passou a avisar "máximo de 5 hashtags" para parte dos usuários. Usamos no máximo 5 |
| Acima do título | Até **3** hashtags da descrição aparecem acima do título (o YouTube escolhe as "mais engajadoras") | Não se aplica |
| Proibido | Hashtag sem relação com o vídeo, enganosa, de assédio, ódio, sexual ou vulgar; descrição só com tags repetidas | Conteúdo que tenta "inflar curtidas ou seguidores" e conteúdo reaproveitado sem nada novo ficam **fora do Para Você** |
| #Shorts | Opcional: o YouTube detecta vertical de até 3 min sozinho. No benchmark do projeto, #shorts rendeu 0,91x (sem ganho) | Não se aplica |

### 1.2 Hashtags: quanto ajudam e quais usar

- Efeito pequeno, mas positivo. Estudo da SocialCrawl (ago/2026, 1.569 vídeos, 40 contas): com hashtag +3,7% de views
  sobre a mediana da própria conta; 4 a 6 hashtags +3,0%. Metricool 2026 (2,3 milhões de posts): +5% de views e +9%
  de interações com pelo menos uma hashtag, e o tráfego vindo de hashtag cresceu 114% no ano.
- **#fyp, #foryou, #viral**: o suporte do TikTok diz que não dão "nenhum impulso especial". Na SocialCrawl, #fyp aparece
  com +16,7%, mas é correlação (quem já ia bem usa). No benchmark do projeto (#viral 1,31x, #fyp 1,12x) o efeito some ao
  olhar só canais que já iam bem. Ficam **proibidas**: são a assinatura de conta de bot e não trazem público específico.
- **Entidade e tema batem genérica.** Benchmark de canais BR (23/11/2026): no YouTube, #sbt 6,41x, #silviosantos 6,13x,
  #danilogentili 5,85x, #historia 2,41x, #humor 1,53x; no TikTok, #futebolbrasileiro 1,58x, #noticias 1,26x,
  #mbl 1,27x, enquanto #humor (0,93x) e #engraçado (0,70x) ficam abaixo. No TikTok, 4 hashtags = 1,30x.
- **Mistura em camadas** (guias BR de 2026): ampla (mais de 10 milhões de posts), média (500 mil a 10 milhões),
  nicho (menos de 500 mil). Recomendação: 1 ampla + 1 ou 2 médias + 1 de nicho + 1 em alta só se casar com o vídeo,
  total de 3 a 5. Ampla sozinha afoga o vídeo; nicho demais encolhe o público (o dono não quer isso).
- **Hashtag em inglês** em vídeo brasileiro sinaliza público internacional. Traduzimos as genéricas (#funny vira #humor).
- **Proibidas e shadowban**: não existe lista oficial; listas de terceiros envelhecem rápido. Evitamos o que as regras
  citam (sexual, ódio, assédio, enganosa), pedido de engajamento (#likeforlike, #segue), outras redes (#tiktok no YouTube,
  #youtube no TikTok), aposta (#bet, #tigrinho), palavrão e xingamento partidário (#fora..., "ladrao", "petralha"...).

### 1.3 Legenda e CTA

- A legenda pesa mais que as hashtags na busca do TikTok: a palavra-chave (nome da pessoa, programa, jogo) deve estar
  nos primeiros 150 caracteres, em linguagem natural. Título, texto na tela e fala usando o mesmo termo ajudam.
- No benchmark, os 10% melhores do TikTok têm legenda mediana de 79 caracteres (manchete + contexto + pergunta); legenda
  genérica repetida ("assista o EP completo no link da bio") é o pior padrão (mediana de 395 views com 428 mil seguidores).
- CTA que funciona: pergunta de escolha que se responde com uma palavra ("Concorda? Sim ou não?", "W ou L?") e pedido
  de envio ("Manda pra quem precisa ver isso"). Quanto mais esforço o comentário exige, menos comentários.
- **"Segue pra parte 2" no TikTok** pode cair na regra de manipulação para inflar seguidores (fora do Para Você). No
  YouTube pedir inscrição é normal. Por isso o pedido de follow em série sai só no YouTube (configurável).
- 30% dos posts sem CTA e a mesma CTA não volta antes de 10 posts (anti-molde, `docs/ideias/criativo_genz.md`).

### 1.4 Hashtags em alta do Brasil (fonte pública sem login)

- A **Central Criativa do TikTok** (hashtags em alta por país) não é acessível desta máquina sem login: a página
  `ads.tiktok.com/business/creativecenter/.../hashtag` agora redireciona para o app JS do "TikTok One" (sem dados no HTML)
  e a API interna exige cabeçalhos assinados. Desde 2024 o TikTok também restringe buscas de hashtags na Central.
  Por isso ela ficou de fora (nada de contornar).
- Fonte usada: os assuntos que a própria descoberta já coleta (Google Trends, Google News, X), lidos da tabela `trends`
  do banco nas últimas 48 h, viram hashtags (1 a 3 palavras, até 20 caracteres). Cache de 12 h em
  `data/estado/hashtags_trending.json`. Uma tag em alta só entra se o termo aparecer no texto do corte.
- Fonte manual: `publicacao.hashtags_em_alta: ["#blackfriday", ...]` (copie da Central Criativa no seu navegador).

---

## 2. O que o CORTEX faz

### 2.1 Hashtags (`hashtags.choose`)

1. Normaliza: `#` + minúsculas, sem acento, só `[a-z0-9_]`, de 2 a 22 caracteres (mais longo = nichado demais).
2. Barra proibidas (`proibidas`, `proibidas_trechos`, `proibidas_prefixos` do JSON + `publicacao.hashtags_proibidas`).
3. Nicho = categoria do plano (`esportes` vira futebol, `entretenimento` vira celebridades, `outros` vira geral).
4. Vagas com 5 hashtags: **entidade** (do cérebro ou detectada no título, gancho, descrição, título do vídeo e canal:
   `#gta6`, `#casimiro`, `#neymar`, `#afazenda18`...) + **1 ampla** + **2 médias** + **1 de nicho**. Com 3: entidade,
   ampla, média. Sem entidade, a vaga vai para nicho ou ampla (fica 2 amplas + 2 médias + 1 nicho).
   Itens com `se: [...]` só entram se um dos termos estiver no texto do corte (nada de #stf num corte sem STF).
5. Corte legendado ganha `#legendado` na vaga de nicho.
6. Sem categoria conhecida: hashtags do cérebro primeiro, depois as fixas, entidades, em alta e amplas gerais.
7. Rodízio: dentro de cada camada, a menos usada nos últimos 12 posts da rede vem primeiro; se o conjunto final for
   idêntico a um dos últimos 6, troca uma ampla ou média. Memória por rede em `data/estado/hashtags_recentes.json`
   (o mesmo corte chamado de novo devolve as mesmas tags).
8. Ordem final: entidade primeiro (as 3 primeiras aparecem acima do título no YouTube). YouTube: `#Shorts` no fim.
9. Limites: `publicacao.max_hashtags` (número ou `{youtube: 3, tiktok: 4}`); TikTok no máximo 5; YouTube no máximo 15
   contando o #Shorts.

### 2.2 CTA (`hashtags.cta`) e tom

- Biblioteca no JSON (`cta`): perguntas por nicho, universais, de legendado, e pools por tom.
- Tom = `conteudo.tom_titulo` via `fabrica/tom.py` (neutro, polemico, malicioso, super_polemico, modo_besta).
  Parte das CTAs sai no tom pedido (0%, 50%, 60%, 75%, 90% conforme a intensidade) e o resto é pergunta do nicho.
  - malicioso: curiosidade e duplo sentido dirigidos a quem assiste ("Comenta o que você entendeu 😏",
    "Se você entendeu, não fala nada 🤐", "Repara no final 👀").
  - super_polemico e modo_besta: provocação e ragebait ("Se discordar comenta que eu respondo 😤",
    "Duvido você assistir até o final sem ficar p*to 😤").
  - **Piso fixo em todos os níveis**: a CTA da biblioteca nunca afirma nada sobre a pessoa do corte (ela não "lê" o
    vídeo). Frases como "Ela não negou..." só podem vir da IA e com base no corte (ver 2.4). Palavrão da biblioteca sai
    sempre mascarado (não foi dito no corte).
  - **Política e notícias têm teto "polemico"**: insinuação e ragebait ali viram desinformação e risco de remoção.
- Série: "Parte 2/3, continua na parte 3 🔜" (ou no tom: "o resto fica pra parte 3 🤐"); no YouTube também
  "Parte 1/3, segue pra ver a próxima 👀"; última parte: "Parte 3/3, a última. Viu as anteriores? Tão no perfil 👀".
- 30% sem CTA (fora de série), sem repetir nenhuma das últimas 10 CTAs da rede (`data/estado/cta_recentes.json`).
- Nunca: "curte e segue", "deixa o like", "se inscreve e ativa o sininho", "comenta EU", "segue pra mais".

### 2.3 Estrutura do post (`build_post_text`)

**YouTube** (título <= 100, descrição <= 5.000):
```
Título: citação e até 2 emojis do plano (3 no modo_besta, 1 no neutro) + (LEGENDADO) + (Parte X/Y)
Descrição:
  gancho (se não repetir o título; CAPS vira frase normal, exceto super_polemico/modo_besta)
  contexto (descrição do cérebro) + "Original em inglês, com legenda em português."
  CTA
  Fonte: Canal - "título do vídeo"         (publicacao.creditar_fonte)
  rodapé                                    (publicacao.descricao_rodape)
  #entidade #ampla #media #media #nicho #Shorts
```
**TikTok** (<= 2.200; hashtags sempre na última linha, digitadas uma a uma pelo publicador):
```
título do post (linha de gancho/citação)
contexto curto (até 150 caracteres, com a palavra-chave)    (publicacao.tiktok_contexto)
CTA
Fonte: Canal - "título do vídeo"
#entidade #ampla #media #media #nicho
```
- "(LEGENDADO)": quando `plan.idioma_origem` não é `pt` (ou a categoria/descrição/título já indicam). Não duplica se o
  pipeline já pôs; `conteudo.marcar_legendado: false` desliga. Sufixos "(LEGENDADO)" e "(Parte X/Y)" nunca são cortados.
- "Parte N" que o cérebro pôs no título ("parte 2", "(parte 3, final)", "parte 2 de 3") sai e vira "(Parte X/Y)".
- Palavrão: modo do tom (`tom.settings`: neutro remove, modo_besta mostra) ou `conteudo.palavroes`
  (mascarar = p*rra). Política e notícias nunca mostram palavrão sem máscara. O título do vídeo-fonte é sempre mascarado.
- Proibidos em qualquer texto: travessão, meia-risca, marcador e ponto médio (viram " - " ou ", "), `<` e `>`.

### 2.4 Polimento com IA (opcional)

`conteudo.legenda_post_ia: true` pede ao cérebro disponível (Claude CLI ou Ollama, via `fabrica.brain`) uma "linha"
(gancho/contexto, até 120 caracteres) e uma "pergunta" (CTA, até 80), com o bloco de tom de `tom.prompt_block`.
Uma chamada por corte (as duas redes reaproveitam). A resposta é **recusada** (volta o texto determinístico) se:
passar do tamanho, tiver hashtag, @, link, pedido de like/follow/inscrição, CAPS demais, ou tocar em tema sensível
(traição, caso, sexo, crime, droga, prisão...) que **não esteja no próprio corte**; menor de idade e estupro são
sempre recusados. Palavrão da IA que não foi dito no corte sai mascarado mesmo no modo_besta.
Série e "sem CTA" continuam determinísticos.

---

## 3. Chaves de configuração (todas opcionais, lidas com `cfg.get`)

| Chave | Padrão | Para quê |
|---|---|---|
| `publicacao.max_hashtags` | 5 | número ou `{youtube: N, tiktok: N}`; TikTok no máximo 5, YouTube no máximo 14 + #Shorts |
| `publicacao.hashtags_fixas` | `[]` | sempre entram (logo depois da entidade). Recomendado: no máximo 1 |
| `publicacao.hashtags_proibidas` | `[]` | proibidas extras |
| `publicacao.youtube_hashtag_shorts` | true | `#Shorts` no fim da descrição |
| `publicacao.hashtags_em_alta` | `[]` | em alta manual (só entram se casarem com o corte) |
| `publicacao.hashtags_em_alta_auto` | true | usa as tendências do banco (cache 12 h) |
| `publicacao.hashtags_memoria` | true | grava a memória anti-repetição (hashtags e CTA) |
| `publicacao.cta_sem_prob` | 0.3 | fração de posts sem CTA |
| `publicacao.cta_nao_repetir` | 10 | quantas CTAs recentes não podem voltar |
| `publicacao.cta_pedir_seguir` | `youtube` | `youtube`, `sempre` ou `nunca`: pedir follow/inscrição em série |
| `publicacao.tiktok_contexto` | true | linha de contexto na legenda do TikTok |
| `publicacao.creditar_fonte`, `descricao_rodape`, `tiktok_rodape` | (já existiam) | crédito e rodapé |
| `conteudo.tom_titulo` | `malicioso` | nível do tom (`fabrica/tom.py`) |
| `conteudo.palavroes` | `mascarar` | usado quando o nível do tom não define |
| `conteudo.emojis` | true | false tira todos os emojis |
| `conteudo.marcar_legendado` | true | "(LEGENDADO)" no título |
| `conteudo.legenda_post_ia` | false | polimento com IA |
| `conteudo.legenda_post_ia_timeout_s` | 90 | tempo máximo da IA |

## 4. Como editar os dados

`fabrica/dados/hashtags_ptbr.json`: `nichos.<nicho>.amplas|medias|nicho` aceitam `"#tag"` (sempre relevante no nicho)
ou `{"tag": "#tag", "se": ["termo", ...]}` (só se o termo aparecer; termos sem acento, em minúsculas, palavra inteira).
`entidades` liga termos a tags de pessoa, programa, time ou jogo (o termo mais longo vence: "flavio bolsonaro" não vira
também #bolsonaro). Evite termos ambíguos ("galo", "peixe", "fogão" foram retirados). `traducoes` troca genérica em
inglês por PT. `cta` guarda a biblioteca de CTAs e as regras. O arquivo é relido sozinho quando muda.

## 5. Limitações

- Volume real de cada hashtag no Brasil não é público sem login; as camadas são curadoria (guias de 2026 + benchmark).
- Entidades: lista fixa de cerca de 70 nomes; nomes novos dependem das hashtags do cérebro ou das tendências do banco.
- A CTA não sabe o que acontece no vídeo; por isso só usa frases dirigidas ao espectador.
- O limite de 5 hashtags do TikTok não é oficial e pode mudar; o de 60 do YouTube é oficial.

## 6. Fontes

- YouTube Help, regras de hashtags: https://support.google.com/youtube/answer/6390658
- Social Media Today (17/08/2025), TikTok e o limite de 5 hashtags: https://www.socialmediatoday.com/news/tiktok-implements-five-hashtag-limit-per-post/757857/
- Search Engine Land, limite de hashtags no TikTok: https://searchengineland.com/tiktok-limits-hashtags-460894
- TikTok Community Guidelines, Integridade e autenticidade (manipulação de engajamento e conteúdo não original fora do Para Você): https://www.tiktok.com/community-guidelines/en/integrity-authenticity
- SocialCrawl (ago/2026), "Do hashtags work on TikTok": https://www.socialcrawl.dev/blog/do-hashtags-work-on-tiktok
- Metricool, hashtags e tendências do TikTok 2026: https://metricool.com/tiktok-hashtags/ e https://metricool.com/pt/tendencias-tiktok/
- Go Viral (mar/2026), estratégia de hashtags em 3 camadas: https://www.go-viral.app/pt/blog/estrategia-hashtags-tiktok/
- GhostShorts (mar/2026), faixas ampla/média/nicho: https://ghostshorts.com/pt-br/blog/melhores-hashtags-para-crescer-no-tiktok-2026
- Hootsuite, legenda de 4.000 caracteres no app: https://www.hootsuite.com/whats-new/expanded-tiktok-caption-length-in-create
- Metricool, SEO no TikTok 2026: https://metricool.com/tiktok-seo/
- Darkroom, palavras-chave de busca por vídeo (abr/2026, não confirmado pelo TikTok): https://www.darkroomagency.com/observatory/tiktok-seo
- Fliki e Fluxnote, #Shorts em 2026: https://fliki.ai/blog/youtube-shorts-hashtags e https://fluxnote.io/guides/youtube-shorts-tags-vs-hashtags-2026
- vidIQ e TunePocket, título de Shorts: https://vidiq.com/blog/post/youtube-shorts-titles/ e https://www.tunepocket.com/youtube-shorts-video-titles/
- Wild and Free Tools, não existe lista oficial de hashtags banidas: https://wildandfreetools.com/blog/banned-hashtags-tiktok-list-2026/
- Cut.Pro (set/2026), hashtags em cortes BR: https://cut.pro/pt-BR/blog/hashtag-campeonato-de-cortes-2026
- Internos: `docs/ideias/benchmark_canais.md` (medição de 23/11/2026), `docs/ideias/criativo_genz.md`,
  `docs/ideias/algoritmo_e_riscos.md`.

Cuidado com a evidência: quase todos os números de efeito vêm de blogs de fornecedores ou de amostras pequenas e servem
como direção. As regras de plataforma (60 hashtags e 3 acima do título no YouTube; Para Você do TikTok) vêm de fontes
oficiais. Valide na própria conta (a memória e o relatório de métricas permitem comparar conjuntos).
