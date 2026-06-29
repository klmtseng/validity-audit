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
    """Max drawdown must divide by the RUNNING peak, not the global peak.
    Meta-audit fix T5: invariant is buggy <= correct ALWAYS (equal only when global peak is the first
    peak / flat / down series); assert positive equity (formula is nonsense across zero)."""
    eq = np.asarray(equity_curve, float)
    assert (eq > 0).all(), "equity curve must be positive (start at 1.0); MDD ratio undefined otherwise"
    cummax = np.maximum.accumulate(eq)
    correct = float(((cummax - eq) / cummax).max())
    buggy = float((cummax - eq).max() / cummax.max())  # common bug (global-peak denominator)
    return {"mdd_correct": correct, "mdd_buggy_global_peak": buggy, "understated_by": correct - buggy,
            "NOTE": "buggy<=correct always; gap>0 means a real understatement (only in up-trending curves)"}


def check_oos_segmentation(backtest_range, model_train_range):
    """Does the headline window include the model's training window (in-sample blending)?"""
    bt0, bt1 = backtest_range; tr0, tr1 = model_train_range
    overlap = not (bt1 < tr0 or bt0 > tr1)
    return {"backtest": backtest_range, "train": model_train_range, "overlaps": overlap,
            "RED_FLAG": "overlaps and no pure-OOS segment -> headline is in-sample; report lockbox-only"}


# ---------- A. Leakage / lookahead ----------
def check_lookahead_grep(src_dir="."):
    """Two severity buckets (meta-audit fix T3): definite leaks vs needs-review — a bare `.mean()`
    on a trailing rolling window is benign, so don't lump it with future-peeking patterns (alarm fatigue)."""
    definite = [r"shift\(-", r"fillna\(method=.bfill", r"\.rolling\([^)]*center=True"]   # future-peeking
    review = [r"StandardScaler\(\)\.fit\(X(_full|_all)?\)", r"\bdf\.mean\(\)",
              r"np\.corrcoef\(", r"LedoitWolf\("]   # OK iff on train/trailing only — verify by hand
    def scan(pats):
        hits = []
        for p in pathlib.Path(src_dir).rglob("*.py"):
            if ".venv" in str(p) or "site-packages" in str(p):
                continue
            t = p.read_text(errors="ignore")
            for pat in pats:
                if re.search(pat, t):
                    hits.append(f"{p}: {pat}")
        return sorted(set(hits))
    return {"DEFINITE_LEAK": scan(definite), "NEEDS_REVIEW": scan(review),
            "NOTE": "DEFINITE = future-peeking, fix now. NEEDS_REVIEW = fine iff on train/trailing window only."}


def check_label_shuffle(X, y, fit_predict_fn, n=200, seed=0, higher_is_better=True):
    """Shuffle labels -> score should fall to the EMPIRICAL null. Permutation p-value (not mean±2σ).
    Fixes (from meta-audit): n>=100 not 5; permutation p-value not 2σ (tiny-n was unsound);
    `higher_is_better` so it works for loss metrics (regression MSE etc.), not only accuracy."""
    rng = np.random.default_rng(seed)
    real = fit_predict_fn(X, y)
    shuf = np.array([fit_predict_fn(X, rng.permutation(y)) for _ in range(n)])
    if higher_is_better:
        p = (1 + np.sum(shuf >= real)) / (n + 1)        # P(null >= real)
    else:
        p = (1 + np.sum(shuf <= real)) / (n + 1)        # lower=better
    return {"real": float(real), "shuffled_mean": float(shuf.mean()), "n_perm": n,
            "perm_p_value": float(p), "higher_is_better": higher_is_better,
            "verdict": "signal real (above permutation null)" if p < 0.01
                       else "RED_FLAG: not above null — result indistinguishable from chance",
            "NOTE": "this is a PERMUTATION test (is the score real or a chance artifact), NOT a leakage "
                    "detector on its own — leakage that inflates the original score would PASS here; "
                    "catch leakage with the purged-CV / OOS / point-in-time checks. p = rank of real among shuffles."}


# ---------- B. Data / universe bias ----------
def check_survivorship(last_dates, cutoff=None):
    """Meta-audit fix T4: derive cutoff from the data's own max date (not a hardcoded past date that
    drifts & inverts on a stale cache). Flag BOTH survivorship and the stale-cache masquerade."""
    import pandas as pd
    s = pd.Series(pd.to_datetime(last_dates))
    data_max = s.max()
    if cutoff is None:
        cutoff = data_max - pd.Timedelta(days=30)
    pct_ended_early = float((s < cutoff).mean())   # names ending well before the data's own max
    if pct_ended_early < 0.05:
        flag = "RED_FLAG survivorship: ~0% names end early -> only winners; portfolio inflated (unfixable on free data)"
    elif pct_ended_early > 0.8:
        flag = "RED_FLAG STALE CACHE: most names end before data max -> can't assess survivorship; refresh data"
    else:
        flag = "OK-ish: a real spread of end-dates (some delisting present)"
    return {"n": len(s), "data_max": str(data_max.date()), "cutoff": str(pd.Timestamp(cutoff).date()),
            "pct_ended_early": pct_ended_early, "verdict": flag}


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
