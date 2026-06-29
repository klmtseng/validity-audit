# Meta-audit — auditing the validity-audit itself

We applied the protocol **to its own design** (dogfooding). By its own thesis, the builder can't audit
their own work — so the meaningful test is Stage 2: an **independent reviewer** red-teamed the framework.
It found real gaps and **five bugs in the protocol's own Stage-1 template**, including the very tiny-n sin
the protocol lectures against. Findings were verified by reproduction (the new hard rule) before fixing.

## Methodology gaps found → fixed
- **[critical] No reproduction gate.** Reviewer findings could be hallucinated; "verify" was a soft
  sentence. → Stage 3 now: a finding counts only once reproduced with a runnable check (also the
  builder↔reviewer tiebreaker).
- **[critical] Reviewer not truly independent.** The prompt handed it the claims + a hint list → it finds
  what it's pointed at. → Stage 2 now: a **cold/unprimed pass first**, then a primed pass; prefer a
  *different model family* for the cold pass (same-model = correlated blind spots).
- **[major] Stage 1 false comfort + no enforcement.** A clean Stage-1 artifact is citable cover to skip
  Stage 2. → Stage 1 is framed as "necessary, never a pass"; retraction made the mechanical default.
- **[major] Silent scope.** A pass was over-readable as "validated." → explicit **Out of scope** section.
- **[major] Evidence base n=1 (self-selected success).** → log every run (hits/misses/false alarms),
  don't argue from the one catch.

## Template bugs found (reproduced) → fixed
| # | bug | fix |
|---|---|---|
| T1 | `check_label_shuffle` verdict sign-blind (wrong for loss metrics) | added `higher_is_better`; oriented the test |
| T2 | label-shuffle used n=5 + mean±2σ (≈9% false-positive — the protocol's own tiny-n sin) | n≥200 + **permutation p-value** |
| T3 | lookahead grep flagged every trailing `.mean()`/`LedoitWolf` → alarm fatigue | split into DEFINITE_LEAK vs NEEDS_REVIEW buckets |
| T4 | `check_survivorship` hardcoded cutoff **inverted on stale data** (stale cache → looks bias-free) | derive cutoff from data's max date; flag stale-cache too |
| T5 | MDD red-flag only fired on up-trending curves; broke across zero | stated invariant `buggy ≤ correct`; assert positive equity |

**Plus a meta-meta point** the reviewer itself missed (found while reproducing): the label-shuffle test is
a *permutation test* (is the score real or chance), **not a leakage detector** — leakage that inflates the
original score would pass it. Wording corrected; leakage detection deferred to the purged-CV/OOS checks.

## Verdict
The methodology is **sound and worth keeping** — its core insight (a builder's audit structurally misses
arithmetic/protocol bugs, so an independent adversarial re-check is non-optional) held up. But "as written"
it over-trusted the reviewer and oversold a clean Stage 1, and its own template contained bugs it warns
about. All fixed above. **Read a passing audit as "no flattering arithmetic bug found by a primed
reviewer," not "validated."** The fact that auditing the auditor found this much is the strongest evidence
the discipline is worth running.
