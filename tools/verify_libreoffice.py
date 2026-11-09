#!/usr/bin/env python3
"""External LibreOffice consumer QA, or honest verification of stored evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal

from check_bundle import CheckError, check_bundle, column_name, require, workbook_cells, xml, zip_members

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "interop"
TOLERANCE = Decimal("0.000000000001")
AUDIT_HEADERS = ("Item", "Lote", "Estoque", "Direta", "Bruta calculada", "Utilizado calculado", "Líquida calculada", "Lotes calculados", "Planejado calculado", "Saldo calculado", "Bruta esperada", "Utilizado esperado", "Líquida esperada", "Lotes esperados", "Planejado esperado", "Saldo esperado")
# The expected tuple is literal, rather than calculated by the production planner.
# Each parent pair is (parent row number in its sheet, quantity per parent batch).
AUDIT_SCENARIOS = {
    "Demo": [
        ("expositor", "1", "0", "2", (), ("2", "0", "2", "2", "2", "0")),
        ("kit", "2", "1", "3", (), ("3", "1", "2", "1", "2", "0")),
        ("painel", "3", "2", "0", ((2, "2"), (3, "3")), ("7", "2", "5", "2", "6", "1")),
        ("chapa", "2", "1", "0", ((4, "1"),), ("2", "1", "1", "1", "2", "1")),
        ("suporte", "4", "1", "0", ((2, "2"), (3, "4")), ("8", "1", "7", "2", "8", "1")),
        ("tinta", "1", "0.3", "0", ((2, "0.2"), (3, "0.5"), (4, "0.3")), ("1.5", "0.3", "1.2", "2", "2", "0.8")),
    ],
    "Estoque submontagem": [
        ("raiz", "1", "0", "4", (), ("4", "0", "4", "4", "4", "0")),
        ("submontagem", "2", "3", "0", ((2, "2"),), ("8", "3", "5", "3", "6", "1")),
        ("comprado", "4", "2", "0", ((3, "3"),), ("9", "2", "7", "2", "8", "1")),
    ],
    "Compartilhado em profundidades": [
        ("raiz", "2", "0", "3", (), ("3", "0", "3", "2", "4", "1")),
        ("ramo", "1", "1", "0", ((2, "1"),), ("2", "1", "1", "1", "1", "0")),
        ("compartilhado", "3", "1", "0", ((2, "1"), (3, "2")), ("4", "1", "3", "1", "3", "0")),
    ],
}


def audit_formulas(row, parents):
    gross = f"=D{row}" + "".join(f"+H{parent}*{quantity}" for parent, quantity in parents)
    return (gross, f"=MIN(E{row},C{row})", f"=MAX(E{row}-C{row},0)", f"=ROUNDUP(G{row}/B{row},0)", f"=H{row}*B{row}", f"=C{row}+I{row}-E{row}")


def make_audit(path):
    # openpyxl is only an authoring dependency of this external QA script.
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, rows in AUDIT_SCENARIOS.items():
        sheet = workbook.create_sheet(name)
        sheet.append(AUDIT_HEADERS)
        for row_index, (item, lot, stock, direct, parents, expected) in enumerate(rows, 2):
            sheet.append((item, float(lot), float(stock), float(direct), *audit_formulas(row_index, parents), *(float(value) for value in expected)))
        sheet.freeze_panes = "E2"
        for cell in sheet[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor="E6EFF2")
        for col in range(1, 17):
            sheet.column_dimensions[get_column_letter(col)].width = 23
    workbook.save(path)


def verify_audit(source, recalculated):
    original = workbook_cells(source, static=False)
    result = workbook_cells(recalculated, static=False)
    require(set(original) == set(AUDIT_SCENARIOS) == set(result), "Abas da auditoria divergentes")
    checked = 0
    for name, rows in AUDIT_SCENARIOS.items():
        before, after = original[name], result[name]
        for index, heading in enumerate(AUDIT_HEADERS, 1):
            col = chr(64 + index)
            require(before[f"{col}1"][1] == heading and after[f"{col}1"][1] == heading, "Cabeçalho da auditoria divergente")
        for row_index, (item, lot, stock, direct, parents, expected) in enumerate(rows, 2):
            require(before[f"A{row_index}"][1] == item == after[f"A{row_index}"][1], "Item da auditoria divergente")
            for offset, value in enumerate((lot, stock, direct), 2):
                ref = f"{chr(64 + offset)}{row_index}"
                require(Decimal(before[ref][1]) == Decimal(value) == Decimal(after[ref][1]), "Entrada literal da auditoria divergente")
            for offset, (formula, expected_value) in enumerate(zip(audit_formulas(row_index, parents), expected), 5):
                ref = f"{chr(64 + offset)}{row_index}"
                require(before[ref][2] == formula[1:], "Fórmula original da auditoria divergente")
                require(ref in after and after[ref][2] is not None and after[ref][0] == "number", "Fórmula sem cache numérico recalculado")
                cached = Decimal(after[ref][1])
                require(cached.is_finite() and abs(cached - Decimal(expected_value)) <= TOLERANCE, "Cache da auditoria diverge do esperado literal")
                literal_ref = f"{chr(64 + offset + 6)}{row_index}"
                require(Decimal(before[literal_ref][1]) == Decimal(expected_value) == Decimal(after[literal_ref][1]), "Esperado literal alterado")
                checked += 1
    return {"scenarios": len(AUDIT_SCENARIOS), "formulaCachesChecked": checked, "absoluteTolerance": str(TOLERANCE), "expectedValues": "independently authored literals"}


def digest(path):
    content = path.read_bytes()
    return {"sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}


def check_text_case(bundle):
    members = zip_members(bundle, bundle=True)
    plan = json.loads(members["plano.json"])
    names = {row["name"] for row in plan["items"]}
    require({"=1+1", "+SUM(A1:A2)", "-2+3", "@SUM(A1:A2)", "Aço <&> \"ação\" 'ç'", "_x0041_", "_x000D_", "_x005F_x0041_", "_x0041__x000D_", "_x0041_x000D_", "_xD83D__xDE00_"} == names, "Bundle de texto não contém todos os payloads autorais exatos")
    require("item_x0041_" in {row["item"] for row in plan["items"]}, "ID literal ST_Xstring ausente")
    require(plan["title"] == "=Oficina <A&B> – ação", "Título de texto divergente")


ODNS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}
EVIDENCE_FILES = {"demo.zip", "text.zip", "demo-original.xlsx", "demo-libreoffice.xlsx", "text-original.xlsx", "text-libreoffice.xlsx", "audit-source.xlsx", "audit-libreoffice.xlsx", "demo-import.ods", "text-import.ods", "text-reopened.ods"}


def ods_text(element):
    parts = [element.text or ""]
    for child in element:
        if child.tag == f"{{{ODNS['text']}}}s":
            count = int(child.get(f"{{{ODNS['text']}}}c", "1"))
            require(1 <= count <= 10000, "Repetição de espaços ODS excessiva")
            parts.append(" " * count)
        elif child.tag == f"{{{ODNS['text']}}}tab":
            parts.append("\t")
        elif child.tag == f"{{{ODNS['text']}}}line-break":
            parts.append("\n")
        else:
            parts.append(ods_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def ods_cells(data):
    """Read the consumer's initial import using ODF, without ST_Xstring escapes."""
    members = zip_members(data, allow_directories=True)
    require(members.get("mimetype") == b"application/vnd.oasis.opendocument.spreadsheet", "Mimetype ODS divergente")
    require(not any(name.lower().startswith(("basic/", "scripts/")) for name in members), "Macros em ODS")
    root = xml(members["content.xml"])
    require(root.find("office:scripts", ODNS) is None or not list(root.find("office:scripts", ODNS)), "Scripts ODS")
    for node in root.iter():
        require(f"{{{ODNS['table']}}}formula" not in node.attrib, "Fórmula em importação de relatório estático")
        require("{http://www.w3.org/1999/xlink}href" not in node.attrib, "Relação externa em conteúdo ODS")
    result = {}
    for table in root.findall("office:body/office:spreadsheet/table:table", ODNS):
        name = table.get(f"{{{ODNS['table']}}}name")
        require(name and name not in result, "Aba ODS repetida ou sem nome")
        cells = {}
        row_index = 1
        for row in table.iter(f"{{{ODNS['table']}}}table-row"):
            row_repeat = int(row.get(f"{{{ODNS['table']}}}number-rows-repeated", "1"))
            require(1 <= row_repeat <= 1048576 and row_index + row_repeat <= 1048577, "Limite de linhas ODS")
            column_index = 1
            for cell in row:
                require(cell.tag in (f"{{{ODNS['table']}}}table-cell", f"{{{ODNS['table']}}}covered-table-cell"), "Célula ODS inesperada")
                col_repeat = int(cell.get(f"{{{ODNS['table']}}}number-columns-repeated", "1"))
                require(1 <= col_repeat <= 16384 and column_index + col_repeat <= 16385, "Limite de colunas ODS")
                kind = cell.get(f"{{{ODNS['office']}}}value-type")
                if kind is not None:
                    if kind == "string":
                        value = "\n".join(ods_text(p) for p in cell.findall("text:p", ODNS))
                        explicit = cell.get(f"{{{ODNS['office']}}}string-value")
                        if explicit is not None:
                            require(not value or value == explicit, "Texto ODS visível diverge do valor explícito")
                            value = explicit
                        cell_type = "text"
                    elif kind == "float":
                        raw = cell.get(f"{{{ODNS['office']}}}value", "")
                        require(re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.0+)?", raw), "Número ODS não inteiro")
                        value, cell_type = int(Decimal(raw)), "integer"
                    else:
                        raise CheckError("Tipo de célula ODS inesperado")
                    require(row_repeat * col_repeat <= 10000 and len(cells) + row_repeat * col_repeat <= 10000, "Células ODS demais")
                    for row_offset in range(row_repeat):
                        for col_offset in range(col_repeat):
                            ref = f"{column_name(column_index + col_offset)}{row_index + row_offset}"
                            cells[ref] = (cell_type, value, None)
                column_index += col_repeat
            row_index += row_repeat
        result[name] = cells
    return result


