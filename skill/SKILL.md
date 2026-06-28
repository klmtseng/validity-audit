---
name: validity-audit
description: 量化研究結案前的驗證檢驗機制。兩段式:內部機械審計(洩漏/lookahead/倖存者/算術-協定bug/統計效力)+ 強制獨立 reviewer(另一個沒參與建造的 subagent 對抗式複查)。適用任何回測/因子/ML 量化研究在「下結論或發表前」自我否證。觸發詞:檢驗研究、walk-forward 汙染、lookahead、overfitting、發表前驗證、audit、leakage。
---

# Validity Audit — 量化研究自我否證機制

目標:在「下結論 / 寫報告 / 發表」**之前**,主動找出研究的邏輯與驗證問題。
核心教訓(來自 repr-lab 2026-06):**單一建造者有盲點。內部洩漏審計能抓「洩漏」,卻常漏掉「算術/協定 bug」**
(例如 log 報酬當簡單複利、MDD 除錯高點、in-sample 混入)——所以**第二段「獨立 reviewer」是強制、不可省略**。

## 何時用
任何回測/因子/ML 量化研究,在宣稱「贏過基準 / 有 alpha / Sharpe 多少」之前。寧可結案前跑一次。

---

## 第 1 段:內部機械審計(逐項檢查,寫成 `audit/leak_audit.md`)

對每一項:說明檢查什麼、怎麼驗、紅旗是什麼。可參考/移植本機現成模板:
- `~/Desktop/AI_MAC/projects/bwet_shipping/src/leak_audit.py`(6 檢:feature audit / rolling-window grep / purged CV / **label-shuffle 虛無** / train-test 比 / val-test 一致)
- `~/Desktop/AI_MAC/projects/relationship-validity-monitor/engine_v2/dsr_pbo.py`(**DSR / PBO** 多重檢定過擬合)
- 本 skill 附 `leak_audit_template.py`(通用起點)

### A. 洩漏 / Lookahead
1. **label-shuffle 虛無**:打亂標籤重訓→分數應掉到「經驗虛無」(注意類別不平衡→虛無 > 1/n,用打亂後的實測值當虛無,不是 1/n)。真標籤需**顯著高於打亂虛無**才算真訊號。
2. **特徵 point-in-time**:所有特徵/正規化只能用 `≤ as-of` 的資料。grep `StandardScaler().fit(`、`.mean()`、`corrcoef`、`LedoitWolf`、`shift(-`、全樣本 fit;確認都在訓練段或 trailing 窗。
3. **purge / embargo**:train 與 OOS 之間要有 ≥ 特徵窗長度的緩衝;檢查相鄰視窗會不會滲漏。

### B. 資料 / 宇宙偏誤
4. **倖存者偏誤**:看每檔 last-date;若 0% 已下市 → 只交易贏家 → **組合績效高估**。免費資料(yfinance)無法修,**必須 caveat**。
5. **point-in-time 宇宙與標籤**:宇宙成員是否用「全歷史」篩(預知誰活下來)?sector/country 標籤是否取自「現在」用到過去?

### C. ★ 算術 / 協定 bug(內部審計最常漏 —— 重點查)
6. **報酬複利**:報酬是 **log 還是 simple**?期報酬正確算法:log→`expm1(Σlog)`;simple→`prod(1+r)-1`。**混用會系統性灌水**(對高波動標的偏負→灌水 minvar)。
7. **指標公式**:MDD 要除「**當時** running peak」非全域高點;annualization 因子;Sharpe 的 ddof。
8. **in-sample 混入**:回測期是否含模型「訓練期」?**headline 必須有純 OOS(lockbox)分段**,不能用 train+OOS 混合的單一數字。
9. **自由重組/對齊**:換手/漂移計算有無「免費再平衡」、forward 窗對齊錯位、雙重計數。

### D. 統計效力
10. **CI 正確性**:n 小要用 t 非 z;`np.std` 用 ddof=1;別把「seed 敏感度」當「抽樣不確定性」(**偽複製**:多 seed 共用同一條報酬路徑 → 應對**報酬序列做 block-bootstrap**)。
11. **多重檢定**:試過幾種方法/設定?對最終「贏家」跑 **DSR(deflated Sharpe)+ PBO**,n_trials = 試過的策略數。

### E. 回測現實
12. **交易成本 / 換手**:gross 不算數;報 net@合理 bps;高換手策略尤其要看 net。

---

## 第 2 段:獨立 reviewer(★ 強制,不可省略)

用 **Agent 工具** spawn 一個 `general-purpose` subagent(沒參與建造)做對抗式複查。要點:
- 明確說「你**沒**建造這個,任務是找作者**漏掉或合理化**的問題」。
- **告訴它作者已發現什麼**,要它「別重複、往更深挖 / 挑戰」。
- 要它**實際讀碼**(列關鍵檔)+ 可跑唯讀檢查,但**別改檔、別跑長訓練**。
- 要求輸出:(a) 依嚴重度排序的問題清單(file:line + 機制 + critical/major/minor)、(b) 哪些 headline 數字可信/不可信、(c) **單一最重要的修正**。

Prompt 範本(填入專案路徑與宣稱):
> 你是獨立、對抗式的量化研究審查者。審計 `<專案路徑>`,找出 validity/leakage/bias/算術 問題。
> 你沒建造它;找作者漏掉或合理化的瑕疵。
> 宣稱:<列 headline 主張 + 對應檔案>。作者已發現:<列已知問題>——別重複,往更深挖。
> 重點查:lookahead/leakage、**報酬複利(log vs simple)**、**MDD/指標公式**、**in-sample 混入**、
> 權重/正規化 bug、point-in-time 宇宙與標籤、CI 正確性與偽複製、資料品質、任何會改 headline 的程式 bug。
> 讀實際的碼(列關鍵檔),可跑唯讀檢查但別改檔/別跑長訓練。
> 輸出:(a) 排序問題清單(file:line+機制+嚴重度)、(b) 可信/不可信的 headline、(c) 單一最重要修正。

---

## 第 3 段:回應與更正(誠實)
1. **逐項驗證** reviewer 的發現(用唯讀檢查確認,別照單全收也別護短)。
2. **修正確認的 bug**,**只 OOS 重跑** headline。
3. **誠實更正報告**:撐不住的結論明白**撤回/降級**(paper / README / JOURNEY 都改),保留「沒撐過」紀錄。
4. 不可修的(如倖存者)→ 明列為硬限制 + caveat。
5. 把 reviewer 報告存 `audit/independent_review.md`,內部審計存 `results/leak_audit.md`。

## 判讀原則
- **所有偏誤若都指向同一個(灌水)方向 → 高度可疑**。
- **headline 數字若同時被多項擊中 → 不可信,寧可撤回**。
- 區分:橫斷面/分類結論通常較穩;**報酬/組合績效最易被算術+倖存者灌水**。
- 「指標看起來好 ≠ 兌現到底線」;「monitor 的 change ≠ death」。

## 如何啟動
在任何對話打 `/validity-audit`(可附專案路徑),或說「幫我用 validity-audit 檢驗這個研究」。
