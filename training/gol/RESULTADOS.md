# Resultados do `gol_grito`

**Experimental e não recomendado para uso:** cumpre 1/3 metas, acerta 43,8% no limiar 0,9 e detectou 0/17 gritos humanos reais. Não habilite a rota até cumprir as metas e passar pela aceitação ao vivo (`tools/grito_ao_vivo.py`).

Gerado por `uv run python eval.py --resumo --markdown RESULTADOS.md` em
2026-11-08 04:18. Modelo: `models/gol_grito.onnx`
(198.4 KB, entrada [1, 16, 96], saida [1, 1]).

## Limiar sugerido: **0.90**

| meta | valor | alvo | resultado |
|---|---|---|---|
| acerto nos gritos de teste (com portao) | 43.8% (500/1142) | >= 85% | NAO bate |
| FA/h conversa pt-BR (com portao, todos os conjuntos) | 0.05 | <= 0,5 | bate |
| FA/h jogo+musica (com portao) | 0.22 | <= 0,2 | NAO bate |
| metas cumpridas | 1/3 | 3/3 | parcial |

O limiar `0.90` e o maior da grade. Nenhum limiar atingiu as 2 metas de FA.
`eval.py --resumo` informa `meta de FA não atingida`.

## Tabelas

"Sem portao" = so o classificador, com intervalo minimo de 8 s entre disparos.
"Com portao" = a mesma contagem depois do portao de volume de producao
(`ronaldo.grito.PortaoGrito`, simulado). FA/h entre parenteses: disparos
contados; limite superior unilateral de 95% Poisson.

### Sem portao de volume

| limiar | sintetico limpo | sintetico ruido | narradores reais | real teste (novo) | total | validation | conversa_mls | jogo | musica | conversa_futebol | jogo+musica |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.30 | 76.2% (381/500) | 70.0% (350/500) | 4.0% (5/125) | 0.0% (0/17) (IC95 Wilson 0.0–18.4%) | 64.4% (736/1142) | 36.74 (393; <= 39.94) | 2.83 (24; <= 3.98) | 10.88 (103; <= 12.81) | 18.35 (156; <= 20.96) | 2.53 (27; <= 3.49) | 14.41 (259; <= 15.98) |
| 0.40 | 74.6% (373/500) | 67.4% (337/500) | 4.0% (5/125) | 0.0% (0/17) (IC95 Wilson 0.0–18.4%) | 62.6% (715/1142) | 30.10 (322; <= 33.01) | 2.36 (20; <= 3.42) | 8.45 (80; <= 10.18) | 14.82 (126; <= 17.19) | 2.25 (24; <= 3.16) | 11.47 (206; <= 12.87) |
| 0.50 | 72.0% (360/500) | 64.4% (322/500) | 4.0% (5/125) | 0.0% (0/17) (IC95 Wilson 0.0–18.4%) | 60.2% (687/1142) | 24.87 (266; <= 27.53) | 1.18 (10; <= 2.00) | 6.34 (60; <= 7.86) | 11.53 (98; <= 13.64) | 1.59 (17; <= 2.39) | 8.79 (158; <= 10.03) |
| 0.60 | 68.6% (343/500) | 61.2% (306/500) | 4.0% (5/125) | 0.0% (0/17) (IC95 Wilson 0.0–18.4%) | 57.3% (654/1142) | 20.38 (218; <= 22.80) | 0.82 (7; <= 1.55) | 4.96 (47; <= 6.33) | 9.88 (84; <= 11.85) | 1.41 (15; <= 2.16) | 7.29 (131; <= 8.43) |
| 0.70 | 64.0% (320/500) | 57.0% (285/500) | 4.0% (5/125) | 0.0% (0/17) (IC95 Wilson 0.0–18.4%) | 53.4% (610/1142) | 15.80 (169; <= 17.95) | 0.71 (6; <= 1.40) | 3.70 (35; <= 4.90) | 6.59 (56; <= 8.23) | 1.22 (13; <= 1.94) | 5.06 (91; <= 6.03) |
| 0.80 | 61.2% (306/500) | 52.6% (263/500) | 4.0% (5/125) | 0.0% (0/17) (IC95 Wilson 0.0–18.4%) | 50.3% (574/1142) | 11.87 (127; <= 13.76) | 0.59 (5; <= 1.24) | 2.32 (22; <= 3.32) | 4.47 (38; <= 5.86) | 1.12 (12; <= 1.82) | 3.34 (60; <= 4.14) |
| 0.90 | 54.0% (270/500) | 45.8% (229/500) | 0.8% (1/125) | 0.0% (0/17) (IC95 Wilson 0.0–18.4%) | 43.8% (500/1142) | 5.89 (63; <= 7.26) | 0.12 (1; <= 0.56) | 1.16 (11; <= 1.92) | 2.00 (17; <= 3.00) | 0.56 (6; <= 1.11) | 1.56 (28; <= 2.14) |

### Com portao de volume

