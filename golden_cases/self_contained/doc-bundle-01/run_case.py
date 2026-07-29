#!/usr/bin/env python3
"""Run and score the self-contained public-key regression case."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CASE = Path(__file__).resolve().parent
WORK_BASE = ROOT / ".validity-audit"
sys.path.insert(0, str(ROOT))

from benchmarks.golden.score import score_findings


def run_cli(*args: str, expected_code: int) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "validity_audit.cli", *args],
        cwd=ROOT,
        check=False,
    )
    if completed.returncode != expected_code:
        raise SystemExit(
            f"CLI returned {completed.returncode}; expected {expected_code}: {' '.join(args)}"
        )


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    if os.environ.get("VALIDITY_AUDIT_REQUIRE_OFFLINE") == "1":
        if os.environ.get("VALIDITY_AUDIT_NETWORK_GUARD") != "active":
            raise SystemExit("offline run requested but Python network guard is not active")

    WORK_BASE.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="golden-doc-bundle-01-", dir=WORK_BASE))
    try:
        run_cli(
            "prepare",
            "--workspace",
            str(ROOT),
            "--contract",
            "golden_cases/self_contained/doc-bundle-01/task_contract.json",
            "--run-dir",
            str(run_dir),
            "--run-id",
            "run-golden-doc-bundle-01",
            "--started-at",
            "2026-07-29T00:00:00Z",
            "--review-context",
            "primed",
            "--reviewer-kind",
            "human",
            "--reviewer-label",
            "checked-in-regression-fixture",
            "--operator-id",
            "golden-case-runner",
            "--priming-source",
            "golden_cases/self_contained/doc-bundle-01/key-v1.json",
            expected_code=0,
        )
        run_cli(
            "finalize",
            "--workspace",
            str(ROOT),
            "--run-dir",
            str(run_dir),
            "--reviewer-output",
            "golden_cases/self_contained/doc-bundle-01/reviewer_output.json",
            "--transcript",
            "golden_cases/self_contained/doc-bundle-01/reviewer_transcript.txt",
            "--completed-at",
            "2026-07-29T00:05:00Z",
            "--issued-at",
            "2026-07-29T00:06:00Z",
            "--attestation-id",
            "attestation-golden-doc-bundle-01",
            "--no-ledger",
            expected_code=2,
        )

        actual_attestation = load_json(run_dir / "attestation.json")
        expected_attestation = load_json(CASE / "expected_attestation.json")
        if actual_attestation != expected_attestation:
            raise SystemExit("attestation differs from expected_attestation.json")

        actual_score = score_findings(
            load_json(CASE / "key-v1.json"),
            load_json(CASE / "reviewer_output.json"),
        )
        expected_score = load_json(CASE / "expected_score.json")
        if actual_score != expected_score:
            raise SystemExit("regression score differs from expected_score.json")

        print(
            "Golden case PASS: expected fail attestation and 1/1 regression score reproduced"
        )
        return 0
    finally:
        shutil.rmtree(run_dir)


if __name__ == "__main__":
    raise SystemExit(main())
