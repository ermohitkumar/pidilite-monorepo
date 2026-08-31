import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.dependencies import RoleChecker
from core.permissions import Permissions
from core.response import make_response
from core.exceptions import APIException
from db.session import get_db
from db.models import KeywordDictionary
from schemas.schemas import (
    KeywordCreate, KeywordUpdate, KeywordListResponse, KeywordActionResponse
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/keywords", tags=["Keyword Management"])

# ── RBAC Security Dependencies ──
# Admins and Super Admins can view and manage keywords
read_access = Depends(RoleChecker(Permissions.VIEW_DASHBOARD))
write_access = Depends(RoleChecker(Permissions.MANAGE_REGISTRY))

# ── Annotated dependency aliases ──
DbSession = Annotated[Session, Depends(get_db)]

_INTERNAL_ERROR = "Internal error"


@router.get("/", response_model=KeywordListResponse, dependencies=[read_access])
def list_keywords(
    db: DbSession,
    category: Annotated[Optional[str], Query(
        description="Filter by category")] = None,
):
    """Fetch all keywords, populating the main data table in the UI."""
    try:
        query = db.query(KeywordDictionary)
        if category:
            query = query.filter(KeywordDictionary.category == category)

        keywords = query.order_by(KeywordDictionary.priority.desc()).all()

        items = [{
            "canonical_id": kw.canonical_id,
            "canonical_term": kw.canonical_term,
            "category": kw.category,
            "aliases": kw.aliases or [],
            "priority": kw.priority,
            "owner": kw.owner,
            "version": kw.version,
            "updated_at": kw.updated_at
        } for kw in keywords]

        return make_response(success=True, message="Keywords retrieved successfully", data=items)
    except Exception:
        logger.exception("Failed to fetch keywords")
        raise APIException(
            status_code=500, message="Failed to fetch keywords", error=_INTERNAL_ERROR)


@router.post("/", response_model=KeywordActionResponse, dependencies=[write_access])
def create_keyword(payload: KeywordCreate, db: DbSession):
    """Adds a new canonical product and its known misspellings to the dictionary."""
    existing = db.query(KeywordDictionary).filter(
        KeywordDictionary.canonical_id == payload.canonical_id).first()
    if existing:
        raise APIException(
            status_code=409, message="Canonical ID already exists", error="Conflict")

    try:
        new_kw = KeywordDictionary(
            canonical_id=payload.canonical_id,
            canonical_term=payload.canonical_term,
            category=payload.category,
            aliases=payload.aliases,
            priority=payload.priority,
            owner=payload.owner,
        )
        db.add(new_kw)
        db.commit()
        db.refresh(new_kw)

        return make_response(
            success=True,
            message="Keyword created successfully",
            data={"canonical_id": new_kw.canonical_id}
        )
    except Exception:
        db.rollback()
        logger.exception("Failed to create keyword")
        raise APIException(
            status_code=500, message="Failed to create keyword", error=_INTERNAL_ERROR)


@router.put("/{canonical_id}", response_model=KeywordActionResponse, dependencies=[write_access])
def update_keyword(canonical_id: str, payload: KeywordUpdate, db: DbSession):
    """Updates an existing keyword (e.g., adding a new misspelling alias)."""
    kw = db.query(KeywordDictionary).filter(
        KeywordDictionary.canonical_id == canonical_id).first()
    if not kw:
        raise APIException(
            status_code=404, message="Keyword not found", error="NotFound")

    try:
        update_data = payload.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(kw, key, value)

        kw.version = (kw.version or 1) + 1
        db.commit()
        db.refresh(kw)

        return make_response(
            success=True,
            message="Keyword updated successfully",
            data={"canonical_id": kw.canonical_id, "version": kw.version}
        )
    except Exception:
        db.rollback()
        logger.exception("Failed to update keyword %s", canonical_id)
        raise APIException(
            status_code=500, message="Failed to update keyword", error=_INTERNAL_ERROR)


@router.delete("/{canonical_id}", response_model=KeywordActionResponse, dependencies=[write_access])
def delete_keyword(canonical_id: str, db: DbSession):
    """Permanently deletes the keyword from the dictionary."""
    kw = db.query(KeywordDictionary).filter(
        KeywordDictionary.canonical_id == canonical_id).first()
    if not kw:
        raise APIException(
            status_code=404, message="Keyword not found", error="NotFound")

    try:
        db.delete(kw)
        db.commit()

        return make_response(
            success=True,
            message="Keyword deleted successfully",
            data={"canonical_id": canonical_id}
        )
    except Exception:
        db.rollback()
        logger.exception("Failed to delete keyword %s", canonical_id)
        raise APIException(
            status_code=500, message="Failed to delete keyword", error=_INTERNAL_ERROR)
