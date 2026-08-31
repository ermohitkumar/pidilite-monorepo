"""
Backend API Service  (port 8000)
──────────────────────────────────
The only public-facing service (behind VPC / Cloud Run ingress).
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from core.config import settings
import db.session
from db import models
from services.api.routers import auth, dashboard, users, keywords, registry_categories, registry_languages, reports, catalog
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from core.exceptions import APIException
from core.response import make_response
from fastapi.encoders import jsonable_encoder

logger = logging.getLogger(__name__)


# ── Security Headers Middleware ───────────────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Injects defence-in-depth HTTP headers on every response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        # Disable legacy XSS auditor — CSP is the modern replacement
        response.headers["X-XSS-Protection"] = "0"

        # Swagger UI requires inline scripts/styles and external CDNs.
        # Apply a relaxed CSP for docs, and strict CSP for everything else.
        if request.url.path in ["/docs", "/redoc", "/openapi.json"]:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "img-src 'self' data: https://fastapi.tiangolo.com; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "frame-ancestors 'none'"
            )
        else:
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; frame-ancestors 'none'"
            )

        # HSTS — only set when running behind TLS in production
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )
        return response


# ── CSRF Protection Middleware ────────────────────────────────────────────────
_CSRF_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class CsrfHeaderMiddleware(BaseHTTPMiddleware):
    """
    Requires a custom header ``X-Requested-With`` on all state-mutating requests.

    Browsers will NOT attach custom headers on cross-origin form submissions
    or simple CORS requests, so its presence proves the request came from
    JavaScript running on an allowed origin (enforced by CORS preflight).
    """

    async def dispatch(self, request: Request, call_next):
        if request.method not in _CSRF_SAFE_METHODS:
            if not request.headers.get("X-Requested-With"):
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "Missing X-Requested-With header."},
                )
        return await call_next(request)


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        db.session.Base.metadata.create_all(bind=db.session.engine)
        logger.info("DB tables verified successfully")
        print("✅  DB tables verified.")
    except Exception as exc:
        logger.critical(
            "Failed to initialise database tables: %s", exc, exc_info=True)
        raise
    yield
    logger.info("Application shutting down")


# ── App Factory ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Pidilite Audio Pipeline — API",
    description=(
        "Backend API for the Pidilite audio transcription + insights pipeline. "
        "Runs inside a GCP VPC. 5 endpoints for the full processing flow."
    ),
    version="0.1.0",
    lifespan=lifespan,
    # Disable interactive docs in production to avoid exposing the API surface
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

# ── Middleware Stack (ASGI is LIFO — first added = last to execute) ───────────

# 1. Security headers — runs on every response
if settings.is_production:
    app.add_middleware(SecurityHeadersMiddleware)

# 2. CSRF custom-header check — runs before route handlers
if settings.is_production:
    app.add_middleware(CsrfHeaderMiddleware)

# 3. Session middleware for form-login
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET_KEY,
    max_age=settings.SESSION_MAX_AGE,
    https_only=settings.is_production,     # Secure flag in production
    same_site="strict" if settings.is_production else "lax",
)

# 4. CORS — added last so it executes first in the middleware chain
# Never use allow_origins=["*"] with allow_credentials=True — browsers block it.
# Dev reflects any http(s) origin via regex; production uses an explicit allow-list.
_cors_kwargs = dict(
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=(
        ["Content-Type", "Authorization", "X-Requested-With"]
        if settings.is_production
        else ["*"]
    ),
)
if settings.is_production:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        **_cors_kwargs,
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://.*",
        **_cors_kwargs,
    )


# ── Global error handler ──────────────────────────────────────────────────────
@app.exception_handler(APIException)
async def api_exception_handler(request: Request, exc: APIException):
    response = make_response(
        success=False,
        message=exc.message,
        data={},
        error=exc.error
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=response.model_dump(mode="json")
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = jsonable_encoder(exc.errors())
    message = "Validation Error"
    if len(errors) > 0 and "msg" in errors[0]:
        # Fastapi might prepend "Value error, " which we could clean up
        message = errors[0]["msg"].replace("Value error, ", "")

    response = make_response(
        success=False,
        message=message,
        data={},
        error=errors
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=response.model_dump(mode="json")
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    response = make_response(
        success=False,
        message=str(exc.detail),
        error="HTTPException"
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=response.model_dump(mode="json")
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled exception on %s %s: %s",
        request.method, request.url.path, exc, exc_info=True,
    )
    # Never leak exception details to the client
    response = make_response(
        success=False,
        message="Internal server error.",
        error="InternalServerError"
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=response.model_dump(mode="json")
    )


# ── Routers ──────────────────────────────────────────────────────────────────
PREFIX = "/api/v1"
app.include_router(auth.router, prefix=PREFIX)
app.include_router(dashboard.router, prefix=PREFIX)
app.include_router(users.router, prefix=PREFIX)
app.include_router(keywords.router, prefix=PREFIX)
app.include_router(registry_categories.router, prefix=PREFIX)
app.include_router(registry_languages.router, prefix=PREFIX)
app.include_router(reports.router, prefix=PREFIX)
app.include_router(catalog.products_router, prefix=PREFIX)
app.include_router(catalog.tags_router, prefix=PREFIX)


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok", "service": "backend-api"}
