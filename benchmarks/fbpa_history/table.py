#!/usr/bin/env python3
"""Generate docs/specs/fbpa-history-v0.5.0.md from benchmarks/fbpa_history/results/*.json.

This file is GENERATED. Never hand-edit the markdown output; edit this script
instead and regenerate. See docs/specs/probe-fail-before-pass-after.md §7
(S2 historical validation plan) for what the table is supposed to show.

Also performs an internal consistency check per PR (spec §4.1): the number of
claims in scope must equal the number of distinct claim-level checks, and the
sum of the §4.1 bucket counts must equal the number of claims plus the number
of claims that landed in two buckets at once (the only two-bucket case the
spec allows is a `fixes` claim that is both `base_passes` and
`head_not_passing` -- base already passed, and head's own implementation
still does not pass it either). A mismatch means the report itself is
internally inconsistent and must not be trusted; the script exits nonzero
without writing the md.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = Path(__file__).resolve().parent / "results"
OUT_PATH = REPO_ROOT / "docs" / "specs" / "fbpa-history-v0.5.0.md"

COMMAND_TEMPLATE = (
    "systemd-run --user --scope -q -p MemoryMax=4G -p MemorySwapMax=0 -- "
    "python3 benchmarks/fbpa_history/run.py --pr <n>"
)


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(REPO_ROOT), capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _load_records() -> list[dict[str, Any]]:
    records = []
    for path in sorted(RESULTS_DIR.glob("pr-*.json")):
        records.append(json.load(path.open(encoding="utf-8")))
    records.sort(key=lambda r: r["pr"])
    return records


def _reason_breakdown(checks: list[dict[str, Any]], prefix: str) -> dict[str, int]:
    """Tally `inconclusive:<reason>` or `fault:<code>` components by their suffix."""
    out: dict[str, int] = {}
    for check in checks:
        for component in check["components"]:
            if component.startswith(prefix):
                key = component[len(prefix) :]
                out[key] = out.get(key, 0) + 1
    return out


def _fmt_breakdown(breakdown: dict[str, int]) -> str:
    if not breakdown:
        return "-"
    return ", ".join(f"{k}:{v}" for k, v in sorted(breakdown.items()))


def _check_consistency(record: dict[str, Any]) -> list[str]:
    """Return a list of problems (empty if consistent) for one PR's record."""
    problems: list[str] = []
    pr = record["pr"]
    fbpa = record["fbpa_result"]["fbpa"]
    checks = record["fbpa_result"]["checks"]
    in_scope = fbpa["in_scope"]

    if len(checks) != in_scope:
        problems.append(
            f"PR {pr}: in_scope={in_scope} but {len(checks)} claim-level checks "
            "are present (expected equal, one check per claim)"
        )

    multi_bucket = [c for c in checks if len(c["verdicts"]) > 1]
    for check in multi_bucket:
        if check["verdicts"] != ["base_passes", "head_not_passing"]:
            problems.append(
                f"PR {pr}: claim {check['path']} has an unexpected multi-bucket "
                f"verdict set {check['verdicts']!r} (spec §3.4 allows only "
                "['base_passes', 'head_not_passing'] as a two-bucket claim)"
            )

    expected_total = in_scope + len(multi_bucket)
    actual_total = sum(fbpa["counts"].values())
    if expected_total != actual_total:
        problems.append(
            f"PR {pr}: claims ({in_scope}) + multi-bucket claims ({len(multi_bucket)}) "
            f"= {expected_total}, but sum(counts.values()) = {actual_total} "
            f"(counts={fbpa['counts']!r})"
        )
    return problems


_VERSION_OR_CONSTANT_KEYWORDS = ("version", "const")


def _heuristic_flags(check: dict[str, Any]) -> list[str]:
    """Simple, explicitly-labeled heuristics (task-requested, not probe output).

    - "exc-only": the claim was ``demonstrated`` solely through ``B_FAIL_EXC``
      (an exception, not an assertion) -- spec §9 flags this as weaker evidence
      than ``B_FAIL_ASSERT``.
    - "heuristic:name-version-or-constant": the node id's test name contains
      "version" or "const" (case-insensitive). This is a crude name-based
      heuristic, not an AST check, and is labeled as such deliberately (spec §9:
      "a test that only asserts a constant ... is weak evidence").
    """
    flags: list[str] = []
    if check["verdict"] == "demonstrated" and check["base_verdict"] == "B_FAIL_EXC":
        flags.append("exc-only")
    name = check["path"].rsplit("::", 1)[-1].lower()
    if any(kw in name for kw in _VERSION_OR_CONSTANT_KEYWORDS):
        flags.append("heuristic:name-version-or-constant")
    return flags


