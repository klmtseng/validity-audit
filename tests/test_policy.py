from __future__ import annotations

import copy

import pytest

from validity_audit.policy import POLICY_ID, PolicyError, evaluate_policy


def contract(overrides: list[dict] | None = None) -> dict:
    value = {
        "schema_version": "0.3.0",
        "task_id": "policy-test",
        "claims": [{"claim_id": "claim-1", "statement": "The claim is bounded."}],
        "artifact_paths": ["artifact.txt"],
        "packs": ["docs"],
    }
    if overrides is not None:
        value["policy_overrides"] = overrides
    return value


def finding(
    *,
    finding_id: str = "finding-1",
    error_class: str = "fabrication",
    reproduction: str = "reproduced",
) -> dict:
    value = {
        "finding_id": finding_id,
        "title": "A finding",
        "description": "A synthetic policy finding.",
        "error_class": error_class,
        "source": "cold_review",
        "severity": "high",
        "confidence": "high",
        "reproduction": reproduction,
        "evidence": [
            {
                "evidence_id": f"evidence-{finding_id}",
                "kind": "note",
                "description": "Synthetic evidence.",
            }
        ],
    }
    if reproduction != "reproduced":
        value["reproduction_notes"] = "Reproduction is pending."
    return value


def claims(outcome: str = "supported") -> list[dict]:
    value = {
        "claim_id": "claim-1",
        "statement": "The claim is bounded.",
        "outcome": outcome,
        "evidence": [],
        "finding_ids": [],
    }
    if outcome in {"supported", "refuted"}:
        value["evidence"] = [
            {
                "evidence_id": "claim-evidence",
                "kind": "note",
                "description": "Synthetic claim evidence.",
            }
        ]
    else:
        value["rationale"] = "The evidence is incomplete."
    return [value]


def test_policy_id_is_versioned() -> None:
    assert POLICY_ID == "validity-audit-default-v0.3.0"


@pytest.mark.parametrize(
    "error_class",
    [
        "correctness",
        "evidence_tampering",
        "fabrication",
        "leakage",
        "material_requirement_miss",
        "unauthorized_action",
    ],
)
def test_reproduced_approved_blocking_classes_fail(error_class: str) -> None:
    result = evaluate_policy(
        contract=contract(),
        findings=[finding(error_class=error_class)],
        claim_results=claims(),
        waiver_requests=[],
        issued_at="2026-07-29T00:00:00Z",
    )
    assert result.status == "fail"
    assert result.findings[0]["gate_effect"] == "fail"


@pytest.mark.parametrize("reproduction", ["unreproduced", "not_reproducible", "not_attempted"])
def test_unresolved_blocking_class_needs_review(reproduction: str) -> None:
    result = evaluate_policy(
        contract=contract(),
        findings=[finding(reproduction=reproduction)],
        claim_results=claims(),
        waiver_requests=[],
        issued_at="2026-07-29T00:00:00Z",
    )
    assert result.status == "needs_review"
    assert result.findings[0]["gate_effect"] == "none"


@pytest.mark.parametrize("error_class", ["other", "novel_error_class", "broken-reference"])
def test_unclassified_error_class_needs_review(error_class: str) -> None:
    result = evaluate_policy(
        contract=contract(),
        findings=[finding(error_class=error_class)],
        claim_results=claims(),
        waiver_requests=[],
        issued_at="2026-07-29T00:00:00Z",
    )
    assert result.status == "needs_review"
    assert result.findings[0]["gate_effect"] == "none"


@pytest.mark.parametrize("error_class", ["fitness", "maintainability"])
def test_explicit_advisory_error_class_passes(error_class: str) -> None:
    result = evaluate_policy(
        contract=contract(),
        findings=[finding(error_class=error_class)],
        claim_results=claims(),
        waiver_requests=[],
        issued_at="2026-07-29T00:00:00Z",
    )
    assert result.status == "pass"
    assert result.findings[0]["gate_effect"] == "advisory"


def test_refuted_claim_forces_unknown_error_class_to_fail() -> None:
    claim_results = claims("refuted")
    claim_results[0]["finding_ids"] = ["finding-1"]
    result = evaluate_policy(
        contract=contract(),
        findings=[finding(error_class="novel-error-class")],
        claim_results=claim_results,
        waiver_requests=[],
        issued_at="2026-07-29T00:00:00Z",
    )
    assert result.status == "fail"
    assert result.findings[0]["gate_effect"] == "fail"


