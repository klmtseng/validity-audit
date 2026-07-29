# Scoring and adjudication — `doc-bundle-01`

This is a public-key **regression** case, not a cold-recall measurement. The answer key is
intentionally checked in and must not be supplied to a reviewer during a genuinely cold run.

## Automated matching

`benchmarks/golden/score.py` matches a reviewer finding to the frozen key by:

1. exact `finding_id`;
2. exact `error_class`, `severity`, and `reproduction`;
3. the exact set of claim ids that link to the finding.

The automated output reports matched, missed, mismatched, and unexpected finding ids. Recall is
`matched / expected`; precision is `matched / reviewer findings`.

## Disposition

- `pass`: every frozen finding matches and no additional finding was returned.
- `fail`: at least one frozen finding is missing or mismatched.
- `needs_adjudication`: every frozen finding matches, but the reviewer returned an additional
  finding.

An additional finding is not automatically a false positive. A human adjudicator must reproduce
it, classify it, and either reject it with a recorded reason or create a new immutable key version.
Existing public keys are not rewritten in place.

The checked-in reviewer output is primed benchmark material and exists only to make CI
deterministic. It is not evidence of model performance.