def _case_summary(cases: list[dict[str, Any]]) -> str:
    """Render per-case outcome/exc_type/first_failure_line for the enumeration row."""
    if not cases:
        return "-"
    parts = []
    for case in cases:
        bits = [case["outcome"]]
        if case.get("phase"):
            bits.append(case["phase"])
        if case.get("exc_type"):
            bits.append(case["exc_type"])
        parts.append(f"{case['name']}: {'/'.join(bits)}")
    return "; ".join(parts)


def _first_failure_lines(cases: list[dict[str, Any]]) -> str:
    lines = [c["first_failure_line"] for c in cases if c.get("first_failure_line")]
    if not lines:
        return "-"
    # Escape pipes so a traceback fragment never breaks the markdown table.
    return "<br>".join(line.replace("|", "\\|").replace("\n", " ") for line in lines)


def _finding_types_for(record: dict[str, Any], node_id: str) -> list[str]:
    out = []
    for finding in record["fbpa_result"]["findings"]:
        locator = finding.get("evidence", [{}])[0].get("locator")
        if locator == node_id:
            out.append(finding["finding_type"])
    return out


def _build_summary_rows(records: list[dict[str, Any]]) -> list[str]:
    header = (
        "| PR | base SHA | head SHA | non_test_diff_count | claims | demonstrated | "
        "base_passes | head_not_passing | absence_only | inconclusive (by reason) | "
        "faults (by code) |"
    )
    sep = "|---|---|---|---|---|---|---|---|---|---|---|"
    rows = [header, sep]
    for record in records:
        fbpa = record["fbpa_result"]["fbpa"]
        checks = record["fbpa_result"]["checks"]
        resolved = fbpa["resolved"]
        base_sha12 = resolved.get("base", "")[:12] if resolved.get("base") else "-"
        head_sha12 = resolved.get("head", "")[:12] if resolved.get("head") else "-"
        counts = fbpa["counts"]
        claims = fbpa["in_scope"]
        label = "not_applicable" if claims == 0 else str(claims)
        inconclusive_breakdown = _fmt_breakdown(_reason_breakdown(checks, "inconclusive:"))
        fault_breakdown = _fmt_breakdown(_reason_breakdown(checks, "fault:"))
        rows.append(
            "| {pr} | {base} | {head} | {ntd} | {claims} | {demo} | {bp} | {hnp} | {ao} | "
            "{inc} | {faults} |".format(
                pr=record["pr"],
                base=base_sha12,
                head=head_sha12,
                ntd=fbpa["non_test_diff_count"],
                claims=label,
                demo=counts.get("demonstrated", 0),
                bp=counts.get("base_passes", 0),
                hnp=counts.get("head_not_passing", 0),
                ao=counts.get("absence_only", 0),
                inc=inconclusive_breakdown,
                faults=fault_breakdown,
            )
        )
    return rows


def _build_enumeration_rows(records: list[dict[str, Any]]) -> list[str]:
    header = (
        "| PR | test node id | base class (per-case B_* and exc type) | "
        "base first_failure_line | head result | verdict | finding_type | flags |"
    )
    sep = "|---|---|---|---|---|---|---|---|"
    rows = [header, sep]
    for record in records:
        checks = sorted(record["fbpa_result"]["checks"], key=lambda c: c["path"])
        for check in checks:
            base_class = check["base_verdict"] or "-"
            per_case = _case_summary(check["base_cases"])
            base_class_cell = base_class if per_case == "-" else f"{base_class} ({per_case})"
            base_first_failure = _first_failure_lines(check["base_cases"])
            head_result = check["head_verdict"] or "-"
            verdict = ", ".join(check["verdicts"])
            finding_types = _finding_types_for(record, check["path"])
            finding_type_cell = ", ".join(finding_types) if finding_types else "(none)"
            flags = _heuristic_flags(check)
            flags_cell = ", ".join(flags) if flags else "-"
            node_id_cell = check["path"].replace("|", "\\|")
            rows.append(
                f"| {record['pr']} | {node_id_cell} | {base_class_cell} | "
                f"{base_first_failure} | {head_result} | {verdict} | {finding_type_cell} | "
                f"{flags_cell} |"
            )
    return rows


