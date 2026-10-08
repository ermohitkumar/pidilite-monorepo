"""
/backlog/replay — register existing GCS audio that never got an upload event.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.response import make_error_response, make_response
from db.session import get_db
from services.shared.backlog_replay import DEFAULT_DAYS, replay_days

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backlog", tags=["Backlog"])


class BacklogReplayRequest(BaseModel):
    days: Optional[list[str]] = Field(
        default=None,
        description="sitelead day folders such as 22:09:26; defaults to last-week backlog",
    )
    bucket: Optional[str] = Field(default=None, description="Override GCS input bucket")
    limit: int = Field(default=0, ge=0, description="Optional cap for a dry run")


@router.post("/replay", summary="Register existing GCS audio without a new upload")
def replay_backlog(
    payload: BacklogReplayRequest = BacklogReplayRequest(),
    db: Session = Depends(get_db),
):
    """List sitelead day prefixes and call ingest for each object. Idempotent on URI."""
    try:
        result = replay_days(
            db,
            bucket=payload.bucket,
            days=payload.days or list(DEFAULT_DAYS),
            limit=payload.limit,
        )
    except Exception as exc:
        logger.exception("backlog replay failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=make_error_response(
                message="Backlog replay failed",
                error=str(exc),
            ).model_dump(),
        ) from exc

    # Drop per-file details from the HTTP envelope when the list is large; keep counts.
    summary = {key: value for key, value in result.items() if key != "results"}
    summary["sample"] = result.get("results", [])[:5]
    return make_response(
        success=True,
        message=(
            f"Backlog replay listed {result['listed']}: "
            f"{result['created']} created, {result['duplicates']} duplicates, "
            f"{result['failed']} failed"
        ),
        data=summary,
    )
