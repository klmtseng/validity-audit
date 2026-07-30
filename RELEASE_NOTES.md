# Validity Audit v0.3.0

> **Approved release notes.** Reviewed through the three-party loop (PR #8, verdict `GO` at
> `be7b85de`) and approved by the project owner, who authorized the `v0.3.0` tag and release.

Validity Audit v0.3.0 turns the repository's self-falsification protocol into a runnable,
provider-neutral reference path for one bounded audit:

> one task run, one contract, one digest-bound artifact set, and one explicitly unsigned
> validity attestation.

It does **not** certify an agent, model, workflow, or organization globally. The release is
designed to preserve the evidence boundary: what was claimed, which exact bytes were reviewed,
what the reviewer received, what could be reproduced, and which policy rule produced the result.

## What v0.3 delivers

### A two-stage audit CLI

The packaged `validity-audit` command now supports:

1. `prepare` — validates the task contract, snapshots artifacts, computes the digest chain,
   runs deterministic probes, and emits a provider-neutral review bundle;
2. `finalize` — rechecks the evidence, imports structured reviewer findings and the raw
   transcript, applies the versioned policy, and emits an unsigned attestation.

The stable exit-code contract distinguishes pass (`0`), operational error (`1`), policy fail
(`2`), needs-review (`3`), and digest/provenance mismatch (`4`).

### Versioned machine-readable boundaries

Draft 2020-12 JSON Schemas define:

- a minimal task contract for one audit run;
- provider-neutral reviewer output;
- an unsigned validity attestation.

The attestation binds the contract, individual artifacts, canonical artifact manifest, probe
report, review bundle, and raw transcript through SHA-256 digests. The receipt ledger is a
downstream copy that holds the attestation SHA-256; it is itself a mutable append-only file and
is not part of the digest chain. In v0.3, `signature` is required to be `null`.

Reviewer-controlled `finding.title` values are constrained to a single line by schema and
neutralised to literal text when rendered into `attestation.md`; they cannot form headings,
links, images, or raw HTML in the human-readable record.

### Fail-closed policy and durable run states

`validity-audit-default-v0.3.0` is the sole writer of finding `gate_effect`.

- Reproduced correctness, evidence-tampering, fabrication, leakage, material-requirement-miss,
  and unauthorized-action findings fail by default.
- Reproduced fitness and maintainability findings are advisory by default.
- Unknown and `other` classes route to `needs_review` unless an explicit, reason-bearing
  contract override classifies them.
- A waiver retains the underlying finding and original policy result, and requires issuer,
  reason, issue time, and expiry.

Runs persist the approved lifecycle: `preparing`, `awaiting_review`, `review_imported`, then
`completed`, `failed`, or `needs_review`.

### Public regression and offline reproducibility

The public benchmark harness includes:

- the relocated planted-defect floor at `benchmarks/injected/run.py`;
- a self-contained scored golden case at
  `golden_cases/self_contained/doc-bundle-01`;
- a frozen, versioned public key and explicit scoring/adjudication rules;
- expected findings, score, and unsigned attestation;
- a CI path that clears common API-key variables, blocks outbound Python socket access, and
  runs prepare, finalize, attestation comparison, and regression scoring end to end.

Unexpected findings are marked for adjudication rather than automatically counted as false
positives. Accepted key changes require a new immutable key version.

### Documentation as an executable contract

The README now includes a CI-backed quickstart, sample report, worked attestation, five assurance
layers, three adoption modes with maturity labels, cold-versus-regression distinctions, the
default policy, limitations, threat model, compatibility window, and roadmap.

Documentation tests keep the quickstart aligned with CI, the policy tables aligned with code,
the worked attestation aligned with the golden fixture and schema, and the architecture diagram
aligned with the five layers and three modes.

## Three-party review receipts

v0.3 was built through a three-party control loop:

- **Project owner:** approved scope, adjudicated design choices, and retained exclusive authority
  over merge and release decisions.
- **Codex:** implemented bounded PRs, published exact reviewed commit and tree SHAs, supplied
  validation reports, and responded to review conditions.
- **Claude Code:** independently inspected or reproduced each review target and returned
  `GO` / `REVISE` decisions against named commits.

GitHub labels acted as the baton:

- `ai:codex-action` — implementation or revision is assigned to Codex;
- `ai:claude-review` — the exact checkpoint is ready for independent review;
- `owner:decision` — review is complete and the next action belongs to the owner.

The principal receipts are:

