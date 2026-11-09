"""CLI sem rede ou configuração implícita do ambiente."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys

from . import __version__
from .core import PlanError
from .demo import demo_mapping
from .reports import publish_bundle


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, "Uso inválido. Consulte --help.\n")


def _read_regular(path: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise OSError("A entrada deve ser um arquivo regular.")
        data = stream.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise PlanError("E_LIMIT", "", "O arquivo excede 1 MiB.")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(
        prog="materiais-em-lote",
        description="Planeje materiais por listas técnicas multinível, estoque e lotes exatos.",
        epilog="A saída é um relatório estático; não reserva estoque nem realiza compras.",
    )
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    planning = commands.add_parser("planejar", help="Calcular uma entrada JSON explícita.")
    planning.add_argument("projeto", help="Arquivo JSON UTF-8 de até 1 MiB.")
    planning.add_argument("--saida", required=True, help="Caminho .zip novo em diretório existente.")
    example = commands.add_parser("exemplo", help="Gerar o cenário autoral de uma oficina.")
    example.add_argument("--saida", required=True, help="Caminho .zip novo em diretório existente.")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "exemplo":
            data = (json.dumps(demo_mapping(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        else:
            data = _read_regular(arguments.projeto)
        publish_bundle(data, Path(arguments.saida))
    except PlanError as error:
        print(f"{error.code} em {error.path or '/'}: {error.message}", file=sys.stderr)
        return 2
    except (OSError, ValueError):
        print("E_IO: não foi possível ler a entrada ou publicar a saída nova. "
              "Confira o arquivo, o diretório, a extensão .zip e o suporte a hardlink; "
              "destinos existentes são preservados.", file=sys.stderr)
        return 3
    print("Pacote completo criado: " + arguments.saida)
    return 0
