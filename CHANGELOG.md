# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

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
