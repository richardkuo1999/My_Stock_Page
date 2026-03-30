import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from analysis_bot.main import app

TEST_API_KEY = "test-secret-key"

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {TEST_API_KEY}"}

@pytest.fixture(autouse=True)
def patch_api_key(monkeypatch):
    import analysis_bot.api.web as web_module
    monkeypatch.setattr(web_module.settings, "WEB_API_KEY", TEST_API_KEY)


class TestHealthCheck:
    def test_health_check(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestStockAPI:
    def test_analyze_stock_with_valid_ticker(self, client, auth_headers):
        with patch('analysis_bot.services.stock_service.StockService.get_or_analyze_stock') as mock_analyze:
            mock_analyze.return_value = ({
                'name': 'Test Stock',
                'price': 100.0,
                'sector': 'Technology',
                '_last_analyzed': None
            }, False)

            response = client.post("/analyze/AAPL", headers=auth_headers)

            assert response.status_code == 200
            assert response.json()["status"] == "success"
            assert response.json()["ticker"] == "AAPL"

    def test_analyze_stock_with_error(self, client, auth_headers):
        with patch('analysis_bot.services.stock_service.StockService.get_or_analyze_stock') as mock_analyze:
            mock_analyze.return_value = ({'error': 'Stock not found'}, False)

            response = client.post("/analyze/INVALID", headers=auth_headers)

            assert response.status_code == 200
            assert "error" in response.json()

    def test_analyze_stock_with_force_update(self, client, auth_headers):
        with patch('analysis_bot.services.stock_service.StockService.get_or_analyze_stock') as mock_analyze:
            mock_analyze.return_value = ({'name': 'Test Stock', 'price': 100.0}, False)

            response = client.post("/analyze/AAPL?force=True", headers=auth_headers)

            assert response.status_code == 200
            assert response.json()["status"] == "success"


class TestSettingsAPI:
    def test_toggle_tag(self, client, auth_headers):
        with patch('analysis_bot.services.stock_service.StockService.toggle_daily_tag') as mock_toggle:
            response = client.post("/settings/tags/toggle", json={"tag": "favorite", "enable": True}, headers=auth_headers)

            assert response.status_code == 200
            assert response.json()["status"] == "ok"
            mock_toggle.assert_called_once_with("favorite", True)

    def test_toggle_tag_no_auth(self, client):
        response = client.post("/settings/tags/toggle", json={"tag": "favorite", "enable": True})
        assert response.status_code in (401, 403, 503)

    def test_update_list(self, client, auth_headers):
        with patch('analysis_bot.services.stock_service.StockService.set_system_config') as mock_update:
            response = client.post("/settings/lists/update", json={"key": "user_choice", "value": "2330 2317"}, headers=auth_headers)

            assert response.status_code == 200
            assert response.json()["status"] == "ok"
            mock_update.assert_called_once_with("user_choice", "2330 2317")

    def test_update_list_invalid_key(self, client, auth_headers):
        with patch('analysis_bot.services.stock_service.StockService.set_system_config') as mock_update:
            response = client.post("/settings/lists/update", json={"key": "invalid", "value": "test"}, headers=auth_headers)

            # Pydantic rejects invalid key with 422
            assert response.status_code == 422
            mock_update.assert_not_called()
