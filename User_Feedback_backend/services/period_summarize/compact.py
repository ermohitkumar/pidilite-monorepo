"""Compact insight lines, token estimates, and adaptive chunk packing."""
from __future__ import annotations

import hashlib
import math
from collections import Counter
from datetime import date
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.period_summarize.period_keys import (
    INSIGHT_GRAINS,
    display_key,
    group_label,
    group_token,
    parse_insight_key,
)

INPUT_BUDGET_TOKENS = 8000
COMBINE_BUDGET_TOKENS = 6000
FLOOR_LINES = 15
LINE_SUMMARY_CHARS = 160
CHILD_SUMMARY_TOKENS = 400
MAX_PACK_DEPTH = 20
INSIGHT_CALL_COLUMNS = ("fd.call_date", "fb.created_at")


def estimate_tokens(text_value: str | None) -> int:
    if not text_value:
        return 0
    return max(1, math.ceil(len(text_value) / 4))


def truncate_chars(value: str | None, limit: int) -> str:
    text_value = (value or "").replace("\n", " ").strip()
    if len(text_value) <= limit:
        return text_value
    return text_value[: max(0, limit - 1)] + "…"


def truncate_to_tokens(value: str | None, max_tokens: int = CHILD_SUMMARY_TOKENS) -> str:
    text_value = (value or "").strip()
    max_chars = max_tokens * 4
    if len(text_value) <= max_chars:
        return text_value
    return text_value[: max(0, max_chars - 1)] + "…"


def compact_line(row: dict[str, Any]) -> str:
    call_date = row.get("call_date")
    if hasattr(call_date, "isoformat"):
        day = call_date.isoformat()[:10]
    else:
        day = str(call_date or "")[:10]
    group = str(row.get("group_type") or "").replace(" GROUP", "")[:12]
    product = truncate_chars(str(row.get("product_name") or "-"), 40)
    tags = truncate_chars(str(row.get("tags") or ""), 40)
    summary = truncate_chars(str(row.get("ai_summary") or ""), LINE_SUMMARY_CHARS)
    return f"{day}|{group}|{product}|{tags}|{summary}"


def _summary_key(line: str) -> str:
    summary = line.rsplit("|", 1)[-1].strip().lower()
    return "".join(summary.split())


