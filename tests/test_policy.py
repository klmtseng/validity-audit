from __future__ import annotations

import copy

import pytest

from validity_audit.policy import POLICY_ID, PolicyError, evaluate_policy


def contract(
    overrides: list[dict] | None = None,
    *,
    waiver_issuers: list[str] | None = None,
) -> dict:
    value = {
        "schema_version": "0.3.0",
        "task_id": "policy-test",
        "claims": [{"claim_id": "claim-1", "statement": "The claim is bounded."}],
        "artifact_paths": ["artifact.txt"],
        "packs": ["docs"],
    }
    if overrides is not None:
        value["policy_overrides"] = overrides
    if waiver_issuers is not None:
        value["waiver_issuers"] = waiver_issuers
    return value


def finding(
    *,
    finding_id: str = "finding-1",
    error_class: str = "fabrication",
    reproduction: str = "reproduced",
    severity: str = "high",
) -> dict:
    value = {
        "finding_id": finding_id,
        "title": "A finding",
        "description": "A synthetic policy finding.",
        "error_class": error_class,
        "source": "cold_review",
        "severity": severity,
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
    assert POLICY_ID == "validity-audit-default-v0.6.0"


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
def test_unclassified_error_class_is_rejected(error_class: str) -> None:
    with pytest.raises(PolicyError, match="unclassified error_class") as excinfo:
        evaluate_policy(
            contract=contract(),
            findings=[finding(error_class=error_class)],
            claim_results=claims(),
            waiver_requests=[],
            issued_at="2026-07-29T00:00:00Z",
        )
    message = str(excinfo.value)
    assert "finding-1" in message
    assert error_class in message
    # The full legal set must be listed so the contract author can self-serve a fix.
    for legal_class in (
        "correctness",
        "evidence_tampering",
        "fabrication",
        "fitness",
        "leakage",
        "maintainability",
        "material_requirement_miss",
        "unauthorized_action",
    ):
        assert legal_class in message


def test_unclassified_error_class_lists_all_violations_at_once() -> None:
    with pytest.raises(PolicyError) as excinfo:
        evaluate_policy(
            contract=contract(),
            findings=[
                finding(finding_id="finding-1", error_class="other"),
                finding(finding_id="finding-2", error_class="novel_error_class"),
            ],
            claim_results=claims(),
            waiver_requests=[],
            issued_at="2026-07-29T00:00:00Z",
        )
    message = str(excinfo.value)
    assert "finding-1" in message
    assert "finding-2" in message


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


@pytest.mark.parametrize("reproduction", ["unreproduced", "not_reproducible", "not_attempted"])
def test_high_severity_unreproduced_advisory_class_needs_review(reproduction: str) -> None:
    result = evaluate_policy(
        contract=contract(),
        findings=[
            finding(error_class="fitness", reproduction=reproduction, severity="high")
        ],
        claim_results=claims("inconclusive"),
        waiver_requests=[],
        issued_at="2026-07-29T00:00:00Z",
    )
    assert result.status == "needs_review"
    assert result.findings[0]["gate_effect"] == "none"


@pytest.mark.parametrize("severity", ["med", "low"])
def test_non_high_severity_unreproduced_advisory_class_stays_advisory(severity: str) -> None:
    result = evaluate_policy(
        contract=contract(),
        findings=[
            finding(error_class="fitness", reproduction="unreproduced", severity=severity)
        ],
        claim_results=claims(),
        waiver_requests=[],
        issued_at="2026-07-29T00:00:00Z",
    )
    assert result.status == "pass"
    assert result.findings[0]["gate_effect"] == "advisory"


def test_refuted_claim_forces_advisory_class_to_fail() -> None:
    claim_results = claims("refuted")
    claim_results[0]["finding_ids"] = ["finding-1"]
    result = evaluate_policy(
        contract=contract(),
        findings=[finding(error_class="fitness")],
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
        contract=contract(waiver_issuers=["owner"]),
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
            contract=contract(waiver_issuers=["owner"]),
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
    # The error_class landing check now runs before waiver application, so an
    # unclassified finding is rejected outright -- it never reaches the point
    # where a waiver could apply to it.
    with pytest.raises(PolicyError, match="unclassified error_class"):
        evaluate_policy(
            contract=contract(waiver_issuers=["owner"]),
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
            contract=contract(waiver_issuers=["owner"]),
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


def test_waiver_without_declared_issuers_is_rejected() -> None:
    with pytest.raises(PolicyError, match="does not declare waiver_issuers"):
        evaluate_policy(
            contract=contract(),
            findings=[finding()],
            claim_results=claims(),
            waiver_requests=[
                {
                    "finding_id": "finding-1",
                    "issuer": "owner",
                    "reason": "No waiver_issuers declared on this contract.",
                    "issued_at": "2026-07-28T00:00:00Z",
                    "expires_at": "2026-07-30T00:00:00Z",
                }
            ],
            issued_at="2026-07-29T00:00:00Z",
        )


def test_waiver_issuer_not_in_contract_list_is_rejected() -> None:
    with pytest.raises(PolicyError, match="waiver issuer not permitted") as excinfo:
        evaluate_policy(
            contract=contract(waiver_issuers=["owner"]),
            findings=[finding()],
            claim_results=claims(),
            waiver_requests=[
                {
                    "finding_id": "finding-1",
                    "issuer": "impostor",
                    "reason": "Not an authorized issuer.",
                    "issued_at": "2026-07-28T00:00:00Z",
                    "expires_at": "2026-07-30T00:00:00Z",
                }
            ],
            issued_at="2026-07-29T00:00:00Z",
        )
    message = str(excinfo.value)
    assert "impostor" in message
    assert "owner" in message


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


def test_waiver_issuers_non_list_type_is_rejected() -> None:
    bad_contract = contract()
    bad_contract["waiver_issuers"] = "owner"
    with pytest.raises(PolicyError, match="must be an array of issuer strings"):
        evaluate_policy(
            contract=bad_contract,
            findings=[finding()],
            claim_results=claims(),
            waiver_requests=[
                {
                    "finding_id": "finding-1",
                    "issuer": "owner",
                    "reason": "Non-list waiver_issuers must not silently iterate characters.",
                    "issued_at": "2026-07-28T00:00:00Z",
                    "expires_at": "2026-07-30T00:00:00Z",
                }
            ],
            issued_at="2026-07-29T00:00:00Z",
        )


def test_waiver_unknown_target_is_reported_before_issuer_check() -> None:
    # The waiver's issuer is also not in the contract's allowlist, but the
    # unknown-finding problem must surface first: fixing the issuer alone
    # would not make this waiver valid, so that error must not be the one
    # the caller sees.
    with pytest.raises(PolicyError, match="unknown findings") as excinfo:
        evaluate_policy(
            contract=contract(waiver_issuers=["owner"]),
            findings=[finding(finding_id="finding-1")],
            claim_results=claims(),
            waiver_requests=[
                {
                    "finding_id": "finding-that-was-not-imported",
                    "issuer": "impostor",
                    "reason": "Targets a finding this run never imported.",
                    "issued_at": "2026-07-28T00:00:00Z",
                    "expires_at": "2026-07-30T00:00:00Z",
                }
            ],
            issued_at="2026-07-29T00:00:00Z",
        )
    message = str(excinfo.value)
    assert "finding-that-was-not-imported" in message
    assert "impostor" not in message


@pytest.mark.parametrize("reproduction", ["unreproduced", "not_reproducible", "not_attempted"])
def test_high_severity_unreproduced_explicit_none_override_still_needs_review(
    reproduction: str,
) -> None:
    # A reason-bearing contract override that explicitly classifies an open
    # slug as gate_effect "none" must not exempt a high-severity,
    # unreproduced finding from the severity-based needs_review rule.
    result = evaluate_policy(
        contract=contract(
            [
                {
                    "error_class": "novel_error_class",
                    "gate_effect": "none",
                    "reason": "The owner explicitly classified this slug as non-blocking.",
                }
            ]
        ),
        findings=[
            finding(
                error_class="novel_error_class",
                reproduction=reproduction,
                severity="high",
            )
        ],
        claim_results=claims("inconclusive"),
        waiver_requests=[],
        issued_at="2026-07-29T00:00:00Z",
    )
    assert result.status == "needs_review"
    assert result.findings[0]["gate_effect"] == "none"
    assert "high-severity finding lacks completed reproduction" in result.summary


@pytest.mark.parametrize("severity", ["high", "med", "low"])
def test_refuted_advisory_class_finding_fails_regardless_of_severity(severity: str) -> None:
    # Documents the current behavior of the refutation path for item 6g:
    # a refuted claim forces its linked finding's configured effect to
    # "fail" unconditionally; severity plays no role once a claim is
    # refuted, unlike the unreproduced/advisory interaction above.
    claim_results = claims("refuted")
    claim_results[0]["finding_ids"] = ["finding-1"]
    result = evaluate_policy(
        contract=contract(),
        findings=[finding(error_class="fitness", severity=severity)],
        claim_results=claim_results,
        waiver_requests=[],
        issued_at="2026-07-29T00:00:00Z",
    )
    assert result.status == "fail"
    assert result.findings[0]["gate_effect"] == "fail"


def test_summary_distinguishes_blocking_class_and_high_severity_causes() -> None:
    result = evaluate_policy(
        contract=contract(),
        findings=[
            finding(
                finding_id="finding-1",
                error_class="correctness",
                reproduction="unreproduced",
                severity="med",
            ),
            finding(
                finding_id="finding-2",
                error_class="fitness",
                reproduction="unreproduced",
                severity="high",
            ),
        ],
        claim_results=claims(),
        waiver_requests=[],
        issued_at="2026-07-29T00:00:00Z",
    )
    assert result.status == "needs_review"
    assert "blocking-class finding lacks completed reproduction" in result.summary
    assert "high-severity finding lacks completed reproduction" in result.summary


def test_summary_names_only_the_blocking_class_cause_when_alone() -> None:
    result = evaluate_policy(
        contract=contract(),
        findings=[finding(reproduction="unreproduced", severity="med")],
        claim_results=claims(),
        waiver_requests=[],
        issued_at="2026-07-29T00:00:00Z",
    )
    assert result.status == "needs_review"
    assert "blocking-class finding lacks completed reproduction" in result.summary
    assert "high-severity finding" not in result.summary
