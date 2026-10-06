# Validity Audit v0.6.0

Validity Audit v0.6.0 adds one check to its own evidence chain:

> If the fix is removed, does the test that is claimed to prove it actually fail?

A test can assert something that was already true before the fix, or that stays true after the fix is reverted. This is a common way for AI-written tests to go wrong. Such a test always passes and proves nothing, but in a pass/fail report it looks exactly like a real regression guard. v0.6.0 adds a deterministic probe, FBPA (fail-before / pass-after), that checks this directly: it runs the claimed test against the commit before the change and the commit after it, under `git worktree` and pytest. It never calls an LLM.

The release keeps the same bounded assurance model: one task run, one contract, one digest-bound artifact set, and one explicitly unsigned validity attestation.

## Why this release exists

We ran FBPA, with `auto_discover: true`, against all 21 merged pull requests in this repository's own history: 135 claims. 34 were `demonstrated` (fails before, passes after), 24 `base_passes` (the test already passed before the change), 35 `absence_only` (the only before-failure was a missing symbol), 42 inconclusive, 0 faults.

Hand adjudication of every `demonstrated` and `base_passes` row found two tests that pass regardless of the bug they are supposed to guard: PR #10's single-line Markdown-title check, and PR #1's duplicate-key check. It also found one real gap: PR #23 changed the policy so a high-severity, unreproduced finding forces `needs_review`, but no test in the suite guards that specific change. A mutation that deleted the condition from the policy code left the full suite at 174 passed. A separate pull request adds the missing test.

These numbers describe one repository with 21 PRs. They show FBPA found two weak tests and one real coverage gap here. They are not a rate claim about other repositories, and they are not mutation testing: mutation testing asks whether any test in the suite catches a given change, and FBPA only compares one claimed test against one claimed fix.

## What changed

### 1. The `fail_before_pass_after` contract field

An optional field on the task contract names a `base` commit, a `head` commit, and a list of claims, each a test node id and an intent. `intent: "fixes"` must fail at `base` and pass at `head`. `intent: "characterizes"` only has to pass at `head`; passing at `base` too is expected for a test-only change and produces no finding. Verdicts feed the existing policy pipeline; no new error class was added. See `docs/specs/probe-fail-before-pass-after.md`.

### 2. New policy identifier

This release can change verdicts, so it ships under a new policy identifier, **`validity-audit-default-v0.6.0`**. v0.5.0 promised that `validity-audit-default-v0.3.0` would keep its meaning, and it still does; `validity-audit-default-v0.5.0` keeps its meaning too. Attestations already issued keep their original identifiers. New attestations carry the new identifier, whether or not their contract declares `fail_before_pass_after`.

### 3. Contract `schema_version` 0.6.0 is opt-in

`0.3.0` contracts are unchanged: the schema keeps rejecting `fail_before_pass_after` on a `0.3.0` contract. A contract that wants the field declares `schema_version: "0.6.0"`. An older tool reading a `0.6.0` contract rejects it explicitly instead of silently skipping the probe.

### 4. Environment requirement

Run the probe from an environment where this project is not importable from anywhere else. Checking the package name is not enough: an editable install of a different checkout can serve a submodule the probed worktree itself lacks, under the same name. This happened during this release's own validation, not in a hypothetical. A runtime module-origin audit now records every project module whose origin lies outside the run's worktree and faults the affected claim, but a clean environment is still the cheaper fix.

## What this does not prove

FBPA shows that one claimed test depends on one claimed fix. It does not show the test catches every bug of that kind, and it does not show the test targets the property a user actually cares about; that remains a fitness question. It is not mutation testing.

## Known limitations

See `docs/specs/probe-fail-before-pass-after.md` §9 for the full list. In short: `test_paths` decides what counts as the fix, so a fix placed inside the test directory is treated as test code; a test that only asserts a constant (a version string, for example) is `demonstrated` when the constant changes, which is technically correct and weak evidence; and existence checks are recognised only in the forms the spec lists, so one written through `__all__` or `inspect.getmembers` still counts as `demonstrated`.

## Migrating

**Contracts that want FBPA:** declare `schema_version: "0.6.0"` and add `fail_before_pass_after` with a `base`, a `head`, and at least one claim.

**Everyone else:** nothing changes in the field sense, and `0.3.0` contracts keep working. The policy identifier on new attestations changes regardless, because the identifier describes the policy code, not whether a given contract used the new field.

## Compatibility and boundaries

The attestation schema version is unchanged. `probe_version` moves to `0.6.0`, which moves the probe-report digest embedded in golden fixtures; every fixture that embedded the old `policy_id` or `probe_version` string was updated by re-running `prepare_run` / `finalize_run` against the golden case, not computed by hand. The task-contract schema gains one optional field and one new accepted `schema_version` value. Historical compatibility entry points remain present.

Still out of scope:

- mutation testing;
- cryptographic signing and issuer authentication;
- hosted provider adapters or API-key installation;
- certification of an agent, model, organization, or workflow.

## Reproduce it

```console
python -m pip install -e .
python golden_cases/self_contained/doc-bundle-01/run_case.py
```
