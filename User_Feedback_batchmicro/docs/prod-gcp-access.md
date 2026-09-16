# Production GCP access

**Region:** `asia-south1`  
**Template (Dev):** project `pidilite-user-feedback-ai`, SA `cloud-run-api@…`, CI SA `github-actions-sa@…`, WIF `projects/634870075270/locations/global/workloadIdentityPools/github-pool/providers/github-provider`  
**Prod:** same pattern on the **prod project** (or clearly named prod resources). Replace `PROJECT_ID` and `PROJECT_NUMBER`. Do not reuse Dev secrets, buckets, or SQL.

Runtime identity for Cloud Run (`pidilite-pipeline-svc`, `pidilite-dashboard`, `pidilite-frontend`) and Cloud Run Job `pidilite-pipeline-migrate`:

`cloud-run-api@PROJECT_ID.iam.gserviceaccount.com`

CI/CD identity (GitHub Actions via Workload Identity Federation):

`github-actions-sa@PROJECT_ID.iam.gserviceaccount.com`

---

## IAM — service, role, scope

| GCP service | Identity | Role | Scope |
|-------------|----------|------|-------|
| Cloud Run | `cloud-run-api@PROJECT_ID` | `roles/run.invoker` | Services `pidilite-pipeline-svc`, `pidilite-dashboard` (OIDC from Cloud Tasks + Cloud Scheduler + Eventarc). Not on `pidilite-frontend` unless internal invoke is required. |
| Cloud Run | Cloud Scheduler agent `service-PROJECT_NUMBER@gcp-sa-cloudscheduler.iam.gserviceaccount.com` | `roles/iam.serviceAccountUser` | SA `cloud-run-api@PROJECT_ID` (mint OIDC for `/api/v1/batch`, `/api/v1/checker/run`, and dashboard `POST /api/v1/reports/period-summaries/run`) |
| Cloud Run | Cloud Tasks agent `service-PROJECT_NUMBER@gcp-sa-cloudtasks.iam.gserviceaccount.com` | `roles/iam.serviceAccountUser` | SA `cloud-run-api@PROJECT_ID` (mint OIDC for STT / translate / post-process / Gemini STT tasks) |
| Cloud Run | Eventarc trigger SA (`cloud-run-api@PROJECT_ID` or dedicated `eventarc-trigger@PROJECT_ID`) | `roles/run.invoker` | Service `pidilite-pipeline-svc` (`POST /api/v1/file`, `POST /api/v1/files/stt-complete`) |
| Cloud Run | Eventarc trigger SA | `roles/eventarc.eventReceiver` | Project |
| Cloud Run | `github-actions-sa@PROJECT_ID` | `roles/run.developer` | Project (or services `pidilite-pipeline-svc`, `pidilite-dashboard`, `pidilite-frontend` + job `pidilite-pipeline-migrate`) |
| Cloud Run | `github-actions-sa@PROJECT_ID` | `roles/iam.serviceAccountUser` | SA `cloud-run-api@PROJECT_ID` (deploy revisions **as** that runtime SA) |
| Artifact Registry | `github-actions-sa@PROJECT_ID` | `roles/artifactregistry.writer` | Repos `user-feedback-batchmicro`, `user-feedback-backend`, `user-feedback-frontend` in `asia-south1` |
| Artifact Registry | Cloud Run service agent `service-PROJECT_NUMBER@serverless-robot-prod.iam.gserviceaccount.com` | `roles/artifactregistry.reader` | Same three repos (pull images at deploy/start) |
| Secret Manager | `cloud-run-api@PROJECT_ID` | `roles/secretmanager.secretAccessor` | **Secrets only:** `PROD_DB_HOST`, `PROD_DB_PORT`, `PROD_DB_NAME`, `PROD_DB_USER`, `PROD_DB_PASSWORD`, `PROD_GCP_PROJECT_ID`, `PROD_GCP_LOCATION`, `PROD_GCS_INPUT_BUCKET`, `PROD_GCS_OUTPUT_BUCKET`, `PROD_CLOUD_TASKS_*`, `PROD_GEMINI_MODEL`, `PROD_SESSION_SECRET_KEY`, `PROD_SESSION_MAX_AGE` |
| Secret Manager | `github-actions-sa@PROJECT_ID` | `roles/secretmanager.secretAccessor` | **Secrets only:** `PROD_AUTH_SECRET`, `PROD_NEXT_PUBLIC_*`, `PROD_AZURE_AD_CLIENT_ID`, `PROD_AZURE_AD_CLIENT_SECRET`, `PROD_AZURE_AD_TENANT_ID` (frontend image build) |
| Cloud SQL | `cloud-run-api@PROJECT_ID` | `roles/cloudsql.client` | Prod instance only (private IP; Cloud Run via VPC connector) |
| Cloud Storage | `cloud-run-api@PROJECT_ID` | `roles/storage.objectViewer` | Prod input bucket (raw audio). Pipeline read + dashboard/frontend audio play. |
| Cloud Storage | `cloud-run-api@PROJECT_ID` | `roles/storage.objectAdmin` | Prod output bucket (STT JSON / transcripts). Create + overwrite `stt-output/{job_id}/…` |
| Cloud Storage | Speech agent `service-PROJECT_NUMBER@gcp-sa-speech.iam.gserviceaccount.com` | `roles/storage.objectViewer` | Prod input bucket (Speech v2 fallback reads `gs://` audio) |
| Cloud Storage | Speech agent `service-PROJECT_NUMBER@gcp-sa-speech.iam.gserviceaccount.com` | `roles/storage.objectCreator` | Prod output bucket (Speech v2 writes transcript JSON) |
| Cloud Storage | Vertex AI agent `service-PROJECT_NUMBER@gcp-sa-aiplatform.iam.gserviceaccount.com` | `roles/storage.objectViewer` | Prod input bucket (Gemini Flash STT `fileUri`) |
| Cloud Storage | GCS service agent `service-PROJECT_NUMBER@gs-project-accounts.iam.gserviceaccount.com` | `roles/pubsub.publisher` | Eventarc Pub/Sub topics for object finalize (input + STT output buckets) |
| Cloud Tasks | `cloud-run-api@PROJECT_ID` | `roles/cloudtasks.enqueuer` | Queues `pidilite-stt-queue`, `pidilite-gemini-stt-queue` in `asia-south1` |
| Cloud Tasks | `cloud-run-api@PROJECT_ID` | `roles/iam.serviceAccountUser` | SA `cloud-run-api@PROJECT_ID` (self; attach OIDC on HTTP tasks) |
| Vertex AI | `cloud-run-api@PROJECT_ID` | `roles/aiplatform.user` | Project, location `asia-south1` (Gemini translate, insights, optional Flash STT) |
| Speech-to-Text | `cloud-run-api@PROJECT_ID` | `roles/speech.client` | Project, location `asia-south1` (v2 `BatchRecognize` fallback) |
| Serverless VPC Access | Cloud Run runtime (connector attach is a resource setting, not an extra SA role) | — | Connector e.g. `pidilite-run-connector`; egress `private-ranges-only` to Cloud SQL private IP |
| Workload Identity Federation | GitHub repo(s) → WIF provider | `roles/iam.workloadIdentityUser` | On SA `github-actions-sa@PROJECT_ID` (attribute `principalSet://…/attribute.repository/ORG/REPO` for the three app repos) |
| Logging | `cloud-run-api@PROJECT_ID` | `roles/logging.logWriter` | Project (Cloud Run default if missing) |
| Monitoring | `cloud-run-api@PROJECT_ID` | `roles/monitoring.metricWriter` | Project |

