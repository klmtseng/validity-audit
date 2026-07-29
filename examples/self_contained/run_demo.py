"""Run and verify the deterministic self-contained v0.3 demonstration."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = Path(__file__).resolve().parent
WORK_BASE = ROOT / ".validity-audit"


def run(*args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "validity_audit.cli", *args],
        cwd=ROOT,
        check=True,
    )


def main() -> int:
    WORK_BASE.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="self-contained-", dir=WORK_BASE))
    try:
        run(
            "prepare",
            "--workspace",
            str(ROOT),
            "--contract",
            "examples/self_contained/task_contract.json",
            "--run-dir",
            str(run_dir),
            "--run-id",
            "run-self-contained-001",
            "--started-at",
            "2026-07-29T00:00:00Z",
            "--review-context",
            "cold",
            "--reviewer-kind",
            "human",
            "--reviewer-label",
            "self-contained-example-reviewer",
            "--operator-id",
            "self-contained-example-operator",
        )
        run(
            "finalize",
            "--workspace",
            str(ROOT),
            "--run-dir",
            str(run_dir),
            "--reviewer-output",
            "examples/self_contained/reviewer_output.json",
            "--transcript",
            "examples/self_contained/reviewer_transcript.txt",
            "--completed-at",
            "2026-07-29T00:05:00Z",
            "--issued-at",
            "2026-07-29T00:06:00Z",
            "--attestation-id",
            "attestation-self-contained-001",
            "--no-ledger",
        )
        actual = json.loads((run_dir / "attestation.json").read_text(encoding="utf-8"))
        expected = json.loads(
            (EXAMPLE / "expected_attestation.json").read_text(encoding="utf-8")
        )
        if actual != expected:
            raise SystemExit("self-contained attestation differs from the frozen expectation")
        print("Self-contained demo PASS: attestation matches expected_attestation.json")
        return 0
    finally:
        shutil.rmtree(run_dir)


if __name__ == "__main__":
    raise SystemExit(main())
