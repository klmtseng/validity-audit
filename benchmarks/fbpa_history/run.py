#!/usr/bin/env python3
"""Driver for the FBPA historical validation (S2, docs/specs/probe-fail-before-pass-after.md §7).

Runs the FBPA probe against every merged PR listed in ``prs.txt``, treating
each PR's merge commit as ``head`` and, by default, its parent as ``base``.
Squash merges need nothing more; a rebase merge (PR #5, two first-parent
commits on master) names its real base in a third ``prs.txt`` column. ``auto_discover`` is used
because historical PRs have no ``fail_before_pass_after`` contract.

The probe implementation is always imported from THIS checkout (the repo
containing this script), never from the editable install registered on the
machine (``pip show validity-audit`` -> ``~/src/va-audit``, a
different, older checkout). Importing the wrong copy would silently run an
older/different probe. See spec §2 "Import-origin canary" for the analogous
risk inside the probe itself; this check is about the driver's own import.

For each PR, ``run_fbpa`` is handed a disposable ``git clone`` of this repo
(never the main repo tree) as ``repo_root``, so the ``git worktree add/remove``
calls it makes never touch the main working tree. The clone is removed when
the PR finishes, success or failure.

Resumable: a PR whose ``results/pr-<n>.json`` already exists is skipped unless
``--force``. Each PR is checkpointed to its own file as soon as it finishes, so
a run interrupted between PRs loses no completed work.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

# Must happen before importing validity_audit: put this checkout ahead of
# anything else on sys.path (including the editable install's site-packages
# entry), then verify the import actually resolved here.
sys.path.insert(0, str(REPO_ROOT))

import validity_audit  # noqa: E402

_resolved_pkg_file = Path(validity_audit.__file__).resolve()
if REPO_ROOT not in (_resolved_pkg_file, *_resolved_pkg_file.parents):
    raise RuntimeError(
        f"validity_audit imported from {_resolved_pkg_file}, which is not inside "
        f"{REPO_ROOT}. The editable install is shadowing this checkout; refusing "
        "to run the historical probe against the wrong implementation."
    )

from validity_audit.fbpa import run_fbpa  # noqa: E402

PRS_FILE = Path(__file__).resolve().parent / "prs.txt"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

DEFAULT_LIMITS = {"memory_max": "2G", "timeout_s": 300, "repeats": 2}


def _load_prs() -> list[tuple[int, str, str]]:
    """Return ``(pr, head_sha, base)``; base defaults to ``<head>^``.

    A third column overrides the base. It is needed for rebase merges, where a PR
    occupies several first-parent commits on master and ``<head>^`` would measure
    only the last of them (PR #5).
    """
    prs: list[tuple[int, str, str]] = []
    for lineno, raw_line in enumerate(PRS_FILE.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) not in (2, 3):
            raise ValueError(
                f"{PRS_FILE}:{lineno}: expected '<pr> <sha> [<base>]', got {raw_line!r}"
            )
        pr_str, sha = parts[0], parts[1]
        base = parts[2] if len(parts) == 3 else f"{sha}^"
        prs.append((int(pr_str), sha, base))
    return prs


def _environment() -> dict[str, Any]:
    import site

    return {
        "python": sys.version.split()[0],
        "venv": sys.prefix != sys.base_prefix,
        "user_site_enabled": bool(site.ENABLE_USER_SITE),
        # Missing optional deps (the `quant` extra CI installs) turn head runs into
        # errors/skips, so the versions are evidence too.
        "packages": {name: _version(name) for name in _ENV_PACKAGES},
    }


_ENV_PACKAGES = ("pytest", "jsonschema", "numpy", "pandas", "scipy")


def _version(name: str) -> str | None:
    from importlib import metadata

    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _fresh_clone(scratch_root: Path, pr: int) -> Path:
    clone_dir = Path(tempfile.mkdtemp(prefix=f"fbpa-clone-pr{pr}-", dir=str(scratch_root)))
    # Clone from the main checkout's .git, not from a worktree-mutated state;
    # this clone is disposable and discarded at the end of _run_one.
    subprocess.run(
        ["git", "clone", "--quiet", "--no-local", "--", str(REPO_ROOT), str(clone_dir)],
        check=True,
        cwd=str(REPO_ROOT),
    )
    return clone_dir


def _run_one(pr: int, sha: str, base: str, scratch_root: Path) -> dict[str, Any]:
    clone = _fresh_clone(scratch_root, pr)
    try:
        contract = {
            "base": base,
            "head": sha,
            "runner": "pytest",
            "auto_discover": True,
            "claims": [],
            "limits": dict(DEFAULT_LIMITS),
        }
        fbpa_result = run_fbpa(clone, contract)
    finally:
        shutil.rmtree(clone, ignore_errors=True)
    # Normalized output only (spec §2): no absolute paths. The PR/sha identify
    # the inputs; the contract's base/head are commit-ish strings (not paths);
    # fbpa_result is already normalized by the probe itself (worktree paths
    # are stripped in first_failure_line, canary paths are worktree-relative).
    return {
        "pr": pr,
        "sha": sha,
        # The interpreter environment decides what the base side can import
        # (an editable install of another checkout serves missing submodules),
        # so it is part of the evidence. No paths, only properties.
        "environment": _environment(),
        "contract": {
            "base": contract["base"],
            "head": contract["head"],
            "runner": contract["runner"],
            "auto_discover": contract["auto_discover"],
            "limits": contract["limits"],
        },
        "fbpa_result": fbpa_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pr",
        type=int,
        action="append",
        dest="prs",
        help="run only this PR number (repeatable); default is every PR in prs.txt",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="rerun a PR even if results/pr-<n>.json already exists",
    )
    parser.add_argument(
        "--scratch",
        type=str,
        default=None,
        help="directory to hold disposable clones (default: a fresh mkdtemp)",
    )
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    all_prs = _load_prs()
    wanted = set(args.prs) if args.prs else {pr for pr, _, _ in all_prs}
    known = {pr for pr, _, _ in all_prs}
    unknown = wanted - known
    if unknown:
        print(f"unknown PR number(s) not in prs.txt: {sorted(unknown)}", file=sys.stderr)
        return 2

    if args.scratch:
        scratch_root = Path(args.scratch)
        scratch_root.mkdir(parents=True, exist_ok=True)
        owns_scratch = False
    else:
        scratch_root = Path(tempfile.mkdtemp(prefix="fbpa-run-scratch-"))
        owns_scratch = True

    exit_code = 0
    try:
        for pr, sha, base in all_prs:
            if pr not in wanted:
                continue
            out_path = RESULTS_DIR / f"pr-{pr}.json"
            if out_path.exists() and not args.force:
                print(f"PR {pr}: skip (result exists at {out_path.name})")
                continue
            print(f"PR {pr}: running (base={base}, head={sha})", flush=True)
            try:
                record = _run_one(pr, sha, base, scratch_root)
            except Exception:  # noqa: BLE001 - report which PR broke, then stop
                print(f"PR {pr}: driver raised an exception:", file=sys.stderr)
                traceback.print_exc()
                exit_code = 1
                break
            out_path.write_text(
                json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            fbpa_block = record["fbpa_result"]["fbpa"]
            print(
                f"PR {pr}: wrote {out_path.name} "
                f"(in_scope={fbpa_block['in_scope']} judged={fbpa_block['judged']} "
                f"counts={fbpa_block['counts']})",
                flush=True,
            )
    finally:
        if owns_scratch:
            shutil.rmtree(scratch_root, ignore_errors=True)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
