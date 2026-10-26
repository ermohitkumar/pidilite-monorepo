# routers/users.py

import logging
from typing import Optional, Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from core.permissions import Permissions
from core.dependencies import RoleChecker, get_current_user
from core.response import make_response
from core.exceptions import APIException
from core.roles import ensure_system_roles
from core.security import hash_password
from db.session import get_db
from db.models import Role, User
from schemas.schemas import UserCreate, UserUpdate, UserResponse, UserListResponse, PermissionsListResponse

logger = logging.getLogger(__name__)

# ── Annotated dependency aliases ──
DbSession = Annotated[Session, Depends(get_db)]

_USER_NOT_FOUND_MSG = "User not found"

router = APIRouter(prefix="/users", tags=["User Management"])


def _require_role(db: Session, slug: str) -> Role:
    """Return a role created in the admin panel, seeding the built-in ones first."""
    ensure_system_roles(db)
    role = db.query(Role).filter(Role.slug == slug).first()
    if not role:
        raise APIException(
            status_code=400,
            message="Unknown role. Create it in the admin panel before assigning it.",
            error="InvalidRole",
        )
    return role


def _permissions_for(role: Role, explicit: list | None) -> list:
    if explicit:
        return explicit
    return list(role.permissions or [])


@router.get("/permissions", response_model=PermissionsListResponse)
def list_available_permissions(
    request_user: Annotated[dict, Depends(
        RoleChecker(Permissions.MANAGE_USERS))]
):
    """Returns the list of all available dynamic permissions that a Super Admin can allocate."""
    return make_response(
        success=True,
        message="Permissions retrieved successfully",
        data=Permissions.list_all()
    )


@router.post("/", response_model=UserResponse)
def create_user(
    payload: UserCreate,
    db: DbSession,
    request_user: Annotated[dict, Depends(
        RoleChecker(Permissions.MANAGE_USERS))]
):
    """Create a new user. Applies Role Escalation Guarding."""

    # ── 1. ROLE ESCALATION GUARD (Creation) ──
    if payload.role == "super_admin" and request_user.get("role") != "super_admin":
        raise APIException(
            status_code=403,
            message="Permission Denied: Only Super Admins can create other Super Admins.",
            error="Forbidden"
        )

    existing_user = db.query(User).filter(User.email == payload.email).first()
    if existing_user:
        raise APIException(
            status_code=409, message="Email already registered", error="Conflict")

    if payload.username:
        taken = db.query(User).filter(User.username == payload.username).first()
        if taken:
            raise APIException(
                status_code=409, message="Username already registered", error="Conflict")

    role = _require_role(db, payload.role)
    new_user = User(
        email=payload.email,
        username=payload.username,
        full_name=payload.full_name,
        role=role.slug,
        password_hash=hash_password(payload.password) if payload.password else None,
        is_active=True,
        allowed_resources=_permissions_for(role, payload.allowed_resources),
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    user_data = {
        "user_id": str(new_user.user_id),
        "email": new_user.email,
        "username": new_user.username,
        "full_name": new_user.full_name,
        "role": new_user.role,
        "is_active": new_user.is_active,
        "allowed_resources": new_user.allowed_resources,
        "created_at": new_user.created_at
    }
    return make_response(success=True, message="User created successfully", data=user_data)


@router.get("/", response_model=UserListResponse)
def list_users(db: DbSession, request_user: Annotated[dict, Depends(RoleChecker(Permissions.MANAGE_USERS))]):
    """List all users in the system."""
    users = db.query(User).all()
    items = [{
        "user_id": str(u.user_id),
        "email": u.email,
        "username": u.username,
        "full_name": u.full_name,
        "role": u.role,
        "is_active": u.is_active,
        "allowed_resources": u.allowed_resources,
        "created_at": u.created_at
    } for u in users]

    return make_response(success=True, message="Users retrieved successfully", data={"items": items, "total": len(items)})


@router.get("/{user_id}", response_model=UserResponse)
def get_user_profile(
    user_id: str,
    db: DbSession,
    token_payload: Annotated[dict, Depends(get_current_user)]
):
    """Get a user's profile. Admins/Users can only see their own; Super Admins can see anyone."""

    # SECURITY CHECK: Block users from viewing other people's user_ids
    if token_payload.get("user_id") != user_id and token_payload.get("role") != "super_admin":
        raise APIException(
            status_code=403,
            message="Unauthorized: You can only view your own profile",
            error="Forbidden"
        )

    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise APIException(
            status_code=404, message=_USER_NOT_FOUND_MSG, error="NotFound")

    user_data = {
        "user_id": str(user.user_id),
        "email": user.email,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "is_active": user.is_active,
        "allowed_resources": user.allowed_resources,
        "created_at": user.created_at
    }

    return make_response(success=True, message="Profile retrieved successfully", data=user_data)


@router.put("/{target_user_id}", response_model=UserResponse)
def update_user(
    target_user_id: str,
    payload: UserUpdate,
    db: DbSession,
    request_user: Annotated[dict, Depends(
        RoleChecker(Permissions.MANAGE_USERS))]
):
    """Update an existing user's details, role, or dynamic permissions."""
    user = db.query(User).filter(User.user_id == target_user_id).first()
    if not user:
        raise APIException(
            status_code=404, message=_USER_NOT_FOUND_MSG, error="NotFound")

    # ── 1. ROLE ESCALATION GUARD (Update) ──
    if payload.role is not None:
        role = _require_role(db, payload.role)
        if payload.role != user.role:
            if request_user.get("role") != "super_admin":
                raise APIException(
                    status_code=403,
                    message="Permission Denied: Only Super Admins can change user roles.",
                    error="Forbidden"
                )
            user.role = role.slug
        # The role is the source of access unless the caller sends an override.
        if payload.allowed_resources is None:
            user.allowed_resources = list(role.permissions or [])

    # ── 2. DYNAMIC PERMISSIONS (allowed_resources) ──
    if payload.allowed_resources is not None:
        user.allowed_resources = payload.allowed_resources

    # ── 3. STANDARD FIELDS ──
    if payload.email is not None:
        user.email = payload.email
    if payload.username is not None:
        user.username = payload.username
    if payload.full_name is not None:
        user.full_name = payload.full_name
    if payload.is_active is not None:
        user.is_active = payload.is_active

    if payload.password is not None:
        user.password_hash = hash_password(payload.password)

    db.commit()
    db.refresh(user)

    user_data = {
        "user_id": str(user.user_id),
        "email": user.email,
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role,
        "is_active": user.is_active,
        "allowed_resources": user.allowed_resources,
        "created_at": user.created_at
    }
    return make_response(success=True, message="User updated successfully", data=user_data)


@router.delete("/{user_id}")
def delete_user(
    user_id: str,
    db: DbSession,
    request_user: Annotated[dict, Depends(
        RoleChecker(Permissions.MANAGE_USERS))]
):
    """Deactivate a user (soft delete)."""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise APIException(
            status_code=404, message=_USER_NOT_FOUND_MSG, error="NotFound")

    user.is_active = False
    db.commit()

    return make_response(success=True, message="User deactivated successfully")
