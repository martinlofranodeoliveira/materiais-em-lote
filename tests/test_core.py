"""Provas do contrato de cálculo, validação e imutabilidade pública."""

from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
from itertools import product
import copy
import json
from pathlib import Path
import random
import unittest

from materiais_em_lote.core import (
    Component, Demand, Item, PlanError, Project, Stock,
    parse_project, plan_project, quantity_text, validate_project,
)
from materiais_em_lote.demo import demo_mapping, demo_project


def bought(item_id="a", pack="1", **changes):
    result = {"id": item_id, "name": item_id.upper(), "unit": "un", "kind": "buy", "pack": pack}
    result.update(changes)
    return result


def made(item_id, components, batch="1"):
    return {
        "id": item_id, "name": item_id.upper(), "unit": "un", "kind": "make", "batch": batch,
        "components": [{"item": child, "quantity": amount} for child, amount in components],
    }


def document(items=None, demands=None, stock=None):
    return {
        "version": 1, "title": "Oficina",
        "items": [bought()] if items is None else items,
        "demands": [] if demands is None else demands,
        "stock": [] if stock is None else stock,
    }


def demand(item="a", amount="1", demand_id="pedido"):
    return {"id": demand_id, "item": item, "quantity": amount}


class PlanningTests(unittest.TestCase):
    def test_demonstration_manual_golden_and_origin_memory(self):
        plan = plan_project(demo_project())
        expected = {
            "kit": ("3", "1", "2", 1, "2", "0"),
            "expositor": ("2", "0", "2", 2, "2", "0"),
            "painel": ("7", "2", "5", 2, "6", "1"),
            "suporte": ("8", "1", "7", 2, "8", "1"),
            "chapa": ("2", "1", "1", 1, "2", "1"),
            "tinta": ("1.5", "0.3", "1.2", 2, "2", "0.8"),
        }
        for row in plan.rows:
            actual = tuple(quantity_text(getattr(row, key)) for key in ("gross", "used", "net"))
            actual += (row.lots, quantity_text(row.planned), quantity_text(row.leftover))
            self.assertEqual(actual, expected[row.item])
        self.assertEqual([row.item for row in plan.rows], ["expositor", "kit", "painel", "chapa", "suporte", "tinta"])
        self.assertEqual({row.item: row.level for row in plan.rows}, {"expositor": 0, "kit": 0, "painel": 1, "chapa": 2, "suporte": 1, "tinta": 2})
        self.assertEqual(
            [(origin.source, quantity_text(origin.quantity)) for origin in plan.origins if origin.item == "tinta"],
            [("expositor", "0.4"), ("kit", "0.5"), ("painel", "0.6")],
        )
        self.assertEqual(len(plan.origins), 10)
        self.assertEqual(len(plan.edges), 8)

    def test_shared_item_at_different_depths_waits_for_all_parents(self):
        mapping = document(
            [made("a", [("z", "2"), ("b", "1")]), made("b", [("c", "1")]), made("c", [("z", "3")]), bought("z", "4")],
            [demand("a"), demand("z", "1", "direto")],
            [{"item": "z", "quantity": "2"}],
        )
        plan = plan_project(validate_project(mapping))
        row = {row.item: row for row in plan.rows}["z"]
        self.assertEqual((row.level, row.gross, row.used, row.net, row.lots, row.leftover), (3, Fraction(6), Fraction(2), Fraction(4), 1, Fraction(0)))
        self.assertEqual([(origin.kind, origin.source) for origin in plan.origins if origin.item == "z"], [("direct", "direto"), ("parent", "a"), ("parent", "c")])

    def test_subassembly_stock_stops_child_consumption(self):
        mapping = document(
            [made("a", [("b", "3")]), made("b", [("c", "7")], "2"), bought("c", "5")],
            [demand("a", "2")], [{"item": "b", "quantity": "5"}],
        )
        rows = {row.item: row for row in plan_project(validate_project(mapping)).rows}
        self.assertEqual((rows["b"].gross, rows["b"].net, rows["b"].lots, rows["b"].leftover), (Fraction(6), Fraction(1), 1, Fraction(1)))
        self.assertEqual((rows["c"].gross, rows["c"].lots, rows["c"].planned), (Fraction(7), 2, Fraction(10)))
        mapping["stock"][0]["quantity"] = "6"
        plan = plan_project(validate_project(mapping))
        rows = {row.item: row for row in plan.rows}
        self.assertEqual(rows["c"].gross, Fraction(0))
        self.assertFalse(any(origin.item == "c" for origin in plan.origins))
        self.assertEqual(len(plan.edges), 2)

    def test_fractional_batch_and_pack_use_per_batch_consumption(self):
        mapping = document(
            [made("a", [("b", "0.3")], "0.25"), bought("b", "0.4")],
            [demand("a", "0.6")], [{"item": "a", "quantity": "0.1"}, {"item": "b", "quantity": "0.1"}],
        )
        a, b = plan_project(validate_project(mapping)).rows
        self.assertEqual((a.lots, a.planned, a.leftover), (2, Fraction(1, 2), Fraction(0)))
        self.assertEqual((b.gross, b.net, b.lots, b.planned, b.leftover), (Fraction(3, 5), Fraction(1, 2), 2, Fraction(4, 5), Fraction(3, 10)))

    def test_no_demands_keeps_stock_and_full_catalog(self):
        mapping = document([made("a", [("b", "3")]), bought("b"), bought("c")], stock=[{"item": "a", "quantity": "2"}, {"item": "c", "quantity": "0.000001"}])
        plan = plan_project(validate_project(mapping))
        self.assertEqual(plan.origins, ())
        self.assertEqual(len(plan.edges), 1)
        for row in plan.rows:
            self.assertEqual((row.gross, row.used, row.net, row.lots, row.planned), (Fraction(0), Fraction(0), Fraction(0), 0, Fraction(0)))
            self.assertEqual(row.leftover, row.stock)

    def test_input_permutations_have_identical_results_and_no_mutation(self):
        original = demo_mapping()
        expected = plan_project(validate_project(original))
        for seed in range(12):
            mapping = copy.deepcopy(original)
            randomizer = random.Random(seed)
            for key in ("items", "demands", "stock"):
                randomizer.shuffle(mapping[key])
            for item in mapping["items"]:
                if "components" in item:
                    randomizer.shuffle(item["components"])
            before = copy.deepcopy(mapping)
            self.assertEqual(plan_project(validate_project(mapping)), expected)
            self.assertEqual(mapping, before)

    def test_independent_small_dag_oracle_enumerates_feasible_lot_vectors(self):
        # Este oráculo busca vetores de lotes por força bruta. Não usa topologia,
        # netting, ceil nem as funções aritméticas internas do planejador.
        possible_edges = ((0, 1), (0, 2), (1, 2))
        for mask in range(8):
            edges = [(parent, child, 1 + child % 2) for bit, (parent, child) in enumerate(possible_edges) if mask & (1 << bit)]
            for requested, stocks in (((3, 0, 1), (1, 0, 1)), ((2, 1, 2), (0, 1, 0))):
                yields = (2, 3, 2)
                solution = None
                for lots in product(range(9), repeat=3):
                    gross = tuple(requested[child] + sum(lots[parent] * per_batch for parent, target, per_batch in edges if target == child) for child in range(3))
                    if all(stocks[index] + lots[index] * yields[index] >= gross[index] for index in range(3)):
                        solution = lots, gross
                        break
                self.assertIsNotNone(solution)
                expected_lots, expected_gross = solution
                items = []
                for index, item_id in enumerate(("a", "b", "c")):
                    children = [("abc"[child], str(amount)) for parent, child, amount in edges if parent == index]
                    items.append(made(item_id, children, str(yields[index])) if children else bought(item_id, str(yields[index])))
                mapping = document(items, [demand("abc"[index], str(amount), f"p{index}") for index, amount in enumerate(requested) if amount], [{"item": "abc"[index], "quantity": str(amount)} for index, amount in enumerate(stocks)])
                rows = {row.item: row for row in plan_project(validate_project(mapping)).rows}
                for index, item_id in enumerate("abc"):
                    with self.subTest(mask=mask, requested=requested, item=item_id):
                        self.assertEqual(rows[item_id].lots, expected_lots[index])
                        self.assertEqual(rows[item_id].gross, expected_gross[index])
                        self.assertEqual(rows[item_id].leftover, stocks[index] + expected_lots[index] * yields[index] - expected_gross[index])


