# Architecture change request: Gemini Flash speech-to-text

**Service:** User Feedback pipeline (`pidilite-pipeline-svc`)  
**Duration:** 2 weeks development (plus a short production soak after the flag is turned on)  
**Default after deploy:** current Cloud Speech-to-Text v2 (no behaviour change until `STT_PROVIDER` is flipped)

Related sequence today: [batch-process-sequence.md](batch-process-sequence.md). Endpoint contracts: [api-endpoints.md](api-endpoints.md).

---

## Brief current scope

The live product turns **field call recordings** into **tagged English feedback**.

| In scope today | What it does |
|----------------|--------------|
| Upload | Audio lands in `gs://pidilite-raw-audio`. Eventarc registers a job (`POST /api/v1/file`). |
| Batch | Cloud Scheduler `POST /api/v1/batch` groups `PENDING` jobs and enqueues Cloud Tasks. |
| Speech-to-text | `POST /api/v1/files/transcription` submits **async** Cloud Speech-to-Text **v2 `telephony`** in `asia-south1`. Checker polls the LRO. Output JSON is `gs://pidilite-processed-text/stt-output/{job_id}/output.json`. |
| Translate | Eventarc `POST /api/v1/files/stt-complete` → Gemini translates to English and labels **FME** / **User**. |
| Insights | `POST /api/v1/files/post-processing` tags product / user / dealer feedback. |
| Recover | Cloud Scheduler `POST /api/v1/checker/run` every 15 minutes: poll STT LROs, retry `ERROR` up to `MAX_RETRY_COUNT` (2), recover stuck `BATCHED` / `TRANSLATED` jobs. |
| Website / Power BI | Read the same feedbacks. Unchanged by this CR. |

**Limits of current STT (why this CR exists):** v2 is configured with **one** language (`hi-IN`) and **no diarization** (telephony in this region often collapses speakers or only tags the last window). Mixed Hindi / Marathi / Gujarati / Hinglish and multi-speaker site calls are weak. Speaker roles are guessed later at translate time.

**Out of original STT scope:** using Gemini to transcribe audio, a second Cloud Tasks queue, multilingual STT, or `Speaker 1…N` on the raw transcript.

---

## Why this is a change request

Pidilite wants **Gemini Flash** as an optional speech-to-text engine that:

- Runs **asynchronously** (must not block the existing `/transcription` Cloud Task).
- Scales via a **dedicated queue** with a concurrency cap.
- Retries **transient** failures **3 times**, then **falls back** to current Speech v2 so jobs still complete.
- Labels **two or more speakers** on the raw transcript.
- Handles **multi-regional** / code-switched Indian languages at transcribe time.

**Downstream output must stay the same:** English `FME:` / `User:` conversation, tagged feedbacks, dashboard and Power BI. Extra speakers’ words are kept, then mapped into those two roles.

This is not a prompt-only tweak. It adds a worker endpoint, a queue, a GCS JSON variant, checker rules, and a production flag.

---

## Target architecture

```
STT_PROVIDER=speech_v2 (default)
  POST /transcription → Speech v2 LRO → same output.json → Eventarc /stt-complete → translate → insights

STT_PROVIDER=gemini_flash
  POST /transcription (fast) → enqueue pidilite-gemini-stt-queue
       → POST /files/gemini-stt (Gemini Flash on gs:// audio)
            success → write same output.json → existing Eventarc path
            429 / 5xx / timeout / empty / MAX_TOKENS → Cloud Tasks retry (max 3)
            3rd failure → submit Speech v2 LRO (current fallback) → existing checker path
```

