"""RQ2 harness: inject faulty compilations and measure which checks detect them.

    python -m guardrailgen.evaluation.rq2 analyze            # offline, no API
    python -m guardrailgen.evaluation.rq2 repair --max-calls 80 --env-file .env

Faults are produced by mutation operators applied to the hand-authored
reference of each in-scope paraphrase family of the RQ1 corpus. Detection is
measured per validation layer:

  structural   schema/grounding validation (Rule.from_dict)
  validator    RTAMT parse + direct contradiction check (validate_rule)
  random20     20 uniformly random states labeled by the reference monitor
  boundary     boundary-value trace bank labeled by the reference monitor
  solver       Z3 agreement with the reference (fail-closed: anything but
               `equivalent` rejects)

Mutants that the solver proves equivalent to their reference are not faults and
are excluded (standard mutation-analysis practice). A fault is `real` only when
a concrete state is found where mutant and reference monitors disagree, so the
solver's detection of real faults is complete by construction; the informative
numbers are how many faults the cheaper layers miss.
Trace checks here evaluate the Boolean monitor directly; RTAMT robustness is only
checked once per mutant (parse), since deterministic lowering cannot diverge.
"""
import argparse
import copy
import itertools
import json
import os
from pathlib import Path
import random
import statistics
import sys
import zlib

from guardrailgen.compiler import Compiler, GroqBackend, OpenRouterBackend
from guardrailgen.compiler.backend import BackendResponse
from guardrailgen.schema import Rule, RuleValidationError, VARIABLES, compile_rule
from guardrailgen.validation import validate_rule

import time

from .rq1 import STOP_AT_ONCE, TRANSIENT, CountingBackend, load_corpus, load_groq_env
from .semantic import check_agreement, region_distance

DELTA = 0.01
LAYERS = ("structural", "validator", "random20", "boundary", "solver")
PIPELINES = {
    "always_on": ("structural", "validator"),
    "always_on+random20": ("structural", "validator", "random20"),
    "always_on+boundary": ("structural", "validator", "boundary"),
    "always_on+boundary+solver": ("structural", "validator", "boundary", "solver"),
}
UNITS = {name: meta["unit"] for name, meta in VARIABLES.items()}


# --------------------------------------------------------------- mutation sites
def _walk(expr, path=()):
    yield path, expr
    if expr.get("op") == "not":
        yield from _walk(expr["arg"], path + ("arg",))
    elif expr.get("op") in ("and", "or"):
        for i, child in enumerate(expr["args"]):
            yield from _walk(child, path + ("args", i))


def _replace(expr, path, new):
    if not path:
        return new
    result = copy.deepcopy(expr)
    node = result
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = new
    return result


def _compares(expr):
    return [(p, n) for p, n in _walk(expr) if n.get("op") == "compare"]


