#!/usr/bin/env python3
"""Generic leakage / bias audit template (Stage 1 of the validity-audit protocol).
Copy into your research project, fill the TODOs, emit `audit/leak_audit.md`.
Stage 2 (independent reviewer) is run separately — see validity_audit/README.md.

Each check is independently runnable. If a check doesn't apply, mark it N/A — don't fake a pass.
"""
import re
import pathlib
import numpy as np

# ============== TODO: wire to your project's data/model ==============
# load_returns(ticker) -> pd.Series   # NOTE: are these LOG or SIMPLE returns?
# universe, embeddings, probe, equity_curve, ...


# ---------- C. Arithmetic / protocol (most-missed — do these first) ----------
def check_return_compounding(is_log_returns: bool):
    """Correct period return: log -> expm1(sum); simple -> prod(1+r)-1. Mixing = systematic bias."""
    f = np.array([0.03, -0.04, 0.05, -0.02, 0.06])  # example period
    as_simple = (1 + f).prod() - 1
    as_log = np.expm1(f.sum())
    correct = as_log if is_log_returns else as_simple
    wrong = as_simple if is_log_returns else as_log
    return {"is_log": is_log_returns, "correct": float(correct), "if_mixed_up": float(wrong),
            "gap": float(wrong - correct),
            "RED_FLAG": "log returns compounded via (1+f).prod()-1 -> inflated (too-negative for high-vol)"}


def check_mdd_formula(equity_curve):
    """Max drawdown must divide by the RUNNING peak, not the global peak."""
    eq = np.asarray(equity_curve, float)
    cummax = np.maximum.accumulate(eq)
    correct = float(((cummax - eq) / cummax).max())
    buggy = float((cummax - eq).max() / cummax.max())  # common bug
    return {"mdd_correct": correct, "mdd_buggy_global_peak": buggy,
            "RED_FLAG": "buggy < correct -> drawdown understated in an up-trending series"}


def check_oos_segmentation(backtest_range, model_train_range):
    """Does the headline window include the model's training window (in-sample blending)?"""
    bt0, bt1 = backtest_range; tr0, tr1 = model_train_range
    overlap = not (bt1 < tr0 or bt0 > tr1)
    return {"backtest": backtest_range, "train": model_train_range, "overlaps": overlap,
            "RED_FLAG": "overlaps and no pure-OOS segment -> headline is in-sample; report lockbox-only"}


# ---------- A. Leakage / lookahead ----------
def check_lookahead_grep(src_dir="."):
    pats = [r"StandardScaler\(\)\.fit\(", r"\.mean\(\)", r"np\.corrcoef", r"LedoitWolf",
            r"shift\(-", r"fillna\(method=.bfill", r"\.rolling\(.*center=True"]
    hits = []
    for p in pathlib.Path(src_dir).rglob("*.py"):
        if ".venv" in str(p) or "site-packages" in str(p):
            continue
        t = p.read_text(errors="ignore")
        for pat in pats:
            if re.search(pat, t):
                hits.append(f"{p}: {pat}")
    return {"suspects": sorted(set(hits)),
            "NOTE": "manual review: must use train-window/trailing only; bfill & shift(-) are direct leaks"}


def check_label_shuffle(X, y, fit_predict_fn, n=5, seed=0):
    """Shuffle labels -> score should fall to the EMPIRICAL null. Real must exceed shuffled, not 1/n."""
    rng = np.random.default_rng(seed)
    real = fit_predict_fn(X, y)
    shuf = [fit_predict_fn(X, rng.permutation(y)) for _ in range(n)]
    sm, ss = float(np.mean(shuf)), float(np.std(shuf))
    return {"real": real, "shuffled_null": sm, "shuffled_std": ss,
            "verdict": "OK (no leakage)" if real > sm + 2 * ss else "RED_FLAG (leakage/memorization)",
            "NOTE": "class imbalance makes the null > 1/n; compare real vs shuffled, not vs 1/n"}


# ---------- B. Data / universe bias ----------
def check_survivorship(last_dates, cutoff="2025-01-01"):
    import pandas as pd
    s = pd.Series(pd.to_datetime(last_dates))
    delisted = float((s < pd.Timestamp(cutoff)).mean())
    return {"n": len(s), "pct_delisted": delisted,
            "RED_FLAG": "pct_delisted ~0 -> survivorship; portfolio inflated; often unfixable on free data"}


# ---------- D. Statistical validity ----------
def check_ci(values):
    """Small-n CI: use t not z, ddof=1. And don't pass seed-sensitivity off as sampling uncertainty."""
    from scipy import stats
    v = np.asarray(values, float); n = len(v)
    t = stats.t.ppf(0.975, n - 1) if n > 1 else np.nan
    ci_t = t * v.std(ddof=1) / np.sqrt(n) if n > 1 else np.nan
    ci_z_buggy = 1.96 * v.std(ddof=0) / np.sqrt(n) if n > 1 else np.nan
    return {"n": n, "mean": float(v.mean()), "ci95_t_correct": float(ci_t),
            "ci95_z_buggy": float(ci_z_buggy),
            "RED_FLAG": "seeds sharing one return path = pseudo-replication; block-bootstrap the series"}

# Multiple testing: from engine_v2.dsr_pbo import deflated_sharpe_ratio, pbo_cscv


if __name__ == "__main__":
    print(check_return_compounding(is_log_returns=True))
    print(check_mdd_formula([1, 1.4, 1.1, 1.6, 1.5]))
    print(check_oos_segmentation(("2015-01", "2026-03"), ("2015-01", "2021-12")))
    print("TODO: wire data, enable A/B/D checks, then run Stage 2 (independent reviewer).")
