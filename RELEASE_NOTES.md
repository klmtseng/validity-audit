# Validity Audit v0.4.0

Validity Audit v0.4.0 adds one question to the bounded audit path introduced in v0.3:

> **Has the checker demonstrated that it can fail when it should?**

The release keeps the same bounded assurance model: one task run, one contract, one digest-bound artifact set, and one explicitly unsigned validity attestation. It does not certify an agent, model, workflow, or organization globally.

## What changed

v0.4 introduces a verifier-challenge contract for home-grown checks and wrappers. A representative verifier should be exercised with:

- a **positive control** that must pass;
- a **negative control** containing the defect it claims to detect and therefore must fail;
- a **fault control** where broken, missing, malformed, or unreadable input must hard-fail rather than turn into a clean pass;
- explicit accounting when in-scope inputs are skipped.

Three standing challenge families now exercise real production paths in tests and CI.

### 1. Deterministic probes

The artifact/Markdown probe path no longer reports readability before it has actually read the artifact. Standing controls cover a clean artifact, a broken Markdown reference, a missing non-Markdown artifact, and invalid UTF-8 Markdown. Broken inputs fail closed instead of disappearing behind a green result.

### 2. Public-key scorer denominator integrity

The frozen-key scorer previously used empty-list defaults for some denominator-bearing fields. That made a missing population indistinguishable from an explicit declaration of zero observations in direct scorer use.

v0.4 requires `expected_findings`, reviewer `findings`, and `claim_results` to be present lists. Explicit `[]` remains valid and distinct; omission is malformed evidence and raises a scoring error.

### 3. Review import and claim linkage

The runtime already enforced important import/linkage invariants. v0.4 turns them into standing regression challenges against the real `finalize_run` path:

- complete claim coverage can finalize;
- missing claim coverage cannot produce an attestation;
- a claim cannot link to a finding that was never imported;
- a refuted claim cannot finalize without a linked finding.

These controls protect evidence-link integrity without changing the v0.3 policy semantics.

## Architecture

The README architecture now shows two connected paths: the normal bounded audit pipeline and a verifier-challenge feedback loop. The latter feeds known controls, coverage accounting, standing challenges, and regression memory back into the mechanisms that produce green checks.

## External motivating case

The verifier-challenge framing was sharpened by a public contribution to `AmazingAng/old-coder`. Its maintainer confirmed a fail-open checker class, adopted explicit fail-closed rules, and merged a follow-up regression test covering a forbidden match, a clean input, and a broken scan.

This is an external adoption case for the failure pattern. It is not evidence that Validity Audit as a whole has been scientifically validated.

## Compatibility and boundaries

v0.4.0 keeps the v0.3 attestation schema version and `validity-audit-default-v0.3.0` policy identifier. The release hardens verifier behavior and adds regression controls; it does not silently reinterpret existing v0.3 records.

The historical compatibility entry points remain present for migration convenience, although v0.4.0 was the earliest documented removal point. New integrations should use the canonical package and benchmark paths.

Still out of scope:

- cryptographic signing;
- hosted provider adapters or API-key installation;
- global trust scores;
- certification of an agent, model, organization, or workflow;
- a claim that every verifier in the repository has been proven correct.

## Reproduce it

```console
python -m pip install -e .
python golden_cases/self_contained/doc-bundle-01/run_case.py
```

The golden case is intentionally a regression fixture. Its expected audit result is a blocking `fail` because the artifact contains a planted defect; the benchmark passes when that expected finding is reproduced. CI also runs this path with common API-key variables removed and outbound Python socket access blocked.
