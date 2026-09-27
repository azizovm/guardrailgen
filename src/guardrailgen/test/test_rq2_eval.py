"""RQ2 fault-injection contracts. No network."""
import copy
import json
from pathlib import Path

import pytest

from guardrailgen.compiler import BackendResponse, Compiler
from guardrailgen.evaluation.rq1 import load_corpus

pytest.importorskip("z3")
from guardrailgen.evaluation.rq2 import (InjectingBackend, _rule, boundary_bank, detect, families,  # noqa: E402
                                         mutants, random_bank, trace_failures)

ROOT = Path(__file__).resolve().parents[3]
CORPUS, SCENARIO, DOMAINS, LIBRARY = load_corpus(ROOT)


def family(name):
    entry = next(r for r in families(CORPUS) if r["family"] == name)
    return entry, _rule(entry["reference"], entry["id"], entry["text"], SCENARIO)


def banks(ref):
    return {"boundary": boundary_bank(ref, SCENARIO, DOMAINS), "random20": random_bank(ref, SCENARIO, DOMAINS)}


def test_one_reference_per_in_scope_family():
    names = [f["family"] for f in families(CORPUS)]
    assert len(names) == len(set(names)) == 16


def test_mutants_cover_operators_and_differ_from_reference():
    entry, _ = family("f10-school-speed")
    produced = list(mutants(entry["reference"], SCENARIO))
    operators = {op for op, _, _ in produced}
    assert {"flip_direction", "strictness", "threshold_x10", "sign_flip", "wrong_variable", "swap_region",
            "drop_negation", "and_or_swap", "drop_conjunct", "drop_condition", "unknown_region",
            "unit_error", "unknown_variable", "temporal_operator"} <= operators
    assert all(expr != entry["reference"] for _, _, expr in produced)


def test_reference_passes_every_layer_and_bank_is_labeled_by_reference():
    entry, ref = family("f15-dock-and-school")
    b = banks(ref)
    assert {c["expected"] for c in b["boundary"]} == {"SAFE", "UNSAFE"}
    assert trace_failures(ref, SCENARIO, b["boundary"]) == []
    layers, agreement = detect(entry["reference"], ref, SCENARIO, DOMAINS, b)
    assert agreement["status"] == "equivalent"
    assert not any(layer["detected"] for layer in layers.values())


def test_strictness_fault_is_missed_by_cheap_checks_and_caught_by_boundary_and_solver():
    entry, ref = family("f04-speed-mag-0-3")
    faulty = copy.deepcopy(entry["reference"])
    faulty["args"][0]["comparator"] = "lt"          # <= 0.3 becomes < 0.3
    layers, agreement = detect(faulty, ref, SCENARIO, DOMAINS, banks(ref))
    assert not layers["structural"]["detected"] and not layers["validator"]["detected"]
    assert layers["boundary"]["detected"] and layers["solver"]["detected"]
    assert agreement["status"] == "not_equivalent"


def test_structural_fault_short_circuits():
    entry, ref = family("f02-dock-keepout")
    faulty = {"op": "not", "arg": {"op": "inside", "region": "garage"}}
    layers, agreement = detect(faulty, ref, SCENARIO, DOMAINS, banks(ref))
    assert layers["structural"]["detected"] and agreement is None


class Scripted:
    def __init__(self, payload):
        self.payload, self.messages = payload, []

    def configuration(self):
        return {"provider": "fixture"}

    def generate(self, messages, schema):
        self.messages.append(copy.deepcopy(messages))
        return BackendResponse(copy.deepcopy(self.payload), {"usage": None})


def test_injecting_backend_sends_fault_first_and_repair_prompt_hides_reference():
    entry, ref = family("f07-no-reverse")
    fixed = {"status": "compiled", "message": "m", "rule": {"schema_version": "1.0", "id": entry["id"],
             "text": entry["text"], "expression": entry["reference"]}}
    injected = copy.deepcopy(fixed)
    injected["rule"]["expression"] = dict(entry["reference"], comparator="le")
    inner = Scripted(fixed)

    def validator(rule, cfg):
        from guardrailgen.evaluation.semantic import check_agreement
        status = check_agreement(rule, ref, cfg, DOMAINS)
        return {"errors": [] if status["status"] == "equivalent" else ["disagrees"],
                "equivalence": {"status": status["status"], "counterexample": status.get("counterexample")}}

    result = Compiler(InjectingBackend(inner, injected), SCENARIO, validator=validator).compile(entry["text"], entry["id"])
    assert result.ok and len(result.attempts) == 2 and len(inner.messages) == 1
    assert "disagrees" in result.attempts[0]["errors"][0]
    assert json.dumps(entry["reference"]) not in json.dumps(inner.messages[0][-1])
