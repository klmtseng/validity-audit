# Case study — the protocol catching a headline it would otherwise have shipped

A worked example of the two-stage protocol on a real internal project (de-identified). The point: **Stage 1
passed clean, Stage 2 retracted the headline.** Both stages were necessary.

## The study
A representation-learning project on ~1,100 global equities: self-supervised encoders produce per-asset
embeddings; a probe predicts forward realized volatility; a long-only **minimum-variance** portfolio is
built from predicted vols + a block-shrunk (Ledoit-Wolf) correlation, grouped by GICS sector.

**Headline claim (pre-audit):** "block-GICS min-variance, quarterly-rebalanced, **net Sharpe ~1.0** at
10bps/side, MDD ~6%, vs equal-weight 0.60 — robust across encoder seeds."

## Stage 1 — internal mechanical audit → **passed clean**
- **Label-shuffle null:** real sector probe 0.194 ≫ shuffled empirical null 0.127 → no label leakage.
- **Features point-in-time:** vol/correlation use trailing windows ending at the as-of date.
- **Embargo:** a one-year buffer sits between train and the lockbox test window.
- Flagged: **survivorship** (0% delisted names) and **multiple-testing** (not yet DSR-deflated).

Internal verdict: *"no leakage; representation findings trustworthy; portfolio inflated only by
survivorship."* — **This verdict was wrong about the portfolio**, in a way leakage checks can't see.

## Stage 2 — independent reviewer (did not build the code) → **3 flattering bugs**
1. **Log returns compounded as simple.** Returns were log; every backtest formed the period return as
   `(1+f).prod()-1` instead of `expm1(Σf)`. The error is quadratic in magnitude → systematically
   **too-negative for high-volatility names** → spuriously **flatters min-variance** (which underweights
   them). Directionally aligned with the claim.
2. **~64% in-sample.** The backtest ran 2015–2026 but the encoder + probe were trained on 2015–2021.
   ~84 of ~132 months were in-sample; **no pure lockbox-only portfolio number existed.**
3. **MDD over the global peak.** Max drawdown divided by the final/global peak, not the running peak →
   every drawdown understated in an up-trending sample.
   *(Also: the "0.90 ± 0.05" CI used n=3 with a z-quantile and a shared return path = pseudo-replication.)*

## Stage 3 — correction → **headline retracted**
Fixes: `expm1` compounding; MDD over the running peak; block-bootstrap CI on the return path; and a
**re-run reporting OOS segments separately.**

| segment | equal | block-GICS (corrected, net) |
|---|---|---|
| back_oos 2012–14 (OOS) | 0.73 | **0.08** — loses badly |
| in-sample 2015–21 | 1.08 | 1.17 |
| lockbox 2023–26 (OOS) | 1.42 | 2.57 — wins, but bootstrap CIs **overlap** equal |
| full 2012–26 | 0.53 | **0.02** — loses |

A real edge should hold in *both* OOS regimes. It won one and failed the other and the full period, with
overlapping CIs. **The "~1.0 robustly beats equal-weight" headline was retracted.** The cross-sectional
representation findings were unaffected — the bugs lived only in the portfolio code.

## Why both stages were needed
Stage 1 was scoped to *leakage* and passed honestly. The bugs were *arithmetic/protocol* (compounding,
metric formula, in-sample blending) — a class a builder's own audit is structurally prone to miss. An
**independent reviewer that did not build the code** found all three in one pass. Internal rigor is
necessary but not sufficient; the independent stage is what turned a shippable false positive into a
retraction.
