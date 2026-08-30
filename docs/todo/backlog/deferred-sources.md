# 延後討論的引入來源（Not yet specified）

> 這些是已知想引入、但**尚未進入 wayfinder map** 的來源。目前聚焦 `uanalyze_cli`（見 `docs/map-uanalyze-cli.md`）。
> 待 uanalyze_cli 的 map 走完後，再逐一 graduate 成正式討論。
>
> 整理時間：2026-08-22

---

## 來源 B：`industry_agent`（產業研究報告產生器）

**路徑：** `/Users/richardkuo/Desktop/stock code/stocktool/industry_agent`

**一句話：** 自動化產業與個股基本面研究系統 — 多數據源整合 + PDF 法人報告解析 + 一鍵生成 Markdown/HTML 分析報告。專為台股及連動美股巨頭設計。

**可搬功能盤點：**

| # | 功能 | 檔案 | 與現有專案的關係 |
|---|---|---|---|
| B1 | 多數據源 fetcher：FinMind / Fugle / TWSE / yfinance | `scripts/{finmind,fugle,twse,yfinance}_fetcher.py` | **部分重疊** — 現專案已有 Fugle 股價、FinMind |
| B2 | UAnalyze fetcher | `scripts/uanalyze_fetcher.py` | **重疊** — 現專案已有 `tools/uanalyze.py` |
| B3 | PDF 法人報告解析器 | `scripts/file_parser.py` | 全新 — 掃 `data/raw/report/` 券商 PDF（富邦/國泰/中信/MS） |
| B4 | 美台股聯動分析（美股巨頭 → 台股供應鏈） | `scripts/generate_report.py` | 全新 |
| B5 | 一鍵產業報告生成 → Markdown + HTML | `scripts/generate_report.py` | 全新、**重功能**，含 SWOT / 產業護城河 / 領先指標 / 估值比較 |
| B6 | Agent skills：top-down（產業）/ bottom-up（個股） | `.agents/skills/` | 另一套 Antigravity skill 設計，與現有 `agent/prompts.py` 相關 |

**內建產業模組：** 記憶體、CPO 光通訊、CoWoS 先進封裝（可自訂 `--industry --giant --keywords --stocks`）。

**額外數據源憑證：** 除了現有的 FinMind/Fugle/UAnalyze，還多一個「定錨 Anchors」（`ANCHORS_USERNAME/PASSWORD`）。

**與現有架構的張力：**
- 產出 HTML/Markdown 報告檔，跟「Telegram bot 薄殼」形態不同 → 需決定觸發與交付形態（bot 觸發產檔後傳連結/檔案？）
- 多個 fetcher 與現有工具重疊，需決定合併或並存
- 自帶 Agent skills，與現有 `@mention` prompt 設計如何整合

---

## 來源 C：`cb_analyzer.py`（台灣可轉債 CB 選股系統）

**路徑：** `/Users/richardkuo/Desktop/stock code/stocktool/cb_analyzer.py`（單檔）

**一句話：** 台灣可轉債（CB）自動化數據抓取 + 「權證小哥」全策略實戰選股系統。

**資料來源：** 統一證券 CBAS 資訊網（`cbas16889.pscnet.com.tw`），API + Excel 匯出兩個端點；用 `verify=False`（自訂證書鏈）。

**內建 6 大策略：**
1. 靜態折價套利（Static Arbitrage）
2. 黃金動態避險/蛛網交易（Dynamic Hedging & Grid Trading）
3. 經典雙低聖杯型（Double-Low）
4. 強勢平價攻擊型（Momentum Parity）
5. 保本高殖利率防守型（Defensive Yield to Put）
6. 小哥風控警訊（主力換股離場/高風險警示）

**形態：** 目前是終端輸出（含中文對齊排版 `visual_width`/`pad_str`），輸出到 `cb_output/`。

**與現有架構的張力：**
- 全新資料域（可轉債），現專案沒有任何 CB 相關功能
- 終端表格輸出形態 → 若進 bot 需決定如何在 Telegram 呈現（圖片？文字表？篩選後推播？）
- 6 大策略是否全搬、或只搬選股結果推播

---

## 下一步

1. 先完成 `uanalyze_cli` 的 wayfinder map（`docs/map-uanalyze-cli.md`）
2. 之後 graduate 來源 B（`industry_agent`）— 可能自成一張 map（量大）
3. 最後討論來源 C（`cb_analyzer`）— 單檔、單一資料域，可能一張 grilling ticket 就夠
