# Resultados do `gol_grito`

Gerado por `uv run python eval.py --resumo --markdown RESULTADOS.md` em
2026-11-08 01:16. Modelo: `models/gol_grito.onnx`
(198.4 KB, entrada [1, 16, 96], saida [1, 1]).

## Limiar sugerido: **0.30**

| meta | valor | alvo | resultado |
|---|---|---|---|
| acerto nos gritos de teste (com portao) | 65.4% (736/1125) | >= 85% | NAO bate |
| FA/h conversa pt-BR (com portao, todos os conjuntos) | 0.37 | <= 0,5 | bate |
| FA/h jogo+musica (com portao) | 1.67 | <= 0,2 | NAO bate |
| metas cumpridas | 1/3 | 3/3 | parcial |

## Tabelas

"Sem portao" = so o classificador, com intervalo minimo de 8 s entre disparos.
"Com portao" = a mesma contagem depois do portao de volume de producao
(`ronaldo.grito.PortaoGrito`, simulado). FA/h entre parenteses: disparos
contados; limite superior unilateral de 95% Poisson.

### Sem portao de volume

| limiar | sintetico limpo | sintetico ruido | narradores reais | total | validation | conversa_mls | jogo | musica | conversa_futebol | jogo+musica |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.30 | 76.2% (381/500) | 70.0% (350/500) | 4.0% (5/125) | 65.4% (736/1125) | 36.74 (393; <= 39.94) | 2.83 (24; <= 3.98) | 10.88 (103; <= 12.81) | 18.35 (156; <= 20.96) | 2.53 (27; <= 3.49) | 14.41 (259; <= 15.98) |
| 0.40 | 74.6% (373/500) | 67.4% (337/500) | 4.0% (5/125) | 63.6% (715/1125) | 30.10 (322; <= 33.01) | 2.36 (20; <= 3.42) | 8.45 (80; <= 10.18) | 14.82 (126; <= 17.19) | 2.25 (24; <= 3.16) | 11.47 (206; <= 12.87) |
| 0.50 | 72.0% (360/500) | 64.4% (322/500) | 4.0% (5/125) | 61.1% (687/1125) | 24.87 (266; <= 27.53) | 1.18 (10; <= 2.00) | 6.34 (60; <= 7.86) | 11.53 (98; <= 13.64) | 1.59 (17; <= 2.39) | 8.79 (158; <= 10.03) |
| 0.60 | 68.6% (343/500) | 61.2% (306/500) | 4.0% (5/125) | 58.1% (654/1125) | 20.38 (218; <= 22.80) | 0.82 (7; <= 1.55) | 4.96 (47; <= 6.33) | 9.88 (84; <= 11.85) | 1.41 (15; <= 2.16) | 7.29 (131; <= 8.43) |
| 0.70 | 64.0% (320/500) | 57.0% (285/500) | 4.0% (5/125) | 54.2% (610/1125) | 15.80 (169; <= 17.95) | 0.71 (6; <= 1.40) | 3.70 (35; <= 4.90) | 6.59 (56; <= 8.23) | 1.22 (13; <= 1.94) | 5.06 (91; <= 6.03) |
| 0.80 | 61.2% (306/500) | 52.6% (263/500) | 4.0% (5/125) | 51.0% (574/1125) | 11.87 (127; <= 13.76) | 0.59 (5; <= 1.24) | 2.32 (22; <= 3.32) | 4.47 (38; <= 5.86) | 1.12 (12; <= 1.82) | 3.34 (60; <= 4.14) |
| 0.90 | 54.0% (270/500) | 45.8% (229/500) | 0.8% (1/125) | 44.4% (500/1125) | 5.89 (63; <= 7.26) | 0.12 (1; <= 0.56) | 1.16 (11; <= 1.92) | 2.00 (17; <= 3.00) | 0.56 (6; <= 1.11) | 1.56 (28; <= 2.14) |

### Com portao de volume

