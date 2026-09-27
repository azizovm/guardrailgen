"""RQ1 harness contracts: ablation switches, semantic scoring, corpus hygiene. No network."""
import copy
import io
import json
from pathlib import Path

import pytest

from guardrailgen.compiler import BackendResponse, Compiler, GroqBackend, build_messages
from guardrailgen.compiler.backend import unconstrained_json_payload
from guardrailgen.evaluation.rq1 import CONFIGS, OracleBackend, load_corpus, make_compiler, score
from guardrailgen.schema import Rule

z3 = pytest.importorskip("z3")
from guardrailgen.evaluation.semantic import check_agreement, exclusive_pairs  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
CORPUS, SCENARIO, DOMAINS, LIBRARY = load_corpus(ROOT)
V, W = "command.linear_speed", "command.angular_speed"


def C(var, cmp, val):
    return {"op": "compare", "variable": var, "comparator": cmp, "value": val,
            "unit": {"command.linear_speed": "m/s", "command.angular_speed": "rad/s",
                     "state.x": "m", "state.y": "m"}[var]}


def rule(expr, rid="t"):
    return Rule.from_dict({"schema_version": "1.0", "id": rid, "text": "x", "expression": expr}, SCENARIO)


def ref(rule_id):
    entry = next(r for r in CORPUS["rules"] if r["id"] == rule_id)
    return rule(entry["reference"], rule_id)


def agree(expr, rule_id):
    return check_agreement(rule(expr), ref(rule_id), SCENARIO, DOMAINS)["status"]


def test_corpus_is_consistent_and_disjoint_from_library():
    ids = [r["id"] for r in CORPUS["rules"]]
    assert len(ids) == len(set(ids)) == 50
    library_ids = {e["id"] for e in LIBRARY["examples"]}
    assert not library_ids & set(ids)
    assert all((r["reference"] is None) == (r["expected"] == "refusal") for r in CORPUS["rules"])


def test_regions_are_pairwise_exclusive_under_footprint():
    names = SCENARIO.regions.keys()
    assert len(exclusive_pairs(SCENARIO, names)) == len(names) * (len(names) - 1) // 2


def test_structurally_different_but_equivalent_rules_pass():
    # not(or(in kitchen, in loading)) == and(not kitchen, not loading)
    expr = {"op": "not", "arg": {"op": "or", "args": [{"op": "inside", "region": "kitchen"},
                                                      {"op": "inside", "region": "loading_area"}]}}
    assert agree(expr, "f03-two-keepouts-a") == "equivalent"
    # |v| <= 0.3 written as not(v > 0.3 or v < -0.3)
    expr = {"op": "not", "arg": {"op": "or", "args": [C(V, "gt", 0.3), C(V, "lt", -0.3)]}}
    assert agree(expr, "f04-speed-mag-0-3-a") == "equivalent"


@pytest.mark.parametrize("expr,rule_id", [
    (C(V, "le", 0.3), "f04-speed-mag-0-3-a"),                                    # one-sided magnitude
    ({"op": "and", "args": [C(V, "le", 0.25), C(V, "ge", -0.25)]}, "f05-forward-strict-0-25-a"),
    ({"op": "and", "args": [C(V, "le", 0.18), C(V, "ge", -0.18)]}, "f09-units-cm-a"),  # strictness lost
    ({"op": "and", "args": [C(V, "lt", 18), C(V, "gt", -18)]}, "f09-units-cm-a"),      # unit not converted
    ({"op": "and", "args": [C(V, "le", 0.1), C(V, "ge", -0.1)]}, "f10-school-speed-a"),  # condition dropped
    ({"op": "not", "arg": {"op": "inside", "region": "school_zone"}}, "f10-school-speed-a"),
    ({"op": "not", "arg": {"op": "inside", "region": "kitchen"}}, "f02-dock-keepout-a"),  # wrong region
])
def test_semantic_errors_are_detected_with_concrete_witness(expr, rule_id):
    report = check_agreement(rule(expr), ref(rule_id), SCENARIO, DOMAINS)
    assert report["status"] == "not_equivalent"
    witness = report["counterexample"]
    assert witness["candidate"] != witness["reference"]


def test_position_rectangle_approximation_is_not_proved_equivalent():
    # x/y bounds that imitate the kitchen without the footprint are not the same rule.
    expr = {"op": "not", "arg": {"op": "and", "args": [C("state.x", "ge", -0.8), C("state.x", "le", 0.8),
                                                        C("state.y", "ge", -3.4), C("state.y", "le", -1.6)]}}
    assert agree(expr, "f01-kitchen-keepout-a") in ("not_equivalent", "unconfirmed")


