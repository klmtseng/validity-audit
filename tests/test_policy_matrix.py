"""Combination matrix for the schema 0.7.0 evidence discipline.

Two fixes that withdrew a forced fail (F5: absence rule; H1: unbound
refutation) forgot that waiver validation downstream still expected that fail,
and finalize rejected the whole run. Then an exemption in this very matrix was
wide enough to hide a planted bug (mutant M2). So the module enumerates

* single-claim inputs: contract version x reviewer-output version x claim
  outcome x binding x claim requirement x evidence kind x finding shape
  (error class x reproduction x absence marker x coverage) x severity x cited x
  waiver, and
* two-claim, two-finding inputs: outcome pair x finding-shape pair x citation
  pattern x waiver target,

and checks on every schema-valid input:

(a) No new rejections: evaluating may raise only where the *legacy* evaluation
    (0.3.0 contract and reviewer output, every discipline field stripped)
    raises the same error under the general rule "a waiver must target a
    reproduced fail" (shapes E1/E2 below).
(a') The inputs the legacy evaluation rejects but the discipline accepts are
    exactly ``LEGACY_REJECTS_HEAD_ACCEPTS`` and never land on pass or
    pass_with_waiver.
(b) No movement toward pass: adding the absence markers, or the whole 0.7.0
    discipline, never makes the disposition less strict
    (fail > needs_review > pass_with_waiver > pass), except fail -> needs_review
    under the two named designs X1 and X2 (``allowed_relaxation``).
(c) Per-finding invariants, so an exemption in (b) cannot hide a finding that
    lost its own fail: see ``finding_invariant_violations``.

The matrix calls the functions finalize uses for its verdict
(``_review_findings``, ``_claim_results``, ``evaluate_policy``), schema-validates
every evaluated input, validates baseline inputs and recorded claim results and
findings on a fixed 1-in-8 sample (schema validation dominates run time), and
caches each verdict. ``protocol/matrix_mutants.py`` plants known policy bugs and
asserts this module catches every one.
"""

from __future__ import annotations

import copy
import itertools
from functools import lru_cache
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from validity_audit.policy import NON_REPRODUCED, PolicyError, evaluate_policy
from validity_audit.runtime import AuditRuntimeError, _claim_results, _review_findings
from validity_audit.schemas import load_schema

ISSUED = "2026-07-29T00:06:00Z"
COMPLETE = {"scope": "rg -n X over docs/", "status": "complete", "truncated": False,
            "omitted_count": 0}
WAIVER = {"finding_id": "f1", "issuer": "lead", "reason": "ok",
          "issued_at": "2026-07-29T00:00:00Z", "expires_at": "2026-08-29T00:00:00Z"}
RANK = {"pass": 0, "pass_with_waiver": 1, "needs_review": 2, "fail": 3}
FAIL_CLASS, ADVISORY_CLASS = "correctness", "fitness"


def _shape(error_class: str, reproduction: str, absence: bool = False, cov: bool = False) -> dict:
    return dict(error_class=error_class, reproduction=reproduction, absence=absence, cov=cov)


FINDING_SHAPES: dict[str, dict[str, Any]] = {
    "fail_repro": _shape(FAIL_CLASS, "reproduced"),
    "fail_repro_abs_unproven": _shape(FAIL_CLASS, "reproduced", absence=True),
    "fail_repro_abs_proven": _shape(FAIL_CLASS, "reproduced", absence=True, cov=True),
    "fail_unrepro": _shape(FAIL_CLASS, "unreproduced"),
    "fail_not_attempted": _shape(FAIL_CLASS, "not_attempted"),
    "fail_unrepro_abs": _shape(FAIL_CLASS, "unreproduced", absence=True),
    "adv_repro": _shape(ADVISORY_CLASS, "reproduced"),
    "adv_repro_abs_unproven": _shape(ADVISORY_CLASS, "reproduced", absence=True),
    "adv_not_reproducible": _shape(ADVISORY_CLASS, "not_reproducible"),
}
CLAIM_REQUIREMENTS = ["none", "kind_command", "absence_covered", "absence_uncovered"]

