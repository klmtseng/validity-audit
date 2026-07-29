"""Two-stage operator-in-the-loop runtime for Validity Audit v0.3."""

from __future__ import annotations

import base64
import copy
import json
import mimetypes
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validity_audit.digests import (
    canonical_sha256,
    sha256_bytes,
    sha256_file,
    write_json_atomic,
)
from validity_audit.policy import POLICY_ID, PolicyError, evaluate_policy
from validity_audit.probes import run_probes
from validity_audit.schemas import (
    FORMAT_CHECKER,
    SchemaValidationError,
    load_schema,
    validate_document,
)

STATE_FILENAME = "run_state.json"
BUNDLE_FILENAME = "review_bundle.json"
PROBE_FILENAME = "probe_report.json"
ATTESTATION_FILENAME = "attestation.json"
REPORT_FILENAME = "attestation.md"
REVIEWER_OUTPUT_FILENAME = "evidence/reviewer_output.json"
TRANSCRIPT_FILENAME = "evidence/reviewer_transcript.txt"


class AuditRuntimeError(ValueError):
    """Raised when a run violates a runtime or cross-document invariant."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_time(value: str, label: str) -> datetime:
    if not FORMAT_CHECKER.conforms(value, "date-time"):
        raise AuditRuntimeError(f"{label} must be an RFC 3339 date-time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuditRuntimeError(f"{label} must be an RFC 3339 date-time") from exc
    if parsed.tzinfo is None:
        raise AuditRuntimeError(f"{label} must include a timezone")
    return parsed


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AuditRuntimeError(f"{label} does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AuditRuntimeError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise AuditRuntimeError(f"{label} must be a JSON object")
    return value


def _workspace_path(workspace: str | Path) -> Path:
    root = Path(workspace).resolve()
    if not root.is_dir():
        raise AuditRuntimeError(f"workspace is not a directory: {root}")
    return root


def _inside_workspace(workspace: Path, path: Path, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(workspace):
        raise AuditRuntimeError(f"{label} must remain inside the workspace: {path}")
    return resolved


def _relative_file(workspace: Path, path: str | Path, label: str) -> tuple[Path, str]:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    lexical = Path(os.path.abspath(candidate))
    resolved = _inside_workspace(workspace, candidate, label)
    if lexical != resolved:
        raise AuditRuntimeError(f"{label} must not traverse a symbolic link: {candidate}")
    if not resolved.is_file():
        raise AuditRuntimeError(f"{label} is not a regular file: {candidate}")
    return resolved, lexical.relative_to(workspace).as_posix()


def _run_directory(workspace: Path, run_dir: str | Path, *, create: bool) -> Path:
    candidate = Path(run_dir)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    resolved = _inside_workspace(workspace, candidate, "run directory")
    if resolved == workspace:
        raise AuditRuntimeError("run directory cannot be the workspace root")
    if create:
        if resolved.exists() and any(resolved.iterdir()):
            raise AuditRuntimeError(f"run directory is not empty: {resolved}")
        resolved.mkdir(parents=True, exist_ok=True)
    elif not resolved.is_dir():
        raise AuditRuntimeError(f"run directory does not exist: {resolved}")
    return resolved


def _assert_unique(values: list[str], label: str) -> None:
    if len(values) != len(set(values)):
        raise AuditRuntimeError(f"{label} must be unique")


def _artifact_descriptor(workspace: Path, relative_path: str) -> dict[str, Any]:
    path, normalized = _relative_file(workspace, relative_path, "artifact")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return {
        "path": normalized,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "media_type": media_type,
    }


def _artifact_snapshot(workspace: Path, descriptor: dict[str, Any]) -> dict[str, Any]:
    path = workspace / descriptor["path"]
    payload = path.read_bytes()
    snapshot = dict(descriptor)
    try:
        snapshot["encoding"] = "utf-8"
        snapshot["content"] = payload.decode("utf-8")
    except UnicodeDecodeError:
        snapshot["encoding"] = "base64"
        snapshot["content"] = base64.b64encode(payload).decode("ascii")
    return snapshot


def _artifact_manifest(workspace: Path, paths: list[str]) -> dict[str, Any]:
    artifacts = sorted(
        (_artifact_descriptor(workspace, path) for path in paths),
        key=lambda artifact: artifact["path"],
    )
    return {
        "manifest_sha256": canonical_sha256(artifacts),
        "void_if_changed": True,
        "artifacts": artifacts,
    }


def _pack_snapshots(workspace: Path, packs: list[str]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for pack_id in sorted(packs):
        candidate = workspace / "domains" / f"{pack_id}.md"
        if candidate.is_file() and not candidate.is_symlink():
            snapshots.append(
                {
                    "pack_id": pack_id,
                    "status": "embedded",
                    "path": candidate.relative_to(workspace).as_posix(),
                    "sha256": sha256_file(candidate),
                    "content": candidate.read_text(encoding="utf-8"),
                }
            )
        else:
            snapshots.append(
                {
                    "pack_id": pack_id,
                    "status": "external_or_unresolved",
                }
            )
    return snapshots


def _review_configuration(
    *,
    context: str,
    reviewer_kind: str,
    reviewer_label: str,
    operator_id: str,
    priming_sources: list[str],
) -> dict[str, Any]:
    if context not in {"cold", "primed"}:
        raise AuditRuntimeError("review context must be cold or primed")
    if reviewer_kind not in {"human", "model", "hybrid"}:
        raise AuditRuntimeError("reviewer kind must be human, model, or hybrid")
    if not reviewer_label.strip() or not operator_id.strip():
        raise AuditRuntimeError("reviewer label and operator id must be non-empty")
    if context == "cold" and priming_sources:
        raise AuditRuntimeError("a cold review cannot declare priming sources")
    if context == "primed" and not priming_sources:
        raise AuditRuntimeError("a primed review must declare at least one priming source")
    _assert_unique(priming_sources, "priming sources")

    review: dict[str, Any] = {
        "context": context,
        "reviewer": {
            "kind": reviewer_kind,
            "label": reviewer_label,
        },
        "operator_id": operator_id,
    }
    if priming_sources:
        review["priming_sources"] = priming_sources
    return review


def prepare_run(
    *,
    workspace: str | Path,
    contract_path: str | Path,
    run_dir: str | Path,
    review_context: str,
    reviewer_kind: str,
    reviewer_label: str,
    operator_id: str,
    priming_sources: list[str] | None = None,
    run_id: str | None = None,
    started_at: str | None = None,
    previous_run_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Validate and snapshot one bounded audit run for independent review."""
    root = _workspace_path(workspace)
    contract_file, contract_relative = _relative_file(root, contract_path, "task contract")
    contract = _load_json_object(contract_file, "task contract")
    try:
        validate_document(contract, "task_contract")
    except SchemaValidationError as exc:
        raise AuditRuntimeError(str(exc)) from exc

    claim_ids = [claim["claim_id"] for claim in contract["claims"]]
    _assert_unique(claim_ids, "contract claim ids")

    actual_run_id = run_id or f"run-{contract['task_id']}-{uuid.uuid4().hex[:12]}"
    if not actual_run_id or len(actual_run_id) > 128:
        raise AuditRuntimeError("run id must be between 1 and 128 characters")
    actual_started_at = started_at or utc_now()
    _parse_time(actual_started_at, "started_at")
    previous = list(previous_run_ids or [])
    _assert_unique(previous, "previous run ids")
    if actual_run_id in previous:
        raise AuditRuntimeError("run id cannot also be a previous run id")

    review = _review_configuration(
        context=review_context,
        reviewer_kind=reviewer_kind,
        reviewer_label=reviewer_label,
        operator_id=operator_id,
        priming_sources=list(priming_sources or []),
    )
    manifest = _artifact_manifest(root, contract["artifact_paths"])
    probe_report = run_probes(root, contract["artifact_paths"])
    output_dir = _run_directory(root, run_dir, create=True)
    probe_path = output_dir / PROBE_FILENAME
    write_json_atomic(probe_path, probe_report)
    probe_sha256 = sha256_file(probe_path)

    bundle: dict[str, Any] = {
        "bundle_version": "0.3.0",
        "run_id": actual_run_id,
        "task_id": contract["task_id"],
        "prepared_at": actual_started_at,
        "review_context": review["context"],
        "reviewer": review["reviewer"],
        "operator_id": review["operator_id"],
        "contract_sha256": sha256_file(contract_file),
        "claims": contract["claims"],
        "packs": contract["packs"],
        "pack_snapshots": _pack_snapshots(root, contract["packs"]),
        "artifact_manifest": manifest,
        "artifacts": [
            _artifact_snapshot(root, artifact) for artifact in manifest["artifacts"]
        ],
        "probe_report_sha256": probe_sha256,
        "probe_report": probe_report,
        "reviewer_output_schema": load_schema("reviewer_output"),
        "instructions": {
            "task": (
                "Audit every claim against the embedded artifact snapshots. Return JSON that "
                "validates against schemas/reviewer_output.schema.json."
            ),
            "policy_boundary": (
                "Do not assign gate_effect. The versioned policy engine is its sole writer."
            ),
            "transcript": (
                "Retain the raw reviewer transcript separately and import it during finalize."
            ),
        },
    }
    if review["context"] == "cold":
        bundle["excluded_context"] = ["answer keys", "miss ledger", "builder hint list"]
    else:
        bundle["priming_sources"] = review["priming_sources"]

    bundle_path = output_dir / BUNDLE_FILENAME
    write_json_atomic(bundle_path, bundle)
    bundle_sha256 = sha256_file(bundle_path)

    state: dict[str, Any] = {
        "state_version": "0.3.0",
        "state": "prepared",
        "run_id": actual_run_id,
        "task_id": contract["task_id"],
        "started_at": actual_started_at,
        "previous_run_ids": previous,
        "contract": {
            "path": contract_relative,
            "sha256": sha256_file(contract_file),
        },
        "artifact_manifest": manifest,
        "review": review,
        "probe_report": {
            "path": PROBE_FILENAME,
            "sha256": probe_sha256,
        },
        "review_bundle": {
            "path": BUNDLE_FILENAME,
            "sha256": bundle_sha256,
        },
    }
    write_json_atomic(output_dir / STATE_FILENAME, state)
    return {
        "state": "prepared",
        "run_id": actual_run_id,
        "run_dir": output_dir.relative_to(root).as_posix(),
        "review_bundle": (output_dir / BUNDLE_FILENAME).relative_to(root).as_posix(),
        "bundle_sha256": bundle_sha256,
        "manifest_sha256": manifest["manifest_sha256"],
        "probe_findings": len(probe_report["findings"]),
    }


