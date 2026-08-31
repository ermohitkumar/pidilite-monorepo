#!/usr/bin/env bash
# Build linux/amd64 frontend image and deploy pidilite-frontend (same as CI-CD.yaml).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SHORT_SHA="$(git rev-parse --short HEAD)"
PROJECT=pidilite-user-feedback-ai
IMAGE="asia-south1-docker.pkg.dev/${PROJECT}/user-feedback-frontend/pidilite-frontend-image"

echo "Deploying frontend SHORT_SHA=${SHORT_SHA}"

gcloud auth print-access-token >/dev/null

AUTH_SECRET="$(gcloud secrets versions access latest --secret=DEV_AUTH_SECRET --project="$PROJECT")"
NEXT_PUBLIC_NODE_ENV="$(gcloud secrets versions access latest --secret=DEV_NEXT_PUBLIC_NODE_ENV --project="$PROJECT")"
NEXT_PUBLIC_APP_URL="$(gcloud secrets versions access latest --secret=DEV_NEXT_PUBLIC_APP_URL --project="$PROJECT")"
NEXT_PUBLIC_BACKEND_API_URL="$(gcloud secrets versions access latest --secret=DEV_NEXT_PUBLIC_BACKEND_API_URL --project="$PROJECT")"
AZURE_AD_CLIENT_ID="$(gcloud secrets versions access latest --secret=DEV_AZURE_AD_CLIENT_ID --project="$PROJECT")"
AZURE_AD_CLIENT_SECRET="$(gcloud secrets versions access latest --secret=DEV_AZURE_AD_CLIENT_SECRET --project="$PROJECT")"
AZURE_AD_TENANT_ID="$(gcloud secrets versions access latest --secret=DEV_AZURE_AD_TENANT_ID --project="$PROJECT")"

gcloud auth configure-docker asia-south1-docker.pkg.dev --quiet

docker build --platform linux/amd64 \
  --build-arg AUTH_SECRET="$AUTH_SECRET" \
  --build-arg NEXT_PUBLIC_NODE_ENV="$NEXT_PUBLIC_NODE_ENV" \
  --build-arg NEXT_PUBLIC_APP_URL="$NEXT_PUBLIC_APP_URL" \
  --build-arg NEXT_PUBLIC_BACKEND_API_URL="$NEXT_PUBLIC_BACKEND_API_URL" \
  --build-arg AZURE_AD_CLIENT_ID="$AZURE_AD_CLIENT_ID" \
  --build-arg AZURE_AD_CLIENT_SECRET="$AZURE_AD_CLIENT_SECRET" \
  --build-arg AZURE_AD_TENANT_ID="$AZURE_AD_TENANT_ID" \
  -t "${IMAGE}:${SHORT_SHA}" \
  -t "${IMAGE}:latest" \
  .

docker push "${IMAGE}:${SHORT_SHA}"
docker push "${IMAGE}:latest"

gcloud run deploy pidilite-frontend \
  --image="${IMAGE}:${SHORT_SHA}" \
  --region=asia-south1 \
  --project="$PROJECT" \
  --platform=managed \
  --port=3000 \
  --service-account="cloud-run-api@${PROJECT}.iam.gserviceaccount.com" \
  --quiet

echo "DEPLOY_OK SHORT_SHA=${SHORT_SHA}"
gcloud run services describe pidilite-frontend \
  --region=asia-south1 \
  --project="$PROJECT" \
  --format='value(status.url,status.latestReadyRevisionName)'
