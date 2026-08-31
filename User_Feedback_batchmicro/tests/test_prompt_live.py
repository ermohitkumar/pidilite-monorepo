"""
Live Prompt Tester — Calls Gemini with the Two-Part Prompt Architecture.

Requires:
  - GCP_PROJECT_ID and GOOGLE_APPLICATION_CREDENTIALS set in .env
  - A working internet connection to Vertex AI

Usage:
    source .venv/bin/activate
    python tests/test_prompt_live.py
    python tests/test_prompt_live.py --transcript "your transcript text here"
    python tests/test_prompt_live.py --file path/to/transcript.txt
"""
import argparse
import json
import os
import sys
import time

# ── Ensure project root is on sys.path ──
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.config import settings
from services.shared.vertex_ai import generate_insights

# ── Sample Sales Call Transcript (used when no --transcript or --file is given)
SAMPLE_TRANSCRIPT = """
Speaker 1: Good morning sir, how is business going?
Speaker 2: Business is okay. But I am having problems with Fevicol SH. The packets are leaking from the sides. 
My customers are complaining about the packaging quality. Earlier the quality was much better.
Speaker 1: I understand sir. We will raise this with the product team. Anything else?
Speaker 2: Yes. The competition brand SupaStik is giving 45 days credit to dealers but we only get 30 days.
Many dealers in my area are switching because of this. Also their product price is 15% lower.
Speaker 1: We will look into the credit terms. What about Roff tiles adhesive?
Speaker 2: Roff is doing well. Contractors are happy with the non-skid adhesive performance. 
But we need more FCC app training sessions for the contractors. Many of them don't know how to redeem points.
Speaker 1: Noted sir. We will arrange an FCC Meet next month. Thank you.
""".strip()

# ── Sample Product Catalog (mirrors seed.py) ──
SAMPLE_PRODUCT_TSV = """FEV-SH-001|Fevicol SH|Adhesives
FEV-KWK-001|Fevikwik|Adhesives
DRF-LW-001|Dr. Fixit LW+|Waterproofing
ROF-NSA-001|Roff Non-Skid Adhesive|Tiling
FEV-MAR-001|Fevicol Marine|Adhesives""".strip()


def main():
    parser = argparse.ArgumentParser(description="Test Gemini Two-Part Prompt")
    parser.add_argument("--transcript", type=str, help="Inline transcript text to analyze")
    parser.add_argument("--file", type=str, help="Path to a .txt file containing the transcript")
    parser.add_argument("--product-tsv", type=str, help="Path to a custom product catalog TSV file")
    parser.add_argument("--model", type=str, default=None, help=f"Gemini model override (default: {settings.GEMINI_MODEL})")
    args = parser.parse_args()

    # ── Resolve transcript text ──
    if args.file:
        with open(args.file, "r") as f:
            transcript = f.read().strip()
        print(f"📄 Loaded transcript from: {args.file} ({len(transcript)} chars)")
    elif args.transcript:
        transcript = args.transcript.strip()
        print(f"📝 Using inline transcript ({len(transcript)} chars)")
    else:
        transcript = SAMPLE_TRANSCRIPT
        print(f"🎤 Using built-in sample transcript ({len(transcript)} chars)")

    # ── Resolve product catalog ──
    if args.product_tsv:
        with open(args.product_tsv, "r") as f:
            product_tsv = f.read().strip()
        print(f"📦 Loaded product catalog from: {args.product_tsv}")
    else:
        product_tsv = SAMPLE_PRODUCT_TSV
        print(f"📦 Using built-in sample product catalog ({product_tsv.count(chr(10)) + 1} products)")

    model_name = args.model or settings.GEMINI_MODEL
    print(f"🤖 Model: {model_name}")
    print(f"🌍 GCP Project: {settings.GCP_PROJECT_ID}")
    print(f"📍 GCP Location: {settings.GCP_LOCATION}")
    print("─" * 60)

    # ── Preflight check ──
    if not settings.GCP_PROJECT_ID:
        print("❌ ERROR: GCP_PROJECT_ID is not set in .env")
        sys.exit(1)

    # ── Call Gemini ──
    print("⏳ Sending to Gemini...\n")
    start = time.time()
    try:
        insights_array, tokens_used = generate_insights(
            translated_text=transcript,
            product_catalog_tsv=product_tsv,
            model_name=model_name,
        )
    except Exception as exc:
        print(f"❌ Gemini call failed: {exc}")
        sys.exit(1)
    elapsed = time.time() - start

    # ── Print results ──
    print("─" * 60)
    print(f"✅ Response received in {elapsed:.2f}s | Tokens used: {tokens_used}")
    print(f"📊 Feedback items extracted: {len(insights_array)}")
    print("─" * 60)
    print("\n🔍 RAW JSON RESPONSE:\n")
    print(json.dumps(insights_array, indent=2, ensure_ascii=False))

    # ── Quick validation ──
    print("\n" + "─" * 60)
    print("📋 VALIDATION SUMMARY:")
    valid_groups = {"PDT GROUP", "USER GROUP", "DEALER GROUP", "Product", "User", "Dealer"}
    for i, fb in enumerate(insights_array):
        group = fb.get("group_type", "MISSING")
        tags = fb.get("tags", [])
        si = fb.get("start_index")
        ei = fb.get("end_index")
        product_id = fb.get("product_id")
        competitors = fb.get("competitors_mentioned", [])

        # Derive the verbatim excerpt from the transcript
        if si is not None and ei is not None:
            excerpt = transcript[si : ei + 1][:80]
        else:
            excerpt = fb.get("summary", "")[:80]

        status = "✅" if group in valid_groups else "⚠️"
        print(f"  {status} [{i+1}] group={group}, tags={len(tags)}, "
              f"indices=[{si}:{ei}], "
              f"product_id={'SET' if product_id else 'null'}, "
              f"competitors={competitors or 'none'}")
        print(f"       excerpt: \"{excerpt}...\"")

    print(f"\n🏁 Done. Total feedback items: {len(insights_array)}")


if __name__ == "__main__":
    main()
