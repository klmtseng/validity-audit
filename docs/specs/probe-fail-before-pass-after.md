# Spec: deterministic fail-before / pass-after probe (FBPA)

Status: **approved (S0, 2026-10-04); amended six times on 2026-10-04 after S1 reviews**; implemented and validated against this repository's history (S2, see [`fbpa-history-v0.5.0.md`](fbpa-history-v0.5.0.md) and [`fbpa-history-adjudication-v0.5.0.md`](fbpa-history-adjudication-v0.5.0.md)). Branch `feat/fbpa-probe`, starting point
`aee302e484e9e5074d1a1b22727a8b4064f6e56f` (v0.5.0). Target release: v0.6.0.

## 0. The question this probe answers

> A test is claimed to prove a fix. If the fix is removed, does the test fail?

The probe is deterministic (git + pytest + JUnit XML) and never calls an LLM. It checks the causal link
between a test and a fix. It does **not** check whether the test targets the property the user cares
about; that remains a fitness question (see VERIFIER_CHALLENGES.md, "What this does not prove").

## 1. Inputs

### 1.1 New optional contract field

If the field is absent the probe does not run, and the probe output for that contract is unchanged
apart from the `probe_version` string (§5.3).

```json
"fail_before_pass_after": {
  "base": "<commit-ish>",
  "head": "<commit-ish>",
  "runner": "pytest",
  "test_paths": ["tests/**", "**/test_*.py", "**/conftest.py"],
  "claims": [
    {"test": "tests/test_policy.py::test_unknown_error_class_rejected", "intent": "fixes"},
    {"test": "tests/test_policy.py::test_known_classes_ok",            "intent": "characterizes"}
  ],
  "auto_discover": false,
  "limits": {"memory_max": "2G", "timeout_s": 600, "repeats": 2}
}
```

