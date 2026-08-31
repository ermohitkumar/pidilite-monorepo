import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.session import SessionLocal
from db.models import Job, FileDetails, ProcessedFile, Feedback, FeedbackTag, FeedbackCompetitor
from core.enums import JobStatus

def seed_eval_data():
    db = SessionLocal()
    
    # Map integer IDs from tests back to product names
    int_to_name = {
        1001: "Fevicol SH",
        1002: "Fevikwik",
        1003: "Dr. Fixit LW+",
        1004: "Roff Non-Skid Adhesive",
        1005: "Fevicol Marine"
    }
    
    # Pre-fetch product UUIDs
    from db.models import Product
    products = db.query(Product).all()
    name_to_uuid = {p.product_name: p.id for p in products}
    
    results_dir = Path("tests/evaluation_results")
    
    for i in range(1, 6):
        file_path = results_dir / f"result_{i}.json"
        if not file_path.exists():
            continue
            
        print(f"Ingesting {file_path.name}...")
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # 1. Create a dummy Job
        job = Job(status=JobStatus.COMPLETED, gcs_input_uri=f"gs://bucket/audio_{i}.wav")
        db.add(job)
        db.flush()
        
        # 2. Create FileDetails
        fd = FileDetails(
            job_id=job.id,
            file_name=f"transcript_{i}.txt",
            state="Maharashtra",
            division="West",
            town_city="Mumbai",
            user_type="Carpenter"
        )
        db.add(fd)
        
        # 3. Create ProcessedFile with the raw LLM JSON
        pf = ProcessedFile(
            job_id=job.id,
            translated_text=data.get("translated_text", ""),
            insights_raw_json=data.get("insights", [])
        )
        db.add(pf)
        
        # 4. Create Feedbacks
        insights = data.get("insights", [])
        for fb_data in insights:
            si = fb_data.get("start_index")
            ei = fb_data.get("end_index")
            translated_text = data.get("translated_text", "")
            
            if si is not None and ei is not None and translated_text:
                verbatim = translated_text[si : ei + 1]
            else:
                verbatim = fb_data.get("summary", "")
                
            raw_pid = fb_data.get("product_id")
            actual_pid = None
            if raw_pid in int_to_name:
                p_name = int_to_name[raw_pid]
                actual_pid = name_to_uuid.get(p_name)
                
            fb = Feedback(
                job_id=job.id,
                product_id=actual_pid,
                group_type=fb_data.get("group_type", "Unknown"),
                category_type=fb_data.get("category_type"),
                verbatim_quote=verbatim,
                ai_summary=fb_data.get("summary", ""),
                start_index=si,
                end_index=ei,
            )
            db.add(fb)
            db.flush()
            
            # Tags
            for tag_string in fb_data.get("tags", []):
                db_tag = db.query(FeedbackTag).filter(FeedbackTag.tag_name == tag_string).first()
                if not db_tag:
                    db_tag = FeedbackTag(tag_name=tag_string)
                    db.add(db_tag)
                    db.flush()
                fb.tags.append(db_tag)
                
            # Competitors
            for comp_name in fb_data.get("competitors_mentioned", []):
                if comp_name:
                    fc = FeedbackCompetitor(competitor_name=comp_name.strip())
                    fb.competitors.append(fc)
                    
    db.commit()
    print("✅ Successfully ingested all 5 evaluation results into the database!")

if __name__ == "__main__":
    seed_eval_data()
