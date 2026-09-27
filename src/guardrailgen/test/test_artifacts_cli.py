import copy
import json
from pathlib import Path

import pytest

from guardrailgen.api.cli import main
from guardrailgen.artifacts import build_artifact, load_monitor, read_json, save_artifact
from guardrailgen.schema import Rule, RuleValidationError, Scenario, Verdict
from guardrailgen.validation import validate_rule

ROOT = Path(__file__).resolve().parents[3]


def reference():
    scenario = Scenario.from_dict(read_json(ROOT / "config/turtlebot_development.json"))
    rule = Rule.from_dict(read_json(ROOT / "data/reference_rule.json"), scenario)
    return rule, scenario


def test_reference_trace_bank_and_rtamt_agree():
    pytest.importorskip("rtamt")
    rule, scenario = reference()
    report = validate_rule(rule, scenario, require_rtamt=True, traces=read_json(ROOT / "data/reference_traces.json"))
    assert report["errors"] == []
    assert report["rtamt"]["status"] == "passed"
    assert report["trace_validation"]["passed"]


def test_content_addressed_roundtrip_and_tamper_detection(tmp_path):
    rule, scenario = reference()
    path = save_artifact(build_artifact(rule, scenario, validate_rule(rule, scenario)), tmp_path)
    assert load_monitor(path).evaluate({"state.x": 0, "state.y": 0, "command.linear_speed": 0.1}) == Verdict.SAFE
    changed = read_json(path)
    changed["rule"]["expression"]["args"][1]["value"] = 999
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(RuleValidationError, match="checksum"):
        load_monitor(path)


def test_failed_report_cannot_replace_existing_artifact(tmp_path):
    rule, scenario = reference()
    good = build_artifact(rule, scenario, validate_rule(rule, scenario))
    path = save_artifact(good, tmp_path)
    before = path.read_bytes()
    bad = copy.deepcopy(good)
    bad["validation"]["errors"] = ["independent trace mismatch"]
    with pytest.raises(RuleValidationError):
        save_artifact(bad, tmp_path)
    assert path.read_bytes() == before
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_contradictory_affine_conjunction_rejected():
    rule, scenario = reference()
    candidate = rule.to_dict()
    candidate["expression"]["args"][1]["value"] = -1
    invalid = Rule.from_dict(candidate, scenario)
    assert "Contradictory" in validate_rule(invalid, scenario)["errors"][0]


def test_cli_validate_check_and_demo(tmp_path, capsys):
    assert main(["validate", str(ROOT / "data/reference_rule.json"), "--scenario", str(ROOT / "config/turtlebot_development.json"),
                 "--traces", str(ROOT / "data/reference_traces.json"), "--output-dir", str(tmp_path)]) == 0
    output = json.loads(capsys.readouterr().out)
    values = tmp_path / "values.json"
    values.write_text('{"state.x": 0, "state.y": 0, "command.linear_speed": 0.3}', encoding="utf-8")
    assert main(["check", output["artifact"], str(values)]) == 2
    assert json.loads(capsys.readouterr().out)["verdict"] == "UNSAFE"
    assert main(["demo"]) == 0
    assert json.loads(capsys.readouterr().out)["source"] == "hand_authored_demo_no_language_model"


def test_cli_missing_credentials_has_explicit_status(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert main(["compile", "Limit commanded speed", "--model", "test-model", "--scenario",
                 str(ROOT / "config/turtlebot_development.json"), "--output-dir", str(tmp_path)]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "backend_error"
    assert not list(tmp_path.iterdir())
