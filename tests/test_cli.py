from __future__ import annotations

import pytest

from validity_audit import cli
from validity_audit.runtime import AuditRuntimeError, EvidenceMismatchError


def prepare_args() -> list[str]:
    return [
        "prepare",
        "--contract",
        "task.json",
        "--run-dir",
        "run",
        "--review-context",
        "cold",
        "--reviewer-kind",
        "human",
        "--reviewer-label",
        "reviewer",
        "--operator-id",
        "operator",
    ]


def finalize_args() -> list[str]:
    return [
        "finalize",
        "--run-dir",
        "run",
        "--reviewer-output",
        "review.json",
        "--transcript",
        "transcript.txt",
    ]


def test_prepare_success_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli,
        "prepare_run",
        lambda **kwargs: {"state": "awaiting_review", "run_id": "run-1"},
    )
    assert cli.main(prepare_args()) == cli.EXIT_PASS


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("pass", 0),
        ("pass_with_waiver", 0),
        ("fail", 2),
        ("needs_review", 3),
    ],
)
def test_finalize_status_exit_contract(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    expected: int,
) -> None:
    monkeypatch.setattr(
        cli,
        "finalize_run",
        lambda **kwargs: {"state": "completed", "status": status},
    )
    assert cli.main(finalize_args()) == expected


def test_operational_error_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(**kwargs: object) -> dict:
        raise AuditRuntimeError("invalid reviewer output")

    monkeypatch.setattr(cli, "finalize_run", fail)
    with pytest.raises(SystemExit) as raised:
        cli.main(finalize_args())
    assert raised.value.code == cli.EXIT_OPERATIONAL_ERROR


def test_argument_error_exits_one() -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["prepare"])
    assert raised.value.code == cli.EXIT_OPERATIONAL_ERROR


def test_evidence_mismatch_exits_four(monkeypatch: pytest.MonkeyPatch) -> None:
    def mismatch(**kwargs: object) -> dict:
        raise EvidenceMismatchError("artifact digest changed")

    monkeypatch.setattr(cli, "finalize_run", mismatch)
    with pytest.raises(SystemExit) as raised:
        cli.main(finalize_args())
    assert raised.value.code == cli.EXIT_EVIDENCE_MISMATCH
