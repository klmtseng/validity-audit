# Schemas

These [Draft 2020-12](https://json-schema.org/draft/2020-12) JSON Schemas define the two
machine-readable boundaries planned for Validity Audit v0.3:

- [`task_contract.schema.json`](task_contract.schema.json) — the bounded input for one
  audit run over one artifact set;
- [`attestation.schema.json`](attestation.schema.json) — the resulting **unsigned validity
  attestation**.

The schemas accept JSON instances directly. YAML may be used by a future runner after it
is parsed into the same JSON data model.

## Unit of assurance

One attestation covers exactly one task run and one artifact set. A workflow is a sequence
of attestations linked by `previous_run_ids`; v0.3 does not define a nested workflow-level
certificate and never certifies an agent globally.

## Task contract

The contract intentionally contains only:

- a task id;
- one or more explicit claims;
- repository-relative artifact paths;
- one or more domain-pack identifiers;
- optional, reason-bearing policy overrides.

Absolute paths and parent-directory traversal are rejected. Pack names remain open slugs:
pack discovery and compatibility validation are not part of PR 2.

## Unsigned attestation

The attestation binds its statement to:

- the task-contract digest;
- each artifact's digest and size;
- a canonical artifact-manifest digest;
- the exact review-bundle digest;
- the raw reviewer-transcript digest.

Unless the manifest rule below says otherwise, every `sha256` value is the lowercase
SHA-256 digest of the referenced file's exact bytes.

Any artifact digest mismatch voids the record. `signature` is required to be `null` in
v0.3 so the public term cannot imply signing, key identity, or supply-chain guarantees
that do not exist yet.

The finding taxonomy stores four separate axes:

| Axis | Canonical values |
|---|---|
| `severity` | `high`, `med`, `low` |
| `confidence` | `high`, `med`, `low` |
| `reproduction` | `reproduced`, `unreproduced`, `not_reproducible`, `not_attempted` |
| `gate_effect` | `fail`, `waiver`, `advisory`, `none` |

All fixed machine-readable enum values use `snake_case`. `gate_effect` represents policy
output. Until PR 3 exists, an operator records it; PR 3 must make the policy engine its
sole writer and bind `policy_id` to a real versioned rule set.

Overall dispositions are `pass`, `fail`, `pass_with_waiver`, and `needs_review`.
`not_attempted` is distinct from an attempted reproduction that failed, and—like every
non-reproduced state—requires `reproduction_notes`.

A waiver requires an issuer, reason, original policy result, issue time, and expiry. It
changes the effective gate result without erasing the result it overrode. The schema
rejects waivers attached to non-waiver findings.

Cold and primed reviews are visibly distinct. A primed review must name its priming
sources; a cold review cannot carry `priming_sources`.

`operator_id` and `reviewer.label` are descriptive labels in an unsigned record. They are
not authenticated identities. Cryptographic identity belongs to the future signing work.

## Canonical artifact-manifest digest

To compute `artifact_manifest.manifest_sha256`:

1. sort the `artifacts` array by `path`;
2. encode the sorted array as UTF-8 JSON with keys sorted, no insignificant whitespace,
   and non-ASCII characters preserved;
3. compute SHA-256 over those bytes.

In Python, the JSON encoding step is:

```python
json.dumps(artifacts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
```

## Examples and semantic checks

[`examples/`](examples/) contains a contract, review bundle, reviewer transcript, and
unsigned attestation. Their digests are real and pinned by tests.

JSON Schema cannot express every cross-document invariant. The tests additionally verify:

- claim ids and finding ids are unique;
- every contract claim has exactly one attestation result;
- every referenced finding exists;
- task ids agree across the example records;
- file, bundle, transcript, contract, and manifest digests match their bytes;
- run timestamps are chronologically sensible.

JSON Schema can require a waiver expiry to be a date-time, but it cannot compare that
value with the waiver or attestation issue time. The PR 3 runner must enforce:
`waiver.issued_at <= attestation.issued_at < waiver.expires_at`.

The example is a schema fixture, not a claim that the repository as a whole has been
certified.
