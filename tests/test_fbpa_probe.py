"""Controls for the deterministic fail-before/pass-after (FBPA) probe.

Every fixture below ``git init``s a tiny, throwaway repository inside ``tmp_path``
and calls the real :func:`validity_audit.probes.run_probes` (via :func:`_run_fbpa`,
which goes through the public contract shape) or the real ``run_fbpa``, per
``docs/specs/probe-fail-before-pass-after.md`` section 6. None of these fixtures
depend on this repository's own history.

Every fixture that is not itself testing the import canary writes a trivial
``canary_pkg/__init__.py`` before its first commit via :func:`_init_canary_repo`:
spec §9 (amended) says an empty canary list -- nothing declared, nothing
detected -- must itself fault (``F_ENV_IMPORT``), so a fixture with no package at
all would otherwise have every other scenario it is trying to demonstrate masked
by that fault.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path
from typing import Any

import pytest

from validity_audit.fbpa import FAULT_CODES
from validity_audit.probes import run_probes
from validity_audit.runtime import finalize_run, prepare_run

pytestmark = pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")


# ---------------------------------------------------------------------------
# repo-building helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "fbpa-test@example.com")
    _git(repo, "config", "user.name", "FBPA Test")


def _write(repo: Path, relpath: str, content: str) -> None:
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _init_canary_repo(repo: Path) -> None:
    """``_init_repo`` plus a trivial package the default canary will discover."""
    _init_repo(repo)
    _write(repo, "canary_pkg/__init__.py", "")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _run_fbpa(
    repo: Path,
    *,
    base: str,
    head: str,
    claims: list[dict[str, Any]],
    limits: dict[str, Any] | None = None,
    auto_discover: bool = False,
    import_canary: list[str] | None = None,
) -> dict[str, Any]:
    contract: dict[str, Any] = {
        "base": base,
        "head": head,
        "runner": "pytest",
        "claims": claims,
    }
    if limits is not None:
        contract["limits"] = limits
    if auto_discover:
        contract["auto_discover"] = True
    if import_canary is not None:
        contract["import_canary"] = import_canary
    return run_probes(repo, [], contract={"fail_before_pass_after": contract})


def _run_one(
    repo: Path,
    base: str,
    head: str,
    test_id: str,
    *,
    intent: str = "fixes",
    limits: dict[str, Any] | None = None,
    import_canary: list[str] | None = None,
) -> dict[str, Any]:
    return _run_fbpa(
        repo,
        base=base,
        head=head,
        claims=[{"test": test_id, "intent": intent}],
        limits=limits or FAST_LIMITS,
        import_canary=import_canary,
    )


def _labels(result: dict[str, Any]) -> set[str]:
    """The set of §3.4 verdict components the run actually produced."""
    labels: set[str] = set()
    for check in result["checks"]:
        if check["kind"] == "fbpa_claim":
            labels.update(check["components"])
    return labels


FAST_LIMITS = {"memory_max": "256M", "timeout_s": 20, "repeats": 2}

# Shared fixture bodies (kept short so call sites fit the line-length limit).
_MATHY_BUGGY = "def inc(x):\n    return x + 2\n"
_MATHY_FIXED = "def inc(x):\n    return x + 1\n"
_TEST_MATHY = "from mathy import inc\n\n\ndef test_inc():\n    assert inc(1) == 2\n"
_UTIL_NOOP = "def noop():\n    return 1\n"
_TEST_UTIL = "from util import noop\n\n\ndef test_noop():\n    assert noop() == 1\n"
_EXTRA_STUB = "# no helper yet\n"
_EXTRA_HELPER = "def helper():\n    return True\n"
_TEST_EXTRA = "from extra import helper\n\n\ndef test_extra():\n    assert helper() or True\n"
_STABLE = "def answer():\n    return 42\n"
_TEST_STABLE = "from stable import answer\n\n\ndef test_answer():\n    assert answer() == 42\n"
_TEST_PLACEHOLDER_OK = "def test_placeholder():\n    assert True\n"
_TEST_PLACEHOLDER_BAD = "def test_placeholder(:\n    assert True\n"
_TEST_REAL = "def test_real():\n    assert True\n"
_TEST_LOOP = "def test_loop():\n    while True:\n        pass\n"
_TEST_MEM = (
    "def test_mem():\n"
    "    data = []\n"
    "    while True:\n"
    "        data.append(bytearray(8 * 1024 * 1024))\n"
)
_TEST_FLAKY = (
    "from pathlib import Path\n\n\n"
    "def test_flaky_counter():\n"
    "    counter_file = Path(__file__).parent / 'flaky_counter.txt'\n"
    "    n = int(counter_file.read_text()) if counter_file.exists() else 0\n"
    "    counter_file.write_text(str(n + 1))\n"
    "    assert n % 2 == 0\n"
)
_TEST_Q = "from pkg.core import q\n\n\ndef test_q():\n    assert q() == 1\n"
_TEST_D = "from pkg.core import f\n\n\ndef test_d():\n    assert f() == 2\n"
_TEST_NS = "from nspkg.core import f\n\n\ndef test_ns():\n    assert f() == 1\n"
_TEST_N = "from pkg.core import f\n\n\ndef test_n():\n    assert f() == 2\n"
_TEST_UTIL2 = "from util2 import noop\n\n\ndef test_noop():\n    assert noop() == 1\n"
# Passes only where the checked-out commit's subject is the head commit's: base
# and head then differ with no implementation change at all (spec §1.2 invariant).
_TEST_GIT_SUBJECT = (
    "import subprocess\nfrom pathlib import Path\n\n\ndef test_w():\n"
    "    subject = subprocess.check_output(\n"
    "        ['git', 'log', '-1', '--format=%s'], cwd=Path(__file__).parent, text=True\n"
    "    )\n"
    "    assert subject.strip() == 'a test-only change'\n"
)
# Passes only in a directory named "head" (defeated by the shared leaf name).
_TEST_WORKTREE_NAME = (
    "from pathlib import Path\n\n\ndef test_w():\n"
    "    assert Path(__file__).resolve().parents[1].name == 'head'\n"
)
_TEST_SKIPS_AT_BASE = (
    "import pytest\nfrom pkg.core import f\n\n\ndef test_m():\n"
    "    if f() == 1:\n        pytest.skip('x')\n    assert f() == 2\n"
)


# ---------------------------------------------------------------------------
# Positive: base has an off-by-one, head fixes it
# ---------------------------------------------------------------------------


def test_positive_demonstrated(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "mathy.py", _MATHY_BUGGY)
    base = _commit(repo, "off-by-one bug")
    _write(repo, "mathy.py", _MATHY_FIXED)
    _write(repo, "tests/test_mathy.py", _TEST_MATHY)
    head = _commit(repo, "fix off-by-one and add a test")

    result = _run_one(repo, base, head, "tests/test_mathy.py::test_inc")
    assert _labels(result) == {"demonstrated"}
    assert result["findings"] == []
    fbpa = result["fbpa"]
    assert fbpa["in_scope"] == 1
    assert fbpa["judged"] == 1
    assert fbpa["overlay_files"] == ["tests/test_mathy.py"]
    assert fbpa["non_test_diff_count"] == 1
    # Spec §2: the limiter backend is recorded in the fbpa block.
    assert fbpa["limiter_backend"] in ("systemd-run", "rlimit")
    # Spec §1.2: the resolved full SHAs are recorded.
    assert fbpa["resolved"] == {"base": base, "head": head}


# ---------------------------------------------------------------------------
# Negative 1: the test already passes at base
# ---------------------------------------------------------------------------


def test_negative1_base_passes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "util.py", _UTIL_NOOP)
    base = _commit(repo, "initial util")
    _write(repo, "util.py", "def noop():\n    return 1  # unrelated touch\n")
    _write(repo, "tests/test_util.py", _TEST_UTIL)
    head = _commit(repo, "unrelated change plus a weak test")

    result = _run_one(repo, base, head, "tests/test_util.py::test_noop")
    assert _labels(result) == {"base_passes"}
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["error_class"] == "material_requirement_miss"
    assert finding["reproduction"] == "reproduced"
    assert finding["severity"] == "high"


# ---------------------------------------------------------------------------
# Negative 2: the test only imports a new head function and always passes
# ---------------------------------------------------------------------------


def test_negative2_absence_only(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "extra.py", _EXTRA_STUB)
    base = _commit(repo, "no helper yet")
    _write(repo, "extra.py", _EXTRA_HELPER)
    _write(repo, "tests/test_extra.py", _TEST_EXTRA)
    head = _commit(repo, "add helper and a trivially-true test")

    result = _run_one(repo, base, head, "tests/test_extra.py::test_extra")
    assert _labels(result) == {"absence_only"}
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["error_class"] == "fitness"
    assert finding["severity"] == "med"
    assert "helper" in finding["description"]


# ---------------------------------------------------------------------------
# Negative 3: head does not actually fix the implementation
# ---------------------------------------------------------------------------


def test_negative3_head_not_passing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "mathy.py", _MATHY_BUGGY)
    base = _commit(repo, "off-by-one bug")
    _write(repo, "tests/test_mathy.py", _TEST_MATHY)
    head = _commit(repo, "add a test without fixing the bug")

    result = _run_one(repo, base, head, "tests/test_mathy.py::test_inc")
    assert _labels(result) == {"head_not_passing"}
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["error_class"] == "material_requirement_miss"
    assert finding["reproduction"] == "reproduced"


# ---------------------------------------------------------------------------
# Negative 4: a characterizes test passes at base (shows the intent split works)
# ---------------------------------------------------------------------------


def test_negative4_characterizes_passes_at_base(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "stable.py", _STABLE)
    base = _commit(repo, "stable behaviour")
    _write(repo, "tests/test_stable.py", _TEST_STABLE)
    head = _commit(repo, "pin existing behaviour with a characterization test")

    result = _run_one(repo, base, head, "tests/test_stable.py::test_answer", intent="characterizes")
    assert _labels(result) == {"no_finding"}
    assert result["findings"] == []


# ---------------------------------------------------------------------------
# Fault 1: head has a syntax error (in the test file itself)
# ---------------------------------------------------------------------------


def test_fault1_syntax_error(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "tests/test_broken.py", _TEST_PLACEHOLDER_OK)
    base = _commit(repo, "valid placeholder test")
    _write(repo, "tests/test_broken.py", _TEST_PLACEHOLDER_BAD)
    head = _commit(repo, "introduce a syntax error")

    result = _run_one(repo, base, head, "tests/test_broken.py::test_placeholder")
    assert _labels(result) == {"fault:F_RUNNER"}
    finding = result["findings"][0]
    assert finding["error_class"] == "material_requirement_miss"
    assert finding["reproduction"] == "not_reproducible"
    assert "reproduction_notes" in finding


# ---------------------------------------------------------------------------
# Fault 2: the claimed node id does not exist (spec §2.1: exit 3/4 -> F_RUNNER,
# not F_NOT_COLLECTED -- that distinction is item 11 of the S1 review).
# ---------------------------------------------------------------------------


def test_fault2_nonexistent_node_id_is_runner(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "tests/test_real.py", _TEST_REAL)
    base = _commit(repo, "one real test")
    _write(repo, "README.md", "unrelated change\n")
    head = _commit(repo, "unrelated change")

    result = _run_one(repo, base, head, "tests/test_real.py::test_does_not_exist")
    assert _labels(result) == {"fault:F_RUNNER"}


# ---------------------------------------------------------------------------
# Head collection error (spec §2.1 exit-2 row, §3.2): the claimed test's own
# module fails to collect at head (a syntax error in a non-test module it
# imports, head-only). That is H_ERROR -> head_not_passing, not F_NOT_COLLECTED,
# which is reserved for a node id that does not exist at head.
# ---------------------------------------------------------------------------


def test_head_collection_error_is_head_not_passing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/core.py", "def q():\n    return 1\n")
    _write(repo, "tests/test_q.py", _TEST_Q)
    base = _commit(repo, "valid implementation")
    _write(repo, "pkg/core.py", "def q(:\n    return 1\n")  # syntax error, head-only
    head = _commit(repo, "introduce a syntax error in a non-test module")

    result = _run_one(repo, base, head, "tests/test_q.py::test_q")
    # The test passes at base, so it is also base_passes (both classes count).
    assert _labels(result) == {"base_passes", "head_not_passing"}
    assert result["checks"][0]["head_verdict"] == "H_ERROR"


# ---------------------------------------------------------------------------
# Fault 3: the test loops forever
# ---------------------------------------------------------------------------


def test_fault3_timeout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "tests/test_loop.py", _TEST_LOOP)
    base = _commit(repo, "infinite loop test")
    _write(repo, "README.md", "unrelated change\n")
    head = _commit(repo, "unrelated change")

    result = _run_one(
        repo,
        base,
        head,
        "tests/test_loop.py::test_loop",
        limits={"memory_max": "256M", "timeout_s": 5, "repeats": 2},
    )
    assert _labels(result) == {"fault:F_TIMEOUT"}


# ---------------------------------------------------------------------------
# Fault 4: the test allocates a lot of memory
# ---------------------------------------------------------------------------


def test_fault4_oom(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "tests/test_mem.py", _TEST_MEM)
    base = _commit(repo, "memory-hungry test")
    _write(repo, "README.md", "unrelated change\n")
    head = _commit(repo, "unrelated change")

    result = _run_one(
        repo,
        base,
        head,
        "tests/test_mem.py::test_mem",
        limits={"memory_max": "64M", "timeout_s": 15, "repeats": 2},
    )
    assert _labels(result) == {"fault:F_OOM"}
    # The OOM-killed scope must not linger as a "failed" unit record.
    units = subprocess.run(
        ["systemctl", "--user", "list-units", "fbpa-*", "--all", "--no-legend"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert "test_mem.py" not in units


# ---------------------------------------------------------------------------
# Fault 5: import canary via a PYTHONPATH decoy (named honestly -- this is
# not a real editable install; see test_fault5b below for that shape).
# ---------------------------------------------------------------------------


def test_fault5_import_canary_pythonpath_decoy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    # pkgname lives under lib/, which is outside the probe's default canary
    # discovery locations (worktree root and worktree/src), so the probe will
    # only find it via PYTHONPATH -- and nothing in the worktree puts it there.
    _write(repo, "lib/pkgname/__init__.py", "VALUE = 'worktree'\n")
    _write(repo, "tests/test_placeholder.py", _TEST_PLACEHOLDER_OK)
    base = _commit(repo, "worktree copy of pkgname")
    _write(repo, "README.md", "unrelated change\n")
    head = _commit(repo, "unrelated change")

    decoy = tmp_path / "decoy"
    _write(decoy, "pkgname/__init__.py", "VALUE = 'decoy'\n")
    monkeypatch.setenv("PYTHONPATH", str(decoy))

    result = _run_one(
        repo,
        base,
        head,
        "tests/test_placeholder.py::test_placeholder",
        import_canary=["pkgname"],
    )
    assert _labels(result) == {"fault:F_ENV_IMPORT"}
    fbpa = result["fbpa"]
    assert fbpa["import_canary"]["base"]["pkgname"] == {"resolved_outside_worktree": True}
    assert fbpa["import_canary"]["head"]["pkgname"] == {"resolved_outside_worktree": True}


def test_fault5b_import_canary_editable_install_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproduce the actual shape of ``pip install -e`` shadowing (item 16).

    An editable install works by dropping a ``.pth`` file (and, for the
    modern ``pip``, a tiny loader) into a site directory that ``site``
    processes at interpreter startup. This reproduces exactly that -- a
    ``sitecustomize.py`` plus a ``.pth`` file in a throwaway directory added
    to ``PYTHONPATH`` -- so the import genuinely resolves through Python's
    own site-processing machinery, not through a hand-rolled substitute, and
    without touching this machine's real site-packages.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "lib/pkgname/__init__.py", "VALUE = 'worktree'\n")
    _write(repo, "tests/test_placeholder.py", _TEST_PLACEHOLDER_OK)
    base = _commit(repo, "worktree copy of pkgname")
    _write(repo, "README.md", "unrelated change\n")
    head = _commit(repo, "unrelated change")

    editable_src = tmp_path / "editable-src"
    _write(editable_src, "pkgname/__init__.py", "VALUE = 'editable_install'\n")
    site_dir = tmp_path / "fake-site"
    site_dir.mkdir()
    (site_dir / "editable-pkgname.pth").write_text(str(editable_src) + "\n", encoding="utf-8")
    (site_dir / "sitecustomize.py").write_text(
        textwrap.dedent(
            """
            import os
            import site

            site.addsitedir(os.path.dirname(__file__))
            """
        ),
        encoding="utf-8",
    )
    existing = os.environ.get("PYTHONPATH")
    new_path = f"{site_dir}{os.pathsep}{existing}" if existing else str(site_dir)
    monkeypatch.setenv("PYTHONPATH", new_path)

    result = _run_one(
        repo,
        base,
        head,
        "tests/test_placeholder.py::test_placeholder",
        import_canary=["pkgname"],
    )
    assert _labels(result) == {"fault:F_ENV_IMPORT"}


# ---------------------------------------------------------------------------
# Fault 6: a nondeterministic test
# ---------------------------------------------------------------------------


def test_fault6_flaky(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "tests/test_flaky.py", _TEST_FLAKY)
    base = _commit(repo, "a test that alternates outcome deterministically")
    _write(repo, "README.md", "unrelated change\n")
    head = _commit(repo, "unrelated change")

    result = _run_one(repo, base, head, "tests/test_flaky.py::test_flaky_counter")
    assert _labels(result) == {"fault:F_FLAKY"}


# ---------------------------------------------------------------------------
# Item 2: call-phase ImportError / AttributeError on a head-only symbol must
# be absence_only, not "demonstrated" -- the test never actually ran its own
# assertion logic against the fix, it just failed to import/resolve a name
# that does not exist yet.
# ---------------------------------------------------------------------------


def test_call_phase_import_error_is_absence_only(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/core.py", "def old():\n    return 1\n")
    base = _commit(repo, "no new_func yet")
    _write(repo, "pkg/core.py", "def old():\n    return 1\n\n\ndef new_func():\n    return 5\n")
    _write(
        repo,
        "tests/test_a.py",
        "def test_local():\n    from pkg.core import new_func\n    assert new_func() or True\n",
    )
    head = _commit(repo, "add new_func and an in-function import test")

    result = _run_one(repo, base, head, "tests/test_a.py::test_local")
    assert _labels(result) == {"absence_only"}


def test_call_phase_attribute_error_is_absence_only(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/core.py", "def old():\n    return 1\n")
    base = _commit(repo, "no new_func yet")
    _write(repo, "pkg/core.py", "def old():\n    return 1\n\n\ndef new_func():\n    return 5\n")
    _write(
        repo,
        "tests/test_a2.py",
        "import pkg.core\n\n\ndef test_attr():\n    assert pkg.core.new_func() or True\n",
    )
    head = _commit(repo, "add new_func and an attribute-access test")

    result = _run_one(repo, base, head, "tests/test_a2.py::test_attr")
    assert _labels(result) == {"absence_only"}


# ---------------------------------------------------------------------------
# Item 4: a head conftest.py importing a head-only symbol must be absence_only
# at base (attributable), not a bare fault; a conftest forcing exitstatus=0 is
# still F_EXIT_XML_MISMATCH; a conftest failing for an unattributable reason
# (no head-only symbol involved) is F_NO_REPORT.
# ---------------------------------------------------------------------------


def test_conftest_absent_symbol_is_absence_only(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/core.py", "def old():\n    return 1\n")
    _write(repo, "tests/test_c.py", "def test_c():\n    assert True\n")
    base = _commit(repo, "no new_func yet")
    _write(repo, "pkg/core.py", "def old():\n    return 1\n\n\ndef new_func():\n    return 5\n")
    _write(repo, "tests/conftest.py", "from pkg.core import new_func\n")
    head = _commit(repo, "add new_func and a conftest that imports it")

    result = _run_one(repo, base, head, "tests/test_c.py::test_c")
    assert _labels(result) == {"absence_only"}


def test_conftest_forced_exit_zero_is_exit_xml_mismatch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/core.py", "def f():\n    return 1\n")
    base = _commit(repo, "buggy implementation")
    _write(repo, "pkg/core.py", "def f():\n    return 2\n")
    _write(
        repo,
        "tests/conftest.py",
        "def pytest_sessionfinish(session, exitstatus):\n    session.exitstatus = 0\n",
    )
    _write(repo, "tests/test_d.py", _TEST_D)
    head = _commit(repo, "fix the bug and force exitstatus to 0")

    result = _run_one(repo, base, head, "tests/test_d.py::test_d")
    assert _labels(result) == {"fault:F_EXIT_XML_MISMATCH"}


def test_conftest_unattributable_failure_is_no_report(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "tests/conftest.py", "raise RuntimeError('boom')\n")
    _write(repo, "tests/test_c.py", "def test_c():\n    assert True\n")
    base = _commit(repo, "a conftest that always fails to load, for an unrelated reason")
    _write(repo, "README.md", "unrelated change\n")
    head = _commit(repo, "unrelated change")

    result = _run_one(repo, base, head, "tests/test_c.py::test_c")
    assert _labels(result) == {"fault:F_NO_REPORT"}


# ---------------------------------------------------------------------------
# Item 5: F_FLAKY must compare per-case results, not the synthesized verdict --
# two repeats can synthesize to the same base verdict ("at least one case
# failed") while disagreeing about *which* parametrized case failed.
# ---------------------------------------------------------------------------


def test_flaky_masked_by_verdict_synthesis_is_still_caught(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/core.py", "def f():\n    return 1\n")
    base = _commit(repo, "buggy implementation")
    _write(repo, "pkg/core.py", "def f():\n    return 2\n")
    _write(
        repo,
        "tests/test_f.py",
        textwrap.dedent(
            """
            import pytest
            from pathlib import Path
            from pkg.core import f


            @pytest.mark.parametrize("i", [0, 1])
            def test_f(i):
                if f() == 2:
                    return
                p = Path(__file__).parent / "cnt.txt"
                n = int(p.read_text()) if p.exists() else 0
                if i == 1:
                    p.write_text(str(n + 1))
                assert i != n % 2
            """
        ),
    )
    head = _commit(repo, "fix the bug and add a parametrized test")

    result = _run_one(repo, base, head, "tests/test_f.py::test_f")
    assert _labels(result) == {"fault:F_FLAKY"}


# ---------------------------------------------------------------------------
# Item 7: an empty canary list -- nothing declared, nothing detected -- must
# itself fault, not run unguarded.
# ---------------------------------------------------------------------------


def test_empty_canary_list_faults(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)  # deliberately no canary_pkg: nothing to discover
    _write(repo, "data/mod.txt", "not a module\n")
    base = _commit(repo, "no importable module anywhere")
    # The test imports nothing, so no test-imported module joins the canary list.
    _write(repo, "tests/test_e.py", "def test_e():\n    assert True\n")
    head = _commit(repo, "add a test")

    result = _run_one(repo, base, head, "tests/test_e.py::test_e")
    assert _labels(result) == {"fault:F_ENV_IMPORT"}
    assert result["fbpa"]["import_canary"] == {"base": {}, "head": {}}


# ---------------------------------------------------------------------------
# Item 8: canary false positives -- "import failed at base" (a package head
# adds) must not fault; a namespace package's __file__ is None, so __path__
# must be used, both for a genuinely-fine resolution and for detecting a
# namespace package whose contributions are *not* all inside the worktree.
# ---------------------------------------------------------------------------


def test_new_head_package_not_found_at_base_does_not_fault(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "tests/test_g.py", "def test_g():\n    assert True\n")
    base = _commit(repo, "canary package only, no newpkg yet")
    _write(repo, "newpkg/__init__.py", "")
    head = _commit(repo, "head adds a brand new package")

    result = _run_one(repo, base, head, "tests/test_g.py::test_g")
    assert _labels(result) == {"base_passes"}
    canary = result["fbpa"]["import_canary"]
    assert canary["base"]["newpkg"] == {"not_found": True}
    assert canary["head"]["newpkg"]["path"] == "newpkg/__init__.py"


def test_namespace_package_canary_resolves_via_path(tmp_path: Path) -> None:
    """A genuine (undecoyed) namespace package must resolve "ok" via __path__."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "nspkg/core.py", "def f():\n    return 1\n")  # no __init__.py: namespace pkg
    _write(repo, "tests/test_ns.py", _TEST_NS)
    base = _commit(repo, "namespace package")
    _write(repo, "README.md", "unrelated change\n")
    head = _commit(repo, "unrelated change")

    result = _run_one(repo, base, head, "tests/test_ns.py::test_ns", import_canary=["nspkg"])
    assert _labels(result) == {"base_passes"}
    canary = result["fbpa"]["import_canary"]
    assert canary["base"]["nspkg"]["path"] == "nspkg"
    assert canary["head"]["nspkg"]["path"] == "nspkg"


