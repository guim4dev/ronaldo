# Dados do modelo `gol_grito` (treino e avaliação)

Este diretório prepara os dados. **Não treina o modelo** — isso é a tarefa
seguinte. Tudo o que é áudio, feature e download vive em `~/data/gol/`, fora do
repositório. O repo público guarda somente estes scripts e este documento.

## Como reproduzir

Na hemocione-one (12 CPU; 8 processos no máximo; o `.npy` de features ACAV tem
17 GB e é lido com `mmap`, nunca inteiro na memória):

```bash
cd training/gol
uv sync

# 1) downloads (idempotente: pula o que já existe)
uv run python download.py --etapa all

# 2) gritos sintéticos (20 mil treino, 1 mil teste)
uv run python gerar_positivos.py --split treino --n 20000 --workers 8
uv run python gerar_positivos.py --split teste  --n 1000  --workers 8

# 3) negativos (17 mil falas normais + 3 mil palavras gritadas que não são gol)
uv run python gerar_negativos.py --n-fala 17000 --n-grito 3000 --workers 8

# 4) features (mesmo pipeline do ronaldo/detector.py)
uv run python features.py --curtos
uv run python features.py --streaming --horas-avaliacao 8.5

# 5) manifesto e resumo
uv run python manifesto.py

# provas
uv run pytest -q
```

Cada etapa é idempotente. `download.py --etapa X` aceita
`openwakeword|piper|rir|noise|music|speech|game|gol_real`.

## Layout em `~/data/gol/`

```
raw/            áudio bruto, 16 kHz mono (exceto o .npy do openWakeWord)
  openwakeword/ features ACAV100M (17 GB) + validation_set_features.npy
  piper/        binário + vozes pt_BR (faber, edresson, cadu, jeff)
  rir/          270 RIRs MIT (16 kHz)
  noise/        2 000 clipes ESC-50
  music/        3 127 faixas FMA small (~26 h)
  speech_ptbr/  MLS português (~18 h) por falante
  game/         futebol de videogame via yt-dlp (~16 h)
  gol_real/     narrações de gol recortadas (>= 60 clipes <= 3 s)
work/           wavs sintéticos de 2 s (pos_train, pos_test, neg_train)
features/       .npy prontos para o treino
MANIFESTO.json  arquivos, formas, horas, split, vozes
FONTES.md       URL, licença e destino de cada fonte
```

## Pipeline de features (o contrato)

As features são **exatamente** as de `ronaldo/detector.py`:

- áudio 16 kHz mono → `models/melspectrogram.onnx` → `mel/10 + 2`;
- janela de mel de 76 frames, passo 8 → `models/embedding_model.onnx` → 96
  dimensões por embedding; 16 embeddings = janela de 2 s (32 000 amostras);
- clipes curtos entram no **fim** de uma janela de 2 s (o resto é fundo: silêncio
  baixo, ruído, jogo ou música);
- áudio longo vira **streaming**: uma linha `[96]` por chunk de 80 ms
  (1 280 amostras), reproduzindo o estado interno do detector (buffer de
  1 760 amostras, 970 frames de mel, janela de 76). Junto vai o RMS em dBFS de
  cada chunk, para o portão de volume ser simulado na avaliação.

A prova de que bate com o detector é `testes/test_pipeline.py`: o teste compara,
chunk por chunk, a saída de `features_streaming` com `WakeWord.scores` e a saída
da rota de clipe com `WakeWord._embed_clip` (tolerância zero em `float32`).

## Split

- **Curtos**: treino e teste são gerados separadamente. O teste usa vozes que o
  treino não vê: Piper `jeff` + edge-tts pt-BR (Francisca, Antonio, Thalita) e
  pt-PT (Raquel, Duarte). Metade limpa, metade com ruído de jogo.
- **Longos**: split por fonte, nunca por trecho do mesmo arquivo — falante MLS
  (conversa), vídeo (jogo), faixa (música). Nenhuma fonte aparece nos dois
  lados. O detalhe fica em `features/split_streaming.json`.

## Aumento "grito" (treino dos positivos)

Sobre a saída do Piper: pitch +1…+6 semitons, time-stretch da vogal mais longa
1–3×, clipping suave (`tanh`), ganho −3…+9 dB, RIR (45 % dos clipes) e mistura
com jogo/ruído/música a SNR 0–20 dB (85 % dos clipes). As palavras curtas
gritadas dos negativos usam o mesmo aumento.

Piper roda com `length_scale` 0,80–2,50 e `noise_scale`/`noise_w` variados, todas
as qualidades disponíveis de cada voz. Cada modelo pt_BR do catálogo tem um
falante (`num_speakers: 1`), então "todos os speakers" = todas as vozes listadas.

## Fontes

Ver `~/data/gol/FONTES.md` (URL, licença, destino, data). Resumo:

| fonte | uso | licença |
|---|---|---|
| `davidscripka/openwakeword_features` (HF) | negativos gerais (ACAV100M) + validação FA/h | CC-BY 4.0 |
| `rhasspy/piper-voices` (HF) | vozes sintéticas pt_BR | MIT / CC-BY conforme MODEL_CARD |
| edge-tts (Microsoft) | vozes reservadas de teste | termos do serviço |
| `davidscripka/MIT_environmental_impulse_responses` (HF) | RIRs | MIT IR Survey |
| `benjamin-paine/free-music-archive-small` (HF) | música | CC-BY / CC-BY-SA / CC0 por faixa |
| `ashraq/esc50` (HF) | ruído ambiente | CC-BY-NC 3.0 |
| `facebook/multilingual_librispeech` (HF, config portuguese) | conversa pt-BR | CC-BY 4.0 |
| YouTube (yt-dlp) | jogo de futebol de videogame e narrações de gol | conteúdo de terceiros, uso local |

Áudio de terceiros **nunca** entra no git: só scripts, docs e o modelo final.
