# services/api/main.py
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import settings
from db.session import Base, engine
from db import models  # noqa: F401
from services.api.routers import ingest, batch, stt, gemini_stt, stt_complete, translate, normalize, checker

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    from db.session import SessionLocal
    from db.models import Product, FeedbackTag
    import json
    import os
    db = SessionLocal()
    try:
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

        # ── Seed Feedback Tags ──
        if db.query(FeedbackTag).count() == 0:
            logger.info("FeedbackTags table is empty. Seeding from feedback_taxonomy.json...")
            taxonomy_path = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "data", "feedback_taxonomy.json")
            if os.path.exists(taxonomy_path):
                with open(taxonomy_path, encoding="utf-8") as f:
                    data = json.load(f)
                entries = data.get("taxonomy", [])
                for entry in entries:
                    db.add(FeedbackTag(
                        tag_id=entry["tag_id"],
                        tag_name=entry["feedback_tag"],
                        sub_tag_name=entry.get("feedback_sub_tag"),
                        description=entry.get("description"),
                        group_type=entry.get("feedback_group"),
                        category=entry.get("feedback_category"),
                    ))
                db.commit()
                logger.info(f"Seeded {len(entries)} feedback tags.")
            else:
                logger.warning(f"Taxonomy seed file not found at {taxonomy_path}")
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
app.include_router(stt.router,         prefix=PREFIX)
app.include_router(gemini_stt.router,  prefix=PREFIX)
app.include_router(stt_complete.router, prefix=PREFIX)
app.include_router(translate.router,   prefix=PREFIX)
app.include_router(normalize.router,   prefix=PREFIX)
app.include_router(checker.router,   prefix=PREFIX)

@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok", "service": "pipeline"}