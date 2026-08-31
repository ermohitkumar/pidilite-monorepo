"""Report queries against vw_pbi_feedback_fact / _slim.

Thin SQL only — HTTP mapping lives in the reports router.
Prefers vw_pbi_feedback_fact_slim so aggregations never join transcripts.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

SLIM_VIEW = "vw_pbi_feedback_fact_slim"
FAT_VIEW = "vw_pbi_feedback_fact"
NO_PRODUCT_LABEL = "(No product)"

DIM_SEARCH = (
    "("
    "COALESCE(feedback_tag, '') ILIKE :search "
    "OR COALESCE(feedback_category, '') ILIKE :search "
    "OR COALESCE(product_name, '') ILIKE :search "
    "OR COALESCE(file_name, '') ILIKE :search"
    ")"
)

DETAIL_SEARCH = (
    "("
    "COALESCE(feedback_tag, '') ILIKE :search "
    "OR COALESCE(feedback_category, '') ILIKE :search "
    "OR COALESCE(product_name, '') ILIKE :search "
    "OR COALESCE(file_name, '') ILIKE :search "
    "OR COALESCE(feedback_summary_ai, '') ILIKE :search"
    ")"
)

FACT_SEARCH = (
    "("
    "COALESCE(feedback_tag, '') ILIKE :search "
    "OR COALESCE(feedback_category, '') ILIKE :search "
    "OR COALESCE(product_name, '') ILIKE :search "
    "OR COALESCE(feedback_summary_ai, '') ILIKE :search "
    "OR COALESCE(feedback_excerpt, '') ILIKE :search"
    ")"
)

_DETAIL_SORT = {
    "call_datetime": "MAX(feedback_created_at)",
    "file_name": "MAX(file_name)",
    "product_name": "MAX(product_name)",
    "feedback_summary_ai": "MAX(feedback_summary_ai)",
    "feedback_id": "feedback_id",
    "feedback_excerpt": "MAX(feedback_excerpt)",
}


class MissingFactView(Exception):
    """Report fact view is not applied on this database."""


def _serialize(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def build_filters(
    feedback_group: Optional[str] = None,
    product_name: Optional[str] = None,
    feedback_category: Optional[str] = None,
    feedback_tag: Optional[str] = None,
    feedback_sub_tag: Optional[str] = None,
    division: Optional[str] = None,
    zone: Optional[str] = None,
    cluster: Optional[str] = None,
    state: Optional[str] = None,
    data_source: Optional[str] = None,
    fme_code: Optional[str] = None,
    user_type: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    search: Optional[str] = None,
    search_sql: str = DIM_SEARCH,
    exact_tag: bool = False,
) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}

    def eq(column: str, value: Optional[str]) -> None:
        if value:
            clauses.append(f"{column} = :{column}")
            params[column] = value

    eq("feedback_group", feedback_group)
    eq("feedback_sub_tag", feedback_sub_tag)
    eq("division", division)
    eq("zone", zone)
    eq("cluster", cluster)
    eq("state", state)
    eq("data_source", data_source)
    eq("fme_code", fme_code)
    eq("user_type", user_type)

    if product_name:
        if product_name.strip().lower() == NO_PRODUCT_LABEL.lower():
            clauses.append("(product_name IS NULL OR TRIM(product_name) = '')")
        else:
            # Match by exact name / product_id / unique short-code alias only.
            # Never equate shared or empty short_codes across different products —
            # that made count=1 per product but detail return every feedback.
            clauses.append(
                "("
                "LOWER(TRIM(product_name)) = LOWER(TRIM(:product_name)) "
                "OR ("
                "  NULLIF(TRIM(COALESCE(product_short_code, '')), '') IS NOT NULL "
                "  AND LOWER(TRIM(product_short_code)) = LOWER(TRIM(:product_name)) "
                "  AND ("
                "    SELECT COUNT(*) FROM products p "
                "    WHERE NULLIF(TRIM(COALESCE(p.short_code, '')), '') IS NOT NULL "
                "      AND LOWER(TRIM(p.short_code)) = LOWER(TRIM(:product_name))"
                "  ) <= 1"
                ") "
                "OR product_id IN ("
                "  SELECT p.id FROM products p "
                "  WHERE LOWER(TRIM(p.product_name)) = LOWER(TRIM(:product_name)) "
                "     OR ("
                "       NULLIF(TRIM(COALESCE(p.short_code, '')), '') IS NOT NULL "
                "       AND LOWER(TRIM(p.short_code)) = LOWER(TRIM(:product_name)) "
                "       AND ("
                "         SELECT COUNT(*) FROM products p2 "
                "         WHERE NULLIF(TRIM(COALESCE(p2.short_code, '')), '') IS NOT NULL "
                "           AND LOWER(TRIM(p2.short_code)) = LOWER(TRIM(:product_name))"
                "       ) = 1"
                "     )"
                ") "
                "OR EXISTS ("
                "  SELECT 1 FROM products p "
                "  WHERE LOWER(TRIM(p.product_name)) = LOWER(TRIM(:product_name)) "
                "    AND NULLIF(TRIM(COALESCE(p.short_code, '')), '') IS NOT NULL "
                "    AND LOWER(TRIM(product_name)) = LOWER(TRIM(p.short_code)) "
                "    AND ("
                "      SELECT COUNT(*) FROM products p2 "
                "      WHERE NULLIF(TRIM(COALESCE(p2.short_code, '')), '') IS NOT NULL "
                "        AND LOWER(TRIM(p2.short_code)) = LOWER(TRIM(p.short_code))"
                "    ) = 1"
                ") "
                "OR EXISTS ("
                "  SELECT 1 FROM products p "
                "  WHERE LOWER(TRIM(p.product_name)) = LOWER(TRIM(:product_name)) "
                "    AND NULLIF(TRIM(product_name), '') IS NOT NULL "
                "    AND LENGTH(TRIM(product_name)) >= 3 "
                "    AND ("
                "      LOWER(TRIM(p.product_name)) LIKE ('% ' || LOWER(TRIM(product_name))) "
                "      OR ("
                "        LENGTH(REPLACE(REPLACE(LOWER(TRIM(product_name)), '-', ''), ' ', '')) >= 4 "
                "        AND REPLACE(REPLACE(LOWER(TRIM(p.product_name)), '-', ''), ' ', '') "
                "            LIKE ('%' || REPLACE(REPLACE(LOWER(TRIM(product_name)), '-', ''), ' ', ''))"
                "      )"
                "    ) "
                "    AND NOT EXISTS ("
                "      SELECT 1 FROM products p2 "
                "      WHERE p2.id IS DISTINCT FROM p.id "
                "        AND ("
                "          LOWER(TRIM(p2.product_name)) LIKE ('% ' || LOWER(TRIM(product_name))) "
                "          OR ("
                "            LENGTH(REPLACE(REPLACE(LOWER(TRIM(product_name)), '-', ''), ' ', '')) >= 4 "
                "            AND REPLACE(REPLACE(LOWER(TRIM(p2.product_name)), '-', ''), ' ', '') "
                "                LIKE ('%' || REPLACE(REPLACE(LOWER(TRIM(product_name)), '-', ''), ' ', ''))"
                "          )"
                "        )"
                "    )"
                ")"
                ")"
            )
            params["product_name"] = product_name
    if feedback_category:
        clauses.append(
            "LOWER(TRIM(feedback_category)) = LOWER(TRIM(:feedback_category))"
        )
        params["feedback_category"] = feedback_category

    if feedback_tag:
        if exact_tag:
            clauses.append("LOWER(TRIM(feedback_tag)) = LOWER(TRIM(:feedback_tag))")
        else:
            clauses.append(
                "("
                "LOWER(TRIM(feedback_tag)) = LOWER(TRIM(:feedback_tag)) "
                "OR LOWER(TRIM(COALESCE(feedback_sub_tag, ''))) = LOWER(TRIM(:feedback_tag))"
                ")"
            )
        params["feedback_tag"] = feedback_tag

    if start_date:
        clauses.append(
            "COALESCE(call_date, CAST(feedback_created_at AS DATE)) >= :start_date"
        )
        params["start_date"] = start_date.isoformat()
    if end_date:
        clauses.append(
            "COALESCE(call_date, CAST(feedback_created_at AS DATE)) <= :end_date"
        )
        params["end_date"] = end_date.isoformat()
    if search:
        clauses.append(search_sql)
        params["search"] = f"%{search}%"

    where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where_sql, params


def execute(db: Session, sql: str, params: dict[str, Any]):
    try:
        return db.execute(text(sql), params)
    except (ProgrammingError, OperationalError) as exc:
        db.rollback()
        msg = str(exc).lower()
        # Do not match bare "exist" — filter SQL contains EXISTS and that false-positive
        # turned GROUPING SETS / other dialect errors into MissingFactView.
        if (
            "does not exist" in msg
            or "undefinedtable" in msg
            or "no such table" in msg
            or "no such view" in msg
        ):
            raise MissingFactView(str(exc)) from exc
        raise


def fact_table(db: Session) -> str:
    """Prefer slim view so aggregations never join transcripts."""
    for name in (SLIM_VIEW, FAT_VIEW):
        try:
            execute(db, f"SELECT 1 FROM {name} LIMIT 0", {})
            return name
        except MissingFactView:
            continue
    raise MissingFactView(f"{SLIM_VIEW} / {FAT_VIEW} not applied")


def _distinct_values(
    db: Session,
    sources: list[tuple[str, str]],
    limit: int,
) -> list:
    """First successful DISTINCT list wins; later sources fill missing values."""
    seen: set[str] = set()
    out: list = []
    for table, column in sources:
        sql = (
            f"SELECT DISTINCT {column} AS v FROM {table} "
            f"WHERE {column} IS NOT NULL AND TRIM(CAST({column} AS TEXT)) <> '' "
            f"ORDER BY 1 LIMIT :limit"
        )
        try:
            rows = execute(db, sql, {"limit": limit}).fetchall()
        except (MissingFactView, ProgrammingError, OperationalError):
            continue
        for row in rows:
            value = _serialize(row[0])
            if not value or value in seen:
                continue
            seen.add(value)
            out.append(value)
    return out


def filter_options(db: Session, fact: str, limit: int = 400) -> dict[str, list]:
    """Dimension lists from file_details / catalog, then the fact view."""
    geo = {
        "divisions": "division",
        "zones": "zone",
        "clusters": "cluster",
        "states": "state",
        "data_sources": "data_source",
        "fme_codes": "fme_code",
        "user_types": "user_type",
    }
    out: dict[str, list] = {}
    for key, column in geo.items():
        out[key] = _distinct_values(
            db,
            [("file_details", column), (fact, column)],
            limit,
        )

    out["products"] = _distinct_values(
        db,
        [("products", "product_name")],
        limit,
    )
    return out


def _summary_from_rows(rows) -> dict[str, Any]:
    tags: list[dict[str, Any]] = []
    categories: list[dict[str, Any]] = []
    total = 0
    for category, tag, count, g_category, g_tag in rows:
        value = int(count or 0)
        if g_category and g_tag:
            total = value
        elif g_tag:
            categories.append({
                "feedback_category": _serialize(category),
                "feedback_count": value,
            })
        else:
            tags.append({
                "feedback_category": _serialize(category),
                "feedback_tag": _serialize(tag),
                "feedback_count": value,
            })
    tags.sort(key=lambda row: (
        (row["feedback_category"] or ""),
        (row["feedback_tag"] or ""),
    ))
    return {"tags": tags, "categories": categories, "total": total}


def summary_counts(db: Session, fact: str, where_sql: str, params: dict[str, Any]) -> dict[str, Any]:
    """Tag, category, and grand totals. GROUPING SETS on Postgres; UNION ALL fallback."""
    grouping_sql = f"""
        SELECT
            feedback_category,
            feedback_tag,
            COUNT(DISTINCT feedback_id) AS feedback_count,
            GROUPING(feedback_category) AS g_category,
            GROUPING(feedback_tag) AS g_tag
        FROM {fact}
        {where_sql}
        GROUP BY GROUPING SETS (
            (feedback_category, feedback_tag),
            (feedback_category),
            ()
        )
    """
    try:
        rows = execute(db, grouping_sql, params).fetchall()
        return _summary_from_rows(rows)
    except MissingFactView:
        raise
    except (ProgrammingError, OperationalError):
        pass

    union_sql = f"""
        SELECT feedback_category, feedback_tag,
               COUNT(DISTINCT feedback_id) AS feedback_count, 0 AS g_category, 0 AS g_tag
        FROM {fact} {where_sql}
        GROUP BY feedback_category, feedback_tag
        UNION ALL
        SELECT feedback_category, NULL,
               COUNT(DISTINCT feedback_id), 0, 1
        FROM {fact} {where_sql}
        GROUP BY feedback_category
        UNION ALL
        SELECT NULL, NULL, COUNT(DISTINCT feedback_id), 1, 1
        FROM {fact} {where_sql}
    """
    rows = execute(db, union_sql, params).fetchall()
    return _summary_from_rows(rows)


def _norm_product(value: str | None) -> str:
    return " ".join((value or "").split()).strip().lower()


def _catalog_product_maps(db: Session) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """Canonical product_name keyed by lower name and lower short_code."""
    by_name: dict[str, str] = {}
    by_code: dict[str, str] = {}
    names: list[str] = []
    try:
        rows = execute(
            db,
            "SELECT product_name, short_code FROM products "
            "WHERE product_name IS NOT NULL AND TRIM(CAST(product_name AS TEXT)) <> ''",
            {},
        ).fetchall()
    except (MissingFactView, ProgrammingError, OperationalError):
        return {}, {}, []
    for raw_name, raw_code in rows:
        name = str(raw_name).strip() if raw_name else ""
        if not name:
            continue
        by_name[_norm_product(name)] = name
        names.append(name)
        if raw_code and str(raw_code).strip():
            by_code[_norm_product(str(raw_code))] = name
    return by_name, by_code, names


def _canonical_catalog_product(
    raw: str | None,
    by_name: dict[str, str],
    by_code: dict[str, str],
) -> str:
    """Map a stored product_name to a catalog Product_Name, else (No product)."""
    if not raw or _norm_product(raw) == _norm_product(NO_PRODUCT_LABEL):
        return NO_PRODUCT_LABEL
    key = _norm_product(raw)
    if key in by_name:
        return by_name[key]
    if key in by_code:
        return by_code[key]
    candidates: dict[str, str] = {}
    for canonical in by_name.values():
        tokens = canonical.lower().replace("-", " ").split()
        compact = canonical.lower().replace("-", "").replace(" ", "")
        compact_key = key.replace("-", "").replace(" ", "")
        if key in tokens or canonical.lower().endswith(" " + key):
            candidates[canonical] = canonical
        if compact_key and len(compact_key) >= 4 and compact_key in compact:
            candidates[canonical] = canonical
    if len(candidates) == 1:
        return next(iter(candidates))
    if candidates:
        # Ambiguous soft match — do not guess.
        return NO_PRODUCT_LABEL
    # No catalog hit: keep the stored label so product counts stay visible.
    return (raw or "").strip() or NO_PRODUCT_LABEL


def product_counts(
    db: Session, fact: str, where_sql: str, params: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    query_params = {**params, "no_product": NO_PRODUCT_LABEL}
    sql = f"""
        SELECT
            COALESCE(NULLIF(TRIM(product_name), ''), :no_product) AS product_name,
            COUNT(DISTINCT feedback_id) AS feedback_count
        FROM {fact}
        {where_sql}
        GROUP BY 1
        HAVING COUNT(DISTINCT feedback_id) > 0
        ORDER BY 1
        LIMIT 500
    """
    rows = execute(db, sql, query_params).fetchall()
    by_name, by_code, _catalog_names = _catalog_product_maps(db)
    rolled: dict[str, int] = {}
    for name, count in rows:
        label = _canonical_catalog_product(_serialize(name), by_name, by_code)
        rolled[label] = rolled.get(label, 0) + int(count or 0)
    items = [
        {"product_name": name, "feedback_count": count}
        for name, count in rolled.items()
    ]
    items.sort(key=lambda row: (
        row["product_name"] == NO_PRODUCT_LABEL,
        row["product_name"] or "",
    ))
    total = int(execute(
        db, f"SELECT COUNT(DISTINCT feedback_id) FROM {fact} {where_sql}", params,
    ).scalar() or 0)
    return items, total


def detail_page(
    db: Session,
    fact: str,
    where_sql: str,
    params: dict[str, Any],
    page: int,
    page_size: int,
    sort_by: Optional[str] = None,
    sort_dir: Optional[str] = None,
) -> tuple[list[dict[str, Any]], int]:
    order_expr = _DETAIL_SORT.get(sort_by or "", "call_datetime")
    direction = "DESC" if (sort_dir or "desc").lower() == "desc" else "ASC"
    page_params = {
        **params,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }
    count_sql = f"SELECT COUNT(DISTINCT feedback_id) FROM {fact} {where_sql}"
    total = int(execute(db, count_sql, params).scalar() or 0)

    sql = f"""
        SELECT
            feedback_id,
            MAX(CAST(job_id AS TEXT)) AS job_id,
            MAX(product_name) AS product_name,
            MAX(feedback_category) AS feedback_category,
            MAX(feedback_tag) AS feedback_tag,
            MAX(feedback_summary_ai) AS feedback_summary_ai,
            MAX(feedback_excerpt) AS feedback_excerpt,
            MAX(file_name) AS file_name,
            MAX(CAST(call_date AS TEXT)) AS call_date,
            MAX(CAST(feedback_created_at AS TEXT)) AS feedback_created_at,
            COALESCE(
                MAX(CAST(call_date AS TEXT)),
                MAX(CAST(feedback_created_at AS TEXT))
            ) AS call_datetime
        FROM {fact}
        {where_sql}
        GROUP BY feedback_id
        ORDER BY {order_expr} {direction}, feedback_id
        LIMIT :limit OFFSET :offset
    """
    rows = execute(db, sql, page_params).mappings().fetchall()
    items = []
    for row in rows:
        items.append({
            "feedback_id": _serialize(row["feedback_id"]),
            "job_id": _serialize(row["job_id"]),
            "product_name": _serialize(row["product_name"]),
            "feedback_category": _serialize(row["feedback_category"]),
            "feedback_tag": _serialize(row["feedback_tag"]),
            "feedback_summary_ai": _serialize(row["feedback_summary_ai"]),
            "feedback_excerpt": _serialize(row["feedback_excerpt"]),
            "file_name": _serialize(row["file_name"]),
            "call_date": _serialize(row["call_date"]),
            "feedback_created_at": _serialize(row["feedback_created_at"]),
            "call_datetime": _serialize(
                row["call_datetime"] or row["call_date"] or row["feedback_created_at"]
            ),
        })
    return items, total


def conversation(
    db: Session, feedback_id: str, job_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    clauses = ["feedback_id = :feedback_id"]
    params: dict[str, Any] = {"feedback_id": feedback_id}
    if job_id:
        clauses.append("CAST(job_id AS TEXT) = CAST(:job_id AS TEXT)")
        params["job_id"] = job_id
    sql = f"""
        SELECT
            feedback_id,
            job_id,
            feedback_excerpt,
            NULLIF(TRIM(full_conversation), '') AS full_conversation,
            NULLIF(TRIM(full_conversation_raw), '') AS full_conversation_raw
        FROM {FAT_VIEW}
        WHERE {" AND ".join(clauses)}
        ORDER BY
            CASE WHEN NULLIF(TRIM(full_conversation), '') IS NULL THEN 1 ELSE 0 END,
            CASE WHEN NULLIF(TRIM(full_conversation_raw), '') IS NULL THEN 1 ELSE 0 END
        LIMIT 1
    """
    row = execute(db, sql, params).mappings().first()
    if not row:
        return None
    text_value = row["full_conversation"] or row["full_conversation_raw"]
    return {
        "feedback_id": _serialize(row["feedback_id"]),
        "job_id": _serialize(row["job_id"]),
        "feedback_excerpt": _serialize(row["feedback_excerpt"]),
        "full_conversation": _serialize(text_value),
    }


def fetch_feedback_fact(
    db: Session,
    where_sql: str,
    params: dict[str, Any],
    select_columns: list[str],
    order_sql: str,
) -> tuple[list[Any], int]:
    count_params = {key: value for key, value in params.items() if key not in ("limit", "offset")}
    total = int(execute(
        db, f"SELECT COUNT(*) FROM {FAT_VIEW} {where_sql}", count_params,
    ).scalar() or 0)
    select_sql = f"""
        SELECT {", ".join(select_columns)}
        FROM {FAT_VIEW}
        {where_sql}
        ORDER BY {order_sql}
        LIMIT :limit OFFSET :offset
    """
    rows = execute(db, select_sql, params).fetchall()
    return rows, total
