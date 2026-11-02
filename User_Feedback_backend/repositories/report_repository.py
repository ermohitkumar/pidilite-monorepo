"""Report queries against vw_pbi_feedback_fact / _slim.

Thin SQL only — HTTP mapping lives in the reports router.
Prefers vw_pbi_feedback_fact_slim so aggregations never join transcripts.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import inspect, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

SLIM_VIEW = "vw_pbi_feedback_fact_slim"
FAT_VIEW = "vw_pbi_feedback_fact"
FILTER_VIEW = "vw_filter_options"
HIERARCHY_VIEW = "vw_filter_hierarchy"
HIERARCHY_TABLE = "dimhierarchy"
# Fevicol retail: dimhierarchy.divisioncode plus the SH7 display name used on files.
# Zone dropdowns and report rows keep only zones (sh5name, else sh5code) in that slice.
ZONE_DIVISION_CODE = "10"
ZONE_DIVISION_NAME = "FV-RETAIL-NSM"
NO_PRODUCT_LABEL = "(No product)"
MASTER_FILTER_LIMIT = 5000

# vw_filter_options.filter_type → report API keys (clusters also get RFMM).
_FILTER_TYPE_KEYS = {
    "division": ("divisions",),
    "zone": ("zones",),
    "rfmm_cluster": ("clusters", "rfmm_clusters"),
    "fme_code": ("fme_codes",),
    "user_type": ("user_types",),
    "product": ("products",),
}

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
    division_zones: Optional[set[str]] = None,
) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = ["NULLIF(TRIM(COALESCE(product_name, '')), '') IS NOT NULL"]
    params: dict[str, Any] = {}

    def eq(column: str, value: Optional[str]) -> None:
        if value:
            clauses.append(f"{column} = :{column}")
            params[column] = value

    eq("feedback_group", feedback_group)
    eq("feedback_sub_tag", feedback_sub_tag)
    eq("division", division)
    eq("zone", zone)
    if cluster:
        clauses.append("(cluster = :cluster OR rfmm_cluster = :cluster)")
        params["cluster"] = cluster
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
        # A category filter already scopes the level-2 tag. Matching the category
        # column again would return every level-3 row when the names are the same.
        tag_match = ["LOWER(TRIM(feedback_tag)) = LOWER(TRIM(:feedback_tag))"]
        if not exact_tag:
            tag_match.append(
                "LOWER(TRIM(COALESCE(feedback_sub_tag, ''))) = LOWER(TRIM(:feedback_tag))"
            )
            if not feedback_category:
                tag_match.append(
                    "LOWER(TRIM(COALESCE(feedback_category, ''))) = LOWER(TRIM(:feedback_tag))"
                )
        clauses.append(tag_match[0] if len(tag_match) == 1 else "(" + " OR ".join(tag_match) + ")")
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
    restrict_clauses_to_division_zones(clauses, params, division_zones, column="zone")

    where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where_sql, params


def where_summarized(db: Session, fact: str, where_sql: str) -> str:
    """Drop feedbacks whose own summary has not been generated yet."""
    clause = "NULLIF(TRIM(COALESCE(feedback_summary_ai, '')), '') IS NOT NULL"
    try:
        db.execute(text(f"SELECT feedback_summary_ai FROM {fact} WHERE 1 = 0"))
    except (ProgrammingError, OperationalError):
        db.rollback()
        return where_sql
    if " where " in where_sql.lower():
        return f"{where_sql} AND {clause}"
    return f"WHERE {clause}" if not where_sql.strip() else f"{where_sql} WHERE {clause}"


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


def _merge_values(*lists: list, limit: int) -> list:
    seen: set[str] = set()
    out: list = []
    for values in lists:
        for value in values:
            if not value or value in seen:
                continue
            seen.add(value)
            out.append(value)
            if len(out) >= limit:
                return out
    return out


def _sorted_unique(values: list) -> list:
    seen: set[str] = set()
    out: list = []
    for value in values:
        text_value = _serialize(value)
        if not text_value or text_value in seen:
            continue
        seen.add(text_value)
        out.append(text_value)
    out.sort(key=lambda item: item.casefold())
    return out


def _options_from_filter_view(db: Session) -> dict[str, list]:
    """Official dropdowns from vw_filter_options. Empty dict if the view is missing."""
    sql = (
        f"SELECT filter_type, value FROM {FILTER_VIEW} "
        "WHERE value IS NOT NULL AND TRIM(CAST(value AS TEXT)) <> '' "
        "ORDER BY filter_type, value "
        f"LIMIT {MASTER_FILTER_LIMIT}"
    )
    try:
        rows = execute(db, sql, {}).fetchall()
    except (MissingFactView, ProgrammingError, OperationalError):
        return {}

    out: dict[str, list] = {}
    seen: dict[str, set[str]] = {}
    for filter_type, value in rows:
        text_value = _serialize(value)
        if not text_value:
            continue
        for key in _FILTER_TYPE_KEYS.get(str(filter_type), ()):
            bucket = out.setdefault(key, [])
            used = seen.setdefault(key, set())
            if text_value in used:
                continue
            used.add(text_value)
            bucket.append(text_value)
    return out


def _options_from_hierarchy(
    db: Session,
    *,
    division: Optional[str] = None,
    zone: Optional[str] = None,
    cluster: Optional[str] = None,
) -> dict[str, list]:
    """Linked Division → Zone → RFMM → FME lists from vw_filter_hierarchy."""
    sql = (
        f"SELECT division, zone, rfmm_cluster, fme_code FROM {HIERARCHY_VIEW} "
        f"LIMIT {MASTER_FILTER_LIMIT}"
    )
    try:
        rows = execute(db, sql, {}).fetchall()
    except (MissingFactView, ProgrammingError, OperationalError):
        return {}
    if not rows:
        return {}

    paths = [
        {
            "division": _serialize(row[0]),
            "zone": _serialize(row[1]),
            "rfmm_cluster": _serialize(row[2]),
            "fme_code": _serialize(row[3]),
        }
        for row in rows
    ]
    # Keep only Fevicol (divisioncode 10) paths when dimhierarchy is present.
    scope = _division_scope(db)
    if scope is not None:
        allowed_divisions, allowed_zones = scope
        paths = [
            path
            for path in paths
            if (not path["zone"] or path["zone"] in allowed_zones)
            and (not path["division"] or path["division"] in allowed_divisions)
        ]
    divisions = _sorted_unique([path["division"] for path in paths])

    scoped = paths
    if division:
        scoped = [path for path in scoped if path["division"] == division]
    zones = _sorted_unique([path["zone"] for path in scoped])

    if zone:
        scoped = [path for path in scoped if path["zone"] == zone]
    rfmms = _sorted_unique([path["rfmm_cluster"] for path in scoped])

    if cluster:
        scoped = [path for path in scoped if path["rfmm_cluster"] == cluster]
    fmes = _sorted_unique([path["fme_code"] for path in scoped])

    return {
        "divisions": divisions,
        "zones": zones,
        "clusters": rfmms,
        "rfmm_clusters": rfmms,
        "fme_codes": fmes,
    }


def _division_scope(db: Session) -> Optional[tuple[set[str], set[str]]]:
    """Division names and zones for code 10 × FV-RETAIL-NSM. None if dimhierarchy is missing."""
    sql = (
        "SELECT DISTINCT "
        "COALESCE(NULLIF(TRIM(sh7name), ''), NULLIF(TRIM(sh7code), '')), "
        "COALESCE(NULLIF(TRIM(sh5name), ''), NULLIF(TRIM(sh5code), '')) "
        f"FROM {HIERARCHY_TABLE} "
        "WHERE TRIM(divisioncode) = :division_code "
        "AND LOWER(TRIM(COALESCE(sh7name, ''))) = LOWER(TRIM(:division_name))"
    )
    try:
        rows = execute(
            db,
            sql,
            {
                "division_code": ZONE_DIVISION_CODE,
                "division_name": ZONE_DIVISION_NAME,
            },
        ).fetchall()
    except (MissingFactView, ProgrammingError, OperationalError):
        return None
    divisions = set(_sorted_unique([row[0] for row in rows]))
    zones = set(_sorted_unique([row[1] for row in rows]))
    return divisions, zones


def _division_zones(db: Session) -> Optional[set[str]]:
    """Zones under code 10 × FV-RETAIL-NSM. None if dimhierarchy is missing."""
    scope = _division_scope(db)
    if scope is None:
        return None
    return scope[1]


def _division_names(db: Session) -> Optional[set[str]]:
    """Division display names under code 10 × FV-RETAIL-NSM. None if dimhierarchy is missing."""
    scope = _division_scope(db)
    if scope is None:
        return None
    return scope[0]


def _division_zone_clause(zones: set[str], column: str) -> tuple[str, dict[str, Any]]:
    """Match fact/file zone names for division code 10. Empty set matches nothing."""
    names = sorted({str(zone).strip() for zone in zones if zone and str(zone).strip()})
    if not names:
        return "1 = 0", {}
    params: dict[str, Any] = {}
    holders: list[str] = []
    for index, name in enumerate(names):
        key = f"div10_zone_{index}"
        params[key] = name
        holders.append(f":{key}")
    return f"TRIM({column}) IN ({', '.join(holders)})", params


def restrict_clauses_to_division_zones(
    clauses: list[str],
    params: dict[str, Any],
    zones: Optional[set[str]],
    *,
    column: str,
) -> None:
    """Apply the code-10 zone list. A missing hierarchy (zones is None) leaves rows alone."""
    if zones is None:
        return
    clause, extra = _division_zone_clause(zones, column)
    clauses.append(clause)
    params.update(extra)


def filter_options(
    db: Session,
    fact: Optional[str] = None,
    limit: int = 400,
    *,
    division: Optional[str] = None,
    zone: Optional[str] = None,
    cluster: Optional[str] = None,
) -> dict[str, list]:
    """Masters from hierarchy / vw_filter_options; file_details only if masters are empty."""
    linked = _options_from_hierarchy(db, division=division, zone=zone, cluster=cluster)
    master = _options_from_filter_view(db)
    fill_limit = MASTER_FILTER_LIMIT if (linked or master) else limit
    geo = {
        "divisions": "division",
        "zones": "zone",
        "clusters": "cluster",
        "states": "state",
        "data_sources": "data_source",
        "fme_codes": "fme_code",
        "user_types": "user_type",
    }
    geo_from_hierarchy = {"divisions", "zones", "clusters", "fme_codes"}
    # When hierarchy is present, keep scoped RFMM/FME even if the zone has none.
    # Do not refill from the unscoped master view. Unscoped empty lists still fall
    # through to file_details so dropdowns are not blanked by a sparse hierarchy.
    scoped = bool(division or zone or cluster)
    out: dict[str, list] = {
        "rfmm_clusters": list(
            linked.get("rfmm_clusters", []) if linked else master.get("rfmm_clusters", [])
        ),
    }
    for key, column in geo.items():
        linked_values = linked.get(key, []) if linked else []
        if linked and key in geo_from_hierarchy and (linked_values or scoped):
            out[key] = list(linked_values)
            continue
        preferred = master.get(key, [])
        fallback_tables: list[tuple[str, str]] = []
        if not preferred:
            fallback_tables.append(("file_details", column))
            if fact:
                fallback_tables.append((fact, column))
            if key == "clusters":
                fallback_tables.extend(
                    [("file_details", "rfmm_cluster")]
                    + ([(fact, "rfmm_cluster")] if fact else [])
                )
        fallback = _distinct_values(db, fallback_tables, fill_limit) if fallback_tables else []
        out[key] = _merge_values(preferred or [], fallback, limit=fill_limit)

    out["products"] = _merge_values(
        master.get("products", []),
        _distinct_values(db, [("products", "product_name")], fill_limit),
        limit=fill_limit,
    )
    if not out["rfmm_clusters"]:
        out["rfmm_clusters"] = list(out.get("clusters", []))
    scope = _division_scope(db)
    if scope is not None:
        allowed_divisions, allowed_zones = scope
        out["divisions"] = [
            value for value in out.get("divisions", [])
            if str(value).strip() and value in allowed_divisions
        ]
        out["zones"] = [
            value for value in out.get("zones", [])
            if str(value).strip() and value in allowed_zones
        ]
    else:
        out["zones"] = [
            value for value in out.get("zones", [])
            if str(value).strip()
        ]
    return out


def _summary_from_rows(rows) -> dict[str, Any]:
    tags: list[dict[str, Any]] = []
    categories: list[dict[str, Any]] = []
    total = 0
    for category, tag, count, visits, g_category, g_tag in rows:
        value = int(count or 0)
        visit_count = int(visits or 0)
        if g_category and g_tag:
            total = value
        elif g_tag:
            categories.append({
                "feedback_category": _serialize(category),
                "feedback_count": value,
                "site_visit_count": visit_count,
            })
        else:
            tags.append({
                "feedback_category": _serialize(category),
                "feedback_tag": _serialize(tag),
                "feedback_count": value,
                "site_visit_count": visit_count,
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
            COUNT(DISTINCT job_id) AS site_visit_count,
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
               COUNT(DISTINCT feedback_id) AS feedback_count,
               COUNT(DISTINCT job_id) AS site_visit_count,
               0 AS g_category, 0 AS g_tag
        FROM {fact} {where_sql}
        GROUP BY feedback_category, feedback_tag
        UNION ALL
        SELECT feedback_category, NULL,
               COUNT(DISTINCT feedback_id), COUNT(DISTINCT job_id), 0, 1
        FROM {fact} {where_sql}
        GROUP BY feedback_category
        UNION ALL
        SELECT NULL, NULL, COUNT(DISTINCT feedback_id), COUNT(DISTINCT job_id), 1, 1
        FROM {fact} {where_sql}
    """
    rows = execute(db, union_sql, params).fetchall()
    return _summary_from_rows(rows)


