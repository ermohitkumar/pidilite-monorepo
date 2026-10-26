# services/api/main.py
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import settings
from db.session import Base, engine
from db import models  # noqa: F401
from services.api.routers import (
    ingest,
    batch,
    backlog,
    stt,
    stt_complete,
    translate,
    normalize,
    checker,
)

logger = logging.getLogger(__name__)

def _sync_taxonomy(db) -> None:
    """Upsert scripts/data/feedback_taxonomy.json and retire tags it no longer lists.

    group_type stays the level-1 bucket (PDT GROUP, USER GROUP, DEALER GROUP).
    Repeated names such as Others are kept as separate tag_id rows.
    """
    import json
    import os

    from db.models import FeedbackTag

    taxonomy_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "scripts", "data", "feedback_taxonomy.json"
    )
    if not os.path.exists(taxonomy_path):
        logger.warning("Taxonomy seed file not found at %s", taxonomy_path)
        return
    with open(taxonomy_path, encoding="utf-8") as handle:
        entries = json.load(handle).get("taxonomy", [])
    seen: set[int] = set()
    for entry in entries:
        tag_id = int(entry["tag_id"])
        seen.add(tag_id)
        fields = {
            "tag_name": entry["feedback_tag"],
            "sub_tag_name": entry.get("feedback_sub_tag"),
            "description": entry.get("description"),
            "group_type": entry.get("feedback_group") or entry.get("level_1"),
            "category": entry.get("feedback_category"),
            "is_active": True,
        }
        tag = db.get(FeedbackTag, tag_id)
        if tag is None:
            db.add(FeedbackTag(tag_id=tag_id, **fields))
        else:
            for key, value in fields.items():
                setattr(tag, key, value)
    retired = 0
    for tag in db.query(FeedbackTag).all():
        if tag.tag_id not in seen and tag.is_active:
            tag.is_active = False
            retired += 1
    db.commit()
    logger.info("Taxonomy sync: %s active tags, %s retired", len(seen), retired)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from sqlalchemy import text

    from db.session import SessionLocal, engine
    from db.models import Product
    import json
    import os
    db = SessionLocal()
    try:
        if engine.dialect.name == "postgresql":
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE feedbacks ADD COLUMN IF NOT EXISTS theme VARCHAR(200)"
                ))
                conn.execute(text(
                    "ALTER TABLE feedbacks ADD COLUMN IF NOT EXISTS others_info TEXT"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_feedbacks_theme ON feedbacks (theme)"
                ))
            with engine.begin() as conn:
                if not conn.execute(text("SELECT to_regclass('public.feedback_tags')")).scalar():
                    names = []
                else:
                    names = conn.execute(text("""
                        SELECT c.conname
                        FROM pg_constraint c
                        JOIN pg_attribute a
                          ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
                        WHERE c.conrelid = 'feedback_tags'::regclass
                          AND c.contype = 'u'
                          AND a.attname = 'tag_name'
                          AND cardinality(c.conkey) = 1
                    """)).fetchall()
                for (name,) in names:
                    conn.execute(text(
                        f'ALTER TABLE feedback_tags DROP CONSTRAINT IF EXISTS "{name}"'
                    ))
            logger.info("Feedback theme columns verified")

        # ── Seed Products ──
        if db.query(Product).count() == 0:
            logger.info("Products table is empty. Seeding from local_products.json...")
            catalog_path = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "data", "local_products.json")
            if os.path.exists(catalog_path):
                with open(catalog_path) as f:
                    products = json.load(f)
                for row in products:
                    db.add(Product(
                        product_name=row.get("product_name"),
                        short_code=row.get("short_code"),
                        description=row.get("description"),
                        is_active=bool(row.get("is_active", True))
                    ))
                db.commit()
                logger.info(f"Seeded {len(products)} products.")
            else:
                logger.warning(f"Seed file not found at {catalog_path}")

        _sync_taxonomy(db)
    except Exception as e:
        logger.error(f"Failed to seed data: {e}")
    finally:
        db.close()
    yield

app = FastAPI(
    title="Pidilite Pipeline Service",
    description="GCP-triggered pipeline: ingest → batch → STT → translate → normalize → insights",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_methods=["POST"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception on %s %s: %s",
                 request.method, request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error."},
    )

PREFIX = "/api/v1"
app.include_router(ingest.router,    prefix=PREFIX)
app.include_router(batch.router,     prefix=PREFIX)
app.include_router(backlog.router,   prefix=PREFIX)
app.include_router(stt.router,         prefix=PREFIX)
app.include_router(stt_complete.router, prefix=PREFIX)
app.include_router(translate.router,   prefix=PREFIX)
app.include_router(normalize.router,   prefix=PREFIX)
app.include_router(checker.router,   prefix=PREFIX)

@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok", "service": "pipeline"}


@app.get("/health/gcs", tags=["Health"])
def health_gcs():
    """Probe HTTPS to the output bucket — fails fast if SSL/CA is broken."""
    try:
        from google.cloud import storage as gcs_storage

        client = gcs_storage.Client()
        bucket_name = settings.GCS_OUTPUT_BUCKET
        exists = client.bucket(bucket_name).exists()
        return {
            "status": "ok" if exists else "missing_bucket",
            "service": "pipeline",
            "bucket": bucket_name,
            "exists": exists,
        }
    except Exception as exc:
        logger.exception("GCS health probe failed")
        return {
            "status": "error",
            "service": "pipeline",
            "error": type(exc).__name__,
            "message": str(exc)[:500],
        }