| limiar | sintetico limpo | sintetico ruido | narradores reais | total | validation | conversa_mls | jogo | musica | conversa_futebol | jogo+musica |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.30 | 76.2% (381/500) | 70.0% (350/500) | 4.0% (5/125) | 65.4% (736/1125) | n/d | 0.71 (6; <= 1.40) | 2.75 (26; <= 3.81) | 0.47 (4; <= 1.08) | 0.09 (1; <= 0.44) | 1.67 (30; <= 2.26) |
| 0.40 | 74.6% (373/500) | 67.4% (337/500) | 4.0% (5/125) | 63.6% (715/1125) | n/d | 0.59 (5; <= 1.24) | 2.01 (19; <= 2.94) | 0.24 (2; <= 0.74) | 0.09 (1; <= 0.44) | 1.17 (21; <= 1.68) |
| 0.50 | 72.0% (360/500) | 64.4% (322/500) | 4.0% (5/125) | 61.1% (687/1125) | n/d | 0.35 (3; <= 0.91) | 1.58 (15; <= 2.44) | 0.00 (0; <= 0.35) | 0.09 (1; <= 0.44) | 0.83 (15; <= 1.29) |
| 0.60 | 68.6% (343/500) | 61.2% (306/500) | 4.0% (5/125) | 58.1% (654/1125) | n/d | 0.24 (2; <= 0.74) | 1.27 (12; <= 2.05) | 0.00 (0; <= 0.35) | 0.09 (1; <= 0.44) | 0.67 (12; <= 1.08) |
| 0.70 | 64.0% (320/500) | 57.0% (285/500) | 4.0% (5/125) | 54.2% (610/1125) | n/d | 0.24 (2; <= 0.74) | 0.74 (7; <= 1.39) | 0.00 (0; <= 0.35) | 0.09 (1; <= 0.44) | 0.39 (7; <= 0.73) |
| 0.80 | 61.2% (306/500) | 52.6% (263/500) | 4.0% (5/125) | 51.0% (574/1125) | n/d | 0.12 (1; <= 0.56) | 0.53 (5; <= 1.11) | 0.00 (0; <= 0.35) | 0.09 (1; <= 0.44) | 0.28 (5; <= 0.59) |
| 0.90 | 54.0% (270/500) | 45.8% (229/500) | 0.8% (1/125) | 44.4% (500/1125) | n/d | 0.12 (1; <= 0.56) | 0.42 (4; <= 0.97) | 0.00 (0; <= 0.35) | 0.00 (0; <= 0.28) | 0.22 (4; <= 0.51) |

### Alinhamento: ultima janela vs maximo por chunk (limiar sugerido)

| conjunto | so a ultima janela | maximo por chunk |
|---|---|---|
| sintetico_limpo | 29.6% (148/500) | 76.2% (381/500) |
| sintetico_ruido | 22.6% (113/500) | 70.0% (350/500) |
| narradores | 0.0% (0/125) | 4.0% (5/125) |

### Disparos no jogo no limiar sugerido (com portao)

`arquivo` e `tempo no arquivo` so aparecem quando o stream tem <= 8 fontes
(2 videos no jogo); o tempo no stream sempre aparece. O portao deixa passar
somente os disparos acima da referencia de fala.

