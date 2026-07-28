from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = ROOT / "golden_cases"
VALID_SEVERITIES = {"high", "med", "low"}


def load_cases() -> list[dict]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(GOLDEN_DIR.glob("*.json"))
    ]


def test_case_ids_are_unique() -> None:
    ids = [case["case_id"] for case in load_cases()]
    assert len(ids) == len(set(ids))


def test_aliases_are_excluded_and_point_to_canonical_case() -> None:
    cases = load_cases()
    by_id = {case["case_id"]: case for case in cases}
    aliases = [case for case in cases if case.get("record_type") == "alias"]
    assert aliases, "historical duplicate should be retained as an explicit alias"
    for alias in aliases:
        assert alias["excluded_from_metrics"] is True
        canonical = by_id[alias["canonical_case_id"]]
        assert canonical.get("record_type", "canonical") == "canonical"
        assert "expected_findings" not in alias


def test_canonical_cases_reference_public_domain_packs() -> None:
    for case in load_cases():
        if case.get("record_type") == "alias":
            continue
        for pack in case["domain_packs"]:
            assert (ROOT / "domains" / f"{pack}.md").is_file(), (
                f"{case['case_id']} references missing public pack {pack!r}"
            )


def test_findings_use_canonical_severity() -> None:
    for case in load_cases():
        for finding in case.get("expected_findings", []):
            assert finding["severity"] in VALID_SEVERITIES, (
                f"{case['case_id']}:{finding['id']} has noncanonical severity "
                f"{finding['severity']!r}"
            )


def test_canonical_answer_keys_are_not_duplicated() -> None:
    seen: dict[str, str] = {}
    for case in load_cases():
        if case.get("record_type") == "alias":
            continue
        normalized = json.dumps(case.get("expected_findings", []), sort_keys=True)
        assert normalized not in seen, (
            f"{case['case_id']} duplicates the key from {seen.get(normalized)}"
        )
        seen[normalized] = case["case_id"]
