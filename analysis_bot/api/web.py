from fastapi import APIRouter, Request, BackgroundTasks, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import logging
from typing import Optional
import json
from datetime import datetime
from fastapi.responses import Response

from ..services.stock_service import StockService
from ..services.report_generator import ReportGenerator
from ..scheduler import daily_analysis_job
from ..database import get_session
from ..models.stock import StockData
from sqlmodel import select

router = APIRouter()
logger = logging.getLogger(__name__)

# Templates
templates = Jinja2Templates(directory="analysis_bot/templates")

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Dashboard: List all validation stocks."""
    stocks = StockService.get_tracked_stocks()
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "stocks": stocks
    })

@router.post("/analyze/{ticker}")
async def analyze_stock_api(ticker: str, background_tasks: BackgroundTasks, force: bool = False):
    """Async analysis endpoint."""
    # We await here to get the result immediately for the UI updates
    # But for very long tasks, we might want BackgroundTasks.
    # User requested "Async UI", so we wait but UI shows spinner.
    # Service handles caching.
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
            "last_updated": data.get("_last_analyzed")
        }
    }

@router.get("/stock/{ticker}", response_class=HTMLResponse)
async def stock_detail(request: Request, ticker: str):
    """Detail view for a specific stock."""
    # We use get_or_analyze to ensure data exists if user navigates directly
    # force_update is False by default
    data, from_cache = await StockService.get_or_analyze_stock(ticker)
    
    if not data or "error" in data:
         # Handle error gracefully
         return templates.TemplateResponse("index.html", {
             "request": request,
             "stocks": StockService.get_tracked_stocks(),
             "error": f"Could not load data for {ticker}"
         })
         
    
    # Generate Markdown Report
    report_text = ReportGenerator.generate_telegram_report(data)
    
    # Format Timestamp
    last_updated = data.get('_last_analyzed')
    if last_updated:
        # If it's a string (from JSON/ISO), parse it? 
        # But StockService assigns it as datetime object if fresh, 
        # but if from JSON cache... SQLModel datetime loaded back might be string or datetime?
        # Let's handle both or rely on template to render string if it's ISO.
        # Actually StockService JSON.loads logic: data['_last_analyzed'] = stock_record.last_analyzed (which is datetime)
        # So it is a datetime object.
        last_updated_str = last_updated.strftime("%Y-%m-%d %H:%M")
    else:
        last_updated_str = "Unknown"

    return templates.TemplateResponse("stock_detail.html", {
        "request": request,
        "ticker": ticker,
        "data": data,
        "report_text": report_text,
        "last_updated": last_updated_str
    })

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

@router.get("/news", response_class=HTMLResponse)
async def news_page(request: Request):
    """News page."""
    news_items = StockService.get_recent_news()
    return templates.TemplateResponse("news.html", {
        "request": request,
        "news_items": news_items
    })

@router.get("/settings/export")
async def export_data(session=Depends(get_session)):
    """Export all StockData as JSON."""
    # Use request-scoped DB session (tests override this dependency).
    stmt = select(StockData).order_by(StockData.last_analyzed.desc())
    if hasattr(session, "exec"):
        stocks = session.exec(stmt).all()
    else:
        stocks = session.execute(stmt).scalars().all()
    # Serialize
    data = [stock.model_dump() for stock in stocks]
    # Handle datetime serialization if needed, model_dump might produce datetimes
    # Pydantic v2 model_dump mode='json' handles it, but SQLModel v0.0.8?
    # Let's simple json dump with default str
    json_str = json.dumps(data, default=str, indent=2)
    
    filename = f"stock_data_export_{datetime.now().strftime('%Y%m%d')}.json"
    return Response(content=json_str, media_type="application/json", headers={"Content-Disposition": f"attachment; filename={filename}"})

@router.get("/settings/config")
async def get_settings_config():
    """Get current configuration (Active Tags + List Content)."""
    active_tags = StockService.get_daily_tags()
    investanchors = StockService.get_system_config("investanchors")
    user_choice = StockService.get_system_config("user_choice")
    target_etfs = StockService.get_system_config("target_etfs")
    
    return {
        "active_tags": active_tags,
        "lists": {
            "investanchors": investanchors,
            "user_choice": user_choice,
            "target_etfs": target_etfs
        }
    }

@router.post("/settings/tags/toggle")
async def toggle_tag(payload: dict):
    """Toggle a daily tag."""
    tag = payload.get("tag")
    enable = payload.get("enable")
    if tag:
        StockService.toggle_daily_tag(tag, enable)
    return {"status": "ok"}

@router.post("/settings/lists/update")
async def update_list(payload: dict):
    """Update content of a custom list."""
    key = payload.get("key")
    value = payload.get("value") # space separated string
    if key in ["investanchors", "user_choice", "target_etfs"]:
        StockService.set_system_config(key, value)
    return {"status": "ok"}