# A spec is hashable: (cver, rver, claims, findings, waived)
#   claims:   ((claim_id, outcome, bound, req, kind, cited_finding_ids), ...)
#   findings: ((finding_id, shape, severity), ...)
#   waived:   (finding_id, ...)


@lru_cache(maxsize=None)
def _validator(schema_name: str, definition: str | None = None) -> Draft202012Validator:
    schema = load_schema(schema_name)
    if definition is not None:
        schema = {"$ref": f"#/$defs/{definition}", "$defs": schema["$defs"]}
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _evidence(eid: str, kind: str, covers: list[str] | None, coverage: dict | None) -> dict:
    item = {"evidence_id": eid, "kind": kind, "description": "Synthetic evidence."}
    if covers is not None:
        item["covers_claim_ids"] = covers
    if coverage is not None:
        item["coverage"] = coverage
    return item


def build(spec: tuple, mode: str = "full") -> tuple[dict, dict]:
    """mode: full | no_absence (drop absence markers) | legacy (0.3.0, no discipline)."""
    cver, rver, claims, findings, waived = spec
    legacy = mode == "legacy"
    if legacy:
        cver = rver = "0.3.0"
    discipline = rver == "0.7.0"
    contract_claims, results = [], []
    for claim_id, outcome, bound, req, kind, cited in claims:
        claim = {"claim_id": claim_id, "statement": "s"}
        if not legacy and req == "kind_command":
            claim["required_evidence_kind"] = "command"
        if not legacy and req.startswith("absence") and mode == "full":
            claim["assertion"] = "absence"
        contract_claims.append(claim)
        covers = [claim_id] if (discipline and bound) else None
        coverage = COMPLETE if (discipline and req == "absence_covered") else None
        results.append({"claim_id": claim_id, "outcome": outcome,
                        "evidence": [_evidence(f"e_{claim_id}", kind, covers, coverage)],
                        "finding_ids": list(cited), "rationale": "R"})
    out_findings = []
    for finding_id, shape_name, severity in findings:
        shape = FINDING_SHAPES[shape_name]
        finding = {"finding_id": finding_id, "title": "t", "description": "d",
                   "error_class": shape["error_class"], "severity": severity,
                   "confidence": "high", "reproduction": shape["reproduction"],
                   "evidence": [_evidence(f"g_{finding_id}", "note", None,
                                          COMPLETE if (discipline and shape["cov"]) else None)]}
        if shape["reproduction"] != "reproduced":
            finding["reproduction_notes"] = "not reproduced"
        if discipline and shape["absence"] and mode == "full":
            finding["assertion"] = "absence"
        out_findings.append(finding)
    contract = {"schema_version": cver, "task_id": "m", "claims": contract_claims,
                "artifact_paths": ["docs/README.md"], "packs": ["docs"],
                "waiver_issuers": ["lead"]}
    output = {"schema_version": rver, "review_context": "cold",
              "reviewer": {"kind": "model", "label": "rev"}, "operator_id": "op",
              "claim_results": results, "findings": out_findings, "summary": "s"}
    if waived:
        output["waivers"] = [dict(copy.deepcopy(WAIVER), finding_id=fid) for fid in waived]
    return contract, output


def _evaluate(contract: dict, output: dict) -> tuple[Any, ...]:
    try:
        findings = _review_findings(output, {"findings": []}, "0" * 64)
        claim_results = _claim_results(contract, output, {f["finding_id"] for f in findings})
        policy = evaluate_policy(contract=contract, findings=findings,
                                 claim_results=claim_results,
                                 waiver_requests=output.get("waivers", []), issued_at=ISSUED)
    except (AuditRuntimeError, PolicyError) as exc:
        return "error", str(exc), (), None
    return "ok", policy.status, claim_results, policy.findings