| Layer | Today | After this CR |
|-------|--------|----------------|
| Dispatcher | `/transcription` always calls Speech v2 | Same URL; if Flash is on, **only enqueues** Gemini STT task and sets sentinel `stt_operation_name=gemini-flash:{job_id}` |
| Heavy work | Speech LRO (async) | Gemini on **`pidilite-gemini-stt-queue`**; v2 unchanged as fallback |
| Transcript file | Cloud STT JSON `results[]` | Same GCS path; Flash writes `{ provider, model, transcript }` |
| Translate / insights | Unchanged URLs | Unchanged URLs; translate prompt allows **N speakers → two roles** |
| Reports | Unchanged | Unchanged |

---

## Security

| Control | Requirement |
|---------|-------------|
| Auth | New `/files/gemini-stt` is **internal only**, same as `/transcription`: Cloud Tasks **OIDC** as `cloud-run-api@…`, Cloud Run invoker IAM. No public unauthenticated invoke. |
| Identity | Reuse existing invoker SA. Do not mint user tokens. |
| Data path | Audio stays in `gs://pidilite-raw-audio`. Gemini is called in **`asia-south1`** with `fileData.fileUri` (no extra copy of audio to a third bucket). Transcripts stay in `gs://pidilite-processed-text`. |
| Secrets | New settings via Secret Manager. CI `--set-secrets` must list **every existing secret plus new ones** (never `--set-env-vars` that drops DB/GCS secrets). |
| Vertex | Same project, location, and safety settings as translate/insights (`thinkingBudget: 0`). Pipeline SA already used for Gemini must be allowed to **read** input GCS objects (same as Speech). |
| PII | Field calls remain in GCP; no new egress. Logs: job id, provider, token counts — **not** full transcripts. |
| Idempotency | Worker returns **200** for unknown/already-done jobs so Cloud Tasks does not retry forever (same pattern as `/transcription`). |

---

## Retries

Two separate counters. Do **not** raise global `MAX_RETRY_COUNT` (stays **2** for translate / insights).

| Mechanism | What it covers | Max | Then |
|-----------|----------------|-----|------|
| Cloud Tasks on `pidilite-gemini-stt-queue` | 429, 5xx, timeout, empty Gemini text, `MAX_TOKENS` | **3** attempts (`X-CloudTasks-TaskRetryCount` 0, 1, 2) | On the **3rd** failure: submit Speech v2, return **200** so Tasks stops |
| Job `retry_count` + checker | Speech LRO errors, translate, insights (as today) | `MAX_RETRY_COUNT` = 2 | `FAILED` |
| Worker HTTP | Transient Flash | Return **503** so Tasks retries | — |
| Worker HTTP | Non-retryable audio (bad encoding, empty file, wrong mime) | Return **200**, job `FAILED` | No Flash retry, no v2 if the file is unusable |

Exponential backoff on the Gemini queue (Cloud Tasks retry config). Existing `pidilite-worker-queue` retry behaviour for `/transcription` / translate / post-processing is **unchanged**.

---

## Error handling

| Failure | Job status | Who recovers |
|---------|------------|--------------|
| Flash enqueue fails | `ERROR`, retryable | Checker re-enqueues `/transcription` (dispatcher) after age gate |
| Flash 429 / 503 / timeout / empty | Tasks retry (up to 3) | Queue |
| Flash still failing on 3rd attempt | Speech v2 LRO name stored, `STT_SUBMITTED` | Checker polls v2 as today |
| v2 LRO error | `ERROR` + `retry_count++` | Checker, then `FAILED` at max |
| GCS transcript written | Eventarc `/stt-complete` | Same as today |
| Eventarc missed | `STT_COMPLETED` with URI | Checker kicks translate |
| Gemini `MAX_TOKENS` on a very long file | Treated as transient until attempt 3, then **v2 fallback** (v2 already handles long files) | No audio chunking in this CR |

Non-retryable STT exceptions stay as in [`stt.py`](../services/api/routers/stt.py) (`STTBadEncodingError`, credentials, etc.).

---

## Stuck jobs (how they are managed)

Checker (`POST /api/v1/checker/run`, every 15 minutes) plus Cloud Tasks. Age gate: `STUCK_JOB_RECOVERY_MINUTES` (default **10**).