def cell_differences(expected, actual):
    result = []
    for sheet in sorted(set(expected) | set(actual)):
        for ref in sorted(set(expected.get(sheet, {})) | set(actual.get(sheet, {}))):
            wanted, got = expected.get(sheet, {}).get(ref), actual.get(sheet, {}).get(ref)
            if wanted != got:
                result.append({"sheet": sheet, "cell": ref, "expected": list(wanted) if wanted is not None else None, "actual": list(got) if got is not None else None})
    return result


def known_text_export_loss(differences):
    expected = [
        {"sheet": "Plano", "cell": "B5", "expected": ["text", "_x005F_x0041_", None], "actual": ["text", "_x0041_", None]},
        {"sheet": "Plano", "cell": "B6", "expected": ["text", "_x0041_x000D_", None], "actual": ["text", "_x0041\r", None]},
    ]
    return differences == expected


def check_artifacts(directory, *, allow_known_export_limitation=False):
    demo = (directory / "demo.zip").read_bytes()
    text = (directory / "text.zip").read_bytes()
    demo_result = check_bundle(demo, demo=True)
    text_result = check_bundle(text)
    check_text_case(text)
    workbook_results, imports = {}, {}
    text_exact = True
    for label, bundle in (("demo", demo), ("text", text)):
        generated = zip_members(bundle, bundle=True)["plano.xlsx"]
        original = (directory / f"{label}-original.xlsx").read_bytes()
        consumed = (directory / f"{label}-libreoffice.xlsx").read_bytes()
        require(original == generated, "Workbook original não é o produzido pelo bundle CLI")
        before = workbook_cells(original, static=True)
        imported = ods_cells((directory / f"{label}-import.ods").read_bytes())
        require(before == imported, "LibreOffice alterou células/tipos/textos durante a importação inicial para ODS")
        imports[label] = {"sheets": len(before), "cellsCompared": sum(len(cells) for cells in before.values()), "equal": True}
        after = workbook_cells(consumed, static=True)
        differences = cell_differences(before, after)
        if label == "demo":
            require(not differences, "LibreOffice alterou a demonstração na reexportação XLSX")
        else:
            text_exact = not differences
            require(not differences or allow_known_export_limitation and known_text_export_loss(differences), "LibreOffice alterou células/tipos/textos do relatório estático; use a flag explícita somente para registrar o contraexemplo conhecido")
            reopened = ods_cells((directory / "text-reopened.ods").read_bytes())
            require(after == reopened, "Reimportação ODS não confirma a semântica do XLSX reexportado")
        title_tag = "{http://purl.org/dc/elements/1.1/}title"
        original_title = xml(zip_members(original)["docProps/core.xml"]).findtext(title_tag)
        consumed_title = xml(zip_members(consumed)["docProps/core.xml"]).findtext(title_tag)
        require(original_title == consumed_title, "LibreOffice alterou o título autoral do workbook")
        workbook_results[label] = {"sheets": len(before), "cellsCompared": sum(len(cells) for cells in before.values()), "equal": not differences, "differences": differences}
    audit_result = verify_audit((directory / "audit-source.xlsx").read_bytes(), (directory / "audit-libreoffice.xlsx").read_bytes())
    return {"demoBundle": demo_result, "textBundle": text_result, "initialImports": imports, "staticRoundtrips": workbook_results, "textRoundtripExact": text_exact, "textReopenedConfirmed": True, "audit": audit_result}


