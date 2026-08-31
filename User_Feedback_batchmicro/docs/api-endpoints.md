# Pipeline API endpoints

Source: [`services/api/main.py`](../services/api/main.py) and routers under [`services/api/routers/`](../services/api/routers/).  
Schemas: [`schemas/schemas.py`](../schemas/schemas.py).  
Interactive OpenAPI: `http://localhost:8001/docs`.  
Postman: [postman/User_Feedback_Pipeline.postman_collection.json](postman/User_Feedback_Pipeline.postman_collection.json).

Cloud Run service `pidilite-pipeline-svc` (port **8001**). These endpoints are pipeline triggers (Eventarc, Cloud Scheduler, Cloud Tasks), not a public product API.

Sequence of calls: [batch-process-sequence.md](batch-process-sequence.md). Tables written by the pipeline: [db-schema.md](db-schema.md).

---

## Conventions

### Response envelope

Every `/api/v1/*` response uses:

```json
{
  "success": true,
  "message": "...",
  "data": {},
  "error": null,
  "timestamp": "2026-08-25T09:00:00+00:00",
  "request_id": "req_xxxxxxxxxxxx"
}
```

`GET /health` is not wrapped.

### HTTP status

Pipeline handlers usually return **200** even when a job is skipped, already processed, or not found. That stops Cloud Tasks from retrying a payload that will never succeed.

`success: false` in the envelope still often has HTTP 200. Treat `success` + `data.status` as the business result.

Unhandled exceptions return **500** (`{"detail": "Internal server error."}`).

### Auth

No application-level JWT or API key. Production access is Cloud Run IAM: Scheduler and Cloud Tasks send an OIDC token as the invoker service account. See [`scripts/configure-checker-scheduler.sh`](../scripts/configure-checker-scheduler.sh).

CORS allows **POST** only (`ALLOWED_ORIGINS`).

### Idempotency

Re-delivery is expected (Eventarc and Cloud Tasks). Duplicate ingest, duplicate STT-complete, and already-translated / already-completed jobs are skipped rather than rewound.

---

## Index

| Method | Path | Trigger | Purpose |
|--------|------|---------|---------|
| `GET` | `/health` | Ops / Cloud Run | Liveness |
| `POST` | `/api/v1/file` | Eventarc (input bucket finalize) | Register audio job |
| `POST` | `/api/v1/batch` | Cloud Scheduler | Claim `PENDING` jobs, enqueue STT |
| `POST` | `/api/v1/files/transcription` | Cloud Tasks | Submit Speech-to-Text LRO |
| `POST` | `/api/v1/files/stt-complete` | Eventarc (STT output bucket) | Enqueue translate |
| `POST` | `/api/v1/files/translate` | Cloud Tasks | Translate transcript (Gemini) |
| `POST` | `/api/v1/files/post-processing` | Cloud Tasks | Insights → `feedbacks` |
| `POST` | `/api/v1/checker/run` | Cloud Scheduler / ops | Recover stuck jobs, close batches |

Happy path: `file` → `batch` → `transcription` → `stt-complete` → `translate` → `post-processing`. Checker fills gaps.

---

## `GET /health`

Liveness. Not under `/api/v1`.

**Response**

```json
{ "status": "ok", "service": "pipeline" }
```

---

## `POST /api/v1/file`

Register a GCS upload as a `Job` + `FileDetails` with status `PENDING`. Duplicate `gs://` URIs return the existing job.

**Trigger:** Eventarc on `GCS_INPUT_BUCKET` `object.finalize`.

**Request** — GCS object JSON (`GCSObjectPayload`). Required: `name`. Bucket comes from `bucket` or `selfLink`.

```json
{
  "name": "audio/meeting-20260430.wav",
  "bucket": "pidilite-raw-audio",
  "contentType": "audio/wav",
  "size": "24567890",
  "md5Hash": "xrX0h3SqCoeoKidv+GvlBw==",
  "selfLink": "https://www.googleapis.com/storage/v1/b/pidilite-raw-audio/o/audio%2Fmeeting-20260430.wav",
  "metadata": {
    "state": "Maharashtra",
    "division": "West",
    "zone": "Mumbai",
    "cluster": "C1",
    "rbdm_cluster": "R1",
    "town_city": "Mumbai",
    "tsi_territory_code": "TSI01",
    "fme_code": "FME01",
    "tty_code": "TTY01",
    "user_id": "emp-123",
    "user_type": "TSI",
    "data_source": "Voice Conversations"
  }
}
```

`metadata` is copied onto `file_details` (dashboard filters). `rbdm_cluster` falls back to `rfmm_cluster`. `data_source` defaults to `Voice Conversations`.

