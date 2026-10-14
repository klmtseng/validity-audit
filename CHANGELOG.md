# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- **Evidence discipline (schema 0.7.0), adapted from three REA (morluto/rea) evidence primitives**
  (`validity_audit/evidence.py`):
  - *Required evidence kind:* contract claims may declare `required_evidence_kind`; a `supported`
    outcome counts only evidence whose kind satisfies it under a fixed substitution table
    (`command` satisfies `command`, `file_line`, `note`; `file_line` satisfies `file_line`, `note`;
    `digest` satisfies only `digest` and `note`; `note` satisfies only `note`).
  - *Claim binding:* 0.7.0 reviewer-output evidence carries `covers_claim_ids`; evidence counts
    toward a claim only when it names that claim. Unknown claim ids and divergent reuse of one
    evidence id are rejected.
  - *Absence coverage:* claims and findings may declare `assertion: "absence"`; evidence carries a
    `coverage` proof (`scope`, `status`, `truncated`, `omitted_count`). Without a complete proof an
    absence claim cannot be `supported` and an absence finding is gated as unreproduced. An absence
    claim that also declares `required_evidence_kind` needs one evidence item that satisfies the kind
    and carries the complete coverage. An unproven absence finding is named in the summary and the
    Markdown report under every disposition, including `pass`. A reproduced fail-class finding
    marked as an absence without coverage moves from `fail` to `needs_review` (intended).
  - *Refutations:* under a 0.7.0 reviewer output, a `refuted` claim with no claim-bound evidence is
    downgraded to `inconclusive` (`reviewer_outcome: "refuted"`) and does not force its findings to
    `fail`. A bound refutation needs no particular kind or complete search; an absence finding
    backing it is recorded `absence_coverage: "not_required"` and still fails.
  - Downgrades keep the reviewer's `rationale` verbatim; the reasons live only in `evidence_gate`.
    Downgrades are named in the summary and report under every disposition. Unproven absence
    findings record `effective_reproduction: "unreproduced"` next to the reviewer's `reproduction`.
    A waiver on a fail the discipline withheld (unproven absence finding, or a finding cited only by
    an unbound, downgraded refutation) is kept as `unapplied_waiver` with `not_applied_because`
    (`absence_coverage_unproven` / `refutation_unbound`), run `needs_review`, instead of rejecting
    the run. Evidence-id reuse compares `covers_claim_ids` as a
    set.
  - 0.7.0 review bundles carry `instructions.evidence_discipline`, explaining these requirements
    to the reviewer; the instructions in bundles for 0.3.0/0.6.0 contracts are unchanged.
- Attestation schema records the new policy outputs: `reviewer_outcome` + `evidence_gate` on a
  downgraded claim result, `absence_coverage` on an absence finding, and the new evidence fields.
- `tests/test_policy_matrix.py`: enumerates 3616 schema-valid combinations (contract version x
  reviewer-output version x claim outcome x binding x claim requirement x evidence kind x finding
  shape x severity x cited x waiver, plus two-claim two-finding combinations) and asserts no new
  rejections versus the legacy evaluation, no legacy rejection accepted, no move toward `pass`
  except the named `fail` -> `needs_review` moves, and per-finding gate invariants.
- `protocol/matrix_mutants.py` (new CI step "Matrix mutation regression"): plants five known policy
  bugs (M1-M5) into temporary copies and exits 0 only if the matrix test catches every one.
- A waiver on a finding the reviewer declared unreproduced is rejected by the general waiver rule
  even when an unbound refutation cites it (it was briefly accepted as `refutation_unbound`).
- `tests/test_evidence_discipline.py`: per primitive, a negative control that the previous behavior
  accepts (or fails on an unproven absence) and the new behavior blocks, plus positive controls.

### Changed (breaking)

- **Policy identifier bumped to `validity-audit-default-v0.7.0`:** a 0.7.0 contract or reviewer
  output can now turn a reviewer-`supported` claim into `inconclusive` (run `needs_review`) and keep an
  uncovered absence finding from deciding `fail`. `ERROR_CLASS_EFFECTS` is unchanged. 0.3.0/0.6.0
  contracts produce the same dispositions as before only when the reviewer output is also 0.3.0; a
  0.7.0 reviewer output on such a contract turns on claim binding and absence gating.
