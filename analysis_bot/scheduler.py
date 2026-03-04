from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import select, Session
from .database import engine
from .models.stock import StockData
from .services.stock_analyzer import StockAnalyzer
from datetime import datetime
import asyncio
import json

from .services.podcast_service import PodcastService

import logging
scheduler = AsyncIOScheduler()
logger = logging.getLogger(__name__)

async def daily_analysis_job(run_daily=True, run_anchors=True, run_tracked=True):

    logger.info("Starting daily analysis job...")
    analyzer = StockAnalyzer()
    
    # Reuse existing bot instance from the running application if available
    from .config import get_settings
    from .services.report_generator import ReportGenerator
    import tempfile
    import shutil
    import os
    import zipfile
    from pathlib import Path

    settings = get_settings()
    
    # Try to get the bot from the running application to avoid creating duplicate instances
    from . import main as _main_mod
    if getattr(_main_mod, 'bot_app', None) and _main_mod.bot_app.bot:
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
        active_tags = StockService.get_daily_tags()
        logger.info(f"Active Tags: {active_tags}")
        
        # 1. Initialize StockSelector
        from .services.stock_selector import StockSelector
        selector = StockSelector()
        
        final_tickers_map = {} # Ticker -> Set of Tags

        import aiohttp
        async with aiohttp.ClientSession() as http_session:
            
            # --- Tag: ETF ---
            if "ETF" in active_tags:
                try:
                    targets = await selector.get_target_etfs() # List of '0050', '0056'
                    logger.info(f"Processing Target ETFs: {targets}")
                    for etf_code in targets:
                        constituents = await selector.fetch_etf_constituents(http_session, etf_code)
                        for c in constituents:
                            if c not in final_tickers_map: final_tickers_map[c] = set()
                            final_tickers_map[c].add(f"ETF_{etf_code}")
                except Exception as e:
                    logger.error(f"Error processing ETF tag: {e}")

            # --- Tag: ETF_Rank ---
            if "ETF_Rank" in active_tags:
                try:
                    stocks = await selector.fetch_etf_rank_stocks(http_session)
                    for s in stocks:
                        if s not in final_tickers_map: final_tickers_map[s] = set()
                        final_tickers_map[s].add("ETF_Rank")
                except Exception as e:
                    logger.error(f"Error processing ETF_Rank: {e}")

            # --- Tag: Institutional_TOP50 ---
            if "Institutional_TOP50" in active_tags:
                 try:
                    stocks = await selector.fetch_institutional_top50(http_session)
                    for s in stocks:
                        if s not in final_tickers_map: final_tickers_map[s] = set()
                        final_tickers_map[s].add("Institutional")
                 except Exception as e:
                    logger.error(f"Error processing Institutional: {e}")

            # --- Tag: Invest Anchors ---
            if "investanchors" in active_tags:
                 try:
                    stocks = await selector.get_invest_anchors()
                    for s in stocks:
                        if s not in final_tickers_map: final_tickers_map[s] = set()
                        final_tickers_map[s].add("InvestAnchor")
                 except Exception as e:
                    logger.error(f"Error processing Anchors: {e}")

            # --- Tag: User Choice ---
            if "User_Choice" in active_tags:
                 try:
                    stocks = await selector.get_user_choice()
                    for s in stocks:
                        if s not in final_tickers_map: final_tickers_map[s] = set()
                        final_tickers_map[s].add("User_Choice")
                 except Exception as e:
                    logger.error(f"Error processing User Choice: {e}")
                    
        # 2. Update DB Tags (Merge with existing or Create new)
        with Session(engine) as session:
            # Fetch all existing stocks to clean up old tags
            all_stocks = session.exec(select(StockData)).all()
            existing_tickers = {s.ticker for s in all_stocks}
            
            # Managed Tags that should be reset every run
            MANAGED_TAG_SET = {"ETF", "ETF_Rank", "Institutional", "InvestAnchor", "User_Choice"}
            
            # 1. Update Existing Stocks (Clean old managed tags + Add new ones)
            for stock in all_stocks:
                current_tags = set(stock.tag.split(",")) if stock.tag else set()
                
                # Remove Managed Tags (Exact match or Prefix for ETF_ codes)
                tags_to_keep = set()
                for t in current_tags:
                    if t in MANAGED_TAG_SET or t.startswith("ETF_"):
                        continue
                    tags_to_keep.add(t)
                
                # Add back new tags if this stock is in the current map
                if stock.ticker in final_tickers_map:
                    tags_to_keep.update(final_tickers_map[stock.ticker])
                
                # Update DB if changed
                new_tag_str = ",".join(sorted(list(tags_to_keep)))
                if stock.tag != new_tag_str:
                    stock.tag = new_tag_str
                    session.add(stock)

            # 2. Create New Stocks (That didn't exist in DB)
            for ticker, new_tags in final_tickers_map.items():
                if ticker not in existing_tickers:
                    stock = StockData(ticker=ticker, tag=",".join(sorted(list(new_tags))))
                    session.add(stock)
            
            session.commit()
            
            # 3. Final List to Analyze (Active tags + Tracked if enabled)
            if run_tracked:
                 # Re-fetch or just add all existing tickers?
                 # If run_tracked is True, we want to analyze EVERYTHING in StockData
                 # (which now includes all previous stocks + newly added ones)
                 ticker_set = set(final_tickers_map.keys())
                 ticker_set.update(existing_tickers)
                 final_tickers = list(ticker_set)
            else:
                 final_tickers = list(final_tickers_map.keys())
             
        logger.info(f"Analyzing {len(final_tickers)} stocks (Daily={run_daily}, Anchors={run_anchors}, Tracked={run_tracked})")
        tickers = list(final_tickers)

        # If no tickers were selected, we should notify and exit early (otherwise users see only the start message).
        if not tickers:
            logger.warning("No tickers selected for daily analysis. Check active_daily_tags or enable run_tracked.")
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
                            text=f"📊 分析進度：{current}/{total} ({current/total*100:.0f}%)"
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send progress update: {e}")

                return result

            logger.info(f"Starting parallel analysis with MAX_CONCURRENT={MAX_CONCURRENT}")
            await bot.send_message(
                chat_id=chat_id,
                text=f"🔍 開始分析 {len(tickers)} 檔股票（並發數：{MAX_CONCURRENT}）..."
            )

            # Run all analyses in parallel
            results = await asyncio.gather(
                *[analyze_with_progress(ticker) for ticker in tickers],
                return_exceptions=True
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

            logger.info(f"Analysis complete: {len(successful_results)} succeeded, {len(failed_tickers)} failed")

            # Send failure summary if any
            if failed_tickers and chat_id:
                fail_msg = f"⚠️ 失敗 {len(failed_tickers)} 檔：\n"
                fail_msg += "\n".join([f"- {t}: {e[:30]}..." if len(e) > 30 else f"- {t}: {e}" for t, e in failed_tickers[:10]])
                if len(failed_tickers) > 10:
                    fail_msg += f"\n... 及其他 {len(failed_tickers) - 10} 檔"
                try:
                    await bot.send_message(chat_id=chat_id, text=fail_msg)
                except Exception as e:
                    logger.warning(f"Failed to send failure summary: {e}")

            underestimated_stocks = []

            # Batch database writes
            with Session(engine) as session:
                for i, (ticker, result) in enumerate(successful_results):
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
                        stock_record.name = result.get('name')
                        stock_record.sector = result.get('sector')
                        stock_record.price = result.get('price')
                        stock_record.last_analyzed = datetime.now()
                        session.add(stock_record)

                        # Generate Report
                        report_text = ReportGenerator.generate_full_report(result)
                        filename = f"{ticker}_{result.get('name', 'Stock').replace('/', '_')}.txt"

                        with open(report_path / filename, "w", encoding="utf-8") as f:
                            f.write(report_text)

                        # Check Underestimated
                        mr = result.get("analysis", {}).get("mean_reversion", {})
                        targets = mr.get("targetprice", [])
                        price = result.get("price", 0)

                        if len(targets) > 4 and price > 0:
                            target_sad = targets[4]  # TL-1SD (TL-SD)
                            if price < target_sad:
                                potential = (target_sad - price) / price * 100
                                underestimated_stocks.append({
                                    "ticker": ticker,
                                    "name": result.get("name"),
                                    "price": price,
                                    "target": target_sad,
                                    "potential": potential,
                                    "sector": result.get("sector", "N/A")
                                })

                        # Batch commit every BATCH_SIZE records
                        if (i + 1) % BATCH_SIZE == 0:
                            session.commit()
                            logger.debug(f"Committed batch at {i + 1} records")

                    except Exception as e:
                        logger.error(f"Error processing result for {ticker}: {e}")

                # Final commit for remaining records
                session.commit()
            
            # 4. Create ZIP
            # Ensure reports directory exists
            reports_dir = Path("reports")
            reports_dir.mkdir(exist_ok=True)
            
            zip_filename = f"Daily_Report_{datetime.now().strftime('%Y%m%d')}.zip"
            zip_filepath = reports_dir / zip_filename # Save to persistent reports/ dir
            
            # Write to persistent location
            with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
                 for root, dirs, files in os.walk(report_path):
                    for file in files:
                        zipf.write(os.path.join(root, file), arcname=file)
            
            # Clean up temp files (handled by TemporaryDirectory, but ZIP is now outside)
            
            # 5. Send Notifications (ZIP + Underestimated)
            
            # Format Underestimated Message
            under_msg = "📉 **Underestimated Stocks (Price < TL-SD)**\n\n"
            if underestimated_stocks:
                # Sort by potential desc
                underestimated_stocks.sort(key=lambda x: x['potential'], reverse=True)
                
                header = f"{'Code':<6} {'Name':<6} {'Sector':<6} {'Pot%':>5}\n"
                under_msg += f"```\n{header}"
                for s in underestimated_stocks:
                    under_msg += f"{s['ticker']:<6} {s['name'][:6]:<6} {s['sector'][:6]:<6} {s['potential']:>5.1f}%\n"
                under_msg += "```"
            else:
                under_msg += "No stocks found below TL-SD."

            # Function to send to list of users
            async def send_daily_bundle(target_chat_id):
                 try:
                     # Send ZIP
                     with open(zip_filepath, 'rb') as f:
                         await bot.send_document(
                            chat_id=target_chat_id,
                            document=f,
                            filename=zip_filename,
                            caption="📊 Daily Analysis Reports",
                            read_timeout=60, 
                            write_timeout=60, 
                            connect_timeout=60
                         )
                     # Send Underestimated List
                     await bot.send_message(chat_id=target_chat_id, text=under_msg, parse_mode='Markdown')
                 except Exception as e:
                     logger.error(
                        f"Failed to send bundle to {redact_telegram_id(target_chat_id, salt=pii_salt)}: {e}"
                     )

            # Send to Admin
            if chat_id:
                try:
                    await bot.send_message(chat_id=chat_id, text="✅ Run Finished. Sending results...")
                except: pass
                await send_daily_bundle(chat_id)
            
            # Send to Subscribers
            from .models.subscriber import Subscriber
            
            subscribers = []
            with Session(engine) as session:
                 subs = session.exec(select(Subscriber).where(Subscriber.is_active == True)).all()
                 subscribers = [s.chat_id for s in subs]
            
            for sub_id in subscribers:
                await send_daily_bundle(sub_id)

    logger.info("Daily analysis job completed.")

async def daily_podcast_job():
    """Daily podcast fetch and summary job."""
    logger.info("Starting daily podcast job...")
    service = PodcastService()
    
    # Reuse existing bot instance from the running application if available
    from .config import get_settings
    from .models.subscriber import Subscriber
    from sqlmodel import Session, select
    from .database import engine

    settings = get_settings()
    
    from . import main as _main_mod
    if getattr(_main_mod, 'bot_app', None) and _main_mod.bot_app.bot:
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
        
        for file_path, host, title, url in new_episodes:
            if not file_path.exists():
                continue
                
            caption = f"🎙️ **{host}** - {title}\nSummary Generated."
            
            # Send to Admin/Group
            if chat_id:
                try:
                    with open(file_path, 'rb') as f:
                        await bot.send_document(
                            chat_id=chat_id, 
                            document=f,
                            filename=file_path.name,
                            caption=caption,
                            parse_mode='Markdown'
                        )
                    logger.info(
                        f"Sent {title} to Main Chat {redact_telegram_id(chat_id, salt=pii_salt)}"
                    )
                except Exception as e:
                    logger.error(f"Failed to send to Main Chat: {e}")

            # Send to Subscribers
            subscribers = []
            with Session(engine) as session:
                 subs = session.exec(select(Subscriber).where(Subscriber.is_active == True)).all()
                 subscribers = [s.chat_id for s in subs]
                 
            for sub_id in subscribers:
                try:
                    with open(file_path, 'rb') as f:
                        await bot.send_document(
                            chat_id=sub_id,
                            document=f,
                            filename=file_path.name,
                            caption=caption,
                            parse_mode='Markdown'
                        )
                except Exception as e:
                    logger.error(
                        f"Failed to send to subscriber {redact_telegram_id(sub_id, salt=pii_salt)}: {e}"
                    )

            # Mark as processed in DB (so we don't process again)
            service.mark_as_processed(host, title, url)
            
            # Remove file after sending? Or keep for record?
            # Implementation plan said "Clean up file after sending"
            try:
                import os
                os.remove(file_path)
            except Exception as e:
                logger.warning(f"Error removing file {file_path}: {e}")
             
    except Exception as e:
        logger.error(f"Podcast job failed: {e}")

def start_scheduler():
    """Start the scheduler."""
    # Run at 14:00 Taipei time (UTC+8) -> 06:00 UTC? 
    # APScheduler supports timezones.
    trigger = CronTrigger(hour=14, minute=0, timezone='Asia/Taipei')
    
    # Add job
    scheduler.add_job(
        daily_analysis_job, 
        trigger=trigger, 
        id="daily_analysis", 
        replace_existing=True
    )
    
    from apscheduler.triggers.interval import IntervalTrigger
 
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
    
    # Add News Check Job (Every 10 mins)
    # 註: check_news_job 已交由 telegram.ext.Application.job_queue 排程 (bot/main.py)
    # 為避免產生 ConflictError (雙 Bot 實例衝突)，這裡不再透過 apscheduler 排程。

    scheduler.start()
    logger.info("Scheduler started.")

def shutdown_scheduler():
    """Shutdown the scheduler."""
    scheduler.shutdown()
    logger.info("Scheduler shut down.")

