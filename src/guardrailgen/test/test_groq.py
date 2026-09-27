"""Groq transport and CLI routing contracts, with no network requests."""
import io
import json
from pathlib import Path
import socket
import urllib.error

import pytest

from guardrailgen.api.cli import main
from guardrailgen.artifacts import read_json
from guardrailgen.compiler import BackendError, Compiler, GroqBackend, response_schema
from guardrailgen.schema import Scenario

ROOT = Path(__file__).resolve().parents[3]
TEXT = "Keep commanded linear speed at or below 0.2 m/s."


def candidate():
    return {"status": "compiled", "message": "The signed linear command is at most 0.2 m/s.",
            "rule": {"schema_version": "1.0", "id": "operator-rule", "text": TEXT,
                     "expression": {"op": "compare", "variable": "command.linear_speed",
                                    "comparator": "le", "value": 0.2, "unit": "m/s"}}}


def response(content=None, finish="stop", **message_fields):
    return {"id": "groq-fixture", "model": "openai/gpt-oss-120b",
            "usage": {"prompt_tokens": 100, "completion_tokens": 30},
            "system_fingerprint": "test-fingerprint",
            "choices": [{"index": 0, "finish_reason": finish, "message": {
                "role": "assistant", "content": json.dumps(candidate()) if content is None else content,
                **message_fields}}]}


def test_groq_strict_transport_and_artifact_provenance(monkeypatch):
    calls = []
    def transport(request, timeout):
        calls.append((request, timeout))
        return io.BytesIO(json.dumps(response()).encode())
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-unused-secret")
    monkeypatch.setattr("urllib.request.urlopen", transport)
    scenario = Scenario.from_dict(read_json(ROOT / "config/turtlebot_development.json"))
    result = Compiler(GroqBackend(timeout=7), scenario).compile(TEXT)
    assert result.ok
    request, timeout = calls[0]
    body = json.loads(request.data)
    assert request.full_url == "https://api.groq.com/openai/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer groq-test-secret"
    assert timeout == 7 and len(calls) == 1
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["schema"] == response_schema(scenario, TEXT, "operator-rule")
    assert body["messages"] and body["max_completion_tokens"] == 4096
    assert body["stream"] is False and "input" not in body and "text" not in body
    assert result.artifact["provenance"]["backend"]["provider"] == "groq"
    metadata = result.artifact["compilation_attempts"][0]["metadata"]
    assert metadata["response_id"] == "groq-fixture"
    assert metadata["usage"]["completion_tokens"] == 30
    assert metadata["system_fingerprint"] == "test-fingerprint"
    assert "secret" not in json.dumps(result.to_dict())


@pytest.mark.parametrize("data,status", [
    (response(finish="length"), "incomplete"),
    (response(finish="content_filter"), "refusal"),
    (response(refusal="Cannot comply"), "refusal"),
    (response(finish="tool_calls", tool_calls=[{}]), "backend_error"),
    (response(tool_calls=[{}]), "backend_error"),
    (response(finish=None), "backend_error"),
    (response(content="{incomplete"), "backend_error"),
    (response(content="[]"), "backend_error"),
    (response(content='{"value":1e999}'), "backend_error"),
    (response(content='{"a":1,"a":2}'), "backend_error"),
    ({"choices": []}, "backend_error"),
    ({"choices": [{"finish_reason": "stop", "message": None}]}, "backend_error"),
    ({"error": {"message": "private server error"}}, "backend_error"),
])
def test_groq_incomplete_refused_and_invalid_output(data, status):
    with pytest.raises(BackendError) as caught:
        GroqBackend()._parse_response(data)
    assert caught.value.status == status


@pytest.mark.parametrize("exception,status", [
    (socket.timeout("timeout"), "timeout"),
    (urllib.error.URLError(socket.timeout("timeout")), "timeout"),
    (urllib.error.HTTPError("https://api.groq.com", 429, "Rate limited", {}, None), "backend_error"),
    (urllib.error.HTTPError("https://api.groq.com", 401, "Bad credentials", {}, None), "backend_error"),
])
def test_transport_failure_never_falls_back_or_retries(monkeypatch, exception, status):
    calls = []
    def fail(request, **kwargs):
        calls.append(request.full_url)
        raise exception
    monkeypatch.setenv("GROQ_API_KEY", "test-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(BackendError) as caught:
        GroqBackend().generate([], {})
    assert caught.value.status == status
    assert calls == [GroqBackend.endpoint]


def test_missing_groq_key_cannot_use_openai_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    def forbidden(*args, **kwargs):
        pytest.fail("No credential means no request")
    monkeypatch.setattr("urllib.request.urlopen", forbidden)
    with pytest.raises(BackendError, match="GROQ_API_KEY"):
        GroqBackend().generate([], {})


@pytest.mark.parametrize('body,detail', [
    (b'error code: 1010', 'edge access denied, code 1010'),
    (b'{"error":{"code":"model_permission_blocked_org","message":"secret"}}', 'organization permissions'),
    (b'{"error":{"code":"model_permission_blocked_project"}}', 'project permissions'),
    (b'{"error":{"code":"secret","message":"secret"}}', 'HTTP 403'),
    (b'<html>secret</html>', 'HTTP 403'),
])
def test_http_diagnostics_do_not_leak_arbitrary_bodies(monkeypatch, body, detail):
    def fail(request, **kwargs):
        raise urllib.error.HTTPError(request.full_url,403,'Forbidden',{},io.BytesIO(body))
    monkeypatch.setenv('GROQ_API_KEY','secret')
    monkeypatch.setattr('urllib.request.urlopen',fail)
    with pytest.raises(BackendError) as caught:
        GroqBackend().generate([], {})
    assert detail in str(caught.value)
    assert 'secret' not in str(caught.value)


@pytest.mark.parametrize("model_env,model_arg,expected", [
    (None, None, "openai/gpt-oss-120b"),
    ("groq-env-model", None, "groq-env-model"),
    ("groq-env-model", "explicit-model", "explicit-model"),
])
def test_cli_defaults_to_groq_ignoring_old_openai_model(monkeypatch, tmp_path, capsys, model_env, model_arg, expected):
    monkeypatch.setenv("GROQ_API_KEY", "test-secret")
    monkeypatch.setenv("OPENAI_MODEL", "unwanted-openai-model")
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    if model_env:
        monkeypatch.setenv("GROQ_MODEL", model_env)
    def transport(request, timeout):
        assert request.full_url == GroqBackend.endpoint
        assert json.loads(request.data)["model"] == expected
        return io.BytesIO(json.dumps(response()).encode())
    monkeypatch.setattr("urllib.request.urlopen", transport)
    args = ["compile", TEXT, "--scenario", str(ROOT / "config/turtlebot_development.json"), "--output-dir", str(tmp_path)]
    if model_arg:
        args += ["--model", model_arg]
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["provenance"]["backend"]["provider"] == "groq"
    assert Path(result["artifact_path"]).is_file()


def test_cli_openai_requires_explicit_provider(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("OPENAI_MODEL", "openai-test-model")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "must-not-be-used")
    assert main(["compile", TEXT, "--provider", "openai", "--scenario",
                 str(ROOT / "config/turtlebot_development.json"), "--output-dir", str(tmp_path)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["provenance"]["backend"]["provider"] == "openai"
    assert "OPENAI_API_KEY" in result["message"]