**Accepted extensions:** `webm`, `mp3`, `wav`, `ogg`. Anything else creates the job as `FAILED` and a `failed_jobs` row (`pipeline_stage=INGEST`).

**Response `data`**

| Field | Type | Notes |
|-------|------|--------|
| `job_id` | string | UUID |
| `file_name` | string | Basename of `name` |
| `gcs_input_uri` | string | `gs://{bucket}/{name}` |
| `status` | string | `PENDING` or `FAILED` |

Messages: `File ingested successfully` · `File already ingested` · `File rejected due to unsupported format`.

---

## `POST /api/v1/batch`

Claim `PENDING` jobs (`FOR UPDATE SKIP LOCKED`), chunk by `app_config.batch_size` (fallback `BATCH_SIZE`, default 10), set jobs to `BATCHED`, enqueue Cloud Tasks to `/api/v1/files/transcription`.

**Trigger:** Cloud Scheduler (OIDC). **Body:** none.

Each STT task payload uses `language_code: "hi-IN"` and `model: "telephony"`. Output prefix: `gs://{GCS_OUTPUT_BUCKET}/stt-output/{job_id}/`.

Enqueue failure marks that job `ERROR` (checker can retry).

**Response `data`**

| Field | Type | Notes |
|-------|------|--------|
| `batch_id` | string | Last batch created; `""` if nothing to flush |
| `jobs_enqueued` | int | Tasks created this run (all batches) |

Empty queue: `No pending jobs to batch`.

---

## `POST /api/v1/files/transcription`

Submit one audio file to Cloud Speech-to-Text v2 (async BatchRecognize). Stores `stt_operation_name`, sets status `STT_SUBMITTED`.

**Trigger:** Cloud Tasks (`CLOUD_TASKS_CALLBACK_URL`). Eligible job statuses: `BATCHED`, `ERROR`.

**Request** (`STTSubmitRequest`)

```json
{
  "job_id": "uuid",
  "gcs_input_uri": "gs://pidilite-raw-audio/audio/meeting.wav",
  "gcs_output_uri_prefix": "gs://pidilite-stt-output/stt-output/{job_id}/",
  "batch_id": "optional",
  "language_code": "hi-IN",
  "model": "telephony"
}
```

**Guards (non-retryable `FAILED`)**

- File size &lt; 100 bytes
- MIME type not `audio/*` or `video/*`

**STT errors:** retryable → `ERROR` + `retry_count++`; non-retryable (credentials, 403, bad encoding, multi-channel, too long) → `FAILED`. Both write `failed_jobs` (`pipeline_stage=STT`).

Missing job or wrong status: HTTP 200, skip (`NOT_FOUND` or current status).

**Response `data`**

| Field | Type | Notes |
|-------|------|--------|
| `job_id` | string | |
| `status` | string | `STT_SUBMITTED`, `ERROR`, `FAILED`, `NOT_FOUND`, or skipped status |
| `stt_operation_name` | string \| null | LRO name on success |

---

## `POST /api/v1/files/stt-complete`

STT JSON landed in the output bucket. Record `gcs_stt_output_uri`, set `TRANSLATING`, enqueue `/api/v1/files/translate`.

**Trigger:** Eventarc on `GCS_OUTPUT_BUCKET`. **Request:** same GCS object JSON as ingest. `job_id` is parsed from the object path (`stt-output/{job_id}/...`).

**Allowed statuses:** `STT_SUBMITTED`, `STT_COMPLETED`, `ERROR` (unless translation already exists). Downstream statuses (`TRANSLATING` … `COMPLETED`) are ignored so Eventarc cannot rewind the job.

**Response `data`** (`SttCompleteResponseData`)

| Field | Type | Notes |
|-------|------|--------|
| `job_id` | string | `"unknown"` if path parse fails |
| `status` | string | New or skipped status |
| `action` | string | `enqueued_translate` · `skipped` · `enqueue_failed` |
| `previous_status` | string \| null | |
| `skip_reason` | string \| null | |
| `cloud_task_name` | string \| null | |
| `gcs_stt_output_uri` | string \| null | |

Task creation failure → job `ERROR`, `success: false`.

---

## `POST /api/v1/files/translate`

Read STT JSON from GCS (or cached `raw_transcript_text`), translate to English with Vertex Gemini, save `processed_file`, set `TRANSLATED`, enqueue `/api/v1/files/post-processing`.

**Trigger:** Cloud Tasks (`CLOUD_TASKS_TRANSLATE_URL`). Eligible: `TRANSLATING`, `STT_COMPLETED`, `ERROR`.

**Request** (`TranslateRequest`)

