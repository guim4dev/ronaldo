# Ronaldo

Ditado mãos-livres para macOS em cima do [Hex](https://hex.kitlangton.com): você fala **"Ronaldo"**, fala o que quiser e faz uma pausa. O Hex transcreve, o texto é colado no app em foco e o Enter é pressionado.

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

`~/.config/ronaldo/config.toml` (todas as chaves são opcionais):

```toml
model = "ronaldo_ptbr.onnx"   # arquivo em models/ ou caminho absoluto
threshold = 0.5               # nota mínima da wake word
silence_seconds = 2.0         # silêncio que encerra o ditado
no_speech_seconds = 6.0       # desiste se nada for dito após a wake word
max_seconds = 60.0            # limite por ditado
vad_threshold = 0.5
press_enter = true
cooldown_seconds = 1.5
```

Reinicie após mudar: `launchctl kickstart -k gui/$(id -u)/dev.guima.ronaldo`.

## Ver funcionando

```sh
tail -f ~/Library/Logs/ronaldo.log                   # o que o serviço está fazendo
uv run python tools/live_test.py 20                  # nota da wake word ao vivo + RAM
uv run python tools/live_test.py 20 models/extra/wall-e.onnx
uv run pytest                                        # testes
```

## Modelos

Os modelos prontos de "Ronaldo" que existem são treinados com pronúncia em inglês e não reconhecem um brasileiro falando (nota máxima de 0,12 com voz real). Por isso o `ronaldo_ptbr.onnx` é treinado para este projeto com vozes sintéticas pt-BR. Alternativas prontas que funcionam razoavelmente com voz brasileira ficam em `models/extra/` (`wall-e`, `hey_zelda`). Licenças em [`models/LICENSES.md`](models/LICENSES.md).

## Cuidados

- O Enter vai para **qualquer** app em foco. No Slack, por exemplo, a mensagem é enviada na hora. Para só colar, use `press_enter = false`.
- A área de transferência é restaurada depois de colar, mas só se continha texto.
