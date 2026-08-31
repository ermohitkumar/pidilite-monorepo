"""GCS path helpers for the audio pipeline."""
from core.config import settings


def build_stt_output_gcs_uri(job_id: str, bucket: str | None = None) -> str:
    """Canonical STT JSON path: gs://{bucket}/stt-output/{job_id}/output.json"""
    b = bucket or settings.GCS_OUTPUT_BUCKET
    return f"gs://{b}/stt-output/{job_id}/output.json"
