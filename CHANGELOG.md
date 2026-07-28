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

### Changed

- Begin the v0.3 packaging and test foundation.
- Validate canonical ledger severities instead of silently ranking unknown values as zero.
- Preserve the historical `protocol/ledger.py` command through a compatibility shim.
- Correct public benchmark provenance and distinguish public-key regression from cold evaluation.
- Mark the duplicated content-pipeline golden case as a metric-excluded alias.

### Fixed

- Correct repository-relative documentation links.
- Mark referenced `engine_v2` helpers as planned rather than present.
- Preserve the legacy no-argument ledger behavior (`challenges`) in the compatibility shim.
