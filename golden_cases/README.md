# Golden cases — recall benchmarking for the audit itself

An audit protocol is a static evaluator; it decays (Goodhart, blind spots). The fix:
keep an answer key of **verified expert findings** per audited target, and after every
protocol revision, re-run a *cold* independent reviewer against the target and measure
**recall against the key**.

## Rules
- The cold reviewer must never see the expected findings (or the miss-ledger) first.
- A hit = semantic match, not verbatim. New reproducible findings beyond the key are
  bonus, never penalized — and get merged into the key.
- Every expected finding carries its threat tier (T1/T2/T3), the checklist item that
  should catch it, and a one-line reproduction recipe.

## Schema (`*.json`)
```json
{
  "case_id": "...", "target": "...", "domain_packs": ["content", "systems"],
  "expected_findings": [
    {"id": "P1", "tier": "T1", "checklist": "C1", "severity": "high",
     "finding": "...", "reproduce": "..."}
  ],
  "grading_notes": "..."
}
```

## Measured results (anonymized, 2026-07)
| Case | Domain | Key size | v1 recall (structural ceiling) | v2 cold recall |
|---|---|---|---|---|
| educational content pipeline | content+systems+fitness | 6 | ~2.5/6 | **5/6** + 3 bonus findings (2 confirmed gate bugs) |
| internal rules/docs suite | docs | 5 | n/a (pack didn't exist) | seeded from cold review, key finding = rule conflict in always-loaded layer |

The v1→v2 gap was closed by (a) adding the T3 tier, (b) swapping the quant-only Stage-1
checklist for domain packs — not by making reviewers "try harder".
