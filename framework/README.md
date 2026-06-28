# Validity Audit — a two-stage self-falsification protocol for quant research

A reusable process to catch logical, leakage, and **arithmetic/protocol** bugs in backtests / factor /
ML quant research **before** you claim an edge. Companion to this repo's `engine_v2/dsr_pbo.py`
(Deflated Sharpe / PBO) and `engine_v2/csw_monitor.py`.

## The core lesson
A single builder has blind spots. An **internal leakage audit catches "leakage" but routinely misses
"arithmetic/protocol bugs"** (e.g. log returns compounded as simple, max-drawdown divided by the global
peak, in-sample blended into the headline). So **Stage 2 — an independent reviewer that did not build the
code — is mandatory, not optional.**

> Case study: an internal audit of a representation-learning study passed clean (label-shuffle null,
> point-in-time features). An *independent* reviewer then found three flattering bugs (log-return
> compounding, ~64% in-sample blending, MDD denominator) — and the corrected, OOS-only re-run showed the
> portfolio edge over equal-weight was **not robust**. The headline was retracted. That is the protocol
> working as intended. → full write-up: **[CASE_STUDY.md](CASE_STUDY.md)**.

## Stage 1 — internal mechanical audit (write to `audit/leak_audit.md`)
Use `leak_audit_template.py` as a starting point. Check, with a red flag for each:

**A. Leakage / lookahead**
1. **Label-shuffle null** — shuffle labels, retrain; score must fall to the *empirical* null. With class
   imbalance the null is **above** `1/n` (majority-class effect) — compare to the shuffled score, not `1/n`.
   Real labels must sit *significantly above* the shuffled null.
2. **Feature point-in-time** — every feature/normalization uses only data `≤ as-of`. Grep for full-sample
   `fit`, `.mean()`, `corrcoef`, `LedoitWolf`, `shift(-…)`, `bfill`.
3. **Purge / embargo** — a buffer ≥ feature-window length between train and OOS.

**B. Data / universe bias**
4. **Survivorship** — if ~0% of names are delisted, you trade only winners → backtests inflated. Often
   unfixable on free data → must be a stated caveat.
5. **Point-in-time universe & labels** — is membership decided with full history? Are sector/country
   labels taken from *today* and applied to the past?

**C. ★ Arithmetic / protocol (most-missed — check hardest)**
6. **Return compounding** — log vs simple. log→`expm1(Σ log)`; simple→`prod(1+r)-1`. Mixing them is a
   *systematic, directional* bias (too-negative for high-vol names → flatters min-variance).
7. **Metric formulas** — MDD divides by the **running** peak, not the global peak; check annualization, ddof.
8. **In-sample blending** — does the backtest window include the model's *training* window? The headline
   must report a **pure OOS (lockbox)** segment, never a train+OOS blend.
9. **Free re-alignment** — turnover/drift with hidden cost-free rebalances; forward-window misalignment.

**D. Statistical validity**
10. **CI correctness** — small `n`: use `t` not `z`, `ddof=1`. Don't pass off **seed sensitivity** as
    sampling uncertainty (**pseudo-replication**: many seeds sharing one return path) — block-bootstrap the
    *return series* instead.
11. **Multiple testing** — run **DSR + PBO** (`engine_v2/dsr_pbo.py`) on the final winner; `n_trials` =
    number of strategies/configs tried.

**E. Backtest realism**
12. **Costs / turnover** — gross doesn't count; report net at realistic bps, especially for high turnover.

## Stage 2 — independent reviewer (mandatory)
Have a reviewer (a person, or an LLM agent) **that did not build the code** adversarially re-check it.
Brief them with: the headline claims + files; what Stage 1 already found ("don't repeat — go deeper");
and tell them to **read the actual code**, run read-only checks, and rank findings by severity with
`file:line` + mechanism. Demand: (a) ranked issues, (b) which headline numbers to trust vs distrust,
(c) the single most important fix. The Stage-1 bug classes above (esp. C) are the prompt's focus.

## Stage 3 — honest correction
Verify each finding, fix confirmed bugs, **re-run headline OOS-only**, and **retract/downgrade** claims
that don't survive (in the paper/README, keeping a record of what failed). Unfixable issues (survivorship)
→ explicit hard limitations.

## Judging principle
If every bias points the **same (flattering) direction**, be very suspicious. A headline hit by several at
once is untrustworthy — prefer to retract. Cross-sectional/classification results are usually more robust;
**return/portfolio metrics are the easiest to inflate** via arithmetic + survivorship.
