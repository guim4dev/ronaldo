#!/usr/bin/env python3
"""WER do piloto A/B de transcrição pt-BR do Ronaldo.

Compara pares referência/hipótese — sem rede, sem modelo, sem tocar no Hex.
A hipótese vem de `hex transcribe ... --json` (chave "text") ou de um .txt.

Fórmula: WER = (substituições + inserções + deleções) / palavras da referência.
Agregado: soma das distâncias / soma das palavras de referência (não é a média
das frases: frase longa pesa mais, como no WER de verdade).

Normalização (igual para referência e hipótese):
  - minúsculas;
  - `_` e todo caractere que não é letra/número vira espaço;
  - espaços colapsados;
  - acentos ficam (acento errado conta como erro);
  - números ficam como estão (dígito não vira palavra e vice-versa).

Uso:
  tools/piloto/wer.py --frases docs/piloto/frases.json \
      --modelo v3=~/ab-arara/resultados/v3 \
      --modelo turbo=~/ab-arara/resultados/turbo

  tools/piloto/wer.py --selftest

Saída: markdown no stdout; `--json` e `--markdown` gravam cópias.
Código de saída: 0 ok; 1 falta hipótese/arquivo inválido; 2 uso errado.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

# ---------------------------------------------------------------- normalização


def normalizar(texto: str) -> list[str]:
    """Palavras comparáveis: minúsculas, sem pontuação, com acento, números como estão."""
    s = texto.lower().replace("_", " ")
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s.split()


def distancia(ref: list[str], hyp: list[str]) -> int:
    """Distância de edição (substituição, inserção, deleção), O(len(ref)*len(hyp))."""
    if not ref:
        return len(hyp)
    if not hyp:
        return len(ref)
    anterior = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        atual = [i]
        for j, h in enumerate(hyp, 1):
            atual.append(
                min(
                    anterior[j] + 1,          # deleção
                    atual[j - 1] + 1,         # inserção
                    anterior[j - 1] + (r != h)  # substituição ou acerto
                )
            )
        anterior = atual
    return anterior[-1]


# ---------------------------------------------------------------- leitura


def ler_frases(caminho: Path) -> list[dict]:
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    frases = dados.get("frases") if isinstance(dados, dict) else dados
    if not isinstance(frases, list) or not frases:
        raise ValueError(f"{caminho}: esperava uma lista 'frases' não vazia")
    vistos: set[str] = set()
    for f in frases:
        if not isinstance(f, dict) or not f.get("id") or not isinstance(f.get("texto"), str):
            raise ValueError(f"{caminho}: frase sem 'id' ou 'texto': {f!r}")
        if f["id"] in vistos:
            raise ValueError(f"{caminho}: id repetido: {f['id']}")
        vistos.add(f["id"])
    return frases


def ler_hipotese(diretorio: Path, frase_id: str) -> tuple[str | None, str | None]:
    """Devolve (texto, aviso). texto None = arquivo ausente."""
    json_path = diretorio / f"{frase_id}.json"
    txt_path = diretorio / f"{frase_id}.txt"
    if json_path.exists():
        bruto = json_path.read_text(encoding="utf-8").strip()
        if not bruto:
            return "", f"{json_path.name}: vazio"
        try:
            dados = json.loads(bruto)
        except json.JSONDecodeError as exc:
            return None, f"{json_path.name}: JSON inválido ({exc.msg})"
        if isinstance(dados, str):
            return dados, None
        if isinstance(dados, dict) and isinstance(dados.get("text"), str):
            return dados["text"], None
        return None, f"{json_path.name}: sem a chave 'text'"
    if txt_path.exists():
        return txt_path.read_text(encoding="utf-8").strip(), None
    return None, f"falta {frase_id}.json ou {frase_id}.txt em {diretorio}"


# ---------------------------------------------------------------- contas


def avaliar(frases: list[dict], modelos: list[tuple[str, Path]], permitir_faltando: bool):
    """Devolve (resultado por modelo, problemas)."""
    resultado = {}
    problemas: list[str] = []
    for nome, diretorio in modelos:
        if not diretorio.is_dir():
            problemas.append(f"{nome}: pasta não existe: {diretorio}")
            continue
        por_frase = []
        erros_total = palavras_total = 0
        for f in frases:
            texto, aviso = ler_hipotese(diretorio, f["id"])
            if aviso:
                problemas.append(f"{nome}: {aviso}")
            if texto is None:
                continue  # sem hipótese: fica fora do total (o aviso já foi para `problemas`)
            ref = normalizar(f["texto"])
            hyp = normalizar(texto)
            erros = distancia(ref, hyp)
            palavras = len(ref)
            erros_total += erros
            palavras_total += palavras
            por_frase.append(
                {
                    "id": f["id"],
                    "categoria": f.get("categoria", ""),
                    "palavras": palavras,
                    "erros": erros,
                    "wer": (erros / palavras) if palavras else 0.0,
                }
            )
        if not por_frase:
            problemas.append(f"{nome}: nenhuma frase avaliada")
            continue
        wers = [p["wer"] for p in por_frase]
        ordenado = sorted(wers)
        p90 = ordenado[min(len(ordenado) - 1, int(0.9 * len(ordenado)))]
        resultado[nome] = {
            "frases": por_frase,
            "palavras": palavras_total,
            "erros": erros_total,
            "wer_total": (erros_total / palavras_total) if palavras_total else 0.0,
            "mediana": statistics.median(wers),
            "p90": p90,
            "piores": sorted(por_frase, key=lambda p: (-p["wer"], p["id"]))[:5],
        }
    return resultado, problemas


def pct(x: float) -> str:
    return f"{100 * x:.2f}%"


def markdown(resultado: dict, frases: list[dict]) -> str:
    nomes = list(resultado)
    linhas = ["## WER por modelo", ""]
    linhas.append("| Modelo | Palavras | Erros | WER total | Mediana | p90 |")
    linhas.append("|---|---:|---:|---:|---:|---:|")
    for nome in nomes:
        r = resultado[nome]
        linhas.append(
            f"| {nome} | {r['palavras']} | {r['erros']} | **{pct(r['wer_total'])}** | "
            f"{pct(r['mediana'])} | {pct(r['p90'])} |"
        )

    if len(nomes) == 2:
        a, b = nomes
        delta = 100 * (resultado[b]["wer_total"] - resultado[a]["wer_total"])
        linhas += ["", f"**Delta ({b} − {a}): {delta:+.2f} pontos percentuais.** "
                       "Sinal negativo = o segundo modelo errou menos."]

    linhas += ["", "## Por frase", ""]
    cabecalho = "| Frase | Categoria | Palavras | " + " | ".join(f"{n} (erros)" for n in nomes) + " |"
    linhas.append(cabecalho)
    linhas.append("|---|---|---:|" + "---:|" * len(nomes))
    por_id = {f["id"]: f for f in frases}
    for frase_id in [f["id"] for f in frases]:
        if not any(any(p["id"] == frase_id for p in resultado[n]["frases"]) for n in nomes):
            continue
        cat = por_id[frase_id].get("categoria", "")
        palavras = next(
            (p["palavras"] for n in nomes for p in resultado[n]["frases"] if p["id"] == frase_id),
            0,
        )
        celulas = []
        for n in nomes:
            p = next((p for p in resultado[n]["frases"] if p["id"] == frase_id), None)
            celulas.append(f"{p['erros']} ({pct(p['wer'])})" if p else "—")
        linhas.append(f"| {frase_id} | {cat} | {palavras} | " + " | ".join(celulas) + " |")

    for nome in nomes:
        linhas += ["", f"## Piores frases — {nome}", ""]
        for p in resultado[nome]["piores"]:
            linhas.append(f"- {p['id']} ({p['categoria']}): {pct(p['wer'])} — {p['erros']}/{p['palavras']} erros")
    return "\n".join(linhas) + "\n"


# ---------------------------------------------------------------- selftest


def selftest() -> int:
    casos = [
        ("Olá, mundo! 42_vezes", ["olá", "mundo", "42", "vezes"]),
        ("  PT-BR   é   técnico  ", ["pt", "br", "é", "técnico"]),
        ("4,17 por cento", ["4", "17", "por", "cento"]),
    ]
    for entrada, esperado in casos:
        obtido = normalizar(entrada)
        assert obtido == esperado, f"normalizar({entrada!r}) = {obtido!r}, esperava {esperado!r}"
    assert distancia([], []) == 0
    assert distancia(["a"], []) == 1
    assert distancia([], ["a", "b"]) == 2
    assert distancia(["a", "b", "c"], ["a", "b", "c"]) == 0
    assert distancia(["a", "b", "c"], ["a", "x", "c"]) == 1
    assert distancia(["a", "b"], ["b", "a"]) == 2
    assert distancia(["o", "gato"], ["o", "gato", "preto"]) == 1
    # acento errado conta
    assert distancia(normalizar("é"), normalizar("e")) == 1
    print("selftest ok")
    return 0


# ---------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="WER por pares referência/hipótese do piloto A/B.")
    p.add_argument("--frases", type=Path, help="JSON com as frases de referência")
    p.add_argument("--modelo", action="append", default=[], metavar="NOME=DIR",
                   help="modelo e pasta de hipóteses (repita para comparar)")
    p.add_argument("--json", type=Path, help="grava o resultado em JSON")
    p.add_argument("--markdown", type=Path, help="grava a tabela em markdown")
    p.add_argument("--permitir-faltando", action="store_true",
                   help="não falha quando falta hipótese; só avisa e segue")
    p.add_argument("--selftest", action="store_true", help="roda as asserções internas e sai")
    a = p.parse_args(argv)

    if a.selftest:
        return selftest()
    if not a.frases or not a.modelo:
        p.error("use --frases e pelo menos um --modelo (ou --selftest)")

    modelos: list[tuple[str, Path]] = []
    for item in a.modelo:
        if "=" not in item:
            p.error(f"--modelo espera NOME=DIR, veio {item!r}")
        nome, diretorio = item.split("=", 1)
        nome = nome.strip()
        if not nome:
            p.error(f"--modelo sem nome: {item!r}")
        modelos.append((nome, Path(diretorio).expanduser()))

    try:
        frases = ler_frases(a.frases)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1

    resultado, problemas = avaliar(frases, modelos, a.permitir_faltando)
    if problemas:
        for aviso in problemas:
            print(f"aviso: {aviso}", file=sys.stderr)
    if not resultado:
        print("erro: nenhum modelo pôde ser avaliado", file=sys.stderr)
        return 1

    texto = markdown(resultado, frases)
    print(texto)
    if a.markdown:
        a.markdown.parent.mkdir(parents=True, exist_ok=True)
        a.markdown.write_text(texto, encoding="utf-8")
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(
            json.dumps({"frases": frases, "resultado": resultado, "problemas": problemas},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    faltando = [x for x in problemas if "falta " in x or "pasta não existe" in x or "nenhuma frase" in x]
    if faltando and not a.permitir_faltando:
        print("erro: há frases sem hipótese; corrija ou use --permitir-faltando", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