def test_contract_override_changes_error_class_gate() -> None:
    result = evaluate_policy(
        contract=contract(
            [
                {
                    "error_class": "maintainability",
                    "gate_effect": "fail",
                    "reason": "This task treats maintainability as blocking.",
                }
            ]
        ),
        findings=[finding(error_class="maintainability")],
        claim_results=claims(),
        waiver_requests=[],
        issued_at="2026-07-29T00:00:00Z",
    )
    assert result.status == "fail"
    assert result.findings[0]["gate_effect"] == "fail"


def test_contract_override_can_explicitly_classify_unknown_as_advisory() -> None:
    result = evaluate_policy(
        contract=contract(
            [
                {
                    "error_class": "novel_error_class",
                    "gate_effect": "advisory",
                    "reason": "The owner explicitly classified this bounded class.",
                }
            ]
        ),
        findings=[finding(error_class="novel_error_class")],
        claim_results=claims(),
        waiver_requests=[],
        issued_at="2026-07-29T00:00:00Z",
    )
    assert result.status == "pass"
    assert result.findings[0]["gate_effect"] == "advisory"


def test_active_waiver_preserves_original_policy_result() -> None:
    result = evaluate_policy(
        contract=contract(),
        findings=[finding()],
        claim_results=claims(),
        waiver_requests=[
            {
                "finding_id": "finding-1",
                "issuer": "owner",
                "reason": "Accepted for one bounded run.",
                "issued_at": "2026-07-28T00:00:00Z",
                "expires_at": "2026-07-30T00:00:00Z",
            }
        ],
        issued_at="2026-07-29T00:00:00Z",
    )
    assert result.status == "pass_with_waiver"
    assert result.findings[0]["gate_effect"] == "waiver"
    assert result.findings[0]["waiver"]["original_policy_result"] == "fail"


def test_expired_waiver_is_rejected() -> None:
    with pytest.raises(PolicyError, match="not active"):
        evaluate_policy(
            contract=contract(),
            findings=[finding()],
            claim_results=claims(),
            waiver_requests=[
                {
                    "finding_id": "finding-1",
                    "issuer": "owner",
                    "reason": "Expired.",
                    "issued_at": "2026-07-27T00:00:00Z",
                    "expires_at": "2026-07-28T00:00:00Z",
                }
            ],
            issued_at="2026-07-29T00:00:00Z",
        )


def test_unclassified_error_class_cannot_be_waived() -> None:
    with pytest.raises(PolicyError, match="unclassified error class"):
        evaluate_policy(
            contract=contract(),
            findings=[finding(error_class="other")],
            claim_results=claims(),
            waiver_requests=[
                {
                    "finding_id": "finding-1",
                    "issuer": "owner",
                    "reason": "Classification must come first.",
                    "issued_at": "2026-07-28T00:00:00Z",
                    "expires_at": "2026-07-30T00:00:00Z",
                }
            ],
            issued_at="2026-07-29T00:00:00Z",
        )


def test_waiver_cannot_turn_unattempted_blocker_into_pass() -> None:
    with pytest.raises(PolicyError, match="reproduced fail result"):
        evaluate_policy(
            contract=contract(),
            findings=[finding(reproduction="not_attempted")],
            claim_results=claims("inconclusive"),
            waiver_requests=[
                {
                    "finding_id": "finding-1",
                    "issuer": "owner",
                    "reason": "Cannot waive evidence that was never reproduced.",
                    "issued_at": "2026-07-28T00:00:00Z",
                    "expires_at": "2026-07-30T00:00:00Z",
                }
            ],
            issued_at="2026-07-29T00:00:00Z",
        )


def test_finder_cannot_set_policy_outputs() -> None:
    tainted = copy.deepcopy(finding())
    tainted["gate_effect"] = "none"
    with pytest.raises(PolicyError, match="policy outputs"):
        evaluate_policy(
            contract=contract(),
            findings=[tainted],
            claim_results=claims(),
            waiver_requests=[],
            issued_at="2026-07-29T00:00:00Z",
        )


def test_unresolved_claim_needs_review() -> None:
    result = evaluate_policy(
        contract=contract(),
        findings=[],
        claim_results=claims("not_evaluated"),
        waiver_requests=[],
        issued_at="2026-07-29T00:00:00Z",
    )
    assert result.status == "needs_review"
