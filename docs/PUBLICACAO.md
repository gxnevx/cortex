> Nota: a camada que imitava uma pessoa (mouse em curva, tremor, clique fora do centro, digitacao irregular) foi removida do codigo. Trechos abaixo que a descrevem sao historicos.

# Publicação (YouTube Shorts + TikTok pelo navegador)

Módulo: `fabrica/publish/`: `browser.py` (navegador, login, cookies), `youtube.py`, `tiktok.py`,
`captions.py` (título, descrição, legenda), `human.py` (ritmo humano), `guard.py` (travas), `__init__.py`
(`publish_batch`, `selftest`). Regras das redes, API oficial e riscos: `docs/PUBLICACAO_SEGURA.md`.
Testes: `tests/publish_humano_unit.py` (camada humana e travas, sem rede social), `tests/publish_smoke.py` (com o perfil
logado roda só a parte sem navegador) e `tests/publish_dryrun.py` (ao vivo, perfil logado, não publica).

> Regras fixas: a Fábrica **nunca** digita senha, nunca faz login sozinha e nunca resolve captcha.
> Login, captcha e verificação são sempre feitos por você. Quando aparece um bloqueio, a publicação daquela
> rede **para** e o erro começa com `ACAO_NECESSARIA:` (ou `LIMITE_DIARIO:`), explicando o que fazer.

---

## 1. Primeiro uso (passo a passo)

1. `cortex login youtube`: abre o **Chrome da Fábrica** (perfil separado em `data\navegador`, não é o seu Chrome
   normal). Entre na conta Google do canal. Se pedir para criar canal, crie. Quando aparecer o YouTube Studio,
   **feche a janela**. A Fábrica confere os cookies e diz "Login detectado".
2. `cortex login tiktok`: mesma coisa (entre na conta do TikTok, resolva o que pedir, feche a janela).
3. `cortex testar-publicacao`: abre a página de upload das duas redes **sem enviar nada** e mostra cada item conferido.
4. Teste completo sem publicar: `cortex revisar` e escolha "Publicação de TESTE" (ou `cortex cortar <link> --publicar auto --teste`).
   Ele envia o arquivo, preenche título, descrição e legenda, marca as opções e **para antes do botão Publicar**.
   - YouTube: o envio vira um rascunho; a Fábrica deixa **Privado**, fecha e tenta apagar esse rascunho de teste.
     Se não conseguir apagar, o log mostra o link `studio.youtube.com/video/<id>/edit` para você apagar.
   - TikTok: clica em "Descartar" (nada fica salvo).