- Contract `schema_version` accepts `0.7.0`; reviewer-output `schema_version` accepts `0.7.0`. A 0.7.0
  contract requires a 0.7.0 reviewer output. The attestation `schema_version` stays `0.3.0`, with the
  new fields optional (same approach as FBPA's `finding_type`).
- The review bundle embeds the reviewer-output schema, so every bundle's bytes and digest changed
  (for all contract versions), and runs prepared by an earlier release cannot be finalized by this
  one. The golden
  `expected_attestation.json` and `docs/attestation-example.json` were updated for the new
  `bundle_sha256` and `policy_id` only.

## [0.6.0] — 2026-10-05

### Added

- **Deterministic fail-before / pass-after probe (FBPA):** an optional task-contract field,
  `fail_before_pass_after`, lets a contract claim that a specific test fails at a `base` commit and
  passes at a `head` commit. The probe checks this by running the claimed test against both
  commits under `git worktree` + pytest + JUnit XML; it never calls an LLM. `intent: "fixes"` claims
  must fail at `base` and pass at `head`; `intent: "characterizes"` claims only need to pass at
  `head`. A required runtime module-origin audit (spec §2, amendment 6) catches an editable install
  of a different checkout serving a submodule the probed worktree itself lacks. See
  `docs/specs/probe-fail-before-pass-after.md` and the README section "Deterministic fail-before /
  pass-after probe (FBPA)".
- Add the FBPA probe's own standing positive, negative, and fault controls
  (`tests/test_fbpa_probe.py`, spec §6), including a per-item coverage self-check that compares
  (`==`, never `in`) the exact verdict and finding-type set each control triggers against its
  expected set, and a dedicated control for the editable-install-finder failure mode found during
  validation.
- Add the S2 historical validation of FBPA: `docs/specs/fbpa-history-v0.5.0.md` (generated, over all
  21 merged PRs in this repository) and `docs/specs/fbpa-history-adjudication-v0.5.0.md` (hand
  adjudication of every row). Result: 135 claims, 34 demonstrated, 24 base_passes, 35 absence_only,
  42 inconclusive, 0 faults; 2 weak tests found (PR #10, PR #1); PR #23 has a policy change
  (high-severity-and-unreproduced forcing `needs_review`) that no test guards, shown by a mutation
  that left the full suite green.

### Changed (breaking)

- **Policy identifier bumped to `validity-audit-default-v0.6.0`:** `ERROR_CLASS_EFFECTS` itself is
  unchanged, but the new `fail_before_pass_after` field can turn a previously accepted contract into
  a `fail`, which is a change in verdict semantics — the same reason the policy identifier changed
  for v0.5.0 above — so the policy carries a new identifier instead of silently reinterpreting
  existing records under the old one.
- **Contract `schema_version` now also accepts `0.6.0`:** `0.3.0` contracts keep rejecting
  `fail_before_pass_after` (an `if`/`then`/`false` schema branch); `0.6.0` contracts may declare it.
  An older tool reading a `0.6.0` contract rejects it explicitly instead of silently skipping the
  probe.
- **`probe_version` bumped to `0.6.0`:** this moves the probe-report digest embedded in golden
  fixtures. Every fixture embedding the old `policy_id` or `probe_version` string was grepped before
  being changed: `golden_cases`' `expected_attestation.json` and `docs/attestation-example.json` each
  needed two field updates — `policy_id`, and `review.bundle_sha256` (the review bundle embeds
  `probe_report`, whose digest moved with `probe_version`). Both new values were produced by
  actually re-running `prepare_run` / `finalize_run` against the golden case, not computed by hand.

## [0.5.0] — 2026-10-02

### Changed (breaking)

- **Policy identifier bumped to `validity-audit-default-v0.5.0`:** the three behaviors
  below change landing-time semantics relative to every prior `validity-audit-default-v0.3.0`
  record, so the policy now carries a new identifier instead of silently reinterpreting
  v0.3 records under the old one. `overall_result.policy_id` on every new attestation is
  `validity-audit-default-v0.5.0`.
- **Unclassified `error_class` now a hard operational error, not a `needs_review`
  attestation:** `finding.error_class` values outside `ERROR_CLASS_EFFECTS` or a contract
  `policy_overrides` entry used to land as `gate_effect: "none"` with a `needs_review`
  disposition (exit code `3`, attestation emitted). They now raise a `PolicyError` naming
  the offending finding ids and the full legal class set; `finalize` emits no attestation
  at all and the CLI exits `1`.
- **Waiver issuer labels must be declared in the contract:** a new optional task-contract
  field, `waiver_issuers`, lists the issuer labels a waiver may carry. This restricts
  accepted labels; it does not authenticate issuer identity (attestations remain unsigned). A
  waiver request against a contract that omits `waiver_issuers`, or whose issuer is not
  listed, is rejected fail-closed (`PolicyError`, exit code `1`, no attestation) instead of
  accepting whatever issuer string the reviewer output supplied.
- **High-severity unreproduced findings now force `needs_review` regardless of error
  class:** a high-severity finding that was never reproduced used to land as plain
  `advisory` (and the run could `pass`) whenever its error class defaulted to advisory
  (e.g. `fitness`). It now forces `needs_review` regardless of error class, including
  under an explicit `policy_overrides` entry of `gate_effect: "none"`. Lower-severity
  unreproduced advisory findings are unaffected.

## [0.4.0] — 2026-08-08

### Added

- Add the v0.4 verifier-challenge protocol: positive, negative, and fault controls plus skip accounting for home-grown verifiers.
- Add standing fail-closed challenges for deterministic artifact and Markdown probes.
- Add standing denominator-integrity challenges for the frozen public-key regression scorer; missing populations are errors rather than implicit empty lists.
- Add standing review-import and claim-linkage challenges covering complete claim coverage, unknown finding links, and refuted claims without linked findings.
- Add a v0.4 architecture diagram that shows the bounded audit pipeline and the verifier-challenge feedback loop.
- Add the external-repository-intake domain pack (`domains/external-repo.md`, X1–X8), including claims-surface and pre-execution safety checks. It ships without a public golden key because its motivating source case is not a deterministic public fixture.

### Changed

- Mark post-v0.3 master development with an explicit development version, then promote the package to `0.4.0` for this release.
- Make the README lead with the verifier-challenge thesis and document the three implemented standing challenge families.
- Keep the v0.3 attestation schema and `validity-audit-default-v0.3.0` policy identifier unchanged; v0.4 hardens verifier behavior without silently changing existing record semantics.
- Keep the historical v0.3 compatibility entry points in v0.4.0 for migration convenience while marking them deprecated.

### Fixed

- Fail closed when deterministic probes cannot read an artifact instead of reporting an unconditional readability pass.
- Fail closed when the public-key scorer is missing `expected_findings`, reviewer `findings`, or `claim_results`; an explicit empty list remains a distinct valid declaration.
- Remove release-identity drift where post-v0.3 master changes still identified themselves as package version `0.3.0`.

## [0.3.0] — 2026-07-30

### Fixed

- **Markdown injection (tag-blocking, extended):** reviewer-controlled `finding.title` values are sanitized before insertion into `attestation.md`. ASCII newlines and Unicode line/paragraph separators are collapsed to a space; CommonMark inline punctuation is escaped so links, images, raw HTML, comments, and emphasis render as literal text. The reviewer-output schema enforces a single-line title constraint.
- **Receipt-digest overclaim (tag-blocking):** documentation previously overstated the digest boundary. The receipt ledger holds the attestation SHA-256 but is itself mutable and is not part of the digest chain.
- **Golden-case fixture regenerated after schema tightening:** the review bundle embeds the reviewer-output schema, so the title constraint changed its digest. The expected attestation and worked example were refreshed; the scoring key was unchanged.
- **Dev-install test collection failure (tag-blocking):** numpy-dependent injected-benchmark tests now skip cleanly when the optional quant extra is absent instead of aborting collection.

### Added

- Add Draft 2020-12 schemas for the minimal task contract, reviewer output, and unsigned validity attestation.
- Add the two-stage `validity-audit prepare` / `finalize` CLI.
- Bind contracts, artifacts, canonical manifests, probe reports, review bundles, and raw reviewer transcripts into one digest-checked run.
- Add deterministic artifact and Markdown-link probes, durable run-state vocabulary, provider-neutral reviewer-output import, and transcript retention.
- Add the versioned `validity-audit-default-v0.3.0` error-class policy as the sole writer of finding gate effects.
- Add human- and machine-readable unsigned attestations, an append-only attestation receipt ledger, packaged schema resources, and a frozen self-contained demonstration.
- Add a public benchmark harness with a scored golden regression case, frozen versioned key, explicit adjudication rules, and offline CI execution.

### Changed

- Standardize fixed schema vocabulary on `snake_case`.
- Preserve original policy results and issue times inside waivers.
- Implement and document the stable CLI exit-code contract (`0` through `4`).
- Define idempotent preparation as deterministic output across fresh run directories; existing evidence directories remain immutable.
- Correct public benchmark provenance and distinguish public-key regression from cold evaluation.
- Mark the duplicated content-pipeline golden case as metric-excluded alias.
- Classify reproduced `fitness` findings as advisory in the default policy.
- Document the legacy shim support window through all v0.3.x releases, with v0.4.0 as the earliest removal point.
