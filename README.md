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

**3. Golden-case regression benchmarking — the audit's own scorecard.**
For each audited target, verified expert findings become an answer key. After every
protocol revision, a reviewer re-audits the target and the result is compared with the
frozen key. Once a key is public, this measures regression against known failures — not
fresh cold-review performance. Protocol changes get a number, not a feeling.
→ [`golden_cases/`](golden_cases/)

## Historical result and provenance

Generalizing the protocol (v1 → v2) was validated on a real content-pipeline case with
a 6-finding expert key. The reported **~2.5/6** v1 figure was a retrospective
structural-ceiling estimate, not a measured cold run. The **5/6** v2 figure was measured
by a reviewer that was cold before the key was published; because the key is now public,
future runs on this case are regression checks. That review additionally surfaced
**two confirmed bugs in the target's own anti-fabrication gate**
(empty-string subset pass, cross-item marking pass) that the builder had never noticed.
The most instructive catch: the builder's verbal claim "covers all 110 items" was false
(107) — *builders forget to verify their own claims; that is why independent review exists.*

## How to use this

This release is a protocol plus reference primitives, not yet an end-to-end tool. There
are three ways in, by increasing effort:

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
scoring for your own evaluator (`golden_cases/` shows the historical format). The
packaged ledger entry point rejects non-canonical severities instead of silently
mis-ranking them:

```bash
python -m pip install -e .
validity-audit-ledger challenges
```

This repo is the canonical protocol upstream and reference implementation.

If you try any of these and it breaks, an issue describing the failure is worth more
to me than a star.

## Structure

| Path | What it is |
|---|---|
| [`domains/`](domains/) | Three-tier threat model (T1 claims false / T2 unclaimed risks / T3 unfit-for-purpose) + Stage-1 checklist packs: quant, generated content, deployed systems, documentation |
| [`golden_cases/`](golden_cases/) | Public regression mechanism + anonymized historical answer keys |
| [`protocol/`](protocol/) | The core two-stage protocol, runnable leakage-audit template, meta-audit of the framework itself, coevolution design, worked case study |

## Origin

Distilled from ~30 audited projects (quant backtests, generative-narrative engines,
educational content pipelines, deployed prediction systems, internal rule sets). First
published as part of [relationship-validity-monitor](https://github.com/klmtseng/relationship-validity-monitor);
promoted to a standalone project when the protocol generalized beyond finance.