5. Se algo falhar, veja os prints em `logs\screenshots\`. Depois disso, pode usar `--publicar auto`.

Se aparecer **"Feche a janela do navegador da Fábrica e tente de novo"**: há uma janela do Chrome da Fábrica aberta
(por exemplo a do login). Feche-a e rode de novo.

### Modo semi do TikTok (`publicacao.tiktok_modo: semi`)
A Fábrica faz tudo (envia o vídeo, escreve a legenda, escolhe as hashtags, ajusta a privacidade), traz a janela para a
frente e **espera você clicar em Publicar** (até `tiktok_espera_humano_s`, padrão 10 min). Ela nunca clica em Publicar
nem em "Publicar agora" nesse modo. Quando o TikTok confirma, ela pega o link. Se aparecer captcha depois do seu clique,
ela avisa e continua esperando você resolver (sem tocar no captcha). Se ninguém clicar a tempo, o vídeo não é publicado e o
TikTok é pausado no resto do lote (`ACAO_NECESSARIA`). Nesse modo a janela sempre abre visível, mesmo com `headless: true`.

---

## 2. Estratégia do navegador (por que assim)

| Momento | Como abre | Por quê |
|---|---|---|
| `login()` | `chrome.exe --user-data-dir=data\navegador` **puro** (subprocess, sem Playwright, sem porta de depuração) | O Google bloqueia login em navegador automatizado ("Este navegador ou app pode não ser seguro"). No Chrome 158 testado aqui, só ligar a porta de depuração já faz `navigator.webdriver = true`; por isso a janela de login é um Chrome 100% normal. O humano entra; detectamos o fim quando a janela fecha (limite de 10 min) e lemos nomes e validades dos cookies direto do SQLite do perfil (sem descriptografar). |
| publicar, testar, exportar cookies | o **mesmo** `chrome.exe` e o **mesmo** perfil, com `--remote-debugging-port=0`; o Playwright conecta via `connect_over_cdp(is_local=True, no_defaults=True)` | Mesmo binário, mesmo perfil e mesmas flags do login: sem `--enable-automation`, sem perfil temporário, sem as cerca de 20 flags padrão do Playwright (`--disable-sync`, `--disable-background-networking`...). A sessão criada pelo humano continua válida e os cookies que o Google e o TikTok renovam (ex.: `__Secure-*PSIDTS`) e as chaves de sessão vinculadas ao dispositivo ficam salvos no perfil. Se já houver uma janela da Fábrica aberta **com** porta de automação, ela é reaproveitada (e não é fechada no fim). |
| alternativa | `publicacao.modo_navegador: playwright`: `launch_persistent_context(data\navegador, channel=chrome/msedge)` | Use só se a política do PC bloquear a porta de depuração. |

Detalhes:
- **Não há camuflagem**: nada de plugins "stealth", não mudamos user-agent nem `navigator.webdriver`. A automação se
  apresenta como é. O ritmo "humano" (`human.py`: mouse em curva, hover, digitação pausada, espera de prontidão) imita uma
  pessoa, mas não torna a automação permitida pelos Termos (ver `docs/PUBLICACAO_SEGURA.md`).
- `is_local=True` é necessário: sem ele o Playwright recusa enviar arquivos acima de 50 MB pelo CDP (testado: 55 e 60 MB OK).
- **Perfil travado**: no Windows o Chrome segura `data\navegador\lockfile` sem compartilhamento; tentamos abri-lo em
  modo exclusivo (sem apagar nada). Em uso e sem porta de automação: `ProfileInUseError("Feche a janela do navegador da Fábrica e tente de novo.")`.
- `check_login(platform)`: cookies **presentes e não expirados** (pelo CDP se o navegador da Fábrica estiver aberto, senão pelo SQLite):
  - YouTube (domínio `youtube.com`): um de `SAPISID`, `__Secure-3PAPISID`, `__Secure-1PAPISID` **e** um de `__Secure-3PSID`, `__Secure-1PSID`, `SID`.
  - TikTok (`tiktok.com`): `sessionid`, `sessionid_ss` ou `sid_tt`.
  - Se o servidor encerrou a sessão mas o cookie ainda existe, o `check_login` dá True e o upload detecta a tela de
    login (`ACAO_NECESSARIA`). `check_login(..., deep=True)` também abre a página de upload sem janela para confirmar.
- `export_cookies_txt(cfg)`: grava `data\cookies.txt` (formato Netscape, com `#HttpOnly_`) com cookies de
  youtube.com, google.com, twitch.tv e tiktok.com (testado: o `YoutubeDLCookieJar` do yt-dlp lê o arquivo). Usa a sessão
  aberta, ou abre o Chrome **sem janela** por uns 6 s só para ler os cookies (o Chrome 127+ criptografa cookies vinculados
  ao próprio app, então só o Chrome consegue lê-los). Também é atualizado no fim de cada lote com YouTube.
- Antes de abrir, apaga só métricas antigas do Chrome (`BrowserMetrics\*.pma` com mais de 1 dia). Cache HTTP limitado a 100 MB.
- A porta de depuração escuta só em 127.0.0.1, com número aleatório, enquanto o lote roda; a Fábrica fecha o navegador
  que ela mesma abriu (`Browser.close`, com `taskkill` como último recurso).

---

## 3. Fluxo e seletores: YouTube Studio

URL: `https://www.youtube.com/upload` (redireciona para `studio.youtube.com/channel/UC.../videos/upload?d=ud`; deslogado
vai para `accounts.google.com/v3/signin/identifier`, **confirmado aqui**). O Studio usa Polymer com ShadyDOM: CSS
funciona; ids se repetem (`#textbox`, `#close-button`), então sempre com escopo do diálogo `ytcp-uploads-dialog` (= `D`).
Os hosts Polymer podem ter tamanho zero; para saber se estão visíveis olhamos o `tp-yt-paper-dialog` interno.

