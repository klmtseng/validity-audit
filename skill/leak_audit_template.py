#!/usr/bin/env python3
"""通用洩漏/偏誤審計模板 —— 複製到你的研究專案、填入 TODO、跑出 audit/leak_audit.md。
配合 validity-audit skill 的第 1 段使用;第 2 段(獨立 reviewer)用 Agent 工具另跑。

設計成「逐項可獨立執行」;沒有的檢查就標 N/A,不要假裝通過。
"""
import re
import pathlib
import numpy as np

# ============== TODO: 接上你專案的資料/模型 ==============
# def load_returns(ticker) -> pd.Series   # 你的報酬載入(注意:log 還是 simple?)
# universe = [...]; embeddings/probe = ...
# 下面每個 check 用到的地方標了 TODO。


# ---------- C. 算術/協定(最常漏,優先) ----------
def check_return_compounding(is_log_returns: bool):
    """報酬複利是否正確。log→expm1(Σ);simple→prod(1+r)-1。混用=系統性灌水。"""
    f = np.array([0.03, -0.04, 0.05, -0.02, 0.06])  # 範例
    as_simple = (1 + f).prod() - 1
    as_log = np.expm1(f.sum())
    correct = as_log if is_log_returns else as_simple
    wrong = as_simple if is_log_returns else as_log
    return {"is_log": is_log_returns, "correct": float(correct), "if_mixed_up": float(wrong),
            "gap": float(wrong - correct),
            "RED_FLAG": "若程式對 log 報酬用 (1+f).prod()-1 → 灌水(對高波動標的偏負)"}


def check_mdd_formula(equity_curve):
    """MDD 必須除『當時 running peak』,非全域高點。"""
    eq = np.asarray(equity_curve, float)
    cummax = np.maximum.accumulate(eq)
    correct = float(((cummax - eq) / cummax).max())
    buggy = float((cummax - eq).max() / cummax.max())   # 常見錯誤
    return {"mdd_correct": correct, "mdd_buggy_global_peak": buggy,
            "RED_FLAG": "buggy < correct → 牛市裡回撤被低估"}


def check_oos_segmentation(backtest_range, model_train_range):
    """headline 是否含模型訓練期(in-sample 混入)?必須有純 OOS(lockbox)分段。"""
    bt0, bt1 = backtest_range; tr0, tr1 = model_train_range
    overlap = not (bt1 < tr0 or bt0 > tr1)
    return {"backtest": backtest_range, "train": model_train_range, "overlaps": overlap,
            "RED_FLAG": "overlaps=True 且沒有純 OOS 分段 → headline 是 in-sample,需只報 lockbox"}


# ---------- A. 洩漏 ----------
def check_lookahead_grep(src_dir="."):
    pats = [r"StandardScaler\(\)\.fit\(", r"\.mean\(\)", r"np\.corrcoef", r"LedoitWolf",
            r"shift\(-", r"fillna\(method=.bfill", r"\.max\(\)\s*#?.*全"]
    hits = []
    for p in pathlib.Path(src_dir).rglob("*.py"):
        if ".venv" in str(p) or "site-packages" in str(p):
            continue
        t = p.read_text(errors="ignore")
        for pat in pats:
            if re.search(pat, t):
                hits.append(f"{p}: {pat}")
    return {"suspects": sorted(set(hits)),
            "NOTE": "人工判讀:這些只能在訓練段/trailing 窗用,不可碰未來;bfill/shift(-) 是直接洩漏"}


def check_label_shuffle(X, y, fit_predict_fn, n=5, seed=0):
    """打亂標籤→分數應掉到經驗虛無。真標籤需顯著高於打亂虛無。"""
    rng = np.random.default_rng(seed)
    real = fit_predict_fn(X, y)
    shuf = [fit_predict_fn(X, rng.permutation(y)) for _ in range(n)]
    sm, ss = float(np.mean(shuf)), float(np.std(shuf))
    return {"real": real, "shuffled_null": sm, "shuffled_std": ss,
            "verdict": "OK 無洩漏" if real > sm + 2 * ss else "RED_FLAG 疑似洩漏/記憶",
            "NOTE": "類別不平衡→虛無 > 1/n;比的是 real vs 打亂虛無,不是 1/n"}


# ---------- B. 資料/宇宙 ----------
def check_survivorship(last_dates, cutoff="2025-01-01"):
    import pandas as pd
    s = pd.Series(pd.to_datetime(last_dates))
    delisted = float((s < pd.Timestamp(cutoff)).mean())
    return {"n": len(s), "pct_delisted": delisted,
            "RED_FLAG": "pct_delisted≈0 → 嚴重倖存者偏誤,組合績效高估,免費資料無法修→必須 caveat"}


# ---------- D. 統計效力 ----------
def check_ci(values):
    """小 n 的 CI:用 t 非 z、ddof=1;且別把 seed 敏感度當抽樣不確定性。"""
    from scipy import stats
    v = np.asarray(values, float); n = len(v)
    t = stats.t.ppf(0.975, n - 1) if n > 1 else np.nan
    ci_t = t * v.std(ddof=1) / np.sqrt(n) if n > 1 else np.nan
    ci_z_buggy = 1.96 * v.std(ddof=0) / np.sqrt(n) if n > 1 else np.nan
    return {"n": n, "mean": float(v.mean()), "ci95_t_correct": float(ci_t),
            "ci95_z_buggy": float(ci_z_buggy),
            "RED_FLAG": "若 seeds 共用同一條報酬路徑 → 偽複製;應對報酬序列做 block-bootstrap"}

# DSR/PBO:import 自 relationship-validity-monitor/engine_v2/dsr_pbo.py
#   from engine_v2.dsr_pbo import deflated_sharpe_ratio, pbo_cscv


if __name__ == "__main__":
    # 範例:把每個 check 串起來、印出、寫 audit/leak_audit.md
    print(check_return_compounding(is_log_returns=True))
    print(check_mdd_formula([1, 1.4, 1.1, 1.6, 1.5]))
    print(check_oos_segmentation(("2015-01", "2026-03"), ("2015-01", "2021-12")))
    print("TODO: 接上專案資料後啟用 A/B/D 各 check,並跑第 2 段獨立 reviewer。")
