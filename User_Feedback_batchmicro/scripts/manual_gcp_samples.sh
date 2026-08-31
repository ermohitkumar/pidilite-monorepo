#!/usr/bin/env bash
# Manual GCP pipeline test for one or more sample_*.mp3 files (no e2e_samples.py).
set -euo pipefail

BASE="${BASE_URL:-https://pidilite-pipeline-svc-px6kcgjomq-el.a.run.app}"
BUCKET="${GCS_INPUT_BUCKET:-pidilite-raw-audio}"
OUT_BUCKET="${GCS_OUTPUT_BUCKET:-pidilite-processed-text}"
PROJECT="${GCP_PROJECT_ID:-pidilite-user-feedback-ai}"
PREFIX="manual-e2e-$(date -u +%Y%m%d-%H%M%S)"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${ROOT}/.venv/bin/python"
cd "$ROOT"
if [[ $# -gt 0 ]]; then
  SAMPLES=("$@")
else
  SAMPLES=(samples/sample_01.mp3 samples/sample_02.mp3 samples/sample_03.mp3)
fi

META='{"division":"Consumer","zone":"West","rfmm_cluster":"ManualCluster","rbdm_cluster":"ManualCluster","cluster":"ManualCluster","fme_code":"M001","user_type":"FME","state":"Maharashtra","town_city":"Mumbai","tsi_territory_code":"TSI-M","tty_code":"TTY-M","user_id":"manual-user","data_source":"manual_test"}'

echo "Health: $(curl -sS "$BASE/health")"
echo "Prefix: $PREFIX"

declare -a JOB_IDS=()
declare -a GCS_INS=()
declare -a LOCALS=()

for SAMPLE in "${SAMPLES[@]}"; do
  [[ -f "$SAMPLE" ]] || SAMPLE="$ROOT/$SAMPLE"
  NAME="$(basename "$SAMPLE")"
  OBJECT="$PREFIX/$NAME"
  SIZE=$(stat -f%z "$SAMPLE" 2>/dev/null || stat -c%s "$SAMPLE")

  echo ""
  echo "=== UPLOAD $NAME ==="
  "$PY" - <<PY
from google.cloud import storage
client = storage.Client(project="$PROJECT")
blob = client.bucket("$BUCKET").blob("$OBJECT")
blob.upload_from_filename("$SAMPLE", content_type="audio/mpeg")
blob.metadata = $META
blob.patch()
print("uploaded", blob.name, blob.size)
PY

  echo "=== INGEST $NAME ==="
  INGEST=$(curl -sS -X POST "$BASE/api/v1/file" -H 'Content-Type: application/json' \
    -d "{\"name\":\"$OBJECT\",\"bucket\":\"$BUCKET\",\"contentType\":\"audio/mpeg\",\"size\":\"$SIZE\",\"metadata\":$META}")
  echo "$INGEST" | "$PY" -m json.tool 2>/dev/null || echo "$INGEST"
  JOB_ID=$("$PY" -c "import json,sys; print(json.loads(sys.argv[1])['data']['job_id'])" "$INGEST")
  GCS_IN=$("$PY" -c "import json,sys; print(json.loads(sys.argv[1])['data']['gcs_input_uri'])" "$INGEST")
  JOB_IDS+=("$JOB_ID")
  GCS_INS+=("$GCS_IN")
  LOCALS+=("$NAME")
done

echo ""
echo "=== BATCH ==="
curl -sS -X POST "$BASE/api/v1/batch" -H 'Content-Type: application/json' -d '{}' | "$PY" -m json.tool

RESULTS=()
for i in "${!JOB_IDS[@]}"; do
  JOB_ID="${JOB_IDS[$i]}"
  GCS_IN="${GCS_INS[$i]}"
  NAME="${LOCALS[$i]}"
  STT_URI="gs://$OUT_BUCKET/stt-output/$JOB_ID/output.json"
  STT_PATH="stt-output/$JOB_ID/output.json"

  echo ""
  echo "=== STT $NAME ($JOB_ID) ==="
  curl -sS -X POST "$BASE/api/v1/files/transcription" -H 'Content-Type: application/json' \
    -d "{\"job_id\":\"$JOB_ID\",\"gcs_input_uri\":\"$GCS_IN\",\"gcs_output_uri_prefix\":\"gs://$OUT_BUCKET/stt-output/$JOB_ID/\",\"language_code\":\"hi-IN\",\"model\":\"latest_long\"}" \
    | "$PY" -m json.tool

  echo "Waiting for STT output..."
  "$PY" - <<PY
import time
from google.cloud import storage
uri = "$STT_URI".replace("gs://", "")
bucket, path = uri.split("/", 1)
blob = storage.Client(project="$PROJECT").bucket(bucket).blob(path)
for left in range(180, 0, -1):
    if blob.exists():
        print("STT READY", "$STT_URI")
        break
    time.sleep(10)
    if left % 6 == 0:
        print(f"waiting... {left*10}s budget left")
else:
    raise SystemExit("STT timeout for $JOB_ID")
PY

  echo "=== stt-complete $NAME ==="
  curl -sS -X POST "$BASE/api/v1/files/stt-complete" -H 'Content-Type: application/json' \
    -d "{\"name\":\"$STT_PATH\",\"bucket\":\"$OUT_BUCKET\",\"contentType\":\"application/json\"}" \
    | "$PY" -m json.tool

  # Eventarc may already be TRANSLATING — still call translate (idempotent when done)
  echo "=== translate $NAME ==="
  # brief wait so Eventarc/Cloud Task can land first
  sleep 5
  TRANSLATE=$(curl -sS -X POST "$BASE/api/v1/files/translate" -H 'Content-Type: application/json' \
    -d "{\"job_id\":\"$JOB_ID\",\"gcs_transcript_uri\":\"$STT_URI\"}")
  echo "$TRANSLATE" | "$PY" -m json.tool

  echo "=== insights $NAME ==="
  INSIGHTS=$(curl -sS -X POST "$BASE/api/v1/files/post-processing" -H 'Content-Type: application/json' \
    -d "{\"job_id\":\"$JOB_ID\"}")
  echo "$INSIGHTS" | "$PY" -m json.tool
  STATUS=$("$PY" -c "import json,sys; d=json.loads(sys.argv[1]); print((d.get('data') or {}).get('status'))" "$INSIGHTS")
  GEN=$("$PY" -c "import json,sys; d=json.loads(sys.argv[1]); print((d.get('data') or {}).get('insights_generated'))" "$INSIGHTS")
  RESULTS+=("$NAME|$JOB_ID|$STATUS|$GEN")
done

echo ""
echo "═══ MANUAL SUMMARY ═══"
FAIL=0
for row in "${RESULTS[@]}"; do
  echo "$row"
  STATUS=$(echo "$row" | cut -d'|' -f3)
  [[ "$STATUS" == "COMPLETED" ]] || FAIL=1
done
[[ $FAIL -eq 0 ]]
