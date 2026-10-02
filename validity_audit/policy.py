"""Versioned error-class policy for v0.3 unsigned attestations."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime
from typing import Any

POLICY_ID = "validity-audit-default-v0.3.0"
ERROR_CLASS_EFFECTS = {
    "correctness": "fail",
    "evidence_tampering": "fail",
    "fabrication": "fail",
    "fitness": "advisory",
    "leakage": "fail",
    "material_requirement_miss": "fail",
    "unauthorized_action": "fail",
    "maintainability": "advisory",
}
NON_REPRODUCED = {"unreproduced", "not_reproducible", "not_attempted"}


class PolicyError(ValueError):
    """Raised when policy inputs or waivers are inconsistent."""


@dataclass(frozen=True)
class PolicyEvaluation:
    findings: list[dict[str, Any]]
    status: str
    summary: str


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _effects(contract: dict[str, Any]) -> dict[str, str]:
    effects = dict(ERROR_CLASS_EFFECTS)
    for override in contract.get("policy_overrides", []):
        effects[override["error_class"]] = override["gate_effect"]
    return effects


def _validate_error_classes(
    findings: list[dict[str, Any]],
    effects: dict[str, str],
) -> None:
    """Reject any finding whose error_class is not a policy-mapped slug.

    A finding's error_class must resolve to a configured gate effect at landing
    time (fixed defaults in ``ERROR_CLASS_EFFECTS`` or a contract
    ``policy_overrides`` entry). Previously an unmapped class silently became
    gate_effect "none" with a needs_review disposition; that let a typo or a
    novel class pass through undetected until a human read the summary. This
    is now a hard PolicyError so the contract author must either fix the class
    or add an explicit policy_overrides entry.
    """
    violations = [
        (finding["finding_id"], finding["error_class"])
        for finding in findings
        if finding["error_class"] not in effects
    ]
    if not violations:
        return
    allowed = ", ".join(sorted(effects))
    detail = "; ".join(
        f"{finding_id!r} declares error_class {error_class!r}"
        for finding_id, error_class in violations
    )
    raise PolicyError(
        f"unclassified error_class: {detail}. Allowed error classes: {allowed}. "
        "Add a policy_overrides entry to the task contract or correct the error_class."
    )


def _validate_waiver_issuers(
    contract: dict[str, Any],
    waiver_requests: list[dict[str, Any]],
) -> None:
    """Reject any waiver whose issuer the task contract has not pre-authorized.

    The task contract's optional ``waiver_issuers`` array is the only source of
    truth for who may issue a waiver on this bounded run. If any waiver request
    is present but the contract declares no waiver_issuers, or an issuer is
    present but not in that list, the run is rejected fail-closed rather than
    silently accepting whatever string the reviewer output supplied.
    """
    if not waiver_requests:
        return
    declared = contract.get("waiver_issuers") or []
    allowed = set(declared)
    if not allowed:
        raise PolicyError(
            "waiver requests were submitted but the task contract does not declare "
            "waiver_issuers; add a waiver_issuers array to the contract before any "
            "waiver can be accepted"
        )
    violations = [
        (waiver["finding_id"], waiver["issuer"])
        for waiver in waiver_requests
        if waiver["issuer"] not in allowed
    ]
    if violations:
        allowed_list = ", ".join(sorted(allowed))
        detail = "; ".join(
            f"{finding_id!r} waiver issuer {issuer!r}" for finding_id, issuer in violations
        )
        raise PolicyError(
            f"waiver issuer not permitted by the task contract: {detail}. "
            f"Permitted waiver_issuers: {allowed_list}"
        )


def evaluate_policy(
    *,
    contract: dict[str, Any],
    findings: list[dict[str, Any]],
    claim_results: list[dict[str, Any]],
    waiver_requests: list[dict[str, Any]],
    issued_at: str,
) -> PolicyEvaluation:
    """Assign every gate effect and derive the bounded run disposition."""
    effects = _effects(contract)
    _validate_error_classes(findings, effects)
    _validate_waiver_issuers(contract, waiver_requests)
    refuted_finding_ids = {
        finding_id
        for result in claim_results
        if result["outcome"] == "refuted"
        for finding_id in result["finding_ids"]
    }
    waiver_by_finding: dict[str, dict[str, Any]] = {}
    for waiver in waiver_requests:
        finding_id = waiver["finding_id"]
        if finding_id in waiver_by_finding:
            raise PolicyError(f"duplicate waiver request for {finding_id!r}")
        waiver_by_finding[finding_id] = waiver

    evaluated: list[dict[str, Any]] = []
    pending_blocking = False
    for raw_finding in findings:
        finding = copy.deepcopy(raw_finding)
        if "gate_effect" in finding or "waiver" in finding:
            raise PolicyError("gate_effect and waiver are policy outputs, not finder inputs")

        configured_effect = effects[finding["error_class"]]
        if finding["finding_id"] in refuted_finding_ids:
            configured_effect = "fail"
        reproduction = finding["reproduction"]
        waiver_request = waiver_by_finding.pop(finding["finding_id"], None)

        original_effect = (
            "none"
            if configured_effect == "fail" and reproduction in NON_REPRODUCED
            else configured_effect
        )
        # A high-severity finding that was never reproduced is a blocking
        # unknown regardless of its error class's default gate effect: an
        # advisory class (e.g. "fitness") must not let a high-severity,
        # unreproduced suspicion pass through silently as "advisory".
        high_severity_unreproduced = (
            finding["severity"] == "high" and reproduction in NON_REPRODUCED
        )

        if waiver_request is not None:
            if original_effect != "fail":
                raise PolicyError(
                    f"{finding['finding_id']!r} does not have a reproduced fail result "
                    "and cannot be waived"
                )
            issued = _parse_time(waiver_request["issued_at"])
            attested = _parse_time(issued_at)
            expires = _parse_time(waiver_request["expires_at"])
            if not issued <= attested < expires:
                raise PolicyError(
                    f"waiver for {finding['finding_id']!r} is not active at attestation time"
                )
            finding["gate_effect"] = "waiver"
            finding["waiver"] = {
                "issuer": waiver_request["issuer"],
                "reason": waiver_request["reason"],
                "original_policy_result": original_effect,
                "issued_at": waiver_request["issued_at"],
                "expires_at": waiver_request["expires_at"],
            }
        elif original_effect == "none" and configured_effect == "fail":
            finding["gate_effect"] = original_effect
            pending_blocking = True
        elif high_severity_unreproduced and configured_effect != "fail":
            finding["gate_effect"] = "none"
            pending_blocking = True
        else:
            finding["gate_effect"] = original_effect
        evaluated.append(finding)

    if waiver_by_finding:
        missing = ", ".join(sorted(waiver_by_finding))
        raise PolicyError(f"waiver requests reference unknown findings: {missing}")

    gate_effects = {finding["gate_effect"] for finding in evaluated}
    unresolved_claim = any(
        result["outcome"] in {"inconclusive", "not_evaluated"} for result in claim_results
    )
    if "fail" in gate_effects:
        status = "fail"
        summary = "One or more reproduced findings triggered a fail-class policy gate."
    elif pending_blocking or unresolved_claim:
        status = "needs_review"
        summary = (
            "A blocking-class finding lacks completed reproduction or a claim "
            "remains unresolved."
        )
    elif "waiver" in gate_effects:
        status = "pass_with_waiver"
        summary = "No unwaived fail gate remains; one or more active waivers are recorded."
    else:
        status = "pass"
        summary = "No finding triggered a fail gate and every claim received a final outcome."

    return PolicyEvaluation(findings=evaluated, status=status, summary=summary)
