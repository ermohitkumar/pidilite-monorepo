import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from db.models import User
from core.security import verify_password
from services.api.main import app
from db.session import get_db
from core.config import settings


@pytest.fixture
def guest_client(db_session):
    """Client with 'guest' role for RBAC negative tests."""
    def _override_get_db():
        yield db_session

    _orig_env = settings.ENVIRONMENT
    settings.ENVIRONMENT = "production"

    guest_id = "00000000-0000-0000-0000-000000000001"
    guest = User(user_id=guest_id, email="guest@example.com", username="guest",
                 password_hash="x", role="guest", is_active=True, allowed_resources=[])
    db_session.add(guest)
    db_session.commit()

    app.dependency_overrides[get_db] = _override_get_db
    with patch("core.dependencies.jwt.decode", return_value={"role": "guest", "user_id": guest_id}):
        with TestClient(app, raise_server_exceptions=False) as c:
            c.cookies.set("pidilite_session_cookie", "fake-token")
            c.headers.update({
                "X-Requested-With": "XMLHttpRequest",
                "Authorization": "Bearer fake-token"
            })
            yield c
    app.dependency_overrides.clear()
    settings.ENVIRONMENT = _orig_env


@pytest.fixture
def admin_client(db_session):
    """Client with 'admin' role for RBAC tests."""
    def _override_get_db():
        yield db_session

    _orig_env = settings.ENVIRONMENT
    settings.ENVIRONMENT = "production"

    admin_id = "00000000-0000-0000-0000-000000000002"
    admin = User(user_id=admin_id, email="admin@example.com", username="admin",
                 password_hash="x", role="admin", is_active=True, allowed_resources=["view_profile"])
    db_session.add(admin)
    db_session.commit()

    app.dependency_overrides[get_db] = _override_get_db
    with patch("core.dependencies.jwt.decode", return_value={"role": "admin", "user_id": admin_id}):
        with TestClient(app, raise_server_exceptions=False) as c:
            c.cookies.set("pidilite_session_cookie", "fake-token")
            c.headers.update({
                "X-Requested-With": "XMLHttpRequest",
                "Authorization": "Bearer fake-token"
            })
            yield c
    app.dependency_overrides.clear()
    settings.ENVIRONMENT = _orig_env


