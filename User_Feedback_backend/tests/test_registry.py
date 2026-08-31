"""
Comprehensive tests for Registry configuration endpoints (decoupled).
Covers:
  Categories:
    - GET    /api/v1/registry/categories/                (read list)
    - POST   /api/v1/registry/categories/                (add one item)
    - PUT    /api/v1/registry/categories/{old_value}      (rename one item)
    - DELETE /api/v1/registry/categories/{value_to_delete} (remove one item)
  Languages:
    - GET    /api/v1/registry/languages/                 (read list)
    - POST   /api/v1/registry/languages/                 (add one item)
    - PUT    /api/v1/registry/languages/{old_value}       (rename one item)
    - DELETE /api/v1/registry/languages/{value_to_delete}  (remove one item)
"""
import pytest
from unittest.mock import patch
from db.models import AppConfig
from sqlalchemy.orm import Session


@pytest.fixture
def create_app_config(db_session: Session):
    def _create(key: str, value: list, description: str = ""):
        config = AppConfig(key=key, value=value, description=description)
        db_session.add(config)
        db_session.commit()
        db_session.refresh(config)
        return config
    return _create


# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORIES — GET /api/v1/registry/categories/
# ═══════════════════════════════════════════════════════════════════════════════

class TestCategoriesGet:
    def test_get_categories_success(self, client, create_app_config):
        """Happy path: existing config is returned."""
        create_app_config("keyword_categories", ["A", "B"], "test desc")
        resp = client.get("/api/v1/registry/categories/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["key"] == "keyword_categories"
        assert data["data"]["values"] == ["A", "B"]
        assert data["data"]["description"] == "test desc"
        assert "updated_at" in data["data"]

    def test_get_categories_auto_init_defaults(self, client):
        """Neutral path: DB empty → auto-creates with defaults."""
        resp = client.get("/api/v1/registry/categories/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["key"] == "keyword_categories"
        assert "Product" in data["data"]["values"]
        assert data["data"]["description"] == "System defaults"

    @patch("core.dependencies.jwt.decode")
    def test_get_categories_unauthorized(self, mock_decode, client):
        """Sad path: unauthorized role → 403."""
        mock_decode.return_value = {"role": "viewer"}
        resp = client.get("/api/v1/registry/categories/")
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORIES — POST /api/v1/registry/categories/  (add one item)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCategoriesPost:
    def test_add_category_success(self, client, create_app_config):
        """Happy path: append a new value to an existing registry."""
        create_app_config("keyword_categories", ["A", "B"], "desc")
        resp = client.post(
            "/api/v1/registry/categories/",
            json={"value": "C"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "C" in data["data"]["values"]

    def test_add_category_auto_init(self, client):
        """Happy path: registry doesn't exist yet → auto-init, then append."""
        resp = client.post(
            "/api/v1/registry/categories/",
            json={"value": "NewItem"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "NewItem" in data["data"]["values"]
        # Should also contain the defaults
        assert "Product" in data["data"]["values"]

    def test_add_category_duplicate(self, client, create_app_config):
        """Sad path: value already exists → conflict error."""
        create_app_config("keyword_categories", ["A", "B"], "desc")
        resp = client.post(
            "/api/v1/registry/categories/",
            json={"value": "A"},
        )
        assert resp.status_code == 409
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == "Conflict"

    def test_add_category_missing_value(self, client):
        """Edge case: missing required 'value' field → 422."""
        resp = client.post(
            "/api/v1/registry/categories/",
            json={},
        )
        assert resp.status_code == 422

    @patch("core.dependencies.jwt.decode")
    def test_add_category_unauthorized(self, mock_decode, client):
        """Sad path: unauthorized role → 403."""
        mock_decode.return_value = {"role": "viewer"}
        resp = client.post(
            "/api/v1/registry/categories/",
            json={"value": "X"},
        )
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORIES — PUT /api/v1/registry/categories/{old_value}  (rename one item)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCategoriesPut:
    def test_rename_category_success(self, client, create_app_config):
        """Happy path: rename an existing value."""
        create_app_config("keyword_categories", ["A", "B"], "desc")
        resp = client.put(
            "/api/v1/registry/categories/A",
            json={"new_value": "A_Renamed"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "A_Renamed" in data["data"]["values"]
        assert "A" not in data["data"]["values"]

    def test_rename_category_not_found(self, client, create_app_config):
        """Sad path: old_value doesn't exist in registry."""
        create_app_config("keyword_categories", ["A", "B"], "desc")
        resp = client.put(
            "/api/v1/registry/categories/NonExistent",
            json={"new_value": "X"},
        )
        assert resp.status_code == 404
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == "NotFound"

    def test_rename_category_conflict(self, client, create_app_config):
        """Sad path: new_value already exists in registry."""
        create_app_config("keyword_categories", ["A", "B"], "desc")
        resp = client.put(
            "/api/v1/registry/categories/A",
            json={"new_value": "B"},
        )
        assert resp.status_code == 409
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == "Conflict"

    def test_rename_category_missing_new_value(self, client, create_app_config):
        """Edge case: missing required 'new_value' → 422."""
        create_app_config("keyword_categories", ["A"], "desc")
        resp = client.put(
            "/api/v1/registry/categories/A",
            json={},
        )
        assert resp.status_code == 422

    @patch("core.dependencies.jwt.decode")
    def test_rename_category_unauthorized(self, mock_decode, client):
        """Sad path: unauthorized role → 403."""
        mock_decode.return_value = {"role": "viewer"}
        resp = client.put(
            "/api/v1/registry/categories/A",
            json={"new_value": "X"},
        )
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# CATEGORIES — DELETE /api/v1/registry/categories/{value_to_delete}
# ═══════════════════════════════════════════════════════════════════════════════

class TestCategoriesDelete:
    def test_delete_category_success(self, client, create_app_config):
        """Happy path: remove an existing value."""
        create_app_config("keyword_categories", ["A", "B", "C"], "desc")
        resp = client.delete("/api/v1/registry/categories/B")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "B" not in data["data"]["values"]
        assert data["data"]["values"] == ["A", "C"]

    def test_delete_category_not_found(self, client, create_app_config):
        """Sad path: value doesn't exist → NotFound error."""
        create_app_config("keyword_categories", ["A", "B"], "desc")
        resp = client.delete("/api/v1/registry/categories/NonExistent")
        assert resp.status_code == 404
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == "NotFound"

    @patch("core.dependencies.jwt.decode")
    def test_delete_category_unauthorized(self, mock_decode, client):
        """Sad path: unauthorized role → 403."""
        mock_decode.return_value = {"role": "viewer"}
        resp = client.delete("/api/v1/registry/categories/A")
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# LANGUAGES — GET /api/v1/registry/languages/
# ═══════════════════════════════════════════════════════════════════════════════

class TestLanguagesGet:
    def test_get_languages_success(self, client, create_app_config):
        """Happy path: existing config is returned."""
        create_app_config("keyword_languages", ["en-IN", "hi-IN"], "test desc")
        resp = client.get("/api/v1/registry/languages/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["key"] == "keyword_languages"
        assert data["data"]["values"] == ["en-IN", "hi-IN"]
        assert data["data"]["description"] == "test desc"
        assert "updated_at" in data["data"]

    def test_get_languages_auto_init_defaults(self, client):
        """Neutral path: DB empty → auto-creates with defaults."""
        resp = client.get("/api/v1/registry/languages/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["key"] == "keyword_languages"
        assert "en-IN" in data["data"]["values"]
        assert data["data"]["description"] == "System defaults"

    @patch("core.dependencies.jwt.decode")
    def test_get_languages_unauthorized(self, mock_decode, client):
        """Sad path: unauthorized role → 403."""
        mock_decode.return_value = {"role": "viewer"}
        resp = client.get("/api/v1/registry/languages/")
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# LANGUAGES — POST /api/v1/registry/languages/  (add one item)
# ═══════════════════════════════════════════════════════════════════════════════

class TestLanguagesPost:
    def test_add_language_success(self, client, create_app_config):
        """Happy path: append a new value to an existing registry."""
        create_app_config("keyword_languages", ["en-IN", "hi-IN"], "desc")
        resp = client.post(
            "/api/v1/registry/languages/",
            json={"value": "ta-IN"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "ta-IN" in data["data"]["values"]

    def test_add_language_auto_init(self, client):
        """Happy path: registry doesn't exist yet → auto-init, then append."""
        resp = client.post(
            "/api/v1/registry/languages/",
            json={"value": "te-IN"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "te-IN" in data["data"]["values"]
        # Should also contain the defaults
        assert "en-IN" in data["data"]["values"]

    def test_add_language_duplicate(self, client, create_app_config):
        """Sad path: value already exists → conflict error."""
        create_app_config("keyword_languages", ["en-IN", "hi-IN"], "desc")
        resp = client.post(
            "/api/v1/registry/languages/",
            json={"value": "en-IN"},
        )
        assert resp.status_code == 409
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == "Conflict"

    def test_add_language_missing_value(self, client):
        """Edge case: missing required 'value' field → 422."""
        resp = client.post(
            "/api/v1/registry/languages/",
            json={},
        )
        assert resp.status_code == 422

    @patch("core.dependencies.jwt.decode")
    def test_add_language_unauthorized(self, mock_decode, client):
        """Sad path: unauthorized role → 403."""
        mock_decode.return_value = {"role": "viewer"}
        resp = client.post(
            "/api/v1/registry/languages/",
            json={"value": "X"},
        )
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# LANGUAGES — PUT /api/v1/registry/languages/{old_value}  (rename one item)
# ═══════════════════════════════════════════════════════════════════════════════

class TestLanguagesPut:
    def test_rename_language_success(self, client, create_app_config):
        """Happy path: rename an existing value."""
        create_app_config("keyword_languages", ["en-IN", "hi-IN"], "desc")
        resp = client.put(
            "/api/v1/registry/languages/en-IN",
            json={"new_value": "en-GB"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "en-GB" in data["data"]["values"]
        assert "en-IN" not in data["data"]["values"]

    def test_rename_language_not_found(self, client, create_app_config):
        """Sad path: old_value doesn't exist in registry."""
        create_app_config("keyword_languages", ["en-IN", "hi-IN"], "desc")
        resp = client.put(
            "/api/v1/registry/languages/NonExistent",
            json={"new_value": "X"},
        )
        assert resp.status_code == 404
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == "NotFound"

    def test_rename_language_conflict(self, client, create_app_config):
        """Sad path: new_value already exists in registry."""
        create_app_config("keyword_languages", ["en-IN", "hi-IN"], "desc")
        resp = client.put(
            "/api/v1/registry/languages/en-IN",
            json={"new_value": "hi-IN"},
        )
        assert resp.status_code == 409
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == "Conflict"

    def test_rename_language_missing_new_value(self, client, create_app_config):
        """Edge case: missing required 'new_value' → 422."""
        create_app_config("keyword_languages", ["en-IN"], "desc")
        resp = client.put(
            "/api/v1/registry/languages/en-IN",
            json={},
        )
        assert resp.status_code == 422

    @patch("core.dependencies.jwt.decode")
    def test_rename_language_unauthorized(self, mock_decode, client):
        """Sad path: unauthorized role → 403."""
        mock_decode.return_value = {"role": "viewer"}
        resp = client.put(
            "/api/v1/registry/languages/en-IN",
            json={"new_value": "X"},
        )
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# LANGUAGES — DELETE /api/v1/registry/languages/{value_to_delete}
# ═══════════════════════════════════════════════════════════════════════════════

class TestLanguagesDelete:
    def test_delete_language_success(self, client, create_app_config):
        """Happy path: remove an existing value."""
        create_app_config("keyword_languages", ["en-IN", "hi-IN", "mr-IN"], "desc")
        resp = client.delete("/api/v1/registry/languages/hi-IN")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "hi-IN" not in data["data"]["values"]
        assert data["data"]["values"] == ["en-IN", "mr-IN"]

    def test_delete_language_not_found(self, client, create_app_config):
        """Sad path: value doesn't exist → NotFound error."""
        create_app_config("keyword_languages", ["en-IN", "hi-IN"], "desc")
        resp = client.delete("/api/v1/registry/languages/NonExistent")
        assert resp.status_code == 404
        data = resp.json()
        assert data["success"] is False
        assert data["error"] == "NotFound"

    @patch("core.dependencies.jwt.decode")
    def test_delete_language_unauthorized(self, mock_decode, client):
        """Sad path: unauthorized role → 403."""
        mock_decode.return_value = {"role": "viewer"}
        resp = client.delete("/api/v1/registry/languages/en-IN")
        assert resp.status_code == 403
