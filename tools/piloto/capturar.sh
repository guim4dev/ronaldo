#!/usr/bin/env bash
# Transcreve um diretório de áudio com UM modelo do Hex que JÁ esteja instalado.
#
# O que este script NÃO faz (de propósito):
#   - não instala modelo (`hex model install`);
#   - não troca o modelo selecionado (`hex model use`);
#   - não muda settings, atalho global, LaunchAgent ou qualquer estado do Hex;
#   - não mexe no microfone.
# Ele só lê os arquivos de áudio e chama `hex transcribe ... --json`.
#
# Uso:
#   tools/piloto/capturar.sh --modelo parakeet_v3 --audio ~/ab-arara/audio --saida ~/ab-arara/v3
#   tools/piloto/capturar.sh --modelo whisper_large_v3_turbo --idioma pt \
#       --audio ~/ab-arara/audio --saida ~/ab-arara/turbo
#   tools/piloto/capturar.sh ... --seco    # só mostra o que faria
#
# Saída: um <id>.json por áudio (o JSON do `hex transcribe --json`, com a chave "text")
# e um manifest.json com o que foi feito.
set -euo pipefail

HEX="${HEX:-/Applications/Hex.app/Contents/MacOS/hex}"
MODELO=""
AUDIO=""
SAIDA=""
IDIOMA=""
SECO=0

uso() {
  sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

erro() { echo "erro: $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --modelo) MODELO="${2:-}"; shift 2 ;;
    --audio)  AUDIO="${2:-}";  shift 2 ;;
    --saida)  SAIDA="${2:-}";  shift 2 ;;
    --idioma) IDIOMA="${2:-}"; shift 2 ;;
    --hex)    HEX="${2:-}";    shift 2 ;;
    --seco)   SECO=1; shift ;;
    -h|--help) uso 0 ;;
    *) erro "argumento desconhecido: $1 (use --help)" ;;
  esac
done

[[ -n "$MODELO" ]] || erro "falta --modelo"
[[ -n "$AUDIO"  ]] || erro "falta --audio"
[[ -n "$SAIDA"  ]] || erro "falta --saida"
[[ -x "$HEX" ]] || erro "Hex não encontrado em $HEX (ou passe --hex)"
[[ -d "$AUDIO" ]] || erro "pasta de áudio não existe: $AUDIO"

# O modelo tem que estar instalado; o script nunca instala nem troca.
if ! "$HEX" model list --json 2>/dev/null | python3 -c '
import json, sys
alvo = sys.argv[1]
d = json.load(sys.stdin)
for m in d.get("models", []):
    if m.get("id") == alvo:
        sys.exit(0 if m.get("installed") else 3)
sys.exit(4)
' "$MODELO"; then
  erro "modelo '$MODELO' não está instalado (ou o Hex não respondeu). Este script não instala nem troca modelo; instale/peça antes e rode de novo."
fi

quantos="$(find "$AUDIO" -maxdepth 1 -type f \
  \( -iname '*.m4a' -o -iname '*.wav' -o -iname '*.aiff' -o -iname '*.aif' \
     -o -iname '*.caf' -o -iname '*.flac' -o -iname '*.mp3' -o -iname '*.ogg' \
     -o -iname '*.oga' -o -iname '*.opus' -o -iname '*.webm' -o -iname '*.mp4' \
     -o -iname '*.mov' -o -iname '*.m4v' \) | wc -l | tr -d ' ')"
[[ "$quantos" -gt 0 ]] || erro "nenhum áudio suportado em $AUDIO"

if [[ "$SECO" -eq 0 ]]; then
  mkdir -p "$SAIDA"
fi

falhas=0
feitos=0
# Sem mapfile: o bash 3.2 do macOS não tem. O loop roda no shell atual (process substitution).
while IFS= read -r f; do
  base="$(basename "$f")"
  id="${base%.*}"                 # f01.m4a -> f01
  destino="$SAIDA/$id.json"
  cmd=("$HEX" transcribe "$f" --model "$MODELO" --json)
  if [[ -n "$IDIOMA" ]]; then cmd+=(--language "$IDIOMA"); fi
  if [[ "$SECO" -eq 1 ]]; then
    printf '%q ' "${cmd[@]}"; printf '> %q\n' "$destino"
    continue
  fi
  echo "→ $base"
  if "${cmd[@]}" > "$destino.tmp" 2>"$destino.err"; then
    mv "$destino.tmp" "$destino"
    rm -f "$destino.err"
    feitos=$((feitos + 1))
  else
    echo "  falhou: $(tail -1 "$destino.err" 2>/dev/null || echo 'sem mensagem')" >&2
    rm -f "$destino.tmp"
    falhas=$((falhas + 1))
  fi
done < <(find "$AUDIO" -maxdepth 1 -type f \
  \( -iname '*.m4a' -o -iname '*.wav' -o -iname '*.aiff' -o -iname '*.aif' \
     -o -iname '*.caf' -o -iname '*.flac' -o -iname '*.mp3' -o -iname '*.ogg' \
     -o -iname '*.oga' -o -iname '*.opus' -o -iname '*.webm' -o -iname '*.mp4' \
     -o -iname '*.mov' -o -iname '*.m4v' \) | sort)

if [[ "$SECO" -eq 1 ]]; then
  echo "modo seco: nada foi executado nem escrito."
  exit 0
fi

versao="$("$HEX" --version 2>/dev/null || echo '?')"
python3 - "$SAIDA/manifest.json" "$MODELO" "$IDIOMA" "$versao" "$AUDIO" "$feitos" "$falhas" <<'PY'
import json, sys, time
caminho, modelo, idioma, versao, audio, feitos, falhas = sys.argv[1:]
json.dump({
    "criado": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "hex": versao,
    "modelo": modelo,
    "idioma": idioma or None,
    "audio": audio,
    "arquivos": int(feitos),
    "falhas": int(falhas),
    "nota": "gerado por tools/piloto/capturar.sh; nenhum modelo foi instalado ou trocado",
}, open(caminho, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
open(caminho, "a", encoding="utf-8").write("\n")
PY

echo "pronto: $feitos arquivo(s) em $SAIDA${falhas:+, $falhas falha(s)}"
[[ "$falhas" -eq 0 ]]
