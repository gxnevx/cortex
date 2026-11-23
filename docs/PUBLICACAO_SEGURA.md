> Nota: a camada que imitava uma pessoa (mouse em curva, tremor, clique fora do centro, digitacao irregular) foi removida do codigo. Trechos abaixo que a descrevem sao historicos.

# Publicação segura: regras das redes, API oficial e o que o CORTEX faz

Objetivo do dono: as contas do dono (TikTok e YouTube) nunca serem bloqueadas nem
marcadas como robô ou spam. Este documento junta a pesquisa (novembro de 2026), as regras oficiais com links e o que
o CORTEX faz por causa delas. Complementa `docs/PUBLICACAO.md` (seletores e fluxo).

Regra principal do CORTEX, por escolha: **nada de camuflagem**. Sem plugins "stealth", sem navegador "anti-detect",
sem trocar user-agent, impressão digital ou `navigator.webdriver`, sem proxy ou VPN rotativa, sem resolver captcha. Além
de violar as regras das redes, é exatamente o comportamento que elas descrevem como motivo de bloqueio. O que o CORTEX
faz é publicar pouco, devagar, parar em qualquer verificação e nunca repetir um envio que pode ter dado certo. O ritmo
(mouse, digitação, pausas) imita o de uma pessoa, a pedido do dono: deixa as páginas reagirem, mas **não torna a
automação permitida** nem garante que a conta não seja marcada (seção 4).

Resumo em 5 linhas:

1. **YouTube: trocar para a API oficial** (YouTube Data API v3) assim que possível. Desde 2 nov 2026, projetos não
   auditados podem publicar vídeos **públicos** pela API e o limite padrão é de cerca de 100 envios por dia. Isso elimina
   o risco de "automação do navegador" no YouTube. Enquanto não trocar, o navegador continua com ritmo humano.
2. **TikTok: a API oficial não atende uso pessoal** (as diretrizes excluem ferramentas para publicar na sua própria conta).
   Sem API, o caminho mais seguro é `publicacao.tiktok_modo: semi` (o CORTEX preenche tudo e **você** clica em Publicar),
   pelo menos durante o aquecimento da conta.
3. O que mais protege as duas contas não é o "como envia": é o conteúdo ter edição real, variedade e contexto próprio, e
   volume baixo. As duas redes punem produção em massa com modelo repetido e reaproveitamento sem acréscimo.
4. Legendas, zoom, cortes, trilha e títulos escritos por IA **não** exigem rótulo de IA. Voz clonada de outra pessoa ou
   dublagem com IA da voz do convidado **exigem**.
5. Captcha, "confirme que é você" ou limite da rede: o CORTEX para, tira print, pausa a rede por 24 h e avisa. Só volta
   quando você refaz o login (`cortex login <rede>`) ou a pausa acaba.

---

## 1. YouTube: API oficial (YouTube Data API v3)

### O que mudou (importante: muito tutorial na internet está desatualizado)

| Regra | Situação hoje | Fonte |
|---|---|---|
| Custo de um envio (`videos.insert`) | caiu de cerca de 1600 para cerca de 100 unidades em 4 dez 2025; desde 1 jun 2026 `videos.insert` tem cota própria: **1 unidade por envio, 100 por dia por projeto** | https://developers.google.com/youtube/v3/revision_history , https://developers.google.com/youtube/v3/docs/videos/insert |
| Cota geral | 10.000 unidades por dia para o resto da API | https://developers.google.com/youtube/v3/getting-started |
| "Projeto não auditado só publica privado" (regra de 28 jul 2020) | **revogada em 2 nov 2026**: o envio por projeto não verificado deixou de ficar preso em privado; sem privacidade informada o padrão virou público, e alguns envios ainda podem ficar privados conforme as configurações da conta | https://developers.google.com/youtube/v3/revision_history |
| Auditoria da API | só para pedir cota **acima** do padrão (formulário "Audit and Quota Extension"); não publica prazo | https://support.google.com/youtube/contact/yt_api_form , https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits |
| Limite diário do canal | existe e vale para computador, celular e API somados; o número não é publicado; canal com histórico ou identidade verificada tem limite maior | https://support.google.com/youtube/answer/57407 , https://support.google.com/youtube/answer/9890437 |
| Verificação por telefone | só para vídeos acima de 15 min (não afeta Shorts) | https://support.google.com/youtube/answer/71673 |