```json
{
  "job_id": "uuid",
  "gcs_transcript_uri": "gs://pidilite-stt-output/stt-output/{job_id}/output.json"
}
```

If `translated_text` already exists, Vertex is skipped (`action: idempotent`) and post-processing is enqueued. Empty transcript → `ERROR`.

**Response `data`** (`TranslateResponseData`)

| Field | Type | Notes |
|-------|------|--------|
| `job_id` | string | |
| `status` | string | |
| `action` | string | `translated` · `idempotent` · `skipped` · `failed` · `enqueue_failed` |
| `previous_status` | string \| null | |
| `skip_reason` | string \| null | |
| `cloud_task_name` | string \| null | |
| `translated_chars` | int \| null | |
| `raw_transcript_chars` | int \| null | |

---

## `POST /api/v1/files/post-processing`

Generate Gemini insights from `processed_file.translated_text`, write `feedbacks` / tags / competitors, set job `COMPLETED`.

**Trigger:** Cloud Tasks (`CLOUD_TASKS_POSTPROCESS_URL`). Eligible: `TRANSLATED`, `PROCESSING`, `NORMALIZED`, `INSIGHTS`, `ERROR`. Already `COMPLETED` is a no-op.

**Request** (`PostProcessRequest`)

```json
{ "job_id": "uuid" }
```

Requires `translated_text`. Existing feedback rows short-circuit to `COMPLETED`. PDT-group insights without a master-catalog product are skipped. Raw LLM payload is stored in `processed_file.insights_raw_json`.

**Response `data`**

| Field | Type | Notes |
|-------|------|--------|
| `job_id` | string | |
| `status` | string | `COMPLETED`, `ERROR`, `NOT_FOUND`, or skipped status |
| `insights_generated` | bool | True if at least one `feedbacks` row exists |

---

## `POST /api/v1/checker/run`

Recovery pass. Typical schedule: every 15 minutes ([`scripts/configure-checker-scheduler.sh`](../scripts/configure-checker-scheduler.sh)). Re-enqueue is age-gated by `STUCK_JOB_RECOVERY_MINUTES` (default 10). `ERROR` jobs retry until `MAX_RETRY_COUNT` (default 2), then `FAILED`.

**Trigger:** Cloud Scheduler. **Request** optional:

```json
{ "max_jobs_to_check": 50 }
```

`max_jobs_to_check`: 1–500, default 50.

**Steps (in order)**

1. Poll STT LROs (`STT_SUBMITTED`)
2. Kick `STT_COMPLETED` jobs into translate
3. Recover stuck `BATCHED` (never got an STT task)
4. Re-enqueue translate for stuck `TRANSLATING`
5. Recover stuck `TRANSLATED` (no post-processing)
6. Re-enqueue post-processing for `PROCESSING` / `NORMALIZED` / `INSIGHTS`
7. Retry or fail `ERROR` jobs
8. Close `PROCESSING` batches (`COMPLETED` / `PARTIAL_SUCCESS` / `FAILED`)

**Response `data`** (`CheckerRunResponseData`)

| Field | Type |
|-------|------|
| `jobs_checked` | int |
| `jobs_recovered` | int |
| `jobs_marked_failed` | int |
| `jobs_still_pending` | int |
| `stt_lro_polled` | int |
| `stt_lro_completed` | int |
| `stt_lro_errored` | int |
| `translate_kicked` | int |
| `translate_kick_skipped_no_uri` | int |
| `stuck_batched_recovered` | int |
| `stuck_translating_recovered` | int |
| `stuck_translated_recovered` | int |
| `stuck_post_processing_recovered` | int |
| `batches_reconciled` | int |

---

## Job status flow

```
PENDING
  → BATCHED
  → STT_SUBMITTED
  → STT_COMPLETED          (checker LRO poll; Eventarc may skip this)
  → TRANSLATING
  → TRANSLATED
  → PROCESSING / NORMALIZED / INSIGHTS   (legacy / in-flight)
  → COMPLETED

ERROR   → retry (checker) or FAILED after MAX_RETRY_COUNT
FAILED  → terminal (ingest rejection, non-retryable STT, exhausted retries)
```

Full enum meanings: [db-schema.md](db-schema.md#jobstatus-jobsstatus).

---

## Env vars that point at these URLs

| Variable | Endpoint |
|----------|----------|
| `CLOUD_TASKS_CALLBACK_URL` | `POST /api/v1/files/transcription` |
| `CLOUD_TASKS_TRANSLATE_URL` | `POST /api/v1/files/translate` |
| `CLOUD_TASKS_POSTPROCESS_URL` | `POST /api/v1/files/post-processing` |
