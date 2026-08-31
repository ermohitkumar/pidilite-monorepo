"""Shared Cloud Tasks enqueue helper."""
import json
import logging
from urllib.parse import urlparse

from core.config import settings

logger = logging.getLogger(__name__)

try:
    from google.cloud import tasks_v2
    _HAS_CLOUD_TASKS = True
except ImportError:
    _HAS_CLOUD_TASKS = False


def _oidc_audience_for_url(url: str) -> str:
    if settings.CLOUD_RUN_SERVICE_AUDIENCE:
        return settings.CLOUD_RUN_SERVICE_AUDIENCE
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def enqueue_http_task(
    *,
    url: str,
    payload: dict,
    queue: str | None = None,
    dispatch_deadline_seconds: int | None = None,
) -> str | None:
    """
    Create one HTTP Cloud Task targeting Cloud Run.

    When CLOUD_TASKS_USE_OIDC is true (production default), attaches an OIDC token so
    private Cloud Run accepts the request. This is required by Google Cloud when the
    service does not allow unauthenticated invocation — it is not optional for
    internal pipeline callbacks (/transcription, /translate, /post-processing).

    Returns the task resource name, or None if skipped (local dev without SDK).
    """
    job_id = payload.get("job_id")
    queue_name = queue or settings.CLOUD_TASKS_QUEUE

    if not _HAS_CLOUD_TASKS:
        logger.warning(
            "Cloud Tasks SDK not available — skipped enqueue job_id=%s url=%s queue=%s",
            job_id, url, queue_name,
        )
        return None

    if not url:
        raise ValueError("Cloud Tasks callback URL is not configured")
    if not settings.GCP_PROJECT_ID or not settings.GCP_LOCATION:
        raise ValueError("GCP_PROJECT_ID and GCP_LOCATION must be set for Cloud Tasks")

    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(
        settings.GCP_PROJECT_ID,
        settings.GCP_LOCATION,
        queue_name,
    )

    http_request: dict = {
        "http_method": tasks_v2.HttpMethod.POST,
        "url": url,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload).encode(),
    }

    use_oidc = settings.CLOUD_TASKS_USE_OIDC
    if use_oidc:
        invoker_sa = settings.cloud_tasks_invoker_service_account
        if not invoker_sa:
            raise ValueError(
                "CLOUD_TASKS_INVOKER_SA or GCP_PROJECT_ID must be set when CLOUD_TASKS_USE_OIDC=true"
            )
        audience = _oidc_audience_for_url(url)
        http_request["oidc_token"] = {
            "service_account_email": invoker_sa,
            "audience": audience,
        }
        auth_mode = f"oidc({invoker_sa})"
    else:
        auth_mode = "none (requires Cloud Run to allow unauthenticated invoke)"
        logger.warning(
            "Cloud Task job_id=%s url=%s: OIDC disabled — only valid for public Cloud Run",
            job_id, url,
        )

    task: dict = {"http_request": http_request}
    if dispatch_deadline_seconds:
        from google.protobuf import duration_pb2

        deadline = duration_pb2.Duration()
        deadline.seconds = int(dispatch_deadline_seconds)
        task["dispatch_deadline"] = deadline
    created = client.create_task(request={"parent": parent, "task": task})
    task_name = created.name
    logger.info(
        "Cloud Task created: name=%s queue=%s url=%s job_id=%s auth=%s",
        task_name, queue_name, url, job_id, auth_mode,
    )
    return task_name


def enqueue_gemini_stt_task(payload: dict) -> str | None:
    """Enqueue the long-running Gemini Flash STT worker on its dedicated queue."""
    url = settings.gemini_stt_callback_url
    if not url:
        raise ValueError(
            "Gemini STT callback URL is not configured "
            "(set CLOUD_TASKS_GEMINI_STT_URL or CLOUD_TASKS_CALLBACK_URL)"
        )
    return enqueue_http_task(
        url=url,
        payload=payload,
        queue=settings.CLOUD_TASKS_GEMINI_STT_QUEUE,
        dispatch_deadline_seconds=settings.GEMINI_STT_DISPATCH_DEADLINE_SECONDS,
    )
