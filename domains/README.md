# Domain packs — what Stage 1 checks, by target type

The audit pipeline (pin claims → historical challenges → mechanical audit → independent
reviewer → reproduction gate → ledger closure) is domain-independent. Only the Stage-1
checklist changes. Route by target type; load multiple packs if the target spans types.

| Target | Pack |
|---|---|
| Quant research / backtests / ML performance claims | `quant.md` |
| Generated content / educational material / datasets | `content.md` |
| Deployed systems / pipelines / project handoff | `systems.md` |
| Documentation / rule sets / runbooks | `docs.md` |
| External repository intake (pre-execution) | `external-repo.md` — cross-family review is non-negotiable for this pack |

## Three-tier threat model (decide before you start)

- **T1 — claims are false** (always run): headline claims vs. reality — inflated
  numbers, incomplete coverage, dishonest flags, fabricated citations.
  *Verbal claims made to stakeholders count as claims.*
- **T2 — nobody claimed it, but it bites** (run for deployed systems & deliverables):
  unbacked irreproducible data, deliverables never executed end-to-end, unbounded growth.
- **T3 — true, but unfit for purpose** (opt-in; advisory by default):
  the artifact is honest and safe, yet fails its reason to exist — e.g. a learning tool
  with no progress memory, review sampling that ignores the user's weaknesses.
  T3 findings still use canonical `high` / `med` / `low` **impact severity**, but severity
  is separate from the policy result. Under the default policy, T3 is non-blocking and
  reported as advisory.

Why the ladder exists: a real case passed T1+T2 cleanly while an expert review still
produced six material findings — two of them structural T3 issues the audit could not
express. Generalizing the threat model, not adding more T1 checks, closed the gap.