@lru_cache(maxsize=None)
def verdict_of(spec: tuple, mode: str = "full") -> tuple[str, str, tuple]:
    """("ok", status, ((finding_id, gate_effect, unapplied_reason), ...)) or ("error", msg, ()).

    Inputs are schema-validated for every "full" evaluation. Schema validation
    dominates run time, so baseline inputs and recorded outputs are validated on
    a fixed sample by test_matrix_schema_validity_sample instead.
    """
    contract, output = build(spec, mode)
    if mode == "full":
        _validator("task_contract").validate(contract)
        _validator("reviewer_output").validate(output)
    kind, status, _, findings = _evaluate(contract, output)
    if kind == "error":
        return kind, status, ()
    gates = tuple(
        (f["finding_id"], f["gate_effect"],
         f.get("unapplied_waiver", {}).get("not_applied_because"))
        for f in findings
    )
    return kind, status, gates


def single_claim_specs() -> list[tuple]:
    rows = []
    for cver, rver, outcome, bound, req, kind, shape, severity, cited, waiver in itertools.product(
        ["0.3.0", "0.6.0", "0.7.0"], ["0.3.0", "0.7.0"],
        ["supported", "refuted", "inconclusive"], [True, False], CLAIM_REQUIREMENTS,
        ["command", "note"], [None, *FINDING_SHAPES], ["low", "high"], [True, False],
        [False, True],
    ):
        if cver == "0.7.0" and rver == "0.3.0":
            continue  # documented rejection; see test_new_contract_requires_new_reviewer_output
        if req != "none" and cver != "0.7.0":
            continue  # claim requirements are 0.7.0-only (schema)
        if kind == "note" and req != "kind_command":
            continue  # evidence kind only matters against a kind requirement
        if rver == "0.3.0" and (not bound or (shape and FINDING_SHAPES[shape]["absence"])):
            continue  # a 0.3.0 output cannot express binding or absence
        if shape is None and (cited or waiver or severity == "high"):
            continue
        if outcome == "refuted" and not cited:
            continue  # a refuted claim must cite a finding
        claims = (("c1", outcome, bound, req, kind, ("f1",) if cited else ()),)
        findings = (("f1", shape, severity),) if shape else ()
        rows.append((cver, rver, claims, findings, ("f1",) if waiver else ()))
    return rows


def two_claim_specs() -> list[tuple]:
    outcomes = {"supported": ("supported", True), "refuted_bound": ("refuted", True),
                "refuted_unbound": ("refuted", False)}
    shapes = ["fail_repro", "fail_repro_abs_unproven", "adv_repro", "adv_repro_abs_unproven"]
    citations = {"split": (("f1",), ("f2",)), "c2_both": (("f1",), ("f1", "f2")),
                 "c1_both": (("f1", "f2"), ("f2",))}
    rows = []
    for o1, o2, s1, s2, cite, waived in itertools.product(
        outcomes, outcomes, shapes, shapes, citations, [(), ("f2",)]
    ):
        c1_cites, c2_cites = citations[cite]
        claims = (("c1", *outcomes[o1], "none", "command", c1_cites),
                  ("c2", *outcomes[o2], "none", "command", c2_cites))
        findings = (("f1", s1, "low"), ("f2", s2, "high"))
        rows.append(("0.7.0", "0.7.0", claims, findings, waived))
    return rows


SPECS = single_claim_specs() + two_claim_specs()


def _effectively_bound(spec: tuple, claim: tuple) -> bool:
    return spec[1] == "0.3.0" or claim[2]


def _citers(spec: tuple, finding_id: str) -> list[tuple]:
    return [claim for claim in spec[2] if claim[1] == "refuted" and finding_id in claim[5]]


