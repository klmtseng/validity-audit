from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from validity_audit.ledger import (
    LedgerError,
    append_record,
    load_records,
    render_challenges,
    validate_record,
)


def record(record_id: str, severity: str = "low", category: str = "coverage") -> dict:
    return {
        "id": record_id,
        "category": category,
        "detector": f"detector for {record_id}",
        "caught_by": "reviewer",
        "severity": severity,
    }


@pytest.mark.parametrize("severity", ["high", "med", "low"])
def test_canonical_severities_append_and_reload(tmp_path: Path, severity: str) -> None:
    ledger = tmp_path / "ledger.jsonl"
    expected = record(f"id-{severity}", severity)
    append_record(expected, ledger)
    assert load_records(ledger) == [expected]


@pytest.mark.parametrize("severity", ["P1", "P2", "P3", "advisory", "critical", ""])
def test_noncanonical_severity_is_rejected(severity: str) -> None:
    with pytest.raises(LedgerError, match="severity"):
        validate_record(record("bad", severity))


def test_missing_field_is_rejected() -> None:
    invalid = record("missing")
    del invalid["detector"]
    with pytest.raises(LedgerError, match="detector"):
        validate_record(invalid)


def test_malformed_existing_json_is_not_changed(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    original = '{"id": "truncated"'
    ledger.write_text(original, encoding="utf-8")

    with pytest.raises(LedgerError, match="invalid JSON"):
        append_record(record("new"), ledger)

    assert ledger.read_text(encoding="utf-8") == original


def test_duplicate_id_is_rejected_without_writing(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    append_record(record("same"), ledger)
    before = ledger.read_bytes()

    with pytest.raises(LedgerError, match="duplicate id"):
        append_record(record("same", "high"), ledger)

    assert ledger.read_bytes() == before


def test_challenges_are_sorted_and_deduplicated_by_category() -> None:
    rows = [
        record("low-a", "low", "a"),
        record("high-a", "high", "a"),
        record("med-b", "med", "b"),
        record("low-c", "low", "c"),
    ]
    output = render_challenges(rows)

    assert output.index("[1] a") < output.index("[2] b") < output.index("[3] c")
    assert "low-a" not in output
    assert "3 categories, 4 records" in output


def test_empty_ledger_message_is_compatible() -> None:
    assert render_challenges([]) == "(ledger empty; no historical misses yet)"


def test_legacy_entry_point_still_runs(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "protocol/ledger.py", "--ledger", str(tmp_path / "x.jsonl"), "challenges"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "ledger empty" in completed.stdout


def test_legacy_entry_point_without_arguments_defaults_to_challenges() -> None:
    project_root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "protocol/ledger.py"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "ledger empty" in completed.stdout


def test_cli_invalid_severity_returns_nonzero_without_write(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    ledger = tmp_path / "x.jsonl"
    invalid = json.dumps(record("bad", "P1"))
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "validity_audit.ledger",
            "--ledger",
            str(ledger),
            "append",
            invalid,
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "unknown severity" in completed.stderr
    assert not ledger.exists()


def test_cli_rejects_non_object_json_without_write(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    ledger = tmp_path / "x.jsonl"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "validity_audit.ledger",
            "--ledger",
            str(ledger),
            "append",
            "[]",
        ],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "record must be a JSON object" in completed.stderr
    assert not ledger.exists()
