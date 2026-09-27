"""Compile, inspect, and exercise monitors without ROS."""
import argparse
import json
import os
from pathlib import Path
import sys

from guardrailgen.artifacts import build_artifact, load_monitor, read_json, save_artifact, write_json_atomic
from guardrailgen.compiler import Compiler, GroqBackend, OpenAIBackend
from guardrailgen.schema import Rule, Scenario, Verdict, compile_rule
from guardrailgen.validation import validate_rule


def _print(data):
    print(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False))


def parser():
    root = argparse.ArgumentParser(description="GuardrailGen invariant compiler (development milestone)")
    commands = root.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Validate and save a hand-authored structured rule")
    validate.add_argument("rule")
    validate.add_argument("--scenario", required=True)
    validate.add_argument("--traces", help="Independent labeled trace cases for this rule")
    validate.add_argument("--require-rtamt", action="store_true")
    validate.add_argument("--output-dir", default="artifacts")
    compile_cmd = commands.add_parser("compile", help="Compile English using a hosted structured-output model")
    compile_cmd.add_argument("text")
    compile_cmd.add_argument("--id", default="operator-rule")
    compile_cmd.add_argument("--scenario", required=True)
    compile_cmd.add_argument("--provider", choices=("groq", "openai"), default="groq",
                             help="Hosted provider (default: groq; no automatic fallback)")
    compile_cmd.add_argument("--model", help="Model ID (Groq default: openai/gpt-oss-120b)")
    compile_cmd.add_argument("--require-rtamt", action="store_true")
    compile_cmd.add_argument("--traces", help="Independent labels for this operator rule, never retrieval examples")
    compile_cmd.add_argument("--output-dir", default="artifacts")
    compile_cmd.add_argument("--report", help="Write the full result, including failed attempts")
    for command in (validate,compile_cmd):
        command.add_argument('--reference',help='Independent structured reference rule for required numeric/Boolean equivalence')
        command.add_argument('--domains',help='Explicit variable domains JSON, with min/max/unit for each variable')
        command.add_argument('--solver-timeout-ms',type=int,default=1000)
    check = commands.add_parser("check", help="Check a saved artifact against named state/input values")
    check.add_argument("artifact")
    check.add_argument("values", help="JSON file containing fully qualified signal names and numeric values")
    commands.add_parser("demo", help="Run an offline, hand-authored invariant demonstration")
    return root


def _demo():
    scenario = Scenario.from_dict({"schema_version": "1.0", "frame": "odom", "footprint_radius": 0.12,
        "regions": {"loading_area": {"kind": "rectangle", "xmin": 1, "xmax": 2, "ymin": -0.5, "ymax": 0.5}},
        "supported_variables": ["state.x", "state.y", "command.linear_speed"]})
    rule = Rule.from_dict({"schema_version": "1.0", "id": "demo", "text": "Avoid loading area and command at most 0.2 m/s in either direction.",
        "expression": {"op": "and", "args": [
            {"op": "not", "arg": {"op": "inside", "region": "loading_area"}},
            {"op": "compare", "variable": "command.linear_speed", "comparator": "le", "value": 0.2, "unit": "m/s"},
            {"op": "compare", "variable": "command.linear_speed", "comparator": "ge", "value": -0.2, "unit": "m/s"}]}}, scenario)
    mon = compile_rule(rule, scenario)
    cases = [
        ("clear and within limit", {"state.x": (0, 0.1), "state.y": (0, 0.1), "command.linear_speed": (0.1, 0.1)}, Verdict.SAFE),
        ("command above limit", {"state.x": (0, 0.1), "state.y": (0, 0.1), "command.linear_speed": (0.3, 0.3)}, Verdict.UNSAFE),
        ("possible footprint overlap", {"state.x": (0.8, 1.0), "state.y": (0, 0.1), "command.linear_speed": (0.1, 0.1)}, Verdict.UNKNOWN),
    ]
    results = [{"case": label, "verdict": mon.check_bounds(bounds).value, "expected": expected.value}
               for label, bounds, expected in cases]
    _print({"source": "hand_authored_demo_no_language_model", "formal_enforcement": False,
            "stl": mon.stl, "validation": validate_rule(rule, scenario), "cases": results})
    return 0 if all(r["verdict"] == r["expected"] for r in results) else 1


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "demo":
            return _demo()
        if args.command == "check":
            mon = load_monitor(args.artifact)
            values = read_json(args.values)
            if not isinstance(values, dict):
                raise ValueError("Signal values must be a JSON object")
            verdict = mon.evaluate(values)
            _print({"rule_id": mon.name, "verdict": verdict.value,
                    "permit": verdict == Verdict.SAFE, "scope": "supplied point values only"})
            return 0 if verdict == Verdict.SAFE else 2
        scenario = Scenario.from_dict(read_json(args.scenario))
        traces = read_json(args.traces) if args.traces else None
        if bool(args.reference)!=bool(args.domains):
            raise ValueError('--reference and --domains must be supplied together')
        if not 1<=args.solver_timeout_ms<=60000:
            raise ValueError('--solver-timeout-ms must be from 1 to 60000')
        reference=Rule.from_dict(read_json(args.reference),scenario) if args.reference else None
        domains=read_json(args.domains) if args.domains else None
        if domains is not None:
            from guardrailgen.validation.equivalence import validate_domains
            validate_domains(domains,scenario)
        validation_options=dict(require_rtamt=args.require_rtamt,traces=traces,
            reference=reference,domains=domains,solver_timeout_ms=args.solver_timeout_ms)
        if args.command == "validate":
            rule = Rule.from_dict(read_json(args.rule), scenario)
            report = validate_rule(rule, scenario, **validation_options)
            if report["errors"]:
                _print({"status": "validation_failed", "validation": report})
                return 2
            path = save_artifact(build_artifact(rule, scenario, report), args.output_dir)
            _print({"status": "validated", "artifact": str(path.resolve()), "validation": report})
            return 0
        if reference is not None:
            from guardrailgen.validation.equivalence import check_equivalence
            preflight=check_equivalence(reference,reference,scenario,domains,timeout_ms=args.solver_timeout_ms)
            if preflight['status']!='equivalent':
                _print({'status':'validation_failed','validation':{'equivalence':preflight,
                    'errors':['Requested reference check cannot run; no model request sent']}})
                return 2
        if args.provider == "groq":
            model = args.model or os.environ.get("GROQ_MODEL") or GroqBackend.default_model
            backend = GroqBackend(model)
        else:
            model = args.model or os.environ.get("OPENAI_MODEL")
            if not model:
                raise ValueError("Choose an OpenAI structured-output model with --model or OPENAI_MODEL")
            backend = OpenAIBackend(model)
        result = Compiler(backend, scenario, validator=lambda rule, config: validate_rule(
            rule, config, **validation_options)).compile(args.text, args.id)
        output = result.to_dict()
        if result.ok:
            output["artifact_path"] = str(save_artifact(result.artifact, args.output_dir).resolve())
        if args.report:
            write_json_atomic(args.report, output)
        _print(output)
        return 0 if result.ok else 2
    except (ValueError, OSError, KeyError, TypeError) as exc:
        _print({"status": "error", "message": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
