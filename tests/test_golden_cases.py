from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = ROOT / "golden_cases"
VALID_SEVERITIES = {"high", "med", "low"}


def load_cases() -> list[dict]:
    historical = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(GOLDEN_DIR.glob("*.json"))
    ]
    self_contained = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(GOLDEN_DIR.glob("self_contained/*/case.json"))
    ]
    return historical + self_contained


def expected_findings(case: dict) -> list[dict]:
    key = case.get("key")
    if key is None:
        return case.get("expected_findings", [])
    key_path = ROOT / key["path"]
    payload = json.loads(key_path.read_text(encoding="utf-8"))
    return payload["expected_findings"]


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
        for finding in expected_findings(case):
            assert finding["severity"] in VALID_SEVERITIES, (
                f"{case['case_id']}:{finding.get('id', finding.get('finding_id'))} "
                "has noncanonical severity "
                f"{finding['severity']!r}"
            )


def test_canonical_answer_keys_are_not_duplicated() -> None:
    seen: dict[str, str] = {}
    for case in load_cases():
        if case.get("record_type") == "alias":
            continue
        normalized = json.dumps(expected_findings(case), sort_keys=True)
        assert normalized not in seen, (
            f"{case['case_id']} duplicates the key from {seen.get(normalized)}"
        )
        seen[normalized] = case["case_id"]


def test_external_keys_are_frozen_versioned_and_digest_pinned() -> None:
    for case in load_cases():
        key = case.get("key")
        if key is None:
            continue
        key_path = ROOT / key["path"]
        payload = json.loads(key_path.read_text(encoding="utf-8"))
        assert case["record_type"] == "canonical"
        assert case["excluded_from_metrics"] is False
        assert payload["record_type"] == "frozen_regression_key"
        assert payload["frozen"] is True
        assert payload["case_id"] == case["case_id"]
        assert payload["key_version"] == key["version"]
        assert sha256(key_path.read_bytes()).hexdigest() == key["sha256"]
