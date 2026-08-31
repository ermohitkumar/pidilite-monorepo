# Batch process sequence

End-to-end flow for the Pidilite user-feedback pipeline: GCS audio ingest through batch orchestration, Speech-to-Text, translation, and Gemini insights.

HTTP contracts for each step: [api-endpoints.md](api-endpoints.md).

## Participants

| Actor | Role |
|-------|------|
| Uploader | Client / field app uploading audio to GCS |
| GCS Input | Raw audio bucket (`GCS_INPUT_BUCKET`) |
| Eventarc | GCS `object.finalize` → HTTP to Cloud Run |
| Pipeline API | This service (`:8001`) |
| Postgres | Jobs, batches, transcripts, feedback |
| Cloud Scheduler | Periodic `/batch` and `/checker/run` |
| Cloud Tasks | Per-job HTTP callbacks (STT, translate, post-process) |
| Cloud Speech | Long-running recognize (LRO) |
| GCS STT Output | Transcript JSON bucket (`GCS_OUTPUT_BUCKET`) |
| Vertex Gemini | Translate + insights generation |

## Sequence diagram

![Batch process sequence](assets/batch-process-sequence.png)

<details>
<summary>Mermaid source</summary>

```mermaid
sequenceDiagram
    autonumber
    participant Uploader
    participant GCSIn as GCS Input
    participant Eventarc
    participant API as Pipeline API
    participant DB as Postgres
    participant Sched as Cloud Scheduler
    participant CT as Cloud Tasks
    participant STT as Cloud Speech
    participant GCSOut as GCS STT Output
    participant Vertex as Vertex Gemini

    Note over Uploader,Vertex: 1. Ingest
    Uploader->>GCSIn: Upload audio (+ object metadata)
    GCSIn->>Eventarc: object.finalize
    Eventarc->>API: POST /api/v1/file
    API->>DB: Create Job (PENDING) + FileDetails
    API-->>Eventarc: 200 { job_id, status: PENDING }

    Note over Sched,CT: 2. Batch orchestration
    Sched->>API: POST /api/v1/batch (OIDC)
    API->>DB: Select PENDING jobs (BATCH_SIZE)
    API->>DB: Create Batch (PROCESSING), jobs → BATCHED
    API->>CT: Enqueue POST /api/v1/files/transcription
    API-->>Sched: 200 { batch_id, jobs_enqueued }

    Note over CT,STT: 3. Speech-to-Text
    CT->>API: POST /api/v1/files/transcription
    API->>STT: long_running_recognize
    API->>DB: Job → STT_SUBMITTED
    API-->>CT: 200 { job_id, stt_operation_name }

    STT->>GCSOut: Write stt-output/{job_id}/output.json
    GCSOut->>Eventarc: object.finalize
    Eventarc->>API: POST /api/v1/files/stt-complete
    API->>DB: Job → TRANSLATING
    API->>CT: Enqueue POST /api/v1/files/translate
    API-->>Eventarc: 200 { action: enqueued_translate }

    Note over CT,Vertex: 4. Translate
    CT->>API: POST /api/v1/files/translate
    API->>GCSOut: Read STT JSON
    API->>Vertex: translate_transcript
    API->>DB: ProcessedFile + Job → TRANSLATED
    API->>CT: Enqueue POST /api/v1/files/post-processing
    API-->>CT: 200 { action: translated }

    Note over CT,Vertex: 5. Insights / post-processing
    CT->>API: POST /api/v1/files/post-processing
    API->>Vertex: generate_insights (product catalog)
    API->>DB: Insert Feedback (+ tags, competitors)
    API->>DB: Job → COMPLETED
    API-->>CT: 200 { insights_generated: true }

    Note over Sched,API: 6. Recovery (safety net)
    Sched->>API: POST /api/v1/checker/run
    API->>STT: Poll stuck LROs (optional)
    API->>DB: Retry ERROR / kick missed stages / reconcile Batch
    API-->>Sched: 200 { jobs_recovered, jobs_marked_failed, ... }
```

</details>

## Job status progression

```
PENDING
  → BATCHED
  → STT_SUBMITTED
  → STT_COMPLETED
  → TRANSLATING
  → TRANSLATED
  → PROCESSING / NORMALIZED / INSIGHTS
  → COMPLETED

ERROR  → (checker retries up to MAX_RETRY_COUNT) → FAILED
```

## Batch statuses

After checker reconciliation, a `Batch` ends as:

- `COMPLETED` — all jobs succeeded
- `PARTIAL_SUCCESS` — mix of success and failure
- `FAILED` — no successful jobs

## Triggers summary

| Step | Trigger | Endpoint |
|------|---------|----------|
| Ingest | Eventarc on input bucket | `POST /api/v1/file` |
| Batch | Cloud Scheduler | `POST /api/v1/batch` |
| STT submit | Cloud Tasks | `POST /api/v1/files/transcription` |
| STT done | Eventarc on output bucket | `POST /api/v1/files/stt-complete` |
| Translate | Cloud Tasks | `POST /api/v1/files/translate` |
| Insights | Cloud Tasks | `POST /api/v1/files/post-processing` |
| Checker | Cloud Scheduler / ops | `POST /api/v1/checker/run` |
