"""Combination matrix for the schema 0.7.0 evidence discipline.

Twice a fix that withdrew a forced fail (F5: absence rule; H1: unbound
refutation) forgot that waiver validation downstream still expected that fail,
and finalize rejected the whole run. Single-case tests did not catch either, so
this module enumerates

    contract version x reviewer-output version x claim outcome x claim binding
    x claim requirement x evidence kind x finding shape x cited-by-claim x waiver

and checks two properties on every schema-valid input:

(a) No new rejections. Evaluating the input must not raise, except where the
    *legacy* evaluation of the same input (0.3.0 contract and reviewer output,
    every discipline field stripped) raises the same error, i.e. a general rule
    that predates the evidence discipline. The only such rule in this matrix is
    "a waiver must target a reproduced fail"; its two shapes are listed in
    ``LEGACY_WAIVER_REJECTIONS`` and asserted explicitly.
(b) No movement toward pass. Adding the absence markers, or the whole 0.7.0
    discipline, never makes the disposition less strict
    (fail > needs_review > pass_with_waiver > pass), except for the designed
    fail -> needs_review moves named by ``allowed_relaxation`` (X1, X2).

The matrix calls the same functions finalize uses for its verdict
(``_review_findings``, ``_claim_results``, ``evaluate_policy``) plus schema
validation of every input and of the recorded claim results and findings, so it
stays fast; end-to-end finalize coverage of the same cases lives in
tests/test_evidence_discipline.py.
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

FINDING_SHAPES: dict[str, dict[str, Any] | None] = {
    "none": None,
    "fail_repro": dict(error_class="correctness", reproduction="reproduced", absence=False,
                       cov=False),
    "fail_repro_abs_unproven": dict(error_class="correctness", reproduction="reproduced",
                                    absence=True, cov=False),
    "fail_repro_abs_proven": dict(error_class="correctness", reproduction="reproduced",
                                  absence=True, cov=True),
    "fail_unrepro_abs": dict(error_class="correctness", reproduction="unreproduced",
                             absence=True, cov=False),
    "adv_repro": dict(error_class="fitness", reproduction="reproduced", absence=False, cov=False),
    "adv_repro_abs_unproven": dict(error_class="fitness", reproduction="reproduced",
                                   absence=True, cov=False),
}
CLAIM_REQUIREMENTS = ["none", "kind_command", "absence_covered", "absence_uncovered"]


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


def build(spec: dict, *, mode: str = "full") -> tuple[dict, dict]:
    """mode: full | no_absence (drop absence markers) | legacy (0.3.0, no discipline)."""
    legacy = mode == "legacy"
    cver = "0.3.0" if legacy else spec["cver"]
    rver = "0.3.0" if legacy else spec["rver"]
    discipline = rver == "0.7.0"
    claim = {"claim_id": "c1", "statement": "s"}
    req = spec["req"]
    if not legacy:
        if req == "kind_command":
            claim["required_evidence_kind"] = "command"
        if req.startswith("absence") and mode == "full":
            claim["assertion"] = "absence"
    contract = {"schema_version": cver, "task_id": "m", "claims": [claim],
                "artifact_paths": ["docs/README.md"], "packs": ["docs"],
                "waiver_issuers": ["lead"]}
    covers = ["c1"] if (discipline and spec["bound"]) else None
    coverage = COMPLETE if (discipline and req == "absence_covered") else None
    result = {"claim_id": "c1", "outcome": spec["outcome"],
              "evidence": [_evidence("e1", spec["kind"], covers, coverage)],
              "finding_ids": ["f1"] if spec["cited"] else [], "rationale": "R"}
    findings = []
    shape = FINDING_SHAPES[spec["finding"]]
    if shape:
        finding = {"finding_id": "f1", "title": "t", "description": "d",
                   "error_class": shape["error_class"], "severity": "med",
                   "confidence": "high", "reproduction": shape["reproduction"],
                   "evidence": [_evidence("g1", "note", None,
                                          COMPLETE if (discipline and shape["cov"]) else None)]}
        if shape["reproduction"] != "reproduced":
            finding["reproduction_notes"] = "not reproduced"
        if discipline and shape["absence"] and mode == "full":
            finding["assertion"] = "absence"
        findings.append(finding)
    output = {"schema_version": rver, "review_context": "cold",
              "reviewer": {"kind": "model", "label": "rev"}, "operator_id": "op",
              "claim_results": [result], "findings": findings, "summary": "s"}
    if spec["waiver"]:
        output["waivers"] = [copy.deepcopy(WAIVER)]
    return contract, output


def evaluate(contract: dict, output: dict) -> tuple[str, str]:
    """Return ("ok", status) or ("error", message), as finalize would decide."""
    _validator("task_contract").validate(contract)
    _validator("reviewer_output").validate(output)
    try:
        findings = _review_findings(output, {"findings": []}, "0" * 64)
        claim_results = _claim_results(
            contract, output, {finding["finding_id"] for finding in findings}
        )
        policy = evaluate_policy(contract=contract, findings=findings,
                                 claim_results=claim_results,
                                 waiver_requests=output.get("waivers", []), issued_at=ISSUED)
    except (AuditRuntimeError, PolicyError) as exc:
        return "error", str(exc)
    for result in claim_results:
        _validator("attestation", "claimResult").validate(result)
    for finding in policy.findings:
        _validator("attestation", "finding").validate(finding)
    return "ok", policy.status


def specs() -> list[dict]:
    rows = []
    for cver, rver, outcome, bound, req, kind, finding, cited, waiver in itertools.product(
        ["0.3.0", "0.6.0", "0.7.0"], ["0.3.0", "0.7.0"],
        ["supported", "refuted", "inconclusive"], [True, False], CLAIM_REQUIREMENTS,
        ["command", "note"], list(FINDING_SHAPES), [True, False], [False, True],
    ):
        if cver == "0.7.0" and rver == "0.3.0":
            continue  # documented rejection; see test_new_contract_requires_new_reviewer_output
        if req != "none" and cver != "0.7.0":
            continue  # claim requirements are 0.7.0-only (schema)
        if rver == "0.3.0" and (not bound or (FINDING_SHAPES[finding] or {}).get("absence")):
            continue  # 0.3.0 output cannot express binding or absence
        if finding == "none" and (cited or waiver):
            continue
        if outcome == "refuted" and not cited:
            continue  # a refuted claim must cite a finding
        rows.append(dict(cver=cver, rver=rver, outcome=outcome, bound=bound, req=req, kind=kind,
                         finding=finding, cited=cited, waiver=waiver))
    return rows


SPECS = specs()
_KEYS = ("cver", "rver", "outcome", "bound", "req", "kind", "finding", "cited", "waiver")


@lru_cache(maxsize=None)
def _cached(key: tuple, mode: str) -> tuple[str, str]:
    return evaluate(*build(dict(zip(_KEYS, key)), mode=mode))


def verdict_of(spec: dict, mode: str = "full") -> tuple[str, str]:
    return _cached(tuple(spec[key] for key in _KEYS), mode)


def _id(spec: dict) -> str:
    return "-".join(str(spec[key]) for key in spec)


def _shape(spec: dict) -> dict:
    return FINDING_SHAPES[spec["finding"]] or {}


def legacy_waiver_rejection(spec: dict) -> str | None:
    """Return why the legacy rule "a waiver must target a reproduced fail" rejects spec."""
    if not spec["waiver"]:
        return None
    shape = _shape(spec)
    if shape.get("reproduction") in NON_REPRODUCED:
        return "E1: waiver on a finding the reviewer declared unreproduced"
    refuted_cites = spec["outcome"] == "refuted" and spec["cited"]
    if shape.get("error_class") == "fitness" and not refuted_cites:
        return "E2: waiver on an advisory-class finding that no refutation forces to fail"
    return None


LEGACY_WAIVER_REJECTIONS = (
    "E1: waiver on a finding the reviewer declared unreproduced",
    "E2: waiver on an advisory-class finding that no refutation forces to fail",
)


def allowed_relaxation(spec: dict) -> str | None:
    """Designed fail -> needs_review moves (never further toward pass)."""
    if spec["rver"] != "0.7.0":
        return None
    shape = _shape(spec)
    bound_refutation = spec["outcome"] == "refuted" and spec["bound"] and spec["cited"]
    if spec["outcome"] == "refuted" and not spec["bound"]:
        return "X1 (D1): an unbound refutation no longer forces its findings to fail"
    if (shape.get("absence") and not shape.get("cov") and shape.get("reproduction") == "reproduced"
            and not bound_refutation):
        return "X2: an uncovered absence finding cannot decide fail (README B12 paragraph)"
    return None


def test_matrix_is_large_and_covers_every_dimension() -> None:
    assert len(SPECS) > 1000
    for key in ("cver", "rver", "outcome", "bound", "req", "kind", "finding", "cited", "waiver"):
        assert len({spec[key] for spec in SPECS}) > 1, key


def test_matrix_no_new_rejections() -> None:
    failures = []
    for spec in SPECS:
        verdict = verdict_of(spec)
        if verdict[0] != "error":
            continue
        legacy = verdict_of(spec, "legacy")
        reason = legacy_waiver_rejection(spec)
        if legacy != verdict or reason is None or "cannot be waived" not in verdict[1]:
            failures.append(f"{_id(spec)}: {verdict[1]} (legacy: {legacy}; exemption: {reason})")
    assert not failures, f"{len(failures)} new rejections, e.g.\n" + "\n".join(failures[:10])


def test_matrix_legacy_waiver_rejections_are_exactly_the_listed_shapes() -> None:
    # The exemptions in (a) must stay what they say: every listed shape is
    # rejected by the legacy evaluation too, with the same message.
    seen = set()
    for spec in SPECS:
        reason = legacy_waiver_rejection(spec)
        if reason is None:
            continue
        seen.add(reason)
        legacy = verdict_of(spec, "legacy")
        assert legacy[0] == "error" and "cannot be waived" in legacy[1], (_id(spec), legacy)
    assert seen == set(LEGACY_WAIVER_REJECTIONS)


@pytest.mark.parametrize("baseline_mode", ["no_absence", "legacy"])
def test_matrix_discipline_never_moves_toward_pass(baseline_mode: str) -> None:
    failures = []
    relaxations_used = set()
    for spec in SPECS:
        verdict = verdict_of(spec)
        baseline = verdict_of(spec, baseline_mode)
        if verdict[0] == "error" or baseline[0] == "error":
            continue  # (a) covers errors
        if RANK[verdict[1]] >= RANK[baseline[1]]:
            continue
        reason = allowed_relaxation(spec)
        if reason and (baseline[1], verdict[1]) == ("fail", "needs_review"):
            relaxations_used.add(reason)
            continue
        failures.append(f"{_id(spec)}: {baseline[1]} -> {verdict[1]}")
    assert not failures, f"{len(failures)} moves toward pass, e.g.\n" + "\n".join(failures[:10])
    if baseline_mode == "legacy":
        assert relaxations_used == {
            "X1 (D1): an unbound refutation no longer forces its findings to fail",
            "X2: an uncovered absence finding cannot decide fail (README B12 paragraph)",
        }


def test_new_contract_requires_new_reviewer_output() -> None:
    spec = dict(cver="0.7.0", rver="0.3.0", outcome="supported", bound=True, req="none",
                kind="command", finding="none", cited=False, waiver=False)
    verdict = evaluate(*build(spec))
    assert verdict[0] == "error" and "0.7.0 reviewer output" in verdict[1]