class ValidationTests(unittest.TestCase):
    def assert_error(self, code, operation, *args):
        with self.assertRaises(PlanError) as caught:
            operation(*args)
        self.assertEqual(caught.exception.code, code)
        self.assertTrue(caught.exception.path.startswith("$"))
        return caught.exception

    def test_strict_json_and_sanitized_errors(self):
        bad_inputs = (
            b"\xef\xbb\xbf{}", b"\xff", '{"version":1,"version":1}',
            '{"secret":"SEGREDO-SENTINELA", "number":NaN}', '{"x":Infinity}',
            '{"x":-Infinity}', '{"x":1.5}', '{"x":1e2}', '{"x":',
            "\ud800", '{"value":' + "9" * 5000 + "}",
        )
        for value in bad_inputs:
            with self.subTest(value_type=type(value).__name__):
                error = self.assert_error("E_JSON", parse_project, value)
                self.assertNotIn("SEGREDO-SENTINELA", str(error))
                self.assertNotIn("Traceback", str(error))
        self.assert_error("E_LIMIT", parse_project, b" " * (1024 * 1024 + 1))
        self.assert_error("E_LIMIT", parse_project, "[" * 2000 + "]" * 2000)
        self.assert_error("E_JSON", parse_project, bytearray(b"{}"))
        self.assertEqual(parse_project(json.dumps(demo_mapping()).encode()), demo_project())

    def test_schema_is_closed_and_types_are_exact(self):
        mutations = (
            lambda data: data.update(extra="sentinela"),
            lambda data: data.pop("stock"),
            lambda data: data.update(version=True),
            lambda data: data.update(version=2),
            lambda data: data.update(items=()),
            lambda data: data["items"][0].update(components=[]),
            lambda data: data["items"][0].update(kind="other"),
            lambda data: data["items"][0].update(pack=1),
        )
        for mutate in mutations:
            data = document()
            mutate(data)
            with self.subTest(mutation=mutate):
                with self.assertRaises(PlanError):
                    validate_project(data)
        self.assert_error("E_SCHEMA", validate_project, document(items=[]))
        self.assert_error("E_SCHEMA", validate_project, demo_project())
        self.assert_error("E_SCHEMA", validate_project, document([made("a", [])]))
        for subclassed in (type("MappingSubclass", (dict,), {})(document()),):
            self.assert_error("E_SCHEMA", validate_project, subclassed)
        for key, value in (("items", type("ListSubclass", (list,), {})([bought()])), ("title", type("StringSubclass", (str,), {})("Título")), ("version", type("IntegerSubclass", (int,), {})(1))):
            data = document()
            data[key] = value
            self.assert_error("E_SCHEMA", validate_project, data)
        for value in (1.0, object(), set(), b"x"):
            self.assert_error("E_SCHEMA", validate_project, document(stock=value))

    def test_quantity_grammar_and_limits(self):
        for value in (0, 1, True, None, "", "01", "00.1", ".5", "1.", "+1", "-1", "1e2", " 1", "1 ", "١", "1.0000000", "NaN"):
            with self.subTest(quantity=value):
                self.assert_error("E_QUANTITY", validate_project, document([bought(pack=value)]))
        self.assert_error("E_QUANTITY", validate_project, document([bought(pack="0")]))
        self.assert_error("E_QUANTITY", validate_project, document(demands=[demand(amount="0")]))
        for value in ("1000000000001", "999999999999999999999999"):
            self.assert_error("E_LIMIT", validate_project, document([bought(pack=value)]))
        valid = document([bought(pack="1000000000000.000000")], stock=[{"item": "a", "quantity": "0.000000"}])
        self.assertEqual(validate_project(valid).items[0].lot, Fraction(10**12))
        self.assertEqual(validate_project(document([bought(pack="0.000001")])).items[0].lot, Fraction(1, 10**6))

    def test_identifiers_and_unicode_text(self):
        for value in ("A", "1a", "a b", "á", "a" * 41, "a/secret", "a\n"):
            with self.subTest(identifier=value):
                self.assert_error("E_SCHEMA", validate_project, document([bought(value)]))
        for value in ("un " , "U", "u" * 17):
            self.assert_error("E_SCHEMA", validate_project, document([bought(unit=value)]))
        for value in ("", "x" * 121, " externo", "externo ", "x\x00", "x\x7f", "x\ud800", "x\u2028", "x\u2029", "x\ufffe", "x\uffff"):
            data = document()
            data["title"] = value
            self.assert_error("E_SCHEMA", validate_project, data)
        for value in ("x" * 101, "nome\n"):
            self.assert_error("E_SCHEMA", validate_project, document([bought(name=value)]))
        data = document([bought("a" * 40, unit="u" * 16, name="á" * 100)])
        data["title"] = "😀" * 120
        self.assertEqual(validate_project(data).title, data["title"])
        for leader in ("=1+1", "+SUM(A1)", "-nome", "@nome", "<a>&á"):
            data = document([bought(name=leader)])
            self.assertEqual(validate_project(data).items[0].name, leader)

    def test_references_duplicates_and_global_cycles(self):
        self.assert_error("E_REFERENCE", validate_project, document(demands=[demand("missing")]))
        self.assert_error("E_REFERENCE", validate_project, document(stock=[{"item": "missing", "quantity": "0"}]))
        data = document([made("a", [("zmissing", "1"), ("b", "1")]), bought("b")])
        error = self.assert_error("E_REFERENCE", validate_project, data)
        self.assertEqual(error.path, "$.items[0].components[0].item")
        self.assert_error("E_DUPLICATE", validate_project, document([bought(), bought()]))
        self.assert_error("E_DUPLICATE", validate_project, document(demands=[demand(), demand()]))
        self.assert_error("E_DUPLICATE", validate_project, document(stock=[{"item": "a", "quantity": "0"}] * 2))
        self.assert_error("E_DUPLICATE", validate_project, document([made("a", [("b", "1"), ("b", "2")]), bought("b")]))
        self.assert_error("E_CYCLE", validate_project, document([made("a", [("a", "1")])]))
        # O ciclo está desconectado do pedido e ainda assim invalida o catálogo.
        self.assert_error("E_CYCLE", validate_project, document([bought("a"), made("b", [("c", "1")]), made("c", [("b", "1")])], [demand("a")]))

    def test_catalog_and_demand_boundaries(self):
        items = [bought(f"i{index}") for index in range(250)]
        demands = [demand("i0", "1", f"p{index}") for index in range(250)]
        self.assertEqual(len(plan_project(validate_project(document(items, demands))).rows), 250)
        self.assert_error("E_LIMIT", validate_project, document(items + [bought("last")]))
        self.assert_error("E_LIMIT", validate_project, document([bought()], [demand(demand_id=f"p{index}") for index in range(251)]))
        # 2000 arestas distintas em um DAG de 250 nós são aceitas; a próxima não.
        nodes = [bought(f"i{index}") for index in range(250)]
        remaining = 2000
        for parent in range(9):
            count = min(249 - parent, remaining)
            nodes[parent] = made(f"i{parent}", [(f"i{child}", "1") for child in range(parent + 1, parent + count + 1)])
            remaining -= count
        valid = validate_project(document(nodes))
        self.assertEqual(sum(len(item.components) for item in valid.items), 2000)
        self.assertEqual(len(plan_project(valid).edges), 2000)
        nodes[9] = made("i9", [("i10", "1")])
        self.assert_error("E_LIMIT", validate_project, document(nodes))

    def test_result_limits_fail_without_returning_partial_plan(self):
        cases = (
            document(demands=[demand(amount="1000000000000"), demand(amount="1", demand_id="outro")]),
            document([bought(pack="0.000001")], [demand(amount="1000000000000")]),
            document([bought(pack="999999999999")], [demand(amount="1000000000000")]),
            document([made("a", [("b", "1000000000000")]), bought("b")], [demand(amount="2")]),
        )
        for data in cases:
            with self.subTest(data=data):
                self.assert_error("E_LIMIT", plan_project, validate_project(data))
        boundary = plan_project(validate_project(document(demands=[demand(amount="1000000000000")]))).rows[0]
        self.assertEqual((boundary.gross, boundary.lots, boundary.planned), (Fraction(10**12), 10**12, Fraction(10**12)))


