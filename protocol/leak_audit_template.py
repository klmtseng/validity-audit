#!/usr/bin/env python3
"""ILLUSTRATIVE Stage-1 scaffolding — NOT a turnkey detector.

⚠️ Two independent meta-audits (a primed pass and a cold/unprimed pass) EACH found fresh bugs in this
template. The honest conclusion: a hand-written check template is itself bug-prone, so **treat a clean
Stage-1 run as near-zero evidence** — its job is to *prompt the right questions on your actual project*.
The real assurance comes from Stage 2 (an independent reviewer) + the reproduction gate. Adapt these
checks to your data; don't trust them blind.

Each function returns a dict; verdicts are heuristic and example/curve-dependent — read the NOTE fields.
"""
import re
import pathlib
import numpy as np


# ---------- C. Arithmetic / protocol (most-missed) ----------
def demo_return_compounding(is_log_returns: bool):
    """DEMO on a fixed example (not a project-wide detector): log -> expm1(Σ); simple -> prod(1+r)-1."""
    f = np.array([0.03, -0.04, 0.05, -0.02, 0.06])
    as_simple = (1 + f).prod() - 1
    as_log = np.expm1(f.sum())
    correct, wrong = (as_log, as_simple) if is_log_returns else (as_simple, as_log)
    return {"correct": float(correct), "if_mixed_up": float(wrong), "gap": float(wrong - correct),
            "NOTE": "ACTION: grep your code for (1+f).prod() on LOG returns. Bias is too-negative for "
                    "high-vol names -> flatters min-variance. This demo does NOT inspect your code."}


def check_mdd_formula(equity_curve):
    """Compare correct MDD (running-peak) vs the TWO common global-peak bugs. Curve-dependent:
    on some curves a buggy variant equals correct, so a 0 gap here is NOT an all-clear."""
    eq = np.asarray(equity_curve, float)
    assert (eq > 0).all(), "equity must be positive; MDD ratio undefined across zero"
    cummax = np.maximum.accumulate(eq)
    g = cummax.max()
    correct = float(((cummax - eq) / cummax).max())             # running peak (right)
    bug_abs_over_global = float((cummax - eq).max() / g)        # max abs dd / global peak
    bug_pointwise_over_global = float(((g - eq) / g).max())     # per-point dd vs global peak (overstates)
    return {"mdd_correct": correct, "bug_abs_over_global": bug_abs_over_global,
            "bug_pointwise_over_global": bug_pointwise_over_global,
            "NOTE": "ACTION: confirm your MDD divides by the RUNNING peak. Both bug variants shown; on "
                    "some curves they equal `correct`, so equality here does NOT prove your code is right."}


def check_oos_segmentation(backtest_range, model_train_range):
    """Flag only when the backtest window overlaps the model's training window (in-sample blending)."""
    import pandas as pd
    bt0, bt1 = (pd.Period(str(x), "M") for x in backtest_range)
    tr0, tr1 = (pd.Period(str(x), "M") for x in model_train_range)
    overlap = not (bt1 < tr0 or bt0 > tr1)
    return {"backtest": backtest_range, "train": model_train_range, "overlaps": overlap,
            "verdict": "RED_FLAG: in-sample blend — report a pure-OOS (lockbox) segment" if overlap
                       else "OK: backtest window is outside the training window"}


# ---------- A. Leakage / lookahead ----------
def check_lookahead_grep(src_dir="."):
    """Broad recall on purpose (meta-audit M4: narrow patterns miss most leak idioms). Two severity buckets."""
    definite = [r"shift\(\s*(periods\s*=\s*)?-", r"\.bfill\(", r"fillna\([^)]*bfill",
                r"\.rolling\([^)]*center\s*=\s*True"]                       # future-peeking
    review = [r"\.(mean|std|min|max|median|quantile|corr|cov)\(",          # stats — OK iff trailing/train only
              r"\.fit(_transform)?\(", r"LedoitWolf\(", r"corrcoef\(",
              r"groupby\([^)]*\)\.transform\(", r"PCA\("]
    def scan(pats):
        hits = []
        for p in pathlib.Path(src_dir).rglob("*.py"):
            if ".venv" in str(p) or "site-packages" in str(p):
                continue
            t = p.read_text(errors="ignore")
            for pat in pats:
                if re.search(pat, t):
                    hits.append(f"{p.name}: {pat}")
        return sorted(set(hits))
    return {"DEFINITE_LEAK": scan(definite), "NEEDS_REVIEW": scan(review),
            "NOTE": "NEEDS_REVIEW is expected to be large — that's the point; verify each uses only "
                    "train/trailing data. A clean grep is weak evidence (recall is imperfect)."}


