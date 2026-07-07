# Case study — Stage 1 catches a tautology, Stage 2 catches a confound

The protocol is often assumed to be finance-specific because its checklist grew up around backtests
(leakage, log-vs-simple compounding, drawdown denominators). It isn't. The failure modes it targets —
**a metric that passes by construction, a correlation mistaken for an independent signal, a statistic
computed over the wrong subset** — are properties of *empirical claims in general*, not of asset returns.

Here is a worked example on a **procedural-narrative engine**: a data-driven storytelling system plus a
"generative-diversity" metric suite that scores how much *distinct mechanical variety* a content set
produces (as opposed to reskinned surface variety). No prices, no portfolio, no returns. De-identified.

## The study
The engine drives an interactive-fiction world from a library of "storylets" (small authored events with
mechanical fields + flavor text). The metric suite claims to separate **surface diversity** (how many
distinct events / how varied the labels look) from **effective dimension** (how many mechanically distinct
behaviors actually exist). The experiment inflates a baseline content set with **reskins** — duplicates
that change only flavor text, never mechanical fields — and measures what moves.

**Headline claims (pre-audit), reported as an 8/8 PASS:**
1. **C1** — "surface diversity ≠ effective dimension" holds in this domain: surface 10→30, label entropy
   3.04→4.55, **effective dimension stays 10**, slop 0→67%.
2. **C2** — a *dynamic* structural metric (the interval-CV of "revelation" story beats) is a **faithful,
   independent** structural signal: it moves when pacing genuinely changes and stays flat under pure reskin.
3. **C3** — a side finding about a content-gating mechanism leaking into pacing.

## Stage 1 — internal mechanical audit → caught one, blessed another
- **C1 flagged as a tautology.** The mechanical fingerprint *by definition ignores flavor text*, and a
  reskin *by definition changes only flavor text*. So "effective dimension unchanged under reskin" is
  **true by construction** — a consistency check, not a cross-domain empirical finding. Correctly downgraded.
- **C2 judged sound.** A paired t-test across 48 seeds showed the CV shift was large and stable
  (t ≈ 7.9). The builder concluded the dynamic metric was faithful. **This conclusion was wrong**, in a way
  a "does it move / is it stable" check cannot see.

## Stage 2 — independent reviewer (did not build it) → the confound the builder missed
The reviewer derived its own threat model and asked a question the builder never had: *is the CV actually
independent of the event count, or is it just the count's shadow?*
- **CV and event rate are confounded.** Pooled `corr(rate, CV) = 0.71`. Every condition that moved the CV
  also moved the rate; **no condition in the experiment ever moved one without the other.** The claim that
  CV carries structural information *independent of how many events fired* was never actually tested.
- Also flagged a **selection-bias latent bug**: the rate was averaged over all seeds, but the CV over only
  the non-NaN subset — two statistics on different sample subsets. Benign at the chosen horizon, but at a
  shorter horizon it silently drops 27 of 48 seeds, asymmetrically.

## Reproduction gate (every finding reproduced before it counts)
- `corr(rate, CV) = 0.71` — reproduced.
- Decisive test — regress `CV ~ 1 + rate + group`: after controlling for rate, the group coefficient is
  **t = 1.92 (borderline, p≈0.06, not significant at α=0.05)**. This is *failure to detect* a rate-independent
  signal, not proof one is absent — but the burden was on the claim, and the CV movement is fully accounted
  for by the rate change, so "CV is an *independent* structural metric" is unsupported as stated. (Honest
  caveat: this residualization is computed over the same 48 correlated seeds and a pooled correlation, i.e.
  it inherits the pseudo-replication limitation the protocol elsewhere flags; a clean test needs a
  decoupling design where rate and rhythm move independently.)
- NaN-drop: 27/48 at the short horizon, 0/48 at the reported one — reproduced.

## Stage 3 — correction
- **C1 downgraded** to a labeled consistency check (may not be presented as empirical evidence).
- **C2 retracted.** The beat-CV movement is not separable from the rate change (i.e. from C3), so it can't
  be claimed as an independent structural axis. The residualization test is now built into the experiment
  as the verdict.
- **C3 kept** — it is the one real, directly-measured finding.
- Subset bug fixed (rate and CV now computed on the same seed set).

## Why this case matters for the protocol
It reproduces the finance case's core lesson **with zero finance content**:

| | Finance case (representation-learning study) | This case (generative-narrative engine) |
|---|---|---|
| Stage 1 caught | survivorship + multiple-testing flags | a **tautological PASS** (metric invariant by construction) |
| Stage 1 **missed** | the arithmetic/compounding bugs | the **rate–CV confound** |
| Stage 2 caught | log-vs-simple, in-sample, MDD denominator | correlation-mistaken-for-independence + subset bias |
| Outcome | portfolio headline retracted | dynamic-metric headline retracted |

Same shape, different domain: **the builder's self-audit is real but blind in a stable direction, and
the independent second reader is what converts "8/8 PASS" into an honest, partly-retracted result.** The
tautology-detection habit ("could this check ever have failed, or is it true by construction?") came *out
of* this case and is now a standing rule in the protocol.

> A passing audit is not a validation — see the README's *Out of scope* section.

---

*Notes: this is the author's own personal project (private names removed; no employer/client/NDA data).
Figures illustrate the audit process; the study code is not part of this repository and the numbers are
not independently reproducible from it. "Independent reviewer" here means a reviewer that did not build the
code, run in a fresh context — in practice a separate LLM instance, not a different model family; that is
weaker independence than a human or cross-family reviewer would give, and is itself a stated limitation of
the anecdote. Personal research methodology; not investment advice.*