| Receipt | Delivered control | Review outcome |
|---|---|---|
| [PR #1](https://github.com/klmtseng/validity-audit/pull/1) | packaging, canonical ledger taxonomy, tests, CI, provenance correction, alias/dedup rules, compatibility foundation | Claude Code `GO` with two conditions folded into the final commit; merged as `e8f7c803` |
| [PR #2](https://github.com/klmtseng/validity-audit/pull/2) | task-contract and unsigned-attestation schemas | initial `REVISE`; R1–R4 resolved and revalidated; merged as `39d0d3b7` |
| [PR #4](https://github.com/klmtseng/validity-audit/pull/4) | D7 claimed-versus-delivered documentation check | cold and primed/hot audit findings folded into the shipped rule; merged as `683d631c` |
| [PR #5](https://github.com/klmtseng/validity-audit/pull/5) | two-stage runtime, digest chain, reviewer import, policy engine, run states, output receipts | C1–C5 revised and independently reproduced; merged through `9637208f` and `74172ab9` |
| [PR #6](https://github.com/klmtseng/validity-audit/pull/6) | benchmark relocation, scored golden case, offline reproducibility CI | Claude Code `GO`, no conditions; merged as `fa30df92` |
| [PR #7](https://github.com/klmtseng/validity-audit/pull/7) | release-candidate README, worked attestation, architecture diagram, N1 fitness policy, shim window | stacked `GO`, then final retarget `GO` on an identical tree; merged as `fa055647` |
| [PR #10](https://github.com/klmtseng/validity-audit/pull/10) | pre-tag fixes from the [issue #9](https://github.com/klmtseng/validity-audit/issues/9) two-AI cross-audit: version identity, attestation markdown-injection neutralisation (block-level and inline), receipt-digest wording, dev-install test collection | roles reversed for this PR: Claude Code implemented; a fresh-context adversarial reviewer returned `GO` after a follow-up closed inline/Unicode gaps; Codex was unavailable, so no heterogeneous second view — disclosed on the PR; merged as `f6946496` |

The runtime scope was agreed in
[planning issue #3](https://github.com/klmtseng/validity-audit/issues/3). PR bodies and review
threads retain the exact baseline, reviewed SHA, tree SHA, test report, reviewer response, and
owner-controlled merge boundary.

## Results and provenance

These results support different claims and must not be combined into one headline accuracy
number.

| Result | Provenance label | What it supports |
|---|---|---|
| **142/142 tests passed** on the v0.3.0 pre-tag tree (124/124 on the earlier release-candidate tree) | release-gate verification; Python 3.12 clean environment, with CI also covering Python 3.11/3.12 and offline regression | implementation and regression checks passed; this is not evaluator accuracy |
| **1/1 expected finding matched**, 0 missed, 0 unexpected; expected policy result `fail` | public-key regression; frozen checked-in key and primed reviewer fixture | the current protocol retains this known catch; not cold-review or model-performance evidence |
| **6/6 mechanical planted defects caught**, **0/6 false alarms** on paired clean cases | deterministic planted benchmark; deliberately easy mechanical cases | a fixed mechanical smoke test for deterministic probes, not general precision or recall |
| **0/5 reasoning-level planted defects caught**; **6/11 overall floor** | deterministic planted benchmark | deterministic checks do not replace independent reasoning review |
| Historical **~2.5/6** | retrospective structural-ceiling estimate of the v1 protocol; not a measured cold run | historical design comparison only |
| Historical **5/6** | measured before the key became public; the material is now public | historical measured result; future runs on that key are regression runs |

The self-contained case reproduces without a model API key. During the dedicated CI execution,
the Python process and its child Python processes run with outbound socket access blocked after
checkout and dependency installation. Checkout and dependency installation are not claimed to be
offline.

## Limitations

- **Unsigned output:** v0.3 records are integrity-bound but not identity-signed. Operator and
  reviewer labels are descriptive, not authenticated identities.
- **Bounded assurance:** an attestation applies only to one run and one artifact set. Linked run
  ids do not create a workflow certificate.
- **Operator in the loop:** v0.3 generates and imports review material but does not call a model,
  manage API keys, or enforce model-family independence.
- **Reviewer fallibility:** reviewers can miss defects, share builder blind spots, or receive
  contaminated context. Bundle and transcript digests record the boundary but cannot prove the
  reviewer followed it.
- **Public-key overfitting:** checked-in keys measure regression. Cold-performance claims require
  never-published material, a defined denominator and scorer, false-positive accounting, and
  contamination controls.
- **Small deterministic probe set:** current runtime probes cover artifact readability and
  relative Markdown links. The 0/5 reasoning benchmark is an explicit warning against treating
  probes as a complete evaluator.
- **No signing or supply-chain identity:** byte mismatch can be detected, but v0.3 does not prove
  who created an artifact, who ran the audit, or whether the runner itself was trustworthy.
- **No multi-file crash transaction:** individual evidence writes are atomic and ledger
  duplicates are preflighted, but v0.3 does not promise rollback across every output.
- **No provider adapters or embedded-key installation:** plugin distribution, provider execution,
  user-key management, and direct model integration remain future work.

## Compatibility and shim deprecation window

The following legacy paths remain supported throughout all v0.3.x releases:

| Legacy path | Canonical replacement |
|---|---|
| `protocol/injected_bug_recall.py` | `benchmarks/injected/run.py` |
| `examples/self_contained/run_demo.py` | `golden_cases/self_contained/doc-bundle-01/run_case.py` |
| `protocol/ledger.py` | `validity-audit-ledger` or `validity_audit/ledger.py` |

The earliest permitted removal is v0.4.0. Any removal requires both a changelog entry and a
migration note. Compatibility behavior remains covered by CI for the v0.3 line.

## Release boundary

Merging these notes does not publish v0.3.0. The tag and GitHub Release remain separate,
owner-authorized actions. No package publication, release asset, or social announcement is
created by the release-notes PR.
