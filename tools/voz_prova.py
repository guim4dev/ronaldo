#!/usr/bin/env python3
"""Prova manual do modo voz: envia uma fala pelos comandos do config e mede a resposta.

Usa `[voz].enviar` e `[voz].resposta` do `~/.config/ronaldo/config.toml`.

Exemplos:
    uv run python tools/voz_prova.py --texto "[teste do modo voz] Responda só: ok"
    uv run python tools/voz_prova.py --id <32hex> --contexto canal=casa

Manda no máximo uma fala (--texto), só para teste. O resto é leitura.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ronaldo import agent, voz  # noqa: E402


def enviar_fala(texto: str) -> tuple[str, dict]:
    cfg = voz.VozConfig.load()
    if not cfg.enviar:
        raise SystemExit("config sem [voz].enviar")
    if not cfg.resposta:
        raise SystemExit("config sem [voz].resposta")
    oid = uuid.uuid4().hex
    argv, faltando = voz.substituir(cfg.enviar, {"id": oid, "text": texto})
    if faltando:
        raise SystemExit(f"o envio pede {voz.campos(faltando)}, que não tem valor")
    tem_texto = any("{text}" in argumento for argumento in cfg.enviar)
    env = {**os.environ, "PATH": agent.login_path()}
    print(f"fala enviada: id={oid} comando={argv[0]}")
    resultado = subprocess.run(
        argv,
        input=None if tem_texto else texto,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        cwd=os.path.expanduser("~"),
    )
    if resultado.returncode != 0:
        raise SystemExit(f"o envio saiu {resultado.returncode}: {resultado.stderr.strip() or resultado.stdout.strip()}")
    try:
        dados = json.loads(resultado.stdout)
    except ValueError as exc:
        raise SystemExit(f"o envio devolveu JSON inválido: {exc}: {resultado.stdout!r}") from exc
    if not isinstance(dados, dict) or dados.get("ok") is not True:
        raise SystemExit(f"o envio recusou: {dados}")
    contexto = {"id": oid}
    for chave, valor in dados.items():
        if isinstance(chave, str) and isinstance(valor, str):
            contexto[chave] = valor
    _, faltando = voz.substituir(cfg.resposta, contexto)
    if faltando:
        raise SystemExit(f"a resposta pede {voz.campos(faltando)}, que não veio no envio")
    print(f"id={oid} campos={sorted(contexto)}")
    return oid, contexto


def _contexto(pares: list[str]) -> dict:
    valores = {}
    for par in pares:
        chave, _, valor = par.partition("=")
        if not chave or not _:
            raise SystemExit(f"--contexto espera chave=valor, recebeu {par!r}")
        valores[chave] = valor
    return valores


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--texto", help="pergunta nova; usa [voz].enviar do config")
    parser.add_argument("--id", help="id de uma fala que já existe")
    parser.add_argument("--contexto", action="append", default=[], metavar="CHAVE=VALOR", help="campo do contexto (repita para vários)")
    parser.add_argument("--volume", type=float, default=0.15, help="volume do afplay (padrão 0.15)")
    parser.add_argument("--motores", nargs="+", help="cadeia de motores (padrão: [voz] do config)")
    args = parser.parse_args(argv)

    if args.texto:
        oid, contexto = enviar_fala(args.texto)
    elif args.id:
        oid, contexto = args.id, {"id": args.id, **_contexto(args.contexto)}
        print(f"id={oid} campos={sorted(contexto)} (fala existente)")
    else:
        parser.error("use --texto ou --id")

    motores = args.motores or voz.VozConfig.load().motores

    def consultar(id: str, contexto_fala: dict) -> dict:
        return voz.consultar_resposta(id, contexto_fala)

    def falar(texto: str, em: float | None = None) -> bool:
        print(f"resposta pronta: em={em}")
        inicio = time.time()
        latencia = f"{inicio - float(em):.2f}" if isinstance(em, (int, float)) else "?"
        print(f"voz começou: latência={latencia}s (desde em)")
        ok = voz.falar_texto(texto, motores=motores, volume=args.volume)
        print("voz acabou" if ok else "voz falhou")
        return ok

    falador = voz.Falador(
        consultar=consultar,
        falar=falar,
        ligado_fn=lambda: True,
        gravando_fn=lambda: False,
        automatico=False,
    )
    if not falador.enfileirar(oid, contexto):
        raise SystemExit(f"id {oid} já foi falado; nada a fazer")
    prazo = time.monotonic() + voz.PRAZO_FALADOR
    while time.monotonic() < prazo:
        falador.passo()
        if falador.ja_falado(oid):
            print("fim: fala tratada")
            return 0
        time.sleep(voz.INTERVALO_FALADOR)
    print("fim: prazo de 15 min sem resposta falável", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