---

## Human / group access (prod project)

**GCP IAM is sufficient for Production access.** Do not require a PAM jump host or OS login. People use the GCP Console / `gcloud` with the roles below. Prefer groups, not personal Owner.

| Who | GCP service | Role | Scope |
|-----|-------------|------|-------|
| Pidilite GCP admin | Project | `roles/resourcemanager.projectIamAdmin` + billing / API enable | Prod project (grant the rows above) |
| Bootlabs DevOps | Cloud Run | `roles/run.developer` | Prod Cloud Run services + migrate job |
| Bootlabs DevOps | Cloud SQL | `roles/cloudsql.admin` | Prod instance (create, private IP, backups, PITR). After go-live can drop to `roles/cloudsql.viewer` + `roles/cloudsql.client`. |
| Bootlabs DevOps | Secret Manager | `roles/secretmanager.admin` | `PROD_*` secrets only (or project if no secret-level IAM) |
| Bootlabs DevOps | Cloud Storage | `roles/storage.admin` | Prod input + output buckets |
| Bootlabs DevOps | Artifact Registry | `roles/artifactregistry.admin` | Three prod image repos |
| Bootlabs DevOps | Cloud Tasks | `roles/cloudtasks.admin` | `asia-south1` queues |
| Bootlabs DevOps | Cloud Scheduler | `roles/cloudscheduler.admin` | Batch + checker jobs |
| Bootlabs DevOps | Eventarc | `roles/eventarc.admin` | GCS → pipeline triggers |
| Bootlabs DevOps | VPC / Compute | `roles/vpcaccess.admin` + `roles/compute.networkUser` | Connector + Cloud SQL private services |
| Bootlabs DevOps | IAM | `roles/iam.serviceAccountAdmin` | Create/bind `cloud-run-api` and `github-actions-sa` only |
| Bootlabs DevOps | Observability | `roles/logging.viewer` + `roles/monitoring.viewer` | Prod project |
| Pidilite UAT / ops (read) | Cloud Run | `roles/run.viewer` | Prod services |
| Pidilite UAT / ops (read) | Cloud SQL | `roles/cloudsql.viewer` | Prod instance (no data plane; app is the data path) |
| Reporting login (Postgres, not IAM) | Cloud SQL | DB role `SELECT` only | Views / masters used by reports — **not** `cloud-run-api` |

