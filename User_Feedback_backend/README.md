# Pidilite Audio Pipeline — Backend

GCP-native FastAPI monolith for ingesting, transcribing, normalising,
and generating insights from sales-call audio files (MP3).

---


## Architecture Overview

```
External Uploader
      │ Upload MP3
      ▼
 GCS Input Bucket ──(GCS Finalize Event)──► Eventarc
                                                │
                                                ▼
                                   POST /api/v1/file
                                   ┌───────────────────────┐
                                   │ Create Job + FileDetails│
                                   │ in Cloud SQL            │
                                   └──────────┬──────────────┘
                                              │
                                              ▼
                                  POST /api/v1/batch
                                  ┌────────────────────────┐
                                  │ Group into batches (≥10) │
                                  │ Enqueue Cloud Tasks      │
                                  └──────────┬───────────────┘
                                             │ task per job
                                             ▼
                                  POST /api/v1/files/transcription
                                  ┌─────────────────────┐
                                  │ Async LRO → STT     │
                                  └────────┬────────────┘
                                           │ LRO completes
                                           ▼
                                  GCS Output Bucket
                                           │ GCS Finalize
                                           ▼
                              POST /api/v1/files/post-processing
                              ┌─────────────────────────────┐
                              │ Extract transcript            │
                              │ Keyword replacement           │
                              │ Gemini insight generation     │
                              │ Store in Cloud SQL            │
                              └───────────────────────────────┘

Cloud Scheduler (every 15 min) ──► POST /api/v1/checker/run
                                   Poll STT LROs, retry errors,
                                   reconcile batch statuses

Cloud SQL ──► Backend API ──► Next.js Dashboard
                  ▲
                  │  Session cookie auth (JWT)
                  │  RBAC role checks
```

---

## API Endpoints

All endpoints follow a unified response envelope:

```json
{
  "success": true,
  "message": "Operation completed successfully",
  "data": { ... },
  "error": null,
  "timestamp": "2026-04-30T11:25:30.456Z",
  "request_id": "req_abc123xyz"
}
```

### Processing Pipeline

| # | Method | Path | Trigger | Description |
|---|--------|------|---------|-------------|
| 1 | POST | `/api/v1/file` | Eventarc (GCS input) | Register new audio file as a job |
| 2 | POST | `/api/v1/batch` | Cloud Scheduler / manual | Group PENDING jobs into batches, enqueue Cloud Tasks |
| 3 | POST | `/api/v1/files/transcription` | Cloud Tasks | Submit async STT LRO for a single job |
| 4 | POST | `/api/v1/files/post-processing` | Eventarc (GCS output) | Download STT transcript, normalise, generate Gemini insights |
| 5 | POST | `/api/v1/checker/run` | Cloud Scheduler (15 min) | Poll LROs, retry errors, reconcile batch statuses |

### Authentication & User Management

| # | Method | Path | Description | Roles Allowed |
|---|--------|------|-------------|---------------|
| 6 | POST | `/api/v1/auth/login` | Authenticate user, set session cookie | (Public) |
| 7 | POST | `/api/v1/auth/logout` | Clear session cookie | (Any authenticated) |
| 8 | POST | `/api/v1/users` | Create user | `super_admin` |
| 9 | GET | `/api/v1/users` | List all users | `super_admin` |
| 10| GET | `/api/v1/users/{id}` | Get user profile | `super_admin` or Self |
| 11| PUT | `/api/v1/users/{id}` | Update user (role, status, password) | `super_admin` |
| 12| DELETE | `/api/v1/users/{id}` | Delete user | `super_admin` |

### Keywords Management

| # | Method | Path | Description | Roles Allowed |
|---|--------|------|-------------|---------------|
| 13| GET | `/api/v1/keywords` | List all dictionary keywords | `super_admin`, `admin` |
| 14| POST | `/api/v1/keywords` | Add a new keyword | `super_admin`, `admin` |
| 15| PUT | `/api/v1/keywords/{id}` | Update keyword mapping | `super_admin`, `admin` |
| 16| DELETE | `/api/v1/keywords/{id}` | Delete keyword mapping | `super_admin`, `admin` |

