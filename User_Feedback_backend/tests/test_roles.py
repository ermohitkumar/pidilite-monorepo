"""Roles created in the admin panel, and the accounts that sign in with them."""
from unittest.mock import patch

from fastapi.testclient import TestClient

from core.config import settings
from db.models import User
from db.session import get_db
from services.api.main import app


def test_list_roles_seeds_builtins(client):
    res = client.get("/api/v1/roles/")
    assert res.status_code == 200
    slugs = {item["slug"] for item in res.json()["data"]["items"]}
    assert {"super_admin", "admin", "user"} <= slugs


def test_create_assign_and_block_unknown_role(client, db_session):
    created = client.post("/api/v1/roles/", json={
        "label": "Field Reviewer",
        "slug": "field_reviewer",
        "description": "Reads summaries only",
        "permissions": ["reports"],
    })
    assert created.status_code == 200
    role_id = created.json()["data"]["role_id"]
    assert created.json()["data"]["permissions"] == ["reports"]
    assert created.json()["data"]["is_system"] is False

    duplicate = client.post("/api/v1/roles/", json={
        "label": "Field Reviewer",
        "slug": "field_reviewer",
        "permissions": ["reports"],
    })
    assert duplicate.status_code == 409

    unknown = client.post("/api/v1/users/", json={
        "email": "nobody@example.com",
        "role": "does_not_exist",
    })
    assert unknown.status_code == 400
    assert unknown.json()["error"] == "InvalidRole"

    user = client.post("/api/v1/users/", json={
        "email": "reviewer@example.com",
        "password": "StrongPassword123",
        "username": "reviewer",
        "full_name": "Reviewer",
        "role": "field_reviewer",
    })
    assert user.status_code == 200
    assert user.json()["data"]["role"] == "field_reviewer"
    assert user.json()["data"]["allowed_resources"] == ["reports"]

    login = client.post("/api/v1/auth/login", json={
        "email": "reviewer@example.com",
        "password": "StrongPassword123",
    })
    assert login.status_code == 200
    assert login.json()["data"]["user"]["role"] == "field_reviewer"

    updated = client.put(f"/api/v1/roles/{role_id}", json={
        "permissions": ["reports", "monitor"],
    })
    assert updated.status_code == 200
    db_user = db_session.query(User).filter_by(email="reviewer@example.com").first()
    db_session.refresh(db_user)
    assert db_user.allowed_resources == ["reports", "monitor"]

    blocked = client.delete(f"/api/v1/roles/{role_id}")
    assert blocked.status_code == 409

    system = next(
        item for item in client.get("/api/v1/roles/").json()["data"]["items"]
        if item["slug"] == "user"
    )
    assert client.delete(f"/api/v1/roles/{system['role_id']}").status_code == 403


def test_reports_role_can_open_own_profile(db_session):
    """Page access from a role must not block loading the signed-in profile."""
    reviewer_id = "00000000-0000-0000-0000-000000000099"
    reviewer = User(
        user_id=reviewer_id,
        email="reviewer@example.com",
        username="reviewer",
        password_hash="x",
        role="field_reviewer",
        is_active=True,
        allowed_resources=["reports"],
    )
    db_session.add(reviewer)
    db_session.commit()

    def _override_get_db():
        yield db_session

    original = settings.ENVIRONMENT
    settings.ENVIRONMENT = "production"
    app.dependency_overrides[get_db] = _override_get_db
    try:
        with patch(
            "core.dependencies.jwt.decode",
            return_value={"role": "field_reviewer", "user_id": reviewer_id},
        ):
            with TestClient(app, raise_server_exceptions=False) as http:
                http.headers.update({"Authorization": "Bearer fake-token"})
                profile = http.get(f"/api/v1/users/{reviewer_id}")
                assert profile.status_code == 200
                assert profile.json()["data"]["email"] == "reviewer@example.com"
                listing = http.get("/api/v1/users/")
                assert listing.status_code == 403
    finally:
        app.dependency_overrides.clear()
        settings.ENVIRONMENT = original