Na prática: para o nosso volume (1 ou 2 Shorts por dia), a cota padrão sobra com folga e **não é preciso auditoria**.

### Como ligar (quando o dono quiser)

1. https://console.cloud.google.com/ > criar projeto > ativar **YouTube Data API v3**.
2. Tela de consentimento OAuth: tipo Externo, escopo `https://www.googleapis.com/auth/youtube.upload`, você como único
   usuário. Publicar o app como "Em produção" (em "Teste" o token de acesso expira em 7 dias). Apps de uso
   próprio ou com menos de 100 usuários não precisam de verificação, mas o Google pode mostrar o aviso de app não verificado.
   https://developers.google.com/identity/protocols/oauth2 , https://support.google.com/cloud/answer/13464323
3. O CORTEX pede sua autorização uma vez (janela do Google), guarda o token localmente e passa a enviar por
   `videos.insert` (título, descrição, "não é para crianças", visibilidade) sem abrir navegador. **Ainda não existe no
   código**: é uma proposta.
4. Regras dos desenvolvedores a conferir antes de ligar: consentimento expresso seu antes de cada envio automático,
   opção clara de privacidade e um só projeto por app. Não avaliamos se o autopiloto atual cumpre a primeira.
   https://developers.google.com/youtube/terms/developer-policies

Não confirmado na pesquisa: se o modo "pessoal" do Google evita a expiração de 7 dias; se o escopo `youtube.upload` é
classificado como "sensível" (o exemplo oficial de sensível é apagar vídeo). Conferir na hora de ativar.

**Recomendação: migrar o YouTube para a API antes de passar de 1 ou 2 posts por dia.** O navegador continua como plano B.

## 2. TikTok: API oficial (Content Posting API)

- Dois modos: **Direct Post** (publica direto) e **Upload** (manda para a caixa de entrada; a pessoa termina no app).
  https://developers.tiktok.com/doc/content-posting-api-get-started-upload-content
- App sem auditoria: só publica **privado** (visível apenas para você), no
  máximo 5 contas em 24 h, e a conta precisa estar privada na hora. https://developers.tiktok.com/doc/content-sharing-guidelines
- Limites: cerca de 15 posts por dia por criador; consultas de criador 20 por minuto; início de vídeo 6 por minuto; até 5
  envios pendentes na caixa de entrada em 24 h. https://developers.tiktok.com/doc/content-posting-api-reference-direct-post ,
  https://developers.tiktok.com/doc/content-posting-api-reference-upload-video
- Auditoria exige: site público com política de privacidade e termos, vídeo demo, tela que mostra o perfil do criador,
  privacidade escolhida **na hora** (sem valor padrão), caixas de comentário, dueto e costura desligadas por padrão,
  aviso de conteúdo comercial, prévia do post, **sem marca d'água ou logo**. https://developers.tiktok.com/doc/app-review-guidelines
- **Uso pessoal é recusado explicitamente**: um dos exemplos de app inaceitável é o utilitário que envia para contas que
  você ou a sua equipe administram. https://developers.tiktok.com/doc/content-sharing-guidelines

Conclusão: a API oficial do TikTok não serve para o CORTEX (uso pessoal, e as regras proíbem logo, que os nossos cortes
têm). Opções: `tiktok_modo: semi` (você clica em Publicar) ou usar o agendador nativo do TikTok Studio (15 min a 10 dias
à frente) para o envio que você confirma. https://ads.tiktok.com/business/en/blog/introducing-video-scheduler-now-you-can-plan-tiktoks-in-advance

