#!/usr/bin/env python3
"""Compatibility entry point for the v0.2 ledger command.

New code should import :mod:`validity_audit.ledger` or use
``validity-audit-ledger``. This shim preserves the historical command, its
no-argument ``challenges`` default, and its ``protocol/audit_ledger.jsonl``
location.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from validity_audit import ledger as _ledger  # noqa: E402

LedgerError = _ledger.LedgerError
append_record = _ledger.append_record
load_records = _ledger.load_records
render_challenges = _ledger.render_challenges
render_stats = _ledger.render_stats
validate_record = _ledger.validate_record
ledger_main = _ledger.main

LEDGER = Path(__file__).with_name("audit_ledger.jsonl")


def load():
    """Return records from the legacy default location."""
    return load_records(LEDGER)


def challenges():
    """Print challenges from the legacy default location."""
    print(render_challenges(load()))


def append(js):
    """Append a JSON string to the legacy default location."""
    import json

    record = append_record(json.loads(js), LEDGER)
    print(f"Appended: {record['id']}  [{record['category']}]")


def stats():
    """Print stats from the legacy default location."""
    print(render_stats(load()))


if __name__ == "__main__":
    arguments = sys.argv[1:] or ["challenges"]
    raise SystemExit(ledger_main(arguments, default_ledger=LEDGER))