class PublicBoundaryTests(unittest.TestCase):
    def test_quantity_text_exact_formats_and_rational_limits(self):
        for value, expected in ((Fraction(0), "0"), (Fraction(100), "100"), (Fraction(1, 8), "0.125"), (Fraction(-3, 40), "-0.075"), (Fraction(1, 3), "1/3"), (Fraction(-8, 6), "-4/3"), (Fraction("1.200000"), "1.2")):
            self.assertEqual(quantity_text(value), expected)
        self.assertEqual(quantity_text(Fraction(1, 10**79)), "0." + "0" * 78 + "1")
        for value in (Fraction(10**12 + 1), Fraction(1, 10**80)):
            with self.assertRaises(PlanError) as caught:
                quantity_text(value)
            self.assertEqual(caught.exception.code, "E_LIMIT")
        for value in (1, 0.5, "1", type("FractionSubclass", (Fraction,), {})(1)):
            with self.assertRaises(PlanError):
                quantity_text(value)

    def test_no_mutable_aliases_and_all_output_records_are_frozen(self):
        mapping = demo_mapping()
        project = validate_project(mapping)
        plan = plan_project(project)
        mapping["items"][0]["components"][0]["quantity"] = "999"
        mapping["demands"].clear()
        self.assertEqual(plan_project(project), plan)
        component = next(item.components[0] for item in project.items if item.components)
        for record, field in ((project, "title"), (project.items[0], "name"), (component, "item"), (project.demands[0], "item"), (project.stock[0], "item"), (plan, "title"), (plan.rows[0], "item"), (plan.origins[0], "item"), (plan.edges[0], "parent")):
            with self.assertRaises(FrozenInstanceError):
                setattr(record, field, "alteração")
        first, second = demo_mapping(), demo_mapping()
        first["items"][0]["components"].clear()
        self.assertTrue(second["items"][0]["components"])

    def test_manual_project_is_revalidated_including_forged_objects(self):
        project = validate_project(document(demands=[demand()]))
        invalid_projects = [
            replace(project, items=list(project.items)),
            replace(project, items=(replace(project.items[0], lot=Fraction(1, 3)),)),
            replace(project, items=(replace(project.items[0], lot=Fraction(-1)),)),
            replace(project, items=(replace(project.items[0], lot=Fraction(0)),)),
            replace(project, items=(replace(project.items[0], lot=1),)),
            replace(project, items=(replace(project.items[0], components=(Component("a", Fraction(1)),)),)),
            replace(project, items=(replace(project.items[0], components=[]),)),
            replace(project, demands=(Demand("p", "absent", Fraction(1)),)),
            replace(project, stock=(Stock("a", Fraction(-1)),)),
            replace(project, items=(Item("a", "A", "un", "make", Fraction(1), (Component("a", Fraction(1)),)),)),
            Project.__new__(Project),
        ]
        for invalid in invalid_projects:
            with self.subTest(invalid_type=type(invalid).__name__):
                with self.assertRaises(PlanError):
                    plan_project(invalid)
        for numerator, denominator in ((2, 2), (1, 0), (True, 1), (1, -1)):
            fraction = Fraction(1)
            object.__setattr__(fraction, "_numerator", numerator)
            object.__setattr__(fraction, "_denominator", denominator)
            forged = replace(project, items=(replace(project.items[0], lot=fraction),))
            with self.assertRaises(PlanError):
                plan_project(forged)
        class Subclass(Project):
            pass
        with self.assertRaises(PlanError):
            plan_project(Subclass(project.title, project.items, project.demands, project.stock))
        # Fractions e registros construídos à mão dentro da fronteira são válidos.
        manual = Project("Manual", (Item("a", "A", "un", "buy", Fraction(1, 2), ()),), (Demand("p", "a", Fraction(3, 4)),), ())
        self.assertEqual(plan_project(manual).rows[0].planned, Fraction(1))

    def test_fixture_is_the_original_demonstration(self):
        fixture = Path(__file__).resolve().parents[1] / "fixtures" / "projeto-oficina.json"
        self.assertEqual(json.loads(fixture.read_text(encoding="utf-8")), demo_mapping())
        self.assertEqual(parse_project(fixture.read_bytes()), demo_project())


if __name__ == "__main__":
    unittest.main()