def legacy_waiver_rejection(spec: tuple) -> str | None:
    """Why the legacy rule "a waiver must target a reproduced fail" rejects spec."""
    for finding_id, shape_name, _ in spec[3]:
        if finding_id not in spec[4]:
            continue
        shape = FINDING_SHAPES[shape_name]
        if shape["reproduction"] in NON_REPRODUCED:
            return "E1: waiver on a finding the reviewer declared unreproduced"
        if shape["error_class"] == ADVISORY_CLASS and not _citers(spec, finding_id):
            return "E2: waiver on an advisory-class finding that no refutation forces to fail"
    return None


LEGACY_WAIVER_REJECTIONS = {
    "E1: waiver on a finding the reviewer declared unreproduced",
    "E2: waiver on an advisory-class finding that no refutation forces to fail",
}

# Inputs the legacy evaluation rejects but the 0.7.0 discipline accepts. After the
# R1 fix none remain: a waiver on a finding the reviewer declared unreproduced is
# rejected with or without the discipline.
LEGACY_REJECTS_HEAD_ACCEPTS: frozenset[tuple] = frozenset()


X2_REASON = (
    "X2: an uncovered absence finding cannot decide fail "
    "(README 'Evidence discipline', absence coverage bullet)"
)


def allowed_relaxation(spec: tuple) -> str | None:
    """Designed fail -> needs_review moves (never further toward pass).

    X1 is deliberately narrow: only an *advisory-class* finding loses the fail
    that the unbound refutation would have forced. A fail-class finding keeps its
    own fail (checked again per finding by I1).
    """
    if spec[1] != "0.7.0":
        return None
    for finding_id, shape_name, _ in spec[3]:
        shape = FINDING_SHAPES[shape_name]
        citers = _citers(spec, finding_id)
        bound_citers = [c for c in citers if _effectively_bound(spec, c)]
        if shape["error_class"] == ADVISORY_CLASS and citers and not bound_citers:
            return "X1 (D1): an unbound refutation no longer forces an advisory finding to fail"
        if (shape["absence"] and not shape["cov"] and shape["reproduction"] == "reproduced"
                and not bound_citers and (shape["error_class"] == FAIL_CLASS or citers)):
            return X2_REASON
    return None


def finding_invariant_violations(spec: tuple, gates: tuple) -> list[str]:
    """I1: a reviewer-reproduced fail-class finding that is not an uncovered absence
    finding, and has no waiver, fails. I2: a reviewer-reproduced finding cited by a
    claim-bound refutation, with no waiver, fails (D2 included). I3: an advisory
    finding cited only by unbound refutations does not fail (D1)."""
    gate_by_id = {finding_id: gate for finding_id, gate, _ in gates}
    problems = []
    for finding_id, shape_name, _ in spec[3]:
        shape = FINDING_SHAPES[shape_name]
        if finding_id in spec[4] or shape["reproduction"] != "reproduced":
            continue
        gate = gate_by_id[finding_id]
        citers = _citers(spec, finding_id)
        bound_citers = [c for c in citers if _effectively_bound(spec, c)]
        uncovered_absence = spec[1] == "0.7.0" and shape["absence"] and not shape["cov"]
        if shape["error_class"] == FAIL_CLASS and not uncovered_absence and gate != "fail":
            problems.append(f"I1 {finding_id}: fail-class reproduced finding gated {gate}")
        if bound_citers and gate != "fail":
            problems.append(f"I2 {finding_id}: cited by a bound refutation but gated {gate}")
        if (shape["error_class"] == ADVISORY_CLASS and citers and not bound_citers
                and gate == "fail"):
            problems.append(f"I3 {finding_id}: advisory, only unbound refutations, gated fail")
    return problems


def test_matrix_is_large_and_covers_every_dimension() -> None:
    assert len(SPECS) == 3616  # the count README.md and CHANGELOG.md state
    single = single_claim_specs()
    assert {s[0] for s in single} == {"0.3.0", "0.6.0", "0.7.0"}
    assert {s[1] for s in single} == {"0.3.0", "0.7.0"}
    assert {s[2][0][1] for s in single} == {"supported", "refuted", "inconclusive"}
    assert {s[2][0][3] for s in single} == set(CLAIM_REQUIREMENTS)
    assert {f[1] for s in single for f in s[3]} == set(FINDING_SHAPES)
    assert {f[2] for s in single for f in s[3]} == {"low", "high"}
    assert any(len(s[2]) == 2 and len(s[3]) == 2 for s in SPECS)


