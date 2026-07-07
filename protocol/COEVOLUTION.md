# Co-evolution — keeping the audit itself from being Goodharted

A validation protocol is itself **a static evaluator**: a fixed checklist plus a fixed reviewer prompt.
Anything optimized against a fixed evaluator eventually games it — the checklist starts passing by habit,
and you stop measuring what you meant to. This is the same failure mode that shows up in LLM-as-judge,
auto-research referees, and reward models. So the protocol needs the other half of the loop: a way to keep
the evaluator *moving* and *learning from its own misses*. This borrows the idea of co-evolving the
evaluator against the thing it evaluates (Red Queen / Gödel-machine–style co-evolution), kept deliberately
lightweight — not a continuous co-evolution loop, which is overkill for a human-triggered, once-per-study
protocol.

## Mechanism 1 — an accreting miss-ledger
Every audit appends its misses (retractions, near-misses, false alarms) to an append-only ledger, each
with a reusable **detector** (the check that *would* have caught it). At the start of every new audit, the
ledger's distinct failure categories are replayed as **mandatory challenges**: "could this study commit
this same mistake? show how you verified it didn't." The checklist stops being a frozen A–E list and
starts carrying forward what past audits learned the hard way.

*Example ledger entries (de-identified), each now a standing challenge:*

| category | reusable detector |
|---|---|
| tautological pass (true by construction) | for each PASS, ask: could it have *failed*, or is it definitional? construction-necessary passes are labeled "consistency check," never evidence |
| correlation mistaken for independence | to claim metric X is an *independent* signal, residualize it on the suspected confounder (regression + group dummy / partial corr); the residual effect must survive |
| accepting the null as evidence | when *retracting* an effect, don't write "not significant" as "no effect"; report power/CI, and for borderline cases run an equivalence test |
| statistic over the wrong subset | two compared statistics must be computed over the *same* rows; check that NaN/drop filters aren't applied asymmetrically |

## Mechanism 2 — tautology detection
A check that can never fail measures nothing — and "always passes" is precisely the signature of a slack,
gamed evaluator. So **every PASS is tagged**: could it have failed, or is it true by construction? A
construction-necessary pass may only be reported as a *consistency check*, never as evidence. (This rule
came directly out of the generative-content case study, where a metric was invariant under a transform
*by definition* — see [CASE_STUDY_GENERATIVE.md](CASE_STUDY_GENERATIVE.md). The lesson the tool learned
about a study is now a standing rule the tool applies to itself.)

## Mechanism 3 — adversary rotation + logical erasure
- **Rotate the adversary.** Prefer a different model family / framing for the cold reviewer (a same-family
  reviewer shares the builder's blind spots), plus a reviewer whose only job is to *attack the checklist
  itself* — hunt for the tautological on-check and the off-list threat.
- **Logical erasure.** The cold reviewer is **not** shown the ledger (or it just pattern-matches past
  answers and independence collapses). The ledger's challenges feed only the *builder-side* audit; the
  primed (hot) pass may see the categories. The gap between the two passes measures how much a finding
  depended on framing.

## Honest status
This is a **design**, not a demonstrated result. The compounding claim — "the ledger makes the audit
stronger over time" — is a hypothesis with a handful of seed entries, not evidence; treating it as proven
would be exactly the kind of unearned causal claim this protocol exists to catch. The right read today:
the machinery is in place and the loop is closed (every audit reads the ledger in, writes its misses back
out); whether it compounds is something the run log will show over time, not something to assert now.

*Personal research methodology; not investment advice.*
