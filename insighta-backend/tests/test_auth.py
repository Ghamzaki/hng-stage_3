"""
Basic smoke tests for auth and profile endpoints.
These run without a real DB — they validate imports and app structure.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, MagicMock


def test_app_imports():
    """App must import without errors."""
    with patch("database.get_pool", new_callable=AsyncMock):
        from main import app
        assert app is not None


def test_health_endpoint():
    with patch("database.get_pool", new_callable=AsyncMock), \
         patch("database.init_db", new_callable=AsyncMock), \
         patch("database.seed_db", new_callable=AsyncMock):
        from main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


def test_profiles_requires_auth():
    with patch("database.get_pool", new_callable=AsyncMock), \
         patch("database.init_db", new_callable=AsyncMock), \
         patch("database.seed_db", new_callable=AsyncMock):
        from main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/profiles", headers={"X-API-Version": "1"})
        assert resp.status_code == 401


def test_profiles_requires_version_header():
    with patch("database.get_pool", new_callable=AsyncMock), \
         patch("database.init_db", new_callable=AsyncMock), \
         patch("database.seed_db", new_callable=AsyncMock):
        from main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/profiles")
        assert resp.status_code == 400
        assert "version" in resp.json()["message"].lower()


def test_auth_github_redirects():
    with patch("database.get_pool", new_callable=AsyncMock), \
         patch("database.init_db", new_callable=AsyncMock), \
         patch("database.seed_db", new_callable=AsyncMock):
        from main import app
        client = TestClient(app, raise_server_exceptions=False, follow_redirects=False)
        resp = client.get("/auth/github")
        assert resp.status_code in (302, 307)
        assert "github.com/login/oauth/authorize" in resp.headers.get("location", "")


def test_error_response_shape():
    """Error responses must match {status, message} shape."""
    with patch("database.get_pool", new_callable=AsyncMock), \
         patch("database.init_db", new_callable=AsyncMock), \
         patch("database.seed_db", new_callable=AsyncMock):
        from main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/profiles/nonexistent-id", headers={"X-API-Version": "1"})
        # Will be 401 (no auth), shape check
        body = resp.json()
        assert "status" in body
        assert "message" in body