## 3. O que os "uploaders" de código aberto fazem e por que as contas são marcadas

| Projeto | Ritmo / espera | O que os usuários relatam |
|---|---|---|
| wkaisertexas/tiktok-uploader | esperas fixas (5 s entre hashtags, 180 s de upload), sem novas tentativas | "muitas tentativas" depois de vários uploads (resolve esperando horas); captcha no modo sem janela; suspeita de shadowban (zero views) (issues 158, 220, 169, 170, 135, 149) |
| linouk23/youtube_uploader_selenium (parado) | 1 s entre passos, sem limite de tempo | o Google bloqueia o login em navegador automatizado (issue 78) |
| makiisthenes/TiktokAutoUploader | API privada com assinatura (evasão; não usamos) | relato de banimento (issue 37); o próprio README avisa do risco |
| dreammis/social-auto-upload | `stealth.min.js` e esperas fixas de 0,5 a 3 s, laços de repetição sem limite | publicação em sequência desloga a conta (160), navegador recusado no login (220, 303); o mantenedor recomenda lotes pequenos, com janela, sem conteúdo de baixa qualidade feito por IA (188) |

Fontes: https://github.com/wkaisertexas/tiktok-uploader , https://github.com/makiisthenes/TiktokAutoUploader ,
https://github.com/dreammis/social-auto-upload , https://github.com/linouk23/youtube_uploader_selenium

Padrão que aparece em todos: (a) captcha aparece mais em **navegador sem janela** e em **login recente**; (b) "muitas
tentativas" vem de **rajadas de posts**; (c) o Google bloqueia **login** feito em navegador automatizado. O CORTEX já evita os
três: janela normal (só fora da tela), login feito por você sem automação, poucos posts bem espaçados.

## 4. O que as redes dizem sobre automação e spam

- YouTube, Termos: proíbem acessar o serviço por meios automatizados, salvo buscadores ou autorização prévia por escrito.
  Enviar pelo Studio automatizado está no lado errado dessa frase; enviar pela **API** é o meio permitido.
  https://www.youtube.com/static?template=terms&gl=US&hl=en
- YouTube, spam e práticas enganosas: proíbe usar ferramentas ou IA para produzir muito conteúdo parecido com poucas
  mudanças e reaproveitar conteúdo sem acréscimo; poucas variações do mesmo vídeo são aceitas. https://support.google.com/youtube/answer/2801973 . Engajamento falso (views, curtidas, inscritos por script):
  https://support.google.com/youtube/answer/3399767
- TikTok, Termos (1 dez 2025): proíbem usar scripts automatizados para coletar dados ou interagir com os serviços. https://www.tiktok.com/legal/page/row/terms-of-service/en
- TikTok, Diretrizes (24 set 2026): proíbem ferramentas de automação, scripts e truques feitos para contornar os sistemas
  da plataforma, e conteúdo sem novidade fica fora do feed Para Você. https://www.tiktok.com/community-guidelines/en/integrity-authenticity

Leitura honesta: pelo texto dos Termos, publicar por script no navegador **não é permitido** em nenhuma das duas redes
sem autorização. O ritmo calmo não muda isso: mouse em curva, tremor, clique fora do centro e digitação pausada imitam uma
pessoa, mas o envio continua sendo automação e a conta continua sujeita às regras. O que reduz o risco de verdade é usar
a API no YouTube e deixar o clique final com o dono no TikTok (`tiktok_modo: semi`).

## 5. Não ser confundido com spam, robô ou "AI slop" (de forma legítima)

### 5.1 "Conteúdo inautêntico" no YouTube (julho de 2025)

Em 15 jul 2025 o YouTube renomeou "conteúdo repetitivo" para **"conteúdo inautêntico"** nas regras de monetização e
deixou claro que inclui conteúdo repetitivo ou produzido em massa; não mudou a regra de conteúdo reutilizado.
https://support.google.com/youtube/answer/1311392

