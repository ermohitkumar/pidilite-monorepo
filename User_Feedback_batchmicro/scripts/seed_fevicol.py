import sys
import os
import json
from sqlalchemy.orm import Session
from sqlalchemy import text

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.session import SessionLocal
from db.models import Product, Feedback
from services.shared.vertex_ai import GenerativeModel
from core.config import settings
import vertexai

TARGET_PRODUCTS = [
    "Fevicol X-Per",
    "Fevicol Multilock",
    "Fevicol ProGel",
    "Fevicol MARINE",
    "Fevicol PROBOND",
    "Fevicol SPEEDX",
    "Fevicol SH",
    "Fevicol SB",
    "Fevicol EZEESPRAY",
    "Fevicol PLASTILOK",
    "Fevicol RELAM",
    "Fevicol XPRES",
    "Fevicol HEATX",
    "Fevicol SR 998",
    "Fevicol GRIPPO",
    "Fevicol FALCOBOND PLUS",
    "Fevicol PROBOND EDGELOK",
    "Fevicol BULBOND",
    "Fevicol BULBOND XTRA",
    "Fevicol MASTERLOK",
    "Fevicol MASTERLOK XTRA",
    "Fevicol HI-PER",
    "Fevicol HI-PER STAR",
    "Fevikwik 463",
    "Fevicol Nail Free",
    "Fevicol Terminator",
]

def generate_short_code(product_name: str) -> str:
    """Generates a short code for the product."""
    clean = product_name.replace("Fevicol", "").strip().split()
    if not clean:
        return "F-SH"
    
    parts = [w[0].upper() for w in clean if w]
    return f"F-{''.join(parts[:3])}"

def seed():
    print("Initializing Vertex AI...")
    vertexai.init(project=settings.GCP_PROJECT_ID, location=settings.GCP_LOCATION)
    model = GenerativeModel(settings.GEMINI_MODEL)
    
    db: Session = SessionLocal()
    
    print("🧹 Cleaning up old product data...")
    # Because feedbacks relies on products, we update feedbacks to null first
    db.execute(text("UPDATE feedbacks SET product_id = NULL"))
    db.query(Product).delete()
    db.commit()
    
    print(f"📦 Populating {len(TARGET_PRODUCTS)} Fevicol products...")
    
    # Let's ask Gemini to give us a JSON dict of descriptions for all products at once
    prompt = f"""
    You are an expert on Pidilite Industries products.
    Please provide a concise, accurate 2-sentence description for each of the following Fevicol products.
    Return ONLY a valid JSON object where the keys are the exact product names below and the values are the descriptions.
    
    Products:
    {json.dumps(TARGET_PRODUCTS, indent=2)}
    """
    
    print("🤖 Asking Gemini for product descriptions...")
    try:
        response = model.generate_content(prompt)
        text_resp = response.text.strip()
        if text_resp.startswith("```json"):
            text_resp = text_resp[7:]
        if text_resp.endswith("```"):
            text_resp = text_resp[:-3]
        
        descriptions_map = json.loads(text_resp.strip())
        print("✅ Received descriptions from Gemini!")
    except Exception as e:
        print(f"⚠️ Failed to get descriptions from Gemini: {e}")
        descriptions_map = {}
        
    for prod_name in TARGET_PRODUCTS:
        short_code = generate_short_code(prod_name)
        desc = descriptions_map.get(prod_name, "Adhesive product by Pidilite.")
        
        db_prod = Product(
            product_name=prod_name,
            short_code=short_code,
            description=desc
        )
        db.add(db_prod)
        print(f"  + Added: {prod_name} | Code: {short_code} | Desc: {desc[:40]}...")
        
    db.commit()
    print("🎉 Done! Database populated with curated Fevicol catalog.")

if __name__ == "__main__":
    seed()
