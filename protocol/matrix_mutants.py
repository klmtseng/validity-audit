#!/usr/bin/env python3
"""Mutation regression for tests/test_policy_matrix.py.

Each mutant plants a known policy bug into a temporary copy of the package and
runs the matrix test against it. Every mutant must make the matrix fail
("caught"). An unmutated copy must pass first, otherwise the run is void.

Exit codes: 0 = clean copy passes and every mutant is caught; 1 = at least one
mutant survived, or the clean copy failed, or a copy imported the wrong module;
2 = a mutant no longer applies to the current source (update this file together
with the policy). Variants run in parallel, one temporary copy each.

M1-M4 come from the round-four review of PR #27, which found M2 surviving a
too-wide exemption in the matrix; M5 is the R1 bug from the same review. M6-M7
come from the heterogeneous review of 4e13671 (P1-1), which showed both survived.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = Path("validity_audit/policy.py")

MUTANTS: dict[str, list[tuple[str, str]]] = {
    # Revert H1: a waiver on a finding of an unbound refutation is rejected again.
    "M1_revert_h1": [(
        "            and finding[\"finding_id\"] in unbound_refutation_finding_ids\n",
        "            and False\n",
    )],
    # A finding cited by an unbound refutation loses even its own fail-class fail.
    "M2_unbound_softens_failclass": [(
        "        original_effect = (\n",
        "        if finding[\"finding_id\"] in unbound_refutation_finding_ids "
        "and waiver_request is None:\n"
        "            reproduction = \"unreproduced\"\n"
        "        original_effect = (\n",
    )],
    # Downgraded claims stop counting as unresolved.
    "M3_ignore_downgraded_claims": [(
        "result[\"outcome\"] in {\"inconclusive\", \"not_evaluated\"} for result in claim_results",
        "result[\"outcome\"] in {\"inconclusive\", \"not_evaluated\"} "
        "and \"evidence_gate\" not in result for result in claim_results",
    )],
    # Drop D2: the absence rule softens a finding behind a bound refutation.
    "M4_absence_softens_bound_refutation": [(
        "            elif finding[\"finding_id\"] in refuted_finding_ids:\n"
        "                finding[\"absence_coverage\"] = \"not_required\"\n",
        "",
    )],
    # Revert R1: a waiver on a reviewer-unreproduced finding of an unbound
    # refutation is accepted (needs_review) instead of rejected as in legacy.
    "M5_revert_r1": [(
        "            and finding[\"reproduction\"] not in NON_REPRODUCED\n",
        "",
    )],
    # Drop the fail-class exclusion: a waiver on a finding that keeps its own
    # fail-class fail is withheld as refutation_unbound (run fail, not waived).
    "M6_withhold_failclass_waiver": [(
        "            and not (configured_effect == \"fail\" "
        "and reproduction not in NON_REPRODUCED)\n",
        "",
    )],
    # Swap the two not_applied_because reason codes.
    "M7_swap_unapplied_reasons": [
        ("and configured_effect == \"fail\":\n"
         "            withheld_because = \"absence_coverage_unproven\"\n",
         "and configured_effect == \"fail\":\n"
         "            withheld_because = \"refutation_unbound\"\n"),
        ("# below, exactly as without the discipline.\n"
         "            withheld_because = \"refutation_unbound\"\n",
         "# below, exactly as without the discipline.\n"
         "            withheld_because = \"absence_coverage_unproven\"\n"),
    ],
}


def _copy_tree(destination: Path) -> None:
    for name in ("validity_audit", "tests", "schemas"):
        shutil.copytree(ROOT / name, destination / name,
                        ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT / "pyproject.toml", destination / "pyproject.toml")


def _run_matrix(workdir: Path) -> tuple[int, str]:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x",
         "tests/test_policy_matrix.py"],
        cwd=workdir, capture_output=True, text=True,
        env={"PYTHONPATH": str(workdir), "PYTHONDONTWRITEBYTECODE": "1",
             "PATH": "/usr/bin:/bin"},
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    return completed.returncode, lines[-1] if lines else completed.stderr.strip()[-200:]


def inapplicable(source: str) -> list[str]:
    """Mutants whose patterns do not occur exactly once in ``source``."""
    return [
        f"{name}: pattern found {source.count(old)} times"
        for name, edits in MUTANTS.items()
        for old, _ in edits
        if source.count(old) != 1
    ]


def _origin_ok(workdir: Path) -> bool:
    origin = subprocess.run(
        [sys.executable, "-c", "import validity_audit.policy as p; print(p.__file__)"],
        cwd=workdir, capture_output=True, text=True,
        env={"PYTHONPATH": str(workdir), "PYTHONDONTWRITEBYTECODE": "1"},
    ).stdout.strip()
    return bool(origin) and Path(origin).resolve().is_relative_to(workdir.resolve())


def _run_variant(base: Path, name: str, source: str) -> tuple[str, int, str]:
    """Copy the tree, apply mutant ``name`` (or none for "clean"), run the matrix."""
    workdir = base / name
    _copy_tree(workdir)
    mutated = source
    for old, new in MUTANTS.get(name, []):
        mutated = mutated.replace(old, new, 1)
    (workdir / TARGET).write_text(mutated, encoding="utf-8")
    if not _origin_ok(workdir):
        return name, -1, "policy module not imported from the mutated copy"
    code, tail = _run_matrix(workdir)
    return name, code, tail


def main() -> int:
    source = (ROOT / TARGET).read_text(encoding="utf-8")
    problems = inapplicable(source)
    if problems:
        print(f"RESULT: STALE — mutants no longer apply to {TARGET}: " + "; ".join(problems))
        return 2

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="va-matrix-mutants-") as tmp:
        names = ["clean", *MUTANTS]
        with ThreadPoolExecutor(max_workers=min(len(names), os.cpu_count() or 1)) as pool:
            results = {name: (code, tail) for name, code, tail in
                       pool.map(lambda n: _run_variant(Path(tmp), n, source), names)}
    elapsed = time.monotonic() - started

    code, tail = results["clean"]
    print(f"clean: exit={code} :: {tail}")
    if code != 0:
        print(f"RESULT: VOID — the unmutated matrix does not pass ({elapsed:.0f}s)")
        return 1
    survivors = []
    for name in MUTANTS:
        code, tail = results[name]
        # Caught means the matrix ran and reported failing tests (pytest exit 1),
        # not that it crashed or could not import the copy.
        caught = code == 1 and " failed" in tail
        print(f"{name}: {'caught' if caught else 'NOT CAUGHT'} (exit={code}) :: {tail}")
        if not caught:
            survivors.append(name)
    caught_count = len(MUTANTS) - len(survivors)
    verdict = "PASS" if not survivors else "FAIL"
    print(f"RESULT: {verdict} — {caught_count}/{len(MUTANTS)} mutants caught"
          f"{'' if not survivors else '; not caught: ' + ', '.join(survivors)}"
          f" ({elapsed:.0f}s)")
    return 0 if not survivors else 1


if __name__ == "__main__":
    raise SystemExit(main())
