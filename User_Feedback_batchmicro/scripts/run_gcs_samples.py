#!/usr/bin/env python3
"""Upload sample audio to GCS, trigger Cloud Scheduler, monitor until done.

Production path (not the HTTP e2e driver):
  1. Delete prior test01 jobs/feedbacks in Cloud SQL (via pidilite-sql-ops)
  2. Upload samples/test01/sample_*.mp3 to gs://pidilite-raw-audio/<prefix>/
  3. Wait for Eventarc ingest (PENDING jobs)
  4. Run pidilite-pipeline-batch-hourly, then poll + checker until terminal

Usage:
  poetry run python scripts/run_gcs_samples.py
  poetry run python scripts/run_gcs_samples.py --no-delete --prefix test01-20260823-120000
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES_DIR = ROOT / "samples" / "test01"

PROJECT = os.getenv("GCP_PROJECT_ID", "pidilite-user-feedback-ai")
REGION = os.getenv("GCP_LOCATION", "asia-south1")
BUCKET = os.getenv("GCS_INPUT_BUCKET", "pidilite-raw-audio")
SQL_OPS_JOB = os.getenv("SQL_OPS_JOB", "pidilite-sql-ops")
BATCH_SCHEDULER = os.getenv("BATCH_SCHEDULER_JOB", "pidilite-pipeline-batch-hourly")
CHECKER_SCHEDULER = os.getenv("CHECKER_SCHEDULER_JOB", "pidilite-pipeline-checker-15min")

TERMINAL = frozenset({"COMPLETED", "FAILED"})

DEFAULT_METADATA = {
    "division": "Consumer",
    "zone": "West",
    "rfmm_cluster": "Test01-Cluster",
    "rbdm_cluster": "Test01-Cluster",
    "cluster": "Test01-Cluster",
    "fme_code": "TEST01",
    "user_type": "FME",
    "state": "Maharashtra",
    "town_city": "Mumbai",
    "tsi_territory_code": "TSI-TEST01",
    "tty_code": "TTY-TEST01",
    "user_id": "test01-user",
    "data_source": "test01",
}


def _adc_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("CLOUDSDK_AUTH_ACCESS_TOKEN", None)
    token = subprocess.check_output(
        ["gcloud", "auth", "application-default", "print-access-token"],
        env=env,
        text=True,
    ).strip()
    env["CLOUDSDK_AUTH_ACCESS_TOKEN"] = token
    env["CLOUDSDK_CORE_PROJECT"] = PROJECT
    env["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "1"
    return env


def _run(args: list[str], env: dict[str, str] | None = None, timeout: int = 180) -> str:
    env = env or _adc_env()
    print(f"  $ {' '.join(args)}", flush=True)
    proc = subprocess.run(
        args,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed ({proc.returncode}):\n{out[-2000:]}")
    return out


def _sample_files(samples_dir: Path) -> list[Path]:
    files = sorted(samples_dir.glob("sample_*.mp3"))
    if not files:
        raise SystemExit(f"No sample_*.mp3 under {samples_dir}")
    return files


def _upload(files: list[Path], prefix: str) -> list[str]:
    from google.cloud import storage

    client = storage.Client(project=PROJECT)
    bucket = client.bucket(BUCKET)
    uris = []
    for path in files:
        object_name = f"{prefix}/{path.name}"
        blob = bucket.blob(object_name)
        print(f"  upload gs://{BUCKET}/{object_name} ({path.stat().st_size} bytes)", flush=True)
        blob.upload_from_filename(str(path), content_type="audio/mpeg")
        blob.metadata = dict(DEFAULT_METADATA)
        blob.patch()
        uris.append(f"gs://{BUCKET}/{object_name}")
    return uris


_STATUS_PY = r'''
import json, os
from sqlalchemy import text
from db.session import SessionLocal
prefix = (os.environ.get("PREFIX") or "test01").strip()
like = f"%{prefix}%"
sql = (
    "SELECT j.id, j.status::text AS status, fd.file_name, "
    "(SELECT count(*) FROM feedbacks f WHERE f.job_id = j.id) AS feedback_count, "
    "j.stt_operation_name, j.gcs_stt_output_uri, j.error_message FROM jobs j "
    "LEFT JOIN file_details fd ON fd.job_id = j.id "
    "WHERE j.gcs_input_uri LIKE :like ORDER BY fd.file_name"
)
db = SessionLocal()
try:
    rows = db.execute(text(sql), {"like": like}).mappings().all()
    jobs = [dict(r) for r in rows]
    by_status = {}
    for job in jobs:
        by_status[job["status"]] = by_status.get(job["status"], 0) + 1
    print("SQL_OPS_JSON=" + json.dumps({
        "like": like,
        "count": len(jobs),
        "by_status": by_status,
        "feedback_total": sum(int(job["feedback_count"] or 0) for job in jobs),
        "jobs": jobs,
    }, default=str, separators=(",", ":")))
finally:
    db.close()
'''


def _sql_ops(action: str, prefix: str) -> dict:
    env = _adc_env()
    args = [
        "gcloud",
        "run",
        "jobs",
        "execute",
        SQL_OPS_JOB,
        f"--region={REGION}",
        "--wait",
        f"--update-env-vars=ACTION={action},PREFIX={prefix}",
    ]
    if action in {"status", "summary"}:
        import base64

        b64 = base64.b64encode(_STATUS_PY.encode()).decode()
        args.append("--args")
        args.append(f"^|^run|python|-c|import base64; exec(base64.b64decode('{b64}').decode())")
    out = _run(args, env=env, timeout=180)
    match = re.search(r"Execution \[([^\]]+)\]", out)
    if not match:
        raise RuntimeError(f"sql-ops: no execution name in output:\n{out[-1500:]}")
    execution = match.group(1)
    raw = _run(
        [
            "gcloud",
            "logging",
            "read",
            (
                'resource.type="cloud_run_job" AND '
                f'resource.labels.job_name="{SQL_OPS_JOB}" AND '
                f'labels."run.googleapis.com/execution_name"="{execution}"'
            ),
            "--limit=80",
            "--format=json",
            "--freshness=10m",
        ],
        env=env,
        timeout=60,
    )
    return _parse_sql_ops_logs(raw, execution)


def _parse_sql_ops_logs(raw: str, execution: str) -> dict:
    entries = json.loads(raw)
    lines: list[str] = []
    for entry in reversed(entries):
        text = entry.get("textPayload")
        if text:
            lines.append(text)
            continue
        payload = entry.get("jsonPayload")
        if isinstance(payload, dict) and ("like" in payload or "deleted_jobs" in payload):
            return payload
    blob = "\n".join(lines)
    marker = "SQL_OPS_JSON="
    if marker in blob:
        start = blob.index(marker) + len(marker)
        decoder = json.JSONDecoder()
        obj, _end = decoder.raw_decode(blob, start)
        if isinstance(obj, dict):
            return obj
    decoder = json.JSONDecoder()
    idx = 0
    last: dict | None = None
    while idx < len(blob):
        start = blob.find("{", idx)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(blob, start)
        except json.JSONDecodeError:
            idx = start + 1
            continue
        if isinstance(obj, dict) and ("like" in obj or "deleted_jobs" in obj or "by_status" in obj):
            last = obj
        idx = end
    if last is not None:
        return last
    raise RuntimeError(f"sql-ops: could not parse result for {execution}:\n{blob[:1500]}")


def _trigger_scheduler(job_name: str) -> None:
    _run(
        [
            "gcloud",
            "scheduler",
            "jobs",
            "run",
            job_name,
            f"--location={REGION}",
        ],
        timeout=60,
    )
    print(f"  triggered scheduler {job_name}", flush=True)


def _print_summary(payload: dict, label: str) -> None:
    by_status = payload.get("by_status") or {}
    parts = [f"{k}={v}" for k, v in sorted(by_status.items())]
    extra = ""
    if "feedback_total" in payload:
        extra = f" feedbacks={payload['feedback_total']}"
    print(
        f"{label}: n={payload.get('count', 0)} {', '.join(parts) or 'none'}{extra}",
        flush=True,
    )
    for job in payload.get("jobs") or []:
        err = f" err={job['error_message']}" if job.get("error_message") else ""
        op = job.get("stt_operation_name") or ""
        if op.startswith("gemini-flash:"):
            engine = "flash"
        elif "/operations/" in op:
            engine = "v2"
        elif op:
            engine = op[:24]
        else:
            engine = "-"
        print(
            f"  {job.get('status'):14} stt={engine:5} fb={job.get('feedback_count', 0):2} {job.get('file_name')}{err}",
            flush=True,
        )


def _all_terminal(payload: dict, expected: int) -> bool:
    jobs = payload.get("jobs") or []
    if len(jobs) < expected:
        return False
    return all((j.get("status") in TERMINAL) for j in jobs)


def _wait_ingest(prefix: str, expected: int, timeout: int, poll_seconds: int) -> dict:
    deadline = time.time() + timeout
    payload: dict = {"count": 0, "jobs": []}
    while time.time() < deadline:
        payload = _sql_ops("status", prefix)
        _print_summary(payload, "ingest")
        if payload.get("count", 0) >= expected:
            return payload
        time.sleep(poll_seconds)
    raise TimeoutError(
        f"Eventarc ingested {payload.get('count', 0)}/{expected} files"
    )


def _monitor(
    prefix: str,
    expected: int,
    timeout: int,
    poll_seconds: int,
    checker_every: int,
) -> dict:
    deadline = time.time() + timeout
    last_checker = 0.0
    last_batch = time.time()
    payload: dict = {"count": 0, "jobs": []}
    while time.time() < deadline:
        payload = _sql_ops("status", prefix)
        _print_summary(payload, time.strftime("%H:%M:%S", time.localtime()))
        if _all_terminal(payload, expected):
            return payload
        by_status = payload.get("by_status") or {}
        now = time.time()
        if by_status.get("PENDING") and now - last_batch >= 90:
            print("  still PENDING — re-trigger batch scheduler", flush=True)
            _trigger_scheduler(BATCH_SCHEDULER)
            last_batch = now
        if now - last_checker >= checker_every:
            _trigger_scheduler(CHECKER_SCHEDULER)
            last_checker = now
        time.sleep(poll_seconds)
    raise TimeoutError("timed out waiting for jobs to finish")


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload samples, trigger scheduler, monitor")
    parser.add_argument(
        "--prefix",
        default=None,
        help="GCS object prefix (default: test01-<utc-timestamp>)",
    )
    parser.add_argument(
        "--samples-dir",
        default=str(SAMPLES_DIR),
        help="Directory of sample_*.mp3 files",
    )
    parser.add_argument("--no-delete", action="store_true", help="Skip deleting prior test01 jobs")
    parser.add_argument(
        "--delete-like",
        default="test01",
        help="PREFIX passed to sql-ops delete (wrapped as %%value%%)",
    )
    parser.add_argument("--skip-upload", action="store_true", help="Assume objects already in GCS")
    parser.add_argument("--ingest-timeout", type=int, default=600, help="Seconds to wait for Eventarc")
    parser.add_argument("--run-timeout", type=int, default=5400, help="Seconds to wait for COMPLETED")
    parser.add_argument("--poll-seconds", type=int, default=45)
    parser.add_argument("--checker-every", type=int, default=180, help="Re-run checker this often")
    args = parser.parse_args()

    files = _sample_files(Path(args.samples_dir))
    prefix = args.prefix or time.strftime("test01-%Y%m%d-%H%M%S", time.gmtime())
    expected = len(files)

    print(f"Project: {PROJECT}")
    print(f"Prefix:  gs://{BUCKET}/{prefix}/")
    print(f"Files:   {[p.name for p in files]}")

    if not args.no_delete:
        print("\n=== Delete old test01 jobs / feedbacks ===", flush=True)
        deleted = _sql_ops("delete", args.delete_like)
        print(
            f"  deleted_jobs={deleted.get('deleted_jobs')} "
            f"before={deleted.get('before')}",
            flush=True,
        )

    if not args.skip_upload:
        print("\n=== Upload to GCS ===", flush=True)
        _upload(files, prefix)
    else:
        print("\n=== Skip upload ===", flush=True)

    print("\n=== Wait for Eventarc ingest ===", flush=True)
    try:
        _wait_ingest(prefix, expected, args.ingest_timeout, args.poll_seconds)
    except TimeoutError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("\n=== Trigger batch scheduler ===", flush=True)
    _trigger_scheduler(BATCH_SCHEDULER)

    print("\n=== Monitor pipeline ===", flush=True)
    try:
        payload = _monitor(
            prefix,
            expected,
            args.run_timeout,
            args.poll_seconds,
            args.checker_every,
        )
    except TimeoutError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("\n=== Done ===", flush=True)
    _print_summary(payload, "final")
    failed = [j for j in payload["jobs"] if j.get("status") != "COMPLETED"]
    if failed:
        print(f"FAILED: {len(failed)}/{expected} not COMPLETED")
        return 1
    print(f"OK: {expected}/{expected} COMPLETED, feedbacks={payload.get('feedback_total')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
