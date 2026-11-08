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

## Modo voz

O rei pode responder **falando**, se o `corte` souber devolver a resposta. Ligue e
desligue por voz ("Ronaldo, modo voz", "liga o modo tts", "liga a voz" / "Ronaldo, modo texto",
"desliga o modo fala", "desliga a voz"; só fala curta, até 5 palavras) ou pela CLI:

```sh
ronaldo-voz on       # liga
ronaldo-voz off      # desliga e para a fala atual
ronaldo-voz status
ronaldo-voz falar "teste do motor"   # fala direto, sem passar pelo rei
```

O estado fica em `~/.config/ronaldo/modo-voz.json` (`{"ligado": true}`) e é lido a cada
uso. Só rotas `command` com `voz = true` entram no modo voz; as outras continuam como
antes. Com o modo ligado, a rota chama `corte falar --id <uuid> --json -- <texto>` e um
Falador consulta `corte --reino <k> resposta <id> --json` a cada segundo; quando a
resposta fica `pronta`, ele fala uma vez. Cada id falado fica em
`~/.config/ronaldo/falados.json` (últimos 500), então reiniciar não repete resposta.

A wake word para a fala na hora, e nada fala enquanto o ditado está gravando. A cadeia de
motores e o volume vêm de `[voz]` no `config.toml`:

```toml
[[routes]]
model = "ronaldo_ptbr.onnx"
action = "command"
command = ["/Users/guima/.local/bin/corte", "falar", "{text}"]
voz = true

[voz]
motores = ["wyoming://omarchy:10201#kokoro:pm_alex", "wyoming://omarchy:10200#pt_BR-faber-medium", "say:Luciana"]
volume = 0.3   # afplay -v
```

Sem `[voz]`, a cadeia é `["say:Luciana"]`. Cada motor tem 4 s para sintetizar; se falhar
ou estourar, o próximo entra. `say:<Voz>` usa o `say` do macOS; `wyoming://host:porta#voz`
usa um servidor Wyoming (Kokoro/Piper) e escreve um WAV temporário tocado com `afplay`.

## Grito de gol

**Experimental: `gol_grito.onnx` não é recomendado para uso.** O modelo cumpre 1/3 metas, acerta 43,8% no limiar 0,9 e detectou 0/17 gritos humanos reais. Não habilite a rota até um modelo cumprir as metas e passar pela aceitação ao vivo (`tools/grito_ao_vivo.py`).

Uma rota `action = "som"` toca um som local quando o modelo ouve o grito — sem "Ronaldo", sem Hex e
sem passar pelo modo voz. O comando roda sem esperar e `~` é expandido em cada argumento.

```toml
[[routes]]
model = "gol_grito.onnx"
action = "som"
command = ["/usr/bin/afplay", "-v", "0.6", "~/Music/Reino/gol-rematch.wav"]
threshold = 0.9
intervalo_seconds = 8
grito_db_acima = 10
```

O portão de volume só libera quando o pico do RMS dos últimos ~1 s fica `grito_db_acima` dB acima da
mediana da fala normal dos últimos ~5 min. Sem 20 s de fala acumulada não há referência e nada
dispara: não existe piso absoluto, então cada boot recalibra. Se o ganho do microfone mudar mais de
6 dB, a referência é invalidada e o log mostra `referência de grito recalibrando`; são precisos 20 s
de fala nova. Nada é gravado em disco. `intervalo_seconds` limita novos disparos da mesma rota; as
outras rotas continuam ouvindo, e um disparo não aplica o `cooldown_seconds` global.

O som para na hora quando começa um ditado ("Ronaldo"), antes do Hex. O Falador espera o som acabar
antes de falar uma resposta pronta, mas um som que dispara durante uma fala não interrompe a fala.

Para calibrar sem gravar nem tocar nada:

```sh
uv run python tools/grito_ao_vivo.py 60                 # modelo da rota som do config
uv run python tools/grito_ao_vivo.py 60 models/gol_grito.onnx
```

Ele imprime nota, nível e referência e diz `DISPARARIA` quando o portão libera. O
`tools/live_test.py` também mostra nível dBFS e referência por linha.

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

Atalhos podem encaminhar uma frase iniciada por uma palavra configurada para um terminal Hex dedicado:

```toml
[[routes.atalhos]]
palavras = ["batuqueiro"]
terminal = "batuqueiro"
nome = "batuqueiro"
```

Ou rodar um comando local, sem passar pelo agente nem pelo modo voz (ex.: tocar um som). Atalho com
`comando` só vale em fala curta: até `max_palavras` palavras depois do "Ronaldo" (padrão 5). `~` é expandido
e o comando roda sem esperar; trocar o arquivo no caminho troca o som, sem reiniciar.

```toml
[[routes.atalhos]]
palavras = ["gol gol gol", "golaço", "gol"]
comando = ["/usr/bin/afplay", "-v", "0.6", "~/Music/Reino/gol-rematch.wav"]
nome = "gol"
```
