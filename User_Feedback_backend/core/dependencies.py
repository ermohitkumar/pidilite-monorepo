# core/dependencies.py

import jwt
import logging
from fastapi import Request, HTTPException, status, Depends, Security
from sqlalchemy.orm import Session
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from core.config import settings
from db.session import get_db
from db.models import User

logger = logging.getLogger(__name__)

SECRET_KEY = settings.SESSION_SECRET_KEY
ALGORITHM = "HS256"
COOKIE_NAME = "pidilite_session_cookie"

token_auth_scheme = HTTPBearer()


def create_access_token(data: dict, expires_hours: int = 24) -> str:
    """Mint an internal HS256 JWT for the session."""
    from datetime import datetime, timezone, timedelta

    payload = data.copy()
    payload["exp"] = datetime.now(
        tz=timezone.utc) + timedelta(hours=expires_hours)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


class RoleChecker:
    def __init__(self, resource_name: str):
        self.resource_name = resource_name

    def __call__(self, request: Request, db: Session = Depends(get_db), swagger_auth: HTTPBearer = Depends(token_auth_scheme)):
        # 0. Bypass in development
        if not settings.is_production:
            return {"user_id": "dev-bypass-id", "role": "super_admin"}

        # 1. Check Header or Cookie
        token = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
        if not token:
            token = request.cookies.get(COOKIE_NAME)

        if not token:
            raise HTTPException(
                status_code=401, detail="Not authenticated. Missing session token.")

        # 2. Decode the JWT to get the user ID
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            user_id = payload.get("user_id") or payload.get("userId") or payload.get("sub")
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Session expired.")
        except jwt.InvalidTokenError:
            raise HTTPException(
                status_code=401, detail="Invalid session token.")

        # 3. REAL-TIME DATABASE CHECK
        user = db.query(User).filter(User.user_id == user_id).first()

        if not user or not user.is_active:
            raise HTTPException(
                status_code=403, detail="Account is disabled or deleted.")

        # 4. Super Admins always have access to everything
        if user.role == "super_admin":
            return payload

        # 5. Check if this specific user has been granted this specific resource
        has_access = False
        if user.allowed_resources:
            for item in user.allowed_resources:
                if isinstance(item, str) and item == self.resource_name:
                    has_access = True
                    break
                elif isinstance(item, dict) and self.resource_name in item.values():
                    has_access = True
                    break

        if not has_access:
            raise HTTPException(
                status_code=403,
                detail=f"You do not have permission to access the '{self.resource_name}' resource."
            )

        return payload


def verify_sso_user(
    credentials: HTTPAuthorizationCredentials = Security(token_auth_scheme),
    db: Session = Depends(get_db)
):
    """
    Decodes an incoming JWT, extracts the email, and verifies the user exists in the database.
    """
    # 1. Extract the raw token from the header
    sso_token = credentials.credentials

    # 2. Decode the JWT token
    try:
        payload = jwt.decode(sso_token, SECRET_KEY, algorithms=[ALGORITHM])

        extracted_email = payload.get("email")

        if not extracted_email:
            raise HTTPException(
                status_code=400,
                detail="Token does not contain a valid 'email' claim."
            )

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401, detail="Token has expired.")
    except jwt.DecodeError:
        raise HTTPException(
            status_code=401, detail="Invalid token format.")
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=401, detail="Invalid token.")

    # 3. Perform the real-time Database Check
    user = db.query(User).filter(User.email == extracted_email).first()

    if not user:
        raise HTTPException(
            status_code=401, detail="User not registered in the system.")
    if not user.is_active:
        raise HTTPException(
            status_code=403, detail="User account is deactivated.")

    return user