- `intent: fixes` claims the test guards against the bug the change fixes. It **must** fail before and pass after.
- `intent: characterizes` pins existing behaviour (for example PRs #2, #16 and #17, which only add tests).
  It must pass after. Passing before is expected and produces no finding. Without this distinction,
  every PR that only adds standing controls would be reported as having useless tests.
- `auto_discover: true` treats test functions added or modified in the diff (§1.3) as `fixes` claims.
  It is meant for historical PRs that have no contract (S2).

### 1.2 Exact meaning of "head tests on base"

1. `git worktree add --detach <tmp_b>/wt <base>`, with `<tmp_b>` outside the repository. Both sides use the same leaf directory name (`wt`) under separate temporary parents, so a test cannot tell the sides apart by path.
2. Copy every head file that matches `test_paths` over the base tree, including files that head added.
   Delete from the base tree every file that matches `test_paths` and does not exist at head (a moved or
   deleted `conftest.py` left behind at base would otherwise change base behaviour).
3. Every other file (implementation, schemas, golden fixtures, docs) stays at base.
4. Head side: `git worktree add --detach <tmp_h>/wt <head>`, with no overlay.

> `test_paths` is itself an assumption. A fix that lives in a helper under `tests/`, or a test that depends on
> a fixture changed in head, changes the verdict. The report therefore lists the overlaid files and the number
> of base→head changed files outside `test_paths`. It also records the resolved full SHAs of `base` and `head`
(`git rev-parse`), so a contract that names a branch or `HEAD` still pins what was measured.
>
> `non_test_diff_count` does not count a changed `.py` file whose `ast.dump` is identical at base and head (comment or whitespace edits).
>
> **Invariant:** if `non_test_diff_count == 0`, no `fixes` claim may be `demonstrated`; such claims become
> `inconclusive:no_impl_change`. With no implementation change, any base/head difference comes from test code.

### 1.3 Auto-discovery

Parse the AST of the test files at base and head. A node id that exists only at head is **added**. The same
node id with a different function-body AST is **modified**. Methods inside classes and parametrized tests are
judged at function level (§3.3). Changes to imports, whitespace or comments alone do not count as modified.

## 2. Execution

- Command per claim and side (one process per claim, so one hanging test cannot take other claims down): `systemd-run --user --scope -p MemoryMax=<memory_max> -p MemorySwapMax=0 -- timeout <timeout_s> python -m pytest -p no:cacheprovider -q --junitxml=<out> <node id>`, with the worktree as cwd.
- **Limiter backends.** `systemd-run --user` is preferred. Where no user systemd exists (for example CI runners) the probe falls back to `setrlimit(RLIMIT_AS)`, which limits virtual memory per process; under that backend memory exhaustion that does not surface as `MemoryError` may be misread. The backend used is recorded in the `fbpa` block (not in finding text). If neither backend works, every claim faults `F_RUNNER`.
- **Process cleanup.** When a run ends for any reason, every process it started, including detached grandchildren, is terminated (for systemd, by running each invocation as a named unit and stopping it).
- **Import-origin canary (required).** On the development machine, `pip show validity-audit` reports an
  editable install at `~/src/va-audit`, which is a different checkout from this repository.
  If the worktree imports the editable install, the base run executes some other implementation, every
  test "passes before", and the probe fires on everything. Before each run, execute
  `python -c "import <pkg>; print(<pkg>.__file__)"` once per side, under the same limits and environment. A path outside that worktree
  is fault `F_ENV_IMPORT`. The canary list is the union of the declared `import_canary` names and the auto-detected packages, every importable top-level module/package name found in either tree, and the project top-level modules imported by the claimed test files; each side must resolve every such test-imported module, and at least one name overall, inside its worktree, otherwise `F_ENV_IMPORT` (this stops a misspelled declared name from disabling the canary).
- **Runtime module-origin audit (required, amendment 6).** The static canary only checks top-level names. An
  editable install's finder sits at the end of `sys.meta_path` and serves any *submodule* the worktree package
  lacks from the other checkout (observed: base of PR #5 had `validity_audit/__init__.py` but no `runtime.py`;
  `import validity_audit.runtime` silently loaded `~/src/va-audit/validity_audit/runtime.py`, so 36
  tests "passed before"). Therefore the probe's pytest plugin records, at the end of every run, every module in
  `sys.modules` whose top-level name is a project name (any top-level module/package found in either tree) and
  whose origin (`__file__`, or each `__path__` entry for packages) lies outside that run's worktree. Any such module
  is fault `F_ENV_IMPORT` for the claim, with the module names listed. A missing or unreadable audit record is
  `F_NO_REPORT`. This check runs on both sides and supersedes the static canary as the primary guard; the static
  canary stays as a cheap pre-check.
- Each side runs `repeats` times (default 2). If any node id gets different results across runs, that is
  fault `F_FLAKY`.
- The report stores normalized results only (outcome, exception class, phase), never timings or absolute
  paths, so that finalize can rerun the probe and compare byte for byte. This reuses the existing
  "rerun must match" mechanism in `_verify_prepared_evidence` (`runtime.py:406-415`).

### 2.1 Explicit pytest exit-code contract

A nonzero exit is never read as "test failed" on its own.

| exit | meaning | base side | head side |
|---|---|---|---|
| 0 | all passed | normal, read XML | normal, read XML |
| 1 | some tests failed | normal, read XML | normal, read XML |
| 2 | interrupted / collection error | read XML and classify (usually import errors) | read XML; a collection error in the claimed test's module is `H_ERROR` (§3.2); `F_NOT_COLLECTED` only when the node id does not exist at head |
| 3 / 4 | internal error / usage error | fault `F_RUNNER` | fault `F_RUNNER` |
| 5 | no tests collected | attribute per §3.1 (may end as `B_ABSENT`, `B_COLLATERAL` or `inconclusive:unattributed`) | fault `F_NOT_COLLECTED` |
| 124 / 137 / killed by systemd | timeout / OOM | fault `F_TIMEOUT` / `F_OOM` | same |

Cross-check exit code against the XML. Exit 0 with failures in the XML, or exit 1 with an all-pass XML, is
fault `F_EXIT_XML_MISMATCH`. A missing or unparseable XML file is fault `F_NO_REPORT`.

## 3. Outcome classification (core rule: an import error is not an assertion failure)

### 3.1 Base side, per node id

| Class | Condition | Counts as "fails before"? |
|---|---|---|
| `B_FAIL_ASSERT` | call phase failed with `AssertionError`, `pytest.fail`, or `Failed: DID NOT RAISE` — except existence assertions below | **yes** (strong evidence) |
| `B_FAIL_EXC` | call phase raised any other exception not covered by the next row | **yes** (marked "failed by exception") |
| `B_ABSENT` | `ImportError`/`ModuleNotFoundError` while collecting the module (including a head `conftest.py`), or an `ImportError`, `NameError` or `AttributeError` raised in the call or setup phase, **whenever** the symbol named in the error exists at head but not at base (AST check on both sides) | **no**: it only shows the symbol did not exist yet |
| `B_COLLATERAL` | caught in a module-level collection error, but this test does not reference the **attributed target name** itself (other names bound by the same import statement do not count) | no; listed |
| `B_SETUP_ERROR` | fixture/setup error not covered by `B_ABSENT` | no; listed |
| `B_SKIP` | skipped / xfail / xpass (strict or not) | no; listed |
| `B_PASS` | passed | n/a (source of the main finding) |

**How absence is attributed (amendment 2).** Never use an unscoped bag of names. Parse the error message
into a scoped target, then look the target up in the scoped symbol tables of base and head:

| Message shape | Target |
|---|---|
| `cannot import name 'X' from 'pkg.mod'` | module `pkg.mod`, name `X` |
| `No module named 'pkg.mod'` | module `pkg.mod` |
| `module 'pkg.mod' has no attribute 'X'` | module `pkg.mod`, name `X` |
| `'Cls' object has no attribute 'X'` / `type object 'Cls' has no attribute 'X'` | class `Cls` (every project class with that name), attribute `X` |
| `name 'X' is not defined` | the test module's own scope, name `X` |

Scoped tables hold, per module: top-level functions, classes, `Assign`/`AnnAssign` targets, and import aliases;
per class: methods, properties, class-level `Assign`/`AnnAssign` (this covers dataclass fields), and
`self.X = ...` assignments in methods. Then:

- the target exists at head and not at base → `B_ABSENT`;
- the target exists at base, or the scope is not a project module/class (for example `'NoneType' object has no attribute`) → `B_FAIL_EXC` (a real behavioural failure);
- the message cannot be parsed, or a class name is ambiguous across base and head → `inconclusive:unattributed`, never `B_FAIL_EXC`.

**Existence assertions.** A failing assertion whose expression tests for a name — `hasattr(x, 'N')`,
`getattr(x, 'N', default)`, `'N' in dir(x)`, `'N' in vars(x)` or `x.__dict__` — where `N` resolves (by the
scoped tables above) to something that exists at head and not at base is `B_ABSENT`, not `B_FAIL_ASSERT`.
This applies to the whole failing statement at the innermost traceback frame, including `unittest` assertion
methods (`self.assertTrue(hasattr(...))`) and assertions inside helper functions. If such an existence call
names its attribute with a non-constant expression, the case is `inconclusive:unattributed`.

When the target exists at base, the class depends on the phase: call phase → `B_FAIL_EXC`; setup phase →
`B_SETUP_ERROR`; collection phase → `B_COLLATERAL` (setup and collection failures never count as failing before).
For a `NameError`, the lookup scope is the module of the innermost traceback frame, not always the test module.

The same attribution applies in the collection, setup and call phases. The test file is the file named in the
node id (class methods are qualified by class); never search by bare function name.

**Why `B_ABSENT` must not count.** If it did, every test that calls a new function would automatically "fail
before" and the probe would pass everything. That is exactly where AI-generated "new function plus a test
that always passes" hides. So it gets its own class. It neither passes nor convicts. It produces an advisory
(`fbpa-absence-only`, §4) stating that the test's pre-fix failure comes only from a missing symbol and cannot
show that it catches a behavioural fault.

### 3.2 Head side

Only `H_PASS` counts as passing. `H_FAIL`, `H_ERROR` (collection/setup, including a collection error in the
claimed test's own module) and `H_SKIP`/xfail/xpass all count as "does not pass after" → `head_not_passing`
(fail). A skip is not a pass. A claimed node id that is not collected at head at all is fault
`F_NOT_COLLECTED` (the claim points at a test that does not exist).

### 3.3 Parametrized tests and function-level synthesis

- Fails before: **at least one** case under the function is `B_FAIL_ASSERT` or `B_FAIL_EXC`.
- Passes after: **every** case under the function is `H_PASS`.
- Every per-case result is listed in the report, not only the synthesized verdict.

### 3.4 Verdict matrix (intent = fixes)

| base \ head | H_PASS | anything else |
|---|---|---|
| B_FAIL_ASSERT / B_FAIL_EXC | ✅ `demonstrated` | ❌ `head_not_passing` |
| B_PASS | ❌ **`base_passes` (main output)** | ❌ `base_passes` + `head_not_passing` |
| B_ABSENT | ⚠️ `absence_only` | ❌ `head_not_passing` |
| B_COLLATERAL / B_SETUP_ERROR / B_SKIP | ⚠️ `inconclusive:<reason>` | ❌ `head_not_passing` |

For intent = characterizes, only head matters: `H_PASS` is ✅, anything else is ❌ `head_not_passing`.

## 4. Finding and policy wiring (reuses the existing pipeline; no new error class)

Findings come out of `run_probes()` with `source: deterministic_probe` and enter `evaluate_policy` on the same
path as the existing probes.

| Finding | Trigger | error_class | severity | reproduction | Policy result (current `policy.py:185-230`) |
|---|---|---|---|---|---|
| `fbpa-base-passes` | a `fixes` claim is `base_passes` | `material_requirement_miss` | high | reproduced | **fail** |
| `fbpa-head-not-passing` | `head_not_passing` | `material_requirement_miss` | high | reproduced | **fail** |
| `fbpa-fault` | any `F_*` | `material_requirement_miss` | high | `not_reproducible` | effect none + **needs_review** (fail-closed: never a pass) |
| `fbpa-inconclusive` | a contract claim lands in inconclusive, or nothing was judged | `material_requirement_miss` | high | `not_reproducible` | **needs_review** |
| `fbpa-absence-only` | `absence_only` | `fitness` | med | reproduced | advisory |
| a test-level non-`demonstrated` result from auto_discover (`base_passes`, `head_not_passing`, `absence_only`, inconclusive) | inferred, not claimed by the author | `fitness` | med | reproduced | advisory |

The last row exists because an auto-discovered new test is not an author's claim that it proves the fix.
Feature PRs often add tests that pin existing behaviour at the same time, so these cannot be failed. The S2
manual spot-check measures the false-positive rate of this row.

Environment-level faults are never downgraded, in auto_discover mode included: an environment-level fault (`F_ENV_IMPORT`,
`F_RUNNER`, `F_OOM`, `F_TIMEOUT`, `F_NO_REPORT`, `F_EXIT_XML_MISMATCH`) means the probe could not measure, which is
not a property of an inferred claim. These keep the `fbpa-fault` row (needs_review) in every mode. `F_FLAKY` and
`F_NOT_COLLECTED` on an auto-discovered test are test-level and follow the advisory row. Likewise, `in_scope == 0`
or `judged == 0` with the field present yields needs_review in every mode. Head test files that auto-discovery
cannot parse are listed in `skipped` with a reason.

Every fbpa finding carries a `finding_type` field equal to the name in the first column (for example
`fbpa-base-passes`); `finding_id` itself is a sequence number and must not be used for grouping.

### 4.1 Skip accounting (per VERIFIER_CHALLENGES, "Skip accounting")

`probe_report` gains an `fbpa` block that must contain: `in_scope` (number of claims), `judged`, a count per
class, `skipped: [{test, reason}]` (every entry named), `overlay_files`, `non_test_diff_count`, and the import
canary path for each side. **If `in_scope > 0` and `judged == 0`, the result must not be clean**: there must be at
least one `fbpa-inconclusive` or `fbpa-fault` finding.

## 5. Versioning decisions (approved 2026-10-04)

1. **policy_id → `validity-audit-default-v0.6.0`.** `ERROR_CLASS_EFFECTS` is unchanged and contracts without the
   new field keep their verdicts, but the new field can turn a previously accepted change into a fail. That is a
   change in verdict semantics, so the ID changes (the lesson recorded in CHANGELOG 0.5.0).
2. **Contract `schema_version` → `0.6.0`.** Today it is `const "0.3.0"` with `additionalProperties: false`. The schema
   accepts both `0.3.0` (without the new field) and `0.6.0` (new field allowed). An older tool reading a 0.6.0
   contract rejects it explicitly instead of silently skipping the probe.
3. **`probe_version` `0.3.0` → `0.6.0`.** This changes the probe_report digest in golden cases. Before changing it,
   grep every fixture that embeds the digest or the string (`golden_cases/`, `schemas/examples/`,
   `docs/attestation-example.json`, tests) and update them together, then run the CI workflow step by step.

## 6. The probe's own controls (S1; all in tests/, all calling the real `run_probes`)

Each fixture runs `git init` on a small repo inside `tmp_path` and does not depend on this repository's history.

| Control | Fixture | Required result |
|---|---|---|
| Positive | base has an off-by-one, head fixes it, the test asserts the correct value | `demonstrated`, no finding |
| Negative 1 | the test already passes at base (its assertion is unrelated to the bug) | `fbpa-base-passes` (fail) |
| Negative 2 | the test only imports a new head function and asserts something always true | `absence_only` advisory, **not** demonstrated |
| Negative 3 | head does not actually fix the implementation | `fbpa-head-not-passing` |
| Negative 4 | a `characterizes` test passes at base | no finding (shows the intent distinction works) |
| Fault 1 | head has a syntax error | `fbpa-fault`, needs_review |
| Fault 2 | the claimed node id does not exist | `F_RUNNER` (pytest exits 4 for an unknown node id, §2.1) |
| Fault 3 | the test loops forever | `F_TIMEOUT` (timeout_s=5) |
| Fault 4 | the test allocates a lot of memory | `F_OOM` (MemoryMax=64M) |
| Fault 5 | import canary: the package is imported from outside the worktree | `F_ENV_IMPORT` |
| Fault 6 | a nondeterministic test | `F_FLAKY` |

Plus a **per-item coverage self-check**: every finding type and every `F_*` must be triggered by at least one
control, and the set each control triggers must **equal** its expected set (compare with `==`, not `in`). Any
uncovered item fails the test.

## 7. S2 historical validation plan

- All 21 merged PRs are squash merges (checked locally: every merge commit has one parent), so `base = <sha>^`
  and `head = <sha>`.
- 7 PRs touch no test file (#4 #8 #11 #12 #19 #20 #21): listed as `not_applicable`, still in the table.
- 3 PRs change tests but no non-test `.py` file (#2 #16 #17). They may still change non-test files (for example
  #16 changes `docs/architecture.svg`, which its test asserts), so they are not guaranteed to be `base_passes`.
- Output: `docs/specs/fbpa-history-v0.5.0.md`, a full enumeration (PR | claimed tests | base result | head result |
  verdict). Every `base_passes` is read by hand against the test and the diff and judged as one of: probe wrong,
  PR genuinely weak, or characterization.

## 8. Out of scope for this round

Mutation testing (mutmut is not installed), non-pytest runners, other languages, network isolation (could later
reuse `benchmarks/offline_guard`), and "stub the new symbols and rerun to turn `absence_only` into a decision"
(feasible, separate work).

## 9. Known limitations (to be stated in the README)

- Failing before only shows the test breaks when the fix is removed. It does not show the test catches **every**
  bug of that kind; that is mutation testing.
- `test_paths` decides what counts as the fix. A fix placed inside the test directory is treated as test code, and
  vice versa.
- `B_FAIL_EXC` counts any non-absence exception as failing before. A `TypeError` from a keyword argument that head added, or a `FileNotFoundError` from a data file that head added, is reported as `demonstrated` even though it is close to an absence failure. Reclassifying these would hide real exception bugs, so they stay as a stated limitation.
- The fault code `F_ENV_IMPORT` requires a canary list. If none is declared and none can be detected, the probe faults rather than running without a canary.
- Existence checks are recognised only in the forms listed in §3.1. Checks written via `__all__`,
  `inspect.getmembers`, `.keys()`, or `if not hasattr(...): pytest.fail(...)` are still judged `demonstrated`.
- For importable names that are only located (not imported) by the canary, a namespace package is checked by
  its first portion only; a later portion outside the worktree (for example merged in from an editable install)
  is recorded as `outside_portions` but does not fault. A test that dynamically imports a submodule existing only
  in that outside portion is not caught.
- Auto-discovery follows pytest's default collection names; it ignores a repository's own `python_files` /
  `python_functions` / `python_classes` settings and `unittest.TestCase` subclasses not named `Test*`.
- A test that only asserts a constant (for example a version string) is `demonstrated` when the constant
  changed. That is technically correct and weak evidence; the S2 table flags such tests.
- `repeats: 1` disables flake detection; the schema requires `repeats >= 2`.
- Absence attribution parses CPython's error-message wording (§3.1). A Python release that rewords these messages degrades attributions to `inconclusive:unattributed`, which is safe but noisy.
- `B_ABSENT` relies on an AST check for symbol existence. Dynamically created symbols (`getattr`, module
  `__getattr__`) are misclassified as `B_FAIL_EXC`.
