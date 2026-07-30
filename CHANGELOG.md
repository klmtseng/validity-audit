# Changelog

All notable changes to this project will be documented in this file.

## [0.3.0] — 2026-07-30

### Fixed

- **Markdown injection (tag-blocking, extended):** reviewer-controlled `finding.title`
  values are sanitized before insertion into `attestation.md`.  ASCII newlines and Unicode
  line/paragraph separators (U+000B, U+000C, U+0085, U+2028, U+2029) are collapsed to a
  space; all CommonMark inline punctuation characters (`\`, `[`, `]`, `(`, `)`, `_`, `*`,
  `~`, `<`, `>`, `!`, `&`, backtick) are backslash-escaped so links, images, raw HTML,
  HTML comments, and emphasis spans render as literal text.  Leading markdown structural
  characters (`#`, `-`, `>`, `|`, backtick) are additionally escaped for belt-and-suspenders
  block-level protection.  The `reviewer_output` schema now enforces a single-line
  constraint on `title` (pattern `^[^\n\r  ]*$`) to block
  Unicode line-separator bypass at the schema layer.
- **Receipt-digest overclaim (tag-blocking):** documentation incorrectly stated that the
  digest chain covers the "final attestation receipt".  The receipt ledger
  (`.validity-audit/attestations.jsonl`) holds the attestation SHA-256 but is itself a
  mutable append-only file not included in the chain.  README corrected to reflect the
  actual boundary.
- **Dev-install test collection failure (tag-blocking):** `tests/test_benchmarks.py`
  imported `benchmarks/injected/run.py`, which hard-imported `numpy` (a `quant` extra).
  A fresh `.[dev]` install without `quant` caused collection to abort.  Fixed by guarding
  the two numpy-dependent benchmark tests with `pytest.importorskip("numpy")`; the tests
  are skipped when numpy is absent and collected normally when it is present.

## Unreleased

### Added

- Add Draft 2020-12 schemas for the minimal task contract and unsigned validity attestation.
- Add digest-bound schema examples and regression tests for taxonomy, waivers, review context,
  signatures, and cross-document integrity.
- Standardize fixed schema vocabulary on `snake_case`, including `not_attempted`,
  `pass_with_waiver`, and `needs_review`.
- Preserve the original policy result and issue time inside every waiver.
- Fail loudly when the optional JSON Schema `date-time` format checker is unavailable.
- New docs-pack check D7 "Claimed vs. delivered": feature claims must be verified by
  a live run or shipping signals (negative signals decisive, positive ones just
  another claim), not by file existence.
- Add the two-stage `validity-audit prepare` / `finalize` CLI.
- Bind contracts, artifacts, canonical manifests, probe reports, review bundles, and raw
  reviewer transcripts into one digest-checked run.
- Add deterministic artifact and Markdown-link probes, approved run-state vocabulary and
  history, provider-neutral reviewer-output import, and transcript retention.
- Add the versioned `validity-audit-default-v0.3.0` error-class policy as the sole writer
  of finding gate effects.
- Add human- and machine-readable unsigned attestations, an append-only attestation
  receipt ledger, packaged schema resources, and a frozen self-contained demonstration.
- Add a public benchmark harness with a scored, self-contained golden regression case,
  frozen versioned key, explicit adjudication rules, and an offline CI execution path.
- Add the v0.3 release-candidate README, worked unsigned-attestation JSON, and five-layer
  architecture diagram with explicit adoption-mode maturity labels.

### Changed

- Begin the v0.3 packaging and test foundation.
- Complete the default fail-class policy with the approved `snake_case` taxonomy; route
  unclassified and `other` findings to `needs_review` instead of advisory pass-through.
- Implement and document the stable CLI exit-code contract (`0` through `4`).
- Define idempotent preparation as deterministic output across fresh run directories;
  existing evidence directories remain immutable.
- Validate canonical ledger severities instead of silently ranking unknown values as zero.
- Preserve the historical `protocol/ledger.py` command through a compatibility shim.
- Correct public benchmark provenance and distinguish public-key regression from cold evaluation.
- Mark the duplicated content-pipeline golden case as a metric-excluded alias.
- Relocate the injected-bug floor demonstration to `benchmarks/injected/run.py` while
  retaining the historical protocol path as a v0.3 compatibility shim.
- Promote the self-contained example to `golden_cases/self_contained/doc-bundle-01`;
  retain its historical runner path as a v0.3 compatibility launcher.
- Classify reproduced `fitness` findings as advisory in the default policy, resolving the
  previously omitted plan §8 category without changing the v0.3 policy identifier.
- Document the legacy shim support window through all v0.3.x releases, with v0.4.0 as the
  earliest removal point and a required changelog migration note.

### Fixed

- Correct repository-relative documentation links.
- Mark referenced `engine_v2` helpers as planned rather than present.
- Preserve the legacy no-argument ledger behavior (`challenges`) in the compatibility shim.
