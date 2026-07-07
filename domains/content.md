# Domain pack: generated content / educational material / datasets

For AI-generated curricula, translations, definitions, question banks, curated datasets.
Each item: state what you checked (command / file:line) + PASS or FLAG.
Prefer checks that are scripts (re-runnable) over prose assurances.

## C1 Coverage vs. ground truth (the most common false claim)
"Covers all N items" must be **machine-counted** against the ground-truth source.
Red flag: the generation process contained "skip these" instructions — skipped items
must appear in the delivery notes, or the coverage claim is false.
> Real case: "covers all 110 verbs" — actual 107; the 3 skipped (hardest, multi-form)
> were dropped by writer instructions and then forgotten by the builder.

## C2 Factual correctness (knowledge content)
Domain facts (science, history, numbers) must trace to a **pre-supplied fact sheet**;
anything beyond it is flagged "unverified". Generate with the fact sheet as a hard
boundary; audit by diffing content against it.

## C3 The anti-fabrication gate exists AND actually ran
Verbatim-match gates (generated items must exist in a verified source) must be
deterministic scripts (no LLM), and: ① this batch actually ran through it, output
retained; ② the gate has negative tests (dirty data gets caught); ③ gate version
matches output version. Red flag: subset checks — an **empty field is a subset of
everything** and passes silently; require non-empty + subset.
> Real case: a cold reviewer injected dirty data and found two gate loopholes
> (empty-string pass, cross-item marking pass) the builder never noticed.

## C4 Meta-flag honesty (`human_verified` and friends)
Grep every verified/checked/approved flag and ask: **who verified, by what method?**
Model self-review ≠ human sign-off. Label truthfully (`machine_gated + model_reviewed`).

## C5 Happy-path bias (QA of the QA)
Does every automated test end by typing the correct answer? Require realistic-user
paths: wrong answers, gibberish, empty input, mixed case, mid-session exit.
Tests must live in the repo, not in the builder's throwaway shell.

## C6 Regeneration consistency
Same pipeline, re-run: schema-compatible output? Environment (model version, venv,
script paths) recorded? Monolith artifacts noted as maintenance risk (T3, record only).

## C7 Licensing / privacy / provenance
Original vs. derivative? Source materials marked "do not redistribute" must be
quarantined from the published artifact. No personal data in shipped content.
