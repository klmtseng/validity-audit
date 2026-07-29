# Golden cases — public regression keys for the audit itself

An audit protocol is an evaluator, and a fixed evaluator can decay or be optimized against. Golden
cases freeze verified findings so a protocol change can be checked for regressions.

## What public keys can and cannot show

A public answer key supports:

- deterministic reproduction;
- regression monitoring;
- scorer and schema testing;
- worked examples.

Once a key is public, it does **not** support a new claim of cold-review recall. A cold-performance
claim requires never-published material, a defined corpus and scorer, false-positive reporting, and
documented contamination controls.

The historical reviews below were originally conducted before their keys were published. All future
runs against these checked-in keys are regression runs.

## Rules

- A genuinely cold reviewer must never see expected findings or the miss-ledger first.
- A hit is a semantic match, not necessarily verbatim.
- New reproducible findings beyond a frozen key are recorded separately; changing the key creates a
  new key version.
- Every expected finding states its threat tier, severity, and a reproduction recipe.
- Canonical severity values are `high`, `med`, and `low`.
- P1/P2/P3 and `advisory` are retained only as legacy metadata where historical context requires it.
- Alias records are excluded from all aggregate metrics.
- A new canonical record stores its key once, pins the key version and digest, and declares
  `excluded_from_metrics: false`.
- An alias stores no expected findings or key copy, points to one canonical `case_id`, and declares
  `excluded_from_metrics: true`.

## Canonical historical-case shape

```json
{
  "case_id": "example-2026-07",
  "record_type": "canonical",
  "domain_packs": ["content", "systems"],
  "expected_findings": [
    {
      "id": "P1",
      "tier": "T1",
      "checklist": "C1",
      "severity": "high",
      "finding": "...",
      "reproduce": "..."
    }
  ]
}
```

Alias records contain `canonical_case_id` and `excluded_from_metrics: true`; they do not duplicate
the answer key.

## Historical results and provenance

| Canonical case | Public domain packs | Key size | Original evidence | Current use |
|---|---|---:|---|---|
| `study-forge-2026-07` | content + systems | 6 | v1 `~2.5/6` was a retrospective structural-ceiling estimate; v2 measured `5/6` plus three bonus findings before publication | public-key regression |
| `rules-docs-2026-07` | docs | 5 | key seeded from an originally cold review; no v1 baseline | public-key regression |
| `doc-bundle-01` | docs | 1 | intentionally planted, fully checked-in self-contained target | public-key regression |

`content-pipeline-2026-07` is a deprecated alias for `study-forge-2026-07`. The two files previously
duplicated one audit event and must not be counted as independent cases.

### `study-forge-2026-07`

The v2 reviewer matched five of six expected findings. The miss was P4, a low-severity
maintainability finding. Both high-severity fabrication-class findings were caught. Three additional
issues were reported, including two reproduced anti-fabrication-gate defects.

Project notes said P1 and P6 entered a ledger, but no corresponding ledger data file is tracked in
this repository. Treat that statement as untracked historical process context, not independently
reproducible repository evidence.

P2 and P3 were originally mapped to a private fitness pack. v0.3 retains them as historical T3
expert findings but removes the unavailable pack from public routing and marks the checklist mapping
as historical/unmapped.

### `rules-docs-2026-07`

The original reviewer matched all five expected findings. Its P1/P2/P3 labels are retained as
`legacy_priority`; canonical severity is stored separately. Future runs are regression checks.

## Runnable public case

The two historical targets are not included in the public repository, so their findings cannot be
reproduced end to end here. `doc-bundle-01` is different: its target, contract, reviewer fixture,
versioned key, scoring rules, expected attestation, and runner are all checked in.

```console
python golden_cases/self_contained/doc-bundle-01/run_case.py
```

The checked-in reviewer fixture is primed and supports regression only. It does not convert this
public case into a cold-recall benchmark.
