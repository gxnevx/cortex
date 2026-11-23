# Legendas queimadas: precisao do Whisper e traducao (modulos `fabrica/transcribe.py` e `fabrica/translate.py`)

Este documento registra a avaliacao feita em nov/2026 nesta maquina (CPU de notebook, sem NVIDIA,
faster-whisper 1.2.1 em CPU int8, `cpu_threads` 6) e as escolhas padrao que o codigo implementa.

## 1. Como foi medido

- **Referencia (verdade)**: legendas MANUAIS em portugues do YouTube (`writesubtitles`, nunca a
  automatica). Muitos canais (Achismos, Podcast 3 Irmaos, DebateCast, Rodrigo Pimentel) publicam como
  "manual" uma copia do ASR do YouTube (mascara `[ __ ]`, `&nbsp;`, texto 91 a 100% igual ao automatico):
  esses foram descartados. Ficaram 4 videos com legenda feita por pessoa:

  | video | tipo | trecho |
  |---|---|---|
  | `V7R4idWK518` | podcast (Eu Nao Mordo, JuvTV), conversa com convidada | 56 s |
  | `CxCD0XZJyPM` | podcast (Emicida entrevista Sergio Vaz, Nubank) | 59 s |
  | `tH-Nuqm8zms` | entrevista/debate de TV de 1994 (Eneas no Roda Viva), audio antigo | 60 s |
  | `YTlQ_2SaQmM` | esquete com dialogo rapido e varias vozes (Porta dos Fundos) | 45 s |

  A legenda do Roda Viva e uma transcricao "limpa" (troca "to" por "estou", corta interrupcoes, tem
  acentos quebrados no arquivo, tratados como coringa): o WER desse video e alto para todos os modelos,
  serve para comparar, nao como valor absoluto.
- **Trecho**: 45 a 60 s comecando e terminando em limites de bloco da legenda manual; audio da melhor
  faixa m4a do YouTube (como no corte final), recortado com ffmpeg.
- **WER normalizado**: minusculas, sem pontuacao, sem anotacoes (`[risos]`, `(musica)`, "Fulano: "),
  numeros por extenso (10 = dez, 100% = cem por cento, R$ 10 = dez reais), formas faladas equivalentes
  (pra = para, ta = esta, to = estou, ce = voce), sem hesitacoes (ah, eh, hum). WER = (S + D + I) / N
  somando os 4 videos.
- **Velocidade (RTF)**: tempo de transcricao / duracao do trecho, com o modelo ja carregado (carga:
  small 3 s, turbo 6 s, so na primeira vez por execucao).
- **Sincronia das palavras (karaoke)**: inicio de cada palavra comparado com o ASR do YouTube (que tem
  tempo por palavra). Dois videos tem um atraso CONSTANTE de ~0,4 s no ASR do YouTube (confirmado pelo
  inicio de fala medido na energia do audio), por isso a tabela mostra o erro sem esse atraso constante:
  `jit_med` (mediana do erro, s), `jit>250ms` (fracao de palavras com erro acima de 250 ms) e `deriva`
  (diferenca do erro entre o primeiro e o ultimo terco do trecho; perto de 0 = nao escorrega).

Script: `tests/legendas_avaliacao.py` (`preparar`, `rodar <modelo> <variantes>`, `tabela --md`,
`limpar`). Antes de cada job pesado ele espera nao haver outro `ffmpeg.exe` rodando.

## 2. Resultados

Total dos 4 trechos (660 palavras de referencia). `base` = como o pipeline estava (VAD 500/300 ms, sem
prompt). `prompt_ini` = `initial_prompt`; `hotwords` = parametro `hotwords`; `cond_prev` = prompt +
`condition_on_previous_text=True`; `beam1` = beam 1; `temp0` = sem fallback de temperatura; `sem_vad` = VAD
desligado; `vad_fino` = prompt + VAD sensivel (`threshold` 0,35, silencio 300 ms, margem 400 ms);
`best` = padrao final do `transcribe()` (igual a `vad_fino` no turbo); `best_tempo_cru` = `best` sem o
ajuste de tempo por palavra. RTF medido com outros agentes usando a CPU ao mesmo tempo (varia ~30%).