def mutants(reference, scenario):
    """Yield (operator, kind, expression) for every applicable site."""
    regions = sorted(scenario.regions)
    for path, node in _walk(reference):
        op = node.get("op")
        if op == "compare":
            cmp, val = node["comparator"], node["value"]
            yield "flip_direction", "semantic", _replace(reference, path, dict(node, comparator={"lt": "gt", "gt": "lt", "le": "ge", "ge": "le"}[cmp]))
            yield "strictness", "semantic", _replace(reference, path, dict(node, comparator={"lt": "le", "le": "lt", "gt": "ge", "ge": "gt"}[cmp]))
            yield "threshold_x10", "semantic", _replace(reference, path, dict(node, value=round(val * 10, 6) if val else 0.1))
            if val:
                yield "sign_flip", "semantic", _replace(reference, path, dict(node, value=-val))
            other = {"command.linear_speed": "command.angular_speed",
                     "command.angular_speed": "command.linear_speed"}.get(node["variable"])
            if other:
                yield "wrong_variable", "semantic", _replace(reference, path, dict(node, variable=other, unit=UNITS[other]))
            yield "unknown_variable", "structural", _replace(reference, path, dict(node, variable="state.linear_speed", unit="m/s"))
            yield "unit_error", "structural", _replace(reference, path, dict(node, unit="km/h"))
        elif op == "inside":
            swap = regions[(regions.index(node["region"]) + 1) % len(regions)]
            yield "swap_region", "semantic", _replace(reference, path, dict(node, region=swap))
            yield "unknown_region", "structural", _replace(reference, path, dict(node, region="garage"))
        elif op == "not":
            yield "drop_negation", "semantic", _replace(reference, path, copy.deepcopy(node["arg"]))
        elif op in ("and", "or"):
            yield "and_or_swap", "semantic", _replace(reference, path, dict(node, op="or" if op == "and" else "and"))
            if op == "and":
                for i in range(len(node["args"])):
                    rest = [a for j, a in enumerate(node["args"]) if j != i]
                    new = rest[0] if len(rest) == 1 else dict(node, args=rest)
                    yield "drop_conjunct", "semantic", _replace(reference, path, copy.deepcopy(new))
            if op == "or" and len(node["args"]) == 2 and node["args"][0] == {"op": "not", "arg": node["args"][0].get("arg")} \
                    and node["args"][0].get("arg", {}).get("op") == "inside":
                yield "drop_condition", "semantic", _replace(reference, path, copy.deepcopy(node["args"][1]))
    # Contradiction: add a conjunct excluding a top-level upper bound's feasible side.
    top = reference["args"] if reference.get("op") == "and" else [reference]
    for atom in top:
        if atom.get("op") == "compare" and atom["comparator"] in ("le", "lt"):
            bad = dict(atom, comparator="gt", value=round(atom["value"] + 0.1, 6))
            yield "contradiction", "semantic", {"op": "and", "args": copy.deepcopy(top) + [bad]}
            break
    yield "temporal_operator", "structural", {"op": "eventually", "arg": copy.deepcopy(reference)}


# ------------------------------------------------------------------ trace banks
def _free_point(scenario):
    best = None
    for x in [i * 0.5 for i in range(-9, 10)]:
        for y in [i * 0.5 for i in range(-9, 10)]:
            point = {"kind": "circle", "cx": x, "cy": y, "radius": 1e-9}
            clearance = min(region_distance(point, r) for r in scenario.regions.values())
            if best is None or clearance > best[0]:
                best = (clearance, (x, y))
    return best[1]


def positions(scenario):
    r = scenario.footprint_radius
    points = [_free_point(scenario)]
    for region in scenario.regions.values():
        if region["kind"] == "rectangle":
            cx, cy = (region["xmin"] + region["xmax"]) / 2, (region["ymin"] + region["ymax"]) / 2
            points += [(cx, cy), (region["xmin"] - r, cy), (region["xmin"] - r - 0.02, cy),
                       (region["xmax"] + r + 0.02, cy)]
        else:
            cx, cy, rad = region["cx"], region["cy"], region["radius"]
            points += [(cx, cy), (cx - rad - r, cy), (cx - rad - r - 0.02, cy)]
    return points


def _thresholds(expr):
    out = {}
    for _, node in _compares(expr):
        out.setdefault(node["variable"], set()).add(node["value"])
    return out


def boundary_bank(reference_rule, scenario, domains):
    values = {}
    for var, ts in _thresholds(reference_rule.expression).items():
        d = domains[var]
        candidates = {0.0, d["min"], d["max"]}
        for t in ts:
            candidates |= {t, t - DELTA, t + DELTA, -t}
        values[var] = sorted(v for v in candidates if d["min"] <= v <= d["max"])
    names = sorted(values)
    monitor = compile_rule(reference_rule, scenario)
    bank = []
    for (x, y) in positions(scenario):
        for combo in itertools.product(*(values[n] for n in names)):
            state = {"state.x": x, "state.y": y, **dict(zip(names, combo))}
            bank.append({"values": state, "expected": monitor.evaluate(state).value})
    return bank


def random_bank(reference_rule, scenario, domains, n=20, seed=0):
    rng = random.Random(seed)
    variables = sorted(set(_thresholds(reference_rule.expression)) | {"state.x", "state.y"})
    monitor = compile_rule(reference_rule, scenario)
    bank = []
    for _ in range(n):
        state = {v: rng.uniform(domains[v]["min"], domains[v]["max"]) for v in variables}
        bank.append({"values": state, "expected": monitor.evaluate(state).value})
    return bank


def trace_failures(rule, scenario, bank, limit=None):
    monitor = compile_rule(rule, scenario)
    failures = []
    for case in bank:
        actual = monitor.evaluate(case["values"]).value
        if actual != case["expected"]:
            failures.append({"values": case["values"], "expected": case["expected"], "actual": actual})
            if limit and len(failures) >= limit:
                break
    return failures


