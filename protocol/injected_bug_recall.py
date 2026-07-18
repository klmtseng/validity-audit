#!/usr/bin/env python3
"""Meta-eval: quantify the DETERMINISTIC FLOOR's bug-detection recall (a proper eval of the evaluator).

We plant KNOWN bugs (from the ledger + Stage-1 template) into small fixtures, run the deterministic
detectors, and measure recall + false-alarm. Two honest properties this is built to surface:

  1. The floor catches mechanical/arithmetic bugs but is STRUCTURALLY BLIND to reasoning-level bugs
     (tautology, correlation-as-independence, accepting-the-null, fabricated citation). Those have no
     deterministic detector -> recall 0 -> which is exactly why the real ledger shows the independent
     reviewer catching ~7/9 misses. The floor is a lower bound; Stage 2 is not optional.
  2. Even the mechanical recall here is an UPPER bound: the planted bugs are blatant by construction
     ("easy mode"). Subtle real-world instances are harder and unmeasured. Don't read 100% as "solved".

Pure stdlib + numpy (scipy/pandas only if available; degrade gracefully). Run: python3 injected_bug_recall.py
"""
import os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # leak_audit_template.py lives in the same directory
import leak_audit_template as T


# ---- helpers: turn each detector's output into a boolean "flagged as problematic" ----
def flagged_oos(bug):
    r = T.check_oos_segmentation(("2015-01", "2026-03"),
                                 ("2015-01", "2021-12") if bug else ("2010-01", "2013-12"))
    return "RED_FLAG" in r["verdict"]

def flagged_survivorship(bug):
    last = ["2026-06-01"] * 50 if bug else (["2026-06-01"] * 40 + ["2017-03-01", "2019-08-01",
            "2020-01-01", "2021-06-01", "2022-11-01", "2018-02-01", "2023-04-01", "2016-07-01",
            "2024-01-01", "2015-05-01"])
    try:
        r = T.check_survivorship(last)
    except Exception as e:
        return None  # pandas missing
    return "RED_FLAG" in r["verdict"]

def flagged_label_shuffle(bug):
    rng = np.random.default_rng(0)
    X = rng.normal(size=(300, 3))
    signal = X[:, 0] + 0.3 * rng.normal(size=300)
    y = rng.permutation(signal) if bug else signal          # bug: labels are noise, claimed as signal
    def fit_predict(Xtr, ytr):                              # score = |corr(feature0, y)|
        return abs(np.corrcoef(Xtr[:, 0], ytr)[0, 1])
    r = T.check_label_shuffle(X, y, fit_predict, n=500, alpha=0.01, seed=1)
    return "RED_FLAG" in r["verdict"]

def flagged_ci(bug):
    # claim: strategy mean beats baseline 0.0. bug: noisy values whose CI overlaps 0.
    rng = np.random.default_rng(2)
    vals = rng.normal(0.05, 0.5, size=8) if bug else rng.normal(1.2, 0.2, size=8)
    r = T.check_ci(vals, baseline=0.0)
    return "RED_FLAG" in r.get("verdict", "")

def flagged_mdd(bug):
    # up-trending curve: the global-peak bug overstates. "reported" = buggy if bug else correct.
    eq = [1.0, 1.4, 1.1, 1.7, 1.5, 2.0, 1.8]
    r = T.check_mdd_formula(eq)
    reported = r["bug_pointwise_over_global"] if bug else r["mdd_correct"]
    return abs(reported - r["mdd_correct"]) > 1e-6         # flagged iff reported != correct running-peak

def flagged_lookahead(bug):
    # isolate the fixture in its own dir — else the grep scans this harness's own source
    # (which literally contains "shift(-1)") and false-alarms. (meta-eval self-bug, fixed.)
    import tempfile, shutil
    d = tempfile.mkdtemp(prefix="la_case_")
    try:
        open(os.path.join(d, "case.py"), "w").write(
            "z = df['x'].shift(-1)\n" if bug else "z = df['x'].rolling(20).mean()\n")
        r = T.check_lookahead_grep(d)
        return len(r["DEFINITE_LEAK"]) > 0
    finally:
        shutil.rmtree(d)


# ---- the test suite: (id, category, detector, has_deterministic_detector) ----
MECHANICAL = [
    ("oos_in_sample_blend", "in-sample blend in OOS window", flagged_oos),
    ("survivorship", "survivorship bias", flagged_survivorship),
    ("label_shuffle_noise", "signal = noise (label-shuffle test)", flagged_label_shuffle),
    ("ci_overlaps_baseline", "CI overlaps baseline", flagged_ci),
    ("mdd_global_peak", "MDD computed over global peak instead of running peak", flagged_mdd),
    ("lookahead_shift", "future leak (shift(-1))", flagged_lookahead),
]
# reasoning-level bugs from the ledger with NO deterministic detector in the floor:
REASONING_ONLY = [
    "tautological PASS (claim is constructed to be always true)",
    "correlation treated as independence (confounded variable)",
    "accepting null as evidence of absence",
    "fabricated / unverifiable citation",
    "metric measured on different subsets (selection bias)",
]


def run():
    print("=" * 78)
    print("META-EVAL: validity-audit deterministic floor — planted-bug detection recall")
    print("=" * 78)
    tp = fn = fp = tn = skipped = 0
    print(f"\n{'Case':<36}{'Bug planted → caught? (recall)':<28}{'Clean → false alarm?':<16}")
    for cid, cat, fn_det in MECHANICAL:
        got_bug = fn_det(True)
        got_clean = fn_det(False)
        if got_bug is None or got_clean is None:
            skipped += 1
            print(f"{cat:<36}{'(skipped: pandas/scipy missing)':<28}")
            continue
        tp += int(got_bug); fn += int(not got_bug)
        fp += int(got_clean); tn += int(not got_clean)
        print(f"{cat:<36}{('CAUGHT' if got_bug else 'MISSED'):<28}{('FALSE ALARM' if got_clean else 'ok'):<16}")

    n_mech = tp + fn
    recall = tp / n_mech if n_mech else float("nan")
    far = fp / (fp + tn) if (fp + tn) else float("nan")
    print("-" * 78)
    print(f"Mechanical recall = {tp}/{n_mech} = {recall:.0%}   |   False-alarm rate = {fp}/{fp+tn} = {far:.0%}"
          + (f"   (skipped {skipped})" if skipped else ""))

    print("\nReasoning-level bugs (no deterministic detector → structural miss, recall=0):")
    for r in REASONING_ONLY:
        print(f"  MISSED  {r}  — requires Stage-2 independent reviewer")
    print(f"Reasoning-level recall = 0/{len(REASONING_ONLY)} = 0%")

    total_bugs = n_mech + len(REASONING_ONLY)
    floor_caught = tp
    print("=" * 78)
    print(f"Overall: floor caught {floor_caught}/{total_bugs} = {floor_caught/total_bugs:.0%} (remainder requires Stage 2)")
    print("Honest caveats:")
    print("  · Mechanical cases are blatant by construction (easy mode) → this recall is an UPPER BOUND.")
    print("  · Reasoning-level 0% mirrors the real ledger: reviewer catches ~7x what self-audit catches.")
    print("  · False-negative denominator is unknown (only counts planted bugs); recall is a lower bound on coverage.")
    print("=" * 78)
    return dict(mech_recall=recall, far=far, floor_overall=floor_caught / total_bugs)


if __name__ == "__main__":
    run()
