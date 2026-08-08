#!/usr/bin/env python3
"""Score reviewer findings against a frozen public regression key."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


class ScoringError(ValueError):
    """Raised when a key or reviewer output cannot be scored safely."""


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ScoringError(f"{label} does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ScoringError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ScoringError(f"{label} must be a JSON object")
    return value


def _required_list(document: dict[str, Any], field: str, label: str) -> list[Any]:
    if field not in document:
        raise ScoringError(f"{label} is missing required field {field!r}")
    value = document[field]
    if not isinstance(value, list):
        raise ScoringError(f"{label} field {field!r} must be a list")
    return value


def _unique_by_id(
    records: list[dict[str, Any]], id_field: str, label: str
) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ScoringError(f"{label} must contain JSON objects")
        record_id = record.get(id_field)
        if not isinstance(record_id, str) or not record_id:
            raise ScoringError(f"{label} contains a missing or invalid {id_field}")
        if record_id in indexed:
            raise ScoringError(f"{label} contains duplicate {id_field} {record_id!r}")
        indexed[record_id] = record
    return indexed


def _claim_links(reviewer_output: dict[str, Any]) -> dict[str, set[str]]:
    links: dict[str, set[str]] = {}
    for result in _required_list(reviewer_output, "claim_results", "reviewer output"):
        if not isinstance(result, dict):
            raise ScoringError("reviewer claim_results must contain JSON objects")
        claim_id = result.get("claim_id")
        if not isinstance(claim_id, str) or not claim_id:
            raise ScoringError("reviewer claim_results contains a missing or invalid claim_id")
        finding_ids = result.get("finding_ids")
        if not isinstance(finding_ids, list):
            raise ScoringError(
                f"reviewer claim result {claim_id!r} is missing a valid finding_ids list"
            )
        for finding_id in finding_ids:
            if not isinstance(finding_id, str) or not finding_id:
                raise ScoringError(
                    f"reviewer claim result {claim_id!r} contains an invalid finding_id"
                )
            links.setdefault(finding_id, set()).add(claim_id)
    return links


def score_findings(
    key: dict[str, Any], reviewer_output: dict[str, Any]
) -> dict[str, Any]:
    """Return an exact-id public-key regression score and adjudication state."""
    if key.get("record_type") != "frozen_regression_key" or key.get("frozen") is not True:
        raise ScoringError("key must declare record_type=frozen_regression_key and frozen=true")

    expected = _unique_by_id(
        _required_list(key, "expected_findings", "key"),
        "finding_id",
        "expected findings",
    )
    actual = _unique_by_id(
        _required_list(reviewer_output, "findings", "reviewer output"),
        "finding_id",
        "reviewer findings",
    )
    claim_links = _claim_links(reviewer_output)

    matched: list[str] = []
    mismatched: list[dict[str, Any]] = []
    for finding_id in sorted(expected.keys() & actual.keys()):
        wanted = expected[finding_id]
        got = actual[finding_id]
        differences: list[str] = []
        for field in ("error_class", "severity", "reproduction"):
            if got.get(field) != wanted.get(field):
                differences.append(
                    f"{field}: expected {wanted.get(field)!r}, got {got.get(field)!r}"
                )
        wanted_claims = set(wanted.get("claim_ids", []))
        got_claims = claim_links.get(finding_id, set())
        if got_claims != wanted_claims:
            differences.append(
                f"claim_ids: expected {sorted(wanted_claims)!r}, "
                f"got {sorted(got_claims)!r}"
            )
        if differences:
            mismatched.append({"finding_id": finding_id, "differences": differences})
        else:
            matched.append(finding_id)

    missed = sorted(expected.keys() - set(matched))
    unexpected = sorted(actual.keys() - expected.keys())
    expected_total = len(expected)
    actual_total = len(actual)
    recall = len(matched) / expected_total if expected_total else None
    precision = len(matched) / actual_total if actual_total else None

    if missed:
        status = "fail"
    elif unexpected:
        status = "needs_adjudication"
    else:
        status = "pass"

    return {
        "score_version": "1.0.0",
        "case_id": key["case_id"],
        "key_version": key["key_version"],
        "public_key_regression_only": True,
        "status": status,
        "expected_total": expected_total,
        "actual_total": actual_total,
        "matched_total": len(matched),
        "matched_finding_ids": matched,
        "missed_finding_ids": missed,
        "unexpected_finding_ids": unexpected,
        "mismatched_findings": mismatched,
        "recall": recall,
        "precision": precision,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Score reviewer output against a frozen public regression key."
    )
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--reviewer-output", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = score_findings(
            _load_object(args.key, "key"),
            _load_object(args.reviewer_output, "reviewer output"),
        )
    except ScoringError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return {"pass": 0, "fail": 2, "needs_adjudication": 3}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
