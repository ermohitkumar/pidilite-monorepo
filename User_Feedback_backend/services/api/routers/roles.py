"""Admin CRUD for roles that form-login users are assigned to."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from core.dependencies import RoleChecker
from core.exceptions import APIException
from core.permissions import Permissions
from core.response import make_response
from core.roles import clean_permissions, ensure_system_roles
from db.models import Role, User
from db.session import get_db
from schemas.schemas import RoleCreate, RoleListResponse, RoleResponse, RoleUpdate

logger = logging.getLogger(__name__)

DbSession = Annotated[Session, Depends(get_db)]
ManageUsers = Annotated[dict, Depends(RoleChecker(Permissions.MANAGE_USERS))]

router = APIRouter(prefix="/roles", tags=["Role Management"])


def _user_counts(db: Session) -> dict[str, int]:
    rows = db.query(User.role, func.count(User.user_id)).group_by(User.role).all()
    return {slug: count for slug, count in rows}


def _role_data(role: Role, user_count: int) -> dict:
    return {
        "role_id": str(role.role_id),
        "slug": role.slug,
        "label": role.label,
        "description": role.description,
        "permissions": list(role.permissions or []),
        "is_system": bool(role.is_system),
        "user_count": user_count,
        "created_at": role.created_at,
    }


def _sync_members(db: Session, role: Role) -> None:
    """Users keep the access bundle of the role they were given."""
    permissions = list(role.permissions or [])
    for member in db.query(User).filter(User.role == role.slug).all():
        member.allowed_resources = permissions


@router.get("/", response_model=RoleListResponse)
def list_roles(db: DbSession, request_user: ManageUsers):
    """List roles an administrator can assign, including the built-in ones."""
    ensure_system_roles(db)
    counts = _user_counts(db)
    roles = db.query(Role).order_by(Role.is_system.desc(), Role.label.asc()).all()
    items = [_role_data(role, counts.get(role.slug, 0)) for role in roles]
    return make_response(
        success=True,
        message="Roles retrieved successfully",
        data={"items": items, "total": len(items)},
    )


@router.post("/", response_model=RoleResponse)
def create_role(payload: RoleCreate, db: DbSession, request_user: ManageUsers):
    """Create a role and the pages it can open."""
    ensure_system_roles(db)
    existing = db.query(Role).filter(Role.slug == payload.slug).first()
    if existing:
        raise APIException(
            status_code=409,
            message="A role with this name already exists.",
            error="Conflict",
        )
    try:
        permissions = clean_permissions(payload.permissions)
    except ValueError as exc:
        raise APIException(status_code=422, message=str(exc), error="ValidationError")

    role = Role(
        slug=payload.slug,
        label=payload.label,
        description=payload.description,
        permissions=permissions,
        is_system=False,
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    logger.info("Role created slug=%s", role.slug)
    return make_response(
        success=True,
        message="Role created successfully",
        data=_role_data(role, 0),
    )


@router.put("/{role_id}", response_model=RoleResponse)
def update_role(role_id: str, payload: RoleUpdate, db: DbSession, request_user: ManageUsers):
    """Rename a role or change the pages it grants. Members pick up the new pages."""
    ensure_system_roles(db)
    role = db.query(Role).filter(Role.role_id == role_id).first()
    if not role:
        raise APIException(status_code=404, message="Role not found", error="NotFound")

    if payload.permissions is not None:
        if role.slug == "super_admin":
            raise APIException(
                status_code=403,
                message="Super Admin always has full access.",
                error="Forbidden",
            )
        try:
            role.permissions = clean_permissions(payload.permissions)
        except ValueError as exc:
            raise APIException(status_code=422, message=str(exc), error="ValidationError")
        _sync_members(db, role)

    if payload.label is not None:
        role.label = payload.label
    if payload.description is not None:
        role.description = payload.description

    db.commit()
    db.refresh(role)
    count = db.query(func.count(User.user_id)).filter(User.role == role.slug).scalar() or 0
    return make_response(
        success=True,
        message="Role updated successfully",
        data=_role_data(role, int(count)),
    )


@router.delete("/{role_id}")
def delete_role(role_id: str, db: DbSession, request_user: ManageUsers):
    """Delete a custom role that no account is using."""
    ensure_system_roles(db)
    role = db.query(Role).filter(Role.role_id == role_id).first()
    if not role:
        raise APIException(status_code=404, message="Role not found", error="NotFound")
    if role.is_system:
        raise APIException(
            status_code=403,
            message="Built-in roles cannot be deleted.",
            error="Forbidden",
        )
    in_use = db.query(func.count(User.user_id)).filter(User.role == role.slug).scalar() or 0
    if in_use:
        raise APIException(
            status_code=409,
            message=f"{in_use} account(s) still use this role. Reassign them first.",
            error="Conflict",
        )
    db.delete(role)
    db.commit()
    return make_response(success=True, message="Role deleted successfully")
