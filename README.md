<p align="center">
  <img src="docs/cortex_banner.png" alt="CORTEX: Central Operacional de Recortes, Tendências e EXposição" width="900">
</p>

Sistema local (roda no seu PC, pelo CMD) que faz sozinho todo o ciclo de um canal de cortes:

| Etapa | O que faz |
|---|---|
| 1. Descobre | O que está em alta no Brasil: Google Trends, Google Notícias, X/Twitter, YouTube, Twitch e Kick. Ou busca o tema que você mandar, ou corta um link que você colar. |
| 2. Acha os vídeos | Lives de hoje de canais grandes, podcasts, debates, polêmicas, games, humor (YouTube, Twitch, Kick). |
| 3. Escolhe os momentos | Transcreve (legenda da plataforma ou Whisper local) e a IA escolhe os trechos com mais chance de viralizar, com nota de 0 a 100 e o porquê. Assunto longo vira Parte 1, 2, 3. |
| 4. Baixa só o necessário | Só os trechos que viram corte, nunca o vídeo inteiro. |
| 5. Edita em 9:16 | Vídeo + gameplay/ASMR, fundo desfocado ou tela cheia; legenda grande palavra por palavra; título com emoji; selo PARTE X; barra de progresso; áudio normalizado. |
| 6. Publica | YouTube Shorts e TikTok, pelo navegador, sozinho ou depois da sua aprovação. |
| 7. Relata | Painel ao vivo no terminal, relatório HTML, notificação do Windows e cópia no OneDrive. |

## Primeiros passos

Dê dois cliques em **`cortex.bat`**. No menu:

1. **Login > YouTube** e depois **Login > TikTok**. Abre o navegador do CORTEX (separado do seu Chrome). Entre na conta, crie o canal se pedir e feche a janela. Logo depois ele oferece um teste da página de upload, que não publica nada.
2. **Login > Claude** (recomendado). Abre o Claude Code: digite `/login` e siga. É a IA que escolhe os cortes e escreve os títulos. Sem isso o CORTEX funciona no modo heurístico (sem IA), com títulos mais genéricos.
3. **Revisar e publicar > Publicação de TESTE** em uma rodada qualquer, para ver tudo sendo preenchido sem publicar.
4. **Piloto automático > LIGAR**.
5. **Piloto automático > Ligar sozinho quando o Windows iniciar**. Assim, se o PC reiniciar, o piloto volta sozinho depois que você entrar no Windows.

## Piloto automático 24/7

`cortex autopiloto` mostra um painel ao vivo com o que está acontecendo agora, a fila de cortes prontos, os posts do dia, os próximos horários e o log rolando.

| Parte | Como funciona |
|---|---|
| Produtor | Quando a fila de cortes prontos fica baixa, roda uma rodada completa e enche a fila. |
| Publicador | Posta um corte por vez, espaçado, preferindo o horário nobre de cada dia da semana. Só publica sozinho nota 62 ou mais; o resto espera sua aprovação em Revisar. |
| Proteção da conta | Conta nova não posta nos dias 0 a 3; depois 1 post por dia até o dia 10, 2 até o dia 21, 3 até o dia 42 e 4 a partir daí (por rede). Mínimo de 2 h entre posts no YouTube e 2 h 30 no TikTok. |
| Erros | Nada derruba o piloto: ele registra, espera e tenta de novo. Captcha ou verificação pausam aquela rede e avisam você. |
| Energia | Mantém o PC acordado enquanto roda. |

Variações: `cortex autopiloto --teste` (simula a publicação) e `cortex autopiloto --so-produzir`.

## Comandos (CMD, dentro da pasta do CORTEX)

| Comando | O que faz |
|---|---|
| `cortex` | abre o menu |
| `cortex autopiloto` | piloto automático 24/7 com painel ao vivo |
| `cortex inicio-automatico ligar` | liga o piloto quando o Windows iniciar |
| `cortex rodar` | uma rodada completa |
| `cortex rodar --temas "gta 6, debate" --videos 10 --publicar revisar` | rodada por tema |
| `cortex cortar https://www.youtube.com/watch?v=...` | corta um link específico |
| `cortex tendencias` | o que está em alta agora |
| `cortex buscar neymar` | lista vídeos de um tema sem processar |
| `cortex revisar` | revisa, aprova e publica de uma vez |
| `cortex login youtube`, `tiktok` ou `claude` | logins |
| `cortex testar-publicacao` | confere a página de upload sem publicar |
| `cortex agendar` / `desagendar` / `agenda` | modo agendado (2 a 4 vezes por dia) em vez do 24/7 |
| `cortex status` | diagnóstico completo |
| `cortex relatorio` | abre o último relatório |
| `cortex fundos baixar` | mais vídeos de fundo (Creative Commons) |
| `cortex limpar` | libera espaço em disco |

