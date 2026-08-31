"""
Simple form-based login for VPC-internal use.
No JWT. Uses Starlette's signed-cookie session middleware.

Usage:
    from core.security import require_login, hash_password, verify_password
"""
import bcrypt
from fastapi import Request, HTTPException, status


def hash_password(plain: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def get_session_user(request: Request) -> dict | None:
    """Return the logged-in user dict from session, or None."""
    return request.session.get("user")


def require_login(request: Request) -> dict:
    """
    FastAPI dependency — redirect to /login if not authenticated.
    Use in router dependencies:
        user = Depends(require_login)
    """
    user = get_session_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in.",
            headers={"WWW-Authenticate": "Session"},
        )
    return user


def login_user(request: Request, user_data: dict) -> None:
    """Store user data in session after successful login."""
    request.session["user"] = {
        "user_id": user_data["user_id"],
        "username": user_data["username"],
        "role": user_data.get("role", "viewer"),
    }


def logout_user(request: Request) -> None:
    """Clear user session."""
    request.session.clear()
