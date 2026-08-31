"""
Full Pipeline Evaluator — Translation → Insight Generation for all 5 transcripts.

Runs each Hindi transcript through:
  1. translate_transcript() → English text
  2. generate_insights() → JSON array (using Two-Part Prompt)

Saves results to tests/evaluation_results/ for review.

Usage:
    source .venv/bin/activate
    python tests/test_evaluate_pipeline.py
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.config import settings
from services.shared.vertex_ai import translate_transcript, generate_insights
from services.api.routers.normalize import _build_tags_context

TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"
RESULTS_DIR = Path(__file__).parent / "evaluation_results"

from db.session import SessionLocal
from sqlalchemy import func
from db.models import Job, ProcessedFile, Feedback, FeedbackTag, Batch, FileDetails
from core.enums import JobStatus, BatchStatus
from services.shared.product_catalog import build_product_tsv

# We defer building the TSV until after arguments are parsed
PRODUCT_CATALOG_TSV = ""

VALID_GROUPS = {"PDT GROUP", "USER GROUP", "DEALER GROUP", "Product", "User", "Dealer"}


def _print_header(title: str):
    print(f"\n{'═' * 70}")
    print(f"  {title}")
    print(f"{'═' * 70}")


def _validate_insights(insights: list) -> dict:
    """Quick validation of the generated insights."""
    issues = []
    for i, fb in enumerate(insights):
        if fb.get("group_type") not in VALID_GROUPS:
            issues.append(f"  Item {i+1}: Invalid group_type='{fb.get('group_type')}'")
        
        tags = fb.get("tag_ids") or []
        if not tags:
            issues.append(f"  Item {i+1}: Empty tag_ids array")
        elif len(tags) != len(set(tags)):
            issues.append(f"  Item {i+1}: Duplicate values in tag_ids array")
            
        comps = fb.get("competitors_mentioned") or []
        if len(comps) != len(set(comps)):
            issues.append(f"  Item {i+1}: Duplicate values in competitors array")
            
        if not fb.get("verbatim_quote"):
            issues.append(f"  Item {i+1}: Missing verbatim_quote")
        if not fb.get("summary"):
            issues.append(f"  Item {i+1}: Missing summary")
    return {
        "total_items": len(insights),
        "group_counts": {
            g: sum(1 for fb in insights if fb.get("group_type") == g) for g in VALID_GROUPS
        },
        "issues": issues,
        "all_tag_ids": list(set([tag for fb in insights for tag in fb.get("tag_ids", [])])),
        "all_competitors": list(set([c for fb in insights for c in fb.get("competitors_mentioned", []) if c])),
    }


def process_transcript(filepath: Path, index: int) -> dict:
    """Process a single transcript through translate → insights."""
    _print_header(f"TRANSCRIPT {index}: {filepath.name}")

    hindi_text = filepath.read_text(encoding="utf-8").strip()
    print(f"📄 Input: {len(hindi_text)} chars (Hindi)")

    # ── Step 1: Translation ──
    print("\n⏳ Step 1: Translating Hindi → English...")
    t_start = time.time()
    try:
        translated, t_tokens = translate_transcript(hindi_text, product_catalog_tsv=PRODUCT_CATALOG_TSV)
    except Exception as exc:
        print(f"❌ Translation FAILED: {exc}")
        return {"error": f"Translation failed: {exc}", "file": filepath.name}
    t_elapsed = time.time() - t_start
    print(f"✅ Translated in {t_elapsed:.2f}s | Tokens: {t_tokens['total']} (In: {t_tokens['input']}, Out: {t_tokens['output']})")
    print(f"   Preview: \"{translated[:200]}...\"")

    # ── Step 2: Insight Generation ──
    print(f"\n⏳ Step 2: Generating insights...")
    i_start = time.time()
    try:
        db = SessionLocal()
        tags_context = _build_tags_context(db)
        db.close()
        
        insights, i_tokens = generate_insights(
            translated_text=translated,
            product_catalog_tsv=PRODUCT_CATALOG_TSV,
            tags_context=tags_context,
        )
    except Exception as exc:
        print(f"❌ Insight generation FAILED: {exc}")
        return {
            "error": f"Insights failed: {exc}",
            "file": filepath.name,
            "translated_text": translated,
            "total_tokens": t_tokens,
        }
    i_elapsed = time.time() - i_start
    print(f"✅ Insights generated in {i_elapsed:.2f}s | Tokens: {i_tokens['total']} (In: {i_tokens['input']}, Out: {i_tokens['output']})")

    total_input_tokens = t_tokens['input'] + i_tokens['input']
    total_output_tokens = t_tokens['output'] + i_tokens['output']
    total_tokens = t_tokens['total'] + i_tokens['total']
    t_elapsed += i_elapsed

    # ── Validation ──
    validation = _validate_insights(insights)
    print(f"\n📊 Results: {validation['total_items']} feedback items extracted")
    print(f"   Groups: {validation['group_counts']}")
    if validation['all_competitors']:
        print(f"   🏷️  Competitors: {validation['all_competitors']}")
    if validation.get('all_tag_ids'):
        print(f"   🏷️  Tag IDs ({len(validation['all_tag_ids'])}): {validation['all_tag_ids'][:5]}{'...' if len(validation['all_tag_ids']) > 5 else ''}")
    if validation['issues']:
        print(f"   ⚠️  Issues:")
        for issue in validation['issues']:
            print(f"      {issue}")
    else:
        print(f"   ✅ No validation issues")

    return {
        "file": filepath.name,
        "hindi_chars": len(hindi_text),
        "translated_text": translated,
        "translation_tokens": t_tokens,
        "insights_tokens": i_tokens,
        "total_tokens": {"input": total_input_tokens, "output": total_output_tokens, "total": total_tokens},
        "total_time_s": round(t_elapsed, 2),
        "insights": insights,
        "validation": validation,
        "raw_hindi": hindi_text,
    }


def _save_to_db(db, all_results: list):
    """Saves all evaluation results to the Postgres database."""
    print(f"\n⏳ Saving {len(all_results)} transcripts to database...")
    
    # Create a mock batch
    import random
    batch = Batch(
        batch_number=random.randint(10000, 99999),
        batch_size=len(all_results),
        status=BatchStatus.COMPLETED
    )
    db.add(batch)
    db.flush()

    saved_count = 0
    for result in all_results:
        if "error" in result:
            continue
            
        # 1. Create Mock Job
        job = Job(
            batch_id=batch.id,
            gcs_input_uri=f"gs://test-eval/{result['file']}",
            status=JobStatus.COMPLETED,
            stt_operation_name="TEST_EVAL"
        )
        db.add(job)
        db.flush()
        
        # 2. Create FileDetails
        fd = FileDetails(
            job_id=job.id,
            file_name=result['file'],
            language_code="hi-IN"
        )
        db.add(fd)

        # 3. Create ProcessedFile
        processed = ProcessedFile(
            job_id=job.id,
            raw_transcript_text=result.get("raw_hindi", ""),
            translated_text=result.get("translated_text", ""),
            insights_raw_json=result.get("insights", [])
        )
        db.add(processed)
        
        # 4. Ingest Feedback & Tags (same as normalize.py)
        # Pre-build product name → UUID lookup
        from db.models import Product
        all_products = db.query(Product).filter(Product.is_active == True).all()
        product_name_to_id = {p.product_name.lower(): str(p.id) for p in all_products}
        
        for feedback_data in result.get("insights", []):
            verbatim = feedback_data.get("verbatim_quote", "")

            # Resolve product_name → product_id
            llm_product_name = feedback_data.get("product_name")
            resolved_product_id = None
            if llm_product_name:
                resolved_product_id = product_name_to_id.get(llm_product_name.strip().lower())

            fb = Feedback(
                job_id=job.id,
                product_name=llm_product_name,
                product_id=resolved_product_id,
                group_type=feedback_data.get("group_type", "Unknown"),
                category_type=feedback_data.get("category_type"),
                verbatim_quote=verbatim,
                ai_summary=feedback_data.get("summary", ""),
            )
            db.add(fb)
            
            # Tags
            raw_tag_ids = feedback_data.get("tag_ids", [])
            from services.api.routers.normalize import _load_taxonomy
            taxonomy = _load_taxonomy()
            tag_id_to_entry = {e["tag_id"]: e for e in taxonomy if "tag_id" in e}
            
            for tid in raw_tag_ids:
                tax_entry = tag_id_to_entry.get(tid)
                if not tax_entry:
                    continue
                tag_name = tax_entry["feedback_tag"]
                db_tag = db.query(FeedbackTag).filter(func.lower(FeedbackTag.tag_name) == tag_name.lower()).first()
                if not db_tag:
                    db_tag = FeedbackTag(tag_name=tag_name)
                    db.add(db_tag)
                    db.flush()
                fb.tags.append(db_tag)
                
            # Competitors
            from db.models import FeedbackCompetitor
            for comp_name in feedback_data.get("competitors_mentioned", []):
                if comp_name and comp_name.strip():
                    fc = FeedbackCompetitor(competitor_name=comp_name.strip())
                    fb.competitors.append(fc)
            
        saved_count += 1

    db.commit()
    print(f"✅ Successfully saved {saved_count} transcripts to the database! (Batch ID: {batch.id})")


def main():
    parser = argparse.ArgumentParser(description="Evaluate PIDILITE AI Pipeline.")
    parser.add_argument("--save-to-db", action="store_true", help="Save the evaluation outputs directly to the Postgres database.")
    parser.add_argument("--no-description", action="store_true", help="Exclude descriptions from the product catalog TSV sent to Gemini.")
    args = parser.parse_args()
    
    global PRODUCT_CATALOG_TSV
    try:
        with SessionLocal() as db:
            PRODUCT_CATALOG_TSV = build_product_tsv(db, include_description=not args.no_description)
    except Exception as e:
        print(f"Failed to connect to DB for product catalog. Is Docker up? {e}")
        PRODUCT_CATALOG_TSV = ""

    _print_header(f"PIDILITE AI PIPELINE — FULL EVALUATION {'(No Descriptions)' if args.no_description else '(With Descriptions)'}")
    print(f"🤖 Model: {settings.GEMINI_MODEL}")
    print(f"🌍 Project: {settings.GCP_PROJECT_ID}")
    print(f"📍 Location: {settings.GCP_LOCATION}")

    # ── Preflight ──
    if not settings.GCP_PROJECT_ID or settings.GCP_PROJECT_ID == "my-project-id":
        print("❌ ERROR: Set GCP_PROJECT_ID in .env first")
        sys.exit(1)

    # ── Discover transcripts ──
    transcript_files = sorted(TRANSCRIPTS_DIR.glob("transcript_*.txt"))
    if not transcript_files:
        print(f"❌ No transcript files found in {TRANSCRIPTS_DIR}")
        sys.exit(1)
    print(f"📂 Found {len(transcript_files)} transcripts in {TRANSCRIPTS_DIR}")

    # ── Process each ──
    RESULTS_DIR.mkdir(exist_ok=True)
    all_results = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_pipeline_tokens = 0

    for i, fpath in enumerate(transcript_files, 1):
        result = process_transcript(fpath, i)
        all_results.append(result)
        if "total_tokens" in result and isinstance(result["total_tokens"], dict):
            total_input_tokens += result["total_tokens"]["input"]
            total_output_tokens += result["total_tokens"]["output"]
            total_pipeline_tokens += result["total_tokens"]["total"]

        # Save individual result
        out_file = RESULTS_DIR / f"result_{i}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False, default=str)

    # ── Summary Report ──
    _print_header("EVALUATION SUMMARY")

    total_items = sum(r.get("validation", {}).get("total_items", 0) for r in all_results if "validation" in r)
    total_issues = sum(len(r.get("validation", {}).get("issues", [])) for r in all_results if "validation" in r)
    errors = [r for r in all_results if "error" in r]

    print(f"📊 Transcripts processed:  {len(all_results)}")
    print(f"📊 Total feedback items:   {total_items}")
    print(f"📊 Total validation issues: {total_issues}")
    print(f"📊 Errors:                  {len(errors)}")
    print(f"💰 Total pipeline tokens:   {total_pipeline_tokens} (In: {total_input_tokens}, Out: {total_output_tokens})")

    # ── Cost estimate ──
    # Gemini 2.5 Flash Pricing (Google Cloud):
    # Input: $0.30 / 1M tokens
    # Output: $2.50 / 1M tokens (Thinking tokens are billed at Output rate)
    thinking_tokens = total_pipeline_tokens - (total_input_tokens + total_output_tokens)
    cost_input = (total_input_tokens / 1_000_000) * 0.30
    cost_output = ((total_output_tokens + thinking_tokens) / 1_000_000) * 2.50
    estimated_cost = cost_input + cost_output
    
    print(f"💰 Estimated cost (5 transcripts): ~${estimated_cost:.4f}")
    print(f"   - Input:    ${cost_input:.4f} ({total_input_tokens} tokens)")
    print(f"   - Output:   ${cost_output:.4f} ({total_output_tokens} output + {thinking_tokens} thinking tokens)")

    # Save full report
    report_file = RESULTS_DIR / "full_report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump({
            "model": settings.GEMINI_MODEL,
            "project": settings.GCP_PROJECT_ID,
            "total_transcripts": len(all_results),
            "total_feedback_items": total_items,
            "total_tokens": {
                "input": total_input_tokens,
                "output": total_output_tokens,
                "total": total_pipeline_tokens
            },
            "estimated_cost_usd": round(estimated_cost, 6),
            "results": all_results,
        }, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n📁 Results saved to: {RESULTS_DIR}/")
    print(f"   - Individual: result_1.json ... result_{len(all_results)}.json")
    print(f"   - Full report: full_report.json")
    
    if args.save_to_db:
        try:
            with SessionLocal() as db:
                _save_to_db(db, all_results)
        except Exception as e:
            print(f"\n❌ Failed to save to database: {e}")
            
    print(f"\n🏁 Evaluation complete!")


if __name__ == "__main__":
    main()
