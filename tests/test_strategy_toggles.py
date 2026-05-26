import pytest
import sqlite3
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from admin_server import app, get_current_user

@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: {"username": "admin"}
    yield TestClient(app)
    app.dependency_overrides.clear()

@patch("admin_server.get_db_connection")
def test_toggle_strategy_endpoint_success(mock_get_db, client):
    # Mock DB
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_get_db.return_value = mock_conn
    mock_cursor.fetchone.return_value = {"value": "0"}  # Currently disabled
    
    response = client.post("/api/strategies/smc_sweep/toggle")
    assert response.status_code == 200
    assert response.json()["enabled"] == True

def test_toggle_strategy_rejects_crt(client):
    response = client.post("/api/strategies/crt/toggle")
    assert response.status_code == 403
    assert "cannot be disabled" in response.json()["detail"]

    response2 = client.post("/api/strategies/advanced_pattern/toggle")
    assert response2.status_code == 403
    assert "cannot be disabled" in response2.json()["detail"]
