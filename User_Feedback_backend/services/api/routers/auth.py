import logging

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from core.response import make_response
from core.exceptions import APIException
from core.security import verify_password, login_user, logout_user
from core.config import settings
from db.session import get_db
from db.models import User
from schemas.schemas import LoginRequest
from core.dependencies import verify_sso_user, create_access_token

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Authentication"])


@router.post("/auth/login")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Authenticates the user using email and sets a secure session cookie.
    Only available in development. Production must use SSO via /auth/verify."""

    # ── ENVIRONMENT GUARD: Form login is disabled in production ──
    if settings.is_production:
        raise APIException(
            status_code=403,
            message="Form login is disabled in production. Please use SSO.",
            error="Forbidden"
        )

    logger.info("Login attempt for email='%s'", payload.email)

    try:
        user = db.query(User).filter(User.email == payload.email).first()
    except Exception as exc:
        logger.error("Database error during login: %s", exc, exc_info=True)
        raise APIException(
            status_code=500,
            message="Login failed due to a server error",
            error="ServerError"
        )

    if not user or not user.password_hash or not verify_password(payload.password, user.password_hash):
        logger.warning("Failed login attempt for email='%s'", payload.email)
        raise APIException(
            status_code=401,
            message="Invalid email or password",
            error=[
                {
                    "type": "authentication_error",
                    "loc": ["body", "credentials"],
                    "msg": "Invalid email or password",
                    "input": payload.email,
                    "ctx": {"error": {}}
                }
            ]
        )

    if not user.is_active:
        logger.warning("Login attempt for inactive user='%s'", payload.email)
        raise APIException(
            status_code=403,
            message="User account is inactive",
            error="AccountDisabled"
        )

    # Establish session
    user_data = {
        "user_id": str(user.user_id),
        "username": user.username,
        "email": user.email,
        "role": user.role
    }
    login_user(request, user_data)

    access_token = create_access_token(
        data={
            "user_id": str(user.user_id),
            "email": user.email,
            "role": user.role
        }
    )

    logger.info("Login successful for email='%s' (role=%s)",
                payload.email, user.role)
    return make_response(
        success=True,
        message="Login successful",
        data={
            "user": user_data,
            "access_token": access_token
        }
    )


@router.post("/auth/verify")
def verify_sso(
    response: Response,
    # Relies entirely on the header now!
    verified_user: User = Depends(verify_sso_user)
):
    # The user is already verified against Postgres by the dependency.
    # 1. Mint the internal FastAPI JWT
    access_token = create_access_token(
        data={
            "user_id": str(verified_user.user_id),
            "email": verified_user.email,
            "role": verified_user.role
        }
    )

    # 2. Return the data to Next.js
    return {
        "success": True,
        "data": {
            "user": {
                "user_id": str(verified_user.user_id),
                "email": verified_user.email,
                "role": verified_user.role
            },
            "access_token": access_token
        }
    }


@router.post("/auth/logout")
def logout(request: Request):
    """Clears the session cookie."""
    logout_user(request)
    logger.info("User logged out")
    return make_response(success=True, message="Logged out successfully")
