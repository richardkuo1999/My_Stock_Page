import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def mock_stock_data():
    dates = [datetime.now() - timedelta(days=i) for i in range(5, 0, -1)]
    return pd.DataFrame(
        {
            "Open": [100.0, 102.0, 105.0, 103.0, 106.0],
            "High": [105.0, 108.0, 110.0, 107.0, 112.0],
            "Low": [98.0, 100.0, 103.0, 101.0, 105.0],
            "Close": [103.0, 106.0, 107.0, 105.0, 110.0],
            "Volume": [1000000, 1200000, 1100000, 1300000, 1400000],
        },
        index=pd.to_datetime(dates),
    )


@pytest.fixture
def mock_stock_info():
    return {
        "longName": "Test Stock Inc.",
        "sector": "Technology",
        "exchange": "NYSE",
        "currentPrice": 110.0,
        "trailingEps": 5.5,
        "forwardEps": 6.0,
        "trailingPE": 20.0,
        "priceToBook": 2.5,
        "pegRatio": 1.5,
        "bookValue": 44.0,
        "targetMeanPrice": 130.0,
        "grossMargins": 0.45,
        "longBusinessSummary": "Test summary",
    }