def test_matrix_schema_validity_sample() -> None:
    # Every 8th spec: baseline inputs are schema-valid, and the recorded claim
    # results and findings validate against the attestation schema.
    for spec in SPECS[::8]:
        for mode in ("full", "no_absence", "legacy"):
            contract, output = build(spec, mode)
            _validator("task_contract").validate(contract)
            _validator("reviewer_output").validate(output)
            kind, _, claim_results, findings = _evaluate(contract, output)
            if kind == "ok":
                for result in claim_results:
                    _validator("attestation", "claimResult").validate(result)
                for finding in findings:
                    _validator("attestation", "finding").validate(finding)


def test_matrix_no_new_rejections() -> None:
    failures = []
    for spec in SPECS:
        verdict = verdict_of(spec)
        if verdict[0] != "error":
            continue
        legacy = verdict_of(spec, "legacy")
        reason = legacy_waiver_rejection(spec)
        if legacy[:2] != verdict[:2] or reason is None or "cannot be waived" not in verdict[1]:
            failures.append(f"{spec}: {verdict[1]} (legacy: {legacy[:2]}; exemption: {reason})")
    assert not failures, f"{len(failures)} new rejections, e.g.\n" + "\n".join(failures[:10])


def test_matrix_legacy_waiver_rejections_are_exactly_the_listed_shapes() -> None:
    seen = set()
    for spec in SPECS:
        reason = legacy_waiver_rejection(spec)
        if reason is None:
            continue
        seen.add(reason)
        legacy = verdict_of(spec, "legacy")
        assert legacy[0] == "error" and "cannot be waived" in legacy[1], (spec, legacy)
    assert seen == LEGACY_WAIVER_REJECTIONS


def test_matrix_legacy_rejections_accepted_by_discipline_are_listed_and_never_pass() -> None:
    accepted = {}
    for spec in SPECS:
        if verdict_of(spec, "legacy")[0] == "error" and verdict_of(spec)[0] == "ok":
            accepted[spec] = verdict_of(spec)[1]
    assert not [s for s, status in accepted.items() if status in {"pass", "pass_with_waiver"}]
    assert frozenset(accepted) == LEGACY_REJECTS_HEAD_ACCEPTS, (
        f"{len(accepted)} unlisted, e.g. {list(accepted.items())[:5]}"
    )


@pytest.mark.parametrize("baseline_mode", ["no_absence", "legacy"])
def test_matrix_discipline_never_moves_toward_pass(baseline_mode: str) -> None:
    failures = []
    relaxations_used = set()
    for spec in SPECS:
        verdict = verdict_of(spec)
        baseline = verdict_of(spec, baseline_mode)
        if verdict[0] == "error" or baseline[0] == "error":
            continue  # covered by the rejection tests above
        if RANK[verdict[1]] >= RANK[baseline[1]]:
            continue
        reason = allowed_relaxation(spec)
        if reason and (baseline[1], verdict[1]) == ("fail", "needs_review"):
            relaxations_used.add(reason)
            continue
        failures.append(f"{spec}: {baseline[1]} -> {verdict[1]} (exemption: {reason})")
    assert not failures, f"{len(failures)} moves toward pass, e.g.\n" + "\n".join(failures[:10])
    if baseline_mode == "legacy":
        assert relaxations_used == {
            "X1 (D1): an unbound refutation no longer forces an advisory finding to fail",
            X2_REASON,
        }


def test_matrix_per_finding_invariants() -> None:
    failures = []
    for spec in SPECS:
        verdict = verdict_of(spec)
        if verdict[0] == "ok":
            failures += [f"{spec}: {p}" for p in finding_invariant_violations(spec, verdict[2])]
    assert not failures, f"{len(failures)} invariant violations, e.g.\n" + "\n".join(failures[:10])


