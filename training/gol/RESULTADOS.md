# Resultados do `gol_grito`

Gerado por `uv run python eval.py --resumo --markdown RESULTADOS.md` em
2026-11-07 22:27. Modelo: `models/gol_grito.onnx`
(198.4 KB, entrada [1, 16, 96], saida [1, 1]).

## Limiar sugerido: **0.30**

| meta | valor | alvo | resultado |
|---|---|---|---|
| acerto nos gritos de teste (com portao) | 62.0% (697/1125) | >= 85% | NAO bate |
| FA/h conversa pt-BR (com portao, todos os conjuntos) | 0.26 | <= 0,5 | bate |
| FA/h jogo+musica (com portao) | 1.22 | <= 0,2 | NAO bate |
| metas cumpridas | 1/3 | 3/3 | parcial |

## Tabelas

"Sem portao" = so o classificador, com intervalo minimo de 8 s entre disparos.
"Com portao" = a mesma contagem depois do portao de volume de producao
(`ronaldo.grito.PortaoGrito`, simulado). FA/h entre parenteses: disparos
contados; limite superior unilateral de 95% Poisson.

### Sem portao de volume

| limiar | sintetico limpo | sintetico ruido | narradores reais | total | validation | conversa_mls | jogo | musica | conversa_futebol | jogo+musica |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.30 | 72.8% (364/500) | 65.8% (329/500) | 3.2% (4/125) | 62.0% (697/1125) | 26.93 (288; <= 29.69) | 0.82 (7; <= 1.55) | 11.51 (109; <= 13.50) | 18.00 (153; <= 20.58) | 2.25 (24; <= 3.16) | 14.58 (262; <= 16.15) |
| 0.40 | 71.0% (355/500) | 64.0% (320/500) | 2.4% (3/125) | 60.3% (678/1125) | 24.40 (261; <= 27.04) | 0.71 (6; <= 1.40) | 9.72 (92; <= 11.56) | 16.35 (139; <= 18.83) | 1.87 (20; <= 2.72) | 12.86 (231; <= 14.34) |
| 0.50 | 68.6% (343/500) | 63.6% (318/500) | 2.4% (3/125) | 59.0% (664/1125) | 21.41 (229; <= 23.89) | 0.47 (4; <= 1.08) | 8.66 (82; <= 10.41) | 14.82 (126; <= 17.19) | 1.69 (18; <= 2.50) | 11.58 (208; <= 12.99) |
| 0.60 | 67.2% (336/500) | 62.6% (313/500) | 2.4% (3/125) | 58.0% (652/1125) | 19.17 (205; <= 21.52) | 0.35 (3; <= 0.91) | 7.92 (75; <= 9.60) | 13.06 (111; <= 15.29) | 1.69 (18; <= 2.50) | 10.35 (186; <= 11.69) |
| 0.70 | 65.6% (328/500) | 60.8% (304/500) | 2.4% (3/125) | 56.4% (635/1125) | 17.02 (182; <= 19.24) | 0.24 (2; <= 0.74) | 7.08 (67; <= 8.67) | 11.18 (95; <= 13.26) | 1.50 (16; <= 2.28) | 9.02 (162; <= 10.27) |
| 0.80 | 63.8% (319/500) | 58.4% (292/500) | 1.6% (2/125) | 54.5% (613/1125) | 14.96 (160; <= 17.05) | 0.24 (2; <= 0.74) | 6.34 (60; <= 7.86) | 8.59 (73; <= 10.44) | 1.03 (11; <= 1.71) | 7.40 (133; <= 8.55) |
| 0.90 | 60.2% (301/500) | 54.4% (272/500) | 0.8% (1/125) | 51.0% (574/1125) | 11.22 (120; <= 13.06) | 0.12 (1; <= 0.56) | 4.65 (44; <= 5.98) | 6.35 (54; <= 7.97) | 0.75 (8; <= 1.35) | 5.45 (98; <= 6.45) |

### Com portao de volume

