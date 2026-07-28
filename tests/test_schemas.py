from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
EXAMPLE_DIR = SCHEMA_DIR / "examples"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


TASK_SCHEMA = load_json(SCHEMA_DIR / "task_contract.schema.json")
ATTESTATION_SCHEMA = load_json(SCHEMA_DIR / "attestation.schema.json")
TASK_EXAMPLE = load_json(EXAMPLE_DIR / "task_contract.json")
ATTESTATION_EXAMPLE = load_json(EXAMPLE_DIR / "unsigned_attestation.json")
FORMAT_CHECKER = FormatChecker()


def validate(instance: dict, schema: dict) -> None:
    Draft202012Validator(schema, format_checker=FORMAT_CHECKER).validate(instance)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_sha256(artifacts: list[dict]) -> str:
    ordered = sorted(artifacts, key=lambda artifact: artifact["path"])
    payload = json.dumps(
        ordered,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def synthetic_finding(
    *,
    finding_id: str = "finding-1",
    gate_effect: str = "advisory",
    reproduction: str = "reproduced",
    source: str = "operator",
) -> dict:
    severity = "high" if gate_effect == "fail" else "low"
    confidence = "low" if reproduction != "reproduced" else "high"
    return {
        "finding_id": finding_id,
        "title": "Synthetic schema-test finding",
        "description": "This fixture exists only to test attestation constraints.",
        "error_class": "schema-test",
        "source": source,
        "severity": severity,
        "confidence": confidence,
        "reproduction": reproduction,
        "gate_effect": gate_effect,
        "evidence": [
            {
                "evidence_id": f"evidence-{finding_id}",
                "kind": "note",
                "description": "Synthetic evidence for schema validation.",
            }
        ],
    }


def waiver() -> dict:
    return {
        "issuer": "owner",
        "reason": "Temporary acceptance for this schema test.",
        "original_policy_result": "fail",
        "issued_at": "2026-07-28T06:03:00Z",
        "expires_at": "2026-08-01T00:00:00Z",
    }


def test_schemas_are_valid_draft_2020_12() -> None:
    for schema in (TASK_SCHEMA, ATTESTATION_SCHEMA):
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(schema)


def test_date_time_format_checker_is_registered() -> None:
    assert "date-time" in FORMAT_CHECKER.checkers, (
        "The date-time format checker is unavailable. Install the development extras "
        "with `pip install -e '.[dev]'` before running the schema suite."
    )


def test_examples_validate() -> None:
    validate(TASK_EXAMPLE, TASK_SCHEMA)
    validate(ATTESTATION_EXAMPLE, ATTESTATION_SCHEMA)


@pytest.mark.parametrize("path", ["/etc/passwd", "../secret.txt", "docs/../../secret.txt"])
def test_task_contract_rejects_unbounded_artifact_paths(path: str) -> None:
    contract = copy.deepcopy(TASK_EXAMPLE)
    contract["artifact_paths"] = [path]
    with pytest.raises(ValidationError):
        validate(contract, TASK_SCHEMA)


def test_policy_override_requires_a_reason() -> None:
    contract = copy.deepcopy(TASK_EXAMPLE)
    del contract["policy_overrides"][0]["reason"]
    with pytest.raises(ValidationError):
        validate(contract, TASK_SCHEMA)


@pytest.mark.parametrize(
    ("axis", "invalid_value"),
    [
        ("severity", "P1"),
        ("confidence", "certain"),
        ("reproduction", "probably"),
        ("gate_effect", "ignore"),
    ],
)
def test_finding_taxonomy_is_canonical(axis: str, invalid_value: str) -> None:
    attestation = copy.deepcopy(ATTESTATION_EXAMPLE)
    finding = synthetic_finding(source="deterministic_probe")
    finding[axis] = invalid_value
    attestation["findings"] = [finding]
    with pytest.raises(ValidationError):
        validate(attestation, ATTESTATION_SCHEMA)


def test_v03_attestation_cannot_claim_a_signature() -> None:
    attestation = copy.deepcopy(ATTESTATION_EXAMPLE)
    attestation["signature"] = {"algorithm": "not-implemented"}
    with pytest.raises(ValidationError):
        validate(attestation, ATTESTATION_SCHEMA)


def test_schema_rejects_global_agent_certification_claim() -> None:
    attestation = copy.deepcopy(ATTESTATION_EXAMPLE)
    attestation["agent_certified"] = True
    with pytest.raises(ValidationError):
        validate(attestation, ATTESTATION_SCHEMA)


def test_attestation_rejects_invalid_date_time() -> None:
    attestation = copy.deepcopy(ATTESTATION_EXAMPLE)
    attestation["issued_at"] = "not-a-date"
    with pytest.raises(ValidationError):
        validate(attestation, ATTESTATION_SCHEMA)


@pytest.mark.parametrize(
    "missing_field",
    ["issuer", "reason", "original_policy_result", "issued_at", "expires_at"],
)
def test_waiver_requires_a_complete_audit_trail(missing_field: str) -> None:
    attestation = copy.deepcopy(ATTESTATION_EXAMPLE)
    finding = synthetic_finding(finding_id="finding-waived", gate_effect="waiver")
    finding["waiver"] = waiver()
    del finding["waiver"][missing_field]
    attestation["findings"] = [finding]
    attestation["overall_result"]["status"] = "pass_with_waiver"
    with pytest.raises(ValidationError):
        validate(attestation, ATTESTATION_SCHEMA)


def test_complete_waiver_is_valid() -> None:
    attestation = copy.deepcopy(ATTESTATION_EXAMPLE)
    finding = synthetic_finding(finding_id="finding-waived", gate_effect="waiver")
    finding["waiver"] = waiver()
    attestation["findings"] = [finding]
    attestation["overall_result"]["status"] = "pass_with_waiver"
    validate(attestation, ATTESTATION_SCHEMA)

    issued = datetime.fromisoformat(finding["waiver"]["issued_at"].replace("Z", "+00:00"))
    attested = datetime.fromisoformat(ATTESTATION_EXAMPLE["issued_at"].replace("Z", "+00:00"))
    expires = datetime.fromisoformat(finding["waiver"]["expires_at"].replace("Z", "+00:00"))
    assert issued <= attested < expires


def test_waiver_cannot_override_another_waiver() -> None:
    attestation = copy.deepcopy(ATTESTATION_EXAMPLE)
    finding = synthetic_finding(finding_id="finding-waived", gate_effect="waiver")
    finding["waiver"] = waiver()
    finding["waiver"]["original_policy_result"] = "waiver"
    attestation["findings"] = [finding]
    attestation["overall_result"]["status"] = "pass_with_waiver"
    with pytest.raises(ValidationError):
        validate(attestation, ATTESTATION_SCHEMA)


def test_nonwaiver_finding_cannot_carry_waiver_metadata() -> None:
    attestation = copy.deepcopy(ATTESTATION_EXAMPLE)
    finding = synthetic_finding(finding_id="finding-advisory")
    finding["waiver"] = waiver()
    attestation["findings"] = [finding]
    with pytest.raises(ValidationError):
        validate(attestation, ATTESTATION_SCHEMA)


@pytest.mark.parametrize(
    "reproduction",
    ["unreproduced", "not_reproducible", "not_attempted"],
)
def test_nonreproduced_finding_requires_notes(reproduction: str) -> None:
    attestation = copy.deepcopy(ATTESTATION_EXAMPLE)
    attestation["findings"] = [
        synthetic_finding(
            finding_id=f"finding-{reproduction}",
            gate_effect="none",
            reproduction=reproduction,
            source="cold_review",
        )
    ]
    with pytest.raises(ValidationError):
        validate(attestation, ATTESTATION_SCHEMA)

    attestation["findings"][0]["reproduction_notes"] = (
        "The allegation could not be reproduced from the supplied artifact set."
    )
    validate(attestation, ATTESTATION_SCHEMA)


def test_pass_cannot_hide_fail_or_waiver_gate_effects() -> None:
    attestation = copy.deepcopy(ATTESTATION_EXAMPLE)
    attestation["findings"] = [
        synthetic_finding(
            finding_id="finding-fail",
            gate_effect="fail",
            source="deterministic_probe",
        )
    ]
    with pytest.raises(ValidationError):
        validate(attestation, ATTESTATION_SCHEMA)


def test_fail_status_requires_a_failing_finding() -> None:
    attestation = copy.deepcopy(ATTESTATION_EXAMPLE)
    attestation["overall_result"]["status"] = "fail"
    with pytest.raises(ValidationError):
        validate(attestation, ATTESTATION_SCHEMA)

    attestation["findings"] = [
        synthetic_finding(
            finding_id="finding-fail",
            gate_effect="fail",
            source="deterministic_probe",
        )
    ]
    validate(attestation, ATTESTATION_SCHEMA)


def test_needs_review_represents_not_attempted_reproduction() -> None:
    attestation = copy.deepcopy(ATTESTATION_EXAMPLE)
    finding = synthetic_finding(
        finding_id="finding-needs-review",
        gate_effect="none",
        reproduction="not_attempted",
        source="cold_review",
    )
    finding["reproduction_notes"] = "Reproduction was deferred pending protected material."
    attestation["findings"] = [finding]
    attestation["overall_result"]["status"] = "needs_review"
    validate(attestation, ATTESTATION_SCHEMA)


def test_pass_with_waiver_cannot_hide_a_failing_finding() -> None:
    attestation = copy.deepcopy(ATTESTATION_EXAMPLE)
    failed = synthetic_finding(
        finding_id="finding-fail",
        gate_effect="fail",
        source="deterministic_probe",
    )
    waived = synthetic_finding(finding_id="finding-waived", gate_effect="waiver")
    waived["waiver"] = waiver()
    attestation["findings"] = [failed, waived]
    attestation["overall_result"]["status"] = "pass_with_waiver"
    with pytest.raises(ValidationError):
        validate(attestation, ATTESTATION_SCHEMA)


def test_primed_review_requires_sources_and_cold_review_forbids_them() -> None:
    primed = copy.deepcopy(ATTESTATION_EXAMPLE)
    primed["review"]["context"] = "primed"
    with pytest.raises(ValidationError):
        validate(primed, ATTESTATION_SCHEMA)

    cold = copy.deepcopy(ATTESTATION_EXAMPLE)
    cold["review"]["priming_sources"] = ["answer key"]
    with pytest.raises(ValidationError):
        validate(cold, ATTESTATION_SCHEMA)

    primed["review"]["priming_sources"] = ["published regression key"]
    validate(primed, ATTESTATION_SCHEMA)


def test_examples_have_unique_ids_and_complete_references() -> None:
    claim_ids = [claim["claim_id"] for claim in TASK_EXAMPLE["claims"]]
    result_ids = [result["claim_id"] for result in ATTESTATION_EXAMPLE["claim_results"]]
    finding_ids = [finding["finding_id"] for finding in ATTESTATION_EXAMPLE["findings"]]
    referenced_findings = {
        finding_id
        for result in ATTESTATION_EXAMPLE["claim_results"]
        for finding_id in result["finding_ids"]
    }

    assert len(claim_ids) == len(set(claim_ids))
    assert len(result_ids) == len(set(result_ids))
    assert len(finding_ids) == len(set(finding_ids))
    assert set(result_ids) == set(claim_ids)
    assert referenced_findings <= set(finding_ids)
    assert ATTESTATION_EXAMPLE["run"]["task_id"] == TASK_EXAMPLE["task_id"]


def test_example_digests_bind_to_real_files() -> None:
    contract = ATTESTATION_EXAMPLE["contract"]
    assert contract["sha256"] == sha256(ROOT / contract["path"])

    artifacts = ATTESTATION_EXAMPLE["artifact_manifest"]["artifacts"]
    for artifact in artifacts:
        path = ROOT / artifact["path"]
        assert artifact["sha256"] == sha256(path)
        assert artifact["size_bytes"] == path.stat().st_size

    assert (
        ATTESTATION_EXAMPLE["artifact_manifest"]["manifest_sha256"]
        == manifest_sha256(artifacts)
    )
    assert ATTESTATION_EXAMPLE["review"]["bundle_sha256"] == sha256(
        EXAMPLE_DIR / "review_bundle.json"
    )
    assert ATTESTATION_EXAMPLE["review"]["transcript_sha256"] == sha256(
        EXAMPLE_DIR / "reviewer_transcript.json"
    )


def test_example_timestamps_are_chronological() -> None:
    run = ATTESTATION_EXAMPLE["run"]
    started = datetime.fromisoformat(run["started_at"].replace("Z", "+00:00"))
    completed = datetime.fromisoformat(run["completed_at"].replace("Z", "+00:00"))
    issued = datetime.fromisoformat(ATTESTATION_EXAMPLE["issued_at"].replace("Z", "+00:00"))
    assert started <= completed <= issued