# -------------------------------------------------------------------- analysis
def _rule(expr, rid, text, scenario):
    return Rule.from_dict({"schema_version": "1.0", "id": rid, "text": text, "expression": expr}, scenario)


def families(corpus):
    seen = {}
    for rule in corpus["rules"]:
        if rule["reference"] is not None and rule["family"] not in seen:
            seen[rule["family"]] = rule
    return list(seen.values())


def detect(expr, reference_rule, scenario, domains, banks):
    """Run every layer independently on one candidate expression."""
    result = {layer: None for layer in LAYERS}
    try:
        candidate = _rule(expr, reference_rule.id, reference_rule.text, scenario)
    except (RuleValidationError, ValueError, TypeError, KeyError, RecursionError) as exc:
        result["structural"] = {"detected": True, "error": str(exc)[:160]}
        for layer in LAYERS[1:]:
            result[layer] = {"detected": True, "note": "not reached; structurally invalid"}
        return result, None
    result["structural"] = {"detected": False}
    report = validate_rule(candidate, scenario)
    rtamt_failed = report["rtamt"] == "failed"
    result["validator"] = {"detected": bool(report["errors"]) or rtamt_failed,
                           "errors": report["errors"][:3],
                           "rtamt": report["rtamt"] if isinstance(report["rtamt"], str) else report["rtamt"].get("status")}
    for name in ("random20", "boundary"):
        failures = trace_failures(candidate, scenario, banks[name], limit=1)
        result[name] = {"detected": bool(failures), "first_failure": failures[0] if failures else None}
    agreement = check_agreement(candidate, reference_rule, scenario, domains)
    result["solver"] = {"detected": agreement["status"] != "equivalent", "status": agreement["status"]}
    return result, agreement


