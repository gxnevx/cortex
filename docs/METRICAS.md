# Métricas, saúde das contas e aprendizado (CORTEX)

Módulos: `fabrica/metrics.py` e `fabrica/learning.py`. Base da pesquisa: `docs/ideias/algoritmo_e_riscos.md`
(seções 1.5 e 7) e `docs/ideias/estrategia_conteudo.md` (seção 4.3, afinidade).

Tudo é leitura PÚBLICA: o yt-dlp abre a URL pública do post, sem login, sem chave de API e sem os cookies
do dono (a não ser que `metricas.usar_cookies: true`). Nenhuma função levanta exceção para quem chama.

## API (assinaturas estáveis)

```python
from fabrica import metrics, learning

metrics.collect(cfg, max_items=30) -> dict
    # Lê os posts (ok=1, dry_run=0) com checkpoint vencido: T+2h, T+24h, T+72h, T+7d.
    # 1 chamada do yt-dlp por item, no máximo metricas.tempo_max_s (60 s) por rodada.
    # Retorna {"ok", "devidos", "lidos", "problemas", "falhas", "bloqueados", "pulados",
    #          "tempo_s", "saude": {rede: nivel}, "mensagens": [str pt-BR, sem emoji]}

metrics.account_health(platform, cfg) -> dict
    # {"ok": bool, "motivo": str, "pausar_ate": ts | None, "nivel": "normal" | "atencao" | "pausa",
    #  "atencao_ate": ts | None, "mudou": bool, "posts_avaliados": int, "rede": str}
    # ok = False só quando nivel == "pausa". "mudou" = o nível mudou nesta avaliação (para notificar 1 vez).
    # Cache de 60 s em memória (barato para chamar no policy a cada decisão).

metrics.volume_factor(platform, cfg) -> float      # 1.0 normal, 0.5 atencao, 0.0 pausa (erro -> 1.0)
metrics.summary_rows(cfg, limit=30, dias=7) -> list[dict]
    # cada linha: titulo, rede, idade, views, likes, situacao (textos prontos para tabela)
    # + url, post_id, views_n, likes_n, views_24h, idade_h (números crus)
metrics.record_reading(post_id, views, likes=None, comments=None, shares=None,
                       status="ok", fonte="externo", ts=None, cfg=None) -> bool
    # grava uma leitura vinda de outra fonte (ex.: o publicador lendo o painel do TikTok Studio)
metrics.resume(platform) -> None                   # retomada manual (tira pausa e atenção)

learning.weights(cfg, force=False) -> dict
    # {"categoria": {"politica": 1.12, ...}, "layout": {"full": 1.08, ...}, "hora": {"18-21": 1.1, ...},
    #  "canal": {...}, "dia_semana": {"seg": ...}, "duracao": {"35-45s": ...}, "emojis_titulo": {"0"|"1"|"2+"},
    #  "estilo_titulo": {"pergunta"|"exclamacao"|"caixa_alta"|"neutro"}, "serie": {"serie"|"avulso"},
    #  "n_posts": int, "suficiente": bool, "atualizado": ts, "metodo": "thompson_beta", "medianas": {rede: views}}
    # Valor ausente = 1.0. Todos os pesos ficam em [0.7, 1.3].
learning.weight_for(cfg, dim, value) -> float     # atalho; normaliza acento e caixa ("Política" -> "politica")
learning.insights(cfg) -> list[str]               # frases pt-BR; antes de 20 posts avisa que falta dado
learning.hour_bucket(hour) -> str                 # "00-06", "06-09", "09-12", "12-15", "15-18", "18-21", "21-24"
learning.duration_bucket(seconds) -> str | None   # "ate 25s", "25-35s", "35-45s", "45-60s", "acima de 60s"
```

## Tabelas novas (criadas pelo próprio `metrics.py` com CREATE TABLE IF NOT EXISTS)

- `post_metrics(id, post_id, clip_id, platform, ts, idade_h, checkpoint, views, likes, comments, shares,
  status, detalhe, fonte, url)`: uma linha por leitura. `checkpoint` = "2h" | "24h" | "72h" | "7d" (ou NULL
  para leitura extra). `status` = ok | removido | privado | restrito | direitos | violacao. Falhas de leitura
  (rede bloqueou, erro, link não achado) NÃO viram linha aqui.