def entry(rule_id):
    return next(r for r in CORPUS["rules"] if r["id"] == rule_id)


def test_scoring_classifies_outcomes():
    for rid in ("f10-school-speed-a", "f17-dwell-a", "f22-no-threshold-a"):
        compiler = make_compiler("full", OracleBackend(entry(rid)), SCENARIO, LIBRARY)
        result = compiler.compile(entry(rid)["text"], rid).to_dict()
        outcome = score(entry(rid), result, SCENARIO, DOMAINS)["outcome"]
        assert outcome == ("correct" if entry(rid)["expected"] == "compiled" else "correct_refusal")


class Scripted:
    def __init__(self, *payloads):
        self.payloads, self.messages = list(payloads), []

    def configuration(self):
        return {"provider": "fixture", "model": "none"}

    def generate(self, messages, schema):
        self.messages.append(copy.deepcopy(messages))
        return BackendResponse(self.payloads.pop(0), {"usage": {"total_tokens": 10}})


def test_wrong_accept_and_refused_in_scope_and_first_attempt_repair():
    rid = "f04-speed-mag-0-3-a"
    wrong = {"status": "compiled", "message": "m", "rule": {"schema_version": "1.0", "id": rid,
             "text": entry(rid)["text"], "expression": C(V, "le", 0.3)}}
    result = make_compiler("full", Scripted(wrong), SCENARIO, LIBRARY).compile(entry(rid)["text"], rid).to_dict()
    assert score(entry(rid), result, SCENARIO, DOMAINS)["outcome"] == "wrong_accept"
    refused = {"status": "clarification", "message": "?", "rule": None}
    result = make_compiler("full", Scripted(refused), SCENARIO, LIBRARY).compile(entry(rid)["text"], rid).to_dict()
    assert score(entry(rid), result, SCENARIO, DOMAINS)["outcome"] == "refused_in_scope"
    # Invalid first attempt (bad unit) repaired into the correct rule.
    bad = copy.deepcopy(wrong)
    bad["rule"]["expression"] = C(V, "le", 0.3) | {"unit": "rad/s"}
    good = copy.deepcopy(wrong)
    good["rule"]["expression"] = entry(rid)["reference"]
    backend = Scripted(bad, good)
    result = make_compiler("full", backend, SCENARIO, LIBRARY).compile(entry(rid)["text"], rid).to_dict()
    scored = score(entry(rid), result, SCENARIO, DOMAINS)
    assert scored["outcome"] == "correct" and scored["repairs"] == 1
    assert not scored["first_attempt_well_formed"] and not scored["first_attempt_correct"]
    # The repair prompt must not contain the reference answer.
    assert json.dumps(entry(rid)["reference"]) not in json.dumps(backend.messages[1])


def test_ablation_switches_change_only_their_component():
    rid = "f10-school-speed-a"
    text = entry(rid)["text"]
    prompts = {}
    for config in CONFIGS:
        backend = Scripted({"status": "unsupported", "message": "m", "rule": None})
        result = make_compiler(config, backend, SCENARIO, LIBRARY).compile(text, rid)
        prompts[config] = (backend.messages[0], result.provenance)
    full_sys, full_user = prompts["full"][0][0]["content"], json.loads(prompts["full"][0][1]["content"])
    assert "Configured schema" in full_sys and full_user["retrieval_examples"]
    assert json.loads(prompts["no_retrieval"][0][1]["content"])["retrieval_examples"] == []
    assert prompts["no_retrieval"][0][0]["content"] == full_sys
    assert "Configured schema" not in prompts["no_schema"][0][0]["content"]
    assert json.loads(prompts["no_schema"][0][1]["content"]) == full_user
    unconstrained = prompts["no_constrained"][0][0]["content"]
    assert unconstrained.startswith(full_sys) and "does not enforce the output format" in unconstrained
    assert prompts["no_retrieval"][1]["retrieval"] == "disabled"
    assert prompts["no_schema"][1]["schema_text_in_prompt"] is False


def test_default_compiler_prompt_is_unchanged_by_new_options():
    scenario = SCENARIO
    examples = []
    assert build_messages("t", "r", scenario, examples) == build_messages(
        "t", "r", scenario, examples, include_schema=True, response_format=None)