### Dashboard & Analytics

| # | Method | Path | Description |
|---|--------|------|-------------|
| 17| GET | `/api/v1/dashboard/summary` | KPI cards (total batches, active jobs, success rate, failures) |
| 18| GET | `/api/v1/dashboard/analytics` | Rollup analytics on jobs and sentiments |
| 19| GET | `/api/v1/dashboard/batches` | Paginated batch list with search & status filter |
| 20| GET | `/api/v1/dashboard/batches/{id}` | Single batch detail with its jobs |
| 21| GET | `/api/v1/dashboard/jobs` | Global paginated job list across all batches |
| 22| GET | `/api/v1/dashboard/jobs/{id}/insights` | Processed verbatims mapped by product for the 'View' modal |

### Health

| # | Method | Path | Description |
|---|--------|------|-------------|
| — | GET | `/health` | Load balancer health check |

Swagger UI: http://localhost:8000/docs

---

## Authentication & Security Settings

The API uses **session-based authentication** with JWT tokens stored in HTTPOnly, secure cookies.

- **Login**: `POST /api/v1/auth/login` validates credentials (bcrypt) and sets a `pidilite_session_cookie`.
- **Environment Targeting**: Secure cookies are toggled depending on the `.env` file setting `ENVIRONMENT="production"`.
- **RBAC**: The `RoleChecker` dependency decodes the JWT and enforces per-resource role checks (`guest`, `admin`, `super_admin`).

| Resource | Allowed Roles |
|----------|---------------|
| `view_dashboard` | `super_admin`, `admin` |
| `manage_users` | `super_admin` |
| `manage_keywords` | `super_admin`, `admin` |
| `run_batch_jobs` | `super_admin`, `admin` |
| `view_jobs` | `super_admin`, `admin` |

---

## STT Error Handling

