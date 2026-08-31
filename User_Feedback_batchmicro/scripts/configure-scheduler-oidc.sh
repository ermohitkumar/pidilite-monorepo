#!/usr/bin/env bash
# Configure Cloud Scheduler → Cloud Run /api/v1/batch with OIDC (required when
# the service does not allow unauthenticated invocation).
set -euo pipefail

PROJECT="${GCP_PROJECT_ID:-pidilite-user-feedback-ai}"
REGION="${GCP_LOCATION:-asia-south1}"
JOB_NAME="${SCHEDULER_JOB_NAME:-pidilite-pipeline-batch-hourly}"
INVOKER_SA="${CLOUD_TASKS_INVOKER_SA:-cloud-run-api@${PROJECT}.iam.gserviceaccount.com}"
SERVICE_URL="${CLOUD_RUN_SERVICE_URL:-https://pidilite-pipeline-svc-634870075270.asia-south1.run.app}"
AUDIENCE="${CLOUD_RUN_SERVICE_AUDIENCE:-${SERVICE_URL}}"

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')"
SCHEDULER_AGENT="service-${PROJECT_NUMBER}@gcp-sa-cloudscheduler.iam.gserviceaccount.com"

echo "Granting Scheduler agent permission to mint OIDC as ${INVOKER_SA}..."
gcloud iam service-accounts add-iam-policy-binding "${INVOKER_SA}" \
  --project="${PROJECT}" \
  --member="serviceAccount:${SCHEDULER_AGENT}" \
  --role="roles/iam.serviceAccountUser" \
  --quiet

echo "Updating Scheduler job ${JOB_NAME} with OIDC..."
gcloud scheduler jobs update http "${JOB_NAME}" \
  --project="${PROJECT}" \
  --location="${REGION}" \
  --uri="${SERVICE_URL}/api/v1/batch" \
  --http-method=POST \
  --update-headers="Content-Type=application/json" \
  --message-body='{}' \
  --oidc-service-account-email="${INVOKER_SA}" \
  --oidc-token-audience="${AUDIENCE}" \
  --quiet

echo "Done. Test with: gcloud scheduler jobs run ${JOB_NAME} --location=${REGION} --project=${PROJECT}"