| arquivo | tempo no arquivo (s) | tempo no stream (s) | nota | nivel (dBFS) |
|---|---|---|---|---|
| 5f_qwkdNGYE.wav | 633.2 | 633.20 | 0.535 | -22.8 |
| 5f_qwkdNGYE.wav | 2559.52 | 2559.52 | 0.511 | -38.4 |
| 5f_qwkdNGYE.wav | 3353.2 | 3353.20 | 0.676 | -32.1 |
| 5f_qwkdNGYE.wav | 4341.84 | 4341.84 | 0.633 | -34.0 |
| 5f_qwkdNGYE.wav | 5217.04 | 5217.04 | 0.386 | -40.4 |
| 5f_qwkdNGYE.wav | 6569.12 | 6569.12 | 0.425 | -40.2 |
| 5f_qwkdNGYE.wav | 7436.88 | 7436.88 | 0.442 | -35.5 |
| 5f_qwkdNGYE.wav | 8608.4 | 8608.40 | 0.512 | -37.1 |
| 5f_qwkdNGYE.wav | 9255.84 | 9255.84 | 0.355 | -39.2 |
| 5f_qwkdNGYE.wav | 9808.8 | 9808.80 | 0.342 | -33.5 |
| 5f_qwkdNGYE.wav | 9900.4 | 9900.40 | 0.634 | -40.2 |
| 5f_qwkdNGYE.wav | 9986.0 | 9986.00 | 0.841 | -37.9 |
| 5f_qwkdNGYE.wav | 10380.4 | 10380.40 | 0.348 | -36.3 |
| 5f_qwkdNGYE.wav | 10754.16 | 10754.16 | 0.794 | -51.0 |
| 5f_qwkdNGYE.wav | 10841.12 | 10841.12 | 0.417 | -34.9 |
| 5f_qwkdNGYE.wav | 12423.92 | 12423.92 | 0.350 | -33.0 |
| 5f_qwkdNGYE.wav | 13425.12 | 13425.12 | 0.384 | -48.0 |
| 5f_qwkdNGYE.wav | 15512.4 | 15512.40 | 0.528 | -36.5 |
| 5f_qwkdNGYE.wav | 15591.28 | 15591.28 | 0.325 | -36.5 |
| R2WW-JVLaIE.wav | 115.28 | 17388.48 | 0.318 | -19.5 |
| R2WW-JVLaIE.wav | 4444.24 | 21717.44 | 0.586 | -33.3 |
| R2WW-JVLaIE.wav | 12196.0 | 29469.20 | 0.466 | -27.6 |
| R2WW-JVLaIE.wav | 13965.36 | 31238.56 | 0.600 | -54.0 |
| R2WW-JVLaIE.wav | 15354.56 | 32627.76 | 0.626 | -36.7 |
| R2WW-JVLaIE.wav | 15786.96 | 33060.16 | 0.677 | -21.8 |
| R2WW-JVLaIE.wav | 15804.0 | 33077.20 | 0.336 | -28.1 |

## Conjuntos

| conjunto | clipes | fonte |
|---|---|---|
| sintetico limpo | 500 | pos_test, vozes reservadas (Piper jeff + edge-tts), sem ruido |
| sintetico ruido | 500 | pos_test com ruido de jogo (SNR 0-20 dB) |
| narradores reais | 125 | `raw/gol_real/clips` (videos publicos, uso local) |

| conversa_mls | 8.49 h | 1925 arquivo(s) | `stream_speech_ptbr_avaliacao_features.npy` |
| jogo | 9.47 h | 2 arquivo(s) | `stream_game_avaliacao_features.npy` |
| musica | 8.50 h | 1020 arquivo(s) | `stream_music_avaliacao_features.npy` |
| conversa_futebol | 10.67 h | 5 arquivo(s) | `stream_conversa_futebol_avaliacao_features.npy` |
| validation openWakeWord | 10.70 h | `validation_set_features.npy` |
| fala normal com "gol" | 1000 clipes | amostra de `work/neg_train` (tipo fala_normal) |
| palavras curtas gritadas | 500 clipes | amostra de `work/neg_train` (tipo palavra_gritada) |

## O que bate e o que nao bate

- Acerto nos gritos de teste (com portao) no limiar sugerido:
  65.4% — NAO bate a meta de 85%.
  Por conjunto: sintetico limpo 76.2%,
  sintetico com ruido 70.0%,
  narradores reais 4.0%.
- FA/h observada com portao no limiar sugerido: conversa 0.37
  (bate a meta de 0,5), jogo+musica 1.67
  (NAO bate a meta de 0,2).
  Por conjunto de conversa (o pior e `conversa_mls`, 0.71 FA/h):
  - conversa_mls: 0.71 FA/h com portao (8.49 h)
  - conversa_futebol: 0.09 FA/h com portao (10.67 h)
