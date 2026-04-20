# Stock Analysis

## Overview
The "樂活五線譜" (Lohas Five-Line Spectrum) is the core algorithm for mean reversion analysis.

## Algorithm Components

### MathUtils Methods
**Location:** `analysis_bot/services/math_utils.py`

There are **two different methods** for calculating bands:

#### 1. `std()` - Median-Based Bands (Legacy)
- Uses **median** as the baseline (TL = median of prices)
- Used for simple standard deviation analysis
- Returns band labels: `TL±3SD`, `TL±2SD`, `TL±1SD`, `TL`

```python
# Median-based TL
tl_val = statistics.median(datas_np)
sd = np.std(datas_np - tl_val, ddof=1)
```

#### 2. `mean_reversion()` - Linear Regression Bands (Primary)
**This is the core algorithm for stock valuation.**

**Core Logic:**
1. **Trend Line (TL)** - Linear regression fit to price series
2. **Standard Deviation Bands** - Calculate SD bands at ±1, ±2, ±3 SD from TL
3. **Probability Estimation** - Use CDF approximation for movement probability
4. **Expected Value Calculation** - Risk/reward for bull/bear scenarios

```python
# Trend line calculation (linear regression)
slope, intercept = np.polyfit(idx, prices_np, 1)
tl = intercept + idx * slope
y_minus_tl = prices_np - tl
sd = np.std(y_minus_tl, ddof=1)

# Band calculation
for i in range(1, 4):
    bands[f"TL-{i}SD"] = (tl - i * sd).tolist()
    bands[f"TL+{i}SD"] = (tl + i * sd).tolist()
```

### Lohas Five-Line Labels

| Index | Label | Meaning |
|-------|-------|---------|
| 0 | 超極樂觀價位 | TL+3SD |
| 1 | 極樂觀價位 | TL+2SD |
| 2 | 樂觀價位 | TL+1SD |
| 3 | 趨勢價位 | TL |
| 4 | 悲觀價位 | TL-1SD |
| 5 | 極悲觀價位 | TL-2SD |
| 6 | 超極悲觀價位 | TL-3SD |

## Data Sources for Analysis

**Location:** `analysis_bot/services/stock_analyzer.py`

1. **Yahoo Finance** - Price history, basic info (PE, PB, EPS, sector)
2. **FinMind API** - Historical PER/PBR for Taiwan stocks
3. **Anue (鉅亨網)** - FactSet estimated EPS and target price

## Analysis Result Structure

```python
{
    "ticker": "2330",
    "name": "台積電",
    "sector": "半導體",
    "price": 600.0,
    "exchange": "TWSE",
    "financials": {
        "eps_ttm": 35.0,
        "forward_eps": 38.0,
        "pe_ttm": 17.14,
        "pb": 3.5,
        "bps": 170.0,
        "target_mean_price": 700.0,
        "gross_margins": 0.55,
        "long_business_summary": "..."
    },
    "estimates": {  # From Anue
        "est_eps": 36.5,
        "est_pe": 16.44,
        "est_price": 650.0,
        "date": "2024-01-15",
        "url": "..."
    },
    "analysis": {
        "mean_reversion": {
            "prob": [35.0, 10.0, 55.0],  # Up, Hold, Down
            "TL": [580.0],
            "expect": [15.0, 20.0, -10.0],
            "targetprice": [720, 680, 640, 580, 520, 480, 440],
            "bands": {...},
            "lohas_years": 3.5
        },
        "pe_stats": {
            "quartile": [15.0, 18.0, 22.0, 19.5],
            "bands": [...],
            "percentile": 45.0
        },
        "pb_stats": {...}
    },
    "chart_data": {
        "dates": ["2023-01-01", ...],
        "close": [580, 585, ...]
    }
}
```

## Report Generation

**Full Report:** `ReportGenerator.generate_full_report()`
- Comprehensive text format with all metrics

**Telegram Report:** `ReportGenerator.generate_telegram_report()`
- Compact format optimized for Telegram display

## Cache Strategy

**Location:** `analysis_bot/services/stock_service.py`

**TTL:** 6 hours

**Flow:**
```python
if not force_update:
    cached = session.exec(select(StockData).where(StockData.ticker == ticker)).first()
    if cached and cached.last_analyzed < datetime.now() - timedelta(hours=6):
        return json.loads(cached.data), True  # from_cache

# Analyze fresh
data = await analyzer.analyze_stock(ticker)
# Save to DB
stock_record.data = json.dumps(data)
session.commit()
return data, False
```

## Daily Analysis Job

**Location:** `analysis_bot/scheduler.py`

**Tags System:**
- `ETF` - ETF constituent stocks
- `ETF_Rank` - Top-ranked ETF stocks
- `Institutional_TOP50` - Institutional top 50 holdings
- `InvestAnchor` - Anchor investor stocks
- `User_Choice` - User-selected stocks

**Workflow:**
1. Load active tags from `SystemConfig`
2. Fetch stock lists for each tag via `StockSelector`
3. Merge with existing tracked stocks
4. Run analysis for each stock
5. Generate ZIP file with all reports
6. Identify underestimated stocks (price < TL-1SD)
7. Send to subscribers

## Modifying the Analysis Algorithm

1. Core math is in `math_utils.py`
2. Data fetching is in `stock_analyzer.py`
3. Report formatting is in `report_generator.py`
4. Always run tests after changes: `python -m pytest tests/test_math_utils.py -v`