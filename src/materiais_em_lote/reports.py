"""Relatórios estáticos e publicação exclusiva de um pacote completo."""

from __future__ import annotations

import csv
from datetime import datetime
from fractions import Fraction
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from . import __version__
from .core import PlanError, parse_project, plan_project, quantity_text


ROW_FIELDS = (
    "item", "name", "unit", "kind", "level", "lot", "gross", "stock",
    "used", "net", "lots", "planned", "leftover",
)
ORIGIN_FIELDS = ("item", "kind", "source", "quantity")
DEMAND_FIELDS = ("id", "item", "quantity")
EDGE_FIELDS = ("parent", "child", "per_batch")
SHEET_HEADERS = (
    ("Item", "Nome", "Unidade", "Origem", "Nível", "Lote/embalagem",
     "Demanda bruta", "Estoque inicial", "Estoque utilizado",
     "Necessidade líquida", "Lotes/embalagens", "Quantidade planejada", "Saldo final"),
    ("Item", "Tipo", "Origem", "Quantidade"),
    ("Pedido", "Item", "Quantidade"),
    ("Pai", "Componente", "Por lote"),
)
FIXED_DATE = datetime(2000, 1, 1)
MAX_BUNDLE = 24 * 1024 * 1024


def _json(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _record(value, names) -> dict:
    result = {}
    for name in names:
        item = getattr(value, name)
        result[name] = quantity_text(item) if type(item) is Fraction else item
    return result


def _wire(plan) -> dict:
    return {
        "version": 1,
        "title": plan.title,
        "items": [_record(row, ROW_FIELDS) for row in plan.rows],
        "origins": [_record(row, ORIGIN_FIELDS) for row in plan.origins],
        "demands": [_record(row, DEMAND_FIELDS) for row in plan.demands],
        "edges": [_record(row, EDGE_FIELDS) for row in plan.edges],
    }


def _csv_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _csv(report: dict) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(ROW_FIELDS)
    for row in report["items"]:
        writer.writerow(_csv_cell(row[name]) for name in ROW_FIELDS)
    return buffer.getvalue().encode("utf-8")


def _md_text(value) -> str:
    # HTML and Markdown are both presentation syntax; authored content is literal.
    text = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([\\`*_{}\[\]()#+.!|~\-])", r"\\\1", text)


def _markdown(report: dict) -> bytes:
    lines = [
        "# " + _md_text(report["title"]), "",
        "Plano declarado de materiais. Estoque e pedidos vêm da entrada; não houve reserva ou compra.", "",
        "Cada quantidade usa a unidade do próprio item. Frações são exatas; não somar unidades diferentes.", "",
        "| Item | Unidade | Tipo | Bruta | Estoque | Usado | Líquida | Lote | Lotes | Planejado | Saldo |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["items"]:
        values = [
            row["item"] + " - " + row["name"], row["unit"],
            "Fabricar" if row["kind"] == "make" else "Comprar",
            *[row[k] for k in ("gross", "stock", "used", "net", "lot", "lots", "planned", "leftover")],
        ]
        lines.append("| " + " | ".join(_md_text(v) for v in values) + " |")
    lines.extend(["", "## Origens da demanda", "", "| Item | Origem | Quantidade |", "| --- | --- | --- |"])
    for origin in report["origins"]:
        label = "Pedido " if origin["kind"] == "direct" else "Produção de "
        values = (origin["item"], label + origin["source"], origin["quantity"])
        lines.append("| " + " | ".join(_md_text(v) for v in values) + " |")
    if not report["origins"]:
        lines.extend(["", "Sem demanda. Todo estoque permanece no saldo final."])
    lines.extend([
        "", "## Como ler", "",
        "A demanda de todos os pais é reunida antes de descontar o estoque uma única vez. "
        "Fabricados geram componentes somente pelos lotes necessários. Comprados são arredondados por embalagem. "
        "Saldo final = estoque inicial + quantidade planejada - demanda bruta.", "",
        "O relatório XLSX é estático. Edite a entrada JSON e gere outro pacote para recalcular. "
        "Não há conversão de unidades, custos, prazos ou otimização de produção.", "",
        "LOFRANO TECNOLOGIA - https://lofranotecnologia.com.br/", "",
    ])
    return "\n".join(lines).encode("utf-8")


def _zip(members: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(members.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data, compresslevel=9)
    return stream.getvalue()


def _xlsx_literal(value: str) -> str:
    # ST_Xstring is decoded once by Office consumers. Escape each lead
    # underscore, including overlapping tokens, before the XML writer runs.
    return re.sub(r"_(?=x[0-9A-Fa-f]{4}_)", "_x005F_", value)


def _xlsx(report: dict) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    workbook.properties.creator = "LOFRANO TECNOLOGIA"
    workbook.properties.lastModifiedBy = "LOFRANO TECNOLOGIA"
    workbook.properties.title = report["title"]
    workbook.properties.description = "Relatório estático; quantidades exatas armazenadas como texto."
    workbook.properties.created = FIXED_DATE
    workbook.properties.modified = FIXED_DATE
    sections = (
        ("Plano", "items", ROW_FIELDS), ("Origens", "origins", ORIGIN_FIELDS),
        ("Pedidos", "demands", DEMAND_FIELDS), ("Estrutura", "edges", EDGE_FIELDS),
    )
    for section_index, (title, key, fields) in enumerate(sections):
        sheet = workbook.create_sheet(title)
        widths = [22] * len(fields)
        if key == "items":
            widths[1] = 32
            widths[2:5] = [12, 12, 10]
        for column, header in enumerate(SHEET_HEADERS[section_index], 1):
            cell = sheet.cell(1, column, header)
            cell.data_type = "s"
            cell.font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="243B3C")
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            sheet.column_dimensions[cell.column_letter].width = widths[column - 1]
        sheet.row_dimensions[1].height = 34
        for row_index, record in enumerate(report[key], 2):
            line_count = 1
            for column, field in enumerate(fields, 1):
                value = record[field]
                cell = sheet.cell(row_index, column, _xlsx_literal(value) if type(value) is str else value)
                # Explicit text avoids formula or hyperlink interpretation of authored labels.
                cell.data_type = "n" if field in ("level", "lots") else "s"
                cell.number_format = "0" if cell.data_type == "n" else "@"
                cell.font = Font(name="Calibri", size=10, color="213637")
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                if row_index % 2 == 0:
                    cell.fill = PatternFill("solid", fgColor="EDF0E9")
                units = sum(1 if ord(c) < 128 else 2 for c in str(value))
                line_count = max(line_count, math.ceil(units / max(1, widths[column - 1] - 3)))
            sheet.row_dimensions[row_index].height = max(27, 14 * line_count + 5)
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        sheet.print_title_rows = "1:1"
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.paperSize = sheet.PAPERSIZE_A3 if key == "items" else sheet.PAPERSIZE_A4
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.print_options.horizontalCentered = True
        sheet.oddFooter.center.text = "Materiais em Lote - relatório estático"
    output = io.BytesIO()
    workbook.save(output)
    # The writer updates modified time and ZIP dates. Normalize only our own generated OOXML.
    with zipfile.ZipFile(io.BytesIO(output.getvalue())) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    properties = ET.fromstring(members["docProps/core.xml"])
    for local_name in ("created", "modified"):
        node = properties.find("{http://purl.org/dc/terms/}" + local_name)
        if node is not None:
            node.text = "2000-01-01T00:00:00Z"
    members["docProps/core.xml"] = ET.tostring(properties, encoding="utf-8", xml_declaration=True)
    return _zip(members)


def build_bundle(data: bytes | str) -> bytes:
    """Valida uma entrada JSON e constrói o ZIP inteiro, sem escrever arquivos."""
    project = parse_project(data)
    raw = data if type(data) is bytes else data.encode("utf-8")
    report = _wire(plan_project(project))
    members = {
        "projeto.json": raw,
        "plano.json": _json(report),
        "plano.csv": _csv(report),
        "plano.md": _markdown(report),
        "plano.xlsx": _xlsx(report),
        "LEIA-ME.md": (
            "# Materiais em Lote\n\n"
            "Relatórios de um cenário declarado, sem reserva de estoque ou compra real.\n\n"
            "projeto.json é a entrada original; plano.json é a memória estruturada. "
            "CSV e Markdown resumem o plano. XLSX tem quatro abas e quantidades como texto exato: "
            "é estático e não recalcula ao editar células. Não converter n/d para float se precisar de igualdade exata.\n\n"
            "CSV acrescenta apóstrofo a textos que começam com =, +, - ou @ (após espaços). "
            "O JSON e o XLSX preservam esses textos literalmente. Os IDs e as quantidades têm gramáticas próprias.\n\n"
            "manifesto.json identifica seis membros por tamanho e SHA-256; hashes não autenticam o autor. "
            "Quantidades de unidades diferentes não têm um total geral. Guarde a entrada para recalcular.\n\n"
            "LOFRANO TECNOLOGIA - https://lofranotecnologia.com.br/\n"
        ).encode("utf-8"),
    }
    manifest = {
        "version": 1,
        "packageVersion": __version__,
        "inputSHA256": hashlib.sha256(raw).hexdigest(),
        "files": [
            {"name": name, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
            for name, content in sorted(members.items())
        ],
    }
    members["manifesto.json"] = _json(manifest)
    result = _zip(members)
    if len(result) > MAX_BUNDLE:
        raise PlanError("E_LIMIT", "", "O pacote excede o limite de saída.")
    return result


def publish_bundle(data: bytes | str, destination: str | Path) -> Path:
    """Publica um ZIP completo em caminho novo por hardlink sem substituição."""
    content = build_bundle(data)
    target = Path(destination)
    if target.suffix.lower() != ".zip":
        raise OSError("A saída precisa ter extensão .zip.")
    parent = target.parent.resolve(strict=True)
    if not parent.is_dir():
        raise OSError("O diretório de saída não existe.")
    target = parent / target.name
    descriptor, temporary = tempfile.mkstemp(prefix=".materiais-", suffix=".tmp", dir=parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # link() fails atomically if target already exists, including a symlink or directory.
        os.link(temporary, target)
    finally:
        os.unlink(temporary)
    return target
