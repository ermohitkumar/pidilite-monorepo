#!/usr/bin/env bash
# Create or update pidilite-gemini-stt-queue for the Gemini Flash STT worker.
# Retry max 3, concurrency cap, exponential backoff. OIDC is attached per task
# by enqueue_http_task (same invoker SA as the existing worker queue).
set -euo pipefail

PROJECT="${GCP_PROJECT_ID:-pidilite-user-feedback-ai}"
REGION="${GCP_LOCATION:-asia-south1}"
QUEUE="${CLOUD_TASKS_GEMINI_STT_QUEUE:-pidilite-gemini-stt-queue}"
MAX_ATTEMPTS="${GEMINI_STT_QUEUE_MAX_ATTEMPTS:-3}"
MAX_CONCURRENT="${GEMINI_STT_QUEUE_MAX_CONCURRENT:-8}"
MAX_DISPATCHES_PER_SEC="${GEMINI_STT_QUEUE_MAX_DISPATCHES_PER_SEC:-5}"

COMMON_FLAGS=(
  --project="${PROJECT}"
  --location="${REGION}"
  --max-attempts="${MAX_ATTEMPTS}"
  --max-concurrent-dispatches="${MAX_CONCURRENT}"
  --max-dispatches-per-second="${MAX_DISPATCHES_PER_SEC}"
  --min-backoff=10s
  --max-backoff=120s
  --max-doublings=3
  --max-retry-duration=0s
)

if gcloud tasks queues describe "${QUEUE}" --project="${PROJECT}" --location="${REGION}" >/dev/null 2>&1; then
  echo "Updating Cloud Tasks queue ${QUEUE}..."
  gcloud tasks queues update "${QUEUE}" "${COMMON_FLAGS[@]}" --quiet
else
  echo "Creating Cloud Tasks queue ${QUEUE}..."
  gcloud tasks queues create "${QUEUE}" "${COMMON_FLAGS[@]}" --quiet
fi

echo "Done. Queue ${QUEUE} in ${REGION}: max_attempts=${MAX_ATTEMPTS}, max_concurrent=${MAX_CONCURRENT}."
echo "STT_PROVIDER is gemini_flash in config; /transcription will enqueue this queue."