| limiar | sintetico limpo | sintetico ruido | narradores reais | real teste (novo) | total | validation | conversa_mls | jogo | musica | conversa_futebol | jogo+musica |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.30 | 76.2% (381/500) | 70.0% (350/500) | 4.0% (5/125) | 0.0% (0/17) (IC95 Wilson 0.0–18.4%) | 64.4% (736/1142) | n/d | 0.71 (6; <= 1.40) | 2.75 (26; <= 3.81) | 0.47 (4; <= 1.08) | 0.09 (1; <= 0.44) | 1.67 (30; <= 2.26) |
| 0.40 | 74.6% (373/500) | 67.4% (337/500) | 4.0% (5/125) | 0.0% (0/17) (IC95 Wilson 0.0–18.4%) | 62.6% (715/1142) | n/d | 0.59 (5; <= 1.24) | 2.01 (19; <= 2.94) | 0.24 (2; <= 0.74) | 0.09 (1; <= 0.44) | 1.17 (21; <= 1.68) |
| 0.50 | 72.0% (360/500) | 64.4% (322/500) | 4.0% (5/125) | 0.0% (0/17) (IC95 Wilson 0.0–18.4%) | 60.2% (687/1142) | n/d | 0.35 (3; <= 0.91) | 1.58 (15; <= 2.44) | 0.00 (0; <= 0.35) | 0.09 (1; <= 0.44) | 0.83 (15; <= 1.29) |
| 0.60 | 68.6% (343/500) | 61.2% (306/500) | 4.0% (5/125) | 0.0% (0/17) (IC95 Wilson 0.0–18.4%) | 57.3% (654/1142) | n/d | 0.24 (2; <= 0.74) | 1.27 (12; <= 2.05) | 0.00 (0; <= 0.35) | 0.09 (1; <= 0.44) | 0.67 (12; <= 1.08) |
| 0.70 | 64.0% (320/500) | 57.0% (285/500) | 4.0% (5/125) | 0.0% (0/17) (IC95 Wilson 0.0–18.4%) | 53.4% (610/1142) | n/d | 0.24 (2; <= 0.74) | 0.74 (7; <= 1.39) | 0.00 (0; <= 0.35) | 0.09 (1; <= 0.44) | 0.39 (7; <= 0.73) |
| 0.80 | 61.2% (306/500) | 52.6% (263/500) | 4.0% (5/125) | 0.0% (0/17) (IC95 Wilson 0.0–18.4%) | 50.3% (574/1142) | n/d | 0.12 (1; <= 0.56) | 0.53 (5; <= 1.11) | 0.00 (0; <= 0.35) | 0.09 (1; <= 0.44) | 0.28 (5; <= 0.59) |
| 0.90 | 54.0% (270/500) | 45.8% (229/500) | 0.8% (1/125) | 0.0% (0/17) (IC95 Wilson 0.0–18.4%) | 43.8% (500/1142) | n/d | 0.12 (1; <= 0.56) | 0.42 (4; <= 0.97) | 0.00 (0; <= 0.35) | 0.00 (0; <= 0.28) | 0.22 (4; <= 0.51) |

### Alinhamento: ultima janela vs maximo por chunk (limiar sugerido)

| conjunto | so a ultima janela | maximo por chunk |
|---|---|---|
| sintetico_limpo | 17.8% (89/500) | 54.0% (270/500) |
| sintetico_ruido | 10.8% (54/500) | 45.8% (229/500) |
| narradores | 0.0% (0/125) | 0.8% (1/125) |
| real_teste | 0.0% (0/17) | 0.0% (0/17) |

### Disparos no jogo no limiar sugerido (com portao)

`arquivo` e `tempo no arquivo` so aparecem quando o stream tem <= 8 fontes
(2 videos no jogo); o tempo no stream sempre aparece. O portao deixa passar
somente os disparos acima da referencia de fala.

| arquivo | tempo no arquivo (s) | tempo no stream (s) | nota | nivel (dBFS) |
|---|---|---|---|---|
| 5f_qwkdNGYE.wav | 636.32 | 636.32 | 0.923 | -20.2 |
| 5f_qwkdNGYE.wav | 2559.84 | 2559.84 | 0.915 | -48.4 |
| 5f_qwkdNGYE.wav | 9986.16 | 9986.16 | 0.953 | -37.1 |
| R2WW-JVLaIE.wav | 15354.72 | 32627.92 | 0.956 | -36.4 |

## Conjuntos

