"""Deterministic fail-before / pass-after (FBPA) probe.

See ``docs/specs/probe-fail-before-pass-after.md`` for the full specification this
module implements. In short: a contract can claim that a specific pytest node id
*fixes* a bug (it must fail at ``base`` and pass at ``head``) or *characterizes*
existing behaviour (it only has to pass at ``head``). This module checks that
claim with git worktrees and real pytest runs -- no LLM involved -- and returns
findings that slot into the existing probe/policy pipeline unchanged.

Everything this module returns must be reproducible byte for byte on a rerun:
no timings, no absolute paths, and no temporary directory names may leak into
the report (see ``runtime.py``'s "rerun must match" check). Helper functions are
careful to translate any worktree-relative fact (an import's resolved file, an
overlay target) into a path relative to the worktree, to compose detail strings
from fixed vocabulary rather than raw subprocess output, and to iterate over
files, claims and symbols in sorted order so that two machines produce the same
report (``os.walk`` order is filesystem dependent).
"""

from __future__ import annotations

import ast
import fnmatch
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

PROBE_VERSION = "0.6.0"

DEFAULT_TEST_PATHS = ["tests/**", "**/test_*.py", "**/conftest.py"]
DEFAULT_LIMITS: dict[str, Any] = {"memory_max": "2G", "timeout_s": 600, "repeats": 2}

# The closed vocabulary of infrastructure fault codes this probe can emit.
# See spec section 2.1 for the exit-code contract these come from.
FAULT_CODES = frozenset(
    {
        "F_ENV_IMPORT",
        "F_FLAKY",
        "F_RUNNER",
        "F_NOT_COLLECTED",
        "F_TIMEOUT",
        "F_OOM",
        "F_EXIT_XML_MISMATCH",
        "F_NO_REPORT",
    }
)

# The closed vocabulary of ``finding_type`` values (spec section 4, first column).
FINDING_TYPES = frozenset(
    {
        "fbpa-base-passes",
        "fbpa-head-not-passing",
        "fbpa-fault",
        "fbpa-inconclusive",
        "fbpa-absence-only",
    }
)

_MEMORY_UNITS = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}

# ``timeout -k``: how long a test that ignores SIGTERM gets before SIGKILL.
_KILL_GRACE_S = 5
# Extra wall-clock slack before the Python-side backstop kills the whole
# process group itself (in case ``timeout`` itself is stuck or was killed).
_BACKSTOP_SLACK_S = 30


class FbpaError(RuntimeError):
    """Raised for a contract or environment problem that is not a per-claim fault."""


class FbpaInvariantError(FbpaError):
    """Raised when the probe's own output violates a documented invariant.

    A dedicated exception class (rather than ``raise AssertionError(...)``) so the
    check is not confused with, and cannot be mistaken for, a bare ``assert``
    statement -- those are stripped under ``python -O``, this raise is not.
    """


# ---------------------------------------------------------------------------
# glob matching for ``test_paths``
# ---------------------------------------------------------------------------


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a ``test_paths``-style glob (supports ``**``) into a regex."""
    parts: list[str] = []
    i, n = 0, len(pattern)
    while i < n:
        char = pattern[i]
        if char == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                if i + 2 < n and pattern[i + 2] == "/":
                    parts.append("(?:.*/)?")
                    i += 3
                    continue
                parts.append(".*")
                i += 2
                continue
            parts.append("[^/]*")
            i += 1
            continue
        if char == "?":
            parts.append("[^/]")
            i += 1
            continue
        parts.append(re.escape(char))
        i += 1
    return re.compile("^" + "".join(parts) + "$")


def _compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    return [_glob_to_regex(pattern) for pattern in patterns]


def _matches_any(relpath: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(pattern.match(relpath) for pattern in patterns)


# ---------------------------------------------------------------------------
# git / worktree plumbing
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


# Both worktrees use this leaf name under their own temporary parent (spec §1.2),
# so a test cannot tell base from head by its path.
_WORKTREE_LEAF = "wt"


def _add_worktree(repo: Path, parent: Path, side: str, commit: str) -> Path:
    target = parent / _WORKTREE_LEAF
    result = _git(repo, "worktree", "add", "--detach", str(target), commit)
    if result.returncode != 0:
        raise FbpaError(
            f"could not create a {side} worktree for {commit!r}: {result.stderr.strip()}"
        )
    return target


def _remove_worktree(repo: Path, path: Path) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "remove", "--force", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "prune"],
        capture_output=True,
        text=True,
        check=False,
    )
    shutil.rmtree(path, ignore_errors=True)


def _list_files(root: Path) -> list[str]:
    """Every file under ``root`` (minus ``.git``), as sorted posix relpaths."""
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != ".git")
        for name in filenames:
            out.append((Path(dirpath) / name).relative_to(root).as_posix())
    return sorted(out)


def _overlay_test_files(base_wt: Path, head_wt: Path, patterns: list[re.Pattern[str]]) -> list[str]:
    """Make base's test files exactly head's (spec 1.2).

    Every head file matching ``test_paths`` is copied over the base tree, and every
    base file matching ``test_paths`` that does not exist at head is deleted (a
    moved or deleted ``conftest.py`` left at base would change base behaviour).
    A broken symlink among the test files is a contract/environment problem, not a
    per-claim fault, so it raises :class:`FbpaError`.
    """
    overlaid: list[str] = []
    head_files = {rel for rel in _list_files(head_wt) if _matches_any(rel, patterns)}
    for rel in sorted(head_files):
        src = head_wt / rel
        if src.is_symlink() and not src.exists():
            raise FbpaError(f"test file {rel!r} is a broken symlink at head")
        dst = base_wt / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        try:
            shutil.copyfile(src, dst)
        except OSError as exc:
            raise FbpaError(f"could not overlay test file {rel!r}: {exc.strerror}") from exc
        overlaid.append(rel)
    for rel in _list_files(base_wt):
        if _matches_any(rel, patterns) and rel not in head_files:
            (base_wt / rel).unlink()
    return sorted(overlaid)


def _resolve_commit(repo: Path, commit: str) -> str:
    """The full SHA a commit-ish names (spec 1.2: the report pins what was measured)."""
    result = _git(repo, "rev-parse", "--verify", "--end-of-options", f"{commit}^{{commit}}")
    if result.returncode != 0:
        raise FbpaError(f"could not resolve {commit!r} to a commit: {result.stderr.strip()}")
    return result.stdout.strip()


def _ast_dump_at(repo: Path, commit: str, rel: str) -> str | None:
    result = _git(repo, "show", f"{commit}:{rel}")
    if result.returncode != 0:
        return None
    try:
        return ast.dump(ast.parse(result.stdout))
    except (SyntaxError, ValueError):
        return None


def _non_test_diff_count(repo: Path, base: str, head: str, patterns: list[re.Pattern[str]]) -> int:
    """Changed files outside ``test_paths`` (spec §1.2).

    A ``.py`` file whose ``ast.dump`` is identical at base and head (a comment or
    whitespace edit) does not count: it cannot change behaviour, and counting it
    would let a cosmetic edit switch off the no-implementation-change invariant.
    """
    result = _git(repo, "diff", "--name-only", base, head)
    changed = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    count = 0
    for rel in changed:
        if _matches_any(rel, patterns):
            continue
        if rel.endswith(".py"):
            before, after = _ast_dump_at(repo, base, rel), _ast_dump_at(repo, head, rel)
            if before is not None and before == after:
                continue
        count += 1
    return count


# ---------------------------------------------------------------------------
# memory limiter backend and the one place that spawns limited processes
# ---------------------------------------------------------------------------


def _detect_memory_backend() -> str | None:
    if shutil.which("systemd-run") is not None:
        try:
            probe = subprocess.run(
                [
                    "systemd-run",
                    "--user",
                    "--scope",
                    "-q",
                    "-p",
                    "MemoryMax=16M",
                    "-p",
                    "MemorySwapMax=0",
                    "--",
                    "/bin/true",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            probe = None
        if probe is not None and probe.returncode == 0:
            return "systemd-run"
    try:
        import resource  # noqa: F401
    except ImportError:
        return None
    return "rlimit"


def _parse_memory_bytes(value: str) -> int:
    value = value.strip()
    suffix = value[-1].upper() if value else ""
    if suffix in _MEMORY_UNITS:
        return int(float(value[:-1]) * _MEMORY_UNITS[suffix])
    return int(value)


@dataclass
class _Proc:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool


def _kill_process_group(pgid: int) -> None:
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _stop_unit(unit: str) -> None:
    """Stop a transient systemd scope, killing every process left in its cgroup.

    ``reset-failed`` then drops the unit record: a scope whose process was
    OOM-killed otherwise stays listed as "failed" in the user manager forever.
    """
    for action in ("stop", "reset-failed"):
        try:
            subprocess.run(
                ["systemctl", "--user", action, unit],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired):  # pragma: no cover - defensive
            pass


def _run_limited(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_s: int,
    memory_max: str,
    backend: str,
) -> _Proc:
    """Run ``cmd`` under the memory limit and a hard wall-clock limit.

    Four layers make sure this always returns and leaves nothing behind (spec §2,
    "Process cleanup"):

    1. ``timeout -k`` sends SIGTERM at ``timeout_s`` and SIGKILL ``_KILL_GRACE_S``
       later, to the command's whole process group (``timeout`` without
       ``--foreground`` signals its group), so a test that ignores SIGTERM or
       spawns children still dies.
    2. The child is started in its own session, and a Python-side backstop
       SIGKILLs that entire process group if the wrapper has not exited
       ``_BACKSTOP_SLACK_S`` seconds after ``timeout -k`` should have.
    3. When the run ends for any reason: under systemd every invocation is a
       named transient scope (``fbpa-<uuid>.scope``) that is stopped, which kills
       every process in its cgroup, including grandchildren that called
       ``setsid``; under rlimit the process group is SIGKILLed. Residual limit of
       the rlimit backend: a grandchild that leaves the process group with
       ``setsid`` survives (there is no cgroup to find it by).
    4. The caller's ``finally`` removes the worktrees regardless.

    ``timed_out`` is decided without parsing (locale-dependent) ``timeout``
    diagnostics: exit 124 is unambiguous, and a SIGKILL exit (137/-9) counts as
    a timeout only when the wall-clock limit had actually been reached --
    otherwise it is the memory limiter's kill (F_OOM).
    """
    inner = ["timeout", "-k", str(_KILL_GRACE_S), str(timeout_s), *cmd]
    preexec: Callable[[], None] | None = None
    unit: str | None = None
    if backend == "systemd-run":
        unit = f"fbpa-{uuid.uuid4().hex}.scope"
        full = [
            "systemd-run",
            "--user",
            "--scope",
            f"--unit={unit}",
            "-q",
            "-p",
            f"MemoryMax={memory_max}",
            "-p",
            "MemorySwapMax=0",
            "--",
            *inner,
        ]
    elif backend == "rlimit":
        limit_bytes = _parse_memory_bytes(memory_max)

        def _preexec() -> None:
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))

        preexec = _preexec
        full = inner
    else:  # pragma: no cover - guarded by the caller before this is reached
        raise FbpaError("no memory limiter backend is available")

    started = time.monotonic()
    forced = False
    stdout: str | None = ""
    stderr: str | None = ""
    proc: subprocess.Popen[str] | None = None
    try:
        # Test output is arbitrary bytes: decode leniently so a non-UTF-8 write
        # cannot raise out of the probe.
        proc = subprocess.Popen(
            full,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
            preexec_fn=preexec,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout_s + _KILL_GRACE_S + _BACKSTOP_SLACK_S)
        except subprocess.TimeoutExpired:
            forced = True
            _kill_process_group(proc.pid)
            if unit is not None:
                _stop_unit(unit)
            try:
                stdout, stderr = proc.communicate(timeout=30)
            except subprocess.TimeoutExpired:  # pragma: no cover - a setsid'd child holds the pipe
                proc.kill()
                stdout, stderr = "", ""
    finally:
        if unit is not None:
            _stop_unit(unit)
        if proc is not None:
            if proc.poll() is None:  # pragma: no cover - only on an exception above
                proc.kill()
                proc.wait()
            _kill_process_group(proc.pid)
    elapsed = time.monotonic() - started
    returncode = proc.returncode if proc.returncode is not None else -9
    timed_out = forced or returncode == 124 or (returncode in (137, -9) and elapsed >= timeout_s)
    return _Proc(
        returncode=returncode, stdout=stdout or "", stderr=stderr or "", timed_out=timed_out
    )


# ---------------------------------------------------------------------------
# import-origin canary (spec section 2, orchestrator clarification 1)
# ---------------------------------------------------------------------------


def _default_canary_packages(head_wt: Path) -> list[str]:
    names: set[str] = set()
    for base in (head_wt, head_wt / "src"):
        if not base.is_dir():
            continue
        for child in base.iterdir():
            if child.is_dir() and (child / "__init__.py").is_file():
                names.add(child.name)
    return sorted(names)


def _build_pythonpath(worktree: Path) -> str:
    parts = [str(worktree)]
    src = worktree / "src"
    if src.is_dir():
        parts.append(str(src))
    return os.pathsep.join(parts)


def _subprocess_env(worktree: Path, plugin_dir: Path | None = None) -> dict[str, str]:
    env = dict(os.environ)
    parts = [_build_pythonpath(worktree)]
    if env.get("PYTHONPATH"):
        parts.append(env["PYTHONPATH"])
    if plugin_dir is not None:
        parts.append(str(plugin_dir))  # last, so it can never shadow project code
    env["PYTHONPATH"] = os.pathsep.join(parts)
    # Fixed string hashing: a set/dict repr in a failure message is then the same
    # in every repeat, so a deterministic failure is not misread as F_FLAKY.
    env["PYTHONHASHSEED"] = "0"
    return env


@dataclass
class _CanaryResult:
    # "ok": resolves inside the worktree. "not_found": the import failed outright
    # (ImportError/ModuleNotFoundError) -- benign, e.g. a package head adds that
    # does not exist at base yet. "outside_worktree": the import *succeeded* but
    # resolved to a file outside the worktree -- the genuine F_ENV_IMPORT risk.
    status: str
    relative_path: str | None = None


_CANARY_PROBE_TEMPLATE = (
    "import {package}\n"
    "p = getattr({package}, '__file__', None)\n"
    "if p is not None:\n"
    "    print('FILE:' + p)\n"
    "else:\n"
    "    paths = list(getattr({package}, '__path__', []) or [])\n"
    "    print('PATH:' + ';'.join(paths))\n"
)


def _check_import_canary(
    worktree: Path,
    package: str,
    env: dict[str, str],
    *,
    backend: str,
    memory_max: str,
    timeout_s: int,
) -> _CanaryResult:
    # The canary imports project code, so it runs under the same memory and
    # wall-clock limits as the tests themselves (an import-time allocation bomb
    # must not be able to take the machine down from here either).
    script = _CANARY_PROBE_TEMPLATE.format(package=package)
    proc = _run_limited(
        [sys.executable, "-c", script],
        cwd=worktree,
        env=env,
        timeout_s=timeout_s,
        memory_max=memory_max,
        backend=backend,
    )
    if proc.returncode != 0:
        # Import failed outright: nothing resolved anywhere. This is expected
        # for a package head adds that legitimately does not exist at base.
        return _CanaryResult(status="not_found")
    output = proc.stdout.strip()
    if output.startswith("FILE:"):
        candidates = [output[len("FILE:") :]]
    elif output.startswith("PATH:"):
        # A namespace package (PEP 420): __file__ is None, so fall back to
        # __path__. Namespace packages can merge contributions from several
        # directories; every contribution must resolve inside the worktree.
        candidates = [c for c in output[len("PATH:") :].split(";") if c]
    else:
        return _CanaryResult(status="not_found")
    if not candidates:
        return _CanaryResult(status="not_found")
    worktree_resolved = worktree.resolve()
    relative_paths: list[str] = []
    for candidate in candidates:
        resolved = Path(candidate).resolve()
        try:
            relative_paths.append(resolved.relative_to(worktree_resolved).as_posix())
        except ValueError:
            return _CanaryResult(status="outside_worktree")
    return _CanaryResult(status="ok", relative_path=sorted(relative_paths)[0])


# ---------------------------------------------------------------------------
# JUnit XML parsing
# ---------------------------------------------------------------------------

# Last traceback line pytest writes for a call/setup failure: "{file}:{line}: {Type}".
_LAST_LINE_TYPE = re.compile(r"^\S.*:\d+: ([A-Za-z_][\w.]*)$")
# Any traceback frame/location line: "{file}:{line}: ..." (the last one is innermost).
_FRAME_LINE = re.compile(r"^(\S[^:\s]*\.py):(\d+): ")
_HEX_ADDRESS = re.compile(r"0x[0-9a-fA-F]+")
_TEMP_PARENT = re.compile(
    "(?:"
    + "|".join(
        sorted(
            {re.escape(tempfile.gettempdir()), re.escape(os.path.realpath(tempfile.gettempdir()))},
            key=len,
            reverse=True,
        )
    )
    + r")/fbpa-[A-Za-z0-9_]*"
)
_TEMP_NAME = re.compile(r"fbpa-[A-Za-z0-9_]+")
# pytest's repr truncation can cut a path right inside the random parent name:
# "...l0jv1t/wt/pkg/core.py". Whatever survives between the ellipsis and one of
# the probe's fixed leaf names is random.
_TRUNCATED_PARENT = re.compile(r"\.\.\.[A-Za-z0-9_-]*/(wt|basetemp|plugins)\b")
# A pytest "E   Type: message" line.
_E_LINE = re.compile(r"^E\s+([A-Za-z_][\w.]*): (.*)$")
# JUnit ``message`` attribute: "Type: msg" or 'failed on setup with "Type: msg"'.
_MESSAGE_ATTR = re.compile(
    r'^(?:failed on (?:setup|teardown) with ")?([A-Za-z_][\w.]*): (.*?)"?$', re.DOTALL
)


def _exception_from_text(text: str) -> tuple[str | None, str | None]:
    """(exception type, first message line) from a pytest traceback or stderr.

    pytest 8's JUnit XML does not populate ``<failure>``/``<error>`` elements'
    ``type`` attribute at all, so the type comes from the traceback text: its last
    line is ``"{file}:{line}: {Type}"`` for call/setup failures; for collection and
    conftest failures the last ``E   Type: message`` line carries it.
    """
    lines = [line.rstrip() for line in (text or "").strip().splitlines()]
    eff_type: str | None = None
    if lines:
        match = _LAST_LINE_TYPE.match(lines[-1])
        if match:
            eff_type = match.group(1)
    for line in reversed(lines):
        match = _E_LINE.match(line)
        if not match:
            continue
        line_type = match.group(1)
        if eff_type is None or line_type == eff_type or line_type.endswith("." + eff_type):
            return (eff_type or line_type), match.group(2)
    return eff_type, None


@dataclass
class _CaseOutcome:
    classname: str
    name: str
    outcome: str  # "pass" | "failure" | "error" | "skipped"
    phase: str | None  # "call" | "setup" | "teardown" | "collection" | None (pass/skip)
    exc_type: str | None  # effective exception class name (or the skip marker type)
    exc_message: str | None  # first line of the exception message
    message: str | None
    text: str
    innermost: tuple[str, int] | None = None  # innermost traceback frame (file as printed, line)


def _innermost_frame(text: str) -> tuple[str, int] | None:
    found: tuple[str, int] | None = None
    for line in (text or "").splitlines():
        match = _FRAME_LINE.match(line.strip())
        if match:
            found = (match.group(1), int(match.group(2)))
    return found


def _phase_of(outcome: str, message: str | None) -> str | None:
    if outcome == "failure":
        return "call"
    if outcome != "error":
        return None
    lowered = (message or "").lower()
    if lowered.startswith("collection failure"):
        return "collection"
    if lowered.startswith("failed on teardown"):
        return "teardown"
    return "setup"


def _case_from_parts(
    *, classname: str, name: str, outcome: str, xml_type: str | None, message: str | None, text: str
) -> _CaseOutcome:
    exc_type: str | None = xml_type
    exc_message: str | None = None
    if outcome == "failure" and (message or "").startswith((_XPASS_PREFIX, "[XPASS(strict)]")):
        # An unexpected pass of an xfail-marked test, strict (pytest's own
        # "[XPASS(strict)]" failure) or not (see _XPASS_PLUGIN): it is listed with
        # skip/xfail, never a pass and never a failure (spec §3.1 B_SKIP, §3.2).
        outcome, exc_type = "skipped", "pytest.xpass"
    if outcome in ("failure", "error"):
        parsed_type, parsed_message = _exception_from_text(text)
        attr = _MESSAGE_ATTR.match(message or "")
        exc_type = xml_type or parsed_type or (attr.group(1) if attr else None)
        exc_message = parsed_message
        if exc_message is None and attr and attr.group(1) == exc_type:
            exc_message = attr.group(2).splitlines()[0] if attr.group(2) else None
    return _CaseOutcome(
        classname=classname,
        name=name,
        outcome=outcome,
        phase=_phase_of(outcome, message),
        exc_type=exc_type,
        exc_message=exc_message,
        message=message,
        text=text,
        innermost=_innermost_frame(text) if outcome in ("failure", "error") else None,
    )


def _parse_junit(path: Path) -> list[_CaseOutcome] | None:
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return None
    cases: list[_CaseOutcome] = []
    for testcase in tree.getroot().iter("testcase"):
        failure = testcase.find("failure")
        error = testcase.find("error")
        skipped = testcase.find("skipped")
        if failure is not None:
            outcome, node = "failure", failure
        elif error is not None:
            outcome, node = "error", error
        elif skipped is not None:
            outcome, node = "skipped", skipped
        else:
            outcome, node = "pass", None
        cases.append(
            _case_from_parts(
                classname=testcase.get("classname", ""),
                name=testcase.get("name", ""),
                outcome=outcome,
                xml_type=node.get("type") if node is not None else None,
                message=node.get("message") if node is not None else None,
                text=(node.text or "") if node is not None else "",
            )
        )
    return cases


# ---------------------------------------------------------------------------
# running one claim's pytest process
# ---------------------------------------------------------------------------


_XPASS_PREFIX = "[XPASS(fbpa)]"
# A tiny pytest plugin loaded into every run (from a directory outside both
# worktrees): it turns an xfail-marked test that passes -- strict or not -- into a
# failure carrying ``_XPASS_PREFIX``, because pytest's JUnit XML otherwise records
# a non-strict xpass as a plain pass.
_XPASS_PLUGIN_NAME = "_fbpa_xpass_plugin"
# The same plugin also writes the runtime module-origin audit (spec §2,
# amendment 6) when pytest unconfigures: every module in ``sys.modules`` whose
# top-level name is a project name and whose origin lies outside the run's
# worktree. An editable install's finder serves *submodules* the worktree package
# lacks from another checkout, which the static (top-level) canary cannot see.
_AUDIT_OUT_ENV = "FBPA_MODULE_AUDIT_OUT"
_AUDIT_ROOT_ENV = "FBPA_MODULE_AUDIT_ROOT"
_AUDIT_NAMES_ENV = "FBPA_MODULE_AUDIT_NAMES"
_XPASS_PLUGIN_SOURCE = f"""
import json
import os
import sys

