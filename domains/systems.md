# Domain pack: deployed systems / pipelines / project handoff (T2 layer)

Threat model here is NOT "the claims are false" — it is **"nobody claimed it, but it
bites"** (completeness-critic view). Run when the target includes: live cron/daemon,
outbound notifications, cumulative ledgers, project closure, deliverables.

## S1 Irreproducible assets & backups
List every file that **cannot be recomputed** (point-in-time ledgers, quota-limited API
snapshots, human annotations). For each: second copy? in git? repo backed up off-machine?
Red flag: irreproducible + gitignored + single machine.

## S2 Deliverables executed end-to-end
Every deliverable: "was it run **the way its final consumer will run it**, at least
once?" LaTeX through the compiler; cron commands from cron's environment; PDFs opened;
receivers actually received. Red flag: "written" treated as "works"; export success
treated as content correctness.

## S3 Statistical power of future checks
For every "we'll verify later automatically": expected n? detectable effect at that n?
If underpowered, write the expectation-management sentence **now**.

## S4 Known-simplifications registry
Collect scattered approximations into one list: bias direction + rough magnitude +
when it becomes worth fixing. Red flag: simplifications live only in the author's memory.

## S5 Limits & quotas
Every external dependency: quota (who consumes it? do retries burn it?), message-size
caps, unbounded file growth (rotation?), timeouts, mobile-data cost of eager loading.

## S6 Orphan dual-writers
Two code paths writing the same file/state? Single writer or explicit locking.

## S7 Opportunity cost (say it out loud)
Is there an obviously higher-leverage alternative for the same effort? Only raise when
the gap is stark.
