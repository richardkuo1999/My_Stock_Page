# 引入 uanalyze_cli 功能到 Stock Bot

<!-- labels: wayfinder:map -->

## Destination

產出一份「引入 `uanalyze_cli` 的 spec」——逐一決定 `uanalyze_cli`（UAnalyze 終端工具箱，A1–A12）的每個功能是否引入現有 Stock Bot、以及引入後的形態（Telegram 指令 / Agent 工具 / 不引入），並解決三套認證如何在現有 `tools/uanalyze.py` 統一。交付給後續 `/to-tickets → /implement`。**本 map 只做決策、不寫 code。**

## Notes

- 領域：台股投資輔助 Telegram Bot（見 ARCHITECTURE.md）
- 架構鐵則：Bot 薄殼 + 純確定性工具（工具不呼叫 AI）+ Agent 協調；快捷指令走 Python、`@mention` 走 Agent
- 來源：`/Users/richardkuo/Desktop/stock code/stocktool/uanalyze_cli`
- **形態不設橫切原則**：每個功能單獨在各自 ticket 裡決定觸發形態（使用者裁決 6）
- 每個 grilling session 應諮詢 `/grilling` 和 `/domain-modeling`
- **延後來源**（在霧裡，已存 `docs/todo/backlog/deferred-sources.md`）：
  - 來源 B `industry_agent`（產業報告產生器，量大，可能自成一張 map）
  - 來源 C `cb_analyzer.py`（可轉債選股，單檔單資料域）

### 關鍵事實（breadth-first 掃描發現）

- **三套認證並存**：(1) JWT Bearer `/auth/token`（現有 tools/uanalyze.py + A1/A2/A10）；(2) Session cookie `uanalyze_session_cookies.json`（A3–A9 的 `data_fetch/api/{Module}/{ticker}`）；(3) 寫死公開 GIDP token（股名對照表）
- A10（研報摘要）**已擁有** — 現有 `tools/uanalyze.py` + 監控推播已涵蓋
- A3–A9 共用 session cookie，一次解認證即全通

## Blocking edges

```
[調查 uanalyze_cli 三套認證機制與統一可行性] ──blocks──► [online 驗證 cronjob/gidp 是否接受 JWT Bearer]  ✅→task
[online 驗證 cronjob/gidp 是否接受 JWT Bearer] ──blocks──► [UAnalyze 認證統一策略決策]
[UAnalyze 認證統一策略決策] ──blocks──► [群2：法說會逐字稿/AI主題 是否引入與形態]
[UAnalyze 認證統一策略決策] ──blocks──► [群3：data_fetch 模組群 是否引入與形態]
[群3：data_fetch 模組群 是否引入與形態] ──blocks──► [A5 動態 DCF 估值 是否引入與形態]
```

**Frontier（現在可開工）：**
（無 — 全部功能決策已完成 ✅）

**Blocked（等前置決定）：**
（無）

## Decisions so far

<!-- one line per closed ticket: gist + link -->

