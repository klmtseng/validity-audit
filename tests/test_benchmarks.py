from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

from benchmarks.golden.score import ScoringError, score_findings
from benchmarks.injected.run import run as run_injected

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "golden_cases" / "self_contained" / "doc-bundle-01"


def load(name: str) -> dict:
    return json.loads((CASE / name).read_text(encoding="utf-8"))


def test_injected_floor_baseline_is_preserved(capsys) -> None:
    result = run_injected()
    capsys.readouterr()
    assert result["mechanical_caught"] == 6
    assert result["mechanical_total"] == 6
    assert result["false_alarms"] == 0
    assert result["clean_total"] == 6
    assert result["reasoning_caught"] == 0
    assert result["reasoning_total"] == 5
    assert result["overall_caught"] == 6
    assert result["overall_total"] == 11


def test_legacy_injected_shim_matches_canonical_output() -> None:
    canonical = subprocess.run(
        [sys.executable, "benchmarks/injected/run.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    legacy = subprocess.run(
        [sys.executable, "protocol/injected_bug_recall.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert legacy.stdout == canonical.stdout


def test_frozen_reviewer_output_matches_expected_score() -> None:
    assert score_findings(load("key-v1.json"), load("reviewer_output.json")) == load(
        "expected_score.json"
    )


def test_missing_expected_finding_fails_regression() -> None:
    output = copy.deepcopy(load("reviewer_output.json"))
    output["findings"] = []
    output["claim_results"][1]["finding_ids"] = []
    result = score_findings(load("key-v1.json"), output)
    assert result["status"] == "fail"
    assert result["missed_finding_ids"] == ["incorrect-artifact-count"]


def test_unexpected_finding_requires_adjudication() -> None:
    output = copy.deepcopy(load("reviewer_output.json"))
    extra = copy.deepcopy(output["findings"][0])
    extra["finding_id"] = "new-finding"
    output["findings"].append(extra)
    result = score_findings(load("key-v1.json"), output)
    assert result["status"] == "needs_adjudication"
    assert result["unexpected_finding_ids"] == ["new-finding"]


def test_mismatched_taxonomy_fails_regression() -> None:
    output = copy.deepcopy(load("reviewer_output.json"))
    output["findings"][0]["error_class"] = "maintainability"
    result = score_findings(load("key-v1.json"), output)
    assert result["status"] == "fail"
    assert result["mismatched_findings"][0]["finding_id"] == "incorrect-artifact-count"


def test_duplicate_finding_ids_are_rejected() -> None:
    output = copy.deepcopy(load("reviewer_output.json"))
    output["findings"].append(copy.deepcopy(output["findings"][0]))
    try:
        score_findings(load("key-v1.json"), output)
    except ScoringError as exc:
        assert "duplicate finding_id" in str(exc)
    else:
        raise AssertionError("duplicate finding ids should not be scored")