class TestUserManagement:
    # ── POST /users/ (production mode — no password, SSO only) ──
    def test_create_user_success_production(self, client, db_session):
        """In production, users are created without passwords (SSO only)."""
        payload = {
            "email": "newuser@example.com",
            "username": "newuser",
            "full_name": "New User",
            "role": "admin"
        }
        res = client.post("/api/v1/users/", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["data"]["email"] == "newuser@example.com"

        # Verify in DB — no password hash for SSO-only user
        db_user = db_session.query(User).filter_by(
            email="newuser@example.com").first()
        assert db_user is not None
        assert db_user.password_hash is None

    def test_create_user_rejects_password_in_production(self, client):
        """Production must not accept a password field."""
        payload = {
            "email": "bad@example.com",
            "password": "StrongPassword123",
            "role": "admin"
        }
        res = client.post("/api/v1/users/", json=payload)
        assert res.status_code == 422  # model_validator rejects password in production

    # ── POST /users/ (development mode — password required) ──
    def test_create_user_success_development(self, client, db_session):
        """In development, password is required and hashed."""
        from core.config import settings
        _orig_env = settings.ENVIRONMENT
        settings.ENVIRONMENT = "development"
        try:
            payload = {
                "email": "devuser@example.com",
                "password": "StrongPassword1",
                "username": "devuser",
                "full_name": "Dev User",
                "role": "admin"
            }
            res = client.post("/api/v1/users/", json=payload)
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert data["data"]["email"] == "devuser@example.com"

            # Verify in DB — password hash should exist
            db_user = db_session.query(User).filter_by(
                email="devuser@example.com").first()
            assert db_user is not None
            assert verify_password("StrongPassword1", db_user.password_hash)
        finally:
            settings.ENVIRONMENT = _orig_env

    def test_create_user_missing_password_in_development(self, client):
        """In development, omitting password should fail validation."""
        from core.config import settings
        _orig_env = settings.ENVIRONMENT
        settings.ENVIRONMENT = "development"
        try:
            payload = {"email": "nopass@example.com", "role": "admin"}
            res = client.post("/api/v1/users/", json=payload)
            assert res.status_code == 422
        finally:
            settings.ENVIRONMENT = _orig_env

    def test_create_user_weak_password_development(self, client):
        """In development, weak password should fail validation."""
        from core.config import settings
        _orig_env = settings.ENVIRONMENT
        settings.ENVIRONMENT = "development"
        try:
            payload = {"email": "weak@example.com",
                       "password": "weak", "role": "admin"}
            res = client.post("/api/v1/users/", json=payload)
            assert res.status_code == 422
        finally:
            settings.ENVIRONMENT = _orig_env

    def test_create_user_duplicate_email(self, client, create_test_user):
        create_test_user(email="dup@example.com")
        payload = {"email": "dup@example.com", "role": "admin"}
        res = client.post("/api/v1/users/", json=payload)
        assert res.status_code == 409
        assert res.json()["success"] is False
        assert res.json()["error"] == "Conflict"

    def test_create_user_unauthorized(self, admin_client):
        payload = {"email": "test@example.com", "role": "admin"}
        res = admin_client.post("/api/v1/users/", json=payload)
        assert res.status_code == 403

    # ── GET /users/ ──
    def test_list_users_success(self, client, create_test_user):
        create_test_user(email="u1@example.com", username="u1")
        create_test_user(email="u2@example.com", username="u2")
        res = client.get("/api/v1/users/")
        assert res.status_code == 200
        assert res.json()["data"]["total"] >= 2

    def test_list_users_empty(self, client):
        res = client.get("/api/v1/users/")
        assert res.status_code == 200
        # Since conftest.py seeds a super_admin user, it won't be 0.
        assert res.json()["data"]["total"] >= 1

    def test_list_users_unauthorized(self, admin_client):
        res = admin_client.get("/api/v1/users/")
        assert res.status_code == 403

    # ── GET /users/{user_id} ──
    def test_get_profile_super_admin_views_other(self, client, create_test_user):
        u = create_test_user()
        res = client.get(f"/api/v1/users/{u.user_id}")
        assert res.status_code == 200
        assert res.json()["data"]["email"] == u.email

    def test_get_profile_self_view(self, admin_client, db_session):
        res = admin_client.get(
            "/api/v1/users/00000000-0000-0000-0000-000000000002")
        assert res.status_code == 200
        assert res.json()["data"]["email"] == "admin@example.com"

    def test_get_profile_forbidden(self, admin_client, create_test_user):
        u = create_test_user()
        res = admin_client.get(f"/api/v1/users/{u.user_id}")
        assert res.status_code == 403
        assert res.json()["error"] == "Forbidden"

    def test_get_profile_not_found(self, client):
        res = client.get("/api/v1/users/nonexistent-id")
        assert res.status_code == 404
        assert res.json()["error"] == "NotFound"

    # ── PUT /users/{user_id} ──
    def test_update_user_success(self, client, create_test_user, db_session):
        u = create_test_user(full_name="Old Name")
        payload = {"full_name": "New Name"}
        res = client.put(f"/api/v1/users/{u.user_id}", json=payload)
        assert res.status_code == 200
        assert res.json()["data"]["full_name"] == "New Name"

        db_session.refresh(u)
        assert u.full_name == "New Name"

    def test_update_user_password(self, client, create_test_user, db_session):
        u = create_test_user(password="OldPass123")
        payload = {"password": "NewStrongPassword123"}
        res = client.put(f"/api/v1/users/{u.user_id}", json=payload)
        assert res.status_code == 200

        db_session.refresh(u)
        assert verify_password("NewStrongPassword123", u.password_hash)

    def test_update_user_mass_assignment_protection(self, client, create_test_user, db_session):
        u = create_test_user(email="test@example.com")
        original_hash = u.password_hash
        payload = {"email": "updated@example.com",
                   "password_hash": "hacked_hash"}
        res = client.put(f"/api/v1/users/{u.user_id}", json=payload)
        assert res.status_code == 200

        db_session.refresh(u)
        assert u.email == "updated@example.com"
        assert u.password_hash == original_hash  # Should not be updated!

    def test_update_user_not_found(self, client):
        res = client.put("/api/v1/users/nonexistent-id",
                         json={"full_name": "test"})
        assert res.status_code == 404
        assert res.json()["error"] == "NotFound"

    # ── DELETE /users/{user_id} ──
    def test_delete_user_success(self, client, create_test_user, db_session):
        u = create_test_user(is_active=True)
        res = client.delete(f"/api/v1/users/{u.user_id}")
        assert res.status_code == 200
        assert res.json()["success"] is True

        db_session.refresh(u)
        assert u.is_active is False  # Soft delete

    def test_delete_user_not_found(self, client):
        res = client.delete("/api/v1/users/nonexistent-id")
        assert res.status_code == 404
        assert res.json()["error"] == "NotFound"

    def test_delete_user_unauthorized(self, admin_client, create_test_user):
        u = create_test_user()
        res = admin_client.delete(f"/api/v1/users/{u.user_id}")
        assert res.status_code == 403
