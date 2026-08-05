# Domain pack: external repository intake (pre-execution)

For third-party code you are about to study, adopt, or run. Two surfaces, always both:
**claims** (README/docs vs. the artifact) and **pre-execution safety**. Every check here
is static — never execute the target's scripts, tests, or installers during the audit;
record "behavioral claims unverified" as a stated limitation.

## Claims surface

### X1 Listed ≠ shipped
Capabilities declared in registries, enums, or tables (`SUPPORTED_*`, capability lists,
host lists) must be verified **per entry**: the backing module is non-trivial (line
count + real logic), and "accepted at the planning/validation layer" is distinguished
from "an execution adapter exists". Only the latter counts as shipped. Sampling some
entries can never support an all-entries CONFIRMED; a universal verdict requires a
per-entry table.
> Real case: a control-plane repo listed three supported agent hosts; only one had an
> execution adapter. Another had an activation profile plus a 23-line stub package —
> and a cold reviewer confirmed the universal claim after sampling two unrelated,
> genuinely substantial modules.

### X2 Fixture ≠ runtime
Numbers found under `examples/`, `fixtures/`, `*.example.*`, `*.sample.*` must never
support "the system really runs" or "has run N times". Runtime claims accept only
runtime-artifact paths or externally auditable records; otherwise UNVERIFIABLE. Before
citing any number, check which kind of path its file lives on.
> Real case: a `run_count` of 8,440 in `status.example.json` was cited as live
> dogfooding evidence by an intake report. The claim-coverage diff caught it: an
> example file cannot be distinguished from a handwritten fixture.

### X3 Marketing quantities and their trust chain
For hours/runs/users figures in the README, ask: **can this be recomputed from the
repo?** Not recomputable → UNVERIFIABLE, regardless of sincere wording or screenshots
(which may be redacted). For recomputable counts (tests, LOC), state the counting
convention — file count and test-function count legitimately differ.

## Safety surface (static, zero execution)

### X4 Installers
Read `curl | bash` installers line by line. A checksum computed but never compared to a
trusted value is an existence check, not verification. **Enumerate every environment
variable the installer honors** (`*_URL` / `*_REPO` / `*_REF` overrides are an
injection-to-code-execution boundary). List everything it writes, and which shell
rc/profile/LaunchAgent it touches — "touches" means write, append, source, symlink, or
plist creation; check all five.
> Real case: an installer accepted an archive-URL override and extracted-then-executed
> whatever it pointed to. Three same-family review perspectives missed it; the
> cross-family reviewer caught it.

### X5 "Diagnostic" commands that write
`doctor` / `status` / `check` / `init` style commands: verify against the
implementation whether they create directories, run write/rename/unlink probes, or
spawn subprocesses. Never accept a command's self-description as read-only.
> Real case: a `doctor` command created the runtime root and ran filesystem write
> probes on every invocation — "just run the doctor to look around" was not a
> zero-risk action.

### X6 Egress, enumerated exhaustively
Grep **all** network imports (`urllib`, `requests`, `httpx`, `socket`, `curl`, `wget`)
— an enumeration, not a sample. For each real call site: destination (hardcoded or
configurable), trigger condition, payload. API-key-gated paths get their own line
stating where the data goes, jurisdiction included, stated plainly.

### X7 Plugin / extension execution model
With what privileges does third-party plugin code run? Is there a process sandbox?
Which environment variables are inherited (`env=None` in a subprocess call means the
entire parent environment)? An unsandboxed extension mechanism gets its **own risk
grade**, not folded into the main verdict.

### X8 SSRF / callback surface
For features accepting URLs: is loopback / private-range / cloud-metadata access
blocked? Reverse-tunnel, bridge, and relay scripts are listed separately and marked
default-path or opt-in.

## Process differences vs. the generic workflow

1. **Cross-family review is non-negotiable for this pack.** In the source audit, four
   findings (of the X4/X5/X7/X8 types) were missed by three same-model-family
   perspectives — a deterministic scan, a cold review, and the main line — and all four
   came from the cross-family reviewer. If no second model family is available, state
   that in the report; never silently skip.
2. Cross-family findings still pass the reproduction gate: verify each at its cited
   `file:line` before accepting it.
3. Grade conclusions **by usage tier** — read-only design study / install + CLI /
   enabling networked or extension features — each tier with its own risk grade and
   evidence. No single overall score.
4. If your own earlier recon notes on the target exist, their unique claims join the
   claim-coverage diff: an intake report is itself a claimed artifact.
