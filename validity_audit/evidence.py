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

All three are fail-closed toward review, never toward pass: an unmet
requirement downgrades a ``supported`` claim to ``inconclusive`` (which the
policy turns into ``needs_review``), and an absence finding without coverage is
gated as unreproduced. Refuted outcomes are not downgraded here, because doing
so could only weaken a fail verdict.
"""

from __future__ import annotations

import copy
from typing import Any

EVIDENCE_DISCIPLINE_VERSION = "0.7.0"

# required kind -> evidence kinds accepted for it. Read as "a claim that
# requires K may be supported by any kind in EVIDENCE_KIND_SATISFIES[K]".
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

MAX_RATIONALE = 4000
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
        previous = seen.get(evidence["evidence_id"])
        if previous is None:
            seen[evidence["evidence_id"]] = evidence
        elif previous != evidence:
            raise EvidenceDisciplineError(
                f"evidence id {evidence['evidence_id']!r} is reused in {where} with different "
                "content; one evidence id must denote one evidence item"
            )


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def gate_claim_result(
    claim: dict[str, Any],
    result: dict[str, Any],
    *,
    enforce_binding: bool,
) -> dict[str, Any]:
    """Return the claim result, downgraded to inconclusive if evidence is insufficient."""
    if result["outcome"] != "supported":
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
    if claim.get("assertion") == "absence" and not any(
        coverage_proves_absence(item) for item in counted
    ):
        reasons.append(
            {
                "code": "absence_coverage_unproven",
                "detail": (
                    "Absence claim lacks claim-bound evidence with a complete coverage proof "
                    "(status complete, truncated false, omitted_count 0)."
                ),
            }
        )
    if not reasons:
        return result

    gated = copy.deepcopy(result)
    gated["reviewer_outcome"] = "supported"
    gated["outcome"] = "inconclusive"
    gated["evidence_gate"] = {"status": "insufficient", "reasons": reasons}
    codes = ", ".join(reason["code"] for reason in reasons)
    rationale = f"Policy downgraded the reviewer's supported outcome: {codes}."
    if "rationale" in result:
        rationale += f" Reviewer rationale: {result['rationale']}"
    gated["rationale"] = _clip(rationale, MAX_RATIONALE)
    return gated


def absence_finding_proven(finding: dict[str, Any]) -> bool:
    return any(coverage_proves_absence(item) for item in finding["evidence"])