def test_unconstrained_groq_sends_no_response_format_and_repairs_parse_errors(monkeypatch):
    bodies = []
    rid = "f07-no-reverse-a"
    good = {"status": "compiled", "message": "m", "rule": {"schema_version": "1.0", "id": rid,
            "text": entry(rid)["text"], "expression": entry(rid)["reference"]}}
    contents = ["Sure! {not json", "```json\n" + json.dumps(good) + "\n```"]

    def transport(request, timeout):
        bodies.append(json.loads(request.data))
        content = contents.pop(0)
        return io.BytesIO(json.dumps({"id": "x", "choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": content}}], "usage": {"total_tokens": 5}}).encode())
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr("urllib.request.urlopen", transport)
    compiler = make_compiler("no_constrained", GroqBackend(strict=False), SCENARIO, LIBRARY)
    result = compiler.compile(entry(rid)["text"], rid)
    assert result.ok and len(bodies) == 2
    assert all("response_format" not in body for body in bodies)
    assert "not a valid JSON object" in result.attempts[0]["errors"][0]
    assert result.provenance["backend"]["strict"] is False


def test_unconstrained_payload_parser():
    assert unconstrained_json_payload('{"a": 1}') == {"a": 1}
    assert unconstrained_json_payload('```json\n{"a": 1}\n```') == {"a": 1}
    assert "_parse_error" in unconstrained_json_payload("no json here")
    assert "_parse_error" in unconstrained_json_payload("[1, 2]")


def test_rate_limited_calls_do_not_consume_budget_and_transient_failures_rerun(tmp_path):
    from guardrailgen.compiler import BackendError
    from guardrailgen.evaluation.rq1 import CountingBackend, latest_records

    class Limited:
        def __init__(self):
            self.n = 0

        def configuration(self):
            return {}

        def generate(self, messages, schema):
            self.n += 1
            if self.n == 1:
                raise BackendError("backend_error", "Hosted generation returned HTTP 429")
            return BackendResponse({"status": "unsupported", "message": "m", "rule": None},
                                   {"usage": {"total_tokens": 7}})

    counting = CountingBackend(Limited(), budget=5)
    with pytest.raises(BackendError):
        counting.generate([], {})
    counting.generate([], {})
    assert counting.calls == 1 and counting.rate_limited == 1 and counting.tokens == 7
    path = tmp_path / "results.jsonl"
    rows = [{"rule_id": "a", "outcome": "failed", "message": "Hosted generation returned HTTP 429"},
            {"rule_id": "b", "outcome": "correct", "message": "ok"}]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    assert [r["rule_id"] for r in latest_records(path)] == ["b"]


def test_openrouter_is_pinned_to_groq_with_strict_schema(monkeypatch):
    from guardrailgen.compiler import OpenRouterBackend
    bodies, requests = [], []
    rid = "f07-no-reverse-a"
    good = {"status": "compiled", "message": "m", "rule": {"schema_version": "1.0", "id": rid,
            "text": entry(rid)["text"], "expression": entry(rid)["reference"]}}

    def transport(request, timeout):
        requests.append(request)
        bodies.append(json.loads(request.data))
        return io.BytesIO(json.dumps({"id": "x", "model": "openai/gpt-oss-120b", "choices": [{
            "finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps(good)}}],
            "usage": {"total_tokens": 5}}).encode())
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr("urllib.request.urlopen", transport)
    result = make_compiler("full", OpenRouterBackend(), SCENARIO, LIBRARY).compile(entry(rid)["text"], rid)
    assert result.ok
    body = bodies[0]
    assert requests[0].full_url == "https://openrouter.ai/api/v1/chat/completions"
    assert requests[0].get_header("Authorization") == "Bearer or-test-key"
    assert body["provider"] == {"order": ["groq"], "allow_fallbacks": False, "require_parameters": True}
    assert body["response_format"]["json_schema"]["strict"] is True
    assert result.provenance["backend"]["provider"] == "openrouter"
    assert "or-test-key" not in json.dumps(result.to_dict())


def test_out_of_credit_rows_are_rerun_not_scored(tmp_path):
    from guardrailgen.evaluation.rq1 import latest_records
    path = tmp_path / "results.jsonl"
    rows = [{"rule_id": "a", "outcome": "failed", "message": "Hosted generation returned HTTP 402"},
            {"rule_id": "b", "outcome": "correct", "message": "ok"}]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    assert [r["rule_id"] for r in latest_records(path)] == ["b"]
