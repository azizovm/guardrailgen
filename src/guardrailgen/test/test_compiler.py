"""Offline contract tests. Fixtures are not measurements of NL translation accuracy."""

import copy
import io
import json
import socket
import urllib.error

import pytest

from guardrailgen.compiler import (BackendError, BackendResponse, Compiler,
                                   OpenAIBackend, response_schema, retrieve_examples)
from guardrailgen.compiler.core import UNITS
from guardrailgen.compiler.backend import strict_json_loads
from guardrailgen.schema import Scenario, Verdict, Rule, compile_rule


TEXT = "Keep commanded linear speed at most 0.2 m/s in either direction."


@pytest.fixture
def scenario():
    return Scenario.from_dict({
        "schema_version": "1.0", "frame": "map", "footprint_radius": 0.1,
        "regions": {"school_zone": {"kind": "rectangle", "xmin": 1, "xmax": 2,
                                    "ymin": -1, "ymax": 1},
                    "loading_area": {"kind": "circle", "cx": 4, "cy": 1, "radius": 0.5}},
        "supported_variables": ["state.x", "state.y", "state.heading",
                                "command.linear_speed", "command.angular_speed", "command.duration"],
    })


def candidate(text=TEXT, rule_id="operator-rule"):
    return {"status": "compiled", "message": "The signed command is bounded from -0.2 to 0.2 m/s inclusive.",
            "rule": {"schema_version": "1.0", "id": rule_id, "text": text,
                     "expression": {"op": "and", "args": [
                         {"op": "compare", "variable": "command.linear_speed", "comparator": "le", "value": 0.2, "unit": "m/s"},
                         {"op": "compare", "variable": "command.linear_speed", "comparator": "ge", "value": -0.2, "unit": "m/s"}]}}}


class FakeBackend:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def configuration(self):
        return {"provider": "offline-test-fixture", "model": "none",
                "structured_output": "mocked; not a live generation test"}

    def generate(self, messages, schema):
        self.calls.append((messages, schema))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return BackendResponse(copy.deepcopy(result), {"response_id": "fixture-" + str(len(self.calls))})


def test_compile_builds_reproducible_inspectable_artifact(scenario):
    backend = FakeBackend(candidate())
    result = Compiler(backend, scenario).compile(TEXT)
    assert result.ok
    serialized = json.loads(json.dumps(result.to_dict(), allow_nan=False))
    assert serialized["artifact"]["validation"]["english_semantics_verified"] is False
    assert serialized["artifact"]["validation"]["rtamt"] == "not_checked"
    assert serialized["artifact"]["compilation_attempts"][0]["metadata"]["response_id"] == "fixture-1"
    assert len(serialized["provenance"]["retrieved_ids"]) == 3
    assert "commanded" in backend.calls[0][0][1]["content"]
    assert "state.linear_speed" not in backend.calls[0][0][0]["content"].split("Configured schema:")[1]
    monitor = compile_rule(Rule.from_dict(result.artifact["rule"], scenario), scenario)
    # Independent intended meaning includes reverse speed and inclusive edges.
    for value, expected in [(-0.3, Verdict.UNSAFE), (-0.2, Verdict.SAFE),
                            (0.0, Verdict.SAFE), (0.2, Verdict.SAFE), (0.3, Verdict.UNSAFE)]:
        assert monitor.evaluate({"command.linear_speed": value}) == expected
    repeated = Compiler(FakeBackend(candidate()), scenario).compile(TEXT)
    assert repeated.to_dict() == result.to_dict()


def test_retrieval_is_stable_and_excludes_unavailable_regions(scenario):
    raw = scenario.to_dict()
    raw["regions"] = {}
    subset = Scenario.from_dict(raw)
    retrieved = retrieve_examples("Never command reverse motion in school_zone.", subset)
    assert retrieved == retrieve_examples("Never command reverse motion in school_zone.", subset)
    assert len(retrieved) == 3
    assert not any("school_zone" in item["text"] or "loading_area" in item["text"] for item in retrieved)
    assert retrieve_examples(TEXT, scenario)[0]["id"] == "command-speed-magnitude"


