from datetime import datetime, timedelta
import json
import logging
from typing import Optional, Dict, Any, Tuple
from sqlmodel import Session, select
from ..database import engine
from ..models.stock import StockData
from ..models.config import SystemConfig
from ..models.content import News
from .stock_analyzer import StockAnalyzer

logger = logging.getLogger(__name__)

class StockService:
    @staticmethod
    def get_recent_news(limit_per_source: int = 15) -> list[News]:
        """Fetch news ensuring diversity of sources."""
        with Session(engine) as session:
            # 1. Get all distinct sources
            sources = session.exec(select(News.source).distinct()).all()
            
            all_news = []
            for src in sources:
                # Get Top N per source
                news = session.exec(
                    select(News)
                    .where(News.source == src)
                    .order_by(News.created_at.desc())
                    .limit(limit_per_source)
                ).all()
                all_news.extend(news)
                
            # Sort final list by date desc
            all_news.sort(key=lambda x: x.created_at, reverse=True)
            return all_news

    @staticmethod
    async def get_or_analyze_stock(ticker: str, force_update: bool = False) -> Tuple[Optional[Dict[str, Any]], bool]:
        """
        Get stock analysis result.
        Returns: (data, from_cache)
        """
        analyzer = StockAnalyzer()
        
        # Check Cache
        if not force_update:
            with Session(engine) as session:
                stock_record = session.exec(select(StockData).where(StockData.ticker == ticker)).first()
                if stock_record and stock_record.data and stock_record.last_analyzed:
                    if datetime.now() - stock_record.last_analyzed < timedelta(hours=6):
                        try:
                            data = json.loads(stock_record.data)
                            data['_last_analyzed'] = stock_record.last_analyzed
                            data['_tag'] = stock_record.tag
                            return data, True
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to decode cached data for {ticker}")

        # Analyze
        data = await analyzer.analyze_stock(ticker)
        if "error" in data:
            return data, False

        # Save to DB (Auto-Subscribe)
        try:
            with Session(engine) as session:
                stock_record = session.exec(select(StockData).where(StockData.ticker == ticker)).first()
                if not stock_record:
                    stock_record = StockData(ticker=ticker)
                    session.add(stock_record)
                
                stock_record.data = json.dumps(data)
                stock_record.name = data.get('name')
                stock_record.sector = data.get('sector')
                stock_record.price = data.get('price')
                stock_record.last_analyzed = datetime.now()
                session.add(stock_record)
                session.commit()
                session.refresh(stock_record)
                data['_last_analyzed'] = stock_record.last_analyzed
                data['_tag'] = stock_record.tag
        except Exception as e:
            logger.error(f"Failed to save StockData for {ticker}: {e}")
            
        return data, False

    @staticmethod
    def get_tracked_stocks() -> list[StockData]:
        """Fetch all tracked stocks."""
        with Session(engine) as session:
            return session.exec(select(StockData).order_by(StockData.last_analyzed.desc())).all()

    @staticmethod
    def get_daily_tags() -> list[str]:
        """Get list of active daily tokens (ETF, etc)."""
        # Read from SystemConfig "active_daily_tags"
        # stored as space-separated string
        val = StockService.get_system_config("active_daily_tags")
        if not val:
            return []
        return [x.strip() for x in val.split(" ") if x.strip()]

    @staticmethod
    def toggle_daily_tag(tag: str, enable: bool):
        """Enable or disable a daily tag configuration."""
        current_tags = set(StockService.get_daily_tags())
        if enable:
            current_tags.add(tag)
        else:
            current_tags.discard(tag)
        
        # Save back
        new_val = " ".join(current_tags)
        StockService.set_system_config("active_daily_tags", new_val)

    @staticmethod
    def get_system_config(key: str) -> str:
        with Session(engine) as session:
            conf = session.exec(select(SystemConfig).where(SystemConfig.key == key)).first()
            return conf.value if conf else ""

    @staticmethod
    def set_system_config(key: str, value: str):
        with Session(engine) as session:
            conf = session.exec(select(SystemConfig).where(SystemConfig.key == key)).first()
            if not conf:
                conf = SystemConfig(key=key, value=value)
            else:
                conf.value = value
                conf.updated_at = datetime.now()
            session.add(conf)
            session.commit()
