# Changelog

All notable changes to this project will be documented in this file.

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

### Fixed

- Correct repository-relative documentation links.
- Mark referenced `engine_v2` helpers as planned rather than present.
- Preserve the legacy no-argument ledger behavior (`challenges`) in the compatibility shim.
