"""Arquivos finais, fronteira de publicação e execução real da CLI."""

from fractions import Fraction
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

from openpyxl import load_workbook

from materiais_em_lote import build_bundle, demo_mapping, publish_bundle


ROOT = Path(__file__).resolve().parents[1]
NAMES = {"projeto.json", "plano.json", "plano.csv", "plano.md", "plano.xlsx", "LEIA-ME.md", "manifesto.json"}


def source(mapping=None):
    return (json.dumps(demo_mapping() if mapping is None else mapping, ensure_ascii=False, indent=2) + "\n").encode()


def members(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.testzip() is not None:
            raise AssertionError("CRC inválido")
        return {name: archive.read(name) for name in archive.namelist()}


class ReportsTest(unittest.TestCase):
    def test_complete_bundle_manifest_and_literal_source(self):
        raw = source()
        files = members(build_bundle(raw))
        self.assertEqual(set(files), NAMES)
        self.assertEqual(files["projeto.json"], raw)
        manifest = json.loads(files["manifesto.json"])
        self.assertEqual(set(manifest), {"version", "packageVersion", "inputSHA256", "files"})
        self.assertEqual(manifest["packageVersion"], "1.0.0")
        self.assertEqual(manifest["inputSHA256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual([v["name"] for v in manifest["files"]], sorted(NAMES - {"manifesto.json"}))
        for item in manifest["files"]:
            self.assertEqual(item["size"], len(files[item["name"]]))
            self.assertEqual(item["sha256"], hashlib.sha256(files[item["name"]]).hexdigest())

    def test_manual_demo_values_and_no_cross_unit_total(self):
        report = json.loads(members(build_bundle(source()))["plano.json"])
        rows = {r["item"]: r for r in report["items"]}
        self.assertEqual(Fraction(rows["tinta"]["gross"]), Fraction(3, 2))
        self.assertEqual(Fraction(rows["tinta"]["planned"]), 2)
        self.assertEqual(Fraction(rows["tinta"]["leftover"]), Fraction(4, 5))
        self.assertEqual(Fraction(rows["painel"]["planned"]), 6)
        self.assertEqual(Fraction(rows["suporte"]["net"]), 7)
        self.assertNotIn("total", report)
        self.assertEqual(len(report["origins"]), 10)
        self.assertEqual({v["source"] for v in report["origins"] if v["item"] == "tinta"}, {"kit", "expositor", "painel"})

    def test_deterministic_complete_archives_and_fixed_metadata(self):
        first, second = build_bundle(source()), build_bundle(source())
        self.assertEqual(first, second)
        for blob in (first, members(first)["plano.xlsx"]):
            with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                self.assertEqual(archive.namelist(), sorted(archive.namelist()))
                self.assertTrue(all(i.date_time == (1980, 1, 1, 0, 0, 0) for i in archive.infolist()))
        inner = members(members(first)["plano.xlsx"])
        core = ET.fromstring(inner["docProps/core.xml"])
        for tag in ("created", "modified"):
            self.assertEqual(core.find("{http://purl.org/dc/terms/}" + tag).text, "2000-01-01T00:00:00Z")

    def test_xlsx_exact_text_and_literal_formula_leaders(self):
        mapping = demo_mapping()
        labels = ["=SUM(1,2)", "+1+1", "-2+3", "@teste", "Aço & madeira <nova>", "Peça | `especial`"]
        for item, label in zip(mapping["items"], labels):
            item["name"] = label
        mapping["title"] = "=Um cenário & <literal>"
        files = members(build_bundle(source(mapping)))
        book = load_workbook(io.BytesIO(files["plano.xlsx"]), data_only=False, keep_links=False)
        self.assertEqual(book.sheetnames, ["Plano", "Origens", "Pedidos", "Estrutura"])
        self.assertEqual(book.properties.title, mapping["title"])
        names = {row[0].value: row[1] for row in list(book["Plano"].rows)[1:]}
        for item in mapping["items"]:
            self.assertEqual(names[item["id"]].value, item["name"])
            self.assertEqual(names[item["id"]].data_type, "s")
        for sheet in book:
            self.assertEqual(sheet.freeze_panes, "A2")
            self.assertEqual(sheet.page_setup.fitToWidth, 1)
            for row in sheet:
                for cell in row:
                    self.assertNotEqual(cell.data_type, "f")
                    self.assertIsNone(cell.hyperlink)
        csv_text = files["plano.csv"].decode()
        self.assertIn("'=SUM", csv_text)
        self.assertIn("'+1+1", csv_text)
        self.assertIn("'-2+3", csv_text)
        self.assertIn("'@teste", csv_text)
        self.assertIn("&lt;", files["plano.md"].decode())
        self.assertNotIn("<nova>", files["plano.md"].decode())
        inner = members(files["plano.xlsx"])
        ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        for name, value in inner.items():
            if name.startswith("xl/worksheets/") and name.endswith(".xml"):
                self.assertEqual(ET.fromstring(value).findall(".//s:f", ns), [])

    def test_empty_demands_keep_stock_without_invented_origins(self):
        mapping = demo_mapping()
        mapping["demands"] = []
        files = members(build_bundle(source(mapping)))
        report = json.loads(files["plano.json"])
        self.assertEqual(report["origins"], [])
        self.assertTrue(all(Fraction(r["gross"]) == 0 and r["stock"] == r["leftover"] for r in report["items"]))
        self.assertIn("Sem demanda", files["plano.md"].decode())

    def test_ooxml_escape_lookalikes_are_protected_in_the_wire_text(self):
        mapping = demo_mapping()
        names = ["_x0041_", "_x000D_", "_x005F_x0041_", "_x0041__x0042_", "_x0041_x0042_", "_xD83D__xDE00_ ação"]
        expected = ["_x005F_x0041_", "_x005F_x000D_", "_x005F_x005F_x005F_x0041_",
                    "_x005F_x0041__x005F_x0042_", "_x005F_x0041_x005F_x0042_",
                    "_x005F_xD83D__x005F_xDE00_ ação"]
        for item, name in zip(mapping["items"], names):
            item["name"] = name
        files = members(build_bundle(source(mapping)))
        report = json.loads(files["plano.json"])
        self.assertEqual({r["name"] for r in report["items"]}, set(names))
        inner = members(files["plano.xlsx"])
        ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        root = ET.fromstring(inner["xl/worksheets/sheet1.xml"])
        text = {cell.attrib["r"]: "".join(cell.itertext()) for cell in root.findall(".//s:c", ns)}
        encoded_by_id = dict(zip((i["id"] for i in mapping["items"]), expected))
        for row, item in enumerate(report["items"], 2):
            self.assertEqual(text[f"B{row}"], encoded_by_id[item["item"]])

    def test_atomic_new_publication_and_existing_file_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "novo.zip"
            publish_bundle(source(), output)
            before = output.read_bytes()
            with self.assertRaises(FileExistsError):
                publish_bundle(source(), output)
            self.assertEqual(output.read_bytes(), before)
            self.assertEqual(list(Path(directory).iterdir()), [output])

    def test_existing_directory_or_symlink_are_never_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "novo.zip"
            output.mkdir()
            with self.assertRaises(OSError):
                publish_bundle(source(), output)
            self.assertTrue(output.is_dir())
            if os.name != "nt":
                output.rmdir()
                original = root / "original"
                original.write_bytes(b"preservar")
                output.symlink_to(original)
                with self.assertRaises(OSError):
                    publish_bundle(source(), output)
                self.assertTrue(output.is_symlink())
                self.assertEqual(original.read_bytes(), b"preservar")

    def test_failed_link_and_fsync_leave_no_partial_destination_or_temp(self):
        for failing in ("os.link", "os.fsync"):
            with self.subTest(failing=failing), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "plano.zip"
                with patch("materiais_em_lote.reports." + failing, side_effect=OSError("falha simulada")):
                    with self.assertRaises(OSError):
                        publish_bundle(source(), output)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_validation_failure_never_creates_output(self):
        with tempfile.TemporaryDirectory() as directory:
            from materiais_em_lote import PlanError
            with self.assertRaises(PlanError):
                publish_bundle(b'{"version":1}', Path(directory) / "novo.zip")
            self.assertEqual(list(Path(directory).iterdir()), [])


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        return subprocess.run([sys.executable, "-m", "materiais_em_lote", *map(str, args)],
                              env=environment, capture_output=True, text=True, timeout=20)

    def test_version_help_and_sanitized_bad_usage(self):
        self.assertEqual(self.run_cli("--version").stdout.strip(), "materiais-em-lote 1.0.0")
        self.assertEqual(self.run_cli("planejar", "--help").returncode, 0)
        invalid = self.run_cli("exemplo", "--private-SYNTHETIC-MARKER")
        self.assertEqual(invalid.returncode, 2)
        self.assertNotIn("SYNTHETIC-MARKER", invalid.stderr)

    def test_example_cli_real_files_and_existing_destination_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "oficina.zip"
            result = self.run_cli("exemplo", "--saida", output)
            self.assertEqual(result.returncode, 0, result.stderr)
            files = members(output.read_bytes())
            self.assertEqual(set(files), NAMES)
            digest = hashlib.sha256(output.read_bytes()).digest()
            again = self.run_cli("exemplo", "--saida", output)
            self.assertEqual(again.returncode, 3)
            self.assertEqual(hashlib.sha256(output.read_bytes()).digest(), digest)
            self.assertNotIn(directory, again.stderr)

    def test_planning_preserves_input_and_invalid_input_has_no_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "entrada.json"
            output = root / "plano.zip"
            raw = source()
            project.write_bytes(raw)
            self.assertEqual(self.run_cli("planejar", project, "--saida", output).returncode, 0)
            self.assertEqual(project.read_bytes(), raw)
            self.assertEqual(members(output.read_bytes())["projeto.json"], raw)
            invalid = root / "invalido.json"
            invalid.write_text('{"version":1,"private-SYNTHETIC-MARKER":"value"}')
            failure = self.run_cli("planejar", invalid, "--saida", root / "falha.zip")
            self.assertEqual(failure.returncode, 2)
            self.assertNotIn("SYNTHETIC-MARKER", failure.stderr)
            self.assertNotIn(directory, failure.stderr)
            self.assertFalse((root / "falha.zip").exists())

    def test_large_input_and_missing_parent_are_explicit_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            large = root / "grande.json"
            large.write_bytes(b" " * (1024 * 1024 + 1))
            result = self.run_cli("planejar", large, "--saida", root / "falha.zip")
            self.assertEqual(result.returncode, 2)
            self.assertIn("E_LIMIT", result.stderr)
            result = self.run_cli("exemplo", "--saida", root / "ausente" / "plano.zip")
            self.assertEqual(result.returncode, 3)
            self.assertFalse((root / "ausente").exists())

    @unittest.skipIf(os.name == "nt", "FIFO POSIX")
    def test_fifo_is_rejected_without_waiting_for_a_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "entrada"
            os.mkfifo(path)
            result = self.run_cli("planejar", path, "--saida", Path(directory) / "falha.zip")
            self.assertEqual(result.returncode, 3)


if __name__ == "__main__":
    unittest.main()
