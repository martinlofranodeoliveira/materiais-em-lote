"""Validação e planejamento de materiais com aritmética racional exata.

Um componente declara consumo por lote do pai. A ordem topológica permite
reunir todas as origens de um item antes de aplicar seu estoque uma única vez.
Não há conversão de unidades, acesso a arquivos ou estado global mutável.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import heapq
import json
import math
import re
from typing import Any


MAX_BYTES = 1024 * 1024
MAX_ITEMS = 250
MAX_EDGES = 2000
MAX_DEMANDS = 250
MAX_QUANTITY = 10**12
MAX_RATIONAL_PART = 10**80
_ID = re.compile(r"[a-z][a-z0-9_-]{0,39}\Z", re.ASCII)
_UNIT = re.compile(r"[a-z][a-z0-9_-]{0,15}\Z", re.ASCII)
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?\Z", re.ASCII)
_ZERO = Fraction(0)


class PlanError(ValueError):
    """Erro público sanitizado: código, caminho estrutural e mensagem fixa."""

    def __init__(self, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        self.message = message
        super().__init__(f"{code} em {path}: {message}")


@dataclass(frozen=True, slots=True)
class Component:
    item: str
    quantity: Fraction


@dataclass(frozen=True, slots=True)
class Item:
    id: str
    name: str
    unit: str
    kind: str
    lot: Fraction
    components: tuple[Component, ...]


@dataclass(frozen=True, slots=True)
class Demand:
    id: str
    item: str
    quantity: Fraction


@dataclass(frozen=True, slots=True)
class Stock:
    item: str
    quantity: Fraction


@dataclass(frozen=True, slots=True)
class Project:
    title: str
    items: tuple[Item, ...]
    demands: tuple[Demand, ...]
    stock: tuple[Stock, ...]


@dataclass(frozen=True, slots=True)
class PlanRow:
    item: str
    name: str
    unit: str
    kind: str
    level: int
    lot: Fraction
    gross: Fraction
    stock: Fraction
    used: Fraction
    net: Fraction
    lots: int
    planned: Fraction
    leftover: Fraction


@dataclass(frozen=True, slots=True)
class Origin:
    item: str
    kind: str
    source: str
    quantity: Fraction


@dataclass(frozen=True, slots=True)
class Edge:
    parent: str
    child: str
    per_batch: Fraction


@dataclass(frozen=True, slots=True)
class Plan:
    title: str
    rows: tuple[PlanRow, ...]
    origins: tuple[Origin, ...]
    demands: tuple[Demand, ...]
    edges: tuple[Edge, ...]


def _error(code: str, path: str, message: str) -> Any:
    raise PlanError(code, path, message)


def _check_json_tree(value: Any, path: str = "$", depth: int = 0) -> None:
    """Recusa subclasses e objetos executáveis antes de ler seus campos."""
    value_type = type(value)
    if value_type is dict or value_type is list:
        if depth >= 12:
            _error("E_LIMIT", path, "A profundidade estrutural excede o limite.")
        if value_type is dict:
            for key, child in value.items():
                if type(key) is not str:
                    _error("E_SCHEMA", path, "As chaves devem ser textos JSON.")
                # Nunca usar a chave da entrada no caminho de um erro.
                _check_json_tree(child, path, depth + 1)
        else:
            for child in value:
                _check_json_tree(child, path, depth + 1)
    elif value_type not in (str, int, bool, type(None)):
        _error("E_SCHEMA", path, "A entrada deve conter apenas tipos JSON aceitos.")


def _object(value: Any, fields: set[str], path: str) -> dict:
    if type(value) is not dict:
        _error("E_SCHEMA", path, "Era esperado um objeto JSON.")
    if set(value) != fields:
        _error("E_SCHEMA", path, "O objeto deve conter exatamente os campos previstos.")
    return value


def _array(value: Any, path: str, maximum: int, *, nonempty: bool = False) -> list:
    if type(value) is not list:
        _error("E_SCHEMA", path, "Era esperado um array JSON.")
    if len(value) > maximum:
        _error("E_LIMIT", path, "O array excede o limite de elementos.")
    if nonempty and not value:
        _error("E_SCHEMA", path, "O catálogo deve conter pelo menos um item.")
    return value


def _identifier(value: Any, path: str, *, unit: bool = False) -> str:
    pattern = _UNIT if unit else _ID
    if type(value) is not str or pattern.fullmatch(value) is None:
        _error("E_SCHEMA", path, "O identificador não segue o formato permitido.")
    return value


def _text(value: Any, path: str, maximum: int) -> str:
    if type(value) is not str or not 1 <= len(value) <= maximum:
        _error("E_SCHEMA", path, "O texto tem tipo ou comprimento inválido.")
    if value != value.strip():
        _error("E_SCHEMA", path, "O texto não pode ter espaços externos.")
    for character in value:
        point = ord(character)
        if (
            point < 32
            or point == 127
            or 0xD800 <= point <= 0xDFFF
            or point in (0x2028, 0x2029, 0xFFFE, 0xFFFF)
        ):
            _error("E_SCHEMA", path, "O texto contém um caractere não permitido.")
    return value


def _quantity(value: Any, path: str, *, positive: bool) -> Fraction:
    if type(value) is not str or _DECIMAL.fullmatch(value) is None:
        _error("E_QUANTITY", path, "A quantidade deve ser um texto decimal válido.")
    # Impede conversão de inteiros arbitrariamente longos.
    if len(value) > 20:
        _error("E_LIMIT", path, "A quantidade excede o limite permitido.")
    number = Fraction(value)
    if number > MAX_QUANTITY:
        _error("E_LIMIT", path, "A quantidade excede o limite permitido.")
    if positive and number == 0:
        _error("E_QUANTITY", path, "A quantidade deve ser positiva.")
    return number


def _checked(value: Fraction | int, path: str) -> Fraction | int:
    if abs(value) > MAX_QUANTITY:
        _error("E_LIMIT", path, "Um resultado excede o limite permitido.")
    if type(value) is Fraction and (
        abs(value.numerator) >= MAX_RATIONAL_PART
        or value.denominator >= MAX_RATIONAL_PART
    ):
        _error("E_LIMIT", path, "Um resultado racional excede o limite de precisão.")
    return value


def quantity_text(value: Fraction) -> str:
    """Formata um racional exato: decimal finito ou fração irredutível."""
    _fraction_parts(value, "$", input_value=False)
    _checked(value, "$")
    numerator, denominator = value.numerator, value.denominator
    if numerator == 0:
        return "0"
    twos = fives = 0
    remaining = denominator
    while remaining % 2 == 0:
        twos += 1
        remaining //= 2
    while remaining % 5 == 0:
        fives += 1
        remaining //= 5
    if remaining != 1:
        return f"{numerator}/{denominator}"
    places = max(twos, fives)
    if places == 0:
        return str(numerator)
    scaled = abs(numerator) * (10**places // denominator)
    digits = str(scaled).zfill(places + 1)
    result = f"{digits[:-places]}.{digits[-places:]}".rstrip("0").rstrip(".")
    return ("-" if numerator < 0 else "") + result


def _fraction_parts(value: Any, path: str, *, input_value: bool) -> Fraction:
    if type(value) is not Fraction:
        _error("E_SCHEMA", path, "Era esperada uma quantidade racional exata.")
    try:
        numerator, denominator = value.numerator, value.denominator
    except AttributeError:
        _error("E_SCHEMA", path, "A quantidade racional está incompleta.")
    if (
        type(numerator) is not int
        or type(denominator) is not int
        or denominator <= 0
        or math.gcd(numerator, denominator) != 1
    ):
        _error("E_SCHEMA", path, "A quantidade racional está inválida.")
    _checked(value, path)
    if input_value:
        # Qualquer decimal com até seis casas é múltiplo exato de 1/1.000.000.
        if numerator < 0 or 1_000_000 % denominator != 0:
            _error(
                "E_QUANTITY", path,
                "A quantidade de entrada deve ser decimal não negativa com até seis casas.",
            )
    return value


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            _error("E_JSON", "$", "O JSON contém chaves repetidas.")
        result[key] = value
    return result


def _reject_json_number(value: str) -> Any:
    _error("E_JSON", "$", "O JSON contém uma representação numérica não permitida.")


def _check_serialized_depth(text: str) -> None:
    """Limita aninhamento antes do decodificador, ignorando conteúdo textual."""
    depth = 0
    quoted = escaped = False
    for character in text:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in "[{":
            depth += 1
            if depth > 12:
                _error("E_LIMIT", "$", "A profundidade estrutural excede o limite.")
        elif character in "]}":
            depth -= 1


def parse_project(data: bytes | str) -> Project:
    """Lê JSON UTF-8 estrito, sem BOM, números fracionários ou chaves repetidas."""
    if type(data) not in (bytes, str):
        _error("E_JSON", "$", "A entrada deve ser bytes UTF-8 ou texto JSON.")
    try:
        encoded = data if type(data) is bytes else data.encode("utf-8", errors="strict")
        if len(encoded) > MAX_BYTES:
            _error("E_LIMIT", "$", "O arquivo excede o limite de tamanho.")
        decoded = encoded.decode("utf-8", errors="strict")
        if decoded.startswith("\ufeff"):
            _error("E_JSON", "$", "O JSON não pode conter BOM.")
        _check_serialized_depth(decoded)
        mapping = json.loads(
            decoded,
            object_pairs_hook=_no_duplicate_keys,
            parse_float=_reject_json_number,
            parse_constant=_reject_json_number,
        )
    except PlanError:
        raise
    except (UnicodeError, ValueError, RecursionError):
        _error("E_JSON", "$", "O conteúdo não é um JSON UTF-8 válido.")
    return validate_project(mapping)


def validate_project(mapping: dict) -> Project:
    """Valida o formato JSON fechado e produz uma cópia imutável canônica."""
    _check_json_tree(mapping)
    root = _object(mapping, {"version", "title", "items", "demands", "stock"}, "$")
    if type(root["version"]) is not int or root["version"] != 1:
        _error("E_SCHEMA", "$.version", "A versão deve ser o inteiro 1.")
    title = _text(root["title"], "$.title", 120)
    raw_items = _array(root["items"], "$.items", MAX_ITEMS, nonempty=True)
    raw_demands = _array(root["demands"], "$.demands", MAX_DEMANDS)
    raw_stock = _array(root["stock"], "$.stock", MAX_ITEMS)
    items: list[Item] = []
    item_ids: set[str] = set()
    edge_count = 0
    for index, raw in enumerate(raw_items):
        path = f"$.items[{index}]"
        if type(raw) is not dict or type(raw.get("kind")) is not str:
            _error("E_SCHEMA", path, "O item deve declarar um tipo permitido.")
        kind = raw["kind"]
        if kind not in ("buy", "make"):
            _error("E_SCHEMA", path + ".kind", "O tipo deve ser buy ou make.")
        fields = {"id", "name", "unit", "kind"} | (
            {"pack"} if kind == "buy" else {"batch", "components"}
        )
        _object(raw, fields, path)
        item_id = _identifier(raw["id"], path + ".id")
        if item_id in item_ids:
            _error("E_DUPLICATE", path + ".id", "O identificador de item deve ser único.")
        item_ids.add(item_id)
        name = _text(raw["name"], path + ".name", 100)
        unit = _identifier(raw["unit"], path + ".unit", unit=True)
        lot_key = "pack" if kind == "buy" else "batch"
        lot = _quantity(raw[lot_key], path + "." + lot_key, positive=True)
        components: list[Component] = []
        if kind == "make":
            raw_components = _array(raw["components"], path + ".components", MAX_EDGES)
            if not raw_components:
                _error("E_SCHEMA", path + ".components", "Um item fabricado deve ter componentes.")
            edge_count += len(raw_components)
            if edge_count > MAX_EDGES:
                _error("E_LIMIT", path + ".components", "A estrutura excede o limite de arestas.")
            children: set[str] = set()
            for component_index, component in enumerate(raw_components):
                component_path = f"{path}.components[{component_index}]"
                _object(component, {"item", "quantity"}, component_path)
                child = _identifier(component["item"], component_path + ".item")
                if child in children:
                    _error(
                        "E_DUPLICATE", component_path + ".item",
                        "Os componentes de um pai devem ser distintos.",
                    )
                children.add(child)
                amount = _quantity(component["quantity"], component_path + ".quantity", positive=True)
                components.append(Component(child, amount))
        items.append(Item(item_id, name, unit, kind, lot, tuple(components)))
    demands: list[Demand] = []
    demand_ids: set[str] = set()
    for index, raw in enumerate(raw_demands):
        path = f"$.demands[{index}]"
        _object(raw, {"id", "item", "quantity"}, path)
        demand_id = _identifier(raw["id"], path + ".id")
        if demand_id in demand_ids:
            _error("E_DUPLICATE", path + ".id", "O identificador de pedido deve ser único.")
        demand_ids.add(demand_id)
        item_id = _identifier(raw["item"], path + ".item")
        if item_id not in item_ids:
            _error("E_REFERENCE", path + ".item", "O pedido deve referenciar um item do catálogo.")
        amount = _quantity(raw["quantity"], path + ".quantity", positive=True)
        demands.append(Demand(demand_id, item_id, amount))
    stock: list[Stock] = []
    stock_ids: set[str] = set()
    for index, raw in enumerate(raw_stock):
        path = f"$.stock[{index}]"
        _object(raw, {"item", "quantity"}, path)
        item_id = _identifier(raw["item"], path + ".item")
        if item_id in stock_ids:
            _error("E_DUPLICATE", path + ".item", "O estoque de um item deve aparecer uma única vez.")
        stock_ids.add(item_id)
        if item_id not in item_ids:
            _error("E_REFERENCE", path + ".item", "O estoque deve referenciar um item do catálogo.")
        stock.append(Stock(item_id, _quantity(raw["quantity"], path + ".quantity", positive=False)))
    for index, item in enumerate(items):
        for component_index, component in enumerate(item.components):
            if component.item not in item_ids:
                _error(
                    "E_REFERENCE", f"$.items[{index}].components[{component_index}].item",
                    "O componente deve referenciar um item do catálogo.",
                )
    project = Project(
        title,
        tuple(
            Item(
                item.id, item.name, item.unit, item.kind, item.lot,
                tuple(sorted(item.components, key=lambda component: component.item)),
            )
            for item in sorted(items, key=lambda item: item.id)
        ),
        tuple(sorted(demands, key=lambda demand: demand.id)),
        tuple(sorted(stock, key=lambda entry: entry.item)),
    )
    _topology(project)
    return project


def _topology(project: Project) -> tuple[tuple[str, ...], dict[str, int]]:
    items = {item.id: item for item in project.items}
    indegree = {item_id: 0 for item_id in items}
    levels = dict(indegree)
    for item in project.items:
        for component in item.components:
            indegree[component.item] += 1
    ready = [item_id for item_id, count in indegree.items() if count == 0]
    heapq.heapify(ready)
    ordered: list[str] = []
    while ready:
        item_id = heapq.heappop(ready)
        ordered.append(item_id)
        for component in items[item_id].components:
            levels[component.item] = max(levels[component.item], levels[item_id] + 1)
            indegree[component.item] -= 1
            if indegree[component.item] == 0:
                heapq.heappush(ready, component.item)
    if len(ordered) != len(items):
        _error("E_CYCLE", "$.items", "Todo o catálogo deve ser acíclico.")
    return tuple(ordered), levels


def _dataclass(value: Any, expected: type, fields: tuple[str, ...], path: str) -> None:
    if type(value) is not expected:
        _error("E_SCHEMA", path, "O objeto deve ter o tipo imutável previsto.")
    if any(not hasattr(value, field) for field in fields):
        _error("E_SCHEMA", path, "O objeto imutável está incompleto.")


def _tuple(value: Any, path: str) -> tuple:
    if type(value) is not tuple:
        _error("E_SCHEMA", path, "A coleção deve ser uma tupla imutável.")
    return value


def _revalidate_project(project: Project) -> Project:
    """Reconstitui o formato fechado sem confiar no construtor do chamador."""
    _dataclass(project, Project, ("title", "items", "demands", "stock"), "$")
    mapping: dict = {"version": 1, "title": project.title, "items": [], "demands": [], "stock": []}
    items = _tuple(project.items, "$.items")
    demands = _tuple(project.demands, "$.demands")
    stock = _tuple(project.stock, "$.stock")
    if len(items) > MAX_ITEMS or len(demands) > MAX_DEMANDS or len(stock) > MAX_ITEMS:
        _error("E_LIMIT", "$", "O projeto excede o limite de elementos.")
    for index, item in enumerate(items):
        path = f"$.items[{index}]"
        _dataclass(item, Item, ("id", "name", "unit", "kind", "lot", "components"), path)
        components = _tuple(item.components, path + ".components")
        if len(components) > MAX_EDGES:
            _error("E_LIMIT", path + ".components", "A estrutura excede o limite de arestas.")
        lot = _fraction_parts(item.lot, path + ".lot", input_value=True)
        raw = {"id": item.id, "name": item.name, "unit": item.unit, "kind": item.kind}
        # O tipo será validado antes de qualquer interpretação do seu valor.
        if type(item.kind) is not str or item.kind not in ("make", "buy"):
            _error("E_SCHEMA", path + ".kind", "O tipo deve ser buy ou make.")
        raw["pack" if item.kind == "buy" else "batch"] = quantity_text(lot)
        if item.kind == "make":
            raw["components"] = []
            for component_index, component in enumerate(components):
                component_path = f"{path}.components[{component_index}]"
                _dataclass(component, Component, ("item", "quantity"), component_path)
                amount = _fraction_parts(component.quantity, component_path + ".quantity", input_value=True)
                raw["components"].append({"item": component.item, "quantity": quantity_text(amount)})
        elif components:
            _error("E_SCHEMA", path + ".components", "Um item comprado não pode ter componentes.")
        mapping["items"].append(raw)
    for index, demand in enumerate(demands):
        path = f"$.demands[{index}]"
        _dataclass(demand, Demand, ("id", "item", "quantity"), path)
        amount = _fraction_parts(demand.quantity, path + ".quantity", input_value=True)
        mapping["demands"].append({"id": demand.id, "item": demand.item, "quantity": quantity_text(amount)})
    for index, entry in enumerate(stock):
        path = f"$.stock[{index}]"
        _dataclass(entry, Stock, ("item", "quantity"), path)
        amount = _fraction_parts(entry.quantity, path + ".quantity", input_value=True)
        mapping["stock"].append({"item": entry.item, "quantity": quantity_text(amount)})
    return validate_project(mapping)


def plan_project(project: Project) -> Plan:
    """Planeja todo o catálogo, agregando antes de estoque e arredondamento."""
    project = _revalidate_project(project)
    ordered, levels = _topology(project)
    items = {item.id: item for item in project.items}
    stocks = {entry.item: entry.quantity for entry in project.stock}
    gross = {item_id: _ZERO for item_id in items}
    origins: dict[str, list[Origin]] = {item_id: [] for item_id in items}
    for demand in project.demands:
        gross[demand.item] = _checked(gross[demand.item] + demand.quantity, "$.demands")
        origins[demand.item].append(Origin(demand.item, "direct", demand.id, demand.quantity))
    rows: list[PlanRow] = []
    all_origins: list[Origin] = []
    for item_id in ordered:
        item = items[item_id]
        path = "$.items"
        available = stocks.get(item_id, _ZERO)
        used = min(gross[item_id], available)
        net = max(gross[item_id] - available, _ZERO)
        quotient = net / item.lot
        lots = _checked(-(-quotient.numerator // quotient.denominator), path)
        planned = _checked(lots * item.lot, path)
        leftover = _checked(available + planned - gross[item_id], path)
        rows.append(PlanRow(
            item_id, item.name, item.unit, item.kind, levels[item_id], item.lot,
            gross[item_id], available, used, net, lots, planned, leftover,
        ))
        all_origins.extend(sorted(
            origins[item_id],
            key=lambda origin: (0 if origin.kind == "direct" else 1, origin.source),
        ))
        if item.kind == "make" and lots:
            for component in item.components:
                amount = _checked(lots * component.quantity, path)
                gross[component.item] = _checked(gross[component.item] + amount, path)
                origins[component.item].append(Origin(component.item, "parent", item_id, amount))
    edges = tuple(
        Edge(item.id, component.item, component.quantity)
        for item in project.items
        for component in item.components
    )
    return Plan(project.title, tuple(rows), tuple(all_origins), project.demands, edges)