| Passo | Seletores (em ordem) | Texto en / pt-BR |
|---|---|---|
| Campo de arquivo | `D ytcp-uploads-file-picker input[type=file]`, `ytcp-uploads-file-picker input[type=file]`, `input[type=file][name=Filedata]`, `input[type=file]` | - |
| Botão selecionar | `#select-files-button`, role=button | "Select files" / "Selecionar arquivos" |
| Título | `D #title-textarea #textbox`, `#title-textarea #textbox`, `ytcp-social-suggestions-textbox#title-textarea #textbox`, `ytcp-video-title #textbox`, `div#textbox[contenteditable][aria-label*=title/título]` | - |
| Descrição | `D #description-textarea #textbox`, `#description-textarea #textbox`, `ytcp-video-description #textbox`, `div#textbox[aria-label*=viewers/espectadores]` | - |
| Não é para crianças | `tp-yt-paper-radio-button[name=VIDEO_MADE_FOR_KIDS_NOT_MFK]`, `[name=VIDEO_MADE_FOR_KIDS_NOT_MFK]`, `[name=NOT_MADE_FOR_KIDS]` (antigo), role=radio | "No, it's not made for kids" / "Não é conteúdo para crianças" |
| Mostrar mais, Conteúdo alterado: Não (opcional) | `D #toggle-button`; `tp-yt-paper-radio-button[name=VIDEO_HAS_ALTERED_CONTENT_NO]` | "Show more" / "Mostrar mais" |
| Próximo (3 vezes; 4 ou mais em canal monetizado) | `D #next-button`, `#next-button`, role=button | "Next" / "Próximo" ou "Próxima" |
| Adequação para anúncios (monetizado) | role=checkbox, role=button | "None of the above" / "Nenhuma das opções acima", "Submit rating" / "Enviar classificação" |
| Visibilidade | `D tp-yt-paper-radio-button[name=PUBLIC, UNLISTED ou PRIVATE]`, `#privacy-radios [name=...]`, role=radio | Public / Público, Unlisted / Não listado, Private / Privado |
| Publicar ou Salvar | `D #done-button`, `#done-button`, role=button (espera `aria-disabled` diferente de true) | Publish / Publicar, Save / Salvar |
| Fechar diálogo | `D #close-button`, `[aria-label="Save and close"]`, `[aria-label="Salvar e fechar"]` | - |
| Link do vídeo | `D ytcp-video-info a`, `ytcp-video-info a`, `a.ytcp-video-info`, `.video-url-fadeable a`, `a[href^="https://youtu.be/"]`, `a[href*="youtube.com/shorts/"]`, regex `(youtu.be/ ou /shorts/ ou v=)(11 caracteres)` | "Video link" / "Link do vídeo" |
| Progresso | `ytcp-video-upload-progress` (atributo `uploading`), `span.progress-label` | "Uploading 45%" / "Fazendo upload... 76%", "Upload complete", "Processing" / "Processando", "Checks complete" / "Verificações concluídas" |
| Depois de publicar | `ytcp-video-share-dialog`, `ytcp-uploads-still-processing-dialog`, `ytcp-prechecks-warning-dialog` ("Publish anyway" / "Publicar mesmo assim" ou `#secondary-action-button`); fechar com `#close-button` dentro deles | "Video published" / "Vídeo publicado" |
| Erros e avisos | `D .error-short`, `D .error-area`, `D #error-message`, `ytcp-confirmation-dialog` | "Daily upload limit reached" / "O limite diário de envios foi alcançado" |
| Sem canal | `#create-channel-button`, `ytd-channel-creation-dialog-renderer`, role=button | "Create channel" / "Criar canal" |
| Apagar rascunho de teste | `studio.../videos/short` e `/videos/upload`, depois `ytcp-video-row:has(a[href*=<id>])`, `#overflow-menu-button` ou role "Options" / "Opções", "Delete forever" / "Excluir permanentemente", `#confirm-checkbox`, `#confirm-button` | - |

Cuidados implementados: o título vem pré-preenchido com o nome do arquivo (espera estabilizar, Ctrl+A, apaga, digita;
confere o texto e tenta de novo com inserção direta); digitar `#` abre o autocompletar de hashtags (`tp-yt-iron-dropdown`)
que cobre os botões, então a descrição é inserida sem eventos por tecla e o dropdown é fechado com Esc **só se estiver
visível**; rádios do Polymer: clique e conferência de `aria-checked` (com `element.click()` de reserva); só publica depois
do envio chegar a 100% (fechar antes corta o upload); depois de Publicar exige evidência (diálogo "publicado" ou o botão
sumir por 4 leituras) antes de fechar a aba. Título com no máximo 100 caracteres, sem `<` e `>`; vídeo vertical de até 3 min
vira Short sozinho e a descrição leva `#Shorts`. URL final: `https://youtube.com/shorts/<id>`.

