from __future__ import annotations

import json
from pathlib import Path

import pytest

from validity_audit.digests import sha256_file
from validity_audit.runtime import AuditRuntimeError, finalize_run, prepare_run
from validity_audit.schemas import validate_document

STARTED = "2026-07-29T00:00:00Z"
COMPLETED = "2026-07-29T00:05:00Z"
ISSUED = "2026-07-29T00:06:00Z"


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def make_workspace(tmp_path: Path, *, broken_link: bool = False) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / "docs").mkdir(parents=True)
    target = "missing.md" if broken_link else "details.md"
    (workspace / "docs" / "README.md").write_text(
        f"# Demo\n\n[Details]({target})\n",
        encoding="utf-8",
    )
    (workspace / "docs" / "details.md").write_text("# Details\n", encoding="utf-8")
    write_json(
        workspace / "task.json",
        {
            "$schema": "schemas/task_contract.schema.json",
            "schema_version": "0.3.0",
            "task_id": "runtime-test",
            "claims": [
                {
                    "claim_id": "links-resolve",
                    "statement": "All relative links resolve.",
                }
            ],
            "artifact_paths": ["docs/README.md", "docs/details.md"],
            "packs": ["docs"],
        },
    )
    return workspace


def reviewer_output(
    *,
    outcome: str = "supported",
    findings: list[dict] | None = None,
    context: str = "cold",
) -> dict:
    result = {
        "$schema": "schemas/reviewer_output.schema.json",
        "schema_version": "0.3.0",
        "review_context": context,
        "reviewer": {"kind": "model", "label": "independent-reviewer"},
        "operator_id": "operator-1",
        "claim_results": [
            {
                "claim_id": "links-resolve",
                "outcome": outcome,
                "evidence": [
                    {
                        "evidence_id": "review-evidence",
                        "kind": "note",
                        "description": "The artifact snapshots were inspected.",
                    }
                ],
                "finding_ids": [
                    finding["finding_id"] for finding in (findings or [])
                ],
            }
        ],
        "findings": findings or [],
        "summary": "Independent review completed.",
    }
    if outcome in {"inconclusive", "not_evaluated"}:
        result["claim_results"][0]["evidence"] = []
        result["claim_results"][0]["rationale"] = "The available evidence was incomplete."
    return result


def review_finding(
    *,
    finding_id: str = "review-finding-1",
    error_class: str = "fabrication",
    reproduction: str = "reproduced",
) -> dict:
    value = {
        "finding_id": finding_id,
        "title": "Reviewer finding",
        "description": "A bounded synthetic finding.",
        "error_class": error_class,
        "severity": "high",
        "confidence": "high",
        "reproduction": reproduction,
        "evidence": [
            {
                "evidence_id": f"evidence-{finding_id}",
                "kind": "note",
                "description": "Reviewer evidence.",
            }
        ],
    }
    if reproduction != "reproduced":
        value["reproduction_notes"] = "Reproduction was not completed."
    return value


def prepare(workspace: Path, *, context: str = "cold") -> dict:
    return prepare_run(
        workspace=workspace,
        contract_path="task.json",
        run_dir=".validity-audit/runs/test-run",
        review_context=context,
        reviewer_kind="model",
        reviewer_label="independent-reviewer",
        operator_id="operator-1",
        priming_sources=["published key"] if context == "primed" else [],
        run_id="run-runtime-test-001",
        started_at=STARTED,
    )


def finalize(
    workspace: Path,
    output: dict,
    *,
    append_ledger: bool = True,
) -> dict:
    write_json(workspace / "reviewer-output.json", output)
    (workspace / "transcript.txt").write_bytes(b"Raw reviewer transcript.\n")
    return finalize_run(
        workspace=workspace,
        run_dir=".validity-audit/runs/test-run",
        reviewer_output_path="reviewer-output.json",
        transcript_path="transcript.txt",
        completed_at=COMPLETED,
        issued_at=ISSUED,
        attestation_id="attestation-runtime-test-001",
        append_ledger=append_ledger,
    )


