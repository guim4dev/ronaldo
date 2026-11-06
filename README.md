# Ronaldo

Ditado mãos-livres para macOS em cima do [Hex](https://hex.kitlangton.com): você fala uma wake word, fala o que quiser e faz uma pausa. Conforme a palavra, o texto é **digitado no app em foco** (com Enter) ou **enviado para um agente** (Claude Code, Codex, Hermes…), e a resposta do agente aparece como notificação.

```
"Ronaldo"  →  hex dictation start  →  você fala  →  ~2 s de silêncio  →  hex dictation stop --print  →  cola + Enter
```

- **Tudo local.** A wake word roda com [openWakeWord](https://github.com/dscripka/openWakeWord) e a detecção de fim de fala com o [Silero VAD](https://github.com/snakers4/silero-vad). A transcrição é a do próprio Hex.
- **Leve.** São ~80 MB de RAM e ~4% de um núcleo de CPU ouvindo. O pipeline do openWakeWord foi reimplementado só com `onnxruntime` ([`ronaldo/detector.py`](ronaldo/detector.py)), sem scipy/sklearn, que custavam +150 MB. Os testes provam que as notas são idênticas às da biblioteca original.
- **Sobe sozinho.** Um LaunchAgent inicia no login e reinicia se cair. O instalador liga o "abrir no login" do Hex, e o Ronaldo abre o Hex se ele não estiver rodando.

## Instalar

Requisitos: macOS, [Hex](https://hex.kitlangton.com) em `/Applications`, [`uv`](https://docs.astral.sh/uv/) e Xcode Command Line Tools (`clang`).

```sh
./install.sh
```

Na primeira vez, libere em **Ajustes do Sistema → Privacidade e Segurança**:
- **Microfone** para "Ronaldo" (aparece um pop-up).
- **Acessibilidade** para "Ronaldo" (para colar e dar Enter).

Depois, reinicie o serviço: `launchctl kickstart -k gui/$(id -u)/dev.guima.ronaldo`.

As permissões ficam no `~/Applications/Ronaldo.app`, um executável mínimo em C ([`macos/launcher.c`](macos/launcher.c)) que inicia o Python como processo filho. Assim o acesso a microfone e teclado fica com o "Ronaldo", não com qualquer script `python3` da máquina.

Desinstalar: `./uninstall.sh`.

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
command = ["claude", "-p", "--dangerously-skip-permissions", "{text}"]
# command = ["codex", "exec", "{text}"]
# command = ["hermes", "chat"]          # sem {text}: o texto vai pelo stdin
# notify = true                        # resposta do agente vira notificação
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

Reinicie após mudar: `launchctl kickstart -k gui/$(id -u)/dev.guima.ronaldo`.

## Ver funcionando

```sh
tail -f ~/Library/Logs/ronaldo.log                   # o que o serviço está fazendo
uv run python tools/live_test.py 20                  # nota da wake word ao vivo + RAM
uv run python tools/live_test.py 20 models/extra/wall-e.onnx
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
