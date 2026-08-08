# Validity Audit

**A self-falsification protocol and reference runtime for bounded, evidence-backed claims about agent-produced work.**

Most evaluation systems ask whether the agent output passes a check. Validity Audit asks a second question too: **has the checker demonstrated that it can fail when it should?** v0.4.0 adds standing positive, negative, and fault controls around representative home-grown verifiers so a green result is less likely to be a silent fail-open.

![Validity Audit architecture: bounded audit flow plus verifier challenge loop](docs/architecture.svg)

Validity Audit does not certify an agent, model, organization, or workflow globally. It produces an **unsigned validity attestation for one task run over one digest-bound artifact set**. The record says what was claimed, what evidence was reviewed, what reproduced findings triggered policy, and which exact bytes the result covers.

The project exists because static evaluators decay. Builders miss their own assumptions; reviewers can hallucinate findings; public benchmarks get optimized against. Validity Audit combines independent review, reproduction gates, an accreting miss ledger, public-key regression tests, and standing verifier challenges so the evaluator can be challenged too.

> **Maturity:** v0.4.0 is the current release. The bounded `prepare` / `finalize` audit path remains compatible with v0.3 records and policy identifiers. v0.4 adds three standing challenge families: deterministic probes, public-key scorer denominator integrity, and review-import / claim-link integrity. Signing, provider adapters, API-key installation, and global agent certification are not available.

## Quickstart: reproduce the public golden case

These are the same install and execution commands used by the offline CI job:

```console
python -m pip install -e .
python golden_cases/self_contained/doc-bundle-01/run_case.py
```

The second command runs `prepare` and `finalize`, verifies the complete unsigned attestation, and scores the imported reviewer fixture against a frozen key. Its final line is:

```text
Golden case PASS: expected fail attestation and 1/1 regression score reproduced
```

The apparent contrast is intentional: the audit correctly returns a blocking `fail` for the planted artifact defect, while the benchmark passes because that expected finding was reproduced. The case uses no API key; CI also blocks outbound socket access during execution.

## What v0.4 challenges

A checker is not trusted merely because it printed PASS. The v0.4 protocol distinguishes:

| Control | Expected behavior |
|---|---|
| Positive | known-good input must pass |
| Negative | known-bad input must fail |
| Fault | broken, missing, or malformed input must hard-fail rather than become a clean pass |

Three representative standing challenge families exercise the real production paths in tests and CI:

1. **Deterministic probes** — readable artifacts pass; broken Markdown, missing artifacts, and invalid text fail closed.
2. **Public-key scorer** — missing denominator-bearing fields are errors; explicit empty populations remain valid and distinct.
3. **Review import / claim linkage** — missing claim coverage, unknown finding links, and refuted claims without linked findings cannot produce a clean attestation.

This is deliberately not a claim that every verifier has been proven correct. The full contract, including skip accounting and its limits, is in [`protocol/VERIFIER_CHALLENGES.md`](protocol/VERIFIER_CHALLENGES.md).

## Run one audit

Create a JSON task contract that names one task, its bounded claims, repository-relative artifacts, domain packs, and any reason-bearing policy overrides. See [`schemas/examples/task_contract.json`](schemas/examples/task_contract.json) for a minimal example. Then prepare a fresh run directory:

```console
validity-audit prepare \
  --workspace . \
  --contract path/to/task_contract.json \
  --run-dir .validity-audit/runs/my-run \
  --review-context cold \
  --reviewer-kind human \
  --reviewer-label independent-reviewer \
  --operator-id local-operator
```

Give the emitted `review_bundle.json`—not the answer key or miss ledger—to an independent reviewer. Retain the raw transcript and collect JSON that validates against [`schemas/reviewer_output.schema.json`](schemas/reviewer_output.schema.json). Then finalize:

```console
validity-audit finalize \
  --workspace . \
  --run-dir .validity-audit/runs/my-run \
  --reviewer-output path/to/reviewer_output.json \
  --transcript path/to/raw_transcript.txt
```

`prepare` validates the contract, snapshots the exact artifact bytes, computes the digest chain, runs deterministic probes, and emits the provider-neutral review bundle. `finalize` refuses changed evidence, retains the raw transcript, imports findings without trusting reviewer-supplied policy results, applies the versioned policy, and writes:

