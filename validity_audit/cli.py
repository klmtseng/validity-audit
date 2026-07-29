"""Command-line entry point for the two-stage v0.3 runtime."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from validity_audit.runtime import AuditRuntimeError, finalize_run, prepare_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="validity-audit",
        description="Prepare and finalize one bounded, unsigned validity attestation.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser(
        "prepare",
        help="validate inputs, snapshot artifacts, run probes, and emit a review bundle",
    )
    prepare.add_argument("--workspace", type=Path, default=Path("."))
    prepare.add_argument("--contract", type=Path, required=True)
    prepare.add_argument("--run-dir", type=Path, required=True)
    prepare.add_argument("--run-id")
    prepare.add_argument("--started-at")
    prepare.add_argument("--previous-run-id", action="append", default=[])
    prepare.add_argument("--review-context", choices=["cold", "primed"], required=True)
    prepare.add_argument(
        "--reviewer-kind",
        choices=["human", "model", "hybrid"],
        required=True,
    )
    prepare.add_argument("--reviewer-label", required=True)
    prepare.add_argument("--operator-id", required=True)
    prepare.add_argument("--priming-source", action="append", default=[])

    finalize = subparsers.add_parser(
        "finalize",
        help="import reviewer evidence, apply policy, and emit an unsigned attestation",
    )
    finalize.add_argument("--workspace", type=Path, default=Path("."))
    finalize.add_argument("--run-dir", type=Path, required=True)
    finalize.add_argument("--reviewer-output", type=Path, required=True)
    finalize.add_argument("--transcript", type=Path, required=True)
    finalize.add_argument("--completed-at")
    finalize.add_argument("--issued-at")
    finalize.add_argument("--attestation-id")
    finalize.add_argument("--ledger", type=Path)
    finalize.add_argument(
        "--no-ledger",
        action="store_true",
        help="do not append the finalized attestation receipt to the workspace ledger",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_run(
                workspace=args.workspace,
                contract_path=args.contract,
                run_dir=args.run_dir,
                review_context=args.review_context,
                reviewer_kind=args.reviewer_kind,
                reviewer_label=args.reviewer_label,
                operator_id=args.operator_id,
                priming_sources=args.priming_source,
                run_id=args.run_id,
                started_at=args.started_at,
                previous_run_ids=args.previous_run_id,
            )
        else:
            result = finalize_run(
                workspace=args.workspace,
                run_dir=args.run_dir,
                reviewer_output_path=args.reviewer_output,
                transcript_path=args.transcript,
                completed_at=args.completed_at,
                issued_at=args.issued_at,
                attestation_id=args.attestation_id,
                ledger_path=args.ledger,
                append_ledger=not args.no_ledger,
            )
    except (AuditRuntimeError, OSError) as exc:
        parser.exit(1, f"Validity Audit error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
