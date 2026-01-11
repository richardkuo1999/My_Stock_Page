import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

class DataFetcher:
    """Service to fetch stock data from external sources."""
    
    @staticmethod
    def fetch_yahoo_data(ticker: str, period_years: float = 5):
        """Fetch historical data and basic info from Yahoo Finance."""
        # Clean ticker for TW market if needed (e.g., append .TW)
        # But usually user provides full ticker in this legacy system? 
        # Legacy checks logic: "market = "TW" if stock_info["type"] == "twse" else "TWO""
        # It adds .TW or .TWO to ticker.
        # For now, let's assume ticker is passed correctly or we need detection logic.
        # We'll just try strict ticker first.
        
        # Improve ticker handling: if numeric only, it might need suffix
        # But for simplification, we assume the caller handles logic or we add it here.
        # Let's add simple logic: if all digits, default to .TW? Or try both?
        # Legacy had FinMind to determine market.
        
        stock = yf.Ticker(ticker)
        
        # Get history
        # period = f"{int(period_years)}y" # yfinance supports "1y", "2y", "5y", "10y", "ytd", "max"
        # If period is float like 4.5, we might need start date
        start_date = (datetime.now() - timedelta(days=int(period_years * 365)))
        hist = stock.history(start=start_date)
        
        info = stock.info
        
        return {
            "history": hist,
            "info": info
        }

    @staticmethod
    def fill_nan(series: pd.Series) -> pd.Series:
        """Fill NaN values with interpolation or forward/backward fill."""
        return series.interpolate(method='linear').fillna(method='ffill').fillna(method='bfill')