def analyze(args):
    root = Path(args.root)
    corpus, scenario, domains, _ = load_corpus(root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    records, reference_checks = [], []
    for family_rule in families(corpus):
        ref_rule = _rule(family_rule["reference"], family_rule["id"], family_rule["text"], scenario)
        banks = {"boundary": boundary_bank(ref_rule, scenario, domains),
                 "random20": random_bank(ref_rule, scenario, domains, seed=zlib.crc32(family_rule["family"].encode()))}
        # False-rejection check: the correct reference must pass every layer.
        layers, _ = detect(family_rule["reference"], ref_rule, scenario, domains, banks)
        reference_checks.append({"family": family_rule["family"],
                                 "rejected_by": [l for l in LAYERS if layers[l]["detected"]],
                                 "boundary_bank_size": len(banks["boundary"])})
        seen = set()
        for index, (operator, kind, expr) in enumerate(mutants(family_rule["reference"], scenario)):
            key = json.dumps(expr, sort_keys=True)
            if key in seen or expr == family_rule["reference"]:
                continue
            seen.add(key)
            layers, agreement = detect(expr, ref_rule, scenario, domains, banks)
            if layers["structural"]["detected"]:
                fault = "real"
            else:
                fault = {"equivalent": "equivalent_mutant", "not_equivalent": "real"}.get(agreement["status"], "undetermined")
            records.append({"family": family_rule["family"], "category": family_rule["category"],
                            "mutant_id": f"{family_rule['family']}#{index}", "operator": operator, "kind": kind,
                            "fault": fault, "expression": expr,
                            "detected": {l: layers[l]["detected"] for l in LAYERS}, "layers": layers})
    with (out / "mutants.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    summary = summarize(records, reference_checks)
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out / "summary.md").write_text(markdown(summary), encoding="utf-8")
    print(markdown(summary))


def summarize(records, reference_checks):
    real = [r for r in records if r["fault"] == "real"]
    def rates(rows):
        n = len(rows)
        single = {l: round(sum(r["detected"][l] for r in rows) / n, 4) if n else None for l in LAYERS}
        piped = {}
        for name, layers in PIPELINES.items():
            caught = sum(any(r["detected"][l] for l in layers) for r in rows)
            piped[name] = {"detection_rate": round(caught / n, 4) if n else None,
                           "false_acceptance": n - caught}
        return {"faults": n, "per_layer": single, "pipelines": piped}
    by_operator = {}
    for op in sorted({r["operator"] for r in real}):
        by_operator[op] = rates([r for r in real if r["operator"] == op])
    return {
        "mutants_generated": len(records),
        "equivalent_mutants_excluded": sum(r["fault"] == "equivalent_mutant" for r in records),
        "undetermined_excluded": sum(r["fault"] == "undetermined" for r in records),
        "real_faults": len(real),
        "structural_faults": sum(r["kind"] == "structural" for r in real),
        "semantic_faults": sum(r["kind"] == "semantic" for r in real),
        "overall": rates(real),
        "semantic_only": rates([r for r in real if r["kind"] == "semantic"]),
        "by_operator": by_operator,
        "reference_false_rejections": sum(bool(c["rejected_by"]) for c in reference_checks),
        "reference_checks": reference_checks,
    }


def markdown(summary):
    lines = [f"Mutants: {summary['mutants_generated']}; equivalent excluded: {summary['equivalent_mutants_excluded']}; "
             f"undetermined excluded: {summary['undetermined_excluded']}; real faults: {summary['real_faults']} "
             f"({summary['structural_faults']} structural, {summary['semantic_faults']} semantic); "
             f"false rejections of correct references: {summary['reference_false_rejections']}", "",
             "| operator | faults | " + " | ".join(PIPELINES) + " |", "|---|---|" + "---|" * len(PIPELINES)]
    rows = list(summary["by_operator"].items()) + [("**all semantic**", summary["semantic_only"]), ("**all**", summary["overall"])]
    for name, block in rows:
        lines.append(f"| {name} | {block['faults']} | " + " | ".join(
            str(block["pipelines"][p]["detection_rate"]) for p in PIPELINES) + " |")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------ live repair experiment
class InjectingBackend:
    """First call returns the injected faulty candidate; repairs go to the model."""

    def __init__(self, inner, candidate):
        self.inner, self.candidate, self.used = inner, candidate, False

    def configuration(self):
        return dict(self.inner.configuration(), first_attempt="injected_fault")

    def generate(self, messages, response_schema):
        if not self.used:
            self.used = True
            return BackendResponse(copy.deepcopy(self.candidate), {"injected": True, "usage": None})
        return self.inner.generate(messages, response_schema)


def repair(args):
    root = Path(args.root)
    corpus, scenario, domains, library = load_corpus(root)
    if args.env_file:
        load_groq_env(args.env_file)
    backend_class = OpenRouterBackend if args.provider == "openrouter" else GroqBackend
    if not os.environ.get(backend_class.key_env, "").strip():
        raise SystemExit(backend_class.key_env + " is not set (use --env-file)")
    records = [json.loads(l) for l in (Path(args.out) / "mutants.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    # One real fault per (family, operator), deterministic order, capped by --sample.
    chosen, seen = [], set()
    for r in records:
        if r["fault"] == "real" and (r["family"], r["operator"]) not in seen:
            seen.add((r["family"], r["operator"]))
            chosen.append(r)
    random.Random(7).shuffle(chosen)
    chosen = chosen[:args.sample]
    by_family = {r["family"]: r for r in families(corpus)}
    path = Path(args.out) / "repair.jsonl"
    done = set()
    if path.exists():
        done = {row["mutant_id"] for row in (json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip())
                if not _transient(row)}
    provider = CountingBackend(backend_class(args.model, timeout=args.timeout,
                                            max_output_tokens=args.max_completion_tokens), args.max_calls)
    for record in chosen:
        if record["mutant_id"] in done:
            continue
        if provider.calls + 2 > provider.budget:
            print(f"Stopping: call budget reached ({provider.calls}/{provider.budget}).")
            break
        family_rule = by_family[record["family"]]
        ref_rule = _rule(family_rule["reference"], family_rule["id"], family_rule["text"], scenario)
        bank = boundary_bank(ref_rule, scenario, domains)

        def validator(rule, cfg, ref_rule=ref_rule, bank=bank):
            report = validate_rule(rule, cfg)
            failures = trace_failures(rule, cfg, bank, limit=3)
            if failures:
                report["errors"].append(f"{len(failures)}+ labeled test states disagree")
                report["failing_test_states"] = failures
            agreement = check_agreement(rule, ref_rule, cfg, domains)
            report["equivalence"] = {k: agreement[k] for k in ("status", "counterexample") if k in agreement}
            if agreement["status"] != "equivalent":
                report["errors"].append("Disagrees with the approved test oracle: " + agreement["status"])
            return report

        injected = {"status": "compiled", "message": "Candidate interpretation.",
                    "rule": {"schema_version": "1.0", "id": family_rule["id"], "text": family_rule["text"],
                             "expression": record["expression"]}}
        calls_before = provider.calls
        retries = 0
        while True:
            compiler = Compiler(InjectingBackend(provider, injected), scenario, max_repairs=2, validator=validator,
                                examples=library["examples"], example_set_version=library["version"])
            result = compiler.compile(family_rule["text"], family_rule["id"]).to_dict()
            transient = result["status"] in ("backend_error", "timeout") and \
                any(m in result["message"] for m in TRANSIENT + ("timed out",))
            if transient and retries < args.retries and not any(m in result["message"] for m in STOP_AT_ONCE):
                retries += 1
                wait = min(300, 30 * 2 ** (retries - 1))
                print(f"  {record['mutant_id']}: transient '{result['message']}', retry {retries} in {wait}s")
                time.sleep(wait)
                continue
            break
        if transient:
            print("Provider said: " + result["message"])
            print("Stopping: still rate-limited; nothing recorded for this fault. Rerun later to resume.")
            break
        final = None
        if result["status"] == "compiled":
            final = check_agreement(_rule(result["artifact"]["rule"]["expression"], family_rule["id"],
                                          family_rule["text"], scenario), ref_rule, scenario, domains)["status"]
        out = {"mutant_id": record["mutant_id"], "family": record["family"], "operator": record["operator"],
               "kind": record["kind"], "final_status": result["status"], "final_agreement": final,
               "repaired": final == "equivalent", "attempts": len(result["attempts"]),
               "model_calls": provider.calls - calls_before, "message": result["message"][:300],
               "attempt_log": [{k: a.get(k) for k in ("attempt", "status", "errors")} for a in result["attempts"]]}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(out, ensure_ascii=False) + "\n")
        print(f"{record['mutant_id']:32s} {record['operator']:18s} {result['status']:18s} repaired={out['repaired']} calls={provider.calls}")
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()] if path.exists() else []
    rows = [r for r in rows if not _transient(r)]
    if rows:
        repaired = [r for r in rows if r["repaired"]]
        summary = {"injected": len(rows), "repaired_to_reference": len(repaired),
                   "repair_rate": round(len(repaired) / len(rows), 4),
                   "safe_outcome_rate": round(sum(r["repaired"] or r["final_status"] != "compiled" for r in rows) / len(rows), 4),
                   "accepted_but_wrong": sum(r["final_status"] == "compiled" and not r["repaired"] for r in rows),
                   "mean_repairs_when_repaired": round(statistics.mean(r["attempts"] - 1 for r in repaired), 3) if repaired else None,
                   "by_final_status": {s: sum(r["final_status"] == s for r in rows) for s in sorted({r["final_status"] for r in rows})},
                   "model_calls": sum(r["model_calls"] for r in rows)}
        (Path(args.out) / "repair_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary, indent=2))


def _transient(row):
    return row.get("final_status") in ("backend_error", "timeout") and \
        any(m in (row.get("message") or "") for m in TRANSIENT + ("timed out",))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("analyze")
    a.add_argument("--root", default=".")
    a.add_argument("--out", default="runs/rq2")
    r = sub.add_parser("repair")
    r.add_argument("--root", default=".")
    r.add_argument("--out", default="runs/rq2")
    r.add_argument("--max-calls", type=int, required=True)
    r.add_argument("--sample", type=int, default=40)
    r.add_argument("--model", default=os.environ.get("GROQ_MODEL") or GroqBackend.default_model)
    r.add_argument("--timeout", type=float, default=60.0)
    r.add_argument("--env-file")
    r.add_argument("--max-completion-tokens", type=int, default=2500)
    r.add_argument("--provider", choices=("groq", "openrouter"), default="openrouter")
    r.add_argument("--retries", type=int, default=5)
    args = parser.parse_args(argv)
    analyze(args) if args.command == "analyze" else repair(args)


if __name__ == "__main__":
    sys.exit(main())