import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.passed and hasattr(report, "wasxfail"):
        report.outcome = "failed"
        report.longrepr = {_XPASS_PREFIX!r} + " " + str(report.wasxfail)


def _inside(path, root):
    path = os.path.realpath(path)
    return path == root or path.startswith(root + os.sep)


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config):
    out = os.environ.get({_AUDIT_OUT_ENV!r})
    if not out:
        return
    root = os.path.realpath(os.environ[{_AUDIT_ROOT_ENV!r}])
    with open(os.environ[{_AUDIT_NAMES_ENV!r}], encoding="utf-8") as handle:
        names = set(json.load(handle))
    outside = []
    for name, module in list(sys.modules.items()):
        if module is None or name.split(".", 1)[0] not in names:
            continue
        origin = getattr(module, "__file__", None)
        if origin:
            if not _inside(origin, root):
                outside.append(name)
            continue
        # A namespace package (no __file__) is only the sum of its portions; its
        # imported submodules are checked one by one above. It is outside only
        # when no portion at all is in the worktree.
        portions = [p for p in list(getattr(module, "__path__", None) or []) if p]
        if portions and not any(_inside(p, root) for p in portions):
            outside.append(name)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump({{"outside": sorted(outside)}}, handle)
"""


def _install_xpass_plugin(parent: Path) -> Path:
    plugin_dir = parent / "plugins"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / f"{_XPASS_PLUGIN_NAME}.py").write_text(_XPASS_PLUGIN_SOURCE, encoding="utf-8")
    return plugin_dir


@dataclass
class _RunResult:
    exit_code: int
    cases: list[_CaseOutcome]
    report_exists: bool
    stderr: str
    timed_out: bool = False
    # Runtime module-origin audit: project modules loaded from outside the
    # worktree, or None when the audit record is missing or unreadable.
    outside_modules: list[str] | None = None


def _read_module_audit(path: Path) -> list[str] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        outside = data["outside"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(outside, list) or not all(isinstance(n, str) for n in outside):
        return None
    return sorted(outside)


def _run_pytest_once(
    worktree: Path,
    node_id: str,
    *,
    timeout_s: int,
    memory_max: str,
    backend: str,
    env: dict[str, str],
) -> _RunResult:
    # The report and pytest's basetemp live next to the worktree, under the same
    # relative layout on both sides and in every run: a tmp_path in a failure
    # message is then identical across repeats (no pytest-of-<user>/pytest-<N>).
    report_path = worktree.parent / "junit.xml"
    report_path.unlink(missing_ok=True)
    audit_path = worktree.parent / "module-audit.json"
    audit_path.unlink(missing_ok=True)
    env = {**env, _AUDIT_OUT_ENV: str(audit_path), _AUDIT_ROOT_ENV: str(worktree)}
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "-p",
        _XPASS_PLUGIN_NAME,
        "-q",
        f"--basetemp={worktree.parent / 'basetemp'}",
        f"--junitxml={report_path}",
        node_id,
    ]
    proc = _run_limited(
        cmd, cwd=worktree, env=env, timeout_s=timeout_s, memory_max=memory_max, backend=backend
    )
    if report_path.exists():
        cases = _parse_junit(report_path)
        report_exists = cases is not None
        cases = cases or []
        report_path.unlink(missing_ok=True)
    else:
        cases, report_exists = [], False
    outside_modules = _read_module_audit(audit_path)
    audit_path.unlink(missing_ok=True)

    return _RunResult(
        exit_code=proc.returncode,
        cases=cases,
        report_exists=report_exists,
        stderr=proc.stderr,
        timed_out=proc.timed_out,
        outside_modules=outside_modules,
    )


# ---------------------------------------------------------------------------
# node ids
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _NodeId:
    raw: str
    file_rel: str
    class_path: tuple[str, ...]
    func: str  # bare function name, parametrization stripped
    case_name: str  # last node id segment, parametrization kept


def _parse_node_id(node_id: str) -> _NodeId:
    file_rel, _, remainder = node_id.partition("::")
    segments = remainder.split("::") if remainder else [node_id]
    case_name = segments[-1]
    return _NodeId(
        raw=node_id,
        file_rel=file_rel,
        class_path=tuple(segments[:-1]),
        func=case_name.split("[", 1)[0],
        case_name=case_name,
    )


def _find_function(
    tree: ast.Module, node: _NodeId
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """The test function a node id names: file from the node id, then each class."""
    scope: list[ast.stmt] = list(tree.body)
    for class_name in node.class_path:
        match = next(
            (s for s in scope if isinstance(s, ast.ClassDef) and s.name == class_name), None
        )
        if match is None:
            return None
        scope = list(match.body)
    for stmt in scope:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name == node.func:
            return stmt
    return None


def _parse_file(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# scoped symbol tables (spec section 3.1, "How absence is attributed")
# ---------------------------------------------------------------------------


def _target_names(target: ast.expr) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        out: list[str] = []
        for elt in target.elts:
            out.extend(_target_names(elt))
        return out
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    return []


def _child_blocks(stmt: ast.stmt) -> list[list[ast.stmt]]:
    """The statement blocks nested in a compound statement that share its scope
    (if/for/while/with/try bodies), i.e. everything except def/class bodies."""
    if isinstance(stmt, (ast.If, ast.For, ast.AsyncFor, ast.While)):
        return [stmt.body, stmt.orelse]
    if isinstance(stmt, (ast.With, ast.AsyncWith)):
        return [stmt.body]
    if isinstance(stmt, ast.Try) or type(stmt).__name__ == "TryStar":
        return [
            stmt.body,  # type: ignore[attr-defined]
            *[handler.body for handler in stmt.handlers],  # type: ignore[attr-defined]
            stmt.orelse,  # type: ignore[attr-defined]
            stmt.finalbody,  # type: ignore[attr-defined]
        ]
    return []


def _flat_statements(body: list[ast.stmt]) -> list[ast.stmt]:
    """Statements of a block, descending into if/try/with/for/while but not defs."""
    out: list[ast.stmt] = []
    for stmt in body:
        out.append(stmt)
        for block in _child_blocks(stmt):
            out.extend(_flat_statements(block))
    return out


def _statement_bindings(stmt: ast.stmt) -> list[str]:
    """Names a single statement binds in the scope it appears in."""
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [stmt.name]
    if isinstance(stmt, ast.Assign):
        out: list[str] = []
        for target in stmt.targets:
            out.extend(_target_names(target))
        return out
    if isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
        return _target_names(stmt.target)
    if isinstance(stmt, ast.Import):
        return [alias.asname or alias.name.split(".", 1)[0] for alias in stmt.names]
    if isinstance(stmt, ast.ImportFrom):
        return [alias.asname or alias.name for alias in stmt.names if alias.name != "*"]
    return []


@dataclass
class _ModuleTable:
    names: set[str]
    stars: list[tuple[int, str | None]]  # (level, module) of every ``from X import *``
    explicit_all: list[str] | None
    dynamic: bool  # module-level __getattr__


@dataclass
class _ClassTable:
    attrs: set[str]
    bases: list[str]  # simple names of base classes
    dynamic: bool  # __getattr__/__getattribute__, or a base we cannot read (a call)


class _SymbolIndex:
    """Scoped symbol tables of one worktree, built from its files on disk.

    The base index is built from the base worktree *after* the test overlay, i.e.
    from exactly the tree the base pytest run imports.
    """

    def __init__(self, root: Path, test_patterns: list[re.Pattern[str]]) -> None:
        self.root = root
        all_files = _list_files(root)
        self.py_files = [rel for rel in all_files if rel.endswith(".py")]
        self.py_set = set(self.py_files)
        self.trees: dict[str, ast.Module | None] = {}
        # Every file stem and directory name anywhere in the tree: used to tell
        # "a project module we failed to map" apart from a genuinely external one.
        self.basenames: set[str] = set()
        for rel in self.py_files:
            parts = rel.split("/")
            self.basenames.update(parts[:-1])
            self.basenames.add(parts[-1][: -len(".py")])
        roots: set[str] = {""}
        if (root / "src").is_dir():
            roots.add("src")
        for rel in self.py_files:
            if _matches_any(rel, test_patterns):
                # pytest's default "prepend" import mode puts the first ancestor
                # directory without an __init__.py on sys.path.
                directory = Path(rel).parent
                while (
                    directory != Path(".") and (directory / "__init__.py").as_posix() in self.py_set
                ):
                    directory = directory.parent
                roots.add("" if directory == Path(".") else directory.as_posix())
        self.module_files: dict[str, list[str]] = {}
        self.packages: set[str] = set()
        for rel in self.py_files:
            for prefix in sorted(roots):
                if prefix and not rel.startswith(prefix + "/"):
                    continue
                sub = rel[len(prefix) + 1 :] if prefix else rel
                parts = sub[: -len(".py")].split("/")
                if parts[-1] == "__init__":
                    parts = parts[:-1]
                if not parts or not all(p.isidentifier() for p in parts):
                    continue
                dotted = ".".join(parts)
                self.module_files.setdefault(dotted, [])
                if rel not in self.module_files[dotted]:
                    self.module_files[dotted].append(rel)
                for i in range(1, len(parts)):
                    self.packages.add(".".join(parts[:i]))
        for files in self.module_files.values():
            files.sort()
        self._module_tables: dict[str, _ModuleTable] = {}
        self._module_names_cache: dict[str, tuple[set[str], bool]] = {}
        self.classes: dict[str, list[tuple[str, str]]] = {}
        self.class_tables: dict[tuple[str, str], _ClassTable] = {}
        for rel in self.py_files:
            tree = self.tree(rel)
            if tree is not None:
                self._index_classes(rel, tree.body, prefix="")
        for keys in self.classes.values():
            keys.sort()

    # -- files ------------------------------------------------------------

    def tree(self, rel: str) -> ast.Module | None:
        if rel not in self.trees:
            self.trees[rel] = _parse_file(self.root / rel) if rel in self.py_set else None
        return self.trees[rel]

    def module_exists(self, dotted: str) -> bool:
        return dotted in self.module_files or dotted in self.packages

    # -- module tables ----------------------------------------------------

    def _module_table(self, rel: str) -> _ModuleTable:
        if rel in self._module_tables:
            return self._module_tables[rel]
        tree = self.tree(rel)
        names: set[str] = set()
        stars: list[tuple[int, str | None]] = []
        explicit_all: list[str] | None = None
        dynamic = False
        if tree is not None:
            for stmt in _flat_statements(tree.body):
                names.update(_statement_bindings(stmt))
                if isinstance(stmt, ast.ImportFrom) and any(a.name == "*" for a in stmt.names):
                    stars.append((stmt.level, stmt.module))
                if (
                    isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and stmt.name == "__getattr__"
                ):
                    dynamic = True
                if (
                    isinstance(stmt, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "__all__" for t in stmt.targets)
                    and isinstance(stmt.value, (ast.List, ast.Tuple))
                    and all(
                        isinstance(e, ast.Constant) and isinstance(e.value, str)
                        for e in stmt.value.elts
                    )
                ):
                    explicit_all = [e.value for e in stmt.value.elts]  # type: ignore[attr-defined]
        if rel.endswith("/__init__.py") or rel == "__init__.py":
            # A package's submodules are reachable as attributes once imported.
            directory = rel[: -len("__init__.py")]
            for other in self.py_files:
                if not other.startswith(directory) or other == rel:
                    continue
                first = other[len(directory) :].split("/", 1)[0]
                stem = first[: -len(".py")] if first.endswith(".py") else first
                if stem.isidentifier():
                    names.add(stem)
        table = _ModuleTable(names=names, stars=stars, explicit_all=explicit_all, dynamic=dynamic)
        self._module_tables[rel] = table
        return table

    def _resolve_star(self, rel: str, level: int, module: str | None) -> list[str] | None:
        if level == 0:
            return self.module_files.get(module or "")
        directory = Path(rel).parent
        for _ in range(level - 1):
            directory = directory.parent
        base = directory.as_posix()
        stem = "/".join(((base + "/") if base != "." else "", (module or "").replace(".", "/")))
        stem = stem.replace("//", "/").strip("/")
        candidates = [f"{stem}.py", f"{stem}/__init__.py"] if stem else ["__init__.py"]
        found = [c for c in candidates if c in self.py_set]
        return found or None

    def module_names(self, rel: str, _seen: frozenset[str] = frozenset()) -> tuple[set[str], bool]:
        """(names bound at module level, dynamic?) with ``import *`` expanded."""
        if rel in self._module_names_cache:
            return self._module_names_cache[rel]
        table = self._module_table(rel)
        names = set(table.names)
        dynamic = table.dynamic
        for level, module in table.stars:
            targets = self._resolve_star(rel, level, module)
            if not targets:
                dynamic = True  # a star import we cannot read
                continue
            for target in targets:
                if target in _seen or target == rel:
                    continue
                target_names, target_dynamic = self.module_names(target, _seen | {rel})
                explicit = self._module_table(target).explicit_all
                exported = (
                    set(explicit)
                    if explicit is not None
                    else {n for n in target_names if not n.startswith("_")}
                )
                names |= exported
                dynamic = dynamic or target_dynamic
        if not _seen:
            self._module_names_cache[rel] = (names, dynamic)
        return names, dynamic

    def file_has(self, rel: str, name: str) -> bool | None:
        if rel not in self.py_set:
            return None
        names, dynamic = self.module_names(rel)
        if name in names:
            return True
        return None if dynamic else False

    def module_has(self, dotted: str, name: str) -> bool | None | str:
        """True/False/None (unknown), or "missing" if no such module on this side."""
        files = self.module_files.get(dotted)
        if not files:
            if dotted in self.packages:
                # A namespace package: only its submodules/subpackages exist.
                prefix = dotted + "."
                children = {
                    m[len(prefix) :].split(".", 1)[0]
                    for m in self.module_files
                    if m.startswith(prefix)
                }
                return name in children
            return "missing"
        results = {self.file_has(rel, name) for rel in files}
        return results.pop() if len(results) == 1 else None

    # -- class tables -----------------------------------------------------

    def _index_classes(self, rel: str, body: list[ast.stmt], prefix: str) -> None:
        for stmt in body:
            if isinstance(stmt, ast.ClassDef):
                qualname = f"{prefix}{stmt.name}"
                key = (rel, qualname)
                self.classes.setdefault(stmt.name, []).append(key)
                self.class_tables[key] = self._class_table(stmt)
                self._index_classes(rel, stmt.body, prefix=f"{qualname}.")
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._index_classes(rel, stmt.body, prefix=f"{prefix}{stmt.name}.<locals>.")
            else:
                for block in _child_blocks(stmt):
                    self._index_classes(rel, block, prefix=prefix)

    @staticmethod
    def _class_table(node: ast.ClassDef) -> _ClassTable:
        attrs: set[str] = set()
        dynamic = False
        bases: list[str] = []
        for base in node.bases:
            target = base.value if isinstance(base, ast.Subscript) else base
            if isinstance(target, ast.Name):
                bases.append(target.id)
            elif isinstance(target, ast.Attribute):
                bases.append(target.attr)
            else:
                dynamic = True  # e.g. namedtuple("X", ...): attributes we cannot read
        for stmt in _flat_statements(node.body):
            attrs.update(_statement_bindings(stmt))
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if stmt.name in ("__getattr__", "__getattribute__"):
                    dynamic = True
                positional = [*stmt.args.posonlyargs, *stmt.args.args]
                receivers = {positional[0].arg} if positional else set()
                for inner in ast.walk(stmt):
                    targets: list[ast.expr] = []
                    if isinstance(inner, ast.Assign):
                        targets = list(inner.targets)
                    elif isinstance(inner, (ast.AnnAssign, ast.AugAssign)):
                        targets = [inner.target]
                    for target in targets:
                        if (
                            isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id in receivers
                        ):
                            attrs.add(target.attr)
        return _ClassTable(attrs=attrs, bases=bases, dynamic=dynamic)

    def class_has(
        self, key: tuple[str, str], name: str, _seen: frozenset[tuple[str, str]] = frozenset()
    ) -> bool | None:
        """Whether the class (with its project base classes) defines ``name``."""
        table = self.class_tables[key]
        if name in table.attrs:
            return True
        unknown = table.dynamic
        for base_name in table.bases:
            candidates = [k for k in self.classes.get(base_name, []) if k not in _seen and k != key]
            if not candidates:
                continue  # an external base class: its attributes are out of scope
            results = {self.class_has(k, name, _seen | {key}) for k in candidates}
            if results == {True}:
                return True
            if True in results or None in results:
                unknown = True
        return None if unknown else False


@dataclass
class _Attribution:
    kind: str  # "absent" | "present" | "unattributed"
    target: str | None = None
    # The attributed name itself (the X in "module M, name X"); None when the
    # target is a whole module ("No module named 'pkg.mod'").
    name: str | None = None


_MSG_NO_MODULE = re.compile(r"No module named '([\w.]+)'")
_MSG_CANNOT_IMPORT = re.compile(
    r"cannot import name '(\w+)' from (?:partially initialized module )?'([\w.]+)'"
)
_MSG_MODULE_ATTR = re.compile(r"module '([\w.]+)' has no attribute '(\w+)'")
# monkeypatch.setattr / unittest.mock.patch on a module that lacks the attribute:
# "<module 'pkg.mod' from '...'> has no attribute 'X'" / "... does not have the attribute 'X'".
_MSG_REPR_MODULE_ATTR = re.compile(
    r"<module '([\w.]+)'(?: from [^>]*)?> (?:has no attribute|does not have the attribute) '(\w+)'"
)
_MSG_TYPE_ATTR = re.compile(r"^type object '(\w+)' has no attribute '(\w+)'")
_MSG_OBJECT_ATTR = re.compile(r"^'(\w+)' object has no attribute '(\w+)'")
_MSG_NAME = re.compile(r"^name '(\w+)' is not defined")

# Exception classes whose message is parsed for an absence target (spec §3.1).
_ABSENCE_EXC_TYPES = {"ImportError", "ModuleNotFoundError", "NameError", "AttributeError"}


class _Attributor:
    """Message-driven, scoped absence attribution (spec §3.1, amendment 2)."""

    def __init__(self, base: _SymbolIndex, head: _SymbolIndex) -> None:
        self.base = base
        self.head = head

    def _mentioned(self, dotted: str) -> bool:
        top = dotted.split(".", 1)[0]
        return any(idx.module_exists(top) or top in idx.basenames for idx in (self.base, self.head))

    @staticmethod
    def _decide(base_has: bool | None | str, head_has: bool | None | str) -> str:
        if base_has is True:
            return "present"
        if base_has is None:
            return "unattributed"
        return "absent" if head_has is True else "unattributed"

    def attribute(self, message: str | None, *, test_rel: str | None) -> _Attribution:
        """Attribute an absence-type error message.

        ``test_rel`` is the scope a ``NameError`` is looked up in: the module of the
        innermost traceback frame (spec §3.1), or None when that frame is outside
        the project (then the name is not a project symbol: "present").
        """
        msg = (message or "").strip()
        match = _MSG_NO_MODULE.search(msg)
        if match:
            module = match.group(1)
            in_head, in_base = self.head.module_exists(module), self.base.module_exists(module)
            if in_base:
                return _Attribution("present", module)
            if in_head:
                return _Attribution("absent", module)
            return _Attribution("unattributed" if self._mentioned(module) else "present", module)

        match = (
            _MSG_CANNOT_IMPORT.search(msg)
            or _MSG_MODULE_ATTR.search(msg)
            or _MSG_REPR_MODULE_ATTR.search(msg)
        )
        if match:
            if match.re is _MSG_CANNOT_IMPORT:
                name, module = match.group(1), match.group(2)
            else:
                module, name = match.group(1), match.group(2)
            target = f"{module}.{name}"
            base_has = self.base.module_has(module, name)
            head_has = self.head.module_has(module, name)
            if base_has == "missing" and head_has == "missing":
                kind = "unattributed" if self._mentioned(module) else "present"
                return _Attribution(kind, target, name)
            if base_has == "missing":
                base_has = False
            return _Attribution(self._decide(base_has, head_has), target, name)

        match = _MSG_TYPE_ATTR.search(msg) or _MSG_OBJECT_ATTR.search(msg)
        if match:
            class_name, name = match.group(1), match.group(2)
            target = f"{class_name}.{name}"
            base_keys = self.base.classes.get(class_name, [])
            head_keys = self.head.classes.get(class_name, [])
            if not base_keys and not head_keys:
                # Not a project class (NoneType, dict, a third-party type):
                # a real behavioural failure.
                return _Attribution("present", target, name)
            if not base_keys or any(k not in self.head.class_tables for k in base_keys):
                return _Attribution("unattributed", target, name)  # ambiguous across sides
            base_results = {self.base.class_has(k, name) for k in base_keys}
            if base_results == {True}:
                return _Attribution("present", target, name)
            if base_results != {False}:
                return _Attribution("unattributed", target, name)
            head_results = {self.head.class_has(k, name) for k in base_keys}
            kind = "absent" if head_results == {True} else "unattributed"
            return _Attribution(kind, target, name)

        match = _MSG_NAME.search(msg)
        if match:
            name = match.group(1)
            if test_rel is None:
                return _Attribution("present", name, name)
            base_has = self.base.file_has(test_rel, name)
            head_has = self.head.file_has(test_rel, name)
            return _Attribution(self._decide(base_has, head_has), name, name)

        return _Attribution("unattributed")


# ---------------------------------------------------------------------------
# collection-phase "does this test reference the missing symbol" check
# ---------------------------------------------------------------------------

_MODULE_FRAME = re.compile(r"^(.*):(\d+): in <module>$")


def _failing_line(text: str, file_rel: str) -> int | None:
    for line in (text or "").splitlines():
        match = _MODULE_FRAME.match(line.strip())
        if match and (match.group(1) == file_rel or match.group(1).endswith("/" + file_rel)):
            return int(match.group(2))
    return None


def _statement_at(body: list[ast.stmt], line: int) -> ast.stmt | None:
    for stmt in body:
        end = getattr(stmt, "end_lineno", None) or stmt.lineno
        if stmt.lineno <= line <= end:
            for block in _child_blocks(stmt):
                found = _statement_at(block, line)
                if found is not None:
                    return found
            return stmt
    return None


def _is_fixture(node: ast.AST) -> bool:
    for decorator in getattr(node, "decorator_list", []):
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Name) and target.id == "fixture":
            return True
        if isinstance(target, ast.Attribute) and target.attr == "fixture":
            return True
    return False


def _reference_closure(tree: ast.Module, node: _NodeId) -> set[str] | None:
    """Every name the test can reach in its own module: its body, decorators,
    fixtures named as parameters, and module-level helpers it calls (transitively)."""
    func = _find_function(tree, node)
    if func is None:
        return None
    module_defs: dict[str, list[ast.stmt]] = {}
    for stmt in _flat_statements(tree.body):
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            continue
        for name in _statement_bindings(stmt):
            module_defs.setdefault(name, []).append(stmt)
    class_defs: dict[str, ast.stmt] = {}
    scope: list[ast.stmt] = list(tree.body)
    for class_name in node.class_path:
        cls = next((s for s in scope if isinstance(s, ast.ClassDef) and s.name == class_name), None)
        if cls is None:
            break
        for stmt in cls.body:
            for name in _statement_bindings(stmt):
                class_defs[name] = stmt
        scope = list(cls.body)

    referenced: set[str] = set()
    attribute_names: set[str] = set()
    visited: set[int] = set()
    worklist: list[ast.AST] = [func]
    while worklist:
        current = worklist.pop()
        if id(current) in visited:
            continue
        visited.add(id(current))
        new_names: set[str] = set()
        for inner in ast.walk(current):
            if isinstance(inner, ast.Name):
                new_names.add(inner.id)
            elif isinstance(inner, ast.Attribute) and isinstance(inner.value, ast.Name):
                attribute_names.add(inner.attr)  # e.g. ``core.newfn`` reaches ``newfn``
                if inner.value.id in ("self", "cls") and inner.attr in class_defs:
                    worklist.append(class_defs[inner.attr])
            elif isinstance(inner, ast.arg):
                new_names.add(inner.arg)  # fixture requested by parameter name
        for name in new_names - referenced:
            worklist.extend(module_defs.get(name, []))
            if name in class_defs and _is_fixture(class_defs[name]):
                worklist.append(class_defs[name])
        referenced |= new_names
    return referenced | attribute_names


def _target_local_names(stmt: ast.stmt, attribution: _Attribution) -> set[str]:
    """The local names through which the test module can reach the attributed target.

    Spec §3.1 (B_COLLATERAL row): only the attributed target name counts, never the
    other names the same import statement binds. ``from m import a, b`` failing on
    ``b`` makes only ``b`` (or its ``as`` alias) count; a test using only ``a`` is
    collateral. A whole-module target ("No module named 'm'") makes every name the
    statement binds count, since all of them come from the missing module.
    """
    name = attribution.name
    if name is None:
        return set(_statement_bindings(stmt))
    if isinstance(stmt, ast.ImportFrom):
        local = {alias.asname or alias.name for alias in stmt.names if alias.name == name}
        if any(alias.name == "*" for alias in stmt.names):
            local.add(name)
        return local
    return {name}


def _collection_references_failure(
    head_wt: Path, node: _NodeId, text: str, attribution: _Attribution
) -> bool:
    """True iff the claimed test references the attributed target (spec §3.1)."""
    tree = _parse_file(head_wt / node.file_rel)
    if tree is None:
        return False
    line = _failing_line(text, node.file_rel)
    if line is None:
        return False
    stmt = _statement_at(tree.body, line)
    if stmt is None:
        return False
    local = _target_local_names(stmt, attribution)
    closure = _reference_closure(tree, node)
    return bool(closure and local & closure)


# ---------------------------------------------------------------------------
# per-run / per-case classification (spec sections 2.1 and 3)
# ---------------------------------------------------------------------------


@dataclass
class _Context:
    """What the classifiers need beyond the run itself."""

    side: str
    backend: str
    node: _NodeId
    base_wt: Path
    head_wt: Path
    attributor: Callable[[], _Attributor]


def _classify_run(run: _RunResult, ctx: _Context) -> tuple[str, dict[str, Any]]:
    side = ctx.side
    # A timeout (``timeout -k`` 124, its SIGKILL escalation 137, or the
    # Python-side backstop) is decided in ``_run_limited``. The systemd scope
    # that enforces MemoryMax SIGKILLs processes inside it: ``timeout`` then
    # exits 137 for its killed child, or our direct child itself dies (-9).
    if run.timed_out:
        return "FAULT", {"code": "F_TIMEOUT", "detail": "pytest exceeded timeout_s"}
    if run.exit_code in (137, -9):
        return "FAULT", {"code": "F_OOM", "detail": "pytest was killed by the memory limiter"}
    if run.exit_code == -15:
        return "FAULT", {"code": "F_TIMEOUT", "detail": "pytest was terminated"}
    # A conftest.py that fails to load is reported by pytest's CLI as a usage
    # error -- the *same* exit code 4 as a plain "node id not found" -- but it
    # is checked first: it carries its own distinctive stderr message, is
    # attributable to a head-only symbol (spec §3.1), and that attribution must
    # win over the generic exit-4 rule below.
    if side == "base" and "while loading conftest" in run.stderr:
        return "CONFTEST_ERROR", {"stderr": run.stderr}
    # A module-level collection error for an explicitly-targeted function node
    # id is reported by this pytest version via exit 4 ("found no collectors
    # for ...") -- the *same* exit code as a flat-out nonexistent node id --
    # but the JUnit XML is still written and carries a "collection failure"
    # pseudo-testcase for the file. That is checked before the blanket exit-4
    # rule, so a real import error does not get flattened into F_RUNNER.
    if run.report_exists:
        collection_cases = [c for c in run.cases if c.phase == "collection"]
        if collection_cases:
            if side == "head":
                # Spec §2.1/§3.2: a collection error in the claimed test's own
                # module is H_ERROR (head_not_passing), not "not collected".
                return "CASES", {"cases": collection_cases}
            return "COLLECTION_ERROR", {"cases": collection_cases}
    if run.exit_code in (3, 4):
        return "FAULT", {
            "code": "F_RUNNER",
            "detail": f"pytest reported a usage or internal error (exit code {run.exit_code})",
        }
    if not run.report_exists:
        return "FAULT", {
            "code": "F_NO_REPORT",
            "detail": "the junit xml report is missing or unparseable",
        }

    node = ctx.node
    if node.case_name != node.func:  # a single parametrized case was claimed
        matched = [c for c in run.cases if c.name == node.case_name]
    else:
        matched = [
            c for c in run.cases if c.name == node.func or c.name.startswith(node.func + "[")
        ]
    if not matched:
        if side == "head":
            return "FAULT", {
                "code": "F_NOT_COLLECTED",
                "detail": "claimed node id was not collected at head",
            }
        if run.exit_code == 5:
            # "No tests collected": spec §2.1 says classify as B_ABSENT, i.e.
            # attempt the same attribution a collection error gets. There is no
            # per-testcase XML to read here, only stderr.
            exc_type, exc_message = _exception_from_text(run.stderr)
            return "COLLECTION_ERROR", {
                "cases": [
                    _CaseOutcome(
                        classname="",
                        name="",
                        outcome="error",
                        phase="collection",
                        exc_type=exc_type,
                        exc_message=exc_message,
                        message="collection failure",
                        text=run.stderr,
                    )
                ],
            }
        return "FAULT", {
            "code": "F_NOT_COLLECTED",
            "detail": (
                "claimed node id was not collected at base and no collection error was recorded"
            ),
        }

    # An xpass is reported by pytest as a failure (strict, or via _XPASS_PLUGIN)
    # and exits 1; it is reclassified as a skip only after this cross-check.
    any_bad = any(
        case.outcome in ("failure", "error") or case.exc_type == "pytest.xpass" for case in matched
    )
    if run.exit_code == 0 and any_bad:
        return "FAULT", {
            "code": "F_EXIT_XML_MISMATCH",
            "detail": "exit code 0 but the junit report records a failure or error",
        }
    if run.exit_code == 1 and not any_bad:
        return "FAULT", {
            "code": "F_EXIT_XML_MISMATCH",
            "detail": "exit code 1 but the junit report records no failure or error",
        }
    return "CASES", {"cases": matched}


def _resolve_collection_failure(
    cases: list[_CaseOutcome], ctx: _Context
) -> tuple[str, dict[str, Any]]:
    """Attribute a module-level collection error at base (spec §3.1).

    - SyntaxError: F_RUNNER.
    - An absence-type error whose target exists at head but not base: B_ABSENT if
      the claimed test references a name the failing import binds, else
      B_COLLATERAL.
    - An unparseable / ambiguous absence-type message: inconclusive (unattributed).
    - Anything else (including an absence-type error whose target exists at base):
      B_COLLATERAL. A module that fails to import is not evidence about this one
      test's behaviour, so it never counts as "fails before" -- the conservative
      reading of the B_COLLATERAL row (B_FAIL_EXC is defined for the call phase).
    """
    for case in cases:
        if case.exc_type == "SyntaxError" or "SyntaxError" in (case.text or ""):
            return "FAULT", {"code": "F_RUNNER", "detail": "collection failed with a SyntaxError"}
    case = cases[-1]
    if case.exc_type not in _ABSENCE_EXC_TYPES:
        return "B_COLLATERAL", {}
    scope = _frame_rel(case, ctx) if case.exc_type == "NameError" else ctx.node.file_rel
    attribution = ctx.attributor().attribute(case.exc_message, test_rel=scope)
    if attribution.kind == "unattributed":
        return "B_UNATTRIBUTED", {}
    if attribution.kind == "present":
        return "B_COLLATERAL", {}
    if _collection_references_failure(ctx.head_wt, ctx.node, case.text, attribution):
        return "B_ABSENT", {"symbol": attribution.target}
    return "B_COLLATERAL", {}


def _resolve_conftest_failure(stderr: str, ctx: _Context) -> tuple[str, dict[str, Any]]:
    """Attribute a head conftest.py that fails to load at base (spec §3.1).

    A conftest failure aborts the whole session before any test (including the
    claimed one) is collected, so there is no per-function reference check: the
    conftest is part of the test suite head changed, and every claim under it is
    equally affected. NameErrors are looked up in the failing conftest's scope.
    """
    if "SyntaxError" in stderr:
        return "FAULT", {
            "code": "F_RUNNER",
            "detail": "a head conftest.py failed to load with a SyntaxError",
        }
    exc_type, exc_message = _exception_from_text(stderr)
    if exc_type in _ABSENCE_EXC_TYPES:
        match = re.search(r"while loading conftest '([^']+)'", stderr)
        conftest_rel = ctx.node.file_rel
        if match:
            try:
                conftest_path = Path(match.group(1)).resolve()
                conftest_rel = conftest_path.relative_to(ctx.base_wt.resolve()).as_posix()
            except ValueError:
                conftest_rel = ctx.node.file_rel
        attribution = ctx.attributor().attribute(exc_message, test_rel=conftest_rel)
        if attribution.kind == "absent":
            return "B_ABSENT", {"symbol": attribution.target}
        if attribution.kind == "unattributed":
            return "B_UNATTRIBUTED", {}
    return "FAULT", {
        "code": "F_NO_REPORT",
        "detail": "a conftest.py failed to load and no head-only symbol could be attributed",
    }


def _frame_rel(case: _CaseOutcome, ctx: _Context) -> str | None:
    """The innermost frame's file as a worktree-relative path; None if outside.

    pytest prints paths relative to its rootdir (the worktree) when it can, and
    absolute otherwise.
    """
    if case.innermost is None:
        return ctx.node.file_rel
    printed = Path(case.innermost[0])
    if not printed.is_absolute():
        return printed.as_posix()
    for root in (ctx.base_wt, ctx.head_wt):
        try:
            return printed.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
    return None


def _membership_container(container: ast.expr) -> ast.expr | None:
    """The object of ``dir(x)``, ``vars(x)`` or ``x.__dict__``, else None."""
    if (
        isinstance(container, ast.Call)
        and isinstance(container.func, ast.Name)
        and container.func.id in ("dir", "vars")
        and len(container.args) == 1
    ):
        return container.args[0]
    if isinstance(container, ast.Attribute) and container.attr == "__dict__":
        return container.value
    return None


def _constant_name(expr: ast.expr) -> str | None:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    return None


def _existence_names(statement: ast.AST) -> list[tuple[str | None, ast.expr]]:
    """(name, object expression) for every existence check in a statement (spec §3.1):
    ``hasattr(x, N)``, ``getattr(x, N, default)``, ``N in dir(x)``, ``N in vars(x)``,
    ``N in x.__dict__`` and ``self.assertIn(N, <one of those>)``, wherever they occur
    (inside ``assert``, ``self.assertTrue(...)``, ``all(...)``, ...). ``name`` is
    None when N is not a string constant."""
    found: list[tuple[str | None, ast.expr]] = []
    for node in ast.walk(statement):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            args = node.args
            is_hasattr = node.func.id == "hasattr" and len(args) == 2
            is_getattr_default = node.func.id == "getattr" and len(args) == 3
            if is_hasattr or is_getattr_default:
                found.append((_constant_name(args[1]), args[0]))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "assertIn"
            and len(node.args) >= 2
        ):
            obj = _membership_container(node.args[1])
            if obj is not None:
                found.append((_constant_name(node.args[0]), obj))
        elif (
            isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.In)
        ):
            obj = _membership_container(node.comparators[0])
            if obj is not None:
                found.append((_constant_name(node.left), obj))
    return found


def _dotted(expr: ast.expr) -> str | None:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        inner = _dotted(expr.value)
        return f"{inner}.{expr.attr}" if inner else None
    return None


def _existence_message(
    obj: ast.expr, name: str, tree: ast.Module, attributor: _Attributor
) -> str | None:
    """Rephrase an existence check as the AttributeError message its failure means,
    so the scoped attribution can judge it; None if the object cannot be resolved."""
    aliases: dict[str, str] = {}
    for stmt in _flat_statements(tree.body):
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name
                else:
                    top = alias.name.split(".", 1)[0]
                    aliases[top] = top
        elif isinstance(stmt, ast.ImportFrom) and stmt.level == 0 and stmt.module:
            for alias in stmt.names:
                if alias.name != "*":
                    aliases[alias.asname or alias.name] = f"{stmt.module}.{alias.name}"
    instance = isinstance(obj, ast.Call)
    dotted = _dotted(obj.func if isinstance(obj, ast.Call) else obj)
    if dotted is None:
        return None
    head, _, rest = dotted.partition(".")
    resolved = aliases.get(head, head) + (f".{rest}" if rest else "")
    last = resolved.rsplit(".", 1)[-1]
    sides = (attributor.base, attributor.head)
    if not instance and any(side.module_exists(resolved) for side in sides):
        return f"module '{resolved}' has no attribute '{name}'"
    if any(last in side.classes for side in sides):
        if instance:
            return f"'{last}' object has no attribute '{name}'"
        return f"type object '{last}' has no attribute '{name}'"
    return None


def _existence_assertion(case: _CaseOutcome, ctx: _Context) -> _Attribution | None:
    """Attribution of a failed existence assertion at base, or None if the failing
    assert is not an existence check. An existence check whose object cannot be
    resolved is unattributed (never counted as failing before)."""
    rel = _frame_rel(case, ctx)
    if rel is None or case.innermost is None:
        return None
    tree = _parse_file(ctx.head_wt / rel)
    if tree is None:
        return None
    line = case.innermost[1]
    # The whole failing statement at the innermost frame (an ``assert``, a
    # ``self.assertTrue(...)`` call, or a statement inside a helper), narrowed to
    # the innermost statement that spans the line.
    statements = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.stmt)
        and not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and n.lineno <= line <= (n.end_lineno or n.lineno)
    ]
    if not statements:
        return None
    statement = min(statements, key=lambda n: (n.end_lineno or n.lineno) - n.lineno)
    checks = _existence_names(statement)
    if not checks:
        return None
    if any(name is None for name, _obj in checks):
        # A non-constant attribute name cannot be looked up (spec §3.1).
        return _Attribution("unattributed")
    attributor = ctx.attributor()
    kinds: list[_Attribution] = []
    for name, obj in checks:
        if name is None:  # pragma: no cover - handled above
            continue
        message = _existence_message(obj, name, tree, attributor)
        if message is None:
            kinds.append(_Attribution("unattributed", name, name))
        else:
            kinds.append(attributor.attribute(message, test_rel=rel))
    for kind in ("absent", "unattributed"):
        for attribution in kinds:
            if attribution.kind == kind:
                return attribution
    return None  # every checked name exists at base: a genuine assertion failure


def _classify_case(case: _CaseOutcome, ctx: _Context) -> tuple[str, str | None]:
    """Classify one JUnit testcase. Returns (label, absent_target_or_None)."""
    if ctx.backend == "rlimit" and (case.exc_type == "MemoryError" or "MemoryError" in case.text):
        return "FAULT:F_OOM", None
    if case.outcome == "pass":
        return "PASS", None
    if case.outcome == "skipped":
        return "SKIP", None
    if (
        ctx.side == "base"
        and case.phase in ("call", "setup")
        and case.exc_type in _ABSENCE_EXC_TYPES
    ):
        scope = _frame_rel(case, ctx) if case.exc_type == "NameError" else ctx.node.file_rel
        attribution = ctx.attributor().attribute(case.exc_message, test_rel=scope)
        if attribution.kind == "absent":
            return "ABSENT", attribution.target
        if attribution.kind == "unattributed":
            return "UNATTRIBUTED", None
        # "present": the target exists at base (or is not a project symbol), so
        # this is a real behavioural failure in the call phase; a setup-phase one
        # stays a setup error (B_SETUP_ERROR, never "fails before").
    if ctx.side == "base" and case.phase == "call" and case.exc_type == "AssertionError":
        existence = _existence_assertion(case, ctx)
        if existence is not None:
            if existence.kind == "absent":
                return "ABSENT", existence.target
            return "UNATTRIBUTED", None
    if case.outcome == "failure":
        combined = f"{case.message or ''} {case.text or ''}"
        if case.exc_type in {"AssertionError", "Failed"} or "DID NOT RAISE" in combined:
            return "FAIL_ASSERT", None
        return "FAIL_EXC", None
    return "SETUP_ERROR", None


def _synthesize_base(case_classes: list[str]) -> str:
    if any(c in ("FAIL_ASSERT", "FAIL_EXC") for c in case_classes):
        return "B_FAIL_ASSERT" if "FAIL_ASSERT" in case_classes else "B_FAIL_EXC"
    if any(c == "UNATTRIBUTED" for c in case_classes):
        return "B_UNATTRIBUTED"
    if any(c == "ABSENT" for c in case_classes):
        return "B_ABSENT"
    if all(c == "PASS" for c in case_classes):
        return "B_PASS"
    if any(c == "SETUP_ERROR" for c in case_classes):
        return "B_SETUP_ERROR"
    if any(c == "PASS" for c in case_classes):
        return "B_PASS"
    return "B_SKIP"


def _synthesize_head(case_classes: list[str]) -> str:
    if all(c == "PASS" for c in case_classes):
        return "H_PASS"
    if any(c in ("FAIL_ASSERT", "FAIL_EXC") for c in case_classes):
        return "H_FAIL"
    if any(c == "SETUP_ERROR" for c in case_classes):
        return "H_ERROR"
    return "H_SKIP"


# ---------------------------------------------------------------------------
# per-claim judging
# ---------------------------------------------------------------------------


@dataclass
class _SideOutcome:
    status: str  # "ok" | "fault"
    verdict: str | None = None
    code: str | None = None
    detail: str | None = None
    symbol: str | None = None
    cases: list[dict[str, Any]] = field(default_factory=list)
    outside_modules: list[str] = field(default_factory=list)


_FIRST_FAILURE_LINE_MAX = 300


def _first_failure_line(case: _CaseOutcome, worktree: Path) -> str | None:
    """The normalized first line of the failure, for hand-reading in S2.

    Worktree paths (which contain a random temporary directory) and memory
    addresses are replaced so the line is identical across reruns.
    """
    if case.outcome not in ("failure", "error"):
        return None
    line = f"{case.exc_type}: {case.exc_message}" if case.exc_message else (case.exc_type or "")
    roots = {str(worktree), str(worktree.resolve())}
    for root in sorted(roots, key=len, reverse=True):
        line = line.replace(root, "<worktree>")
    # Anything else under one of the probe's temporary parents (basetemp, the
    # other side), then any fragment of a temporary parent's random name that
    # survived pytest's truncation of a long repr ("/tmp/fbpa-k2j...").
    line = _TEMP_PARENT.sub("<tmp>", line)
    line = _TRUNCATED_PARENT.sub(r"...<tmp>/\1", line)
    line = _TEMP_NAME.sub("fbpa-?", line)
    line = _HEX_ADDRESS.sub("0x?", line)
    return line[:_FIRST_FAILURE_LINE_MAX] or None


def _case_payload(case: _CaseOutcome, worktree: Path) -> dict[str, Any]:
    """The normalized per-case record stored in the report (spec §2)."""
    return {
        "name": case.name,
        "outcome": case.outcome,
        "phase": case.phase,
        "exc_type": case.exc_type,
        "first_failure_line": _first_failure_line(case, worktree),
    }


def _case_signature(cases: list[_CaseOutcome], worktree: Path) -> tuple[Any, ...]:
    """A reproducible per-case fingerprint used to detect flakiness (spec §2, F_FLAKY).

    Compared across repeats instead of the synthesized verdict: two repeats can
    synthesize to the same verdict while disagreeing about *which* case failed,
    in which phase, with which exception type, or with which (normalized) message.
    Including the message keeps the stored first_failure_line stable: a message
    that changes between repeats is F_FLAKY rather than a report that cannot be
    reproduced at finalize.
    """
    return tuple(
        sorted(
            (
                c.name,
                c.outcome,
                c.phase or "",
                c.exc_type or "",
                _first_failure_line(c, worktree) or "",
            )
            for c in cases
        )
    )


def _judge_side(
    *,
    ctx: _Context,
    worktree: Path,
    repeats: int,
    timeout_s: int,
    memory_max: str,
    env: dict[str, str],
) -> _SideOutcome:
    per_repeat: list[str] = []
    signatures: list[Any] = []
    absent_symbol: str | None = None
    case_payload: list[dict[str, Any]] = []
    synthesizer = _synthesize_base if ctx.side == "base" else _synthesize_head
    for _ in range(repeats):
        run = _run_pytest_once(
            worktree,
            ctx.node.raw,
            timeout_s=timeout_s,
            memory_max=memory_max,
            backend=ctx.backend,
            env=env,
        )
        kind, detail = _classify_run(run, ctx)
        if kind == "FAULT":
            return _SideOutcome(status="fault", code=detail["code"], detail=detail["detail"])
        # Spec §2, runtime module-origin audit: a project module loaded from
        # outside the worktree means this side ran some other implementation.
        if run.outside_modules:
            return _SideOutcome(
                status="fault",
                code="F_ENV_IMPORT",
                detail="project modules were loaded from outside the worktree",
                outside_modules=run.outside_modules,
            )
        if run.outside_modules is None and kind != "CONFTEST_ERROR":
            # A conftest that fails to load aborts pytest before plugins can
            # write anything, so only that case may lack the record.
            return _SideOutcome(
                status="fault",
                code="F_NO_REPORT",
                detail="the module-origin audit record is missing or unreadable",
            )
        if kind in ("CONFTEST_ERROR", "COLLECTION_ERROR"):
            if kind == "CONFTEST_ERROR":
                resolved_kind, resolved = _resolve_conftest_failure(detail["stderr"], ctx)
            else:
                resolved_kind, resolved = _resolve_collection_failure(detail["cases"], ctx)
            if resolved_kind == "FAULT":
                return _SideOutcome(
                    status="fault", code=resolved["code"], detail=resolved["detail"]
                )
            absent_symbol = resolved.get("symbol") or absent_symbol
            per_repeat.append(resolved_kind)
            signatures.append((kind, resolved_kind))
            continue
        cases: list[_CaseOutcome] = detail["cases"]
        results = [_classify_case(c, ctx) for c in cases]
        labels = [label for label, _ in results]
        memory_faults = [label for label in labels if label.startswith("FAULT:")]
        if memory_faults:
            return _SideOutcome(
                status="fault",
                code=memory_faults[0].split(":", 1)[1],
                detail="MemoryError observed inside the test process under the rlimit backend",
            )
        for _label, target in results:
            if target:
                absent_symbol = target
        per_repeat.append(synthesizer(labels))
        signatures.append(_case_signature(cases, worktree))
        case_payload = sorted(
            (_case_payload(c, worktree) for c in cases), key=lambda p: (p["name"], p["outcome"])
        )

    if len(set(signatures)) > 1 or len(set(per_repeat)) > 1:
        return _SideOutcome(
            status="fault",
            code="F_FLAKY",
            detail=f"{ctx.side} side produced different per-case results across repeats",
        )
    return _SideOutcome(
        status="ok", verdict=per_repeat[0], symbol=absent_symbol, cases=case_payload
    )


def _components(base: _SideOutcome, head: _SideOutcome) -> list[str]:
    # The caller returns early on a base fault, so only head can fault here.
    if head.status == "fault":
        return [f"fault:{head.code}"]

    head_pass = head.verdict == "H_PASS"
    base_verdict = base.verdict
    if base_verdict in ("B_FAIL_ASSERT", "B_FAIL_EXC"):
        return ["demonstrated"] if head_pass else ["head_not_passing"]
    if base_verdict == "B_PASS":
        return ["base_passes"] if head_pass else ["base_passes", "head_not_passing"]
    if base_verdict == "B_ABSENT":
        return ["absence_only"] if head_pass else ["head_not_passing"]
    verdict = base_verdict or "unknown"
    reason = "unattributed" if verdict == "B_UNATTRIBUTED" else verdict.lower()
    return [f"inconclusive:{reason}"] if head_pass else ["head_not_passing"]


def _components_characterizes(head: _SideOutcome) -> list[str]:
    if head.status == "fault":
        return [f"fault:{head.code}"]
    return ["no_finding"] if head.verdict == "H_PASS" else ["head_not_passing"]


@dataclass
class _ClaimReport:
    node_id: str
    intent: str
    auto_discovered: bool
    components: list[str]
    base_absent_symbol: str | None = None
    base_verdict: str | None = None
    head_verdict: str | None = None
    base_cases: list[dict[str, Any]] = field(default_factory=list)
    head_cases: list[dict[str, Any]] = field(default_factory=list)
    # Module names (never paths) the runtime audit found loaded from outside.
    outside_modules: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Limits:
    repeats: int
    timeout_s: int
    memory_max: str

    @classmethod
    def from_contract(cls, raw: dict[str, Any] | None) -> _Limits:
        merged = {**DEFAULT_LIMITS, **(raw or {})}
        return cls(
            repeats=int(merged["repeats"]),
            timeout_s=int(merged["timeout_s"]),
            memory_max=str(merged["memory_max"]),
        )


def _judge_claim(
    *,
    claim: dict[str, Any],
    base_wt: Path,
    head_wt: Path,
    limits: _Limits,
    env_by_side: dict[str, dict[str, str]],
    backend: str,
    attributor: Callable[[], _Attributor],
) -> _ClaimReport:
    node = _parse_node_id(claim["test"])
    intent = claim.get("intent", "fixes")
    auto_discovered = bool(claim.get("_auto_discovered"))

    def judge(side: str) -> _SideOutcome:
        ctx = _Context(
            side=side,
            backend=backend,
            node=node,
            base_wt=base_wt,
            head_wt=head_wt,
            attributor=attributor,
        )
        return _judge_side(
            ctx=ctx,
            worktree=base_wt if side == "base" else head_wt,
            repeats=limits.repeats,
            timeout_s=limits.timeout_s,
            memory_max=limits.memory_max,
            env=env_by_side[side],
        )

    if intent == "characterizes":
        # Spec §1.1: a characterizes claim only needs to pass at head. Base is
        # never run for it -- in particular, a slow/hanging/broken base must
        # not fault a claim that never asked base a question.
        head_outcome = judge("head")
        return _ClaimReport(
            node_id=node.raw,
            intent=intent,
            auto_discovered=auto_discovered,
            components=_components_characterizes(head_outcome),
            head_verdict=head_outcome.verdict if head_outcome.status == "ok" else None,
            head_cases=head_outcome.cases,
            outside_modules=head_outcome.outside_modules,
        )

    base_outcome = judge("base")
    if base_outcome.status == "fault":
        return _ClaimReport(
            node_id=node.raw,
            intent=intent,
            auto_discovered=auto_discovered,
            components=[f"fault:{base_outcome.code}"],
            outside_modules=base_outcome.outside_modules,
        )

    head_outcome = judge("head")
    return _ClaimReport(
        node_id=node.raw,
        intent=intent,
        auto_discovered=auto_discovered,
        components=_components(base_outcome, head_outcome),
        base_absent_symbol=base_outcome.symbol,
        base_verdict=base_outcome.verdict,
        head_verdict=head_outcome.verdict if head_outcome.status == "ok" else None,
        base_cases=base_outcome.cases,
        head_cases=head_outcome.cases,
        outside_modules=head_outcome.outside_modules,
    )


# ---------------------------------------------------------------------------
# auto-discovery (spec section 1.3), following pytest's default collection rules
# ---------------------------------------------------------------------------

# pytest defaults: python_files, python_classes, python_functions, norecursedirs.
_PYTEST_FILE_PATTERNS = ("test_*.py", "*_test.py")
_PYTEST_NORECURSE = (
    "*.egg",
    ".*",
    "_darcs",
    "build",
    "CVS",
    "dist",
    "node_modules",
    "venv",
    "{arch}",
)


def _is_pytest_test_file(rel: str) -> bool:
    parts = rel.split("/")
    if any(fnmatch.fnmatch(d, pat) for d in parts[:-1] for pat in _PYTEST_NORECURSE):
        return False
    return any(fnmatch.fnmatch(parts[-1], pat) for pat in _PYTEST_FILE_PATTERNS)


def _test_function_defs_from_source(source: str) -> dict[str, str]:
    """Test functions pytest would collect by default, keyed by node-id suffix.

    Module-level ``test*`` functions; ``test*`` methods of ``Test*`` classes that
    define no ``__init__`` (pytest skips those), including nested ``Test*``
    classes. ``@pytest.fixture`` functions are never tests.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    defs: dict[str, str] = {}

    def visit_functions(body: list[ast.stmt], prefix: str) -> None:
        for child in body:
            if (
                isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and child.name.startswith("test")
                and not _is_fixture(child)
            ):
                defs[f"{prefix}{child.name}"] = ast.dump(child)
            elif isinstance(child, ast.ClassDef) and child.name.startswith("Test"):
                has_init = any(
                    isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)) and s.name == "__init__"
                    for s in child.body
                )
                if not has_init:
                    visit_functions(child.body, prefix=f"{prefix}{child.name}::")

    visit_functions(tree.body, "")
    return defs