| limiar | sintetico limpo | sintetico ruido | narradores reais | total | validation | conversa_mls | jogo | musica | conversa_futebol | jogo+musica |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.30 | 72.8% (364/500) | 65.8% (329/500) | 3.2% (4/125) | 62.0% (697/1125) | n/d | 0.12 (1; <= 0.56) | 2.11 (20; <= 3.07) | 0.24 (2; <= 0.74) | 0.37 (4; <= 0.86) | 1.22 (22; <= 1.75) |
| 0.40 | 71.0% (355/500) | 64.0% (320/500) | 2.4% (3/125) | 60.3% (678/1125) | n/d | 0.00 (0; <= 0.35) | 1.90 (18; <= 2.82) | 0.24 (2; <= 0.74) | 0.37 (4; <= 0.86) | 1.11 (20; <= 1.62) |
| 0.50 | 68.6% (343/500) | 63.6% (318/500) | 2.4% (3/125) | 59.0% (664/1125) | n/d | 0.00 (0; <= 0.35) | 1.80 (17; <= 2.69) | 0.24 (2; <= 0.74) | 0.28 (3; <= 0.73) | 1.06 (19; <= 1.55) |
| 0.60 | 67.2% (336/500) | 62.6% (313/500) | 2.4% (3/125) | 58.0% (652/1125) | n/d | 0.00 (0; <= 0.35) | 1.69 (16; <= 2.57) | 0.12 (1; <= 0.56) | 0.28 (3; <= 0.73) | 0.95 (17; <= 1.42) |
| 0.70 | 65.6% (328/500) | 60.8% (304/500) | 2.4% (3/125) | 56.4% (635/1125) | n/d | 0.00 (0; <= 0.35) | 1.37 (13; <= 2.18) | 0.12 (1; <= 0.56) | 0.28 (3; <= 0.73) | 0.78 (14; <= 1.22) |
| 0.80 | 63.8% (319/500) | 58.4% (292/500) | 1.6% (2/125) | 54.5% (613/1125) | n/d | 0.00 (0; <= 0.35) | 1.37 (13; <= 2.18) | 0.12 (1; <= 0.56) | 0.28 (3; <= 0.73) | 0.78 (14; <= 1.22) |
| 0.90 | 60.2% (301/500) | 54.4% (272/500) | 0.8% (1/125) | 51.0% (574/1125) | n/d | 0.00 (0; <= 0.35) | 0.84 (8; <= 1.52) | 0.12 (1; <= 0.56) | 0.19 (2; <= 0.59) | 0.50 (9; <= 0.87) |

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

A categoria `conversa_futebol` é só de avaliação. O soldado de dados zerou
562,35 s (277 janelas) de trechos acima de +12 dB da mediana de fala do arquivo
`EszF7EZ3N6k` (grito, vaia ou vinheta alta). Um grito de gol ali seria um
positivo, não um falso alarme.

## O que bate e o que nao bate

- Acerto nos gritos de teste (com portao) no limiar sugerido:
  62.0% — NAO bate a meta de 85%.
  Por conjunto: sintetico limpo 72.8%,
  sintetico com ruido 65.8%,
  narradores reais 3.2%.
- FA/h observada com portao no limiar sugerido: conversa 0.26
  (bate a meta de 0,5), jogo+musica 1.22
  (NAO bate a meta de 0,2).
  Por conjunto de conversa (o pior e `conversa_futebol`, 0.37 FA/h):
  - conversa_mls: 0.12 FA/h com portao (8.49 h)
  - conversa_futebol: 0.37 FA/h com portao (10.67 h)
- **Conversa MLS e de um falante so.** A conversa de futebol multi-falante entrou
  como conjunto proprio para medir a generalizacao entre falantes; a meta de
  conversa vale para a soma dos conjuntos.
- Fala normal com "gol" no nível da referência: o portão barra
  5 de
  5 disparos
  do classificador em 1000 clipes de fala normal (amostra).
- Palavras curtas gritadas que não são "gol": o portão barra
  64 de
  64 disparos
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

## Treino e escolha do modelo

Três variantes treinadas com os dados completos. A escolha usou só o
`validation_set_features.npy` e o split de validação de `pos_train`. `pos_test`
e os streams de avaliação nunca entraram na escolha.

| variante | ACAV / janelas de stream por lote | peso negativo máx. | época escolhida | recall@0,5 (val) | FA/h@0,5 (validation) |
|---|---|---|---|---|---|
| **a** | 512 / 384 | 50 | 24 | 0,967 | 21,41 |
| b | 512 / 512 | 50 | 18 | 0,937 | 31,69 |
| c | 768 / 384 | 100 | 24 | 0,903 | 18,89 |

A variante **a** foi a escolhida: maior recall e FA/h menor que a b. O treino usa
mineração de exemplos difíceis e agenda cosine, como o openWakeWord. O limiar
sugerido é a escolha de implantação feita sobre a curva de avaliação.

## Diagnóstico do que não bateu

- O recall de validação (0,967) não se repete nos gritos sintéticos de teste
  (0,728 limpo, 0,658 com ruído). O treino viu três vozes Piper (cadu, edresson,
  faber); o teste usa seis vozes que o treino não viu (jeff e edge-tts).
- Narradores reais acertam só 3,2% (4/125). O grito humano de estádio difere do
  TTS aumentado. Este conjunto é só de avaliação; nenhum clipe real entrou no
  treino.
- Há um desalinhamento de representação: o treino usa a **última** janela de 16
  embeddings do clipe; a produção pontua **todo** chunk e aceita o máximo. Nos
  mesmos clipes de teste, essa última janela passa o limiar em ~18% dos clipes,
  enquanto o máximo por chunk chega a 72,8%: o modelo dispara em janelas
  intermediárias (chunk ~15), que o treino não viu. A próxima iteração deve
  treinar em todas as janelas de produção e incluir gritos humanos reais no
  treino (não só na avaliação).
- FA/h de jogo com portão ficou em 2,11 (meta 0,2). Música ficou em 0,24 (quase
  na meta). O portão reduz a FA no jogo em ~5×, mas não o suficiente.

## Modelo e licença

`models/gol_grito.onnx` — CC BY-NC-SA 4.0 (c) Thiago Guimaraes, os mesmos
termos do `ronaldo_ptbr.onnx` (ver `models/LICENSES.md`). Pesos treinados nesta
maquina; nenhum audio de terceiros entra no repositorio.
