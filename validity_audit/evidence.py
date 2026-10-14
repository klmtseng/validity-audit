"""Evidence discipline for schema 0.7.0 contracts and reviewer outputs.

Three primitives, adapted from REA (morluto/rea) evidence handling:

* **Evidence-kind requirement (P2).** A contract claim may declare
  ``required_evidence_kind``. A reviewer's ``supported`` outcome then counts only
  evidence whose kind satisfies that requirement under the fixed substitution
  table :data:`EVIDENCE_KIND_SATISFIES`. The table is code, not configuration:
  a contract cannot widen it.
* **Claim binding (P3).** Under a 0.7.0 reviewer output, an evidence item inside
  a claim result counts toward that claim only when its ``covers_claim_ids``
  names the claim. A single "the whole suite is green" item no longer closes
  every claim by being pasted into each result; it must enumerate them.
* **Absence coverage (P6).** A universal-negative conclusion (a claim or finding
  marked ``assertion: "absence"``) needs evidence carrying a ``coverage`` proof
  with ``status == "complete"``, ``truncated is False`` and ``omitted_count == 0``.

All three are fail-closed toward review: an unmet requirement downgrades a
``supported`` claim to ``inconclusive`` (which the policy turns into
``needs_review``), and an absence finding without coverage is gated as
unreproduced. A ``refuted`` claim is held to claim binding only: an unbound
refutation is downgraded to ``inconclusive`` and no longer forces its findings
to fail, while a bound refutation needs neither a particular kind nor a
complete search (one counterexample refutes), so its findings are not softened
by the absence rule. Downgrades never rewrite the reviewer's fields; the
policy's reasons are recorded only in ``evidence_gate``.
"""

from __future__ import annotations

import copy
from typing import Any

EVIDENCE_DISCIPLINE_VERSION = "0.7.0"

# Substitution table, read from the evidence side (same wording as the README):
#   command   satisfies command, file_line, note
#   file_line satisfies file_line, note
#   digest    satisfies digest, note
#   note      satisfies note
# Stored keyed by the required kind for lookup: evidence of kind E satisfies a
# requirement K iff E in EVIDENCE_KIND_SATISFIES[K].
# command (an executed check whose output was observed) is the strongest
# general kind; file_line (a located citation in an artifact) is next; note
# (a reviewer remark or second-hand account) is weakest. digest (a content
# hash) proves byte identity, not content, so it neither substitutes for nor
# is substituted by command/file_line.
EVIDENCE_KIND_SATISFIES: dict[str, frozenset[str]] = {
    "command": frozenset({"command"}),
    "file_line": frozenset({"command", "file_line"}),
    "digest": frozenset({"digest"}),
    "note": frozenset({"command", "file_line", "digest", "note"}),
}

# Embedded in the review bundle of a schema 0.7.0 contract only; legacy bundles
# are unchanged.
EVIDENCE_DISCIPLINE_INSTRUCTIONS: dict[str, str] = {
    "schema_version": (
        "This contract uses schema_version 0.7.0. Return reviewer output with "
        "schema_version 0.7.0; a 0.3.0 reviewer output is rejected at finalize."
    ),
    "claim_binding": (
        "Every evidence item inside a claim result must name that claim in "
        "covers_claim_ids. Evidence that does not name the claim does not count toward it, "
        "and a supported or refuted outcome with no claim-bound evidence is downgraded to "
        "inconclusive (a downgraded refutation does not turn its findings into fail). "
        "An evidence_id denotes one item: reuse it only with identical content, and only "
        "name claim ids that exist in the contract."
    ),
    "required_evidence_kind": (
        "A claim with required_evidence_kind can be supported only by claim-bound evidence "
        "whose kind satisfies it: command satisfies command, file_line, note; file_line "
        "satisfies file_line, note; digest satisfies digest, note; note satisfies note. "
        "Otherwise the supported outcome is downgraded to inconclusive."
    ),
    "absence": (
        "A claim or finding with assertion 'absence' concludes that something does not "
        "exist. Support it with evidence carrying coverage {scope, status, truncated, "
        "omitted_count}; only status complete, truncated false and omitted_count 0 proves "
        "absence. For an absence claim that also has required_evidence_kind, one and the "
        "same evidence item must both satisfy the kind and carry the complete coverage. "
        "Without proof an absence claim is not supported and an absence finding is gated "
        "as unreproduced, unless the finding backs a claim-bound refutation (one "
        "counterexample suffices to refute)."
    ),
}

MAX_DETAIL = 2000


class EvidenceDisciplineError(ValueError):
    """Raised when reviewer evidence is structurally inconsistent."""


def kind_satisfies(actual: str, required: str) -> bool:
    """Return whether evidence of kind ``actual`` meets a ``required`` kind."""
    return actual in EVIDENCE_KIND_SATISFIES[required]


def coverage_proves_absence(evidence: dict[str, Any]) -> bool:
    """Return whether one evidence item carries a complete coverage proof."""
    coverage = evidence.get("coverage")
    if not isinstance(coverage, dict):
        return False
    return (
        coverage.get("status") == "complete"
        and coverage.get("truncated") is False
        and coverage.get("omitted_count") == 0
        and isinstance(coverage.get("scope"), str)
        and bool(coverage["scope"].strip())
    )


def binding_enforced(reviewer_output: dict[str, Any]) -> bool:
    return reviewer_output.get("schema_version") == EVIDENCE_DISCIPLINE_VERSION


