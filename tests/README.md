# 測試指南 (Testing Guide)

## 概述

本專案使用 pytest 作為測試框架。測試分為兩個目錄：
- `tests/` — 核心 services 與 API 測試
- `analysis_bot/tests/` — Bot handler 與 job 測試

## 測試結構

```
tests/
├── conftest.py                # 共享 fixtures（mock_stock_data, mock_stock_info）
├── test_math_utils.py         # MathUtils quartile/percentile/mean_reversion
├── test_math_utils_std.py     # MathUtils.std() 方法
├── test_models.py             # SQLModel 資料模型（StockData, Subscriber, News, Report, Podcast）
├── test_stock_analyzer.py     # StockAnalyzer 服務
├── test_web_api.py            # FastAPI Web API 端點
├── test_volume_spike.py       # VolumeSpikeScanner + MarketDataFetcher + Formatter
├── test_intraday_spike.py     # IntradaySpikeScanner（動態閾值、時段進度）
└── test_threads_telegram_watch.py  # Threads 推播腳本（sanitize, merge_seen, pick_new_posts）

analysis_bot/tests/
├── bot_fakes.py               # 共用 Fake 物件（FakeUpdate, FakeMessage, FakeContext, FakeNewsParser）
├── test_bot_news.py           # /news 指令與 InlineKeyboard 新聞選單
├── test_bot_watchlist.py      # /watch add/remove/list 自選股
├── test_bot_name_command.py   # /name 指令
├── test_bot_menu.py           # /menu 互動選單系統
├── test_bot_google.py         # /google 新聞搜尋
├── test_bot_subscribe.py      # /subscribe, /unsubscribe, /sub_ispike, /unsub_ispike
├── test_bot_threads.py        # /threads add/remove/list
├── test_bot_ua_mega.py        # /ua, /uask, /mega 指令
├── test_news_watchlist_mentions.py  # check_news_job 自選股新聞比對
├── test_uanalyze_monitor.py   # UAnalyze 報告監控（state, format, check_new_reports）
└── test_http_session.py       # http.py create_session SSL 驗證
```

## 執行測試

### 執行所有測試
```bash
python -m pytest tests/ analysis_bot/tests/ -v
```

### 執行特定測試檔案
```bash
python -m pytest tests/test_math_utils.py -v
```

### 執行特定測試類別或方法
```bash
python -m pytest tests/test_math_utils.py::TestMathUtilsStd::test_std_with_valid_data -v
```

### 執行測試並生成覆蓋率報告
```bash
python -m pytest tests/ analysis_bot/tests/ -v --cov=analysis_bot --cov-report=html --cov-report=term
```

## 測試依賴

- `pytest` — 主要測試框架
- `pytest-asyncio` — 異步測試支援
- `pytest-mock` — Mock 功能
- `pytest-cov` — 覆蓋率報告

## 共用 Fixtures 與 Fakes

### `tests/conftest.py`
- `mock_stock_data` — 模擬股票歷史資料 DataFrame
- `mock_stock_info` — 模擬股票基本資訊字典

### `analysis_bot/tests/bot_fakes.py`
- `FakeMessage` — 記錄 `reply_text` 呼叫
- `FakeCallbackQuery` — 記錄 `answer` 和 `edit_message_text` 呼叫
- `FakeUpdate` — 可設定 `chat_id`, `user_id`, `message`, `callback_query`
- `FakeContext` — 可設定 `args`, `bot_data`
- `FakeNewsParser` — 以 `results_by_key` 控制各新聞來源回傳值

## 編寫測試的指導原則

### 命名規範
- 測試檔案：`test_<module>.py`
- 測試函式：`test_<method>_<scenario>`
- 測試類別：`Test<ClassName>`

### 最佳實踐
- 每個測試只測試一個行為
- 使用 fixtures 設置測試環境
- 對外部依賴使用 mock（DB 用 in-memory SQLite，HTTP 用 monkeypatch）
- Bot handler 測試使用 `bot_fakes.py` 中的 Fake 物件
- 需要 DB 的測試使用 `tmp_path` + in-memory engine + `monkeypatch`