| conjunto | clipes | fonte |
|---|---|---|
| sintetico limpo | 500 | pos_test, vozes reservadas (Piper jeff + edge-tts), sem ruido |
| sintetico ruido | 500 | pos_test com ruido de jogo (SNR 0-20 dB) |
| narradores reais | 125 | `raw/gol_real/clips` (videos publicos, uso local) |
| real teste (novo) | 17 | `features/real_test.npy` |
| conversa_mls | 8.49 h | 1925 arquivo(s) | `stream_speech_ptbr_avaliacao_features.npy` |
| jogo | 9.47 h | 2 arquivo(s) | `stream_game_avaliacao_features.npy` |
| musica | 8.50 h | 1020 arquivo(s) | `stream_music_avaliacao_features.npy` |
| conversa_futebol | 10.67 h | 5 arquivo(s) | `stream_conversa_futebol_avaliacao_features.npy` |
| validation openWakeWord | 10.70 h | `validation_set_features.npy` |
| fala normal com "gol" | 1000 clipes | amostra de `work/neg_train` (tipo fala_normal) |
| palavras curtas gritadas | 500 clipes | amostra de `work/neg_train` (tipo palavra_gritada) |

## O que bate e o que nao bate

- Acerto nos gritos de teste (com portao) no limiar sugerido:
  43.8% — NAO bate a meta de 85%.
  Por conjunto: sintetico limpo 54.0%,
  sintetico com ruido 45.8%,
  narradores reais 0.8%, real teste 0.0%.
- FA/h observada com portao no limiar sugerido: conversa 0.05
  (bate a meta de 0,5), jogo+musica 0.22
  (NAO bate a meta de 0,2).
  Por conjunto de conversa (o pior e `conversa_mls`, 0.12 FA/h):
  - conversa_mls: 0.12 FA/h com portao (8.49 h)
  - conversa_futebol: 0.00 FA/h com portao (10.67 h)
- **Conversa MLS e de um falante so.** A conversa de futebol multi-falante entrou
  como conjunto proprio para medir a generalizacao entre falantes; a meta de
  conversa vale para a soma dos conjuntos.
- Fala normal com "gol" no nivel da referencia: o portao barra
  1
  de
  1 disparos
  do classificador em 1000 clipes de fala normal (amostra).
- Palavras curtas gritadas que nao sao "gol": o portao barra
  5
  de
  5 disparos
  do classificador em 500 clipes (amostra).

## Aproximacoes (importantes)

1. **Portao nos streams.** O stream so tem o RMS dBFS por chunk (nao ha audio).
   O chunk sintetico tem amplitude constante com o mesmo RMS, porque o portao de
   producao so olha o RMS. O VAD e aproximado por `RMS > piso + 10 dB`, com piso =
   percentil 10 do RMS em blocos de ~2 min. O stream inteiro e tratado como uma
   sessao continua: o conversor de features paraleliza por arquivo e nao registra
   a ordem da concatenacao, entao nao ha fronteira de arquivo confiavel. Os
   eventos de fronteira sao ~1 janela por arquivo (desprezivel no total).
2. **validation_set_features** (~11 h) nao tem RMS: a coluna COM portao e `n/d`.
   O numero sem portao e o que vale para esse conjunto; o portao so pode reduzir
   disparos, nunca aumentar.
3. **Clipes de grito.** A fala normal simulada tem RMS de referencia -26 dBFS
   (25 s para a referencia do portao); o grito e simulado a referencia+12 dB.
   A fala normal com "gol" e avaliada no nivel da referencia.
4. **Warmup.** Nos streams as 15 primeiras janelas sao descartadas (historico
   incompleto); nos clipes vale o warmup real do `WakeWord` (5 primeiros chunkos
   com nota 0).
5. **Alcance.** Os numeros provam vozes sinteticas e narradores reais. **Nao
   provam a voz do Guima**: isso depende do teste ao vivo
   (`tools/grito_ao_vivo.py`, 10 gritos + 2 min de conversa, nada gravado).
   As metas devem ser conferidas contra o alvo; se nao baterem, o deploy espera
   a aceitacao ao vivo ou uma ordem explicita do Guima.
6. **Arquivo e tempo no jogo.** O conversor paralelo nao guarda a ordem da
   concatenacao. No jogo ha 2 videos e 6 fatias: a ordem concatenada coincide
   com a lista ordenada, entao `arquivo` e `tempo no arquivo` saem exatos. Para
   os outros streams (muitos arquivos) a coluna nao se aplica.

## Modelo e licenca

## Treino da iteracao 3

A selecao usou apenas validacao: recall em `0.5` com FA/h limitada a `30`.
Os gritos de teste nao participaram da escolha.

| variante | camada | epoca | recall@0,5 | janela final | FA/h@0,5 |
|---|---:|---:|---:|---:|---:|
| v2 misto-a | 32 | 13 | 0,845 | 0,692 | 24,87 |
| v3-a | 32 | 16 | 0,820 | 0,658 | 21,69 |
| v3-b | 48 | 20 | 0,839 | 0,698 | 23,84 |
| v3-c | 24 | 20 | 0,818 | 0,652 | 25,80 |

A v2 manteve o maior recall de validacao. `models/gol_grito.onnx` permanece na v2.

`models/gol_grito.onnx` — CC BY-NC-SA 4.0 (c) Thiago Guimaraes, os mesmos
termos do `ronaldo_ptbr.onnx` (ver `models/LICENSES.md`). Pesos treinados nesta
maquina; nenhum audio de terceiros entra no repositorio.
