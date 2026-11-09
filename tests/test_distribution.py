"""O gate de distribuição deve recusar vazamentos e adulteração do RECORD."""
from __future__ import annotations

import csv
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
import zipfile


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_distribution.py"
SPEC = importlib.util.spec_from_file_location("distribution_check", SCRIPT)
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def wheel_members() -> dict[str, bytes]:
    members = {name: b"# pacote de teste\n" for name in CHECK.PACKAGE_FILES}
    metadata = ("Metadata-Version: 2.4\nName: materiais-em-lote\nVersion: 1.0.0\n"
                "Requires-Python: >=3.11\nLicense-Expression: MIT\n"
                "License-File: LICENSE\nLicense-File: THIRD-PARTY-NOTICES.md\n"
                "Requires-Dist: openpyxl==3.1.5\nRequires-Dist: et-xmlfile==2.0.0\n\n")
    prefix = CHECK.DIST_INFO + "/"
    members.update({
        prefix + "METADATA": metadata.encode(),
        prefix + "WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n",
        prefix + "entry_points.txt": b"[console_scripts]\nmateriais-em-lote = materiais_em_lote.cli:main\n",
        prefix + "top_level.txt": b"materiais_em_lote\n",
        prefix + "licenses/LICENSE": b"MIT License\n",
        prefix + "licenses/THIRD-PARTY-NOTICES.md": b"# Avisos\n",
    })
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    for name, data in sorted(members.items()):
        writer.writerow((name, "sha256=" + CHECK.digest(data), str(len(data))))
    writer.writerow((prefix + "RECORD", "", ""))
    members[prefix + "RECORD"] = output.getvalue().encode()
    return members


class DistributionGateTests(unittest.TestCase):
    def check_members(self, members: dict[str, bytes]) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "materiais_em_lote-1.0.0-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "x") as archive:
                for name, data in members.items():
                    archive.writestr(name, data)
            return CHECK.check_wheel(wheel)

    def test_accepts_exact_wheel_inventory_with_valid_record(self):
        self.assertEqual(self.check_members(wheel_members())["arquivos"], len(CHECK.WHEEL_FILES))

    def test_rejects_private_file_even_with_other_valid_contents(self):
        members = wheel_members()
        members["local/token.json"] = b'{}'
        with self.assertRaises(CHECK.DistributionError):
            self.check_members(members)

    def test_rejects_arbitrary_public_looking_module(self):
        members = wheel_members()
        members["materiais_em_lote/undocumented.py"] = b"# inesperado\n"
        with self.assertRaises(CHECK.DistributionError):
            self.check_members(members)

    def test_rejects_modified_bytes_after_record_was_created(self):
        members = wheel_members()
        members["materiais_em_lote/core.py"] += b"# adulterado\n"
        with self.assertRaisesRegex(CHECK.DistributionError, "Hash ou tamanho"):
            self.check_members(members)

    def test_rejects_unpinned_dependency_even_with_valid_record(self):
        members = wheel_members()
        name = CHECK.DIST_INFO + "/METADATA"
        members[name] = members[name].replace(b"openpyxl==3.1.5", b"openpyxl>=3.1.5")
        with self.assertRaisesRegex(CHECK.DistributionError, "Dependências"):
            self.check_members(members)

    def test_rejects_symlink_in_wheel(self):
        members = wheel_members()
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "materiais_em_lote-1.0.0-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "x") as archive:
                for name, data in members.items():
                    info = zipfile.ZipInfo(name)
                    info.create_system = 3
                    info.external_attr = (0o120777 if name.endswith("core.py") else 0o100644) << 16
                    archive.writestr(info, data)
            with self.assertRaisesRegex(CHECK.DistributionError, "regulares"):
                CHECK.check_wheel(wheel)

    def test_rejects_duplicate_archive_member(self):
        members = wheel_members()
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "materiais_em_lote-1.0.0-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "x") as archive:
                for name, data in members.items():
                    archive.writestr(name, data)
                with self.assertWarns(UserWarning):
                    archive.writestr("materiais_em_lote/core.py", b"duplicate\n")
            with self.assertRaisesRegex(CHECK.DistributionError, "repetidos"):
                CHECK.check_wheel(wheel)

    def test_source_inventory_never_contains_executables_or_private_paths(self):
        for name in CHECK.expected_source_files() | CHECK.SOURCE_GENERATED:
            CHECK.safe_name(name)
            self.assertFalse(name.endswith((".exe", ".bin", ".pyc", ".so", ".dll")), name)


if __name__ == "__main__":
    unittest.main()
