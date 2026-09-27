"""Explicit validation evidence, never a proof of English-rule equivalence."""
import importlib.metadata
import json

from guardrailgen.schema import Verdict, compile_rule


def _atoms(expr):
    if expr["op"] == "and":
        return [atom for child in expr["args"] for atom in _atoms(child)]
    return [expr]


def _contradictions(expr):
    """Detect direct contradictory conjuncts; arbitrary Boolean SAT is deferred."""
    atoms = _atoms(expr)
    seen = {json.dumps(atom, sort_keys=True) for atom in atoms}
    limits = {}
    for atom in atoms:
        if atom["op"] == "not" and json.dumps(atom["arg"], sort_keys=True) in seen:
            return ["Contradictory conjuncts: expression and its negation"]
        if atom["op"] != "compare":
            continue
        bounds = limits.setdefault(atom["variable"], [float("-inf"), False, float("inf"), False])
        value, op = atom["value"], atom["comparator"]
        if op in ("gt", "ge"):
            if value > bounds[0]:
                bounds[0:2] = [value, op == "gt"]
            elif value == bounds[0]:
                bounds[1] |= op == "gt"
        else:
            if value < bounds[2]:
                bounds[2:4] = [value, op == "lt"]
            elif value == bounds[2]:
                bounds[3] |= op == "lt"
        if bounds[0] > bounds[2] or (bounds[0] == bounds[2] and (bounds[1] or bounds[3])):
            return [f"Contradictory bounds on {atom['variable']}"]
    return []


def _signals(expr):
    if expr["op"] == "compare":
        return {expr["variable"].replace(".", "_")}
    if expr["op"] == "inside":
        return {"region_" + expr["region"]}
    if expr["op"] == "not":
        return _signals(expr["arg"])
    return set().union(*(_signals(arg) for arg in expr["args"]))


def _rtamt_spec(monitor):
    import rtamt
    spec = rtamt.StlDiscreteTimeSpecification()
    for name in sorted(_signals(monitor.rule.expression)):
        spec.declare_var(name, "float")
    spec.spec = monitor.stl
    spec.parse()
    return spec


def validate_rule(rule, scenario, *, require_rtamt=False, traces=None,
                  reference=None, domains=None, solver_timeout_ms=1000):
    """Optional independently labeled point traces: {values: {...}, expected: SAFE|UNSAFE}.

    RTAMT robustness zero does not distinguish strict/inclusive boundaries. Exact
    boundary truth therefore comes from the Boolean monitor and supplied labels.
    Positive/negative RTAMT robustness must agree with the Boolean verdict.
    """
    if (reference is None)!=(domains is None):
        raise ValueError('Reference equivalence requires both a reference rule and declared domains')
    monitor = compile_rule(rule, scenario)
    report = {"structure": "passed", "grounding": "passed", "lowering": "passed",
              "consistency": "direct_conjuncts_checked_only", "rtamt": "not_checked",
              "trace_validation": "not_checked", "english_semantics_verified": False,
              "equivalence": "not_checked", "errors": _contradictions(rule.expression)}
    spec = None
    try:
        spec = _rtamt_spec(monitor)
        report["rtamt"] = {"status": "passed", "version": importlib.metadata.version("rtamt"),
                           "scope": "instantaneous predicate syntax; enforce at every step"}
    except ImportError as exc:
        report["rtamt"] = {"status": "unavailable", "reason": str(exc)}
        if require_rtamt:
            report["errors"].append("RTAMT cannot be imported; use Python 3.10 with the validation extra")
    except Exception as exc:
        report["rtamt"] = "failed"
        report["errors"].append(f"RTAMT parse failed: {exc}")
    if traces is not None:
        if not isinstance(traces, list) or not traces:
            raise ValueError("Trace bank must be a nonempty list of independently labeled states")
        results = []
        for index, trace in enumerate(traces):
            if not isinstance(trace, dict) or set(trace) != {"values", "expected"} or not isinstance(trace["values"], dict):
                raise ValueError("Each trace case requires values and expected fields")
            expected = Verdict(trace["expected"])
            verdict = monitor.evaluate(trace["values"])
            entry = {"index": index, "expected": expected.value, "actual": verdict.value, "passed": verdict == expected}
            if not entry["passed"]:
                report["errors"].append(f"Trace {index}: expected {expected.value}, got {verdict.value}")
            if spec is not None and verdict != Verdict.UNKNOWN:
                signals = monitor.to_stl_signals(trace["values"])
                needed = _signals(rule.expression)
                if needed.issubset(signals):
                    try:
                        sample_spec = _rtamt_spec(monitor)
                        # Instantaneous invariants require no future buffering.
                        # The online API also avoids RTAMT 0.3.5's one-sample
                        # offline-duration bug without fabricating trace samples.
                        robustness = sample_spec.update(0, [(k, signals[k]) for k in sorted(needed)])
                        entry["rtamt_robustness"] = float(robustness)
                        if (robustness > 0 and verdict != Verdict.SAFE) or (robustness < 0 and verdict != Verdict.UNSAFE):
                            report["errors"].append(f"Trace {index}: RTAMT and Boolean monitor disagree")
                            entry["passed"] = False
                    except Exception as exc:
                        report["errors"].append(f"Trace {index}: RTAMT evaluation failed: {exc}")
                        entry["passed"] = False
            results.append(entry)
        report["trace_validation"] = {"cases": results, "passed": all(r["passed"] for r in results),
                                      "scope": "finite supplied reference cases; not a proof"}
    if reference is not None:
        from .equivalence import check_equivalence
        report['equivalence']=check_equivalence(rule,reference,scenario,domains,timeout_ms=solver_timeout_ms)
        if report['equivalence']['status']!='equivalent':
            report['errors'].append('Reference equivalence: '+report['equivalence']['status'])
    return report