def _show_file_at_commit(repo: Path, commit: str, relpath: str) -> str | None:
    """``git show <commit>:<relpath>``, or None if it does not exist there."""
    result = _git(repo, "show", f"{commit}:{relpath}")
    if result.returncode != 0:
        return None
    return result.stdout


def _discover_claims(
    repo_root: Path,
    base: str,
    head_wt: Path,
    test_patterns: list[re.Pattern[str]],
    already_claimed: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """AST-diff test functions added or modified between base and head (spec §1.3).

    Returns ``(claims, skipped)``: head test files that cannot be decoded or
    parsed are listed in ``skipped`` with a reason (spec §4), never silently
    dropped. Base's AST must come from the base commit's own git blob, via ``git show``,
    never from the worktree: the worktree's test files have already been
    overlaid with head's by this point.
    """
    discovered: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for rel in _list_files(head_wt):
        if not _matches_any(rel, test_patterns) or not _is_pytest_test_file(rel):
            continue
        try:
            head_source = (head_wt / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            reason = f"auto-discovery could not read head test file ({type(exc).__name__})"
            skipped.append({"test": rel, "reason": reason})
            continue
        try:
            ast.parse(head_source)
        except (SyntaxError, ValueError) as exc:
            reason = f"auto-discovery could not parse head test file ({type(exc).__name__})"
            skipped.append({"test": rel, "reason": reason})
            continue
        head_defs = _test_function_defs_from_source(head_source)
        base_source = _show_file_at_commit(repo_root, base, rel)
        base_defs = _test_function_defs_from_source(base_source) if base_source is not None else {}
        for qualname, dump in sorted(head_defs.items()):
            if base_defs.get(qualname) == dump:
                continue
            node_id = f"{rel}::{qualname}"
            if node_id in already_claimed:
                continue
            discovered.append({"test": node_id, "intent": "fixes", "_auto_discovered": True})
    return sorted(discovered, key=lambda c: c["test"]), skipped


# ---------------------------------------------------------------------------
# finding assembly
# ---------------------------------------------------------------------------


def _fbpa_finding(
    *,
    finding_id: str,
    finding_type: str,
    title: str,
    description: str,
    error_class: str,
    severity: str,
    reproduction: str,
    locator: str,
    reproduction_notes: str | None = None,
) -> dict[str, Any]:
    if finding_type not in FINDING_TYPES:  # pragma: no cover - closed vocabulary
        raise FbpaInvariantError(f"unknown fbpa finding_type {finding_type!r}")
    finding: dict[str, Any] = {
        "finding_id": finding_id,
        "finding_type": finding_type,
        "title": title,
        "description": description,
        "error_class": error_class,
        "source": "deterministic_probe",
        "severity": severity,
        "confidence": "high",
        "reproduction": reproduction,
    }
    # The attestation schema requires reproduction_notes whenever reproduction
    # is not "reproduced" (unreproduced / not_reproducible / not_attempted).
    if reproduction != "reproduced":
        finding["reproduction_notes"] = reproduction_notes or (
            "The deterministic probe could not run the claimed test to a definite "
            "pass/fail result; see the finding description for why."
        )
    finding["evidence"] = [
        {
            "evidence_id": f"evidence-{finding_id}",
            "kind": "file_line",
            "description": "Produced by the fail-before/pass-after (FBPA) probe.",
            "locator": locator,
        }
    ]
    return finding


def _component_finding(component: str, report: _ClaimReport) -> tuple[str, dict[str, Any]] | None:
    """(bucket, finding kwargs) for one §3.4 component, or None for no finding."""
    node_id = report.node_id
    if component in ("demonstrated", "no_finding"):
        return None
    if component == "base_passes":
        return "base_passes", {
            "finding_type": "fbpa-base-passes",
            "title": "FBPA: the claimed test already passes before the fix",
            "description": (
                f"{node_id} is claimed to fix a bug (intent=fixes), but it already passes "
                "with head's implementation removed (base_passes)."
            ),
            "error_class": "material_requirement_miss",
            "severity": "high",
            "reproduction": "reproduced",
        }
    if component == "head_not_passing":
        return "head_not_passing", {
            "finding_type": "fbpa-head-not-passing",
            "title": "FBPA: the claimed test does not pass at head",
            "description": (
                f"{node_id} does not pass with head's own implementation (head_not_passing)."
            ),
            "error_class": "material_requirement_miss",
            "severity": "high",
            "reproduction": "reproduced",
        }
    if component == "absence_only":
        return "absence_only", {
            "finding_type": "fbpa-absence-only",
            "title": "FBPA: the test fails before only because a symbol is missing",
            "description": (
                f"{node_id} fails at base only because a head-only symbol "
                f"({report.base_absent_symbol!r}) does not exist yet (absence_only). "
                "This does not show the test catches a behavioural fault."
            ),
            "error_class": "fitness",
            "severity": "med",
            "reproduction": "reproduced",
        }
    if component.startswith("inconclusive:"):
        reason = component.split(":", 1)[1]
        return "inconclusive", {
            "finding_type": "fbpa-inconclusive",
            "title": "FBPA: the claim could not be judged",
            "description": (
                f"{node_id} landed in an inconclusive base-side state ({reason}); the probe "
                "cannot tell whether it fails before the fix."
            ),
            "error_class": "material_requirement_miss",
            "severity": "high",
            "reproduction": "not_reproducible",
            "reproduction_notes": (
                f"Base landed in an inconclusive state ({reason}); rerunning the probe "
                "cannot turn this into a pass or fail without a code change."
            ),
        }
    if component.startswith("fault:"):
        code = component.split(":", 1)[1]
        return "fault", {
            "finding_type": "fbpa-fault",
            "title": f"FBPA: infrastructure fault ({code})",
            "description": (
                f"{node_id} could not be judged because of an infrastructure fault ({code})."
            ),
            "error_class": "material_requirement_miss",
            "severity": "high",
            "reproduction": "not_reproducible",
            "reproduction_notes": (
                f"Infrastructure fault {code}: the probe could not reach a pass/fail "
                "verdict for this claim (fail-closed; this is never silently a pass)."
            ),
        }
    raise FbpaInvariantError(f"unknown fbpa component {component!r}")  # pragma: no cover


# Spec §4: faults that mean the probe could not measure. These are never
# downgraded, in auto_discover mode included.
_ENV_FAULT_CODES = frozenset(
    {"F_ENV_IMPORT", "F_RUNNER", "F_OOM", "F_TIMEOUT", "F_NO_REPORT", "F_EXIT_XML_MISMATCH"}
)
# Components whose result is an actual measurement of the test (it ran to a
# pass/fail verdict on both sides), as opposed to "could not be judged".
_MEASURED_BUCKETS = frozenset({"base_passes", "head_not_passing", "absence_only"})


def _downgrades_in_auto_mode(component: str) -> bool:
    """Spec §4 last row: test-level results of an auto-discovered test are advisory;
    environment-level faults are not (they keep the fbpa-fault row)."""
    if component.startswith("fault:"):
        return component.split(":", 1)[1] not in _ENV_FAULT_CODES
    return True


def _advisory(kwargs: dict[str, Any], *, measured: bool) -> dict[str, Any]:
    """The advisory form (fitness/med) of a test-level auto-discovered result.

    ``reproduction`` stays truthful: "reproduced" only when the result is an
    actual measurement (base_passes, head_not_passing, absence_only); an
    inconclusive, F_FLAKY or F_NOT_COLLECTED result is "not_reproducible".
    """
    out = dict(kwargs)
    out.update(error_class="fitness", severity="med")
    if measured:
        out["reproduction"] = "reproduced"
        out.pop("reproduction_notes", None)
    else:
        out["reproduction"] = "not_reproducible"
        out.setdefault(
            "reproduction_notes",
            "The probe could not reach a pass/fail measurement for this auto-discovered test.",
        )
    out["description"] = (
        out["description"] + " This test was auto-discovered, not claimed by the author, "
        "so the result is advisory."
    )
    return out


def _emit_findings(
    report: _ClaimReport, counter: list[int]
) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Return (findings, buckets, all_advisory).

    ``buckets`` lists every §4.1 counting class this claim lands in, in component
    order: a claim that is both base_passes and head_not_passing counts in both.
    ``all_advisory`` is True when every finding was downgraded to advisory.
    """
    findings: list[dict[str, Any]] = []
    buckets: list[str] = []
    all_advisory = True
    for component in report.components:
        produced = _component_finding(component, report)
        if produced is None:
            buckets.append("no_finding" if component == "no_finding" else "demonstrated")
            continue
        bucket, kwargs = produced
        buckets.append(bucket)
        if report.auto_discovered and _downgrades_in_auto_mode(component):
            kwargs = _advisory(kwargs, measured=bucket in _MEASURED_BUCKETS)
        else:
            all_advisory = False
        counter[0] += 1
        findings.append(
            _fbpa_finding(finding_id=f"fbpa-{counter[0]}", locator=report.node_id, **kwargs)
        )
    return findings, buckets, all_advisory and bool(findings)


# ---------------------------------------------------------------------------
# top-level entry point
# ---------------------------------------------------------------------------


_CANARY_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")


def _validate_claims(claims: list[dict[str, Any]]) -> None:
    """Contract-level claim checks the JSON schema cannot express."""
    seen: set[str] = set()
    for claim in claims:
        test = claim.get("test", "")
        if "::" not in test:
            raise FbpaError(f"fail_before_pass_after claim {test!r} is not a pytest node id")
        if test in seen:
            # Two claims on one node id (e.g. with two intents) would produce two
            # checks with the same check_id; the contract must pick one intent.
            raise FbpaError(f"fail_before_pass_after claims name {test!r} more than once")
        seen.add(test)


def _importable_roots_names(worktree: Path, test_patterns: list[re.Pattern[str]]) -> set[str]:
    """Top-level module names a worktree provides outside its test files.

    A name counts if it is a module/package at the worktree root, or one directory
    down inside a directory that is not itself a package (``src/pkg``,
    ``lib/pkgname``). Standard-library names are excluded so a stray
    ``scripts/json.py`` cannot make the stdlib ``json`` look like project code.
    """
    files = [
        rel
        for rel in _list_files(worktree)
        if rel.endswith(".py") and not _matches_any(rel, test_patterns)
    ]
    file_set = set(files)
    names: set[str] = set()
    for rel in files:
        parts = rel[: -len(".py")].split("/")
        candidates = [parts[0]]
        if len(parts) >= 2 and f"{parts[0]}/__init__.py" not in file_set:
            candidates.append(parts[1])
        names.update(c for c in candidates if c.isidentifier() and c != "__init__")
    return names - set(getattr(sys, "stdlib_module_names", ()))


def _test_imported_project_modules(
    head_wt: Path, claims: list[dict[str, Any]], test_patterns: list[re.Pattern[str]]
) -> list[str]:
    """Top-level project modules the claimed test files import (spec §2 canary).

    "Project" is :func:`_importable_roots_names` of head. A helper inside ``tests/``
    that pytest puts on ``sys.path`` itself does not count, since a plain
    ``python -c`` canary cannot import it.
    """
    imported: set[str] = set()
    for rel in sorted({_parse_node_id(c["test"]).file_rel for c in claims}):
        tree = _parse_file(head_wt / rel)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".", 1)[0])
    return sorted(imported & _importable_roots_names(head_wt, test_patterns))


_LOCATE_SCRIPT = (
    "import importlib.util, json, sys\n"
    "out = {}\n"
    "for name in json.loads(sys.argv[1]):\n"
    "    try:\n"
    "        spec = importlib.util.find_spec(name)\n"
    "    except Exception:\n"
    "        spec = None\n"
    "    if spec is None:\n"
    "        out[name] = None\n"
    "        continue\n"
    "    origin = spec.origin if spec.has_location else None\n"
    "    locations = list(spec.submodule_search_locations or [])\n"
    "    out[name] = {'origin': origin, 'locations': locations}\n"
    "print(json.dumps(out))\n"
)


def _locate_names(
    worktree: Path,
    names: list[str],
    env: dict[str, str],
    *,
    backend: str,
    limits: _Limits,
) -> dict[str, dict[str, Any]]:
    """Where each top-level name would be imported from, without executing it.

    Used for the "every importable top-level name in either tree" part of the
    canary (spec §2): those names include scripts, which must not be run just to
    find out where they live, so ``importlib.util.find_spec`` locates them in one
    limited process per side. A name found nowhere is harmless (``not_found``);
    a name found outside the worktree, or with no file location, is not.

    A namespace package (no ``__init__.py``) merges every same-named directory on
    ``sys.path``; it resolves inside the worktree when its *first* portion is the
    worktree's, which is where its submodules are looked up first. Later portions
    outside the worktree (for example an editable install of another checkout)
    are recorded as ``outside_portions`` but do not fault on their own.
    """
    if not names:
        return {}
    proc = _run_limited(
        [sys.executable, "-c", _LOCATE_SCRIPT, json.dumps(names)],
        cwd=worktree,
        env=env,
        timeout_s=limits.timeout_s,
        memory_max=limits.memory_max,
        backend=backend,
    )
    try:
        located = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        # The locator itself failed: nothing is known, so nothing is trusted.
        return {name: {"resolved_outside_worktree": True} for name in names}
    root = worktree.resolve()

    def inside(candidate: str) -> str | None:
        try:
            return Path(candidate).resolve().relative_to(root).as_posix()
        except ValueError:
            return None

    out: dict[str, dict[str, Any]] = {}
    for name in names:
        found = located.get(name)
        if found is None:
            out[name] = {"not_found": True}
            continue
        origin, locations = found.get("origin"), list(found.get("locations") or [])
        primary = origin or (locations[0] if locations else None)
        relative = inside(primary) if primary else None
        if relative is None:
            out[name] = {"resolved_outside_worktree": True}
            continue
        status: dict[str, Any] = {"path": relative}
        if origin is None and any(inside(loc) is None for loc in locations[1:]):
            status["outside_portions"] = True
        out[name] = status
    return out


def _run_canary(
    canary_packages: list[str],
    *,
    worktrees: dict[str, Path],
    env_by_side: dict[str, dict[str, str]],
    backend: str,
    limits: _Limits,
    required: dict[str, set[str]] | None = None,
    locate_only: list[str] | None = None,
) -> tuple[dict[str, dict[str, Any]], bool]:
    """Spec §2 import-origin canary: (report, ok).

    ``ok`` requires that no name resolves outside its worktree, that each side
    resolves at least one name inside its worktree (so a misspelled declared name
    cannot disable the canary), and that every ``required`` name for a side (the
    project top-level modules the claimed test files import, where that side's
    tree contains them) resolves inside that worktree. Names that are not dotted
    identifiers are never imported (they would be interpolated into code) and are
    reported as invalid. ``locate_only`` names are located without being imported
    (see :func:`_locate_names`) and follow the same outside/at-least-one rules.
    """
    report: dict[str, dict[str, Any]] = {"base": {}, "head": {}}
    ok = True
    for side, worktree in sorted(worktrees.items()):
        side_ok = False
        located = _locate_names(
            worktree,
            [n for n in (locate_only or []) if _CANARY_NAME.match(n)],
            env_by_side[side],
            backend=backend,
            limits=limits,
        )
        for name, status in located.items():
            report[side][name] = status
            if "path" in status:
                side_ok = True
            elif status.get("resolved_outside_worktree"):
                ok = False
        for package in canary_packages:
            if not _CANARY_NAME.match(package):
                report[side][package] = {"invalid_name": True}
                continue
            result = _check_import_canary(
                worktree,
                package,
                env_by_side[side],
                backend=backend,
                memory_max=limits.memory_max,
                timeout_s=limits.timeout_s,
            )
            if result.status == "ok":
                report[side][package] = {"path": result.relative_path}
                side_ok = True
            elif result.status == "not_found":
                # Benign on its own (e.g. a package head adds that does not exist
                # at base yet), as long as some other name resolves on this side --
                # unless the claimed tests import it and this tree contains it.
                report[side][package] = {"not_found": True}
                if package in (required or {}).get(side, set()):
                    ok = False
            else:
                report[side][package] = {"resolved_outside_worktree": True}
                ok = False
        ok = ok and side_ok
    return report, ok


def run_fbpa(repo_root: Path, fbpa_contract: dict[str, Any]) -> dict[str, Any]:
    """Run the fail-before/pass-after probe for one contract and return its report.

    Returns a dict with ``checks``, ``findings`` and ``fbpa`` (the §4.1 accounting
    block). Raises :class:`FbpaError` only for contract/environment problems that
    cannot be attributed to a single claim (for example, the base or head commit
    does not exist); per-claim problems always become ``fbpa-fault`` findings
    instead of exceptions, per the fail-closed policy in spec section 4.
    """
    base = fbpa_contract["base"]
    head = fbpa_contract["head"]
    runner = fbpa_contract.get("runner", "pytest")
    if runner != "pytest":
        raise FbpaError(f"unsupported fail_before_pass_after runner: {runner!r}")

    test_patterns = _compile_patterns(fbpa_contract.get("test_paths") or DEFAULT_TEST_PATHS)
    limits = _Limits.from_contract(fbpa_contract.get("limits"))
    claims: list[dict[str, Any]] = [dict(c) for c in (fbpa_contract.get("claims") or [])]
    _validate_claims(claims)
    auto_discover = bool(fbpa_contract.get("auto_discover", False))
    discovery_skipped: list[dict[str, str]] = []

    # Separate temporary parents, same leaf name (spec §1.2); the plugin lives in
    # a third directory so PYTHONPATH does not point into either side's parent.
    parents = {side: Path(tempfile.mkdtemp(prefix="fbpa-")) for side in ("base", "head", "aux")}
    base_wt: Path | None = None
    head_wt: Path | None = None
    try:
        base_sha = _resolve_commit(repo_root, base)
        head_sha = _resolve_commit(repo_root, head)
        base_wt = _add_worktree(repo_root, parents["base"], "base", base_sha)
        head_wt = _add_worktree(repo_root, parents["head"], "head", head_sha)
        overlay_files = _overlay_test_files(base_wt, head_wt, test_patterns)
        non_test_diff_count = _non_test_diff_count(repo_root, base_sha, head_sha, test_patterns)

        if auto_discover:
            already = {c["test"] for c in claims}
            discovered, discovery_skipped = _discover_claims(
                repo_root, base_sha, head_wt, test_patterns, already
            )
            claims.extend(discovered)
        # Contract order is not significant; a stable order keeps finding ids and
        # check order identical across prepare/finalize on different machines.
        claims.sort(key=lambda c: c["test"])

        backend = _detect_memory_backend()
        logger.info("fbpa memory limiter backend: %s", backend or "none")

        # Spec §2: the canary list is the union of declared and auto-detected
        # names. An empty list (nothing declared, nothing detected) fails the
        # "at least one name resolves" rule and so faults F_ENV_IMPORT.
        declared = list(fbpa_contract.get("import_canary") or [])
        test_imported = _test_imported_project_modules(head_wt, claims, test_patterns)
        canary_packages = sorted(
            set(declared) | set(_default_canary_packages(head_wt)) | set(test_imported)
        )
        # Spec §2: every importable top-level name in either tree is also checked
        # (a test can reach a module through importlib, not only a static import).
        locate_only = sorted(
            (
                _importable_roots_names(base_wt, test_patterns)
                | _importable_roots_names(head_wt, test_patterns)
            )
            - set(canary_packages)
        )
        plugin_dir = _install_xpass_plugin(parents["aux"])
        # Project names for the runtime audit: every top-level name in either
        # tree, test files included (spec §2, amendment 6).
        audit_names = parents["aux"] / "project-names.json"
        audit_names.write_text(
            json.dumps(
                sorted(
                    _importable_roots_names(base_wt, [])
                    | _importable_roots_names(head_wt, [])
                    | set(_default_canary_packages(head_wt))
                )
            ),
            encoding="utf-8",
        )
        env_by_side = {
            side: {**_subprocess_env(wt, plugin_dir), _AUDIT_NAMES_ENV: str(audit_names)}
            for side, wt in (("base", base_wt), ("head", head_wt))
        }
        canary_report: dict[str, dict[str, Any]] = {"base": {}, "head": {}}
        canary_ok = False
        if backend is not None:
            canary_report, canary_ok = _run_canary(
                canary_packages,
                worktrees={"base": base_wt, "head": head_wt},
                env_by_side=env_by_side,
                backend=backend,
                limits=limits,
                required={
                    side: set(test_imported) & _importable_roots_names(wt, test_patterns)
                    for side, wt in (("base", base_wt), ("head", head_wt))
                },
                locate_only=locate_only,
            )

        indexes: list[_Attributor] = []
        index_roots = (base_wt, head_wt)

        def attributor() -> _Attributor:
            # Built lazily (most claims never need it) and once per probe run.
            if not indexes:
                base_index = _SymbolIndex(index_roots[0], test_patterns)
                head_index = _SymbolIndex(index_roots[1], test_patterns)
                indexes.append(_Attributor(base_index, head_index))
            return indexes[0]

        claim_reports: list[_ClaimReport] = []
        for claim in claims:
            fault = None
            if backend is None:
                fault = "F_RUNNER"
            elif not canary_ok:
                fault = "F_ENV_IMPORT"
            else:
                try:
                    claim_reports.append(
                        _judge_claim(
                            claim=claim,
                            base_wt=base_wt,
                            head_wt=head_wt,
                            limits=limits,
                            env_by_side=env_by_side,
                            backend=backend,
                            attributor=attributor,
                        )
                    )
                    continue
                except Exception:  # noqa: BLE001 - one claim's crash must not sink the rest
                    logger.exception("fbpa: judging %s raised; recording F_RUNNER", claim["test"])
                    fault = "F_RUNNER"
            claim_reports.append(
                _ClaimReport(
                    node_id=claim["test"],
                    intent=claim.get("intent", "fixes"),
                    auto_discovered=bool(claim.get("_auto_discovered")),
                    components=[f"fault:{fault}"],
                )
            )
    finally:
        for worktree in (base_wt, head_wt):
            if worktree is not None:
                _remove_worktree(repo_root, worktree)
        for parent in parents.values():
            shutil.rmtree(parent, ignore_errors=True)

    if non_test_diff_count == 0:
        # Spec §1.2 invariant: with no implementation change, any base/head
        # difference comes from test code (or the environment), so no fixes claim
        # may be demonstrated.
        for report in claim_reports:
            if report.intent == "fixes" and report.components == ["demonstrated"]:
                report.components = ["inconclusive:no_impl_change"]

    return _assemble_report(
        claim_reports,
        overlay_files=overlay_files,
        non_test_diff_count=non_test_diff_count,
        resolved={"base": base_sha, "head": head_sha},
        canary_report=canary_report,
        limiter_backend=backend or "none",
        discovery_skipped=discovery_skipped,
    )


_JUDGED_BUCKETS = ("demonstrated", "no_finding", "base_passes", "head_not_passing", "absence_only")
_FAILING_BUCKETS = ("base_passes", "head_not_passing", "fault")


def _skip_reason(report: _ClaimReport) -> str:
    """Why this claim is not in ``judged`` (every inconclusive reason and every fault)."""
    for component in report.components:
        if component.startswith("inconclusive:"):
            return f"inconclusive: {component.split(':', 1)[1]}"
        if component.startswith("fault:"):
            return f"fault: {component.split(':', 1)[1]}"
    return "not judged"  # pragma: no cover - defensive, every non-judged bucket matches above


def _nothing_judged_finding(finding_id: str, description: str) -> dict[str, Any]:
    """Spec §4/§4.1: ``in_scope == 0`` or ``judged == 0`` with the field present is
    needs_review in every mode (auto_discover included).

    A contract that asks for the probe but ends up judging nothing -- an empty
    claim list, auto-discovery that matched nothing (exactly how a mistyped
    ``test_paths`` would hide), or every claim inconclusive/faulted -- must not
    look clean.
    """
    return _fbpa_finding(
        finding_id=finding_id,
        finding_type="fbpa-inconclusive",
        title="FBPA: nothing was judged",
        description=description,
        error_class="material_requirement_miss",
        severity="high",
        reproduction="not_reproducible",
        reproduction_notes=(
            "No claim reached a verdict; check the claims list, test_paths and the "
            "skipped entries. Rerunning cannot change this without a change."
        ),
        locator="fail_before_pass_after",
    )


def _assemble_report(
    claim_reports: list[_ClaimReport],
    *,
    overlay_files: list[str],
    non_test_diff_count: int,
    canary_report: dict[str, dict[str, Any]],
    limiter_backend: str,
    discovery_skipped: list[dict[str, str]] | None = None,
    resolved: dict[str, str] | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    verdict_counts: dict[str, int] = {}
    skipped: list[dict[str, str]] = list(discovery_skipped or [])
    judged = 0
    auto_advisory = 0
    counter = [0]

    for report in claim_reports:
        claim_findings, buckets, all_advisory = _emit_findings(report, counter)
        findings.extend(claim_findings)
        for bucket in buckets:
            counts[bucket] = counts.get(bucket, 0) + 1
        if all_advisory:
            auto_advisory += 1
        for verdict in (report.base_verdict, report.head_verdict):
            if verdict:
                verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
        if all(bucket in _JUDGED_BUCKETS for bucket in buckets):
            judged += 1
        else:
            # Every claim not judged lands in "inconclusive" or "fault" -- every
            # one of those must be listed, with its reason.
            skipped.append({"test": report.node_id, "reason": _skip_reason(report)})
        if all_advisory:
            status = "advisory"
        else:
            status = "fail" if any(b in _FAILING_BUCKETS for b in buckets) else "pass"
        checks.append(
            {
                "check_id": f"fbpa:{report.node_id}",
                "kind": "fbpa_claim",
                "path": report.node_id,
                "status": status,
                "verdict": buckets[0],
                "verdicts": buckets,
                "auto_discovered": report.auto_discovered,
                "components": list(report.components),
                "base_verdict": report.base_verdict,
                "head_verdict": report.head_verdict,
                "base_absent_target": report.base_absent_symbol,
                "outside_modules": report.outside_modules,
                "base_cases": report.base_cases,
                "head_cases": report.head_cases,
            }
        )

    in_scope = len(claim_reports)
    if in_scope == 0:
        findings.append(
            _nothing_judged_finding(
                "fbpa-no-claims",
                "fail_before_pass_after is present but no claim was in scope (no declared "
                "claims and no auto-discovered tests under test_paths); nothing was judged.",
            )
        )
    elif judged == 0 and all(f["error_class"] == "fitness" for f in findings):
        # Every claim was auto-discovered and test-level inconclusive (advisory):
        # the per-claim findings alone would let the whole result pass.
        findings.append(
            _nothing_judged_finding(
                "fbpa-none-judged",
                f"fail_before_pass_after had {in_scope} claim(s) in scope but none could "
                "be judged; see skipped.",
            )
        )
    if in_scope > 0 and judged == 0:
        if not any(f["finding_type"] in ("fbpa-inconclusive", "fbpa-fault") for f in findings):
            raise FbpaInvariantError(
                "fbpa invariant violated: in_scope > 0 and judged == 0 produced no "
                "fbpa-inconclusive or fbpa-fault finding"
            )

    fbpa_block = {
        "in_scope": in_scope,
        "judged": judged,
        "counts": dict(sorted(counts.items())),
        "auto_advisory": auto_advisory,
        "verdict_counts": dict(sorted(verdict_counts.items())),
        "skipped": skipped,
        "overlay_files": overlay_files,
        "non_test_diff_count": non_test_diff_count,
        "import_canary": canary_report,
        # Spec §2: the limiter backend is recorded here, never in finding text.
        # finalize requires the same backend as prepare (runtime.py), since an
        # rlimit run can legitimately classify memory exhaustion differently.
        "limiter_backend": limiter_backend,
        # Spec §1.2: the full SHAs actually measured, whatever the contract named.
        "resolved": resolved or {},
    }
    return {"checks": checks, "findings": findings, "fbpa": fbpa_block}
