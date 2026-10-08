#!/usr/bin/env bash
# Daily period-summary job on the dashboard: refresh the current month incrementally.
set -euo pipefail

PROJECT="${GCP_PROJECT_ID:-pidilite-user-feedback-ai}"
REGION="${GCP_LOCATION:-asia-south1}"
JOB_NAME="${SCHEDULER_JOB_NAME:-pidilite-period-summaries-daily}"
INVOKER_SA="${CLOUD_TASKS_INVOKER_SA:-cloud-run-api@${PROJECT}.iam.gserviceaccount.com}"
SERVICE_URL="${DASHBOARD_SERVICE_URL:-https://pidilite-dashboard-px6kcgjomq-el.a.run.app}"
AUDIENCE="${CLOUD_RUN_SERVICE_AUDIENCE:-${SERVICE_URL}}"
SCHEDULE="${SCHEDULE:-30 2 * * *}"
TIME_ZONE="${TIME_ZONE:-Asia/Kolkata}"
# Empty body → runner uses current month (and previous month on days 1–2).
BODY="${MESSAGE_BODY:-{}}"

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')"
SCHEDULER_AGENT="service-${PROJECT_NUMBER}@gcp-sa-cloudscheduler.iam.gserviceaccount.com"

echo "Granting Scheduler agent permission to mint OIDC as ${INVOKER_SA}..."
if ! gcloud iam service-accounts add-iam-policy-binding "${INVOKER_SA}" \
  --project="${PROJECT}" \
  --member="serviceAccount:${SCHEDULER_AGENT}" \
  --role="roles/iam.serviceAccountUser" \
  --quiet; then
  echo "IAM bind skipped (permission denied or already granted). Continuing."
fi

if gcloud scheduler jobs describe "${JOB_NAME}" --project="${PROJECT}" --location="${REGION}" >/dev/null 2>&1; then
  echo "Updating Scheduler job ${JOB_NAME}..."
  gcloud scheduler jobs update http "${JOB_NAME}" \
    --project="${PROJECT}" \
    --location="${REGION}" \
    --schedule="${SCHEDULE}" \
    --time-zone="${TIME_ZONE}" \
    --uri="${SERVICE_URL}/api/v1/reports/period-summaries/run" \
    --http-method=POST \
    --update-headers="Content-Type=application/json" \
    --message-body="${BODY}" \
    --oidc-service-account-email="${INVOKER_SA}" \
    --oidc-token-audience="${AUDIENCE}" \
    --quiet
else
  echo "Creating Scheduler job ${JOB_NAME}..."
  gcloud scheduler jobs create http "${JOB_NAME}" \
    --project="${PROJECT}" \
    --location="${REGION}" \
    --schedule="${SCHEDULE}" \
    --time-zone="${TIME_ZONE}" \
    --uri="${SERVICE_URL}/api/v1/reports/period-summaries/run" \
    --http-method=POST \
    --headers="Content-Type=application/json" \
    --message-body="${BODY}" \
    --oidc-service-account-email="${INVOKER_SA}" \
    --oidc-token-audience="${AUDIENCE}" \
    --quiet
fi

echo "Done. Test with:"
echo "  gcloud scheduler jobs run ${JOB_NAME} --location=${REGION} --project=${PROJECT}"