- `attestation.json` — machine-readable unsigned attestation;
- `attestation.md` — human-readable report;
- `run_state.json` — durable lifecycle and evidence digests;
- an optional canonical receipt in `.validity-audit/attestations.jsonl`.

Every `prepare` requires a new or empty `--run-dir`. Equal inputs, ids, and timestamps produce equal digests in separate fresh directories; an existing evidence directory is never overwritten.

### Exit-code contract

| Code | Meaning |
|---:|---|
| `0` | prepare succeeded, or finalize produced `pass` / `pass_with_waiver` |
| `1` | invalid arguments, invalid input, or another operational error |
| `2` | finalize emitted a blocking `fail` attestation |
| `3` | finalize emitted a `needs_review` attestation |
| `4` | digest or provenance mismatch; no attestation emitted |

## What the output looks like

The human-readable report is deliberately short:

```markdown
# Unsigned Validity Attestation

- Task: `golden-doc-bundle-01`
- Status: **fail**
- Policy: `validity-audit-default-v0.3.0`

## Findings

- `incorrect-artifact-count` — **fail** — Details file overstates the audited artifact count

> This record is unsigned. It covers one task run and one artifact set;
> it does not certify an agent globally.
```

See the complete, schema-valid [`docs/attestation-example.json`](docs/attestation-example.json).

## Assurance layers

Validity Audit keeps different kinds of evidence separate rather than collapsing them into one score.

1. **Contract** — define the bounded claims, artifact set, domain packs, and policy overrides.
2. **Evidence** — snapshot exact artifact bytes, compute canonical digests, and run deterministic probes.
3. **Independent review** — provide a provider-neutral bundle to a human or model reviewer and retain the raw transcript.
4. **Reproduction and policy** — reproduced findings receive policy effects from versioned code, not from the reviewer.
5. **Attestation** — emit a machine-readable and human-readable unsigned record bound to the evidence chain.
6. **Verifier challenges** — exercise representative home-grown checkers with known-good, known-bad, and broken inputs so their own failure semantics are regression-tested.

## Review contexts and benchmark provenance

A `cold` review excludes answer keys, the miss ledger, and builder hint lists. A `primed` review records the sources used to prime the reviewer. Public golden cases are **regression evidence**, not fresh cold-review accuracy measurements: once the key is public, repeated success can demonstrate reproducibility and non-regression, but not independent recall.

Unexpected findings in public-key scoring are sent to adjudication rather than automatically counted as false positives. Accepted key changes require a new immutable key version.

## Default policy

The versioned `validity-audit-default-v0.3.0` policy remains the authority for v0.4 attestations; the release does not silently change v0.3 record semantics.

| Error class | Default gate effect |
|---|---|
| `correctness` | `fail` |
| `evidence_tampering` | `fail` |
| `fabrication` | `fail` |
| `fitness` | `advisory` |
| `leakage` | `fail` |
| `material_requirement_miss` | `fail` |
| `unauthorized_action` | `fail` |
| `maintainability` | `advisory` |

Unknown or unclassified error classes route to `needs_review`. Reproduced fail-class findings may be waived only through an explicit, time-bounded waiver with issuer and reason; the original policy result remains recorded.

## Audit the auditor

The miss ledger is append-only and records newly discovered misses, severities, sources, and follow-up actions. The public golden case turns accepted misses into regression memory. v0.4 adds standing verifier challenges so selected checkers also have executable positive, negative, and fault controls.

The public `old-coder` issue and merged PR linked from [`protocol/VERIFIER_CHALLENGES.md`](protocol/VERIFIER_CHALLENGES.md) are a motivating external adoption case for the fail-open pattern, not validation of this project as a whole.

## Compatibility

The historical entry points remain available:

- `protocol/injected_bug_recall.py`
- `examples/self_contained/run_demo.py`
- `protocol/ledger.py`

They were guaranteed through all v0.3.x releases, with earliest removal v0.4.0. They remain present in v0.4.0 for migration convenience but are deprecated; new integrations should use the canonical package and benchmark paths.

## Scope limits

Validity Audit is intentionally bounded. It does not currently provide cryptographic signatures, hosted reviewer integrations, API-key management, a global trust score, or certification of an agent/model/organization. Verifier challenges demonstrate that selected checking mechanisms respond correctly to selected controls; they do not prove that the specification measures everything that matters.

## License

MIT.
