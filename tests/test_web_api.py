import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from analysis_bot.main import app

@pytest.fixture
def client():
    return TestClient(app)


class TestHealthCheck:
    def test_health_check(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestStockAPI:
    def test_analyze_stock_with_valid_ticker(self, client):
        with patch('analysis_bot.services.stock_service.StockService.get_or_analyze_stock') as mock_analyze:
            mock_analyze.return_value = ({
                'name': 'Test Stock',
                'price': 100.0,
                'sector': 'Technology',
                '_last_analyzed': None
            }, False)
            
            response = client.post("/analyze/AAPL")
            
            assert response.status_code == 200
            assert response.json()["status"] == "success"
            assert response.json()["ticker"] == "AAPL"
    
    def test_analyze_stock_with_error(self, client):
        with patch('analysis_bot.services.stock_service.StockService.get_or_analyze_stock') as mock_analyze:
            mock_analyze.return_value = ({'error': 'Stock not found'}, False)
            
            response = client.post("/analyze/INVALID")
            
            assert response.status_code == 200
            assert "error" in response.json()
    
    def test_analyze_stock_with_force_update(self, client):
        with patch('analysis_bot.services.stock_service.StockService.get_or_analyze_stock') as mock_analyze:
            mock_analyze.return_value = ({'name': 'Test Stock', 'price': 100.0}, False)
            
            response = client.post("/analyze/AAPL?force=True")
            
            assert response.status_code == 200
            assert response.json()["status"] == "success"


class TestSettingsAPI:
    def test_toggle_tag(self, client):
        with patch('analysis_bot.services.stock_service.StockService.toggle_daily_tag') as mock_toggle:
            response = client.post("/settings/tags/toggle", json={"tag": "favorite", "enable": True})
            
            assert response.status_code == 200
            assert response.json()["status"] == "ok"
            mock_toggle.assert_called_once_with("favorite", True)
    
    def test_update_list(self, client):
        with patch('analysis_bot.services.stock_service.StockService.set_system_config') as mock_update:
            response = client.post("/settings/lists/update", json={"key": "user_choice", "value": "2330 2317"})
            
            assert response.status_code == 200
            assert response.json()["status"] == "ok"
            mock_update.assert_called_once_with("user_choice", "2330 2317")
    
    def test_update_list_invalid_key(self, client):
        with patch('analysis_bot.services.stock_service.StockService.set_system_config') as mock_update:
            response = client.post("/settings/lists/update", json={"key": "invalid", "value": "test"})
            
            assert response.status_code == 200
            assert response.json()["status"] == "ok"
            mock_update.assert_not_called()
