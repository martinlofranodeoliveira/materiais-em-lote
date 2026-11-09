#!/usr/bin/env python3
"""Independent stdlib reader for Materiais em Lote bundles; never imports the package."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import posixpath
import re
import sys
import zipfile
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree as ET

MEMBERS = {"projeto.json", "plano.json", "plano.csv", "plano.md", "plano.xlsx", "LEIA-ME.md", "manifesto.json"}
FIELDS = ("item", "name", "unit", "kind", "level", "lot", "gross", "stock", "used", "net", "lots", "planned", "leftover")
QFIELDS = ("lot", "gross", "stock", "used", "net", "planned", "leftover")
SHEETS = {
    "Plano": (FIELDS, ("Item", "Nome", "Unidade", "Origem", "Nível", "Lote/embalagem", "Demanda bruta", "Estoque inicial", "Estoque utilizado", "Necessidade líquida", "Lotes/embalagens", "Quantidade planejada", "Saldo final")),
    "Origens": (("item", "kind", "source", "quantity"), ("Item", "Tipo", "Origem", "Quantidade")),
    "Pedidos": (("id", "item", "quantity"), ("Pedido", "Item", "Quantidade")),
    "Estrutura": (("parent", "child", "per_batch"), ("Pai", "Componente", "Por lote")),
}
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
XSTRING_TOKEN = re.compile(r"_x([0-9A-Fa-f]{4})_")
DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?\Z", re.ASCII)
ID = re.compile(r"[a-z][a-z0-9_-]{0,39}\Z", re.ASCII)
UNIT = re.compile(r"[a-z][a-z0-9_-]{0,15}\Z", re.ASCII)


class CheckError(ValueError):
    """The independently checked artifact is inconsistent or unsafe."""


def require(condition, message):
    if not condition:
        raise CheckError(message)


def keys(value, expected, context):
    require(type(value) is dict and set(value) == set(expected), f"Campos inválidos: {context}")


def bounded(value):
    value = Fraction(value)
    require(abs(value) <= 10**12, "Resultado acima do limite de magnitude")
    require(len(str(abs(value.numerator))) <= 80 and len(str(value.denominator)) <= 80, "Resultado acima do limite racional")
    return value


def quantity_text(value):
    """Independent canonical decimal/fraction implementation."""
    value = bounded(value)
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        twos += 1
        denominator //= 2
    while denominator % 5 == 0:
        fives += 1
        denominator //= 5
    if denominator != 1:
        return f"{value.numerator}/{value.denominator}"
    places = max(twos, fives)
    integer = abs(value.numerator) * 2 ** (places - twos) * 5 ** (places - fives)
    if not places:
        return str(value.numerator)
    digits = str(integer).zfill(places + 1)
    result = (digits[:-places] + "." + digits[-places:]).rstrip("0").rstrip(".")
    return ("-" if value < 0 else "") + result


def input_quantity(value, positive=False):
    require(type(value) is str and DECIMAL.fullmatch(value), "Quantidade de entrada inválida")
    result = bounded(Fraction(value))
    require(result > 0 if positive else result >= 0, "Sinal de quantidade inválido")
    return result


def text_ok(value, maximum):
    require(type(value) is str and 1 <= len(value) <= maximum and value.strip() == value, "Texto inválido")
    require(all(ord(c) >= 32 and ord(c) != 127 and not 0xD800 <= ord(c) <= 0xDFFF and ord(c) not in (0x2028, 0x2029, 0xFFFE, 0xFFFF) for c in value), "Caractere proibido")


def json_bytes(data, maximum=2**20):
    require(len(data) <= maximum and not data.startswith(b"\xef\xbb\xbf"), "Tamanho ou BOM JSON inválido")
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Chave JSON repetida")
            result[key] = value
        return result
    def invalid(_):
        raise CheckError("Número JSON não permitido")
    try:
        result = json.loads(data.decode("utf-8", "strict"), object_pairs_hook=pairs, parse_float=invalid, parse_constant=invalid)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise CheckError("JSON inválido") from error
    def depth(value, level=0):
        require(level <= 12, "Profundidade JSON excedida")
        if isinstance(value, dict):
            for child in value.values():
                depth(child, level + 1)
        elif isinstance(value, list):
            for child in value:
                depth(child, level + 1)
    depth(result)
    return result


def zip_members(data, *, bundle=False, allow_directories=False):
    require(len(data) <= 32 * 2**20, "Arquivo ZIP grande demais")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            require(len(infos) <= 3000 and len({i.filename for i in infos}) == len(infos), "ZIP duplicado ou grande demais")
            total = 0
            require(not bundle or not archive.comment, "Comentário de bundle inesperado")
            result = {}
            for info in infos:
                name = info.filename
                safe_name = name[:-1] if info.is_dir() and allow_directories else name
                if bundle:
                    require(info.date_time == (1980, 1, 1, 0, 0, 0) and info.create_system == 3 and info.external_attr == 0o100644 << 16 and not info.extra and not info.comment, "Metadados de bundle divergentes")
                require(name and not name.startswith(("/", "\\")) and "\\" not in name and ":" not in name and all(p not in ("", ".", "..") for p in safe_name.split("/")), "Nome ZIP inseguro")
                require((not info.is_dir() or allow_directories) and not info.flag_bits & 1, "ZIP contém diretório ou criptografia")
                if info.is_dir():
                    require(info.file_size == 0, "Diretório ZIP com conteúdo")
                    continue
                require(info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), "Compressão não permitida")
                require((info.external_attr >> 16) & 0o170000 in (0, 0o100000), "Membro ZIP não regular")
                total += info.file_size
                require(info.file_size <= 16 * 2**20 and total <= 32 * 2**20, "ZIP expandido grande demais")
                result[name] = archive.read(info)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
        raise CheckError("ZIP inválido") from error
    if bundle:
        require(set(result) == MEMBERS, "Inventário do bundle divergente")
    return result


def xml(data):
    require(b"<!DOCTYPE" not in data.upper() and b"<!ENTITY" not in data.upper(), "Declaração XML proibida")
    try:
        return ET.fromstring(data)
    except ET.ParseError as error:
        raise CheckError("XML inválido") from error


def column_name(index):
    result = ""
    while index:
        index, rem = divmod(index - 1, 26)
        result = chr(65 + rem) + result
    return result


def decode_xstring(value):
    """Decode ST_Xstring exactly once inside one XML text run.

    Regex substitution consumes each original token; newly produced underscores
    are never scanned again. Adjacent escaped UTF-16 surrogate units form one
    Unicode scalar. Unpaired units are invalid for this project's Unicode text.
    """
    units = XSTRING_TOKEN.sub(lambda match: chr(int(match.group(1), 16)), value)
    result = []
    index = 0
    while index < len(units):
        first = ord(units[index])
        if 0xD800 <= first <= 0xDBFF:
            require(index + 1 < len(units) and 0xDC00 <= ord(units[index + 1]) <= 0xDFFF, "Surrogate UTF16 sem par em ST_Xstring")
            second = ord(units[index + 1])
            result.append(chr(0x10000 + ((first - 0xD800) << 10) + second - 0xDC00))
            index += 2
        else:
            require(not 0xDC00 <= first <= 0xDFFF, "Surrogate UTF16 sem par em ST_Xstring")
            result.append(units[index])
            index += 1
    return "".join(result)


def rich_text(container):
    """Read t/r text in document order; phonetic annotations are not cell text."""
    if container is None:
        return ""
    runs = []
    for child in container:
        if child.tag == f"{{{NS['m']}}}t":
            runs.append(decode_xstring(child.text or ""))
        elif child.tag == f"{{{NS['m']}}}r":
            runs.extend(decode_xstring(t.text or "") for t in child.findall("m:t", NS))
    return "".join(runs)


def workbook_cells(data, *, static=True, require_format=False):
    """Read OOXML cells without openpyxl; static mode rejects active content."""
    members = zip_members(data)
    require("xl/workbook.xml" in members and "xl/_rels/workbook.xml.rels" in members, "Workbook incompleto")
    types = xml(members["[Content_Types].xml"])
    for node in types:
        kind = node.get("ContentType", "").lower()
        require(not any(token in kind for token in ("macro", "vba", "activex", "oleobject", "external", "connections")), "Conteúdo ativo no workbook")
    require(not any(any(token in name.lower() for token in ("vba", "externallink", "connections", "activex", "embeddings")) for name in members), "Parte ativa no workbook")
    for name, content in members.items():
        if name.endswith(".rels"):
            root = xml(content)
            base = posixpath.dirname(posixpath.dirname(name))
            for rel in root:
                require(rel.get("TargetMode", "").lower() != "external", "Relação externa no workbook")
                target = rel.get("Target", "")
                require(target and "\\" not in target and ":" not in target and "?" not in target and "#" not in target, "Destino de relação inseguro")
                resolved = posixpath.normpath(target.lstrip("/") if target.startswith("/") else posixpath.join(base, target))
                require(not resolved.startswith("../") and resolved in members, "Destino de relação ausente")
                require("hyperlink" not in rel.get("Type", "").lower(), "Hyperlink proibido")
    shared = []
    if "xl/sharedStrings.xml" in members:
        for si in xml(members["xl/sharedStrings.xml"]).findall("m:si", NS):
            shared.append(rich_text(si))
    rels = {rel.get("Id"): rel.get("Target") for rel in xml(members["xl/_rels/workbook.xml.rels"])}
    workbook = xml(members["xl/workbook.xml"])
    if static:
        require(workbook.find("m:externalReferences", NS) is None, "Referência externa proibida")
    result = {}
    for sheet in workbook.findall("m:sheets/m:sheet", NS):
        name = sheet.get("name")
        require(name not in result, "Nome de aba repetido")
        target = rels.get(sheet.get(f"{{{NS['r']}}}id"))
        require(target is not None, "Relação de aba ausente")
        part = posixpath.normpath(target.lstrip("/") if target.startswith("/") else posixpath.join("xl", target))
        root = xml(members[part])
        require(not static or root.find(".//m:f", NS) is None, "Fórmula em relatório estático")
        require(root.find("m:hyperlinks", NS) is None, "Hyperlink em aba")
        if require_format:
            pane = root.find("m:sheetViews/m:sheetView/m:pane", NS)
            require(pane is not None and pane.get("state") == "frozen" and pane.get("ySplit") == "1", "Cabeçalho não congelado")
            setup = root.find("m:pageSetup", NS)
            require(setup is not None and setup.get("fitToWidth") == "1", "Impressão não ajustada à largura")
            require(root.find("m:autoFilter", NS) is not None or root.find("m:tableParts", NS) is not None, "Filtro/tabela ausente")
        cells = {}
        for cell in root.findall("m:sheetData/m:row/m:c", NS):
            ref = cell.get("r")
            require(ref and re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]{0,6}", ref) and ref not in cells, "Endereço de célula inválido")
            formula = cell.find("m:f", NS)
            require(not static or formula is None, "Fórmula em relatório estático")
            kind = cell.get("t", "n")
            value_node = cell.find("m:v", NS)
            raw = value_node.text if value_node is not None else None
            if kind == "inlineStr":
                value = rich_text(cell.find("m:is", NS))
                cell_type = "text"
            elif kind == "s":
                require(raw is not None and raw.isdigit() and int(raw) < len(shared), "Shared string inválida")
                value, cell_type = shared[int(raw)], "text"
            elif kind == "str":
                require(not static, "Tipo de texto de fórmula inesperado")
                value, cell_type = decode_xstring(raw or ""), "text"
            elif kind == "n":
                if raw is None and formula is None:
                    continue  # formatting-only cells after a consumer roundtrip
                require(not static or re.fullmatch(r"-?(?:0|[1-9][0-9]*)", raw), "Número não inteiro em relatório estático")
                value = int(raw) if static else raw
                cell_type = "integer" if static else "number"
            else:
                raise CheckError("Tipo de célula não permitido")
            cells[ref] = (cell_type, value, formula.text if formula is not None else None)
        result[name] = cells
    return result


def expected_plan(project):
    keys(project, ("version", "title", "items", "demands", "stock"), "projeto")
    require(type(project["version"]) is int and project["version"] == 1, "Versão de entrada inválida")
    text_ok(project["title"], 120)
    require(type(project["items"]) is list and 1 <= len(project["items"]) <= 250, "Catálogo inválido")
    require(type(project["demands"]) is list and len(project["demands"]) <= 250, "Pedidos inválidos")
    require(type(project["stock"]) is list and len(project["stock"]) <= 250, "Estoque inválido")
    items, components, indegree, levels = {}, {}, {}, {}
    for item in project["items"]:
        require(type(item) is dict and item.get("kind") in ("buy", "make"), "Tipo de item inválido")
        make = item["kind"] == "make"
        keys(item, ("id", "name", "unit", "kind", "batch", "components") if make else ("id", "name", "unit", "kind", "pack"), "item")
        require(type(item["id"]) is str and ID.fullmatch(item["id"]) and item["id"] not in items, "ID de item inválido")
        text_ok(item["name"], 100)
        require(type(item["unit"]) is str and UNIT.fullmatch(item["unit"]), "Unidade inválida")
        input_quantity(item["batch" if make else "pack"], True)
        items[item["id"]] = item
        components[item["id"]] = {}
        indegree[item["id"]], levels[item["id"]] = 0, 0
        if make:
            require(type(item["components"]) is list and item["components"], "Componentes inválidos")
            for component in item["components"]:
                keys(component, ("item", "quantity"), "componente")
                child = component["item"]
                require(type(child) is str and child not in components[item["id"]], "Componente repetido")
                components[item["id"]][child] = input_quantity(component["quantity"], True)
    require(sum(map(len, components.values())) <= 2000, "Arestas demais")
    for children in components.values():
        for child in children:
            require(child in items, "Referência inexistente")
            indegree[child] += 1
    order = []
    ready = sorted(item for item in items if indegree[item] == 0)
    while ready:
        item = ready.pop(0)
        order.append(item)
        for child in sorted(components[item]):
            levels[child] = max(levels[child], levels[item] + 1)
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort()
    require(len(order) == len(items), "Ciclo no catálogo")
    demands, stock, direct = [], {}, {item: [] for item in items}
    demand_ids = set()
    for demand in project["demands"]:
        keys(demand, ("id", "item", "quantity"), "pedido")
        require(type(demand["id"]) is str and ID.fullmatch(demand["id"]) and demand["id"] not in demand_ids, "ID de pedido inválido")
        demand_ids.add(demand["id"])
        require(demand["item"] in items, "Pedido referencia item inexistente")
        quantity = input_quantity(demand["quantity"], True)
        demands.append(dict(demand, quantity=quantity_text(quantity)))
        direct[demand["item"]].append((demand["id"], quantity))
    for record in project["stock"]:
        keys(record, ("item", "quantity"), "estoque")
        require(record["item"] in items and record["item"] not in stock, "Estoque duplicado/inexistente")
        stock[record["item"]] = input_quantity(record["quantity"])
    origins, rows, contributions = [], [], {item: [] for item in items}
    for item_id in order:
        item = items[item_id]
        sources = [("direct", source, quantity) for source, quantity in sorted(direct[item_id])] + [("parent", source, quantity) for source, quantity in sorted(contributions[item_id])]
        gross = bounded(sum((quantity for _, _, quantity in sources), Fraction(0)))
        available = stock.get(item_id, Fraction(0))
        used = min(gross, available)
        net = bounded(gross - used)
        lot = input_quantity(item["batch"] if item["kind"] == "make" else item["pack"], True)
        quotient = bounded(net / lot)
        lots = (quotient.numerator + quotient.denominator - 1) // quotient.denominator
        planned = bounded(lots * lot)
        leftover = bounded(available + planned - gross)
        for kind, source, quantity in sources:
            if quantity:
                origins.append({"item": item_id, "kind": kind, "source": source, "quantity": quantity_text(quantity)})
        rows.append({"item": item_id, "name": item["name"], "unit": item["unit"], "kind": item["kind"], "level": levels[item_id], "lot": quantity_text(lot), "gross": quantity_text(gross), "stock": quantity_text(available), "used": quantity_text(used), "net": quantity_text(net), "lots": lots, "planned": quantity_text(planned), "leftover": quantity_text(leftover)})
        for child, per_batch in components[item_id].items():
            quantity = bounded(lots * per_batch)
            if quantity:
                contributions[child].append((item_id, quantity))
    edges = [{"parent": parent, "child": child, "per_batch": quantity_text(components[parent][child])} for parent in sorted(items) for child in sorted(components[parent])]
    return {"version": 1, "title": project["title"], "items": rows, "origins": origins, "demands": sorted(demands, key=lambda d: d["id"]), "edges": edges}


# Literal manual answers, independent of the producer and reconstruction above.
DEMO = {
    "kit": ("3", "1", "2", 1, "2", "0"),
    "expositor": ("2", "0", "2", 2, "2", "0"),
    "painel": ("7", "2", "5", 2, "6", "1"),
    "suporte": ("8", "1", "7", 2, "8", "1"),
    "chapa": ("2", "1", "1", 1, "2", "1"),
    "tinta": ("1.5", "0.3", "1.2", 2, "2", "0.8"),
}
DEMO_TRACES = {
    ("kit", "direct", "pedido-kit"): "3", ("expositor", "direct", "pedido-expositor"): "2",
    ("painel", "parent", "kit"): "3", ("painel", "parent", "expositor"): "4",
    ("suporte", "parent", "kit"): "4", ("suporte", "parent", "expositor"): "4",
    ("chapa", "parent", "painel"): "2", ("tinta", "parent", "kit"): "0.5",
    ("tinta", "parent", "expositor"): "0.4", ("tinta", "parent", "painel"): "0.6",
}


def expected_workbook(plan):
    result = {}
    records = {"Plano": plan["items"], "Origens": plan["origins"], "Pedidos": plan["demands"], "Estrutura": plan["edges"]}
    for name, (fields, headings) in SHEETS.items():
        cells = {f"{column_name(index)}1": ("text", heading, None) for index, heading in enumerate(headings, 1)}
        for row_index, record in enumerate(records[name], 2):
            for col_index, field in enumerate(fields, 1):
                value = record[field]
                kind = "integer" if type(value) is int else "text"
                cells[f"{column_name(col_index)}{row_index}"] = (kind, value, None)
        result[name] = cells
    return result


def check_bundle(data, *, demo=False):
    members = zip_members(data, bundle=True)
    manifest = json_bytes(members["manifesto.json"])
    keys(manifest, ("version", "packageVersion", "inputSHA256", "files"), "manifesto")
    require(type(manifest["version"]) is int and manifest["version"] == 1 and manifest["packageVersion"] == "1.0.0", "Versão de manifesto divergente")
    require(manifest["inputSHA256"] == hashlib.sha256(members["projeto.json"]).hexdigest(), "Hash da entrada divergente")
    require(type(manifest["files"]) is list, "Inventário de manifesto inválido")
    expected_files = [{"name": name, "size": len(members[name]), "sha256": hashlib.sha256(members[name]).hexdigest()} for name in sorted(MEMBERS - {"manifesto.json"})]
    require(manifest["files"] == expected_files, "Inventário/hash/tamanho de manifesto divergente")
    project = json_bytes(members["projeto.json"])
    expected = expected_plan(project)
    plan = json_bytes(members["plano.json"], maximum=16 * 2**20)
    require(type(plan.get("version")) is int and plan == expected, "Plano JSON diverge da reconstrução racional independente")
    # Equality alone accepts bool == 1; enforce the exact scalar types as well.
    for row in plan["items"]:
        require(all(type(row[field]) is int for field in ("level", "lots")), "Inteiro de plano com tipo incorreto")
        require(all(type(row[field]) is str for field in QFIELDS), "Quantidade não textual")
    if demo:
        require(plan["title"] == "Uma oficina, dois pedidos" and set(DEMO) == {row["item"] for row in plan["items"]}, "Demonstração incorreta")
        for row in plan["items"]:
            require(tuple(row[field] for field in ("gross", "used", "net", "lots", "planned", "leftover")) == DEMO[row["item"]], "Demonstração diverge do cálculo manual")
        traces = {(o["item"], o["kind"], o["source"]): o["quantity"] for o in plan["origins"]}
        require(traces == DEMO_TRACES and len(plan["origins"]) == 10, "Rastros manuais da demonstração divergentes")
    csv_data = members["plano.csv"]
    require(b"\r" not in csv_data and not csv_data.startswith(b"\xef\xbb\xbf"), "CSV deve usar UTF-8/LF sem BOM")
    try:
        rows = list(csv.reader(io.StringIO(csv_data.decode("utf-8"), newline=""), strict=True))
    except (UnicodeError, csv.Error) as error:
        raise CheckError("CSV inválido") from error
    expected_csv = [list(FIELDS)]
    for row in plan["items"]:
        values = []
        for field in FIELDS:
            value = str(row[field])
            if field in ("item", "name", "unit", "kind") and value.startswith(("=", "+", "-", "@")):
                value = "'" + value
            values.append(value)
        expected_csv.append(values)
    require(rows == expected_csv, "CSV diverge do JSON ou da proteção de texto")
    xlsx_members = zip_members(members["plano.xlsx"])
    properties = xml(xlsx_members["docProps/core.xml"])
    require(properties.findtext("{http://purl.org/dc/elements/1.1/}title") == plan["title"], "Título do workbook divergente")
    cells = workbook_cells(members["plano.xlsx"], static=True, require_format=True)
    require(cells == expected_workbook(plan), "Células/tipos do XLSX divergem do JSON")
    for name in ("plano.md", "LEIA-ME.md"):
        require(members[name] and len(members[name]) <= 16 * 2**20, "Markdown vazio/grande demais")
        try:
            members[name].decode("utf-8", "strict")
        except UnicodeError as error:
            raise CheckError("Markdown não UTF-8") from error
    return {"status": "ok", "bundleSHA256": hashlib.sha256(data).hexdigest(), "items": len(plan["items"]), "origins": len(plan["origins"]), "demands": len(plan["demands"]), "edges": len(plan["edges"]), "manualDemo": demo}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--demo", action="store_true", help="comparar também a respostas manuais literais")
    args = parser.parse_args(argv)
    try:
        result = check_bundle(args.bundle.read_bytes(), demo=args.demo)
    except (CheckError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"Falha na verificação independente: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
