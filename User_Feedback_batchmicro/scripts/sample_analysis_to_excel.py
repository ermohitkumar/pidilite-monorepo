#!/usr/bin/env python3
"""
Run samples/*.mp3 through current-repo STT → translate → insights and export Excel.

Uses:
  - Google Cloud Speech-to-Text (same config as services/api/routers/stt.py)
  - services.shared.vertex_ai.translate_transcript / generate_insights
  - taxonomy + product catalog from scripts/data/

Usage:
  poetry run python scripts/sample_analysis_to_excel.py
  poetry run python scripts/sample_analysis_to_excel.py --files sample_04.mp3 --out scratch/sample_analysis.xlsx
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

from core.config import settings
from services.api.routers.normalize import _build_tags_context, _load_taxonomy
from services.shared.transcript import extract_transcript_from_stt_json
from services.shared.vertex_ai import generate_insights, translate_transcript
from services.shared.product_resolve import enforce_master_product_names
from types import SimpleNamespace

SAMPLES_DIR = ROOT / "samples"
CATALOG_PATH = ROOT / "scripts" / "data" / "products_catalog.json"
DEFAULT_OUT = ROOT / "scratch" / "sample_analysis.xlsx"


def _build_product_tsv_from_catalog() -> str:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    lines: list[str] = []
    for p in data:
        if not p.get("is_active", True):
            continue
        name = (p.get("product_name") or "").strip()
        if not name or len(name) > 50:
            continue
        name_lower = name.lower()
        if any(kw in name_lower for kw in settings.MARKETING_KEYWORDS):
            continue
        sku = p.get("short_code") or name[:8]
        desc = (p.get("description") or "").strip()
        if desc:
            lines.append(f"{sku}|{name}|{desc}")
        else:
            lines.append(f"{sku}|{name}")
    return "\n".join(lines)


def _catalog_products_for_resolve() -> list:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    products = []
    for i, p in enumerate(data, start=1):
        if not p.get("is_active", True):
            continue
        name = (p.get("product_name") or "").strip()
        if not name or len(name) > 50:
            continue
        products.append(
            SimpleNamespace(
                id=i,
                product_name=name,
                short_code=(p.get("short_code") or "").strip() or None,
            )
        )
    return products


def _upload_audio(local_path: Path, object_name: str) -> str:
    from google.cloud import storage

    client = storage.Client(project=settings.GCP_PROJECT_ID or None)
    blob = client.bucket(settings.GCS_INPUT_BUCKET).blob(object_name)
    print(f"  upload gs://{settings.GCS_INPUT_BUCKET}/{object_name}")
    blob.upload_from_filename(str(local_path), content_type="audio/mpeg")
    return f"gs://{settings.GCS_INPUT_BUCKET}/{object_name}"


def _submit_stt(gcs_input_uri: str, gcs_output_prefix: str, language_code: str, model: str) -> str:
    from google.cloud import speech_v1 as speech

    from services.shared.stt_config import alternative_language_codes, encoding_and_sample_rate, file_extension

    client = speech.SpeechClient()
    audio = speech.RecognitionAudio(uri=gcs_input_uri)
    encoding_name, sample_rate = encoding_and_sample_rate(file_extension(gcs_input_uri))
    config_kwargs = {
        "language_code": language_code,
        "alternative_language_codes": alternative_language_codes(language_code),
        "model": model,
        "enable_automatic_punctuation": True,
        "enable_word_confidence": True,
        "enable_word_time_offsets": True,
    }
    if encoding_name:
        config_kwargs["encoding"] = getattr(speech.RecognitionConfig.AudioEncoding, encoding_name)
    if sample_rate:
        config_kwargs["sample_rate_hertz"] = sample_rate
    config = speech.RecognitionConfig(**config_kwargs)
    output_uri = f"{gcs_output_prefix.rstrip('/')}/output.json"
    operation = client.long_running_recognize(
        request={
            "config": config,
            "audio": audio,
            "output_config": speech.TranscriptOutputConfig(gcs_uri=output_uri),
        }
    )
    return operation.operation.name, output_uri


def _wait_gcs_blob(gcs_uri: str, timeout_s: int) -> None:
    from google.cloud import storage

    without = gcs_uri.replace("gs://", "")
    bucket_name, blob_path = without.split("/", 1)
    client = storage.Client(project=settings.GCP_PROJECT_ID or None)
    blob = client.bucket(bucket_name).blob(blob_path)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if blob.exists():
            print(f"  STT ready: {gcs_uri}")
            return
        left = int(deadline - time.time())
        print(f"  waiting STT… {left}s left", flush=True)
        time.sleep(15)
    raise TimeoutError(f"Timed out waiting for {gcs_uri}")


def _process_one(
    path: Path,
    *,
    run_id: str,
    language_code: str,
    stt_model: str,
    stt_timeout: int,
    product_tsv: str,
    tags_context: str,
    cache_dir: Path,
    reuse_stt_from: Path | None = None,
) -> dict:
    stem = path.stem
    cache_json = cache_dir / f"{stem}.json"
    if cache_json.exists():
        print(f"  reuse cache {cache_json.name}")
        return json.loads(cache_json.read_text(encoding="utf-8"))

    job_key = f"{run_id}/{stem}-{uuid.uuid4().hex[:8]}"
    object_name = f"sample-analysis/{job_key}/{path.name}"
    out_prefix = f"gs://{settings.GCS_OUTPUT_BUCKET}/sample-analysis/{job_key}"

    row: dict = {
        "file_name": path.name,
        "language_code": language_code,
        "gcs_input_uri": None,
        "gcs_transcript_uri": None,
        "region_transcript": None,
        "translated_text": None,
        "insights": [],
        "error": None,
        "timings_s": {},
    }

    try:
        t0 = time.time()
        region = ""
        if reuse_stt_from:
            prior = reuse_stt_from / f"{stem}.json"
            if prior.exists():
                prior_row = json.loads(prior.read_text(encoding="utf-8"))
                region = prior_row.get("region_transcript") or ""
                row["gcs_input_uri"] = prior_row.get("gcs_input_uri")
                row["gcs_transcript_uri"] = prior_row.get("gcs_transcript_uri")
                row["timings_s"]["stt"] = 0
                print(f"  reuse STT from {prior.name}: {len(region)} chars")

        if not region.strip():
            gcs_in = _upload_audio(path, object_name)
            row["gcs_input_uri"] = gcs_in
            op_name, gcs_out = _submit_stt(gcs_in, out_prefix, language_code, stt_model)
            print(f"  STT submitted: {op_name}")
            row["gcs_transcript_uri"] = gcs_out
            _wait_gcs_blob(gcs_out, stt_timeout)
            region = extract_transcript_from_stt_json(gcs_out)
            row["timings_s"]["stt"] = round(time.time() - t0, 2)

        row["region_transcript"] = region
        print(f"  region transcript: {len(region)} chars")

        if not region.strip():
            row["error"] = "Empty STT transcript"
            cache_json.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
            return row

        t1 = time.time()
        translated, t_tokens = translate_transcript(region, product_catalog_tsv=product_tsv)
        row["translated_text"] = translated
        row["translation_tokens"] = t_tokens
        row["timings_s"]["translate"] = round(time.time() - t1, 2)
        print(f"  translated: {len(translated)} chars")

        t2 = time.time()
        insights, i_tokens = generate_insights(
            translated_text=translated,
            product_catalog_tsv=product_tsv,
            tags_context=tags_context,
        )
        enforce_master_product_names(insights, _catalog_products_for_resolve())
        for item in insights:
            item.pop("_resolved_product_id", None)
        row["insights"] = insights
        row["insights_tokens"] = i_tokens
        row["timings_s"]["insights"] = round(time.time() - t2, 2)
        print(f"  insights: {len(insights)} items")
        groups = sorted({(i.get("group_type") or "?") for i in insights})
        print(f"  groups: {groups}")
        products = sorted({(i.get("product_name") or "") for i in insights if i.get("product_name")})
        if products:
            print(f"  products (master-validated): {products}")
    except Exception as exc:
        row["error"] = str(exc)
        print(f"  ERROR: {exc}")

    cache_json.write_text(json.dumps(row, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return row


def _tag_labels(tag_ids: list) -> str:
    tax = {e["tag_id"]: e for e in _load_taxonomy() if "tag_id" in e}
    labels = []
    for tid in tag_ids or []:
        e = tax.get(tid)
        if e:
            labels.append(f"{tid}:{e.get('feedback_tag')}")
        else:
            labels.append(str(tid))
    return "; ".join(labels)


def _write_excel(rows: list[dict], out_path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "summary"
    headers = [
        "file_name",
        "language_code",
        "region_transcript",
        "translated_text",
        "insights_count",
        "insights_json",
        "error",
        "gcs_input_uri",
        "gcs_transcript_uri",
    ]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    wrap = Alignment(wrap_text=True, vertical="top")
    for row in rows:
        insights = row.get("insights") or []
        ws.append(
            [
                row.get("file_name"),
                row.get("language_code"),
                row.get("region_transcript") or "",
                row.get("translated_text") or "",
                len(insights),
                json.dumps(insights, ensure_ascii=False, indent=2),
                row.get("error") or "",
                row.get("gcs_input_uri") or "",
                row.get("gcs_transcript_uri") or "",
            ]
        )

    for col in ("C", "D", "F"):
        ws.column_dimensions[col].width = 60
    for r in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=3, max_col=6):
        for cell in r:
            cell.alignment = wrap
    ws.row_dimensions[1].height = 18
    for i in range(2, ws.max_row + 1):
        ws.row_dimensions[i].height = 120

    wi = wb.create_sheet("insights")
    ih = [
        "file_name",
        "group_type",
        "category_type",
        "tag_ids",
        "tag_labels",
        "product_name",
        "verbatim_quote",
        "summary",
        "competitors_mentioned",
    ]
    wi.append(ih)
    for cell in wi[1]:
        cell.font = Font(bold=True)
    for row in rows:
        for item in row.get("insights") or []:
            tags = item.get("tag_ids") or []
            comps = item.get("competitors_mentioned") or []
            wi.append(
                [
                    row.get("file_name"),
                    item.get("group_type"),
                    item.get("category_type"),
                    ", ".join(str(t) for t in tags),
                    _tag_labels(tags),
                    item.get("product_name"),
                    item.get("verbatim_quote"),
                    item.get("summary"),
                    ", ".join(str(c) for c in comps if c),
                ]
            )
    for col, width in {"A": 16, "B": 14, "C": 18, "D": 14, "E": 40, "F": 22, "G": 50, "H": 50, "I": 30}.items():
        wi.column_dimensions[col].width = width
    for r in wi.iter_rows(min_row=2, max_row=max(2, wi.max_row), min_col=5, max_col=8):
        for cell in r:
            cell.alignment = wrap

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    print(f"Wrote {out_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sample audio → Excel analysis")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--files", nargs="*", default=None, help="Optional sample filenames")
    parser.add_argument("--language-code", default="hi-IN")
    parser.add_argument("--stt-model", default="latest_long")
    parser.add_argument("--stt-timeout", type=int, default=1800)
    parser.add_argument("--reuse-cache", action="store_true", help="Reuse scratch cache JSONs if present")
    parser.add_argument(
        "--reuse-stt-from",
        type=Path,
        default=None,
        help="Reuse region_transcript from a prior cache dir; re-run translate+insights",
    )
    args = parser.parse_args()

    if not settings.GCP_PROJECT_ID:
        print("GCP_PROJECT_ID must be set in .env")
        return 1
    if not settings.GCS_INPUT_BUCKET or not settings.GCS_OUTPUT_BUCKET:
        print("GCS_INPUT_BUCKET / GCS_OUTPUT_BUCKET must be set")
        return 1

    if args.files:
        files = [SAMPLES_DIR / n for n in args.files]
    else:
        files = sorted(SAMPLES_DIR.glob("sample_*.mp3"))
    missing = [str(p) for p in files if not p.exists()]
    if missing:
        print(f"Missing: {missing}")
        return 1
    if not files:
        print(f"No samples under {SAMPLES_DIR}")
        return 1

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    cache_dir = ROOT / "scratch" / "sample_analysis_cache" / run_id
    if args.reuse_cache:
        # use latest cache dir if any
        parent = ROOT / "scratch" / "sample_analysis_cache"
        dirs = sorted(parent.glob("*")) if parent.exists() else []
        cache_dir = dirs[-1] if dirs else cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)

    print(f"Project: {settings.GCP_PROJECT_ID}")
    print(f"Model:   {settings.GEMINI_MODEL}")
    print(f"Samples: {[p.name for p in files]}")
    print(f"Cache:   {cache_dir}")

    product_tsv = _build_product_tsv_from_catalog()
    tags_context = _build_tags_context(None)  # taxonomy JSON only; db unused
    print(f"Product TSV lines: {len(product_tsv.splitlines())}")
    print(f"Taxonomy tags: {len(_load_taxonomy())}")

    rows = []
    for path in files:
        print(f"\n=== {path.name} ===", flush=True)
        row = _process_one(
            path,
            run_id=run_id,
            language_code=args.language_code,
            stt_model=args.stt_model,
            stt_timeout=args.stt_timeout,
            product_tsv=product_tsv,
            tags_context=tags_context,
            cache_dir=cache_dir,
            reuse_stt_from=args.reuse_stt_from,
        )
        rows.append(row)

    _write_excel(rows, args.out)
    failed = [r["file_name"] for r in rows if r.get("error")]
    print("\n═══ SUMMARY ═══")
    for r in rows:
        n = len(r.get("insights") or [])
        print(f"  {r['file_name']}: insights={n} error={r.get('error')}")
    if failed:
        print(f"FAILED: {failed}")
        return 1
    print(f"OK → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