| Symptom | Detection | Action |
|---------|-----------|--------|
| `STT_SUBMITTED` + `gemini-flash:{id}` and **no** Speech LRO | Checker **must not** call Speech `get_operation` | If `output.json` exists → `STT_COMPLETED`. If missing after age gate and 3 Task attempts are exhausted → **submit v2** (same fallback as the worker). |
| `STT_SUBMITTED` + real Speech LRO | Existing LRO poll | Existing complete / error path |
| `STT_SUBMITTED` forever (queue drained, no blob, no v2) | Age gate | Checker submits v2 |
| `BATCHED` with no `stt_operation_name` | Existing `_recover_stuck_batched_jobs` | Re-enqueue `/transcription` |
| `STT_COMPLETED` no translate | Existing kick | Enqueue translate |
| `ERROR` | Existing `_retry_error_jobs` | Re-enqueue the right stage; `FAILED` after `MAX_RETRY_COUNT` |
| Gemini queue backlog | Queue **max concurrent dispatches** (5–10) | Jobs stay `STT_SUBMITTED` until a worker slot opens — not stuck; do not flip to v2 until retries + age gate |

Operators: Monitor job status + `stt_operation_name` prefix and Cloud Tasks queue depth. Dashboard failed-files view is unchanged.

---

## Specific changes

### New

| Item | Detail |
|------|--------|
| Queue | `pidilite-gemini-stt-queue` in `asia-south1`: OIDC, `max_attempts=3`, dispatch deadline ~15 min, concurrency cap |
| Endpoint | `POST /api/v1/files/gemini-stt` in a new router (or `stt.py`) |
| Client | New `services/shared/gemini_stt.py` — Vertex `generateContent` with `fileData.fileUri` |
| Script | Queue create/update script next to `scripts/configure-checker-scheduler.sh` |

### Config (`core/config.py` + Secret Manager + CI-CD `--set-secrets`)

- `STT_PROVIDER` — `speech_v2` (default) or `gemini_flash`
- `STT_FALLBACK_PROVIDER` — `speech_v2`
- `GEMINI_STT_MODEL` — default `gemini-2.5-flash`
- `GEMINI_STT_TIMEOUT_SECONDS` — default `540`
- `CLOUD_TASKS_GEMINI_STT_QUEUE` — default `pidilite-gemini-stt-queue`
- `CLOUD_TASKS_GEMINI_STT_URL` — `…/api/v1/files/gemini-stt`

### Existing files (must change)

| File | Change |
|------|--------|
| [`services/api/routers/stt.py`](../services/api/routers/stt.py) | If Flash: enqueue Gemini queue, set sentinel, return 200. If `speech_v2`: current `submit_batch_recognize` only. |
| [`services/shared/cloud_tasks.py`](../services/shared/cloud_tasks.py) | Optional `queue` + `dispatch_deadline`; existing callers unchanged. |
| [`services/shared/transcript.py`](../services/shared/transcript.py) | If JSON `provider == "gemini_flash"`, return `transcript` string. Cloud STT `results[]` unchanged. |
| [`services/api/routers/checker.py`](../services/api/routers/checker.py) | Skip Speech poll for `gemini-flash:`; blob present → complete; stuck with no blob → v2 fallback. |
| [`services/shared/stt_client.py`](../services/shared/stt_client.py) | v2 `language_codes` = primary + `alternative_language_codes` (up to 4). **Do not** enable v2 diarization. |
| [`services/shared/vertex_ai.py`](../services/shared/vertex_ai.py) | Translate/relabel: **two roles**, not two people; Speaker 3+ → `User:`; multilingual source. |
| [`services/shared/speakers.py`](../services/shared/speakers.py) | Tests: Speaker 3 words survive as `User:`. |
| [`services/api/main.py`](../services/api/main.py) | Register Gemini STT router. |
| [`schemas/schemas.py`](../schemas/schemas.py) | Request body for `/files/gemini-stt`. |
| [`.github/workflows/CI-CD.yaml`](../.github/workflows/CI-CD.yaml) | New secrets; Cloud Run request timeout **≥ 15 minutes** (Gemini worker only; dispatcher stays short). |
| Tests | `test_gemini_stt.py`, checker sentinel tests, transcript Gemini JSON, v2 language list, `test_api_v1.py` still green with default `speech_v2`. |

