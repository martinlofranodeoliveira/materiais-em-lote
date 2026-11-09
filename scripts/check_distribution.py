"""Confere inventários, RECORD e instalação real fora da árvore fonte.

Uso: --dist dist; --install ARQUIVO.whl|ARQUIVO.tar.gz; ou --installed.
O modo --install cria um venv descartável e instala pelo pip. Somente esse
modo de QA pode acessar o índice de pacotes; a aplicação nunca faz rede.
"""
from __future__ import annotations

import argparse
import base64
import configparser
import csv
import hashlib
import importlib
import importlib.metadata
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile
from email.parser import BytesParser

ROOT = Path(__file__).resolve().parents[1]
NAME = "materiais-em-lote"
VERSION = "1.0.0"
PREFIX = "materiais_em_lote"
DIST_INFO = f"{PREFIX}-{VERSION}.dist-info"
PACKAGE_FILES = frozenset(f"{PREFIX}/{name}.py" for name in (
    "__init__", "__main__", "cli", "core", "demo", "reports",
))
METADATA_FILES = frozenset(f"{DIST_INFO}/{name}" for name in (
    "METADATA", "WHEEL", "entry_points.txt", "top_level.txt", "RECORD",
    "licenses/LICENSE", "licenses/THIRD-PARTY-NOTICES.md",
))
WHEEL_FILES = PACKAGE_FILES | METADATA_FILES
BUNDLE_FILES = frozenset(("projeto.json", "plano.json", "plano.csv", "plano.md",
                          "plano.xlsx", "LEIA-ME.md", "manifesto.json"))
# Os nomes públicos são deliberadamente fechados. Inclua uma nova fonte aqui
# somente após revisar sua finalidade; local/, perfis e executáveis nunca entram.
# Os ZIP/XLSX/ODS sintéticos de QA são públicos e verificados por evidence.json.
SOURCE_FILES = frozenset((
    ".editorconfig", ".gitattributes", ".gitignore", ".github/workflows/ci.yml",
    "CONTRACT.md", "PRODUCT.md", "README.md", "LICENSE", "THIRD-PARTY-NOTICES.md",
    "CONTRIBUTING.md", "SECURITY.md", "docs/FORMATO.md", "docs/VALIDACAO.md",
    "pyproject.toml", "MANIFEST.in",
    "scripts/check_distribution.py", "scripts/package_release.py",
    "tests/test_core.py", "tests/test_reports_cli.py", "tests/test_distribution.py",
    "tests/test_interop.py", "tools/check_bundle.py", "tools/verify_libreoffice.py",
    "fixtures/projeto-oficina.json",
    "fixtures/interop/text-project.json", "fixtures/interop/evidence.json",
    "docs/INTEROPERABILIDADE.md",
    "fixtures/interop/demo.zip", "fixtures/interop/text.zip",
    "fixtures/interop/demo-original.xlsx", "fixtures/interop/demo-libreoffice.xlsx",
    "fixtures/interop/text-original.xlsx", "fixtures/interop/text-libreoffice.xlsx",
    "fixtures/interop/audit-source.xlsx", "fixtures/interop/audit-libreoffice.xlsx",
    "fixtures/interop/demo-import.ods", "fixtures/interop/text-import.ods",
    "fixtures/interop/text-reopened.ods",
)) | frozenset(f"src/{name}" for name in PACKAGE_FILES)
SOURCE_GENERATED = frozenset(("PKG-INFO", "setup.cfg")) | frozenset(
    f"src/{PREFIX}.egg-info/{name}" for name in (
        "PKG-INFO", "SOURCES.txt", "dependency_links.txt", "entry_points.txt",
        "requires.txt", "top_level.txt",
    )
)


