# Validity Audit — a self-falsification protocol for any artifact that makes claims

A reusable process to catch false claims, hidden landmines, and **arithmetic/protocol** bugs **before**
you ship a result. Born in quant research (backtests / factor / ML) — the checklist is deepest there, and
the original private workspace paired it with `engine_v2/dsr_pbo.py` (Deflated Sharpe / PBO) and
`engine_v2/csw_monitor.py`. Those helpers are **planned references and are not included in this
repository**. But
the failure modes it targets — *a metric that passes by construction, a coverage claim nobody re-counted,
a `verified` flag nobody verified* — are properties of empirical claims in general.

## v2 — Generalized (2026-07)

The pipeline (pin claims → historical challenges → mechanical audit → independent reviewer →
reproduction gate → miss-ledger closure) is domain-independent; only the Stage-1 checklist swaps.

- **[Three-tier threat model](../domains/README.md)**: **T1** claims are false · **T2** nobody claimed it
  but it bites · **T3** true but unfit for purpose (advisory only, never blocks).
- **Domain packs**: [quant](../domains/quant.md) ·
  [generated content / educational material](../domains/content.md) ·
  [deployed systems / handoff](../domains/systems.md) ·
  [documentation / rule sets](../domains/docs.md).
- **[Golden-case regression benchmarking](../golden_cases/README.md)**: the audit audits itself — keep
  an answer key of verified expert findings per target and replay it after protocol changes. The
  historical content-pipeline result was a retrospective v1 structural-ceiling estimate of
  **~2.5/6** followed by a measured **5/6** v2 review plus three bonus findings. The reviewer was cold
  before publication; now that the key is public, future runs are regression checks, not fresh cold
  recall.

Everything below is the v1 quant-native protocol — still the Stage-1 pack for financial claims.

## The core lesson
A single builder has blind spots. An **internal leakage audit catches "leakage" but routinely misses
"arithmetic/protocol bugs"** (e.g. log returns compounded as simple, max-drawdown divided by the global
peak, in-sample blended into the headline). So **Stage 2 — an independent reviewer that did not build the
code — is mandatory, not optional.**

> **Case study — Stage 1 catches a tautology, Stage 2 catches a confound.** On a generative-narrative
> engine's diversity metrics, self-audit flagged a metric that passed *by construction*; the independent
> reviewer then caught a *correlation mistaken for an independent signal* that self-audit had blessed.
> Headline retracted. → **[CASE_STUDY_GENERATIVE.md](CASE_STUDY_GENERATIVE.md)**.

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
11. **Multiple testing** — run **DSR + PBO** on the final winner; `n_trials` = number of
    strategies/configs tried. The historical helper path `engine_v2/dsr_pbo.py` is not included in
    this repository.

**E. Backtest realism**
12. **Costs / turnover** — gross doesn't count; report net at realistic bps, especially for high turnover.

## Stage 2 — independent reviewer (mandatory)
A reviewer **that did not build the code** adversarially re-checks it. Two passes, in order:

1. **COLD / unprimed pass (do first):** give it *only* the code + the headline claim — **no hint list,
   no "what Stage 1 found."** Ask it to derive the threat model and find what's wrong. This is the only
   pass that measures *real* independence; a primed reviewer mostly finds what it was pointed at.
2. **Primed pass:** then share the Stage-1 findings ("don't repeat — go deeper") and the bug classes
   above. Compare passes — the gap shows how much the result depended on framing.

For **true independence**, prefer a *different model family* (or a human) for the cold pass — a same-model
reviewer shares the builder's blind spots. Demand: ranked issues (`file:line` + mechanism + severity),
which headline numbers to trust vs distrust, and the single most important fix.

> **Honest note on the case study below:** its "independent reviewer" was a separate LLM instance in a
> fresh context (not the builder), but *same model family* — so it shares some blind spots with the
> builder. That is weaker independence than a human or cross-family reviewer, and a stated limitation of
> how much the anecdote proves. Even at that strength, the second pass caught bugs the self-audit missed.

## Stage 3 — honest correction
- **Reproduction gate (hard rule):** a reviewer finding counts **only** once you reproduce it with a
  runnable read-only check / numeric demonstration. A finding without a reproduction is a *hypothesis*,
  not a finding — this guards against reviewer hallucination (the symmetric twin of the builder's blind
  spot) and is the tiebreaker when builder and reviewer disagree (truth = code execution, not authority).
- **Fix → re-run headline OOS-only → retract.** Retraction is the **default**, not a judgment call, when
  an OOS regime fails or CIs overlap the baseline. Unfixable issues (survivorship) → explicit hard limits.

## ⚠️ Out of scope — a passing audit does NOT mean "validated"
This protocol mainly catches **leakage and flattering arithmetic in return/portfolio metrics.** A pass
means *"no flattering arithmetic bug was found by a primed reviewer"* — not that the research is true. It
does **not** check: regime / structural-break risk, data-snooping in *feature engineering* (vs the final
model), p-hacking via universe / date-range selection, transaction-cost/capacity/liquidity optimism,
look-ahead in the *label definition* itself, or non-stationarity invalidating the test window.

> **Self-meta-audit:** this methodology was itself put through Stage 2 — an independent reviewer found
> several template bugs (incl. the protocol's own tiny-n sin) and the gaps now fixed above. See
> [META_AUDIT.md](META_AUDIT.md). Evidence base is small; log every run (hits / misses / false alarms),
> don't argue from the one memorable catch.
>
> **A checklist is itself a static evaluator — and static evaluators get Goodharted** (the same problem as
> LLM-as-judge, auto-research referees, reward models). The other half of the loop — an accreting
> miss-ledger, tautology detection, and adversary rotation, so the audit learns from its own misses — is in
> **[COEVOLUTION.md](COEVOLUTION.md)**.

## Judging principle
If every bias points the **same (flattering) direction**, be very suspicious. A headline hit by several at
once is untrustworthy — prefer to retract. Cross-sectional/classification results are usually more robust;
**return/portfolio metrics are the easiest to inflate** via arithmetic + survivorship.

---

*Disclaimer: personal research methodology. Not investment advice; no solicitation or recommendation
of any security. Past results — retracted or otherwise — do not indicate future performance.*
