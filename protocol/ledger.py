#!/usr/bin/env python3
"""validity-audit cumulative miss-ledger (Red Queen anchor-from-ledger).

Red Queen idea: a static evaluator will be Goodharted. Persist every audit
miss / retraction / false-alarm, and on the next audit surface the historical
miss *categories + detectors* as **mandatory challenges** — so the checklist
grows cumulatively over time, instead of staying static.

Pure stdlib, append-only, local.

Usage:
  python3 ledger.py challenges          # list historical misses as mandatory challenges (for builder-side mechanical audit)
  python3 ledger.py append '<json>'     # append a new miss record (do this at audit close-out)
  python3 ledger.py stats               # category distribution / who-caught-it breakdown

Logical erasure (P3): `challenges` output feeds ONLY the builder-side mechanical audit.
The cold reviewer MUST NOT see the ledger (or they pattern-match against the answer key
instead of independently reconstructing the threat model). Only the hot pass may use categories.
"""
import json, os, sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "audit_ledger.jsonl")


def load():
    if not os.path.exists(LEDGER):
        return []
    with open(LEDGER, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def challenges():
    rows = load()
    if not rows:
        print("(ledger empty; no historical misses yet)")
        return
    # De-duplicate by category, keeping the highest-severity representative (P2: anchor-from-ledger)
    by_cat = {}
    order = {"high": 3, "med": 2, "low": 1}
    for r in rows:
        c = r["category"]
        if c not in by_cat or order.get(r.get("severity", "low"), 0) > order.get(by_cat[c].get("severity", "low"), 0):
            by_cat[c] = r
    print("=" * 88)
    print(f"Historical misses → mandatory challenges for this audit ({len(by_cat)} categories, {len(rows)} records)")
    print("For each category: explicitly state whether this project could make the same error, and how you verify it doesn't.")
    print("=" * 88)
    for i, (cat, r) in enumerate(sorted(by_cat.items(), key=lambda kv: -order.get(kv[1].get("severity", "low"), 0)), 1):
        print(f"\n[{i}] {cat}  ({r.get('severity','?')}, first seen in project: {r.get('project','?')})")
        print(f"    Detector: {r['detector']}")
    print("\n" + "=" * 88)


def append(js):
    try:
        rec = json.loads(js)
    except json.JSONDecodeError as e:
        sys.exit(f"JSON parse error: {e}")
    need = {"id", "category", "detector", "caught_by", "severity"}
    missing = need - rec.keys()
    if missing:
        sys.exit(f"Missing fields: {missing}  (required: id / category / detector / caught_by / severity)")
    with open(LEDGER, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"Appended: {rec['id']}  [{rec['category']}]")


def stats():
    rows = load()
    print(f"Total miss records: {len(rows)}")
    print("By category:", dict(Counter(r["category"] for r in rows)))
    print("Caught by  :", dict(Counter(r.get("caught_by", "?") for r in rows)))
    print("By severity:", dict(Counter(r.get("severity", "?") for r in rows)))
    internal = sum(1 for r in rows if r.get("caught_by", "").startswith("internal"))
    reviewer = sum(1 for r in rows if r.get("caught_by") == "reviewer")
    print(f"-> Self-audit caught {internal}, independent reviewer caught {reviewer}"
          + ("  (reviewer surplus proves Stage 2 is not optional)" if reviewer > internal else ""))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "challenges"
    if cmd == "challenges":
        challenges()
    elif cmd == "append":
        if len(sys.argv) < 3:
            sys.exit("Usage: python3 ledger.py append '<json>'")
        append(sys.argv[2])
    elif cmd == "stats":
        stats()
    else:
        sys.exit(f"Unknown command '{cmd}'; available: challenges / append / stats")
