# Validity Audit v0.5.0

Validity Audit v0.5.0 closes a gap in its own landing path:

> **Can a reviewer-supplied field silently change the verdict, or silently escape it?**

Before this release, several fields in `reviewer_output.json` were accepted as long as they were well-formed, even when the policy engine had no rule for the value supplied. The verdict was still computed, but some findings were never actually judged. v0.5.0 rejects those values when the reviewer output is imported, or routes them to review, instead of letting them pass through.

The release keeps the same bounded assurance model: one task run, one contract, one digest-bound artifact set, and one explicitly unsigned validity attestation.

## Why this release exists

An audit of our own historical reviewer outputs found 119 distinct findings across 16 runs. 68 of them used an `error_class` slug the policy did not recognize. Every one of those 68, including 17 marked high severity, landed with `gate_effect: "none"`: the run reported `needs_review`, but the policy had never decided anything about those findings. The same pattern appeared in two consecutive review rounds of one project before anyone noticed.

## What changed

This release changes verdicts, so it ships under a new policy identifier, **`validity-audit-default-v0.5.0`**. v0.4.0 promised that `validity-audit-default-v0.3.0` would keep its meaning, and it still does. Attestations already issued keep the old identifier, and new attestations carry the new one.

### 1. `error_class` is validated at landing

`finding.error_class` must be one of the eight built-in classes (`correctness`, `evidence_tampering`, `fabrication`, `leakage`, `material_requirement_miss`, `unauthorized_action`, `fitness`, `maintainability`) or a class the task contract maps in `policy_overrides`. Any other value makes `finalize` fail with an error listing the offending finding ids and the full legal set. No attestation is written.

**Exit code changes from `3` (needs_review attestation) to `1` (operational error).** CI jobs that treated exit 3 as "a human should look" will now see exit 1 for this case.

### 2. Waiver issuer labels must be declared

The task contract gains an optional `waiver_issuers` array. If the reviewer output contains any waiver request, the contract must declare `waiver_issuers` and every waiver's `issuer` must appear in it, matched exactly. Otherwise `finalize` fails with exit `1`.

This **restricts which issuer labels are accepted. It does not authenticate who issued the waiver.** Attestations are still unsigned, and anyone who can write the reviewer output can type a listed label.

### 3. High-severity, unreproduced findings go to review

A finding with `severity: "high"` whose reproduction status is `unreproduced`, `not_reproducible`, or `not_attempted` now forces `needs_review` whatever its error class is. This includes advisory classes such as `fitness`, and classes overridden to `none`. Previously such a finding under an advisory class let the run `pass`. The attestation summary states which rule triggered.

Findings below high severity behave as before.

## Migrating

**Contracts that use waivers:** add the issuer labels you accept.

```json
{
  "waiver_issuers": ["release-owner"]
}
```

**Reviewer prompts and tooling:** give reviewers the eight legal `error_class` values, or declare any custom class in the contract's `policy_overrides`. A reviewer who invents a descriptive slug now stops the run instead of producing a hollow `needs_review`.

**Consumers of attestations:** branch on `overall_result.policy_id` if you compare outcomes across releases.

## Compatibility and boundaries

The attestation schema version is unchanged. The task-contract schema gains one optional field. Historical compatibility entry points remain present.

Still out of scope:

- cryptographic signing and issuer authentication;
- hosted provider adapters or API-key installation;
- global trust scores;
- certification of an agent, model, organization, or workflow.

## Reproduce it

```console
python -m pip install -e .
python golden_cases/self_contained/doc-bundle-01/run_case.py
```
