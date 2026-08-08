# Verifier challenges

A validity claim can fail even when every reported check is green. The check itself may be
fail-open, may silently skip inputs, or may produce a number that no longer measures the property
its name implies.

This document defines the v0.4 verifier-challenge contract for challenging **home-grown verifiers** and
wrappers whose result contributes to an audit conclusion. It does not make v0.3 attestations
stronger retroactively, and it does not claim that negative controls prove a specification is fit
for purpose.

## The question

For every home-grown verifier that can contribute evidence, ask:

> How do we know this verifier is capable of failing for the reason it claims to detect?

A passing verifier is evidence only after its failure semantics have themselves been exercised.

## Three controls

A verifier challenge should distinguish three cases.

| Control | Fixture | Required result | What it protects against |
|---|---|---|---|
| Positive control | known-good input | pass | a checker that can never pass |
| Negative control | known-bad input for the claimed property | fail | vacuous or disconnected checks |
| Fault control | broken invocation or unreadable / missing input | hard fail, never clean pass | fail-open error handling |

A tool-specific nonzero exit code is not automatically a semantic failure. The wrapper must
interpret the tool's documented exit-code contract explicitly. If an execution error, timeout, or
parse failure is indistinguishable from "property absent", the verifier is not fail-closed.

## Skip accounting

A verifier must not silently drop inputs that were in scope. If some inputs are unsupported,
unreadable, filtered, or skipped, the audit evidence should report at least:

- how many inputs were in scope;
- how many were actually checked;
- which inputs were skipped when identity matters;
- why each skip class occurred.

A clean result over an unknown denominator is not equivalent to a clean result over the declared
artifact set. A missing denominator-bearing field is also not equivalent to an explicitly declared
empty list: omission means the verifier does not know what population it is scoring.

## Standing versus one-off controls

One-off controls are useful during development, but a regression-prone verifier should keep a
standing challenge in tests or CI. The standing challenge must exercise the **real verifier or
wrapper**, not a copied implementation. Otherwise the challenge can stay green while the production
checker regresses.

Not every off-the-shelf tool needs a repository fixture. The requirement is strongest for:

- home-grown shell or Python gates;
- wrappers that reinterpret third-party exit codes;
- custom scorers and benchmark adapters;
- filters that decide which inputs count;
- evidence importers that can downgrade or discard failures.

### Current implementation status

`tests/test_probe_challenges.py` exercises `validity_audit.probes.run_probes` directly with:

- a clean artifact that must pass;
- a broken Markdown reference that must fail;
- a missing non-Markdown artifact that must fail closed rather than being reported readable;
- non-UTF-8 Markdown that must fail the link checker rather than crashing or disappearing.

`tests/test_benchmarks.py` challenges the public-key scorer's denominator semantics. The scorer must
distinguish an explicit empty `expected_findings`, `findings`, or `claim_results` list from a missing
field. Missing denominator-bearing fields are malformed evidence and must raise a scoring error
rather than being silently interpreted as zero observations.

`tests/test_runtime.py` challenges the real review-import path used by `finalize_run`. A complete
claim set must import successfully, while incomplete claim coverage, links to findings that were not
imported, and a refuted claim with no linked finding must fail before an attestation is emitted. This
keeps review evidence from becoming a clean record after linkage information is missing or invalid.

These controls are intentionally narrow. They do not imply that every verifier in the repository has
standing challenges yet.

## What this does not prove

Verifier challenges test the trustworthiness of the checking mechanism. They do **not** prove that
its target property is the right property.

A transcript can be non-empty yet semantically useless. A benchmark can be reproducible yet measure
the wrong objective. A specification can be implemented exactly and still omit what matters to the
user. Those remain review and fitness questions.

The protocol therefore keeps two questions separate:

1. **Did the verifier correctly implement its own pass/fail contract?**
2. **Does that contract measure a property that matters for the task?**

Negative controls address the first question. Independent review, reproduction, and explicit
fitness reasoning address the second.

## Evidence record

When verifier challenges are used, the audit record should identify:

- verifier name and version or digest where practical;
- positive, negative, and fault-control fixtures used;
- expected and observed outcomes;
- skipped-input accounting;
- whether the controls are standing CI/tests or one-off evidence;
- any verifier failure mode that remains untested.

A failed control invalidates evidence from that verifier until the checker is repaired and the
control passes again.

## Public motivating case

The distinction was sharpened by a public external contribution to
[`AmazingAng/old-coder` issue #1](https://github.com/AmazingAng/old-coder/issues/1). A fail-open class
was confirmed by the maintainer, who adopted explicit fail-closed rules. A follow-up contribution,
[`old-coder` PR #3](https://github.com/AmazingAng/old-coder/pull/3), turned the one-off checks into a
standing regression test covering a forbidden match, a clean input, and a broken scan.

This is an **external adoption case for the failure pattern**, not evidence that Validity Audit as a
whole is scientifically validated.
