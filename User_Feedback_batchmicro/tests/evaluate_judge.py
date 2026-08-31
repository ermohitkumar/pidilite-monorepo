"""
LLM-as-a-Judge Evaluator

Reads pipeline results and uses gemini-2.5-pro to judge the extraction quality,
detecting hallucinations, missing contexts, and overall accuracy.
Generates an HTML report in tests/evaluation_results/judge_report.html
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.config import settings
from services.shared.vertex_ai import evaluate_as_judge

RESULTS_DIR = Path(__file__).parent / "evaluation_results"
TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"

def generate_html_report(evaluations: list):
    """Generates a styled HTML report from the evaluation results."""
    html_out = RESULTS_DIR / "judge_report.html"
    
    avg_score = sum(e["evaluation"]["score"] for e in evaluations) / len(evaluations) if evaluations else 0
    
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LLM Judge Evaluation Report</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {{ font-family: 'Inter', sans-serif; background-color: #f3f4f6; }}
        .glass {{ background: rgba(255, 255, 255, 0.95); backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.2); }}
    </style>
</head>
<body class="p-8">
    <div class="max-w-6xl mx-auto">
        <header class="mb-10 text-center">
            <h1 class="text-4xl font-extrabold text-gray-900 tracking-tight">AI Pipeline Audit Report</h1>
            <p class="text-lg text-gray-600 mt-2">LLM-as-a-Judge Evaluation (Gemini 2.5 Pro)</p>
        </header>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mb-10">
            <div class="glass p-6 rounded-2xl shadow-sm flex items-center justify-between">
                <div>
                    <h3 class="text-gray-500 text-sm font-semibold uppercase tracking-wider">Average Score</h3>
                    <p class="text-5xl font-black text-indigo-600 mt-1">{avg_score:.1f}<span class="text-2xl text-gray-400">/10</span></p>
                </div>
            </div>
            <div class="glass p-6 rounded-2xl shadow-sm flex items-center justify-between">
                <div>
                    <h3 class="text-gray-500 text-sm font-semibold uppercase tracking-wider">Transcripts Audited</h3>
                    <p class="text-5xl font-black text-gray-800 mt-1">{len(evaluations)}</p>
                </div>
            </div>
        </div>

        <h2 class="text-2xl font-bold text-gray-800 mb-6">Detailed Findings</h2>
        <div class="space-y-8">
"""

    for eval_item in evaluations:
        file_name = eval_item["file"]
        score = eval_item["evaluation"]["score"]
        reasoning = eval_item["evaluation"]["reasoning"]
        weakness = eval_item["evaluation"]["weakness"]
        output = eval_item["evaluation"]["output"]
        
        score_color = "text-green-600" if score >= 8 else "text-yellow-600" if score >= 5 else "text-red-600"
        weakness_alert = ""
        if weakness.lower() not in ["none", "none.", "n/a", "no weaknesses found"]:
            weakness_alert = f"""
            <div class="mt-4 p-4 bg-red-50 border-l-4 border-red-500 rounded-r text-red-700 text-sm">
                <strong>🚨 Weakness Detected:</strong> {weakness}
            </div>"""

        html_content += f"""
            <div class="glass p-8 rounded-2xl shadow-sm">
                <div class="flex justify-between items-start mb-4">
                    <h3 class="text-xl font-bold text-gray-900">{file_name}</h3>
                    <span class="text-3xl font-black {score_color}">{score}/10</span>
                </div>
                
                <div class="space-y-4 text-gray-700">
                    <div>
                        <span class="font-semibold text-gray-900">Verdict:</span> {output}
                    </div>
                    <div>
                        <span class="font-semibold text-gray-900 block mb-1">Reasoning:</span>
                        <p class="text-sm leading-relaxed text-gray-600">{reasoning}</p>
                    </div>
                    {weakness_alert}
                </div>
            </div>
        """
        
    html_content += """
        </div>
    </div>
</body>
</html>
"""

    html_out.write_text(html_content, encoding="utf-8")
    print(f"✅ HTML report generated: {html_out}")

def main():
    print("⚖️ Starting LLM-as-a-Judge Evaluation...")
    print(f"🤖 Judge Model: gemini-2.5-pro")
    
    if not settings.GCP_PROJECT_ID or settings.GCP_PROJECT_ID == "my-project-id":
        print("❌ ERROR: Set GCP_PROJECT_ID in .env first")
        sys.exit(1)

    result_files = sorted(RESULTS_DIR.glob("result_*.json"))
    if not result_files:
        print(f"❌ No result files found in {RESULTS_DIR}")
        sys.exit(1)

    evaluations = []

    for fpath in result_files:
        print(f"\nEvaluating {fpath.name}...")
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            transcript_file = TRANSCRIPTS_DIR / data["file"]
            if not transcript_file.exists():
                print(f"⚠️ Transcript {data['file']} not found. Skipping.")
                continue
                
            hindi_text = transcript_file.read_text(encoding="utf-8").strip()
            translated_text = data.get("translated_text", "")
            insights = data.get("insights", [])

            # Same product catalog as seed.py
            PRODUCT_CATALOG_TSV = """1001|Fevicol SH|Adhesives
1002|Fevikwik|Adhesives
1003|Dr. Fixit LW+|Waterproofing
1004|Roff Non-Skid Adhesive|Tiling
1005|Fevicol Marine|Adhesives""".strip()

            # Call Judge
            evaluation, tokens = evaluate_as_judge(hindi_text, translated_text, insights, model_name="gemini-2.5-pro", product_catalog_tsv=PRODUCT_CATALOG_TSV)
            
            print(f"   Score: {evaluation.get('score')}/10")
            print(f"   Verdict: {evaluation.get('output')}")
            
            evaluations.append({
                "file": data["file"],
                "evaluation": evaluation,
                "tokens_used": tokens
            })
            
        except Exception as exc:
            print(f"❌ Failed to evaluate {fpath.name}: {exc}")

    # Generate Report
    if evaluations:
        generate_html_report(evaluations)
        
        # Save JSON audit log
        audit_log = RESULTS_DIR / "judge_audit.json"
        with open(audit_log, "w", encoding="utf-8") as f:
            json.dump(evaluations, f, indent=2, ensure_ascii=False)
        print(f"✅ JSON audit log saved: {audit_log}")
    
    print("\n🏁 LLM-as-a-Judge complete!")

if __name__ == "__main__":
    main()