def test_namespace_package_canary_detects_outside_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A namespace package merges contributions; a decoy contribution must still fault."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "nspkg/core.py", "def f():\n    return 1\n")
    _write(repo, "tests/test_ns.py", _TEST_NS)
    base = _commit(repo, "namespace package")
    _write(repo, "README.md", "unrelated change\n")
    head = _commit(repo, "unrelated change")

    decoy = tmp_path / "decoy"
    _write(decoy, "nspkg/other.py", "")
    monkeypatch.setenv("PYTHONPATH", str(decoy))

    result = _run_one(repo, base, head, "tests/test_ns.py::test_ns", import_canary=["nspkg"])
    assert _labels(result) == {"fault:F_ENV_IMPORT"}


# ---------------------------------------------------------------------------
# Item 12: a characterizes claim must never run base -- a hanging/broken base
# must not fault a claim that never asked base a question.
# ---------------------------------------------------------------------------


def test_characterizes_intent_never_runs_base(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/core.py", "def f():\n    while True:\n        pass\n")
    base = _commit(repo, "base hangs forever")
    _write(repo, "pkg/core.py", "def f():\n    return 2\n")
    _write(repo, "tests/test_n.py", _TEST_N)
    head = _commit(repo, "head is fine")

    result = _run_one(
        repo,
        base,
        head,
        "tests/test_n.py::test_n",
        intent="characterizes",
        limits={"memory_max": "256M", "timeout_s": 5, "repeats": 1},
    )
    assert _labels(result) == {"no_finding"}


# ---------------------------------------------------------------------------
# Item 1: auto_discover must diff base's AST from the base *commit* (via
# ``git show``), not from the worktree -- by the time auto-discovery runs,
# the worktree's base copy of every test file has already been overlaid with
# head's, so comparing against the worktree would always see "no change".
# ---------------------------------------------------------------------------


def test_auto_discover_finds_added_and_modified_tests(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/core.py", "def f():\n    return 2\n")
    base = _commit(repo, "initial implementation")
    _write(
        repo,
        "tests/test_l.py",
        textwrap.dedent(
            """
            from pkg.core import f


            class TestA:
                def test_m(self):
                    assert f() == 2

            class TestB:
                def test_m(self):
                    assert True
            """
        ),
    )
    head = _commit(repo, "add two tests in two classes, same method name")

    result = _run_fbpa(
        repo, base=base, head=head, claims=[], auto_discover=True, limits=FAST_LIMITS
    )
    paths = {check["path"] for check in result["checks"]}
    assert paths == {"tests/test_l.py::TestA::test_m", "tests/test_l.py::TestB::test_m"}
    assert result["fbpa"]["in_scope"] == 2


# ---------------------------------------------------------------------------
# Per-item coverage self-check (spec section 6, final paragraph)
# ---------------------------------------------------------------------------

# name -> (expected §3.4 components, expected finding_type values). Every
# control's triggered sets must equal these (==, never in).
_EXPECTED: dict[str, tuple[set[str], set[str]]] = {
    "positive": ({"demonstrated"}, set()),
    "negative1": ({"base_passes"}, {"fbpa-base-passes"}),
    "negative2": ({"absence_only"}, {"fbpa-absence-only"}),
    "negative3": ({"head_not_passing"}, {"fbpa-head-not-passing"}),
    "negative4": ({"no_finding"}, set()),
    "inconclusive": ({"inconclusive:b_skip"}, {"fbpa-inconclusive"}),
    "fault1": ({"fault:F_RUNNER"}, {"fbpa-fault"}),
    "fault2": ({"fault:F_RUNNER"}, {"fbpa-fault"}),
    "fault2b": ({"fault:F_NOT_COLLECTED"}, {"fbpa-fault"}),
    "inconclusive_collateral": ({"inconclusive:b_collateral"}, {"fbpa-inconclusive"}),
    "inconclusive_setup_error": ({"inconclusive:b_setup_error"}, {"fbpa-inconclusive"}),
    "inconclusive_unattributed": ({"inconclusive:unattributed"}, {"fbpa-inconclusive"}),
    "inconclusive_no_impl_change": ({"inconclusive:no_impl_change"}, {"fbpa-inconclusive"}),
    "fault3": ({"fault:F_TIMEOUT"}, {"fbpa-fault"}),
    "fault4": ({"fault:F_OOM"}, {"fbpa-fault"}),
    "fault5": ({"fault:F_ENV_IMPORT"}, {"fbpa-fault"}),
    "fault6": ({"fault:F_FLAKY"}, {"fbpa-fault"}),
    "conftest_exit_mismatch": ({"fault:F_EXIT_XML_MISMATCH"}, {"fbpa-fault"}),
    "conftest_no_report": ({"fault:F_NO_REPORT"}, {"fbpa-fault"}),
    "auto_advisory": ({"base_passes"}, {"fbpa-base-passes"}),
}

# name -> the §4.1 bucket its single claim must land in.
_EXPECTED_BUCKETS: dict[str, str] = {
    "positive": "demonstrated",
    "negative1": "base_passes",
    "negative2": "absence_only",
    "negative3": "head_not_passing",
    "negative4": "no_finding",
    "inconclusive": "inconclusive",
    "fault1": "fault",
    "fault2": "fault",
    "fault2b": "fault",
    "inconclusive_collateral": "inconclusive",
    "inconclusive_setup_error": "inconclusive",
    "inconclusive_unattributed": "inconclusive",
    "inconclusive_no_impl_change": "inconclusive",
    "fault3": "fault",
    "fault4": "fault",
    "fault5": "fault",
    "fault6": "fault",
    "conftest_exit_mismatch": "fault",
    "conftest_no_report": "fault",
    "auto_advisory": "base_passes",
}


def _finding_types(result: dict[str, Any]) -> set[str]:
    return {f["finding_type"] for f in result["findings"] if f["finding_id"].startswith("fbpa-")}


def test_coverage_self_check(tmp_path: Path) -> None:
    from validity_audit.fbpa import FINDING_TYPES

    results: dict[str, dict[str, Any]] = {}

    repo = tmp_path / "positive"
    _init_canary_repo(repo)
    _write(repo, "mathy.py", _MATHY_BUGGY)
    base = _commit(repo, "off-by-one bug")
    _write(repo, "mathy.py", _MATHY_FIXED)
    _write(repo, "tests/test_mathy.py", _TEST_MATHY)
    head = _commit(repo, "fix")
    results["positive"] = _run_one(repo, base, head, "tests/test_mathy.py::test_inc")

    repo = tmp_path / "negative1"
    _init_canary_repo(repo)
    _write(repo, "util.py", _UTIL_NOOP)
    base = _commit(repo, "initial util")
    _write(repo, "tests/test_util.py", _TEST_UTIL)
    head = _commit(repo, "weak test")
    results["negative1"] = _run_one(repo, base, head, "tests/test_util.py::test_noop")

    repo = tmp_path / "negative2"
    _init_canary_repo(repo)
    _write(repo, "extra.py", _EXTRA_STUB)
    base = _commit(repo, "no helper")
    _write(repo, "extra.py", _EXTRA_HELPER)
    _write(repo, "tests/test_extra.py", _TEST_EXTRA)
    head = _commit(repo, "add helper")
    results["negative2"] = _run_one(repo, base, head, "tests/test_extra.py::test_extra")

    repo = tmp_path / "negative3"
    _init_canary_repo(repo)
    _write(repo, "mathy.py", _MATHY_BUGGY)
    base = _commit(repo, "off-by-one bug")
    _write(repo, "tests/test_mathy.py", _TEST_MATHY)
    head = _commit(repo, "add a test without fixing")
    results["negative3"] = _run_one(repo, base, head, "tests/test_mathy.py::test_inc")

    repo = tmp_path / "negative4"
    _init_canary_repo(repo)
    _write(repo, "stable.py", _STABLE)
    base = _commit(repo, "stable behaviour")
    _write(repo, "tests/test_stable.py", _TEST_STABLE)
    head = _commit(repo, "characterization test")
    results["negative4"] = _run_one(
        repo, base, head, "tests/test_stable.py::test_answer", intent="characterizes"
    )

    # A real inconclusive: the claimed test skips at base and passes at head.
    repo = tmp_path / "inconclusive"
    _init_canary_repo(repo)
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/core.py", "def f():\n    return 1\n")
    base = _commit(repo, "buggy")
    _write(repo, "pkg/core.py", "def f():\n    return 2\n")
    _write(repo, "tests/test_m.py", _TEST_SKIPS_AT_BASE)
    head = _commit(repo, "fix, test skips at base")
    results["inconclusive"] = _run_one(repo, base, head, "tests/test_m.py::test_m")

    repo = tmp_path / "fault1"
    _init_canary_repo(repo)
    _write(repo, "tests/test_broken.py", _TEST_PLACEHOLDER_OK)
    base = _commit(repo, "valid")
    _write(repo, "tests/test_broken.py", _TEST_PLACEHOLDER_BAD)
    head = _commit(repo, "syntax error")
    results["fault1"] = _run_one(repo, base, head, "tests/test_broken.py::test_placeholder")

    repo = tmp_path / "fault2"
    _init_canary_repo(repo)
    _write(repo, "tests/test_real.py", _TEST_REAL)
    base = _commit(repo, "one real test")
    _write(repo, "README.md", "x\n")
    head = _commit(repo, "unrelated")
    results["fault2"] = _run_one(repo, base, head, "tests/test_real.py::test_does_not_exist")

    # F_NOT_COLLECTED: the node id exists in the file but pytest does not collect
    # it at head (a conftest deselects everything; exit 5).
    repo = tmp_path / "fault2b"
    _init_canary_repo(repo)
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/core.py", "def q():\n    return 1\n")
    base = _commit(repo, "valid")
    _write(repo, "pkg/core.py", "def q():\n    return 1  # touched\n")
    _write(repo, "tests/test_q.py", _TEST_Q)
    _write(
        repo,
        "tests/conftest.py",
        "def pytest_collection_modifyitems(config, items):\n    items.clear()\n",
    )
    head = _commit(repo, "a conftest that deselects every test")
    results["fault2b"] = _run_one(repo, base, head, "tests/test_q.py::test_q")

    # inconclusive:b_collateral -- the module's failing import is not this test's.
    repo = tmp_path / "inconclusive_collateral"
    _init_canary_repo(repo)
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/mod.py", "def a():\n    return 1\n")
    base = _commit(repo, "base")
    _write(repo, "pkg/mod.py", "def a():\n    return 1\ndef b():\n    return 2\n")
    _write(
        repo,
        "tests/test_p.py",
        "from pkg.mod import a, b\n\n\ndef test_a():\n    assert a() == 1\n",
    )
    head = _commit(repo, "head")
    results["inconclusive_collateral"] = _run_one(repo, base, head, "tests/test_p.py::test_a")

    # inconclusive:b_setup_error -- a fixture raises at base for a non-absence reason.
    repo = tmp_path / "inconclusive_setup_error"
    _init_canary_repo(repo)
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/core.py", "def make():\n    raise RuntimeError('broken')\n")
    base = _commit(repo, "base")
    _write(repo, "pkg/core.py", "def make():\n    return 2\n")
    _write(
        repo,
        "tests/test_s.py",
        "import pytest\nfrom pkg.core import make\n\n\n@pytest.fixture\ndef thing():\n"
        "    return make()\n\n\ndef test_s(thing):\n    assert thing == 2\n",
    )
    head = _commit(repo, "head")
    results["inconclusive_setup_error"] = _run_one(repo, base, head, "tests/test_s.py::test_s")

    # inconclusive:unattributed -- an ambiguous class name.
    repo = tmp_path / "inconclusive_unattributed"
    _init_canary_repo(repo)
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/a.py", "class Foo:\n    pass\n")
    _write(repo, "pkg/b.py", "class Foo:\n    pass\n")
    base = _commit(repo, "base")
    _write(repo, "pkg/a.py", "class Foo:\n    x = 1\n")
    _write(
        repo,
        "tests/test_amb.py",
        "from pkg.a import Foo\n\n\ndef test_amb():\n    assert Foo().x == 1\n",
    )
    head = _commit(repo, "head")
    results["inconclusive_unattributed"] = _run_one(repo, base, head, "tests/test_amb.py::test_amb")

    # inconclusive:no_impl_change -- base and head differ only in where they run.
    repo = tmp_path / "inconclusive_no_impl_change"
    _init_canary_repo(repo)
    _write(repo, "README.md", "a\n")
    base = _commit(repo, "base")
    _write(repo, "tests/test_w.py", _TEST_GIT_SUBJECT)
    head = _commit(repo, "a test-only change")
    results["inconclusive_no_impl_change"] = _run_one(repo, base, head, "tests/test_w.py::test_w")

    repo = tmp_path / "fault3"
    _init_canary_repo(repo)
    _write(repo, "tests/test_loop.py", _TEST_LOOP)
    base = _commit(repo, "infinite loop")
    _write(repo, "README.md", "x\n")
    head = _commit(repo, "unrelated")
    results["fault3"] = _run_one(
        repo,
        base,
        head,
        "tests/test_loop.py::test_loop",
        limits={"memory_max": "256M", "timeout_s": 5, "repeats": 2},
    )

    repo = tmp_path / "fault4"
    _init_canary_repo(repo)
    _write(repo, "tests/test_mem.py", _TEST_MEM)
    base = _commit(repo, "memory hungry")
    _write(repo, "README.md", "x\n")
    head = _commit(repo, "unrelated")
    results["fault4"] = _run_one(
        repo,
        base,
        head,
        "tests/test_mem.py::test_mem",
        limits={"memory_max": "64M", "timeout_s": 15, "repeats": 2},
    )

    repo = tmp_path / "fault5"
    _init_repo(repo)
    _write(repo, "lib/pkgname/__init__.py", "VALUE = 'worktree'\n")
    _write(repo, "tests/test_placeholder.py", _TEST_PLACEHOLDER_OK)
    base = _commit(repo, "worktree copy")
    _write(repo, "README.md", "x\n")
    head = _commit(repo, "unrelated")
    decoy = tmp_path / "fault5-decoy"
    _write(decoy, "pkgname/__init__.py", "VALUE = 'decoy'\n")
    old_pythonpath = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = str(decoy)
    try:
        results["fault5"] = _run_one(
            repo,
            base,
            head,
            "tests/test_placeholder.py::test_placeholder",
            import_canary=["pkgname"],
        )
    finally:
        if old_pythonpath is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = old_pythonpath

    repo = tmp_path / "fault6"
    _init_canary_repo(repo)
    _write(repo, "tests/test_flaky.py", _TEST_FLAKY)
    base = _commit(repo, "alternating outcome")
    _write(repo, "README.md", "x\n")
    head = _commit(repo, "unrelated")
    results["fault6"] = _run_one(repo, base, head, "tests/test_flaky.py::test_flaky_counter")

    repo = tmp_path / "conftest_exit_mismatch"
    _init_canary_repo(repo)
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/core.py", "def f():\n    return 1\n")
    base = _commit(repo, "buggy")
    _write(repo, "pkg/core.py", "def f():\n    return 2\n")
    _write(
        repo,
        "tests/conftest.py",
        "def pytest_sessionfinish(session, exitstatus):\n    session.exitstatus = 0\n",
    )
    _write(repo, "tests/test_d.py", _TEST_D)
    head = _commit(repo, "fix and force exit 0")
    results["conftest_exit_mismatch"] = _run_one(repo, base, head, "tests/test_d.py::test_d")

    repo = tmp_path / "conftest_no_report"
    _init_canary_repo(repo)
    _write(repo, "tests/conftest.py", "raise RuntimeError('boom')\n")
    _write(repo, "tests/test_c.py", "def test_c():\n    assert True\n")
    base = _commit(repo, "conftest always fails")
    _write(repo, "README.md", "x\n")
    head = _commit(repo, "unrelated")
    results["conftest_no_report"] = _run_one(repo, base, head, "tests/test_c.py::test_c")

    repo = tmp_path / "auto_advisory"
    _init_canary_repo(repo)
    _write(repo, "util2.py", "def noop():\n    return 1\n")
    base = _commit(repo, "initial util2")
    _write(repo, "tests/test_util2.py", _TEST_UTIL2)
    head = _commit(repo, "auto-discovered weak test")
    results["auto_advisory"] = _run_fbpa(
        repo, base=base, head=head, claims=[], auto_discover=True, limits=FAST_LIMITS
    )

    for name, (expected_components, expected_types) in _EXPECTED.items():
        result = results[name]
        assert _labels(result) == expected_components, name
        assert _finding_types(result) == expected_types, name
        verdicts = [c["verdict"] for c in result["checks"] if c["kind"] == "fbpa_claim"]
        assert verdicts == [_EXPECTED_BUCKETS[name]], name
        for finding in result["findings"]:
            assert finding["finding_type"] in FINDING_TYPES, name

    # The auto-discovered weak test is advisory, not a fail (spec §4 last row).
    auto_findings = results["auto_advisory"]["findings"]
    assert [(f["error_class"], f["severity"], f["reproduction"]) for f in auto_findings] == [
        ("fitness", "med", "reproduced")
    ]

    # Every F_* fault code, every finding_type and every §4.1 bucket is covered.
    all_labels = {label for labels, _ in _EXPECTED.values() for label in labels}
    covered_faults = {label.split(":", 1)[1] for label in all_labels if label.startswith("fault:")}
    assert covered_faults == FAULT_CODES
    covered_types = {t for _, types in _EXPECTED.values() for t in types}
    assert covered_types == FINDING_TYPES
    assert set(_EXPECTED_BUCKETS.values()) == {
        "demonstrated",
        "no_finding",
        "base_passes",
        "head_not_passing",
        "absence_only",
        "inconclusive",
        "fault",
    }
    assert set(_EXPECTED) == set(_EXPECTED_BUCKETS) == set(results)


# ---------------------------------------------------------------------------
# Full prepare/finalize path with a contract that uses the new field, for
# every §4.1 finding type (item 3/6): base-passes, head-not-passing, fault,
# inconclusive, absence-only, auto-advisory, each with its policy gate_effect.
# ---------------------------------------------------------------------------


def _round_trip(
    repo: Path,
    *,
    fbpa_claims: list[dict[str, Any]],
    base: str,
    head: str,
    auto_discover: bool = False,
    run_name: str,
    extra_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    import json

    fbpa_contract: dict[str, Any] = {
        "base": base,
        "head": head,
        "runner": "pytest",
        "claims": fbpa_claims,
        "limits": FAST_LIMITS,
    }
    if auto_discover:
        fbpa_contract["auto_discover"] = True
    contract = {
        "schema_version": "0.6.0",
        "task_id": run_name,
        "claims": [{"claim_id": "c1", "statement": "The repository's tests are trustworthy."}],
        "artifact_paths": ["notes.md"],
        "packs": ["docs"],
        "fail_before_pass_after": fbpa_contract,
        **(extra_contract or {}),
    }
    (repo / "task.json").write_text(json.dumps(contract), encoding="utf-8")

    prepare_run(
        workspace=repo,
        contract_path="task.json",
        run_dir=f".va/{run_name}",
        review_context="cold",
        reviewer_kind="model",
        reviewer_label="independent-reviewer",
        operator_id="operator-1",
        run_id=f"run-{run_name}",
        started_at="2026-10-04T00:00:00Z",
    )
    reviewer_output = {
        "schema_version": "0.3.0",
        "review_context": "cold",
        "reviewer": {"kind": "model", "label": "independent-reviewer"},
        "operator_id": "operator-1",
        "claim_results": [
            {
                "claim_id": "c1",
                "outcome": "supported",
                "evidence": [
                    {
                        "evidence_id": "review-evidence",
                        "kind": "note",
                        "description": "The artifact snapshot was inspected.",
                    }
                ],
                "finding_ids": [],
            }
        ],
        "findings": [],
        "summary": "Independent review completed.",
    }
    (repo / f"ro-{run_name}.json").write_text(json.dumps(reviewer_output), encoding="utf-8")
    (repo / f"tr-{run_name}.txt").write_bytes(b"Raw reviewer transcript.\n")
    finalize_run(
        workspace=repo,
        run_dir=f".va/{run_name}",
        reviewer_output_path=f"ro-{run_name}.json",
        transcript_path=f"tr-{run_name}.txt",
        completed_at="2026-10-04T00:05:00Z",
        issued_at="2026-10-04T00:06:00Z",
        attestation_id=f"attestation-{run_name}",
        append_ledger=False,
    )
    import json as _json

    return _json.loads((repo / f".va/{run_name}/attestation.json").read_text())


def test_prepare_finalize_path_surfaces_fbpa_finding(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "util.py", _UTIL_NOOP)
    base = _commit(repo, "initial util")
    _write(repo, "util.py", "def noop():\n    return 1  # unrelated touch\n")
    _write(repo, "tests/test_util.py", _TEST_UTIL)
    _write(repo, "notes.md", "# Notes\n\nNothing special.\n")
    head = _commit(repo, "unrelated change plus a weak claimed-fix test")

    attestation = _round_trip(
        repo,
        fbpa_claims=[{"test": "tests/test_util.py::test_noop", "intent": "fixes"}],
        base=base,
        head=head,
        run_name="base-passes",
    )
    fbpa_findings = [f for f in attestation["findings"] if f["finding_id"].startswith("fbpa-")]
    assert len(fbpa_findings) == 1
    finding = fbpa_findings[0]
    assert finding["error_class"] == "material_requirement_miss"
    assert finding["gate_effect"] == "fail"
    assert attestation["overall_result"]["status"] == "fail"
    assert finding["finding_type"] == "fbpa-base-passes"


def test_prepare_finalize_every_finding_type(tmp_path: Path) -> None:
    # head_not_passing -> fail
    repo = tmp_path / "hnp"
    _init_canary_repo(repo)
    _write(repo, "mathy.py", _MATHY_BUGGY)
    base = _commit(repo, "bug")
    _write(repo, "tests/test_mathy.py", _TEST_MATHY)
    _write(repo, "notes.md", "# n\n")
    head = _commit(repo, "test without fix")
    att = _round_trip(
        repo,
        fbpa_claims=[{"test": "tests/test_mathy.py::test_inc", "intent": "fixes"}],
        base=base,
        head=head,
        run_name="hnp",
    )
    findings = [f for f in att["findings"] if f["finding_id"].startswith("fbpa-")]
    assert findings[0]["gate_effect"] == "fail"
    assert att["overall_result"]["status"] == "fail"

    # fault -> needs_review (fail-closed, never a silent pass)
    repo = tmp_path / "fault"
    _init_canary_repo(repo)
    _write(repo, "tests/test_broken.py", _TEST_PLACEHOLDER_OK)
    base = _commit(repo, "valid")
    _write(repo, "tests/test_broken.py", _TEST_PLACEHOLDER_BAD)
    _write(repo, "notes.md", "# n\n")
    head = _commit(repo, "syntax error")
    att = _round_trip(
        repo,
        fbpa_claims=[{"test": "tests/test_broken.py::test_placeholder", "intent": "fixes"}],
        base=base,
        head=head,
        run_name="fault",
    )
    findings = [f for f in att["findings"] if f["finding_id"].startswith("fbpa-")]
    assert findings[0]["gate_effect"] == "none"
    assert att["overall_result"]["status"] == "needs_review"

    # inconclusive -> needs_review
    repo = tmp_path / "inconclusive"
    _init_canary_repo(repo)
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/core.py", "def f():\n    return 1\n")
    base = _commit(repo, "buggy")
    _write(repo, "pkg/core.py", "def f():\n    return 2\n")
    _write(
        repo,
        "tests/test_m.py",
        "import pytest\nfrom pkg.core import f\n\n\ndef test_m():\n"
        "    if f() == 1:\n        pytest.skip('x')\n    assert f() == 2\n",
    )
    _write(repo, "notes.md", "# n\n")
    head = _commit(repo, "fix, test skips at base")
    att = _round_trip(
        repo,
        fbpa_claims=[{"test": "tests/test_m.py::test_m", "intent": "fixes"}],
        base=base,
        head=head,
        run_name="inconclusive",
    )
    findings = [f for f in att["findings"] if f["finding_id"].startswith("fbpa-")]
    assert findings[0]["gate_effect"] == "none"
    assert att["overall_result"]["status"] == "needs_review"

    # absence_only -> advisory, pass
    repo = tmp_path / "absence"
    _init_canary_repo(repo)
    _write(repo, "extra.py", _EXTRA_STUB)
    base = _commit(repo, "no helper")
    _write(repo, "extra.py", _EXTRA_HELPER)
    _write(repo, "tests/test_extra.py", _TEST_EXTRA)
    _write(repo, "notes.md", "# n\n")
    head = _commit(repo, "add helper")
    att = _round_trip(
        repo,
        fbpa_claims=[{"test": "tests/test_extra.py::test_extra", "intent": "fixes"}],
        base=base,
        head=head,
        run_name="absence",
    )
    findings = [f for f in att["findings"] if f["finding_id"].startswith("fbpa-")]
    assert findings[0]["gate_effect"] == "advisory"
    assert att["overall_result"]["status"] == "pass"

    # auto_advisory (auto-discovered base_passes) -> advisory, pass
    repo = tmp_path / "auto"
    _init_canary_repo(repo)
    _write(repo, "util3.py", "def noop():\n    return 1\n")
    base = _commit(repo, "initial")
    _write(
        repo,
        "tests/test_util3.py",
        "from util3 import noop\n\n\ndef test_noop():\n    assert noop() == 1\n",
    )
    _write(repo, "notes.md", "# n\n")
    head = _commit(repo, "auto-discovered weak test")
    att = _round_trip(
        repo, fbpa_claims=[], base=base, head=head, auto_discover=True, run_name="auto"
    )
    findings = [f for f in att["findings"] if f["finding_id"].startswith("fbpa-")]
    assert findings[0]["error_class"] == "fitness"
    assert findings[0]["gate_effect"] == "advisory"
    assert att["overall_result"]["status"] == "pass"


# ---------------------------------------------------------------------------
# Round-2 review, item 1: scoped absence attribution (spec §3.1, amendment 2).
# Each of the six strawmen below was judged ``demonstrated`` by the unscoped
# bag-of-names attribution; each pre-fix failure comes only from a symbol head
# adds, so each must be ``absence_only``.
# ---------------------------------------------------------------------------


def _absence_strawman(
    tmp_path: Path, base_files: dict[str, str], head_files: dict[str, str], node_id: str
) -> dict[str, Any]:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    for rel, content in base_files.items():
        _write(repo, rel, textwrap.dedent(content))
    base = _commit(repo, "base")
    for rel, content in head_files.items():
        _write(repo, rel, textwrap.dedent(content))
    head = _commit(repo, "head")
    return _run_one(repo, base, head, node_id)


def test_strawman_method_name_collision_across_classes(tmp_path: Path) -> None:
    # Base already has Bar.reset; head adds Foo.reset. "reset" existing on some
    # other class at base must not make Foo().reset's absence a real failure.
    result = _absence_strawman(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/core.py": """
            class Foo:
                pass
            class Bar:
                def reset(self):
                    return 0
            """,
        },
        {
            "pkg/core.py": """
            class Foo:
                def reset(self):
                    return True
            class Bar:
                def reset(self):
                    return 0
            """,
            "tests/test_foo.py": """
            from pkg.core import Foo
            def test_reset():
                assert Foo().reset() is not None
            """,
        },
        "tests/test_foo.py::test_reset",
    )
    assert _labels(result) == {"absence_only"}
    assert result["checks"][0]["base_absent_target"] == "Foo.reset"


def test_strawman_local_variable_named_like_new_property(tmp_path: Path) -> None:
    result = _absence_strawman(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/core.py": """
            class Box:
                def __init__(self):
                    self._v = 1
            def other():
                value = 3
                return value
            """,
        },
        {
            "pkg/core.py": """
            class Box:
                def __init__(self):
                    self._v = 1
                @property
                def value(self):
                    return self._v
            def other():
                value = 3
                return value
            """,
            "tests/test_b.py": """
            from pkg.core import Box
            def test_value():
                assert Box().value == 1
            """,
        },
        "tests/test_b.py::test_value",
    )
    assert _labels(result) == {"absence_only"}


def test_strawman_new_dataclass_field(tmp_path: Path) -> None:
    result = _absence_strawman(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/core.py": """
            from dataclasses import dataclass
            @dataclass
            class R:
                a: int = 1
            """,
        },
        {
            "pkg/core.py": """
            from dataclasses import dataclass
            @dataclass
            class R:
                a: int = 1
                new_field: int = 0
            """,
            "tests/test_r.py": """
            from pkg.core import R
            def test_field():
                assert R().new_field >= 0
            """,
        },
        "tests/test_r.py::test_field",
    )
    assert _labels(result) == {"absence_only"}


def test_strawman_new_annotated_module_constant(tmp_path: Path) -> None:
    result = _absence_strawman(
        tmp_path,
        {"pkg/__init__.py": "", "pkg/core.py": "X = 1\n"},
        {
            "pkg/core.py": "X = 1\nLIMIT: int = 5\n",
            "tests/test_r.py": """
            from pkg import core
            def test_limit():
                assert core.LIMIT > 0
            """,
        },
        "tests/test_r.py::test_limit",
    )
    assert _labels(result) == {"absence_only"}


def test_strawman_new_function_reached_via_test_helper(tmp_path: Path) -> None:
    result = _absence_strawman(
        tmp_path,
        {"pkg/__init__.py": "", "pkg/core.py": "def old():\n    return 1\n"},
        {
            "pkg/core.py": "def old():\n    return 1\ndef newfn():\n    return 2\n",
            "tests/test_h.py": """
            from pkg import core
            def _call():
                return core.newfn()
            def test_h():
                assert _call() == 2
            """,
        },
        "tests/test_h.py::test_h",
    )
    assert _labels(result) == {"absence_only"}


def test_strawman_same_test_name_in_two_directories(tmp_path: Path) -> None:
    head_files = {"pkg/core.py": "def old():\n    return 1\ndef newfn():\n    return 2\n"}
    for d in ["aa", "bb", "cc", "dd", "zz"]:
        head_files[f"tests/{d}/test_{d}.py"] = (
            "from pkg import core\ndef test_same():\n    assert core.old() == 1\n"
        )
    head_files["tests/mm/test_mm.py"] = (
        "from pkg import core\ndef test_same():\n    assert core.newfn() == 2\n"
    )
    result = _absence_strawman(
        tmp_path,
        {"pkg/__init__.py": "", "pkg/core.py": "def old():\n    return 1\n"},
        head_files,
        "tests/mm/test_mm.py::test_same",
    )
    assert _labels(result) == {"absence_only"}


def test_setup_phase_absence_is_absence_only(tmp_path: Path) -> None:
    result = _absence_strawman(
        tmp_path,
        {"pkg/__init__.py": "", "pkg/core.py": "def old():\n    return 1\n"},
        {
            "pkg/core.py": "def old():\n    return 1\ndef make_thing():\n    return 2\n",
            "tests/test_s.py": """
            import pytest
            from pkg import core
            @pytest.fixture
            def thing():
                return core.make_thing()
            def test_s(thing):
                assert thing == 2
            """,
        },
        "tests/test_s.py::test_s",
    )
    assert _labels(result) == {"absence_only"}
    assert result["checks"][0]["base_cases"] == [
        {
            "name": "test_s",
            "outcome": "error",
            "phase": "setup",
            "exc_type": "AttributeError",
            "first_failure_line": "AttributeError: module 'pkg.core' has no attribute 'make_thing'",
        }
    ]


def test_aliased_import_collection_error_is_absence_only(tmp_path: Path) -> None:
    result = _absence_strawman(
        tmp_path,
        {"pkg/__init__.py": "", "pkg/core.py": "def old():\n    return 1\n"},
        {
            "pkg/core.py": "def old():\n    return 1\ndef newfn():\n    return 2\n",
            "tests/test_c.py": """
            from pkg.core import newfn as nf
            def test_c():
                assert nf() == 2
            """,
        },
        "tests/test_c.py::test_c",
    )
    assert _labels(result) == {"absence_only"}


def test_existing_symbol_attribute_error_still_counts_as_failing(tmp_path: Path) -> None:
    # The scoped lookup must not over-correct: an AttributeError on a symbol
    # that exists at base (here on None) is a behavioural failure.
    result = _absence_strawman(
        tmp_path,
        {"pkg/__init__.py": "", "pkg/core.py": "def find():\n    return None\n"},
        {
            "pkg/core.py": "class Hit:\n    name = 'x'\ndef find():\n    return Hit()\n",
            "tests/test_f.py": """
            from pkg.core import find
            def test_find():
                assert find().name == 'x'
            """,
        },
        "tests/test_f.py::test_find",
    )
    assert _labels(result) == {"demonstrated"}


def test_ambiguous_class_name_is_unattributed(tmp_path: Path) -> None:
    # Two project classes named Foo; head adds ``x`` to only one of them, so the
    # message "'Foo' object has no attribute 'x'" cannot be attributed.
    result = _absence_strawman(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/a.py": "class Foo:\n    pass\n",
            "pkg/b.py": "class Foo:\n    pass\n",
        },
        {
            "pkg/a.py": "class Foo:\n    x = 1\n",
            "tests/test_amb.py": """
            from pkg.a import Foo
            def test_amb():
                assert Foo().x == 1
            """,
        },
        "tests/test_amb.py::test_amb",
    )
    assert _labels(result) == {"inconclusive:unattributed"}
    assert _finding_types(result) == {"fbpa-inconclusive"}


# ---------------------------------------------------------------------------
# Round-2 review, item 2: the test file and function come from the node id
# (file, then class), never from a search by bare function name.
# ---------------------------------------------------------------------------


def test_collection_reference_check_uses_node_id_class(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/core.py", "def old():\n    return 1\n")
    base = _commit(repo, "no newfn yet")
    _write(repo, "pkg/core.py", "def old():\n    return 1\ndef newfn():\n    return 2\n")
    _write(
        repo,
        "tests/test_k.py",
        textwrap.dedent(
            """
            from pkg.core import newfn


            class TestA:
                def test_m(self):
                    assert newfn() == 2


            class TestB:
                def test_m(self):
                    assert True
            """
        ),
    )
    head = _commit(repo, "add newfn; only TestA uses it")
    result = _run_fbpa(
        repo,
        base=base,
        head=head,
        claims=[
            {"test": "tests/test_k.py::TestA::test_m", "intent": "fixes"},
            {"test": "tests/test_k.py::TestB::test_m", "intent": "fixes"},
        ],
        limits=FAST_LIMITS,
    )
    by_path = {c["path"]: c["components"] for c in result["checks"]}
    assert by_path == {
        "tests/test_k.py::TestA::test_m": ["absence_only"],
        "tests/test_k.py::TestB::test_m": ["inconclusive:b_collateral"],
    }


# ---------------------------------------------------------------------------
# Round-2 review, item 3: a test that ignores SIGTERM must still end as
# F_TIMEOUT, with no leftover pytest process and no leftover worktree. The
# probe runs in a child process with its own deadline so a regression fails
# this test instead of hanging the suite.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_sigterm_ignoring_test_times_out_and_cleans_up(tmp_path: Path) -> None:
    import json
    import signal
    import sys
    import uuid

    marker = f"test_ignores_sigterm_{uuid.uuid4().hex[:12]}"
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(
        repo,
        "tests/test_t.py",
        "import signal, time\n\n\n"
        f"def {marker}():\n"
        "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "    while True:\n"
        "        time.sleep(0.1)\n",
    )
    base = _commit(repo, "a test that ignores SIGTERM")
    _write(repo, "README.md", "x\n")
    head = _commit(repo, "unrelated")
    contract = {
        "fail_before_pass_after": {
            "base": base,
            "head": head,
            "runner": "pytest",
            "claims": [{"test": f"tests/test_t.py::{marker}", "intent": "fixes"}],
            "limits": {"memory_max": "256M", "timeout_s": 3, "repeats": 1},
        }
    }
    script = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "from validity_audit.probes import run_probes\n"
        "contract = json.loads(sys.argv[2])\n"
        "result = run_probes(Path(sys.argv[1]), [], contract=contract)\n"
        "print(json.dumps(result['checks']))\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT)
    proc = subprocess.Popen(
        [sys.executable, "-c", script, str(repo), json.dumps(contract)],
        cwd=_REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    hung = False
    try:
        stdout, _stderr = proc.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        hung = True
        os.killpg(proc.pid, signal.SIGKILL)
        stdout, _stderr = proc.communicate()
    leftovers = subprocess.run(
        ["pgrep", "-f", marker], capture_output=True, text=True, check=False
    ).stdout.split()
    if leftovers:
        subprocess.run(["pkill", "-9", "-f", marker], check=False)
    worktrees = subprocess.run(
        ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert not hung, "the probe hung on a SIGTERM-ignoring test"
    assert leftovers == []
    assert worktrees.count("worktree ") == 1
    checks = json.loads(stdout)
    assert [c["components"] for c in checks if c["kind"] == "fbpa_claim"] == [["fault:F_TIMEOUT"]]


# ---------------------------------------------------------------------------
# Round-2 review, item 4: auto_discover follows pytest's default collection
# rules, and every non-demonstrated auto-discovered result is advisory.
# ---------------------------------------------------------------------------


def test_auto_discover_follows_pytest_collection_and_is_advisory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/core.py", "def f():\n    return 1\n")
    _write(repo, "tests/test_a.py", "def test_a():\n    assert True\n")
    base = _commit(repo, "base")
    _write(
        repo,
        "tests/conftest.py",
        "import pytest\n\n\n@pytest.fixture\ndef test_repo():\n    return 1\n",
    )
    _write(repo, "tests/helpers.py", "def test_helper_data():\n    return 1\n")
    _write(
        repo,
        "tests/test_a.py",
        textwrap.dedent(
            """
            import sys, pytest


            def test_a():
                assert True


            @pytest.mark.skipif(sys.platform == "linux", reason="not on linux")
            def test_platform():
                assert True


            @pytest.fixture
            def test_fixture_named_like_a_test():
                return 1


            class Helper:
                def test_x(self):
                    assert True


            class TestWithInit:
                def __init__(self):
                    pass

                def test_y(self):
                    assert True
            """
        ),
    )
    head = _commit(repo, "head: noise pytest does not collect, plus a test that skips")
    result = _run_fbpa(
        repo, base=base, head=head, claims=[], auto_discover=True, limits=FAST_LIMITS
    )
    assert [c["path"] for c in result["checks"]] == ["tests/test_a.py::test_platform"]
    assert _labels(result) == {"head_not_passing"}
    assert [(f["error_class"], f["severity"], f["reproduction"]) for f in result["findings"]] == [
        ("fitness", "med", "reproduced")
    ]
    assert result["checks"][0]["status"] == "advisory"


def test_auto_mode_all_timeout_needs_review(tmp_path: Path) -> None:
    # Spec §4: an environment-level fault (here F_TIMEOUT) is never downgraded,
    # auto_discover mode included.
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "README.md", "base\n")
    base = _commit(repo, "base")
    _write(repo, "tests/test_loop.py", _TEST_LOOP)
    head = _commit(repo, "auto-discovered test that loops forever")
    result = _run_fbpa(
        repo,
        base=base,
        head=head,
        claims=[],
        auto_discover=True,
        limits={"memory_max": "256M", "timeout_s": 3, "repeats": 1},
    )
    assert _labels(result) == {"fault:F_TIMEOUT"}
    assert [(f["error_class"], f["severity"], f["reproduction"]) for f in result["findings"]] == [
        ("material_requirement_miss", "high", "not_reproducible")
    ]
    assert [f["finding_type"] for f in result["findings"]] == ["fbpa-fault"]


def test_auto_mode_canary_outside_worktree_needs_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "lib/pkgname/__init__.py", "")
    _write(repo, "README.md", "base\n")
    base = _commit(repo, "base")
    _write(repo, "tests/test_x.py", "def test_x():\n    assert True\n")
    head = _commit(repo, "auto-discovered test")
    decoy = tmp_path / "decoy"
    _write(decoy, "pkgname/__init__.py", "")
    monkeypatch.setenv("PYTHONPATH", str(decoy))
    result = _run_fbpa(
        repo,
        base=base,
        head=head,
        claims=[],
        auto_discover=True,
        limits=FAST_LIMITS,
        import_canary=["pkgname"],
    )
    assert _labels(result) == {"fault:F_ENV_IMPORT"}
    assert [(f["error_class"], f["severity"], f["reproduction"]) for f in result["findings"]] == [
        ("material_requirement_miss", "high", "not_reproducible")
    ]


def test_auto_mode_flaky_is_advisory_but_nothing_judged_needs_review(tmp_path: Path) -> None:
    # F_FLAKY on an auto-discovered test is test-level (advisory, and not a
    # measurement, so not "reproduced"); with nothing judged, the run as a
    # whole still needs review (spec §4).
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "README.md", "base\n")
    base = _commit(repo, "base")
    _write(repo, "tests/test_flaky.py", _TEST_FLAKY)
    head = _commit(repo, "auto-discovered flaky test")
    result = _run_fbpa(
        repo, base=base, head=head, claims=[], auto_discover=True, limits=FAST_LIMITS
    )
    assert _labels(result) == {"fault:F_FLAKY"}
    assert [
        (f["finding_type"], f["error_class"], f["severity"], f["reproduction"])
        for f in result["findings"]
    ] == [
        ("fbpa-fault", "fitness", "med", "not_reproducible"),
        ("fbpa-inconclusive", "material_requirement_miss", "high", "not_reproducible"),
    ]
    assert result["fbpa"]["judged"] == 0


# ---------------------------------------------------------------------------
# Round-2 review, item 6: the stored per-case record carries the effective
# exception type and phase, and F_FLAKY sees a varying exception type.
# ---------------------------------------------------------------------------


def test_case_record_stores_exception_type_and_phase(tmp_path: Path) -> None:
    result = _absence_strawman(
        tmp_path,
        {"pkg/__init__.py": "", "pkg/core.py": "def f(x):\n    return x['k']\n"},
        {
            "pkg/core.py": "def f(x):\n    return x.get('k', 0)\n",
            "tests/test_f.py": "from pkg.core import f\ndef test_f():\n    assert f({}) == 0\n",
        },
        "tests/test_f.py::test_f",
    )
    assert _labels(result) == {"demonstrated"}
    assert result["checks"][0]["base_cases"] == [
        {
            "name": "test_f",
            "outcome": "failure",
            "phase": "call",
            "exc_type": "KeyError",
            "first_failure_line": "KeyError: 'k'",
        }
    ]


def test_flaky_exception_type_is_caught(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(
        repo,
        "tests/test_x.py",
        "from pathlib import Path\n\n\n"
        "def test_x():\n"
        "    p = Path(__file__).parent / 'n.txt'\n"
        "    n = int(p.read_text()) if p.exists() else 0\n"
        "    p.write_text(str(n + 1))\n"
        "    if n % 2 == 0:\n"
        "        raise ValueError('a')\n"
        "    raise TypeError('b')\n",
    )
    base = _commit(repo, "a test whose exception type alternates")
    _write(repo, "README.md", "x\n")
    head = _commit(repo, "unrelated")
    result = _run_one(repo, base, head, "tests/test_x.py::test_x")
    assert _labels(result) == {"fault:F_FLAKY"}


# ---------------------------------------------------------------------------
# Round-2 review, item 7: FbpaError maps onto the CLI exit-code contract.
# ---------------------------------------------------------------------------


def _cli_contract(repo: Path, base: str, head: str) -> None:
    import json

    contract = {
        "schema_version": "0.6.0",
        "task_id": "cli-fbpa",
        "claims": [{"claim_id": "c1", "statement": "The tests are trustworthy."}],
        "artifact_paths": ["notes.md"],
        "packs": ["docs"],
        "fail_before_pass_after": {
            "base": base,
            "head": head,
            "runner": "pytest",
            "claims": [{"test": "tests/test_util.py::test_noop", "intent": "fixes"}],
            "limits": FAST_LIMITS,
        },
    }
    (repo / "task.json").write_text(json.dumps(contract), encoding="utf-8")


def _cli_prepare_args(repo: Path) -> list[str]:
    return [
        "prepare",
        "--workspace",
        str(repo),
        "--contract",
        "task.json",
        "--run-dir",
        ".va/cli",
        "--review-context",
        "cold",
        "--reviewer-kind",
        "model",
        "--reviewer-label",
        "independent-reviewer",
        "--operator-id",
        "operator-1",
        "--run-id",
        "run-cli",
        "--started-at",
        "2026-10-04T00:00:00Z",
    ]


def test_cli_prepare_with_missing_base_commit_is_operational_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from validity_audit.cli import EXIT_OPERATIONAL_ERROR, main

    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "notes.md", "# n\n")
    _write(repo, "util.py", _UTIL_NOOP)
    _write(repo, "tests/test_util.py", _TEST_UTIL)
    head = _commit(repo, "head")
    _cli_contract(repo, "0" * 40, head)
    with pytest.raises(SystemExit) as excinfo:
        main(_cli_prepare_args(repo))
    assert excinfo.value.code == EXIT_OPERATIONAL_ERROR
    assert "fail_before_pass_after probe could not run" in capsys.readouterr().err


def test_cli_finalize_when_fbpa_cannot_rerun_is_evidence_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    from validity_audit import runtime
    from validity_audit.cli import EXIT_EVIDENCE_MISMATCH, main
    from validity_audit.fbpa import FbpaError

    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "notes.md", "# n\n")
    _write(repo, "util.py", _UTIL_NOOP)
    base = _commit(repo, "base")
    _write(repo, "tests/test_util.py", _TEST_UTIL)
    head = _commit(repo, "head")
    _cli_contract(repo, base, head)
    assert main(_cli_prepare_args(repo)) == 0
    capsys.readouterr()

    def _gone(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise FbpaError("could not create a base worktree")

    monkeypatch.setattr(runtime, "run_probes", _gone)
    reviewer_output = {
        "schema_version": "0.3.0",
        "review_context": "cold",
        "reviewer": {"kind": "model", "label": "independent-reviewer"},
        "operator_id": "operator-1",
        "claim_results": [
            {
                "claim_id": "c1",
                "outcome": "supported",
                "evidence": [{"evidence_id": "e", "kind": "note", "description": "Looked."}],
                "finding_ids": [],
            }
        ],
        "findings": [],
        "summary": "Done.",
    }
    (repo / "ro.json").write_text(json.dumps(reviewer_output), encoding="utf-8")
    (repo / "tr.txt").write_bytes(b"transcript\n")
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "finalize",
                "--workspace",
                str(repo),
                "--run-dir",
                ".va/cli",
                "--reviewer-output",
                "ro.json",
                "--transcript",
                "tr.txt",
                "--no-ledger",
            ]
        )
    assert excinfo.value.code == EXIT_EVIDENCE_MISMATCH


# ---------------------------------------------------------------------------
# Round-2 review, item 8: report order does not depend on claim order or on
# filesystem iteration order.
# ---------------------------------------------------------------------------


def test_report_is_independent_of_claim_order(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "util.py", _UTIL_NOOP)
    _write(repo, "mathy.py", _MATHY_BUGGY)
    base = _commit(repo, "base")
    _write(repo, "mathy.py", _MATHY_FIXED)
    _write(repo, "tests/test_mathy.py", _TEST_MATHY)
    _write(repo, "tests/test_util.py", _TEST_UTIL)
    head = _commit(repo, "head")
    claims = [
        {"test": "tests/test_util.py::test_noop", "intent": "fixes"},
        {"test": "tests/test_mathy.py::test_inc", "intent": "fixes"},
    ]
    forward = _run_fbpa(repo, base=base, head=head, claims=claims, limits=FAST_LIMITS)
    backward = _run_fbpa(repo, base=base, head=head, claims=claims[::-1], limits=FAST_LIMITS)
    assert forward == backward
    assert [c["path"] for c in forward["checks"]] == sorted(c["test"] for c in claims)


def test_list_files_is_sorted(tmp_path: Path) -> None:
    from validity_audit.fbpa import _list_files

    for name in ["zz/b.py", "aa/c.py", "mm/a.py", "a.py", "zz/a/x.py"]:
        _write(tmp_path, name, "")
    assert _list_files(tmp_path) == sorted(_list_files(tmp_path))


# ---------------------------------------------------------------------------
# Round-2 review, item 10: an empty scope is never clean, and the canary runs
# under the memory limit.
# ---------------------------------------------------------------------------


def test_no_claims_in_scope_is_not_clean(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "tests/test_real.py", _TEST_REAL)
    base = _commit(repo, "base")
    _write(repo, "tests/test_real.py", "def test_real():\n    assert 1\n")
    head = _commit(repo, "head")
    explicit = _run_fbpa(repo, base=base, head=head, claims=[], limits=FAST_LIMITS)
    assert explicit["fbpa"]["in_scope"] == 0
    assert [
        (f["finding_type"], f["error_class"], f["reproduction"]) for f in explicit["findings"]
    ] == [("fbpa-inconclusive", "material_requirement_miss", "not_reproducible")]
    # A mistyped test_paths makes auto-discovery match nothing: still not clean.
    auto = run_probes(
        repo,
        [],
        contract={
            "fail_before_pass_after": {
                "base": base,
                "head": head,
                "runner": "pytest",
                "claims": [],
                "auto_discover": True,
                "test_paths": ["tset/**"],
                "limits": FAST_LIMITS,
            }
        },
    )
    assert auto["fbpa"]["in_scope"] == 0
    assert [(f["finding_type"], f["error_class"]) for f in auto["findings"]] == [
        ("fbpa-inconclusive", "material_requirement_miss")
    ]


def test_canary_runs_under_memory_limit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    # Importing ``hog`` allocates ~512M: under memory_max=64M the canary is
    # killed (reported not_found) instead of running unbounded.
    _write(repo, "hog/__init__.py", "BLOB = bytearray(512 * 1024 * 1024)\n")
    _write(repo, "tests/test_real.py", _TEST_REAL)
    base = _commit(repo, "base")
    _write(repo, "README.md", "x\n")
    head = _commit(repo, "head")
    result = _run_one(
        repo,
        base,
        head,
        "tests/test_real.py::test_real",
        limits={"memory_max": "64M", "timeout_s": 15, "repeats": 1},
        import_canary=["hog"],
    )
    canary_pkg = {"path": "canary_pkg/__init__.py"}
    assert result["fbpa"]["import_canary"] == {
        "base": {"canary_pkg": canary_pkg, "hog": {"not_found": True}},
        "head": {"canary_pkg": canary_pkg, "hog": {"not_found": True}},
    }


# ---------------------------------------------------------------------------
# Round-3 review, item 1: only the attributed target name counts as "this test
# references the missing symbol"; another name bound by the same import does not.
# ---------------------------------------------------------------------------


def test_strawman_collateral_other_name_from_same_import(tmp_path: Path) -> None:
    result = _absence_strawman(
        tmp_path,
        {"pkg/__init__.py": "", "pkg/mod.py": "def a():\n    return 1\n"},
        {
            "pkg/mod.py": "def a():\n    return 1\ndef b():\n    return 2\n",
            "tests/test_p.py": "from pkg.mod import a, b\n\n\ndef test_a():\n    assert a() == 1\n",
        },
        "tests/test_p.py::test_a",
    )
    assert _labels(result) == {"inconclusive:b_collateral"}


# ---------------------------------------------------------------------------
# Round-3 review, item 3: non-UTF-8 test output must not crash the probe.
# ---------------------------------------------------------------------------


def test_non_utf8_test_output_does_not_crash(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "README.md", "a\n")
    base = _commit(repo, "base")
    _write(
        repo,
        "tests/test_b.py",
        "import os\n\n\ndef test_b(capfd):\n    with capfd.disabled():\n"
        "        os.write(1, b'\\xff\\xfe')\n    assert True\n",
    )
    head = _commit(repo, "a test that writes raw bytes to stdout")
    result = _run_one(repo, base, head, "tests/test_b.py::test_b")
    assert _labels(result) == {"base_passes"}


# ---------------------------------------------------------------------------
# Round-3 review, item 4: a detached (setsid) grandchild does not survive.
# ---------------------------------------------------------------------------


def test_detached_grandchild_is_stopped(tmp_path: Path) -> None:
    import random

    sentinel = f"{random.randint(10000, 99999)}.{random.randint(1000, 9999)}"
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "README.md", "a\n")
    base = _commit(repo, "base")
    _write(
        repo,
        "tests/test_s.py",
        "import subprocess\n\n\ndef test_s():\n"
        f"    subprocess.Popen(['setsid', 'sleep', '{sentinel}'])\n"
        "    assert True\n",
    )
    head = _commit(repo, "a test that leaves a detached grandchild")
    try:
        result = _run_one(repo, base, head, "tests/test_s.py::test_s")
        survivors = subprocess.run(
            ["pgrep", "-f", f"sleep {sentinel}"], capture_output=True, text=True, check=False
        ).stdout.split()
    finally:
        subprocess.run(["pkill", "-9", "-f", f"sleep {sentinel}"], check=False)
    assert _labels(result) == {"base_passes"}
    assert survivors == []


# ---------------------------------------------------------------------------
# Round-3 review, item 5: the canary list is the union of declared and detected
# names, and each side needs at least one name resolved inside its worktree.
# ---------------------------------------------------------------------------


def test_canary_union_checks_real_package_despite_misspelled_name(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "realpkg/__init__.py", "")
    _write(repo, "tests/test_x.py", "def test_x():\n    assert True\n")
    base = _commit(repo, "base")
    _write(repo, "README.md", "x\n")
    head = _commit(repo, "head")
    result = _run_one(repo, base, head, "tests/test_x.py::test_x", import_canary=["realpkgg"])
    canary = result["fbpa"]["import_canary"]
    assert canary["base"] == {
        "realpkg": {"path": "realpkg/__init__.py"},
        "realpkgg": {"not_found": True},
    }
    assert _labels(result) == {"base_passes"}


def test_canary_only_invalid_or_missing_names_faults(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)  # no package to auto-detect
    _write(repo, "tests/test_x.py", "def test_x():\n    assert True\n")
    base = _commit(repo, "base")
    _write(repo, "README.md", "x\n")
    head = _commit(repo, "head")
    result = _run_one(
        repo, base, head, "tests/test_x.py::test_x", import_canary=["not a name", "nosuchpkg"]
    )
    assert _labels(result) == {"fault:F_ENV_IMPORT"}
    assert result["fbpa"]["import_canary"]["base"] == {
        "not a name": {"invalid_name": True},
        "nosuchpkg": {"not_found": True},
    }


# ---------------------------------------------------------------------------
# Round-3 review, item 6: finalize requires the prepare-time limiter backend.
# ---------------------------------------------------------------------------


def test_finalize_with_different_limiter_backend_is_evidence_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from validity_audit import fbpa as fbpa_module
    from validity_audit.runtime import EvidenceMismatchError

    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "util.py", _UTIL_NOOP)
    base = _commit(repo, "initial util")
    _write(repo, "tests/test_util.py", _TEST_UTIL)
    _write(repo, "notes.md", "# n\n")
    head = _commit(repo, "weak test")
    prepared_backend = fbpa_module._detect_memory_backend()
    other = "rlimit" if prepared_backend == "systemd-run" else "systemd-run"
    calls = {"n": 0}
    real_detect = fbpa_module._detect_memory_backend

    def _switching() -> str | None:
        calls["n"] += 1
        return real_detect() if calls["n"] == 1 else other

    monkeypatch.setattr(fbpa_module, "_detect_memory_backend", _switching)
    with pytest.raises(EvidenceMismatchError, match="limiter backend changed"):
        _round_trip(
            repo,
            fbpa_claims=[{"test": "tests/test_util.py::test_noop", "intent": "fixes"}],
            base=base,
            head=head,
            run_name="backend",
        )


# ---------------------------------------------------------------------------
# Round-3 review, item 7: an unparseable head test file is listed in skipped.
# ---------------------------------------------------------------------------


def test_unparseable_head_test_file_listed_in_skipped(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "README.md", "a\n")
    base = _commit(repo, "base")
    _write(repo, "tests/test_bad.py", "def test_bad(:\n    pass\n")
    _write(repo, "tests/test_ok.py", "def test_ok():\n    assert True\n")
    head = _commit(repo, "head")
    result = _run_fbpa(
        repo, base=base, head=head, claims=[], auto_discover=True, limits=FAST_LIMITS
    )
    assert {
        "test": "tests/test_bad.py",
        "reason": ("auto-discovery could not parse head test file (SyntaxError)"),
    } in result["fbpa"]["skipped"]


# ---------------------------------------------------------------------------
# Round-3 review, item 8: base_passes + head_not_passing counts in both classes.
# ---------------------------------------------------------------------------


def test_base_passes_and_head_not_passing_count_in_both(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "m.py", "def f():\n    return 1\n")
    base = _commit(repo, "base")
    _write(repo, "m.py", "def f():\n    return 2\n")
    _write(repo, "tests/test_m.py", "from m import f\n\n\ndef test_m():\n    assert f() == 1\n")
    head = _commit(repo, "head breaks the behaviour the test pins")
    result = _run_one(repo, base, head, "tests/test_m.py::test_m")
    assert _labels(result) == {"base_passes", "head_not_passing"}
    assert result["fbpa"]["counts"] == {"base_passes": 1, "head_not_passing": 1}


# ---------------------------------------------------------------------------
# Round-3 review, item 10: monkeypatch's "<module ...> has no attribute" form.
# ---------------------------------------------------------------------------


def test_monkeypatch_module_repr_message_is_attributed(tmp_path: Path) -> None:
    result = _absence_strawman(
        tmp_path,
        {"pkg/__init__.py": "", "pkg/core.py": "def old():\n    return 1\n"},
        {
            "pkg/core.py": "def old():\n    return 1\ndef newfn():\n    return 2\n",
            "tests/test_mp.py": """
            from pkg import core
            def test_mp(monkeypatch):
                monkeypatch.setattr(core, "newfn", lambda: 3)
                assert core.newfn() == 3
            """,
        },
        "tests/test_mp.py::test_mp",
    )
    assert _labels(result) == {"absence_only"}


# ---------------------------------------------------------------------------
# Round-3 review, item 11: one node id, one claim; node ids must contain "::".
# ---------------------------------------------------------------------------


def test_duplicate_node_id_and_non_node_id_claims_are_rejected(tmp_path: Path) -> None:
    from validity_audit.fbpa import FbpaError, run_fbpa
    from validity_audit.schemas import SchemaValidationError, validate_document

    duplicate = {
        "base": "HEAD",
        "head": "HEAD",
        "runner": "pytest",
        "claims": [
            {"test": "tests/test_x.py::test_x", "intent": "fixes"},
            {"test": "tests/test_x.py::test_x", "intent": "characterizes"},
        ],
    }
    with pytest.raises(FbpaError, match="more than once"):
        run_fbpa(tmp_path, duplicate)
    contract = {
        "schema_version": "0.6.0",
        "task_id": "t",
        "claims": [{"claim_id": "c1", "statement": "s"}],
        "artifact_paths": ["notes.md"],
        "packs": ["docs"],
        "fail_before_pass_after": {
            "base": "a",
            "head": "b",
            "runner": "pytest",
            "claims": [{"test": "tests/test_x.py", "intent": "fixes"}],
        },
    }
    with pytest.raises(SchemaValidationError):
        validate_document(contract, "task_contract")


# ---------------------------------------------------------------------------
# Round-4 review, item 1: existence assertions (spec §3.1).
# ---------------------------------------------------------------------------


def test_strawman_hasattr_existence_assertion(tmp_path: Path) -> None:
    result = _absence_strawman(
        tmp_path,
        {"pkg/__init__.py": "", "pkg/core.py": "def old():\n    return 1\n"},
        {
            "pkg/core.py": "def old():\n    return 1\n\ndef newfn():\n    return 1\n",
            "tests/test_x.py": "import pkg.core as core\n\n\ndef test_newfn_exists():\n"
            "    assert hasattr(core, 'newfn')\n    assert core.newfn() is not None\n",
        },
        "tests/test_x.py::test_newfn_exists",
    )
    assert _labels(result) == {"absence_only"}


def test_existence_assertion_variants_are_absence_only(tmp_path: Path) -> None:
    result = _absence_strawman(
        tmp_path,
        {"pkg/__init__.py": "", "pkg/core.py": "class Box:\n    pass\n"},
        {
            "pkg/core.py": "class Box:\n    size = 1\n",
            "tests/test_v.py": textwrap.dedent(
                """
                from pkg import core
                from pkg.core import Box


                def test_getattr():
                    assert getattr(Box, 'size', None) == 1


                def test_dir():
                    assert 'size' in dir(Box())


                def test_dict():
                    assert 'size' in Box.__dict__
                """
            ),
        },
        "tests/test_v.py::test_getattr",
    )
    assert _labels(result) == {"absence_only"}


def test_hasattr_on_existing_conditional_attribute_stays_failing(tmp_path: Path) -> None:
    # ``value`` exists at base (set only when flag is true); head sets it always.
    # The failing hasattr is a real behavioural failure, not an absence.
    result = _absence_strawman(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/core.py": "class Box:\n    def __init__(self, flag):\n"
            "        if flag:\n            self.value = 1\n",
        },
        {
            "pkg/core.py": "class Box:\n    def __init__(self, flag):\n        self.value = 1\n",
            "tests/test_b.py": "from pkg.core import Box\n\n\ndef test_b():\n"
            "    assert hasattr(Box(False), 'value')\n",
        },
        "tests/test_b.py::test_b",
    )
    assert _labels(result) == {"demonstrated"}
    assert result["checks"][0]["base_verdict"] == "B_FAIL_ASSERT"


# ---------------------------------------------------------------------------
# Round-4 review, item 2: test files head removed are removed from base, and
# with no implementation change nothing can be demonstrated.
# ---------------------------------------------------------------------------


def test_head_moved_conftest_is_not_left_at_base(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/core.py", "def f(x):\n    return x\n")
    _write(repo, "pkg/other.py", "X = 1\n")
    _write(repo, "tests/conftest.py", "import pytest\n@pytest.fixture\ndef val():\n    return 1\n")
    base = _commit(repo, "base")
    (repo / "tests/conftest.py").unlink()
    _write(repo, "conftest.py", "import pytest\n@pytest.fixture\ndef val():\n    return 2\n")
    _write(repo, "pkg/other.py", "X = 2\n")  # an unrelated impl change
    _write(
        repo,
        "tests/test_x.py",
        "from pkg.core import f\n\n\ndef test_f(val):\n    assert f(val) == 2\n",
    )
    head = _commit(repo, "move the conftest up a directory")
    result = _run_one(repo, base, head, "tests/test_x.py::test_f")
    assert _labels(result) == {"base_passes"}
    assert result["fbpa"]["non_test_diff_count"] == 1


def test_no_impl_change_cannot_be_demonstrated(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "README.md", "a\n")
    base = _commit(repo, "base")
    _write(repo, "tests/test_w.py", _TEST_GIT_SUBJECT)
    head = _commit(repo, "a test-only change")
    result = _run_one(repo, base, head, "tests/test_w.py::test_w")
    assert _labels(result) == {"inconclusive:no_impl_change"}
    assert result["fbpa"]["non_test_diff_count"] == 0


# ---------------------------------------------------------------------------
# Round-4 review, item 3: a policy override lowering material_requirement_miss
# cannot turn an inconclusive claim into a pass (severity high, spec §4).
# ---------------------------------------------------------------------------


def test_inconclusive_with_policy_override_still_needs_review(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/core.py", "def f():\n    return 1\n")
    base = _commit(repo, "buggy")
    _write(repo, "pkg/core.py", "def f():\n    return 2\n")
    _write(repo, "tests/test_m.py", _TEST_SKIPS_AT_BASE)
    _write(repo, "notes.md", "# n\n")
    head = _commit(repo, "fix, test skips at base")
    att = _round_trip(
        repo,
        fbpa_claims=[{"test": "tests/test_m.py::test_m", "intent": "fixes"}],
        base=base,
        head=head,
        run_name="override",
        extra_contract={
            "policy_overrides": [
                {
                    "error_class": "material_requirement_miss",
                    "gate_effect": "advisory",
                    "reason": "lowered on purpose for this control",
                }
            ]
        },
    )
    assert att["overall_result"]["status"] == "needs_review"


# ---------------------------------------------------------------------------
# Round-4 review, item 4: a project module imported by the claimed test is part
# of the canary and must resolve inside the worktree.
# ---------------------------------------------------------------------------


def test_canary_covers_test_imported_project_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "lib/pkgname/__init__.py", "VALUE = 1\n")
    _write(repo, "tests/__init__.py", "")
    _write(repo, "tests/test_v.py", "def test_v():\n    assert True\n")
    base = _commit(repo, "base")
    _write(repo, "lib/pkgname/__init__.py", "VALUE = 2\n")
    _write(
        repo,
        "tests/test_v.py",
        "import pkgname\n\n\ndef test_v():\n    assert pkgname.VALUE == 2\n",
    )
    head = _commit(repo, "head")
    decoy = tmp_path / "decoy"
    _write(decoy, "pkgname/__init__.py", "VALUE = 2\n")
    monkeypatch.setenv("PYTHONPATH", str(decoy))
    result = _run_one(repo, base, head, "tests/test_v.py::test_v")
    assert _labels(result) == {"fault:F_ENV_IMPORT"}


# ---------------------------------------------------------------------------
# Round-4 review, P3 items.
# ---------------------------------------------------------------------------


def test_broken_symlink_under_tests_is_contract_error(tmp_path: Path) -> None:
    from validity_audit.fbpa import FbpaError

    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "README.md", "a\n")
    base = _commit(repo, "base")
    _write(repo, "tests/test_x.py", _TEST_REAL)
    os.symlink("/nonexistent/fbpa-target", repo / "tests" / "data_link")
    head = _commit(repo, "head with a broken symlink")
    with pytest.raises(FbpaError, match="broken symlink"):
        _run_one(repo, base, head, "tests/test_x.py::test_real")


def test_name_error_scope_is_innermost_frame_module(tmp_path: Path) -> None:
    result = _absence_strawman(
        tmp_path,
        {"pkg/__init__.py": "", "pkg/core.py": "def f():\n    return helper()\n"},
        {
            "pkg/core.py": "def helper():\n    return 1\n\n\ndef f():\n    return helper()\n",
            "tests/test_n.py": "from pkg.core import f\n\n\ndef test_n():\n    assert f() == 1\n",
        },
        "tests/test_n.py::test_n",
    )
    assert _labels(result) == {"absence_only"}


def test_xpass_at_head_is_not_passing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/core.py", "def f():\n    return 1\n")
    base = _commit(repo, "base")
    _write(
        repo,
        "tests/test_x.py",
        "import pytest\nfrom pkg.core import f\n\n\n@pytest.mark.xfail(reason='x', strict=False)\n"
        "def test_f():\n    assert f() == 1\n",
    )
    head = _commit(repo, "head")
    result = _run_one(repo, base, head, "tests/test_x.py::test_f", intent="characterizes")
    assert _labels(result) == {"head_not_passing"}
    assert result["checks"][0]["head_verdict"] == "H_SKIP"


def test_schema_rejects_single_repeat_and_option_like_refs() -> None:
    from validity_audit.schemas import SchemaValidationError, validate_document

    def contract(**fbpa: Any) -> dict[str, Any]:
        base = {"base": "a", "head": "b", "runner": "pytest", "claims": []}
        base.update(fbpa)
        return {
            "schema_version": "0.6.0",
            "task_id": "t",
            "claims": [{"claim_id": "c1", "statement": "s"}],
            "artifact_paths": ["notes.md"],
            "packs": ["docs"],
            "fail_before_pass_after": base,
        }

    validate_document(contract(limits={"repeats": 2}), "task_contract")
    bad = [
        contract(limits={"repeats": 1}),
        contract(base="--upload-pack=x"),
        contract(head="-h"),
        contract(claims=[{"test": "-k::x", "intent": "fixes"}]),
    ]
    for document in bad:
        with pytest.raises(SchemaValidationError):
            validate_document(document, "task_contract")


# ---------------------------------------------------------------------------
# Round-5 verification, item 1: a base-side strict xpass is a skip, never a
# failure (spec §3.1 B_SKIP).
# ---------------------------------------------------------------------------


def test_base_strict_xpass_is_skip(tmp_path: Path) -> None:
    result = _absence_strawman(
        tmp_path,
        {"pkg/__init__.py": "", "pkg/core.py": "def f():\n    return 1\n"},
        {
            "pkg/core.py": "def f():\n    return 2\n",
            "tests/test_t.py": "import pytest\nfrom pkg import core\n\n\n"
            "@pytest.mark.xfail(core.f() == 1, reason='x', strict=True)\n"
            "def test_x():\n    assert core.f() in (1, 2)\n",
        },
        "tests/test_t.py::test_x",
    )
    assert _labels(result) == {"inconclusive:b_skip"}


# ---------------------------------------------------------------------------
# Round-5 verification, item 2: existence checks in the whole failing statement.
# ---------------------------------------------------------------------------

_HEAD_ONLY_N = {"pkg/core.py": "N = 1\ndef f():\n    return 2\n"}
_BASE_NO_N = {"pkg/__init__.py": "", "pkg/core.py": "def f():\n    return 1\n"}


def test_unittest_assert_true_hasattr_is_absence_only(tmp_path: Path) -> None:
    result = _absence_strawman(
        tmp_path,
        _BASE_NO_N,
        {
            **_HEAD_ONLY_N,
            "tests/test_t.py": "import unittest\nfrom pkg import core\n\n\n"
            "class TestX(unittest.TestCase):\n    def test_x(self):\n"
            "        self.assertTrue(hasattr(core, 'N'))\n",
        },
        "tests/test_t.py::TestX::test_x",
    )
    assert _labels(result) == {"absence_only"}


def test_helper_hasattr_with_variable_name_is_unattributed(tmp_path: Path) -> None:
    result = _absence_strawman(
        tmp_path,
        _BASE_NO_N,
        {
            **_HEAD_ONLY_N,
            "tests/test_t.py": "from pkg import core\n\n\n"
            "def _has(o, n):\n    assert hasattr(o, n)\n\n\n"
            "def test_x():\n    _has(core, 'N')\n",
        },
        "tests/test_t.py::test_x",
    )
    assert _labels(result) == {"inconclusive:unattributed"}


def test_hasattr_with_constant_variable_is_unattributed(tmp_path: Path) -> None:
    result = _absence_strawman(
        tmp_path,
        _BASE_NO_N,
        {
            **_HEAD_ONLY_N,
            "tests/test_t.py": "from pkg import core\n\nNAME = 'N'\n\n\n"
            "def test_x():\n    assert hasattr(core, NAME)\n",
        },
        "tests/test_t.py::test_x",
    )
    assert _labels(result) == {"inconclusive:unattributed"}


def test_all_hasattr_generator_is_unattributed(tmp_path: Path) -> None:
    result = _absence_strawman(
        tmp_path,
        _BASE_NO_N,
        {
            **_HEAD_ONLY_N,
            "tests/test_t.py": "from pkg import core\n\n\n"
            "def test_x():\n    assert all(hasattr(core, n) for n in ('N',))\n",
        },
        "tests/test_t.py::test_x",
    )
    assert _labels(result) == {"inconclusive:unattributed"}


# ---------------------------------------------------------------------------
# Round-5 verification, item 3: a module reached through importlib is part of
# the canary (every importable top-level name in either tree).
# ---------------------------------------------------------------------------


def test_canary_covers_importlib_reached_head_only_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "README.md", "a\n")
    base = _commit(repo, "base")
    _write(repo, "newmod.py", "def f():\n    return 2\n")
    _write(
        repo,
        "tests/test_n.py",
        "import importlib\n\n\ndef test_n():\n"
        "    assert importlib.import_module('newmod').f() == 2\n",
    )
    head = _commit(repo, "head adds newmod")
    decoy = tmp_path / "decoy"
    _write(decoy, "newmod.py", "def f():\n    return 1\n")
    monkeypatch.setenv("PYTHONPATH", str(decoy))
    result = _run_one(repo, base, head, "tests/test_n.py::test_n")
    assert _labels(result) == {"fault:F_ENV_IMPORT"}
    assert result["fbpa"]["import_canary"]["base"]["newmod"] == {"resolved_outside_worktree": True}


# ---------------------------------------------------------------------------
# Round-5 verification, item 4: the sides share a leaf directory name, and a
# comment-only edit is not an implementation change.
# ---------------------------------------------------------------------------


def test_worktree_leaf_name_does_not_reveal_the_side(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/core.py", "def f():\n    return 1\n")
    base = _commit(repo, "base")
    _write(repo, "pkg/core.py", "def f():\n    return 2\n")  # a real impl change
    _write(repo, "tests/test_w.py", _TEST_WORKTREE_NAME)
    head = _commit(repo, "head")
    result = _run_one(repo, base, head, "tests/test_w.py::test_w")
    assert _labels(result) == {"head_not_passing"}


def test_comment_only_edit_is_not_an_impl_change(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/core.py", "def f():\n    return 1\n")
    base = _commit(repo, "base")
    _write(repo, "pkg/core.py", "# a comment\ndef f():\n    return 1  # unchanged\n")
    _write(repo, "tests/test_w.py", _TEST_GIT_SUBJECT)
    head = _commit(repo, "a test-only change")
    result = _run_one(repo, base, head, "tests/test_w.py::test_w")
    assert _labels(result) == {"inconclusive:no_impl_change"}
    assert result["fbpa"]["non_test_diff_count"] == 0


# ---------------------------------------------------------------------------
# Round-5 verification, items 5-6: failure lines stay identical across reruns
# (truncated temp paths, tmp_path, set reprs).
# ---------------------------------------------------------------------------


def test_truncated_temp_path_in_repr_survives_prepare_finalize(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "pkg/__init__.py", "")
    _write(repo, "pkg/core.py", "def f():\n    return 1\n")
    base = _commit(repo, "base")
    _write(repo, "pkg/core.py", "N = 1\ndef f():\n    return 2\n")
    _write(
        repo,
        "tests/test_t.py",
        "import inspect\nfrom pkg import core\n\n\n"
        "def test_x():\n    assert 'N' in dict(inspect.getmembers(core))\n",
    )
    _write(repo, "notes.md", "# n\n")
    head = _commit(repo, "head")
    att = _round_trip(
        repo,
        fbpa_claims=[{"test": "tests/test_t.py::test_x", "intent": "fixes"}],
        base=base,
        head=head,
        run_name="truncated",
    )
    assert att["overall_result"]["status"] == "pass"


def test_tmp_path_in_failure_message_is_not_flaky(tmp_path: Path) -> None:
    result = _absence_strawman(
        tmp_path,
        _BASE_NO_N,
        {
            **_HEAD_ONLY_N,
            "tests/test_t.py": "from pkg.core import f\n\n\n"
            "def test_x(tmp_path):\n    assert f() == 2, str(tmp_path)\n",
        },
        "tests/test_t.py::test_x",
    )
    assert _labels(result) == {"demonstrated"}


def test_set_repr_in_failure_message_is_not_flaky(tmp_path: Path) -> None:
    result = _absence_strawman(
        tmp_path,
        _BASE_NO_N,
        {
            **_HEAD_ONLY_N,
            "tests/test_t.py": "from pkg.core import f\n\n\n"
            "def test_x():\n    assert f() == 2, repr({'alpha', 'beta', 'gamma', 'delta'})\n",
        },
        "tests/test_t.py::test_x",
    )
    assert _labels(result) == {"demonstrated"}


def test_located_namespace_with_later_outside_portion_does_not_fault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A namespace directory the tests never import, merged with a same-named
    # directory elsewhere on sys.path (as an editable install of another
    # checkout does): its first portion is the worktree's, so it is recorded,
    # not faulted.
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "nsdir/tool.py", "X = 1\n")
    _write(repo, "README.md", "a\n")
    base = _commit(repo, "base")
    _write(repo, "README.md", "b\n")
    _write(repo, "tests/test_r.py", _TEST_REAL)
    head = _commit(repo, "head")
    other = tmp_path / "other-checkout"
    _write(other, "nsdir/extra.py", "")
    monkeypatch.setenv("PYTHONPATH", str(other))
    result = _run_one(repo, base, head, "tests/test_r.py::test_real")
    assert result["fbpa"]["import_canary"]["base"]["nsdir"] == {
        "path": "nsdir",
        "outside_portions": True,
    }
    assert _labels(result) == {"base_passes"}


# ---------------------------------------------------------------------------
# Runtime module-origin audit (spec §2, amendment 6): an editable install's
# finder, appended to sys.meta_path, serves a *submodule* the worktree package
# lacks from another checkout. The static (top-level) canary sees the package
# resolve inside the worktree; only the runtime audit sees the submodule.
# ---------------------------------------------------------------------------

_EDITABLE_FINDER = """
import sys
from importlib.machinery import PathFinder

MAPPING = {mapping!r}


class _EditableFinder:
    @classmethod
    def find_spec(cls, fullname, path=None, target=None):
        parent, _, child = fullname.rpartition(".")
        if parent and parent in MAPPING:
            return PathFinder.find_spec(fullname, path=[MAPPING[parent]])
        return None


def install():
    if _EditableFinder not in sys.meta_path:
        sys.meta_path.append(_EditableFinder)
"""


def test_editable_finder_submodule_from_other_checkout_is_env_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo, "fixpkg/__init__.py", "")
    _write(repo, "fixpkg/ledger.py", "X = 1\n")
    base = _commit(repo, "base: fixpkg without runtime")
    _write(repo, "fixpkg/runtime.py", "def f():\n    return 2\n")
    _write(
        repo,
        "tests/test_rt.py",
        "from fixpkg.runtime import f\n\n\ndef test_rt():\n    assert f() == 2\n",
    )
    head = _commit(repo, "head adds fixpkg.runtime")

    other = tmp_path / "other-checkout"
    _write(other, "fixpkg/__init__.py", "")
    _write(other, "fixpkg/runtime.py", "def f():\n    return 2\n")
    site_dir = tmp_path / "fake-site"
    site_dir.mkdir()
    (site_dir / "__editable___fixpkg_finder.py").write_text(
        _EDITABLE_FINDER.format(mapping={"fixpkg": str(other / "fixpkg")}), encoding="utf-8"
    )
    (site_dir / "__editable__.fixpkg.pth").write_text(
        "import __editable___fixpkg_finder; __editable___fixpkg_finder.install()\n",
        encoding="utf-8",
    )
    (site_dir / "sitecustomize.py").write_text(
        "import os\nimport site\n\nsite.addsitedir(os.path.dirname(__file__))\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYTHONPATH", str(site_dir))

    result = _run_one(repo, base, head, "tests/test_rt.py::test_rt")
    assert _labels(result) == {"fault:F_ENV_IMPORT"}
    # The static canary alone is satisfied: fixpkg itself resolves inside.
    assert result["fbpa"]["import_canary"]["base"]["fixpkg"] == {"path": "fixpkg/__init__.py"}
    assert result["checks"][0]["outside_modules"] == ["fixpkg.runtime"]


def test_namespace_dir_merged_with_outside_checkout_is_not_flagged_at_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The test reaches a submodule of a namespace directory that also exists in
    # another checkout on sys.path (as this repository's protocol/ and examples/
    # merge with the editable checkout); the submodule itself loads from the
    # worktree, so the runtime audit must not flag the namespace package. It is
    # reached through importlib so the static canary only locates it (§9).
    repo = tmp_path / "repo"
    _init_canary_repo(repo)
    _write(repo, "nsdir/tool.py", "def f():\n    return 1\n")
    base = _commit(repo, "base")
    _write(repo, "nsdir/tool.py", "def f():\n    return 2\n")
    _write(
        repo,
        "tests/test_ns.py",
        "import importlib\n\n\ndef test_ns():\n"
        "    assert importlib.import_module('nsdir.tool').f() == 2\n",
    )
    head = _commit(repo, "head")
    other = tmp_path / "other-checkout"
    _write(other, "nsdir/extra.py", "")
    monkeypatch.setenv("PYTHONPATH", str(other))
    result = _run_one(repo, base, head, "tests/test_ns.py::test_ns")
    assert _labels(result) == {"demonstrated"}
    assert result["checks"][0]["outside_modules"] == []
