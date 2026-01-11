# 測試指南 (Testing Guide)

## 概述

本專案使用 pytest 作為測試框架，採用測試驅動開發 (TDD) 方法。目前測試覆蓋率約為 24%。

## 測試結構

```
tests/
├── conftest.py           # 共享 fixtures 和測試配置
├── test_math_utils.py     # MathUtils 服務測試
├── test_math_utils_std.py # MathUtils.std() 方法測試
├── test_models.py         # 資料模型測試
├── test_stock_analyzer.py # StockAnalyzer 服務測試
└── test_web_api.py       # Web API 端點測試
```

## 已實施的測試

### 1. MathUtils 測試 (100% 覆蓋率)
- 標準差計算 (std)
- 四分位數計算 (quartile)
- 百分位數排名 (percentile_rank)
- 平均回歸分析 (mean_reversion)
- 標籤生成 (_generate_band_labels)

### 2. StockAnalyzer 測試 (84% 覆蓋率)
- 有效的股票代碼分析
- 空歷史資料處理
- 異常情況處理
- TW 股票後援機制
- 美國股代碼處理

### 3. 資料模型測試 (100% 覆蓋率)
- StockData 模型
- Subscriber 模型
- News 模型
- Report 模型
- Podcast 模型

### 4. Web API 測試 (64% 覆蓋率)
- 健康檢查端點
- 股票分析 API
- 設定 API (toggle tag, update list)

## 執行測試

### 執行所有測試
```bash
python -m pytest tests/ -v
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
python -m pytest tests/ -v --cov=analysis_bot --cov-report=html --cov-report=term
```

覆蓋率報告將在 `htmlcov/` 目錄中生成，開啟 `htmlcov/index.html` 查看詳細報告。

## 測試依賴

測試所需套件已包含在 `requirements.txt` 中：

- `pytest==8.1.1` - 主要測試框架
- `pytest-asyncio==0.23.6` - 異步測試支援
- `pytest-mock==3.14.0` - Mock 功能
- `pytest-cov==5.0.0` - 覆蓋率報告

## 編寫測試的指導原則

### TDD 循環
1. **RED** - 編寫一個失敗的測試
2. **GREEN** - 編寫最少的程式碼讓測試通過
3. **REFACTOR** - 清理和重構程式碼

### 測試命名規範
- 使用描述性名稱：`test_method_with_scenario`
- 測試類別以 `Test` 開頭
- 測試方法以 `test_` 開頭

### 最佳實踐
- 每個測試應該只測試一個行為
- 使用 fixtures 來設置測試環境
- 對外部依賴使用 mock
- 測試正常路徑和錯誤情況

## 常用 fixtures

### `in_memory_db`
使用記憶體 SQLite 資料庫進行測試，不會影響實際資料庫。

### `db_session`
提供資料庫會話用於測試資料模型操作。

### `mock_stock_data`
提供模擬的股票歷史資料 (DataFrame)。

### `mock_stock_info`
提供模擬的股票基本資訊字典。

## 待實施的測試

- [ ] Bot Handlers 測試 (目前覆蓋率 13%)
- [ ] Jobs 測試 (目前覆蓋率 8%)
- [ ] Scheduler 測試 (目前覆蓋率 6%)
- [ ] ReportGenerator 測試 (目前覆蓋率 2%)
- [ ] StockSelector 測試 (目前覆蓋率 0%)

## 持續改進

測試覆蓋率目標：
- 短期：核心服務達到 70% 以上
- 中期：整體覆蓋率達到 60% 以上
- 長期：整體覆蓋率達到 80% 以上

當新增功能時，請遵循 TDD 原則：
1. 先寫測試
2. 確認測試失敗
3. 實作功能
4. 確認測試通過
5. 重構並保持測試通過
