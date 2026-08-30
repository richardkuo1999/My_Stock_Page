# 延後討論的引入來源（Not yet specified）

<!-- labels: backlog, deferred -->

> 這裡是已知想引入、但**尚未進入 wayfinder map** 的來源。
> `uanalyze_cli` 的 map 已走完（見 `docs/done/projects/02-uanalyze-cli-import/`），
> 剩餘來源待逐一 graduate 成正式討論。
>
> 整理時間：2026-08-22（2026-08-30 更新：來源 B `industry_agent` 已移除，另開獨立專案整併）

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

1. 先完成 `uanalyze_cli` 的 wayfinder map（已完成，見 `docs/done/projects/02-uanalyze-cli-import/`）
2. graduate 來源 C（`cb_analyzer`）— 單檔、單一資料域，可能一張 grilling ticket 就夠

> 來源 B（`industry_agent`）**不引入本專案**，之後另開獨立專案並與其他東西整併，已從本檔移除。
