"""
/files/post-processing — Cloud Task handler for AI Insights. 
Reads translated_text from DB, generates insights using Two-Part Prompt, 
maps them to the flattened dashboard taxonomy, and marks job COMPLETED.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from core.config import settings
from core.response import make_response
from db.session import get_db
from repositories import batch_repository
from db.models import (
    ProcessedFile, Feedback, FeedbackCompetitor, 
    FeedbackTag, Product
)
from core.enums import JobStatus
from schemas.schemas import PostProcessRequest, NormalizeInsightsResponseData
from services.shared import vertex_ai
from services.shared.product_catalog import build_product_tsv
from services.shared.product_resolve import enforce_master_product_names, resolve_product_from_master

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/files", tags=["Files"])

_POST_PROCESS_ALLOWED = frozenset({
    JobStatus.TRANSLATED,
    JobStatus.PROCESSING,
    JobStatus.NORMALIZED,
    JobStatus.INSIGHTS,
    JobStatus.ERROR,
})


def _norm_text(value: str | None) -> str:
    return " ".join((value or "").split()).strip().lower()


def _feedback_dedupe_key(
    product_name: str | None,
    group_type: str | None,
    verbatim_quote: str | None,
    summary: str | None,
) -> tuple[str, str, str, str]:
    return (
        _norm_text(product_name),
        _norm_text(group_type),
        _norm_text(verbatim_quote),
        _norm_text(summary),
    )


def _competitor_names(feedback_data: dict) -> list[str]:
    names = []
    for raw in feedback_data.get("competitors_mentioned") or []:
        name = str(raw).strip()
        if name:
            names.append(name)
    return names


def _is_competition_insight(db: Session, feedback_data: dict) -> bool:
    if _competitor_names(feedback_data):
        return True
    category = (feedback_data.get("category_type") or "").lower()
    if "competit" in category:
        return True
    for raw_tag in feedback_data.get("tags") or []:
        if "competit" in str(raw_tag).lower():
            return True
    tag_ids = [tid for tid in (feedback_data.get("tag_ids") or []) if tid is not None]
    if not tag_ids:
        return False
    tags = db.query(FeedbackTag).filter(FeedbackTag.tag_id.in_(tag_ids)).all()
    for tag in tags:
        blob = f"{tag.tag_name or ''} {tag.category or ''} {tag.sub_tag_name or ''}".lower()
        if "competit" in blob:
            return True
    return False


def _competition_product_name(
    canonical_name: str | None,
    competitor_names: list[str],
    raw_product_name: str | None = None,
) -> tuple[str | None, bool]:
    """Competition insights keep a catalog Pidilite SKU or competitor names.

    product_name is catalog-only. Competitor names (Century, SupaStik, …) stay
    in competitors_mentioned, never in product_name.
    Returns (display_name, keep).
    """
    if canonical_name:
        return canonical_name, True
    if competitor_names or (raw_product_name or "").strip():
        return None, True
    return None, False

def _build_tags_context(db: Session) -> str:
    """Build a human-readable tag context string from the feedback_tags DB table.
    
    Includes tag_id so the LLM outputs integer IDs instead of tag name strings.
    """
    all_tags = db.query(FeedbackTag).filter(FeedbackTag.is_active == True).order_by(FeedbackTag.tag_id).all()

    # Group by group_type (e.g. "PDT GROUP", "USER GROUP", "DEALER GROUP")
    groups: dict[str, list] = {}
    for tag in all_tags:
        group = tag.group_type or "General"
        if group not in groups:
            groups[group] = []
        groups[group].append(tag)

    lines = []
    for group, tags in groups.items():
        lines.append(f"[{group}]:")
        for t in tags:
            cat = f" (Category: {t.category})" if t.category else ""
            desc = f" - {t.description}" if t.description else ""
            sub = f" [Sub-tag guidance: {t.sub_tag_name}]" if t.sub_tag_name else ""
            lines.append(f"  - [tag_id={t.tag_id}] {t.tag_name}{cat}{desc}{sub}")
        lines.append("")

    return "\n".join(lines)


def _process_job(job_id: str, db: Session) -> dict:
    job = batch_repository.get_job(db, job_id)
    if not job:
        logger.warning("Post-processing: job %s not found", job_id)
        return {"error": f"Job {job_id} not found"}

    processed = (
        db.query(ProcessedFile)
        .filter(ProcessedFile.job_id == job_id)
        .with_for_update()
        .first()
    )
    
    if not processed or not processed.translated_text:
        return {"error": f"Job {job_id} has no translated_text - run translation first"}

    # If feedbacks already exist, we consider it completed
    existing_rows = db.query(Feedback).filter(Feedback.job_id == job_id).all()
    if existing_rows:
        batch_repository.update_job_status(db, job_id, status=JobStatus.COMPLETED)
        return {"status": "COMPLETED", "job_id": job_id, "insights_generated": True}

    model_name = settings.GEMINI_MODEL
    try:
        # Update state to insights (bypassing normalisation step completely)
        batch_repository.update_job_status(db, job_id, status=JobStatus.INSIGHTS)

        # ── 1. TWO-PART PROMPT EXECUTION ──────────────────────────────────────
        product_tsv = build_product_tsv(db)
        tags_context = _build_tags_context(db)
        
        insights_array, _tokens = vertex_ai.generate_insights(
            translated_text=processed.translated_text,
            product_catalog_tsv=product_tsv,
            tags_context=tags_context,
            model_name=model_name
        )

        # Pre-load active master products for validation
        all_products = db.query(Product).filter(Product.is_active == True).all()
        raw_product_names = [item.get("product_name") for item in insights_array]
        # Hard validation: Pidilite product_name must resolve to master catalog.
        # Competitor names never stay in product_name (even for competition insights).
        enforce_master_product_names(insights_array, all_products)

        # ── 2. SAVE RAW JSON AUDIT TRAIL ──────────────────────────────────────
        # Persist validated insights (strip internal keys)
        for item in insights_array:
            item.pop("_resolved_product_id", None)
            item.pop("_product_validation_error", None)
        processed.insights_raw_json = insights_array
        db.add(processed)

        # ── 3. DB INGESTION (MANY-TO-MANY TAGS & COMPETITORS) ─────────────
        saved_count = 0
        skipped_pdt = 0
        skipped_competition = 0
        skipped_dup = 0
        seen_keys = {
            _feedback_dedupe_key(row.product_name, row.group_type, row.verbatim_quote, row.ai_summary)
            for row in existing_rows
        }
        for idx, feedback_data in enumerate(insights_array):

            llm_product_name = raw_product_names[idx] if idx < len(raw_product_names) else feedback_data.get("product_name")
            canonical_name, resolved_product_id = resolve_product_from_master(
                llm_product_name, all_products
            )
            group_type = vertex_ai.normalize_group_type(
                feedback_data.get("group_type")
            )
            competitors = _competitor_names(feedback_data)
            is_competition = _is_competition_insight(db, feedback_data)

            display_name = canonical_name
            product_id = resolved_product_id

            if is_competition:
                display_name, keep = _competition_product_name(
                    canonical_name, competitors, llm_product_name
                )
                if not keep:
                    skipped_competition += 1
                    logger.warning(
                        "Job %s: skipping competition insight with no Pidilite or competitor product name (raw=%r)",
                        job_id,
                        llm_product_name,
                    )
                    continue
                product_id = resolved_product_id if canonical_name else None
                raw_extra = (llm_product_name or "").strip()
                if not canonical_name and raw_extra:
                    if raw_extra not in competitors:
                        competitors.append(raw_extra)
            elif group_type == "PDT GROUP" and not canonical_name:
                skipped_pdt += 1
                logger.warning(
                    "Job %s: skipping PDT insight without master product (raw=%r)",
                    job_id,
                    llm_product_name,
                )
                continue

            if llm_product_name and not canonical_name and not is_competition:
                logger.warning(
                    "Job %s: dropping non-master product_name=%r (group=%s)",
                    job_id,
                    llm_product_name,
                    group_type,
                )

            quote = feedback_data.get("verbatim_quote")
            summary = feedback_data.get("summary", "")
            dedupe_key = _feedback_dedupe_key(display_name, group_type, quote, summary)
            if dedupe_key in seen_keys:
                skipped_dup += 1
                logger.info(
                    "Job %s: skipping duplicate insight product=%r summary=%r",
                    job_id,
                    display_name,
                    (summary or "")[:80],
                )
                continue
            seen_keys.add(dedupe_key)

            fb = Feedback(
                job_id=job_id,
                product_name=display_name,
                product_id=product_id,
                group_type=group_type,
                category_type=feedback_data.get("category_type"),
                verbatim_quote=quote,
                ai_summary=summary,
                created_at=datetime.now(timezone.utc),
            )
            db.add(fb)
            saved_count += 1
            
            # 3a. Handle Many-to-Many Tags via tag_id (integers from taxonomy)
            #     Look up existing FeedbackTag rows by tag_id — never create new ones.
            raw_tag_ids = feedback_data.get("tag_ids", [])
            
            for tid in raw_tag_ids:
                db_tag = db.query(FeedbackTag).filter(FeedbackTag.tag_id == tid).first()
                if not db_tag:
                    logger.warning("Job %s: LLM output unknown tag_id=%s, skipping", job_id, tid)
                    continue
                
                # Prevent duplicate link rows on the same feedback
                if db_tag not in fb.tags:
                    fb.tags.append(db_tag)

            # 3b. Extract Competitors for Cross-Competition Analysis
            for comp_name in competitors:
                fc = FeedbackCompetitor(competitor_name=comp_name)
                fb.competitors.append(fc)

        if saved_count == 0:
            if not insights_array:
                processed.empty_reason = "No actionable insights extracted from transcript."
            elif skipped_competition and not skipped_pdt:
                processed.empty_reason = (
                    f"LLM returned {len(insights_array)} insight(s) but none were saved "
                    "(competition insights require a Pidilite or competitor product name)."
                )
            elif skipped_pdt:
                processed.empty_reason = (
                    f"LLM returned {len(insights_array)} insight(s) but none were saved "
                    "(PDT insights require a master catalog product)."
                )
            elif skipped_dup:
                processed.empty_reason = (
                    f"LLM returned {len(insights_array)} insight(s) but all were duplicates."
                )
            else:
                processed.empty_reason = (
                    f"LLM returned {len(insights_array)} insight(s) but none were saved."
                )
            db.add(processed)
        else:
            processed.empty_reason = None
            db.add(processed)

        db.commit()
        
        batch_repository.update_job_status(
            db, job_id,
            status=JobStatus.COMPLETED,
            gcs_stt_output_uri=processed.gcs_transcript_uri,
        )
        logger.info(
            "Job %s: insights complete -> COMPLETED (saved=%d, skipped_dup=%d, skipped_competition=%d, empty_reason=%s)",
            job_id,
            saved_count,
            skipped_dup,
            skipped_competition,
            processed.empty_reason,
        )
        return {
            "status": "COMPLETED",
            "job_id": job_id,
            "insights_generated": saved_count > 0,
        }

    except Exception as exc:
        db.rollback()
        logger.exception("Job %s: post-processing failed: %s", job_id, exc)
        batch_repository.update_job_status(
            db, job_id,
            status=JobStatus.ERROR,
            error_message=f"[pipeline:post-processing] {exc}",
            increment_retry=True,
        )
        return {"error": str(exc), "job_id": job_id, "insights_generated": False}


@router.post("/post-processing", summary="Generate insights", status_code=status.HTTP_200_OK)
def normalize_and_generate_insights(
    payload: PostProcessRequest,
    db: Session = Depends(get_db),
):
    job = batch_repository.get_job(db, payload.job_id)
    if not job:
        return make_response(
            success=True,
            message=f"Job {payload.job_id} not found, skipping.",
            data=NormalizeInsightsResponseData(
                job_id=payload.job_id,
                status="NOT_FOUND",
                insights_generated=False,
            ).model_dump(),
        )

    if job.status == JobStatus.COMPLETED:
        has_feedback = (
            db.query(Feedback).filter(Feedback.job_id == payload.job_id).first() is not None
        )
        return make_response(
            success=True,
            message="Job already completed",
            data=NormalizeInsightsResponseData(
                job_id=payload.job_id,
                status=JobStatus.COMPLETED.value,
                insights_generated=has_feedback,
            ).model_dump(),
        )

    if job.status not in _POST_PROCESS_ALLOWED:
        return make_response(
            success=True,
            message=f"Job {payload.job_id} is in status {job.status.value}, skipping.",
            data=NormalizeInsightsResponseData(
                job_id=payload.job_id,
                status=job.status.value,
                insights_generated=False,
            ).model_dump(),
        )

    result = _process_job(payload.job_id, db)

    if "error" in result:
        return make_response(
            success=False,
            message="Insights generation failed",
            data=NormalizeInsightsResponseData(
                job_id=payload.job_id,
                status=JobStatus.ERROR.value,
                insights_generated=False,
            ).model_dump(),
            error=result["error"],
        )

    return make_response(
        success=True,
        message="Insights generation completed",
        data=NormalizeInsightsResponseData(
            job_id=payload.job_id,
            status=JobStatus.COMPLETED.value,
            insights_generated=result.get("insights_generated", True),
        ).model_dump(),
    )