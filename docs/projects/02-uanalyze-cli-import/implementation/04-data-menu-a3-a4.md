# 04 — `/data` 選單骨架 + 法人共識(A3) + 財務指標(A4)

**What to build:** 新增快捷指令 `/data <代號>`，仿 `/ua` 的 inline 選單模式。本張建立選單框架並填入前兩個選項：「法人共識」（單季 EPS 實際 vs 法人預估、月/年營收共識）與「財務指標」（每股自由現金流/EPS/EBITDA/ROE/ROIC/股利等，只顯示近 4–5 年）。

**Blocked by:** 01（法人共識跨 cronjob+gidp；財務指標走 cronjob）。

**Status:** DONE

- [x] `/data 2330` 跳 inline 選單；選「法人共識」「財務指標」各回對應資料（濃縮成 Telegram 可讀文字，非倒 JSON）
- [x] 財務指標選單標籤為「財務指標」（非「估值」），只顯示近 4–5 年
- [x] 純資料不呼叫 AI
- [x] Agent 支援：工具 CLI 帶參數（如 `--consensus` / `--pershare`）回**摘要 JSON**；`agent/prompts.py` 新增「data 分析工具」說明（回摘要）
- [x] 文件同步：README（新增 /data 指令 + 工具 CLI 範例）、ARCHITECTURE 指令表、`HELP_TEXT`、map/ticket 狀態
- [x] `tests/test_uanalyze.py`（資料函式）+ `tests/test_handlers.py`（/data 選單 callback）；全套測試綠
