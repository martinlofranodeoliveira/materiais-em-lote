"""Negative artifact checks and replayable evidence; no core/report imports."""
from __future__ import annotations

import hashlib
import io
import json
from fractions import Fraction
from pathlib import Path
import sys
import shutil
import tempfile
import unittest
import zipfile

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
from check_bundle import CheckError, check_bundle, decode_xstring, expected_plan, json_bytes, quantity_text, rich_text, workbook_cells, zip_members
from verify_libreoffice import check_artifacts, check_fixtures, ods_cells, verify_audit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "interop"


def archive(members):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as target:
        for name in sorted(members):
            entry = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(entry, members[name])
    return output.getvalue()


def rehash(members):
    manifesto = json.loads(members["manifesto.json"])
    manifesto["inputSHA256"] = hashlib.sha256(members["projeto.json"]).hexdigest()
    manifesto["files"] = [{"name": name, "size": len(members[name]), "sha256": hashlib.sha256(members[name]).hexdigest()} for name in sorted(members) if name != "manifesto.json"]
    members["manifesto.json"] = json.dumps(manifesto).encode()
    return archive(members)


class IndependentBoundaryTests(unittest.TestCase):
    def test_rational_serialization_preserves_exactness(self):
        self.assertEqual(quantity_text(Fraction(1, 3)), "1/3")
        self.assertEqual(quantity_text(Fraction(1000000000000000001, 1000000000000000000)), "1.000000000000000001")
        self.assertEqual(quantity_text(Fraction(4, 5)), "0.8")
        with self.assertRaises(CheckError):
            quantity_text(Fraction(10**12 + 1))

    def test_json_rejects_duplicate_keys_float_and_deep_input(self):
        for value in (b'{"a":1,"a":2}', b'{"a":0.5}', b'{"a":NaN}', b'\xef\xbb\xbf{}', b'[' * 14 + b'0' + b']' * 14):
            with self.subTest(value=value), self.assertRaises(CheckError):
                json_bytes(value)

    def test_xstring_decodes_once_and_combines_utf16_pairs(self):
        cases = {
            "_x0041_": "A", "_x000D_": "\r", "_x005f_x0041_": "_x0041_",
            "_x005F_x005F_x005F_x0041_": "_x005F_x0041_",
            "_x005F_x0041__x005F_x000D_": "_x0041__x000D_",
            "_x005F_x0041_x005F_x000D_": "_x0041_x000D_",
            "_xD83D__xDE00_": "😀",
            "_x005F_xD83D__x005F_xDE00_": "_xD83D__xDE00_",
            "item_x005F_x0041_": "item_x0041_",
        }
        for encoded, expected in cases.items():
            with self.subTest(encoded=encoded):
                self.assertEqual(decode_xstring(encoded), expected)
        for invalid in ("_xD83D_", "_xDE00_", "_xD83D__x0041_"):
            with self.subTest(invalid=invalid), self.assertRaises(CheckError):
                decode_xstring(invalid)

    def test_xstring_does_not_decode_across_rich_text_run_boundaries(self):
        from xml.etree import ElementTree as ET
        fragment = ET.fromstring('<si xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><r><t>_x00</t></r><r><t>41_</t></r><rPh sb="0" eb="1"><t>phonetic annotation</t></rPh></si>')
        self.assertEqual(rich_text(fragment), "_x0041_")

    def test_inline_and_shared_xstring_cells_have_same_semantics(self):
        bodies = (
            '<t>_x005F_x0041_</t>',
            '<t>_x005F_x005F_x005F_x0041_</t>',
            '<t>_x005F_x0041_x005F_x000D_</t>',
            '<r><t>_x00</t></r><r><t>41_</t></r>',
            '<t>_xD83D__xDE00_</t>',
        )
        expected = ("_x0041_", "_x005F_x0041_", "_x0041_x000D_", "_x0041_", "😀")
        members = {
            "[Content_Types].xml": b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
            "xl/workbook.xml": b'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Teste" sheetId="1" r:id="rId1"/></sheets></workbook>',
            "xl/_rels/workbook.xml.rels": b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/></Relationships>',
            "xl/sharedStrings.xml": ('<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' + ''.join('<si>'+body+'</si>' for body in bodies) + '</sst>').encode(),
        }
        rows = ''.join(f'<row r="{index}"><c r="A{index}" t="inlineStr"><is>{body}</is></c><c r="B{index}" t="s"><v>{index-1}</v></c></row>' for index, body in enumerate(bodies, 1))
        members["xl/worksheets/sheet1.xml"] = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+rows+'</sheetData></worksheet>').encode()
        result = workbook_cells(archive(members))["Teste"]
        for row, value in enumerate(expected, 1):
            self.assertEqual(result[f"A{row}"], ("text", value, None))
            self.assertEqual(result[f"B{row}"], ("text", value, None))

    def test_zip_rejects_path_traversal(self):
        with self.assertRaises(CheckError):
            zip_members(archive({"../outside": b"bad"}))

    def test_stock_at_subassembly_reduces_shared_descendant(self):
        project = {"version": 1, "title": "Caso manual", "items": [
            {"id": "raiz", "name": "Raiz", "unit": "un", "kind": "make", "batch": "2", "components": [{"item": "ramo", "quantity": "1"}, {"item": "comum", "quantity": "1"}]},
            {"id": "ramo", "name": "Ramo", "unit": "un", "kind": "make", "batch": "1", "components": [{"item": "comum", "quantity": "2"}]},
            {"id": "comum", "name": "Comum", "unit": "un", "kind": "buy", "pack": "3"}],
            "demands": [{"id": "pedido", "item": "raiz", "quantity": "3"}], "stock": [{"item": "ramo", "quantity": "1"}, {"item": "comum", "quantity": "1"}]}
        result = expected_plan(project)
        rows = {row["item"]: row for row in result["items"]}
        self.assertEqual((rows["ramo"]["gross"], rows["ramo"]["lots"]), ("2", 1))
        self.assertEqual((rows["comum"]["gross"], rows["comum"]["lots"], rows["comum"]["leftover"]), ("4", 1, "0"))
        self.assertEqual([(origin["source"], origin["quantity"]) for origin in result["origins"] if origin["item"] == "comum"], [("raiz", "2"), ("ramo", "2")])


