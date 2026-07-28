"""Validated append-only miss ledger.

The ledger is builder-side evidence. Its challenges must not be shown to a cold
reviewer because doing so contaminates the independent review.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

VALID_SEVERITIES = ("high", "med", "low")
SEVERITY_RANK = {"high": 3, "med": 2, "low": 1}
REQUIRED_FIELDS = ("id", "category", "detector", "caught_by", "severity")
DEFAULT_LEDGER = Path("audit_ledger.jsonl")


class LedgerError(ValueError):
    """Raised when ledger data is malformed or violates the canonical schema."""


def validate_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and copy one canonical ledger record."""
    if not isinstance(record, Mapping):
        raise LedgerError("record must be a JSON object")

    missing = [field for field in REQUIRED_FIELDS if field not in record]
    if missing:
        raise LedgerError(f"missing required fields: {', '.join(missing)}")

    copied = dict(record)
    for field in REQUIRED_FIELDS:
        value = copied[field]
        if not isinstance(value, str) or not value.strip():
            raise LedgerError(f"{field} must be a non-empty string")

    severity = copied["severity"]
    if severity not in VALID_SEVERITIES:
        allowed = ", ".join(VALID_SEVERITIES)
        raise LedgerError(f"unknown severity {severity!r}; expected one of: {allowed}")

    return copied


def load_records(path: str | Path = DEFAULT_LEDGER) -> list[dict[str, Any]]:
    """Load and validate every non-empty JSONL record."""
    ledger_path = Path(path)
    if not ledger_path.exists():
        return []

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    with ledger_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                raise LedgerError(f"{ledger_path}:{line_number}: invalid JSON: {exc}") from exc
            try:
                record = validate_record(parsed)
            except LedgerError as exc:
                raise LedgerError(f"{ledger_path}:{line_number}: {exc}") from exc
            record_id = record["id"]
            if record_id in seen_ids:
                raise LedgerError(f"{ledger_path}:{line_number}: duplicate id {record_id!r}")
            seen_ids.add(record_id)
            records.append(record)
    return records


def append_record(record: Mapping[str, Any], path: str | Path = DEFAULT_LEDGER) -> dict[str, Any]:
    """Validate and append one record without rewriting existing ledger entries."""
    validated = validate_record(record)
    ledger_path = Path(path)
    existing_ids = {row["id"] for row in load_records(ledger_path)}
    if validated["id"] in existing_ids:
        raise LedgerError(f"duplicate id {validated['id']!r}")

    serialized = json.dumps(validated, ensure_ascii=False, sort_keys=True) + "\n"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(serialized)
        handle.flush()
        os.fsync(handle.fileno())
    return validated


def _representative_challenges(
    records: Sequence[Mapping[str, Any]],
) -> list[tuple[str, Mapping[str, Any]]]:
    by_category: dict[str, Mapping[str, Any]] = {}
    for raw_record in records:
        record = validate_record(raw_record)
        category = record["category"]
        current = by_category.get(category)
        if current is None or SEVERITY_RANK[record["severity"]] > SEVERITY_RANK[
            current["severity"]
        ]:
            by_category[category] = record
    return sorted(
        by_category.items(),
        key=lambda item: (-SEVERITY_RANK[item[1]["severity"]], item[0]),
    )


def render_challenges(records: Sequence[Mapping[str, Any]]) -> str:
    """Render historical miss categories as builder-side mandatory challenges."""
    if not records:
        return "(ledger empty; no historical misses yet)"

    challenges = _representative_challenges(records)
    lines = [
        "=" * 88,
        (
            "Historical misses → mandatory challenges for this audit "
            f"({len(challenges)} categories, {len(records)} records)"
        ),
        (
            "For each category: explicitly state whether this project could make the same error, "
            "and how you verify it doesn't."
        ),
        "=" * 88,
    ]
    for index, (category, record) in enumerate(challenges, 1):
        lines.extend(
            [
                "",
                (
                    f"[{index}] {category}  ({record['severity']}, "
                    f"first seen in project: {record.get('project', '?')})"
                ),
                f"    Detector: {record['detector']}",
            ]
        )
    lines.extend(["", "=" * 88])
    return "\n".join(lines)


def render_stats(records: Sequence[Mapping[str, Any]]) -> str:
    """Render ledger distributions without making causal claims from tiny samples."""
    validated = [validate_record(record) for record in records]
    internal = sum(
        1 for record in validated if record.get("caught_by", "").startswith("internal")
    )
    reviewer = sum(1 for record in validated if record.get("caught_by") == "reviewer")
    lines = [
        f"Total miss records: {len(validated)}",
        f"By category: {dict(Counter(record['category'] for record in validated))}",
        f"Caught by  : {dict(Counter(record['caught_by'] for record in validated))}",
        f"By severity: {dict(Counter(record['severity'] for record in validated))}",
        f"Self-audit caught {internal}, independent reviewer caught {reviewer}",
    ]
    return "\n".join(lines)


def parse_json_record(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise LedgerError(f"invalid record JSON: {exc}") from exc
    return validate_record(parsed)


def build_parser(default_ledger: str | Path = DEFAULT_LEDGER) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validity Audit cumulative miss ledger")
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path(default_ledger),
        help="JSONL ledger path (default: %(default)s)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("challenges", help="render builder-side historical challenges")
    append_parser = subparsers.add_parser("append", help="append one validated JSON record")
    append_parser.add_argument("record", help="record as a JSON object")
    subparsers.add_parser("stats", help="show ledger distributions")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    default_ledger: str | Path = DEFAULT_LEDGER,
) -> int:
    parser = build_parser(default_ledger)
    args = parser.parse_args(argv)
    try:
        if args.command == "challenges":
            print(render_challenges(load_records(args.ledger)))
        elif args.command == "append":
            record = append_record(parse_json_record(args.record), args.ledger)
            print(f"Appended: {record['id']}  [{record['category']}]")
        elif args.command == "stats":
            print(render_stats(load_records(args.ledger)))
        else:  # pragma: no cover - argparse enforces command choices
            parser.error(f"unknown command: {args.command}")
    except LedgerError as exc:
        parser.exit(1, f"Ledger error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