| modelo | variante | WER | RTF | Emicida | JuvTV | Porta | Roda Viva | jit_med (s) | jit>250ms | deriva (s) |
|---|---|---|---|---|---|---|---|---|---|---|
| small | base (antes) | 16,1% | 0,27 | 12,5% | 9,0% | 19,3% | 21,7% | 0,059 | 11,2% | 0,040 |
| small | prompt_ini | 14,7% | 0,30 | 9,4% | 12,3% | 15,7% | 20,7% | 0,061 | 11,5% | 0,028 |
| small | hotwords | 15,5% | 0,33 | 11,5% | 12,3% | 15,7% | 21,2% | 0,060 | 11,5% | 0,032 |
| small | cond_prev | 15,5% | 0,32 | 10,9% | 13,1% | 15,0% | 21,7% | 0,059 | 11,1% | 0,036 |
| small | beam1 | 15,3% | 0,21 | 10,9% | 10,7% | 15,0% | 22,7% | 0,055 | 11,8% | 0,045 |
| small | sem_vad | 16,1% | 0,32 | 10,4% | 16,4% | 18,6% | 19,7% | 0,062 | 11,6% | 0,043 |
| small | vad_fino | 17,5% | 0,39 | 10,4% | 14,8% | 24,3% | 21,2% | 0,059 | 11,5% | 0,048 |
| medium | vad_fino sem prompt | 14,6% | 0,78 | 10,9% | 12,3% | 21,4% | 14,6% | 0,061 | 11,8% | 0,031 |
| medium | vad_fino | 12,3% | 0,84 | 8,8% | 9,0% | 16,4% | 14,6% | 0,057 | 11,9% | 0,034 |
| large-v3-turbo | base | 12,1% | 0,55 | 10,9% | 10,7% | 12,9% | 13,6% | 0,052 | 10,0% | 0,034 |
| large-v3-turbo | prompt_ini | 11,3% | 0,44 | 7,3% | 11,5% | 14,3% | 13,1% | 0,051 | 8,9% | 0,028 |
| large-v3-turbo | hotwords | **16,0%** | 0,64 | **23,4%** | 11,5% | 14,3% | 12,6% | 0,050 | 9,3% | 0,030 |
| large-v3-turbo | ini+hot | 11,5% | 0,58 | 8,3% | 11,5% | 13,6% | 13,1% | 0,050 | 9,5% | 0,026 |
| large-v3-turbo | cond_prev | 12,1% | 0,50 | 10,4% | 11,5% | 13,6% | 13,1% | 0,050 | 8,8% | 0,030 |
| large-v3-turbo | beam1 | 12,0% | 0,36 | 8,3% | 12,3% | 15,0% | 13,1% | 0,052 | 11,2% | 0,033 |
| large-v3-turbo | temp0 | 11,3% | 0,51 | 7,3% | 11,5% | 14,3% | 13,1% | 0,051 | 8,9% | 0,028 |
| large-v3-turbo | sem_vad | 10,9% | 0,52 | 7,8% | 7,4% | 15,7% | 12,6% | 0,050 | 9,3% | 0,036 |
| large-v3-turbo | **vad_fino = best (padrao)** | **10,9%** | 0,41 a 0,61 | 7,8% | 7,4% | 15,0% | 13,1% | 0,049 | 10,4% | 0,039 |
| large-v3-turbo | best_tempo_cru | 10,9% | 0,47 | 7,8% | 7,4% | 15,0% | 13,1% | 0,049 | 10,4% | 0,038 |