def test_grammar_only_exposes_grounded_variables_and_units(scenario):
    schema = response_schema(scenario, TEXT, "operator-rule")
    comparisons = [branch for branch in schema["$defs"]["expression"]["anyOf"]
                   if branch["properties"]["op"]["enum"] == ["compare"]]
    allowed = {v for branch in comparisons for v in branch["properties"]["variable"]["enum"]}
    assert allowed == set(scenario.supported_variables)
    assert "state.linear_speed" not in allowed
    # A single compare branch: hosted validators reject several anyOf branches
    # sharing the "compare" discriminator. Units stay confined to the grounded
    # set; the exact variable-to-unit pairing is enforced by Rule.from_dict and
    # covered by test_invalid_unit_repaired_with_concrete_error.
    assert len(comparisons) == 1
    for branch in comparisons:
        assert branch["additionalProperties"] is False
        assert set(branch["required"]) == set(branch["properties"])
        assert set(branch["properties"]["unit"]["enum"]) == {
            UNITS[v] for v in scenario.supported_variables}
    assert schema["type"] == "object" and "anyOf" not in schema
    assert schema["$defs"]["rule"]["properties"]["text"]["enum"] == [TEXT]


def test_grammar_omits_regions_without_position_signals(scenario):
    raw = scenario.to_dict()
    raw["supported_variables"] = ["command.linear_speed"]
    restricted = Scenario.from_dict(raw)
    schema = response_schema(restricted, TEXT, "operator-rule")
    assert not any(branch["properties"]["op"]["enum"] == ["inside"]
                   for branch in schema["$defs"]["expression"]["anyOf"])


def test_invalid_unit_repaired_with_concrete_error(scenario):
    invalid = candidate()
    invalid["rule"]["expression"]["args"][0]["unit"] = "km/h"
    backend = FakeBackend(invalid, candidate())
    result = Compiler(backend, scenario).compile(TEXT)
    assert result.ok and len(backend.calls) == 2
    assert result.attempts[0]["status"] == "validation_failed"
    feedback = json.loads(backend.calls[1][0][-1]["content"])
    assert "requires unit m/s" in feedback["validation_errors"][0]


@pytest.mark.parametrize("mutation", ["unknown_variable", "unknown_region", "temporal", "modified_text", "extra_field"])
def test_repair_limit_fails_without_artifact(scenario, mutation):
    invalid = candidate()
    if mutation == "unknown_variable":
        invalid["rule"]["expression"]["args"][0]["variable"] = "state.gear"
    elif mutation == "unknown_region":
        invalid["rule"]["expression"] = {"op": "inside", "region": "invented_zone"}
    elif mutation == "temporal":
        invalid["rule"]["expression"] = {"op": "eventually", "arg": {"op": "inside", "region": "school_zone"}}
    elif mutation == "modified_text":
        invalid["rule"]["text"] = "A different instruction"
    else:
        invalid["rule"]["python"] = "raise RuntimeError('must not execute')"
    backend = FakeBackend(invalid, invalid, invalid)
    result = Compiler(backend, scenario).compile(TEXT)
    assert result.status == "validation_failed" and not result.ok
    assert result.artifact is None and len(backend.calls) == 3


@pytest.mark.parametrize("status", ["clarification", "unsupported"])
def test_model_declared_failure_is_explicit(scenario, status):
    backend = FakeBackend({"status": status, "message": "Actual velocity is unavailable in this scenario.", "rule": None})
    result = Compiler(backend, scenario).compile("Keep actual speed below 0.2 m/s.")
    assert result.status == status and result.artifact is None
    assert len(backend.calls) == 1


@pytest.mark.parametrize("status", ["refusal", "timeout", "incomplete", "backend_error"])
def test_transport_failures_are_not_repaired(scenario, status):
    backend = FakeBackend(BackendError(status, "Explicit failure"))
    result = Compiler(backend, scenario).compile(TEXT)
    assert result.status == status and result.artifact is None
    assert len(backend.calls) == 1


