import pytest
import pandas as pd
from unittest.mock import MagicMock, AsyncMock, patch
from analysis_bot.services.stock_analyzer import StockAnalyzer


@pytest.mark.asyncio
class TestStockAnalyzer:
    @pytest.fixture
    def analyzer(self):
        return StockAnalyzer()
    
    async def test_analyze_stock_with_valid_ticker(self, analyzer, mock_stock_data, mock_stock_info):
        with patch.object(analyzer.fetcher, 'fetch_yahoo_data') as mock_fetch:
            with patch.object(analyzer.finmind, 'get_per_pbr') as mock_per_pbr:
                with patch.object(analyzer.finmind, 'get_stock_info') as mock_info:
                    with patch.object(analyzer.anue, 'fetch_estimated_data') as mock_anue:
                        mock_fetch.return_value = {
                            'history': mock_stock_data,
                            'info': mock_stock_info
                        }
                        mock_per_pbr.return_value = ([15.0, 18.0, 20.0, 22.0, 25.0], [2.0, 2.2, 2.5, 2.8, 3.0])
                        mock_info.return_value = {'name': 'Test Stock', 'sector': 'Tech'}
                        mock_anue.return_value = {'est_eps': 6.5, 'est_pe': 17.0}
                        
                        result = await analyzer.analyze_stock("2330")
                        
                        assert isinstance(result, dict)
                        assert 'ticker' in result
                        assert 'name' in result
                        assert 'financials' in result
                        assert 'analysis' in result
                        assert 'chart_data' in result
    
    async def test_analyze_stock_with_empty_history(self, analyzer, mock_stock_info):
        with patch.object(analyzer.fetcher, 'fetch_yahoo_data') as mock_fetch:
            empty_df = pd.DataFrame()
            mock_fetch.return_value = {
                'history': empty_df,
                'info': mock_stock_info
            }
            
            result = await analyzer.analyze_stock("99999")
            
            assert isinstance(result, dict)
            assert 'error' in result
    
    async def test_analyze_stock_with_exception(self, analyzer):
        with patch.object(analyzer.fetcher, 'fetch_yahoo_data') as mock_fetch:
            mock_fetch.side_effect = Exception("API Error")
            
            result = await analyzer.analyze_stock("2330")
            
            assert isinstance(result, dict)
            assert 'error' in result
            assert "Failed to fetch data" in result['error']
    
    async def test_analyze_stock_with_tw_fallback(self, analyzer, mock_stock_data, mock_stock_info):
        with patch.object(analyzer.fetcher, 'fetch_yahoo_data') as mock_fetch:
            with patch.object(analyzer.finmind, 'get_per_pbr') as mock_per_pbr:
                with patch.object(analyzer.finmind, 'get_stock_info') as mock_info:
                    with patch.object(analyzer.anue, 'fetch_estimated_data') as mock_anue:
                        mock_fetch.side_effect = [
                            Exception("First attempt failed"),
                            {'history': mock_stock_data, 'info': mock_stock_info}
                        ]
                        mock_per_pbr.return_value = ([15.0, 18.0, 20.0], [2.0, 2.2, 2.5])
                        mock_info.return_value = None
                        mock_anue.return_value = None
                        
                        result = await analyzer.analyze_stock("2330")
                        
                        assert isinstance(result, dict)
                        assert 'ticker' in result
    
    async def test_analyze_stock_with_us_ticker(self, analyzer, mock_stock_data, mock_stock_info):
        with patch.object(analyzer.fetcher, 'fetch_yahoo_data') as mock_fetch:
            mock_fetch.return_value = {
                'history': mock_stock_data,
                'info': mock_stock_info
            }
            
            result = await analyzer.analyze_stock("AAPL")
            
            assert isinstance(result, dict)
            assert 'ticker' in result
