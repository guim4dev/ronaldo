# Piloto A/B de transcrição pt-BR — material da Fase 1

Material para comparar, **nos mesmos áudios**, o `parakeet_v3` (o que o Hex usa hoje no Ronaldo) com o
`whisper_large_v3_turbo` (o mesmo modelo do Arara), e medir o WER de cada um no sotaque do Guima.

Isto é o material da Fase 1 do piloto descrito em
[`../avaliacao-arara-voice.md`](../avaliacao-arara-voice.md). Ele **não decide** nada sozinho: produz números
para a decisão.

## O que este material NÃO faz

- Não instala modelo (`hex model install`) e não troca o modelo selecionado (`hex model use`).
- Não muda settings, atalho global, LaunchAgent, microfone ou qualquer estado do Hex.
- Não toca no fluxo do Ronaldo: nenhum arquivo do Ronaldo é alterado por gravar, transcrever ou calcular.
- Não manda áudio para lugar nenhum: tudo local.

O `hex transcribe --model <id>` usa o modelo **daquela execução**; ele não troca o modelo selecionado no app
(`hex model use` é outro comando). O `capturar.sh` se recusa a rodar com modelo não instalado justamente para
não instalar nada por acidente.

## Pré-requisitos

- Hex 3 ou mais novo em `/Applications` (o caminho do CLI é `/Applications/Hex.app/Contents/MacOS/hex`).
- `parakeet_v3` instalado (é o de hoje).
- `whisper_large_v3_turbo` instalado **quando o Guima autorizar** — a instalação baixa 886 MB e **troca o
  modelo selecionado**; não é parte deste material.
- Python 3 (o `wer.py` só usa a biblioteca padrão).
- Um microfone e um lugar silencioso.

## 1. Gravar as frases (uma vez)

As 24 frases estão em [`frases.json`](frases.json); a versão para ler em voz alta está em
[`frases.md`](frases.md). A referência é o campo `texto`, escrito **antes** de gravar.

1. Crie a pasta de trabalho **fora do repo** (o áudio tem a sua voz; não vai para o GitHub):
   `mkdir -p ~/ab-arara/audio`
2. Grave **um arquivo por frase**, com o nome do `id`: `f01.m4a`, `f02.m4a`, …, `f24.m4a`.
   QuickTime (Arquivo › Nova gravação de áudio) serve; `ffmpeg -f avfoundation -i ":0"` também.
3. Mesmo microfone, mesma sala, mesma distância, nas 24. Um segundo de silêncio antes e depois.
4. Leia **exatamente** o texto da referência. Se errar, regrave o arquivo inteiro; não edite o texto depois.
5. Não use o ditado do Ronaldo/Hex para gravar: o áudio tem que ser cru e igual para os dois modelos.

Conferir se não falta nada:

```sh
cd ~/ab-arara/audio && for i in $(seq -w 1 24); do ls f$i.* >/dev/null 2>&1 || echo "falta f$i"; done
```

## 2. Transcrever com cada modelo

O `capturar.sh` lê o áudio, chama `hex transcribe` e grava um JSON por frase (a chave `text` é a hipótese).

```sh
cd ~/Projects/Personal/worktrees/piloto-ab-turbo   # checkout da branch piloto/ab-turbo
mkdir -p ~/ab-arara/v3 ~/ab-arara/turbo

# parakeet_v3: sem --idioma, porque ele não aceita dica e detecta sozinho
tools/piloto/capturar.sh --modelo parakeet_v3 \
  --audio ~/ab-arara/audio --saida ~/ab-arara/v3

# whisper turbo: com --idioma pt, que é o ganho que estamos testando
tools/piloto/capturar.sh --modelo whisper_large_v3_turbo --idioma pt \
  --audio ~/ab-arara/audio --saida ~/ab-arara/turbo
```

Antes de rodar de verdade, `--seco` mostra os comandos sem executar. O script grava um `manifest.json` em cada
pasta com o modelo, o idioma e a versão do Hex.

## 3. Calcular o WER

```sh
tools/piloto/wer.py --frases docs/piloto/frases.json \
  --modelo v3=~/ab-arara/v3 \
  --modelo turbo=~/ab-arara/turbo \
  --markdown ~/ab-arara/wer.md \
  --json ~/ab-arara/wer.json
```

O script imprime a tabela no terminal e grava as cópias. `--permitir-faltando` avalia só as frases que têm
hipótese (o padrão falha se faltar alguma, para não comparar conjuntos diferentes).

### Fórmula

```
WER da frase   = (substituições + inserções + deleções) / palavras da referência
WER agregado   = soma das distâncias / soma das palavras de referência
```

O agregado **não** é a média das frases: frase longa pesa mais, como no WER de verdade. O script também mostra
mediana e p90 por frase, e as piores frases de cada modelo.

### Normalização (igual para referência e hipótese)

- minúsculas;
- `_` e todo caractere que não é letra/número viram espaço (pontuação não conta);
- espaços colapsados;
- **acentos ficam** (acento errado conta como erro);
- números ficam como estão (dígito não vira palavra e vice-versa).

A normalização é a mesma para os dois lados, então ela não favorece nenhum modelo. A limitação de números é
declarada: se a referência tem `4,17` e o modelo escreve `quatro vírgula dezessete`, isso conta como erro — e
conta igual para os dois.

## 4. Como ler o resultado

- **WER total** de cada modelo e o **delta** (turbo − v3). Negativo = turbo errou menos.
- **Piores frases**: erro sistemático em nome, número ou termo técnico diz mais que um ponto de WER.
- **Critério do piloto** (o mesmo do documento):
  - turbo com WER **≤** v3 no mesmo conjunto **e** latência p50 **≤ 1,5 s** para ~10 s de fala → candidato a trocar;
  - turbo **> 1 ponto** pior → não trocar;
  - dentro de **±1 ponto** → decidir pela dica `pt` (o v3 não aceita; o turbo aceita) e pela latência.
- **24 frases é indicativo, não benchmark conclusivo.** Uma diferença de ~1 ponto não é estatisticamente
  significativa; o piloto detecta diferença grande ou regressão óbvia.

A latência **não** sai deste material: ela é medida no uso real, pelo log do Ronaldo
(`~/Library/Logs/ronaldo.log`, de `fim da gravação` a `colando N caracteres`), como descrito no documento.

## 5. Privacidade e limpeza

- O áudio e os resultados ficam em `~/ab-arara/`; **não comite** áudio, JSON de hipótese nem `wer.json` no repo.
- Para apagar depois: `rm -rf ~/ab-arara`.
- Nada no Hex muda com este material. Se o turbo foi instalado só para o teste, o rollback é
  `hex model use parakeet_v3 --language pt` (1 comando).

## 6. Limitações declaradas

- 24 frases, uma leitura cada: não mede variação entre gravações nem ruído de fundo.
- A referência é a sua escrita; se você mudar a pontuação depois, o WER muda.
- O `hex transcribe` usa o modelo cru (sem output steps, sem vocabulário, sem histórico) — é o que o A/B quer,
  mas não é exatamente o texto que o Ronaldo colaria se o modelo fosse o selecionado.
- Este material não instala nem troca nada; a instalação do turbo e qualquer mudança no Mac são decisão do
  Guima.