Outras medicoes:
- **Prompt sem pontuacao piora**: a primeira versao limpava o prompt tirando os pontos (vinha "titulo,
  canal, nome, nome"). Com ele o turbo deu 12,4% (Emicida 10,4%) e a legenda saiu quase sem virgula; com
  o prompt em frases ("Titulo. Canal. Nome, Nome.") deu 10,9%. O small com `hotwords` sem pontuacao chegou
  a 46,7% no JuvTV (pulou o fim do trecho).
- **Sincronia contra o inicio real da fala** (energia do audio, palavras depois de pausa): o turbo marca
  o inicio 0,10 a 0,16 s ANTES da fala (bom para karaoke: a palavra acende junto com o som); o ASR do
  YouTube e que esta ~0,3 s atrasado nos 2 videos com atraso constante.
- **Ajuste de tempo do karaoke** (`_fix_word_timing`): com o turbo quase nao muda nada (palavra
  "esticada" depois de pausa e rara); fica como rede de seguranca, agora so para casos gritantes
  (palavra curta com mais de 1,2 s e 3x a duracao esperada).
- **Determinismo**: o turbo deu exatamente o mesmo texto em duas execucoes; o small variou ate 8 pontos
  num video entre execucoes iguais (fallback de temperatura).
- **Tempo real no pipeline**: com o modelo carregando junto (7 s na 1a vez) e deteccao de idioma, um
  trecho de 30 a 40 s levou 32 a 45 s (RTF ~1,0); com o modelo ja carregado, RTF 0,4 a 0,7. Teto pedido: 1,5.

## 3. Padroes escolhidos

Legenda final do corte (trecho curto com `start`/`end`, ate `transcricao.legenda_max_s` = 150 s):

| item | padrao | motivo |
|---|---|---|
| modelo | `large-v3-turbo` (`transcricao.modelo_legenda`) | WER bem menor que o small (acerta nomes e palavras dificeis: "aquisitivo", "fragorosamente", "ponei"), RTF ~0,5: um corte de 60 s legenda em ~30 s (limite pedido: 1,5x) |
| modelo do video longo | `small` (`transcricao.modelo_whisper`) | so serve para achar momentos; RTF ~0,25 |
| medium | descartado (apagado) | mais lento que o turbo (RTF ~0,8) e nao melhor |
| prompt | `initial_prompt` = titulo + canal + nomes da descricao (`build_prompt`) | 12,1% -> 11,3% no turbo; o Whisper imita o estilo do prompt, entao ele vai em frases com ponto e virgula (titulo EM CAIXA ALTA vira frase normal, hashtag/URL/emoji saem) |
| `hotwords` | NAO usar | no turbo pulou frases inteiras num podcast (7,3% -> 23,4%) |
| VAD | ligado; no turbo `threshold` 0,35, `min_silence_duration_ms` 300, `speech_pad_ms` 400 | VAD padrao (0,5) cortava a voz mais baixa da convidada (JuvTV: 11,5% -> 7,4%); no small o VAD sensivel piorou, entao modelo pequeno usa 500/300 ms |
| `condition_on_previous_text` | False | igual ou melhor e sem lacos de repeticao |
| beam | 5 | beam 1 e ~25% mais rapido, mas instavel (small com beam 1 perdeu 98 palavras num video) |
| temperatura | fallback [0; 0,2; 0,4; 0,6] | igual ao 0 fixo nos testes, protege contra lacos |
| threads | ate 6 (`transcricao.threads`, 0 = automatico, nunca mais que 6) | regra da maquina (evita saturar a CPU) |

Pos-processamento (sempre, em `postprocess_tokens` + `_fix_word_timing`):
- remove frases inventadas pelo Whisper ("Legendas pela comunidade Amara.org", "legendado por",
  "subtitles by"...; "obrigado por assistir", "inscreva-se", "www." so quando o segmento tem baixa
  confianca) e o eco do proprio prompt (titulo repetido em silencio/musica);
- pontuacao solta vai para a palavra anterior, "-Fala" vira "Fala", travessao e bolinha nunca aparecem;
- laco de repeticao: palavra repetida 5+ vezes fica 3; frase repetida 3+ vezes fica 2;
- numeros: "10 000" -> "10.000", "1,000,000" -> "1.000.000", "50 %" -> "50%";
- tempo por palavra: sem sobreposicao, palavra no maximo 1,6 s, e a primeira palavra depois de uma
  pausa que "engoliu" o silencio (duracao longa para o tamanho) tem o inicio puxado para perto da fala.

Sincronia (karaoke): erro mediano de ~0,05 s por palavra contra o ASR do YouTube, ~10% das palavras com
mais de 250 ms e deriva desprezivel (< 0,1 s do inicio ao fim do trecho): nao escorrega.

Com 4 trechos (~660 palavras), diferencas de 1 ponto entre variantes do turbo sao ruido; a diferenca
small -> turbo (16,1% -> 10,9%, cerca de 1 erro a menos a cada 19 palavras) aparece nos 4 videos
(12,5 -> 7,8; 9,0 -> 7,4; 19,3 -> 15,0; 21,7 -> 13,1) e e maior no audio dificil (TV de 1994).

Se o turbo nao puder ser carregado (sem disco/rede), `transcribe()` cai para `transcricao.modelo_whisper`
com aviso no log. `transcribe.unload_models()` libera os modelos da RAM (turbo ~1 GB).

## 4. Traducao (videos estrangeiros)

`fabrica/translate.py`:

```python
detect_language(transcript_or_media, cfg=None, start=None, end=None) -> str   # "pt", "en", "es"...
to_portuguese(transcript, cfg, context="") -> Transcript | None
translate_text(text, cfg, target="pt") -> str                                 # "" se nao der
```

- **Idioma**: `transcribe(..., language=None)` detecta e grava em `Transcript.language`. Para midia:
  `detect_language(path)` usa o faster-whisper (modelo de selecao, ate 90 s). Para legenda de
  plataforma, confere o idioma do arquivo com um palpite pelo vocabulario (pt/en/es).
- **Motor**: `traducao.motor` = `ollama` (padrao, local e gratis; `cerebro.ollama_modelo` =
  qwen3:4b-instruct, `num_thread` 6, temperatura 0,2). O Claude so entra com `traducao.motor: claude`
  (ou `auto`), ou se o Ollama estiver fora E `traducao.permitir_claude: true` (padrao false: o Claude
  gasta a cota da assinatura do dono). Uma requisicao por vez (trava global).
- **Como traduz**: lotes de ~1100 caracteres (`traducao.lote_caracteres`) com ids em JSON, saida
  estruturada (JSON schema no Ollama), validacao (todo id volta, texto nao vazio, tamanho plausivel,
  nao copiou o ingles), nova tentativa so dos ids que faltaram e, por fim, trecho a trecho. Se ainda
  faltar algum trecho, devolve None e o pipeline pula o corte estrangeiro.
- **Tempo por palavra**: cada segmento traduzido mantem `start`/`end`; as palavras em portugues sao
  espalhadas pelo tempo de FALA do segmento original (as pausas entre as palavras originais ficam sem
  palavra), proporcional ao tamanho de cada palavra. O karaoke continua funcionando.
- **Estilo**: portugues do Brasil falado, girias quando combinam, palavrao com o mesmo peso (fuck =
  porra/caralho), nomes de pessoas/marcas/jogos como estao, frases curtas.

Teste real (`tests/legendas_traducao.py <url> <inicio> <duracao>`), Ollama qwen3:4b-instruct:

| clipe | Whisper (turbo, idioma auto) | traducao (Ollama) | resultado |
|---|---|---|---|
| Bill Burr no Joe Rogan (JRE Clips), 40 s, ingles | 45 s (com carga do modelo), idioma `en` | 50 a 73 s, 10 trechos | 152 palavras PT, sem sobreposicao |
| Ibai, compilado de clipes da Twitch, 30 s, espanhol | 32 s, idioma `es` | 24 s, 10 trechos | 42 palavras PT |

Exemplos (original -> legenda):
- "I was always doing side jobs." -> "Eu sempre fazia bicos."
- "And this Irish guy kept going, Billy, you must work quicker." -> "E esse cara irlandes so repetia,
  Billy, voce precisa trabalhar mais rapido."
- "...if you want me to fucking go quicker ... and he finally shut the fuck" -> "...e ele finalmente cala a
  porra da boca"
- "Hostia, hijoputa!" -> "Que porra do caralho!"; "Es asi una llamita de mierda." -> "E assim uma chamita de merda."

Limitacoes do modelo local de 4B: as vezes some com um "fucking" de enfase (apesar da regra) ou deixa
uma expressao literal ("Que te he parido"); erros do Whisper (gameplay alto, girias espanholas) passam
para a traducao. O Claude traduz melhor, mas so entra se o dono ligar (`traducao.motor: claude` ou
`traducao.permitir_claude: true`). Tempo total por corte estrangeiro de ~40 s: ~1,5 a 2 min.

## 5. Chaves de configuracao (lidas com `cfg.get`, todas opcionais)

```yaml
transcricao:
  modelo_whisper: small            # video longo (achar momentos)
  modelo_legenda: large-v3-turbo   # legenda final do corte (1,6 GB em data/modelos, ja baixado)
  legenda_max_s: 150               # trecho com start/end ate isso usa modelo_legenda
  usar_prompt: true                # initial_prompt com titulo/canal/nomes
  threads: 0                       # 0 = automatico (nunca mais que 6)
  beam_size: 5
traducao:
  motor: ollama                    # ollama (padrao) | claude | auto
  permitir_claude: false           # Claude so se o Ollama cair E isto for true
  ollama_modelo: ""                # vazio = cerebro.ollama_modelo
  lote_caracteres: 1100
  temperatura: 0.2
```

Testes: `tests/legendas_unit.py` (rapido, sem rede/IA), `tests/legendas_avaliacao.py` (WER/RTF),
`tests/legendas_traducao.py` (video estrangeiro de ponta a ponta).
