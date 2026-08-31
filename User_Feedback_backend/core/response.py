"""
Standardised API response builder for all V1 endpoints.

Usage:
    from core.response import make_response, make_error_response
"""
import uuid
from datetime import datetime, timezone

from schemas.schemas import APIResponse


def make_response(
    success: bool,
    message: str,
    data=None,
    error=None,
) -> APIResponse:
    """Build a V1 API response envelope with auto-generated timestamp and request_id."""
    return APIResponse(
        success=success,
        message=message,
        data=data,
        error=error,
        timestamp=datetime.now(timezone.utc).isoformat(),
        request_id=f"req_{uuid.uuid4().hex[:12]}",
    )


def make_error_response(message: str, error: str) -> APIResponse:
    """Convenience wrapper for error responses."""
    return make_response(success=False, message=message, error=error)