def _load_prepared_state(run_dir: Path) -> dict[str, Any]:
    state = _load_json_object(run_dir / STATE_FILENAME, "run state")
    if state.get("state_version") != "0.3.0":
        raise AuditRuntimeError("unsupported run-state version")
    if state.get("state") != "prepared":
        raise AuditRuntimeError(
            f"run must be prepared before finalize; current state is {state.get('state')!r}"
        )
    return state


def _verify_prepared_evidence(
    workspace: Path,
    run_dir: Path,
    state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    contract_path = workspace / state["contract"]["path"]
    if sha256_file(contract_path) != state["contract"]["sha256"]:
        raise AuditRuntimeError("task contract changed after prepare")
    contract = _load_json_object(contract_path, "task contract")
    try:
        validate_document(contract, "task_contract")
    except SchemaValidationError as exc:
        raise AuditRuntimeError(str(exc)) from exc

    current_manifest = _artifact_manifest(workspace, contract["artifact_paths"])
    if current_manifest != state["artifact_manifest"]:
        raise AuditRuntimeError("artifact set changed after prepare; the prepared record is void")

    probe_path = run_dir / state["probe_report"]["path"]
    if sha256_file(probe_path) != state["probe_report"]["sha256"]:
        raise AuditRuntimeError("probe report digest does not match the prepared state")
    stored_probes = _load_json_object(probe_path, "probe report")
    current_probes = run_probes(workspace, contract["artifact_paths"])
    if current_probes != stored_probes:
        raise AuditRuntimeError("deterministic probe results changed after prepare")

    bundle_path = run_dir / state["review_bundle"]["path"]
    if sha256_file(bundle_path) != state["review_bundle"]["sha256"]:
        raise AuditRuntimeError("review bundle digest does not match the prepared state")
    bundle = _load_json_object(bundle_path, "review bundle")
    expected_bundle_fields = {
        "run_id": state["run_id"],
        "task_id": state["task_id"],
        "contract_sha256": state["contract"]["sha256"],
        "artifact_manifest": state["artifact_manifest"],
        "probe_report_sha256": state["probe_report"]["sha256"],
        "probe_report": stored_probes,
        "review_context": state["review"]["context"],
        "reviewer": state["review"]["reviewer"],
        "operator_id": state["review"]["operator_id"],
        "reviewer_output_schema": load_schema("reviewer_output"),
    }
    for key, expected in expected_bundle_fields.items():
        if bundle.get(key) != expected:
            raise AuditRuntimeError(f"review bundle field {key!r} is inconsistent")
    if bundle.get("priming_sources") != state["review"].get("priming_sources"):
        if not (
            state["review"]["context"] == "cold"
            and "priming_sources" not in bundle
            and "priming_sources" not in state["review"]
        ):
            raise AuditRuntimeError("review bundle priming sources are inconsistent")
    return contract, stored_probes


def _review_source(context: str) -> str:
    return "cold_review" if context == "cold" else "primed_review"


def _claim_results(
    contract: dict[str, Any],
    reviewer_output: dict[str, Any],
    finding_ids: set[str],
) -> list[dict[str, Any]]:
    claims = {claim["claim_id"]: claim for claim in contract["claims"]}
    raw_results = reviewer_output["claim_results"]
    result_ids = [result["claim_id"] for result in raw_results]
    _assert_unique(result_ids, "reviewer claim-result ids")
    if set(result_ids) != set(claims):
        missing = sorted(set(claims) - set(result_ids))
        extra = sorted(set(result_ids) - set(claims))
        raise AuditRuntimeError(
            f"claim results must exactly cover the contract; missing={missing}, extra={extra}"
        )

    results: list[dict[str, Any]] = []
    for raw_result in raw_results:
        unknown = set(raw_result["finding_ids"]) - finding_ids
        if unknown:
            raise AuditRuntimeError(
                f"claim {raw_result['claim_id']!r} references unknown findings: "
                f"{', '.join(sorted(unknown))}"
            )
        if raw_result["outcome"] == "refuted" and not raw_result["finding_ids"]:
            raise AuditRuntimeError(
                f"refuted claim {raw_result['claim_id']!r} must reference a finding"
            )
        result = copy.deepcopy(raw_result)
        result["statement"] = claims[result["claim_id"]]["statement"]
        results.append(result)
    return results


def _review_findings(
    reviewer_output: dict[str, Any],
    probe_report: dict[str, Any],
    probe_sha256: str,
) -> list[dict[str, Any]]:
    review_source = _review_source(reviewer_output["review_context"])
    reviewer_findings: list[dict[str, Any]] = []
    for raw_finding in reviewer_output["findings"]:
        finding = copy.deepcopy(raw_finding)
        finding["source"] = review_source
        reviewer_findings.append(finding)

    probe_findings = copy.deepcopy(probe_report["findings"])
    for finding in probe_findings:
        for evidence in finding["evidence"]:
            evidence["sha256"] = probe_sha256
    findings = probe_findings + reviewer_findings
    finding_ids = [finding["finding_id"] for finding in findings]
    _assert_unique(finding_ids, "finding ids")
    return findings


def _assert_reviewer_matches_state(
    state: dict[str, Any],
    reviewer_output: dict[str, Any],
) -> None:
    expected = state["review"]
    if reviewer_output["review_context"] != expected["context"]:
        raise AuditRuntimeError("reviewer output context does not match the prepared bundle")
    if reviewer_output["reviewer"] != expected["reviewer"]:
        raise AuditRuntimeError("reviewer identity label does not match the prepared bundle")
    if reviewer_output["operator_id"] != expected["operator_id"]:
        raise AuditRuntimeError("operator id does not match the prepared bundle")
    if reviewer_output.get("priming_sources") != expected.get("priming_sources"):
        raise AuditRuntimeError("priming sources do not match the prepared bundle")


def _render_attestation(attestation: dict[str, Any]) -> str:
    lines = [
        "# Unsigned Validity Attestation",
        "",
        f"- Attestation: `{attestation['attestation_id']}`",
        f"- Run: `{attestation['run']['run_id']}`",
        f"- Task: `{attestation['run']['task_id']}`",
        f"- Status: **{attestation['overall_result']['status']}**",
        f"- Policy: `{attestation['overall_result']['policy_id']}`",
        f"- Issued: `{attestation['issued_at']}`",
        f"- Contract SHA-256: `{attestation['contract']['sha256']}`",
        (
            "- Artifact manifest SHA-256: "
            f"`{attestation['artifact_manifest']['manifest_sha256']}`"
        ),
        f"- Review bundle SHA-256: `{attestation['review']['bundle_sha256']}`",
        f"- Transcript SHA-256: `{attestation['review']['transcript_sha256']}`",
        "",
        "## Result",
        "",
        attestation["overall_result"]["summary"],
        "",
        "## Findings",
        "",
    ]
    if not attestation["findings"]:
        lines.append("No findings.")
    else:
        for finding in attestation["findings"]:
            lines.append(
                f"- `{finding['finding_id']}` — **{finding['gate_effect']}** — "
                f"{finding['title']}"
            )
    lines.extend(
        [
            "",
            "> This v0.3 record is unsigned. It covers one task run and one artifact set; "
            "it does not certify an agent globally.",
            "",
        ]
    )
    return "\n".join(lines)


def _ledger_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AuditRuntimeError(
                    f"{path}:{line_number}: invalid attestation ledger JSON"
                ) from exc
            if not isinstance(value, dict):
                raise AuditRuntimeError(
                    f"{path}:{line_number}: attestation ledger record must be an object"
                )
            records.append(value)
    return records


def _append_attestation_ledger(path: Path, record: dict[str, Any]) -> None:
    records = _ledger_records(path)
    if any(row.get("attestation_id") == record["attestation_id"] for row in records):
        raise AuditRuntimeError(
            f"attestation ledger already contains {record['attestation_id']!r}"
        )
    serialized = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(serialized)
        handle.flush()
        os.fsync(handle.fileno())


def finalize_run(
    *,
    workspace: str | Path,
    run_dir: str | Path,
    reviewer_output_path: str | Path,
    transcript_path: str | Path,
    completed_at: str | None = None,
    issued_at: str | None = None,
    attestation_id: str | None = None,
    ledger_path: str | Path | None = None,
    append_ledger: bool = True,
) -> dict[str, Any]:
    """Import independent review evidence and emit an unsigned attestation."""
    root = _workspace_path(workspace)
    output_dir = _run_directory(root, run_dir, create=False)
    state = _load_prepared_state(output_dir)
    contract, probe_report = _verify_prepared_evidence(root, output_dir, state)

    reviewer_file, _ = _relative_file(root, reviewer_output_path, "reviewer output")
    transcript_file, _ = _relative_file(root, transcript_path, "reviewer transcript")
    reviewer_output = _load_json_object(reviewer_file, "reviewer output")
    try:
        validate_document(reviewer_output, "reviewer_output")
    except SchemaValidationError as exc:
        raise AuditRuntimeError(str(exc)) from exc
    _assert_reviewer_matches_state(state, reviewer_output)

    transcript_bytes = transcript_file.read_bytes()
    if not transcript_bytes.strip():
        raise AuditRuntimeError("reviewer transcript must not be empty")

    actual_completed_at = completed_at or utc_now()
    actual_issued_at = issued_at or actual_completed_at
    started = _parse_time(state["started_at"], "started_at")
    completed = _parse_time(actual_completed_at, "completed_at")
    issued = _parse_time(actual_issued_at, "issued_at")
    if not started <= completed <= issued:
        raise AuditRuntimeError("timestamps must satisfy started_at <= completed_at <= issued_at")

    findings = _review_findings(
        reviewer_output,
        probe_report,
        state["probe_report"]["sha256"],
    )
    finding_ids = {finding["finding_id"] for finding in findings}
    claim_results = _claim_results(contract, reviewer_output, finding_ids)
    try:
        policy = evaluate_policy(
            contract=contract,
            findings=findings,
            claim_results=claim_results,
            waiver_requests=reviewer_output.get("waivers", []),
            issued_at=actual_issued_at,
        )
    except PolicyError as exc:
        raise AuditRuntimeError(str(exc)) from exc

    review: dict[str, Any] = {
        "context": state["review"]["context"],
        "method": "operator_in_the_loop",
        "bundle_sha256": state["review_bundle"]["sha256"],
        "transcript_sha256": sha256_bytes(transcript_bytes),
        "reviewer": state["review"]["reviewer"],
        "operator_id": state["review"]["operator_id"],
    }
    if "priming_sources" in state["review"]:
        review["priming_sources"] = state["review"]["priming_sources"]

    attestation: dict[str, Any] = {
        "$schema": Path(
            os.path.relpath(root / "schemas" / "attestation.schema.json", output_dir)
        ).as_posix(),
        "schema_version": "0.3.0",
        "attestation_type": "unsigned_validity_attestation",
        "attestation_id": attestation_id or f"attestation-{state['run_id']}",
        "issued_at": actual_issued_at,
        "run": {
            "run_id": state["run_id"],
            "task_id": state["task_id"],
            "started_at": state["started_at"],
            "completed_at": actual_completed_at,
        },
        "contract": state["contract"],
        "artifact_manifest": state["artifact_manifest"],
        "review": review,
        "claim_results": claim_results,
        "findings": policy.findings,
        "overall_result": {
            "status": policy.status,
            "policy_id": POLICY_ID,
            "summary": policy.summary,
        },
        "signature": None,
    }
    if state["previous_run_ids"]:
        attestation["run"]["previous_run_ids"] = state["previous_run_ids"]
    try:
        validate_document(attestation, "attestation")
    except SchemaValidationError as exc:
        raise AuditRuntimeError(str(exc)) from exc

    actual_ledger_path: Path | None = None
    if append_ledger:
        raw_ledger = Path(ledger_path) if ledger_path is not None else Path(
            ".validity-audit/attestations.jsonl"
        )
        if not raw_ledger.is_absolute():
            raw_ledger = root / raw_ledger
        actual_ledger_path = _inside_workspace(root, raw_ledger, "attestation ledger")
        existing_ledger = _ledger_records(actual_ledger_path)
        if any(
            row.get("attestation_id") == attestation["attestation_id"]
            for row in existing_ledger
        ):
            raise AuditRuntimeError(
                f"attestation ledger already contains {attestation['attestation_id']!r}"
            )

    final_outputs = [
        output_dir / ATTESTATION_FILENAME,
        output_dir / REPORT_FILENAME,
    ]
    if any(path.exists() for path in final_outputs):
        raise AuditRuntimeError("finalize outputs already exist; refusing to overwrite evidence")

    (output_dir / "evidence").mkdir(parents=True, exist_ok=True)
    reviewer_target = output_dir / REVIEWER_OUTPUT_FILENAME
    transcript_target = output_dir / TRANSCRIPT_FILENAME
    for source, target in (
        (reviewer_file, reviewer_target),
        (transcript_file, transcript_target),
    ):
        if target.exists() and target.resolve() != source.resolve():
            raise AuditRuntimeError(f"refusing to overwrite retained evidence: {target}")
        if target.resolve() != source.resolve():
            shutil.copyfile(source, target)
    write_json_atomic(output_dir / ATTESTATION_FILENAME, attestation)
    (output_dir / REPORT_FILENAME).write_text(_render_attestation(attestation), encoding="utf-8")
    attestation_sha256 = sha256_file(output_dir / ATTESTATION_FILENAME)

    if actual_ledger_path is not None:
        _append_attestation_ledger(
            actual_ledger_path,
            {
                "attestation_id": attestation["attestation_id"],
                "attestation_sha256": attestation_sha256,
                "issued_at": attestation["issued_at"],
                "path": (output_dir / ATTESTATION_FILENAME).relative_to(root).as_posix(),
                "policy_id": POLICY_ID,
                "run_id": state["run_id"],
                "schema_version": "0.3.0",
                "status": policy.status,
            },
        )

    finalized_state = copy.deepcopy(state)
    finalized_state.update(
        {
            "state": "finalized",
            "completed_at": actual_completed_at,
            "issued_at": actual_issued_at,
            "reviewer_output": {
                "path": REVIEWER_OUTPUT_FILENAME,
                "sha256": sha256_file(output_dir / REVIEWER_OUTPUT_FILENAME),
            },
            "reviewer_transcript": {
                "path": TRANSCRIPT_FILENAME,
                "sha256": sha256_file(output_dir / TRANSCRIPT_FILENAME),
            },
            "attestation": {
                "path": ATTESTATION_FILENAME,
                "sha256": attestation_sha256,
                "status": policy.status,
            },
        }
    )
    if actual_ledger_path is not None:
        finalized_state["attestation_ledger"] = actual_ledger_path.relative_to(root).as_posix()
    write_json_atomic(output_dir / STATE_FILENAME, finalized_state)

    return {
        "state": "finalized",
        "run_id": state["run_id"],
        "attestation": (output_dir / ATTESTATION_FILENAME).relative_to(root).as_posix(),
        "attestation_sha256": attestation_sha256,
        "status": policy.status,
        "findings": len(policy.findings),
        "transcript_sha256": review["transcript_sha256"],
    }
