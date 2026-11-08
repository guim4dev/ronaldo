# Ronaldo

Ditado mãos-livres para macOS em cima do [Hex](https://hex.kitlangton.com): você fala uma wake word, fala o que quiser e faz uma pausa. Conforme a palavra, o texto é **digitado no app em foco** (com Enter) ou **enviado para um agente** (Claude Code, Codex, Hermes…), e a resposta do agente aparece como notificação.

```
"Ronaldo"  →  hex dictation start  →  você fala  →  ~2 s de silêncio  →  hex dictation stop --print  →  cola + Enter
```

- **Tudo local.** A wake word roda com [openWakeWord](https://github.com/dscripka/openWakeWord) e a detecção de fim de fala com o [Silero VAD](https://github.com/snakers4/silero-vad). A transcrição é a do próprio Hex.
- **Leve.** São ~80 MB de RAM e ~4% de um núcleo de CPU ouvindo. O pipeline do openWakeWord foi reimplementado só com `onnxruntime` ([`ronaldo/detector.py`](ronaldo/detector.py)), sem scipy/sklearn, que custavam +150 MB. Os testes provam que as notas são idênticas às das da biblioteca original.
- **Sobe sozinho.** Um LaunchAgent inicia no login e reinicia se cair. O instalador liga o "abrir no login" do Hex, e o Ronaldo abre o Hex se ele não estiver rodando.

## Instalar

Requisitos: macOS, [Hex](https://hex.kitlangton.com) em `/Applications`, [`uv`](https://docs.astral.sh/uv/) e Xcode Command Line Tools (`clang`).

```sh
./install.sh
```

O LaunchAgent usa o label `io.github.ronaldo`. Para instalar com outro label, defina `RONALDO_LABEL`:

```sh
RONALDO_LABEL=dev.exemplo.ronaldo ./install.sh
```

Na primeira vez, libere em **Ajustes do Sistema → Privacidade e Segurança**:
- **Microfone** para "Ronaldo" (aparece um pop-up).
- **Acessibilidade** para "Ronaldo" (para colar e dar Enter).

Depois, reinicie o serviço: `launchctl kickstart -k gui/$(id -u)/${RONALDO_LABEL:-io.github.ronaldo}`.

As permissões ficam no `~/Applications/Ronaldo.app`, um executável mínimo em C ([`macos/launcher.c`](macos/launcher.c)) que inicia o Python como processo filho. Assim o acesso a microfone e teclado fica com o "Ronaldo", não com qualquer script `python3` da máquina.

Desinstalar: `./uninstall.sh`. O script usa `RONALDO_LABEL` se estiver definido; senão lê o `CFBundleIdentifier` do app instalado; senão usa o label padrão.

## Ligar e desligar

O Ronaldo e o Hex deixam o microfone aberto o tempo todo. Para parar os dois, inclusive depois de um novo login, e depois voltar:

```sh
ronaldo off      # para o Ronaldo e fecha o Hex; nenhum dos dois sobe no login
ronaldo on       # liga os dois de novo
ronaldo status   # o que está rodando (o padrão, sem argumento)
```

Se o Hex já estiver fechado, `ronaldo off` não o abre para evitar ligar o microfone; a abertura dele no login fica como estava.

O `install.sh` coloca `ronaldo` e `ronaldo-voz` em `~/.local/bin`. Se essa pasta não estiver no `PATH` do teu shell, ele avisa a linha para pôr no `~/.zshrc` ou no `~/.bashrc`.

## Configurar

`~/.config/ronaldo/config.toml`. Cada **rota** liga uma wake word a uma ação, e dá pra ter quantas quiser:

```toml
# Palavra 1: digita no app em foco + Enter
[[routes]]
model = "extra/wall-e.onnx"   # arquivo em models/ ou caminho absoluto
action = "type"
# press_enter = true
# threshold = 0.5

# Palavra 2: manda o texto pra um agente qualquer (fire-and-forget)
[[routes]]
model = "ronaldo_ptbr.onnx"
action = "command"
command = ["meu-agente", "ask", "{text}"]
# command = ["meu-agente", "chat"]      # sem {text}: o texto vai pelo stdin
# notify = true                         # resposta do agente vira notificação
# timeout_seconds = 900

# Globais (opcionais)
silence_seconds = 2.0     # silêncio que encerra o ditado
no_speech_seconds = 6.0   # desiste se nada for dito após a wake word
max_seconds = 60.0        # limite por ditado
vad_threshold = 0.5
cooldown_seconds = 1.5
language = "auto"         # idioma da transcrição no Hex; "auto" = idioma do macOS (pt-BR → pt)
```

Nas rotas de comando, o HUD flutuante mostra a transcrição, o resultado e falhas sem tirar o foco da janela atual. Desative por rota com `hud = false`.

**Rotas de agente:** o comando roda em segundo plano (a escuta não para), no diretório home e com o `PATH` do teu shell de login. O texto entra no lugar de `{text}`, como argumento separado (sem passar por shell) ou, sem placeholder, pelo stdin, e também fica em `$RONALDO_TEXT`. O que o comando imprimir vira uma notificação do macOS ("Ronaldo · <rota>"), e falhas e timeouts também viram notificação. Que permissões o agente tem é decisão tua, definida no próprio comando. Dica: peça ao agente pra responder em uma frase curta, porque a resposta vira push.

Antes de cada ditado o Ronaldo confere o idioma do Hex e corrige se alguém tiver mudado.

Reinicie após mudar: `launchctl kickstart -k gui/$(id -u)/${RONALDO_LABEL:-io.github.ronaldo}`.

## Modo voz

O agente pode responder **falando**. Ligue e desligue por voz ("Ronaldo, modo voz", "liga o modo tts", "liga a voz" / "Ronaldo, modo texto", "desliga o modo fala", "desliga a voz"; só fala curta, até 5 palavras) ou pela CLI:

```sh
ronaldo-voz on       # liga
ronaldo-voz off      # desliga e para a fala atual
ronaldo-voz status
ronaldo-voz falar "teste do motor"   # fala direto, sem passar pelo agente
```

O estado fica em `~/.config/ronaldo/modo-voz.json` (`{"ligado": true}`) e é lido a cada uso. Só rotas `command` com `voz = true` entram no modo voz; as outras continuam como antes.

Os comandos do modo voz vêm da seção `[voz]`:

```toml
[[routes]]
model = "ronaldo_ptbr.onnx"
action = "command"
command = ["meu-agente", "ask", "{text}"]   # rota normal, modo voz desligado
voz = true

[voz]
enviar   = ["meu-agente", "ask", "--id", "{id}", "--json", "--", "{text}"]
resposta = ["meu-agente", "status", "--canal", "{canal}", "{id}", "--json"]
enviado  = "Enviado ({canal})."             # opcional; padrão "Enviado."
ligado   = "As respostas vão ser faladas."  # opcional
motores  = ["wyoming://servidor:10201#kokoro:voz-a", "say:Luciana"]
volume   = 0.3                              # afplay -v
```

- `enviar` roda com um `{id}` novo (uuid hex) e o `{text}`. Sem `{text}`, o texto vai pelo stdin. Precisa sair 0 e imprimir um objeto JSON com `"ok": true`.
- Cada campo string desse JSON (ex.: `canal`) vira placeholder para `resposta` e para `enviado`.
- `resposta` roda a cada segundo e devolve `{"estado": "pronta", "texto": "...", "em": <epoch>}`. Quando o estado é `pronta`, o texto é falado uma vez.
- Placeholder sem valor em `resposta` faz o envio falhar na hora, com mensagem clara.
- Rota `voz = true` sem `enviar` e `resposta` é erro de config no load.

Cada id falado fica em `~/.config/ronaldo/falados.json` (últimos 500), então reiniciar não repete resposta.

A wake word para a fala na hora, e nada fala enquanto o ditado está gravando. Sem `[voz]`, a cadeia de motores é `["say:Luciana"]`. Cada motor tem 4 s para sintetizar; se falhar ou estourar, o próximo entra. `say:<Voz>` usa o `say` do macOS; `wyoming://host:porta#voz` usa um servidor Wyoming (Kokoro/Piper) e escreve um WAV temporário tocado com `afplay`.

## Atalhos

Atalho liga palavras a um `comando`, sem passar pelo agente nem pelo modo voz.

Sem `{text}`, o atalho só vale em fala curta: até `max_palavras` palavras depois do nome (padrão 5). `~` é expandido e o comando roda sem esperar; trocar o arquivo no caminho troca o som, sem reiniciar.

```toml
[[routes.atalhos]]
palavras = ["musica"]
comando = ["/usr/bin/afplay", "-v", "0.6", "~/Music/favorita.wav"]
nome = "musica"
```

Com `{text}`, o resto da frase vai no lugar do placeholder, sem limite de palavras. O comando roda esperando (teto de 15 s): saída 0 é entrega, 75 é "sem confirmação" (aviso), estourar o teto também conta como "sem confirmação" (o comando pode ter entregado) e qualquer outra é falha. A 1ª linha do stdout (ou do stderr na falha) vira a mensagem do HUD. Resto vazio falha com "nada pra mandar".

```toml
[[routes.atalhos]]
palavras = ["agente"]
comando = ["~/bin/meu-agente", "prompt", "{text}"]
nome = "agente"
```

Com `qualquer_posicao = true`, o atalho de comando curto dispara com qualquer fala curta que **contenha** uma das palavras, em qualquer posição, inclusive esticada ("do gol porra", "que golaço", "goool!"). `qualquer_posicao` não vale para comando com `{text}`.

## Ver funcionando

```sh
tail -f ~/Library/Logs/ronaldo.log                   # o que o serviço está fazendo
uv run python tools/live_test.py 20                  # nota da wake word ao vivo + RAM
uv run python tools/live_test.py 20 models/extra/wall-e.onnx
uv run python tools/voz_prova.py --texto "teste"     # envia e espera a resposta pelo [voz]
uv run pytest                                        # testes
```

## Modelos

Os modelos prontos de "Ronaldo" que existem são treinados com pronúncia em inglês e não reconhecem um brasileiro falando (nota máxima de 0,12 com voz real). Por isso o `ronaldo_ptbr.onnx` é treinado para este projeto com vozes sintéticas pt-BR. Alternativas prontas que funcionam razoavelmente com voz brasileira ficam em `models/extra/` (`wall-e`, `hey_zelda`). O `ronaldo_ptbr.onnx` é aberto sob CC BY-NC-SA 4.0 (uso não-comercial, mesma licença dos modelos do openWakeWord dos quais ele depende). Licenças de cada modelo em [`models/LICENSES.md`](models/LICENSES.md).

## Licença

Código: [MIT](LICENSE). Modelos: ver [`models/LICENSES.md`](models/LICENSES.md).

## Cuidados

- O Enter vai para **qualquer** app em foco. No Slack, por exemplo, a mensagem é enviada na hora. Para só colar, use `press_enter = false`.
- Uma rota de agente com permissão total executa o que for dito, e também o que um disparo falso, um vídeo tocando ou outra pessoa no cômodo disserem. Escolha as permissões do comando com isso em mente.
- A área de transferência é restaurada depois de colar, mas só se continha texto.