class DistributionError(ValueError):
    """Distribuição diferente do inventário público declarado."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DistributionError(message)


def safe_name(name: str) -> None:
    path = PurePosixPath(name)
    require(bool(name) and not path.is_absolute() and ".." not in path.parts
            and "\\" not in name and "\x00" not in name, "Nome inseguro no arquivo.")
    denied = {".git", ".venv", "local", ".openai", "__pycache__", "node_modules"}
    require(not any(part in denied or part == ".env" or part.startswith(".env.")
                    for part in path.parts), "Arquivo privado no inventário.")


def digest(data: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")


def check_metadata(data: bytes) -> None:
    metadata = BytesParser().parsebytes(data)
    require(metadata["Name"] == NAME and metadata["Version"] == VERSION, "Nome ou versão incorretos.")
    require(metadata["Requires-Python"] == ">=3.11", "Versão Python incorreta.")
    require(metadata["License-Expression"] == "MIT", "Licença do pacote precisa ser MIT.")
    requirements = sorted(value.replace(" ", "") for value in metadata.get_all("Requires-Dist", []))
    require(requirements == ["et-xmlfile==2.0.0", "openpyxl==3.1.5"], "Dependências não estão fixadas.")
    require(not metadata.get_all("Provides-Extra", []), "Extras inesperados na distribuição.")
    require(set(metadata.get_all("License-File", [])) == {"LICENSE", "THIRD-PARTY-NOTICES.md"},
            "Avisos de licença incompletos.")


def check_entry_points(data: bytes) -> None:
    config = configparser.ConfigParser(interpolation=None)
    config.read_string(data.decode("utf-8"))
    require(config.sections() == ["console_scripts"], "Grupos de entrada inesperados.")
    require(dict(config["console_scripts"]) == {NAME: f"{PREFIX}.cli:main"}, "CLI incorreta.")


def check_record(members: dict[str, bytes]) -> None:
    record_name = f"{DIST_INFO}/RECORD"
    rows = list(csv.reader(io.StringIO(members[record_name].decode("utf-8"), newline="")))
    require(all(len(row) == 3 for row in rows), "RECORD tem campos incorretos.")
    require(len(rows) == len(members) and len({row[0] for row in rows}) == len(rows),
            "RECORD tem omissões ou duplicatas.")
    require({row[0] for row in rows} == set(members), "RECORD diverge do inventário.")
    for name, checksum, size in rows:
        if name == record_name:
            require(checksum == size == "", "RECORD não deve assinar a si mesmo.")
        else:
            require(checksum == f"sha256={digest(members[name])}" and size == str(len(members[name])),
                    f"Hash ou tamanho incorreto: {name}.")


def check_wheel(path: Path) -> dict:
    require(path.name == f"{PREFIX}-{VERSION}-py3-none-any.whl", "Nome de wheel inesperado.")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), "Wheel tem nomes repetidos.")
        for info in archive.infolist():
            safe_name(info.filename)
            require(not info.is_dir() and ((info.external_attr >> 16) & 0o170000) in (0, 0o100000),
                    "Wheel deve conter apenas arquivos regulares.")
        require(set(names) == WHEEL_FILES, "Inventário do wheel divergente: " +
                repr(sorted(set(names) ^ WHEEL_FILES)))
        require(archive.testzip() is None, "CRC inválido no wheel.")
        members = {name: archive.read(name) for name in names}
    check_metadata(members[f"{DIST_INFO}/METADATA"])
    check_entry_points(members[f"{DIST_INFO}/entry_points.txt"])
    require(members[f"{DIST_INFO}/top_level.txt"] == b"materiais_em_lote\n", "Pacote superior incorreto.")
    wheel = BytesParser().parsebytes(members[f"{DIST_INFO}/WHEEL"])
    require(wheel["Root-Is-Purelib"] == "true" and wheel.get_all("Tag") == ["py3-none-any"],
            "Wheel precisa ser Python puro e independente de plataforma.")
    check_record(members)
    return {"wheel": path.name, "arquivos": len(members), "record": "sha256 verificado"}


def expected_source_files() -> frozenset[str]:
    """Inventário fechado; documentação/evidências extras ficam explícitas aqui."""
    return SOURCE_FILES


def check_sdist(path: Path) -> dict:
    require(path.name == f"{PREFIX}-{VERSION}.tar.gz", "Nome de sdist inesperado.")
    prefix = f"{PREFIX}-{VERSION}/"
    expected = expected_source_files() | SOURCE_GENERATED
    allowed_directories = {parent.as_posix() for name in expected
                           for parent in PurePosixPath(name).parents if parent.as_posix() != "."}
    with tarfile.open(path, "r:gz") as archive:
        files = {}
        for member in archive.getmembers():
            if member.name == prefix.rstrip("/") and member.isdir():
                continue
            require(member.name.startswith(prefix), "Raiz incorreta no sdist.")
            name = member.name[len(prefix):]
            safe_name(name)
            if member.isdir():
                require(name in allowed_directories, "Diretório não declarado no sdist.")
                continue
            require(member.isfile(), "sdist contém link ou arquivo especial.")
            require(name not in files, "sdist tem nomes repetidos.")
            files[name] = archive.extractfile(member).read()
    require(set(files) == expected, "Inventário do sdist divergente: " + repr(sorted(set(files) ^ expected)))
    check_metadata(files["PKG-INFO"])
    check_metadata(files[f"src/{PREFIX}.egg-info/PKG-INFO"])
    check_entry_points(files[f"src/{PREFIX}.egg-info/entry_points.txt"])
    source_list = files[f"src/{PREFIX}.egg-info/SOURCES.txt"].decode("utf-8").splitlines()
    expected_manifest = expected_source_files() | (SOURCE_GENERATED - {"PKG-INFO", "setup.cfg"})
    require(len(source_list) == len(set(source_list)) and set(source_list) == expected_manifest,
            "SOURCES.txt diverge do inventário público.")
    require(files["PKG-INFO"] == files[f"src/{PREFIX}.egg-info/PKG-INFO"], "Metadados do sdist divergentes.")
    require(files[f"src/{PREFIX}.egg-info/requires.txt"].splitlines() ==
            [b"openpyxl==3.1.5", b"et-xmlfile==2.0.0"], "Dependências do sdist divergentes.")
    for name in expected_source_files():
        local = ROOT / name
        require(local.is_file() and not local.is_symlink(), "Fonte pública ausente: " + name)
        require(files[name] == local.read_bytes(), "sdist difere da fonte revisada: " + name)
    return {"sdist": path.name, "arquivos": len(files)}


def check_dist(directory: Path) -> dict:
    require(directory.is_dir(), "Diretório de distribuição inexistente.")
    artifacts = {path.name for path in directory.iterdir()}
    expected = {f"{PREFIX}-{VERSION}-py3-none-any.whl", f"{PREFIX}-{VERSION}.tar.gz"}
    require(artifacts == expected, "dist deve conter somente wheel e sdist esperados.")
    wheel_path = directory / f"{PREFIX}-{VERSION}-py3-none-any.whl"
    sdist_path = directory / f"{PREFIX}-{VERSION}.tar.gz"
    result = {"wheel": check_wheel(wheel_path), "sdist": check_sdist(sdist_path)}
    with zipfile.ZipFile(wheel_path) as archive:
        for name in PACKAGE_FILES:
            require(archive.read(name) == (ROOT / "src" / name).read_bytes(),
                    "Wheel difere da fonte revisada: " + name)
        for name in ("LICENSE", "THIRD-PARTY-NOTICES.md"):
            require(archive.read(f"{DIST_INFO}/licenses/{name}") == (ROOT / name).read_bytes(),
                    "Aviso de licença do wheel divergente.")
        with tarfile.open(sdist_path, "r:gz") as source:
            metadata = source.extractfile(f"{PREFIX}-{VERSION}/PKG-INFO").read()
        require(archive.read(f"{DIST_INFO}/METADATA") == metadata, "Metadados wheel/sdist divergentes.")
    return result


def check_example(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        require(len(archive.namelist()) == len(BUNDLE_FILES) and set(archive.namelist()) == BUNDLE_FILES,
                "Bundle de exemplo com inventário divergente.")
        require(archive.testzip() is None, "Bundle de exemplo com CRC incorreto.")


def check_installed() -> dict:
    distribution = importlib.metadata.distribution(NAME)
    check_metadata(distribution.read_text("METADATA").encode("utf-8"))
    check_entry_points(distribution.read_text("entry_points.txt").encode("utf-8"))
    package = importlib.import_module(PREFIX)
    base = Path(distribution.locate_file(".")).resolve()
    package_root = Path(package.__file__).resolve().parent
    require(package_root == base / PREFIX, "Importação veio de fora da instalação regular.")
    require(not package_root.is_relative_to(ROOT / "src"), "Importação contaminada pela fonte.")
    require(getattr(package, "__version__", None) == VERSION, "Versão importada divergente.")
    present = set()
    for path in package_root.rglob("*"):
        require(not path.is_symlink(), "Link inesperado no pacote instalado.")
        if path.is_file():
            name = path.relative_to(base).as_posix()
            if path.suffix == ".pyc":
                require(path.parent.name == "__pycache__" and
                        any(path.name.startswith(Path(item).stem + ".") for item in PACKAGE_FILES),
                        "Bytecode instalado inesperado.")
            else:
                present.add(name)
    require(present == PACKAGE_FILES, "Inventário do pacote instalado divergente.")
    direct_url = distribution.read_text("direct_url.json")
    require(not direct_url or not json.loads(direct_url).get("dir_info", {}).get("editable", False),
            "Instalação editável não serve como prova de distribuição.")
    records = list(csv.reader(io.StringIO(distribution.read_text("RECORD"), newline="")))
    require(all(len(row) == 3 for row in records), "RECORD instalado inválido.")
    require(len({row[0] for row in records}) == len(records), "RECORD instalado duplicado.")
    recorded_names = {row[0] for row in records}
    require(WHEEL_FILES <= recorded_names, "RECORD instalado perdeu arquivos do wheel.")
    for name, checksum, size in records:
        posix = PurePosixPath(name)
        installed_metadata = name in {f"{DIST_INFO}/{file}" for file in ("INSTALLER", "REQUESTED", "direct_url.json")}
        generated_cache = (posix.parent.as_posix() == f"{PREFIX}/__pycache__" and posix.suffix == ".pyc"
                           and any(posix.name.startswith(Path(item).stem + ".") for item in PACKAGE_FILES))
        console = bool(re.fullmatch(r"(?:\.\./)+(?:bin|Scripts)/materiais-em-lote(?:\.exe)?", name))
        require(name in WHEEL_FILES or installed_metadata or generated_cache or console,
                "Arquivo inesperado no RECORD instalado: " + name)
        path = Path(distribution.locate_file(name))
        require(path.is_file() and not path.is_symlink(), "Arquivo instalado ausente ou link.")
        if console:
            command_name = NAME + (".exe" if os.name == "nt" else "")
            require(path.resolve() == (Path(sys.executable).absolute().parent / command_name).resolve(),
                    "Script de console aponta para fora do ambiente instalado.")
        if checksum:
            require(checksum == "sha256=" + digest(path.read_bytes()) and size == str(path.stat().st_size),
                    "Hash instalado divergente: " + name)
        else:
            require((name == f"{DIST_INFO}/RECORD" or generated_cache) and size == "",
                    "Arquivo instalado sem hash permitido.")
    return {"instalado": VERSION, "arquivos_python": len(present), "record": "sha256 verificado"}


def run(command: list[str], directory: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=directory, env=env, check=True, text=True,
                          encoding="utf-8", capture_output=True)


def check_install(artifact: Path) -> dict:
    artifact = artifact.resolve(strict=True)
    require(artifact.name.endswith((".whl", ".tar.gz")), "Informe wheel ou sdist.")
    with tempfile.TemporaryDirectory(prefix="materiais-install-") as temporary:
        work = Path(temporary)
        virtual = work / "venv"
        venv.EnvBuilder(with_pip=True).create(virtual)
        scripts = virtual / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        cli = scripts / (NAME + (".exe" if os.name == "nt" else ""))
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env["PYTHONUTF8"] = "1"
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        run([str(python), "-I", "-m", "pip", "install", "--no-input", str(artifact)], work, env)
        installed = run([str(python), "-I", str(Path(__file__).resolve()), "--installed"], work, env)
        version = run([str(cli), "--version"], work, env)
        require(VERSION in version.stdout and not version.stderr, "CLI instalada não informou a versão.")
        run([str(cli), "exemplo", "--saida", "exemplo.zip"], work, env)
        check_example(work / "exemplo.zip")
        run([str(python), "-I", str(ROOT / "tools/check_bundle.py"), "exemplo.zip", "--demo"], work, env)
        sentinel = b"destino existente: preservar\n"
        (work / "existente.zip").write_bytes(sentinel)
        result = subprocess.run([str(cli), "exemplo", "--saida", "existente.zip"], cwd=work,
                                env=env, capture_output=True)
        require(result.returncode == 3 and not result.stdout and b"Traceback" not in result.stderr,
                "CLI instalada deve recusar o destino existente com erro de I/O.")
        require((work / "existente.zip").read_bytes() == sentinel, "Destino existente foi alterado.")
        leftovers = {path.name for path in work.iterdir()} - {"venv", "exemplo.zip", "existente.zip"}
        require(not leftovers, "Instalação deixou arquivos temporários fora do venv.")
        return {"artefato": artifact.name, "instalacao": json.loads(installed.stdout),
                "cli": "executada fora da fonte", "exemplo": "leitor independente aprovou",
                "destino_existente": "preservado"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dist", type=Path)
    modes.add_argument("--install", type=Path)
    modes.add_argument("--installed", action="store_true")
    args = parser.parse_args()
    try:
        result = check_dist(args.dist) if args.dist else check_install(args.install) if args.install else check_installed()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (DistributionError, OSError, zipfile.BadZipFile, tarfile.TarError, subprocess.CalledProcessError) as error:
        print("Falha na conferência da distribuição: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
