"""
Database Seeder for AI Feedback Taxonomy.
Populates the products, feedback_categories, and feedback_tags tables.
"""
import sys
import os
import logging

# Add the root directory to the python path so it can find db/
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.session import SessionLocal
from db.models import Product, FeedbackCategory, FeedbackTag

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── 1. Master Product List ────────────────────────────────────────────────────
PRODUCTS = [
    "Fevicol X-Per", "Fevicol Multilock", "Fevicol ProGel", "Fevicol MARINE", 
    "Fevicol PROBOND", "Fevicol SPEEDX", "Fevicol SH", "Fevicol SB", 
    "Fevicol EZEESPRAY", "Fevicol PLASTILOK", "Fevicol RELAM", "Fevicol HEATX", 
    "Fevicol SR 998", "Fevicol GRIPPO", "Fevicol BULBOND", "Fevicol HI-PER STAR", 
    "Not Applicable"
]

# ── 2. Master Category & Tag Taxonomy ─────────────────────────────────────────
TAXONOMY = {
    "Competition-related": [
        "Competition product", 
        "Competition - Price / scheme / credit days", 
        "Competition engagement"
    ],
    "Systems": [
        "FCC App", 
        "M-Power"
    ],
    "Product": [
        "New product idea", 
        "New packaging idea", 
        "New Substrate / Application Trend", 
        "Product quality / packaging complaints", 
        "Existing Product improvements", 
        "Packaging related improvements", 
        "Product Application Awareness"
    ],
    "Group A User Engagement": [
        "FCC Redemption Gifts", 
        "Site visits", 
        "Sponsorship of events", 
        "User LSP", 
        "User meets", 
        "FCC Clubs", 
        "User scheme", 
        "User trips", 
        "Product content (videos etc)"
    ]
}

def seed_database():
    db = SessionLocal()
    try:
        logger.info("Starting Taxonomy Seed...")

        # ── Seed Products ──
        logger.info("Seeding Products...")
        for p_name in PRODUCTS:
            exists = db.query(Product).filter(Product.product_name == p_name).first()
            if not exists:
                db.add(Product(product_name=p_name))
        
        # Flush to get IDs if needed
        db.flush()

        # ── Seed Categories and Tags ──
        logger.info("Seeding Categories and Tags...")
        for cat_name, tags in TAXONOMY.items():
            # Create or fetch the Category
            cat = db.query(FeedbackCategory).filter(FeedbackCategory.category_name == cat_name).first()
            if not cat:
                cat = FeedbackCategory(category_name=cat_name)
                db.add(cat)
                db.flush() # Commits to memory to generate the UUID for the foreign key

            # Create the Tags under this Category
            for tag_name in tags:
                tag_exists = db.query(FeedbackTag).filter(
                    FeedbackTag.tag_name == tag_name, 
                    FeedbackTag.category_id == cat.id
                ).first()
                
                if not tag_exists:
                    db.add(FeedbackTag(tag_name=tag_name, category_id=cat.id))

        # Commit everything to the physical database
        db.commit()
        logger.info("✅ Taxonomy successfully seeded into the database!")

    except Exception as e:
        db.rollback()
        logger.error(f"❌ Failed to seed database: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed_database()