O que um revisor olha no canal: tema principal, vídeos mais vistos, mais recentes e com mais tempo de exibição, títulos,
miniaturas, descrições e a aba Sobre. O que reprova um canal de cortes: aparência de modelo
repetido, recortes emendados com pouca ou nenhuma narrativa, e vídeo já enviado por muitos outros canais. O que passa:
crítica, reação e edição com narrativa e comentário próprios.

### 5.2 Rótulo de IA (quando precisa e quando não precisa)

| Situação | YouTube ("conteúdo alterado ou sintético") | TikTok (rótulo AIGC) |
|---|---|---|
| Vídeo real com cortes, zoom, legenda, legenda traduzida, trilha, cor, título ou miniatura escritos por IA | **não precisa** (a ajuda lista legendas, cor, correção de áudio, e IA para roteiro, título, miniatura) | **não precisa** (regra vale para conteúdo "gerado ou significativamente editado" que mostra cena ou pessoa realista) |
| Voz clonada de outra pessoa (ex.: dublar o convidado com IA), rosto trocado, cena realista inventada | **precisa** | **precisa** |
| Clonar a **sua própria** voz | não precisa | em dúvida, rotular |

Fontes: https://support.google.com/youtube/answer/14328491 , https://support.tiktok.com/en/using-tiktok/creating-videos/ai-generated-content ,
https://www.tiktok.com/community-guidelines/en/integrity-authenticity . As duas redes leem C2PA (marca de origem) e rotulam sozinhas.
Legenda traduzida não aparece com nome na lista do YouTube, mas é legenda (interpretação nossa, conservadora).

CORTEX: `publicacao.youtube_conteudo_alterado: false` (resposta "Não") está certo para cortes reais com legenda e zoom. Se
um dia houver dublagem com IA da voz do convidado, mudar para `true` **e** avisar na legenda do TikTok.

### 5.3 O que o CORTEX deve garantir (variedade e autenticidade)

Conferido na configuração e no código lido: no máximo 3 hashtags no Shorts e 5 no TikTok e crédito da fonte
(`config.yaml`), horários nobres por dia da semana com espaçamento mínimo (`fabrica/policy.py`) e a segunda trava deste
módulo (`publish_batch`). **Não conferido** nesta pesquisa: a memória de hashtags (`fabrica/hashtags.py`) e se títulos e
ganchos nunca se repetem.

Sugestões para o orquestrador (fora dos arquivos deste módulo):

1. **Modelos visuais variados**: alternar entre pelo menos 3 layouts (full, split, blur) e 2 a 3 estilos de legenda; não
   usar o mesmo layout em mais de 2 cortes seguidos.
2. **Contexto próprio em cada corte**: 1 frase de gancho ou comentário original (não a transcrição) na descrição ou no
   primeiro segundo. Sem isso o corte pode ser lido como "reused content".
3. **Nunca repetir texto**: título, descrição e CTA não podem se repetir literalmente; checar contra os últimos 30 posts.
4. **Horários variados**: sortear o minuto dentro da janela nobre (o autopilot já sorteia) e não publicar todo dia no mesmo
   horário exato.
5. **Poucos posts**: manter o aquecimento (0 nos 3 primeiros dias, 1 por dia na primeira semana). Não apagar e reenviar
   um Short que não viralizou (parece spam). https://techcrunch.com/2023/08/25/youtube-demystifies-the-shorts-algorithm-views-and-answers-other-creator-questions/
6. **Sem isca**: nada de "curta se concorda", "marque 3 amigos"; o TikTok tira isso do Para Você.
   https://www.tiktok.com/community-guidelines/en/integrity-authenticity
7. **Hashtags**: só as relacionadas ao vídeo; nunca passar de 60 (o YouTube ignora todas).
   https://support.google.com/youtube/answer/6390658
8. **Interação humana de verdade**: o dono responde comentários e assiste aos próprios vídeos no celular, no dia a dia.

### 5.4 Extensões do Chrome ajudam?