def theme_counts(
    db: Session,
    *,
    feedback_group: Optional[str] = None,
    product_name: Optional[str] = None,
    feedback_category: Optional[str] = None,
    feedback_tag: Optional[str] = None,
    division: Optional[str] = None,
    zone: Optional[str] = None,
    cluster: Optional[str] = None,
    fme_code: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list[dict[str, Any]]:
    """Theme counts for the same slice the summary filters use."""
    try:
        feedback_cols = {col["name"] for col in inspect(db.get_bind()).get_columns("feedbacks")}
        detail_cols = {col["name"] for col in inspect(db.get_bind()).get_columns("file_details")}
    except (ProgrammingError, OperationalError):
        return []
    if "theme" not in feedback_cols:
        return []

    dialect = getattr(getattr(db.get_bind(), "dialect", None), "name", "") or "postgresql"
    call_parts = []
    if "call_date" in detail_cols:
        call_parts.append("CAST(fd.call_date AS DATE)" if dialect != "sqlite" else "DATE(fd.call_date)")
    call_parts.append("CAST(fb.created_at AS DATE)" if dialect != "sqlite" else "DATE(fb.created_at)")
    call_date = call_parts[0] if len(call_parts) == 1 else f"COALESCE({', '.join(call_parts)})"
    others_sql = (
        "GROUP_CONCAT(DISTINCT NULLIF(TRIM(fb.others_info), ''))"
        if dialect == "sqlite"
        else "string_agg(DISTINCT NULLIF(TRIM(COALESCE(fb.others_info, '')), ''), ' · ')"
    )
    sentiment_sql = {
        label: (
            "COUNT(DISTINCT CASE WHEN LOWER(TRIM(COALESCE(fb.sentiment_label, ''))) = "
            f"'{label}' THEN fb.id END)"
            if "sentiment_label" in feedback_cols
            else "0"
        )
        for label in ("positive", "neutral", "negative")
    }
    clauses = [
        "NULLIF(TRIM(COALESCE(fb.theme, '')), '') IS NOT NULL",
        "NULLIF(TRIM(COALESCE(fb.product_name, '')), '') IS NOT NULL",
    ]
    params: dict[str, Any] = {}
    if feedback_group:
        clauses.append("UPPER(TRIM(COALESCE(fb.group_type, ''))) = :feedback_group")
        params["feedback_group"] = feedback_group.strip().upper()
    if product_name:
        clauses.append("LOWER(TRIM(COALESCE(fb.product_name, ''))) = LOWER(TRIM(:product_name))")
        params["product_name"] = product_name
    if division and "division" in detail_cols:
        clauses.append("fd.division = :division")
        params["division"] = division
    if zone and "zone" in detail_cols:
        clauses.append("fd.zone = :zone")
        params["zone"] = zone
    if cluster:
        cluster_cols = [name for name in ("rfmm_cluster", "cluster") if name in detail_cols]
        if cluster_cols:
            clauses.append("(" + " OR ".join(f"fd.{name} = :cluster" for name in cluster_cols) + ")")
            params["cluster"] = cluster
    if fme_code and "fme_code" in detail_cols:
        clauses.append("fd.fme_code = :fme_code")
        params["fme_code"] = fme_code
    if start_date:
        clauses.append(f"{call_date} >= :start_date")
        params["start_date"] = start_date.isoformat()
    if end_date:
        clauses.append(f"{call_date} <= :end_date")
        params["end_date"] = end_date.isoformat()
    if "zone" in detail_cols:
        restrict_clauses_to_division_zones(
            clauses, params, _division_zones(db), column="fd.zone",
        )
    if feedback_category or feedback_tag:
        tag_clauses = ["l.feedback_id = fb.id"]
        if feedback_category:
            tag_clauses.append("LOWER(TRIM(COALESCE(t.group_type, ''))) = LOWER(TRIM(:tag_category))")
            params["tag_category"] = feedback_category
        if feedback_tag:
            tag_clauses.append(
                "("
                "LOWER(TRIM(COALESCE(t.category, ''))) = LOWER(TRIM(:tag_name)) "
                "OR LOWER(TRIM(COALESCE(fb.category_type, ''))) = LOWER(TRIM(:tag_name))"
                ")"
            )
            params["tag_name"] = feedback_tag
        clauses.append(
            "EXISTS (SELECT 1 FROM feedback_tag_link l "
            "JOIN feedback_tags t ON t.tag_id = l.tag_id WHERE " + " AND ".join(tag_clauses) + ")"
        )
    sql = f"""
        SELECT
            TRIM(fb.theme) AS theme,
            NULLIF(TRIM(COALESCE(fb.category_type, '')), '') AS feedback_tag,
            COUNT(DISTINCT fb.id) AS feedback_count,
            COUNT(DISTINCT fb.job_id) AS site_visit_count,
            {others_sql} AS others_info,
            {sentiment_sql['positive']} AS sentiment_positive_count,
            {sentiment_sql['neutral']} AS sentiment_neutral_count,
            {sentiment_sql['negative']} AS sentiment_negative_count
        FROM feedbacks fb
        LEFT JOIN file_details fd ON fd.job_id = fb.job_id
        WHERE {" AND ".join(clauses)}
        GROUP BY TRIM(fb.theme), NULLIF(TRIM(COALESCE(fb.category_type, '')), '')
        ORDER BY COUNT(DISTINCT fb.id) DESC, TRIM(fb.theme)
    """
    try:
        rows = execute(db, sql, params).fetchall()
    except (ProgrammingError, OperationalError, MissingFactView):
        return []
    themes = []
    for row in rows:
        mapping = row._mapping if hasattr(row, "_mapping") else row
        info = _serialize(mapping["others_info"])
        themes.append({
            "theme": _serialize(mapping["theme"]),
            "feedback_tag": _serialize(mapping["feedback_tag"]) or None,
            "feedback_count": int(mapping["feedback_count"] or 0),
            "site_visit_count": int(mapping["site_visit_count"] or 0),
            "others_info": info or None,
            "sentiment_positive_count": int(mapping["sentiment_positive_count"] or 0),
            "sentiment_neutral_count": int(mapping["sentiment_neutral_count"] or 0),
            "sentiment_negative_count": int(mapping["sentiment_negative_count"] or 0),
        })
    return themes


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
            COUNT(DISTINCT feedback_id) AS feedback_count,
            COUNT(DISTINCT job_id) AS site_visit_count
        FROM {fact}
        {where_sql}
        GROUP BY 1
        HAVING COUNT(DISTINCT feedback_id) > 0
        ORDER BY 1
        LIMIT 500
    """
    rows = execute(db, sql, query_params).fetchall()
    by_name, by_code, _catalog_names = _catalog_product_maps(db)
    rolled: dict[str, dict[str, int]] = {}
    for name, count, visits in rows:
        label = _canonical_catalog_product(_serialize(name), by_name, by_code)
        bucket = rolled.setdefault(label, {"feedback_count": 0, "site_visit_count": 0})
        bucket["feedback_count"] += int(count or 0)
        bucket["site_visit_count"] += int(visits or 0)
    items = [
        {
            "product_name": name,
            "feedback_count": counts["feedback_count"],
            "site_visit_count": counts["site_visit_count"],
        }
        for name, counts in rolled.items()
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
            "sentiment_label": None,
        })
    _overlay_feedback_sentiments(db, items)
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


def _table_columns(db: Session, table: str) -> set[str]:
    try:
        return {column["name"] for column in inspect(db.get_bind()).get_columns(table)}
    except Exception:
        return set()


def _overlay_feedback_sentiments(db: Session, items: list[dict[str, Any]]) -> None:
    """Fill sentiment_label from feedbacks when the report fact view lacks it."""
    if not items:
        return
    if "sentiment_label" not in _table_columns(db, "feedbacks"):
        return
    ids = [str(item["feedback_id"]) for item in items if item.get("feedback_id")]
    if not ids:
        return
    lookup_ids: list[str] = []
    for feedback_id in ids:
        lookup_ids.append(feedback_id)
        stripped = feedback_id.replace("-", "")
        if stripped != feedback_id:
            lookup_ids.append(stripped)
    placeholders = ", ".join(f":sid{index}" for index in range(len(lookup_ids)))
    params = {f"sid{index}": lookup_ids[index] for index in range(len(lookup_ids))}
    try:
        rows = db.execute(
            text(
                "SELECT CAST(id AS TEXT) AS id, sentiment_label "
                f"FROM feedbacks WHERE CAST(id AS TEXT) IN ({placeholders})"
            ),
            params,
        ).mappings().fetchall()
    except Exception:
        return
    by_id: dict[str, Any] = {}
    for row in rows:
        if not row["sentiment_label"]:
            continue
        label = _serialize(row["sentiment_label"])
        key = str(row["id"])
        by_id[key] = label
        by_id[key.replace("-", "")] = label
    for item in items:
        feedback_id = str(item.get("feedback_id") or "")
        item["sentiment_label"] = by_id.get(feedback_id) or by_id.get(feedback_id.replace("-", ""))


def _period_label(start: Optional[date], end: Optional[date]) -> str:
    if start and end and start.year == end.year and start.month == end.month and start.day == 1:
        if end.month != start.month or end.day >= 28:
            return start.strftime("%Y-%m")
    if start and end:
        return f"{start.isoformat()} – {end.isoformat()}"
    if start:
        return start.isoformat()
    return ""


def _user_tz(user_timezone: str):
    try:
        return ZoneInfo(user_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def _file_date_window(
    db: Session,
    *,
    start_date: Optional[date],
    end_date: Optional[date],
    user_timezone: str,
) -> tuple[str, list[str], dict[str, Any]]:
    """File timestamp expr (call_date, else job created_at) plus local-day window clauses."""
    dialect = getattr(getattr(db.get_bind(), "dialect", None), "name", "") or "postgresql"
    job_created_at_expr = (
        "NULLIF(j.created_at, '')::timestamptz"
        if dialect != "sqlite"
        else "j.created_at"
    )
    timestamp_expr = f"COALESCE(fd.call_date, {job_created_at_expr})"
    if dialect == "sqlite":
        timestamp_expr = f"datetime({timestamp_expr})"
    user_tz = _user_tz(user_timezone)

    def bound(day: date) -> Any:
        at = datetime.combine(day, time.min, tzinfo=user_tz).astimezone(timezone.utc)
        return at.replace(tzinfo=None).isoformat(sep=" ") if dialect == "sqlite" else at

    clauses: list[str] = []
    params: dict[str, Any] = {}
    if start_date:
        clauses.append(f"{timestamp_expr} >= :start_at")
        params["start_at"] = bound(start_date)
    if end_date:
        clauses.append(f"{timestamp_expr} < :end_before")
        params["end_before"] = bound(end_date + timedelta(days=1))
    return timestamp_expr, clauses, params


def compliance_rows(
    db: Session,
    *,
    division: Optional[str] = None,
    zone: Optional[str] = None,
    cluster: Optional[str] = None,
    fme_code: Optional[str] = None,
    user_type: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    user_timezone: str = "UTC",
) -> list[dict[str, Any]]:
    """FME-level open-conversation compliance from file_details / transcripts."""
    fd_cols = _table_columns(db, "file_details")
    site_expr = (
        "NULLIF(TRIM(COALESCE(fd.site_number, '')), '')"
        if "site_number" in fd_cols
        else "CAST(fd.job_id AS TEXT)"
    )
    duration_expr = "fd.audio_duration_seconds" if "audio_duration_seconds" in fd_cols else "NULL"
    rfmm_expr = (
        "NULLIF(TRIM(COALESCE(fd.rfmm_cluster, fd.cluster, '')), '')"
        if "rfmm_cluster" in fd_cols
        else "NULLIF(TRIM(COALESCE(fd.cluster, '')), '')"
    )
    # Temporary: count every file as recorded, including failed and empty transcripts.
    recorded_join = ""
    recorded_site = "j.id"
    recorded_duration = duration_expr
    _, clauses, params = _file_date_window(
        db, start_date=start_date, end_date=end_date, user_timezone=user_timezone,
    )
    if division:
        clauses.append("NULLIF(TRIM(COALESCE(fd.division, '')), '') = :division")
        params["division"] = division
    if zone:
        clauses.append("NULLIF(TRIM(COALESCE(fd.zone, '')), '') = :zone")
        params["zone"] = zone
    if cluster:
        clauses.append("(fd.cluster = :cluster OR fd.rfmm_cluster = :cluster)" if "rfmm_cluster" in fd_cols else "fd.cluster = :cluster")
        params["cluster"] = cluster
    if fme_code:
        clauses.append("NULLIF(TRIM(COALESCE(fd.fme_code, '')), '') = :fme_code")
        params["fme_code"] = fme_code
    if user_type:
        clauses.append("NULLIF(TRIM(COALESCE(fd.user_type, '')), '') = :user_type")
        params["user_type"] = user_type
    if "zone" in fd_cols:
        restrict_clauses_to_division_zones(
            clauses, params, _division_zones(db), column="fd.zone",
        )
    where_sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    period = _period_label(start_date, end_date)
    sql = f"""
        SELECT
            NULLIF(TRIM(COALESCE(fd.division, '')), '') AS division,
            NULLIF(TRIM(COALESCE(fd.zone, '')), '') AS zone,
            NULLIF(TRIM(COALESCE(fd.user_type, '')), '') AS user_type,
            {rfmm_expr} AS rfmm_cluster,
            NULLIF(TRIM(COALESCE(fd.fme_code, '')), '') AS fme_code,
            COUNT(DISTINCT j.id) AS sites_visited,
            COUNT(DISTINCT {recorded_site}) AS sites_recorded,
            AVG({recorded_duration}) AS avg_seconds
        FROM file_details fd
        JOIN jobs j ON j.id = fd.job_id
        {recorded_join}
        {where_sql}
        GROUP BY 1, 2, 3, 4, 5
        ORDER BY 1, 2, 5
    """
    rows = db.execute(text(sql), params).mappings().all()
    items: list[dict[str, Any]] = []
    for row in rows:
        visited = int(row["sites_visited"] or 0)
        recorded = int(row["sites_recorded"] or 0)
        rate = round((recorded / visited) * 100, 1) if visited else 0.0
        avg_seconds = row["avg_seconds"]
        items.append({
            "division": row["division"] or "",
            "time_period": period,
            "zone": row["zone"] or "",
            "user_type": row["user_type"] or "",
            "rfmm_cluster": row["rfmm_cluster"] or "",
            "fme_code": row["fme_code"] or "",
            "fme_period": period,
            "fme_name": row["fme_code"] or "",
            "sites_visited": visited,
            "sites_recorded": recorded,
            "conversation_rate": rate,
            "avg_conversation_seconds": None if avg_seconds is None else round(float(avg_seconds), 1),
        })
    return items


# Pipeline health: terminal jobs only; ERROR (retrying) counts as failed until it settles.
PIPELINE_STATUSES = ("COMPLETED", "FAILED", "ERROR")
# (label, lower minutes inclusive, upper minutes exclusive)
DURATION_BUCKETS: tuple[tuple[str, float, Optional[float]], ...] = (
    ("0-5", 0, 5),
    ("5-10", 5, 10),
    ("10-15", 10, 15),
    ("15-20", 15, 20),
    ("20+", 20, None),
)
UNKNOWN_DURATION_BUCKET = "unknown"
FAILED_REASONS = ("no_insights", "few_words", "short_audio", "errors")
UNKNOWN_SITE = "Unknown"
# Batchmicro TOO_FEW_WORDS_MESSAGE lands in jobs.error_message / processed_file.empty_reason.
FEW_WORDS_MARKER = "too few words"
# Batchmicro STT gate rejects audio under MIN_AUDIO_SECONDS before transcription.
SHORT_AUDIO_MARKER = "audio too short"


def _as_utc(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _grain_key(day: date, grain: str) -> str:
    if grain == "month":
        return day.strftime("%Y-%m")
    if grain == "week":
        iso = day.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    return day.isoformat()


def _grain_keys(start: date, end: date, grain: str) -> list[str]:
    keys: list[str] = []
    day = start
    while day <= end:
        key = _grain_key(day, grain)
        if not keys or keys[-1] != key:
            keys.append(key)
        day += timedelta(days=1)
    return keys


def _duration_bucket(seconds: Any) -> str:
    if seconds is None:
        return UNKNOWN_DURATION_BUCKET
    minutes = float(seconds) / 60
    for label, low, high in DURATION_BUCKETS:
        if minutes >= low and (high is None or minutes < high):
            return label
    return UNKNOWN_DURATION_BUCKET


def _failure_reason(row: Any) -> Optional[str]:
    """None when the file is successful (completed with at least one insight)."""
    status = str(row["status"] or "").upper()
    if status == "COMPLETED":
        return None if row["has_feedback"] else "no_insights"
    text_blob = f"{row['error_message'] or ''} {row['empty_reason'] or ''}".lower()
    if FEW_WORDS_MARKER in text_blob:
        return "few_words"
    if SHORT_AUDIO_MARKER in text_blob:
        return "short_audio"
    return "errors"


class _PipelineStats:
    def __init__(self) -> None:
        self.processed = 0
        self.successful = 0
        self.failed = 0
        self.bucket_counts = {label: 0 for label, _, _ in DURATION_BUCKETS}
        self.bucket_counts[UNKNOWN_DURATION_BUCKET] = 0
        self.bucket_seconds = dict.fromkeys(self.bucket_counts, 0.0)
        self.reasons = dict.fromkeys(FAILED_REASONS, 0)

    def add(self, reason: Optional[str], seconds: Any) -> None:
        self.processed += 1
        if reason is None:
            self.successful += 1
        else:
            self.failed += 1
            self.reasons[reason] += 1
        bucket = _duration_bucket(seconds)
        self.bucket_counts[bucket] += 1
        if seconds is not None:
            self.bucket_seconds[bucket] += float(seconds)

    def totals(self) -> dict[str, int]:
        return {"processed": self.processed, "successful": self.successful, "failed": self.failed}

    def duration_buckets(self) -> list[dict[str, Any]]:
        labels = [label for label, _, _ in DURATION_BUCKETS]
        if self.bucket_counts[UNKNOWN_DURATION_BUCKET]:
            labels.append(UNKNOWN_DURATION_BUCKET)
        items = []
        for label in labels:
            count = self.bucket_counts[label]
            has_avg = count and label != UNKNOWN_DURATION_BUCKET
            avg = round(self.bucket_seconds[label] / count / 60, 1) if has_avg else None
            items.append({"bucket": label, "count": count, "avg_minutes": avg})
        return items

    def failed_reasons(self) -> list[dict[str, Any]]:
        return [{"reason": reason, "count": self.reasons[reason]} for reason in FAILED_REASONS]


def pipeline_health(
    db: Session,
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    site_number: Optional[str] = None,
    grain: str = "day",
    user_timezone: str = "UTC",
) -> dict[str, Any]:
    """Processed / successful / failed files with duration, failure-reason and site splits."""
    fd_cols = _table_columns(db, "file_details")
    site_expr = (
        "NULLIF(TRIM(COALESCE(fd.site_number, '')), '')" if "site_number" in fd_cols else "NULL"
    )
    duration_expr = "fd.audio_duration_seconds" if "audio_duration_seconds" in fd_cols else "NULL"
    has_empty_reason = "empty_reason" in _table_columns(db, "processed_file")
    empty_reason_expr = "pf.empty_reason" if has_empty_reason else "NULL"
    processed_join = "LEFT JOIN processed_file pf ON pf.job_id = j.id" if has_empty_reason else ""

    timestamp_expr, clauses, params = _file_date_window(
        db, start_date=start_date, end_date=end_date, user_timezone=user_timezone,
    )
    status_holders = []
    for index, status in enumerate(PIPELINE_STATUSES):
        params[f"status_{index}"] = status
        status_holders.append(f":status_{index}")
    clauses.append(f"CAST(j.status AS TEXT) IN ({', '.join(status_holders)})")
    if "zone" in fd_cols:
        restrict_clauses_to_division_zones(
            clauses, params, _division_zones(db), column="fd.zone",
        )
    sql = f"""
        SELECT
            {site_expr} AS site_number,
            {timestamp_expr} AS file_at,
            {duration_expr} AS seconds,
            CAST(j.status AS TEXT) AS status,
            j.error_message AS error_message,
            {empty_reason_expr} AS empty_reason,
            EXISTS (SELECT 1 FROM feedbacks f WHERE f.job_id = j.id) AS has_feedback
        FROM file_details fd
        JOIN jobs j ON j.id = fd.job_id
        {processed_join}
        WHERE {" AND ".join(clauses)}
    """
    rows = db.execute(text(sql), params).mappings().all()

    # Site list ignores the site filter so the dropdown keeps every option.
    sites = sorted({row["site_number"] or UNKNOWN_SITE for row in rows})
    if site_number:
        rows = [row for row in rows if (row["site_number"] or UNKNOWN_SITE) == site_number]

    user_tz = _user_tz(user_timezone)
    overall = _PipelineStats()
    by_site: dict[str, _PipelineStats] = {}
    series: dict[str, dict[str, int]] = {}
    for row in rows:
        reason = _failure_reason(row)
        overall.add(reason, row["seconds"])
        site = row["site_number"] or UNKNOWN_SITE
        by_site.setdefault(site, _PipelineStats()).add(reason, row["seconds"])
        file_at = _as_utc(row["file_at"])
        if file_at is None:
            continue
        point = series.setdefault(
            _grain_key(file_at.astimezone(user_tz).date(), grain),
            {"processed": 0, "successful": 0, "failed": 0},
        )
        point["processed"] += 1
        point["successful" if reason is None else "failed"] += 1

    keys = (
        _grain_keys(start_date, end_date, grain)
        if start_date and end_date and start_date <= end_date
        else sorted(series)
    )
    empty_point = {"processed": 0, "successful": 0, "failed": 0}
    return {
        "totals": overall.totals(),
        "series": [{"key": key, **series.get(key, empty_point)} for key in keys],
        "duration_buckets": overall.duration_buckets(),
        "failed_reasons": overall.failed_reasons(),
        "by_site": [
            {
                "site_number": site,
                **stats.totals(),
                "duration_buckets": stats.duration_buckets(),
                "failed_reasons": stats.failed_reasons(),
            }
            for site, stats in sorted(by_site.items(), key=lambda item: (-item[1].processed, item[0]))
        ],
        "sites": sites,
        "grain": grain,
        "period": _period_label(start_date, end_date),
    }
