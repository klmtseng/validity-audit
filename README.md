# Validity Audit

**A self-falsification protocol for any artifact that makes claims — and an audit that
audits itself.**

Most AI-era verification is a static checklist. Static evaluators decay: they miss
failure modes nobody wrote down, they get gamed by the thing they measure, and nobody
knows whether last month's revision made them better or worse. This project treats the
audit protocol as a system under evaluation too.

## Three ideas

**1. Adversarial two-stage review with a reproduction gate.**
The builder runs a mechanical audit; then an independent reviewer who did *not* build
the artifact attacks it. No finding counts until it is **reproduced** — by a runnable
read-only check, or pinned to file:line with verbatim quotes. This blocks both builder
blind spots and reviewer hallucinations.

**2. A miss-ledger that makes the evaluator evolve.**
Every failure the audit *didn't* catch is appended to a ledger as a category + detector.
The next audit opens by replaying all historical misses as mandatory challenges. The
checklist compounds; it is never finished. → [`protocol/COEVOLUTION.md`](protocol/COEVOLUTION.md)

**3. Golden-case recall benchmarking — the audit's own scorecard.**
For each audited target, verified expert findings become an answer key. After every
protocol revision, a *cold* reviewer (who never sees the key) re-audits the target, and
recall is measured. Protocol changes get a number, not a feeling.
→ [`golden_cases/`](golden_cases/)

## Measured result

Generalizing the protocol (v1 → v2) was validated on a real content-pipeline case with
a 6-finding expert key: **recall went from ~2.5/6 to 5/6**, and the cold reviewer
additionally surfaced **two confirmed bugs in the target's own anti-fabrication gate**
(empty-string subset pass, cross-item marking pass) that the builder had never noticed.
The most instructive catch: the builder's verbal claim "covers all 110 items" was false
(107) — *builders forget to verify their own claims; that is why independent review exists.*

## How to use this

This is a protocol, not an end-to-end tool. There are three ways in, by increasing effort:

**1. Claude Code users: install it as a skill.**

```
/plugin marketplace add https://github.com/klmtseng/claude-skills-marketplace
```

The validity-audit skill ships in that marketplace. Invoke it before shipping anything
that makes claims; it walks the agent through the six-step workflow (pin the claims →
replay ledger challenges → mechanical audit → fresh-context adversarial review →
reproduction gate → correction and ledger append).

**2. Any team or LLM workflow: adopt the process.**

No code required. The core is four rules:

1. The builder self-audits against the relevant checklist in `domains/`.
2. Someone who did not build the thing (a person, or a fresh model session) attacks the claims.
3. No finding counts until it reproduces: a runnable read-only check, or a file:line quote.
4. Every miss goes into a ledger; the next audit opens by replaying all historical misses.

Copy `protocol/` into your process docs and start with rule 3. The reproduction gate is
the piece that kills builder blind spots and reviewer hallucinations at the same time.

**3. Engineers: port the primitives.**

Three mechanisms transplant independently into an existing harness: two-stage adversarial
review with a reproduction gate (fits code review or CI), the miss-ledger
(`protocol/ledger.py`, a small script with no dependencies), and golden-case recall
scoring for your own evaluator (`golden_cases/` shows the format). This repo is the
reference implementation, not the product.

If you try any of these and it breaks, an issue describing the failure is worth more
to me than a star.

## Structure

| Path | What it is |
|---|---|
| [`domains/`](domains/) | Three-tier threat model (T1 claims false / T2 unclaimed risks / T3 unfit-for-purpose) + Stage-1 checklist packs: quant, generated content, deployed systems, documentation |
| [`golden_cases/`](golden_cases/) | Recall-benchmarking mechanism + anonymized answer keys |
| [`protocol/`](protocol/) | The core two-stage protocol, runnable leakage-audit template, meta-audit of the framework itself, coevolution design, worked case study |

## Origin

Distilled from ~30 audited projects (quant backtests, generative-narrative engines,
educational content pipelines, deployed prediction systems, internal rule sets). First
published as part of [relationship-validity-monitor](https://github.com/klmtseng/relationship-validity-monitor);
promoted to a standalone project when the protocol generalized beyond finance.
