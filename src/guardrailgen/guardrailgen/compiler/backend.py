"""Hosted structured generation, isolated from ROS and the control loop.

API contract verified against the official Responses / Structured Outputs
documentation on 2026-09-19:
https://developers.openai.com/api/docs/guides/structured-outputs
No live request is made during import, construction, or offline tests.
Groq Chat Completions / strict Structured Outputs checked 2026-09-20:
https://console.groq.com/docs/structured-outputs
"""

from dataclasses import dataclass, field
import json
import math
import os
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, List, Protocol


USER_AGENT = "guardrailgen/1.0"


class BackendError(RuntimeError):
    """A failure for which no candidate may be used or activated."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class BackendResponse:
    payload: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)


class GenerationBackend(Protocol):
    def configuration(self) -> Dict[str, Any]: ...

    def generate(self, messages: List[Dict[str, str]],
                 response_schema: Dict[str, Any]) -> BackendResponse: ...


def _reject_nonfinite(value):
    raise ValueError("Non-finite numbers are not valid JSON values")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key: " + key)
        result[key] = value
    return result


def strict_json_loads(text):
    """Reject JSON extensions that could obscure the candidate interpretation."""
    def finite_float(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("JSON numeric literal exceeds finite floating-point range")
        return parsed
    return json.loads(text, parse_constant=_reject_nonfinite,
                      parse_float=finite_float, object_pairs_hook=_unique_object)


def _http_failure(exc):
    """Classify known errors without persisting arbitrary bodies or credentials."""
    message = "Hosted generation returned HTTP " + str(exc.code)
    try:
        raw = exc.read(4096).decode("utf-8", errors="replace")
        if raw.strip().lower() == "error code: 1010":
            return message + " (edge access denied, code 1010)"
        data = json.loads(raw)
        error = data.get("error", {}) if isinstance(data, dict) else {}
        code = error.get("code") if isinstance(error, dict) else None
        if code == "model_permission_blocked_org":
            return message + " (model blocked by organization permissions)"
        if code == "model_permission_blocked_project":
            return message + " (model blocked by project permissions)"
        if exc.code == 429 and isinstance(error, dict) and isinstance(error.get("message"), str):
            # Provider rate-limit text names the exhausted limit (per minute/day).
            import re
            reason = re.sub(r" in organization \S+( service tier \S+)?", "", error["message"])
            reason = reason.split(" Need more tokens")[0].split(" Visit https")[0]
            return message + " (" + reason[:260] + ")"
    except (OSError, ValueError, AttributeError):
        pass
    return message


class OpenAIBackend:
    """One Responses request per attempt with provider-enforced JSON Schema.

    Set OPENAI_API_KEY in the process environment. Choose an account-accessible
    model that supports strict Structured Outputs; unsupported models fail
    explicitly. HTTP and timeout errors are not retried automatically.
    """

    endpoint = "https://api.openai.com/v1/responses"
    adapter_version = "1.0"

    def __init__(self, model: str, timeout: float = 30.0,
                 max_output_tokens: int = 2048):
        if not isinstance(model, str) or not model.strip():
            raise ValueError("An explicit hosted model identifier is required")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        if isinstance(max_output_tokens, bool) or not isinstance(max_output_tokens, int) or max_output_tokens < 1:
            raise ValueError("max_output_tokens must be a positive integer")
        self.model = model
        self.timeout = float(timeout)
        self.max_output_tokens = max_output_tokens

    def configuration(self):
        return {"provider": "openai", "model": self.model,
                "adapter_version": self.adapter_version,
                "endpoint": self.endpoint,
                "structured_output": "json_schema", "strict": True,
                "max_output_tokens": self.max_output_tokens,
                "timeout_seconds": self.timeout, "store": False,
                "sampling_parameters": "provider defaults"}

    def generate(self, messages, response_schema):
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key.strip():
            raise BackendError("backend_error", "OPENAI_API_KEY is not set")
        body = {"model": self.model, "input": messages, "store": False,
                "max_output_tokens": self.max_output_tokens,
                "text": {"format": {"type": "json_schema", "name": "guardrail_rule",
                                     "strict": True, "schema": response_schema}}}
        return self._send(body, key)

    def _send(self, body, key):
        """Shared HTTP transport; endpoint and response parser belong to the provider."""
        request = urllib.request.Request(
            self.endpoint, data=json.dumps(body, allow_nan=False).encode("utf-8"),
            headers={"Authorization": "Bearer " + key,
                     "Content-Type": "application/json",
                     # Cloudflare fronts api.groq.com and rejects urllib's default
                     # Python-urllib/<version> agent with HTTP 403 edge code 1010.
                     "User-Agent": USER_AGENT}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                # Limit accidental or malformed upstream payloads to 2 MiB.
                raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise BackendError("backend_error", "Hosted response exceeded the size limit")
            data = strict_json_loads(raw.decode("utf-8"))
        except (TimeoutError, socket.timeout) as exc:
            raise BackendError("timeout", "Hosted generation timed out") from exc
        except urllib.error.HTTPError as exc:
            # Do not echo request credentials or arbitrary server bodies into artifacts.
            raise BackendError("backend_error", _http_failure(exc)) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise BackendError("timeout", "Hosted generation timed out") from exc
            raise BackendError("backend_error", "Hosted generation could not connect") from exc
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise BackendError("backend_error", "Hosted response was not valid JSON") from exc
        except OSError as exc:
            raise BackendError("backend_error", "Hosted generation transport failed") from exc
        return self._parse_response(data)

    def _parse_response(self, data):
        if not isinstance(data, dict):
            raise BackendError("backend_error", "Hosted response must be an object")
        if data.get("status") == "incomplete":
            details = data.get("incomplete_details") or {}
            reason = details.get("reason", "unspecified") if isinstance(details, dict) else "unspecified"
            raise BackendError("incomplete", "Hosted generation is incomplete: " + str(reason))
        if data.get("status") != "completed":
            raise BackendError("backend_error", "Hosted generation did not complete")
        output = data.get("output")
        if not isinstance(output, list):
            raise BackendError("backend_error", "Hosted response has no output list")
        texts = []
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            if item.get("status") not in (None, "completed"):
                raise BackendError("incomplete", "Hosted output message is incomplete")
            content = item.get("content")
            if not isinstance(content, list):
                raise BackendError("backend_error", "Hosted message has invalid content")
            for part in content:
                if not isinstance(part, dict):
                    raise BackendError("backend_error", "Hosted message has invalid content")
                if part.get("type") == "refusal":
                    raise BackendError("refusal", str(part.get("refusal") or "Hosted model refused the request"))
                if part.get("type") == "output_text":
                    if not isinstance(part.get("text"), str):
                        raise BackendError("backend_error", "Hosted output is not text")
                    texts.append(part["text"])
        if len(texts) != 1:
            raise BackendError("backend_error", "Expected one structured output text block")
        try:
            payload = strict_json_loads(texts[0])
        except (ValueError, RecursionError) as exc:
            raise BackendError("backend_error", "Hosted structured output was not valid JSON") from exc
        if not isinstance(payload, dict):
            raise BackendError("backend_error", "Hosted structured output must be an object")
        metadata = {"response_id": data.get("id"), "model": data.get("model", self.model),
                    "usage": data.get("usage")}
        return BackendResponse(payload, metadata)


def unconstrained_json_payload(content):
    """Parse free text without decoder enforcement (ablation only).

    Accepts one JSON object, optionally wrapped in a Markdown code fence. A parse
    failure becomes a candidate that the compiler rejects, so it can be repaired.
    """
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        payload = strict_json_loads(text.strip())
    except (ValueError, RecursionError) as exc:
        return {"_parse_error": str(exc)[:200]}
    if not isinstance(payload, dict):
        return {"_parse_error": "top-level JSON value is not an object"}
    return payload


class GroqBackend(OpenAIBackend):
    """Groq-hosted GPT-OSS with actual strict JSON Schema decoding.

    Reuses HTTP transport and argument validation only. Requests go exclusively
    to Groq with GROQ_API_KEY; there is no automatic OpenAI fallback. Chat
    Completions uses a different request/response envelope from Responses.
    """

    endpoint = "https://api.groq.com/openai/v1/chat/completions"
    default_model = "openai/gpt-oss-120b"
    provider_name = "groq"
    key_env = "GROQ_API_KEY"

    def _extra_body(self):
        return {}

    def __init__(self, model: str = default_model, timeout: float = 30.0,
                 max_output_tokens: int = 4096, strict: bool = True):
        super().__init__(model, timeout, max_output_tokens)
        # strict=False is only for the RQ1 ablation without constrained decoding:
        # no response_format is sent and the text is parsed afterwards.
        self.strict = bool(strict)

    def configuration(self):
        return {"provider": self.provider_name, "model": self.model, "routing": self._extra_body(),
                "adapter_version": self.adapter_version, "endpoint": self.endpoint,
                "structured_output": "json_schema" if self.strict else "none",
                "strict": self.strict,
                "max_completion_tokens": self.max_output_tokens,
                "timeout_seconds": self.timeout, "stream": False,
                "sampling_parameters": "provider defaults"}

    def generate(self, messages, response_schema):
        key = os.environ.get(self.key_env, "")
        if not key.strip():
            raise BackendError("backend_error", self.key_env + " is not set")
        body = {"model": self.model, "messages": messages, "stream": False,
                "max_completion_tokens": self.max_output_tokens, **self._extra_body()}
        if self.strict:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "guardrail_rule", "strict": True, "schema": response_schema}}
        return self._send(body, key)

    def _parse_response(self, data):
        if not isinstance(data, dict) or data.get("error"):
            raise BackendError("backend_error", "Groq returned an invalid completion")
        choices = data.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise BackendError("backend_error", "Expected one Groq completion choice")
        choice = choices[0]
        reason = choice.get("finish_reason")
        if reason == "length":
            raise BackendError("incomplete", "Groq generation reached the completion token limit")
        if reason == "content_filter":
            raise BackendError("refusal", "Groq generation was refused by a content filter")
        message = choice.get("message")
        if not isinstance(message, dict):
            raise BackendError("backend_error", "Groq completion has no valid message")
        if message.get("refusal"):
            raise BackendError("refusal", "Groq model refused the request")
        if reason != "stop" or message.get("tool_calls") or message.get("function_call"):
            raise BackendError("backend_error", "Groq did not finish with a structured text response")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise BackendError("backend_error", "Groq completion has no structured output text")
        if self.strict:
            try:
                payload = strict_json_loads(content)
            except (ValueError, RecursionError) as exc:
                raise BackendError("backend_error", "Groq structured output was not valid JSON") from exc
            if not isinstance(payload, dict):
                raise BackendError("backend_error", "Groq structured output must be an object")
        else:
            payload = unconstrained_json_payload(content)
        return BackendResponse(payload, {"response_id": data.get("id"),
            "model": data.get("model", self.model), "usage": data.get("usage"),
            "system_fingerprint": data.get("system_fingerprint"), "finish_reason": reason})


class OpenRouterBackend(GroqBackend):
    """The same Groq-hosted gpt-oss-120b, reached through OpenRouter.

    Routing is pinned to OpenRouter's Groq provider with fallbacks disabled and
    require_parameters=True, so a request is never silently served by another
    host or without strict JSON-schema decoding. Uses OPENROUTER_API_KEY.
    """

    endpoint = "https://openrouter.ai/api/v1/chat/completions"
    default_model = "openai/gpt-oss-120b"
    provider_name = "openrouter"
    key_env = "OPENROUTER_API_KEY"

    def __init__(self, model: str = default_model, timeout: float = 30.0,
                 max_output_tokens: int = 4096, strict: bool = True, route: str = "groq"):
        super().__init__(model, timeout, max_output_tokens, strict)
        self.route = route

    def _extra_body(self):
        return {"provider": {"order": [self.route], "allow_fallbacks": False, "require_parameters": True}}
