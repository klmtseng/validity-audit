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
| educational content pipeline (`study-forge-2026-07`) | content+systems+fitness | 6 | ~2.5/6 | **5/6** + 3 bonus findings (2 confirmed gate bugs) |
| internal rules/docs suite (`rules-docs-2026-07`) | docs | 5 | n/a (pack didn't exist) | seeded from cold review; sole P1 = upgrade-threshold conflict in always-loaded layer |

The v1→v2 gap was closed by (a) adding the T3 tier, (b) swapping the quant-only Stage-1
checklist for domain packs — not by making reviewers "try harder".

**`study-forge-2026-07` detail:** v2 cold reviewer hit 5/6 expected findings. The single miss was P4, the low-severity maintainability item (single-file app, eager audio
loading, no PWA manifest). Both high-severity fabrication-class findings (P1, P6) were caught.
Named here deliberately: a recall number without naming the miss hides the residual risk class. The 3 bonus
findings (gate accepted empty strings; gate missed cross-item marks; stale engine name in README)
were reproduced with dirty-data injection and subsequently fixed. P1 (missing-item count) and P6
(model-written human_verified flag) were builder self-errors — both entered in the audit ledger.

**`rules-docs-2026-07` detail:** Cold reviewer hit all 5 expected findings. R1 (P1 severity) is
the upgrade-threshold conflict between the always-loaded index (weak-model's only guaranteed read)
and the dispatch protocol — blast radius is highest because it affects every single agent
delegation. R2–R4 are P2 wording gaps; R5 is informational drift (below alert threshold).
Path validity: 24/25 paths verified; one log path absent (health check not yet first-run, expected).
All files within length limits at baseline.