- [調查 uanalyze_cli 三套認證機制與統一可行性](decisions/ua-01-auth-research.md) — 三套認證：A JWT(`api`/`data.twobitto`)、B cookie(`cronjob`)、C 寫死 GIDP token(`gidp`)。**實測 A 的 JWT 與 B 的 cookie access_token byte-for-byte 相同**（同一 token）。現有 tools/uanalyze.py = A 套、domain 完全一致。findings: `research/ua-auth/findings.md`
- [online 驗證 cronjob/gidp 是否接受 JWT Bearer](decisions/ua-08-online-auth-verify.md) — cronjob 用 Bearer→403、gidp 用 JWT→401；三套無法收斂成一套，但只需登入一次。
- [UAnalyze 認證統一策略決策](decisions/ua-02-auth-decision.md) — **單一擴充 `UAnalyzeAuth`**：一次 login → 3 個 helper（jwt/cookie/gidp）。cookie 走**記憶體組 4-cookie + Origin/Referer**（實測 200，不移植 CLI cookie 檔）。GIDP 當**模組常數**。認證整合不重。發現 GIDP 跨 A3/A5/A9（已修正 ua-04）。
- [群2：法說會逐字稿/AI主題 是否引入與形態](decisions/ua-03-jwt-completions.md) — **A2（15主題）不引入**（現有 /ua 32 面向已涵蓋）；**A1 法說會逐字稿併進 /ua 選單**。**逐字稿疑點已解（2026-08-23）**：真端點兩步（GIDP WebStockInfo 取清單 → cronjob `TranscriptDetail?id=&country=TWN` 取全文，B 套 cookie），來源 CLI 漏用。A1 = **接真逐字稿全文**（~16K字）→ 分頁+上下頁按鈕，**做法2 抓一次+記憶體TTL快取翻頁**（翻頁不重打 API），純資料不呼叫 AI。
- [群3：data_fetch 模組群 是否引入與形態](decisions/ua-04-datafetch-modules.md) — **A3/A4/A7/A8 引入**，包進新指令 **`/data <代號>` 選單**（仿 /ua）；A4 正名「財務指標」近4-5年；**A6 河流圖不引入**（需自畫圖）；**A9 併進 `/p`**（a1 best-effort 基本面，失敗不拖累秒回）。A8 無資料回提示。
- [A5 動態 DCF 估值 是否引入與形態](decisions/ua-05-dcf.md) — **引入**，併進 `/data` 選單第 5 項；**走 `only_dcf` 純數字路徑不呼叫 AI**（AI 質化欄位近況/利多/利空與現有 `/ua` 重複，不搬）；**不做 CSV**（批次保留獨立 CLI）。純計算 `_compute_dcf` 可原樣移入。
- [A11 專欄文章庫 是否引入與形態](decisions/ua-06-columns.md) — **引入**，**併入新聞聚合當第 16 來源**；全文 **on-demand**（點才抓，另計 `backlog/news-fulltext-on-demand.md`）；付費內容**自用**。API 確認存活：`api.uanalyze.com.tw/data/fetch/column/search`（斜線非底線；JWT；total 2369；item 帶 content 全文）。research 斜線筆誤已更正。
- [A12 批次 EPS CSV 匯出 是否引入與形態](decisions/ua-07-batch-eps-csv.md) — **A12 批次CSV本體不進 bot**（獨立 CLI，同 ua-05）；`fetch_broker_eps_estimates` **不引入**；**`gidp/StockPool`（12361 檔全台股名對照）引入，取代現有 stock_names 機制**（做法a：灌入本地表+定期刷新，自成長退役，保留 --set 後備）。

## Not yet specified

<!-- fog of war — graduates as frontier advances -->

- **真正的法說會逐字稿 API**（ua-03 衍生）— ✅ **已解（2026-08-23）**：真端點 = 兩步（GIDP `WebStockInfo` 取清單 → cronjob `TranscriptDetail?id=&country=TWN` 取全文，B 套 cookie）。來源 CLI 漏用。A1 已升級為接真逐字稿全文 + 分頁快取。詳見 ua-03。
- **A10 研報摘要的去重整合**：現有監控已涵蓋，但引入 uanalyze_cli 後認證若統一，是否要回頭簡化現有 `tools/uanalyze.py`？等認證決策後看。
- **stock_names 對照表整合** — ✅ **已解（ua-07，2026-08-23）**：用 `gidp/StockPool`（12361 檔全台股）取代現有 seed 20 + 自成長機制（灌入本地表+定期刷新，保留 --set 後備）。
- **來源 B `industry_agent` 引入**（見 backlog）— uanalyze_cli map 走完後 graduate
- **來源 C `cb_analyzer.py` 引入**（見 backlog）— 最後 graduate

## Out of scope

<!-- work beyond the destination — never graduates -->

- 實際實作 / coding（本 map 是 planning，交付 spec）
- 來源 B、C 的實作（本 map 只處理 uanalyze_cli）
- uanalyze_cli 的互動選單迴圈本身（形態與現有架構衝突，一律拆解成指令/工具，不搬選單框架）
