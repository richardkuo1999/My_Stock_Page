import logging
import asyncio
import difflib
import html
import re
import unicodedata
from typing import List, Dict
from datetime import datetime, timedelta
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from sqlmodel import Session, select, col

from ..services.news_parser import NewsParser
from ..models.content import News
from ..database import engine

logger = logging.getLogger(__name__)

# Constants
MAX_ALIAS_LENGTH = 64
TICKER_MATCH_THRESHOLD = 0.85
MAX_SEND_ARTICLES = 5

_WORD_CHARS_RE = re.compile(r"[A-Z0-9]")


def _norm_text(text: str) -> str:
    # NFKC helps normalize full-width characters; upper for ticker matching
    return unicodedata.normalize("NFKC", text or "").upper()


def _normalize_content_for_matching(title: str, url: str) -> tuple[str, str, str, str, str]:
    """
    Normalize title and URL for matching to avoid repeated operations.
    
    Returns:
        tuple: (title_raw, title_norm, url_raw, url_norm, content_norm)
    """
    title_norm = unicodedata.normalize("NFKC", title).strip()
    url_norm = unicodedata.normalize("NFKC", url).strip()
    content_norm = f"{title_norm}\n{url_norm}"
    return title, title_norm, url, url_norm, content_norm


def _contains_ticker(text_upper: str, ticker_upper: str) -> bool:
    """
    Avoid substring false positives by enforcing non-alnum boundaries around ticker.
    Works for both numeric (2330) and alpha (TSLA) tickers.
    """
    if not ticker_upper:
        return False
    if ticker_upper not in text_upper:
        return False

    # Boundary check without heavy regex compilation per call
    start = 0
    while True:
        idx = text_upper.find(ticker_upper, start)
        if idx < 0:
            return False
        left_ok = idx == 0 or not _WORD_CHARS_RE.match(text_upper[idx - 1])
        right_i = idx + len(ticker_upper)
        right_ok = right_i >= len(text_upper) or not _WORD_CHARS_RE.match(text_upper[right_i])
        if left_ok and right_ok:
            return True
        start = idx + 1


