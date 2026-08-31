"""
scripts/seed.py
───────────────
Run once after `alembic upgrade head` to bootstrap:
  - Default admin user
  - App config defaults (batch_size, gemini_prompt_template)
  - Seed Pidilite keyword dictionary entries

Usage:
    poetry run python scripts/seed.py
"""
import sys
import os

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))

from core.permissions import Permissions
from core.security import hash_password
from db.models import User, AppConfig, KeywordDictionary
from db.session import SessionLocal, Base, engine
from datetime import datetime, timezone

Base.metadata.create_all(bind=engine)
db = SessionLocal()


# ── Admin user ────────────────────────────────────────────────────────────────
# Note: We query by email now instead of username!
if not db.query(User).filter(User.email == "admin@pidilite.com").first():
    admin = User(
        username="admin",
        email="admin@pidilite.com",                   # <--- Added this required field!
        # Swapped to the password we tested
        password_hash=hash_password("password123"),
        full_name="Pipeline Admin",
        # <--- Set to super_admin to test your RBAC!
        role="super_admin",
        is_active=True,
        allowed_resources=Permissions.list_all()
    )
    db.add(admin)
    print("✅  Admin user created  (email: admin@pidilite.com / password: password123)")
else:
    print("ℹ️  Admin user already exists, skipping.")


# ── App config defaults ───────────────────────────────────────────────────────
defaults = [
    ("batch_size",              {"value": 10},
     "Number of jobs per STT batch"),
    ("gemini_prompt_template",  {"template": (
        "You are an expert sales analyst for Pidilite Industries. "
        "Analyze the following sales call transcript and return structured JSON insights."
    )},                                            "Gemini base prompt"),
    ("stt_language_code",       {"value": "en-IN"}, "Default STT language"),
    ("max_retry_count",         {"value": 2},
     "Max retries before FAILED"),
]
for key, value, description in defaults:
    if not db.query(AppConfig).filter(AppConfig.key == key).first():
        db.add(AppConfig(key=key, value=value, description=description))
        print(f"✅  Config key '{key}' seeded.")


# ── Keyword dictionary seed ───────────────────────────────────────────────────
# Helper to parse the ISO timestamps from the JSON to Python datetime objects
def parse_dt(dt_str: str) -> datetime:
    return datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


keywords = [
    {
        "canonical_id":   "PID-PRD-000123",
        "canonical_term": "Fevicol SH",
        "category":       "product",
        "language":       ["en", "hi", "mr"],
        "aliases":        ["Fevicol SHH", "Fevicol S H", "fevicol shh", "fevicol esh"],
        "priority":       90,
        "effective_from": parse_dt("2026-02-01T00:00:00Z"),
        "owner":          "brand-team@pidilite.com",
        "version":        7,
        "updated_at":     parse_dt("2026-02-04T06:30:00Z"),
    },
    {
        "canonical_id":   "PID-PRD-000124",
        "canonical_term": "Fevikwik",
        "category":       "product",
        "language":       ["en", "hi", "mr"],
        "aliases":        ["Fevi Kwik", "fevi kwik", "fevikwick"],
        "priority":       80,
        "effective_from": parse_dt("2026-02-01T00:00:00Z"),
        "owner":          "brand-team@pidilite.com",
        "version":        1,
        "updated_at":     parse_dt("2026-02-04T06:30:00Z"),
    },
    {
        "canonical_id":   "PID-PRD-000125",
        "canonical_term": "Fevistik",
        "category":       "product",
        "language":       ["en", "hi", "mr"],
        "aliases":        ["Fevi stick", "Fevi Stick", "fevistick"],
        "priority":       70,
        "effective_from": parse_dt("2026-02-01T00:00:00Z"),
        "owner":          "brand-team@pidilite.com",
        "version":        1,
        "updated_at":     parse_dt("2026-02-04T06:30:00Z"),
    },
    {
        "canonical_id":   "PID-BRD-000001",
        "canonical_term": "Pidilite Industries",
        "category":       "brand",
        "language":       ["en", "hi", "mr"],
        "aliases":        ["Pidilite Ind", "Pidilite ind.", "PIDILITE"],
        "priority":       50,
        "effective_from": parse_dt("2026-02-01T00:00:00Z"),
        "owner":          "brand-team@pidilite.com",
        "version":        1,
        "updated_at":     parse_dt("2026-02-04T06:30:00Z"),
    },
]

for kw_data in keywords:
    if not db.query(KeywordDictionary).filter(
        KeywordDictionary.canonical_id == kw_data["canonical_id"]
    ).first():
        kw = KeywordDictionary(**kw_data)
        db.add(kw)
        print(f"✅  Keyword '{kw_data['canonical_id']}' seeded.")

db.commit()
db.close()
print("\n🎉  Seed complete.")
