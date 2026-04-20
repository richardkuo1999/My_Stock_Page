# News Sources

## Overview
**Location:** `analysis_bot/services/news_parser.py`

## News Aggregation Architecture

The `NewsParser` class supports multiple news sources with dedicated fetchers and content parsers.

## Supported Sources

| Source | Method | Parser | Format |
|--------|--------|--------|--------|
| CNYES (鉅亨網) | `fetch_cnyes_newslist()` | `cnyes_news_parser()` | JSON API |
| Google News TW | `rss_parser()` | - | RSS |
| MoneyDJ | `get_moneydj_report()` | `moneyDJ_news_parser()` | RSS |
| Yahoo 股市 | `get_yahoo_tw_report()` | `yahoo_tw_news_parser()` | RSS |
| UDN (聯合新聞網) | `get_udn_report()` | `udn_news_parser()` | RSS |
| UAnalyze | `get_uanalyze_report()` | `uanalyze_news_parser()` | HTML |
| Fugle | `get_fugle_report()` | `fugle_news_parser()` | HTML |
| Vocus (方格子) | `get_vocus_articles()` | `vocus_news_parser()` | Next.js SSR |
| MacroMicro (財經M平方) | `get_macromicro_report()` | `macromicro_news_parser()` | RSS (morss proxy) |
| FinGuider | `get_finguider_report()` | `finguider_news_parser()` | JSON API |
| Fintastic | `get_fintastic_report()` | `fintastic_news_parser()` | RSS (morss proxy) |
| Forecastock | `get_forecastock_report()` | `forecastock_news_parser()` | RSS (morss proxy) |
| NewsDigest AI | `get_news_digest_ai_report()` | `newsdigestai_news_parser()` | RSS |
| SinoTrade | `get_sinotrade_industry_report()` | `sinotrade_news_parser()` | GraphQL |
| Pocket 學堂 | `get_pocket_school_report()` | `pocket_news_parser()` | JSON API |
| Buffett Letters | `get_buffett_letters()` | `fetch_buffett_letter_content()` | PDF/HTML |
| Howard Marks Memos | `get_howard_marks_memos()` | `oaktree_memo_parser()` | HTML/PDF |

## Content Parsing Strategy

Each source has a specific parser method that extracts article content:

```python
parser_dict = {
    "udn": self.udn_news_parser,
    "cnyes": self.cnyes_news_parser,
    # ...
}
```

**Parser Flow:**
1. Check if URL matches a specific parser key
2. Apply site-specific parser
3. Fall back to `_generic_news_parser()` if specific parser fails

## Deduplication Logic

**Location:** `jobs.py` function `check_news_job()`

**Strategy:**
1. **URL Exact Match** - Check if URL already exists in `News` table
2. **Fuzzy Title Match** - Use `difflib.SequenceMatcher` with 0.85 threshold
3. **In-Batch Deduplication** - Avoid duplicates within same fetch batch

```python
# URL check
existing_link = session.exec(select(News).where(News.link == link)).first()

# Fuzzy title check
ratio = difflib.SequenceMatcher(None, title, recent_title).ratio()
if ratio > 0.85:
    is_duplicate_title = True
```

## News Push Notification Flow

**Location:** `jobs.py` `check_news_job()`

1. Fetch from all configured sources
2. Deduplicate against recent articles (24-hour window)
3. Save new articles to database
4. For each subscriber:
   - Check if news matches watchlist tickers
   - If match: Send personalized notification with ticker mention
   - Otherwise: Send standard notification

**Watchlist Matching:**
```python
def _contains_ticker(text_upper: str, ticker_upper: str) -> bool:
    # Avoid substring false positives by enforcing word boundaries
    # e.g., "2330" matches "2330" but not "123301"
```

## Adding a New News Source

1. Add fetcher method in `NewsParser` class
2. Add site-specific parser if needed (for full content extraction)
3. Register in `parser_dict` mapping
4. Add to `check_news_job()` in `jobs.py`
5. Test with `/news` command