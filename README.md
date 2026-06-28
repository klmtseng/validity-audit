# validity-audit — 本機存檔 (local archive)

量化研究兩段式自我否證檢驗機制的**本機 git 存檔**(離線備份,不推遠端)。

## 三個家(live 來源 → 本檔為快照備份)
- **Claude skill(canonical)**:`~/.claude/skills/validity-audit/` → `/validity-audit` 啟動(跨對話)
- **公開 framework**:`github.com/klmtseng/relationship-validity-monitor/validity_audit/`(英文、求職 portfolio)
- **本機存檔(這裡)**:`projects/validity-audit/` —— skill 版 + framework 版的快照,純本機 git 版控

## 內容
- `skill/` — SKILL.md(完整中文協定)+ leak_audit_template.py(中文註解)
- `framework/` — 公開英文 README + CASE_STUDY(去識別化撤回案例)+ template_en.py

## 核心(一句話)
研究下結論前:**內部機械審計(洩漏/倖存者/算術-協定bug/統計效力)+ 強制獨立 reviewer(沒參與建造的第二者)**。
教訓:內部審計抓「洩漏」卻漏「算術 bug」(log 複利、MDD 除錯、in-sample 混入)→ 獨立 reviewer 不可省。

> 維護:改動以 skill / 公開 repo 為準,本檔定期同步快照。`git log` 留本機演進史。
