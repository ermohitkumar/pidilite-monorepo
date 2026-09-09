# User Feedback Batch Micro

Pidilite Pipeline Service — a FastAPI microservice that turns field/sales voice audio into structured product feedback.

**Pipeline:** ingest → batch → STT → translate → normalize → insights

Triggered by GCS Eventarc, Cloud Scheduler, and Cloud Tasks. Deployed as Cloud Run service `pidilite-pipeline-svc` on port **8001**.

---

## Tech stack

| Layer | Tech |
|-------|------|
| Runtime | Python 3.11, Poetry |
| API | FastAPI, Uvicorn |
| DB | PostgreSQL 15, SQLAlchemy 2, Alembic |
| GCP | Cloud Storage, Speech-to-Text, Cloud Tasks, Vertex AI (Gemini) |
| Deploy | Docker → Artifact Registry → Cloud Run |

---

## Project structure

```
User_Feedback_batchmicro/
├── core/                     # Settings, enums, response helpers, exceptions
├── db/                       # SQLAlchemy models & session
├── schemas/                  # Pydantic request/response models
├── repositories/             # Batch/job data access
├── services/
│   ├── api/
│   │   ├── main.py           # FastAPI app
│   │   └── routers/          # ingest, batch, stt, translate, normalize, checker
│   └── shared/               # Cloud Tasks, Vertex AI, GCS helpers
├── alembic/                  # DB migrations
├── scripts/                  # Seed & ops scripts
├── tests/                    # Pytest + optional live Vertex scripts
├── docs/                     # API endpoints, Postman, sequence diagram, DB schema
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

---

## Prerequisites

- Docker & Docker Compose
- Poetry (for host runs)
- Python 3.11+
- A `.env` file in the project root (see [Environment variables](#environment-variables))
- GCP project access if you want the full STT / Vertex / Cloud Tasks path

---

## Running locally

### Option A — Docker Compose (recommended)

```bash
# From this repo root
docker compose up --build
```

| Service | Port | Notes |
|---------|------|--------|
| `api` | http://localhost:8001 | Swagger: `/docs` |
| `db` | 5432 | Postgres 15 |
| `pgadmin` | http://localhost:5050 | `admin@pidilite.com` / `admin` |

Apply migrations and seed:

```bash
docker compose exec api poetry run alembic upgrade head
docker compose exec api poetry run python scripts/seed.py
```

Health check:

```bash
curl http://localhost:8001/health
```

### Option B — Poetry on the host

```bash
poetry install
# Ensure .env points DB_HOST at localhost (or your Postgres)
poetry run alembic upgrade head
poetry run uvicorn services.api.main:app --host 0.0.0.0 --port 8001 --reload
```

> Cloud Tasks enqueue is skipped locally when GCP/queue config is incomplete (logged as a warning). Full end-to-end needs a real GCP project, buckets, and task URLs.

---

## Environment variables

Copy or create `.env` in the project root. Key settings:

| Variable | Purpose |
|----------|---------|
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Postgres connection |
| `SQLALCHEMY_DATABASE_URL` | Optional full URL override |
| `GCP_PROJECT_ID`, `GCP_LOCATION` | GCP project / region |
| `GCS_INPUT_BUCKET` | Raw audio bucket |
| `GCS_OUTPUT_BUCKET` | STT transcript output bucket |
| `GOOGLE_APPLICATION_CREDENTIALS` | Optional SA JSON path (ADC if unset) |
| `CLOUD_TASKS_QUEUE` | Queue name (default `pidilite-stt-queue`) |
| `CLOUD_TASKS_CALLBACK_URL` | → `/api/v1/files/transcription` |
| `CLOUD_TASKS_TRANSLATE_URL` | → `/api/v1/files/translate` |
| `CLOUD_TASKS_POSTPROCESS_URL` | → `/api/v1/files/post-processing` |
| `CLOUD_TASKS_INVOKER_SA` | OIDC invoker service account |
| `CLOUD_TASKS_USE_OIDC` | Attach OIDC on tasks (`true` in prod) |
| `BATCH_SIZE` | Jobs per batch (default `10`) |
| `MAX_RETRY_COUNT` | Checker retry limit (default `2`) |
| `GEMINI_MODEL` | Vertex model (default `gemini-2.5-flash`) |

---

## API overview

Full request/response reference: [docs/api-endpoints.md](docs/api-endpoints.md).

Base prefix: `/api/v1`  
OpenAPI: http://localhost:8001/docs  
Postman: [docs/postman/User_Feedback_Pipeline.postman_collection.json](docs/postman/User_Feedback_Pipeline.postman_collection.json)

| Method | Path | Trigger | Purpose |
|--------|------|---------|---------|
| `GET` | `/health` | Ops | Liveness |
| `POST` | `/api/v1/file` | Eventarc (GCS finalize) | Register audio job (`PENDING`) |
| `POST` | `/api/v1/batch` | Cloud Scheduler | Chunk PENDING jobs → enqueue STT |
| `POST` | `/api/v1/files/transcription` | Cloud Tasks | Submit Speech-to-Text LRO |
| `POST` | `/api/v1/files/stt-complete` | Eventarc (STT output) | Enqueue translate |
| `POST` | `/api/v1/files/translate` | Cloud Tasks | Translate transcript via Gemini |
| `POST` | `/api/v1/files/post-processing` | Cloud Tasks | Generate insights → Feedback rows |
| `POST` | `/api/v1/checker/run` | Scheduler / ops | Recover stuck / failed jobs |

All `/api/v1/*` responses use a standard envelope:

```json
{
  "success": true,
  "message": "...",
  "data": {},
  "error": null,
  "timestamp": "2026-01-01T00:00:00Z",
  "request_id": "req_xxxxxxxxxxxx"
}
```

---

## Batch process flow

See the sequence diagram: [docs/batch-process-sequence.md](docs/batch-process-sequence.md)

Happy path in short:

1. Audio lands in GCS → Eventarc → `POST /file` → Job `PENDING`
2. Scheduler → `POST /batch` → jobs `BATCHED` → Cloud Tasks → STT
3. STT writes JSON to output bucket → Eventarc → `POST /files/stt-complete` → translate task
4. Translate → `TRANSLATED` → post-processing task
5. Gemini insights → `Feedback` rows → Job `COMPLETED`
6. Checker polls LROs, retries `ERROR`, reconciles batches

---

## Tests

```bash
poetry install
poetry run pytest
poetry run pytest tests/test_api_v1.py
poetry run pytest tests/test_insights_ingestion.py
```

Optional live Vertex scripts (need GCP credentials):

```bash
poetry run python tests/test_prompt_live.py
poetry run python tests/test_evaluate_pipeline.py
```

---

## Docs

| Doc | Description |
|-----|-------------|
| [docs/api-endpoints.md](docs/api-endpoints.md) | Pipeline HTTP endpoints (request/response) |
| [docs/hld-and-powerbi-access.md](docs/hld-and-powerbi-access.md) | Pipeline overview and Power BI access requirements |
| [docs/batch-process-sequence.md](docs/batch-process-sequence.md) | Batch pipeline sequence diagram |
| [docs/db-schema.md](docs/db-schema.md) | PostgreSQL ER diagram and table reference |
| [docs/powerbi-views.md](docs/powerbi-views.md) | Power BI SQL views and column mapping |
| [docs/powerbi-vs-web-reporting.md](docs/powerbi-vs-web-reporting.md) | Plain-language Power BI vs web reporting comparison |
| [docs/architecture-change-gemini-flash-stt.md](docs/architecture-change-gemini-flash-stt.md) | ACR: optional Gemini Flash STT (async queue, v2 fallback, 2-week plan) |
| [docs/filter-master-db-2week-plan.md](docs/filter-master-db-2week-plan.md) | 1–14 Sep 2026: filters + product master from Postgres (`Sample Data.xlsx`) |
| [docs/prod-gcp-access.md](docs/prod-gcp-access.md) | Prod GCP IAM: services, roles, scope |
| [docs/questions-for-pidilite.md](docs/questions-for-pidilite.md) | Open questions Pidilite must answer (prod + filters) |
| [docs/site-visit-dw-integration-plan.md](docs/site-visit-dw-integration-plan.md) | Site visit → Azure warehouse filters (website vs Power BI) |
| [docs/site-visit-dw-estimation.md](docs/site-visit-dw-estimation.md) | 2.5-week hour estimate (backend, UI / Power BI, DevOps, testing, docs) |
| [docs/postman/User_Feedback_Pipeline.postman_collection.json](docs/postman/User_Feedback_Pipeline.postman_collection.json) | Postman collection for all endpoints |
