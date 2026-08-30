# 05 — Tool: draw_kchart

**What to build:** `tools/draw_kchart.py` — 繪製 K 線圖並回傳圖片路徑。從舊版 `candlestick_chart.py` 搬移邏輯。依賴 get_stock_price 取得歷史資料。

**Blocked by:** 04 — Tool: get_stock_price

**Status:** done

- [x] `python tools/draw_kchart.py 2330 --period 60` 回傳 `{"image_path": "/tmp/kchart_2330.png"}`
- [x] `from tools.draw_kchart import draw` 可直接 import 使用
- [x] 支援自訂週期（日數）
- [x] 生成的圖片包含 K 線 + 均線
- [x] 找不到代號或資料不足時回傳 `{"error": "..."}`
- [x] 檔頭 docstring 符合規範
- [x] 有 unit test（mock 資料源，驗證圖片生成）