def expected_waiver_outcome(spec: tuple, finding: tuple, claim_results: list) -> tuple:
    """(gate_effect, not_applied_because) a waived finding must get on an accepted input.

    Derived from the README rules, not from policy.py, and using the claim results
    finalize recorded (so an evidence-gate downgrade counts as unbound whatever
    caused it). A waiver is withheld only from a fail the discipline itself
    withheld: absence_coverage_unproven for an uncovered absence finding that
    would otherwise fail; refutation_unbound for a finding whose only fail came
    from a downgraded refutation. A finding that keeps its own fail-class fail
    takes the waiver, unbound refutation or not.
    """
    finding_id, shape_name, _ = finding
    shape = FINDING_SHAPES[shape_name]
    refuted = any(r["outcome"] == "refuted" and finding_id in r["finding_ids"]
                  for r in claim_results)
    unbound = not refuted and any(r.get("reviewer_outcome") == "refuted"
                                  and finding_id in r["finding_ids"] for r in claim_results)
    softened = spec[1] == "0.7.0" and shape["absence"] and not shape["cov"] and not refuted
    configured_fail = shape["error_class"] == FAIL_CLASS or refuted
    if softened and configured_fail:
        return "none", "absence_coverage_unproven"
    if unbound and not (configured_fail and not softened):
        # The advisory class keeps its own effect; a high-severity one the absence
        # rule made unreproduced is a blocking unknown (gate none, needs_review).
        high_unknown = softened and finding[2] == "high"
        return ("none" if high_unknown else "advisory"), "refutation_unbound"
    return "waiver", None


def test_matrix_waived_findings_get_exact_gate_and_reason() -> None:
    # Checks (b) and (c) skip waived findings and only rank dispositions, so a
    # waiver wrongly withheld (moving the run toward fail) or a swapped
    # not_applied_because code passed them (review of 4e13671, P1-1).
    failures, reasons_seen = [], set()
    for spec in SPECS:
        if not spec[4] or verdict_of(spec)[0] != "ok":
            continue
        contract, output = build(spec)
        _, _, claim_results, findings = _evaluate(contract, output)
        by_id = {f["finding_id"]: f for f in findings}
        for finding in spec[3]:
            if finding[0] not in spec[4]:
                continue
            got = by_id[finding[0]]
            actual = (got["gate_effect"],
                      got.get("unapplied_waiver", {}).get("not_applied_because"))
            expected = expected_waiver_outcome(spec, finding, claim_results)
            reasons_seen.add(expected[1])
            if actual != expected:
                failures.append(f"{spec}: {finding[0]} got {actual}, expected {expected}")
    assert not failures, f"{len(failures)} waived findings, e.g.\n" + "\n".join(failures[:10])
    assert reasons_seen == {None, "absence_coverage_unproven", "refutation_unbound"}


def test_waiver_on_unreproduced_finding_of_unbound_refutation_is_rejected_as_before() -> None:
    # R1: before the fix this landed needs_review with not_applied_because
    # "refutation_unbound", while legacy and the bound variant reject it.
    for shape in ("fail_unrepro", "adv_not_reproducible", "fail_not_attempted"):
        for bound in (True, False):
            spec = ("0.7.0", "0.7.0", (("c1", "refuted", bound, "none", "command", ("f1",)),),
                    (("f1", shape, "low"),), ("f1",))
            verdict = verdict_of(spec)
            assert verdict[0] == "error" and "cannot be waived" in verdict[1], (shape, bound)
            assert verdict[:2] == verdict_of(spec, "legacy")[:2]


def test_new_contract_requires_new_reviewer_output() -> None:
    spec = ("0.7.0", "0.3.0", (("c1", "supported", True, "none", "command", ()),), (), ())
    verdict = verdict_of(spec)
    assert verdict[0] == "error" and "0.7.0 reviewer output" in verdict[1]
