import asyncio
import json
import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlmodel import select

from ..config import get_settings
from ..database import get_session
from ..models.stock import StockData
from ..scheduler import daily_analysis_job
from ..services.report_generator import ReportGenerator
from ..services.stock_service import StockService

router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()
security = HTTPBearer()


# Pydantic Models for Validation
class TagToggleRequest(BaseModel):
    tag: str = Field(..., min_length=1)
    enable: bool


class ListUpdateRequest(BaseModel):
    key: str = Field(..., pattern="^(investanchors|user_choice|target_etfs)$")
    value: str  # space separated string


# Security Dependency
async def verify_api_key(auth: HTTPAuthorizationCredentials = Depends(security)):
    expected_key = settings.WEB_API_KEY
    if not expected_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WEB_API_KEY is not configured. Set it in .env to enable this endpoint.",
        )
    if auth.credentials != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
        )
    return auth.credentials


# Templates
templates = Jinja2Templates(directory="analysis_bot/templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Dashboard: List all validation stocks."""
    stocks = await asyncio.to_thread(StockService.get_tracked_stocks)
    return templates.TemplateResponse("index.html", {"request": request, "stocks": stocks})


import re as _re


def validate_ticker(ticker: str) -> str:
    ticker = ticker.strip().upper()
    if not ticker or len(ticker) > 20:
        raise HTTPException(status_code=400, detail="Invalid Ticker format")
    if not _re.match(r"^[A-Z0-9.\-]+$", ticker):
        raise HTTPException(status_code=400, detail="Invalid Ticker format")
    return ticker


@router.post("/analyze/{ticker}")
async def analyze_stock_api(
    ticker: str,
    background_tasks: BackgroundTasks,
    force: bool = False,
    _key: str = Depends(verify_api_key),
):
    """Async analysis endpoint."""
    ticker = validate_ticker(ticker)

    data, from_cache = await StockService.get_or_analyze_stock(ticker, force_update=force)

    if not data or "error" in data:
        return {"error": data.get("error", "Unknown error") if data else "Unknown error"}

    return {
        "status": "success",
        "ticker": ticker,
        "from_cache": from_cache,
        "tags": data.get("_tag"),
        "data_preview": {
            "name": data.get("name"),
            "price": data.get("price"),
            "sector": data.get("sector"),
            "last_updated": data.get("_last_analyzed"),
        },
    }


@router.get("/stock/{ticker}", response_class=HTMLResponse)
async def stock_detail(request: Request, ticker: str):
    """Detail view for a specific stock."""
    ticker = validate_ticker(ticker)

    data, from_cache = await StockService.get_or_analyze_stock(ticker)

    if not data or "error" in data:
        # Handle error gracefully
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "stocks": await asyncio.to_thread(StockService.get_tracked_stocks),
                "error": f"Could not load data for {ticker}",
            },
        )

    # Generate Markdown Report
    report_text = ReportGenerator.generate_telegram_report(data)

    # Format Timestamp
    last_updated = data.get("_last_analyzed")
    if last_updated:
        if isinstance(last_updated, datetime):
            last_updated_str = last_updated.strftime("%Y-%m-%d %H:%M")
        else:
            last_updated_str = str(last_updated)
    else:
        last_updated_str = "Unknown"

    return templates.TemplateResponse(
        "stock_detail.html",
        {
            "request": request,
            "ticker": ticker,
            "data": data,
            "report_text": report_text,
            "last_updated": last_updated_str,
        },
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Settings page."""
    return templates.TemplateResponse("settings.html", {"request": request})


@router.post("/settings/run-daily")
async def run_daily_analysis(background_tasks: BackgroundTasks):
    """Trigger daily analysis manually."""
    # Run in background
    background_tasks.add_task(daily_analysis_job, run_tracked=False)
    return {"status": "started", "message": "Daily analysis started in background."}


def _validate_date(date_str: str | None) -> str | None:
    """驗證日期格式 YYYY-MM-DD，無效則回傳 None。"""
    if not date_str:
        return None
    try:
        datetime.strptime(date_str.strip(), "%Y-%m-%d")
        return date_str.strip()
    except ValueError:
        return None


@router.get("/price/{ticker}", response_class=PlainTextResponse)
async def price_api(ticker: str):
    """即時股價查詢。例：/price/2330"""
    from ..services.price_fetcher import fetch_price

    return await fetch_price(ticker)


@router.get("/hold981", response_class=PlainTextResponse)
async def hold981_api(date: str | None = None):
    """00981A 持股變化，可用瀏覽器測試。?date=YYYY-MM-DD"""
    from ..services.blake_chips_scraper import fetch_chips_data

    valid_date = _validate_date(date) if date else None
    return await fetch_chips_data(date_str=valid_date)


@router.get("/hold888", response_class=PlainTextResponse)
async def hold888_api(date: str | None = None):
    """00981A 大額權證買超，可用瀏覽器測試。?date=YYYY-MM-DD"""
    from ..services.blake_chips_scraper import fetch_chips_data_888

    valid_date = _validate_date(date) if date else None
    return await fetch_chips_data_888(date_str=valid_date)


@router.get("/news", response_class=HTMLResponse)
async def news_page(request: Request):
    """News page."""
    news_items = await asyncio.to_thread(StockService.get_recent_news)
    return templates.TemplateResponse("news.html", {"request": request, "news_items": news_items})


@router.get("/settings/export", dependencies=[Depends(verify_api_key)])
async def export_data(session=Depends(get_session)):
    """Export all StockData as JSON."""
    try:
        stmt = select(StockData).order_by(StockData.last_analyzed.desc())
        if hasattr(session, "exec"):
            stocks = session.exec(stmt).all()
        else:
            stocks = session.execute(stmt).scalars().all()

        # Use a more robust serialization for datetime
        def json_serial(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise TypeError(f"Type {type(obj)} not serializable")

        data = [stock.model_dump() for stock in stocks]
        json_str = json.dumps(data, default=json_serial, indent=2)

        filename = f"stock_data_export_{datetime.now().strftime('%Y%m%d')}.json"
        return Response(
            content=json_str,
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.error(f"Export failed: {e}")
        raise HTTPException(status_code=500, detail="Export failed") from e


@router.get("/settings/config")
async def get_settings_config():
    """Get current configuration (Active Tags + List Content)."""
    active_tags = await asyncio.to_thread(StockService.get_daily_tags)
    investanchors = await asyncio.to_thread(StockService.get_system_config, "investanchors")
    user_choice = await asyncio.to_thread(StockService.get_system_config, "user_choice")
    target_etfs = await asyncio.to_thread(StockService.get_system_config, "target_etfs")

    return {
        "active_tags": active_tags,
        "lists": {
            "investanchors": investanchors,
            "user_choice": user_choice,
            "target_etfs": target_etfs,
        },
    }


@router.post("/settings/tags/toggle")
async def toggle_tag(payload: TagToggleRequest):
    """Toggle a daily tag."""
    await asyncio.to_thread(StockService.toggle_daily_tag, payload.tag, payload.enable)
    return {"status": "ok"}


@router.post("/settings/lists/update")
async def update_list(payload: ListUpdateRequest):
    """Update content of a custom list."""
    await asyncio.to_thread(StockService.set_system_config, payload.key, payload.value)
    return {"status": "ok"}