Resposta honesta: **não**. Não existe extensão oficial do Google ou do TikTok para publicar. Extensões "humanizadoras",
"anti-detect" ou "para não ser banido" são ferramentas de evasão (o TikTok proíbe truques para contornar os sistemas) e ainda pedem
acesso total às páginas, inclusive à sua sessão logada. Casos reais: a extensão da Cyberhaven (dez 2024) foi sequestrada
para roubar cookies, e a campanha RedDirection (jul 2025) atingiu 18 extensões, algumas verificadas, com 2,3 milhões de
usuários. https://cyberhaven.com/blog/cyberhavens-chrome-extension-security-incident-and-what-were-doing-about-it ,
https://www.theregister.com/2025/07/08/browser_hijacking_campaign/

Regra do CORTEX: o perfil `data\navegador` fica **sem extensões**.

## 6. O que o CORTEX faz hoje (camada humana e travas)

Código: `fabrica/publish/human.py` (ritmo), `youtube.py` e `tiktok.py` (fluxos), `guard.py` (travas), `__init__.py`
(`publish_batch`). Configuração: `publicacao.humano.*` (todas opcionais; padrões abaixo).

| Chave (`publicacao.humano.`) | Padrão | O que faz |
|---|---|---|
| `velocidade` | 1.0 | multiplica todas as esperas (1.5 = mais calmo) |
| `hover_ms` | [120, 450] | tempo com o mouse parado sobre o botão antes do clique |
| `digitacao_cps` | [6, 9] | letras por segundo (a média de cada texto é sorteada nesta faixa) |
| `pausa_pontuacao_s`, `pausa_palavra_s` | [0.25, 0.7], [0.04, 0.22] | pausas extras depois de pontuação e entre palavras |
| `pausa_pensar_s`, `pausa_curta_s` | [1.2, 3.5], [0.4, 1.2] | pausa antes de decisões; entre ações seguidas |
| `digitar_ate_chars` | 280 | textos maiores, ou com `#`, são colados de uma vez (como Ctrl+V) |
| `aquecimento_s`, `rolagens_aquecimento` | [5, 20], [1, 3] | tempo olhando a página inicial, com rolagens, antes do envio |
| `timeout_acao_s` | 45 | paciência de cada ação (uma tentativa só) |
| `pausa_antes_de_repetir_s` | [25, 60] | pausa longa antes da única nova tentativa de um passo |
| `rede_calma_max_s` | 6 | quanto espera a rede acalmar (melhor esforço) |

Fluxo de cada post (por corte, uma sessão de navegador só, fora da tela; `janela_oculta: true`):

1. Abre a página inicial da rede (Studio do YouTube ou TikTok Studio), fica 5 a 20 s, com 1 a 3 rolagens e o mouse passeando.
   Sem curtir, seguir, comentar ou qualquer engajamento.
2. Vai para o envio pelo caminho normal (botão Criar > Carregar vídeos, ou Carregar no menu lateral do TikTok); só se o
   botão não aparecer usa o endereço direto.
3. Clica em "Selecionar" e o seletor de arquivos é interceptado (não abre janela do Windows). Cada clique: mouse em curva
   (Bézier com aceleração suave, tremor, velocidade pela distância), pausa sobre o alvo, ponto aleatório dentro (nunca o
   centro exato), botão pressionado 45 a 130 ms. Antes: elemento visível, parado, sem "carregando" por cima, rede calma.
4. Digita o título letra a letra (média 6 a 9 letras por segundo, pausas em pontuação e palavras), cola a descrição pronta,
   escolhe hashtags na sugestão, marca opções conferindo o estado depois do clique.
5. **Teste (dry run)**: YouTube em Privado e o rascunho é apagado no fim; TikTok em "Somente você" e Descartar. O botão
   final nunca é clicado (checagem no código antes do clique).
6. **De verdade**: pausa de "leitura", clica em Publicar **uma vez**, espera a confirmação (diálogo de publicado, ou o botão
   sumir, ou o TikTok ir para a página de conteúdo), só então fecha.