@unittest.skipUnless((FIXTURES / "demo.zip").is_file(), "Fixture binária não distribuída nesta cópia")
class StoredArtifactTests(unittest.TestCase):
    def setUp(self):
        self.demo = (FIXTURES / "demo.zip").read_bytes()

    def test_stored_external_evidence_does_not_claim_new_run(self):
        result = check_fixtures(FIXTURES)
        self.assertEqual(result["mode"], "stored-evidence-only")
        self.assertFalse(result["newExternalExecution"])
        self.assertEqual(result["status"], "completed-with-consumer-limitation")
        self.assertFalse(result["results"]["textRoundtripExact"])
        self.assertTrue(result["results"]["initialImports"]["text"]["equal"])
        self.assertEqual(result["results"]["initialImports"]["text"]["cellsCompared"], 243)
        self.assertFalse(result["results"]["staticRoundtrips"]["text"]["equal"])
        self.assertEqual([d["cell"] for d in result["results"]["staticRoundtrips"]["text"]["differences"]], ["B5", "B6"])
        self.assertEqual(result["results"]["audit"]["formulaCachesChecked"], 72)
        self.assertEqual(result["results"]["staticRoundtrips"]["demo"]["cellsCompared"], 171)

    def test_strict_mode_rejects_known_consumer_loss(self):
        with self.assertRaises(CheckError):
            check_artifacts(FIXTURES)

    def test_explicit_limitation_flag_rejects_any_additional_loss(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            for source in FIXTURES.iterdir():
                if source.is_file():
                    shutil.copyfile(source, temporary / source.name)
            target = temporary / "text-libreoffice.xlsx"
            workbook = zip_members(target.read_bytes())
            from xml.etree import ElementTree as ET
            tree = ET.fromstring(workbook["xl/worksheets/sheet1.xml"])
            namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            cell = tree.find(".//m:c[@r='A2']", namespace)
            cell.clear()
            cell.set("r", "A2")
            cell.set("t", "inlineStr")
            inline = ET.SubElement(cell, "{" + namespace["m"] + "}is")
            ET.SubElement(inline, "{" + namespace["m"] + "}t").text = "additional-loss"
            workbook["xl/worksheets/sheet1.xml"] = ET.tostring(tree)
            target.write_bytes(archive(workbook))
            with self.assertRaises(CheckError):
                check_artifacts(temporary, allow_known_export_limitation=True)

    def test_initial_import_matches_every_original_cell(self):
        original = workbook_cells((FIXTURES / "text-original.xlsx").read_bytes())
        imported = ods_cells((FIXTURES / "text-import.ods").read_bytes())
        self.assertEqual(original, imported)
        self.assertEqual(original["Plano"]["B5"], ("text", "_x005F_x0041_", None))
        self.assertEqual(original["Plano"]["B6"], ("text", "_x0041_x000D_", None))
        reopened = ods_cells((FIXTURES / "text-reopened.ods").read_bytes())
        self.assertEqual(reopened["Plano"]["B5"], ("text", "_x0041_", None))
        self.assertEqual(reopened["Plano"]["B6"], ("text", "_x0041\r", None))

    def test_hash_failure_is_detected(self):
        members = zip_members(self.demo, bundle=True)
        members["plano.md"] += b"\ntampered"
        with self.assertRaises(CheckError):
            check_bundle(archive(members), demo=True)

    def test_resigned_wrong_total_is_detected(self):
        members = zip_members(self.demo, bundle=True)
        plan = json.loads(members["plano.json"])
        next(row for row in plan["items"] if row["item"] == "tinta")["gross"] = "1.4"
        members["plano.json"] = json.dumps(plan).encode()
        with self.assertRaises(CheckError):
            check_bundle(rehash(members), demo=True)

    def test_resigned_duplicate_origin_is_detected(self):
        members = zip_members(self.demo, bundle=True)
        plan = json.loads(members["plano.json"])
        plan["origins"].append(dict(plan["origins"][0]))
        members["plano.json"] = json.dumps(plan).encode()
        with self.assertRaises(CheckError):
            check_bundle(rehash(members), demo=True)

    def test_static_workbook_rejects_inserted_formula(self):
        members = zip_members(self.demo, bundle=True)
        workbook = zip_members(members["plano.xlsx"])
        worksheet = "xl/worksheets/sheet1.xml"
        workbook[worksheet] = workbook[worksheet].replace(b"</sheetData>", b'<row r="99"><c r="A99"><f>1+1</f><v>2</v></c></row></sheetData>')
        members["plano.xlsx"] = archive(workbook)
        with self.assertRaises(CheckError):
            check_bundle(rehash(members))

    def test_workbook_rejects_external_relationship(self):
        workbook = zip_members(zip_members(self.demo, bundle=True)["plano.xlsx"])
        rel = "xl/_rels/workbook.xml.rels"
        workbook[rel] = workbook[rel].replace(b"</Relationships>", b'<Relationship Id="bad" Type="externalLink" Target="https://example.invalid/" TargetMode="External"/></Relationships>')
        with self.assertRaises(CheckError):
            workbook_cells(archive(workbook))

    def test_formula_looking_csv_text_must_keep_protection(self):
        members = zip_members((FIXTURES / "text.zip").read_bytes(), bundle=True)
        self.assertIn(b"'=1+1", members["plano.csv"])
        members["plano.csv"] = members["plano.csv"].replace(b"'=1+1", b"=1+1")
        with self.assertRaises(CheckError):
            check_bundle(rehash(members))

    def test_audit_rejects_wrong_cached_result(self):
        audit = zip_members((FIXTURES / "audit-libreoffice.xlsx").read_bytes())
        worksheet = "xl/worksheets/sheet1.xml"
        from xml.etree import ElementTree as ET
        tree = ET.fromstring(audit[worksheet])
        namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        cell = tree.find(".//m:c[@r='E2']/m:v", namespace)
        self.assertIsNotNone(cell)
        cell.text = "99"
        audit[worksheet] = ET.tostring(tree)
        with self.assertRaises(CheckError):
            verify_audit((FIXTURES / "audit-source.xlsx").read_bytes(), archive(audit))


if __name__ == "__main__":
    unittest.main()
