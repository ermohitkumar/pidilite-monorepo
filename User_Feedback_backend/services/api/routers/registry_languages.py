import logging
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.dependencies import RoleChecker
from core.permissions import Permissions
from core.response import make_response
from core.exceptions import APIException
from db.session import get_db
from db.models import AppConfig
from schemas.schemas import RegistryItemCreate, RegistryItemUpdate, RegistryResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/registry/languages", tags=["Registry — Languages"])

# ── RBAC Security Dependencies ──
read_access = Depends(RoleChecker(Permissions.VIEW_DASHBOARD))
write_access = Depends(RoleChecker(Permissions.MANAGE_REGISTRY))

CONFIG_KEY = "keyword_languages"
DEFAULT_VALUES = ["en-IN", "en-US", "hi-IN", "mr-IN", "gu-IN"]


def _get_or_init_config(db: Session) -> AppConfig:
    """Helper to fetch the config, or initialize it with defaults if it doesn't exist."""
    config = db.query(AppConfig).filter(AppConfig.key == CONFIG_KEY).first()
    if not config:
        config = AppConfig(key=CONFIG_KEY, value=DEFAULT_VALUES,
                           description="System defaults")
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


# ── READ (List all languages) ──
@router.get("/", response_model=RegistryResponse, dependencies=[read_access])
def get_languages(db: Session = Depends(get_db)):
    """Fetches the list of keyword languages."""
    try:
        config = _get_or_init_config(db)
        return make_response(success=True, message="Languages retrieved", data={
            "key": config.key, "values": config.value, "description": config.description, "updated_at": config.updated_at
        })
    except APIException:
        raise
    except Exception as exc:
        logger.error("Failed to fetch languages: %s", exc, exc_info=True)
        raise APIException(
            status_code=500, message="Failed to fetch languages", error=str(exc))


# ── CREATE (Add one language) ──
@router.post("/", response_model=RegistryResponse, dependencies=[write_access])
def add_language(payload: RegistryItemCreate, db: Session = Depends(get_db)):
    """Appends a new language to the list."""
    try:
        config = _get_or_init_config(db)

        # Unpack JSONB array to a standard python list to manipulate it
        current_values = list(config.value)
        if payload.value in current_values:
            raise APIException(
                status_code=409, message=f"'{payload.value}' already exists in languages", error="Conflict")

        current_values.append(payload.value)
        config.value = current_values  # Re-assign so SQLAlchemy detects the change

        db.commit()
        db.refresh(config)

        return make_response(success=True, message="Language added successfully", data={
            "key": config.key, "values": config.value, "description": config.description, "updated_at": config.updated_at
        })
    except APIException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("Failed to add language: %s", exc, exc_info=True)
        raise APIException(
            status_code=500, message="Failed to add language", error=str(exc))


# ── UPDATE (Rename one language) ──
@router.put("/{old_value}", response_model=RegistryResponse, dependencies=[write_access])
def update_language(old_value: str, payload: RegistryItemUpdate, db: Session = Depends(get_db)):
    """Renames a specific language."""
    try:
        config = _get_or_init_config(db)
        current_values = list(config.value)

        if old_value not in current_values:
            raise APIException(
                status_code=404, message=f"'{old_value}' not found in languages", error="NotFound")

        if payload.new_value in current_values:
            raise APIException(
                status_code=409, message=f"'{payload.new_value}' already exists in languages", error="Conflict")

        # Find the index of the old value and replace it
        idx = current_values.index(old_value)
        current_values[idx] = payload.new_value
        config.value = current_values

        db.commit()
        db.refresh(config)

        return make_response(success=True, message="Language updated successfully", data={
            "key": config.key, "values": config.value, "description": config.description, "updated_at": config.updated_at
        })
    except APIException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("Failed to update language: %s", exc, exc_info=True)
        raise APIException(
            status_code=500, message="Failed to update language", error=str(exc))


# ── DELETE (Remove one language) ──
@router.delete("/{value_to_delete}", response_model=RegistryResponse, dependencies=[write_access])
def delete_language(value_to_delete: str, db: Session = Depends(get_db)):
    """Removes a specific language from the list."""
    try:
        config = _get_or_init_config(db)
        current_values = list(config.value)

        if value_to_delete not in current_values:
            raise APIException(
                status_code=404, message=f"'{value_to_delete}' not found in languages", error="NotFound")

        # Remove the item
        current_values.remove(value_to_delete)
        config.value = current_values

        db.commit()
        db.refresh(config)

        return make_response(success=True, message="Language deleted successfully", data={
            "key": config.key, "values": config.value, "description": config.description, "updated_at": config.updated_at
        })
    except APIException:
        raise
    except Exception as exc:
        db.rollback()
        logger.error("Failed to delete language: %s", exc, exc_info=True)
        raise APIException(
            status_code=500, message="Failed to delete language", error=str(exc))
