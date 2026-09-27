"""RQ1 harness: compile the rule corpus under the full compiler and ablations.

    python -m guardrailgen.evaluation.rq1 run --config full --max-calls 200
    python -m guardrailgen.evaluation.rq1 run --config full --dry-run   # no API
    python -m guardrailgen.evaluation.rq1 summarize runs/rq1

Configurations (each changes exactly one technique; validator and accepted
rule language stay constant):
  full            schema text + retrieval + strict JSON-schema decoding
  no_retrieval    no retrieved examples
  no_schema       configured schema removed from the prompt
  no_constrained  no decoder enforcement; response schema described in the prompt

The validator used during compilation is structural + RTAMT (when available) +
direct contradiction checks only. Reference rules are NEVER used during
compilation, so repairs cannot see the answer. Scoring happens afterwards.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import statistics
import sys
import time

from guardrailgen.compiler import BackendError, Compiler, GroqBackend, OpenRouterBackend
from guardrailgen.compiler.backend import BackendResponse
from guardrailgen.schema import Rule, RuleValidationError, Scenario
from guardrailgen.validation import validate_rule

from .semantic import check_agreement

CONFIGS = {
    "full": dict(retrieval=True, schema_text=True, strict=True),
    "no_retrieval": dict(retrieval=False, schema_text=True, strict=True),
    "no_schema": dict(retrieval=True, schema_text=False, strict=True),
    "no_constrained": dict(retrieval=True, schema_text=True, strict=False),
}
REFUSALS = ("clarification", "unsupported")
TRANSIENT = ("HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504", "could not connect", "HTTP 402")
# HTTP 402 means the provider account has no credit left: stop at once, never retry.
STOP_AT_ONCE = ("HTTP 402",)


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_corpus(root):
    root = Path(root)
    corpus = load_json(root / "data/rq1/corpus.json")
    scenario = Scenario.from_dict(load_json(root / corpus["scenario"]))
    domains = load_json(root / corpus["domains"])
    library = load_json(root / corpus["retrieval_library"])
    lib_texts = {e["text"].strip().lower() for e in library["examples"]}
    for rule in corpus["rules"]:
        if rule["text"].strip().lower() in lib_texts:
            raise ValueError(f"Test rule {rule['id']} also appears in the retrieval library")
        if rule["reference"] is not None:
            Rule.from_dict(_reference_rule(rule), scenario)  # references must be valid
    return corpus, scenario, domains, library


def _reference_rule(rule):
    return {"schema_version": "1.0", "id": rule["id"], "text": rule["text"], "expression": rule["reference"]}


class OracleBackend:
    """Dry-run backend: answers with the reference; consumes no API calls."""

    def __init__(self, rule):
        self.rule = rule

    def configuration(self):
        return {"provider": "dry-run-oracle", "model": "none", "strict": True}

    def generate(self, messages, response_schema):
        if self.rule["reference"] is None:
            status = "clarification" if self.rule["expected_refusal"] == "clarification" else "unsupported"
            return BackendResponse({"status": status, "message": "dry run", "rule": None}, {"usage": None})
        return BackendResponse({"status": "compiled", "message": "dry run",
                                "rule": _reference_rule(self.rule)}, {"usage": None})


class CountingBackend:
    """Wraps a provider backend, counts requests, enforces the call cap."""

    def __init__(self, inner, budget):
        self.inner, self.budget, self.calls, self.tokens = inner, budget, 0, 0
        self.rate_limited = 0  # HTTP 429 rejections: no tokens used, not counted as calls

    def configuration(self):
        return self.inner.configuration()

    def generate(self, messages, response_schema):
        if self.calls >= self.budget:
            raise BackendError("budget_exhausted", "Authorized call budget exhausted")
        try:
            response = self.inner.generate(messages, response_schema)
        except BackendError as exc:
            if "HTTP 429" in str(exc):
                self.rate_limited += 1
            else:
                self.calls += 1
            raise
        self.calls += 1
        usage = (response.metadata or {}).get("usage") or {}
        self.tokens += int(usage.get("total_tokens") or 0)
        return response


def _candidate_rule(candidate, scenario):
    if not isinstance(candidate, dict) or candidate.get("status") != "compiled":
        return None
    try:
        return Rule.from_dict(candidate.get("rule"), scenario)
    except (RuleValidationError, ValueError, TypeError, KeyError, RecursionError):
        return None


def score(rule, result, scenario, domains):
    """Classify one compilation result against the corpus reference."""
    status = result["status"]
    attempts = result.get("attempts") or []
    first = attempts[0] if attempts else {}
    first_candidate = first.get("candidate")
    first_status = first.get("status")
    entry = {"final_status": status, "attempts": len(attempts), "repairs": max(0, len(attempts) - 1),
             "first_attempt_status": first_status,
             "first_attempt_well_formed": first_status in ("compiled",) + REFUSALS,
             "semantic": None, "first_attempt_semantic": None}
    expected = rule["expected"]

    def agree(candidate_rule):
        if candidate_rule is None:
            return None
        return check_agreement(candidate_rule, Rule.from_dict(_reference_rule(rule), scenario), scenario, domains)

    if expected == "compiled":
        if status == "compiled":
            final_rule = Rule.from_dict(result["artifact"]["rule"], scenario)
            entry["semantic"] = agree(final_rule)
            verdict = entry["semantic"]["status"]
            entry["outcome"] = {"equivalent": "correct", "not_equivalent": "wrong_accept"}.get(verdict, "unverified")
        elif status in REFUSALS:
            entry["outcome"] = "refused_in_scope"
        else:
            entry["outcome"] = "failed"
        if first_status == "compiled":
            first_rule = _candidate_rule(first_candidate, scenario)
            entry["first_attempt_semantic"] = agree(first_rule) if first_rule else None
        entry["first_attempt_correct"] = bool(entry["first_attempt_semantic"]) and \
            entry["first_attempt_semantic"]["status"] == "equivalent"
    else:
        if status in REFUSALS:
            entry["outcome"] = "correct_refusal"
            wanted = rule["expected_refusal"]
            entry["refusal_status_match"] = wanted == "either" or wanted == status
        elif status == "compiled":
            entry["outcome"] = "wrong_accept"
        else:
            entry["outcome"] = "failed"
        entry["first_attempt_correct"] = first_status in REFUSALS
    return entry


def make_compiler(config_name, backend, scenario, library):
    config = CONFIGS[config_name]
    return Compiler(backend, scenario, max_repairs=2,
                    validator=lambda rule, cfg: validate_rule(rule, cfg),
                    examples=library["examples"] if config["retrieval"] else (),
                    example_set_version=library["version"],
                    include_schema_text=config["schema_text"],
                    describe_response_schema=not config["strict"])


def run(args):
    root = Path(args.root)
    corpus, scenario, domains, library = load_corpus(root)
    rules = corpus["rules"]
    if args.rules:
        wanted = set(args.rules.split(","))
        rules = [r for r in rules if r["id"] in wanted or r["family"] in wanted]
    if args.limit:
        rules = rules[:args.limit]
    out_dir = Path(args.out) / args.config
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / ("dry_run.jsonl" if args.dry_run else "results.jsonl")
    done = set()
    if results_path.exists():
        for line in results_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if not _is_transient_failure(row):
                    done.add(row["rule_id"])
    strict = CONFIGS[args.config]["strict"]
    provider = None
    if not args.dry_run:
        backend_class = OpenRouterBackend if args.provider == "openrouter" else GroqBackend
        if not os.environ.get(backend_class.key_env, "").strip():
            raise SystemExit(backend_class.key_env + " is not set (use --env-file)")
        provider = CountingBackend(backend_class(args.model, timeout=args.timeout, strict=strict,
                                                 max_output_tokens=args.max_completion_tokens), args.max_calls)
    started = time.time()
    for rule in rules:
        if rule["id"] in done:
            continue
        if provider is not None and provider.calls + 3 > provider.budget:
            print(f"Stopping: fewer than 3 calls left in the authorized budget ({provider.calls}/{provider.budget}).")
            break
        backend = OracleBackend(rule) if args.dry_run else provider
        compiler = make_compiler(args.config, backend, scenario, library)
        retries = 0
        while True:
            calls_before = provider.calls if provider else 0
            t0 = time.time()
            result = compiler.compile(rule["text"], rule["id"]).to_dict()
            latency = time.time() - t0
            transient = result["status"] in ("backend_error", "timeout") and \
                any(marker in result["message"] for marker in TRANSIENT + ("timed out",))
            if transient and (retries >= args.retries or any(m in result["message"] for m in STOP_AT_ONCE)):
                break
            if transient:
                retries += 1
                wait = min(300, args.backoff * 2 ** (retries - 1))
                print(f"  {rule['id']}: transient '{result['message']}', retry {retries} in {wait}s")
                time.sleep(wait)
                continue
            break
        if transient:
            print(f"Provider said: {result['message']}")
            if any(m in result["message"] for m in STOP_AT_ONCE):
                print("Stopping: the provider account is out of credit (HTTP 402). Top up and rerun to resume.")
                break
            print(f"Stopping: {rule['id']} still rate-limited after {retries} retries. "
                  "Nothing was recorded for it; rerun the same command later to resume.")
            break
        record = {"config": args.config, "rule_id": rule["id"], "family": rule["family"],
                  "category": rule["category"], "expected": rule["expected"],
                  "expected_refusal": rule["expected_refusal"], "text": rule["text"],
                  "latency_s": round(latency, 3), "transient_retries": retries,
                  "calls": (provider.calls - calls_before) if provider else 0,
                  "message": result["message"],
                  "provenance": result["provenance"],
                  "compiled_rule": (result["artifact"] or {}).get("rule") if result["artifact"] else None,
                  "attempt_log": [{k: a.get(k) for k in ("attempt", "status", "errors", "candidate")}
                                  for a in result["attempts"]],
                  "usage": [((a.get("metadata") or {}).get("usage")) for a in result["attempts"]]}
        record.update(score(rule, result, scenario, domains))
        with results_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"{args.config:15s} {rule['id']:32s} {record['final_status']:18s} {record['outcome']}"
              + (f"  calls={provider.calls}" if provider else ""))
        if args.sleep and not args.dry_run:
            time.sleep(args.sleep)
    meta = {"config": args.config, "model": args.model, "provider": args.provider, "dry_run": args.dry_run,
            "calls_used_this_invocation": provider.calls if provider else 0,
            "rate_limited_rejections": provider.rate_limited if provider else 0,
            "tokens_this_invocation": provider.tokens if provider else 0,
            "elapsed_s": round(time.time() - started, 1), "corpus_version": corpus["corpus_version"],
            "library_version": library["version"]}
    with (out_dir / "invocations.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(meta) + "\n")
    print(json.dumps(meta))


def load_groq_env(path):
    """Load only the Groq variables; never print or persist their values."""
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        if key in ("GROQ_API_KEY", "GROQ_MODEL", "OPENROUTER_API_KEY"):
            os.environ[key] = value.strip().strip('"').strip("'")


def _is_transient_failure(row):
    return row.get("outcome") == "failed" and any(
        marker in (row.get("message") or "") for marker in TRANSIENT + ("timed out",))


def latest_records(path):
    """Last record per rule, ignoring rate-limit failures that will be rerun."""
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if not _is_transient_failure(row):
                rows[row["rule_id"]] = row
    return list(rows.values())


def _rate(num, den):
    return None if den == 0 else round(num / den, 4)


def summarize_records(records):
    in_scope = [r for r in records if r["expected"] == "compiled"]
    refusal = [r for r in records if r["expected"] == "refusal"]
    accepted = [r for r in in_scope if r["final_status"] == "compiled"]
    count = lambda rows, outcome: sum(1 for r in rows if r["outcome"] == outcome)
    latencies = [r["latency_s"] for r in records]
    tokens = sum(int((u or {}).get("total_tokens") or 0) for r in records for u in r.get("usage", []))
    return {
        "rules": len(records), "in_scope": len(in_scope), "refusal_expected": len(refusal),
        "first_attempt_well_formed": _rate(sum(r["first_attempt_well_formed"] for r in records), len(records)),
        "final_well_formed": _rate(sum(r["final_status"] in ("compiled",) + REFUSALS for r in records), len(records)),
        "semantic_accuracy": _rate(count(in_scope, "correct"), len(in_scope)),
        "first_attempt_semantic_accuracy": _rate(sum(bool(r.get("first_attempt_correct")) for r in in_scope), len(in_scope)),
        "accuracy_among_accepted": _rate(count(in_scope, "correct"), len(accepted)),
        "acceptance_coverage": _rate(len(accepted), len(in_scope)),
        "wrong_accept_in_scope": count(in_scope, "wrong_accept"),
        "unverified_in_scope": count(in_scope, "unverified"),
        "refused_in_scope": count(in_scope, "refused_in_scope"),
        "failed": count(records, "failed"),
        "refusal_accuracy": _rate(count(refusal, "correct_refusal"), len(refusal)),
        "refusal_status_match": _rate(sum(bool(r.get("refusal_status_match")) for r in refusal), len(refusal)),
        "wrong_accept_of_refusal": count(refusal, "wrong_accept"),
        "rules_needing_repair": sum(1 for r in records if r["repairs"] > 0),
        "mean_repairs": round(statistics.mean(r["repairs"] for r in records), 3) if records else None,
        "provider_calls": sum(r["calls"] for r in records),
        "total_tokens": tokens,
        "median_latency_s": round(statistics.median(latencies), 2) if latencies else None,
    }


def summarize(args):
    base = Path(args.out)
    summary = {}
    for config in CONFIGS:
        path = base / config / "results.jsonl"
        if not path.exists():
            continue
        records = latest_records(path)
        summary[config] = {"overall": summarize_records(records),
                           "by_category": {cat: summarize_records([r for r in records if r["category"] == cat])
                                           for cat in sorted({r["category"] for r in records})}}
    (base / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    keys = ["rules", "first_attempt_well_formed", "final_well_formed", "semantic_accuracy",
            "first_attempt_semantic_accuracy", "accuracy_among_accepted", "acceptance_coverage",
            "wrong_accept_in_scope", "refusal_accuracy", "wrong_accept_of_refusal",
            "rules_needing_repair", "provider_calls", "total_tokens", "median_latency_s"]
    lines = ["| metric | " + " | ".join(summary) + " |", "|---|" + "---|" * len(summary)]
    for key in keys:
        lines.append(f"| {key} | " + " | ".join(str(summary[c]["overall"][key]) for c in summary) + " |")
    table = "\n".join(lines)
    (base / "summary.md").write_text(table + "\n", encoding="utf-8")
    print(table)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run")
    run_p.add_argument("--config", choices=sorted(CONFIGS), required=True)
    run_p.add_argument("--root", default=".")
    run_p.add_argument("--out", default="runs/rq1")
    run_p.add_argument("--model", default=os.environ.get("GROQ_MODEL") or GroqBackend.default_model)
    run_p.add_argument("--max-calls", type=int, default=0, help="Authorized provider-call cap for this invocation")
    run_p.add_argument("--rules", help="Comma-separated rule ids or family names")
    run_p.add_argument("--limit", type=int)
    run_p.add_argument("--sleep", type=float, default=25.0, help="Seconds between rules (Groq rate limits)")
    run_p.add_argument("--retries", type=int, default=6)
    run_p.add_argument("--backoff", type=float, default=30.0)
    run_p.add_argument("--timeout", type=float, default=60.0)
    run_p.add_argument("--provider", choices=("groq", "openrouter"), default="openrouter",
                       help="openrouter = same gpt-oss-120b pinned to OpenRouter's Groq route")
    run_p.add_argument("--max-completion-tokens", type=int, default=2500,
                       help="Reserved answer size; prompt + this must fit Groq's per-minute token limit")
    run_p.add_argument("--dry-run", action="store_true", help="Oracle backend, no API calls")
    run_p.add_argument("--env-file", help="Read only GROQ_API_KEY/GROQ_MODEL from this file")
    sum_p = sub.add_parser("summarize")
    sum_p.add_argument("out", nargs="?", default="runs/rq1")
    args = parser.parse_args(argv)
    if args.command == "run":
        if args.env_file:
            load_groq_env(args.env_file)
            if args.model == GroqBackend.default_model and os.environ.get("GROQ_MODEL"):
                args.model = os.environ["GROQ_MODEL"]
        if args.provider == "openrouter" and "--sleep" not in (argv or sys.argv):
            args.sleep = 1.0
        if not args.dry_run and args.max_calls <= 0:
            raise SystemExit("Set --max-calls to the authorized number of provider calls")
        run(args)
    else:
        summarize(args)


if __name__ == "__main__":
    sys.exit(main())