- `post_links(post_id, clip_id, platform, url, video_id, canal, upload_ts, metodo, tentativas,
  proxima_tentativa, ultimo_erro, atualizado)`: URL resolvida do vídeo (metodo = post | perfil) e controle
  de novas tentativas (espera 45 min, 90, 180, 360; teto 6 h).

A tabela `posts` não é alterada.

## Arquivos de estado (data/estado)

- `saude_contas.json`: por rede, `pausar_ate`, `atencao_ate`, motivos, gatilhos já usados (para o mesmo
  conjunto de posts não disparar de novo) e histórico dos últimos 30 eventos.
- `aprendizado.json`: pesos, detalhes por grupo (n, razão mediana, taxa de sucesso) e insights. Recalcula
  quando entra leitura nova ou a cada 6 h.
- `metricas_estado.json`: `bloqueio_ate` por rede (quando a rede bloqueia a leitura, espera 6 h) e
  `ultima_coleta`.

## Checkpoints e resolução de link

- Para cada post vencido, lê o MAIOR checkpoint já alcançado e ainda não lido. Checkpoint atrasado demais
  (idade > 2,5 x checkpoint + 1 h) é pulado e espera o próximo; nada é lido depois de 1,5 x 7 dias.
- Prioridade quando há fila: 24h (alarmes), 72h (aprendizado), 2h, 7d.
- YouTube: a URL salva é `https://youtube.com/shorts/<id>`; usamos o cliente leve do yt-dlp (cerca de 3 s por
  vídeo) e confirmamos "indisponível" com o cliente padrão antes de registrar remoção.
- Sem URL de vídeo (TikTok às vezes só guarda a página do Studio ou do perfil): lista os últimos vídeos do
  perfil (`metricas.perfis.<rede>`, ou o @ tirado da URL do post, ou o canal lido em posts anteriores) e casa
  por horário (mais ou menos 15 min) e legenda (título do corte). No YouTube a listagem não traz horário, então
  casa pelo título e confere o horário na leitura do vídeo. A URL achada fica em `post_links.url`.

## Regras de saúde (avaliadas a cada `account_health`)

| Regra | Efeito |
|---|---|
| 3 posts seguidos com menos de 10 views em 24 h | PAUSA 72 h, depois 120 h em atenção (volume pela metade) |
| Post removido, indisponível, privado, restrito (idade, não listado) ou com aviso de direitos | ATENÇÃO 72 h |
| 2 ou mais posts com problema em 7 dias | PAUSA 72 h |
| Últimos 5 posts abaixo de 20% da mediana da própria conta (com pelo menos 5 posts de base) | ATENÇÃO 72 h |
| A partir do dia 15 da conta: 5 posts seguidos abaixo de 200 (TikTok) / 150 (YouTube) views em 24 h | ATENÇÃO 72 h |
| Nova atenção quando a atenção já dura um ciclo inteiro | PAUSA 72 h |

"Views em 24 h" = leitura ok com idade entre 20 h e 96 h mais próxima de 24 h.

## Aprendizado

- Métrica: views em 24 h dividido pela mediana da própria conta naquela rede (funciona em conta pequena e
  compara YouTube com TikTok). Sucesso = acima da mediana.
- Dimensões: categoria, canal-fonte, layout, faixa de horário, dia da semana, faixa de duração, emojis no
  título, estilo do título, série ou avulso.
- Bandit Thompson Beta(1,1) com meia-vida de 14 dias. Peso = 75% média da posterior + 25% amostra (exploração),
  mapeado em [0.7, 1.3] e encolhido para 1.0 quando há poucos posts (n_ef / (n_ef + 5)). Antes de 10 posts
  com leitura de 24 h todos os pesos são 1.0.
- Insights só a partir de 20 posts com leitura de 24 h; cada grupo precisa de 3 posts e a diferença entre
  o melhor e o pior precisa ser de pelo menos 1,25x.