def check_label_shuffle(X, y, fit_predict_fn, n=500, alpha=0.01, seed=0, higher_is_better=True):
    """Permutation test: is the score above the label-shuffled null? (NOT a leakage detector on its own.)
    Guard (meta-audit M3): permutation resolution 1/(n+1) must be < alpha, else it can never pass."""
    assert 1.0 / (n + 1) < alpha, f"n={n} too small for alpha={alpha}: min p={1/(n+1):.3f}. Raise n."
    rng = np.random.default_rng(seed)
    real = fit_predict_fn(X, y)
    shuf = np.array([fit_predict_fn(X, rng.permutation(y)) for _ in range(n)])
    p = (1 + np.sum((shuf >= real) if higher_is_better else (shuf <= real))) / (n + 1)
    return {"real": float(real), "shuffled_mean": float(shuf.mean()), "n_perm": n,
            "perm_p_value": float(p),
            "verdict": "signal real (above permutation null)" if p < alpha
                       else "RED_FLAG: indistinguishable from chance",
            "NOTE": "NOT a leakage detector — leakage that inflates the original score also inflates this "
                    "test's baseline and PASSES. Detect leakage with purged-CV / OOS / point-in-time checks."}


# ---------- B. Data / universe bias ----------
def check_survivorship(last_dates):
    """Distribution-based (meta-audit M2: a fixed 30-day window mislabels recent delisting). Measures the
    fraction of names whose trading stops materially before their peers'."""
    import pandas as pd
    s = pd.to_datetime(pd.Series(last_dates))
    p95 = s.quantile(0.95)                      # "alive" reference = where the bulk still trades
    thresh = p95 - pd.Timedelta(days=90)
    pct_ended_early = float((s < thresh).mean())
    spread_days = int((s.max() - s.min()).days)
    if spread_days < 30:
        flag = "RED_FLAG: all names share ~one last date -> snapshot/stale cache; survivorship un-assessable"
    elif pct_ended_early < 0.05:
        flag = "RED_FLAG survivorship: ~0% names stop before peers -> only survivors; portfolio inflated"
    else:
        flag = f"OK-ish: {pct_ended_early:.0%} of names stop trading before peers (some delisting present)"
    return {"n": len(s), "p95_last": str(p95.date()), "pct_ended_early": pct_ended_early,
            "spread_days": spread_days, "verdict": flag}


# ---------- D. Statistical validity ----------
def check_ci(values, baseline=None):
    """Small-n CI: t not z, ddof=1. Optionally test overlap with a baseline (the real decision rule)."""
    from scipy import stats
    v = np.asarray(values, float); n = len(v)
    if n < 2:
        return {"n": n, "NOTE": "need >=2 values"}
    ci = stats.t.ppf(0.975, n - 1) * v.std(ddof=1) / np.sqrt(n)
    out = {"n": n, "mean": float(v.mean()), "ci95_t": float(ci),
           "ci95_z_naive": float(1.96 * v.std(ddof=0) / np.sqrt(n)),
           "CAVEAT": "if these values share one return path (e.g. seeds on one backtest), this CI is "
                     "pseudo-replication — block-bootstrap the return SERIES instead."}
    if baseline is not None:
        out["beats_baseline"] = bool(v.mean() - ci > baseline)
        out["verdict"] = ("clears baseline (CI lower bound > baseline)" if out["beats_baseline"]
                          else "RED_FLAG: CI overlaps baseline -> not a robust edge -> default to retract")
    return out

# Multiple testing: from engine_v2.dsr_pbo import deflated_sharpe_ratio, pbo_cscv


if __name__ == "__main__":
    print(demo_return_compounding(is_log_returns=True))
    print(check_mdd_formula([1, 1.4, 1.1, 1.6, 1.5]))
    print(check_oos_segmentation(("2015-01", "2026-03"), ("2015-01", "2021-12")))
    print(check_survivorship(["2026-06-01"] * 40 + ["2018-01-01"] * 10))
    print("Stage-1 is scaffolding (weak evidence). The assurance is Stage 2 + reproduction.")
