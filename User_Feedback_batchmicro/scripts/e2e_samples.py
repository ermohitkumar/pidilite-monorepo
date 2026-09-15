#!/usr/bin/env python3
"""
End-to-end sample runner: upload samples/*.mp3 → ingest → batch → STT →
translate → post-processing.

Drives the HTTP API directly (simulates Eventarc / Cloud Tasks). Requires:
  - API at BASE_URL (default http://localhost:8001)
  - GCP ADC / credentials for GCS upload + Speech-to-Text + Vertex
  - .env with GCS_INPUT_BUCKET / GCS_OUTPUT_BUCKET / GCP_PROJECT_ID

Usage:
  poetry run python scripts/e2e_samples.py
  poetry run python scripts/e2e_samples.py --limit 1 --language-code hi-IN
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.config import settings  # noqa: E402
from services.shared.gcs_paths import build_stt_output_gcs_uri  # noqa: E402

SAMPLES_DIR = ROOT / "samples"
DEFAULT_PREFIX = "e2e-samples"

from services.shared.filename_metadata import parsed_to_file_fields, parse_audio_filename  # noqa: E402

# Fallback ingest metadata when the filename is not the M-Power visit pattern.
DEFAULT_METADATA = {
    "division": "Consumer",
    "zone": "West",
    "rfmm_cluster": "E2E-Cluster",
    "rbdm_cluster": "E2E-Cluster",
    "cluster": "E2E-Cluster",
    "fme_code": "E2E001",
    "user_type": "FME",
    "state": "Maharashtra",
    "town_city": "Mumbai",
    "tsi_territory_code": "TSI-E2E",
    "tty_code": "TTY-E2E",
    "user_id": "e2e-user-001",
    "data_source": "e2e_samples",
}


def _metadata_for_file(path: Path) -> dict:
    parsed = parse_audio_filename(path.name)
    if not parsed:
        return dict(DEFAULT_METADATA)
    fields = parsed_to_file_fields(parsed)
    meta = {k: v for k, v in fields.items() if k != "call_date" and v is not None}
    if parsed.get("saved_epoch"):
        meta["saved_epoch"] = parsed["saved_epoch"]
    meta["data_source"] = "test02"
    return {k: str(v) for k, v in meta.items()}


def _content_type(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".webm": "audio/webm",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".mp3": "audio/mpeg",
    }.get(ext, "application/octet-stream")


def _http_json(
    method: str,
    url: str,
    body: dict | None = None,
    timeout: int = 300,
    extra_headers: dict | None = None,
) -> dict:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    # Optional Cloud Run auth: E2E_ID_TOKEN or gcloud identity token via helper
    token = os.getenv("E2E_ID_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"{method} {url} → HTTP {exc.code}: {detail[:800]}") from exc


def _upload_samples(files: list[Path], prefix: str) -> list[dict]:
    from google.cloud import storage

    client = storage.Client(project=settings.GCP_PROJECT_ID or None)
    bucket = client.bucket(settings.GCS_INPUT_BUCKET)
    uploaded = []
    for path in files:
        object_name = f"{prefix}/{path.name}"
        blob = bucket.blob(object_name)
        print(f"  upload gs://{settings.GCS_INPUT_BUCKET}/{object_name}")
        content_type = _content_type(path)
        blob.upload_from_filename(str(path), content_type=content_type)
        blob.metadata = _metadata_for_file(path)
        blob.patch()
        uploaded.append(
            {
                "name": object_name,
                "bucket": settings.GCS_INPUT_BUCKET,
                "contentType": content_type,
                "size": str(path.stat().st_size),
                "metadata": blob.metadata,
                "local": path.name,
            }
        )
    return uploaded


def _wait_stt_output(job_id: str, timeout_s: int) -> str:
    from google.cloud import storage

    canonical = build_stt_output_gcs_uri(job_id)
    without = canonical.replace("gs://", "")
    bucket_name, blob_path = without.split("/", 1)
    prefix = blob_path.rsplit("/", 1)[0] + "/"
    client = storage.Client(project=settings.GCP_PROJECT_ID or None)
    bucket = client.bucket(bucket_name)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        canonical_blob = bucket.blob(blob_path)
        if canonical_blob.exists():
            print(f"  STT output ready: {canonical}")
            return canonical
        matches = [
            blob.name
            for blob in client.list_blobs(bucket_name, prefix=prefix)
            if blob.name.lower().endswith(".json")
        ]
        if matches:
            uri = f"gs://{bucket_name}/{matches[0]}"
            print(f"  STT output ready: {uri}")
            return uri
        time.sleep(10)
        print(f"  waiting for STT output… ({int(deadline - time.time())}s left)")
    raise TimeoutError(f"Timed out waiting for {canonical}")


def main() -> int:
    parser = argparse.ArgumentParser(description="E2E pipeline with samples/*.mp3")
    parser.add_argument("--base-url", default=os.getenv("E2E_BASE_URL", "http://localhost:8001"))
    parser.add_argument(
        "--prefix",
        default=None,
        help=f"GCS object prefix (default: {DEFAULT_PREFIX}-<utc-timestamp>)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Process only first N samples (0=all)")
    parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="Optional explicit sample filenames (e.g. sample_02.mp3)",
    )
    parser.add_argument("--language-code", default="hi-IN")
    parser.add_argument("--stt-timeout", type=int, default=900, help="Seconds to wait per STT job")
    parser.add_argument("--skip-upload", action="store_true", help="Assume objects already in GCS")
    parser.add_argument(
        "--samples-dir",
        default=str(SAMPLES_DIR),
        help="Directory of sample audio (default: samples/)",
    )
    parser.add_argument(
        "--gemini-stt",
        action="store_true",
        help="Call /api/v1/files/gemini-stt instead of Speech v2 /transcription",
    )
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    prefix = args.prefix or f"{DEFAULT_PREFIX}-{time.strftime('%Y%m%d-%H%M%S', time.gmtime())}"
    samples_dir = Path(args.samples_dir)
    if not samples_dir.is_absolute():
        samples_dir = ROOT / samples_dir
    if args.files:
        files = []
        for name in args.files:
            path = Path(name)
            files.append(path if path.is_absolute() else samples_dir / name)
        missing = [str(p) for p in files if not p.exists()]
        if missing:
            print(f"Missing sample files: {missing}")
            return 1
    else:
        files = sorted(samples_dir.glob("*.webm")) or sorted(samples_dir.glob("sample_*.mp3"))
        if args.limit > 0:
            files = files[: args.limit]
    if not files:
        print(f"No audio files under {samples_dir}")
        return 1

    if not settings.GCS_INPUT_BUCKET or not settings.GCS_OUTPUT_BUCKET:
        print("GCS_INPUT_BUCKET / GCS_OUTPUT_BUCKET must be set in .env")
        return 1

    print(f"Health: {_http_json('GET', f'{base}/health')}")
    print(f"Base URL: {base}")
    print(f"GCS prefix: {prefix}")
    print(f"Samples: {[p.name for p in files]}")

    if args.skip_upload:
        objects = [
            {
                "name": f"{prefix}/{p.name}",
                "bucket": settings.GCS_INPUT_BUCKET,
                "contentType": _content_type(p),
                "size": str(p.stat().st_size),
                "metadata": _metadata_for_file(p),
                "local": p.name,
            }
            for p in files
        ]
    else:
        print("Uploading to GCS…")
        objects = _upload_samples(files, prefix)

    jobs: list[dict] = []
    print("Ingest…")
    for obj in objects:
        resp = _http_json("POST", f"{base}/api/v1/file", obj)
        data = resp.get("data") or {}
        print(f"  {obj['local']} → job_id={data.get('job_id')} status={data.get('status')}")
        jobs.append({"job_id": data["job_id"], "gcs_input_uri": data["gcs_input_uri"], "local": obj["local"]})

    print("Batch…")
    batch_resp = _http_json("POST", f"{base}/api/v1/batch", {})
    print(f"  {batch_resp.get('data')}")

    results = []
    for job in jobs:
        job_id = job["job_id"]
        print(f"\n=== {job['local']} ({job_id}) ===")
        prefix = f"gs://{settings.GCS_OUTPUT_BUCKET}/stt-output/{job_id}/"
        stt_path = "/api/v1/files/gemini-stt" if args.gemini_stt else "/api/v1/files/transcription"
        extra_headers = {"X-CloudTasks-TaskRetryCount": "2"} if args.gemini_stt else None
        stt_resp = _http_json(
            "POST",
            f"{base}{stt_path}",
            {
                "job_id": job_id,
                "gcs_input_uri": job["gcs_input_uri"],
                "gcs_output_uri_prefix": prefix,
                "language_code": args.language_code,
                "model": "telephony",
            },
            timeout=args.stt_timeout,
            extra_headers=extra_headers,
        )
        print(f"  STT submit: {stt_resp.get('data')}", flush=True)
        stt_data = stt_resp.get("data") or {}
        ok_status = {"STT_SUBMITTED", "STT_COMPLETED", "TRANSLATING"}
        if stt_data.get("status") not in ok_status:
            raise RuntimeError(
                f"STT submit did not start for {job_id}: {stt_data}"
            )

        stt_uri = stt_data.get("gcs_stt_output_uri")
        if not stt_uri:
            stt_uri = _wait_stt_output(job_id, args.stt_timeout)
        without = stt_uri.replace("gs://", "")
        bucket_name, object_name = without.split("/", 1)
        complete = _http_json(
            "POST",
            f"{base}/api/v1/files/stt-complete",
            {"name": object_name, "bucket": bucket_name, "contentType": "application/json"},
        )
        print(f"  STT complete: {complete.get('data')}")

        translate = _http_json(
            "POST",
            f"{base}/api/v1/files/translate",
            {"job_id": job_id, "gcs_transcript_uri": stt_uri},
            timeout=600,
        )
        print(f"  Translate: {translate.get('data')}")

        insights = _http_json(
            "POST",
            f"{base}/api/v1/files/post-processing",
            {"job_id": job_id},
            timeout=600,
        )
        print(f"  Insights: {insights.get('data')}")
        results.append(
            {
                "local": job["local"],
                "job_id": job_id,
                "stt": (stt_resp.get("data") or {}).get("status"),
                "translate": (translate.get("data") or {}).get("status"),
                "insights": (insights.get("data") or {}).get("status"),
                "insights_generated": (insights.get("data") or {}).get("insights_generated"),
            }
        )

    print("\n═══ E2E SUMMARY ═══")
    for row in results:
        print(json.dumps(row))
    failed = [r for r in results if r.get("insights") != "COMPLETED"]
    if failed:
        print(f"FAILED: {len(failed)}/{len(results)}")
        return 1
    print(f"OK: {len(results)}/{len(results)} completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
