"""Prepara quatro assets revisados de v1.0.0, sem publicar ou substituir arquivos.

Execute com a árvore Git limpa e build==1.6.1 disponível no ambiente de
desenvolvimento: python scripts/package_release.py --out DIRETORIO_NOVO.
A instalação de QA pode baixar as dependências fixadas do índice de pacotes.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib

from check_distribution import (NAME, PREFIX, ROOT, VERSION, check_dist,
                                check_install, check_example, DistributionError,
                                expected_source_files, require)


def git(*arguments: str) -> bytes:
    return subprocess.check_output(["git", *arguments], cwd=ROOT)


def checked_source() -> str:
    require(Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve() == ROOT,
            "O diretório do projeto precisa ser a raiz Git.")
    require(not git("status", "--porcelain"), "A árvore Git precisa estar limpa.")
    require(git("ls-files", "-z").decode().rstrip("\0").split("\0") ==
            sorted(expected_source_files()), "Arquivos Git diferentes do inventário fonte revisado.")
    for name in expected_source_files():
        path = ROOT / name
        require(path.is_file() and not path.is_symlink() and path.resolve() == path,
                "A fonte deve conter somente arquivos regulares revisados.")
        require(path.read_bytes() == git("show", "HEAD:" + name), "Fonte divergente do commit.")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    require(project["project"]["name"] == NAME and project["project"]["version"] == VERSION,
            "Versão ou projeto incorretos.")
    return git("rev-parse", "HEAD").decode().strip()


def prepare_example(wheel: Path, work: Path) -> bytes:
    """Executa a CLI do wheel instalado em um venv independente da fonte."""
    import os
    import venv

    target = work / "example-venv"
    venv.EnvBuilder(with_pip=True).create(target)
    scripts = target / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    cli = scripts / (NAME + (".exe" if os.name == "nt" else ""))
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["PYTHONUTF8"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    subprocess.run([str(python), "-I", "-m", "pip", "install", "--no-input", str(wheel)],
                   cwd=work, env=env, check=True, capture_output=True)
    subprocess.run([str(cli), "exemplo", "--saida", "exemplo.zip"], cwd=work,
                   env=env, check=True, capture_output=True)
    example = work / "exemplo.zip"
    check_example(example)
    subprocess.run([str(python), "-I", str(ROOT / "tools/check_bundle.py"),
                    str(example), "--demo"], cwd=work, env=env, check=True,
                   capture_output=True)
    return example.read_bytes()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path,
                        help="Diretório novo, cujo pai já existe.")
    args = parser.parse_args()
    try:
        destination = args.out.absolute()
        require(not destination.exists() and not destination.is_symlink(), "O destino precisa ser novo.")
        require(destination.parent.is_dir(), "O diretório pai do destino precisa existir.")
        require(importlib.metadata.version("build") == "1.6.1", "Use build==1.6.1 para preparar a release.")
        commit = checked_source()
        with tempfile.TemporaryDirectory(prefix="materiais-release-") as temporary:
            work = Path(temporary)
            dist = work / "dist"
            subprocess.run([sys.executable, "-m", "build", "--outdir", str(dist)],
                           cwd=ROOT, check=True, capture_output=True)
            inventory = check_dist(dist)
            artifacts = sorted(dist.iterdir())
            installations = [check_install(path) for path in artifacts]
            wheel = dist / f"{PREFIX}-{VERSION}-py3-none-any.whl"
            assets = {path.name: path.read_bytes() for path in artifacts}
            assets["exemplo.zip"] = prepare_example(wheel, work)
            require(checked_source() == commit, "O commit mudou durante o preparo.")
            sums = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(assets.items())}
            assets["SHA256SUMS"] = "".join(f"{checksum}  {name}\n" for name, checksum in sums.items()).encode("utf-8")
            # Tudo já foi construído e conferido; este diretório novo é apenas
            # a apresentação local dos assets. Nenhuma chamada GitHub existe.
            destination.mkdir()
            try:
                for name, data in sorted(assets.items()):
                    with (destination / name).open("xb") as output:
                        output.write(data)
                require({path.name for path in destination.iterdir()} == set(assets), "Assets incompletos.")
                for name, data in assets.items():
                    require((destination / name).read_bytes() == data, "Asset escrito de forma incompleta.")
            except BaseException:
                for name in assets:
                    (destination / name).unlink(missing_ok=True)
                destination.rmdir()
                raise
        print(json.dumps({"version": VERSION, "source_commit": commit, "assets": sums,
                          "inventario": inventory, "instalacoes": installations,
                          "publicacao": "nenhuma"}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (DistributionError, OSError, subprocess.CalledProcessError) as error:
        print("Falha ao preparar a release: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