def check_fixtures(directory):
    evidence_path = directory / "evidence.json"
    require(evidence_path.is_file(), "Evidência externa armazenada ausente")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    require(evidence.get("kind") == "actual-libreoffice-execution" and evidence.get("status") in ("ok", "completed-with-consumer-limitation"), "Registro não documenta execução externa bem-sucedida")
    require(type(evidence.get("files")) is dict and set(evidence["files"]) == EVIDENCE_FILES, "Inventário de evidência divergente")
    for name, expected in evidence["files"].items():
        require(digest(directory / name) == expected, "Hash/tamanho de evidência divergente")
    checked = check_artifacts(directory, allow_known_export_limitation=evidence.get("knownExportLimitationPermitted") is True)
    require(evidence.get("results") == checked, "Resultados registrados divergentes")
    require(evidence["status"] == ("ok" if checked["textRoundtripExact"] else "completed-with-consumer-limitation"), "Status registrado diverge do resultado real")
    return {"status": evidence["status"], "mode": "stored-evidence-only", "newExternalExecution": False, "recordedLibreOfficeVersion": evidence["libreofficeVersion"], "results": checked}


def external_run(bundle, text_bundle, output, executable, unshare, *, record_known_export_limitation=False):
    require(not output.exists(), "Diretório de evidência deve ser novo")
    check_bundle(bundle.read_bytes(), demo=True)
    check_bundle(text_bundle.read_bytes())
    check_text_case(text_bundle.read_bytes())
    output.mkdir()
    shutil.copyfile(bundle, output / "demo.zip")
    shutil.copyfile(text_bundle, output / "text.zip")
    for label in ("demo", "text"):
        workbook = zip_members((output / f"{label}.zip").read_bytes(), bundle=True)["plano.xlsx"]
        (output / f"{label}-original.xlsx").write_bytes(workbook)
    make_audit(output / "audit-source.xlsx")
    commands = []
    with tempfile.TemporaryDirectory(prefix="materiais-interop-") as temporary:
        temporary = Path(temporary)
        for subdir in ("home", "config", "cache", "data", "runtime", "profile"):
            (temporary / subdir).mkdir(mode=0o700)
        profile = temporary / "profile"
        (profile / "user").mkdir()
        (profile / "user" / "registrymodifications.xcu").write_text('''<?xml version="1.0" encoding="UTF-8"?><oor:items xmlns:oor="http://openoffice.org/2001/registry"><item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item><item oor:path="/org.openoffice.Office.Calc/Content/Update"><prop oor:name="Link" oor:op="fuse"><value>0</value></prop></item></oor:items>''', encoding="utf-8")
        environment = {"PATH": "/usr/bin:/bin", "HOME": str(temporary / "home"), "XDG_CONFIG_HOME": str(temporary / "config"), "XDG_CACHE_HOME": str(temporary / "cache"), "XDG_DATA_HOME": str(temporary / "data"), "XDG_RUNTIME_DIR": str(temporary / "runtime"), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "SAL_USE_VCLPLUGIN": "svp"}
        network_prefix = [str(unshare), "--user", "--map-root-user", "--net", "--"]
        version_command = [*network_prefix, str(executable), "--version"]
        version_run = subprocess.run(version_command, env=environment, check=False, capture_output=True, text=True, timeout=30)
        require(version_run.returncode == 0 and "LibreOffice" in version_run.stdout, "Não foi possível identificar LibreOffice")
        version = version_run.stdout.strip()
        commands.append({"argv": version_command, "returnCode": version_run.returncode, "stdout": version_run.stdout, "stderr": version_run.stderr})
        tasks = (
            ("demo-import", "demo-original.xlsx", "ods", "demo-import.ods"),
            ("text-import", "text-original.xlsx", "ods", "text-import.ods"),
            ("demo", "demo-original.xlsx", "xlsx:Calc MS Excel 2007 XML", "demo-libreoffice.xlsx"),
            ("text", "text-original.xlsx", "xlsx:Calc MS Excel 2007 XML", "text-libreoffice.xlsx"),
            ("text-reopened", "text-libreoffice.xlsx", "ods", "text-reopened.ods"),
            ("audit", "audit-source.xlsx", "xlsx:Calc MS Excel 2007 XML", "audit-libreoffice.xlsx"),
        )
        for label, source_name, filter_name, artifact_name in tasks:
            source = temporary / source_name
            shutil.copyfile(output / source_name, source)
            converted = temporary / f"converted-{label}"
            converted.mkdir()
            command = [*network_prefix, str(executable), f"-env:UserInstallation={profile.as_uri()}", "--headless", "--invisible", "--norestore", "--nodefault", "--nolockcheck", "--nofirststartwizard", "--convert-to", filter_name, "--outdir", str(converted), str(source)]
            run = subprocess.run(command, env=environment, check=False, capture_output=True, text=True, timeout=90)
            commands.append({"argv": command, "returnCode": run.returncode, "stdout": run.stdout, "stderr": run.stderr})
            extension = "ods" if filter_name == "ods" else "xlsx"
            destination = converted / f"{Path(source_name).stem}.{extension}"
            require(run.returncode == 0 and destination.is_file(), "LibreOffice não produziu workbook convertido")
            shutil.copyfile(destination, output / artifact_name)
    results = check_artifacts(output, allow_known_export_limitation=record_known_export_limitation)
    status = "ok" if results["textRoundtripExact"] else "completed-with-consumer-limitation"
    file_names = EVIDENCE_FILES
    evidence = {"version": 1, "kind": "actual-libreoffice-execution", "status": status, "knownExportLimitationPermitted": record_known_export_limitation, "libreofficeVersion": version, "commands": commands, "isolation": {"freshTemporaryProfile": True, "freshConversionDirectories": True, "privateHomeAndXdg": True, "existingUserProfileRead": False, "macrosDisabledInTemporaryProfile": True, "externalWorkbookRelationshipsRejected": True, "networkRequested": False, "osNetworkSandbox": True, "networkNamespace": "unshare --user --map-root-user --net"}, "results": results, "files": {name: digest(output / name) for name in sorted(file_names)}, "scope": "Initial XLSX import equality across all four sheets of both reports; exact demo XLSX roundtrip; explicit text XLSX export/reopen comparison with two known literal losses allowed only by flag; 72 independently expected formula caches. No general Excel arithmetic or third-party save guarantee. Linux user/network namespaces isolate the consumer."}
    (output / "evidence.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": status, "mode": "actual-external-execution", "newExternalExecution": True, "libreofficeVersion": version, "results": results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--text-bundle", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--libreoffice", type=Path, default=Path("/usr/bin/libreoffice"))
    parser.add_argument("--unshare", type=Path, default=Path("/usr/bin/unshare"))
    parser.add_argument("--record-known-export-limitation", action="store_true", help="registrar explicitamente somente as duas perdas conhecidas do reexportador LO")
    parser.add_argument("--check-fixtures", action="store_true")
    parser.add_argument("--fixtures-dir", type=Path, default=FIXTURES)
    args = parser.parse_args(argv)
    try:
        if args.check_fixtures:
            require(not any((args.bundle, args.text_bundle, args.output_dir, args.record_known_export_limitation)), "Modo fixture não aceita bundle/saída")
            result = check_fixtures(args.fixtures_dir)
        else:
            require(all((args.bundle, args.text_bundle, args.output_dir)), "Informe --bundle, --text-bundle e --output-dir")
            result = external_run(args.bundle.resolve(), args.text_bundle.resolve(), args.output_dir.resolve(), args.libreoffice.resolve(), args.unshare.resolve(), record_known_export_limitation=args.record_known_export_limitation)
    except (CheckError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        print(f"Falha na prova de interoperabilidade: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