Bloqueios (`ACAO_NECESSARIA`): URL em `accounts.google.com` (login; `/challenge` = "Confirme que é você"),
`google.com/sorry` ou desafio reCAPTCHA (`iframe[src*=recaptcha][src*=bframe]`), conta sem canal, diálogo de verificação.
`LIMITE_DIARIO`: aviso de limite diário no diálogo de upload.

## 4. Fluxo e seletores: TikTok Studio

URL: `https://www.tiktok.com/tiktokstudio/upload?from=webapp` (deslogado vai para `/login?redirect_url=...&enter_from=tiktokstudio`,
título "Entrar | TikTok", **confirmado aqui**; a interface do perfil está em pt-BR). Não forçamos inglês
(`publicacao.tiktok_forcar_ingles: true` acrescenta `&lang=en` se o pt-BR quebrar algo). Em 2026 a página não usa mais
iframe; se o antigo `iframe[data-tt="Upload_index_iframe"]` existir, usamos ele.

| Passo | Seletores (em ordem) | Texto en / pt-BR |
|---|---|---|
| Campo de arquivo | `input[type=file][accept*=video]`, `input[type=file]` | - |
| Botão selecionar | role=button, `button[aria-label="Select file"]`, `.upload-text-container` | "Select video" / "Selecionar vídeo" |
| Legenda (Draft.js) | `div.public-DraftEditor-content[contenteditable=true]`, `.DraftEditor-root [contenteditable=true]`, `div[role=combobox][contenteditable=true]`, `[data-e2e=caption_container] [contenteditable]`, `div[contenteditable=true]` | - |
| Hashtags | digita `#tag` (70 ms por letra), espera o popover `div[class*=mention-list-popover]` ou `div[class*=hashtag-suggestion]` e clica no item **igual** (`span.hash-tag-topic`, `[class*=hash-tag-topic]`, `[role=option]`); sem sugestão, digita espaço. (Hoje Enter quebra linha em vez de escolher.) | - |
| Quem pode assistir | `[data-e2e=video_visibility_container] button[role=combobox]`, `... [role=combobox]`, `div[class*=view-auth-container] button`, role=combobox, `div.tiktok-select-selector` (antigo); opção `[role=option]` ou `div[class*=select-option]` pelo texto | Everyone / Todos, Friends / Amigos, Only you / Somente você |
| Comentários, Reutilização (Dueto e Costura) | label e o `input` irmão (só se `tiktok_permitir_*` estiver definido) | Comment / Comentários, Reuse of content / Reutilização de conteúdo, Duet / Dueto, Stitch / Costura |
| Pronto para publicar | `button[data-e2e=post_video_button]` com `data-disabled` e `aria-disabled` diferentes de true | - |
| Publicar (só no modo auto) | `button[data-e2e=post_video_button]`, role=button, `div.button-group button:has-text(Post ou Publicar)` | Post / Publicar |
| "Continuar publicando?" (só no modo auto) | `.TUXModal.common-modal-confirm-modal button.TUXButton--primary`, role=button | "Post now" / "Publicar agora" |
| Descartar (teste) | `button[data-e2e=discard_video_button]`, role=button, depois confirmar no `.TUXModal` | Discard / Descartar |
| Sucesso | URL `tiktokstudio/content`, ou aviso "Your video has been uploaded" / "Vídeo publicado" | - |
| Link | `div[data-tt=components_PostTable_Container] div[data-tt=components_PostInfoCell_Container] a`, regex `/video/(\d+)` (confere o texto da linha nos primeiros 15 s) | - |
| Avisos fechados | "Got it" / "Entendi", "Not now" / "Agora não", "Skip" / "Pular", tour `react-joyride`; modal "ativar verificações automáticas?" recebe **Cancelar** (não mudamos configurações da conta); banner de cookies: recusar opcionais | - |
| Verificação de conteúdo | `div[class*=status-result][data-show=true]` (`status-warn`, `status-error`, `status-limit` viram aviso no log) | - |