def dedup_lines(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = _summary_key(line)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(line)
    return out


def source_hash(lines: list[str]) -> str:
    payload = "\n".join(lines).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sample_leaders(lines: list[str], floor: int = FLOOR_LINES) -> list[str]:
    products: list[str] = []
    for line in lines:
        parts = line.split("|")
        products.append(parts[2].strip() if len(parts) > 2 else "")
    common = {name for name, _count in Counter(products).most_common(5) if name and name != "-"}
    leaders = [line for line in lines if len(line.split("|")) > 2 and line.split("|")[2].strip() in common]
    rest = [line for line in lines if line not in leaders]
    selected = (leaders + rest)[:floor]
    return selected


def pack_chunks(
    lines: list[str],
    budget: int = INPUT_BUDGET_TOKENS,
    floor: int = FLOOR_LINES,
) -> tuple[list[list[str]], bool]:
    """Split lines so each chunk is under the token budget. Never send oversized prompts."""
    truncated = False

    def _split(items: list[str], depth: int = 0) -> list[list[str]]:
        nonlocal truncated
        if not items:
            return []
        packed = "\n".join(items)
        if estimate_tokens(packed) <= budget:
            return [items]
        if len(items) <= floor or depth >= MAX_PACK_DEPTH:
            truncated = True
            sampled = sample_leaders(items, floor)
            if estimate_tokens("\n".join(sampled)) > budget:
                # Last resort: keep shrinking until it fits or a single truncated line remains.
                while len(sampled) > 1 and estimate_tokens("\n".join(sampled)) > budget:
                    sampled = sampled[: max(1, len(sampled) // 2)]
                if sampled and estimate_tokens(sampled[0]) > budget:
                    sampled = [truncate_to_tokens(sampled[0], budget)]
            return [sampled]
        mid = max(1, len(items) // 2)
        return _split(items[:mid], depth + 1) + _split(items[mid:], depth + 1)

    return _split(lines), truncated


def child_source_lines(children: list[dict[str, Any]], budget: int = COMBINE_BUDGET_TOKENS) -> tuple[list[str], bool]:
    lines = []
    for child in children:
        key = child.get("grain_label") or display_key(child.get("grain_key")) or child.get("grain_key") or ""
        text_value = truncate_to_tokens(child.get("summary_text") or "", CHILD_SUMMARY_TOKENS)
        lines.append(f"{key}: {text_value}")
    chunks, truncated = pack_chunks(lines, budget=budget)
    flat: list[str] = []
    for chunk in chunks:
        flat.extend(chunk)
    if len(chunks) <= 1:
        return flat, truncated
    return lines, truncated


def _dialect_name(db: Session) -> str:
    bind = db.get_bind()
    return getattr(getattr(bind, "dialect", None), "name", "") or "postgresql"


def call_date_sql(dialect: str, *columns: str) -> str:
    """Date filter that tolerates mixed timestamptz / varchar columns."""
    if dialect == "sqlite":
        if len(columns) == 1:
            return f"DATE({columns[0]})"
        return f"DATE(COALESCE({', '.join(columns)}))"
    arms = [f"CAST({column} AS DATE)" for column in columns]
    if len(arms) == 1:
        return arms[0]
    return f"COALESCE({', '.join(arms)})"


def _group_filter(group_type: Optional[str]) -> tuple[str, dict[str, Any]]:
    token = group_token(group_type)
    label = group_label(token)
    if not label:
        return "", {}
    return " AND UPPER(TRIM(COALESCE(fb.group_type, ''))) = :group_type", {"group_type": label.upper()}


def _insight_select_sql(db: Session, extra_where: str = "") -> tuple[Any, str]:
    dialect = _dialect_name(db)
    call_date = call_date_sql(dialect, *INSIGHT_CALL_COLUMNS)
    tag_agg = "GROUP_CONCAT(ft.tag_name, ',')" if dialect == "sqlite" else "string_agg(ft.tag_name, ',')"
    sql = text(
        f"""
        SELECT
            {call_date} AS call_date,
            NULLIF(TRIM(COALESCE(fd.fme_code, '')), '') AS bde_key,
            NULLIF(TRIM(COALESCE(fd.rfmm_cluster, '')), '') AS rfmm_key,
            NULLIF(TRIM(COALESCE(fd.zone, '')), '') AS zone_key,
            NULLIF(TRIM(COALESCE(fd.division, '')), '') AS division_key,
            NULLIF(TRIM(COALESCE(fb.product_name, '')), '') AS product_name,
            COALESCE(fb.group_type, '') AS group_type,
            COALESCE(fb.ai_summary, '') AS ai_summary,
            COALESCE((
                SELECT {tag_agg}
                FROM feedback_tag_link ftl
                JOIN feedback_tags ft ON ft.tag_id = ftl.tag_id
                WHERE ftl.feedback_id = fb.id
            ), '') AS tags
        FROM feedbacks fb
        JOIN file_details fd ON fd.job_id = fb.job_id
        WHERE {call_date} BETWEEN :start AND :end
          {extra_where}
        """
    )
    return sql, call_date


def gather_insights(
    db: Session,
    *,
    start: date,
    end: date,
    grain: str,
    grain_key: str,
) -> list[dict[str, Any]]:
    """Load compact insight rows for a leaf cell. Never includes transcripts."""
    if grain not in INSIGHT_GRAINS:
        raise ValueError(f"{grain} must be built from child summaries, not insights")

    parsed = parse_insight_key(grain, grain_key)
    clauses: list[str] = []
    params: dict[str, Any] = {"start": start.isoformat(), "end": end.isoformat()}
    if parsed.get("geo_key"):
        clauses.append("NULLIF(TRIM(COALESCE(fd.fme_code, '')), '') = :geo_key")
        params["geo_key"] = parsed["geo_key"]
    group_sql, group_params = _group_filter(parsed.get("group_type"))
    if group_sql:
        clauses.append(group_sql.replace(" AND ", "", 1))
        params.update(group_params)
    if parsed.get("product_name"):
        clauses.append("NULLIF(TRIM(COALESCE(fb.product_name, '')), '') = :product_name")
        params["product_name"] = parsed["product_name"]
    if parsed.get("tag_id"):
        clauses.append(
            "EXISTS ("
            " SELECT 1 FROM feedback_tag_link ftl"
            " WHERE ftl.feedback_id = fb.id"
            " AND ftl.tag_id = CAST(:tag_id AS INTEGER)"
            ")"
        )
        params["tag_id"] = parsed["tag_id"]
    extra = (" AND " + " AND ".join(clauses)) if clauses else ""
    sql, _call_date = _insight_select_sql(db, extra)
    rows = db.execute(sql, params).mappings().all()
    return [dict(row) for row in rows]


def list_hierarchy_nodes(
    db: Session,
    start: date,
    end: date,
    group_type: Optional[str] = None,
) -> list[dict[str, Optional[str]]]:
    """Geo keys that actually have insights in the period — skip empty BDEs/clusters."""
    call_date = call_date_sql(_dialect_name(db), *INSIGHT_CALL_COLUMNS)
    group_sql, group_params = _group_filter(group_type)
    sql = text(
        f"""
        SELECT DISTINCT
            NULLIF(TRIM(COALESCE(fd.fme_code, '')), '') AS bde_key,
            NULLIF(TRIM(COALESCE(fd.rfmm_cluster, '')), '') AS rfmm_key,
            NULLIF(TRIM(COALESCE(fd.zone, '')), '') AS zone_key,
            NULLIF(TRIM(COALESCE(fd.division, '')), '') AS division_key
        FROM file_details fd
        JOIN feedbacks fb ON fb.job_id = fd.job_id
        WHERE {call_date} BETWEEN :start AND :end
          {group_sql}
        """
    )
    params = {"start": start.isoformat(), "end": end.isoformat(), **group_params}
    rows = db.execute(sql, params).mappings().all()
    return [dict(row) for row in rows]


def list_groups(db: Session, start: date, end: date) -> list[str]:
    """Known PDT / USER / DEALER labels that have insights in the period."""
    call_date = call_date_sql(_dialect_name(db), *INSIGHT_CALL_COLUMNS)
    sql = text(
        f"""
        SELECT DISTINCT COALESCE(fb.group_type, '') AS group_type
        FROM feedbacks fb
        JOIN file_details fd ON fd.job_id = fb.job_id
        WHERE {call_date} BETWEEN :start AND :end
        """
    )
    rows = db.execute(sql, {"start": start.isoformat(), "end": end.isoformat()}).mappings().all()
    seen: list[str] = []
    for row in rows:
        label = group_label(group_token(str(row.get("group_type") or "")))
        if label and label not in seen:
            seen.append(label)
    return seen


def list_product_keys(
    db: Session,
    start: date,
    end: date,
    group_type: Optional[str] = None,
) -> list[str]:
    call_date = call_date_sql(_dialect_name(db), *INSIGHT_CALL_COLUMNS)
    group_sql, group_params = _group_filter(group_type)
    sql = text(
        f"""
        SELECT DISTINCT NULLIF(TRIM(COALESCE(fb.product_name, '')), '') AS product_name
        FROM feedbacks fb
        JOIN file_details fd ON fd.job_id = fb.job_id
        WHERE {call_date} BETWEEN :start AND :end
          AND NULLIF(TRIM(COALESCE(fb.product_name, '')), '') IS NOT NULL
          {group_sql}
        """
    )
    params = {"start": start.isoformat(), "end": end.isoformat(), **group_params}
    rows = db.execute(sql, params).mappings().all()
    return [str(row["product_name"]) for row in rows if row.get("product_name")]


def list_tag_keys(
    db: Session,
    start: date,
    end: date,
    group_type: Optional[str] = None,
) -> list[dict[str, str]]:
    """Distinct taxonomy tags that appear on insights in the period."""
    call_date = call_date_sql(_dialect_name(db), *INSIGHT_CALL_COLUMNS)
    group_sql, group_params = _group_filter(group_type)
    sql = text(
        f"""
        SELECT DISTINCT ft.tag_id AS grain_key, ft.tag_name AS grain_label
        FROM feedback_tag_link ftl
        JOIN feedback_tags ft ON ft.tag_id = ftl.tag_id
        JOIN feedbacks fb ON fb.id = ftl.feedback_id
        JOIN file_details fd ON fd.job_id = fb.job_id
        WHERE {call_date} BETWEEN :start AND :end
          AND ft.tag_id IS NOT NULL
          {group_sql}
        ORDER BY ft.tag_id
        """
    )
    params = {"start": start.isoformat(), "end": end.isoformat(), **group_params}
    rows = db.execute(sql, params).mappings().all()
    out: list[dict[str, str]] = []
    for row in rows:
        if row.get("grain_key") is None:
            continue
        out.append({
            "grain_key": str(row["grain_key"]),
            "grain_label": str(row.get("grain_label") or row["grain_key"]),
        })
    return out


def list_cube_keys(
    db: Session,
    start: date,
    end: date,
    group_type: Optional[str] = None,
) -> list[dict[str, Optional[str]]]:
    """Sparse geo × product × tag × group cells that have insights in the period."""
    call_date = call_date_sql(_dialect_name(db), *INSIGHT_CALL_COLUMNS)
    group_sql, group_params = _group_filter(group_type)
    sql = text(
        f"""
        SELECT DISTINCT
            COALESCE(fb.group_type, '') AS group_type,
            NULLIF(TRIM(COALESCE(fd.fme_code, '')), '') AS bde_key,
            NULLIF(TRIM(COALESCE(fd.rfmm_cluster, '')), '') AS rfmm_key,
            NULLIF(TRIM(COALESCE(fd.zone, '')), '') AS zone_key,
            NULLIF(TRIM(COALESCE(fd.division, '')), '') AS division_key,
            NULLIF(TRIM(COALESCE(fb.product_name, '')), '') AS product_name,
            ft.tag_id AS tag_id,
            ft.tag_name AS tag_name
        FROM feedbacks fb
        JOIN file_details fd ON fd.job_id = fb.job_id
        JOIN feedback_tag_link ftl ON ftl.feedback_id = fb.id
        JOIN feedback_tags ft ON ft.tag_id = ftl.tag_id
        WHERE {call_date} BETWEEN :start AND :end
          AND NULLIF(TRIM(COALESCE(fd.fme_code, '')), '') IS NOT NULL
          AND ft.tag_id IS NOT NULL
          {group_sql}
        """
    )
    params = {"start": start.isoformat(), "end": end.isoformat(), **group_params}
    rows = db.execute(sql, params).mappings().all()
    out: list[dict[str, Optional[str]]] = []
    for row in rows:
        item = dict(row)
        if item.get("tag_id") is not None:
            item["tag_id"] = str(item["tag_id"])
        out.append(item)
    return out


def lines_from_insights(rows: list[dict[str, Any]]) -> tuple[list[str], dict[str, Any]]:
    raw_lines = [compact_line(row) for row in rows]
    lines = dedup_lines(raw_lines)
    job_dates = {str(row.get("call_date") or "")[:10] for row in rows}
    products = [str(row.get("product_name") or "") for row in rows if row.get("product_name")]
    highlights = {
        "call_count": len({d for d in job_dates if d}),
        "insight_count": len(rows),
        "deduped_count": len(lines),
        "products": sorted({name for name in products if name}),
    }
    return lines, highlights