### Unchanged (pipeline end output)

Ingest, `/batch`, `/stt-complete`, `/translate`, `/post-processing`, insights taxonomy, dashboard, Power BI views, `output.json` **path**.

GCS Flash payload (same object name as today):

```json
{
  "provider": "gemini_flash",
  "model": "gemini-2.5-flash",
  "transcript": "Speaker 1: ...\nSpeaker 2: ...\nSpeaker 3: ...",
  "detected_languages": []
}
```

---

## Activities (2 weeks)

Assumes one developer familiar with this repo. Infra (queue + secrets) on day 1 so coding is not blocked.

### Week 1 — build behind the flag (`STT_PROVIDER=speech_v2`)

| Day | Activities |
|-----|------------|
| 1 | Create queue + secrets (OIDC, retry 3, concurrency cap). Add config fields. Extend `enqueue_http_task`. Document IAM: Cloud Run SA can read raw audio for Vertex. |
| 2–3 | Implement `gemini_stt.py` (prompt: multilingual, `Speaker 1…N`, no translation). Write GCS JSON. Unit tests with mocked Vertex. |
| 4 | `POST /files/gemini-stt`: 200 success / v2 fallback on 3rd attempt; 503 transient; 200 skip unknown job. Wire `/transcription` enqueue-only when Flash is on. |
| 5 | `transcript.py` dual format. Checker: never Speech-poll Flash sentinels. Tests. Deploy to develop with flag still `speech_v2` (prod behaviour unchanged). |

### Week 2 — recovery, languages, speakers, prove E2E

| Day | Activities |
|-----|------------|
| 6 | Stuck-job path: missing blob after age gate → submit v2. Align `FailedJob` / pipeline notes. |
| 7 | Translate/relabel for N speakers; v2 alternative language codes. Tests for 3-speaker raw → `User:` in English. |
| 8 | Cloud Run timeout; queue dispatch deadline. Security pass: OIDC, secret list, log hygiene. |
| 9 | Flip `STT_PROVIDER=gemini_flash` on develop. Run `scripts/run_gcs_samples.py` on `samples/test01` (long file + mixed language). Confirm COMPLETED + feedbacks; raw `Speaker N`; English only `FME`/`User`. Confirm a forced Flash failure falls back to v2. |
| 10 | Fix gaps, buffer, runbook (flag on/off, queue metrics, stuck-job playbook). Production deploy still default `speech_v2` until soak is signed off. |

### After week 2 (not in the 10-day build)

Production flag flip, 1–2 day soak, rollback = set `STT_PROVIDER=speech_v2`.

---

## Acceptance criteria

1. With `STT_PROVIDER=speech_v2`, existing tests and a sample batch match today’s STT path.
2. With `STT_PROVIDER=gemini_flash`, `/transcription` returns quickly and does not call Vertex itself.
3. Flash transients retry at most **3** times; then Speech v2 runs; job can still `COMPLETED`.
4. Checker never calls Speech `get_operation` for `gemini-flash:` names.
5. Raw transcript may have **more than two** `Speaker N` lines; English output is still only **FME** and **User**; extra speakers’ content is not dropped.
6. Insights and reports consume the same fields as today.
7. Rollback is a config change only.

---

## Out of scope

- Splitting long audio into chunks (v2 fallback covers `MAX_TOKENS`).
- Turning on Cloud Speech diarization.
- Changing insights prompts, tag taxonomy, or report schemas.
- Frontend / dashboard UI work.