async def check_news_job(context: ContextTypes.DEFAULT_TYPE = None, bot=None):
    """
    Background job to fetch news and notify subscribers.
    Can be called by PTB JobQueue (context) or APScheduler (bot).
    """
    # Valid check handled later via DB logic

    # Determine Bot and NewsParser
    if context:
        bot_instance = context.bot
        news_parser = context.bot_data.get("news_parser") or NewsParser()
    elif bot:
        bot_instance = bot
        news_parser = NewsParser()
    else:
        # Fallback for standalone run (create bot from settings)
        from ..config import get_settings
        from telegram import Bot
        settings = get_settings()
        bot_instance = Bot(token=settings.TELEGRAM_TOKEN)
        news_parser = NewsParser()
    
    # Sources configuration
    sources = [
        {"name": "CNYES", "url": "https://api.cnyes.com/media/api/v1/newslist/category/headline"},
        # {"name": "GoogleNews", "url": "https://news.google.com/rss?hl=zh-TW&gl=TW&ceid=TW:zh-Hant"},
        {"name": "MoneyDJ", "url": "https://www.moneydj.com/KMDJ/RssCenter.aspx?svc=NR&fno=1&arg=MB010000"}
        # UAnalyze handled separately below
    ]

    new_articles = []
    
    # 1. Fetch from Standard Sources
    for source in sources:
        try:
            articles = await news_parser.fetch_news_list(source["url"])
            if articles:
                for a in articles:
                    a['source_name'] = source["name"]
                new_articles.extend(articles)
        except Exception as e:
            logger.error(f"Error fetching news from {source['name']}: {e}")

    # 2. Fetch from UAnalyze, Fugle, Vocus
    
    # UAnalyze
    try:
        ua_articles = await news_parser.get_uanalyze_report()
        if ua_articles:
            for a in ua_articles: a['source_name'] = "UAnalyze"
            new_articles.extend(ua_articles)
    except Exception as e:
        logger.error(f"Error fetching UAnalyze: {e}")
        
    # Fugle
    try:
        fugle_articles = await news_parser.get_fugle_report("https://blog.fugle.tw/")
        if fugle_articles:
            for a in fugle_articles: a['source_name'] = "Fugle"
            new_articles.extend(fugle_articles)
    except Exception as e:
         logger.error(f"Error fetching Fugle: {e}")
            
    # Vocus
    try:
        vocus_users = ['@ieobserve', '@miula', '65ab564cfd897800018a88cc']
        for v_user in vocus_users:
            try:
                vocus_articles = await news_parser.get_vocus_articles(v_user)
                if vocus_articles:
                    for a in vocus_articles: a['source_name'] = f"Vocus ({v_user})"
                    new_articles.extend(vocus_articles)
            except Exception as e:
                logger.error(f"Error fetching Vocus user {v_user}: {e}")
    except Exception as e:
        logger.error(f"Error Vocus main block: {e}")

    # 3. Fetch from Additional Ported Sources (UDN, Yahoo, Others)
    
    # UDN
    try:
        udn_res = await news_parser.get_udn_report()
        if udn_res:
            for a in udn_res: a['source_name'] = "UDN"
            new_articles.extend(udn_res)
    except Exception as e:
        logger.error(f"Error fetching UDN: {e}")

    # Yahoo TW
    try:
        yahoo_res = await news_parser.get_yahoo_tw_report()
        if yahoo_res:
            for a in yahoo_res: a['source_name'] = "YahooTW"
            new_articles.extend(yahoo_res)
    except Exception as e:
         logger.error(f"Error fetching YahooTW: {e}")
            
    # News Digest AI
    try:
        ndai_res = await news_parser.get_news_digest_ai_report()
        if ndai_res:
             for a in ndai_res: a['source_name'] = "NewsDigestAI"
             new_articles.extend(ndai_res)
    except Exception as e:
         logger.error(f"Error fetching NewsDigestAI: {e}")

    # Fallbacks (Macromicro, FinGuider, Fintastic, Forecastock)
    # We wrap each in try-except individually for robustness
    
    try:
        mm_res = await news_parser.get_macromicro_report()
        if mm_res:
            for a in mm_res: a['source_name'] = "Macromicro"
            new_articles.extend(mm_res)
    except Exception as e: logger.error(f"Macromicro fetch error: {e}")

    try:
        fg_res = await news_parser.get_finguider_report()
        if fg_res:
            for a in fg_res: a['source_name'] = "FinGuider"
            new_articles.extend(fg_res)
    except Exception as e: logger.error(f"FinGuider fetch error: {e}")

    try:
        ft_res = await news_parser.get_fintastic_report()
        if ft_res:
            for a in ft_res: a['source_name'] = "Fintastic"
            new_articles.extend(ft_res)
    except Exception as e: logger.error(f"Fintastic fetch error: {e}")

    try:
        fc_res = await news_parser.get_forecastock_report()
        if fc_res:
            for a in fc_res: a['source_name'] = "Forecastock"
            new_articles.extend(fc_res)
    except Exception as e: logger.error(f"Forecastock fetch error: {e}")

    if not new_articles:
        return

    # 3. Filter and Save with Deduplication
    final_new_articles = []
    
    with Session(engine) as session:
        # Pre-fetch recent titles for fuzzy matching (last 24 hours)
        yesterday = datetime.utcnow() - timedelta(days=1)
        recent_news = session.exec(select(News).where(News.created_at >= yesterday)).all()
        recent_titles = [n.title for n in recent_news]
        
        for article in new_articles:
            link = article.get("url")
            title = article.get("title")
            source_name = article.get("source_name", "Unknown")
            
            if not link or not title:
                continue
                
            # A. Check exact URL match (Fast)
            existing_link = session.exec(select(News).where(News.link == link)).first()
            if existing_link:
                continue

            # B. Check Fuzzy Title Match (Slower but necessary)
            is_duplicate_title = False
            for recent_title in recent_titles:
                ratio = difflib.SequenceMatcher(None, title, recent_title).ratio()
                if ratio > 0.85: # Threshold
                    is_duplicate_title = True
                    logger.info(f"Skipping duplicate title ({ratio:.2f}): '{title}' vs '{recent_title}'")
                    break
            
            if is_duplicate_title:
                continue
            
            # Additional check: Did we already add it in this current batch?
            # (Though unlikely to have duplicate URL in same batch from same source, 
            # but maybe cross-source in same run?)
            # Let's check against final_new_articles as well
            in_batch_duplicate = False
            for added in final_new_articles:
                if difflib.SequenceMatcher(None, title, added['title']).ratio() > 0.85:
                    in_batch_duplicate = True
                    break
            
            if in_batch_duplicate:
                continue

            # New article found!
            news_item = News(
                title=title,
                link=link,
                source=source_name
            )
            session.add(news_item)
            final_new_articles.append(article)
            # Add to recent_titles so next item in loop checks against this one too
            recent_titles.append(title) 
                
        session.commit()

    # Send notifications using final_new_articles
    new_articles = final_new_articles # Update reference for sending logic below

    # Send notifications
    if new_articles:
        from ..models.subscriber import Subscriber
        from ..models.watchlist import WatchlistEntry
        from ..models.stock import StockData
        # Session, select already imported at top
        
        subscribers = []
        with Session(engine) as session:
             subs = session.exec(select(Subscriber).where(Subscriber.is_active == True)).all()
             subscribers = [s.chat_id for s in subs]

        # Preload watchlist entries for subscriber chats
        watch_by_chat: Dict[int, Dict[int, List[WatchlistEntry]]] = {}
        tickers_by_chat: Dict[int, set[str]] = {}
        if subscribers:
            with Session(engine) as session:
                entries = session.exec(
                    select(WatchlistEntry).where(col(WatchlistEntry.chat_id).in_(subscribers))
                ).all()
                for e in entries:
                    watch_by_chat.setdefault(e.chat_id, {}).setdefault(e.user_id, []).append(e)
                    tickers_by_chat.setdefault(e.chat_id, set()).add(e.ticker)

        # Optional enrichment: pull known company names from StockData for tickers
        names_by_ticker: Dict[str, str] = {}
        all_tickers: set[str] = set()
        for tset in tickers_by_chat.values():
            all_tickers.update(tset)
        if all_tickers:
            with Session(engine) as session:
                rows = session.exec(select(StockData).where(col(StockData.ticker).in_(list(all_tickers)))).all()
                for r in rows:
                    if r.ticker and r.name:
                        names_by_ticker[str(r.ticker).upper()] = str(r.name)
             
        logger.info(f"Found {len(new_articles)} new articles. Sending to {len(subscribers)} subscribers.")
        
        # Group messages to avoid spamming? Or send individually?
        # Let's send individually for now as they appear, or in small batches.
        # Sending top MAX_SEND_ARTICLES latest to avoid flood if DB was empty
        to_send = new_articles[:MAX_SEND_ARTICLES]
        
        # Pre-normalize all news articles to avoid repeated operations
        normalized_news = []
        for news in to_send:
            title_raw = news["title"]
            url_raw = news["url"]
            title, title_norm, url, url_norm, content_norm = _normalize_content_for_matching(title_raw, url_raw)
            
            title_md = title.replace("[", "(").replace("]", ")")  # Simple markdown escape
            msg_md = f"📰 *{title_md}*\n{url}"
            
            normalized_news.append({
                'title_raw': title_raw,
                'title_norm': title_norm,
                'url_raw': url,
                'url_norm': url_norm,
                'content_upper': _norm_text(f"{title_raw}\n{url_raw}"),
                'msg_md': msg_md
            })
        
        for news_data in normalized_news:
            title_raw = news_data['title_raw']
            url_raw = news_data['url_raw']
            content_upper = news_data['content_upper']
            msg_md = news_data['msg_md']
            
            for chat_id in subscribers:
                try:
                    # If we have watchlist entries for this chat, try to mention matching users
                    related = watch_by_chat.get(chat_id, {})
                    if related:
                        user_hits: Dict[int, set[str]] = {}
                        for uid, entries in related.items():
                            hits: set[str] = set()
                            for e in entries:
                                t = (e.ticker or "").upper()
                                if t and _contains_ticker(content_upper, t):
                                    hits.add(t)
                                if e.alias:
                                    alias_norm = unicodedata.normalize("NFKC", e.alias).strip()
                                    if alias_norm and alias_norm in f"{news_data['title_norm']}\n{news_data['url_norm']}":
                                        hits.add(alias_norm)
                                # StockData name enrichment
                                name = names_by_ticker.get(t)
                                if name:
                                    name_norm = unicodedata.normalize("NFKC", name).strip()
                                    if name_norm and name_norm in f"{news_data['title_norm']}\n{news_data['url_norm']}":
                                        hits.add(name_norm)
                            if hits:
                                user_hits[uid] = hits

                        if user_hits:
                            title_html = html.escape(title_raw)
                            url_html = html.escape(url_raw)
                            parts = []
                            for uid in sorted(user_hits.keys()):
                                kw = ", ".join(sorted(user_hits[uid]))
                                parts.append(
                                    f'<a href="tg://user?id={uid}">User {uid}</a>（{html.escape(kw)}）'
                                )
                            related_line = "相關：" + "、".join(parts)
                            msg_html = f"📰 <b>{title_html}</b>\n{url_html}\n{related_line}"

                            await bot_instance.send_message(
                                chat_id=chat_id,
                                text=msg_html,
                                parse_mode=ParseMode.HTML,
                                disable_web_page_preview=True,
                            )
                            continue

                    # Default: keep existing broadcast behavior
                    await bot_instance.send_message(
                        chat_id=chat_id,
                        text=msg_md,
                        parse_mode=ParseMode.MARKDOWN,
                        disable_web_page_preview=True,
                    )
                except Exception as e:
                    logger.error(f"Failed to send news to {chat_id}: {e}")
