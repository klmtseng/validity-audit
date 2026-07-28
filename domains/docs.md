# Domain pack: documentation / rule sets / runbooks

For docs that are meant to steer future behavior (of people or of weaker models).
Today's date matters: date-sensitive facts decay.

## D1 Path & command existence
Sample ≥15 referenced paths/scripts/commands (ls/which). List the dead ones.

## D2 Fact decay
Version numbers, model tables, "re-verify after N days" self-imposed deadlines
(is the doc violating its own freshness rule?), stated size limits vs. actual `wc -l`.

## D3 Cross-references
"See section X of doc B" — does doc B still have section X?

## D4 Rule conflicts (the highest-value check)
Two rules giving contradictory instructions for the same situation — especially when
one copy lives in an always-loaded core layer and the other in an on-demand reference:
the core layer is the only one a weak model is guaranteed to read, so a stale core copy
silently wins.
> Real case: core layer said "escalate after two failures", the authoritative dispatch
> table said "cheap models escalate after one". One wasted retry per failure, by design.

## D5 Single points & rot
Which rule has no mechanism guaranteeing it will ever be read (written but unreachable
from the entry-point index)? Which file has no size guard?

## D6 Weak-model misreading (T3, advisory)
Per doc, find ≤3 sentences a mid-tier model would misread, state the misreading, give a
one-line fix. Classic: "verifier must not be the producer" misread as "saying 'verified'
is enough" in solo sessions; "read 4+ files → delegate" misread as per-action instead of
cumulative.

## D7 Claimed vs. delivered (existence ≠ delivery)
For every feature the doc under audit claims (READMEs, progress notes, claim tables),
verify delivery status — not merely that a matching file, directory, or class exists.
Best evidence is a live run. Shipping signals — `isImplemented` flags, `TODO`/stub
markers, `NotImplementedError`/`preconditionFailure` bodies, feature-flag defaults —
are asymmetric: a negative signal is decisive, a positive one is itself just another
claim. If no signal is legible, a live run is mandatory. Claim tables must separate
"delivered" from "planned"; a claim verified only by existence is not verified.
(Scope note: running *your own* deliverable end-to-end is systems-pack S2; D7 audits
delivery claims made by the document in front of you.)
> Real case: a mobile agent app's README listed LAN sync as a feature; the code was a
> skeleton with `isImplemented = false` and hard-trap stubs on 5 of its 7 methods
> (the remaining 2 no-op). A first-pass audit marked it verified because the source
> directory existed; reading the flag caught it. (external repo study, 2026-07)
