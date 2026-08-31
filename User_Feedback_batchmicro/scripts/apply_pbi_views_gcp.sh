#!/usr/bin/env bash
# Apply Power BI views + taxonomy seed to Cloud SQL via Cloud Run migrate job.
# Cloud SQL uses feedback_tags.tag_id (int); SQL join is rewritten accordingly.
set -euo pipefail

export CLOUDSDK_CORE_PROJECT="${CLOUDSDK_CORE_PROJECT:-pidilite-user-feedback-ai}"
REGION="${REGION:-asia-south1}"
JOB="${JOB:-pidilite-pipeline-migrate}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

export CLOUDSDK_AUTH_ACCESS_TOKEN="$(gcloud auth application-default print-access-token)"
IMG="$(gcloud run services describe pidilite-pipeline-svc --region="$REGION" --format='value(spec.template.spec.containers[0].image)')"

B64="$(
python3 - <<PY
import base64, json
from pathlib import Path
root = Path("$ROOT")
tax = json.loads((root / "scripts/data/feedback_taxonomy.json").read_text())
views = (root / "scripts/sql/pbi_views.sql").read_text().replace("ON t.id = l.tag_id", "ON t.tag_id = l.tag_id")
tax_b64 = base64.b64encode(json.dumps(tax).encode()).decode()
views_b64 = base64.b64encode(views.encode()).decode()
code = f'''
import base64, json, os
from sqlalchemy import create_engine, text
tax = json.loads(base64.b64decode("{tax_b64}").decode())
views_sql = base64.b64decode("{views_b64}").decode()
url = (
    f"postgresql+psycopg2://{{os.environ['DB_USER']}}:{{os.environ['DB_PASSWORD']}}"
    f"@{{os.environ['DB_HOST']}}:{{os.environ['DB_PORT']}}/{{os.environ['DB_NAME']}}"
)
e = create_engine(url)
with e.begin() as c:
    c.execute(text("""
    CREATE TABLE IF NOT EXISTS bi_feedback_taxonomy (
        tag_id INTEGER PRIMARY KEY,
        feedback_group VARCHAR(100) NOT NULL,
        feedback_category VARCHAR(100) NOT NULL,
        feedback_tag VARCHAR(300) NOT NULL,
        feedback_sub_tag TEXT,
        description TEXT
    )
    """))
    c.execute(text("TRUNCATE bi_feedback_taxonomy"))
    for entry in tax.get("taxonomy", []):
        c.execute(text("""
            INSERT INTO bi_feedback_taxonomy
            (tag_id, feedback_group, feedback_category, feedback_tag, feedback_sub_tag, description)
            VALUES (:tag_id, :g, :c, :t, :s, :d)
        """), {{
            "tag_id": int(entry["tag_id"]),
            "g": entry.get("feedback_group") or "",
            "c": entry.get("feedback_category") or "",
            "t": entry.get("feedback_tag") or "",
            "s": entry.get("feedback_sub_tag"),
            "d": entry.get("description"),
        }})
    n = len(tax.get("taxonomy", []))
    print("OK: seeded bi_feedback_taxonomy", n, "rows")
    c.execute(text(views_sql))
    print("OK: applied pbi_views.sql")
with e.connect() as c:
    for q in [
        "SELECT count(*) FROM bi_feedback_taxonomy",
        "SELECT count(*) FROM vw_pbi_feedback_fact",
        "SELECT count(*) FROM vw_pbi_tag_counts",
        "SELECT count(*) FROM vw_pbi_taxonomy_coverage",
        "SELECT count(*) FROM information_schema.views WHERE table_schema='public' AND table_name LIKE 'vw_pbi_%'",
    ]:
        print(q, "=>", c.execute(text(q)).scalar())
'''
print(base64.b64encode(code.encode()).decode())
PY
)"

gcloud run jobs update "$JOB" --region="$REGION" --image="$IMG" \
  --command=poetry --args="^|^run|python|-c|import base64; exec(base64.b64decode('${B64}').decode())" --quiet

gcloud run jobs execute "$JOB" --region="$REGION" --wait

EXEC="$(gcloud run jobs executions list --job="$JOB" --region="$REGION" --limit=1 --format='value(name)' --sort-by='~metadata.creationTimestamp')"
echo "EXEC=$EXEC"
gcloud logging read \
  "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"$JOB\" AND labels.\"run.googleapis.com/execution_name\"=\"$EXEC\"" \
  --limit=80 --format='value(textPayload)' --freshness=10m \
  | grep -v '^$' | grep -E 'OK:|=>|Error|Traceback|Undefined' | tail -40

# Restore default migrate command
gcloud run jobs update "$JOB" --region="$REGION" \
  --command=poetry --args="run,python,scripts/migrate_schema.py" --quiet
echo "Restored $JOB command to migrate_schema.py"
