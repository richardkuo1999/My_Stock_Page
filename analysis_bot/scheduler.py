import asyncio
import json
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlmodel import Session, select

from .database import engine
from .models.stock import StockData
from .services.podcast_service import PodcastService
from .services.stock_analyzer import StockAnalyzer

scheduler = AsyncIOScheduler()
logger = logging.getLogger(__name__)


async def daily_analysis_job(run_daily=True, run_anchors=True, run_tracked=True):

    logger.info("Starting daily analysis job...")
    analyzer = StockAnalyzer()

    # Reuse existing bot instance from the running application if available
    import os
    import tempfile
    import zipfile
    from pathlib import Path

    from .config import get_settings
    from .services.report_generator import ReportGenerator

    settings = get_settings()

    # Try to get the bot from the running application to avoid creating duplicate instances
    from . import main as _main_mod

    if getattr(_main_mod, "bot_app", None) and _main_mod.bot_app.bot:
        bot = _main_mod.bot_app.bot
    else:
        from telegram import Bot

        bot = Bot(token=settings.TELEGRAM_TOKEN)

    chat_id = settings.TELEGRAM_CHAT_ID  # Admin/Main Group
    from .utils.pii import redact_telegram_id

    pii_salt = settings.LOG_PII_SALT or None

    # Send Start Message
    if chat_id:
        try:
            await bot.send_message(chat_id=chat_id, text="🚀 Daily Analysis Run Started...")
        except Exception as e:
            logger.error(f"Failed to send start msg: {e}")

    # 0. Load Active Tags
    from .services.stock_service import StockService

    active_tags = await asyncio.to_thread(StockService.get_daily_tags)
    logger.info(f"Active Tags: {active_tags}")

    # 1. Initialize StockSelector
    from .services.stock_selector import StockSelector

    selector = StockSelector()

    final_tickers_map = {}  # Ticker -> Set of Tags

    import aiohttp

    async with aiohttp.ClientSession() as http_session:
        # --- Tag: ETF ---
        if "ETF" in active_tags:
            try:
                targets = await selector.get_target_etfs()  # List of '0050', '0056'
                logger.info(f"Processing Target ETFs: {targets}")
                for etf_code in targets:
                    constituents = await selector.fetch_etf_constituents(http_session, etf_code)
                    for c in constituents:
                        if c not in final_tickers_map:
                            final_tickers_map[c] = set()
                        final_tickers_map[c].add(f"ETF_{etf_code}")
            except Exception as e:
                logger.error(f"Error processing ETF tag: {e}")

        # --- Tag: ETF_Rank ---
        if "ETF_Rank" in active_tags:
            try:
                stocks = await selector.fetch_etf_rank_stocks(http_session)
                for s in stocks:
                    if s not in final_tickers_map:
                        final_tickers_map[s] = set()
                    final_tickers_map[s].add("ETF_Rank")
            except Exception as e:
                logger.error(f"Error processing ETF_Rank: {e}")

        # --- Tag: Institutional_TOP50 ---
        if "Institutional_TOP50" in active_tags:
            try:
                stocks = await selector.fetch_institutional_top50(http_session)
                for s in stocks:
                    if s not in final_tickers_map:
                        final_tickers_map[s] = set()
                    final_tickers_map[s].add("Institutional")
            except Exception as e:
                logger.error(f"Error processing Institutional: {e}")

        # --- Tag: Invest Anchors ---
        if "investanchors" in active_tags:
            try:
                stocks = await selector.get_invest_anchors()
                for s in stocks:
                    if s not in final_tickers_map:
                        final_tickers_map[s] = set()
                    final_tickers_map[s].add("InvestAnchor")
            except Exception as e:
                logger.error(f"Error processing Anchors: {e}")

        # --- Tag: User Choice ---
        if "User_Choice" in active_tags:
            try:
                stocks = await selector.get_user_choice()
                for s in stocks:
                    if s not in final_tickers_map:
                        final_tickers_map[s] = set()
                    final_tickers_map[s].add("User_Choice")
            except Exception as e:
                logger.error(f"Error processing User Choice: {e}")

    # 2. Update DB Tags (Merge with existing or Create new)
    def update_db_tags(final_map, managed_tags):
        with Session(engine) as session:
            # Fetch all existing stocks to clean up old tags
            all_stocks = session.exec(select(StockData)).all()
            existing_tickers = {s.ticker for s in all_stocks}

            # 1. Update Existing Stocks (Clean old managed tags + Add new ones)
            for stock in all_stocks:
                current_tags = set(stock.tag.split(",")) if stock.tag else set()

                # Remove Managed Tags (Exact match or Prefix for ETF_ codes)
                tags_to_keep = set()
                for t in current_tags:
                    if t in managed_tags or t.startswith("ETF_"):
                        continue
                    tags_to_keep.add(t)

                # Add back new tags if this stock is in the current map
                if stock.ticker in final_map:
                    tags_to_keep.update(final_map[stock.ticker])

                # Update DB if changed
                new_tag_str = ",".join(sorted(tags_to_keep))
                if stock.tag != new_tag_str:
                    stock.tag = new_tag_str
                    session.add(stock)

            # 2. Create New Stocks (That didn't exist in DB)
            for ticker, new_tags in final_map.items():
                if ticker not in existing_tickers:
                    stock = StockData(ticker=ticker, tag=",".join(sorted(new_tags)))
                    session.add(stock)

            session.commit()
            return existing_tickers

    MANAGED_TAG_SET = {"ETF", "ETF_Rank", "Institutional", "InvestAnchor", "User_Choice"}
    existing_tickers = await asyncio.to_thread(update_db_tags, final_tickers_map, MANAGED_TAG_SET)

    # 3. Final List to Analyze (Active tags + Tracked if enabled)
    if run_tracked:
        ticker_set = set(final_tickers_map.keys())
        ticker_set.update(existing_tickers)
        final_tickers = list(ticker_set)
    else:
        final_tickers = list(final_tickers_map.keys())

    logger.info(
        f"Analyzing {len(final_tickers)} stocks (Daily={run_daily}, Anchors={run_anchors}, Tracked={run_tracked})"
    )
    tickers = list(final_tickers)

    # If no tickers were selected, we should notify and exit early (otherwise users see only the start message).
    if not tickers:
        logger.warning(
            "No tickers selected for daily analysis. Check active_daily_tags or enable run_tracked."
        )
        if chat_id:
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Daily run skipped: 沒有任何股票被選入分析清單（請先在 Settings 開啟 tags，或改用 Tracked 模式）。",
                )
            except Exception as e:
                logger.error(f"Failed to send empty-tickers msg: {e}")
        return

    # Temp dir for reports
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        report_path = temp_path / "reports"
        report_path.mkdir()

        # === Parallel Stock Analysis ===
        MAX_CONCURRENT = settings.MAX_CONCURRENT_ANALYSIS
        PROGRESS_INTERVAL = settings.ANALYSIS_PROGRESS_INTERVAL
        BATCH_SIZE = settings.ANALYSIS_BATCH_SIZE

        semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        processed_count = 0
        progress_lock = asyncio.Lock()

        async def analyze_single_stock(ticker: str) -> tuple[str, dict | None, str | None]:
            """
            Analyze a single stock with semaphore control.
            Returns: (ticker, result or None, error_message or None)
            """
            nonlocal processed_count
            try:
                async with semaphore:
                    result = await analyzer.analyze_stock(ticker)

                if "error" in result:
                    return (ticker, None, result["error"])

                return (ticker, result, None)
            except Exception as e:
                return (ticker, None, str(e))

        async def analyze_with_progress(ticker: str) -> tuple[str, dict | None, str | None]:
            """
            Wrapper that tracks progress and sends updates.
            """
            nonlocal processed_count
            result = await analyze_single_stock(ticker)

            async with progress_lock:
                processed_count += 1
                current = processed_count
                total = len(tickers)

            # Send progress update at intervals
            if current % PROGRESS_INTERVAL == 0 or current == total:
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"📊 分析進度：{current}/{total} ({current / total * 100:.0f}%)",
                    )
                except Exception as e:
                    logger.warning(f"Failed to send progress update: {e}")

            return result

        logger.info(f"Starting parallel analysis with MAX_CONCURRENT={MAX_CONCURRENT}")
        await bot.send_message(
            chat_id=chat_id,
            text=f"🔍 開始分析 {len(tickers)} 檔股票（並發數：{MAX_CONCURRENT}）...",
        )

        # Run all analyses in parallel
        results = await asyncio.gather(
            *[analyze_with_progress(ticker) for ticker in tickers], return_exceptions=True
        )

        # Process results
        successful_results = []
        failed_tickers = []

        for i, result in enumerate(results):
            ticker = tickers[i]
            if isinstance(result, Exception):
                logger.error(f"Exception analyzing {ticker}: {result}")
                failed_tickers.append((ticker, str(result)))
            elif result[2] is not None:  # error_message
                logger.warning(f"Skipping {ticker}: {result[2]}")
                failed_tickers.append((ticker, result[2]))
            elif result[1] is not None:  # has result
                successful_results.append((ticker, result[1]))

        logger.info(
            f"Analysis complete: {len(successful_results)} succeeded, {len(failed_tickers)} failed"
        )

        # Send failure summary if any
        if failed_tickers and chat_id:
            fail_msg = f"⚠️ 失敗 {len(failed_tickers)} 檔：\n"
            fail_msg += "\n".join(
                [
                    f"- {t}: {e[:30]}..." if len(e) > 30 else f"- {t}: {e}"
                    for t, e in failed_tickers[:10]
                ]
            )
            if len(failed_tickers) > 10:
                fail_msg += f"\n... 及其他 {len(failed_tickers) - 10} 檔"
            try:
                await bot.send_message(chat_id=chat_id, text=fail_msg)
            except Exception as e:
                logger.warning(f"Failed to send failure summary: {e}")

        underestimated_stocks = []

        # Batch database writes (Synchronous part moved to to_thread)
        def process_results_and_generate_reports(results_list, report_dir):
            underestimated = []
            with Session(engine) as session:
                for i, (ticker, result) in enumerate(results_list):
                    try:
                        # Update DB (StockData)
                        json_data = json.dumps(result)

                        stock_record = session.exec(
                            select(StockData).where(StockData.ticker == ticker)
                        ).first()

                        if not stock_record:
                            stock_record = StockData(ticker=ticker)
                            session.add(stock_record)

                        stock_record.data = json_data
                        stock_record.name = result.get("name")
                        stock_record.sector = result.get("sector")
                        stock_record.price = result.get("price")
                        stock_record.last_analyzed = datetime.now()
                        session.add(stock_record)

                        # Generate Report
                        report_text = ReportGenerator.generate_full_report(result)
                        filename = f"{ticker}_{result.get('name', 'Stock').replace('/', '_')}.txt"

                        with open(report_dir / filename, "w", encoding="utf-8") as f:
                            f.write(report_text)

                        # Check Underestimated
                        mr = result.get("analysis", {}).get("mean_reversion", {})
                        targets = mr.get("targetprice", [])
                        price = result.get("price", 0)

                        if len(targets) > 4 and price > 0:
                            target_sad = targets[4]  # TL-1SD (TL-SD)
                            if price < target_sad:
                                potential = (target_sad - price) / price * 100
                                underestimated.append(
                                    {
                                        "ticker": ticker,
                                        "name": result.get("name"),
                                        "price": price,
                                        "target": target_sad,
                                        "potential": potential,
                                        "sector": result.get("sector", "N/A"),
                                    }
                                )

                        # Batch commit every BATCH_SIZE records
                        if (i + 1) % BATCH_SIZE == 0:
                            session.commit()
                            logger.debug(f"Committed batch at {i + 1} records")

                    except Exception as e:
                        logger.error(f"Error processing result for {ticker}: {e}")

                # Final commit for remaining records
                session.commit()
            return underestimated

        underestimated_stocks = await asyncio.to_thread(
            process_results_and_generate_reports, successful_results, report_path
        )

        # 4. Create ZIP
        reports_dir = Path("reports")
        reports_dir.mkdir(exist_ok=True)

        zip_filename = f"Daily_Report_{datetime.now().strftime('%Y%m%d')}.zip"
        zip_filepath = reports_dir / zip_filename

        with zipfile.ZipFile(zip_filepath, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root, _dirs, files in os.walk(report_path):
                for file in files:
                    zipf.write(os.path.join(root, file), arcname=file)

        # 5. Send Notifications (ZIP + Underestimated)
        under_msg = "📉 **Underestimated Stocks (Price < TL-SD)**\n\n"
        if underestimated_stocks:
            underestimated_stocks.sort(key=lambda x: x["potential"], reverse=True)
            header = f"{'Code':<6} {'Name':<6} {'Sector':<6} {'Pot%':>5}\n"
            under_msg += f"```\n{header}"
            for s in underestimated_stocks:
                nm = (s.get("name") or "N/A")[:6]
                sec = (s.get("sector") or "N/A")[:6]
                pot = s.get("potential")
                pot_str = f"{pot:>5.1f}%" if pot is not None else "N/A"
                under_msg += f"{s['ticker']:<6} {nm:<6} {sec:<6} {pot_str}\n"
            under_msg += "```"
        else:
            under_msg += "No stocks found below TL-SD."

        async def send_daily_bundle(target_chat_id):
            try:
                with open(zip_filepath, "rb") as f:
                    await bot.send_document(
                        chat_id=target_chat_id,
                        document=f,
                        filename=zip_filename,
                        caption="📊 Daily Analysis Reports",
                        read_timeout=60,
                        write_timeout=60,
                        connect_timeout=60,
                    )
                await bot.send_message(
                    chat_id=target_chat_id, text=under_msg, parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(
                    f"Failed to send bundle to {redact_telegram_id(target_chat_id, salt=pii_salt)}: {e}"
                )

        if chat_id:
            try:
                await bot.send_message(chat_id=chat_id, text="✅ Run Finished. Sending results...")
            except Exception as e:
                logger.warning("Failed to send run-finished msg: %s", e)
            await send_daily_bundle(chat_id)

        from .models.subscriber import Subscriber

        def get_subscribers():
            with Session(engine) as session:
                subs = session.exec(select(Subscriber).where(Subscriber.is_active)).all()
                return [s.chat_id for s in subs]

        subscribers = await asyncio.to_thread(get_subscribers)

        for sub_id in subscribers:
            await send_daily_bundle(sub_id)

    logger.info("Daily analysis job completed.")


async def daily_podcast_job():
    """Daily podcast fetch and summary job."""
    logger.info("Starting daily podcast job...")
    service = PodcastService()

    # Reuse existing bot instance from the running application if available
    from sqlmodel import Session, select

    from .config import get_settings
    from .database import engine
    from .models.subscriber import Subscriber

    settings = get_settings()

    from . import main as _main_mod

    if getattr(_main_mod, "bot_app", None) and _main_mod.bot_app.bot:
        bot = _main_mod.bot_app.bot
    else:
        from telegram import Bot

        bot = Bot(token=settings.TELEGRAM_TOKEN)

    chat_id = settings.TELEGRAM_CHAT_ID
    from .utils.pii import redact_telegram_id

    pii_salt = settings.LOG_PII_SALT or None

    try:
        # Returns list of (path, host, title, url)
        new_episodes = await service.process_daily_podcasts()

        def get_sub_ids():
            with Session(engine) as session:
                subs = session.exec(select(Subscriber).where(Subscriber.is_active)).all()
                return [s.chat_id for s in subs]

        sub_ids = await asyncio.to_thread(get_sub_ids)

        for file_path, host, title, url in new_episodes:
            if not file_path.exists():
                continue

            caption = f"🎙️ **{host}** - {title}\nSummary Generated."

            # Send to Admin/Group
            if chat_id:
                try:
                    with open(file_path, "rb") as f:
                        await bot.send_document(
                            chat_id=chat_id,
                            document=f,
                            filename=file_path.name,
                            caption=caption,
                            parse_mode="Markdown",
                        )
                    logger.info(
                        f"Sent {title} to Main Chat {redact_telegram_id(chat_id, salt=pii_salt)}"
                    )
                except Exception as e:
                    logger.error(f"Failed to send to Main Chat: {e}")

            # Send to Subscribers
            for sub_id in sub_ids:
                try:
                    with open(file_path, "rb") as f:
                        await bot.send_document(
                            chat_id=sub_id,
                            document=f,
                            filename=file_path.name,
                            caption=caption,
                            parse_mode="Markdown",
                        )
                except Exception as e:
                    logger.error(
                        f"Failed to send to subscriber {redact_telegram_id(sub_id, salt=pii_salt)}: {e}"
                    )

            # Mark as processed in DB (so we don't process again)
            await asyncio.to_thread(service.mark_as_processed, host, title, url)

            # Remove file after sending? Or keep for record?
            # Implementation plan said "Clean up file after sending"
            try:
                import os

                os.remove(file_path)
            except Exception as e:
                logger.warning(f"Error removing file {file_path}: {e}")

    except Exception as e:
        logger.error(f"Podcast job failed: {e}")


async def daily_volume_spike_job():
    """Daily job: scan for volume spikes + AI news analysis, push to Telegram."""
    logger.info("Starting daily volume spike job...")

    from .config import get_settings
    from .models.subscriber import Subscriber
    from .services.volume_spike_scanner import VolumeSpikeScanner, SpikeSortBy

    settings = get_settings()

    # 從設定檔讀取排序方式
    try:
        sort_by = SpikeSortBy(settings.SPIKE_DEFAULT_SORT)
    except ValueError:
        logger.warning(
            f"Invalid SPIKE_DEFAULT_SORT: {settings.SPIKE_DEFAULT_SORT}, fallback to RATIO"
        )
        sort_by = SpikeSortBy.RATIO

    # Reuse running bot instance
    from . import main as _main_mod

    if getattr(_main_mod, "bot_app", None) and _main_mod.bot_app.bot:
        bot = _main_mod.bot_app.bot
    else:
        from telegram import Bot

        bot = Bot(token=settings.TELEGRAM_TOKEN)

    chat_id = settings.TELEGRAM_CHAT_ID
    from .utils.pii import redact_telegram_id

    pii_salt = settings.LOG_PII_SALT or None

    try:
        scanner = VolumeSpikeScanner()

        # 1. Scan
        spike_scan = await scanner.scan(sort_by=sort_by)
        results = spike_scan.results

        # 順帶儲存 MA20 快照（供隔日盤中爆量偵測使用）
        if spike_scan.ma20_snapshot:
            await _save_ma20_snapshot(spike_scan.ma20_snapshot)

        if not results:
            if chat_id:
                await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "📊 無符合條件之爆量股（成交量 ≥ 1000 張，倍數 ≥ 1.5x）\n\n"
                        f"📅 {spike_scan.data_date_caption}"
                    ),
                )
            logger.info("No volume spike stocks found.")
            return

        from .config import get_settings

        if get_settings().SPIKE_NEWS_ENRICHMENT_ENABLED:
            try:
                results = await scanner.enrich_with_news(results, top_n=1)
            except Exception as e:
                logger.error(f"Spike news enrichment failed: {e}")

        from .services.spike_pager import (
            build_spike_markdown_header,
            build_spike_telegram_html_messages,
        )

        _spike_header = build_spike_markdown_header(len(results), sort_by=sort_by)
        spike_msgs = build_spike_telegram_html_messages(results, _spike_header)

        async def send_to(target_id):
            try:
                for m in spike_msgs:
                    await bot.send_message(
                        chat_id=target_id,
                        text=m,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                    await asyncio.sleep(0.5)  # 避免 Telegram flood control
            except Exception as e:
                logger.error(
                    f"Failed to send spike table to {redact_telegram_id(target_id, salt=pii_salt)}: {e}"
                )

        async def send_detail(target_id, text):
            try:
                await bot.send_message(
                    chat_id=target_id,
                    text=text,
                    parse_mode="Markdown",
                    disable_web_page_preview=True,
                )
            except Exception as e:
                logger.error(f"Failed to send spike detail: {e}")

        if chat_id:
            await send_to(chat_id)

        for r in results[:1]:
            if r.analysis and r.analysis != "近期無相關新聞":
                detail = f"📈 *{r.name}*（{r.ticker}）{r.spike_ratio:.1f}x\n{r.analysis}"
                if chat_id:
                    await send_detail(chat_id, detail)
            break

        # 4. Send to subscribers
        def get_sub_chat_ids():
            with Session(engine) as session:
                subs = session.exec(select(Subscriber).where(Subscriber.is_active)).all()
                return [s.chat_id for s in subs]

        sub_ids = await asyncio.to_thread(get_sub_chat_ids)

        for sub_id in sub_ids:
            await send_to(sub_id)
            for r in results[:1]:
                if r.analysis and r.analysis != "近期無相關新聞":
                    detail = f"📈 *{r.name}*（{r.ticker}）{r.spike_ratio:.1f}x\n{r.analysis}"
                    await send_detail(sub_id, detail)
                break
            await asyncio.sleep(0.5)

    except Exception as e:
        logger.error(f"Volume spike job failed: {e}")
        if chat_id:
            try:
                await bot.send_message(chat_id=chat_id, text=f"❌ 爆量偵測失敗：{str(e)[:100]}")
            except Exception:
                pass

    logger.info("Daily volume spike job completed.")


# --- 盤中爆量：去重工具函數 ---

_INTRADAY_NOTIFIED_KEY_PREFIX = "intraday_spike_notified_"


def _intraday_notified_key() -> str:
    from zoneinfo import ZoneInfo
    date_str = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y%m%d")
    return f"{_INTRADAY_NOTIFIED_KEY_PREFIX}{date_str}"


def _load_intraday_notified() -> set[str]:
    """讀取今日已通知的盤中爆量股票清單（去重用）。"""
    from .models.config import SystemConfig
    key = _intraday_notified_key()
    try:
        with Session(engine) as session:
            row = session.exec(
                select(SystemConfig).where(SystemConfig.key == key)
            ).first()
            if row:
                return set(json.loads(row.value))
    except Exception as e:
        logger.warning(f"Intraday notified load failed: {e}")
    return set()


def _save_intraday_notified(tickers: set[str]) -> None:
    """寫入今日已通知的盤中爆量股票清單。"""
    from .models.config import SystemConfig
    key = _intraday_notified_key()
    try:
        with Session(engine) as session:
            row = session.exec(
                select(SystemConfig).where(SystemConfig.key == key)
            ).first()
            value = json.dumps(sorted(tickers))
            if row:
                row.value = value
                session.add(row)
            else:
                session.add(SystemConfig(key=key, value=value))
            session.commit()
    except Exception as e:
        logger.warning(f"Intraday notified save failed: {e}")


async def premarket_vol19_job() -> None:
    """
    盤前排程（08:00）：yfinance 抓全市場過去 19 日成交量加總，存入 IntradayMA20Snapshot。
    盤中爆量偵測 MA20 公式：(今日即時量 + vol_19d_sum) / 20
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import yfinance as yf

    from .models.intraday_ma import IntradayMA20Snapshot
    from .services.market_data_fetcher import MarketDataFetcher

    logger.info("盤前 vol19 掃描開始")

    # 1. 取得全市場股票清單
    try:
        all_stocks = await MarketDataFetcher.fetch_all_market_daily()
    except Exception as e:
        logger.error("盤前 vol19：取得市場清單失敗 %s", e)
        return

    # 過濾 4 碼一般股，排除極度冷門股（< 100 張）
    stocks = [
        s for s in all_stocks
        if s.get("ticker") and s.get("volume_shares", 0) >= 100_000  # 100 張 = 100,000 股
    ]
    if not stocks:
        logger.warning("盤前 vol19：無有效股票")
        return

    logger.info("盤前 vol19：%d 支股票待下載", len(stocks))

    # 2. 轉換 yfinance ticker
    stock_map: dict[str, dict] = {}
    yf_tickers: list[str] = []
    for s in stocks:
        suffix = ".TW" if s["market"] == "TWSE" else ".TWO"
        yf_t = f"{s['ticker']}{suffix}"
        yf_tickers.append(yf_t)
        stock_map[yf_t] = s

    # 3. 批次下載（每批 100 支），取過去 19 個交易日成交量
    BATCH_SIZE = 100
    vol19_map: dict[str, float] = {}  # ticker → 19 日量加總（張）

    def _download(tickers: list[str]):
        return yf.download(
            tickers,
            period="30d",      # 30 天含約 21 個交易日，足以取得 19 個交易日資料
            group_by="ticker",
            threads=False,
            progress=False,
        )

    for i in range(0, len(yf_tickers), BATCH_SIZE):
        batch = yf_tickers[i: i + BATCH_SIZE]
        logger.info("盤前 vol19 下載 %d-%d/%d", i + 1, min(i + BATCH_SIZE, len(yf_tickers)), len(yf_tickers))
        try:
            hist = await asyncio.to_thread(_download, batch)
        except Exception as e:
            logger.warning("盤前 vol19 批次下載失敗: %s", e)
            continue

        for yf_t in batch:
            ticker = yf_t.rsplit(".", 1)[0]
            try:
                if len(batch) == 1:
                    df = hist
                else:
                    if yf_t not in hist.columns.get_level_values(0):
                        continue
                    df = hist[yf_t]

                vol = df["Volume"].dropna().astype(float)
                if len(vol) < 19:
                    continue
                # 取最近 19 個交易日（排除今日，今日尚未收盤）
                vol_19d_sum_shares = float(vol.iloc[-19:].sum())
                vol19_map[ticker] = round(vol_19d_sum_shares / 1000, 4)  # 轉換為張
            except Exception as e:
                logger.debug("盤前 vol19 跳過 %s: %s", yf_t, e)

    if not vol19_map:
        logger.warning("盤前 vol19：無有效資料，跳過寫入")
        return

    # 4. 寫入 DB
    today_str = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d")
    now = datetime.now()

    def _upsert():
        tickers_to_update = list(vol19_map.keys())
        with Session(engine) as session:
            existing = {
                r.ticker: r
                for r in session.exec(
                    select(IntradayMA20Snapshot).where(
                        IntradayMA20Snapshot.ticker.in_(tickers_to_update)
                    )
                ).all()
            }
            for ticker, vol19 in vol19_map.items():
                s = stock_map.get(f"{ticker}.TW") or stock_map.get(f"{ticker}.TWO")
                if not s:
                    continue
                row = existing.get(ticker)
                if row:
                    row.vol_19d_sum_lots = vol19
                    row.snapshot_date = today_str
                    row.updated_at = now
                else:
                    session.add(IntradayMA20Snapshot(
                        ticker=ticker,
                        market=s["market"],
                        name=s["name"],
                        vol_19d_sum_lots=vol19,
                        snapshot_date=today_str,
                        updated_at=now,
                    ))
            session.commit()

    await asyncio.to_thread(_upsert)
    logger.info("盤前 vol19 完成：%d 支股票 (date=%s)", len(vol19_map), today_str)


async def _save_ma20_snapshot(ma20_snapshot: dict[str, dict]) -> None:
    """將 MA20 快照存入 IntradayMA20Snapshot 表（每日收盤掃描後呼叫）。"""
    if not ma20_snapshot:
        return

    from datetime import datetime
    from zoneinfo import ZoneInfo

    from .models.intraday_ma import IntradayMA20Snapshot

    today_str = datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d")
    now = datetime.now()

    def _upsert():
        tickers_to_update = list(ma20_snapshot.keys())
        with Session(engine) as session:
            existing = {
                r.ticker: r
                for r in session.exec(
                    select(IntradayMA20Snapshot).where(
                        IntradayMA20Snapshot.ticker.in_(tickers_to_update)
                    )
                ).all()
            }
            for ticker, snap in ma20_snapshot.items():
                row = existing.get(ticker)
                if row:
                    row.market = snap["market"]
                    row.name = snap["name"]
                    row.ma20_lots = snap["ma20_lots"]
                    row.snapshot_date = today_str
                    row.updated_at = now
                else:
                    session.add(IntradayMA20Snapshot(
                        ticker=ticker,
                        market=snap["market"],
                        name=snap["name"],
                        ma20_lots=snap["ma20_lots"],
                        snapshot_date=today_str,
                        updated_at=now,
                    ))
            session.commit()

    await asyncio.to_thread(_upsert)
    logger.info("MA20 snapshot saved: %d stocks (date=%s)", len(ma20_snapshot), today_str)


async def intraday_spike_scan_job():
    """盤中爆量掃描：從 SQLite 讀取前日 MA20，呼叫 IntradaySpikeScanner，推播新爆量股。"""
    from zoneinfo import ZoneInfo
    now_tw = datetime.now(ZoneInfo("Asia/Taipei"))
    if not ((9, 35) <= (now_tw.hour, now_tw.minute) <= (13, 30)):
        return

    from .config import get_settings
    from .models.intraday_ma import IntradayMA20Snapshot
    from .services.intraday_spike_scanner import IntradaySpikeScanner
    from .services.volume_spike_scanner import SpikeSortBy

    settings = get_settings()
    if not settings.INTRADAY_SPIKE_ENABLED:
        return

    from . import main as _main_mod
    if getattr(_main_mod, "bot_app", None) and _main_mod.bot_app.bot:
        bot = _main_mod.bot_app.bot
    else:
        from telegram import Bot
        bot = Bot(token=settings.TELEGRAM_TOKEN)

    try:
        # 1. 載入前日 MA20 快照
        def _load_snapshot() -> dict[str, dict]:
            with Session(engine) as session:
                rows = session.exec(select(IntradayMA20Snapshot)).all()
                return {r.ticker: {"name": r.name, "market": r.market, "ma20_lots": r.ma20_lots, "vol_19d_sum_lots": r.vol_19d_sum_lots}
                        for r in rows}

        ma20_snapshot = await asyncio.to_thread(_load_snapshot)
        if not ma20_snapshot:
            logger.info("盤中爆量：MA20 快照為空，跳過（請等待 15:30 收盤掃描後才有資料）")
            return

        # 2. 掃描
        try:
            sort_by = SpikeSortBy(settings.SPIKE_DEFAULT_SORT)
        except ValueError:
            sort_by = SpikeSortBy.RATIO

        scanner = IntradaySpikeScanner()
        results = await scanner.scan_intraday(
            ma20_snapshot=ma20_snapshot,
            base_spike_ratio=settings.INTRADAY_SPIKE_BASE_RATIO,
            min_lots=settings.INTRADAY_SPIKE_MIN_LOTS,
            sort_by=sort_by,
        )

        if not results:
            logger.info("盤中爆量：本次無新爆量股")
            return

        # 3. 去重過濾
        notified = _load_intraday_notified()
        new_results = [r for r in results if r.ticker not in notified]
        if not new_results:
            logger.info("盤中爆量：所有爆量股已通知過，跳過")
            return

        # 4. 格式化訊息
        from .services.spike_pager import (
            build_spike_markdown_header,
            build_spike_telegram_html_messages,
        )

        header = "[盤中] " + build_spike_markdown_header(len(new_results), sort_by=sort_by)
        msgs = build_spike_telegram_html_messages(new_results, header)

        # 5. 收集推播對象：訂閱者 + INTRADAY_SPIKE_CHAT_ID / TELEGRAM_CHAT_ID
        from .models.subscriber import Subscriber

        def _load_ispike_subscribers() -> list[int]:
            with Session(engine) as session:
                subs = session.exec(
                    select(Subscriber).where(
                        Subscriber.ispike_enabled == True,
                    )
                ).all()
                return [s.chat_id for s in subs]

        chat_ids_set: set[int] = set(await asyncio.to_thread(_load_ispike_subscribers))
        fallback_id = settings.INTRADAY_SPIKE_CHAT_ID or settings.TELEGRAM_CHAT_ID
        if fallback_id:
            chat_ids_set.add(int(fallback_id))
        chat_ids = list(chat_ids_set)

        if not chat_ids:
            logger.info("盤中爆量：無推播對象（無訂閱者且未設定 INTRADAY_SPIKE_CHAT_ID）")
            return

        # 6. 推播給所有對象
        failed = 0
        for cid in chat_ids:
            try:
                for m in msgs:
                    await bot.send_message(
                        chat_id=cid,
                        text=m,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.error(f"盤中爆量推播失敗 chat_id={cid}: {e}")
                failed += 1

        if failed:
            logger.warning("盤中爆量：%d/%d 推播失敗", failed, len(chat_ids))

        # 更新去重清單（即使部分推播失敗仍記錄，避免重複推播）
        notified.update(r.ticker for r in new_results)
        _save_intraday_notified(notified)
        logger.info("盤中爆量推播完成：%d 支新爆量股", len(new_results))

    except Exception as e:
        logger.error(f"Intraday spike job failed: {e}")


_VIX_COOLDOWN_HOURS = 4  # 同等級 4 小時內不重複推播
_VIX_LAST_ALERT_KEY = "vix_last_alert"  # SystemConfig key


def _load_vix_last_alert() -> dict:
    """從 DB 讀取上次推播狀態。"""
    import json

    from sqlmodel import Session, select

    from .database import engine
    from .models.config import SystemConfig

    try:
        with Session(engine) as session:
            row = session.exec(
                select(SystemConfig).where(SystemConfig.key == _VIX_LAST_ALERT_KEY)
            ).first()
            if row:
                return json.loads(row.value)
    except Exception as e:
        logger.warning(f"VIX alert state load failed: {e}")
    return {"level": None, "time": None}


def _save_vix_last_alert(level: str, time_iso: str) -> None:
    """將推播狀態持久化到 DB。"""
    import json

    from sqlmodel import Session, select

    from .database import engine
    from .models.config import SystemConfig

    try:
        with Session(engine) as session:
            row = session.exec(
                select(SystemConfig).where(SystemConfig.key == _VIX_LAST_ALERT_KEY)
            ).first()
            value = json.dumps({"level": level, "time": time_iso})
            if row:
                row.value = value
                session.add(row)
            else:
                session.add(SystemConfig(key=_VIX_LAST_ALERT_KEY, value=value))
            session.commit()
    except Exception as e:
        logger.warning(f"VIX alert state save failed: {e}")


async def vix_check_job():
    """定時檢查 VIX，有警報才推播。去重：同等級 4 小時內只推一次（重啟後仍有效）。"""
    from datetime import datetime, timedelta

    from . import main as _main_mod
    from .config import get_settings
    from .services.vix_fetcher import fetch_vix_snapshot, format_vix_message

    settings = get_settings()
    # VIX 可設獨立 chat_id，否則 fallback 到預設
    chat_id = settings.TELEGRAM_VIX_CHAT_ID or settings.TELEGRAM_CHAT_ID
    if not chat_id:
        return

    if getattr(_main_mod, "bot_app", None) and _main_mod.bot_app.bot:
        bot = _main_mod.bot_app.bot
    else:
        from telegram import Bot

        bot = Bot(token=settings.TELEGRAM_TOKEN)

    snap = await fetch_vix_snapshot()
    if snap is None:
        logger.warning("VIX check: no data")
        return

    logger.info(f"VIX check: {snap.current:.2f} ({snap.level}), alert={snap.alert}")

    if not snap.alert:
        return

    # 去重：從 DB 讀取上次推播狀態
    state = await asyncio.to_thread(_load_vix_last_alert)
    now = datetime.now()
    last_level = state.get("level")
    last_time_str = state.get("time")
    if last_time_str:
        try:
            last_time = datetime.fromisoformat(last_time_str)
            if last_level == snap.level and now - last_time < timedelta(hours=_VIX_COOLDOWN_HOURS):
                logger.info(f"VIX alert suppressed (same level '{snap.level}', cooldown active)")
                return
        except ValueError:
            pass

    try:
        kwargs = {"chat_id": chat_id, "text": format_vix_message(snap)}
        if settings.TELEGRAM_VIX_TOPIC_ID:
            kwargs["message_thread_id"] = settings.TELEGRAM_VIX_TOPIC_ID
        await bot.send_message(**kwargs)
        await asyncio.to_thread(_save_vix_last_alert, snap.level, now.isoformat())
    except Exception as e:
        logger.error(f"VIX alert send failed: {e}")


def start_scheduler():
    """Start the scheduler."""
    # Run at 14:00 Taipei time (UTC+8) -> 06:00 UTC?
    # APScheduler supports timezones.
    trigger = CronTrigger(hour=14, minute=0, timezone="Asia/Taipei")

    # Add job
    scheduler.add_job(
        daily_analysis_job, trigger=trigger, id="daily_analysis", replace_existing=True
    )

    # Volume Spike Detection — runs at 15:30 Taipei time (yfinance 日線約 15:00 後才更新)
    spike_trigger = CronTrigger(hour=15, minute=30, timezone="Asia/Taipei")
    scheduler.add_job(
        daily_volume_spike_job,
        trigger=spike_trigger,
        id="daily_volume_spike",
        replace_existing=True,
    )

    # NOTE: Podcast job 先暫停（跑太久）。需要再啟用時，把下面區塊取消註解即可。
    #
    # # Run every 60 minutes
    # podcast_interval = IntervalTrigger(minutes=60)
    # scheduler.add_job(
    #     daily_podcast_job,
    #     trigger=podcast_interval,
    #     id="daily_podcast",
    #     replace_existing=True,
    #     # next_run_time=datetime.now()  # 若要啟動後立刻跑，再打開這行
    # )

    # 盤前 vol19 掃描：08:00（抓過去 19 日量，供盤中 MA20 計算）
    scheduler.add_job(
        premarket_vol19_job,
        trigger=CronTrigger(hour=8, minute=0, timezone="Asia/Taipei"),
        id="premarket_vol19",
        replace_existing=True,
    )

    # 盤中爆量偵測：每 5 分鐘觸發，job 內部檢查是否在 09:35~13:30 交易時段
    scheduler.add_job(
        intraday_spike_scan_job,
        trigger=IntervalTrigger(minutes=5),
        id="intraday_spike",
        replace_existing=True,
    )

    # VIX 定時檢查：台股盤前 08:30、台股收盤後 13:35、美股開盤後 22:30
    for vix_hour, vix_minute in [(8, 30), (13, 35), (22, 30)]:
        scheduler.add_job(
            vix_check_job,
            trigger=CronTrigger(hour=vix_hour, minute=vix_minute, timezone="Asia/Taipei"),
            id=f"vix_check_{vix_hour:02d}{vix_minute:02d}",
            replace_existing=True,
        )

    # Add News Check Job (Every 10 mins)
    # 註: check_news_job 已交由 telegram.ext.Application.job_queue 排程 (bot/main.py)
    # 為避免產生 ConflictError (雙 Bot 實例衝突)，這裡不再透過 apscheduler 排程。

    scheduler.start()
    logger.info("Scheduler started.")


def shutdown_scheduler():
    """Shutdown the scheduler."""
    scheduler.shutdown()
    logger.info("Scheduler shut down.")