Bloqueios: URL `/login` ou `/signup`, ou modal de login: `ACAO_NECESSARIA` (login). Captcha (`.captcha-verify-container`,
`#captcha-verify-image`, `.captcha_verify_container`, `.secsdk-captcha-drag-icon`, `.captcha_verify_slide--slidebar`,
`#captcha_refresh_button`, `#tiktok-verify-ele`, "Drag the slider" / "Arraste o controle"): `ACAO_NECESSARIA` (a Fábrica
não resolve). Aviso em toast, alerta ou modal com "too fast", "muito rápido", "try again later", "tente novamente mais tarde"
ou "limite": `LIMITE_DIARIO`. "Something went wrong" / "Algo deu errado": falha comum (com print).

## 5. Texto dos posts (`captions.build_post_text`)

- **Emojis**: entram nos posts por padrão (`conteudo.emojis: true`). Com `conteudo.emojis: false`, todos saem (inclui
  sequências com ZWJ, tons de pele, bandeiras e keycaps). Mensagens de terminal e log **nunca** têm emoji.
- **Pontuação proibida** nos posts: travessão e meia-risca viram " - "; marcador no começo da linha vira "- "; ponto
  médio ou marcador no meio do texto vira ", "; reticências viram "...".
- **YouTube**: título = `plan.title` (sem `<` e `>`, no máximo 100 caracteres, com "(Parte X/Y)" no fim quando é série;
  tira "Parte N" que o cérebro já tenha posto). Descrição = gancho (se diferente do título) + descrição + "Série: ..." +
  `Fonte: <canal> - "<título do vídeo>"` (se `creditar_fonte`) + `descricao_rodape` + hashtags (do plano + `hashtags_fixas`,
  sem repetir, no máximo `max_hashtags`) + `#Shorts`. No máximo 5000 caracteres.
