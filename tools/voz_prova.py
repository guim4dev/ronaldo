#!/usr/bin/env python3
"""Prova manual do modo voz: fala uma pergunta ao rei e mede a resposta.

Exemplos:
    uv run python tools/voz_prova.py --texto "[teste do modo voz] Responda só: ok"
    uv run python tools/voz_prova.py --id <32hex> --reino pessoal
    REINO_CORTE_CASA=/tmp/casa uv run python tools/voz_prova.py --texto "oi"

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


def enviar_fala(texto: str) -> tuple[str, str]:
    oid = uuid.uuid4().hex
    env = {**os.environ, "PATH": agent.login_path()}
    argv = [voz.corte_bin(), "falar", "--id", oid, "--json", "--", texto]
    print(f"fala enviada: id={oid} corte={argv[0]} casa={env.get('REINO_CORTE_CASA', '-')}")
    resultado = subprocess.run(argv, capture_output=True, text=True, timeout=60, env=env, cwd=os.path.expanduser("~"))
    if resultado.returncode != 0:
        raise SystemExit(f"corte falar saiu {resultado.returncode}: {resultado.stderr.strip() or resultado.stdout.strip()}")
    try:
        dados = json.loads(resultado.stdout)
    except ValueError as exc:
        raise SystemExit(f"corte falar devolveu JSON inválido: {exc}: {resultado.stdout!r}") from exc
    if not isinstance(dados, dict) or dados.get("ok") is not True:
        raise SystemExit(f"corte falar recusou: {dados}")
    reino = dados.get("reino")
    if not isinstance(reino, str) or not reino:
        raise SystemExit(f"corte falar não devolveu o reino: {dados}")
    print(f"reino={reino} id={dados.get('id', oid)}")
    return str(dados.get("id", oid)), reino


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--texto", help="pergunta nova; chama `corte falar --id --json`")
    parser.add_argument("--id", help="id de uma fala que já existe")
    parser.add_argument("--reino", help="reino da fala existente")
    parser.add_argument("--volume", type=float, default=0.15, help="volume do afplay (padrão 0.15)")
    parser.add_argument("--motores", nargs="+", help="cadeia de motores (padrão: [voz] do config)")
    args = parser.parse_args(argv)

    if args.texto:
        oid, reino = enviar_fala(args.texto)
    elif args.id and args.reino:
        oid, reino = args.id, args.reino
        print(f"reino={reino} id={oid} (fala existente)")
    else:
        parser.error("use --texto ou --id com --reino")

    motores = args.motores or voz.VozConfig.load().motores

    def consultar(id: str, reino_fala: str) -> dict:
        return voz.consultar_resposta(id, reino_fala)

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
    if not falador.enfileirar(reino, oid):
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