The STT submission endpoint (`/api/v1/files/transcription`) implements granular error handling
based on [Google's official error documentation](https://cloud.google.com/speech-to-text/docs/error-messages).

Each error is mapped to a specific exception class with a `retryable` flag:

| Error | Exception | Retryable | Job Status |
|-------|-----------|-----------|------------|
| Missing GCP credentials | `STTCredentialsError` | ❌ | FAILED |
| API not enabled (403) | `STTPermissionDeniedError` | ❌ | FAILED |
| Bad audio encoding | `STTBadEncodingError` | ❌ | FAILED |
| Multi-channel audio | `STTMultiChannelError` | ❌ | FAILED |
| Audio too long | `STTAudioTooLongError` | ❌ | FAILED |
| Payload too large | `STTPayloadTooLargeError` | ❌ | FAILED |
| Quota exceeded | `STTQuotaExhaustedError` | ✅ | ERROR → retry |
| Service unavailable | `STTUnavailableError` | ✅ | ERROR → retry |

Non-retryable errors mark the job as `FAILED` immediately (no wasted retries).
Retryable errors mark as `ERROR` with incremented `retry_count` — the checker
service will pick them up on the next cycle.

---

## Job & Batch Status Lifecycle

```
Job:    PENDING → BATCHED → STT_SUBMITTED → STT_COMPLETED → PROCESSING → COMPLETED
                                                                        ↘ ERROR (retryable) → retry → PENDING
                                                                        ↘ FAILED (terminal)

Batch:  PENDING → PROCESSING → COMPLETED | PARTIAL_SUCCESS | FAILED
```

---

## Database Schema

| Table | PK | Description |
|---|---|---|
| `users` | `user_id` | VPC form-login accounts (with role-based access) |
| `batches` | `id` | Groups of STT jobs |
| `jobs` | `id` | Central tracking — one per audio file |
| `file_details` | `job_id` (FK=PK) | Audio file metadata |
| `processed_file` | `job_id` (FK=PK) | STT output + normalized text |
| `insights` | `id` | Gemini-generated insights per job |
| `keyword_dictionary` | `canonical_id` | Term replacement rules |
| `app_config` | `key` | Runtime configuration |

---

## Quick Start

### 1. Prerequisites
```bash
# Install Poetry
curl -sSL https://install.python-poetry.org | python3 -

# Install dependencies and create virtualenv
poetry install
```

### 2. Environment setup
```bash
cp .env.example .env
# Edit .env with your GCP project, DB credentials, secret key
# Set ENVIRONMENT="production" for strict secure cookie behaviour
```

### 3. Local dev with Docker Compose
```bash
docker compose up --build

# In a separate terminal — run migrations and seed data
docker compose exec api poetry run alembic upgrade head
docker compose exec api poetry run python scripts/seed.py
```

### 4. Run directly (without Docker)
```bash
poetry run uvicorn services.api.main:app --reload --port 8000
```

### 5. Run tests
```bash
# Run the entire test suite comprehensively:
poetry run pytest tests/ -v
```

Tests use an in-memory SQLite database with GCP service mocks — no cloud
credentials or Postgres needed.

---

## Migrations

```bash
# Generate migration after model changes
poetry run alembic revision --autogenerate -m "describe change"

# Apply all pending migrations
poetry run alembic upgrade head

# Rollback one
poetry run alembic downgrade -1
```

---

## GCP Cloud Scheduler Configuration

| Job | Schedule | Target |
|---|---|---|
| Batch flush | `*/5 * * * *` | `POST {service-url}/api/v1/batch` |
| Checker | `*/15 * * * *` | `POST {service-url}/api/v1/checker/run` |

---

## Project Structure

```
pidilite/
├── core/                          Core shared modules
│   ├── config.py                  Pydantic settings with ENVIRONMENT flags
│   ├── dependencies.py            JWT cookie decoder + RoleChecker dependency
│   ├── enums.py                   JobStatus, BatchStatus, KeywordStatus, LogLevel
│   ├── exceptions.py              STT error hierarchy (10 exception classes)
│   ├── rbac.py                    Resource → role mapping table
│   ├── response.py                Unified API response envelope builder
│   └── security.py                Password hashing + session login/logout helpers
│
├── db/                            Database layer
│   ├── session.py                 SQLAlchemy engine + get_db dependency
│   ├── models.py                  All ORM models (8 tables)
│   └── crud.py                    Thin query helpers (legacy, mostly migrated)
│
├── repositories/                  Repository pattern (data access)
│   └── batch_repository.py        All job/batch/config CRUD operations
│
├── schemas/                       Pydantic request/response schemas
│   └── schemas.py                 Pipeline + dashboard endpoint schemas
│
├── services/
│   └── api/                       Single FastAPI service (port 8000)
│       ├── main.py                App entry point, middleware, router registration
│       └── routers/
│           ├── ingest.py          POST /api/v1/file
│           ├── batch.py           POST /api/v1/batch
│           ├── stt.py             POST /api/v1/files/transcription
│           ├── normalize.py       POST /api/v1/files/post-processing
│           ├── checker.py         POST /api/v1/checker/run
│           ├── auth.py            POST /api/v1/auth/login|logout
│           ├── dashboard.py       GET  /api/v1/dashboard/* (Analytics, Insights)
│           ├── keywords.py        GET|POST|PUT|DELETE /api/v1/keywords (CRUD)
│           └── users.py           GET|POST|PUT|DELETE /api/v1/users (CRUD)
│
├── tests/
│   ├── conftest.py                SQLite engine, GCP mocks, STT error fixtures
│   ├── test_api_v1.py             Pipeline endpoint + STT error handling tests
│   ├── test_dashboard_auth.py     Dashboard & authentication tests
│   ├── test_keywords.py           Keyword dictionary CRUD + RBAC tests
│   └── test_users.py              User CRUD + Role/Password tests
│
├── alembic/                       DB migrations
├── scripts/seed.py                Bootstrap seed data
├── docker-compose.yml             Local dev stack (Postgres + API)
├── Dockerfile                     Single-service container
├── pyproject.toml                 Poetry config
└── .env.example
```