def test_prepare_emits_digest_bound_bundle_and_state(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    (workspace / "domains").mkdir()
    (workspace / "domains/docs.md").write_text("# Docs pack\n", encoding="utf-8")
    result = prepare(workspace)
    run_dir = workspace / result["run_dir"]
    state = json.loads((run_dir / "run_state.json").read_text())
    bundle = json.loads((run_dir / "review_bundle.json").read_text())

    assert result["state"] == "prepared"
    assert state["review_bundle"]["sha256"] == sha256_file(run_dir / "review_bundle.json")
    assert state["artifact_manifest"]["manifest_sha256"] == result["manifest_sha256"]
    assert bundle["contract_sha256"] == sha256_file(workspace / "task.json")
    assert bundle["excluded_context"] == ["answer keys", "miss ledger", "builder hint list"]
    assert bundle["artifacts"][0]["content"]
    assert bundle["pack_snapshots"][0]["status"] == "embedded"
    assert bundle["pack_snapshots"][0]["content"] == "# Docs pack\n"
    assert bundle["reviewer_output_schema"]["$id"].endswith(
        "reviewer_output.schema.json"
    )
    assert result["probe_findings"] == 0


def test_prepare_primed_bundle_records_sources(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    result = prepare(workspace, context="primed")
    bundle = json.loads(
        (workspace / result["review_bundle"]).read_text(encoding="utf-8")
    )
    assert bundle["review_context"] == "primed"
    assert bundle["priming_sources"] == ["published key"]
    assert "excluded_context" not in bundle


def test_prepare_rejects_cold_priming(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    with pytest.raises(AuditRuntimeError, match="cold review"):
        prepare_run(
            workspace=workspace,
            contract_path="task.json",
            run_dir=".validity-audit/runs/test-run",
            review_context="cold",
            reviewer_kind="model",
            reviewer_label="reviewer",
            operator_id="operator",
            priming_sources=["answer key"],
            run_id="run-test",
            started_at=STARTED,
        )


def test_prepare_rejects_non_rfc3339_timestamp(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    with pytest.raises(AuditRuntimeError, match="RFC 3339"):
        prepare_run(
            workspace=workspace,
            contract_path="task.json",
            run_dir=".validity-audit/runs/test-run",
            review_context="cold",
            reviewer_kind="model",
            reviewer_label="reviewer",
            operator_id="operator",
            started_at="2026-07-29 00:00:00+00:00",
        )


def test_prepare_rejects_symlinked_artifact(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    target = workspace / "docs/details.md"
    target.rename(workspace / "docs/real-details.md")
    try:
        target.symlink_to("real-details.md")
    except OSError:
        pytest.skip("symbolic links are unavailable")
    with pytest.raises(AuditRuntimeError, match="symbolic link"):
        prepare(workspace)


def test_finalize_retains_transcript_and_validates_attestation(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    prepare(workspace)
    result = finalize(workspace, reviewer_output())
    run_dir = workspace / ".validity-audit/runs/test-run"
    attestation = json.loads((run_dir / "attestation.json").read_text())
    state = json.loads((run_dir / "run_state.json").read_text())

    assert result["state"] == "finalized"
    assert result["status"] == "pass"
    assert (run_dir / "evidence/reviewer_transcript.txt").read_bytes() == (
        workspace / "transcript.txt"
    ).read_bytes()
    assert attestation["review"]["transcript_sha256"] == sha256_file(
        run_dir / "evidence/reviewer_transcript.txt"
    )
    assert attestation["signature"] is None
    assert attestation["overall_result"]["policy_id"] == "validity-audit-default-v0.3.0"
    assert state["state"] == "finalized"
    validate_document(attestation, "attestation")

    ledger = workspace / ".validity-audit/attestations.jsonl"
    records = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert records[0]["attestation_sha256"] == sha256_file(run_dir / "attestation.json")


def test_policy_engine_is_sole_gate_effect_writer(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    prepare(workspace)
    output = reviewer_output(findings=[review_finding()])
    output["findings"][0]["gate_effect"] = "none"
    write_json(workspace / "reviewer-output.json", output)
    (workspace / "transcript.txt").write_text("Transcript.\n")
    with pytest.raises(AuditRuntimeError, match="reviewer_output validation failed"):
        finalize_run(
            workspace=workspace,
            run_dir=".validity-audit/runs/test-run",
            reviewer_output_path="reviewer-output.json",
            transcript_path="transcript.txt",
            completed_at=COMPLETED,
            issued_at=ISSUED,
            append_ledger=False,
        )


def test_blocking_reviewer_finding_fails(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    prepare(workspace)
    result = finalize(
        workspace,
        reviewer_output(outcome="refuted", findings=[review_finding()]),
        append_ledger=False,
    )
    attestation = json.loads(
        (workspace / result["attestation"]).read_text(encoding="utf-8")
    )
    assert result["status"] == "fail"
    assert attestation["findings"][0]["gate_effect"] == "fail"
    assert attestation["findings"][0]["source"] == "cold_review"


def test_not_attempted_blocking_finding_needs_review(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    prepare(workspace)
    result = finalize(
        workspace,
        reviewer_output(
            outcome="inconclusive",
            findings=[review_finding(reproduction="not_attempted")],
        ),
        append_ledger=False,
    )
    assert result["status"] == "needs_review"


def test_broken_link_probe_is_policy_gated(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path, broken_link=True)
    prepared = prepare(workspace)
    assert prepared["probe_findings"] == 1
    result = finalize(workspace, reviewer_output(), append_ledger=False)
    attestation = json.loads(
        (workspace / result["attestation"]).read_text(encoding="utf-8")
    )
    probe_finding = next(
        finding
        for finding in attestation["findings"]
        if finding["source"] == "deterministic_probe"
    )
    assert result["status"] == "fail"
    assert probe_finding["gate_effect"] == "fail"
    assert probe_finding["evidence"][0]["sha256"]


def test_link_escaping_workspace_is_policy_gated(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    (workspace / "docs/README.md").write_text(
        "# Demo\n\n[Outside](../../outside.md)\n",
        encoding="utf-8",
    )
    prepared = prepare(workspace)
    assert prepared["probe_findings"] == 1
    result = finalize(workspace, reviewer_output(), append_ledger=False)
    assert result["status"] == "fail"


def test_artifact_change_voids_prepared_run(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    prepare(workspace)
    (workspace / "docs/README.md").write_text("# Changed\n", encoding="utf-8")
    write_json(workspace / "reviewer-output.json", reviewer_output())
    (workspace / "transcript.txt").write_text("Transcript.\n")
    with pytest.raises(AuditRuntimeError, match="artifact set changed"):
        finalize_run(
            workspace=workspace,
            run_dir=".validity-audit/runs/test-run",
            reviewer_output_path="reviewer-output.json",
            transcript_path="transcript.txt",
            completed_at=COMPLETED,
            issued_at=ISSUED,
            append_ledger=False,
        )
    assert not (workspace / ".validity-audit/runs/test-run/attestation.json").exists()


def test_finalize_rejects_review_identity_mismatch(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    prepare(workspace)
    output = reviewer_output()
    output["reviewer"]["label"] = "different-reviewer"
    write_json(workspace / "reviewer-output.json", output)
    (workspace / "transcript.txt").write_text("Transcript.\n")
    with pytest.raises(AuditRuntimeError, match="identity label"):
        finalize_run(
            workspace=workspace,
            run_dir=".validity-audit/runs/test-run",
            reviewer_output_path="reviewer-output.json",
            transcript_path="transcript.txt",
            completed_at=COMPLETED,
            issued_at=ISSUED,
            append_ledger=False,
        )


def test_finalize_cannot_run_twice(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    prepare(workspace)
    finalize(workspace, reviewer_output(), append_ledger=False)
    with pytest.raises(AuditRuntimeError, match="must be prepared"):
        finalize(workspace, reviewer_output(), append_ledger=False)


def test_ledger_duplicate_is_rejected_before_final_outputs(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    prepare(workspace)
    ledger = workspace / ".validity-audit/attestations.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(
        json.dumps({"attestation_id": "attestation-runtime-test-001"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(AuditRuntimeError, match="already contains"):
        finalize(workspace, reviewer_output())
    run_dir = workspace / ".validity-audit/runs/test-run"
    assert not (run_dir / "attestation.json").exists()
    assert not (run_dir / "attestation.md").exists()