def _build_base_passes_list(records: list[dict[str, Any]]) -> list[str]:
    lines = ["## PRs with at least one `base_passes`", ""]
    any_found = False
    for record in records:
        checks = record["fbpa_result"]["checks"]
        count = sum(1 for c in checks if "base_passes" in c["verdicts"])
        if count:
            any_found = True
            lines.append(f"- PR {record['pr']}: {count}")
    if not any_found:
        lines.append("- (none)")
    lines.append("")
    return lines


def main() -> int:
    records = _load_records()

    problems: list[str] = []
    for record in records:
        problems.extend(_check_consistency(record))
    if problems:
        print("fbpa history table: internal consistency check FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    # The commit that last touched the probe implementation, not current HEAD:
    # HEAD moves every time this generated file itself is committed, which
    # would make "current HEAD" a moving target and break reproducibility of
    # this file across unrelated later commits (docs, benchmarks/ churn).
    probe_sha = _git("log", "-1", "--format=%H", "--", "validity_audit/fbpa.py")
    probe_date = _git(
        "log", "-1", "--format=%ad", "--date=short", "--", "validity_audit/fbpa.py"
    )
    backends = sorted({r["fbpa_result"]["fbpa"]["limiter_backend"] for r in records})
    backend_str = ", ".join(backends) if backends else "(none)"

    lines: list[str] = []
    lines.append("# FBPA historical validation (S2)")
    lines.append("")
    spec_link = (
        "[probe-fail-before-pass-after.md §7]"
        "(probe-fail-before-pass-after.md#7-s2-historical-validation-plan)"
    )
    lines.append(
        "Generated by `benchmarks/fbpa_history/table.py` from "
        "`benchmarks/fbpa_history/results/*.json`. Do not hand-edit; rerun the "
        f"generator instead. See {spec_link}."
    )
    lines.append("")
    lines.append(
        f"- Probe commit (last commit touching `validity_audit/fbpa.py`): `{probe_sha}`"
    )
    lines.append(f"- Date (that commit's author date): {probe_date}")
    lines.append(f"- Limiter backend used for every run: {backend_str}")
    envs = sorted(
        {json.dumps(r.get("environment"), sort_keys=True) for r in records}
    )
    lines.append(f"- Interpreter environment(s): {', '.join(f'`{e}`' for e in envs)}")
    lines.append(f"- Command used per PR: `{COMMAND_TEMPLATE}`")
    lines.append(
        "- `auto_discover: true` was used for every PR (historical PRs carry no "
        "`fail_before_pass_after` contract); `claims: []`, `limits: "
        '{"memory_max": "2G", "timeout_s": 300, "repeats": 2}`.'
    )
    lines.append(
        "- 7 PRs touch no test file under `test_paths` and so have 0 claims in "
        "scope; they are listed below as `not_applicable`, per spec §7, not dropped."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.extend(_build_summary_rows(records))
    lines.append("")
    lines.extend(_build_base_passes_list(records))
    lines.append("## Full enumeration")
    lines.append("")
    lines.append(
        "Every claimed (including auto-discovered) test, one row per claim. "
        "`finding_type` is `(none)` for `demonstrated`/`no_finding` claims, which "
        "produce no finding. `flags` are driver-side heuristics (see "
        "`table.py:_heuristic_flags`), not probe output; they do not affect the "
        "verdict and are not a substitute for the human read-by-hand pass spec §7 "
        "requires for every `base_passes` row."
    )
    lines.append("")
    lines.extend(_build_enumeration_rows(records))
    lines.append("")

    content = "\n".join(lines) + "\n"
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(content, encoding="utf-8")
    claim_rows = sum(len(r["fbpa_result"]["checks"]) for r in records)
    print(f"wrote {OUT_PATH} ({len(records)} PRs, {claim_rows} claim rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
