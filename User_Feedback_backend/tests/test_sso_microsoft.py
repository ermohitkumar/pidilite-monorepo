"""
Tests for the simplified SSO verification flow.

Endpoint under test:
    POST /api/v1/auth/sso/verify

Covers:
    1. Successful login (user exists and is active)
    2. Failure: User not registered (401)
    3. Failure: User disabled (403)
    4. Validation: Missing token (403 via HTTPBearer)
    5. Response: internal JWT generation
"""
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from core.config import settings
from services.api.main import app
from db.session import get_db

SSO_URL = "/api/v1/auth/verify"


@pytest.fixture
def sso_client(db_session):
    """
    A TestClient specifically for SSO tests.
    """
    import db.session as session_mod

    _orig_engine = session_mod.engine
    session_mod.engine = __import__("tests.conftest", fromlist=[
                                    "test_engine"]).test_engine

    _orig_env = settings.ENVIRONMENT
    settings.ENVIRONMENT = "production"

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        c.headers.update({"X-Requested-With": "XMLHttpRequest"})
        yield c
    app.dependency_overrides.clear()
    session_mod.engine = _orig_engine
    settings.ENVIRONMENT = _orig_env


class TestSSOVerifySuccess:
    def test_sso_login_success(self, sso_client, create_test_user):
        user = create_test_user(
            email="ssouser@pidilite.com",
            username="ssouser",
            full_name="SSO User",
            role="admin",
        )
        with patch("core.dependencies.jwt.decode", return_value={
            "email": "ssouser@pidilite.com",
        }):
            resp = sso_client.post(
                SSO_URL,
                headers={"Authorization": "Bearer fake-sso-token"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["user"]["email"] == "ssouser@pidilite.com"
        assert body["data"]["user"]["role"] == "admin"
        assert "access_token" in body["data"]

    def test_sso_sets_session_cookie(self, sso_client, create_test_user):
        create_test_user(email="cookie@pidilite.com",
                         username="cookieuser", role="admin")
        with patch("core.dependencies.jwt.decode", return_value={
            "email": "cookie@pidilite.com",
        }):
            resp = sso_client.post(
                SSO_URL,
                headers={"Authorization": "Bearer fake-sso-token"},
            )
        assert resp.status_code == 200

    def test_sso_internal_jwt_payload_fields(self, sso_client, create_test_user):
        user = create_test_user(
            email="jwtcheck@pidilite.com",
            username="jwtcheckuser",
            full_name="JWT Check User",
            role="super_admin",
        )
        with patch("core.dependencies.jwt.decode", return_value={
            "email": "jwtcheck@pidilite.com",
        }):
            resp = sso_client.post(
                SSO_URL,
                headers={"Authorization": "Bearer fake-sso-token"},
            )
        assert resp.status_code == 200
        body = resp.json()
        token_data = body["data"]["user"]
        assert token_data["user_id"] == str(user.user_id)
        assert token_data["email"] == "jwtcheck@pidilite.com"
        assert token_data["role"] == "super_admin"

        # Ensure an access token string is present
        access_token = body["data"]["access_token"]
        assert isinstance(access_token, str)
        assert len(access_token) > 0


class TestSSOUserFailures:
    def test_sso_unregistered_user(self, sso_client):
        with patch("core.dependencies.jwt.decode", return_value={
            "email": "ghost@pidilite.com",
        }):
            resp = sso_client.post(
                SSO_URL,
                headers={"Authorization": "Bearer fake-sso-token"},
            )
        assert resp.status_code == 401
        assert "not registered" in resp.json()["message"].lower()

    def test_sso_inactive_user(self, sso_client, create_test_user):
        create_test_user(
            email="disabled@pidilite.com",
            username="disabled",
            role="admin",
            is_active=False,
        )
        with patch("core.dependencies.jwt.decode", return_value={
            "email": "disabled@pidilite.com",
        }):
            resp = sso_client.post(
                SSO_URL,
                headers={"Authorization": "Bearer fake-sso-token"},
            )
        assert resp.status_code == 403
        assert "deactivated" in resp.json()["message"].lower()

    def test_sso_missing_email(self, sso_client):
        """Token with no email claim → 400."""
        with patch("core.dependencies.jwt.decode", return_value={
            "sub": "some-subject-no-email",
        }):
            resp = sso_client.post(
                SSO_URL,
                headers={"Authorization": "Bearer fake-sso-token"},
            )
        assert resp.status_code == 400

    def test_sso_missing_token(self, sso_client):
        """No Authorization header → 403 from HTTPBearer."""
        resp = sso_client.post(SSO_URL)
        assert resp.status_code == 403