def check_versions(contract: dict[str, Any], reviewer_output: dict[str, Any]) -> None:
    """A 0.7.0 contract may only be reviewed by a 0.7.0 reviewer output.

    Its claim-level requirements are meaningless without claim-bound evidence,
    so a legacy reviewer output cannot silently bypass them.
    """
    if contract.get("schema_version") == EVIDENCE_DISCIPLINE_VERSION and not binding_enforced(
        reviewer_output
    ):
        raise EvidenceDisciplineError(
            "a schema_version 0.7.0 task contract requires a schema_version 0.7.0 reviewer "
            f"output; got {reviewer_output.get('schema_version')!r}"
        )


def check_evidence_consistency(
    contract: dict[str, Any],
    reviewer_output: dict[str, Any],
) -> None:
    """Reject unknown covered claim ids and divergent reuse of an evidence id."""
    claim_ids = {claim["claim_id"] for claim in contract["claims"]}
    seen: dict[str, dict[str, Any]] = {}
    items: list[tuple[str, dict[str, Any]]] = []
    for result in reviewer_output["claim_results"]:
        for evidence in result["evidence"]:
            items.append((f"claim {result['claim_id']!r}", evidence))
    for finding in reviewer_output["findings"]:
        for evidence in finding["evidence"]:
            items.append((f"finding {finding['finding_id']!r}", evidence))
    for where, evidence in items:
        unknown = sorted(set(evidence.get("covers_claim_ids", [])) - claim_ids)
        if unknown:
            raise EvidenceDisciplineError(
                f"evidence {evidence['evidence_id']!r} in {where} covers unknown claim ids: "
                f"{', '.join(unknown)}"
            )
        normalized = _normalize_evidence(evidence)
        previous = seen.get(evidence["evidence_id"])
        if previous is None:
            seen[evidence["evidence_id"]] = normalized
        elif previous != normalized:
            raise EvidenceDisciplineError(
                f"evidence id {evidence['evidence_id']!r} is reused in {where} with different "
                "content; one evidence id must denote one evidence item"
            )


def _normalize_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """covers_claim_ids is a set (uniqueItems); compare it order-insensitively."""
    normalized = dict(evidence)
    if "covers_claim_ids" in normalized:
        normalized["covers_claim_ids"] = sorted(normalized["covers_claim_ids"])
    return normalized


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def gate_claim_result(
    claim: dict[str, Any],
    result: dict[str, Any],
    *,
    enforce_binding: bool,
) -> dict[str, Any]:
    """Return the claim result, downgraded to inconclusive if evidence is insufficient.

    ``supported`` outcomes are checked against claim binding, the required evidence
    kind and absence coverage. ``refuted`` outcomes are checked against claim
    binding only: a refutation needs one counterexample, not a complete search
    or a particular evidence kind, but it must still name the claim it refutes.
    A downgrade never rewrites the reviewer's own fields (``rationale`` included);
    the policy's reasons live only in ``evidence_gate``.
    """
    outcome = result["outcome"]
    if outcome not in {"supported", "refuted"}:
        return result
    if outcome == "refuted" and not enforce_binding:
        return result
    claim_id = result["claim_id"]
    evidence = result["evidence"]
    if enforce_binding:
        counted = [item for item in evidence if claim_id in item.get("covers_claim_ids", [])]
    else:
        counted = list(evidence)

    reasons: list[dict[str, str]] = []
    if not counted:
        unbound = ", ".join(item["evidence_id"] for item in evidence) or "none"
        reasons.append(
            {
                "code": "no_claim_bound_evidence",
                "detail": _clip(
                    f"No evidence item names {claim_id!r} in covers_claim_ids "
                    f"(unbound evidence: {unbound}).",
                    MAX_DETAIL,
                ),
            }
        )
    if outcome == "refuted":
        return _downgrade(result, outcome, reasons) if reasons else result
    required = claim.get("required_evidence_kind")
    if required is not None and not any(
        kind_satisfies(item["kind"], required) for item in counted
    ):
        accepted = ", ".join(sorted(EVIDENCE_KIND_SATISFIES[required]))
        kinds = ", ".join(sorted({item["kind"] for item in counted})) or "none"
        reasons.append(
            {
                "code": "evidence_kind_insufficient",
                "detail": _clip(
                    f"Claim requires {required!r} evidence (accepted kinds: {accepted}); "
                    f"claim-bound evidence kinds: {kinds}.",
                    MAX_DETAIL,
                ),
            }
        )
    if claim.get("assertion") == "absence":
        # The coverage proof must come from evidence that also meets the kind
        # requirement: a complete-looking coverage block on a note plus a
        # separate uncovered command must not add up to proof.
        if required is None:
            proving = [item for item in counted if coverage_proves_absence(item)]
            detail = (
                "Absence claim lacks claim-bound evidence with a complete coverage proof "
                "(status complete, truncated false, omitted_count 0)."
            )
        else:
            proving = [
                item
                for item in counted
                if coverage_proves_absence(item) and kind_satisfies(item["kind"], required)
            ]
            detail = (
                "Absence claim lacks a single claim-bound evidence item that both satisfies "
                f"the {required!r} kind requirement and carries a complete coverage proof "
                "(status complete, truncated false, omitted_count 0)."
            )
        if not proving:
            reasons.append({"code": "absence_coverage_unproven", "detail": detail})
    if not reasons:
        return result
    return _downgrade(result, outcome, reasons)


def _downgrade(
    result: dict[str, Any],
    reviewer_outcome: str,
    reasons: list[dict[str, str]],
) -> dict[str, Any]:
    gated = copy.deepcopy(result)
    gated["reviewer_outcome"] = reviewer_outcome
    gated["outcome"] = "inconclusive"
    gated["evidence_gate"] = {"status": "insufficient", "reasons": reasons}
    return gated


def absence_finding_proven(finding: dict[str, Any]) -> bool:
    return any(coverage_proves_absence(item) for item in finding["evidence"])
