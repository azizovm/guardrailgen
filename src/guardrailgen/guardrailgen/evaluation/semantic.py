"""Semantic agreement between a candidate rule and a hand-authored reference.

Extends the numeric/Boolean reference equivalence of validation.equivalence to
rules with region atoms by propositional abstraction:

* every `inside(region)` atom becomes an independent Boolean variable;
* two regions whose footprint-inflated shapes cannot both be touched at once
  (distance > 2 * footprint radius) are declared mutually exclusive.

The abstraction admits every geometrically feasible assignment, so an UNSAT
disagreement query ("equivalent") is a proof over the declared domains. A SAT
answer may be spurious under the abstraction, so a witness only counts as
`not_equivalent` once a concrete state is found where the Boolean monitors of
candidate and reference disagree; otherwise it is `unconfirmed`.
This decides agreement with an author-written reference, not English intent.
"""
import math

from guardrailgen.schema import Rule, Scenario, VARIABLES, compile_rule


def _regions(expr, acc=None):
    acc = set() if acc is None else acc
    op = expr["op"]
    if op == "inside":
        acc.add(expr["region"])
    elif op == "not":
        _regions(expr["arg"], acc)
    elif op in ("and", "or"):
        for child in expr["args"]:
            _regions(child, acc)
    return acc


def _variables(expr, acc=None):
    acc = set() if acc is None else acc
    op = expr["op"]
    if op == "compare":
        acc.add(expr["variable"])
    elif op == "not":
        _variables(expr["arg"], acc)
    elif op in ("and", "or"):
        for child in expr["args"]:
            _variables(child, acc)
    return acc


def region_distance(a, b):
    """Euclidean distance between two closed regions (rectangle or circle)."""
    def rect_point(r, x, y):
        dx = max(r["xmin"] - x, 0.0, x - r["xmax"])
        dy = max(r["ymin"] - y, 0.0, y - r["ymax"])
        return math.hypot(dx, dy)
    if a["kind"] == "rectangle" and b["kind"] == "rectangle":
        dx = max(a["xmin"] - b["xmax"], b["xmin"] - a["xmax"], 0.0)
        dy = max(a["ymin"] - b["ymax"], b["ymin"] - a["ymax"], 0.0)
        return math.hypot(dx, dy)
    if a["kind"] == "circle" and b["kind"] == "circle":
        return max(0.0, math.hypot(a["cx"] - b["cx"], a["cy"] - b["cy"]) - a["radius"] - b["radius"])
    rect, circle = (a, b) if a["kind"] == "rectangle" else (b, a)
    return max(0.0, rect_point(rect, circle["cx"], circle["cy"]) - circle["radius"])


def exclusive_pairs(scenario, names):
    names = sorted(names)
    pairs = []
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            if region_distance(scenario.regions[first], scenario.regions[second]) > 2 * scenario.footprint_radius:
                pairs.append((first, second))
    return pairs


def _lower(expr, reals, bools, z3):
    op = expr["op"]
    if op == "compare":
        left = reals[expr["variable"]]
        right = z3.RealVal(str(expr["value"]), ctx=left.ctx)
        return {"lt": left < right, "le": left <= right, "gt": left > right, "ge": left >= right}[expr["comparator"]]
    if op == "inside":
        return bools[expr["region"]]
    if op == "not":
        return z3.Not(_lower(expr["arg"], reals, bools, z3))
    args = [_lower(child, reals, bools, z3) for child in expr["args"]]
    return z3.And(*args) if op == "and" else z3.Or(*args)


def _grid(domain, step):
    lo, hi = domain["min"], domain["max"]
    count = int(round((hi - lo) / step))
    return [lo + i * step for i in range(count + 1)]


def _confirm(candidate, reference, scenario, values, domains, step=0.05):
    """Search a concrete position (other signals fixed) where the monitors disagree."""
    cand, ref = compile_rule(candidate, scenario), compile_rule(reference, scenario)
    base = dict(values)
    uses_position = bool(_regions(candidate.expression) | _regions(reference.expression)) or \
        {"state.x", "state.y"} & (set(base))
    if not uses_position:
        if cand.evaluate(base).value != ref.evaluate(base).value:
            return base
        return None
    xs = _grid(domains["state.x"], step) if "state.x" in domains else [0.0]
    ys = _grid(domains["state.y"], step) if "state.y" in domains else [0.0]
    for x in xs:
        for y in ys:
            point = dict(base, **{"state.x": x, "state.y": y})
            a, b = cand.evaluate(point).value, ref.evaluate(point).value
            if a != b and "UNKNOWN" not in (a, b):
                return point
    return None


def check_agreement(candidate, reference, scenario, domains, timeout_ms=5000):
    """Return {'status': equivalent|not_equivalent|unconfirmed|unknown, ...}."""
    import z3
    scenario = Scenario.from_dict(scenario.to_dict())
    candidate = Rule.from_dict(candidate.to_dict(), scenario)
    reference = Rule.from_dict(reference.to_dict(), scenario)
    variables = _variables(candidate.expression) | _variables(reference.expression)
    regions = _regions(candidate.expression) | _regions(reference.expression)
    missing = sorted(v for v in variables if v not in domains)
    if missing:
        raise ValueError("Missing declared domains: " + ", ".join(missing))
    ctx = z3.Context()
    reals = {name: z3.Real(name, ctx) for name in sorted(variables)}
    bools = {name: z3.Bool("inside_" + name, ctx) for name in sorted(regions)}
    left = _lower(candidate.expression, reals, bools, z3)
    right = _lower(reference.expression, reals, bools, z3)
    solver = z3.SolverFor("QF_LRA", ctx=ctx)
    solver.set(timeout=int(timeout_ms))
    for name, var in reals.items():
        bounds = domains[name]
        if bounds["unit"] != VARIABLES[name]["unit"]:
            raise ValueError(f"{name} domain unit mismatch")
        solver.add(var >= z3.RealVal(str(bounds["min"]), ctx), var <= z3.RealVal(str(bounds["max"]), ctx))
    exclusive = exclusive_pairs(scenario, regions)
    for first, second in exclusive:
        solver.add(z3.Not(z3.And(bools[first], bools[second])))
    solver.add(z3.Xor(left, right))
    report = {"method": "z3-qf-lra-region-abstraction-v1",
              "regions_abstracted": sorted(regions), "exclusive_region_pairs": [list(p) for p in exclusive],
              "position_compares_with_regions": bool(regions) and bool({"state.x", "state.y"} & variables),
              "english_semantics_verified": False}
    answer = solver.check()
    if answer == z3.unsat:
        return {**report, "status": "equivalent"}
    if answer != z3.sat:
        return {**report, "status": "unknown", "reason": solver.reason_unknown()}
    model = solver.model()
    values = {}
    for name, var in reals.items():
        values[name] = float(model.eval(var, model_completion=True).as_fraction())
    abstract = {name: bool(z3.is_true(model.eval(var, model_completion=True))) for name, var in bools.items()}
    witness = _confirm(candidate, reference, scenario, values, domains)
    if witness is None:
        return {**report, "status": "unconfirmed", "abstract_counterexample": {"values": values, "inside": abstract}}
    cand, ref = compile_rule(candidate, scenario), compile_rule(reference, scenario)
    return {**report, "status": "not_equivalent",
            "counterexample": {"values": witness, "candidate": cand.evaluate(witness).value,
                               "reference": ref.evaluate(witness).value}}