def test_trace_validator_counterexample_enters_repair_feedback(scenario):
    calls = []

    def validator(rule, context):
        calls.append(rule)
        if len(calls) == 1:
            return {"errors": ["Violation on independently labeled reverse trace"],
                    "counterexample": {"command.linear_speed": -0.3}}
        return {"errors": [], "trace_cases_passed": 5}

    backend = FakeBackend(candidate(), candidate())
    result = Compiler(backend, scenario, validator=validator).compile(TEXT)
    assert result.ok and len(backend.calls) == 2
    assert "counterexample" in backend.calls[1][0][-1]["content"]
    assert result.artifact["validation"]["additional_validation"]["trace_cases_passed"] == 5
    assert not result.artifact["validation"]["english_semantics_verified"]


@pytest.mark.parametrize("repairs", [-1, 3, True, 1.2])
def test_repair_budget_is_bounded(scenario, repairs):
    with pytest.raises(ValueError):
        Compiler(FakeBackend(), scenario, max_repairs=repairs)


@pytest.mark.parametrize("text,rule_id", [("", "r"), ("x" * 8001, "r"), (TEXT, "with spaces")])
def test_invalid_input_never_makes_network_request(scenario, text, rule_id):
    backend = FakeBackend()
    with pytest.raises(ValueError):
        Compiler(backend, scenario).compile(text, rule_id)
    assert backend.calls == []


def api_response(content=None, **overrides):
    response = {"status": "completed", "id": "response-test", "model": "model-test",
                "usage": {"input_tokens": 100, "output_tokens": 30},
                "output": [{"type": "message", "status": "completed", "content": content or [
                    {"type": "output_text", "text": json.dumps(candidate())}]}]}
    response.update(overrides)
    return response


def test_openai_transport_sends_real_strict_schema(monkeypatch, scenario):
    recorded = []

    def fake_urlopen(request, timeout):
        recorded.append((request, timeout))
        return io.BytesIO(json.dumps(api_response()).encode("utf-8"))

    monkeypatch.setenv("OPENAI_API_KEY", "test-key-never-transmitted")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = Compiler(OpenAIBackend("model-test", timeout=7), scenario).compile(TEXT)
    assert result.ok
    request, timeout = recorded[0]
    payload = json.loads(request.data)
    assert request.full_url == "https://api.openai.com/v1/responses"
    assert payload["text"]["format"]["type"] == "json_schema"
    assert payload["text"]["format"]["strict"] is True
    assert payload["text"]["format"]["schema"] == response_schema(scenario, TEXT, "operator-rule")
    assert payload["store"] is False and timeout == 7
    assert "test-key-never-transmitted" not in json.dumps(result.to_dict())


@pytest.mark.parametrize("response,status", [
    (api_response(status="incomplete", incomplete_details={"reason": "max_output_tokens"}), "incomplete"),
    (api_response(content=[{"type": "refusal", "refusal": "Refused"}]), "refusal"),
    (api_response(status="failed"), "backend_error"),
    (api_response(content=[{"type": "output_text", "text": "{unfinished"}]), "backend_error"),
    (api_response(output=[]), "backend_error"),
])
def test_openai_response_failure_mapping(response, status):
    with pytest.raises(BackendError) as caught:
        OpenAIBackend("model-test")._parse_response(response)
    assert caught.value.status == status


@pytest.mark.parametrize("exception,status", [
    (socket.timeout("timed out"), "timeout"),
    (urllib.error.URLError(socket.timeout("timed out")), "timeout"),
    (urllib.error.HTTPError("https://api.openai.com", 429, "Too many", {}, None), "backend_error"),
    (urllib.error.URLError("offline"), "backend_error"),
])
def test_openai_network_errors_are_explicit(monkeypatch, exception, status):
    def fail(*args, **kwargs):
        raise exception

    monkeypatch.setenv("OPENAI_API_KEY", "test-key-never-transmitted")
    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(BackendError) as caught:
        OpenAIBackend("model-test").generate([], {})
    assert caught.value.status == status


def test_missing_key_fails_before_transport(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(BackendError, match="OPENAI_API_KEY"):
        OpenAIBackend("model-test").generate([], {})


@pytest.mark.parametrize("raw", ['{"value":NaN}', '{"value":Infinity}', '{"a":1,"a":2}'])
def test_invalid_json_extensions_rejected(raw):
    with pytest.raises(ValueError):
        strict_json_loads(raw)
