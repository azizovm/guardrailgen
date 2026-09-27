"""Content-addressed candidate artifacts with atomic writes and strict reloads."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile

from guardrailgen.compiler.backend import strict_json_loads
from guardrailgen.schema import SCHEMA_VERSION, Rule, RuleValidationError, Scenario, compile_rule


def read_json(path):
    path = Path(path)
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("JSON input exceeds 2 MiB")
    return strict_json_loads(path.read_text(encoding="utf-8-sig"))


def _digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False).encode("utf-8")).hexdigest()


def build_artifact(rule, scenario, validation, provenance=None):
    monitor = compile_rule(rule, scenario)
    return {"schema_version": SCHEMA_VERSION, "rule": rule.to_dict(), "scenario": scenario.to_dict(),
            "stl": monitor.stl, "validation": copy.deepcopy(validation),
            "provenance": provenance or {"source": "hand_authored_structured_rule"},
            "activation": "requires_explicit_runtime_loading"}


def monitor_from_artifact(artifact):
    if not isinstance(artifact, dict) or artifact.get("schema_version") != SCHEMA_VERSION:
        raise RuleValidationError("Unsupported artifact format")
    if "artifact_sha256" in artifact:
        content = {k: v for k, v in artifact.items() if k != "artifact_sha256"}
        if artifact["artifact_sha256"] != _digest(content):
            raise RuleValidationError("Artifact checksum mismatch")
    scenario = Scenario.from_dict(artifact.get("scenario"))
    rule = Rule.from_dict(artifact.get("rule"), scenario)
    monitor = compile_rule(rule, scenario)
    if artifact.get("stl") != monitor.stl:
        raise RuleValidationError("Stored STL differs from deterministic lowering")
    validation = artifact.get("validation")
    if not isinstance(validation, dict) or "errors" not in validation or validation["errors"] != []:
        raise RuleValidationError("Artifact has no passing validation report")
    extra = validation.get("additional_validation", {})
    if not isinstance(extra, dict) or extra.get("errors", []) != []:
        raise RuleValidationError("Artifact has failed additional validation")
    # Metadata and checksums are evidence/integrity aids, not trusted approval.
    from guardrailgen.validation import validate_rule
    if validate_rule(rule, scenario)["errors"]:
        raise RuleValidationError("Artifact failed deterministic revalidation")
    for report in (validation,extra):
        equivalence=report.get('equivalence','not_checked')
        if equivalence=='not_checked':
            continue
        if not isinstance(equivalence,dict) or equivalence.get('status')!='equivalent':
            raise RuleValidationError('Artifact has no passing requested equivalence check')
        from guardrailgen.validation.equivalence import check_equivalence
        reference=Rule.from_dict(equivalence.get('reference_rule'),scenario)
        checked=check_equivalence(rule,reference,scenario,equivalence.get('domains'),
            timeout_ms=equivalence.get('timeout_ms',1000))
        if checked['status']!='equivalent' or checked['inputs_sha256']!=equivalence.get('inputs_sha256'):
            raise RuleValidationError('Artifact failed reference equivalence revalidation')
    return monitor


def load_monitor(path):
    return monitor_from_artifact(read_json(path))


def write_json_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as stream:
            temp_path = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def save_artifact(artifact, directory):
    monitor_from_artifact(artifact)
    content = {k: v for k, v in copy.deepcopy(artifact).items() if k != "artifact_sha256"}
    digest = _digest(content)
    result = {**content, "artifact_sha256": digest}
    path = Path(directory) / (digest + ".json")
    write_json_atomic(path, result)
    return path