## Chaves de config (todas opcionais; padrão entre parênteses)

```yaml
metricas:
  ativo: true
  checkpoints_h: [2, 24, 72, 168]
  tempo_max_s: 60            # orçamento por collect()
  timeout_item_s: 25         # por chamada do yt-dlp
  timeout_rede_s: 15         # socket_timeout do yt-dlp
  reintentar_min: 45         # espera depois de uma falha (dobra até 6 h)
  pausa_bloqueio_h: 6        # rede bloqueou a leitura: espera isso antes de tentar de novo
  usar_cookies: false        # true = usa data/cookies.txt (leitura deixa de ser anônima)
  tolerancia_match_min: 15
  itens_perfil: 12
  perfis: {youtube: "", tiktok: ""}   # ex.: "@minhaconta" (usado quando o post não tem link do vídeo)
  saude:
    ativo: true
    cache_s: 60
    views_quase_zero: 10
    posts_seguidos_quase_zero: 3
    pausa_h: 72
    atencao_h: 72
    atencao_pos_pausa_h: 120
    atencao_vira_pausa: true
    fator_atencao: 0.5
    problemas_7d_para_pausa: 2
    queda_ultimos: 5
    queda_fracao_mediana: 0.20
    queda_base_min: 5
    views_24h_baixo: {tiktok: 200, youtube: 150}
    baixo_a_partir_do_dia: 15
    posts_seguidos_baixo: 5
  aprendizado:
    janela_dias: 60
    meia_vida_dias: 14
    prior: [1, 1]
    explorar_frac: 0.25
    ganho: 1.2
    encolher_k: 5
    peso_min: 0.7
    peso_max: 1.3
    min_posts_pesos: 10
    min_posts_insights: 20
    min_posts_grupo: 3
    max_insights: 8
    cache_min: 360
```

## Integração (feita pelo orquestrador)

- `autopilot`: chamar `metrics.collect(cfg)` a cada cerca de 30 min (fora de uma sessão de upload). Mostrar
  `res["mensagens"]` e, quando `account_health(...)["mudou"]` e o nível não for normal, notificar o dono.
- `policy.daily_limit`: multiplicar o limite por `metrics.volume_factor(platform, cfg)` (arredondar para baixo,
  mínimo 1 quando o fator for maior que 0). `policy.can_post`: se `account_health(...)["nivel"] == "pausa"`,
  devolver `(False, "pausa de saúde até HH:MM: <motivo>")`.
- Cérebro / autopiloto: multiplicar a nota do corte por `learning.weight_for(cfg, "categoria", plan.category)`,
  `weight_for(cfg, "layout", layout)` e, na escolha do horário, por `weight_for(cfg, "hora", hora)`.
  `learning.insights(cfg)` pode ir no prompt do `pick_clips`/`rank_trends` e no relatório.
- CLI/relatório: `metrics.summary_rows(cfg)` para a tabela "Como foram os posts"; um comando `retomar <rede>`
  chama `metrics.resume(rede)`.

## Limitação conhecida (23/11/2026)

O TikTok devolve uma página de desafio anti-robô ("Please wait...") para clientes que não são navegador, e o
yt-dlp desta máquina falha com "Unexpected response from webpage request" (ele avisa que a dependência opcional
de "impersonation" não está instalada). Resultado: a leitura pública do TikTok não funciona daqui; o módulo
registra "bloqueado", espera 6 h e tenta de novo, e a saúde da conta do TikTok fica em "normal" por falta de
leitura (não pausa por engano). O YouTube Shorts funciona (views, likes e comentários). Para o TikTok, a
alternativa oficial é o painel do TikTok Studio lido pelo publicador e gravado com `metrics.record_reading`.

## Testes

- `tests/metricas_unit.py`: sem rede, banco temporário. Checkpoints, classificação de erros, `collect` com
  extrator falso (link, perfil, removido, bloqueio), regras de saúde, bandit e insights.
- `tests/metricas_rede.py`: com rede, banco temporário, posts falsos apontando para Shorts e TikToks públicos
  do Podpah.