Do **not** grant Bootlabs `roles/owner` or `roles/editor` on prod.

---

## APIs to enable on the prod project

| API | Service name |
|-----|----------------|
| Cloud Run | `run.googleapis.com` |
| Cloud SQL Admin | `sqladmin.googleapis.com` |
| Secret Manager | `secretmanager.googleapis.com` |
| Artifact Registry | `artifactregistry.googleapis.com` |
| Cloud Storage | `storage.googleapis.com` |
| Cloud Tasks | `cloudtasks.googleapis.com` |
| Cloud Scheduler | `cloudscheduler.googleapis.com` |
| Eventarc | `eventarc.googleapis.com` |
| Eventarc Publishing | `eventarcpublishing.googleapis.com` |
| Pub/Sub | `pubsub.googleapis.com` |
| Speech-to-Text | `speech.googleapis.com` |
| Vertex AI | `aiplatform.googleapis.com` |
| Serverless VPC Access | `vpcaccess.googleapis.com` |
| Compute Engine | `compute.googleapis.com` |
| Service Networking (Cloud SQL private IP) | `servicenetworking.googleapis.com` |
| IAM | `iam.googleapis.com` |
| IAM Credentials | `iamcredentials.googleapis.com` |
| Security Token Service (WIF) | `sts.googleapis.com` |
| Cloud Logging | `logging.googleapis.com` |
| Cloud Monitoring | `monitoring.googleapis.com` |
| Cloud Resource Manager | `cloudresourcemanager.googleapis.com` |

---

## Cloud Run invoke model (prod)

Prod services must **reject unauthenticated** requests (`--no-allow-unauthenticated`).

| Caller | How it authenticates | Target |
|--------|----------------------|--------|
| Cloud Tasks | OIDC as `cloud-run-api@` | `pidilite-pipeline-svc` worker URLs |
| Cloud Scheduler | OIDC as `cloud-run-api@` | `/api/v1/batch`, `/api/v1/checker/run`, `pidilite-dashboard` `POST /api/v1/reports/period-summaries/run` |
| Eventarc (GCS) | Invoke as Eventarc trigger SA | `/api/v1/file`, `/api/v1/files/stt-complete` |
| Website users | Entra ID on `pidilite-frontend`; frontend → `pidilite-dashboard` | No public invoke of the pipeline |
| M-Power / upload | Write object to **prod input bucket** (their own identity). Eventarc starts the pipeline. | Bucket IAM only — not Cloud Run |

M-Power (or the upload path) needs `roles/storage.objectCreator` on the **prod input bucket** only. That identity is Pidilite-owned; Bootlabs does not mint it.

## Period summaries (reports backend)

Nightly Cloud Scheduler job on `pidilite-dashboard`:

`POST /api/v1/reports/period-summaries/run`

OIDC as `cloud-run-api@PROJECT_ID`, same pattern as `/api/v1/batch`. Refreshes the current month. On the first two days of a month it also freezes the previous month and emits quarter/year when that month closed the period. Optional JSON body: `{"period_type":"month","period_key":"2026-09","force":false}`.