- **TikTok**: legenda = título (com Parte X/Y) + "Fonte: canal" + hashtags (sem #Shorts), no máximo 2200 caracteres.
  O rodapé só entra com `tiktok_rodape: true`.
- Canal e título de origem vêm da tabela `videos` do banco (`captions.source_info`).

## 6. `publish_batch` (comportamento)

Uma sessão de navegador **por corte** (todas as redes dele), fechada no fim. Para cada corte e rede: pula se
`db.already_posted`, se repetido na lista ou se já houve clique em Publicar (`guard.py`); respeita `max_posts_por_dia` e, como
segunda trava, `policy.can_post` (aquecimento, limite, intervalo mínimo) antes de abrir o navegador e antes de cada post
(fora do modo teste); espera aleatória de `intervalo_entre_posts_s` entre posts da mesma rede, com o navegador fechado;
cada resultado vai para `db.save_post`. Captcha, verificação ou `LIMITE_DIARIO` pausa a rede por `pausa_apos_bloqueio_h`
(padrão 24 h, vale também para o teste) ou até `cortex login <rede>`; outro `ACAO_NECESSARIA` pausa só o lote. Os cortes que
ficaram para trás não geram resultado. Só uma publicação por vez no PC. Falha ao abrir o navegador: um resultado por rede
com o motivo. Clique em Publicar sem confirmação: `ok=True` com erro `INCERTO: ...` (o pipeline trata como publicado e pode
liberar o vídeo do PC; ver `docs/PUBLICACAO_SEGURA.md`). Prints de erro em `logs\screenshots\`.

## 7. Chaves do `config.yaml` usadas pelo publicador (seção `publicacao`, mais `conteudo.emojis`)

Já existentes: `plataformas`, `navegador`, `headless`, `intervalo_entre_posts_s`, `max_posts_por_dia`,
`youtube_visibilidade`, `tiktok_visibilidade`, `hashtags_fixas` (padrão `[]`), `max_hashtags` (padrão 5),
`descricao_rodape`, `creditar_fonte`, `tiktok_modo` (`auto` ou `semi`), `conteudo.emojis` (padrão true).

Novas (todas opcionais):

| Chave | Padrão | Para quê |
|---|---|---|
| `modo_navegador` | `cdp` | `cdp` (Chrome real + connect_over_cdp) ou `playwright` (launch_persistent_context) |
| `login_timeout_s` | `600` | quanto o `login()` espera você fechar a janela |
| `timeout_upload_s` | `900` | tempo máximo de envio e processamento de um vídeo |
| `intervalo_teste_s` | `[5, 15]` | intervalo entre envios no modo teste |
| `tiktok_espera_humano_s` | `600` | no modo semi, quanto esperar você clicar em Publicar |
| `youtube_conteudo_alterado` | `false` | resposta de "Conteúdo alterado ou sintético" (false = "Não") |
| `teste_apagar_rascunho` | `true` | modo teste do YouTube apaga o rascunho privado criado |
| `tiktok_forcar_ingles` | `false` | abre o TikTok Studio com `lang=en` |
| `tiktok_permitir_comentarios` | (não mexe) | `true` ou `false` força a opção "Comentários" |
| `tiktok_permitir_reuso` | (não mexe) | `true` ou `false` força "Reutilização de conteúdo" (Dueto e Costura) |
| `tiktok_rodape` | `false` | põe `descricao_rodape` também na legenda do TikTok |
| `exportar_cookies` | `true` | atualiza `data\cookies.txt` no fim de cada lote com YouTube |
| `cookies_dominios` | youtube.com, google.com, twitch.tv, tiktok.com | domínios exportados para o cookies.txt |
| `pausa_apos_bloqueio_h` | `24` | horas de pausa da rede depois de captcha, verificação ou limite |
| `humano.*` | ver `docs/PUBLICACAO_SEGURA.md` | ritmo humano (pausas, mouse, digitação, aquecimento) |
| `cache_navegador_mb` | `100` | limite do cache HTTP do perfil |
| `args_navegador` | `[]` | flags extras do Chrome (avançado) |

## 8. O que foi verificado e o que depende do login

Verificado nesta máquina (Chrome 158, sem login; `tests/publish_smoke.py` passa): abertura do Chrome real pelo CDP e
pelo modo login puro; detecção de perfil travado (sessão, lote, export, selftest, login); `login()` percebe a janela
fechada; reaproveitamento de janela já aberta; redirecionamento para login nas duas redes; `check_login` = False (CDP e
SQLite); `upload()`, `publish_batch` e `selftest` devolvem `ACAO_NECESSARIA: faça login...`; envio de arquivo de 55 a 60 MB;
cookies.txt lido pelo yt-dlp; textos dos posts (emojis ligados e desligados, pontuação, limites).

Verificado logado em 23 nov 2026 (janela fora da tela, sem publicar): selftest das duas redes; YouTube até a etapa
Visibilidade, fechar o diálogo e apagar o rascunho de teste. A interface das duas contas está em **pt-PT** ("Guardar",
"Eliminar definitivamente", "Só tu", "Entendido").

**Não verificado:** o clique final em Publicar e a confirmação nas duas redes, leitura do link do TikTok, modo semi.

## 9. Riscos

- **Captcha e verificação**: o TikTok desafia mais navegadores com automação (com a porta de depuração ligada, o Chrome
  informa `navigator.webdriver=true`; não escondemos isso). A Fábrica para e pede ação; se acontecer sempre, publique menos
  ou use `tiktok_modo: semi`.
- **Limites diários**: o YouTube limita envios por dia (contas novas ou não verificadas têm limite menor); o TikTok limita
  frequência. Comece com poucos posts e intervalos longos (o `aquecimento` do config ajuda).
- **Sinalização da conta e direitos autorais**: cortes de terceiros podem gerar reivindicação do Content ID, restrição no
  TikTok ou strike. `creditar_fonte` ajuda, mas não substitui permissão do dono do conteúdo.
- **Mudanças de interface**: o Studio e o TikTok mudam o HTML com frequência; cada falha salva um print e o seletor que
  falhou vai para o log. Atualize as listas `SEL` em `youtube.py` e `tiktok.py`.
- **cookies.txt** contém a sessão da conta: não compartilhe. O yt-dlp avisa que usar conta logada para baixar em massa
  pode marcar a conta; use o cookies.txt só quando o YouTube pedir "confirme que não é um robô".
- Enquanto um lote roda, a porta de depuração local (127.0.0.1, número aleatório) dá controle do navegador a programas
  do próprio PC. Ela fecha junto com o navegador no fim do lote.