- **Conversa MLS e de um falante so.** A conversa de futebol multi-falante entrou
  como conjunto proprio para medir a generalizacao entre falantes; a meta de
  conversa vale para a soma dos conjuntos.
- Fala normal com "gol" no nivel da referencia: o portao barra
  17
  de
  17 disparos
  do classificador em 1000 clipes de fala normal (amostra).
- Palavras curtas gritadas que nao sao "gol": o portao barra
  46
  de
  46 disparos
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

## Treino da iteracao 2

| variante | dados positivos | epoca | recall@0,5 (val) | janela final (val) | FA/h@0,5 (val) |
|---|---|---|---|---|---|
| alinhado-a | 24 mil sinteticos v2 + 4 mil com fundo longo | 20 | 0,876 | 0,726 | 21,69 |
| **misto-a (escolhida)** | + 25% de `pos_train.npy` antigo (janela final) | 13 | 0,845 | 0,692 | 24,87 |

- **Sinteticos v2**: 24 mil clipes com 4 vozes Piper (cadu, edresson, faber e
  tugao pt_PT), aumento mais forte (pitch +1..+10 semitons, vogal 1..4x,
  compressao ate 8, ganho -3..+12 dB, RIR e ruido a SNR 0..20 dB) e fundo
  antes/depois da palavra; 4 mil variantes com 1,5 s de fundo antes da palavra.
- **Alinhamento**: o sampler usa janelas de 16 embeddings deslocadas. Positiva
  so quando a palavra inteira (>= 80%) esta dentro da janela e o fim dela cai
  nos ultimos ~0,5 s; janelas antes da palavra sao negativas; janelas parciais
  ficam fora. O treino prioriza a janela com o fim da palavra no fim dela.
- **Jogo**: 4 mil janelas dificeis mineradas do stream de TREINO de jogo com o
  modelo da iteracao anterior e usadas como negativos.

## O que a iteracao 2 nao fechou

- **Alinhamento**: no conjunto de validacao a janela final chega a 0,692 com o
  maximo em 0,845. No teste sintetico a divergencia continua: 29,6% (limpo) e
  22,6% (ruido) na ultima janela, contra 76,2% e 70,0% no maximo por chunk. A
  causa principal e o deslocamento do fim da palavra dentro do clipe de teste:
  em 58 de 120 clipes limpos o trecho ativo termina mais de 0,8 s antes do fim
  do wav (silencio/pegada do TTS), entao a ultima janela nao e a janela do fim
  da palavra. O modelo tambem ainda dispara em janelas intermediarias de vozes
  nao vistas. A prova pedida (ultima janela == maximo) NAO foi obtida.
- **Grito humano**: o soldado de gritos reais nao entregou o split nem as
  features ate o prazo (`work/real_train` vazio; `raw/gritos/clips` com poucos
  clipes; sem `features/real_test.npy`). Nada de real entrou no treino e o
  `real_test` nao existe, entao os narradores reais continuam em 4,0% (5/125).
- **Jogo**: os negativos dificeis vieram do video de TREINO; o video de
  avaliacao e outro. A FA/h com portao subiu para 2,75 (jogo) e 1,67
  (jogo+musica) no limiar 0,30. Os 26 disparos no jogo estao na tabela acima.
- **Metas**: acerto 65,4% (meta 85%: nao), conversa 0,37 (meta 0,5: sim),
  jogo+musica 1,67 (meta 0,2: nao).

## Modelo e licenca

`models/gol_grito.onnx` — CC BY-NC-SA 4.0 (c) Thiago Guimaraes, os mesmos
termos do `ronaldo_ptbr.onnx` (ver `models/LICENSES.md`). Pesos treinados nesta
maquina; nenhum audio de terceiros entra no repositorio.
