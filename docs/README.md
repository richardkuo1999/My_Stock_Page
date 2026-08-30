# docs/ 文件規則

本專案的規劃文件（wayfinder map、grilling 決策、spec、backlog 待辦）都放在 `docs/`。
**完成狀態用「資料夾位置」表示，不看檔案內文的 Status 標記**——想知道一件事做完沒，看它在 `done/` 還是 `todo/` 即可，一眼分辨。

## 資料夾結構

```
docs/
├── README.md          ← 本檔：資料夾規則說明
├── done/              ← 已完成
│   ├── projects/      ← 已完成的大型專案（含各自 map / decisions / tasks / implementation）
│   └── backlog/       ← 已完成的零散待辦
└── todo/              ← 未完成
    ├── projects/      ← 進行中或待啟動的大型專案（目前為空）
    └── backlog/       ← 未完成的零散待辦
```

## 兩層分類

**第一層 `done/` vs `todo/`：完成狀態。**
- `done/`：已完成、已交付、已驗收的工作。
- `todo/`：尚未完成的工作（含尚未排入實作的 backlog、進行中的專案）。

**第二層 `projects/` vs `backlog/`：工作型態。**
- `projects/`：**大型、有內部結構**的工作。一個 project 是一個子資料夾，內含 `map.md`（wayfinder 決策地圖）、`decisions/`（grilling 決策）、`tasks/` 或 `implementation/`（實作 ticket）等。
- `backlog/`：**零散、單一主題**的待辦，一個主題一個 `.md` 檔，尚未展開成完整 project。

## 狀態變更＝搬資料夾

工作狀態改變時，**移動檔案/資料夾**到對應位置（請用 `git mv` 保留歷史）：

- backlog 項目完成 → `docs/todo/backlog/x.md` 搬到 `docs/done/backlog/x.md`
- backlog 項目展開成大型專案 → 從 `docs/todo/backlog/x.md` 升格為 `docs/todo/projects/x/`（wayfinder graduate）
- 專案全部做完 → `docs/todo/projects/x/` 整包搬到 `docs/done/projects/x/`

> 檔案內文可保留敘述性的進度說明（例如某 backlog 檔內部同時追蹤 INV-01、INV-02 兩子項），
> 但**整體完成與否以所在資料夾為準**，避免內文 Status 與資料夾位置雙重來源不一致。

## 目前現況（2026-08-30）

| 位置 | 內容 |
|------|------|
| `done/projects/01-bot-rebuild` | Bot 重建專案（12 張 ticket 全 done） |
| `done/projects/02-uanalyze-cli-import` | 引入 uanalyze_cli（決策全 closed、implementation 全 DONE） |
| `done/backlog/data-display-tables.md` | 資料顯示表格化（2026-08-26 完成） |
| `todo/backlog/existing-issues-investigation.md` | INV-01 prompts.py 工具清單缺漏、INV-02 並發阻塞 |
| `todo/backlog/agent-prompt-safety.md` | Agent prompt 安全防護（拒絕規則） |
| `todo/backlog/news-fulltext-on-demand.md` | 新聞全文 on-demand 抓取 |
| `todo/backlog/deferred-sources.md` | 延後引入來源 C（cb_analyzer 可轉債選股）；來源 B industry_agent 已移除另開專案 |
| `todo/projects/` | （目前為空，尚無進行中的大型專案） |