Travas (`guard.py` e `publish_batch`):

- **Nunca duplicar**: pula corte já publicado, repetido na lista, ou com clique em Publicar já registrado
  (`data/estado/publicacao_cliques.json`, gravado **antes** do clique). Se a confirmação não veio, o resultado é
  `ok=True` com erro "INCERTO: ...": o corte nunca é reenviado, e o dono confere no Studio. **Atenção**: o pipeline trata
  `ok=True` como publicado e pode liberar o vídeo do PC (`storage.release_published` move o principal e apaga as versões
  por rede) mesmo que o post não tenha saído. Precisa de ajuste no pipeline.
- **Uma tentativa paciente** por passo; falhou: print + erro em português; no máximo **uma** nova tentativa depois de
  25 a 60 s, e só se a conferência do estado mostrar que o passo não foi feito (passos como escolher arquivo e Publicar
  nunca são repetidos). Captcha, login ou verificação: para na hora.
- **Pausa depois de captcha, verificação ou limite**: a rede fica parada por `publicacao.pausa_apos_bloqueio_h` (padrão 24 h),
  ou até o dono refazer o login (`cortex login <rede>` libera). Nada de insistir em laço.
- **Segunda trava de conta**: `policy.can_post` (aquecimento, limite do dia, intervalo mínimo, saúde) é conferido antes de
  abrir o navegador e de novo antes de cada post. Na prática, com os intervalos atuais, cada chamada publica no máximo
  um post por rede.
- **Uma publicação por vez** no PC (trava entre processos) e uma sessão de navegador por horário de post.
- Registro: cada envio deixa um resumo em `logs/publicacao_ritmo.log` (mouse, hover, letras por segundo, pausas, passos,
  repetições) e um print em `logs/screenshots/` se algo falhar.

Números dos testes (23 nov 2026, dry run, janela fora da tela; detalhes em `logs/publicacao_ritmo.log`):

- YouTube: 1a rodada falhou ao fechar o diálogo (o rascunho privado ficou no Studio e foi apagado depois); 2a rodada
  completa, 0 repetições, hover médio de 239 ms, 7,4 letras por segundo, 34 passos de rolagem, 5 pausas de pensar.
- TikTok: 2 rodadas falharam, cada uma com 1 repetição (tour "Entendido" cobrindo a legenda; opção "Só tu" não
  reconhecida). A 3a chegou ao botão Publicar habilitado sem repetições (hover médio de 232 ms, 190 letras em 24 s).
  Em nenhuma o descarte do envio foi confirmado. Depois, só leitura: a lista de publicados e programados do TikTok e as
  listas do YouTube estavam vazias; rascunhos do TikTok não foram conferidos.

## 7. Se algo acontecer

| Sinal | O que o CORTEX faz | O que o dono faz |
|---|---|---|
| Captcha ou "confirme que é você" | para, print, pausa a rede 24 h, avisa | `cortex login <rede>`, resolve **você mesmo**, fecha a janela |
| "Limite diário de envios" | pausa a rede 24 h | diminui `max_posts_por_dia`; não insiste |
| Sem confirmação depois de Publicar | marca "INCERTO", não reenvia | confere no Studio se saiu |
| Post caiu para 0 views ou conta restrita | o autopiloto pausa pela saúde (`policy.health`) | espera uns dias, revisa o conteúdo, não apaga e reenvia |

## 8. Pendências e limites da pesquisa

- Não verificado: comportamento de `videos.insert` com o nosso canal (precisa do projeto do Google), expiração de token
  no modo pessoal, e regras do Upload (caixa de entrada) do TikTok para apps sem auditoria.
- Duas páginas foram relidas direto (histórico de revisões da API do YouTube e diretrizes do TikTok); as demais fontes foram
  lidas por um agente de pesquisa e não foram conferidas uma a uma.
- As regras mudam: revisar este arquivo a cada 3 meses e quando alguma rede avisar. Fontes oficiais nos links acima.
