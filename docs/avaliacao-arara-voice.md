# Avaliação técnica — Arara-voice no Ronaldo

- **Data:** 17/11/2026
- **Pergunta:** dá para trocar o Hex pelo [Arara-voice](https://github.com/davimatosms/Arara-voice) no Ronaldo, ou manter o Hex e usar o modelo do Arara só para pt-BR?
- **Escopo:** avaliação. Nada foi instalado, alterado ou desinstalado no Mac; a leitura remota foi só de comandos read-only.
- **Versões verificadas:** Ronaldo `b4116bc`; Hex `94cbe24` (app 3.4.0); Arara `12da477` (v0.4.3, 17/11/2026).
- **Máquina de referência:** Mac Apple M2, 16 GB de RAM, macOS 26.6.2, 18 GiB livres em `/`; Hex rodando com `parakeet_v3` e `language=pt`.

> **Premissa corrigida.** O Hex é um app de **ditado (STT)**, não de fala (TTS). O Arara também é STT. O TTS do Ronaldo é outro subsistema (`ronaldo/voz.py`: Wyoming/Kokoro e `say`), e não entra nesta conta. A pergunta real é trocar o **motor de transcrição** ou trocar o **modelo de transcrição**.

## Sumário executivo

- **Hex e Arara são a mesma categoria:** os dois transcrevem fala localmente e colam o texto; nenhum dos dois fala. O TTS do Ronaldo é Kokoro/`say` e continua igual em qualquer cenário.
- **Troca direta: não.** O Arara é um app autocontido: não tem CLI, API, servidor nem modo headless (`app/.../Main.java:47-74`). O Ronaldo só sabe dirigir o binário do Hex (`ronaldo/hexcli.py:13`). Sem esse CLI, o Ronaldo não inicia, não para, não lê o texto, não cancela e não troca idioma — nada disso existe no Arara.
- **A troca quebra o Ronaldo inteiro**, não só a transcrição: `ronaldo on/off/status` chama `hex status --json`, `hex quit` e `hex launch-at-login` (`ronaldo/ctl.py:83-144`), e o `install.sh` exige `/Applications/Hex.app` com o bundle `anomaly.hex` (`install.sh:11-21`). Arara não oferece nenhum desses comandos.
- **Usar o modelo do Arara no Hex: o arquivo, não; o mesmo modelo, sim.** O catálogo do Hex já tem `whisper_large_v3_turbo` (GGUF Q8_0, 886 MB), o mesmo Whisper large-v3-turbo do Arara (lá `ggml-large-v3-turbo-q5_0.bin`, 574 MB). O arquivo do Arara é ggml legado (magic `ggml`, provado) e a quantização declarada é Q5_0; o Hex recusa os dois (só GGUF v2/v3 com F32/F16/Q8_0; K-quants só no lab de macOS).
- **O ganho real de trocar para o turbo é a dica de idioma, não o WER.** No FLEURS `pt` do próprio Hex, turbo 4,17% contra Parakeet v3 4,96% — dentro do ruído de ~1,5 ponto. Mas o turbo aceita `--language pt`; o v3 **não aceita dica de idioma** e detecta sozinho (`models.rs:443`), que é a limitação por trás da issue #68.
- **Não há prova de que o Arara transcreva melhor em pt-BR.** O projeto não publica WER independente; o argumento é prompt fixo + dicionário + fatiamento. O harness E2E do repo calcula WER, mas não há resultados versionados, e ele ignora acentos na normalização (`E2E.java:893-905`).
- **Latência atual no M2, medida no log do Ronaldo:** p50 de 0,72 s e p90 de 1,20 s do fim da fala até "colando N caracteres" (210 ciclos com fala estimada entre 2 e 30 s; no subconjunto de 8–12 s, p50 0,68 s / p90 0,76 s). É a régua do piloto.
- **Recomendação:** manter o Hex; fazer o A/B com `whisper_large_v3_turbo` no Hex (30–60 min, reversível em um comando). Não trocar o Hex pelo app Arara; não portar o Arara para dentro do Ronaldo. O Arara standalone fica como teste opcional, sem integração.

### As cinco perguntas

| # | Pergunta | Resposta curta |
|---|---|---|
| 1 | Hex e Arara são a mesma coisa? | Sim, ambos são STT (ditado). O TTS do Ronaldo é `voz.py`, fora da conta. |
| 2 | Dá para trocar o Hex pelo Arara? | Não como peça; só reescrevendo o Arara para ter uma interface que o Ronaldo chame. |
| 3 | Dá para usar o modelo do Arara no Hex? | O arquivo do Arara não; o mesmo modelo (Whisper large-v3-turbo), já no catálogo, sim. |
| 4 | O Arara é melhor em pt-BR? | Não há WER independente; não dá para afirmar. |
| 5 | Qual o caminho? | A/B do turbo no Hex; manter o Hex. Arara só como app separado, se o turbo não resolver. |

## 1. O Hex hoje no Ronaldo

### 1.1 O que o Hex é

Hex é um app de ditado local da Anomaly, em Rust (`Cargo.toml`), licença MIT, com builds para macOS, Windows e Linux (`hex/README.md:1-11,62-84,105-110`). O app é 3.4.0. O que interessa ao Ronaldo é o **CLI de controle**: um conjunto de comandos versionados (protocolo de controle versão 4) que dirigem a instância que está rodando (`hex/docs/cli.md:1-26,356-389,654-663`). Os comandos são idempotentes, aceitam `--json` e têm códigos de saída estáveis (`cli.md:5-6,309-318`).

O Hex **não é TTS**. Ele transcreve, aplica os passos de Output e cola. Quem fala no Ronaldo é o `voz.py`, com Wyoming/Kokoro e o `say` do macOS (`ronaldo/voz.py:41,358-425`).

### 1.2 Onde ele pluga

| Arquivo | Papel | Linhas |
|---|---|---|
| `ronaldo/hexcli.py` | único ponto que fala com o binário do Hex: caminho, status, start, idioma, ditado, cancelamento | 13-15, 22-33, 36-66, 69-82, 85-113 |
| `ronaldo/listener.py` | wake word, Silero VAD, ciclo do ditado, rotas, HUD e colagem | 84-95, 157-180, 206-275 |
| `ronaldo/agent.py` | entrega o texto ao comando do agente (argv/stdin) e notifica a resposta | 208-224, 242-246 |
| `ronaldo/macos.py` | cola com Cmd+V e dá Return; restaura o clipboard; confere Acessibilidade | 40-59, 62-65 |
| `ronaldo/ctl.py` | `ronaldo on/off/status/cancel`; launchd + `hex status/quit/launch-at-login` | 26, 83-94, 97-181 |
| `install.sh` | exige Hex em `/Applications`, confere o bundle `anomaly.hex`, liga o login do Hex | 11-21, 70-71 |
| `ronaldo/voz.py` | TTS do Ronaldo (Kokoro/say), sem relação com Hex ou Arara | 41, 358-425 |

### 1.3 O ciclo de um ditado

1. A wake word dispara (`detector.py`, pipeline do openWakeWord reimplementado só com `onnxruntime`; `listener.py:289-299`).
2. `hexcli.ensure_running` consulta `hex status --json` e espera o Hex ficar "pronto" — permissões + modelo instalado (`hexcli.py:22-33,36-66`; `listener.py:214`).
3. `hexcli.ensure_language` confere o idioma do modelo e só troca se tiver mudado, com `hex model use <id> --language <lang>` (`hexcli.py:69-82`; `listener.py:221`).
4. `hex dictation start` (`hexcli.py:85-89`; `listener.py:225`).
5. O Ronaldo detecta o fim da fala com o **Silero VAD dele**, em blocos de 80 ms: 2,0 s de silêncio encerram; 6 s sem fala desistem; 60 s é o teto (`listener.py:84-95,147-180,235`).
6. `hex dictation stop --print` para a gravação e devolve o texto no stdout, sem colar (`hexcli.py:92-100`; `cli.md:100-112`). O Hex espera até 60 s; o Ronaldo espera 120 s (`hexcli.py:92`).
7. A rota decide: `type` cola com `macos.type_and_submit`; `command` chama `agent.dispatch`; atalhos e modo voz são casos da rota `command` (`listener.py:252-268`; `agent.py:208-246`).
8. Cancelamento: `hex dictation cancel` descarta de verdade; em Hex antigo, o Ronaldo para e joga o texto fora (`hexcli.py:103-113`; `cli.md:144-150`).

O idioma é pinado por `Config.resolved_language()`: `language="auto"` vira o idioma preferido do macOS, `pt-BR` → `pt` (`listener.py:90-95,124-134`). No Mac, `hex status` confirma `parakeet_v3`/`pt`.

### 1.4 O que o Hex entrega além do texto

| Recurso | Para que serve | Onde |
|---|---|---|
| `status --json` | pid, listener, modelo, idioma, permissões, footprint, labs | `cli.md:423-462` |
| `model use/install` | troca e instala modelo; `--language` fixa o idioma | `cli.md:52-61,235-263` |
| `dictation cancel` | descarta áudio e transcrição, sem colar nem salvar | `cli.md:144-150` |
| Output steps | substituições, limpezas, scripts e reescrita opcional; valem também no `stop --print` | `hex/README.md:20-25`; `cli.md:100-112` |
| Histórico | ditados pesquisáveis, 7 dias por padrão; `hex history` só lê | `hex/README.md:19`; `cli.md:25-26` |
| Vocabulário | lista compartilhada; Parakeet usa como bias, Whisper/Qwen como prompt (500/1.000 caracteres) | `hex/docs/features/vocabulary.md:77-91`; `vocabulary.rs:321-327` |
| `hex transcribe` | transcreve arquivo com `--model` e `--language`, com ou sem Hex rodando | `cli.md:42,171-200` |
| `paste-last`, reuniões, API local/SDK | recursos que o Ronaldo não usa hoje | `hex/README.md:18-30`; `cli.md:30-88` |

### 1.5 O que o Ronaldo faz por conta própria

O Ronaldo não é só um atalho para o Hex. Ele tem wake word, VAD, rotas (`type`/`command`), atalhos por palavra, HUD flutuante, notificações, modo voz (TTS), instância única, LaunchAgent e o arquivo de pedido de cancelamento (`listener.py:206-275`; `ctl.py:147-181`; `README.md:3-11,55-171`). Nada disso vem do Hex, e nada disso seria substituído pelo Arara.

### 1.6 O que está configurado no Mac hoje (leitura)

- Hex 3.4.0, `parakeet_v3`, `language=pt`, permissões de microfone e Acessibilidade prontas, footprint de 201.115.352 bytes (~201 MB), lab `vocabulary-biasing` ligado.
- `dictation_hotkey=option`, `shortcut_mode=hold`, `release_microphone_while_idle=false`, `history_retention=week`; o modelo e o idioma são read-only no CLI e mudam por `hex model use`.
- O Ronaldo tem uma rota `type` (wake word `wall-e`), uma rota `command` que chama um CLI local do Reino, dois atalhos (`batuqueiro` e `gol`) e `[voz]` com Kokoro via Wyoming + `say:Luciana`; `language="auto"` (o padrão) usa o idioma do macOS, e o Hex está em `pt`.
- O Hex também tem o atalho global dele (Option, no modo hold). Ou seja, já existem hoje **duas portas de entrada** de ditado — a wake word do Ronaldo e o atalho do Hex. Acrescentar o Arara criaria uma terceira.

## 2. O Arara-voice

### 2.1 O que é

Arara é um app de ditado local para pt-BR: Java 21 + Swing/FlatLaf, Whisper via `whisper-jni` 1.7.1 (whisper.cpp), licença MIT, versão 0.4.3, com commits de 17/11/2026 (`Arara-voice/README.md:5-6,18-22,116-125`; `gradle.properties`; `LICENSE`). O README oferece Windows 10/11 e macOS Apple Silicon/Intel; Linux aparece no código, mas o `DECISOES.md` diz que fica para depois (`DECISOES.md:36-38`).

Diferente do Hex, o Arara não é uma peça com interface: é o app inteiro — ele abre o microfone, escuta o atalho, transcreve, mostra o pop-up, salva o histórico e **cola sozinho**.

### 2.2 Arquitetura

| Componente | O que faz | Arquivo |
|---|---|---|
| `Microphone` | captura 16 kHz, mono, PCM | `Microphone.java`; `DECISOES.md:46` |
| `WhisperTranscriber` | whisper.cpp via JNI, prompt fixo em pt-BR, download/SHA-256, Metal no Mac | `WhisperTranscriber.java:30-43,138-152,199-229` |
| `DefaultDictationEngine` | toggle/hold, cortes na pausa, alvo de 3 s, prévia, junção, histórico, dicionário, colagem | `DefaultDictationEngine.java:38-55,235-282,379-400,462-496` |
| `Vad` | VAD por energia, piso adaptativo, 2,5 s de silêncio, 5 min sem fala | `Vad.java:3-15,26-41` |
| `GlobalHotkey` | atalho global via JNativeHook; não engole a tecla | `GlobalHotkey.java:16-18,44-48`; `DECISOES.md:123` |
| `ClipboardPaster` | cola com Cmd+V/Ctrl+V e restaura o clipboard | `ClipboardPaster.java:23-58` |
| `DictionaryStore` | substituição de palavras **depois** da transcrição | `JsonDictionaryStore.java:56-72` |
| `HistoryStore` | `historico.jsonl`, sem limite, local | `DECISOES.md:109-119` |
| `Settings` | JSON; não há campo de prompt livre | `Settings.java:22-39` |
| App | janela Swing, pop-up, bandeja, onboarding, temas, updater | `Main.java`; `Arara-voice/README.md:33-46` |

O VAD de 2,5 s **não encerra o ditado**: ele só muda o estado para `SILENCE` (`DefaultDictationEngine.java:255-261`). Quem encerra é o atalho (toggle ou soltar, no modo segurar) ou o limite de 5 min sem fala (`Vad.java:12`). Isso é uma diferença de fluxo importante em relação ao Ronaldo, que encerra sozinho após 2 s de silêncio.

### 2.3 Sem CLI, API, servidor ou headless

Os únicos argumentos de `Main.java` são modos de demonstração/diagnóstico: `--demo` (com `--primeira-execucao` e `--atualizacao`), `--alternar` e `--diagnostico-colar` (`Main.java:47-74,200-203`). `--diagnostico-colar` roda um diagnóstico e sai; `--alternar` é um atalho de sistema para o modo Wayland; `--demo` usa dados falsos. Não existe `--print`, `--model`, `--language`, `stop`, `start` nem um soquete de controle. O único `ServerSocket` do app é o da instância única, que serve para mostrar a janela/toggle (`Main.java:57-72`; `SingleInstance.java:30-56`).

Consequência prática: **não dá para rodar o Arara em lote** (transcrever 20 WAVs) nem para pedir "transcreva e me devolva o texto sem colar". O E2E do repo é um harness de desenvolvimento (`core/src/e2e/.../E2E.java`), não um CLI de produção.

### 2.4 Modelos, tamanhos e formato

| Modelo | Arquivo | Bytes | MB (decimal) | SHA-256 (início) |
|---|---|---|---:|---|
| Leve | `ggml-base.bin` | 147.951.465 | 148 | `60ed5bc3…` |
| Equilibrado | `ggml-small.bin` | 487.601.967 | 488 | `1be3a9b2…` |
| Preciso (padrão) | `ggml-large-v3-turbo-q5_0.bin` | 574.041.195 | 574 | `39422170…` |

Fonte: `WhisperTranscriber.java:37-38,138-152`; tamanhos e magic conferidos por `Range` no arquivo real da Hugging Face (commit `5359861…`), e os SHA-256 são os do código. Os três arquivos começam com os bytes `6c 6d 67 67` — o magic `ggml` legado, **não** `GGUF`. O download vai para `.part`, retoma com `Range`, confere o SHA-256 e só então renomeia (`WhisperTranscriber.java:256-317`).

O prompt é fixo: `"Olá! Tudo bem? Este é um ditado em português do Brasil, com vírgulas, pontos e acentuação corretos."`; o trecho anterior (até 300 caracteres) entra como contexto para continuidade (`WhisperTranscriber.java:34-35,216-218`). O `language` é forçado para `pt` (`:215`). O dicionário é pós-processamento, não bias do modelo (`JsonDictionaryStore.java:56-72`; aplicado em `DefaultDictationEngine.java:467`).

### 2.5 Requisitos, instalação e assinatura

- macOS Apple Silicon e Intel; Windows 10/11. Compilar exige JDK 21; o app distribuído leva um runtime enxuto gerado por `jpackage`/`jlink`, então o usuário não precisa de Java (`app/build.gradle:47-76`; `THIRD_PARTY_NOTICES.md:23`).
- Permissões no macOS: Microfone, Acessibilidade e, se o sistema pedir, Monitoramento de Entrada (`docs/macos.md:33-37`). É mais uma permissão para conceder e manter.
- Instalação: `.dmg`, arrastar para Aplicativos, primeira abertura com "Abrir Mesmo Assim" — o app é assinado só ad-hoc, sem Developer ID (`docs/macos.md:10-31`; `Arara-voice/README.md:83-87`). A cada atualização a assinatura muda e pode ser preciso desligar/ligar o Arara em Acessibilidade (`docs/macos.md:66`).
- Dados em `~/Library/Application Support/Arara/` (histórico, dicionário, configurações e modelos); "Abrir ao iniciar sessão" grava `~/Library/LaunchAgents/br.arara.Arara.plist` (`docs/macos.md:70-72`).
- **Atenção:** `startWithWindows` vem `true` por padrão (`Settings.java:58-63`) e o app sincroniza o login na partida (`Startup.java:92-93`). Instalar e abrir o Arara cria um item de login por padrão; num teste ao lado do Ronaldo, isso precisa ser desligado antes.

### 2.6 Qualidade em pt-BR: o que existe e o que falta

O que o projeto oferece como argumento:

- `language=pt` forçado, porque a detecção automática erra em áudio curto (`DECISOES.md:62`).
- Prompt fixo em pt-BR para estilo, pontuação e acentuação (`WhisperTranscriber.java:34-35`).
- Dicionário de termos aplicado no texto final (`DECISOES.md:64`; `JsonDictionaryStore.java:56-72`).
- Fatiamento em pausas de 0,6 s, com alvo de 3 s para o último trecho, para não perder contexto (`DefaultDictationEngine.java:38-55`).

O que **não** existe:

- WER publicado, em pt-BR ou em qualquer idioma. Não há resultado de FLEURS, Common Voice ou comparação com Parakeet no repo.
- O harness E2E calcula WER em frases fixas (`E2E.java:198-201,893-905`), mas não há resultados versionados; e a normalização dele remove acentos (`Normalizer.Form.NFD` + remoção de marcas), então é mais leniente do que a régua proposta aqui.
- As medições nos comentários são sobre o **corte**, não sobre a qualidade absoluta: trechos de ~4 s elevam o WER de 2% para 16–70%, e de 6 s para 4–8% (`DefaultDictationEngine.java:40-49`). Isso justifica o fatiamento, mas não diz como o modelo se sai no sotaque do Guima.

Ou seja: "português de verdade" é a **meta de projeto** (`Arara-voice/README.md:26-31`), não um resultado medido. Não consegui provar que o Arara transcreve melhor que o Hex em pt-BR.

### 2.7 Latência: medido vs estimado

Medições do autor, **CPU Ryzen 5 5500**, não no M2:

- turbo (Preciso) em CPU: RTF 0,55, isto é, ~0,55 s de Whisper por segundo de áudio (`DefaultDictationEngine.java:40-42`).
- 10 s de áudio com turbo: 7,4 s com 6 threads, 5,3 s com 10, 5,2 s com 12 (`WhisperTranscriber.java:40-43`).
- 9,5 s de fala: turbo 16,5 s → 5,0 s depois do ajuste de `audioCtx` (`WhisperTranscriber.java:211-214`).
- Com prévia: texto na tela ~2 s depois de dito (p50; p90 ~3 s); sem prévia, p50 ~8,5 s (`DefaultDictationEngine.java:50-55`).

No M2 não há medição. O app tenta Metal quando não é M1 (`Gpu.java:16-37`), mas não há número de latência no Mac. O VAD por energia também foi escolhido sem medir em hardware real (`Vad.java:3-5`). O histórico do app trunca o horário para segundos (`DefaultDictationEngine.java:476`), então nem o histórico serve para medir latência fina.

Para comparar: no Hex + `parakeet_v3`, no M2, o log do Ronaldo dá p50 0,72 s / p90 1,20 s (210 ciclos; detalhes no §7). Essa é a régua que o Arara teria de bater.

### 2.8 Custo e manutenção

- Licença: MIT; terceiros: JNativeHook 2.2.2 (LGPL-3.0), whisper-jni 1.7.1 (Apache-2.0, com whisper.cpp/ggml MIT), FlatLaf 3.8 (Apache-2.0), runtime OpenJDK 21 (GPL-2.0 + CPE) (`THIRD_PARTY_NOTICES.md:9-23`; `Arara-voice/README.md:116-125`).
- Custo em dinheiro: zero. Custo em disco: 148–574 MB de modelo + o app com runtime; em RAM, não documentado e não medido.
- Manutenção: projeto de mantenedor único (o doc de inscrição lista `davimatosms` como Author, Reviewer e Approver; `docs/signpath-inscricao.md:32`), muito ativo (v0.4.3, PR #64 em 17/11/2026), mas sem contrato de CLI e com assinatura ad-hoc que muda a cada versão. Um fork para integrar seria manutenção para sempre.

## 3. Troca direta: dá para substituir o Hex?

### 3.1 Veredito

**Não como troca de peça.** O Hex é um componente com CLI; o Arara é um app completo que assume o microfone, o atalho, a transcrição, o histórico e a colagem. Para o Ronaldo usá-lo, seria preciso **dar uma interface ao Arara** (CLI/controle + modo "só transcrever, não colar") ou **automatizar a interface dele**. Nenhum dos dois é trocar um binário pelo outro.

### 3.2 O que quebra, ponto a ponto

| Ponto | O que quebra | Por quê / caminho no código |
|---|---|---|
| (a) `hexcli.py` | O Ronaldo não inicia, não para, não lê o texto, não cancela, não troca idioma | `HEX` é um caminho fixo para o binário do Hex (`hexcli.py:13`); `start`, `stop --print`, `cancel` e `model use` são chamadas de CLI (`:69-113`). O Arara não tem CLI (`Main.java:47-74`). |
| (b) `ctl.py` | `ronaldo on/off/status` não funciona | `estado()` chama `hex status --json` (`ctl.py:83-94`); `desligar()` chama `hex launch-at-login off` e `hex quit` (`:97-124`). Sem o binário, `_run` levanta `FileNotFoundError` — não há `try` em `ctl.py:33-34,85`. `ligar()` só recusa se o caminho não existe (`:127-130`). |
| (c) `install.sh` | Instalação e atualização do Ronaldo falham | Exige `/Applications/Hex.app`, confere o bundle `anomaly.hex` e roda `hex launch-at-login on` (`install.sh:11-21,70-71`). Sem Hex, sai antes de instalar. |
| (d) HUD, modo comando e atalhos | Nunca recebem texto | O texto só existe em `stop_and_transcribe()` (`hexcli.py:92-100`); sem ele, `agent.dispatch` não é chamado (`listener.py:244-262`) e o HUD não mostra transcrição. |
| (e) Colagem dupla | O texto pode ser colado duas vezes, ou nenhuma | O Arara cola sozinho com Cmd+V (`ClipboardPaster.java:23-48`); o Ronaldo também cola (`macos.py:48-59`). Se o Ronaldo for adaptado para ler o texto do Arara e continuar colando, são duas colagens; se não for, o Ronaldo não recebe nada. Não há modo "só transcrever" no Arara. |
| (f) Dois donos do microfone | Duas capturas simultâneas; texto contaminado | Hoje Hex e Ronaldo já mantêm o microfone aberto ao mesmo tempo (`README.md:41`), então o problema não é exclusividade: é coordenação. Com o Arara ao lado dos dois, seriam três capturas; no cenário sem Hex, duas — em qualquer caso, mais de uma. A fala do TTS do Ronaldo (`voz.py`) pode entrar no ditado do Arara, e vice-versa. |
| (g) Permissões e atalhos | Mais superfície e mais atrito | Hoje já são duas permissões de Acessibilidade (Hex e Ronaldo); o Arara acrescenta a dele e, se o macOS pedir, Monitoramento de Entrada (`docs/macos.md:33-37`). São três atalhos globais possíveis (Option do Hex, Ctrl+Shift+Space do Arara, cmd+D do Ronaldo) e o atalho do Arara **não engole a tecla** (`DECISOES.md:123`), então pode digitar espaço no app em foco (`Arara-voice/README.md:99-100`). |
| (h) Sem `hex transcribe`, output steps, vocabulário e histórico consultável | Perde recursos que o Ronaldo usa ou pode usar | O Arara não tem `transcribe` em lote, output steps, vocabulário/prompt configurável nem CLI de histórico. Ele tem dicionário e histórico próprios, mas só na interface. |

### 3.3 O que sobra de saída

1. **Fork do Arara com uma interface de controle.** Adicionar um modo headless com `start`/`stop`/`--print`, sem colar e sem atalho, e mapear o `hexcli.py` para ele. É o caminho tecnicamente limpo, mas é escrever e manter um fork em Java, acompanhando o upstream. Estimativa: **5–8 dias** + manutenção contínua.
2. **Automação da interface.** O Ronaldo aperta o atalho do Arara via `CGEvent`, espera e lê o clipboard. O Arara cola sozinho, então seria preciso um jeito de impedir a colagem ou de restaurar o foco; não há sinal estável de "terminei". Estimativa: **1–2 dias**, frágil, não recomendado.
3. **Arara standalone.** Usar o Arara como app de ditado e abrir mão das rotas/wake word do Ronaldo. Estimativa: **0,5 dia** de configuração, mas não é integração — é trocar de fluxo.

Em qualquer um dos caminhos, o que vira manutenção é o fork/automação; o standalone não deixa manutenção no Ronaldo, mas perde wake word, rotas, HUD e TTS integrado.

## 4. O caminho híbrido

### 4.1 Whisper turbo no Hex: instalar e usar

O catálogo do Hex **já tem** `whisper_large_v3_turbo` (886 MB, GGUF Q8_0, `vocabulary: prompt`, aceita dica de idioma; `models.rs:464-474`; `artifacts.rs:59-67`). É o mesmo modelo do Arara (large-v3-turbo), em outra quantização (Q8_0 contra Q5_0) e outro runtime (transcribe.cpp contra whisper.cpp). Instalar e usar são dois comandos:

```sh
hex model install whisper_large_v3_turbo --language pt   # baixa 886 MB e passa a usar
hex model use whisper_large_v3_turbo --language pt        # se já estiver instalado
```

O `install` baixa e troca; o `use` só troca (`cli.md:52-61,258-263`). O `stop --print` continua devolvendo o texto e o Ronaldo não muda uma linha. O rollback é um comando: `hex model use parakeet_v3 --language pt`.

O que se ganha: a dica `pt` (o v3 não aceita) e o mesmo modelo do Arara. O que **não** se ganha: o prompt fixo, o dicionário e o fatiamento do Arara — mas o Hex tem output steps, vocabulário e o próprio caminho de ditado.

### 4.2 Importar o arquivo do Arara no Hex: não

O Hex importa GGUF próprio, mas recusa o arquivo do Arara por dois motivos independentes:

1. **Formato:** os `.bin` do Arara começam com `6c 6d 67 67` (`ggml` legado); o Hex exige o magic `GGUF` nas versões 2 ou 3 e recusa o resto (`gguf_header.rs:141-152`; `own-models.md:13-31`).
2. **Quantização:** mesmo convertido para GGUF, o arquivo é Q5_0; o Hex só aceita F32, F16 e Q8_0 — K-quants (Q4_K/Q5_K/Q6_K) só no lab de macOS, e Q5_0 fica de fora em qualquer configuração (`gguf_header.rs:458`; `own-models.md:90-123`).

O que seria preciso: converter ggml → GGUF e re-quantizar para Q8_0 ou F16. Isso recria o que o Hex já baixa pronto (Q8_0), sem ganho. Conclusão: **não importe o arquivo; instale o turbo do catálogo**.

### 4.3 Levar prompt, dicionário e fatiamento do Arara para dentro do Hex: não sem escrever Rust

- **Prompt:** o Hex não tem prompt livre; o "prompt" do Whisper é o vocabulário, uma lista de termos separada por vírgulas, limitada a 500 caracteres (`vocabulary.md:77-91`; `vocabulary.rs:321-327`). Não dá para pedir "com vírgulas, pontos e acentuação corretos" por esse canal.
- **Dicionário:** o Output do Hex tem substituições de palavras e limpezas (`hex/README.md:20-25`), que fazem o mesmo tipo de coisa que o `DictionaryStore.apply` do Arara (`JsonDictionaryStore.java:56-72`). Dá para aproximar bem.
- **Fatiamento:** o Arara corta em pausas de 0,6 s e alvo de 3 s (`DefaultDictationEngine.java:38-55`); o Hex tem o caminho de ditado dele, e turbo/v3 são `streams:false` (`models.rs:438,469`). Não há botão para mudar o fatiamento.
- **Mudar o Hex:** seria um patch em Rust, e o Hex não aceita pull requests (`hex/README.md:105-108`). Vira fork/manutenção.

O que dá para fazer sem tocar no Hex: **usar o vocabulário** para os nomes e o **Output** para as substituições. O resto (estilo do prompt, fatiamento) não é replicável por configuração.

### 4.4 Fine-tune pt-BR em GGUF para importar: experimental

O Hex aceita importar um GGUF `whisper` com F32/F16/Q8_0 e o modelo aparece como `custom-…` (`own-models.md:13-31`). Em teoria, um fine-tune de Whisper large-v3-turbo em pt-BR convertido para GGUF Q8_0 seria importável. Na prática:

- Não achei modelo público validado. A busca na Hugging Face por `whisper portuguese`, `whisper-large-v3-turbo portuguese`, `whisper pt-br` e `whisper large-v3 portuguese` (17/11/2026) devolveu fine-tunes `tiny`/`small`/`base` com dezenas de downloads, e alguns `large-v3` pt-BR com 0–39 downloads; os que abri não tinham GGUF nem licença declarada.
- O próprio Hex diz que não mediu a acurácia de nenhum import (`own-models.md:122-123`).
- Fine-tune exige corpus, GPU e avaliação; não é configuração, é projeto. Não recomendo.

### 4.5 Outras opções do catálogo

O catálogo também oferece Qwen3-ASR 0.6B, Cohere Transcribe e Nemotron 3.5 ASR com `pt` na lista de idiomas (`hex model list --json`). Nenhum deles aparece na linha `pt` da tabela FLEURS do Hex (`language-recommendations.md:43`); não achei número pt para eles. O Nemotron streama, mas a doc do Hex o coloca atrás do v3 nas medições de inglês/alemão (`features/README.md:490-502`). Não entram na recomendação sem medição.

O **Parakeet Ultra**, que tem o melhor FLEURS `pt` da tabela (4,16%), não está no picker do 3.4.0. No código atual do Hex ele existe atrás do Lab `parakeet-ultra` (`labs.rs:152`; `models.rs:265-267,559-575`), e o plano o coloca na Phase B (`language-recommendations.md:17-20,178-184`). Ele também não aceita dica de idioma (`models.rs:573`), como o v3. Não consegui provar quando ele chega a um release.

## 5. Recomendação e trade-offs

### 5.1 Tabela de cenários

| Cenário | Qualidade pt-BR | Latência | Esforço | Risco | Reversibilidade | Manutenção |
|---|---|---|---|---|---|---|
| **Hex + Parakeet v3 (hoje)** | FLEURS 4,96%; sem dica de idioma (risco da #68) | p50 0,72 s / p90 1,20 s no M2 (log) | 0 | Baixo; é o que já roda | — | Hex upstream |
| **Hex + Whisper turbo** | FLEURS 4,17% vs 4,96% (dentro do ruído) + dica `pt` | Mesmo fluxo; a medir no M2 | 30–60 min + 886 MB | Baixo | `hex model use parakeet_v3` (1 comando) | Hex upstream |
| **Arara standalone** | Sem WER independente | Sem medição no M2 | 0,5 dia | Médio (mic/atalho, app sem assinatura, login item) | Fechar o app e `ronaldo on` | Projeto de uma pessoa; updates ad-hoc |
| **Motor portado no Ronaldo** | Depende do motor/modelo; a medir | Pode ser bom no Metal; a medir | 2–4 dias | Médio-alto (dependência nativa, chunking, cancel) | `git revert`; sem deploy | Você passa a dono |
| **Arara forkado com CLI** | Sem WER independente | Sem medição no M2 | 5–8 dias | Alto (fork, duplicação de colagem) | Difícil | Fork Java para sempre |

### 5.2 Recomendação

**Manter o Hex e trocar o modelo para `whisper_large_v3_turbo` no pt, depois do A/B da Fase 1.**

Por quê:

1. **É o mesmo modelo do Arara**, sem integração: o catálogo já tem o Q8_0 e o Ronaldo não muda.
2. **A dica `pt` é o ganho concreto.** O v3 não aceita dica (`models.rs:443`); o turbo aceita (`:472`). A issue #68 é o relato dessa limitação, e o próprio mantenedor do Hex recomendou o turbo para português (comentário de 03/09/2026 na issue). A doc do Hex chama o relato de "unreproduced" (`features/README.md:524-528`): é um risco documentado, não uma prova de que o Guima sofra com isso.
3. **O WER do FLEURS não decide sozinho:** 4,17 vs 4,96 é 0,79 ponto, dentro do ruído de ~1,5 ponto (`language-recommendations.md:28,43`). O A/B no sotaque do Guima é que decide.
4. **A troca é reversível em um comando** e preserva wake word, rotas, HUD, TTS, output steps e histórico.
5. **O Arara não tem interface para ser integrado** e a vantagem dele em pt-BR não está provada. O custo de integrar (5–8 dias + fork) não se paga sem uma vitória clara e reproduzível.

O que **não** fazer: não trocar o Hex pelo Arara no Ronaldo; não portar o Arara para dentro do Ronaldo; não importar o arquivo Q5_0; não fugir do A/B.

### 5.3 O que faria mudar de ideia

- O Arara ganhar de forma reproduzível do turbo no mesmo conjunto de frases, por mais de ~2 pontos de WER e com p50 ≤ 1,5 s para 10 s de fala.
- O Arara ganhar uma CLI/API estável com modo "só transcrever" (sem colar), mantida pelo upstream.
- O Hex perder o CLI ou mudar o contrato de forma incompatível (hoje é versão 4, documentado).
- Aparecer um GGUF pt-BR validado (com WER publicado e licença) que o Hex importe.

## 6. Piloto mínimo, passo a passo

### Fase 1 — A/B determinístico no Hex (30–60 min, reversível)

**Objetivo:** comparar Parakeet v3 com Whisper turbo nos **mesmos arquivos**, com o texto de referência escrito antes, e medir o WER. Depois, medir a latência fim-a-fim no uso real.

**Preparação**

1. Confirme o estado: `hex status --json` (permissões `ready`, `parakeet_v3` instalado) e espaço em disco (o turbo tem 886 MB; o Mac tem 18 GiB livres).
2. Crie uma pasta de trabalho fora do repo, por exemplo `~/ab-arara/`, com `audio/`, `v3/`, `turbo/` e `referencia.json`.
3. Escreva **antes** 20–30 frases pt-BR curtas (5–15 s), cobrindo: nomes próprios, termos técnicos, acentos, números, pontuação, uma frase longa. Grave cada frase uma vez com a sua voz, no mesmo microfone e ambiente. QuickTime (Arquivo › Nova gravação de áudio) serve; `ffmpeg -f avfoundation -i ":0"` também, se estiver instalado. O Hex lê `.m4a`, `.wav`, `.aiff`, `.flac`, `.mp3`, `.ogg`, `.webm` e `.mp4/.mov` (`cli.md:171-175`).
4. Salve as referências em `referencia.json`, no formato `{"frase-01.m4a": "texto exato do que foi dito", ...}`. Números em algarismos; acentos como você os escreveria.

**Instalar o turbo**

```sh
hex model install whisper_large_v3_turbo --language pt
hex model list --json        # confira "installed": true e "selected": true
```

**Transcrever os mesmos arquivos com os dois modelos**

```sh
cd ~/ab-arara
for f in audio/*; do
  b=$(basename "$f")
  hex transcribe "$f" --model parakeet_v3 --language pt --json > "v3/$b.json"
  hex transcribe "$f" --model whisper_large_v3_turbo --language pt --json > "turbo/$b.json"
done
```

`hex transcribe` não aplica os passos de Output, não cola e não grava histórico (`cli.md:196-200`); é o modelo cru, que é o que o A/B quer. Com o Hex parado, ele sobe um serviço embutido e funciona igual (`cli.md:182-192`).

**Calcular o WER**

Normalização declarada: minúsculas; pontuação removida; espaços colapsados; **acentos mantidos** (acento errado conta); números escritos em algarismos. WER = (substituições + inserções + deleções) ÷ palavras da referência, por frase e no total (soma das distâncias ÷ soma das palavras).

```python
import glob, json, os, re

ref = json.load(open("referencia.json"))

def words(s):
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)  # mantém letras (com acento) e dígitos
    return re.sub(r"\s+", " ", s).strip().split()

def distance(a, b):
    d = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        prev, d[0] = d[0], i
        for j, y in enumerate(b, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (x != y))
    return d[-1]

for model in ("v3", "turbo"):
    errors = total = 0
    for path in sorted(glob.glob(f"{model}/*.json")):
        name = os.path.basename(path)[:-5]
        hyp = json.load(open(path)).get("text")
        if hyp is None:
            print(f"{model} {name}: SEM TEXTO (no-speech ou erro)"); continue
        r, h = words(ref[name]), words(hyp)
        errors += distance(r, h); total += len(r)
        print(f"{model} {name}: {distance(r, h) / len(r):.1%}")
    print(f"{model} TOTAL: {errors / total:.2%} ({errors}/{total})")
```

**Critério de sucesso (numérico)**

- WER do turbo **≤** WER do v3 no mesmo conjunto, **e**
- latência p50 **≤ 1,5 s** para ~10 s de fala, medida no uso real (abaixo).
- Se o turbo for **> 1 ponto** pior no WER, não troque; se ficar dentro de ±1 ponto, decida pela dica `pt` e pela latência.

Com 20–30 frases, uma diferença de ~1 ponto não é estatisticamente significativa; o piloto serve para detectar diferença grande ou regressão óbvia, não para declarar um vencedor por pouco.

**Latência no uso real**

Depois de escolher o turbo, dite normalmente por um dia e leia o log:

```sh
grep -E 'gravando…|fim da gravação|colando [0-9]+ caracteres' ~/Library/Logs/ronaldo.log
```

O pareamento é: `gravando…` → `fim da gravação: silence` → `colando N caracteres` **imediatamente depois**. Fala estimada = (fim − gravando) − 2,0 s (o `silence_seconds`); latência = colando − fim. Use só pares consecutivos, descarte durações fora de 2–30 s e compare o subconjunto de 8–12 s. O log não guarda a transcrição (guarda o tamanho e o resultado da rota); é para latência, **não** para WER.

**Rollback:** `hex model use parakeet_v3 --language pt` (o v3 já está instalado).

**Não faça:** não desinstale o Hex; não mexa no `install.sh`; não deixe os dois modelos "selecionados" ao mesmo tempo; não use o log para WER; não trate 20–30 frases como benchmark conclusivo (é indicativo).

### Fase 2 — Arara standalone com as mesmas frases (opcional, 1–2 h)

**Objetivo:** ver se o app Arara, no M2, ganha do turbo do Hex no mesmo tipo de frase. Sem integrar nada.

1. `ronaldo off` — isso **não é pausa**: desliga o LaunchAgent do Ronaldo, desliga o login do Hex e fecha o Hex (`ctl.py:97-124`). O rollback é `ronaldo on` (`ctl.py:127-144`).
2. Instale o `.dmg` do Arara, arraste para Aplicativos, abra com "Abrir Mesmo Assim" e conceda Microfone + Acessibilidade (e Monitoramento de Entrada, se pedir). **Desligue "Abrir ao iniciar sessão"** antes de qualquer teste: o padrão é ligado e grava um LaunchAgent (`Settings.java:58-63`; `Startup.java:92-93`).
3. Deixe o modelo no Preciso (turbo, 574 MB, padrão) e dite as **mesmas 20–30 frases**, na mesma ordem, no mesmo microfone/ambiente, colando num editor descartável. O Arara não tem entrada em lote: você fala de novo, não reusa os arquivos. Isso enfraquece a comparação; trate como indicativo.
4. Calcule o WER com a mesma normalização e o mesmo script (salvando as hipóteses em `arara/*.json` ou `.txt`). A latência não tem log: meça com cronômetro ou gravação de tela, do segundo toque (fim) até o texto aparecer; o histórico só guarda segundos (`DefaultDictationEngine.java:476`).
5. **Critério:** WER do Arara ≤ WER do turbo do Hex + 1,0 ponto **e** p50 ≤ 1,5 s para 8–12 s de fala. Se não bater, não siga.
6. **Rollback:** feche o Arara, desligue o item de login, rode `ronaldo on`; apague o app/modelos se quiser. Não é um comando.

**Não faça:** não deixe o Arara e o Ronaldo com atalhos globais ao mesmo tempo; não rode os dois no mesmo teste; não deixe o login do Arara ligado; não desinstale o Hex para "testar" (o `ronaldo off` já basta).

### Fase 3 — Spike de motor portátil no Ronaldo (só se as duas falharem; 2–4 dias)

O listener já recebe os blocos de áudio de 80 ms para o VAD (`listener.py:147-151,157-180`). Dá para guardar uma cópia do áudio durante `_record_until_silence` e, no fim, chamar um whisper.cpp/MLX local em vez de `hexcli.stop_and_transcribe()` (`listener.py:244`). O resto (wake word, rotas, HUD, TTS) fica.

O que fazer: buffer de até 60 s; download/verificação do modelo; prompt/continuidade entre trechos (a ideia do Arara); chunking; dicionário; cancelamento; testes; medição. Estimativa **2–4 dias**.

**Critério:** WER dentro de 0,5 ponto do turbo do Hex no mesmo conjunto; p50 ≤ 1,5 s para 8–12 s; wake word sem regressão de RAM/CPU (o README fala de ~80 MB e ~4% de um núcleo; confira com `tools/live_test.py`).

**Rollback:** `git revert` do spike; nada vai para deploy sem revisão.

**Não faça:** não mexa no `install.sh`; não remova o Hex; não faça merge sem parecer.

## 7. Evidências e limites

### 7.1 Comandos e saídas usados

Leitura remota no Mac, só read-only:

```sh
hex status --json
# app_version 3.4.0; model parakeet_v3/language pt; permissions.ready true;
# memory_footprint_bytes 201115352; labs ["vocabulary-biasing"]

hex model list --json
# parakeet_v3: 739 MB, installed true, selected true
# whisper_large_v3_turbo: 886 MB, installed false, selected false
# parakeet_ultra: ausente

hex settings list --json
# 137 chaves; transcription.model=parakeet_v3; transcription.language=pt;
# dictation_hotkey=option; shortcut_mode=hold;
# release_microphone_while_idle=false; history_retention=week
```

Máquina e log:

```sh
uname -m                      # arm64
sysctl -n machdep.cpu.brand_string   # Apple M2
sysctl -n hw.memsize          # 17179869184 (16 GB)
sw_vers -productVersion       # 26.6.2
df -h /                       # 18Gi disponíveis
grep -E 'gravando…|fim da gravação|colando [0-9]+ caracteres' ~/Library/Logs/ronaldo.log
# 247 ciclos completos; 210 com fala estimada entre 2 e 30 s;
# p50 0,72 s; p90 1,20 s; 8–12 s (n=44): p50 0,68 s; p90 0,76 s
```

Método do log: pareamento consecutivo `gravando…` → `fim da gravação: silence` → `colando N caracteres`; fala = (fim − gravando) − 2,0 s; latência = colando − fim. Exclui o Cmd+V em si e não normaliza por duração. O modelo de cada ciclo não é registrado; o modelo de hoje é `parakeet_v3`. A janela analisada vai de 05/11/2026 a 17/11/2026.

Arquivos do Arara na Hugging Face (Range de 16 bytes):

```sh
curl -r 0-15 https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-large-v3-turbo-q5_0.bin
# 6c 6d 67 67 ...  (magic "ggml", não "GGUF")
# content-range: bytes 0-15/574041195
# base: 147951465; small: 487601967
```

Issue #68 (API do GitHub):

```sh
# state closed; título "Parakeet v3 often tries to transcribe in English instead of Portuguese"
# comentário do mantenedor (03/09/2026): o v3 não usa a dica; sugeriu Whisper large-v3-turbo
```

### 7.2 O que não consegui provar

- WER do Arara em pt-BR (ou em qualquer idioma).
- Latência do Arara no M2; só existe medição do autor em CPU Ryzen 5 5500.
- RAM do Arara; não é documentada nem medida.
- Se o `q5_0` do Arara é pior que o `Q8_0` do Hex no sotaque do Guima; nenhum dos dois foi medido com a voz dele.
- WER e latência do turbo no M2; o A/B da Fase 1 é que produz.
- Se a issue #68 afeta o Guima; não houve reprodução com áudio dele.
- Quando o Parakeet Ultra chega ao release; no 3.4.0 ele não está no picker, e o plano o coloca na Phase B.
- Se o `ffmpeg` está instalado no Mac; não verifiquei.
- Se dois apps disputando o microfone se atrapalham na prática; não testei. Hoje Hex e Ronaldo já convivem com o microfone aberto, mas isso não prova o caso com o Arara.
- Se o prompt fixo do Arara muda o resultado no sotaque do Guima; não há medição.
- Se as substituições do Output do Hex cobrem o dicionário do Arara em todos os casos; são mecanismos parecidos, não idênticos.

### 7.3 Ambiente

Mac Apple M2, 16 GB, macOS 26.6.2, 18 GiB livres; Hex 3.4.0 (`parakeet_v3`, `pt`, footprint 201 MB); Ronaldo `b4116bc` (main, log ativo em 17/11/2026); Hex no código `94cbe24`; Arara `12da477` (v0.4.3). Testes do Ronaldo: `uv run pytest -q` → 238 passed, 12 skipped (nenhum código foi alterado; a suíte foi rodada por completude).

Clones de leitura em `/tmp/opencode/hex` e `/tmp/opencode/Arara-voice`; o repo de produção do Ronaldo foi lido localmente; o Mac foi acessado só com `hc exec` read-only (`hex status`, `hex model list`, `hex settings list`, `cat` do config e `tail`/grep do log). Nada foi instalado, alterado ou desinstalado no Mac.

## 8. Fontes

**Hex**

- Repositório: <https://github.com/anomalyco/hex> (commit `94cbe24`).
- CLI e contrato: `docs/cli.md` (comandos, códigos de saída, transporte, versão 4).
- Modelos próprios e GGUF: `docs/features/own-models.md`; `src/transcription/gguf_header.rs`.
- Recomendações por idioma e FLEURS: `docs/plans/language-recommendations.md`.
- Vocabulário/prompt: `docs/features/vocabulary.md`; `src/dictation/vocabulary.rs`.
- Modelos e rotas: `src/transcription/models.rs`; `src/transcription/artifacts.rs`.
- Limitação do v3 em português e issue #68: `docs/features/README.md:504-528`; <https://github.com/anomalyco/hex/issues/68>.
- Runtime: <https://github.com/handy-computer/transcribe.cpp>.

**Arara-voice**

- Repositório: <https://github.com/davimatosms/Arara-voice> (commit `12da477`, v0.4.3).
- Decisões e fluxo: `DECISOES.md`.
- macOS, permissões e assinatura: `docs/macos.md`.
- Código: `core/src/main/java/br/arara/core/{WhisperTranscriber,DefaultDictationEngine,Vad,Gpu,ClipboardPaster,JsonDictionaryStore,Settings,Startup}.java`; `app/src/main/java/br/arara/app/Main.java`.
- Terceiros e licenças: `THIRD_PARTY_NOTICES.md`.
- Modelos: <https://huggingface.co/ggerganov/whisper.cpp/tree/5359861c739e955e79d9a303bcbc70fb988958b1>.
- whisper-jni: <https://github.com/GiviMAD/whisper-jni>.

**Ronaldo**

- Repositório: <https://github.com/guim4dev/ronaldo> (commit `b4116bc`).
- CLI do Hex: `ronaldo/hexcli.py`; ciclo e rotas: `ronaldo/listener.py`; agente: `ronaldo/agent.py`.
- Ligar/desligar: `ronaldo/ctl.py`, `install.sh`; colagem: `ronaldo/macos.py`; TTS: `ronaldo/voz.py`.
- Requisitos e configuração: `README.md`.
