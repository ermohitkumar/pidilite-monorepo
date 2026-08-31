import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from db.models import KeywordDictionary
from services.api.main import app
from db.session import get_db
from core.config import settings

from db.models import User
from core.security import hash_password


@pytest.fixture
def guest_client(db_session):
    """Client with 'guest' role for RBAC negative tests."""
    def _override_get_db():
        yield db_session

    _orig_env = settings.ENVIRONMENT
    settings.ENVIRONMENT = "production"

    guest_id = "00000000-0000-0000-0000-000000000001"
    guest = User(user_id=guest_id, email="guest@example.com", username="guest",
                 password_hash=hash_password("x"), role="guest", is_active=True, allowed_resources=[])
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
    """Client with 'admin' role (can read/write keywords)."""
    def _override_get_db():
        yield db_session

    _orig_env = settings.ENVIRONMENT
    settings.ENVIRONMENT = "production"

    admin_id = "00000000-0000-0000-0000-000000000002"
    admin = User(user_id=admin_id, email="admin@example.com", username="admin", password_hash=hash_password("x"),
                 role="admin", is_active=True, allowed_resources=["view_dashboard", "run_batch_jobs", "manage_registry"])
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


@pytest.fixture
def create_test_keyword(db_session):
    def _create(
        canonical_id: str = "fevicol_sh",
        canonical_term: str = "Fevicol SH",
        category: str = "adhesives",
        aliases: list = ["fevcol", "fevicol sh"],
        priority: int = 100,
        owner: str = "admin",
    ) -> KeywordDictionary:
        kw = KeywordDictionary(
            canonical_id=canonical_id,
            canonical_term=canonical_term,
            category=category,
            aliases=aliases,
            priority=priority,
            owner=owner,
            version=1
        )
        db_session.add(kw)
        db_session.commit()
        db_session.refresh(kw)
        return kw
    return _create


class TestKeywordManagement:
    # ── GET /keywords/ ──
    def test_list_keywords_success(self, client, create_test_keyword):
        create_test_keyword(canonical_id="kw1", canonical_term="Keyword One", priority=200)
        create_test_keyword(canonical_id="kw2", canonical_term="Keyword Two", priority=100)
        res = client.get("/api/v1/keywords/")
        assert res.status_code == 200
        data = res.json()["data"]
        assert len(data) >= 2
        # Priority sort check
        assert data[0]["canonical_id"] == "kw1"

    def test_list_keywords_filters(self, client, create_test_keyword):
        create_test_keyword(canonical_id="active_adh", canonical_term="Active Adhesive",
                            category="adhesives")
        create_test_keyword(canonical_id="active_wp", canonical_term="Active Waterproofing",
                            category="waterproofing")

        # Filter by category
        res = client.get("/api/v1/keywords/?category=adhesives")
        assert all(k["category"] == "adhesives" for k in res.json()["data"])

    def test_list_keywords_guest_role(self, guest_client, create_test_keyword):
        create_test_keyword()
        res = guest_client.get("/api/v1/keywords/")
        assert res.status_code == 403

    # ── POST /keywords/ ──
    def test_create_keyword_success(self, admin_client, db_session):
        payload = {
            "canonical_id": "dr_fixit_101",
            "canonical_term": "Dr. Fixit 101",
            "category": "waterproofing",
            "aliases": ["fixit", "doctor fixit"],
            "priority": 50,
            "owner": "test"
        }
        res = admin_client.post("/api/v1/keywords/", json=payload)
        assert res.status_code == 200
        assert res.json()["success"] is True
        assert res.json()["data"]["canonical_id"] == "dr_fixit_101"

        db_kw = db_session.query(KeywordDictionary).filter_by(
            canonical_id="dr_fixit_101").first()
        assert db_kw is not None

    def test_create_keyword_duplicate(self, admin_client, create_test_keyword):
        create_test_keyword(canonical_id="dup_id")
        payload = {
            "canonical_id": "dup_id",
            "canonical_term": "Dup",
            "category": "test"
        }
        res = admin_client.post("/api/v1/keywords/", json=payload)
        assert res.status_code == 409
        assert res.json()["error"] == "Conflict"

    def test_create_keyword_forbidden_guest(self, guest_client):
        payload = {"canonical_id": "test",
                   "canonical_term": "test", "category": "test"}
        res = guest_client.post("/api/v1/keywords/", json=payload)
        assert res.status_code == 403

    # ── PUT /keywords/{id} ──
    def test_update_keyword_success(self, admin_client, create_test_keyword, db_session):
        kw = create_test_keyword(aliases=["old"])
        payload = {"aliases": ["old", "new"], "priority": 999}
        res = admin_client.put(
            f"/api/v1/keywords/{kw.canonical_id}", json=payload)
        assert res.status_code == 200
        assert res.json()["data"]["version"] == 2  # Version incremented

        db_session.refresh(kw)
        assert "new" in kw.aliases
        assert kw.priority == 999

    def test_update_keyword_not_found(self, admin_client):
        res = admin_client.put(
            "/api/v1/keywords/nonexistent", json={"priority": 1})
        assert res.status_code == 404
        assert res.json()["error"] == "NotFound"

    def test_update_keyword_forbidden(self, guest_client, create_test_keyword):
        kw = create_test_keyword()
        res = guest_client.put(
            f"/api/v1/keywords/{kw.canonical_id}", json={"priority": 1})
        assert res.status_code == 403

    # ── DELETE /keywords/{id} ──
    def test_delete_keyword_success(self, admin_client, create_test_keyword, db_session):
        kw = create_test_keyword()
        res = admin_client.delete(f"/api/v1/keywords/{kw.canonical_id}")
        assert res.status_code == 200

        deleted = db_session.query(KeywordDictionary).filter_by(
            canonical_id=kw.canonical_id).first()
        assert deleted is None  # Hard delete

    def test_delete_keyword_not_found(self, admin_client):
        res = admin_client.delete("/api/v1/keywords/nonexistent")
        assert res.status_code == 404
        assert res.json()["error"] == "NotFound"

    def test_delete_keyword_forbidden(self, guest_client, create_test_keyword):
        kw = create_test_keyword()
        res = guest_client.delete(f"/api/v1/keywords/{kw.canonical_id}")
        assert res.status_code == 403
