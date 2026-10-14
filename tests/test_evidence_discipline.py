"""Evidence discipline (schema 0.7.0): P2 evidence kind, P3 claim binding, P6 absence coverage.

Each primitive has
* a negative control: an input that the pre-0.7.0 behaviour accepts as
  ``pass`` (or decides as ``fail``) and that the 0.7.0 discipline blocks, and
* a positive control: qualifying evidence that still reaches a final verdict.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from validity_audit.evidence import (
    EVIDENCE_KIND_SATISFIES,
    coverage_proves_absence,
    kind_satisfies,
)
from validity_audit.policy import PolicyError, evaluate_policy
from validity_audit.runtime import AuditRuntimeError, finalize_run, prepare_run
from validity_audit.schemas import SchemaValidationError, validate_document

STARTED = "2026-07-29T00:00:00Z"
COMPLETED = "2026-07-29T00:05:00Z"
ISSUED = "2026-07-29T00:06:00Z"
COMPLETE = {"scope": "rg -n 'TODO' over docs/ (2 files)", "status": "complete",
            "truncated": False, "omitted_count": 0}


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def contract(version: str, claims: list[dict]) -> dict:
    return {
        "schema_version": version,
        "task_id": "evidence-discipline",
        "claims": claims,
        "artifact_paths": ["docs/README.md"],
        "packs": ["docs"],
    }


def evidence(evidence_id: str, kind: str = "note", covers: list[str] | None = None,
             coverage: dict | None = None) -> dict:
    item = {"evidence_id": evidence_id, "kind": kind, "description": "Synthetic evidence."}
    if covers is not None:
        item["covers_claim_ids"] = covers
    if coverage is not None:
        item["coverage"] = coverage
    return item


def claim_result(claim_id: str, items: list[dict], outcome: str = "supported",
                 finding_ids: list[str] | None = None) -> dict:
    return {"claim_id": claim_id, "outcome": outcome, "evidence": items,
            "finding_ids": finding_ids or []}


def reviewer(version: str, results: list[dict], findings: list[dict] | None = None) -> dict:
    return {
        "schema_version": version,
        "review_context": "cold",
        "reviewer": {"kind": "model", "label": "independent-reviewer"},
        "operator_id": "operator-1",
        "claim_results": results,
        "findings": findings or [],
        "summary": "Synthetic review.",
    }


def finding(finding_id: str, items: list[dict], *, absence: bool = False,
            error_class: str = "material_requirement_miss") -> dict:
    value = {
        "finding_id": finding_id,
        "title": "Figure has no source",
        "description": "No artifact produces the reported figure.",
        "error_class": error_class,
        "severity": "med",
        "confidence": "high",
        "reproduction": "reproduced",
        "evidence": items,
    }
    if absence:
        value["assertion"] = "absence"
    return value


def run(tmp_path: Path, task: dict, output: dict) -> dict:
    workspace = tmp_path / "workspace"
    (workspace / "docs").mkdir(parents=True)
    (workspace / "docs" / "README.md").write_text("# Demo\n", encoding="utf-8")
    write_json(workspace / "task.json", task)
    prepare_run(
        workspace=workspace,
        contract_path="task.json",
        run_dir=".validity-audit/runs/test-run",
        review_context="cold",
        reviewer_kind="model",
        reviewer_label="independent-reviewer",
        operator_id="operator-1",
        priming_sources=[],
        run_id="run-evidence-discipline",
        started_at=STARTED,
    )
    write_json(workspace / "reviewer-output.json", output)
    (workspace / "transcript.txt").write_bytes(b"Raw reviewer transcript.\n")
    finalize_run(
        workspace=workspace,
        run_dir=".validity-audit/runs/test-run",
        reviewer_output_path="reviewer-output.json",
        transcript_path="transcript.txt",
        completed_at=COMPLETED,
        issued_at=ISSUED,
        attestation_id="attestation-evidence-discipline",
        append_ledger=False,
    )
    attestation = json.loads(
        (workspace / ".validity-audit/runs/test-run/attestation.json").read_text()
    )
    validate_document(attestation, "attestation")
    return attestation


def gate_codes(attestation: dict, claim_id: str) -> list[str]:
    result = next(r for r in attestation["claim_results"] if r["claim_id"] == claim_id)
    return [reason["code"] for reason in result.get("evidence_gate", {}).get("reasons", [])]


# ---------------------------------------------------------------- P2: evidence kind


def test_p2_substitution_table_is_fixed_and_one_directional() -> None:
    assert EVIDENCE_KIND_SATISFIES == {
        "command": frozenset({"command"}),
        "file_line": frozenset({"command", "file_line"}),
        "digest": frozenset({"digest"}),
        "note": frozenset({"command", "file_line", "digest", "note"}),
    }
    assert kind_satisfies("command", "file_line")
    assert not kind_satisfies("file_line", "command")
    assert not kind_satisfies("note", "file_line")
    assert not kind_satisfies("digest", "file_line")
    assert not kind_satisfies("command", "digest")


def test_p2_negative_note_cannot_support_command_claim(tmp_path: Path) -> None:
    statement = "The --strict flag rejects malformed input."
    # Old behaviour: a 0.3.0 contract cannot express the requirement, and a
    # reviewer note is enough to reach pass.
    legacy = run(
        tmp_path / "legacy",
        contract("0.3.0", [{"claim_id": "c1", "statement": statement}]),
        reviewer("0.3.0", [claim_result("c1", [evidence("read-docs")])]),
    )
    assert legacy["overall_result"]["status"] == "pass"

    gated = run(
        tmp_path / "new",
        contract("0.7.0", [{"claim_id": "c1", "statement": statement,
                            "required_evidence_kind": "command"}]),
        reviewer("0.7.0", [claim_result("c1", [evidence("read-docs", "note", ["c1"])])]),
    )
    assert gated["overall_result"]["status"] == "needs_review"
    result = gated["claim_results"][0]
    assert result["outcome"] == "inconclusive"
    assert result["reviewer_outcome"] == "supported"
    assert gate_codes(gated, "c1") == ["evidence_kind_insufficient"]


def test_p2_negative_file_line_cannot_stand_in_for_command(tmp_path: Path) -> None:
    gated = run(
        tmp_path,
        contract("0.7.0", [{"claim_id": "c1", "statement": "s",
                            "required_evidence_kind": "command"}]),
        reviewer("0.7.0", [claim_result("c1", [evidence("cite", "file_line", ["c1"])])]),
    )
    assert gated["overall_result"]["status"] == "needs_review"
    assert gate_codes(gated, "c1") == ["evidence_kind_insufficient"]


@pytest.mark.parametrize(
    ("required", "actual"),
    [("command", "command"), ("file_line", "command"), ("file_line", "file_line"),
     ("digest", "digest"), ("note", "note")],
)
def test_p2_positive_sufficient_kind_supports(tmp_path: Path, required: str, actual: str) -> None:
    attestation = run(
        tmp_path,
        contract("0.7.0", [{"claim_id": "c1", "statement": "s",
                            "required_evidence_kind": required}]),
        reviewer("0.7.0", [claim_result("c1", [evidence("e1", actual, ["c1"])])]),
    )
    assert attestation["overall_result"]["status"] == "pass"
    assert attestation["claim_results"][0]["outcome"] == "supported"
    assert "evidence_gate" not in attestation["claim_results"][0]


def test_p2_legacy_contract_rejects_required_evidence_kind() -> None:
    with pytest.raises(SchemaValidationError):
        validate_document(
            contract("0.6.0", [{"claim_id": "c1", "statement": "s",
                                "required_evidence_kind": "command"}]),
            "task_contract",
        )


def test_p2_new_contract_requires_new_reviewer_output(tmp_path: Path) -> None:
    with pytest.raises(AuditRuntimeError, match="0.7.0 reviewer output"):
        run(
            tmp_path,
            contract("0.7.0", [{"claim_id": "c1", "statement": "s",
                                "required_evidence_kind": "command"}]),
            reviewer("0.3.0", [claim_result("c1", [evidence("e1", "command")])]),
        )


# ---------------------------------------------------------------- P3: claim binding


def two_claims(version: str) -> dict:
    return contract(version, [{"claim_id": "c1", "statement": "Parser is fixed."},
                              {"claim_id": "c2", "statement": "Docs are updated."}])


def test_p3_negative_one_green_check_cannot_close_every_claim(tmp_path: Path) -> None:
    # Old behaviour: the same "pytest green" item pasted into both results passes.
    green = evidence("pytest-green", "command")
    legacy = run(
        tmp_path / "legacy",
        two_claims("0.3.0"),
        reviewer("0.3.0", [claim_result("c1", [green]), claim_result("c2", [green])]),
    )
    assert legacy["overall_result"]["status"] == "pass"

    bound = evidence("pytest-green", "command", ["c1"])
    gated = run(
        tmp_path / "new",
        two_claims("0.7.0"),
        reviewer("0.7.0", [claim_result("c1", [bound]), claim_result("c2", [bound])]),
    )
    assert gated["overall_result"]["status"] == "needs_review"
    assert gate_codes(gated, "c1") == []
    assert gate_codes(gated, "c2") == ["no_claim_bound_evidence"]
    assert [r["outcome"] for r in gated["claim_results"]] == ["supported", "inconclusive"]


def test_p3_negative_unbound_evidence_is_not_counted_even_under_legacy_contract(
    tmp_path: Path,
) -> None:
    # A 0.7.0 reviewer output opts into binding even for a 0.3.0 contract.
    gated = run(
        tmp_path,
        two_claims("0.3.0"),
        reviewer("0.7.0", [claim_result("c1", [evidence("e1", "note", ["c1"])]),
                           claim_result("c2", [evidence("e2", "note")])]),
    )
    assert gated["overall_result"]["status"] == "needs_review"
    assert gate_codes(gated, "c2") == ["no_claim_bound_evidence"]


def test_p3_positive_evidence_that_enumerates_claims_supports_both(tmp_path: Path) -> None:
    shared = evidence("pytest-green", "command", ["c1", "c2"])
    attestation = run(
        tmp_path,
        two_claims("0.7.0"),
        reviewer("0.7.0", [claim_result("c1", [shared]), claim_result("c2", [shared])]),
    )
    assert attestation["overall_result"]["status"] == "pass"
    assert all(r["outcome"] == "supported" for r in attestation["claim_results"])


def test_p3_unknown_covered_claim_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(AuditRuntimeError, match="covers unknown claim ids: c9"):
        run(
            tmp_path,
            two_claims("0.7.0"),
            reviewer("0.7.0", [claim_result("c1", [evidence("e1", "command", ["c1", "c9"])]),
                               claim_result("c2", [evidence("e2", "command", ["c2"])])]),
        )


def test_p3_divergent_reuse_of_evidence_id_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(AuditRuntimeError, match="reused"):
        run(
            tmp_path,
            two_claims("0.7.0"),
            reviewer("0.7.0", [claim_result("c1", [evidence("e1", "command", ["c1"])]),
                               claim_result("c2", [evidence("e1", "command", ["c2"])])]),
        )


def test_p3_legacy_reviewer_output_rejects_binding_fields() -> None:
    output = reviewer("0.3.0", [claim_result("c1", [evidence("e1", "command", ["c1"])])])
    with pytest.raises(SchemaValidationError):
        validate_document(output, "reviewer_output")


# ---------------------------------------------------------------- P6: absence coverage


ABSENCE_CLAIM = {"claim_id": "c1", "statement": "No secret appears in docs/.",
                 "assertion": "absence"}


def test_p6_negative_absence_claim_without_coverage_cannot_be_supported(
    tmp_path: Path,
) -> None:
    legacy = run(
        tmp_path / "legacy",
        contract("0.3.0", [{"claim_id": "c1", "statement": ABSENCE_CLAIM["statement"]}]),
        reviewer("0.3.0", [claim_result("c1", [evidence("grep", "command")])]),
    )
    assert legacy["overall_result"]["status"] == "pass"

    gated = run(
        tmp_path / "new",
        contract("0.7.0", [ABSENCE_CLAIM]),
        reviewer("0.7.0", [claim_result("c1", [evidence("grep", "command", ["c1"])])]),
    )
    assert gated["overall_result"]["status"] == "needs_review"
    assert gate_codes(gated, "c1") == ["absence_coverage_unproven"]


@pytest.mark.parametrize(
    "override",
    [{"status": "partial"}, {"status": "unknown"}, {"truncated": True}, {"omitted_count": 3}],
)
def test_p6_negative_incomplete_coverage_does_not_prove_absence(
    tmp_path: Path, override: dict
) -> None:
    coverage = {**COMPLETE, **override}
    assert not coverage_proves_absence({"coverage": coverage})
    gated = run(
        tmp_path,
        contract("0.7.0", [ABSENCE_CLAIM]),
        reviewer("0.7.0", [claim_result("c1", [evidence("grep", "command", ["c1"], coverage)])]),
    )
    assert gated["overall_result"]["status"] == "needs_review"
    assert gate_codes(gated, "c1") == ["absence_coverage_unproven"]


def test_p6_negative_coverage_on_unbound_evidence_does_not_count(tmp_path: Path) -> None:
    gated = run(
        tmp_path,
        contract("0.7.0", [ABSENCE_CLAIM]),
        reviewer("0.7.0", [claim_result("c1", [
            evidence("bound-note", "note", ["c1"]),
            evidence("unbound-grep", "command", None, COMPLETE),
        ])]),
    )
    assert gate_codes(gated, "c1") == ["absence_coverage_unproven"]


def test_p6_positive_complete_coverage_supports_absence_claim(tmp_path: Path) -> None:
    attestation = run(
        tmp_path,
        contract("0.7.0", [ABSENCE_CLAIM]),
        reviewer("0.7.0", [claim_result("c1", [evidence("grep", "command", ["c1"], COMPLETE)])]),
    )
    assert attestation["overall_result"]["status"] == "pass"
    assert attestation["claim_results"][0]["outcome"] == "supported"


def test_p6_negative_absence_finding_without_coverage_cannot_decide_fail(
    tmp_path: Path,
) -> None:
    # A fail-class "no source found" finding that no refutation relies on:
    # without coverage it cannot decide fail on its own.
    claim = [{"claim_id": "c1", "statement": "The report is complete."}]
    ok = [claim_result("c1", [evidence("e", "note", ["c1"])])]
    plain = finding("f1", [evidence("search", "note")])
    legacy = run(tmp_path / "legacy", contract("0.3.0", claim),
                 reviewer("0.3.0", [claim_result("c1", [evidence("e", "note")])], [plain]))
    assert legacy["overall_result"]["status"] == "fail"

    gated = run(tmp_path / "new", contract("0.7.0", claim),
                reviewer("0.7.0", ok, [finding("f1", [evidence("search", "note")], absence=True)]))
    assert gated["overall_result"]["status"] == "needs_review"
    recorded = gated["findings"][0]
    assert recorded["absence_coverage"] == "unproven"
    assert recorded["gate_effect"] == "none"
    assert recorded["reproduction"] == "reproduced"  # reviewer's field is preserved
    assert recorded["effective_reproduction"] == "unreproduced"  # F3: what policy used
    assert "search-coverage proof" in gated["overall_result"]["summary"]


def test_p6_positive_absence_finding_with_coverage_still_fails(tmp_path: Path) -> None:
    claim = [{"claim_id": "c1", "statement": "Every reported figure has a source."}]
    search = evidence("search", "command", ["c1"], COMPLETE)
    attestation = run(
        tmp_path,
        contract("0.7.0", claim),
        reviewer("0.7.0", [claim_result("c1", [search], "refuted", ["f1"])],
                 [finding("f1", [search], absence=True)]),
    )
    assert attestation["overall_result"]["status"] == "fail"
    assert attestation["findings"][0]["absence_coverage"] == "proven"
    assert attestation["findings"][0]["gate_effect"] == "fail"


def test_p6_absence_coverage_is_a_policy_output_not_a_finder_input() -> None:
    raw = finding("f1", [evidence("e1")], absence=True)
    raw["absence_coverage"] = "proven"
    with pytest.raises(PolicyError, match="absence_coverage"):
        evaluate_policy(
            contract=contract("0.7.0", [{"claim_id": "c1", "statement": "s"}]),
            findings=[{**raw, "source": "cold_review"}],
            claim_results=[],
            waiver_requests=[],
            issued_at=ISSUED,
        )


def test_p6_legacy_reviewer_output_rejects_absence_fields() -> None:
    base = reviewer("0.3.0", [claim_result("c1", [evidence("e1")])],
                    [finding("f1", [evidence("e2")], absence=True)])
    with pytest.raises(SchemaValidationError):
        validate_document(base, "reviewer_output")
    coverage_only = copy.deepcopy(base)
    del coverage_only["findings"][0]["assertion"]
    coverage_only["findings"][0]["evidence"][0]["coverage"] = COMPLETE
    with pytest.raises(SchemaValidationError):
        validate_document(coverage_only, "reviewer_output")


# ------------------------------------------- review fixes (B2b, B11, B12, P2-4)


ABSENCE_COMMAND_CLAIM = {**ABSENCE_CLAIM, "required_evidence_kind": "command"}


def test_p6_negative_kind_and_coverage_split_across_two_items_is_not_proof(
    tmp_path: Path,
) -> None:
    # B2b: coverage hung on a note plus a separate uncovered command used to pass.
    gated = run(
        tmp_path,
        contract("0.7.0", [ABSENCE_COMMAND_CLAIM]),
        reviewer("0.7.0", [claim_result("c1", [
            evidence("n", "note", ["c1"], COMPLETE),
            evidence("cmd", "command", ["c1"]),
        ])]),
    )
    assert gated["overall_result"]["status"] == "needs_review"
    assert gate_codes(gated, "c1") == ["absence_coverage_unproven"]
    result = gated["claim_results"][0]
    assert "single claim-bound evidence item" in result["evidence_gate"]["reasons"][0]["detail"]


def test_p6_positive_one_command_item_with_complete_coverage_supports(tmp_path: Path) -> None:
    attestation = run(
        tmp_path,
        contract("0.7.0", [ABSENCE_COMMAND_CLAIM]),
        reviewer("0.7.0", [claim_result("c1", [evidence("cmd", "command", ["c1"], COMPLETE)])]),
    )
    assert attestation["overall_result"]["status"] == "pass"
    assert attestation["claim_results"][0]["outcome"] == "supported"


def test_p6_unproven_advisory_absence_finding_is_surfaced_on_pass(tmp_path: Path) -> None:
    # B11: an advisory low-severity absence finding does not block, but the pass
    # summary and the Markdown report must still show the unproven coverage.
    advisory = finding("f1", [evidence("e2", "note")], absence=True, error_class="fitness")
    advisory["severity"] = "low"
    attestation = run(
        tmp_path,
        contract("0.7.0", [{"claim_id": "c1", "statement": "s"}]),
        reviewer("0.7.0", [claim_result("c1", [evidence("e1", "note", ["c1"])])], [advisory]),
    )
    assert attestation["overall_result"]["status"] == "pass"
    assert attestation["findings"][0]["absence_coverage"] == "unproven"
    assert "absence_coverage: unproven" in attestation["overall_result"]["summary"]
    report = (tmp_path / "workspace/.validity-audit/runs/test-run/attestation.md").read_text()
    assert "(absence coverage unproven)" in report


def test_p6_reproduced_absence_finding_without_coverage_moves_fail_to_needs_review(
    tmp_path: Path,
) -> None:
    # B12: documented, intentional. Marking a reproduced fail-class finding as an
    # absence without coverage gates it toward review, not toward pass.
    plain = finding("f1", [evidence("g", "file_line")], error_class="correctness")
    claim = [{"claim_id": "c1", "statement": "s"}]
    ok = [claim_result("c1", [evidence("e", "note", ["c1"])])]
    baseline = run(tmp_path / "a", contract("0.7.0", claim), reviewer("0.7.0", ok, [plain]))
    assert baseline["overall_result"]["status"] == "fail"
    marked = run(tmp_path / "b", contract("0.7.0", claim),
                 reviewer("0.7.0", ok, [{**plain, "assertion": "absence"}]))
    assert marked["overall_result"]["status"] == "needs_review"
    assert marked["findings"][0]["gate_effect"] == "none"


def bundle_instructions(tmp_path: Path, version: str) -> dict:
    workspace = tmp_path / "workspace"
    (workspace / "docs").mkdir(parents=True)
    (workspace / "docs" / "README.md").write_text("# Demo\n", encoding="utf-8")
    write_json(workspace / "task.json", contract(version, [{"claim_id": "c1", "statement": "s"}]))
    prepare_run(
        workspace=workspace, contract_path="task.json", run_dir=".validity-audit/runs/r",
        review_context="cold", reviewer_kind="model", reviewer_label="r", operator_id="o",
        priming_sources=[], run_id="run-bundle", started_at=STARTED,
    )
    bundle = json.loads((workspace / ".validity-audit/runs/r/review_bundle.json").read_text())
    return bundle["instructions"]


def test_bundle_carries_evidence_discipline_instructions_only_for_0_7_0(
    tmp_path: Path,
) -> None:
    new = bundle_instructions(tmp_path / "new", "0.7.0")["evidence_discipline"]
    assert set(new) == {"schema_version", "claim_binding", "required_evidence_kind", "absence"}
    assert "schema_version 0.7.0" in new["schema_version"]
    assert "covers_claim_ids" in new["claim_binding"]
    assert "one and the same evidence item" in new["absence"]
    for version in ("0.3.0", "0.6.0"):
        legacy = bundle_instructions(tmp_path / version, version)
        assert set(legacy) == {"task", "policy_boundary", "transcript"}


# ------------------------------------- round-three fixes (D1-D4, F2-F4)
# Each test names the pre-fix behaviour (at 740a66e) it guards against.

WAIVER = {"finding_id": "f1", "issuer": "lead", "reason": "Accepted for this release.",
          "issued_at": "2026-07-29T00:00:00Z", "expires_at": "2026-08-29T00:00:00Z"}


def test_d2_bound_refutation_is_not_softened_by_absence_rule(tmp_path: Path) -> None:
    # PR4a/PR4b. Before: tagging the refutation's finding as an absence without
    # coverage softened fail to needs_review. After: fail either way.
    claim = [{"claim_id": "c1", "statement": "s"}]
    refuted = [claim_result("c1", [evidence("e", "file_line", ["c1"])], "refuted", ["f1"])]
    advisory = finding("f1", [evidence("g", "file_line")], error_class="fitness")
    plain = run(tmp_path / "a", contract("0.7.0", claim), reviewer("0.7.0", refuted, [advisory]))
    assert plain["overall_result"]["status"] == "fail"
    tagged = run(tmp_path / "b", contract("0.7.0", claim),
                 reviewer("0.7.0", refuted, [{**advisory, "assertion": "absence"}]))
    assert tagged["overall_result"]["status"] == "fail"
    recorded = tagged["findings"][0]
    assert recorded["gate_effect"] == "fail"
    assert recorded["absence_coverage"] == "not_required"
    assert "effective_reproduction" not in recorded


def test_d1_unbound_refutation_is_downgraded_and_does_not_force_fail(tmp_path: Path) -> None:
    # Before: a refuted claim whose evidence names no claim still forced its
    # finding to fail. After: inconclusive, finding keeps its own effect.
    claim = [{"claim_id": "c1", "statement": "s"}]
    advisory = finding("f1", [evidence("g", "file_line")], error_class="fitness")
    unbound = [claim_result("c1", [evidence("e", "file_line")], "refuted", ["f1"])]
    legacy = run(tmp_path / "legacy", contract("0.3.0", claim),
                 reviewer("0.3.0", unbound, [advisory]))
    assert legacy["overall_result"]["status"] == "fail"  # 0.3.0 output: binding not enforced

    gated = run(tmp_path / "new", contract("0.7.0", claim),
                reviewer("0.7.0", unbound, [advisory]))
    assert gated["overall_result"]["status"] == "needs_review"
    result = gated["claim_results"][0]
    assert result["outcome"] == "inconclusive"
    assert result["reviewer_outcome"] == "refuted"
    assert gate_codes(gated, "c1") == ["no_claim_bound_evidence"]
    assert gated["findings"][0]["gate_effect"] == "advisory"


def test_d1_refutation_needs_no_particular_kind(tmp_path: Path) -> None:
    claim = [{"claim_id": "c1", "statement": "s", "required_evidence_kind": "command"}]
    out = reviewer("0.7.0",
                   [claim_result("c1", [evidence("e", "note", ["c1"])], "refuted", ["f1"])],
                   [finding("f1", [evidence("g", "note")], error_class="fitness")])
    assert run(tmp_path, contract("0.7.0", claim), out)["overall_result"]["status"] == "fail"


def test_d3_downgrade_keeps_reviewer_rationale_verbatim(tmp_path: Path) -> None:
    # Before: the rationale was rewritten as "Policy downgraded ... Reviewer
    # rationale: ..." and clipped to 4000 characters.
    long_rationale = "x" * 3990 + " LIMIT-END"
    result = claim_result("c1", [evidence("e", "note")])
    result["rationale"] = long_rationale
    gated = run(tmp_path, two_claims("0.7.0"),
                reviewer("0.7.0", [result, claim_result("c2", [evidence("f", "note", ["c2"])])]))
    recorded = gated["claim_results"][0]
    assert recorded["outcome"] == "inconclusive"
    assert recorded["rationale"] == long_rationale
    assert recorded["evidence"] == [evidence("e", "note")]


def test_d3_downgrade_without_reviewer_rationale_adds_none(tmp_path: Path) -> None:
    gated = run(tmp_path, two_claims("0.7.0"),
                reviewer("0.7.0", [claim_result("c1", [evidence("e", "note")]),
                                   claim_result("c2", [evidence("f", "note", ["c2"])])]))
    assert "rationale" not in gated["claim_results"][0]
    assert gated["claim_results"][0]["evidence_gate"]["reasons"]


def test_d4_waiver_on_unproven_absence_finding_does_not_reject_run(tmp_path: Path) -> None:
    # PR9/PR9b. Before: finalize raised "cannot be waived" and no attestation
    # landed. After: needs_review, waiver kept on record but not applied.
    claim = [{"claim_id": "c1", "statement": "s"}]
    ok = [claim_result("c1", [evidence("e", "note", ["c1"])])]
    fail_f = finding("f1", [evidence("g", "file_line")], error_class="correctness")
    task = {**contract("0.7.0", claim), "waiver_issuers": ["lead"]}
    control = reviewer("0.7.0", ok, [fail_f])
    control["waivers"] = [WAIVER]
    assert run(tmp_path / "a", task, control)["overall_result"]["status"] == "pass_with_waiver"

    tagged = reviewer("0.7.0", ok, [{**fail_f, "assertion": "absence"}])
    tagged["waivers"] = [WAIVER]
    attestation = run(tmp_path / "b", task, tagged)
    assert attestation["overall_result"]["status"] == "needs_review"
    recorded = attestation["findings"][0]
    assert recorded["gate_effect"] == "none"
    assert "waiver" not in recorded
    assert recorded["unapplied_waiver"]["issuer"] == "lead"
    assert recorded["unapplied_waiver"]["not_applied_because"] == "absence_coverage_unproven"
    assert "not applied" in attestation["overall_result"]["summary"]


def test_f2_downgrade_is_visible_when_run_fails(tmp_path: Path) -> None:
    # PR5. Before: status fail and neither summary nor report named the downgrade.
    claim = [{"claim_id": "c1", "statement": "s", "required_evidence_kind": "command"}]
    out = reviewer("0.7.0", [claim_result("c1", [evidence("e", "note", ["c1"])])],
                   [finding("f1", [evidence("g", "file_line")], error_class="correctness")])
    attestation = run(tmp_path, contract("0.7.0", claim), out)
    assert attestation["overall_result"]["status"] == "fail"
    summary = attestation["overall_result"]["summary"]
    assert "downgraded the reviewer outcome of claim(s) c1" in summary
    report = (tmp_path / "workspace/.validity-audit/runs/test-run/attestation.md").read_text()
    assert "claim(s) c1" in report


def test_f4_reused_evidence_compares_covered_claims_as_a_set(tmp_path: Path) -> None:
    # PR6. Before: [c1, c2] vs [c2, c1] raised "reused ... with different content".
    attestation = run(
        tmp_path,
        two_claims("0.7.0"),
        reviewer("0.7.0", [claim_result("c1", [evidence("e", "command", ["c1", "c2"])]),
                           claim_result("c2", [evidence("e", "command", ["c2", "c1"])])]),
    )
    assert attestation["overall_result"]["status"] == "pass"


def test_policy_outputs_cannot_be_finder_inputs() -> None:
    for key, value in (("effective_reproduction", "unreproduced"),
                       ("unapplied_waiver", {"issuer": "x"})):
        raw = {**finding("f1", [evidence("e1")], absence=True), key: value,
               "source": "cold_review"}
        with pytest.raises(PolicyError, match="policy outputs"):
            evaluate_policy(contract=contract("0.7.0", [{"claim_id": "c1", "statement": "s"}]),
                            findings=[raw], claim_results=[], waiver_requests=[],
                            issued_at=ISSUED)


# ------------------------------------------ documented compatibility claims


def test_run_prepared_with_older_embedded_schema_cannot_be_finalized(tmp_path: Path) -> None:
    # README/CHANGELOG: bundles embed the reviewer-output schema, so a run prepared by an
    # earlier release (whose bundle embeds the 0.3.0-only schema) does not finalize here.
    from validity_audit.digests import sha256_file
    from validity_audit.runtime import EvidenceMismatchError

    workspace = tmp_path / "workspace"
    (workspace / "docs").mkdir(parents=True)
    (workspace / "docs" / "README.md").write_text("# Demo\n", encoding="utf-8")
    write_json(workspace / "task.json", contract("0.3.0", [{"claim_id": "c1", "statement": "s"}]))
    run_dir = ".validity-audit/runs/old"
    prepare_run(workspace=workspace, contract_path="task.json", run_dir=run_dir,
                review_context="cold", reviewer_kind="model", reviewer_label="r",
                operator_id="o", priming_sources=[], run_id="run-old", started_at=STARTED)
    bundle_path = workspace / run_dir / "review_bundle.json"
    bundle = json.loads(bundle_path.read_text())
    bundle["reviewer_output_schema"]["properties"]["schema_version"] = {"const": "0.3.0"}
    write_json(bundle_path, bundle)
    state_path = workspace / run_dir / "run_state.json"
    state = json.loads(state_path.read_text())
    state["review_bundle"]["sha256"] = sha256_file(bundle_path)
    write_json(state_path, state)

    output = reviewer("0.3.0", [claim_result("c1", [evidence("e")])])
    output["reviewer"] = {"kind": "model", "label": "r"}
    output["operator_id"] = "o"
    write_json(workspace / "out.json", output)
    (workspace / "t.txt").write_bytes(b"transcript\n")
    with pytest.raises(EvidenceMismatchError, match="reviewer_output_schema"):
        finalize_run(workspace=workspace, run_dir=run_dir, reviewer_output_path="out.json",
                     transcript_path="t.txt", completed_at=COMPLETED, issued_at=ISSUED,
                     append_ledger=False)


def test_prepare_and_finalize_inputs_must_be_inside_workspace(tmp_path: Path) -> None:
    # README: contract, run directory, reviewer output and transcript must resolve
    # inside --workspace.
    workspace = tmp_path / "workspace"
    (workspace / "docs").mkdir(parents=True)
    (workspace / "docs" / "README.md").write_text("# Demo\n", encoding="utf-8")
    task = contract("0.7.0", [{"claim_id": "c1", "statement": "s"}])
    write_json(workspace / "task.json", task)
    write_json(tmp_path / "outside-task.json", task)
    common = dict(review_context="cold", reviewer_kind="model",
                  reviewer_label="independent-reviewer", operator_id="operator-1",
                  priming_sources=[], run_id="run-x", started_at=STARTED)
    with pytest.raises(AuditRuntimeError, match="inside the workspace"):
        prepare_run(workspace=workspace, contract_path=str(tmp_path / "outside-task.json"),
                    run_dir=".validity-audit/runs/a", **common)
    with pytest.raises(AuditRuntimeError, match="inside the workspace"):
        prepare_run(workspace=workspace, contract_path="task.json",
                    run_dir=str(tmp_path / "outside-run"), **common)
    prepare_run(workspace=workspace, contract_path="task.json",
                run_dir=".validity-audit/runs/a", **common)
    output = reviewer("0.7.0", [claim_result("c1", [evidence("e", "note", ["c1"])])])
    write_json(workspace / "out.json", output)
    write_json(tmp_path / "outside-out.json", output)
    (workspace / "t.txt").write_bytes(b"transcript\n")
    (tmp_path / "outside-t.txt").write_bytes(b"transcript\n")
    for out_path, transcript in ((str(tmp_path / "outside-out.json"), "t.txt"),
                                 ("out.json", str(tmp_path / "outside-t.txt"))):
        with pytest.raises(AuditRuntimeError, match="inside the workspace"):
            finalize_run(workspace=workspace, run_dir=".validity-audit/runs/a",
                         reviewer_output_path=out_path, transcript_path=transcript,
                         completed_at=COMPLETED, issued_at=ISSUED, append_ledger=False)
