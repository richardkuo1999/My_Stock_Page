# 平行股票分析設計文件

**日期：** 2025-03-05
**狀態：** 已核准，待實作

## 問題描述

每日股票掃描（`daily_analysis_job`）處理 500+ 檔股票時，採用順序處理方式，導致執行時間過長。每檔股票需要 3-4 個 API 呼叫（Yahoo Finance、FinMind PER/PBR、FinMind Stock Info、Anue Scraper），整體效能瓶頸明顯。

## 解決方案

**方案 A：平行股票處理**

使用 `asyncio.gather()` 配合 `asyncio.Semaphore` 實現受控的並行處理。

## 設計細節

### 1. 核心架構變更

**修改檔案：** `analysis_bot/scheduler.py`

**原始碼（順序處理）：**
```python
for ticker in tickers:
    result = await analyzer.analyze_stock(ticker)
```

**優化後（平行處理）：**
```python
MAX_CONCURRENT = 10  # 可透過 config 調整
semaphore = asyncio.Semaphore(MAX_CONCURRENT)

async def analyze_with_semaphore(ticker):
    async with semaphore:
        return await analyzer.analyze_stock(ticker)

tasks = [analyze_with_semaphore(ticker) for ticker in tickers]
results = await asyncio.gather(*tasks, return_exceptions=True)
```

### 2. 錯誤處理策略

```python
successful_results = []
failed_tickers = []

for ticker, result in zip(tickers, results):
    if isinstance(result, Exception):
        logger.error(f"Failed to analyze {ticker}: {result}")
        failed_tickers.append(ticker)
    elif "error" in result:
        logger.warning(f"Skipping {ticker}: {result['error']']}")
        failed_tickers.append(ticker)
    else:
        successful_results.append((ticker, result))
```

### 3. 進度追蹤

新增 Telegram 進度推播功能：

```python
total = len(tickers)
processed = 0

async def analyze_with_progress(ticker, index):
    global processed
    result = await analyze_with_semaphore(ticker)
    processed += 1

    # 每 50 檔或最後一檔回報進度
    if processed % 50 == 0 or processed == total:
        await bot.send_message(
            chat_id,
            f"📊 分析進度：{processed}/{total} ({processed/total*100:.0f}%)"
        )
    return result
```

### 4. 資料庫寫入優化

採用分批寫入策略，每 100 檔股票 commit 一次：

```python
BATCH_SIZE = 100

for i, (ticker, result) in enumerate(successful_results):
    # ... 更新 stock_record ...

    if (i + 1) % BATCH_SIZE == 0:
        session.commit()

session.commit()  # 最終 commit
```

### 5. 新增設定項

**修改檔案：** `analysis_bot/config.py`

```python
class Settings(BaseSettings):
    # ... 現有設定 ...

    # 並行分析設定
    MAX_CONCURRENT_ANALYSIS: int = 10  # 最大並發數
    ANALYSIS_PROGRESS_INTERVAL: int = 50  # 進度回報間隔
    ANALYSIS_BATCH_SIZE: int = 100  # 資料庫批次寫入大小
```

## 修改範圍

| 檔案 | 修改類型 | 說明 |
|------|----------|------|
| `scheduler.py` | 主要修改 | 平行處理邏輯、進度追蹤、批次寫入 |
| `config.py` | 小幅新增 | 並行設定參數 |

## 預期效果

- **時間縮短：** 60-80%（假設 API 回應時間穩定）
- **API 負載：** 3 組 FinMind Token 可承受 10 並發請求
- **錯誤隔離：** 單一股票失敗不影響其他股票分析
- **可觀察性：** Telegram 進度推播，使用者可知執行狀態

## 測試計畫

1. 單元測試：驗證 Semaphore 控制邏輯
2. 整合測試：小批量（10 檔）測試平行處理
3. 壓力測試：全量（500+ 檔）測試 API 限流情況
4. 回歸測試：確保低估股票列表計算正確

## 風險與緩解

| 風險 | 緩解措施 |
|------|----------|
| API 限流 | Semaphore 控制並發數，可調整 MAX_CONCURRENT |
| 記憶體壓力 | 分批寫入策略，BATCH_SIZE 可調整 |
| 部分失敗 | return_exceptions=True，錯誤不中斷整體流程 |

## 下一步

進入實作階段，建立 Git worktree 進行開發。