## Configuração

Tudo fica em **`config.yaml`** (menu Configurações ou Bloco de Notas). O piloto relê o arquivo a cada rodada.

| Opção | Para que serve |
|---|---|
| `modo_publicacao`, `autopiloto.publicacao` | `auto` publica sozinho; `revisar` só publica o que você aprovar |
| `execucao.videos_por_execucao` | quantos vídeos-fonte por rodada (5, 10, 15, 20...) |
| `busca.modo`, `busca.palavras_chave` | `trends`, `palavra_chave` ou `misto` |
| `busca.canais_monitorados`, `busca.canais_bloqueados` | canais que você quer acompanhar ou nunca usar |
| `cerebro.motor` | `auto`, `claude`, `ollama` ou `heuristico` |
| `conteudo.emojis` | emoji nos títulos e no vídeo (o terminal nunca mostra emoji) |
| `corte.duracao_max_s: 58` | no YouTube, Short acima de 60 s com reivindicação de direitos é bloqueado no mundo todo |
| `edicao.layout`, `edicao.marca_dagua` | layout dos vídeos e sua marca d'água (ex.: @seucanal) |
| `edicao.encoder` | `libx264` (CPU, padrão, mais estável neste PC) ou `h264_amf` (placa AMD, mais rápido) |
| `publicacao.tiktok_modo` | `auto` ou `semi` (ele preenche tudo e você só clica em Publicar) |
| `publicacao.aquecimento` | regras de conta nova |
| `armazenamento.onedrive` | arquiva os cortes publicados no OneDrive e libera o disco |

## OneDrive

Os cortes publicados vão para **`OneDrive\CORTEX\cortes\AAAA-MM\`** e ficam "somente online": depois que sobem para a nuvem, o espaço no C: é liberado. Os relatórios são copiados para `OneDrive\CORTEX\relatorios\`, então dá para ver no celular.

## Se o PC travar rodando 24/7

1. Atualize o driver de vídeo.
2. Rode o Diagnóstico de Memória do Windows: aperte Win+R, digite `mdsched` e escolha reiniciar agora.
3. Mantenha `edicao.encoder: libx264` (CPU): não depende do driver da placa de vídeo.
4. Ligue o início automático do piloto: se o PC reiniciar, ele volta sozinho depois do login.

## Leia antes de ligar no automático

1. **Termos de uso.** O YouTube e o TikTok proíbem automação de upload fora das ferramentas oficiais. Publicar por navegador automatizado pode levar a bloqueio da conta. O CORTEX reduz o risco com volume baixo, aquecimento, horários e textos variados, mas o risco existe e a decisão é sua. Alternativas mais seguras: `autopiloto.publicacao: revisar` ou `publicacao.tiktok_modo: semi`.
2. **Direitos autorais.** Repostar conteúdo de terceiros pode gerar reivindicação ou strike. O CORTEX bloqueia canais que proíbem cortes, pula transmissões esportivas, TV, filmes, música e apostas, e credita a fonte.
3. **Captcha e verificação.** O CORTEX nunca burla: pausa aquela rede, avisa no painel e por notificação, e você resolve no navegador do CORTEX.

## Pastas

| Pasta / arquivo | Conteúdo |
|---|---|
| `cortex.bat` | abre o programa |
| `instalar.bat` | instala ou repara (e cria o atalho na Área de Trabalho) |
| `config.yaml` | suas configurações |
| `work\renders\` | cortes prontos |
| `work\amostras\` | vídeos de exemplo de cada layout |
| `relatorios\` | relatórios HTML de cada rodada |
| `logs\` | logs e prints de erro do navegador |
| `assets\fundos\` | vídeos de fundo (pode colocar os seus nas subpastas) |
| `data\` | banco, navegador e modelos de IA (não apague) |
| `docs\` | detalhes técnicos; `docs\ideias\` tem as pesquisas e o roadmap |
